"""
Embed review texts that have no embedding yet into ZOMATO.AI.REVIEW_EMBEDDINGS (DAG task).

Reviews are built from a small set of sentences, so 300K+ reviews have only a few hundred distinct
texts: one vector per distinct text (comment_hash), shared by every review with that text.
Idempotent: texts already embedded are skipped, so a re-run embeds nothing.

    python ai/embed_reviews.py
"""
import json
import os

from agent import db, embeddings, settings

TABLE = "ZOMATO.AI.REVIEW_EMBEDDINGS"
MAX_TEXTS_PER_RUN = int(os.environ.get("EMBED_MAX_TEXTS", "5000"))   # safety cap on Jina calls


def table_exists():
    _, rows = db.query(
        "select count(*) from ZOMATO.INFORMATION_SCHEMA.TABLES "
        "where table_schema = 'AI' and table_name = 'REVIEW_EMBEDDINGS'",
        role=settings.WRITE_ROLE,
    )
    return rows[0][0] > 0


def texts_to_embed(exists):
    missing = (f"where not exists (select 1 from {TABLE} e where e.comment_hash = r.comment_hash)"
               if exists else "")
    _, rows = db.query(
        f"""select comment_hash, any_value(comment) from ZOMATO.STAGING.STG_REVIEWS r
            {missing} group by comment_hash limit {MAX_TEXTS_PER_RUN}""",
        role=settings.WRITE_ROLE,
    )
    return rows


def main():
    exists = table_exists()
    rows = texts_to_embed(exists)
    if not rows:
        print("No new review texts to embed.")
        return
    print(f"Embedding {len(rows)} distinct review texts with {settings.EMBEDDING_MODEL} ...")
    vectors = embeddings.embed([comment for _, comment in rows], task="retrieval.passage")
    dim = len(vectors[0])

    db.execute(f"""
        create table if not exists {TABLE} (
            comment_hash string, comment string, embedding vector(float, {dim}),
            model string, embedded_at timestamp_ltz default current_timestamp())
    """)
    # VECTOR values cannot be bound directly: load JSON strings into a temp table, then cast.
    db.execute("create or replace temporary table ZOMATO.AI.TMP_REVIEW_EMBEDDINGS (comment_hash string, comment string, v string)")
    db.execute(
        "insert into ZOMATO.AI.TMP_REVIEW_EMBEDDINGS (comment_hash, comment, v) values (%s, %s, %s)",
        [(h, c, json.dumps(v)) for (h, c), v in zip(rows, vectors)],
        many=True,
    )
    db.execute(f"""
        insert into {TABLE} (comment_hash, comment, embedding, model)
        select t.comment_hash, t.comment, parse_json(t.v)::array::vector(float, {dim}), %(model)s
        from ZOMATO.AI.TMP_REVIEW_EMBEDDINGS t
        where not exists (select 1 from {TABLE} e where e.comment_hash = t.comment_hash)
    """, {"model": settings.EMBEDDING_MODEL})
    print(f"Saved {len(rows)} embeddings (dimension {dim}).")


if __name__ == "__main__":
    main()
