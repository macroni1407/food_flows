"""
Import airflow/dags with real Airflow and check the zomato_batch DAG.
Runs inside the apache/airflow image (see the dag-import job in .github/workflows/ci.yml):

    docker run --rm -v "$PWD:/repo:ro" apache/airflow:3.0.3 python /repo/tests/check_dag_import.py
"""
from airflow.models.dagbag import DagBag

bag = DagBag(dag_folder="/repo/airflow/dags", include_examples=False)
assert not bag.import_errors, f"DAG import errors: {bag.import_errors}"

dag = bag.dags["zomato_batch"]
expected_upstream = {
    "generate_data": set(),
    "reload_raw": {"generate_data"},
    "dbt_build_core": {"reload_raw"},
    "enrich_reviews": {"dbt_build_core"},
    "embed_reviews": {"dbt_build_core"},
    "dbt_build_ai": {"enrich_reviews", "embed_reviews"},
    "dbt_docs": {"dbt_build_ai"},
}
actual = {t.task_id: set(t.upstream_task_ids) for t in dag.tasks}
assert actual == expected_upstream, f"unexpected dependencies: {actual}"
assert dag.max_active_runs == 1, "days must run one after another"

order = [t.task_id for t in dag.topological_sort()]
print(f"zomato_batch imported: {' -> '.join(order)}")
