import streamlit as st
import pandas as pd
import json
import io
from datetime import datetime
from modules.session_manager import SessionManager
from modules.ui_components import show_toast, build_log_summary
from modules.replay_generator import generate_replay_script


class ExportReport:
    def __init__(self, sm: SessionManager):
        self.sm = sm

    def render(self):
        show_toast()
        st.header("Export & Report")
        st.write("Package the cleaned dataset, the workflow recipe, and the reproducible code from one workspace.")

        df      = self.sm.df
        df_orig = self.sm.history[0] if self.sm.history else df

        st.subheader("Final Metrics")
        fr  = df.shape[0]      if df      is not None else 0
        fc  = df.shape[1]      if df      is not None else 0
        or_ = df_orig.shape[0] if df_orig is not None else 0
        oc  = df_orig.shape[1] if df_orig is not None else 0
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: st.metric("Final Rows",               f"{fr:,}",                    delta=fr - or_)
        with c2: st.metric("Final Columns",             fc,                           delta=fc - oc)
        with c3: st.metric("Transformations Applied",  self.sm.transformation_count)
        with c4: st.metric("Validation Violations",    self.sm.validation_violations)
        with c5: st.metric("Last Change",
                            self.sm.logs[-1]["timestamp"] if self.sm.logs else "—")

        recipe = None
        if self.sm.logs:
            source_meta = self.sm.state.get("source_metadata") or {}
            recipe = {
                "version":    "1.0",
                "created_at": datetime.now().isoformat(),
                "source":     source_meta,
                "steps":      self.sm.logs,
                "final": {
                    "rows":    int(df.shape[0])  if df is not None else 0,
                    "columns": int(df.shape[1])  if df is not None else 0,
                    "schema":  {col: str(dtype) for col, dtype in df.dtypes.items()} if df is not None else {},
                },
            }

        st.divider()

        with st.container(border=True):
            st.subheader("Export Dataset")
            if df is not None:
                csv_col, xlsx_col = st.columns(2)
                with csv_col:
                    st.download_button(
                        "⬇️ Download CSV",
                        data=df.to_csv(index=False).encode("utf-8"),
                        file_name="cleaned_dataset.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                with xlsx_col:
                    try:
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine="openpyxl") as w:
                            df.to_excel(w, index=False)
                        st.download_button(
                            "⬇️ Download Excel",
                            data=buf.getvalue(),
                            file_name="cleaned_dataset.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                    except Exception as exc:
                        st.warning(
                            f"⚠️ **Excel export unavailable:** {exc}. "
                            "Use CSV download instead, or ensure `openpyxl` is installed."
                        )
            else:
                st.info("No dataset loaded")

        st.divider()

        rc_col, sc_col = st.columns(2)

        with rc_col:
            with st.container(border=True):
                st.subheader("Workflow Recipe")
                st.caption(
                    "A JSON record of every transformation step — includes source metadata, "
                    "final schema, and all step details for full reproducibility."
                )
                if recipe is not None:
                    st.download_button(
                        "⬇️ Download Recipe (.json)",
                        data=json.dumps(recipe, indent=2, default=str).encode("utf-8"),
                        file_name="workflow_recipe.json",
                        mime="application/json",
                        use_container_width=True,
                    )
                    with st.expander("👁️ Preview Recipe JSON"):
                        st.json(recipe)
                else:
                    st.info("No transformations to export")

        with sc_col:
            with st.container(border=True):
                st.subheader("Replay Script")
                st.caption(
                    "A standalone Python script that reproduces every transformation "
                    "step using pandas — run it independently on any CSV."
                )
                if self.sm.logs:
                    source_meta   = self.sm.state.get("source_metadata") or {}
                    default_fname = source_meta.get("filename", "your_file.csv")
                    source_hint   = st.text_input(
                        "Source CSV filename", value=default_fname,
                        help="Written into the script's pd.read_csv() call.",
                        key="replay_source_hint",
                    )
                    script = generate_replay_script(self.sm.logs, source_file=source_hint)

                    st.download_button(
                        "⬇️ Download .py file",
                        data=script.encode("utf-8"),
                        file_name="replay_script.py",
                        mime="text/x-python",
                        use_container_width=True,
                    )

                    if st.button("▶ Run script on current df", key="replay_run"):
                        if df is not None:
                            try:
                                local_ns: dict = {"df": df.copy(), "pd": pd}
                                safe_lines = [
                                    ln for ln in script.splitlines()
                                    if not any(kw in ln for kw in ("read_csv", "to_csv", "print("))
                                ]
                                exec("\n".join(safe_lines), local_ns)
                                result_df = local_ns["df"]
                                st.success(
                                    f"✅ Script ran successfully → "
                                    f"{result_df.shape[0]:,} rows × {result_df.shape[1]} columns"
                                )
                                st.dataframe(result_df.head(20), use_container_width=True)
                            except Exception as exc:
                                st.error(
                                    f"❌ **Script execution error:** {exc}\n\n"
                                    "This can happen if a column was already renamed or dropped "
                                    "before running the script on the current dataframe. "
                                    "Try running the script on the **original** file instead."
                                )
                        else:
                            st.warning("No dataset loaded.")

                    with st.expander("👁️ Preview script"):
                        st.code(script, language="python")
                else:
                    st.info("No transformations to generate a script for")

        st.divider()

        with st.container(border=True):
            st.subheader("Transformation Log")
            st.write(f"Steps applied: **{self.sm.transformation_count}**")
            if self.sm.logs:
                display_rows = []
                for entry in self.sm.logs:
                    details = entry.get("details") or {}
                    row = {
                        "step":      entry.get("step", ""),
                        "action":    entry.get("action", ""),
                        "timestamp": entry.get("timestamp", ""),
                    }
                    if "columns" in details:
                        row["columns"] = ", ".join(str(c) for c in details["columns"])
                    if "rows_affected" in details:
                        row["rows_affected"] = details["rows_affected"]
                    if "rows_removed"  in details:
                        row["rows_removed"]  = details["rows_removed"]
                    if "action" in details:
                        row["sub_action"] = details["action"]
                    if "method" in details:
                        row["method"] = details["method"]
                    if "type" in details:
                        row["type"] = details["type"]
                    if entry.get("before_shape"):
                        row["before"] = "×".join(str(x) for x in entry["before_shape"])
                    if entry.get("after_shape"):
                        row["after"]  = "×".join(str(x) for x in entry["after_shape"])
                    display_rows.append(row)

                st.dataframe(pd.DataFrame(display_rows), use_container_width=True)
            else:
                st.info("No transformations recorded yet")

            uc, rsc = st.columns(2)
            with uc:
                if st.button("↩ Undo Last Step", key="export_undo"):
                    self.sm.undo()
            with rsc:
                if st.button("⟳ Reset All", key="export_reset"):
                    self.sm.reset()
