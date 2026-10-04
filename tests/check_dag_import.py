"""
Import airflow/dags with real Airflow and check the zomato_batch DAG.
Runs inside the apache/airflow image (see the dag-import job in .github/workflows/ci.yml):

    docker run --rm -v "$PWD:/repo:ro" apache/airflow:3.0.3 python /repo/tests/check_dag_import.py
"""
from airflow.models.dagbag import DagBag

bag = DagBag(dag_folder="/repo/airflow/dags", include_examples=False)
assert not bag.import_errors, f"DAG import errors: {bag.import_errors}"

dag = bag.dags["zomato_batch"]
expected = ["generate_data", "reload_raw", "dbt_build_core", "enrich_reviews", "dbt_build_ai"]
order = [t.task_id for t in dag.topological_sort()]
assert order == expected, f"unexpected task order: {order}"
assert dag.max_active_runs == 1, "days must run one after another"

print(f"zomato_batch imported: {' -> '.join(order)}")
