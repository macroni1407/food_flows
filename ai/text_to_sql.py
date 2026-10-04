"""📊 Text-to-SQL page: a thin UI over agent.warehouse.query_warehouse (also used by the Agent)."""
import pandas as pd
import streamlit as st

from agent import agent_logs, settings, warehouse

EXAMPLE_QUESTIONS = [
    "Top 10 cities by GMV",
    "Which cuisine has the most orders?",
    "Average delivery time by city, worst first",
    "Cancel rate by payment method",
    "Share of 1-2 star reviews by day in Delhi in September 2026",
]

st.title("📊 Text-to-SQL")
st.caption(f"{settings.SQL_MODEL} writes Snowflake SQL from the dbt schema; a guard checks it and it runs "
           f"under the read-only role {settings.READ_ROLE}.")

with st.sidebar:
    st.header("Example questions")
    for q in EXAMPLE_QUESTIONS:
        st.markdown(f"- {q}")
    st.info("Need numbers **and** what customers said? Try the **Agent** page.")

question = st.text_input("Ask a question about the data",
                         placeholder="e.g. Top 10 restaurants by revenue in Bangalore")

if question:
    with st.spinner("Writing and running SQL..."):
        result = warehouse.query_warehouse(question)
    agent_logs.write("text_to_sql", question, tool_calls=1, error=result["error"],
                     trace=[{"tool": "query_warehouse", "result": warehouse.for_llm(result)}])

    if result["sql"]:
        st.code(result["sql"], language="sql")
    if result["error"]:
        st.error(result["error"])
    else:
        df = pd.DataFrame(result["rows"], columns=result["columns"])
        st.success(f"{result['row_count']} rows returned")
        for note in result["notes"]:
            st.info(note)
        st.dataframe(df, hide_index=True)
        if len(df.columns) == 2 and pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
            st.bar_chart(df, x=df.columns[0], y=df.columns[1])
