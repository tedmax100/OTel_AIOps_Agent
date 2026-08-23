#!/usr/bin/env python3
"""Is the second incident actually visible, and visible in the right places?

The `session-cache` scenario is only worth having if the telemetry tells the
story it claims to: the symptom on order-service, the cause one hop upstream on
user-service, and nothing in between that shortcuts the walk. This checks that
against a live cluster rather than against the code that emits it.

It also checks the half that is easy to forget: that the answer is NOT sitting
somewhere the agent gets for free. A scenario whose culprit is named in the
prompt is a scenario that measures nothing.

    kubectl -n demo port-forward svc/prometheus 9090:9090 &
    kubectl -n demo port-forward svc/loki 3100:3100 &
    python3 ironman-2026/day32/verify_incident.py

Expects `scripts/incident.sh start session-cache` to have been running long
enough for the projected flag to land and for traffic to have gone through.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROM = "http://localhost:9090"
LOKI = "http://localhost:3100"
WINDOW = "15m"

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]


def prom(query: str) -> list[tuple[dict, float]]:
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    with urllib.request.urlopen(url, timeout=15) as r:
        body = json.load(r)
    return [(m["metric"], float(m["value"][1])) for m in body["data"]["result"]]


def loki(query: str, minutes: int = 15) -> list[tuple[dict, float]]:
    end = int(time.time())
    params = {
        "query": query,
        "start": f"{(end - minutes * 60) * 10**9}",
        "end": f"{end * 10**9}",
        "step": f"{minutes * 60}",
    }
    url = f"{LOKI}/loki/api/v1/query_range?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        body = json.load(r)
    out = []
    for m in body["data"]["result"]:
        values = m.get("values") or []
        out.append((m["metric"], float(values[-1][1]) if values else 0.0))
    return out


def show(title: str, rows: list[tuple[dict, float]]) -> None:
    print(f"\n  {title}")
    if not rows:
        print("      (nothing)")
        return
    for labels, value in sorted(rows, key=lambda r: -r[1]):
        pretty = " ".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "__name__")
        print(f"      {pretty or '(no labels)':60} {value:.3f}")


def main() -> int:
    print("[1] the symptom, on the service that alerted")
    show(
        f"orders_total by outcome, {WINDOW}",
        prom(f"sum by (status, reason) (increase(orders_total[{WINDOW}]))"),
    )
    p95_order = (
        "histogram_quantile(0.95, sum by (le) "
        f"(rate(order_create_duration_seconds_bucket[{WINDOW}])))"
    )
    show("order-service p95", prom(p95_order))

    print("\n[2] nothing here names the cause — that is the point")
    print("    order-service's own labels say `reason=auth`, and stop there.")

    print("\n[3] the cause, one hop upstream")
    show(
        f"user_auth_checks_total by outcome, {WINDOW}",
        prom(f"sum by (status, reason) (increase(user_auth_checks_total[{WINDOW}]))"),
    )
    p95_auth = (
        "histogram_quantile(0.95, sum by (le) "
        f"(rate(user_authcheck_duration_seconds_bucket[{WINDOW}])))"
    )
    show("user-service authcheck p95", prom(p95_auth))

    print("\n[4] the same story in logs")
    show(
        "user-service events",
        # The `event=~` filter is not cosmetic: without a label filter after
        # `| json`, Loki rejects the query outright (400) rather than grouping
        # over whatever the parser found.
        loki(
            "sum by (event) (count_over_time("
            '{service_name="user-service"} | json '
            '| event=~"cache.miss|user.auth_failed|user.logged_in" [15m]))'
        ),
    )

    print("\n[5] is the answer being given away?")
    # The vocabulary block is compiled from the registry, which now carries this
    # incident's reason value. `render_vocabulary` emits label *names* only —
    # this asserts that, rather than trusting the docstring that says so.
    sys.path.insert(0, str(ROOT / "aiops-agent" / "service"))
    from app.signals.vocabulary import render_vocabulary

    catalog = (ROOT / "aiops-agent" / "service" / "app" / "schema_catalog.md").read_text()
    block = render_vocabulary() or ""
    leaked = False
    for token in (
        "session_store_timeout",
        "user_session_cache_disabled",
        "session cache",
        "session store",
    ):
        in_vocab = token.lower() in block.lower()
        in_catalog = token.lower() in catalog.lower()
        leaked = leaked or in_vocab or in_catalog
        print(f"      {token:30} vocabulary={in_vocab!s:5} catalog={in_catalog!s:5}")
    verdict = (
        "      LEAKED — this scenario measures retrieval, not reasoning"
        if leaked
        else "      clean — the agent has to walk the hop"
    )
    print("\n" + verdict)
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
