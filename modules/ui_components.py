import streamlit as st
import pandas as pd

def show_toast():
    t = st.session_state.get("toast")
    if t:
        getattr(st, t["type"])(t["msg"])
        st.session_state.toast = None

def show_last_result():
    r = st.session_state.get("last_result")
    if r:
        if r.get("label"):
            st.caption(r["label"])
        if r.get("df") is not None and not r["df"].empty:
            st.dataframe(r["df"], width="stretch")
        st.session_state.last_result = None

def safe_join(cols):
    return ", ".join(str(c) for c in cols) if cols else "None"

def build_log_summary(details: dict) -> str:
    parts = []
    if details.get("columns"):
        parts.append("cols: " + ", ".join(str(c) for c in details["columns"]))
    if details.get("action"):
        parts.append(str(details["action"]))
    if details.get("rows_affected") is not None:
        parts.append(f"{details['rows_affected']} rows affected")
    if details.get("rows_removed"):
        parts.append(f"{details['rows_removed']} rows removed")
    if details.get("rows_changed"):
        parts.append(f"{details['rows_changed']} rows changed")
    if details.get("values_capped"):
        parts.append(f"{details['values_capped']} values capped")
    if details.get("mapping"):
        parts.append(f"{len(details['mapping'])} columns renamed")
    if details.get("new_column"):
        parts.append(f"new col: {details['new_column']}")
    if details.get("method"):
        parts.append(str(details["method"]))
    if details.get("type"):
        parts.append(str(details["type"]))
    return " · ".join(parts) if parts else "—"

def show_violations(vdf: pd.DataFrame, dl_key: str):
    n = len(vdf)
    st.session_state.validation_violations = n
    if n == 0:
        st.success("No violations found — all values pass the constraint")
    else:
        st.warning(f"{n} violation(s) found")
        st.dataframe(vdf.head(50), width="stretch")
        st.download_button(
            "Download violations as CSV",
            data=vdf.to_csv(index=False).encode("utf-8"),
            file_name="violations.csv",
            mime="text/csv",
            key=dl_key,
        )