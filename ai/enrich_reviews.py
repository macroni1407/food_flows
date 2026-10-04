import json
import os

import snowflake.connector
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

MODEL = "openai/gpt-oss-120b"

SAMPLE_N = int(os.environ.get("SAMPLE_N", "5"))
TOPICS = ["food quality", "delivery", "pricing", "service", "packaging", "other"]
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = f"""
You classify customer reviews for a food delivery app.

For the review you given, return:
- sentiment_label: positive, negative, or neutral
- sentiment_score: a number between -1.0 and 1.0
- topic: one of {TOPICS}
- key_issue: a short phrase of 6 words or less that describes the main issue in the review, if any. If there is no issue, return null

Reply as JSON in this exact format:
{{
  "sentiment_label": "<sentiment_label>",
  "sentiment_score": <sentiment_score>,
  "topic": "<topic>",
  "key_issue": "<key_issue>"
}}
"""

def get_connection():
    return snowflake.connector.connect(
        user=os.environ.get("SNOWFLAKE_USER"),
        password=os.environ.get("SNOWFLAKE_PASSWORD"),
        account=os.environ.get("SNOWFLAKE_ACCOUNT"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "ZOMATO_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "ZOMATO"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA"),
        role=os.environ.get("SNOWFLAKE_ROLE", "DBT_ROLE"),
    )

def create_output_table(cursor):
    cursor.execute("CREATE SCHEMA IF NOT EXISTS ZOMATO.AI")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ZOMATO.AI.REVIEW_ENRICHED (
            REVIEW_ID NUMBER,
            SENTIMENT_LABEL STRING,
            SENTIMENT_SCORE FLOAT,
            TOPIC STRING,
            KEY_ISSUE STRING,
            MODEL STRING,
            ENRICHMENT_AT TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)

def get_reviews_to_enrich(cursor):
    cursor.execute(f"""
        SELECT r.REVIEW_ID, r.COMMENT
        FROM ZOMATO.STAGING.STG_REVIEWS r
        WHERE NOT EXISTS (
            SELECT 1 FROM ZOMATO.AI.REVIEW_ENRICHED e WHERE e.REVIEW_ID = r.REVIEW_ID
        )
        LIMIT {SAMPLE_N}
    """)
    return cursor.fetchall()

def classify_review(comment):
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": comment}
        ]
    )
    answer = response.choices[0].message.content
    return json.loads(answer)

def save_results(cursor, results):
    """Insert all the enriched rows into Snowflake in one go."""
    print(f"Saving {len(results)} enriched reviews to Snowflake...")
    cursor.executemany(
        """
        INSERT INTO ZOMATO.AI.REVIEW_ENRICHED (
            REVIEW_ID, SENTIMENT_LABEL, SENTIMENT_SCORE, TOPIC, KEY_ISSUE, MODEL
        ) VALUES (%(review_id)s, %(sentiment_label)s, %(sentiment_score)s, %(topic)s, %(key_issue)s, %(model)s)
        """,
        results
    )

def main():
    conn = get_connection()
    cursor = conn.cursor()
    create_output_table(cursor)
    reviews = get_reviews_to_enrich(cursor)
    
    if not reviews:
        print("No new reviews to enrich.")
        return

    print(f"Enriching {len(reviews)} reviews...")

    results = []
    for review_id, comment in reviews:
        print(f"Classifying review {review_id}: {comment}")
        try:
            labels = classify_review(comment)
            print(f"Labels for review {review_id}: {labels}")
            results.append({
                "review_id": review_id,
                "sentiment_label": labels["sentiment_label"],
                "sentiment_score": labels["sentiment_score"],
                "topic": labels["topic"],
                "key_issue": labels["key_issue"],
                "model": MODEL
            })
        except Exception as e:
            print(f"Error occurred while classifying review {review_id}: {e}")

    if results:
        save_results(cursor, results)
        conn.commit()
    else:
        print("No results to save.")

    print("Finished enriching reviews.")
    conn.commit()
    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()