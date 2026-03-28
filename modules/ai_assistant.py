import json
import re

import pandas as pd
import requests
import streamlit as st

from modules.replay_generator import generate_replay_script


def _extract_json(text: str) -> dict:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise ValueError("The model did not return valid JSON.")
        return json.loads(match.group(0))


def _preview_values(series: pd.Series, limit: int = 3) -> list[str]:
    values = []
    for value in series.dropna().astype(str).head(50).unique().tolist():
        if value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _dataset_context(sm) -> dict:
    df = sm.df
    if df is None:
        return {"loaded": False}
    columns = []
    for col in df.columns:
        series = df[col]
        columns.append(
            {
                "name": str(col),
                "dtype": str(series.dtype),
                "missing": int(series.isna().sum()),
                "unique": int(series.nunique(dropna=True)),
                "sample_values": _preview_values(series),
            }
        )
    return {
        "loaded": True,
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_names": [str(col) for col in df.columns.tolist()],
        "numeric_columns": [str(col) for col in df.select_dtypes(include="number").columns.tolist()],
        "text_columns": [str(col) for col in df.select_dtypes(include=["object", "category"]).columns.tolist()],
        "recent_actions": [
            {"action": log["action"], "timestamp": log["timestamp"]}
            for log in sm.logs[-6:]
        ],
        "sample_rows": df.head(5).astype(object).where(pd.notna(df.head(5)), None).to_dict(orient="records"),
        "columns_meta": columns,
    }


def _dock_defaults() -> None:
    defaults = {
        "ai_dock_mode": "Cleaning",
        "ai_dock_prompt": "",
        "ai_dock_result": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


class AIService:
    def __init__(self, sm):
        self.sm = sm
        grok_key = st.secrets.get("GROK_API_KEY") or st.secrets.get("XAI_API_KEY")
        groq_key = st.secrets.get("GROQ_API_KEY")
        if grok_key:
            self.base_url = st.secrets.get("GROK_BASE_URL") or st.secrets.get("AI_BASE_URL") or "https://api.x.ai/v1"
            self.api_key = grok_key
            self.model = st.secrets.get("GROK_MODEL") or st.secrets.get("AI_MODEL") or "grok-2-1212"
            self.provider = "grok"
        else:
            self.base_url = st.secrets.get("AI_BASE_URL") or "https://api.groq.com/openai/v1"
            self.api_key = groq_key
            self.model = st.secrets.get("AI_MODEL") or "llama-3.1-8b-instant"
            self.provider = "fallback"

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    def _call(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        if not self.ready:
            raise RuntimeError("No AI API key is configured.")
        response = requests.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"] or ""

    def _call_json(self, system_prompt: str, user_prompt: str) -> dict:
        return _extract_json(self._call(system_prompt, user_prompt))


CHART_REQUIREMENTS = {
    "Box Plot":     {"x": "categorical", "y": "numeric",  "note": "X = category to group by, Y = numeric value to measure spread"},
    "Line Chart":   {"x": "any",         "y": "numeric",  "note": "Y must be numeric. X is usually a date or ordered category"},
    "Scatter Plot": {"x": "numeric",     "y": "numeric",  "note": "Both X and Y must be numeric"},
    "Bar Chart":    {"x": "categorical", "y": "numeric",  "note": "X = category, Y = numeric value to compare. Y can be omitted for counts"},
    "Histogram":    {"x": "numeric",     "y": None,       "note": "Only X needed — it must be numeric"},
    "Correlation Heatmap": {"x": None,   "y": None,       "note": "Select 2+ numeric columns. No axes needed"},
}


def _col_type(col: str, df: pd.DataFrame) -> str:
    """Returns 'numeric', 'categorical', or 'datetime'."""
    if df is None or col not in df.columns:
        return "unknown"
    s = df[col]
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return "categorical"


def _validate_chart_columns(
    chart_type: str,
    mentioned_cols: list[str],
    df: pd.DataFrame,
) -> tuple[bool, str]:
    """
    Returns (is_valid, problem_message).
    is_valid=True means the column combo works for the requested chart.
    """
    if df is None:
        return False, "No dataset loaded."

    req = CHART_REQUIREMENTS.get(chart_type)
    if not req:
        return True, ""

    numeric_cols     = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

    mentioned_numeric     = [c for c in mentioned_cols if c in numeric_cols]
    mentioned_categorical = [c for c in mentioned_cols if c in categorical_cols]
    mentioned_unknown     = [c for c in mentioned_cols if c not in df.columns]

    if mentioned_unknown:
        return False, (
            f"Column(s) **{', '.join(f'`{c}`' for c in mentioned_unknown)}** were not found in the dataset. "
            f"Available columns: {', '.join(f'`{c}`' for c in df.columns.tolist()[:10])}."
        )

    if chart_type == "Scatter Plot":
        if len(mentioned_numeric) < 2 and len(mentioned_cols) >= 2:
            bad = [c for c in mentioned_cols if c not in numeric_cols]
            return False, (
                f"**Scatter plots require two numeric columns**, but "
                f"**{', '.join(f'`{c}`' for c in bad)}** "
                f"{'is' if len(bad) == 1 else 'are'} categorical.\n\n"
                f"💡 **Better alternatives for categorical + categorical:**\n"
                f"- Use a **Bar Chart** to count occurrences by category\n"
                f"- Use a **Heatmap** of value counts to see category combinations"
            )

    if chart_type in ("Line Chart", "Box Plot"):
        if len(mentioned_cols) >= 2 and len(mentioned_numeric) == 0:
            return False, (
                f"**{chart_type}s require at least one numeric column** for the Y axis, "
                f"but all mentioned columns "
                f"({', '.join(f'`{c}`' for c in mentioned_cols)}) are categorical.\n\n"
                f"💡 **What you can do instead:**\n"
                f"- Use a **Bar Chart** with `{mentioned_cols[0]}` on X axis — it can count or sum by category\n"
                f"- If you want to compare **{mentioned_cols[0]}** vs **{mentioned_cols[1]}**, "
                f"try a **Bar Chart** grouped by one and coloured by the other\n"
                f"- Pick a numeric column (e.g. `{numeric_cols[0] if numeric_cols else 'Sales'}`) as Y axis"
            )
        if len(mentioned_cols) >= 2 and len(mentioned_numeric) >= 1:
            return True, ""

    if chart_type == "Bar Chart":
        return True, ""

    if chart_type == "Histogram":
        if mentioned_cols and len(mentioned_numeric) == 0:
            return False, (
                f"**Histograms only work with numeric columns**, but "
                f"**{', '.join(f'`{c}`' for c in mentioned_cols)}** "
                f"{'is' if len(mentioned_cols) == 1 else 'are'} categorical.\n\n"
                f"💡 **Alternatives:**\n"
                f"- Use a **Bar Chart** to see value counts for `{mentioned_cols[0]}`\n"
                f"- Use a **Histogram** on a numeric column like `{numeric_cols[0] if numeric_cols else 'Price'}`"
            )

    return True, ""


def _best_chart_for_columns(
    mentioned_cols: list[str],
    df: pd.DataFrame,
    requested_type: str | None = None,
) -> dict:
    """
    Given the columns the user mentioned, return the best chart config.
    Returns dict with: chart_type, x_col, y_col, reason
    """
    if df is None:
        return {}

    numeric_cols     = df.select_dtypes(include="number").columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

    mentioned_numeric     = [c for c in mentioned_cols if c in numeric_cols]
    mentioned_categorical = [c for c in mentioned_cols if c in categorical_cols]

    if len(mentioned_categorical) >= 2 and len(mentioned_numeric) == 0:
        return {
            "chart_type": "Bar Chart",
            "x_col": mentioned_categorical[0],
            "y_col": None,
            "color_col": mentioned_categorical[1],
            "reason": (
                f"Both `{mentioned_categorical[0]}` and `{mentioned_categorical[1]}` are categorical. "
                f"A **Bar Chart** counting rows, grouped by `{mentioned_categorical[0]}` and "
                f"coloured by `{mentioned_categorical[1]}`, is the best way to compare them."
            ),
        }

    if len(mentioned_categorical) >= 1 and len(mentioned_numeric) >= 1:
        preferred = requested_type if requested_type in ("Box Plot", "Bar Chart", "Line Chart") else "Box Plot"
        return {
            "chart_type": preferred,
            "x_col": mentioned_categorical[0],
            "y_col": mentioned_numeric[0],
            "color_col": None,
            "reason": (
                f"`{mentioned_categorical[0]}` is categorical and `{mentioned_numeric[0]}` is numeric — "
                f"a **{preferred}** is the right choice here."
            ),
        }

    if len(mentioned_numeric) >= 2:
        return {
            "chart_type": "Scatter Plot",
            "x_col": mentioned_numeric[0],
            "y_col": mentioned_numeric[1],
            "color_col": None,
            "reason": (
                f"Both columns are numeric — a **Scatter Plot** is best for checking correlation."
            ),
        }

    if len(mentioned_numeric) == 1:
        return {
            "chart_type": "Histogram",
            "x_col": mentioned_numeric[0],
            "y_col": None,
            "color_col": None,
            "reason": f"`{mentioned_numeric[0]}` is numeric — a **Histogram** shows its distribution.",
        }

    return {}


def _generate_answer(mode: str, prompt: str, items: list, code: str = "", sm=None) -> str:
    prompt_lower = (prompt or "").lower()
    wants_how = any(kw in prompt_lower for kw in [
        "how", "how to", "how do", "generate", "create", "make", "check", "verify"
    ])
    df = sm.df if sm else None

    if mode == "Cleaning":
        if not items:
            return "\n".join([
                "✅ **Your dataset looks clean!** No issues were found for this request.",
                "",
                "**What you can do next:**",
                "- Switch to **Charts** to start exploring your data visually",
                "- Switch to **Dictionary** to review what each column contains",
                "- Switch to **Code** to export a full pandas script of your workflow",
            ])

        problem_items = [
            i for i in items
            if not any(x in i.get("title", "").lower() for x in ["no ", "nothing", "clean"])
        ]
        clean_items = [i for i in items if i not in problem_items]

        lines = []
        if problem_items:
            lines.append(f"⚠️ **{len(problem_items)} issue(s) found.** Here is what to fix:\n")
            for idx, item in enumerate(problem_items, 1):
                title  = item.get("title", "")
                col    = item.get("columns", "")
                reason = item.get("reason", "")
                parts  = reason.split(" — ")
                desc   = parts[0].strip()
                fix    = parts[1].strip() if len(parts) > 1 else ""
                lines.append(f"**{idx}. {title}** on `{col}`")
                lines.append(f"   📌 {desc}")
                if fix:
                    lines.append(f"   ```python\n   {fix}\n   ```")
                lines.append("")

        if clean_items:
            for item in clean_items:
                lines.append(f"✅ {item.get('title', '')} — {item.get('reason', '')}")
            lines.append("")

        if wants_how:
            lines += [
                "**🔍 How to run a quick check yourself:**",
                "```python",
                "df.isna().sum()          # missing values per column",
                "df.duplicated().sum()    # duplicate rows",
                "df.info()                # dtypes overview",
                "df.describe()            # numeric stats",
                "```",
            ]

        return "\n".join(lines)

    if mode == "Charts":
        if not items:
            return "\n".join([
                "❌ **Could not generate this chart** with the current columns.",
                "",
                "**Why?** Each chart needs specific column types:",
                "- 📦 Box plot / 📊 Bar chart → one text + one numeric column",
                "- 🔵 Scatter plot → two numeric columns",
                "- 📊 Histogram → one numeric column",
                "- 🌡️ Heatmap → at least two numeric columns",
                "",
                "Check your dataset has the right columns loaded.",
            ])

        if items[0].get("warning"):
            return items[0]["warning"]

        item      = items[0]
        title     = item.get("title", "")
        cols      = item.get("columns", "")
        reason    = item.get("reason", "")
        desc, code_part = (reason.split("Code:", 1) + [""])[:2]

        insight_map = {
            "Box Plot": (
                "📦 **What this chart tells you:** The box shows where 50% of values sit. "
                "The center line is the median. Dots outside the whiskers are **outliers** — "
                "unusually high or low values. Perfect for comparing spread across categories."
            ),
            "Histogram": (
                "📊 **What this chart tells you:** Shows how values are distributed. "
                "A tall narrow peak = most values are similar. A wide spread = high variance. "
                "Skew left/right = extreme values pulling the average."
            ),
            "Scatter Plot": (
                "🔵 **What this chart tells you:** Each dot = one row. A diagonal pattern = "
                "the two columns are correlated. Clusters = natural groups in your data. "
                "Isolated dots = potential outliers worth investigating."
            ),
            "Bar Chart": (
                "📊 **What this chart tells you:** Compares a numeric value across categories. "
                "Taller bar = higher value. Great for ranking or spotting the best/worst performers."
            ),
            "Line Chart": (
                "📈 **What this chart tells you:** Shows change over time or sequence. "
                "Rising = growth, falling = decline. Sudden spikes may indicate events worth investigating."
            ),
            "Correlation Heatmap": (
                "🌡️ **What this chart tells you:** Each cell = how strongly two columns relate (−1 to +1). "
                "Close to +1 = they rise together. Close to −1 = one rises as the other falls. "
                "Near 0 = no linear relationship."
            ),
        }
        insight = insight_map.get(title, "")

        col_parts = cols.split(" × ")
        tip_col   = col_parts[0] if col_parts else "another_column"

        lines = [
            f"### 📋 How to create a {title} with `{cols}`",
            "",
        ]
        if insight:
            lines += [insight, ""]

        lines += [
            "**Step-by-step:**",
            "1. Install plotly if needed: `pip install plotly`",
            "2. Copy the code below into your script or notebook",
            "3. Make sure your DataFrame is loaded as `df`",
            "4. Run it — the chart opens in your browser or renders inline",
            "",
        ]

        if code_part.strip():
            lines += [f"```python\n{code_part.strip()}\n```", ""]

        lines += [
            "**💡 Customisation tips:**",
            f"- Add `color='{tip_col}'` to split by a category",
            "- Use `fig.update_layout(template='plotly_dark')` for a dark theme",
            "- Use `fig.write_html('chart.html')` to save it as a shareable file",
        ]

        return "\n".join(lines)

    if mode == "Dictionary":
        if not items:
            return "No column information available yet. Load a dataset first."

        issues_found = [
            i for i in items
            if i.get("issues", "No obvious issues") != "No obvious issues"
        ]
        clean_cols = [i for i in items if i not in issues_found]

        lines = []

        if issues_found:
            lines.append(f"⚠️ **{len(issues_found)} column(s) need attention:**\n")
            for item in issues_found:
                col     = item.get("column", "")
                meaning = item.get("meaning", "")
                issues  = item.get("issues", "")
                lines.append(f"**`{col}`** — {meaning}")
                lines.append(f"   ⚠️ {issues}")
                lines.append("")

        if clean_cols:
            lines.append("✅ **Columns that look fine:**\n")
            for item in clean_cols:
                lines.append(f"- **`{item.get('column', '')}`**: {item.get('meaning', '')}")
            lines.append("")

        lines += [
            "**💡 What to do next:**",
            "- Fix ⚠️ issues above before running analysis",
            "- Switch to **Charts** to visualise the most interesting columns",
            "- Switch to **Code** to get a pandas script documenting your column types",
        ]

        return "\n".join(lines)

    if mode == "Code":
        if not code:
            return "No code could be generated for this request."

        prompt_lower = (prompt or "").lower()
        exclude = any(kw in prompt_lower for kw in [
            "filter out", "exclude", "remove", "drop", "without", "except"
        ])
        is_filter   = any(kw in prompt_lower for kw in ["filter", "where", "query", "subset", "keep", "rows"])
        is_missing  = any(kw in prompt_lower for kw in ["missing", "null", "nan", "fillna"])
        is_group    = any(kw in prompt_lower for kw in ["group", "groupby", "aggregate"])
        is_export   = any(kw in prompt_lower for kw in ["export", "save", "csv", "excel"])
        is_describe = any(kw in prompt_lower for kw in ["describe", "summary", "overview", "info"])

        if is_filter and exclude:
            intro = (
                "✅ **Here's the code to exclude those rows.**\n\n"
                "The code is split into **3 steps** — use only what you need:\n"
                "- **Step 1** creates a filtered copy (`df_filtered`) without changing `df`\n"
                "- **Step 2** overwrites `df` permanently — only run this if you're sure\n"
                "- **Step 3** shows how to exclude multiple values at once (optional pattern)\n\n"
                "Replace `'another_value'` in Step 3 with any additional value to exclude."
            )
        elif is_filter:
            intro = (
                "✅ **Here's the code to keep only those rows.**\n\n"
                "The code is split into **3 steps** — use only what you need:\n"
                "- **Step 1** creates a filtered copy (`df_filtered`) without changing `df`\n"
                "- **Step 2** overwrites `df` permanently — only run this if you're sure\n"
                "- **Step 3** shows how to match multiple values at once (optional pattern)\n\n"
                "Replace `'another_value'` in Step 3 with any additional value to keep."
            )
        elif is_missing:
            intro = "✅ **Here's the code to handle missing values.** Choose the approach that fits — fill or drop, depending on how important the column is."
        elif is_group:
            intro = "✅ **Here's the groupby aggregation code.** Change the column names and aggregation functions (`mean`, `sum`, `count`) as needed."
        elif is_export:
            intro = "✅ **Here's the export code.** Make sure your DataFrame is clean before saving."
        elif is_describe:
            intro = "✅ **Here's how to get a full overview of your dataset.**"
        else:
            intro = "✅ **Here's your pandas code** — ready to copy and run."

        return "\n".join([
            intro,
            "",
            "**How to use it:**",
            "1. Copy the code block below",
            "2. Paste it into your script, Jupyter notebook, or Python console",
            "3. Make sure your DataFrame is already loaded as `df`",
            "4. Run it and check the output",
            "",
            "💡 **Tip:** Run `print(df.shape)` before and after to confirm the change.",
        ])

    return ""


def _fallback_cleaning(sm, prompt: str) -> dict:
    df = sm.df
    if df is None:
        return {"summary": "Upload a dataset first.", "items": []}

    prompt_lower     = (prompt or "").lower()
    mentioned_cols   = [col for col in df.columns if col.lower() in prompt_lower]
    target_cols      = mentioned_cols if mentioned_cols else df.columns.tolist()

    wants_missing    = any(kw in prompt_lower for kw in ["missing", "null", "nan", "na", "empty", "blank", "check"])
    wants_duplicates = any(kw in prompt_lower for kw in ["duplicate", "dupl", "repeated", "unique"])
    wants_whitespace = any(kw in prompt_lower for kw in ["whitespace", "space", "strip", "trim"])
    wants_casing     = any(kw in prompt_lower for kw in ["case", "casing", "upper", "lower", "capitalize"])
    wants_dtype      = any(kw in prompt_lower for kw in ["type", "dtype", "convert", "format", "date", "numeric"])
    wants_outlier    = any(kw in prompt_lower for kw in ["outlier", "anomaly", "extreme", "unusual"])
    wants_how        = any(kw in prompt_lower for kw in ["how", "check", "verify", "inspect", "find", "detect"])

    show_all = not any([wants_missing, wants_duplicates, wants_whitespace,
                        wants_casing, wants_dtype, wants_outlier])

    items = []

    if wants_missing or show_all:
        for col in target_cols:
            series    = df[col]
            n_missing = int(series.isna().sum())
            pct       = round(n_missing / len(df) * 100, 1) if len(df) > 0 else 0
            if n_missing > 0:
                fix = (
                    f"df['{col}'].fillna(df['{col}'].median(), inplace=True)"
                    if pd.api.types.is_numeric_dtype(series)
                    else f"df['{col}'].fillna(df['{col}'].mode()[0], inplace=True)"
                )
                items.append({
                    "title":   f"Fix missing values in '{col}'",
                    "columns": col,
                    "reason":  f"{n_missing} missing ({pct}%) — {fix}",
                })
            elif col in mentioned_cols or wants_how:
                items.append({
                    "title":   f"'{col}' has no missing values",
                    "columns": col,
                    "reason":  f"All {len(df)} rows populated. Verify: df['{col}'].isna().sum()",
                })

        if wants_how and not mentioned_cols:
            items.append({
                "title":   "How to check missing values",
                "columns": "all columns",
                "reason":  "df.isna().sum()  # count | df.isna().mean()*100  # percentage",
            })

    if wants_duplicates or show_all:
        n_dup = int(df.duplicated().sum())
        items.append({
            "title":   "Duplicate rows found" if n_dup else "No duplicate rows",
            "columns": "all columns",
            "reason":  (
                f"{n_dup} row(s). Fix: df.drop_duplicates(inplace=True)"
                if n_dup else "Dataset has no fully duplicated rows."
            ),
        })

    if wants_whitespace or show_all:
        for col in [c for c in target_cols if df[c].dtype == object]:
            sample = df[col].dropna().astype(str).head(100)
            if not sample.empty and any(v != v.strip() for v in sample.tolist()):
                items.append({
                    "title":   f"Trim whitespace in '{col}'",
                    "columns": col,
                    "reason":  f"Spaces found — df['{col}'] = df['{col}'].str.strip()",
                })

    if wants_casing or show_all:
        for col in [c for c in target_cols if df[c].dtype == object]:
            sample = df[col].dropna().astype(str).head(100)
            if not sample.empty and sample.str.lower().nunique() < sample.nunique():
                items.append({
                    "title":   f"Standardize casing in '{col}'",
                    "columns": col,
                    "reason":  f"Mixed casing — df['{col}'] = df['{col}'].str.lower()",
                })

    if wants_dtype or show_all:
        for col in [c for c in target_cols if df[c].dtype == object]:
            sample    = df[col].dropna().astype(str).head(50)
            converted = pd.to_numeric(sample, errors="coerce")
            if converted.notna().sum() > len(sample) * 0.8:
                items.append({
                    "title":   f"Convert '{col}' to numeric",
                    "columns": col,
                    "reason":  f"Looks numeric but stored as text — pd.to_numeric(df['{col}'], errors='coerce')",
                })

    if wants_outlier:
        for col in [c for c in target_cols if pd.api.types.is_numeric_dtype(df[c])]:
            series = df[col].dropna()
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr    = q3 - q1
            n_out  = int(((series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)).sum())
            items.append({
                "title":   f"{'Outliers in' if n_out else 'No outliers in'} '{col}'",
                "columns": col,
                "reason":  (
                    f"{n_out} IQR outlier(s) detected — check with a box plot."
                    if n_out else "Values within normal IQR range."
                ),
            })

    if not items:
        items.append({
            "title":   "Nothing to flag",
            "columns": ", ".join(target_cols) if mentioned_cols else "dataset",
            "reason":  "No issues found. Run df.info() and df.describe() for a full overview.",
        })

    summary = f"Suggestions for: {prompt.strip()}" if prompt.strip() else "General cleaning suggestions."
    return {"summary": summary, "items": items[:8]}


def _fallback_charts(sm, goal: str) -> dict:
    df = sm.df
    if df is None:
        return {"summary": "Upload a dataset first.", "items": []}

    goal_lower = (goal or "").lower()
    numeric    = df.select_dtypes(include="number").columns.tolist()
    text       = df.select_dtypes(include=["object", "category"]).columns.tolist()

    mentioned_cols    = [col for col in df.columns if col.lower() in goal_lower]
    mentioned_numeric = [c for c in mentioned_cols if c in numeric]
    mentioned_text    = [c for c in mentioned_cols if c in text]

    wants_box     = any(kw in goal_lower for kw in ["box", "boxplot", "box plot", "spread", "outlier", "iqr"])
    wants_hist    = any(kw in goal_lower for kw in ["hist", "histogram", "distribution", "frequency"])
    wants_scatter = any(kw in goal_lower for kw in ["scatter", "correlation", "relationship", "cluster"])
    wants_bar     = any(kw in goal_lower for kw in ["bar", "compare", "category", "group"])
    wants_line    = any(kw in goal_lower for kw in ["line", "trend", "over time", "time series"])
    wants_heatmap = any(kw in goal_lower for kw in ["heatmap", "heat map", "heat", "matrix"])

    requested_type = None
    if wants_box:     requested_type = "Box Plot"
    elif wants_hist:  requested_type = "Histogram"
    elif wants_scatter: requested_type = "Scatter Plot"
    elif wants_bar:   requested_type = "Bar Chart"
    elif wants_line:  requested_type = "Line Chart"
    elif wants_heatmap: requested_type = "Correlation Heatmap"

    show_all = not requested_type

    if requested_type and mentioned_cols:
        valid, problem = _validate_chart_columns(requested_type, mentioned_cols, df)
        if not valid:
            best = _best_chart_for_columns(mentioned_cols, df, requested_type)
            warning_lines = [
                f"⚠️ **`{requested_type}` won't work well with the columns you mentioned.**\n",
                problem,
                "",
            ]
            if best:
                chart_type = best["chart_type"]
                x_col      = best.get("x_col", "")
                y_col      = best.get("y_col", "")
                color_col  = best.get("color_col", "")

                if chart_type == "Bar Chart" and not y_col:
                    code_str = (
                        f"import plotly.express as px\n"
                        f"fig = px.bar(df, x='{x_col}', color='{color_col}', barmode='group',\n"
                        f"             title='{x_col} count by {color_col}')\n"
                        f"fig.show()"
                    )
                    col_display = f"{x_col} (count) grouped by {color_col}"
                elif chart_type == "Bar Chart":
                    code_str = (
                        f"import plotly.express as px\n"
                        f"fig = px.bar(df, x='{x_col}', y='{y_col}',\n"
                        f"             title='{y_col} by {x_col}')\n"
                        f"fig.show()"
                    )
                    col_display = f"{x_col} × {y_col}"
                elif chart_type == "Box Plot":
                    code_str = (
                        f"import plotly.express as px\n"
                        f"fig = px.box(df, x='{x_col}', y='{y_col}',\n"
                        f"             title='Box Plot: {y_col} by {x_col}')\n"
                        f"fig.show()"
                    )
                    col_display = f"{x_col} × {y_col}"
                else:
                    code_str = ""
                    col_display = ", ".join(filter(None, [x_col, y_col]))

                warning_lines += [
                    f"---\n✅ **Better alternative: {chart_type}** with `{col_display}`\n",
                    best.get("reason", ""),
                    "",
                ]
                if code_str:
                    warning_lines += [f"```python\n{code_str}\n```"]

            return {
                "summary": f"Column type issue for: {goal.strip()}",
                "items": [{"warning": "\n".join(warning_lines), "title": "Column type warning",
                            "columns": ", ".join(mentioned_cols), "reason": problem}],
            }

    cat_col  = mentioned_text[0]    if mentioned_text    else (text[0]    if text    else None)
    num_col  = mentioned_numeric[0] if mentioned_numeric else (numeric[0] if numeric else None)
    num_col2 = (
        mentioned_numeric[1] if len(mentioned_numeric) > 1
        else (numeric[1] if len(numeric) > 1 else None)
    )

    items = []

    if wants_box or show_all:
        if cat_col and num_col:
            code = (
                f"import plotly.express as px\n"
                f"fig = px.box(df, x='{cat_col}', y='{num_col}', "
                f"title='Box Plot: {num_col} by {cat_col}')\n"
                f"fig.show()"
            )
            items.append({
                "title":   "Box Plot",
                "columns": f"{cat_col} × {num_col}",
                "reason":  f"Shows spread and outliers of {num_col} grouped by {cat_col}. Code:\n{code}",
            })

    if wants_hist or show_all:
        if num_col:
            code = (
                f"import plotly.express as px\n"
                f"fig = px.histogram(df, x='{num_col}', title='Distribution of {num_col}')\n"
                f"fig.show()"
            )
            items.append({
                "title":   "Histogram",
                "columns": num_col,
                "reason":  f"Inspect the distribution of {num_col}. Code:\n{code}",
            })

    if wants_scatter or show_all:
        if num_col and num_col2:
            code = (
                f"import plotly.express as px\n"
                f"fig = px.scatter(df, x='{num_col}', y='{num_col2}', "
                f"title='Scatter: {num_col} vs {num_col2}')\n"
                f"fig.show()"
            )
            items.append({
                "title":   "Scatter Plot",
                "columns": f"{num_col} vs {num_col2}",
                "reason":  f"Check correlation between {num_col} and {num_col2}. Code:\n{code}",
            })

    if wants_bar or show_all:
        if cat_col and num_col:
            code = (
                f"import plotly.express as px\n"
                f"fig = px.bar(df, x='{cat_col}', y='{num_col}', "
                f"title='{num_col} by {cat_col}')\n"
                f"fig.show()"
            )
            items.append({
                "title":   "Bar Chart",
                "columns": f"{cat_col} × {num_col}",
                "reason":  f"Compare {num_col} across {cat_col} categories. Code:\n{code}",
            })
        elif cat_col:
            code = (
                f"import plotly.express as px\n"
                f"fig = px.bar(df, x='{cat_col}', title='Count by {cat_col}')\n"
                f"fig.show()"
            )
            items.append({
                "title":   "Bar Chart (count)",
                "columns": cat_col,
                "reason":  f"Count rows by {cat_col}. Code:\n{code}",
            })

    if wants_line or show_all:
        if num_col:
            x_col = cat_col or str(df.columns[0])
            code  = (
                f"import plotly.express as px\n"
                f"fig = px.line(df, x='{x_col}', y='{num_col}', title='Trend of {num_col}')\n"
                f"fig.show()"
            )
            items.append({
                "title":   "Line Chart",
                "columns": f"{x_col} × {num_col}",
                "reason":  f"Track trend of {num_col} over {x_col}. Code:\n{code}",
            })

    if wants_heatmap or show_all:
        if len(numeric) >= 2:
            cols_str = ", ".join(f"'{c}'" for c in numeric[:6])
            code = (
                f"import plotly.express as px\n"
                f"fig = px.imshow(df[[{cols_str}]].corr(), title='Correlation Heatmap', text_auto=True)\n"
                f"fig.show()"
            )
            items.append({
                "title":   "Correlation Heatmap",
                "columns": ", ".join(numeric[:6]),
                "reason":  f"Spot relationships between numeric columns. Code:\n{code}",
            })

    if not items:
        items.append({
            "title":   "Not enough columns for this chart type",
            "columns": "dataset",
            "reason":  "Upload a dataset with the required column types (numeric/text) to generate this chart.",
        })

    summary = f"Chart ideas for: {goal.strip()}" if goal.strip() else "Chart suggestions based on available columns."
    return {"summary": summary, "items": items[:6]}


def _fallback_dictionary(sm, prompt: str = "") -> dict:
    df = sm.df
    if df is None:
        return {"summary": "Upload a dataset first.", "items": []}

    prompt_lower   = (prompt or "").lower()
    mentioned_cols = [col for col in df.columns if col.lower() in prompt_lower]
    target_cols    = mentioned_cols if mentioned_cols else df.columns.tolist()

    items = []
    for col in target_cols:
        series   = df[col]
        missing  = int(series.isna().sum())
        unique   = int(series.nunique(dropna=True))
        pct_miss = round(missing / len(df) * 100, 1) if len(df) > 0 else 0
        samples  = series.dropna().astype(str).unique()[:3].tolist()

        issues = []
        if missing:
            issues.append(f"{missing} missing ({pct_miss}%) — df['{col}'].isna().sum()")
        if unique == len(df) and len(df) > 0:
            issues.append("all values unique — likely an ID column")
        if series.dtype == object:
            converted = pd.to_numeric(series.dropna().astype(str).head(50), errors="coerce")
            if converted.notna().sum() > 40:
                issues.append(f"stored as text but looks numeric — pd.to_numeric(df['{col}'])")

        if pd.api.types.is_numeric_dtype(series):
            meaning = f"Numeric. Range: {series.min()} – {series.max()}, Mean: {round(series.mean(), 2)}"
        elif pd.api.types.is_datetime64_any_dtype(series):
            meaning = f"Date/time. Range: {series.min()} – {series.max()}"
        else:
            meaning = f"Text/category. {unique} unique values. Examples: {', '.join(samples)}"

        items.append({
            "column":  col,
            "meaning": meaning,
            "issues":  "; ".join(issues) if issues else "No obvious issues",
        })

    summary = (
        f"Data dictionary for: {prompt.strip()}" if prompt.strip()
        else "Full data dictionary inferred from column types and values."
    )
    return {"summary": summary, "items": items}


def _extract_filter_intent(prompt: str, col: str, df) -> dict:
    """
    Parse the prompt to extract:
      - filter_value: the actual value to filter on (e.g. "Europe")
      - exclude: True if user wants to REMOVE those rows
      - is_numeric: whether the column is numeric
      - numeric_op: operator for numeric filters (>, <, >=, <=, ==, !=)
      - numeric_val: numeric threshold value
    """
    result = {
        "filter_value": None,
        "exclude": False,
        "is_numeric": False,
        "numeric_op": None,
        "numeric_val": None,
    }

    if df is None or col not in df.columns:
        return result

    series = df[col]
    result["is_numeric"] = pd.api.types.is_numeric_dtype(series)

    prompt_lower = prompt.lower()

    user_wrote_eq  = "==" in prompt
    user_wrote_neq = "!=" in prompt

    if user_wrote_neq:
        result["exclude"] = True
    elif user_wrote_eq:
        result["exclude"] = False
    else:
        result["exclude"] = any(kw in prompt_lower for kw in [
            "filter out", "exclude", "remove", "drop", "without", "except",
            "not equal", "remove rows", "drop rows", "exclude rows"
        ])

    if result["is_numeric"]:
        op_patterns = [
            (r"greater than or equal to\s*([\d.]+)", ">="),
            (r"less than or equal to\s*([\d.]+)",    "<="),
            (r"greater than\s*([\d.]+)",              ">" ),
            (r"more than\s*([\d.]+)",                 ">" ),
            (r"above\s*([\d.]+)",                     ">" ),
            (r"less than\s*([\d.]+)",                 "<" ),
            (r"below\s*([\d.]+)",                     "<" ),
            (r"under\s*([\d.]+)",                     "<" ),
            (r"equal to\s*([\d.]+)",                  "=="),
            (r">=\s*([\d.]+)",                        ">="),
            (r"<=\s*([\d.]+)",                        "<="),
            (r"!=\s*([\d.]+)",                        "!="),
            (r"==\s*([\d.]+)",                        "=="),
            (r">\s*([\d.]+)",                         ">" ),
            (r"<\s*([\d.]+)",                         "<" ),
        ]
        for pattern, op in op_patterns:
            m = re.search(pattern, prompt_lower)
            if m:
                result["numeric_op"] = op
                result["numeric_val"] = m.group(1)
                break
        if not result["numeric_val"]:
            m = re.search(r"\b(\d+(?:\.\d+)?)\b", prompt)
            if m:
                result["numeric_val"] = m.group(1)
                result["numeric_op"]  = "!=" if result["exclude"] else "=="

    else:
        col_escaped = re.escape(col.lower())

        eq_patterns = [
            rf"{col_escaped}\s*[!=]{{0,1}}=\s*['\"]?([a-zA-Z0-9 _\-]+)['\"]?",
            rf"{col_escaped}\s+is\s+(?:not\s+)?['\"]?([a-zA-Z0-9 _\-]+)['\"]?",
            rf"where\s+{col_escaped}\s+['\"]?([a-zA-Z0-9 _\-]+)['\"]?",
            r"(?:is|equals|==|=)\s+['\"]?([a-zA-Z0-9 _\-]+)['\"]?",
            r"['\"]([a-zA-Z0-9 _\-]+)['\"]",
        ]
        for pattern in eq_patterns:
            m = re.search(pattern, prompt_lower)
            if m:
                candidate = m.group(1).strip().rstrip(".")
                for real_val in series.dropna().astype(str).unique():
                    if real_val.lower() == candidate:
                        result["filter_value"] = real_val
                        break
                if not result["filter_value"]:
                    for real_val in series.dropna().astype(str).unique():
                        if candidate in real_val.lower():
                            result["filter_value"] = real_val
                            break
                if result["filter_value"]:
                    break

        if not result["filter_value"]:
            col_vals_lower = {v.lower(): v for v in series.dropna().astype(str).unique()}
            for word in re.findall(r"[a-zA-Z][a-zA-Z0-9 _\-]*", prompt):
                w = word.strip().lower()
                if w in col_vals_lower:
                    result["filter_value"] = col_vals_lower[w]
                    break

    return result


def _fallback_code(sm, prompt: str = "") -> dict:
    source_file  = (sm.source_metadata or {}).get("filename", "your_file.csv")
    prompt_lower = (prompt or "").lower()
    df           = sm.df

    wants_missing   = any(kw in prompt_lower for kw in ["missing", "null", "nan", "fillna", "dropna"])
    wants_duplicate = any(kw in prompt_lower for kw in ["duplicate", "drop_dup"])
    wants_filter    = any(kw in prompt_lower for kw in [
        "filter", "where", "query", "subset", "keep", "remove rows",
        "drop rows", "exclude", "filter out", "only rows", "rows where"
    ])
    wants_group     = any(kw in prompt_lower for kw in ["group", "aggregate", "groupby", "mean", "sum", "count"])
    wants_export    = any(kw in prompt_lower for kw in ["export", "save", "csv", "excel", "output"])
    wants_describe  = any(kw in prompt_lower for kw in ["describe", "summary", "overview", "info", "stats"])
    wants_replay    = any(kw in prompt_lower for kw in ["replay", "history", "workflow", "all steps"])

    mentioned_cols = (
        [col for col in df.columns if col.lower() in prompt_lower]
        if df is not None else []
    )

    if wants_replay or (sm.logs and not any([
        wants_missing, wants_duplicate, wants_filter, wants_group, wants_export, wants_describe
    ])):
        code    = generate_replay_script(sm.logs, source_file=source_file)
        summary = "Full replay script for all transformations applied so far."
        return {"summary": summary, "code": code}

    snippets = []

    if wants_missing:
        col_ref = f"df['{mentioned_cols[0]}']" if mentioned_cols else "df['column_name']"
        snippets.append(
            f"# Check missing values\ndf.isna().sum()\n\n"
            f"# Fill numeric column with median\n{col_ref}.fillna({col_ref}.median(), inplace=True)\n\n"
            f"# Fill text column with most frequent value\n{col_ref}.fillna({col_ref}.mode()[0], inplace=True)\n\n"
            f"# Drop rows where any value is missing\ndf.dropna(inplace=True)"
        )

    if wants_duplicate:
        snippets.append(
            "# Check duplicates\nprint(df.duplicated().sum())\n\n"
            "# Remove duplicates\ndf.drop_duplicates(inplace=True)"
        )

    if wants_filter:
        col    = mentioned_cols[0] if mentioned_cols else None
        intent = _extract_filter_intent(prompt, col, df) if col else {}

        if col and intent:
            exclude     = intent.get("exclude", False)
            is_numeric  = intent.get("is_numeric", False)
            filter_val  = intent.get("filter_value")
            numeric_op  = intent.get("numeric_op")
            numeric_val = intent.get("numeric_val")

            lines = []

            if is_numeric and numeric_val:
                op       = numeric_op or ("!=" if exclude else "==")
                keep_op  = {"==": "!=", "!=": "==", ">": "<=", "<": ">=", ">=": "<", "<=": ">"}
                excl_op  = keep_op.get(op, "!=") if exclude else op
                action   = "exclude" if exclude else "keep"
                lines.append(
                    f"# {action.title()} rows where {col} {op} {numeric_val}\n"
                    f"df_filtered = df[df['{col}'] {excl_op if exclude else op} {numeric_val}]\n\n"
                    f"# Apply in-place\n"
                    f"df = df[df['{col}'] {excl_op if exclude else op} {numeric_val}]\n"
                    f"print(f'Rows remaining: {{len(df)}}')"
                )
            elif filter_val:
                op     = "!=" if exclude else "=="
                action = "Exclude" if exclude else "Keep only"

                lines.append(
                    f"# Step 1: {action} rows where {col} = '{filter_val}'\n"
                    f"df_filtered = df[df['{col}'] {op} '{filter_val}']\n"
                    f"print(f'Rows after filter: {{len(df_filtered)}} / {{len(df)}}')"
                )

                lines.append(
                    f"# Step 2 (optional): apply in-place — overwrites df permanently\n"
                    f"df = df[df['{col}'] {op} '{filter_val}']\n"
                    f"print(f'Rows remaining: {{len(df)}}')"
                )
                if exclude:
                    lines.append(
                        f"# Step 3 (optional): exclude multiple values at once\n"
                        f"# Replace the list below with whichever values you want to remove\n"
                        f"exclude_values = ['{filter_val}', 'another_value']\n"
                        f"df_filtered = df[~df['{col}'].isin(exclude_values)]"
                    )
                else:
                    lines.append(
                        f"# Step 3 (optional): keep multiple values at once\n"
                        f"# Replace the list below with whichever values you want to keep\n"
                        f"keep_values = ['{filter_val}', 'another_value']\n"
                        f"df_filtered = df[df['{col}'].isin(keep_values)]"
                    )
            else:
                if df is not None and col in df.columns:
                    sample_vals = df[col].dropna().astype(str).unique()[:3].tolist()
                    hint = f"  # actual values in this column: {sample_vals}"
                else:
                    hint = ""
                lines.append(
                    f"# Keep rows where '{col}' equals a value\n"
                    f"df_filtered = df[df['{col}'] == 'your_value']{hint}\n\n"
                    f"# Exclude rows where '{col}' equals a value\n"
                    f"df_filtered = df[df['{col}'] != 'your_value']{hint}\n\n"
                    f"# Keep multiple values\n"
                    f"df_filtered = df[df['{col}'].isin(['value1', 'value2'])]\n\n"
                    f"# Exclude multiple values\n"
                    f"df_filtered = df[~df['{col}'].isin(['value1', 'value2'])]"
                )

            snippets.append("\n".join(lines))

        else:
            example_col = (
                df.columns[0] if df is not None and len(df.columns) > 0 else "column_name"
            )
            sample_vals = (
                df[example_col].dropna().astype(str).unique()[:3].tolist()
                if df is not None else []
            )
            hint = f"  # e.g. one of: {sample_vals}" if sample_vals else ""
            snippets.append(
                f"# Keep rows matching a value\n"
                f"df_filtered = df[df['{example_col}'] == 'your_value']{hint}\n\n"
                f"# Exclude rows matching a value\n"
                f"df_filtered = df[df['{example_col}'] != 'your_value']{hint}\n\n"
                f"# Filter by multiple values\n"
                f"df_filtered = df[df['{example_col}'].isin(['val1', 'val2'])]\n\n"
                f"# Numeric range filter\n"
                f"df_filtered = df[(df['numeric_col'] >= 100) & (df['numeric_col'] <= 500)]"
            )

    if wants_group:
        num_cols = df.select_dtypes(include="number").columns.tolist() if df is not None else []
        cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist() if df is not None else []
        grp = mentioned_cols[0] if mentioned_cols else (cat_cols[0] if cat_cols else "category_col")
        val = (
            next((c for c in num_cols if c not in mentioned_cols), num_cols[0])
            if num_cols else "value_col"
        )
        snippets.append(
            f"# Group by '{grp}' and aggregate '{val}'\n"
            f"df.groupby('{grp}')['{val}'].agg(['mean', 'sum', 'count', 'min', 'max'])"
        )

    if wants_export:
        snippets.append(
            f"# Export to CSV\ndf.to_csv('cleaned_{source_file}', index=False)\n\n"
            f"# Export to Excel\ndf.to_excel('cleaned_output.xlsx', index=False)"
        )

    if wants_describe:
        snippets.append("# Dataset overview\ndf.info()\ndf.describe()\ndf.head()")

    if not snippets:
        snippets.append(
            f"import pandas as pd\n\ndf = pd.read_csv('{source_file}')\n"
            f"print(df.shape)\nprint(df.dtypes)\nprint(df.isna().sum())\ndf.head()"
        )

    code    = "\n\n# ---\n\n".join(snippets)
    summary = f"Code for: {prompt.strip()}" if prompt.strip() else "Starter pandas code for the current dataset."
    return {"summary": summary, "code": code}


def _fallback_general(sm, prompt: str) -> dict:
    if sm.df is None:
        return {
            "summary": "Upload a dataset first.",
            "text": (
                "Once a dataset is loaded, I can suggest cleaning steps, "
                "chart ideas, a data dictionary, or pandas code."
            ),
        }

    prompt_lower = (prompt or "").lower()

    if any(kw in prompt_lower for kw in ["clean", "missing", "null", "duplicate", "whitespace", "trim", "casing"]):
        payload = _fallback_cleaning(sm, prompt)
        payload.update({
            "mode": "General", "source": "local",
            "answer": _generate_answer("Cleaning", prompt, payload.get("items", []), sm=sm),
        })
        return payload

    if any(kw in prompt_lower for kw in ["chart", "plot", "graph", "visual", "box",
                                          "histogram", "scatter", "bar", "line", "heatmap"]):
        payload = _fallback_charts(sm, prompt)
        payload.update({
            "mode": "General", "source": "local",
            "answer": _generate_answer("Charts", prompt, payload.get("items", []), sm=sm),
        })
        return payload

    if any(kw in prompt_lower for kw in ["dictionary", "dict", "column meaning", "describe column"]):
        payload = _fallback_dictionary(sm, prompt)
        payload.update({
            "mode": "General", "source": "local",
            "answer": _generate_answer("Dictionary", prompt, payload.get("items", []), sm=sm),
        })
        return payload

    if any(kw in prompt_lower for kw in ["code", "pandas", "python", "script", "snippet"]):
        payload = _fallback_code(sm, prompt)
        payload.update({
            "mode": "General", "source": "local",
            "answer": _generate_answer("Code", prompt, [], code=payload.get("code", ""), sm=sm),
        })
        return payload

    df        = sm.df
    mentioned = [col for col in df.columns if col.lower() in prompt_lower]
    if mentioned:
        col    = mentioned[0]
        series = df[col]
        text   = (
            f"Column **'{col}'**: {series.nunique()} unique values, "
            f"{series.isna().sum()} missing, dtype `{series.dtype}`. "
            f"{_suggest_next_step(sm)}"
        )
    else:
        text = _suggest_next_step(sm)

    return {"summary": "Next step suggestion", "text": text, "mode": "General", "source": "local"}


def _cleaning_items_df(payload: dict) -> pd.DataFrame:
    return pd.DataFrame(payload.get("items", []))

def _chart_items_df(payload: dict) -> pd.DataFrame:
    return pd.DataFrame(payload.get("items", []))

def _dictionary_items_df(payload: dict) -> pd.DataFrame:
    return pd.DataFrame(payload.get("items", []))


def _suggest_next_step(sm) -> str:
    df = sm.df
    if df is None:
        return "Upload a dataset first, then use this dock to get cleaning, chart, dictionary, or code suggestions."
    total_missing = int(df.isna().sum().sum())
    if total_missing:
        top_col = df.isna().sum().sort_values(ascending=False)
        top_col = top_col[top_col > 0]
        if not top_col.empty:
            return f"Start with missing values in '{top_col.index[0]}', then review duplicates."
    duplicate_rows = int(df.duplicated().sum())
    if duplicate_rows:
        return f"Review duplicate handling next. The dataset still has {duplicate_rows} duplicate row(s)."
    if not sm.logs:
        return "The dataset looks ready for exploration. Ask for a data dictionary or chart suggestions next."
    if len(sm.logs) < 3:
        return "You have started cleaning. A chart suggestion is a good next step to validate the current data."
    return "You are close to the finish line. Ask for pandas code or export guidance next."


def _safe_ai_result(service: AIService, mode: str, prompt: str) -> dict:
    try:
        if mode == "Cleaning":
            payload = service._call_json(
                "You are a data cleaning suggestor for a Streamlit app. "
                "Return JSON only with keys summary and items. "
                "Each item must have title, columns, and reason. Suggest only.",
                json.dumps({"request": prompt, "dataset": _dataset_context(service.sm)}, default=str),
            )
            result = {
                "mode": mode, "source": service.provider,
                "summary": payload.get("summary", "Cleaning suggestions generated."),
                "items":   payload.get("items", []),
            }
            result["answer"] = _generate_answer(mode, prompt, result["items"], sm=service.sm)
            return result

        if mode == "Charts":
            payload = service._call_json(
                "You are a chart suggestor for a Streamlit app. "
                "Return JSON only with keys summary and items. "
                "Each item must have title, columns, and reason. Suggest only.",
                json.dumps({"goal": prompt, "dataset": _dataset_context(service.sm)}, default=str),
            )
            result = {
                "mode": mode, "source": service.provider,
                "summary": payload.get("summary", "Chart suggestions generated."),
                "items":   payload.get("items", []),
            }
            result["answer"] = _generate_answer(mode, prompt, result["items"], sm=service.sm)
            return result

        if mode == "Dictionary":
            payload = service._call_json(
                "You are a data dictionary suggestor for a Streamlit app. "
                "Return JSON only with keys summary and items. "
                "Each item must have column, meaning, and issues.",
                json.dumps({"dataset": _dataset_context(service.sm)}, default=str),
            )
            result = {
                "mode": mode, "source": service.provider,
                "summary": payload.get("summary", "Dictionary generated."),
                "items":   payload.get("items", []),
            }
            result["answer"] = _generate_answer(mode, prompt, result["items"], sm=service.sm)
            return result

        if mode == "Code":
            code = service._call(
                "You generate pandas code suggestions for a Streamlit data wrangling app. "
                "Return Python code only with no markdown fences and no comments.",
                json.dumps(
                    {
                        "request": prompt or "Generate a pandas snippet for the current workflow.",
                        "dataset": _dataset_context(service.sm),
                        "transformation_logs": service.sm.logs,
                    },
                    default=str,
                ),
                temperature=0.1,
            ).strip().strip("`")
            result = {
                "mode": mode, "source": service.provider,
                "summary": "Suggested pandas code generated.",
                "code": code,
            }
            result["answer"] = _generate_answer(mode, prompt, [], code=code, sm=service.sm)
            return result

        answer = service._call(
            "You are a concise suggestion-focused helper for a Streamlit data wrangling app. Suggest next steps only.",
            json.dumps({"question": prompt, "dataset": _dataset_context(service.sm)}, default=str),
            temperature=0.3,
        )
        return {"mode": mode, "source": service.provider, "summary": "Suggested next step", "text": answer}

    except Exception:
        if mode == "Cleaning":
            payload = _fallback_cleaning(service.sm, prompt)
            payload["mode"]   = mode
            payload["source"] = "local"
            payload["answer"] = _generate_answer(mode, prompt, payload.get("items", []), sm=service.sm)
            return payload

        if mode == "Charts":
            payload = _fallback_charts(service.sm, prompt)
            payload["mode"]   = mode
            payload["source"] = "local"
            payload["answer"] = _generate_answer(mode, prompt, payload.get("items", []), sm=service.sm)
            return payload

        if mode == "Dictionary":
            payload = _fallback_dictionary(service.sm, prompt)
            payload["mode"]   = mode
            payload["source"] = "local"
            payload["answer"] = _generate_answer(mode, prompt, payload.get("items", []), sm=service.sm)
            return payload

        if mode == "Code":
            payload = _fallback_code(service.sm, prompt)
            payload["mode"]   = mode
            payload["source"] = "local"
            payload["answer"] = _generate_answer(mode, prompt, [], code=payload.get("code", ""), sm=service.sm)
            return payload

        payload = _fallback_general(service.sm, prompt)
        payload["mode"]   = mode
        payload["source"] = "local"
        return payload


def _render_result(result: dict | None) -> None:
    if not result:
        return

    source = "AI" if result.get("source") == "grok" else "Local fallback"
    st.caption(f"Source: {source}")

    mode = result.get("mode")

    if result.get("answer"):
        with st.container(border=True):
            st.markdown(result["answer"])

    if mode == "Code" and result.get("code"):
        st.code(result["code"], language="python")

    items_df = None
    if mode == "Cleaning":
        items_df = _cleaning_items_df(result)
    elif mode == "Charts":
        raw = _chart_items_df(result)
        raw = raw[~raw.get("warning", pd.Series(dtype=str)).notna()] if "warning" in raw.columns else raw
        if not raw.empty and "reason" in raw.columns:
            items_df = raw.copy()
            items_df["reason"] = items_df["reason"].str.split("Code:").str[0].str.strip()
    elif mode == "Dictionary":
        items_df = _dictionary_items_df(result)

    if items_df is not None and not items_df.empty:
        display_df = items_df.drop(columns=["warning"], errors="ignore")
        with st.expander("📋 View full details table", expanded=False):
            st.dataframe(display_df, use_container_width=True)

    if mode not in ("Cleaning", "Charts", "Dictionary", "Code") and result.get("text"):
        st.info(result["text"])


class AIAssistant:
    def __init__(self, session_manager):
        self.sm = session_manager
        _dock_defaults()

    def render(self):
        service = AIService(self.sm)
        st.divider()
        with st.container(border=True):
            st.markdown("### AI Helper Dock")
            st.caption(
                "A single suggestion-focused assistant for the whole app. "
                "It recommends what to do next, but it does not auto-apply changes."
            )

            top_col, status_col = st.columns([2.4, 1])
            with top_col:
                st.info(_suggest_next_step(self.sm))
            with status_col:
                if self.sm.df is None:
                    st.warning("No dataset")
                elif service.provider == "grok":
                    st.success("Grok ready")
                elif service.ready:
                    st.warning("Non-Grok AI")
                else:
                    st.info("Local suggestions")

            modes = ["Cleaning", "Charts", "Dictionary", "Code", "General"]
            st.session_state.ai_dock_mode = st.radio(
                "AI mode",
                modes,
                index=modes.index(st.session_state.ai_dock_mode)
                if st.session_state.ai_dock_mode in modes else 0,
                horizontal=True,
                label_visibility="collapsed",
            )

            mode = st.session_state.ai_dock_mode
            prompt_label = {
                "Cleaning":   "Describe the cleaning help you want",
                "Charts":     "Describe the chart goal you have",
                "Dictionary": "Optional focus for the dictionary",
                "Code":       "Optional instruction for the code suggestion",
                "General":    "Ask for the next best step",
            }[mode]
            prompt_placeholder = {
                "Cleaning":   "how to check for missing values in column Region",
                "Charts":     "I want a box plot with Region and Unit Cost",
                "Dictionary": "focus on important business columns",
                "Code":       "generate code to filter rows where Region is East",
                "General":    "what should I do next with this dataset?",
            }[mode]

            prompt = st.text_area(
                prompt_label,
                value=st.session_state.ai_dock_prompt,
                placeholder=prompt_placeholder,
                key="ai_dock_prompt",
                height=90,
            )

            action_col, reset_col = st.columns([4, 1])
            if action_col.button("Generate Suggestion", use_container_width=True, type="primary"):
                st.session_state.ai_dock_result = _safe_ai_result(service, mode, prompt)
            if reset_col.button("Clear", use_container_width=True):
                st.session_state.ai_dock_result = None
                st.rerun()

            _render_result(st.session_state.get("ai_dock_result"))