import streamlit as st
from modules.session_manager import SessionManager
from modules.overview import Overview
from modules.cleaning import CleaningStudio
from modules.visualization import Visualization
from modules.export_report import ExportReport
from modules.ai_assistant import AIAssistant

st.set_page_config(layout="wide")

sm = SessionManager()
sm.init_session()

with st.sidebar:
    _, main_col, _ = st.columns([0.5, 2, 0.5])
    with main_col:
        st.header("File Upload")
        uploaded_file = st.file_uploader(
            "Upload file",
            type=["csv", "xlsx", "xlsm", "xlsb", "xltx", "xltm", "xls", "json"],
        )
        if uploaded_file:
            sm.load_file(uploaded_file)

        st.divider()
        st.write("**Google Sheets**")
        gsheet_url = st.text_input(
            "Paste sheet URL",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            label_visibility="collapsed",
        )
        if st.button("Load Google Sheet", width="stretch", disabled=not gsheet_url):
            sm.load_google_sheet(gsheet_url)

        st.divider()
        st.write("**Workflow**")
        if st.button("Undo Last Step", width="stretch"):
            sm.undo()
        if st.button("Reset Session", width="stretch"):
            sm.reset()

        st.divider()
        st.write("**Logs**")
        if sm.logs:
            for entry in reversed(sm.logs[-5:]):
                st.caption(f"[{entry['timestamp']}] {entry['action']}")
        else:
            st.caption("No transformations yet")

tabs = st.tabs(["Overview", "Cleaning Studio", "Visualization", "Export & Report"])

with tabs[0]:
    Overview(sm).render()

with tabs[1]:
    CleaningStudio(sm).render()

with tabs[2]:
    Visualization(sm).render()

with tabs[3]:
    ExportReport(sm).render()

AIAssistant(sm).render()
