from __future__ import annotations

import os
import uuid
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
import plotly.graph_objects as go

from app.logging_utils import configure_logging
from app.messages import (
    CLARIFICATION_ACK_PREFIX,
    CLARIFY_REQUEST_MESSAGE,
    DONE_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    VIZ_FOLLOWUP_MESSAGE,
)
from app.pipeline.langgraph_flow import invoke_graph_pipeline

load_dotenv()


def _msg_id(m: dict) -> str:
    return str(m.get("id") or "noid")


def render_plotly(viz: dict, key: str):
    """Render Plotly dict produced by the pipeline."""
    if not viz or viz.get("type") != "plotly":
        return
    fig_dict = viz.get("figure", {})
    try:
        fig = go.Figure(fig_dict)
        st.plotly_chart(fig, use_container_width=True, key=key)
    except Exception as e:
        st.warning("Could not render Plotly figure: {}: {}".format(type(e).__name__, e))


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
            key="dl_{}".format(mid),
        )

    # Viz
    if m.get("viz"):
        render_plotly(m["viz"], key="plt_{}".format(mid))

    # Debug
    if show_debug and m.get("debug"):
        with st.expander("Debug"):
            st.json(m["debug"])


def main():
    configure_logging()
    st.set_page_config(page_title="StatApp SQL Chatbot", layout="wide")
    st.title("StatApp: SQL Chatbot")

    # Sidebar
    st.sidebar.header("Settings")
    db_path = st.sidebar.text_input(
        "SQLite DB path",
        value=os.getenv("SQLITE_PATH", "data/statapp.sqlite"),
    )
    show_debug = st.sidebar.checkbox("Show debug", value=True)

    # Session init
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())

    # Sidebar actions
    if st.sidebar.button("Clear chat"):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4())  # new thread = fresh memory
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

    result, prior = invoke_graph_pipeline(
        db_path=db_path,
        question=user_q,
        thread_id=st.session_state.thread_id,
    )

    route = result.get("route", "")

    # Decide assistant text
    resolved = result.get("resolved_intent", "")
    if route == "CLARIFY":
        qs = result.get("clarifying_questions", [])
        assistant_text = qs[0] if qs else result.get("answer_text", CLARIFY_REQUEST_MESSAGE)
    elif route == "VIZ_FOLLOWUP":
        assistant_text = VIZ_FOLLOWUP_MESSAGE
    elif route in ("OUT_OF_SCOPE", "CHAT", "VIZ_NO_DATA"):
        assistant_text = result.get("answer_text", "")
    elif route == "ERROR" or result.get("error"):
        assistant_text = result.get("answer_text", result.get("error", GENERIC_ERROR_MESSAGE))
    else:
        assistant_text = result.get("answer_text", DONE_MESSAGE)

    # Acknowledge clarification follow-ups
    if resolved == "clarification_merged" and route not in ("CLARIFY", "ERROR", "OUT_OF_SCOPE"):
        assistant_text = CLARIFICATION_ACK_PREFIX + assistant_text

    # Build assistant message — only attach data payload for routes that
    # actually produced/used query results; otherwise stale state leaks through.
    show_data = route in ("DATA", "VIZ_FOLLOWUP")
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": assistant_text,
        "sql": result.get("sql") if show_data else None,
        "columns": result.get("columns") if show_data else None,
        "rows": result.get("rows") if show_data else None,
        "viz": result.get("viz") if show_data else None,
    }

    if show_debug:
        assistant_msg["debug"] = {
            "route": route,
            "resolved_intent": result.get("resolved_intent"),
            "status": result.get("status"),
            "row_count": len(result.get("rows") or []),
            "thread_id": st.session_state.thread_id,
            "prior_route": prior.get("route", ""),
            "prior_question": prior.get("question", ""),
        }

    # Render assistant
    with st.chat_message("assistant"):
        st.markdown(assistant_text)
        render_assistant_payload(assistant_msg, show_debug=show_debug)

    # Save assistant to history
    st.session_state.messages.append(assistant_msg)


if __name__ == "__main__":
    main()
