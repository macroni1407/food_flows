"""query_warehouse: text-to-SQL with a schema built from dbt, a sqlglot guard and self-correction."""
from . import context, db, llm, prompts, schema, settings
from .sql_guard import check_sql


def query_warehouse(question):
    """
    Answer a question with one SQL query on the MARTS schema.
    Returns a dict: question, sql, columns, rows, row_count, fixes, notes, error.
    """
    result = {"question": question, "sql": None, "columns": [], "rows": [], "row_count": 0,
              "fixes": 0, "notes": [], "error": None}
    try:
        ctx = context.get_context()
        marts = schema.load_marts()
    except Exception as error:  # missing dbt artifacts, Snowflake unreachable, ...
        result["error"] = f"setup failed: {error}"
        return result

    allowed = schema.allowed_tables(marts)
    system = prompts.TEXT2SQL_SYSTEM.format(
        latest_order_date=ctx.latest_order_date,
        latest_review_date=ctx.latest_review_date,
        schema=schema.describe(marts, ctx.categorical_values),
    )

    try:
        sql = llm.chat_json(system, question).get("sql", "")
    except Exception as error:
        result["error"] = f"LLM call failed: {error}"
        return result

    for attempt in range(settings.SQL_MAX_FIXES + 1):
        guard = check_sql(sql, allowed, settings.SQL_DEFAULT_LIMIT)
        if guard.ok:
            result["sql"] = guard.sql
            try:
                result["columns"], rows = db.query(guard.sql)
                result["rows"] = [[db.jsonable(v) for v in row] for row in rows]
                result["row_count"] = len(rows)
                result["error"] = None
                break
            except Exception as error:
                problem = f"Snowflake error: {str(error)[:500]}"
        else:
            result["sql"] = sql
            problem = f"Rejected by the safety check: {guard.reason}"

        result["error"] = problem
        if attempt == settings.SQL_MAX_FIXES:
            break
        result["fixes"] += 1
        try:
            fix = prompts.TEXT2SQL_FIX.format(question=question, sql=sql, problem=problem)
            sql = llm.chat_json(system, fix).get("sql", "")
        except Exception as error:
            result["error"] = f"LLM call failed while fixing the query: {error}"
            break

    if result["error"] is None:
        if result["row_count"] == 0:
            result["notes"].append("the query returned no rows: check filter values and dates")
        if result["row_count"] >= settings.SQL_DEFAULT_LIMIT:
            result["notes"].append(f"result capped at {settings.SQL_DEFAULT_LIMIT} rows by LIMIT")
        if result["fixes"]:
            result["notes"].append(f"the query was corrected {result['fixes']} time(s)")
    return result


def for_llm(result, max_rows=None):
    """Compact version of a query_warehouse result for the agent's context."""
    max_rows = max_rows or settings.TOOL_ROWS_FOR_LLM
    compact = dict(result)
    compact["rows"] = result["rows"][:max_rows]
    if len(result["rows"]) > max_rows:
        compact["notes"] = result["notes"] + [f"only the first {max_rows} of {len(result['rows'])} rows are shown"]
    return compact
