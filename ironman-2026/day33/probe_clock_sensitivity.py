#!/usr/bin/env python3
"""Vary only the clock, and see how much of the +-67pp it explains.

Day39 ended on a measurement and an arithmetic argument. The measurement: three
passes inside one container gave 0% spread on all five fixtures — at temperature
0, against a byte-identical prompt, the model returns the same verdict. The
argument: the swings that were actually observed (`order-service-auth-degradation`
control arm, 3/3 in one experiment and 0/3 in the next, on untouched code) sat
between *invocations*, and every invocation booted its own container with
`scenario_time = now`. The generator is seeded, so the data is structurally
identical between boots and differs only by a shift of the whole timeline — but
those absolute timestamps are in the alert, in the pinned clock, and in every
window the agent computes.

That was an argument, not a result. This runs the experiment it implies: hold
the image, the fixture, the store and the code, and move *only* the scenario
time. Whatever spread comes out is attributable to the clock and to nothing
else.

The clocks are deliberately not adjacent minutes. `--times` takes ISO instants;
the default set walks a scenario day so the incident lands at a different hour,
a different minute-of-hour and across a UTC date boundary, which is the shape of
input that should not matter and (Day39's claim) does.

    # one fixture, the default four clocks
    python3 ironman-2026/day33/probe_clock_sensitivity.py --only order-service-auth-degradation

    # what will run, without spending a boot or a token
    python3 ironman-2026/day33/probe_clock_sensitivity.py --only ... --dry-run

Each clock is one full boot plus one pass, so budget minutes and API calls per
entry in `--times`. Uses a dedicated store so it never writes the prod library.
"""

from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
DEFAULT_STORE = SERVICE / "app" / "eval" / "clock-probe.db"
# The eval imports the agent, so it needs the service's own environment —
# the interpreter running this probe does not have langchain installed.
VENV_PY = SERVICE / ".venv" / "bin" / "python"

# A scenario day, not four adjacent minutes: different hour, different
# minute-of-hour, and one crossing midnight UTC.
DEFAULT_TIMES = (
    "2026-08-19T04:11:00Z",
    "2026-08-19T12:37:00Z",
    "2026-08-19T21:53:00Z",
    "2026-08-20T00:29:00Z",
)

_SCORE = re.compile(r"^\s*(?P<id>[a-z0-9-]+)\s+(?P<pct>\d+)%\s+\((?P<hit>\d+)/(?P<n>\d+)\)")


def run_one(
    scenario_time: str, only: str | None, store: Path, seeds: int
) -> dict[str, tuple[int, int]]:
    """One boot at one clock. Returns {fixture_id: (hits, runs)}."""
    python = str(VENV_PY) if VENV_PY.exists() else sys.executable
    cmd = [
        python,
        "-m",
        "app.eval",
        "run",
        "--stack",
        "--scenario-time",
        scenario_time,
        "--store",
        str(store),
        "-n",
        str(seeds),
    ]
    if only:
        cmd += ["--only", only]
    proc = subprocess.run(cmd, cwd=SERVICE, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stderr.write(proc.stderr)
    scores: dict[str, tuple[int, int]] = {}
    for line in proc.stdout.splitlines():
        m = _SCORE.match(line)
        if m:
            scores[m["id"]] = (int(m["hit"]), int(m["n"]))
    return scores


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="fixture id (default: the whole suite)")
    ap.add_argument("--times", nargs="+", default=list(DEFAULT_TIMES))
    ap.add_argument(
        "-n",
        "--seeds",
        type=int,
        default=1,
        help="seeds per fixture; Day39 measured these as correlated, keep at 1",
    )
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if len(args.times) < 2:
        print("need at least two clocks to measure a spread", file=sys.stderr)
        return 2

    print(
        f"clock sensitivity — {len(args.times)} boots, "
        f"fixture(s): {args.only or 'all'}, store {args.store}"
    )
    for t in args.times:
        print(f"  clock {t}")
    if args.dry_run:
        print("\n(dry run — nothing booted)")
        return 0

    per_clock: dict[str, dict[str, tuple[int, int]]] = {}
    for t in args.times:
        print(f"\n=== scenario time {t} " + "=" * 40)
        per_clock[t] = run_one(t, args.only, args.store, args.seeds)

    fixtures = sorted({f for s in per_clock.values() for f in s})
    if not fixtures:
        print("\nno fixture scores parsed — did the stack boot?", file=sys.stderr)
        return 1

    print("\n---- one variable moved: the clock " + "-" * 45 + "\n")
    widest = 0.0
    for fid in fixtures:
        rates = []
        cells = []
        for t in args.times:
            hit_n = per_clock[t].get(fid)
            if hit_n is None:
                cells.append("  --  ")
                continue
            hit, n = hit_n
            rates.append(100.0 * hit / n if n else 0.0)
            cells.append(f"{hit}/{n}")
        if not rates:
            continue
        spread = max(rates) - min(rates)
        widest = max(widest, spread)
        mean = statistics.mean(rates)
        print(
            f"  {fid:<38} {' '.join(f'{c:>6}' for c in cells)}"
            f"   mean {mean:5.1f}%  spread {spread:5.1f}pp"
        )

    print(f"\n  Widest spread across clocks: {widest:.1f}pp.")
    print("  Day39 measured 0pp between passes inside one container. Anything")
    print("  above that here is the scenario clock, not the model — the same input")
    print("  sensitivity a real on-call run has when the incident happens at 04:00")
    print("  instead of 12:00, and not something more seeds will average away.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
