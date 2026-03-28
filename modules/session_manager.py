import streamlit as st
import pandas as pd
import json
from datetime import datetime
import csv
import re
import io
import requests


class SessionManager:
    def __init__(self):
        self.state = st.session_state

    def init_session(self):
        defaults = {
            "open_cleaning_sections": [],
            "df": None,
            "history": [],
            "logs": [],
            "transformation_count": 0,
            "validation_violations": 0,
            "toast": None,
            "loaded_file_key": None,
            "last_result": None,
            "source_metadata": None,
            "chat_history": [],
            "chat_open": False,
        }

        for k, v in defaults.items():
            if k not in self.state:
                self.state[k] = v


    @staticmethod
    def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
        coerced = df.copy()
        for col in coerced.columns:
            try:
                coerced[col] = pd.to_numeric(coerced[col])
            except (ValueError, TypeError):
                pass
        return coerced

    def _set_loaded_data(self, loaded: pd.DataFrame, file_key: str, source_metadata: dict):
        self.state.update({
            "df": loaded,
            "history": [loaded.copy()],
            "logs": [],
            "transformation_count": 0,
            "toast": None,
            "last_result": None,
            "loaded_file_key": file_key,
            "validation_violations": 0,
            "source_metadata": source_metadata,
        })


    def load_google_sheet(self, url: str):
        id_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
        if not id_match:
            st.error(
                "Invalid Google Sheets URL. "
                "Make sure it contains '/spreadsheets/d/<ID>'."
            )
            return

        sheet_id = id_match.group(1)
        gid_match = re.search(r"[#&?]gid=(\d+)", url)
        gid = gid_match.group(1) if gid_match else "0"
        export_url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}"
            f"/export?format=csv&gid={gid}"
        )
        file_key = f"gsheet_{sheet_id}_{gid}"
        if self.state.loaded_file_key == file_key:
            return

        try:
            response = requests.get(export_url, timeout=15)
            if response.status_code == 403:
                st.error(
                    "Access denied (HTTP 403). "
                    "Make sure the sheet is shared as **Anyone with the link → Viewer**."
                )
                return
            response.raise_for_status()

            loaded = self._coerce_numeric_columns(pd.read_csv(io.StringIO(response.text)))
            source_metadata = {
                "filename": f"google_sheet_{sheet_id}_{gid}.csv",
                "file_type": "google_sheet",
                "source_url": url,
                "sheet_id": sheet_id,
                "gid": gid,
                "rows": int(loaded.shape[0]),
                "columns": int(loaded.shape[1]),
                "schema": {col: str(dtype) for col, dtype in loaded.dtypes.items()},
            }
            self._set_loaded_data(loaded, file_key, source_metadata)
            st.success(f"Successfully loaded Google Sheet (id={sheet_id}, gid={gid})")

        except requests.exceptions.ConnectionError:
            st.error("Could not reach Google Sheets. Check your internet connection.")
        except requests.exceptions.Timeout:
            st.error("Request timed out. The sheet may be too large or unreachable.")
        except Exception as e:
            st.error(f"Failed to load Google Sheet: {e}")

    def load_file(self, uploaded_file):
        file_key = f"{uploaded_file.name}_{uploaded_file.size}"
        if self.state.loaded_file_key == file_key:
            return

        try:
            if uploaded_file.name.endswith(".csv"):
                raw_data = uploaded_file.read(8192)
                uploaded_file.seek(0)

                try:
                    sample = raw_data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    sample = raw_data.decode("latin1", errors="ignore")

                try:
                    sniffer = csv.Sniffer()
                    dialect = sniffer.sniff(sample, delimiters=",;\t|")
                    delimiter = dialect.delimiter
                except Exception:
                    first_line = sample.splitlines()[0] if sample else ""
                    delims = [";", ",", "\t", "|"]
                    counts = {d: first_line.count(d) for d in delims}
                    delimiter = max(counts, key=counts.get) if any(counts.values()) else ","

                try:
                    uploaded_file.seek(0)
                    loaded = pd.read_csv(uploaded_file, sep=delimiter, encoding="utf-8-sig")
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    loaded = pd.read_csv(uploaded_file, sep=delimiter, encoding="latin1")

                st.info(f"Detected delimiter: `{delimiter}`")

            elif uploaded_file.name.endswith(".json"):
                loaded = pd.read_json(uploaded_file)
            elif uploaded_file.name.endswith((".xls", ".xlsx")):
                loaded = pd.read_excel(uploaded_file)
            else:
                st.error("Unsupported file format.")
                return

            loaded = self._coerce_numeric_columns(loaded)
            source_metadata = {
                "filename": uploaded_file.name,
                "file_type": uploaded_file.name.split(".")[-1].lower(),
                "rows": int(loaded.shape[0]),
                "columns": int(loaded.shape[1]),
                "schema": {col: str(dtype) for col, dtype in loaded.dtypes.items()},
            }
            self._set_loaded_data(loaded, file_key, source_metadata)
            st.success(f"Successfully loaded **{uploaded_file.name}**")

        except Exception as e:
            st.error(f"Failed to load file: {e}")

    def commit(self, new_df, action, details, toast_msg, result=None):
        before_shape = list(self.state.df.shape) if self.state.df is not None else None
        after_shape  = list(new_df.shape)         if new_df is not None          else None
        self._save_snapshot()
        self.state.df = new_df
        self._log_action(action, details, before_shape, after_shape)
        self.state.toast = {"type": "info", "msg": toast_msg}
        self.state.last_result = result
        self.state.validation_violations = 0
        st.rerun()

    def _save_snapshot(self):
        if self.state.df is not None:
            self.state.history.append(self.state.df.copy())

    def _log_action(self, action, details, before_shape=None, after_shape=None):
        self.state.transformation_count += 1
        self.state.logs.append({
            "step":         self.state.transformation_count,
            "action":       action,
            "details":      details,
            "before_shape": before_shape,
            "after_shape":  after_shape,
            "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    def undo(self):
        if self.state.history:
            self.state.df = self.state.history.pop()
            if self.state.logs:
                self.state.logs.pop()
            self.state.transformation_count = max(0, self.state.transformation_count - 1)
            self.state.last_result = None
            self.state.toast = {"type": "info", "msg": "Last step undone."}
            self.state.validation_violations = 0
        else:
            self.state.toast = {"type": "warning", "msg": "Nothing to undo."}
        st.rerun()

    def reset(self):
        if self.state.history:
            self.state.df = self.state.history[0].copy()
            self.state.history = []
            self.state.logs = []
            self.state.transformation_count = 0
            self.state.last_result = None
            self.state.toast = {"type": "info", "msg": "All transformations reset."}
            self.state.validation_violations = 0
        else:
            self.state.toast = {"type": "warning", "msg": "No history to reset to."}
        st.rerun()

    @property
    def df(self):
        return self.state.df

    @property
    def logs(self):
        return self.state.logs

    @property
    def history(self):
        return self.state.history

    @property
    def transformation_count(self):
        return self.state.transformation_count

    @property
    def validation_violations(self):
        return self.state.validation_violations

    @property
    def source_metadata(self):
        return self.state.get("source_metadata")
