#!/usr/bin/env python3
"""Ask all three signals who is alive, then check that against the declared
topology — a scheduled job, not something you run by hand.

    python3 ironman-2026/day14/topology_watch.py \
        --topology aiops-agent/service/app/signals/topology.yaml \
        --loki http://localhost:3100 \
        --prom http://localhost:9090 \
        --tempo http://localhost:3200 \
        --lookback 6h

Why three sources: each store keeps its own idea of the service set, and they
disagree. A service that stopped shipping logs still shows up in Prometheus. A
discovery function that reads one store can only ever notice the drift that
store happens to see.

Exit codes (for cron / CI):
    0  declared set matches the live set
    1  drift — something is declared-but-dead or live-but-undeclared
    2  can't tell — no source answered, so silence is not evidence
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

import yaml


def _get(base: str, path: str, params: dict) -> dict:
    url = f"{base.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def from_loki(base: str, start_s: int, end_s: int) -> set[str]:
    # Loki wants nanoseconds, and without a range it answers with an empty list
    # rather than an error (see the aiops-native-api-behaviors note).
    d = _get(
        base,
        "/loki/api/v1/label/service_name/values",
        {"start": start_s * 10**9, "end": end_s * 10**9},
    )
    return set(d.get("data") or [])


def from_prometheus(base: str, start_s: int, end_s: int) -> set[str]:
    d = _get(base, "/api/v1/label/service_name/values", {"start": start_s, "end": end_s})
    return set(d.get("data") or [])


def from_tempo(base: str, start_s: int, end_s: int) -> set[str]:
    d = _get(
        base,
        "/api/v2/search/tag/resource.service.name/values",
        {"start": start_s, "end": end_s},
    )
    return {v.get("value") for v in (d.get("tagValues") or []) if v.get("value")}


SOURCES = {"loki": from_loki, "prometheus": from_prometheus, "tempo": from_tempo}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--topology", required=True)
    p.add_argument("--loki")
    p.add_argument("--prom")
    p.add_argument("--tempo")
    p.add_argument("--lookback", default="6h", help="e.g. 30m, 6h, 2d")
    a = p.parse_args()

    unit = {"m": 60, "h": 3600, "d": 86400}[a.lookback[-1]]
    end = int(time.time())
    start = end - int(a.lookback[:-1]) * unit

    declared = {n["name"] for n in yaml.safe_load(open(a.topology))["nodes"]}

    seen: dict[str, set[str]] = {}
    for name, url in (("loki", a.loki), ("prometheus", a.prom), ("tempo", a.tempo)):
        if not url:
            continue
        try:
            seen[name] = SOURCES[name](url, start, end)
        except Exception as e:
            print(f"  ! {name} did not answer ({e}) — treating it as no evidence")

    print(f"# topology watch — declared {len(declared)}, lookback {a.lookback}")
    if not seen:
        print("  no source answered; cannot tell alignment from silence")
        return 2

    for name in sorted(seen):
        print(f"  {name:<11} sees {len(seen[name]):>2}: {', '.join(sorted(seen[name]))}")

    live = set().union(*seen.values())
    # A service only one store knows about is the interesting case: it is alive,
    # but whichever discovery source you picked may not have told you.
    partial = {s: sorted(n for n in seen if s in seen[n]) for s in live if s not in declared}
    for s in sorted(live):
        holders = [n for n in seen if s in seen[n]]
        if len(holders) < len(seen):
            missing = sorted(set(seen) - set(holders))
            print(f"  ~ '{s}' is missing from {', '.join(missing)} but present in others")

    drift = False
    for n in sorted(declared - live):
        print(f"  ✗ declared '{n}' not present in any signal")
        drift = True
    for n in sorted(live - declared):
        print(f"  ✗ live '{n}' is not declared (seen by {', '.join(partial[n])})")
        drift = True

    if not drift:
        print(f"  ✓ declared set matches the live set ({len(live)} services)")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
