"""
Facts about the data that every prompt needs: the latest dates (to interpret "last week"), valid
values of categorical columns (so the LLM writes 'Bangalore', not 'Bengaluru') and the main cities.
Loaded once from Snowflake and cached for an hour.
"""
import time
from dataclasses import dataclass, field

from . import db

CACHE_SECONDS = 3600

# (table, column) pairs whose distinct values go into the text-to-SQL prompt
CATEGORICAL_COLUMNS = [
    ("FCT_ORDERS", "ORDER_STATUS"),
    ("FCT_ORDERS", "PAYMENT_METHOD"),
    ("DIM_CUSTOMER", "AGE_SEGMENT"),
    ("DIM_FOOD", "VEG_OR_NON_VEG"),
    ("MART_REVIEW_INSIGHTS", "SENTIMENT_LABEL"),
    ("MART_REVIEW_INSIGHTS", "TOPIC"),
]
TOP_CITIES = 40


@dataclass
class DataContext:
    latest_order_date: str = "unknown"
    latest_review_date: str = "unknown"
    categorical_values: dict = field(default_factory=dict)   # "TABLE.COLUMN" -> [values]
    cities: list = field(default_factory=list)                # most frequent cities first


_cache = {"value": None, "loaded_at": 0.0}


def get_context():
    if _cache["value"] is None or time.time() - _cache["loaded_at"] > CACHE_SECONDS:
        _cache["value"] = _load()
        _cache["loaded_at"] = time.time()
    return _cache["value"]


def _load():
    ctx = DataContext()
    _, rows = db.query(
        "select (select max(order_date) from FCT_ORDERS), (select max(review_date) from MART_DAILY_REVIEW_STATS)"
    )
    ctx.latest_order_date = str(rows[0][0])
    ctx.latest_review_date = str(rows[0][1])

    union = " union all ".join(
        f"select '{table}.{column}', {column}::string from (select distinct {column} from {table}) "
        f"where {column} is not null"
        for table, column in CATEGORICAL_COLUMNS
    )
    _, rows = db.query(union)
    for key, value in rows:
        ctx.categorical_values.setdefault(key, []).append(value)
    for values in ctx.categorical_values.values():
        values.sort()

    _, rows = db.query(
        f"select city from MART_DAILY_CITY_REVENUE group by city order by sum(orders) desc limit {TOP_CITIES}"
    )
    ctx.cities = [r[0] for r in rows]
    return ctx
