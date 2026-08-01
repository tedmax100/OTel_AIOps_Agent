"""The Day1 agent under test: a ReAct loop with three query tools.

This is deliberately the *unfixed* agent. Its schema knowledge is baked into
`prompt.md` as prose written against one particular cluster, it gets a hard
budget of 4 tool calls per question, and nothing verifies that the numbers or
trace IDs it prints ever appeared in a tool result. Every one of those is a
design decision the rest of the series takes apart.

It is not a toy: the tools speak the same native Prometheus / Loki / Tempo APIs
as the production agent, so the failures the bench records are real failures
against a real stack, not artefacts of a mock.

    from agent.baseline_agent import investigate
    trace = await investigate("which backend had the highest 5xx share?")
    trace.answer      # final text
    trace.tool_calls  # [ToolCall(name, args, output, ok), ...]
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100")
TEMPO_URL = os.getenv("TEMPO_URL", "http://localhost:3200")

MODEL = os.getenv("BASELINE_MODEL", "gemini-3.1-flash-lite")
# The per-question ceiling. 4 is what the production agent shipped with, and
# Day6 comes back to what the agent does when it hits this wall.
TOOL_CALL_BUDGET = int(os.getenv("TOOL_CALL_BUDGET", "4"))
# Tool results are truncated before they reach the model — an unbounded Loki
# response would eat the whole context window on one call.
MAX_TOOL_CHARS = 4000

_PROMPT_PATH = Path(__file__).with_name("prompt.md")


# ---- tool-call recording ----------------------------------------------------


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    output: str
    ok: bool


# Populated by the tools, drained by `investigate`. A single agent run is
# sequential, so a module-level list is enough here; the bench runs one question
# at a time on purpose.
_RECORD: list[ToolCall] = []


def _record(name: str, args: dict[str, Any], output: str, ok: bool) -> str:
    _RECORD.append(ToolCall(name=name, args=args, output=output, ok=ok))
    return output


def _get(base: str, path: str, params: dict[str, Any]) -> tuple[str, bool]:
    """GET a JSON API and return (text, ok). Errors come back as text so the
    model sees them and can react, rather than the graph blowing up."""
    try:
        resp = httpx.get(f"{base.rstrip('/')}{path}", params=params, timeout=30.0)
    except Exception as e:  # network / DNS / timeout
        return f"ERROR: request failed: {type(e).__name__}: {e}", False
    if resp.status_code >= 400:
        return f"ERROR: HTTP {resp.status_code}: {resp.text[:500]}", False
    return resp.text[:MAX_TOOL_CHARS], True


# ---- the three query tools --------------------------------------------------


@tool
def prometheus_query(promql: str) -> str:
    """Run an instant PromQL query against Prometheus and return the raw JSON
    result. Use this for metric questions (rates, ratios, totals)."""
    text, ok = _get(PROMETHEUS_URL, "/api/v1/query", {"query": promql})
    return _record("prometheus_query", {"promql": promql}, text, ok)


@tool
def loki_query(logql: str, hours: int = 6) -> str:
    """Run a LogQL query against Loki over the last `hours` hours. Accepts both
    log selectors and metric queries such as sum(count_over_time(...))."""
    end = int(time.time())
    start = end - hours * 3600
    text, ok = _get(
        LOKI_URL,
        "/loki/api/v1/query_range",
        {"query": logql, "start": f"{start}000000000", "end": f"{end}000000000", "limit": 100},
    )
    return _record("loki_query", {"logql": logql, "hours": hours}, text, ok)


@tool
def tempo_search(traceql: str, hours: int = 24) -> str:
    """Search Tempo with a TraceQL query over the last `hours` hours. Returns
    matching traces including their trace IDs."""
    end = int(time.time())
    start = end - hours * 3600
    text, ok = _get(
        TEMPO_URL,
        "/api/search",
        {"q": traceql, "start": start, "end": end, "limit": 20},
    )
    return _record("tempo_search", {"traceql": traceql, "hours": hours}, text, ok)


TOOLS = [prometheus_query, loki_query, tempo_search]
_TOOLS_BY_NAME = {t.name: t for t in TOOLS}


# ---- the graph --------------------------------------------------------------


class State(TypedDict):
    messages: list
    calls_used: int


def _model() -> Any:
    return ChatGoogleGenerativeAI(model=MODEL, temperature=0).bind_tools(TOOLS)


async def _agent_node(state: State) -> dict:
    reply = await _model().ainvoke(state["messages"])
    return {"messages": state["messages"] + [reply], "calls_used": state["calls_used"]}


async def _tools_node(state: State) -> dict:
    last = state["messages"][-1]
    out = list(state["messages"])
    used = state["calls_used"]
    for call in last.tool_calls:
        fn = _TOOLS_BY_NAME[call["name"]]
        result = await fn.ainvoke(call["args"])
        out.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        used += 1
    return {"messages": out, "calls_used": used}


async def _force_answer_node(state: State) -> dict:
    """Budget exhausted. The agent is told to conclude *now*, with whatever it
    has. Day6 is about what it does with this instruction."""
    nudge = HumanMessage(
        content=(
            "You have used your entire tool budget. Answer the question now with "
            "the data you already collected. Do not request more tools."
        )
    )
    # No tools bound, so it cannot stall by asking for another query.
    plain = ChatGoogleGenerativeAI(model=MODEL, temperature=0)
    reply = await plain.ainvoke(state["messages"] + [nudge])
    return {"messages": state["messages"] + [reply], "calls_used": state["calls_used"]}


def _route(state: State) -> Literal["tools", "force_answer", "__end__"]:
    last = state["messages"][-1]
    wants_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
    if not wants_tools:
        return END
    if state["calls_used"] >= TOOL_CALL_BUDGET:
        return "force_answer"
    return "tools"


def build_graph() -> Any:
    g = StateGraph(State)
    g.add_node("agent", _agent_node)
    g.add_node("tools", _tools_node)
    g.add_node("force_answer", _force_answer_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", _route)
    g.add_edge("tools", "agent")
    g.add_edge("force_answer", END)
    return g.compile()


# ---- entry point ------------------------------------------------------------


@dataclass
class RunTrace:
    question: str
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None

    def tool_output_blob(self) -> str:
        """Everything the agent actually read. The grader checks citations
        against this, which is how a hallucinated trace ID gets caught."""
        return "\n".join(c.output for c in self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "error": self.error,
            "tool_calls": [
                {"name": c.name, "args": c.args, "ok": c.ok, "output": c.output[:1000]}
                for c in self.tool_calls
            ],
        }


def _flatten_content(content: Any) -> str:
    """Gemini returns content as a list of blocks, not a string, and some blocks
    are not text at all (thought signatures — long base64 blobs).

    `str(content)` therefore produces something that *looks* like the answer but
    carries hundreds of digits from the signature. A grader that searches the
    answer for numbers will happily find one that matches, and score a run that
    said "I am unable to calculate" as a pass. Flattening to text only is not a
    cosmetic fix — it is what makes the score mean anything."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _system_prompt() -> str:
    return _PROMPT_PATH.read_text().replace("{budget}", str(TOOL_CALL_BUDGET))


async def investigate(question: str) -> RunTrace:
    """Answer one question. Never raises: a crashed run is a recorded failure,
    because the bench has to survive nine of these in a row."""
    _RECORD.clear()
    messages = [SystemMessage(content=_system_prompt()), HumanMessage(content=question)]
    try:
        final = await build_graph().ainvoke(
            {"messages": messages, "calls_used": 0},
            {"recursion_limit": 25},
        )
        answer = _flatten_content(final["messages"][-1].content)
        return RunTrace(question=question, answer=answer, tool_calls=list(_RECORD))
    except Exception as e:
        return RunTrace(
            question=question,
            answer="",
            tool_calls=list(_RECORD),
            error=f"{type(e).__name__}: {e}",
        )


if __name__ == "__main__":  # manual smoke test: python -m agent.baseline_agent "..."
    import asyncio
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "Is anything failing right now?"
    trace = asyncio.run(investigate(q))
    print(json.dumps(trace.to_dict(), indent=2, ensure_ascii=False))
