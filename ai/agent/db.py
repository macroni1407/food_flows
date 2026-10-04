"""Snowflake connections and queries."""
import datetime as dt
import decimal

import snowflake.connector

from . import settings

_connections = {}


def get_connection(role):
    """One cached connection per role; reopened if it was closed."""
    conn = _connections.get(role)
    if conn is None or conn.is_closed():
        conn = snowflake.connector.connect(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            password=settings.SNOWFLAKE_PASSWORD,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            database=settings.SNOWFLAKE_DATABASE,
            schema="MARTS",
            role=role,
            session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": settings.STATEMENT_TIMEOUT_S},
        )
        _connections[role] = conn
    return conn


def query(sql, params=None, role=None):
    """Run a query and return (column names, rows as tuples)."""
    cursor = get_connection(role or settings.READ_ROLE).cursor()
    try:
        cursor.execute(sql, params)
        columns = [c[0].lower() for c in cursor.description] if cursor.description else []
        return columns, cursor.fetchall()
    finally:
        cursor.close()


def execute(sql, params=None, role=None, many=False):
    """Run a statement (DDL / DML)."""
    cursor = get_connection(role or settings.WRITE_ROLE).cursor()
    try:
        if many:
            cursor.executemany(sql, params)
        else:
            cursor.execute(sql, params)
    finally:
        cursor.close()


def jsonable(value):
    """Make a Snowflake value safe for JSON / the LLM."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value
