import streamlit as st
import pandas as pd
from modules.session_manager import SessionManager
from modules.ui_components import (
    show_toast, show_last_result, safe_join, build_log_summary, show_violations
)
from modules.data_utils import (
    missing_per_col, count_duplicates, dup_preview,
    build_formula_env, prepare_formula, build_missing_summary
)


class CleaningStudio:
    def __init__(self, sm: SessionManager):
        self.sm = sm
        self.df = sm.df
        if "active_tool" not in self.sm.state:
            self.sm.state["active_tool"] = "Missing values"

    def render(self):
        st.header("Cleaning Studio 🧹")
        st.write("Use the manual tools here, and use the AI helper dock below the tabs when you want suggestions.")
        if self.df is None:
            st.info("Upload a dataset first")
            return

        nav_col, tool_col = st.columns([1.05, 1.95])

        with nav_col:
            with st.container(border=True):
                st.subheader("Tool Navigator")
                st.caption("Choose one cleaning area at a time so the workspace stays easy to follow.")
                tools = [
                    "Missing values", "Duplicate handling", "Data type conversion",
                    "Categorical cleaning", "Outlier handling", "Scaling",
                    "Column operations", "Data validation"
                ]
                for tool in tools:
                    if st.button(
                        tool,
                        key=f"nav_{tool}",
                        use_container_width=True,
                        type="primary" if self.sm.state["active_tool"] == tool else "secondary"
                    ):
                        self.sm.state["active_tool"] = tool
                        st.rerun()
                st.info(f"Current focus: {self.sm.state['active_tool']}")

        with tool_col:
            show_toast()
            show_last_result()

            active = self.sm.state["active_tool"]
            st.caption("Set the options for the current tool here, review the preview, then apply the change.")
            st.subheader(f"🛠️ {active}")

            if active == "Missing values":
                self._render_missing_content()
            elif active == "Duplicate handling":
                self._render_duplicate_content()
            elif active == "Data type conversion":
                self._render_dtype_content()
            elif active == "Categorical cleaning":
                self._render_categorical_content()
            elif active == "Outlier handling":
                self._render_outlier_content()
            elif active == "Scaling":
                self._render_scaling_content()
            elif active == "Column operations":
                self._render_column_ops_content()
            elif active == "Data validation":
                self._render_validation_content()

        st.divider()
        st.subheader("Workspace Status")
        self._render_metrics()


    def _render_missing_content(self):
        st.info("💡 **Tip:** Handle null values by filling them with statistics or dropping them entirely.")
        selected_cols = st.multiselect("Select Columns to Clean", self.df.columns.tolist(), key="missing_cols")

        action = st.selectbox(
            "Choose an Action",
            ["Drop rows", "Drop rows above threshold",
             "Fill numeric with median", "Fill numeric with mean",
             "Fill numeric with mode",
             "Fill categorical with the most frequent",
             "Drop columns above threshold",
             "Forward fill", "Backward fill", "Fill with custom value"],
            key="missing_action",
        )

        custom_value = row_threshold = col_threshold = None
        if action == "Fill with custom value":
            custom_value = st.text_input("Enter Custom Value", key="missing_custom")
        elif action == "Drop rows above threshold":
            row_threshold = st.slider("Row missing threshold (%)", 0.0, 100.0, 50.0, 1.0, key="missing_row_thresh")
            st.caption(
                f"Rows where **more than {row_threshold:.0f}%** of the selected columns are missing will be dropped. "
                "Only the selected columns are evaluated — other columns are not affected."
            )
        elif action == "Drop columns above threshold":
            col_threshold = st.slider("Column missing threshold (%)", 0.0, 100.0, 50.0, 1.0, key="missing_col_thresh")
            st.caption(
                f"Columns where **more than {col_threshold:.0f}%** of their values are missing will be dropped."
            )

        if action in ("Forward fill", "Backward fill") and selected_cols:
            non_date = [
                c for c in selected_cols
                if not pd.api.types.is_datetime64_any_dtype(self.df[c])
            ]
            if non_date:
                st.warning(
                    f"⚠️ **Note:** Forward/Backward fill propagates the nearest existing value into empty cells. "
                    f"For non-date/non-sequential columns ({safe_join(non_date)}) this can introduce "
                    "misleading data. Make sure this is intentional."
                )

        if selected_cols:
            miss_rows = [
                {"column": c,
                 "missing_count": int(self.df[c].isna().sum()),
                 "missing_%": round(self.df[c].isna().mean() * 100, 1)}
                for c in selected_cols
            ]
            total_miss = sum(r["missing_count"] for r in miss_rows)

            with st.expander(f"📊 Missing Value Summary — {total_miss:,} missing cells in selected columns"):
                st.dataframe(pd.DataFrame(miss_rows), use_container_width=True)

            _fill_preview = []
            if action in ("Fill numeric with median", "Fill numeric with mean", "Fill numeric with mode"):
                for col in selected_cols:
                    if pd.api.types.is_numeric_dtype(self.df[col]) and self.df[col].isna().any():
                        if action == "Fill numeric with median":
                            val = self.df[col].median()
                            stat = "median"
                        elif action == "Fill numeric with mean":
                            val = self.df[col].mean()
                            stat = "mean"
                        else:
                            m = self.df[col].mode(dropna=True)
                            val = m.iloc[0] if not m.empty else None
                            stat = "mode"
                        if val is not None:
                            _fill_preview.append({
                                "column": col,
                                "statistic": stat,
                                "fill_value": round(float(val), 4),
                                "cells_to_fill": int(self.df[col].isna().sum()),
                            })
            elif action == "Fill categorical with the most frequent":
                for col in selected_cols:
                    if not pd.api.types.is_numeric_dtype(self.df[col]) and self.df[col].isna().any():
                        m = self.df[col].mode(dropna=True)
                        if not m.empty:
                            _fill_preview.append({
                                "column": col,
                                "statistic": "most frequent",
                                "fill_value": str(m.iloc[0]),
                                "cells_to_fill": int(self.df[col].isna().sum()),
                            })

            if _fill_preview:
                st.info("**📋 Fill Preview** — values that will be used to fill missing cells:")
                st.dataframe(pd.DataFrame(_fill_preview), use_container_width=True)

        if st.button("🚀 Apply Changes", key="missing_apply", use_container_width=True):
            if not selected_cols:
                st.warning("⚠️ **No columns selected.** Please choose at least one column to proceed.")
            else:
                cols_with_na = [c for c in selected_cols if self.df[c].isna().any()]
                if not cols_with_na and "Drop rows" not in action and "threshold" not in action:
                    st.success(f"✨ **Perfect!** The selected columns ({safe_join(selected_cols)}) already have no missing values.")
                else:
                    self._apply_missing(selected_cols, action, custom_value, row_threshold, col_threshold)

    def _apply_missing(self, cols, action, custom_value, row_threshold, col_threshold):
        df = self.df.copy()
        rows_affected = 0
        if action == "Drop rows":
            before = len(df)
            df = df.dropna(subset=cols)
            rows_affected = before - len(df)
            if rows_affected == 0:
                st.info("ℹ️ **No changes made.** No rows contained missing values in the selected columns.")
                return
        elif action == "Drop rows above threshold":
            pct = df[cols].isna().mean(axis=1) * 100
            mask = pct > row_threshold
            df = df.loc[~mask].copy()
            rows_affected = int(mask.sum())
            if rows_affected == 0:
                st.info(
                    f"ℹ️ **No rows dropped.** No row had more than {row_threshold:.0f}% of the "
                    f"selected columns missing. Other columns are unaffected by this action."
                )
                return
        elif action == "Drop columns above threshold":
            drop = [c for c in cols if df[c].isna().mean() * 100 > col_threshold]
            if not drop:
                st.info(f"ℹ️ **No columns dropped.** None of the selected columns exceeded {col_threshold:.0f}% missing.")
                return
            df = df.drop(columns=drop)
            rows_affected = len(drop)
        else:
            incompatible = []
            for col in cols:
                mask = df[col].isna()
                before_na = int(mask.sum())
                if before_na == 0:
                    continue
                is_num = pd.api.types.is_numeric_dtype(df[col])
                if action == "Fill numeric with median":
                    if not is_num:
                        incompatible.append(col)
                        continue
                    df.loc[mask, col] = df[col].median()
                elif action == "Fill numeric with mean":
                    if not is_num:
                        incompatible.append(col)
                        continue
                    df.loc[mask, col] = df[col].mean()
                elif action == "Fill numeric with mode":
                    if not is_num:
                        incompatible.append(col)
                        continue
                    m = df[col].mode(dropna=True)
                    if not m.empty:
                        df.loc[mask, col] = m.iloc[0]
                elif action == "Fill categorical with the most frequent":
                    if is_num:
                        incompatible.append(col)
                        continue
                    m = df[col].mode(dropna=True)
                    if not m.empty:
                        df.loc[mask, col] = m.iloc[0]
                elif action == "Forward fill":
                    df.loc[mask, col] = df[col].ffill().loc[mask]
                elif action == "Backward fill":
                    df.loc[mask, col] = df[col].bfill().loc[mask]
                elif action == "Fill with custom value":
                    df.loc[mask, col] = custom_value
                rows_affected += before_na - int(df[col].isna().sum())

            if incompatible:
                label = "numeric" if "numeric" in action else "categorical"
                st.error(
                    f"❌ **Type Mismatch:** '{action}' requires **{label}** columns. "
                    f"Skipped: {safe_join(incompatible)}"
                )
                if rows_affected == 0:
                    return

        details = {
            "action": action,
            "columns": cols,
            "rows_affected": rows_affected,
        }
        if row_threshold is not None:
            details["threshold"] = row_threshold
        if col_threshold is not None:
            details["threshold"] = col_threshold
        if custom_value is not None:
            details["custom_value"] = custom_value

        self.sm.commit(
            df, "Missing Values", details,
            f"✅ **Success!** {rows_affected} cell(s)/row(s) were successfully updated."
        )


    def _render_duplicate_content(self):
        st.info("💡 **Tip:** Identify and remove duplicate entries to ensure data uniqueness.")
        gen = self.sm.transformation_count
        dup_mode = st.radio("Duplicate Check Scope", ["All columns", "Selected columns"], key=f"dup_mode_{gen}")
        subset_cols = None
        if dup_mode == "Selected columns":
            subset_cols = st.multiselect("Select Columns for Comparison", self.df.columns.tolist(), key=f"dup_subset_{gen}")
            if not subset_cols:
                st.warning("⚠️ **Selection required.** Please select columns to check for duplicates.")

        keep_option = st.selectbox(
            "Duplicate Action",
            ["Keep first", "Keep last", "Remove all duplicates (no copies)"],
            key=f"dup_keep_{gen}"
        )
        keep_map = {"Keep first": "first", "Keep last": "last", "Remove all duplicates (no copies)": False}
        keep_val = keep_map[keep_option]

        can_preview = not (dup_mode == "Selected columns" and not subset_cols)
        if can_preview:
            s_tuple = tuple(subset_cols) if subset_cols else None
            dup_count = count_duplicates(self.df, s_tuple, keep_val)
            st.write(f"🔍 **Duplicate rows found:** `{dup_count}`")
            if dup_count > 0:
                with st.expander("👁️ View Duplicates Preview"):
                    st.dataframe(dup_preview(self.df, s_tuple, keep_val), use_container_width=True)
            else:
                st.success("✨ **Clean!** No duplicate rows found with current settings.")

        if st.button("🚀 Apply Deduplication", key=f"dup_apply_{gen}", use_container_width=True):
            if dup_mode == "Selected columns" and not subset_cols:
                st.warning("⚠️ **Action needed.** Please select columns first.")
            else:
                s_list = list(subset_cols) if subset_cols else None
                before = len(self.df)
                if keep_val is False:
                    new_df = self.df[~self.df.duplicated(subset=s_list, keep=False)].copy()
                else:
                    new_df = self.df.drop_duplicates(subset=s_list, keep=keep_val).copy()
                rows_removed = before - len(new_df)
                if rows_removed == 0:
                    st.info("ℹ️ **No duplicates removed.** Dataset is already unique.")
                else:
                    self.sm.commit(
                        new_df, "Duplicate Handling",
                        {"action": keep_option, "rows_removed": rows_removed, "subset": s_list},
                        f"✅ **Success!** Removed {rows_removed} duplicate row(s)."
                    )


    def _render_dtype_content(self):
        st.info("💡 **Tip:** Ensure your data is in the correct format for analysis (e.g., Numbers for math, Datetime for time series).")
        selected_cols = st.multiselect("Select Columns to Convert", self.df.columns.tolist(), key="dtype_cols")
        conv_type = st.selectbox(
            "Target Data Type",
            ["To numeric", "To categorical", "To datetime"],
            key="dtype_conv"
        )

        if conv_type == "To categorical" and selected_cols:
            num_selected = [
                c for c in selected_cols
                if pd.api.types.is_numeric_dtype(self.df[c])
            ]
            if num_selected:
                st.warning(
                    f"⚠️ **Heads up:** {safe_join(num_selected)} appear to be numeric. "
                    "Converting them to categorical will prevent future numeric operations (mean, sum, etc.). "
                    "Only proceed if these columns represent discrete labels (e.g., codes, IDs)."
                )

        if conv_type == "To numeric" and selected_cols:
            dt_selected = [
                c for c in selected_cols
                if pd.api.types.is_datetime64_any_dtype(self.df[c])
            ]
            text_selected = [
                c for c in selected_cols
                if not pd.api.types.is_numeric_dtype(self.df[c])
                and not pd.api.types.is_datetime64_any_dtype(self.df[c])
            ]
            if dt_selected:
                st.warning(
                    f"⚠️ **Heads up:** {safe_join(dt_selected)} are datetime columns. "
                    "Converting them to numeric will produce Unix timestamps (nanoseconds since 1970). "
                    "This is usually not what you want — consider keeping them as datetime."
                )
            if text_selected:
                st.warning(
                    f"⚠️ **Heads up:** {safe_join(text_selected)} contain text. "
                    "Values that cannot be parsed as numbers will be set to NaN. "
                    "Use 'Clean numeric strings' below if your values contain symbols like $, €, or commas."
                )

        dt_fmt = clean_num = None
        if conv_type == "To datetime":
            dt_fmt = st.text_input("Date Format (Optional)", placeholder="e.g. %Y-%m-%d", key="dtype_dtfmt")
            st.caption("Leave blank for smart automatic parsing.")
        elif conv_type == "To numeric":
            clean_num = st.checkbox("Clean numeric strings (remove $, €, commas)", key="dtype_clean")

        if st.button("🚀 Apply Conversion", key="dtype_apply_btn", use_container_width=True):
            if not selected_cols:
                st.warning("⚠️ **No columns selected.** Please pick at least one column.")
            else:
                self._apply_dtype(selected_cols, conv_type, dt_fmt, clean_num)

    def _apply_dtype(self, cols, conv_type, dt_fmt, clean_num):
        new_df = self.df.copy()
        total_conv = total_nan = processed = 0
        warnings = []
        for col in cols:
            orig = new_df[col]
            try:
                before_na = int(orig.isna().sum())
                if conv_type == "To numeric":
                    s = orig.astype(str)
                    if clean_num:
                        s = s.str.replace(r"[,\$\€\£]", "", regex=True).str.replace(r"\s+", "", regex=True)
                    converted = pd.to_numeric(s, errors="coerce")
                elif conv_type == "To datetime":
                    converted = pd.to_datetime(orig, format=dt_fmt if dt_fmt else "mixed", errors="coerce")
                else:
                    converted = orig.astype("category")

                after_na = int(converted.isna().sum())
                newly_null = max(after_na - before_na, 0)
                total_nan += newly_null
                total_conv += max((len(orig) - before_na) - newly_null, 0)
                new_df[col] = converted
                processed += 1
                if newly_null:
                    warnings.append(
                        f"'{col}': {newly_null:,} value(s) could not be parsed as "
                        f"{conv_type.replace('To ', '').lower()} and were set to NaN."
                    )
            except Exception as e:
                warnings.append(f"'{col}': Conversion failed — {e}")

        result_data = {"label": "Conversion Notes:", "df": pd.DataFrame({"details": warnings})} if warnings else None
        if total_nan:
            toast = (
                f"✅ Converted {processed} column(s) to {conv_type.lower()} — "
                f"⚠️ {total_nan:,} value(s) could not be parsed and were set to NaN. "
                "See details below."
            )
        else:
            toast = f"✅ Successfully converted {processed} column(s) to {conv_type.lower()}."

        self.sm.commit(
            new_df, "Data Type Conversion",
            {"type": conv_type, "columns": cols, "rows_changed": total_conv, "coerced_to_nan": total_nan},
            toast, result=result_data
        )


    def _render_categorical_content(self):
        st.info("💡 **Tip:** Clean up text data by trimming spaces, changing case, or grouping rare values.")
        selected_cols = st.multiselect("Select Categorical Columns", self.df.columns.tolist(), key="cat_cols")

        st.markdown("---")
        st.caption("**1. Basic Text Formatting**")
        c1, c2, c3 = st.columns(3)
        with c1: trim  = st.checkbox("Trim Whitespace", key="cat_trim")
        with c2: lower = st.checkbox("Lowercase",       key="cat_lower")
        with c3: title = st.checkbox("Title Case",      key="cat_title")

        if lower and title:
            st.error("❌ **Conflicting options:** Please choose either Lowercase OR Title Case.")

        st.markdown("---")
        st.caption("**2. Value Mapping (Manual Correction)**")
        enable_map = st.checkbox("Enable Manual Mapping Table", key="cat_map_en")
        mapping_df = None
        set_unmatched = False
        other_value = "Other"

        if enable_map:
            if not selected_cols:
                st.warning("⚠️ Select columns first to generate the mapping table.")
            else:
                uniq = pd.Series(dtype="object")
                for col in selected_cols:
                    uniq = pd.concat([uniq, self.df[col].dropna().astype(str)])
                uniq = pd.Series(uniq.unique()).sort_values().reset_index(drop=True)
                st.write("Edit the 'new_value' column below to map values:")
                mapping_df = st.data_editor(
                    pd.DataFrame({"old_value": uniq, "new_value": uniq}),
                    num_rows="dynamic", key="cat_map_editor", use_container_width=True
                )
                set_unmatched = st.checkbox("Set all other (unmatched) values to a specific label", key="cat_unmatched")
                if set_unmatched:
                    other_value = st.text_input("Label for unmatched values", value="Other", key="cat_other")

        st.markdown("---")
        st.caption("**3. Grouping & Encoding**")
        enable_rare = st.checkbox("Group Rare Categories", key="cat_rare_en")
        rare_thresh, rare_label = 0.05, "Other"
        if enable_rare:
            rare_thresh = st.slider("Frequency Threshold (0.05 = 5%)", 0.0, 1.0, 0.05, 0.01, key="cat_rare_thresh")
            rare_label  = st.text_input("Label for Rare Groups", value="Other", key="cat_rare_label")

        one_hot = st.checkbox("Apply One-Hot Encoding (Expand columns)", key="cat_ohe")
        keep_original_ohe = False
        if one_hot:
            keep_original_ohe = st.checkbox(
                "Keep original column(s) after encoding",
                key="cat_ohe_keep",
                help="When enabled, the original column is preserved alongside the new dummy columns."
            )
            st.caption(
                "ℹ️ One-Hot Encoding creates one new binary column per unique category. "
                "The original column is **dropped by default** (uncheck above to keep it)."
            )

        if st.button("🚀 Apply Categorical Cleaning", key="cat_apply_btn", use_container_width=True):
            if not selected_cols:
                st.warning("⚠️ **No columns selected.**")
            elif lower and title:
                st.error("❌ **Conflict:** Fix the case formatting conflict first.")
            else:
                self._apply_categorical(
                    selected_cols, trim, lower, title,
                    enable_map, mapping_df, set_unmatched, other_value,
                    enable_rare, rare_thresh, rare_label,
                    one_hot, keep_original_ohe
                )

    def _apply_categorical(
        self, cols, trim, lower, title,
        enable_map, mapping_df, set_unmatched, other_value,
        enable_rare, rare_thresh, rare_label,
        one_hot, keep_original_ohe=False
    ):
        new_df = self.df.copy()
        rows_aff = cols_aff = 0
        map_dict = (
            dict(zip(mapping_df["old_value"].astype(str), mapping_df["new_value"].astype(str)))
            if enable_map and mapping_df is not None else None
        )
        for col in cols:
            try:
                orig = new_df[col].copy()
                s = new_df[col].astype(object).copy()
                not_null = s.notna()
                w = s[not_null].astype(str)
                if trim:  w = w.str.strip()
                if lower: w = w.str.lower()
                if title: w = w.str.title()
                if map_dict is not None:
                    mapped = w.map(map_dict)
                    w = mapped.fillna(other_value) if set_unmatched else mapped.where(mapped.notna(), w)
                if enable_rare:
                    freq = w.value_counts(normalize=True)
                    rare = freq[freq < rare_thresh].index
                    w = w.where(~w.isin(rare), rare_label)
                s[not_null] = w.values
                new_df[col] = s
                changed = int(
                    (orig.fillna("__NA__").astype(str) != new_df[col].fillna("__NA__").astype(str)).sum()
                )
                if changed:
                    rows_aff += changed
                    cols_aff += 1
            except Exception as e:
                st.warning(f"⚠️ Error on '{col}': {e}")

        if one_hot:
            try:
                ohe_cols = [c for c in cols if c in new_df.columns]
                originals = {c: new_df[c].copy() for c in ohe_cols} if keep_original_ohe else {}
                new_df = pd.get_dummies(new_df, columns=ohe_cols)
                if keep_original_ohe:
                    for c, series in originals.items():
                        dummy_cols = [dc for dc in new_df.columns if dc.startswith(f"{c}_")]
                        insert_pos = new_df.columns.get_loc(dummy_cols[-1]) + 1 if dummy_cols else len(new_df.columns)
                        new_df.insert(insert_pos, f"{c}_original", series)
                cols_aff += len(ohe_cols)
            except Exception as e:
                st.warning(f"⚠️ One-hot encoding failed: {e}")

        self.sm.commit(
            new_df, "Categorical Cleaning",
            {
                "columns":          cols,
                "rows_affected":    rows_aff,
                "columns_affected": cols_aff,
                "trim":             trim,
                "lower":            lower,
                "title":            title,
                "mapping":          map_dict if enable_map and map_dict else None,
                "set_unmatched":    set_unmatched if enable_map else False,
                "other_value":      other_value if (enable_map and set_unmatched) else None,
                "rare_grouping":    enable_rare,
                "rare_threshold":   rare_thresh if enable_rare else None,
                "rare_label":       rare_label  if enable_rare else None,
                "one_hot":          one_hot,
                "keep_original_ohe": keep_original_ohe if one_hot else False,
            },
            f"✅ **Success!** {rows_aff} cell(s) updated across {cols_aff} column(s)."
        )


    def _render_outlier_content(self):
        st.info("💡 **Tip:** Outliers are extreme values that can skew your analysis. You can cap them or remove them.")
        num_cols = self.df.select_dtypes(include="number").columns.tolist()
        if not num_cols:
            st.warning("ℹ️ **No numeric columns found.** Outlier detection requires numerical data.")
            return

        selected_cols = st.multiselect("Select Numeric Columns", num_cols, key="outlier_cols")
        action = st.selectbox(
            "Action to Perform",
            ["Show only (Preview)", "Cap (Winsorize)", "Remove rows"],
            key="outlier_act"
        )

        st.caption(
            "**How outliers are detected:** values below the Lower Percentile bound or above "
            "the Upper Percentile bound are treated as outliers. Adjust the sliders to change "
            "the thresholds — the counts and bounds update when you apply."
        )
        c1, c2 = st.columns(2)
        with c1: lq = st.slider("Lower Percentile", 0.0, 0.5, 0.05, 0.01, key="outlier_lq")
        with c2: uq = st.slider("Upper Percentile", 0.5, 1.0, 0.95, 0.01, key="outlier_uq")

        if selected_cols:
            preview_rows = []
            for col in selected_cols:
                s = self.df[col].dropna()
                if s.empty:
                    continue
                lo = s.quantile(lq)
                hi = s.quantile(uq)
                count_out = int(((s < lo) | (s > hi)).sum())
                preview_rows.append({
                    "column": col,
                    "lower_bound": round(float(lo), 4),
                    "upper_bound": round(float(hi), 4),
                    "outliers_found": count_out,
                    "min": round(float(s.min()), 4),
                    "max": round(float(s.max()), 4),
                })
            if preview_rows:
                with st.expander("📊 Outlier Bounds Preview (updates with slider)"):
                    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

        if st.button("🚀 Apply Outlier Action", key="outlier_apply_btn", use_container_width=True):
            if not selected_cols:
                st.warning("⚠️ **Selection required.** Please pick at least one numeric column.")
            else:
                self._apply_outlier(selected_cols, action, lq, uq)

    def _apply_outlier(self, cols, action, lq, uq):
        new_df = self.df.copy()
        summary = []
        total_ol = total_cap = total_rm = 0
        skipped = []

        for col in cols:
            try:
                s = new_df[col]
                if s.isna().all():
                    skipped.append(col)
                    continue

                lower_bound = s.quantile(lq)
                upper_bound = s.quantile(uq)
                mask = (s < lower_bound) | (s > upper_bound)
                cnt = int(mask.sum())
                total_ol += cnt

                info = {
                    "column": col,
                    "outliers": cnt,
                    "lower_bound": round(float(lower_bound), 4),
                    "upper_bound": round(float(upper_bound), 4),
                    "min": round(float(s.min()), 4),
                    "max": round(float(s.max()), 4),
                }

                if action == "Cap (Winsorize)":
                    capped = s.clip(lower_bound, upper_bound)
                    ch = int((s != capped).sum())
                    total_cap += ch
                    new_df[col] = capped
                    info["capped"] = ch

                summary.append(info)
            except Exception as e:
                skipped.append(f"{col} ({e})")

        if action == "Remove rows":
            combined = pd.Series(False, index=new_df.index)
            for col in cols:
                try:
                    s = new_df[col]
                    lo = s.quantile(lq)
                    hi = s.quantile(uq)
                    combined |= (s < lo) | (s > hi)
                except Exception:
                    pass
            before = len(new_df)
            new_df = new_df[~combined]
            total_rm = before - len(new_df)

        if "Show only" in action:
            if summary:
                st.dataframe(pd.DataFrame(summary), use_container_width=True)
            if skipped:
                st.warning(f"⚠️ Skipped columns (all NaN): {safe_join(skipped)}")
            st.info(
                f"🔍 **Analysis Complete:** Detected {total_ol} outlier(s) across "
                f"{len(summary)} column(s) using percentile bounds "
                f"[{lq*100:.0f}th – {uq*100:.0f}th]."
            )
        else:
            if action == "Cap (Winsorize)":
                if total_cap == 0:
                    st.info(
                        f"ℹ️ **No values capped.** All values in selected columns already fall "
                        f"within the [{lq*100:.0f}th – {uq*100:.0f}th] percentile range."
                    )
                    return
                msg = f"✅ **Capped** {total_cap} value(s) to the [{lq*100:.0f}th – {uq*100:.0f}th] percentile bounds."
            else:
                if total_rm == 0:
                    st.info(
                        f"ℹ️ **No rows removed.** No rows fell outside the "
                        f"[{lq*100:.0f}th – {uq*100:.0f}th] percentile bounds for the selected columns."
                    )
                    return
                msg = f"✅ **Removed** {total_rm} row(s) containing values outside the [{lq*100:.0f}th – {uq*100:.0f}th] percentile bounds."

            result = {"label": "Outlier Summary:", "df": pd.DataFrame(summary)} if summary else None
            self.sm.commit(
                new_df, "Outlier Handling",
                {
                    "action": action,
                    "columns": cols,
                    "total_outliers": total_ol,
                    "rows_removed": total_rm,
                    "values_capped": total_cap,
                    "lower_percentile": lq,
                    "upper_percentile": uq,
                },
                msg, result=result
            )


    def _render_scaling_content(self):
        st.info("💡 **Tip:** Scaling brings all numeric values into a similar range (e.g., 0 to 1), which is essential for many ML models.")
        num_cols = self.df.select_dtypes(include="number").columns.tolist()
        if not num_cols:
            st.warning("ℹ️ **No numeric columns available.**")
            return

        selected_cols = st.multiselect("Select Columns to Scale", num_cols, key="scaling_cols")
        method = st.selectbox(
            "Scaling Method",
            ["Min-Max Scaling (0 to 1)", "Z-score Standardization (Mean=0, Std=1)"],
            key="scaling_method"
        )

        if st.button("🚀 Apply Scaling", key="scaling_apply_btn", use_container_width=True):
            if not selected_cols:
                st.warning("⚠️ **Selection required.**")
            else:
                self._apply_scaling(selected_cols, method)

    def _apply_scaling(self, cols, method):
        new_df = self.df.copy()
        stats = []
        skipped = []
        for col in cols:
            try:
                s = new_df[col]
                if s.isna().all():
                    skipped.append(f"{col} (all NaN)")
                    continue
                bef = {k: float(getattr(s, k)()) for k in ("mean", "std", "min", "max")}
                if "Min-Max" in method:
                    lo, hi = s.min(), s.max()
                    if lo == hi:
                        skipped.append(f"{col} (constant values)")
                        continue
                    scaled = (s - lo) / (hi - lo)
                else:
                    m, sd = s.mean(), s.std()
                    if sd == 0:
                        skipped.append(f"{col} (zero variation)")
                        continue
                    scaled = (s - m) / sd
                new_df[col] = scaled
                stats.append({
                    "column":      col,
                    "before_mean": round(bef["mean"], 4),
                    "after_mean":  round(float(scaled.mean()), 4),
                    "before_std":  round(bef["std"],  4),
                    "after_std":   round(float(scaled.std()),  4),
                    "before_min":  round(bef["min"],  4),
                    "after_min":   round(float(scaled.min()),  4),
                    "before_max":  round(bef["max"],  4),
                    "after_max":   round(float(scaled.max()),  4),
                })
            except Exception as e:
                skipped.append(f"{col} ({e})")

        if not stats:
            st.warning("⚠️ **No columns were scaled.** " + (f"Skipped: {safe_join(skipped)}" if skipped else ""))
        else:
            self.sm.commit(
                new_df, "Scaling",
                {"method": method, "columns": cols},
                f"✅ **Success!** Applied {method} to {len(stats)} column(s).",
                result={"label": f"Scaling Statistics ({method}):", "df": pd.DataFrame(stats)}
            )


    def _render_column_ops_content(self):
        st.info("💡 **Tip:** Use these operations to restructure your dataset columns.")
        operation = st.selectbox(
            "Choose Operation",
            ["Rename column", "Drop columns", "Create column (formula)",
             "Split column", "Binning (Equal Width)", "Binning (Quantile)"],
            key="colops_op"
        )

        if operation == "Rename column":
            rename_target = st.selectbox("Select Column to Rename", self.df.columns.tolist(), key="rf_target")
            rename_new = st.text_input("Enter New Name", placeholder="e.g. price_usd", key="rf_new")
            if st.button("🚀 Rename Now", key="rename_btn", use_container_width=True):
                name = (rename_new or "").strip()
                if not name:
                    st.error("❌ **Error:** New name cannot be empty.")
                elif name == rename_target:
                    st.info("ℹ️ Same name provided. No change needed.")
                elif name in self.df.columns:
                    st.error(f"❌ **Error:** A column named '{name}' already exists.")
                else:
                    self.sm.commit(
                        self.df.rename(columns={rename_target: name}),
                        "Rename Column",
                        {"mapping": {rename_target: name}},
                        f"✅ **Renamed:** '{rename_target}' → '{name}'"
                    )

        elif operation == "Drop columns":
            drop_cols = st.multiselect("Select Columns to Remove", self.df.columns.tolist(), key="df_cols")
            if drop_cols:
                st.warning(f"⚠️ **Careful!** You are about to permanently remove: {safe_join(drop_cols)}")
            if st.button("🗑️ Drop Selected Columns", key="drop_btn", use_container_width=True):
                if not drop_cols:
                    st.warning("⚠️ No columns selected.")
                else:
                    self.sm.commit(
                        self.df.drop(columns=drop_cols),
                        "Drop Columns",
                        {"columns": drop_cols},
                        f"✅ **Dropped** {len(drop_cols)} column(s)."
                    )

        elif operation == "Create column (formula)":
            st.info("📝 **Syntax:** Use `[Column Name]` for names with spaces. Examples: `[Price] * 1.2` or `[Revenue] - [Cost]`")
            col_name = st.text_input("New Column Name", placeholder="e.g. total_cost", key="ff_name")
            formula  = st.text_input("Formula Expression", placeholder="e.g. [Price] * [Quantity]", key="ff_expr")
            if st.button("🚀 Create Column", key="formula_btn", use_container_width=True):
                name = (col_name or "").strip()
                expr = (formula or "").strip()
                err = tmp = None
                if not name:
                    err = "Column name is required."
                elif name in self.df.columns:
                    err = f"Column '{name}' already exists."
                elif not expr:
                    err = "Formula cannot be empty."
                else:
                    try:
                        tmp = self.df.copy()
                        env, al = build_formula_env(tmp)
                        tmp[name] = eval(prepare_formula(expr, al), {"__builtins__": {}}, env)
                    except Exception as e:
                        err = str(e)
                        tmp = None
                if err:
                    st.error(f"❌ **Formula Error:** {err}")
                else:
                    self.sm.commit(
                        tmp, "Create Column",
                        {"new_column": name, "formula": expr},
                        f"✅ **Created:** New column '{name}' added."
                    )

        elif operation == "Split column":
            source_col  = st.selectbox("Select Column to Split", self.df.columns.tolist(), key="split_source")
            delimiter   = st.text_input("Enter Delimiter", value="/", key="split_delim")
            c1, c2 = st.columns(2)
            with c1: left_name  = st.text_input("First New Column Name",  placeholder="e.g. Part 1", key="split_left")
            with c2: right_name = st.text_input("Second New Column Name", placeholder="e.g. Part 2", key="split_right")
            drop_source = st.checkbox("Delete original column after splitting", value=False, key="split_drop")

            delim_live = delimiter if delimiter else "/"
            series_live = self.df[source_col].dropna().astype(str).str.strip()
            total_vals  = len(series_live)

            if total_vals > 0:
                has_delim  = series_live.str.contains(delim_live, regex=False)
                match_count   = int(has_delim.sum())
                no_match      = series_live[~has_delim]
                no_match_count = len(no_match)

                COMMON_DELIMS = ["/", "-", "|", ";", ",", ".", " – ", " — ", "~", "_", "\\"]
                alt_found: dict[str, int] = {}
                for d in COMMON_DELIMS:
                    if d == delim_live:
                        continue
                    cnt = int(no_match.str.contains(d, regex=False).sum())
                    if cnt > 0:
                        alt_found[d] = cnt

                pct_match = match_count / total_vals * 100
                if no_match_count == 0:
                    st.success(
                        f"✅ All **{total_vals:,}** non-null values contain the delimiter "
                        f"`{delim_live}` — clean split expected."
                    )
                else:
                    st.warning(
                        f"⚠️ **{no_match_count:,} of {total_vals:,} values "
                        f"({100 - pct_match:.1f}%) do not contain `{delim_live}`.** "
                        "These rows will produce an empty right-hand side after splitting."
                    )

                    if alt_found:
                        alt_lines = ", ".join(
                            f"`{d}` in {c:,} row{'s' if c > 1 else ''}"
                            for d, c in sorted(alt_found.items(), key=lambda x: -x[1])
                        )
                        st.info(
                            f"🔍 **Possible alternative delimiters detected** in the mismatched rows: "
                            f"{alt_lines}. "
                            "Consider changing the delimiter above or cleaning these rows first."
                        )

                    with st.expander(
                        f"👁️ Preview of {no_match_count:,} rows that won't split with `{delim_live}`",
                        expanded=True,
                    ):
                        preview_df = self.df.loc[no_match.index, [source_col]].head(20).copy()
                        preview_df.index.name = "row"
                        st.dataframe(preview_df, use_container_width=True)
                        if no_match_count > 20:
                            st.caption(f"Showing first 20 of {no_match_count:,} rows.")

            if st.button("🚀 Split Column Now", key="split_btn", use_container_width=True):
                delim = delimiter if delimiter else "/"
                left, right = (left_name or "").strip(), (right_name or "").strip()
                err = tmp = None
                if not left or not right:
                    err = "Both new names are required."
                elif left == right:
                    err = "Names must be different."
                elif left in self.df.columns or right in self.df.columns:
                    err = "One of the new names already exists."
                else:
                    try:
                        tmp = self.df.copy()
                        series = tmp[source_col].dropna().astype(str).str.strip()
                        split_df = series.str.split(delim, n=1, expand=True)
                        if split_df.shape[1] < 2:
                            raise ValueError(f"No values could be split using '{delim}'")

                        source_idx = tmp.columns.get_loc(source_col)
                        full_split = tmp[source_col].astype(str).str.split(delim, n=1, expand=True)
                        left_vals  = full_split[0].str.strip()
                        right_vals = full_split[1].str.strip() if full_split.shape[1] > 1 else ""

                        if drop_source:
                            tmp = tmp.drop(columns=[source_col])
                            tmp.insert(source_idx,     left,  left_vals)
                            tmp.insert(source_idx + 1, right, right_vals)
                        else:
                            tmp.insert(source_idx + 1, left,  left_vals)
                            tmp.insert(source_idx + 2, right, right_vals)
                    except Exception as e:
                        err = str(e)
                        tmp = None

                if err:
                    st.error(f"❌ **Split Error:** {err}")
                else:
                    mismatch_note = (
                        f"{no_match_count} rows had no '{delim}' — right-hand side will be empty for those."
                        if total_vals > 0 and no_match_count > 0 else ""
                    )
                    self.sm.commit(
                        tmp, "Split Column",
                        {
                            "column":    source_col,
                            "delimiter": delim,
                            **({"mismatch_rows": no_match_count, "mismatch_note": mismatch_note}
                               if no_match_count > 0 else {}),
                        },
                        f"✅ **Split:** '{source_col}' split into '{left}' and '{right}'."
                        + (f" ⚠️ {no_match_count:,} row(s) had no `{delim}` and got an empty right value."
                           if no_match_count > 0 else "")
                    )

        elif "Binning" in operation:
            is_q     = "Quantile" in operation
            num_cols = self.df.select_dtypes(include="number").columns.tolist()
            if not num_cols:
                st.warning("⚠️ No numeric columns for binning.")
            else:
                bc    = st.selectbox("Select Column to Bin", num_cols, key="bin_col")
                bn    = st.number_input("Number of Bins", 2, 100, 5, key="bin_n")
                bname = st.text_input("New Column Name", placeholder="e.g. category_group", key="bin_name")
                if st.button("🚀 Apply Binning", key="bin_btn", use_container_width=True):
                    name = (bname or "").strip()
                    err = tmp = None
                    if not name:
                        err = "Name is required."
                    elif name in self.df.columns:
                        err = f"'{name}' already exists."
                    else:
                        try:
                            tmp = self.df.copy()
                            if is_q:
                                tmp[name] = pd.qcut(tmp[bc], q=int(bn), duplicates="drop").astype(str)
                            else:
                                tmp[name] = pd.cut(tmp[bc], bins=int(bn)).astype(str)
                        except Exception as e:
                            err = str(e)
                            tmp = None
                    if err:
                        st.error(f"❌ **Binning Error:** {err}")
                    else:
                        self.sm.commit(
                            tmp, operation,
                            {"column": bc, "bins": int(bn), "new_column": name},
                            f"✅ **Success:** Created binned column '{name}'."
                        )


    def _render_validation_content(self):
        st.info("💡 **Tip:** Validation helps you find data that doesn't follow your rules (e.g., negative prices or invalid categories).")
        val_type = st.selectbox(
            "Validation Rule",
            ["Numeric range", "Allowed categories", "Non-null constraint"],
            key="val_type"
        )

        if val_type == "Numeric range":
            v_col = st.selectbox("Select Column", self.df.columns, key="val_col_r")
            is_numeric = pd.api.types.is_numeric_dtype(self.df[v_col])
            if not is_numeric:
                st.warning(
                    f"⚠️ **Warning:** '{v_col}' contains text or non-numeric data. "
                    "Numeric range validation is only intended for numeric columns."
                )
            c1, c2 = st.columns(2)
            with c1: v_min = st.number_input("Minimum Allowed", key="val_min", disabled=not is_numeric)
            with c2: v_max = st.number_input("Maximum Allowed", key="val_max", disabled=not is_numeric)

            if st.button("🔍 Check for Violations", key="val_rng_btn",
                         use_container_width=True, disabled=not is_numeric):
                if v_min > v_max:
                    st.error("❌ **Error:** Min cannot be greater than Max.")
                else:
                    violations = self.df[(self.df[v_col] < v_min) | (self.df[v_col] > v_max)]
                    if violations.empty:
                        st.success("✨ **Perfect!** No violations found.")
                    else:
                        st.warning(
                            f"⚠️ **{len(violations):,} violation(s) found** — "
                            f"column **'{v_col}'** has values outside the allowed range "
                            f"[{v_min} – {v_max}]."
                        )
                        show_violations(violations, "dl_r")

        elif val_type == "Allowed categories":
            v_col   = st.selectbox("Select Column", self.df.columns, key="val_col_c")
            allowed = st.text_input(
                "Allowed Values (Comma-separated)",
                placeholder="e.g. Yes, No, Maybe",
                key="val_allowed"
            )
            if st.button("🔍 Check for Violations", key="val_cat_btn", use_container_width=True):
                al = [x.strip() for x in allowed.split(",") if x.strip()]
                if not al:
                    st.warning("⚠️ Please enter at least one allowed value.")
                else:
                    violations = self.df[~self.df[v_col].astype(str).isin(al)]
                    if violations.empty:
                        st.success("✨ **Perfect!** No violations found.")
                    else:
                        found_invalid = (
                            self.df[v_col].astype(str)[~self.df[v_col].astype(str).isin(al)]
                            .value_counts().head(10)
                        )
                        invalid_list = ", ".join(
                            f"'{v}' ({c:,})" for v, c in found_invalid.items()
                        )
                        st.warning(
                            f"⚠️ **{len(violations):,} violation(s) found** in column **'{v_col}'**. "
                            f"Allowed values: {', '.join(al)}. "
                            f"Top unexpected values: {invalid_list}."
                        )
                        show_violations(violations, "dl_c")

        elif val_type == "Non-null constraint":
            v_cols = st.multiselect(
                "Select Columns that MUST have values",
                self.df.columns.tolist(),
                key="val_nn_cols"
            )
            if st.button("🔍 Check for Violations", key="val_nn_btn", use_container_width=True):
                if not v_cols:
                    st.warning("⚠️ Please select at least one column.")
                else:
                    violations = self.df[self.df[v_cols].isna().any(axis=1)]
                    if violations.empty:
                        st.success("✨ **Perfect!** No null values found in these columns.")
                    else:
                        null_summary = {
                            c: int(self.df[c].isna().sum()) for c in v_cols if self.df[c].isna().any()
                        }
                        summary_str = ", ".join(f"'{c}': {n:,}" for c, n in null_summary.items())
                        st.warning(
                            f"⚠️ **{len(violations):,} row(s) have at least one null** in the selected columns. "
                            f"Missing counts: {summary_str}."
                        )
                        show_violations(violations, "dl_n")


    def _render_metrics(self):
        df_cur  = self.df
        df_orig = self.sm.history[0] if self.sm.history else df_cur

        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("📊 Data Status")
            if df_cur is not None:
                m1, m2, m3 = st.columns(3)
                orig_r = df_orig.shape[0] if df_orig is not None else df_cur.shape[0]
                orig_c = df_orig.shape[1] if df_orig is not None else df_cur.shape[1]

                m1.metric("Total Rows",    f"{df_cur.shape[0]:,}",
                          delta=f"{df_cur.shape[0]-orig_r:+,}" if df_cur.shape[0] != orig_r else None)
                m2.metric("Total Columns", df_cur.shape[1],
                          delta=f"{df_cur.shape[1]-orig_c:+}"  if df_cur.shape[1] != orig_c else None)

                total_miss, _ = build_missing_summary(df_cur)
                m3.metric("Missing Values", f"{total_miss:,}")

                with st.expander("👁️ View Current Data (First 10 rows)"):
                    st.dataframe(df_cur.head(10), use_container_width=True)
            else:
                st.info("No data loaded")

        with col2:
            st.subheader("🔄 History")
            b1, b2 = st.columns(2)
            if b1.button("↩ Undo",   use_container_width=True):
                self.sm.undo()
                st.rerun()
            if b2.button("⟳ Reset",  use_container_width=True):
                self.sm.reset()
                st.rerun()

            if self.sm.logs:
                for entry in list(reversed(self.sm.logs))[:5]:
                    st.markdown(
                        f"**{entry['action']}**  \n<small>{entry['timestamp']}</small>",
                        unsafe_allow_html=True
                    )
                if len(self.sm.logs) > 5:
                    st.caption(f"... and {len(self.sm.logs)-5} more steps")
            else:
                st.caption("No steps yet.")
