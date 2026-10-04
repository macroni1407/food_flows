"""💬 Review search page: filters + agent.reviews.search_reviews (also used by the Agent) + an LLM answer."""
import datetime as dt
import json

import pandas as pd
import streamlit as st

from agent import agent_logs, context, llm, prompts, reviews, settings

st.title("💬 Chat with reviews")
st.caption(f"Filters narrow the reviews first, then {settings.EMBEDDING_MODEL} ranks the distinct review texts "
           f"by meaning; {settings.ANSWER_MODEL} answers from them.")

try:
    ctx = context.get_context()
except Exception as error:
    st.error(f"Could not load data context from Snowflake: {error}")
    st.stop()

with st.sidebar:
    st.header("Filters")
    city = st.selectbox("City", ["All cities"] + ctx.cities)
    use_dates = st.checkbox("Filter by review date")
    date_range = None
    if use_dates:
        latest = dt.date.fromisoformat(ctx.latest_review_date)
        date_range = st.date_input("Review dates", (latest - dt.timedelta(days=6), latest))
    sentiment = st.selectbox("Stars", ["Any", "negative (1-2★)", "neutral (3★)", "positive (4-5★)"])
    use_rating = st.checkbox("Only restaurants rated at most…")
    max_rating = st.slider("Restaurant rating", 1.0, 5.0, 3.5, 0.1) if use_rating else None
    k = st.slider("Distinct review texts", 3, 10, 5)
    st.info("Questions about **counts or trends** (e.g. most common complaint) are answered better by "
            "Text-to-SQL or the **Agent**.")

question = st.text_input("Ask a question about the reviews",
                         placeholder="e.g. What do customers complain about?")

if question:
    args = {"query": question, "k": k}
    if city != "All cities":
        args["city"] = city
    if date_range and len(date_range) == 2:
        args["date_from"], args["date_to"] = date_range
    if sentiment != "Any":
        args["sentiment"] = sentiment.split(" ")[0]
    if max_rating is not None:
        args["max_restaurant_rating"] = max_rating

    with st.spinner("Searching reviews..."):
        found = reviews.search_reviews(**args)
    answer = None
    if not found.get("error") and found.get("results"):
        with st.spinner("Writing the answer..."):
            payload = json.dumps({"question": question, "filters": found["filters"],
                                  "matching_reviews": found["matching_reviews"], "texts": found["results"]},
                                 default=str)
            answer = llm.chat_text(prompts.REVIEW_ANSWER_SYSTEM, payload)
    agent_logs.write("rag_chat", question, answer=answer, tool_calls=1, error=found.get("error"),
                     trace=[{"tool": "search_reviews", "args": args, "result": found}])

    if found.get("error"):
        st.error(found["error"])
    else:
        st.caption(f"{found['matching_reviews']:,} reviews match the filters {found['filters'] or ''}")
        if found.get("note"):
            st.warning(found["note"])
        if answer:
            st.markdown("### Answer")
            st.write(answer)
        if found["results"]:
            st.markdown("### Review texts used")
            st.dataframe(pd.DataFrame([{"text": r["text"], "reviews": r["reviews"], "similarity": r["similarity"]}
                                       for r in found["results"]]), hide_index=True)
            with st.expander("Example reviews with restaurant and order context"):
                st.dataframe(pd.DataFrame([{"text": r["text"], **e} for r in found["results"] for e in r["examples"]]),
                             hide_index=True)
