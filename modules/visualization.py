from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px
from dataclasses import dataclass, field
from typing import Any

from modules.session_manager import SessionManager
from modules.data_utils import build_correlation_summary

AGG_MAP: dict[str, str] = {
    "Sum":    "sum",
    "Mean":   "mean",
    "Median": "median",
    "Count":  "size",
}

CHARTS_NEEDING_Y = {"Scatter Plot", "Line Chart", "Box Plot"}

CHART_RULES = {
    "Histogram":           "X must be **numeric**. No Y axis needed.",
    "Scatter Plot":        "Both X and Y must be **numeric**.",
    "Line Chart":          "Y must be **numeric**. X is usually a date or ordered category.",
    "Bar Chart":           "X should be **categorical**. Y should be **numeric** (or omit Y to count rows).",
    "Box Plot":            "X must be **categorical**. Y must be **numeric**.",
    "Correlation Heatmap": "Select **2 or more numeric** columns. No axes needed.",
}


@dataclass
class ChartConfig:
    chart_type: str
    x_axis: str = "None"
    y_axis: str = "None"
    group_col: str = "None"
    aggregation: str = "None"
    numeric_filter_col: str = "None"
    filter_range: tuple[float, float] | None = None
    cat_filter_col: str = "None"
    selected_categories: list[Any] = field(default_factory=list)
    date_range: tuple | None = None
    heatmap_cols: list[str] = field(default_factory=list)
    corr_threshold: float = 0.7
    top_n_enabled: bool = False
    top_n_value: int = 10


def _is_numeric(col: str, df: pd.DataFrame) -> bool:
    return col in df.columns and pd.api.types.is_numeric_dtype(df[col])

def _is_categorical(col: str, df: pd.DataFrame, temp_df: pd.DataFrame) -> bool:
    if col not in temp_df.columns:
        return False
    s = temp_df[col]
    return (
        s.dtype == "object"
        or isinstance(s.dtype, pd.CategoricalDtype)
        or pd.api.types.is_datetime64_any_dtype(s)
    )

def _is_datetime(col: str, temp_df: pd.DataFrame) -> bool:
    return col in temp_df.columns and pd.api.types.is_datetime64_any_dtype(temp_df[col])


def _validate_config(
    cfg: ChartConfig,
    df: pd.DataFrame,
    temp_df: pd.DataFrame,
    numeric_cols: list[str],
    categorical_cols: list[str],
) -> list[str]:
    """
    Returns a list of human-readable error/warning strings.
    Empty list = everything is valid.
    """
    errors: list[str] = []
    ct = cfg.chart_type

    if ct == "Correlation Heatmap":
        if len(cfg.heatmap_cols) < 2:
            errors.append("❌ Select **at least 2 numeric columns** for the heatmap.")
        non_numeric = [c for c in cfg.heatmap_cols if c not in numeric_cols]
        if non_numeric:
            errors.append(f"❌ These columns are not numeric: **{', '.join(non_numeric)}**")
        return errors

    if cfg.x_axis == "None":
        errors.append("❌ **X axis** is required — please select a column.")
        return errors

    if ct == "Histogram":
        if not _is_numeric(cfg.x_axis, df):
            errors.append(
                f"❌ Histogram requires a **numeric X axis**, but `{cfg.x_axis}` is categorical. "
                f"Use a **Bar Chart** to count categories instead."
            )

    if ct == "Scatter Plot":
        if not _is_numeric(cfg.x_axis, df):
            errors.append(
                f"❌ Scatter plot requires a **numeric X axis**, but `{cfg.x_axis}` is categorical."
            )
        if cfg.y_axis == "None":
            errors.append("❌ Scatter plot requires a **numeric Y axis** — please select one.")
        elif not _is_numeric(cfg.y_axis, df):
            errors.append(
                f"❌ Scatter plot requires a **numeric Y axis**, but `{cfg.y_axis}` is categorical. "
                f"Try a **Bar Chart** or **Box Plot** for category vs numeric comparisons."
            )
        if (
            cfg.x_axis != "None" and cfg.y_axis != "None"
            and cfg.x_axis == cfg.y_axis
        ):
            errors.append("❌ X and Y axes are the same column — pick two different columns.")

    if ct == "Line Chart":
        if cfg.y_axis == "None":
            errors.append("❌ Line chart requires a **numeric Y axis** — please select one.")
        elif not _is_numeric(cfg.y_axis, df):
            errors.append(
                f"❌ Line chart Y axis must be **numeric**, but `{cfg.y_axis}` is categorical. "
                f"Swap X and Y, or use a **Bar Chart** instead."
            )
        if cfg.x_axis != "None" and cfg.y_axis != "None" and cfg.x_axis == cfg.y_axis:
            errors.append("❌ X and Y axes are the same column — pick two different columns.")
        if (
            cfg.x_axis != "None" and cfg.y_axis != "None"
            and not _is_numeric(cfg.x_axis, df)
            and not _is_numeric(cfg.y_axis, df)
        ):
            errors.append(
                f"❌ Both `{cfg.x_axis}` and `{cfg.y_axis}` are categorical. "
                f"Line charts need at least one **numeric column** on Y. "
                f"Try a **Bar Chart** to compare these categories."
            )

    if ct == "Box Plot":
        if cfg.y_axis == "None":
            errors.append("❌ Box plot requires a **numeric Y axis** — please select one.")
        elif not _is_numeric(cfg.y_axis, df):
            errors.append(
                f"❌ Box plot Y axis must be **numeric**, but `{cfg.y_axis}` is categorical."
            )
        if cfg.x_axis != "None" and _is_numeric(cfg.x_axis, df):
            errors.append(
                f"⚠️ `{cfg.x_axis}` is numeric — box plots work best when X is a **category** "
                f"(e.g. Region, Product Type). Consider using a categorical column on X."
            )
        if cfg.x_axis != "None" and cfg.y_axis != "None" and cfg.x_axis == cfg.y_axis:
            errors.append("❌ X and Y axes are the same column — pick two different columns.")

    if ct == "Bar Chart":
        if cfg.y_axis != "None" and not _is_numeric(cfg.y_axis, df):
            errors.append(
                f"⚠️ Bar chart Y axis `{cfg.y_axis}` is not numeric. "
                f"Aggregations like Sum/Mean won't work. Either pick a **numeric column** or "
                f"leave Y empty to count rows."
            )
        if cfg.aggregation in ("Sum", "Mean", "Median") and cfg.y_axis == "None":
            errors.append(
                f"⚠️ You selected **{cfg.aggregation}** aggregation but no Y axis. "
                f"Either pick a numeric Y column, or switch aggregation to **Count**."
            )

    if cfg.numeric_filter_col != "None" and cfg.filter_range:
        lo, hi = cfg.filter_range
        if lo > hi:
            errors.append(
                f"❌ Filter range for `{cfg.numeric_filter_col}` is invalid — "
                f"Min ({lo}) is greater than Max ({hi})."
            )
        col_data = df[cfg.numeric_filter_col].dropna()
        if lo == hi == float(col_data.min()) or lo == hi:
            errors.append(
                f"⚠️ Filter range for `{cfg.numeric_filter_col}` is a single point ({lo}). "
                f"This may return very few rows."
            )

    if cfg.group_col != "None":
        if cfg.group_col == cfg.x_axis:
            errors.append(
                f"⚠️ **Group by** column `{cfg.group_col}` is the same as X axis. "
                f"This usually creates redundant coloring — pick a different column."
            )
        if cfg.group_col == cfg.y_axis:
            errors.append(
                f"⚠️ **Group by** column `{cfg.group_col}` is the same as Y axis. "
                f"Pick a different column for grouping."
            )
        if _is_numeric(cfg.group_col, df):
            errors.append(
                f"⚠️ **Group by** column `{cfg.group_col}` is numeric with many unique values — "
                f"this may produce too many colors. Use a categorical column instead."
            )

    return errors


def _detect_datetime_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.select_dtypes(include="object").columns:
        try:
            out[col] = pd.to_datetime(out[col])
        except (ValueError, TypeError):
            pass
    return out


def _apply_filters(df: pd.DataFrame, cfg: ChartConfig) -> pd.DataFrame:
    if cfg.numeric_filter_col != "None" and cfg.filter_range:
        lo, hi = cfg.filter_range
        df = df[df[cfg.numeric_filter_col].between(lo, hi)]
    if cfg.cat_filter_col != "None":
        if cfg.date_range:
            df = df[df[cfg.cat_filter_col].dt.date.between(*cfg.date_range)]
        elif cfg.selected_categories:
            df = df[df[cfg.cat_filter_col].isin(cfg.selected_categories)]
    return df


def _aggregate_bar(
    df: pd.DataFrame, x: str, y_col: str, gkeys: list[str], agg: str
) -> pd.DataFrame:
    is_numeric = pd.api.types.is_numeric_dtype(df[y_col]) if y_col in df.columns else False
    fn = AGG_MAP.get(agg, "size")
    if agg in ("Sum", "Mean", "Median") and not is_numeric:
        st.warning(f"Cannot compute {agg} on non-numeric column '{y_col}'. Using Count instead.")
        fn = "size"
    if fn == "size":
        return df.groupby(gkeys).size().reset_index(name=y_col)
    return df.groupby(gkeys)[y_col].agg(fn).reset_index()


def _build_histogram(df: pd.DataFrame, cfg: ChartConfig):
    color = None if cfg.group_col == "None" else cfg.group_col
    fig = px.histogram(df, x=cfg.x_axis, color=color, barmode="overlay",
                       title=f"Distribution of {cfg.x_axis}")
    fig.update_layout(yaxis_title=f"{cfg.x_axis} Frequency")
    return fig


def _build_scatter(df: pd.DataFrame, cfg: ChartConfig):
    if cfg.y_axis == "None":
        raise ValueError("Scatter plot requires a Y axis.")
    color = None if cfg.group_col == "None" else cfg.group_col
    return px.scatter(df, x=cfg.x_axis, y=cfg.y_axis, color=color,
                      title=f"{cfg.x_axis} vs {cfg.y_axis}")


def _build_line(df: pd.DataFrame, cfg: ChartConfig):
    if cfg.y_axis == "None":
        raise ValueError("Line chart requires a Y axis.")
    color = None if cfg.group_col == "None" else cfg.group_col
    gkeys = [cfg.x_axis] + ([color] if color else [])
    if df.duplicated(subset=gkeys).any():
        df = df.groupby(gkeys)[cfg.y_axis].mean().reset_index()
    df = df.sort_values(cfg.x_axis)
    return px.line(df, x=cfg.x_axis, y=cfg.y_axis, color=color,
                   title=f"{cfg.y_axis} Trend over {cfg.x_axis}")


def _build_bar(df: pd.DataFrame, cfg: ChartConfig, categorical_cols: list[str]):
    color  = None if cfg.group_col == "None" else cfg.group_col
    y_col  = cfg.y_axis
    eff_agg = cfg.aggregation
    if cfg.y_axis == "None":
        eff_agg = "Count"
        y_col   = f"{cfg.x_axis} Frequency"
    gkeys = [cfg.x_axis] + ([color] if color else [])
    df = _aggregate_bar(df, cfg.x_axis, y_col, gkeys, eff_agg)
    if cfg.top_n_enabled and cfg.x_axis in categorical_cols:
        top_cats = df.groupby(cfg.x_axis)[y_col].sum().nlargest(cfg.top_n_value).index
        df = df[df[cfg.x_axis].isin(top_cats)]
    return px.bar(df, x=cfg.x_axis, y=y_col, color=color, barmode="group",
                  title=f"{y_col} by {cfg.x_axis}"), y_col


def _build_box(df: pd.DataFrame, cfg: ChartConfig, categorical_cols: list[str]):
    if cfg.y_axis == "None":
        raise ValueError("Box plot requires a Y axis.")
    color = None if cfg.group_col == "None" else cfg.group_col
    if cfg.x_axis not in categorical_cols:
        st.warning(f"'{cfg.x_axis}' is not categorical. Box plots work best when X is a category.")
    return px.box(df, x=cfg.x_axis, y=cfg.y_axis, color=color,
                  title=f"Box Plot of {cfg.y_axis} by {cfg.x_axis}")


def _build_heatmap(df: pd.DataFrame, cfg: ChartConfig, numeric_cols: list[str]):
    cols = cfg.heatmap_cols or numeric_cols
    if len(cols) < 2:
        raise ValueError("Select at least 2 numeric columns.")
    corr = df[cols].corr()
    fig  = px.imshow(corr, text_auto=".2f", color_continuous_scale="RdBu_r",
                     zmin=-1, zmax=1, title="Correlation Heatmap")
    summary = build_correlation_summary(corr, threshold=cfg.corr_threshold)
    return fig, summary


def _collect_config(
    df: pd.DataFrame,
    temp_df: pd.DataFrame,
    numeric_cols: list[str],
    categorical_cols: list[str],
    all_cols: list[str],
) -> ChartConfig:
    chart_type = st.selectbox(
        "Chart Type",
        ["Histogram", "Scatter Plot", "Line Chart", "Bar Chart", "Box Plot", "Correlation Heatmap"],
        key="viz_chart_type",
    )

    rule = CHART_RULES.get(chart_type, "")
    if rule:
        st.caption(f"ℹ️ {rule}")

    cfg = ChartConfig(chart_type=chart_type)

    if chart_type == "Correlation Heatmap":
        cfg.heatmap_cols = st.multiselect(
            "Columns to include", numeric_cols,
            default=numeric_cols[:min(12, len(numeric_cols))],
            key="viz_heatmap_cols",
        )
        if len(cfg.heatmap_cols) < 2:
            st.warning("Select at least 2 numeric columns to generate the heatmap.")
        cfg.corr_threshold = st.slider(
            "Strong-correlation threshold", 0.0, 1.0, 0.7, 0.05, key="viz_corr_thresh"
        )
        return cfg

    cfg.x_axis = st.selectbox("X Axis", all_cols, key=f"viz_x_{chart_type}")

    if cfg.x_axis in numeric_cols:
        st.caption(f"  `{cfg.x_axis}` is **numeric** ✓")
    else:
        st.caption(f"  `{cfg.x_axis}` is **categorical/text**")

    if chart_type == "Histogram":
        st.info("Histogram shows the distribution of the X-axis column. No Y axis needed.")
    else:
        y_opts     = numeric_cols if chart_type == "Box Plot" else all_cols
        cfg.y_axis = st.selectbox("Y Axis", ["None"] + y_opts, key=f"viz_y_{chart_type}")

        if cfg.y_axis != "None":
            if cfg.y_axis in numeric_cols:
                st.caption(f"  `{cfg.y_axis}` is **numeric** ✓")
            else:
                st.caption(f"  `{cfg.y_axis}` is **categorical/text**")

            if chart_type in ("Scatter Plot", "Line Chart", "Box Plot") and cfg.y_axis not in numeric_cols:
                st.warning(
                    f"⚠️ `{cfg.y_axis}` is not numeric. **{chart_type}** requires a numeric Y axis. "
                    f"Pick a numeric column or switch to a Bar Chart."
                )
            if chart_type == "Scatter Plot" and cfg.x_axis not in numeric_cols:
                st.warning(
                    f"⚠️ `{cfg.x_axis}` is not numeric. Scatter plots need numeric X too."
                )
            if cfg.x_axis == cfg.y_axis:
                st.warning("⚠️ X and Y are the same column — results won't be meaningful.")

    used_axes     = {cfg.x_axis, cfg.y_axis} - {"None"}
    group_options = ["None"] + [c for c in categorical_cols if c not in used_axes]
    cfg.group_col = st.selectbox(
        "Group by (Color)", group_options, key="viz_group",
        help="Splits each bar/point/line by a category. Columns already on axes are excluded.",
    )

    if cfg.group_col != "None" and cfg.group_col in numeric_cols:
        st.warning(f"⚠️ `{cfg.group_col}` is numeric — grouping by a numeric column can produce too many colors.")

    if chart_type == "Bar Chart":
        cfg.aggregation = st.selectbox(
            "Aggregation", ["None", "Sum", "Mean", "Count", "Median"], key="viz_agg"
        )
        if cfg.aggregation in ("Sum", "Mean", "Median") and cfg.y_axis != "None" and cfg.y_axis not in numeric_cols:
            st.warning(
                f"⚠️ Cannot apply **{cfg.aggregation}** to `{cfg.y_axis}` — it's not numeric. "
                f"Pick a numeric Y column or use **Count**."
            )
        if cfg.x_axis in categorical_cols:
            cfg.top_n_enabled = st.checkbox("Enable Top N Categories", key="viz_top_n_enabled")
            if cfg.top_n_enabled:
                cfg.top_n_value = st.slider("Number of categories", 1, 20, 10, key="viz_top_n")

    st.caption("**Filters**")
    fn_opts = ["None"] + numeric_cols
    cfg.numeric_filter_col = st.selectbox(
        "Numeric Filter Column", fn_opts, key="viz_num_filter",
        help=(
            "Filters rows by a numeric column's value range before rendering. "
            "You can filter on ANY numeric column — not just the ones on the axes."
        )
    )
    if cfg.numeric_filter_col != "None":
        col_data     = df[cfg.numeric_filter_col].dropna()
        if col_data.empty:
            st.warning(f"⚠️ `{cfg.numeric_filter_col}` has no data to filter.")
        else:
            col_min, col_max = float(col_data.min()), float(col_data.max())
            fa, fb = st.columns(2)
            lo = fa.number_input(f"Min ({cfg.numeric_filter_col})", value=col_min,
                                 min_value=col_min, max_value=col_max, key="viz_fmin")
            hi = fb.number_input(f"Max ({cfg.numeric_filter_col})", value=col_max,
                                 min_value=col_min, max_value=col_max, key="viz_fmax")
            cfg.filter_range = (lo, hi)
            if lo > hi:
                st.error("❌ Min cannot be greater than Max.")
            if cfg.numeric_filter_col not in {cfg.x_axis, cfg.y_axis}:
                st.caption(f"ℹ️ Filtering on **'{cfg.numeric_filter_col}'** (not on an axis). "
                           "Rows outside this range are excluded from the chart.")

    cfg.cat_filter_col = st.selectbox(
        "Categorical/Date Filter Column", ["None"] + categorical_cols, key="viz_cat_filter"
    )
    if cfg.cat_filter_col != "None":
        col_data = temp_df[cfg.cat_filter_col].dropna()
        if col_data.empty:
            st.warning(f"⚠️ `{cfg.cat_filter_col}` has no data to filter.")
        elif pd.api.types.is_datetime64_any_dtype(col_data):
            min_d, max_d = col_data.min().date(), col_data.max().date()
            cfg.date_range = (
                (min_d, max_d)
                if min_d == max_d
                else st.slider("Select Date Range", min_d, max_d, (min_d, max_d), key="viz_date_slider")
            )
        else:
            unique_vals = sorted(col_data.unique().tolist())
            if len(unique_vals) > 15:
                st.info(f"Large number of values ({len(unique_vals)}). Use search below.")
            cfg.selected_categories = st.multiselect("Values", unique_vals, key="viz_cat_vals")
            if cfg.cat_filter_col != "None" and not cfg.selected_categories:
                st.caption("ℹ️ No values selected — all rows will be included.")

    return cfg


class Visualization:
    def __init__(self, sm: SessionManager):
        self.sm = sm

    def render(self):
        st.header("Visualization Studio 📊")
        st.write("Plan the chart on the left and validate the output on the right.")
        df = self.sm.df
        if df is None:
            st.info("Upload a dataset first")
            return

        if df.empty:
            st.warning("⚠️ The dataset is empty. Upload a file with data rows.")
            return

        temp_df          = _detect_datetime_cols(df)
        numeric_cols     = df.select_dtypes(include="number").columns.tolist()
        categorical_cols = [
            c for c in temp_df.columns
            if temp_df[c].dtype == "object"
            or isinstance(temp_df[c].dtype, pd.CategoricalDtype)
            or pd.api.types.is_datetime64_any_dtype(temp_df[c])
        ]
        all_cols = df.columns.tolist()

        if not numeric_cols and not categorical_cols:
            st.warning("⚠️ No usable columns found. Check that the dataset loaded correctly.")
            return

        cfg_col, out_col = st.columns([1, 1])

        with cfg_col:
            with st.container(border=True):
                st.subheader("Chart Configuration")
                cfg     = _collect_config(df, temp_df, numeric_cols, categorical_cols, all_cols)
                gen_btn = st.button("Generate Chart", use_container_width=True, type="primary")
            with st.container(border=True):
                st.subheader("Dataset Guide")
                g1, g2, g3 = st.columns(3)
                with g1:
                    st.metric("Rows", f"{len(df):,}")
                with g2:
                    st.metric("Numeric", len(numeric_cols))
                with g3:
                    st.metric("Category/Date", len(categorical_cols))
                st.write(f"Numeric: {', '.join(numeric_cols[:8]) if numeric_cols else 'None'}")
                st.write(f"Categorical/Date: {', '.join(categorical_cols[:8]) if categorical_cols else 'None'}")

        with out_col:
            with st.container(border=True):
                st.subheader("Visualization Output")

                if not gen_btn:
                    st.markdown(
                        """
                        <div style="
                            display:flex; flex-direction:column;
                            align-items:center; justify-content:center;
                            height:340px; border-radius:8px;
                            border:2px dashed #444; color:#888;
                            font-size:1.1rem; gap:12px;
                        ">
                            <span style="font-size:2.5rem">📈</span>
                            <span>Configure your chart on the left,<br>then click <b>Generate Chart</b>.</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    return

                errors = _validate_config(cfg, df, temp_df, numeric_cols, categorical_cols)
                if errors:
                    for err in errors:
                        if err.startswith("❌"):
                            st.error(err)
                        else:
                            st.warning(err)
                    hard_errors = [e for e in errors if e.startswith("❌")]
                    if hard_errors:
                        st.info(
                            f"💡 **Chart requirements:** {CHART_RULES.get(cfg.chart_type, '')}"
                        )
                        return

                try:
                    fdf = _apply_filters(temp_df.copy(), cfg)
                except Exception as e:
                    st.error(f"❌ Filter error: {e}")
                    return

                if fdf.empty:
                    st.warning(
                        "⚠️ No data matches the current filters. "
                        "Adjust or clear the filter settings."
                    )
                    return

                if len(fdf) < 2 and cfg.chart_type not in ("Histogram", "Bar Chart"):
                    st.warning(
                        f"⚠️ Only {len(fdf)} row(s) match the filters — "
                        f"this may not produce a meaningful {cfg.chart_type}."
                    )

                try:
                    fig             = None
                    corr_summary_df = None
                    y_label         = cfg.y_axis

                    if   cfg.chart_type == "Histogram":
                        fig = _build_histogram(fdf, cfg)
                    elif cfg.chart_type == "Scatter Plot":
                        fig = _build_scatter(fdf, cfg)
                    elif cfg.chart_type == "Line Chart":
                        fig = _build_line(fdf, cfg)
                    elif cfg.chart_type == "Bar Chart":
                        fig, y_label = _build_bar(fdf, cfg, categorical_cols)
                    elif cfg.chart_type == "Box Plot":
                        fig = _build_box(fdf, cfg, categorical_cols)
                    elif cfg.chart_type == "Correlation Heatmap":
                        fig, corr_summary_df = _build_heatmap(fdf, cfg, numeric_cols)

                    if fig:
                        fig.update_layout(
                            xaxis_title=cfg.x_axis,
                            yaxis_title=(
                                y_label
                                if (y_label and y_label != "None" and cfg.chart_type != "Histogram")
                                else (fig.layout.yaxis.title.text or "")
                            ),
                            legend_title=cfg.group_col if cfg.group_col != "None" else None,
                            margin=dict(l=50, r=20, t=50, b=50),
                        )
                        st.plotly_chart(fig, use_container_width=True)

                        if cfg.chart_type == "Correlation Heatmap":
                            st.markdown(f"**Strong Relationships (> {cfg.corr_threshold})**")
                            if corr_summary_df is not None and not corr_summary_df.empty:
                                st.dataframe(corr_summary_df, use_container_width=True)
                            else:
                                st.caption("No strong relationships found at this threshold.")

                        self._render_active_filters(cfg)

                except ValueError as e:
                    st.error(f"❌ Configuration error: {e}")
                    st.info(f"💡 **{cfg.chart_type} requirements:** {CHART_RULES.get(cfg.chart_type, '')}")
                except KeyError as e:
                    st.error(f"❌ Column not found: {e}. It may have been removed or renamed.")
                except Exception as e:
                    st.error(f"❌ Rendering error: {e}")
                    st.info("Try a different column combination or chart type.")

    @staticmethod
    def _render_active_filters(cfg: ChartConfig) -> None:
        active = []
        if cfg.numeric_filter_col != "None" and cfg.filter_range:
            lo, hi = cfg.filter_range
            active.append(f"**{cfg.numeric_filter_col}** between {lo} and {hi}")
        if cfg.cat_filter_col != "None" and (cfg.date_range or cfg.selected_categories):
            val_str = (
                f"{cfg.date_range[0]} → {cfg.date_range[1]}"
                if cfg.date_range
                else ", ".join(str(v) for v in cfg.selected_categories)
            )
            active.append(f"**{cfg.cat_filter_col}**: {val_str}")
        if active:
            st.caption(f"🔍 Active filters: {' | '.join(active)}")