#!/usr/bin/env python3
"""Answer 'am I talking to the Tempo I think I am, and does it have anything
worth reconciling against?' before trusting a topology-drift report.

    python3 ironman-2026/day15/tempo_probe.py http://localhost:3210 [lookback_s]

Prints the build info (which Tempo this really is), how many traces are in the
window, and how those split between health probes and real application traffic.
An empty drift report means nothing until you know which of these is true:
the graph is wrong, or there was simply no traffic to observe.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request


def _get(base: str, path: str, params: dict | None = None) -> dict:
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main(base: str, lookback_s: int) -> int:
    try:
        info = _get(base, "/api/status/buildinfo")
    except Exception as e:
        print(f"{base}: no Tempo answering ({e})")
        return 1
    print(f"{base} → Tempo {info.get('version')} (rev {info.get('revision')})")

    end = int(time.time())
    start = end - lookback_s
    limit = 500
    window = {"start": start, "end": end, "limit": limit}

    def search(q: str) -> tuple[list[dict], bool]:
        got = _get(base, "/api/search", {"q": q, **window}).get("traces", [])
        return got, len(got) >= limit  # capped → the count is a floor, not a total

    everything, capped_all = search("{}")
    if not everything:
        print(f"  last {lookback_s}s: nothing at all — is anything sending to this Tempo?")
        return 0

    # The same server-side filter reconcile uses to skip sub-ms health probes.
    real, capped_real = search("{ trace:duration > 5ms }")

    def n(count: int, capped: bool) -> str:
        return f"{'≥' if capped else ''}{count}"

    print(f"  last {lookback_s}s: {n(len(everything), capped_all)} traces")
    print(f"    slowest seen           : {max(int(t.get('durationMs', 0)) for t in everything)}ms")
    print(f"    survives the >5ms filter: {n(len(real), capped_real)}")
    if capped_all or capped_real:
        print(f"    (limit={limit} hit — counts are floors; shorten the window to compare them)")
    if not real:
        print("    ⚠ reconcile would sample 0 traces here and report every declared")
        print("      edge as unobserved. That is 'no traffic', not 'the graph is wrong'.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1].rstrip("/"), int(sys.argv[2]) if len(sys.argv) > 2 else 900))
