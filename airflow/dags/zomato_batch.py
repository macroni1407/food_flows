from datetime import datetime

from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.providers.standard.operators.bash import BashOperator  # Airflow 3 import

from airflow import DAG

DBT = "/opt/airflow/dbt_venv/bin/dbt"
DBT_PROJECT = "/opt/airflow/dbt/zomato"

# CSV columns of each RAW table, in file order. COPY selects them by position ($1, $2, ...)
# and appends two load-metadata columns: _source_file and _loaded_at.
# daily=True: the generator writes a new raw/<table>/dt=YYYY-MM-DD/ folder every day, and a run
# loads only the folder of its own logical date ({{ ds }}). Static tables load their whole folder
# (files already loaded are skipped by Snowflake's load metadata).
RAW_TABLES = {
    "restaurants": {"daily": True, "on_error": "CONTINUE",
                    "columns": "_idx id name city rating rating_count cost cuisine lic_no link address menu"},
    "users": {"daily": False, "on_error": "CONTINUE",
              "columns": "_idx user_id name email password age gender marital_status occupation "
                         "monthly_income education family_size"},
    "food": {"daily": False, "on_error": "CONTINUE", "columns": "_idx f_id item veg_or_non_veg"},
    "menu": {"daily": False, "on_error": "CONTINUE", "columns": "_idx menu_id r_id f_id cuisine price"},
    "orders": {"daily": True, "on_error": "ABORT_STATEMENT",
               "columns": "order_id order_timestamp order_date user_id r_id restaurant_city cuisine "
                          "items_count sales_qty subtotal discount delivery_fee gst sales_amount currency "
                          "payment_method order_status customer_rating delivery_time_min"},
    "order_items": {"daily": True, "on_error": "ABORT_STATEMENT",
                    "columns": "order_item_id order_id r_id f_id price quantity line_amount"},
    "reviews": {"daily": True, "on_error": "ABORT_STATEMENT",
                "columns": "review_id order_id user_id restaurant_id rating comment review_date"},
}


def copy_statement(table, spec):
    columns = spec["columns"].split()
    positions = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    path = f"{table}/dt={{{{ ds }}}}/" if spec["daily"] else f"{table}/"
    return (
        f"COPY INTO ZOMATO.RAW.{table} ({', '.join(columns)}, _source_file, _loaded_at) "
        f"FROM (SELECT {positions}, METADATA$FILENAME, METADATA$START_SCAN_TIME "
        f"FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/{path}) "
        f"ON_ERROR='{spec['on_error']}'"
    )


COPY_RAW = ["USE WAREHOUSE ZOMATO_WH"] + [copy_statement(t, spec) for t, spec in RAW_TABLES.items()]

# Every run works on the day given by its logical date ({{ ds }}). A run triggered without a
# logical date has no ds, so fail fast with a clear message instead of a template error later.
GENERATE_DATA = (
    "{% if ds is not defined or not ds %}"
    "echo 'This DAG needs a logical date: trigger it with one, or use a backfill.' >&2; exit 1"
    "{% else %}"
    "python /opt/airflow/generator/daily_generator.py --ds {{ ds }} "
    "--data-dir /opt/airflow/data --out-dir /tmp/generator_output"
    "{% endif %}"
)

with DAG(
    dag_id="zomato_batch",
    start_date=datetime(2026, 9, 1),    # first day produced by generator/daily_generator.py
    schedule="@daily",
    catchup=False,
    max_active_runs=1,                  # days must run one after another (shared dbt tables)
    tags=["zomato", "dbt", "snowflake"],
    doc_md=__doc__,
) as dag:

    generate_data = BashOperator(
        task_id="generate_data",
        bash_command=GENERATE_DATA,
    )

    reload_raw = SQLExecuteQueryOperator(
        task_id="reload_raw", conn_id="snowflake_default", 
        sql=COPY_RAW, split_statements=True, autocommit=True
    )

    dbt_build_core = BashOperator(
        task_id="dbt_build_core",
        bash_command=f"{DBT} build --exclude tag:ai --project-dir {DBT_PROJECT} --profiles-dir {DBT_PROJECT}",
    )

    enrich_reviews = BashOperator(
        task_id="enrich_reviews",
        bash_command="python /opt/airflow/ai/enrich_reviews.py",
    )

    # One embedding per distinct review text (AI.REVIEW_EMBEDDINGS), for review search.
    embed_reviews = BashOperator(
        task_id="embed_reviews",
        bash_command="python /opt/airflow/ai/embed_reviews.py",
    )

    # tag:ai models: mart_review_insights and mart_review_search (it carries the enrichment labels)
    dbt_build_ai = BashOperator(
        task_id = "dbt_build_ai",
        bash_command=f"{DBT} build --select tag:ai --project-dir {DBT_PROJECT} --profiles-dir {DBT_PROJECT}"
    )

    # catalog.json (column types) for the text-to-SQL schema prompt (ai/agent/schema.py)
    dbt_docs = BashOperator(
        task_id="dbt_docs",
        bash_command=f"{DBT} docs generate --project-dir {DBT_PROJECT} --profiles-dir {DBT_PROJECT}",
    )

    generate_data >> reload_raw >> dbt_build_core >> [enrich_reviews, embed_reviews] >> dbt_build_ai >> dbt_docs