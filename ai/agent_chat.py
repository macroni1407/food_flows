"""🤖 Agent page: an orchestrator that calls Text-to-SQL and review search, with a visible trace."""
import pandas as pd
import streamlit as st

from agent import agent_logs, settings

EXAMPLE_QUESTIONS = [
    "Top 10 cities by GMV",
    "What do customers in Delhi say about packaging?",
    "Why did customers in Delhi complain so much in early September 2026?",
    "Was delivery in Bangalore unusually slow on 2026-09-05, and did customers complain about it?",
]

st.title("🤖 Agent")
st.caption(f"{settings.AGENT_MODEL} decides which tools to call (Text-to-SQL, review search), in which order, "
           f"and can use one result to drive the next. Budget: {settings.AGENT_MAX_TOOL_CALLS} tool calls.")

with st.sidebar:
    st.header("Example questions")
    for q in EXAMPLE_QUESTIONS:
        st.markdown(f"- {q}")
    if st.button("Clear conversation"):
        st.session_state["agent_history"] = []


@st.cache_resource
def get_agent():
    from agent.tools import build_agent
    return build_agent()


def show_trace(trace):
    for step in trace:
        flag = " (reused)" if step.get("reused") else " (skipped: budget)" if step.get("skipped") else ""
        st.markdown(f"**{step['step']}. `{step['tool']}`**{flag} · {step.get('ms', 0)} ms")
        st.json(step["args"], expanded=False)
        result = step.get("result") or {}
        if result.get("error"):
            st.error(result["error"])
        if step["tool"] == "query_warehouse" and result.get("sql"):
            st.code(result["sql"], language="sql")
            if result.get("rows"):
                st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]), hide_index=True)
        if step["tool"] == "search_reviews" and result.get("results") is not None:
            st.caption(f"{result.get('matching_reviews', 0):,} matching reviews · filters {result.get('filters')}")
            st.dataframe(pd.DataFrame([{"text": r["text"], "reviews": r["reviews"]} for r in result["results"]]),
                         hide_index=True)


history = st.session_state.setdefault("agent_history", [])
for turn in history:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        st.write(turn["answer"])
        st.caption(turn["meta"])
        with st.expander("Steps the agent took"):
            show_trace(turn["trace"])

question = st.chat_input("Ask about orders, revenue, delivery, or what customers said…")
if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        try:
            with st.status("Agent is working…", expanded=False):
                result = get_agent()(question)
        except Exception as error:
            agent_logs.write("agent", question, error=str(error))
            st.error(f"The agent failed: {error}")
            st.stop()
        tools_used = " → ".join(step["tool"] for step in result["trace"]) or "no tools"
        meta = (f"Tools: {tools_used} · {result['tool_calls']} call(s) · {result['duration_ms'] / 1000:.1f} s"
                + (" · stopped at the budget" if result["hit_budget"] else ""))
        st.write(result["answer"])
        st.caption(meta)
        with st.expander("Steps the agent took"):
            show_trace(result["trace"])
    agent_logs.write("agent", question, answer=result["answer"], tool_calls=result["tool_calls"],
                     hit_budget=result["hit_budget"], duration_ms=result["duration_ms"], trace=result["trace"])
    history.append({"question": question, "answer": result["answer"], "trace": result["trace"], "meta": meta})
