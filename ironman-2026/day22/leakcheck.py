"""Grep everything handed to the model for the answer to the incident it is
about to investigate. Zero tokens: the graph is stubbed out, exactly like
`day21/probe_turn.py` — the thing under test is the prompt, not the model, so
the model does not need to be attached.

A "leak" here is any string that only someone who already knows the root cause
would write down: the culprit version boundary, the flag that ships it, the
failure mechanism, or the decline reason value. Naming the service is fine (the
alert names it), and so is the environment's shape (label names, retention).

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day22/leakcheck.py
    uv run python ../../otel-aiops-agent/ironman-2026/day22/leakcheck.py --show

Exit code 1 if anything leaks, so it can sit in CI next to the other
"does it still block" assertions.
"""

from __future__ import annotations

import asyncio
import re
import sys

import app.agent as agent_mod
from app.agent import build_system_prompt, run_headless

# Each pattern is one fact an honest run has to *discover*. Keep the list keyed
# by what the agent would otherwise have to prove, not by wording.
ANSWER_TOKENS: list[tuple[str, str]] = [
    # scenario: bad-validator
    ("culprit version", r"v2\.5\.0"),
    ("previous version", r"v2\.4\.1"),
    ("the flag that ships it", r"payment_use_new_validator"),
    ("failure mechanism", r"odd[- _]?cents?"),
    ("decline reason value", r"new_validator(_odd_cents)?"),
    # scenario: session-cache. Added when the second incident was, because a
    # scanner that only knows the first one reports a clean prompt while
    # handing over the answer to the second — and it would have done, since
    # the registry that feeds the vocabulary block now carries these values.
    ("the flag that ships it", r"user_session_cache_disabled"),
    ("failure mechanism", r"session[- _]?store"),
    ("auth failure reason value", r"session_store_timeout"),
    ("the thing that was turned off", r"session cache"),
]

ALERT = {
    "labels": {
        "alertname": "PaymentDeclineRateHigh",
        "service_name": "payment-service",
        "severity": "critical",
    },
    "annotations": {"summary": "payment-service declined rate above objective"},
    "startsAt": "now",
}

captured: dict = {}


class _StubGraph:
    async def ainvoke(self, state: dict, config: dict | None = None) -> dict:
        captured["state"] = state
        return {"messages": list(state["messages"])}


async def _stub_findings(messages: list) -> object:
    from app.agent import Findings

    return Findings(summary="stub", hypothesis="stub", confidence=0.9)


def _text(msg: object) -> str:
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content", "")
    return content if isinstance(content, str) else str(content)


def _title(text: str) -> str:
    return next((ln for ln in text.splitlines() if ln.strip()), "")[:60]


# Titles of the injections whose content is measured, not written.
_MEASURED = ("diagnostics auto-run", "Dependency health (live)", "Live capability snapshot")

# The case-recall block (Day38). Neither authored nor measured: it is last
# time's confirmed answer, put back on the table on purpose. Scanning it for
# answer tokens will therefore hit — that is the block working, not failing.
#
# It still cannot be treated like a measured block and quietly passed. A run
# with a non-empty recall block is an open-book run, and the number it produces
# is not comparable to one without it. So it gets its own verdict and its own
# line in the summary: the check stays green, and the report says out loud which
# exam this was.
_RECALLED = ("Past cases for this service",)


def _measured(block_name: str) -> bool:
    return any(marker in block_name for marker in _MEASURED)


def _recalled(block_name: str) -> bool:
    return any(marker in block_name for marker in _RECALLED)


def scan(blocks: list[tuple[str, str]]) -> list[tuple[str, str, str, str]]:
    """-> (block name, leaked fact, matched text, the line it sits on)."""
    hits: list[tuple[str, str, str, str]] = []
    for name, text in blocks:
        for fact, pattern in ANSWER_TOKENS:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                line = text[text.rfind("\n", 0, m.start()) + 1 :]
                line = line.split("\n", 1)[0].strip()
                hits.append((name, fact, m.group(0), line))
                break  # one hit per (block, fact) is enough to fail it
    return hits


async def main() -> None:
    agent_mod._build_agent = lambda: asyncio.sleep(0, result=_StubGraph())
    agent_mod.extract_findings = _stub_findings

    await run_headless(ALERT, thread_id="day22-leakcheck")
    state = captured.get("state")
    if state is None:
        print("the graph was never invoked", file=sys.stderr)
        raise SystemExit(2)

    # The system prompt is not in `messages` (it is bound to the model), so it
    # has to be pulled in separately — which is exactly where Day21's leak was.
    blocks: list[tuple[str, str]] = [("system prompt (schema catalog)", build_system_prompt())]
    blocks += [
        (f"injected #{i}: {_title(_text(m))}", _text(m)) for i, m in enumerate(state["messages"])
    ]

    # Only *authored* text can leak. Blocks that are read from the live system
    # (the runbook's read-only diagnostics, the dependency-health SLIs, the
    # capability snapshot) contain whatever the incident really looks like right
    # now — during a real payment incident that legitimately includes `v2.5.0`.
    # Failing on those means the check goes red exactly when the environment is
    # working, which is how you teach everyone to ignore it.
    hits = [h for h in scan(blocks) if not _measured(h[0]) and not _recalled(h[0])]
    recalled = [(name, text) for name, text in blocks if _recalled(name)]
    print(f"scanned {len(blocks)} block(s), {sum(len(t) for _, t in blocks)} chars\n")
    for name, _ in blocks:
        leaked = [h for h in hits if h[0] == name]
        if leaked:
            mark = "LEAK"
        elif _measured(name):
            mark = "read"
        elif _recalled(name):
            mark = "RCLL"
        else:
            mark = "ok  "
        print(f"[{mark}] {name}")
        for _, fact, matched, line in leaked:
            print(f"         {fact}: {matched!r}")
            if "--show" in sys.argv:
                print(f"           | {line}")

    print()
    if recalled:
        cases = sum(ln.startswith("- ") for _, t in recalled for ln in t.splitlines())
        print(
            f"OPEN BOOK: {cases} recalled item(s) from the case library are in this prompt. "
            "Whatever this run scores is not comparable to a run without them — an A/B "
            "has to use a fixture the library has never seen."
        )
    if hits:
        facts = sorted({h[1] for h in hits})
        print(
            f"{len(hits)} leak(s) across {len({h[0] for h in hits})} block(s): {', '.join(facts)}"
        )
        raise SystemExit(1)
    print("no answer tokens in anything handed to the model.")


if __name__ == "__main__":
    asyncio.run(main())
