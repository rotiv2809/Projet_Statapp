from __future__ import annotations

import os
import uuid
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
import plotly.graph_objects as go

from app.pipeline.data_pipeline import run_data_pipeline as run_pipeline

load_dotenv()
def _msg_id(m: dict) -> str:
    return str(m.get("id") or "noid")


def render_plotly(viz: dict, key: str):
    """Render Plotly dict produced by your pipeline"""
    if not viz or viz.get("type") != "plotly":
        return
    fig_dict = viz.get("figure", {})
    try:
        fig = go.Figure(fig_dict)
        st.plotly_chart(fig, use_container_width=True, key=key)
    except Exception as e:
        st.warning(f"Could not render Plotly figure: {type(e).__name__}: {e}")


def render_assistant_payload(m: dict, show_debug: bool):
    """Render assistant extras: SQL, dataframe, download, viz, debug."""
    mid = _msg_id(m)

    # SQL
    if m.get("sql"):
        with st.expander("Show SQL query"):
            st.code(m["sql"], language="sql")

    # Data table
    cols = m.get("columns")
    rows = m.get("rows")
    if cols is not None and rows is not None:
        df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
        st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            data=csv,
            file_name="result.csv",
            mime="text/csv",
            key=f"dl_{mid}",
        )

    # Viz
    if m.get("viz"):
        render_plotly(m["viz"], key=f"plt_{mid}")

    # Debug
    if show_debug and m.get("debug"):
        with st.expander("Debug"):
            st.json(m["debug"])


def main():
    st.set_page_config(page_title="StatApp SQL Chatbot", layout="wide")
    st.title("StatApp: SQL Chatbot")

    # Sidebar
    st.sidebar.header("Settings")
    db_path = st.sidebar.text_input(
        "SQLite DB path",
        value=os.getenv("SQLITE_PATH", "data/statapp.sqlite"),
    )
    show_debug = st.sidebar.checkbox("Show debug", value=True)

    # Session history init
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Sidebar actions
    if st.sidebar.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()

    if st.sidebar.checkbox("Show session history (raw)", value=False):
        st.sidebar.json(st.session_state.messages)

    # Render chat history
    for m in st.session_state.messages:
        with st.chat_message(m.get("role", "assistant")):
            st.markdown(m.get("content", ""))

            if m.get("role") == "assistant":
                render_assistant_payload(m, show_debug=show_debug)

    # User input
    user_q = st.chat_input("Ask about your data...")
    if not user_q:
        return

    # Append and show user message
    user_msg = {"id": str(uuid.uuid4()), "role": "user", "content": user_q}
    st.session_state.messages.append(user_msg)
    with st.chat_message("user"):
        st.markdown(user_q)

    # Run pipeline
    try:
        res = run_pipeline(db_path, user_q)
        if res is None:
            res = {"ok": False, "route": "ERROR", "message": "Pipeline returned None."}
    except Exception as e:
        res = {"ok": False, "route": "ERROR", "message": f"Pipeline error: {type(e).__name__}: {e}"}

    route = res.get("route")
    ok = res.get("ok", True)

    # Decide assistant text
    if ok is False and route == "REFUSE":
        assistant_text = res.get("message") or "Refused: unsafe or destructive request."
    elif ok is False and route == "CLARIFY":
        assistant_text = res.get("question") or res.get("message") or "I need clarification."
    elif route in ("CHAT", "OUT_OF_SCOPE"):
        assistant_text = res.get("message") or "Out of scope."
    elif route == "ERROR":
        assistant_text = res.get("message") or "Error."
    else:
        assistant_text = res.get("answer_text") or res.get("message") or "Done."

    # Build assistant message
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": assistant_text,
        "sql": res.get("sql"),
        "columns": res.get("columns"),
        "rows": res.get("rows"),
        "viz": res.get("viz"),
    }

    if show_debug:
        assistant_msg["debug"] = {
            "route": route,
            "stage": res.get("stage"),
            "ok": ok,
            "row_count": res.get("row_count"),
        }

    # Render assistant 
    with st.chat_message("assistant"):
        st.markdown(assistant_text)
        render_assistant_payload(assistant_msg, show_debug=show_debug)

    # Save assistant to history
    st.session_state.messages.append(assistant_msg)


if __name__ == "__main__":
    main()