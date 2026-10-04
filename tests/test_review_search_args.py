"""Tests for the search_reviews arguments and filters (ai/agent/reviews.py): no Snowflake, no Jina."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from agent.reviews import ReviewSearchArgs, build_filters, filters_applied  # noqa: E402


def test_query_is_not_required_in_the_tool_schema():
    # Groq rejects a whole tool call when a required field is missing, so nothing but filters is required
    assert "required" not in ReviewSearchArgs.model_json_schema()
    assert ReviewSearchArgs(city="Delhi").query == ""


def test_sentiment_maps_to_star_ratings():
    where, params = build_filters(ReviewSearchArgs(query="x", sentiment="negative"))
    assert "rating between" in where and (params["stars_low"], params["stars_high"]) == (1, 2)


def test_values_are_bound_not_inlined():
    sneaky = "Delhi'; drop table x; --"
    where, params = build_filters(ReviewSearchArgs(query="x", city=sneaky, max_restaurant_rating=3.5))
    assert sneaky not in where and params["city"] == sneaky and params["max_rating"] == 3.5


def test_no_filters_means_everything():
    assert build_filters(ReviewSearchArgs(query="x")) == ("1 = 1", {})


def test_dates_are_parsed_and_reported():
    args = ReviewSearchArgs(query="x", date_from="2026-09-06", date_to="2026-09-06")
    assert args.date_from == dt.date(2026, 9, 6)
    assert filters_applied(args) == {"date_from": "2026-09-06", "date_to": "2026-09-06"}


@pytest.mark.parametrize("bad", [{"sentiment": "angry"}, {"topic": "weather"}, {"k": 50}, {"max_restaurant_rating": 9}])
def test_invalid_arguments_are_rejected(bad):
    with pytest.raises(Exception):
        ReviewSearchArgs(query="x", **bad)
