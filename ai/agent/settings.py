"""Configuration from environment variables (ai/.env locally, docker-compose in Airflow)."""
import os
from pathlib import Path

from dotenv import load_dotenv

AI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AI_DIR.parent
load_dotenv(AI_DIR / ".env")

# LLMs on Groq. The agent talks to Groq's OpenAI-compatible endpoint (langchain-openai), because
# langchain-groq does not support the groq==1.x SDK the rest of the project uses.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
SQL_MODEL = os.environ.get("GROQ_SQL_MODEL", "openai/gpt-oss-120b")
ANSWER_MODEL = os.environ.get("GROQ_ANSWER_MODEL", "openai/gpt-oss-120b")
AGENT_MODEL = os.environ.get("GROQ_AGENT_MODEL", "openai/gpt-oss-120b")

# Embeddings (Jina)
JINA_API_KEY = os.environ.get("JINA_API_KEY")
JINA_URL = os.environ.get("JINA_URL", "https://api.jina.ai/v1/embeddings")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "jina-embeddings-v5-omni-small")

# Snowflake. Questions run under the read-only role (snowflake/07_readonly_role.sql); writes
# (agent logs, embeddings) use the pipeline role.
SNOWFLAKE_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT")
SNOWFLAKE_USER = os.environ.get("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD = os.environ.get("SNOWFLAKE_PASSWORD")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "ZOMATO_WH")
SNOWFLAKE_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "ZOMATO")
READ_ROLE = os.environ.get("SNOWFLAKE_TEXT2SQL_ROLE", "ANALYST_RO_ROLE")
WRITE_ROLE = os.environ.get("SNOWFLAKE_ROLE", "DBT_ROLE")
STATEMENT_TIMEOUT_S = int(os.environ.get("STATEMENT_TIMEOUT_IN_SECONDS", "60"))

# dbt artifacts: manifest.json (models, descriptions) and catalog.json (column types)
DBT_TARGET_DIR = Path(os.environ.get("DBT_TARGET_DIR", REPO_ROOT / "zomato" / "target"))

# Text-to-SQL
SQL_DEFAULT_LIMIT = 100
SQL_MAX_FIXES = 2

# Agent budgets
AGENT_MAX_TOOL_CALLS = int(os.environ.get("AGENT_MAX_TOOL_CALLS", "5"))
AGENT_TIMEOUT_S = int(os.environ.get("AGENT_TIMEOUT_S", "90"))
TOOL_ROWS_FOR_LLM = 30
