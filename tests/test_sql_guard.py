"""Unit tests for ai/agent/sql_guard.py (no LLM, no Snowflake)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from agent.sql_guard import check_sql  # noqa: E402

ALLOWED = {"FCT_ORDERS", "DIM_RESTAURANTS", "MART_DAILY_CITY_REVENUE"}


def ok(sql):
    result = check_sql(sql, ALLOWED)
    assert result.ok, result.reason
    return result.sql


def blocked(sql):
    result = check_sql(sql, ALLOWED)
    assert not result.ok, f"should be blocked: {sql}"
    return result.reason


def test_simple_select_gets_a_limit():
    sql = ok("select city, sum(gmv) from mart_daily_city_revenue group by city")
    assert sql.upper().endswith("LIMIT 100")


def test_existing_limit_is_kept():
    sql = ok("select * from fct_orders limit 5")
    assert "LIMIT 5" in sql.upper() and "LIMIT 100" not in sql.upper()


def test_trailing_semicolon_is_fine():
    ok("select count(*) from fct_orders;")


def test_qualified_marts_names_are_accepted():
    ok("select * from ZOMATO.MARTS.FCT_ORDERS")
    ok("select * from marts.fct_orders")


def test_cte_names_are_not_mistaken_for_tables():
    sql = ok("with t as (select city, count(*) n from fct_orders group by city) select * from t order by n desc")
    assert "LIMIT 100" in sql.upper()


def test_union_and_snowflake_syntax():
    ok("select city from fct_orders union select city from dim_restaurants")
    ok("select order_id from fct_orders qualify row_number() over (partition by city order by order_id) = 1")
    ok("select order_date::date, dateadd(day, -7, current_date()) from fct_orders where city ilike 'del%'")


@pytest.mark.parametrize("sql", [
    "delete from fct_orders",
    "drop table fct_orders",
    "update fct_orders set city = 'x'",
    "insert into fct_orders select * from fct_orders",
    "create table x as select * from fct_orders",
    "truncate table fct_orders",
    "grant select on fct_orders to role public",
    "merge into fct_orders t using dim_restaurants s on t.restaurant_id = s.restaurant_id when matched then delete",
])
def test_writes_and_ddl_are_blocked(sql):
    blocked(sql)


def test_two_statements_are_blocked():
    assert "one statement" in blocked("select 1 from fct_orders; drop table fct_orders")


def test_other_schemas_are_blocked():
    assert "schema" in blocked("select * from raw.orders")
    assert "schema" in blocked("select * from ZOMATO.STAGING.STG_ORDERS")
    assert "schema" in blocked("select * from information_schema.tables")


def test_other_databases_are_blocked():
    assert "database" in blocked("select * from snowflake.account_usage.query_history")


def test_unknown_marts_table_is_blocked():
    assert "not an allowed" in blocked("select * from secret_table")


def test_blocked_functions():
    blocked("select * from table(result_scan(last_query_id()))")
    blocked("select system$whitelist() from fct_orders")


def test_unparseable_sql_is_blocked():
    blocked("selec * frm fct_orders whre")


def test_empty_sql_is_blocked():
    blocked("   ")
