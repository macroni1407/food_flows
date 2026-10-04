"""
search_reviews: filter first with SQL, then rank by meaning, in one fixed query.

1. filter MARTS.MART_REVIEW_SEARCH by city / dates / stars / restaurant rating / topic
2. group the filtered reviews by text (comment_hash) and count them
3. cosine similarity between the question and each distinct text (AI.REVIEW_EMBEDDINGS, small)
4. keep the top k texts, each with its review count and up to 2 example reviews with context

The LLM never writes SQL here: it only fills the arguments, which are validated by Pydantic and
passed to Snowflake as bind parameters.
"""
import datetime as dt
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import db, embeddings

SEARCH_TABLE = "ZOMATO.MARTS.MART_REVIEW_SEARCH"
EMBEDDING_TABLE = "ZOMATO.AI.REVIEW_EMBEDDINGS"
EXAMPLES_PER_TEXT = 2

DEFAULT_QUERY = "what customers say about their order"

# Star ratings behind each sentiment (available for every review, unlike LLM labels)
SENTIMENT_STARS = {"negative": (1, 2), "neutral": (3, 3), "positive": (4, 5)}


class ReviewSearchArgs(BaseModel):
    # Not required on purpose: Groq rejects a whole tool call server-side when a required field is
    # missing (seen in practice: the model sent only filters). An empty query falls back to a generic one.
    query: str = Field("", description="What to look for, in natural language, e.g. 'late delivery' or "
                                       "'food spilled'. Always fill it in when you can.")
    city: Optional[str] = Field(None, description="City of the reviewed restaurant, e.g. 'Delhi'.")
    date_from: Optional[dt.date] = Field(None, description="First review date to include (YYYY-MM-DD).")
    date_to: Optional[dt.date] = Field(None, description="Last review date to include (YYYY-MM-DD).")
    sentiment: Optional[Literal["negative", "neutral", "positive"]] = Field(
        None, description="Based on stars: negative = 1-2, neutral = 3, positive = 4-5.")
    topic: Optional[Literal["food quality", "delivery", "pricing", "service", "packaging", "other"]] = Field(
        None, description="LLM topic label. Most reviews have no label yet, so this filter drops many reviews.")
    max_restaurant_rating: Optional[float] = Field(
        None, ge=0, le=5, description="Only restaurants rated at most this on the review date.")
    k: int = Field(5, ge=1, le=10, description="How many distinct review texts to return.")


def build_filters(args):
    """WHERE conditions and bind parameters. Column names are fixed here, values are bound."""
    conditions, params = [], {}
    if args.city:
        conditions.append("lower(city) = lower(%(city)s)")
        params["city"] = args.city
    if args.date_from:
        conditions.append("review_date >= %(date_from)s")
        params["date_from"] = args.date_from
    if args.date_to:
        conditions.append("review_date <= %(date_to)s")
        params["date_to"] = args.date_to
    if args.sentiment:
        low, high = SENTIMENT_STARS[args.sentiment]
        conditions.append("rating between %(stars_low)s and %(stars_high)s")
        params.update(stars_low=low, stars_high=high)
    if args.topic:
        conditions.append("topic = %(topic)s")
        params["topic"] = args.topic
    if args.max_restaurant_rating is not None:
        conditions.append("restaurant_rating_at_review <= %(max_rating)s")
        params["max_rating"] = args.max_restaurant_rating
    where = " and ".join(conditions) if conditions else "1 = 1"
    return where, params


def filters_applied(args):
    return {k: (v.isoformat() if isinstance(v, dt.date) else v)
            for k, v in args.model_dump(exclude={"query", "k"}).items() if v is not None}


def search_reviews(**kwargs):
    """Returns a dict: filters, matching_reviews, results [{text, reviews, similarity, examples}], note, error."""
    try:
        args = ReviewSearchArgs(**kwargs)
    except Exception as error:
        return {"error": f"invalid arguments: {error}"}

    if not args.query.strip():
        args.query = DEFAULT_QUERY
    where, params = build_filters(args)
    out = {"query": args.query, "filters": filters_applied(args), "matching_reviews": 0, "results": [],
           "note": None, "error": None}
    try:
        _, rows = db.query(f"select count(*) from {SEARCH_TABLE} where {where}", params)
        out["matching_reviews"] = rows[0][0]
        if out["matching_reviews"] == 0:
            out["note"] = "0 reviews match these filters; try a wider date range or fewer filters"
            return out

        vector = embeddings.embed([args.query], task="retrieval.query")[0]
        dim = len(vector)
        sql = f"""
            with filtered as (
                select * from {SEARCH_TABLE} where {where}
            ),
            texts as (
                select comment_hash, any_value(comment) as comment, count(*) as n_reviews
                from filtered group by comment_hash
            ),
            scored as (
                select t.comment_hash, t.comment, t.n_reviews,
                       vector_cosine_similarity(e.embedding, parse_json(%(qvec)s)::array::vector(float, {dim})) as similarity
                from texts t
                join {EMBEDDING_TABLE} e on e.comment_hash = t.comment_hash
                order by similarity desc
                limit {int(args.k)}
            )
            select s.comment_hash, s.comment, s.n_reviews, s.similarity,
                   f.review_id, f.review_date, f.city, f.rating, f.restaurant_name, f.cuisine,
                   f.restaurant_rating_at_review, f.cost_for_two_at_review,
                   f.order_id, f.sales_amount, f.delivery_time_min, f.payment_method
            from scored s
            join filtered f on f.comment_hash = s.comment_hash
            qualify row_number() over (partition by s.comment_hash order by f.review_date desc, f.review_id desc)
                    <= {EXAMPLES_PER_TEXT}
            order by s.similarity desc, f.review_date desc
        """
        columns, rows = db.query(sql, {**params, "qvec": json.dumps(vector)})
    except Exception as error:
        out["error"] = f"review search failed: {str(error)[:500]}"
        return out

    by_text = {}
    for row in rows:
        record = dict(zip(columns, (db.jsonable(v) for v in row)))
        item = by_text.setdefault(record["comment_hash"], {
            "text": record["comment"], "reviews": record["n_reviews"],
            "similarity": round(record["similarity"], 3), "examples": [],
        })
        example = {k: record[k] for k in (
            "review_id", "review_date", "city", "rating", "restaurant_name", "cuisine",
            "restaurant_rating_at_review", "cost_for_two_at_review",
            "order_id", "sales_amount", "delivery_time_min", "payment_method") if record[k] is not None}
        item["examples"].append(example)
    out["results"] = list(by_text.values())
    if not out["results"]:
        out["note"] = "matching reviews exist but none has an embedding yet: run ai/embed_reviews.py"
    return out
