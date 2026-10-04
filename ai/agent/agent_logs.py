"""Write each question and its trace to ZOMATO.AI.AGENT_LOGS (pipeline role). Never breaks the app."""
import json
import uuid

from . import db, settings

TABLE = "ZOMATO.AI.AGENT_LOGS"
_table_ready = {"done": False}


def _ensure_table():
    if not _table_ready["done"]:
        db.execute(f"""
            create table if not exists {TABLE} (
                log_id string, logged_at timestamp_ltz default current_timestamp(), page string,
                question string, answer string, tool_calls number, hit_budget boolean,
                duration_ms number, error string, trace variant)
        """, role=settings.WRITE_ROLE)
        _table_ready["done"] = True


def write(page, question, answer=None, tool_calls=0, hit_budget=False, duration_ms=0, error=None, trace=None):
    """Returns the log id, or None if logging failed."""
    log_id = str(uuid.uuid4())
    try:
        _ensure_table()
        db.execute(
            f"""insert into {TABLE} (log_id, page, question, answer, tool_calls, hit_budget, duration_ms, error, trace)
                select %(log_id)s, %(page)s, %(question)s, %(answer)s, %(tool_calls)s, %(hit_budget)s,
                       %(duration_ms)s, %(error)s, parse_json(%(trace)s)""",
            {"log_id": log_id, "page": page, "question": question, "answer": answer,
             "tool_calls": tool_calls, "hit_budget": hit_budget, "duration_ms": duration_ms,
             "error": error, "trace": json.dumps(trace or [], default=str)},
            role=settings.WRITE_ROLE,
        )
        return log_id
    except Exception as exc:
        print(f"agent log not written: {exc}")
        return None
