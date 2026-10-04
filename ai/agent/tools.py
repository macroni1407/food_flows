"""Wire the real tools and the Groq models into the orchestrator."""
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from . import context, prompts, reviews, settings, warehouse
from .graph import make_agent


class QueryWarehouseArgs(BaseModel):
    question: str = Field(description="A self-contained question about numbers or statistics, "
                                      "e.g. 'Share of 1-2 star reviews by day in Delhi from 2026-09-01 to 2026-09-10'.")


def _query_warehouse(question):
    return warehouse.for_llm(warehouse.query_warehouse(question))


TOOLS = {"query_warehouse": _query_warehouse, "search_reviews": reviews.search_reviews}

TOOL_SCHEMAS = [
    StructuredTool.from_function(
        func=_query_warehouse, name="query_warehouse", args_schema=QueryWarehouseArgs,
        description="Numbers and statistics from the data warehouse (orders, revenue, delivery times, "
                    "restaurants, customers, review counts). Writes and runs one SQL query."),
    StructuredTool.from_function(
        func=reviews.search_reviews, name="search_reviews", args_schema=reviews.ReviewSearchArgs,
        description="What customers wrote: top distinct review texts matching the query and filters, "
                    "with how many reviews contain each and example reviews with restaurant context."),
]


def build_agent():
    """Real orchestrator: Groq through its OpenAI-compatible endpoint."""
    from langchain_openai import ChatOpenAI

    ctx = context.get_context()
    model = ChatOpenAI(model=settings.AGENT_MODEL, api_key=settings.GROQ_API_KEY,
                       base_url=settings.GROQ_BASE_URL, temperature=0, timeout=60, max_retries=2)
    system = prompts.ORCHESTRATOR_SYSTEM.format(
        latest_order_date=ctx.latest_order_date, latest_review_date=ctx.latest_review_date,
        cities=", ".join(ctx.cities[:25]), max_tool_calls=settings.AGENT_MAX_TOOL_CALLS)
    return make_agent(
        llm_with_tools=model.bind_tools(TOOL_SCHEMAS),
        llm_plain=model,
        tools=TOOLS,
        max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
        timeout_s=settings.AGENT_TIMEOUT_S,
        system_prompt=system,
        finalize_instruction=prompts.FINALIZE_INSTRUCTION,
    )
