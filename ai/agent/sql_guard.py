"""
Checks SQL written by the LLM before it runs. Defense in depth: the query also runs under the
read-only ANALYST_RO_ROLE, so Snowflake refuses writes even if something slips through here.
"""
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

DATABASE = "ZOMATO"
SCHEMA = "MARTS"
BLOCKED_FUNCTIONS = {"RESULT_SCAN", "GET_DDL", "GENERATOR", "FLATTEN"}
WRITE_NODES = tuple(
    getattr(exp, name) for name in (
        "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterTable",
        "TruncateTable", "Command", "Grant", "Copy",
    ) if hasattr(exp, name)
)


@dataclass
class GuardResult:
    ok: bool
    sql: str = ""
    reason: str = ""


def check_sql(sql, allowed_tables, default_limit=100):
    """Return the (possibly rewritten) SQL if it is a single read-only query on allowed tables."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        return GuardResult(False, reason="empty SQL")
    try:
        statements = [s for s in sqlglot.parse(text, dialect="snowflake") if s is not None]
    except sqlglot.errors.SqlglotError as error:
        message = re.sub(r"\x1b\[[0-9;]*m", "", str(error)).splitlines()[0]  # drop terminal colours
        return GuardResult(False, reason=f"SQL could not be parsed: {message[:200]}")
    if len(statements) != 1:
        return GuardResult(False, reason="only one statement is allowed")

    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return GuardResult(False, reason=f"only SELECT queries are allowed, got {type(statement).__name__}")
    if WRITE_NODES and any(True for _ in statement.find_all(*WRITE_NODES)):
        return GuardResult(False, reason="the query contains a write or DDL operation")

    for func in statement.find_all(exp.Func):
        name = (func.sql_name() if not isinstance(func, exp.Anonymous) else func.name).upper()
        if name in BLOCKED_FUNCTIONS or name.startswith("SYSTEM$"):
            return GuardResult(False, reason=f"function {name} is not allowed")

    allowed = {t.upper() for t in allowed_tables}
    cte_names = {cte.alias_or_name.upper() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        name, db, catalog = table.name.upper(), table.db.upper(), table.catalog.upper()
        if not name:
            return GuardResult(False, reason="table functions are not allowed")
        if name in cte_names and not db:
            continue  # reference to a CTE defined in the query, not a real table
        if catalog and catalog != DATABASE:
            return GuardResult(False, reason=f"database {catalog} is not allowed")
        if db and db != SCHEMA:
            return GuardResult(False, reason=f"schema {db} is not allowed, only {SCHEMA}")
        if name not in allowed:
            return GuardResult(False, reason=f"table {name} is not an allowed MARTS table")

    if statement.args.get("limit") is None:
        statement = statement.limit(default_limit)
    return GuardResult(True, sql=statement.sql(dialect="snowflake"))
