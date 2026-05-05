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
from app.pipeline import invoke_graph_pipeline, run_reviewed_sql

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


def render_assistant_payload(m: dict, show_debug: bool, show_technical_details: bool, db_path: str):
    """Render assistant extras: SQL, dataframe, download, viz, debug."""
    mid = _msg_id(m)
    question = str(m.get("question") or "")

    # SQL
    if show_technical_details and m.get("sql"):
        with st.expander("Show SQL query"):
            st.code(m["sql"], language="sql")

        with st.expander("Expert SQL review"):
            st.caption("Edit the SQL, re-run it safely, and save the correction for future reuse.")
            with st.form("review_form_{}".format(mid)):
                reviewed_sql = st.text_area(
                    "Reviewed SQL",
                    value=m["sql"],
                    key="review_sql_{}".format(mid),
                    height=180,
                )
                review_user = st.text_input(
                    "Reviewer name",
                    value="expert",
                    key="review_user_{}".format(mid),
                )
                submitted = st.form_submit_button("Run reviewed SQL")

            if submitted:
                review_result = run_reviewed_sql(
                    db_path=db_path,
                    question=question,
                    generated_sql=m["sql"],
                    reviewed_sql=reviewed_sql,
                    review_user=review_user,
                )
                if review_result.get("ok"):
                    review_msg = {
                        "id": str(uuid.uuid4()),
                        "role": "assistant",
                        "content": review_result["answer_text"],
                        "question": question,
                        "sql": review_result.get("sql"),
                        "columns": review_result.get("columns"),
                        "rows": review_result.get("rows"),
                        "viz": review_result.get("viz"),
                        "reviewed_from_sql": m["sql"],
                        "review_user": review_result.get("review_user"),
                    }
                    if show_debug:
                        review_msg["debug"] = {
                            "route": review_result.get("route"),
                            "stage": review_result.get("stage"),
                            "row_count": len(review_result.get("rows") or []),
                            "correction_applied": review_result.get("correction_applied"),
                            "saved_correction": review_result.get("saved_correction"),
                            "review_user": review_result.get("review_user"),
                            "save_error": review_result.get("save_error", ""),
                        }
                    st.session_state.messages.append(review_msg)
                    st.rerun()

                st.error(review_result.get("message", GENERIC_ERROR_MESSAGE))
                if review_result.get("error"):
                    st.caption(review_result["error"])

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
    show_technical_details = st.sidebar.checkbox("Show technical details", value=False)

    # Session init
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
    if "conversation_state" not in st.session_state:
        st.session_state.conversation_state = {}
    if "chatbot_state" not in st.session_state:
        st.session_state.chatbot_state = {}
    if "last_result_object" not in st.session_state:
        st.session_state.last_result_object = {}

    # Sidebar actions
    if st.sidebar.button("Clear chat"):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4())  # new thread = fresh memory
        st.session_state.conversation_state = {}
        st.session_state.chatbot_state = {}
        st.session_state.last_result_object = {}
        st.rerun()

    if st.sidebar.checkbox("Show session history (raw)", value=False):
        st.sidebar.json(st.session_state.messages)

    # Render chat history
    for m in st.session_state.messages:
        with st.chat_message(m.get("role", "assistant")):
            st.markdown(m.get("content", ""))
            if m.get("role") == "assistant":
                render_assistant_payload(
                    m,
                    show_debug=show_debug,
                    show_technical_details=show_technical_details,
                    db_path=db_path,
                )

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
        assistant_text = result.get("answer_text", VIZ_FOLLOWUP_MESSAGE)
    elif route in ("OUT_OF_SCOPE", "CHAT", "VIZ_NO_DATA", "VIZ_UNSUPPORTED"):
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
        "question": user_q,
        "sql": result.get("sql") if show_data else None,
        "columns": result.get("columns") if show_data else None,
        "rows": result.get("rows") if show_data else None,
        "viz": result.get("viz") if show_data else None,
        "result_object": result.get("result_object"),
        "conversation_state": result.get("conversation_state"),
        "normalized_request": result.get("normalized_request"),
    }

    if show_debug:
        assistant_msg["debug"] = {
            "route": route,
            "resolved_intent": result.get("resolved_intent"),
            "status": result.get("status"),
            "row_count": len(result.get("rows") or []),
            "reused_correction": result.get("reused_correction", False),
            "sql_source": result.get("sql_source", ""),
            "thread_id": st.session_state.thread_id,
            "prior_route": prior.get("route", ""),
            "prior_question": prior.get("question", ""),
            "result_object": result.get("result_object"),
            "conversation_state": result.get("conversation_state"),
            "normalized_request": result.get("normalized_request"),
        }

    if result.get("conversation_state"):
        st.session_state.conversation_state = result["conversation_state"]
        st.session_state.chatbot_state = result["conversation_state"]
    if result.get("result_object"):
        st.session_state.last_result_object = result["result_object"]

    # Render assistant
    with st.chat_message("assistant"):
        st.markdown(assistant_text)
        render_assistant_payload(
            assistant_msg,
            show_debug=show_debug,
            show_technical_details=show_technical_details,
            db_path=db_path,
        )

    # Save assistant to history
    st.session_state.messages.append(assistant_msg)


if __name__ == "__main__":
    main()
