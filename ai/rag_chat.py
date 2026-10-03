import os
import requests
import numpy as np
import pandas as pd
import streamlit as st
import snowflake.connector
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "jina-embeddings-v5-omni-small"
CHAT_MODEL = "openai/gpt-oss-120b"

NEW_REVIEWS = 500
TOP_K = 5

CACHE_FILE = "review_embeddings.parquet"

JINA_API_KEY = os.getenv("JINA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(
    api_key=GROQ_API_KEY
)

def read_reviews_from_snowflake():
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )

    query = f"""
        SELECT
            REVIEW_ID,
            CITY,
            RATING,
            COMMENT
        FROM ZOMATO.STAGING.STG_REVIEWS
        SAMPLE ({NEW_REVIEWS} ROWS)
    """

    cursor = conn.cursor()

    try:
        df = cursor.execute(query).fetch_pandas_all()
    finally:
        cursor.close()
        conn.close()

    df.columns = [
        col.lower()
        for col in df.columns
    ]
    return df


def embed(texts, task="retrieval.query"):
    url = "https://api.jina.ai/v1/embeddings"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {JINA_API_KEY}"
    }

    data = {
        "model": EMBEDDING_MODEL,
        "task": task,
        "normalized": True,
        "input": [
            {"text": text}
            for text in texts
        ]
    }

    response = requests.post(
        url,
        headers=headers,
        json=data
    )

    response.raise_for_status()
    result = response.json()

    return [
        item["embedding"]
        for item in result["data"]
    ]


@st.cache_data()
def load_reviews():
    # If have cache -> stop
    if os.path.exists(CACHE_FILE):
        return pd.read_parquet(
            CACHE_FILE
        )

    # Load reviews from Snowflake
    df = read_reviews_from_snowflake()

    # Embed review
    df["embedding"] = embed(
        df["comment"].tolist(),
        task="retrieval.passage"
    )

    # Save embedding
    df.to_parquet(
        CACHE_FILE
    )
    return df


def cosine_similarity(vec_a, vec_b):
    return np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))

def find_similar_reviews(question, df):
    # Embed user question
    question_vector = embed(
        [question],
        task="retrieval.query"
    )[0]

    scores = []

    # Compare question với từng review
    for review_vector in df["embedding"]:
        score = cosine_similarity(
            question_vector,
            review_vector
        )
        scores.append(score)

    df = df.copy()
    df["score"] = scores

    # Select TOP_K review nearest to question
    return df.nlargest(
        TOP_K,
        "score"
    )


def ask_llm(question, top_reviews):
    context = ""

    for _, row in top_reviews.iterrows():
        context += (
            f"City: {row['city']}\n"
            f"Rating: {row['rating']} stars\n"
            f"Review: {row['comment']}\n\n"
        )

    system_prompt = """
        You are an assistant analyzing customer reviews.
        Answer ONLY using the customer reviews provided.

        Be concise and factual.

        If the provided reviews do not contain enough
        information to answer the question, say:

        "The provided reviews do not contain enough information
        to answer this question."
    """

    user_prompt = f"""
    Question:
    {question}

    Customer reviews:
    {context}
    """

    response = groq_client.chat.completions.create(
        model=CHAT_MODEL,
        temperature=0,

        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]
    )
    return response.choices[0].message.content


st.title(
    "Chat with your Zomato Reviews"
)

st.caption(
    f"Searching {NEW_REVIEWS} reviews "
    f"using {EMBEDDING_MODEL}, "
    f"answering with {CHAT_MODEL}"
)

# Load data
review_df = load_reviews()

# User question
question = st.text_input(
    "Ask a question about your reviews:",
    placeholder=(
        "e.g. What are the most common "
        "complaints about delivery?"
    )
)


if question:
    top_reviews = find_similar_reviews(
        question,
        review_df
    )

    answer = ask_llm(
        question,
        top_reviews
    )

    st.markdown("### Answer")
    st.write(answer)

    with st.expander(
        "Reviews used to build this answer"
    ):
        st.dataframe(
            top_reviews[
                [
                    "city",
                    "rating",
                    "comment",
                    "score"
                ]
            ],
            hide_index=True
        )

