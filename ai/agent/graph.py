"""
The orchestrator: one LLM that calls query_warehouse and search_reviews in a loop, with a budget.

    START -> agent --(tool calls, budget left)--> tools -> agent ...
                   --(no tool calls)------------> END
                   --(budget or time exhausted)-> finalize -> END

The LLMs and tool functions are passed in (make_agent), so the loop can be tested with fake models.
"""
import json
import time
from typing import TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

MAX_TOOL_RESULT_CHARS = 12000
MAX_INVALID_TOOL_CALLS = 3   # attempts when the provider rejects malformed tool calls


def is_invalid_tool_call(error):
    """Groq answers 400 tool_use_failed when generated tool arguments do not match the schema."""
    text = str(error)
    return "tool_use_failed" in text or "Tool call validation failed" in text


class AgentState(TypedDict, total=False):
    messages: list
    tool_calls: int          # tool calls executed so far
    trace: list              # one entry per tool call, for the UI and AGENT_LOGS
    seen: dict               # call signature -> result, to answer repeated calls without rerunning
    started_at: float
    hit_budget: bool


def make_agent(llm_with_tools, llm_plain, tools, max_tool_calls, timeout_s, system_prompt, finalize_instruction):
    """
    llm_with_tools / llm_plain: objects with .invoke(messages) -> AIMessage.
    tools: {name: function(**args) -> dict}.
    """

    def out_of_budget(state):
        return (state["tool_calls"] >= max_tool_calls
                or time.time() - state["started_at"] > timeout_s)

    def agent(state):
        """Ask the model for the next step. Some providers (Groq) validate tool arguments server-side and
        reject the whole response when they do not match the schema; feed the error back and retry."""
        messages = list(state["messages"])
        trace = list(state["trace"])
        for _ in range(MAX_INVALID_TOOL_CALLS):
            try:
                reply = llm_with_tools.invoke(messages)
                return {"messages": messages + [reply], "trace": trace}
            except Exception as error:
                if not is_invalid_tool_call(error):
                    raise
                problem = str(error)[:600]
                trace.append({"step": len(trace) + 1, "tool": "(invalid tool call)", "args": {},
                              "result": {"error": problem}, "ms": 0})
                messages.append(HumanMessage(content=(
                    f"Your last tool call was rejected: {problem}\n"
                    "Call the tool again with valid arguments (fill in every required field), or answer.")))
        # still invalid: answer without tools so the user gets a reply instead of an error
        messages.append(HumanMessage(content=finalize_instruction))
        reply = llm_plain.invoke(messages)
        return {"messages": messages + [reply], "trace": trace, "hit_budget": True}

    def after_agent(state):
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        return "finalize" if out_of_budget(state) else "tools"

    def run_tools(state):
        messages = list(state["messages"])
        trace = list(state["trace"])
        seen = dict(state["seen"])
        count = state["tool_calls"]
        for call in messages[-1].tool_calls:
            started = time.time()
            entry = {"step": len(trace) + 1, "tool": call["name"], "args": call["args"]}
            signature = call["name"] + json.dumps(call["args"], sort_keys=True, default=str)
            if count >= max_tool_calls:
                result = {"error": "not executed: the tool call budget is used up"}
                entry["skipped"] = True
            elif signature in seen:
                result = {"note": "same call as before, previous result reused", **seen[signature]}
                entry["reused"] = True
            elif call["name"] not in tools:
                result = {"error": f"unknown tool {call['name']}"}
                count += 1
            else:
                try:
                    result = tools[call["name"]](**call["args"])
                except Exception as error:   # tools report problems as text, never crash the loop
                    result = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
                count += 1
                seen[signature] = result
            entry["ms"] = int((time.time() - started) * 1000)
            entry["result"] = result
            trace.append(entry)
            content = json.dumps(result, default=str)[:MAX_TOOL_RESULT_CHARS]
            messages.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        return {"messages": messages, "trace": trace, "seen": seen, "tool_calls": count}

    def finalize(state):
        messages = list(state["messages"])
        last = messages[-1]
        if isinstance(last, AIMessage) and last.tool_calls:   # answer the pending calls before asking again
            for call in last.tool_calls:
                messages.append(ToolMessage(content=json.dumps({"error": "not executed: budget used up"}),
                                            tool_call_id=call["id"], name=call["name"]))
        messages.append(HumanMessage(content=finalize_instruction))
        reply = llm_plain.invoke(messages)
        return {"messages": messages + [reply], "hit_budget": True}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", "finalize", END])
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    compiled = graph.compile()

    def run(question):
        """Returns {answer, trace, tool_calls, hit_budget, duration_ms}."""
        started = time.time()
        state = compiled.invoke(
            {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=question)],
             "tool_calls": 0, "trace": [], "seen": {}, "started_at": started, "hit_budget": False},
            config={"recursion_limit": 2 * max_tool_calls + 6},   # second safety net
        )
        answer = state["messages"][-1].content
        if isinstance(answer, list):   # some providers return content blocks
            answer = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in answer)
        return {"answer": answer, "trace": state["trace"], "tool_calls": state["tool_calls"],
                "hit_budget": state.get("hit_budget", False), "duration_ms": int((time.time() - started) * 1000)}

    return run
