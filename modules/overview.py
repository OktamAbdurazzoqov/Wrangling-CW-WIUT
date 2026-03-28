import streamlit as st
from modules.session_manager import SessionManager
from modules.data_utils import detect_datetime_cols, build_missing_summary, count_duplicates
from modules.ui_components import safe_join

class Overview:
    def __init__(self, sm: SessionManager):
        self.sm = sm

    def render(self):
        df = self.sm.df
        st.header("Dataset Overview")
        st.write("Review the structure, quality, and meaning of the current dataset in one place.")

        if df is not None:
            rows, cols = df.shape
            column_names = df.columns.tolist()
            numeric_cols = [c for c in df.select_dtypes(include="number").columns if df[c].notna().any()]
            cat_cols_raw = df.select_dtypes(include=["object", "category"]).columns.tolist()
            datetime_columns = detect_datetime_cols(df)
            categorical_cols = [c for c in cat_cols_raw if c not in datetime_columns]
            total_missing, missing_summary_df = build_missing_summary(df)
            dup_count = count_duplicates(df, None, "first")
            structure_df = df.dtypes.astype(str).rename("dtype").reset_index().rename(columns={"index": "column"})
            structure_df["missing"] = structure_df["column"].map(lambda col: int(df[col].isna().sum()))
            structure_df["unique"] = structure_df["column"].map(lambda col: int(df[col].nunique(dropna=True)))
        else:
            rows = cols = 0
            column_names = numeric_cols = categorical_cols = datetime_columns = []
            total_missing = dup_count = 0
            missing_summary_df = structure_df = None

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: st.metric("Rows", f"{rows:,}")
        with c2: st.metric("Columns", cols)
        with c3: st.metric("Numeric", len(numeric_cols))
        with c4: st.metric("Categorical", len(categorical_cols))
        with c5: st.metric("Datetime", len(datetime_columns))

        st.divider()
        left_col, right_col = st.columns([1.2, 0.8])

        with left_col:
            with st.container(border=True):
                st.subheader("Dataset Structure")
                if df is not None:
                    st.caption("Column types, missing values, and uniqueness.")
                    st.dataframe(structure_df, use_container_width=True)
                    st.write(f"Columns: {safe_join(column_names)}")
                else:
                    st.info("No dataset loaded")

            with st.container(border=True):
                st.subheader("Quality Checks")
                if df is not None:
                    qc1, qc2 = st.columns(2)
                    with qc1:
                        st.metric("Missing Values", f"{total_missing:,}")
                        if missing_summary_df.empty:
                            st.success("No missing values found")
                        else:
                            st.dataframe(missing_summary_df, use_container_width=True)
                    with qc2:
                        st.metric("Duplicate Rows", f"{dup_count:,}")
                        if dup_count > 0:
                            if st.button("Remove Duplicates", key="overview_remove_dup", use_container_width=True):
                                new_df = df.drop_duplicates()
                                self.sm.commit(
                                    new_df,
                                    "Remove Duplicates",
                                    {"rows_removed": len(df) - len(new_df)},
                                    f"Removed {len(df) - len(new_df)} duplicate rows",
                                )
                        else:
                            st.success("No duplicate rows found")
                else:
                    st.info("No dataset loaded")

        with right_col:
            with st.container(border=True):
                st.subheader("Column Groups")
                if df is not None:
                    st.write(f"Numeric ({len(numeric_cols)}): {safe_join(numeric_cols)}")
                    st.write(f"Categorical ({len(categorical_cols)}): {safe_join(categorical_cols)}")
                    st.write(f"Datetime ({len(datetime_columns)}): {safe_join(datetime_columns)}")
                else:
                    st.info("No dataset loaded")
            with st.container(border=True):
                st.subheader("Data Preview")
                if df is not None:
                    st.dataframe(df.head(10), use_container_width=True)
                else:
                    st.info("No dataset loaded")
            with st.container(border=True):
                st.subheader("Readiness")
                if df is not None:
                    st.metric("Rows", f"{rows:,}")
                    st.metric("Columns with Missing", 0 if missing_summary_df.empty else len(missing_summary_df))
                    st.metric("Duplicate Rows", dup_count)
                else:
                    st.info("No dataset loaded")
