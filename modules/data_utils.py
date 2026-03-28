import pandas as pd
import re
import streamlit as st


def detect_datetime_cols(df: pd.DataFrame) -> list:
    result = []
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            result.append(col)
        elif df[col].dtype == "object" or pd.api.types.is_string_dtype(df[col]):
            sample = df[col].dropna().head(200)
            if len(sample) == 0:
                continue
            try:
                conv = pd.to_datetime(sample, format="mixed", errors="coerce")
                if conv.notna().sum() / len(sample) > 0.8:
                    result.append(col)
            except Exception:
                pass
    return result


@st.cache_data(show_spinner=False)
def missing_per_col(df: pd.DataFrame) -> pd.Series:
    return df.isnull().sum()


@st.cache_data(show_spinner=False)
def build_missing_summary(df: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    missing_per_column = missing_per_col(df)
    total_missing = int(missing_per_column.sum())
    missing_columns = missing_per_column[missing_per_column > 0]
    summary_df = (
        missing_columns.rename("missing_count")
        .reset_index()
        .rename(columns={"index": "column"})
    )
    summary_df["Missing %"] = (summary_df["missing_count"] / len(df) * 100).round(1)
    return total_missing, summary_df


def build_correlation_summary(corr: pd.DataFrame, threshold: float = 0.7) -> pd.DataFrame:
    rows = []
    for i, col_a in enumerate(corr.columns):
        for j, col_b in enumerate(corr.columns):
            if j <= i:
                continue
            value = corr.iloc[i, j]
            if pd.notna(value) and abs(float(value)) > threshold:
                rows.append({
                    "Variable A": col_a,
                    "Variable B": col_b,
                    "Correlation": round(float(value), 3),
                })
    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        return summary_df
    summary_df["Abs Correlation"] = summary_df["Correlation"].abs()
    summary_df = summary_df.sort_values("Abs Correlation", ascending=False)
    return summary_df.drop(columns=["Abs Correlation"])


@st.cache_data(show_spinner=False)
def count_duplicates(df: pd.DataFrame, subset, keep) -> int:
    subset_list = list(subset) if subset else None
    return int(df.duplicated(subset=subset_list, keep=keep).sum())


@st.cache_data(show_spinner=False)
def dup_preview(df: pd.DataFrame, subset, keep=False) -> pd.DataFrame:
    subset_list = list(subset) if subset else None
    mask = df.duplicated(subset=subset_list, keep=False)
    return df[mask].head(100)


def build_formula_env(df: pd.DataFrame):
    env, alias_lookup, used_aliases = {}, {}, set()
    for idx, col in enumerate(df.columns):
        alias = re.sub(r"\W|^(?=\d)", "_", str(col)).strip("_") or f"col_{idx}"
        base, suffix = alias, 1
        while alias in used_aliases:
            alias = f"{base}_{suffix}"
            suffix += 1
        used_aliases.add(alias)
        env[alias] = df[col]
        alias_lookup[str(col)] = alias
    return env, alias_lookup


def prepare_formula(expr: str, alias_lookup: dict) -> str:
    def replace_match(match):
        col_name = match.group(1)
        if col_name not in alias_lookup:
            raise KeyError(f"Unknown column reference: [{col_name}]")
        return alias_lookup[col_name]
    return re.sub(r"\[([^\[\]]+)\]", replace_match, expr)
