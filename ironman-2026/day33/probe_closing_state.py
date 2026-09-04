#!/usr/bin/env python3
"""The closing snapshot: every number Day33 quotes, re-derived in one read-only pass.

Day33 is the only article in the series that goes stale, because it describes a
system that is still moving. So rather than asking the reader to trust a date,
this prints the same figures live. If it disagrees with the article, the article
is the older of the two.

It reports four things, in the order the article needs them:

1. **Is this environment awake.** First, and deliberately so. An idle cluster,
   a one-hour retention window and a genuinely broken agent all produce the same
   report line ("that step returned nothing"), and I read the first as the third
   for several days. Every number below it is meaningless if this section is
   quiet, so it refuses to editorialise further when it is.
2. **The autonomy gates**, current values against their thresholds.
3. **Action effectiveness and its coverage.** The ratio's denominator used to be
   "actions somebody graded" rather than "actions that ran", which made every
   ungraded execution invisible instead of low-scoring. Coverage is printed
   beside every ratio for that reason.
4. **Proposal disposition** — what happened to the proposals nobody executed.
   Outside the ratio on purpose: nothing ran, so "did the fix work" has no
   referent. But `expired` means a person was asked and never answered, and that
   is worth reading somewhere.
5. **Override Rate and dispatch rate** (ARE ch11.5). The denominator here is the
   whole point: `aborted` rows are a pre-execution gate refusing, `actor='system'`
   in the audit trail, not a human overriding, and counting them as human
   decisions would inflate OR into looking healthy for the wrong reason.

    # against the running cluster (reads /data/aiops.db inside the pod)
    python3 ironman-2026/day33/probe_closing_state.py

    # against a local checkout instead
    python3 ironman-2026/day33/probe_closing_state.py --local

Read-only. It opens SQLite files and asks Prometheus one count query. Nothing
here writes, proposes or executes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

PROBE = r"""
import asyncio

from app import store
from app.config import settings
from app.governance import autonomy_status

W = 78


def rule(title):
    print()
    print("=" * W)
    print(title)
    print("=" * W)


# ---- 1. is anything writing to these stores at all -------------------------
# The article's whole closing argument is that an environment failure and a
# model failure are indistinguishable downstream, so this goes first.
rule("is this environment awake")
print()
try:
    # The underscore one, not the StructuredTool the agent is handed: the
    # wrapper is not callable from here, and going through it would also mean
    # this probe travels the agent's retry/diagnostic path instead of asking
    # the question straight.
    from app.tools.query import _query_prometheus

    series = asyncio.run(_query_prometheus('count({job=~".+"})', queryType="instant"))
    # The tool summarises before it returns, so `value` is already a float here
    # rather than Prometheus's [timestamp, "string"] pair.
    result = (series or {}).get("result") or []
    n = int(float(result[0]["value"])) if result else 0
except Exception as e:
    n = -1
    print(f"  could not ask Prometheus: {type(e).__name__}: {e}")

if n < 0:
    print("  UNKNOWN — treat everything below as unverified")
elif n < 100:
    print(f"  QUIET — only {n} series. An idle cluster answers every question with")
    print("  'nothing came back', which is also what a broken agent looks like.")
    print("  Start the load generator before reading anything below as a result.")
else:
    print(f"  awake — {n} series are being written")

# ---- 2. the gates ----------------------------------------------------------
rule("the autonomy gates")
print()
st = autonomy_status()
print(f"  granted={st.get('granted')}  actions_enabled={st.get('actions_enabled')}")
print()
for g in st.get("gates") or []:
    print(f"  {'PASS' if g['proven_good'] else 'FAIL'}  {g['gate']:<16} {g['note']}")
cal = st.get("calibration") or {}
if cal:
    print()
    for now, need, label in (
        ("labeled", "labeled_required", "labeled runs"),
        ("human_labeled", "human_labeled_required", "human/grader labels"),
        ("band_accuracy", "band_accuracy_required", "accuracy in the high band"),
    ):
        print(f"    {label:<26} {cal.get(now)}  (need {cal.get(need)})")
    print(f"    {'mean overconfidence':<26} {cal.get('overconfidence')}  "
          f"(max {cal.get('overconfidence_max')})")
    print(f"    {'worst bin gap':<26} {cal.get('worst_bin_gap')}  "
          f"(max {cal.get('worst_bin_gap_max')})")

# ---- 3. did the actions work, and how much of them we actually judged ------
rule("action effectiveness, and how much of it has been graded")
print()
slo = store.ae_slo()
for arm in ("incidents", "drills"):
    a = slo[arm]
    cov = a["coverage"]
    print(f"  {arm:<10} effective {a['raw']:<6} rate={a['rate']}")
    print(f"  {'':<10} ran {cov['ran']}, graded {cov['graded']}, "
          f"ungraded {cov['ungraded']}  (coverage {cov['fraction']})")
    if a.get("note"):
        print(f"  {'':<10} {a['note']}")
    print()
print(f"  verify vs the on-call: {slo['verify_agreement']['note']}")

pending = store.ungraded_actions(limit=50)
print()
print(f"  waiting on a human verdict: {len(pending)}")
for r in pending:
    kind = "drill" if r["drill"] else "REAL "
    print(f"    {kind}  {r['request_id']}  {r['action']:<24} {r['status']:<16} {r['created_ts']}")

# ---- 4. what happened to the proposals nobody ran --------------------------
rule("proposals (outside the ratio above: nothing ran)")
print()
d = store.proposal_disposition()
for status, count in sorted(d["by_status"].items()):
    print(f"  {status:<18} {count}")
print()
print(f"  expiry rate {d['expiry_rate']}  — {d['note']}")

# ---- 5. Override Rate / dispatch rate (ARE ch11.5) --------------------------
rule("override rate (ARE ch11.5) — the denominator is the point")
print()
o = store.override_rate()
print(f"  total proposals            {o['total']}")
print(f"  dispatched to a human      {o['dispatched']}   (dispatch rate {o['dispatch_rate']})")
print(f"  rejected                   {o['rejected']}   (override rate {o['override_rate']})")
print(f"  system aborts (excluded)   {o['system_aborts_excluded_from_denominator']}")
print(f"  {o['note']}")

print()
print(f"  (fixture record window is {settings.governance_fixture_max_age_days}d)")
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local", action="store_true", help="run against the checkout, not the pod")
    ap.add_argument("--namespace", default="demo")
    args = ap.parse_args()

    if args.local:
        cmd = ["python3", "-c", PROBE]
        cwd = "aiops-agent/service"
    else:
        cmd = [
            "kubectl", "exec", "-n", args.namespace, "deploy/aiops-agent",
            "--", "python3", "-c", PROBE,
        ]
        cwd = None
    return subprocess.call(cmd, cwd=cwd)


if __name__ == "__main__":
    sys.exit(main())
