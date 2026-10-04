"""
Streamlit entry point with three pages that share the same code (ai/agent/):

    streamlit run ai/app.py      (or: make app)
"""
import streamlit as st

st.set_page_config(page_title="Food Flows AI", page_icon="🍽️", layout="wide")

st.navigation([
    st.Page("text_to_sql.py", title="Text-to-SQL", icon="📊", default=True),
    st.Page("rag_chat.py", title="Chat with reviews", icon="💬"),
    st.Page("agent_chat.py", title="Agent", icon="🤖"),
]).run()
