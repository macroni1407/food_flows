"""Tests for the orchestrator loop (ai/agent/graph.py) with scripted fake LLMs: no Groq, no Snowflake."""
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from agent.graph import make_agent  # noqa: E402

FINAL = "final answer"


class ScriptedLLM:
    """Returns the scripted replies in order and records the messages it was given."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def invoke(self, messages):
        self.seen.append(list(messages))
        reply = self.replies.pop(0) if self.replies else AIMessage(content=FINAL)
        return reply


def call(name, args, call_id):
    return {"name": name, "args": args, "id": call_id}


def tool_reply(*calls):
    return AIMessage(content="", tool_calls=list(calls))


class Recorder:
    def __init__(self, result=None, raises=None):
        self.calls = []
        self.result = result or {"ok": True}
        self.raises = raises

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return {**self.result, "args": kwargs}


def build(llm, tools, max_tool_calls=5, timeout_s=60, plain=None):
    plain = plain or ScriptedLLM([AIMessage(content="finalized answer")])
    run = make_agent(llm, plain, tools, max_tool_calls, timeout_s, "system", "finalize now")
    return run, plain


def test_answers_directly_without_tools():
    llm = ScriptedLLM([AIMessage(content="hello")])
    run, _ = build(llm, {})
    result = run("hi")
    assert result["answer"] == "hello" and result["tool_calls"] == 0 and not result["hit_budget"]


def test_hybrid_question_sql_then_reviews():
    warehouse = Recorder({"rows": [["2026-09-06", 0.7]]})
    reviews = Recorder({"results": [{"text": "Gravy spilled all over the bag.", "reviews": 31}]})
    llm = ScriptedLLM([
        tool_reply(call("query_warehouse", {"question": "negative share by day in Delhi"}, "c1")),
        tool_reply(call("search_reviews", {"query": "what went wrong", "city": "Delhi",
                                           "date_from": "2026-09-06", "date_to": "2026-09-06"}, "c2")),
        AIMessage(content="Delhi spiked on 2026-09-06, mostly packaging."),
    ])
    run, _ = build(llm, {"query_warehouse": warehouse, "search_reviews": reviews})
    result = run("Why did Delhi complain in early September?")

    assert [t["tool"] for t in result["trace"]] == ["query_warehouse", "search_reviews"]
    assert result["tool_calls"] == 2 and "packaging" in result["answer"]
    # the SQL result was in the context when the model chose the review filters
    tool_messages = [m for m in llm.seen[1] if isinstance(m, ToolMessage)]
    assert tool_messages and "2026-09-06" in tool_messages[0].content
    assert reviews.calls[0]["date_from"] == "2026-09-06"


def test_budget_stops_the_loop_and_forces_an_answer():
    tool = Recorder()
    llm = ScriptedLLM([tool_reply(call("query_warehouse", {"question": f"q{i}"}, f"c{i}")) for i in range(10)])
    run, plain = build(llm, {"query_warehouse": tool}, max_tool_calls=3)
    result = run("loop forever")
    assert len(tool.calls) == 3 and result["tool_calls"] == 3
    assert result["hit_budget"] and result["answer"] == "finalized answer"
    final_messages = plain.seen[0]
    assert final_messages[-1].content == "finalize now"
    # the tool call that was not executed still got an answer, as the chat API requires
    pending_id = final_messages[-3].tool_calls[0]["id"]
    assert isinstance(final_messages[-2], ToolMessage) and final_messages[-2].tool_call_id == pending_id


def test_repeated_identical_call_is_not_rerun():
    tool = Recorder()
    same = {"question": "top cities by gmv"}
    llm = ScriptedLLM([tool_reply(call("query_warehouse", same, "c1")),
                       tool_reply(call("query_warehouse", same, "c2")),
                       AIMessage(content=FINAL)])
    run, _ = build(llm, {"query_warehouse": tool})
    result = run("top cities")
    assert len(tool.calls) == 1 and result["tool_calls"] == 1
    assert result["trace"][1].get("reused") is True


def test_tool_errors_are_reported_not_raised():
    broken = Recorder(raises=RuntimeError("snowflake is down"))
    llm = ScriptedLLM([tool_reply(call("query_warehouse", {"question": "x"}, "c1")), AIMessage(content=FINAL)])
    run, _ = build(llm, {"query_warehouse": broken})
    result = run("x")
    assert result["answer"] == FINAL
    assert "snowflake is down" in result["trace"][0]["result"]["error"]
    assert "snowflake is down" in [m for m in llm.seen[1] if isinstance(m, ToolMessage)][0].content


def test_unknown_tool_is_reported():
    llm = ScriptedLLM([tool_reply(call("drop_database", {}, "c1")), AIMessage(content=FINAL)])
    run, _ = build(llm, {})
    result = run("x")
    assert "unknown tool" in result["trace"][0]["result"]["error"]


def test_time_limit_goes_straight_to_finalize():
    tool = Recorder()
    llm = ScriptedLLM([tool_reply(call("query_warehouse", {"question": "x"}, "c1"))])
    run, _ = build(llm, {"query_warehouse": tool}, timeout_s=-1)
    result = run("x")
    assert tool.calls == [] and result["hit_budget"] and result["answer"] == "finalized answer"


def test_parallel_calls_in_one_turn_count_against_the_budget():
    warehouse, reviews = Recorder(), Recorder()
    llm = ScriptedLLM([
        tool_reply(call("query_warehouse", {"question": "a"}, "c1"), call("search_reviews", {"query": "b"}, "c2"),
                   call("query_warehouse", {"question": "c"}, "c3")),
        AIMessage(content=FINAL),
    ])
    run, _ = build(llm, {"query_warehouse": warehouse, "search_reviews": reviews}, max_tool_calls=2)
    result = run("compare")
    assert len(warehouse.calls) == 1 and len(reviews.calls) == 1 and result["tool_calls"] == 2
    assert result["trace"][2].get("skipped") is True


class RejectingLLM(ScriptedLLM):
    """Raises like Groq does when generated tool arguments do not match the schema."""

    def __init__(self, replies, rejections):
        super().__init__(replies)
        self.rejections = rejections

    def invoke(self, messages):
        if self.rejections > 0:
            self.rejections -= 1
            self.seen.append(list(messages))
            raise RuntimeError("Error code: 400 - {'error': {'message': \"Tool call validation failed: "
                               "missing properties: 'query'\", 'code': 'tool_use_failed'}}")
        return super().invoke(messages)


def test_rejected_tool_call_is_fed_back_and_retried():
    reviews = Recorder()
    llm = RejectingLLM([tool_reply(call("search_reviews", {"query": "late", "city": "Delhi"}, "c1")),
                        AIMessage(content=FINAL)], rejections=1)
    run, _ = build(llm, {"search_reviews": reviews})
    result = run("x")
    assert result["answer"] == FINAL and len(reviews.calls) == 1
    assert result["trace"][0]["tool"] == "(invalid tool call)"
    retry_messages = llm.seen[1]
    assert "rejected" in retry_messages[-1].content and "missing properties" in retry_messages[-1].content


def test_persistently_rejected_tool_calls_still_produce_an_answer():
    llm = RejectingLLM([], rejections=99)
    run, plain = build(llm, {})
    result = run("x")
    assert result["answer"] == "finalized answer" and result["hit_budget"]
    assert sum(1 for t in result["trace"] if t["tool"] == "(invalid tool call)") == 3


def test_other_errors_are_not_swallowed():
    class Broken(ScriptedLLM):
        def invoke(self, messages):
            raise ValueError("network down")
    run, _ = build(Broken([]), {})
    try:
        run("x")
    except ValueError as error:
        assert "network down" in str(error)
    else:
        raise AssertionError("expected the error to propagate")
