# Common tasks. Run `make` or `make help` to list them.
# Examples:
#   make ci                                   # the same checks GitHub Actions runs
#   make up                                   # start Airflow
#   make backfill FROM=2026-09-06 TO=2026-09-13

PYTHON  ?= python
COMPOSE := docker compose -f airflow/docker-compose.yml
AIRFLOW_IMAGE := apache/airflow:3.0.3
GITLEAKS_IMAGE := zricethezav/gitleaks:v8.30.1

.DEFAULT_GOAL := help
.PHONY: help install lint test dbt-parse dag-check secrets ci build up down logs \
        dbt-build generate trigger backfill app embed text2sql rag

help:  ## List available commands
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-11s\033[0m %s\n", $$1, $$2}'

# --- Setup -----------------------------------------------------------------------------

install:  ## Install Python dependencies (dbt, AI apps, generator, test tools)
	$(PYTHON) -m pip install -r requirements.txt ruff pytest

# --- Checks (same as .github/workflows/ci.yml) ---------------------------------------

lint:  ## Lint Python code with ruff
	ruff check .

test:  ## Run the data generator tests
	$(PYTHON) -m pytest -q tests/

dbt-parse:  ## Parse the dbt project with dummy credentials (no Snowflake connection)
	@tmp=$$(mktemp -d); cp zomato/profiles.example.yml $$tmp/profiles.yml; \
	cd zomato && SNOWFLAKE_ACCOUNT=ci-dummy SNOWFLAKE_USER=ci-dummy SNOWFLAKE_PASSWORD=ci-dummy \
	dbt parse --profiles-dir $$tmp --target-path $$tmp/target --no-partial-parse; \
	status=$$?; rm -rf $$tmp; exit $$status

dag-check:  ## Import the Airflow DAG with real Airflow (Docker)
	docker run --rm -v "$(CURDIR):/repo:ro" $(AIRFLOW_IMAGE) python /repo/tests/check_dag_import.py

secrets:  ## Scan the whole git history for secrets (gitleaks, Docker)
	docker run --rm -v "$(CURDIR):/repo:ro" $(GITLEAKS_IMAGE) git /repo --redact --no-banner

ci: lint test dbt-parse dag-check secrets  ## Run every CI check locally

# --- Airflow ---------------------------------------------------------------------------

build:  ## Build the Airflow image
	$(COMPOSE) build

up:  ## Start Airflow (http://localhost:8080, admin/admin)
	$(COMPOSE) up -d

down:  ## Stop Airflow
	$(COMPOSE) down

logs:  ## Follow scheduler logs
	$(COMPOSE) logs -f scheduler

trigger:  ## Run the pipeline for one day: make trigger DS=2026-09-06
	@test -n "$(DS)" || { echo "usage: make trigger DS=YYYY-MM-DD"; exit 1; }
	$(COMPOSE) exec -T scheduler airflow dags trigger zomato_batch --logical-date "$(DS)T00:00:00+00:00"

backfill:  ## Run the pipeline for a date range: make backfill FROM=2026-09-06 TO=2026-09-13
	@test -n "$(FROM)" -a -n "$(TO)" || { echo "usage: make backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD"; exit 1; }
	@$(PYTHON) -c "from datetime import date, timedelta; a, b = date.fromisoformat('$(FROM)'), date.fromisoformat('$(TO)'); print('\n'.join(str(a + timedelta(i)) for i in range((b - a).days + 1)))" \
	| while read d; do \
		echo "trigger $$d"; \
		$(COMPOSE) exec -T scheduler airflow dags trigger zomato_batch --logical-date "$${d}T00:00:00+00:00" >/dev/null || exit 1; \
	done

# --- Local runs ------------------------------------------------------------------------

dbt-build:  ## Build and test all dbt models except the AI mart (uses zomato/profiles.yml)
	cd zomato && dbt build --exclude tag:ai

generate:  ## Generate one day locally without uploading: make generate DS=2026-09-06
	@test -n "$(DS)" || { echo "usage: make generate DS=YYYY-MM-DD"; exit 1; }
	$(PYTHON) generator/daily_generator.py --ds $(DS) --no-upload

app:  ## Start the AI app: Text-to-SQL, Chat with reviews, Agent (Streamlit)
	cd ai && streamlit run app.py

embed:  ## Embed review texts that have no embedding yet (also a DAG task)
	$(PYTHON) ai/embed_reviews.py

text2sql:  ## Start the text-to-SQL app (Streamlit)
	cd ai && streamlit run text_to_sql.py

rag:  ## Start the RAG review chat (Streamlit)
	cd ai && streamlit run rag_chat.py
