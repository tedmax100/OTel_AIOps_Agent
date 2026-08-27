#!/usr/bin/env python3
"""Drive the second incident all the way round: alert → runbook → propose →
approve → execute → verify → *and then check what the incident learned*.

    python3 ironman-2026/day27/close_the_loop.py preflight
    python3 ironman-2026/day27/close_the_loop.py run          # drill (default)
    python3 ironman-2026/day27/close_the_loop.py run --no-drill
    python3 ironman-2026/day27/close_the_loop.py cleanup

Why another game day
--------------------
Day36 drove one real execution, on the payment bad-deploy, with `k8s.rollout_undo`.
Everything since — the case memory, the human's disproof, the runbook scorecard,
`cases.resolution` — was built on top of a loop that has been closed exactly once,
on one incident, with one action.

The session-cache incident is the harder shape and until today it had no way into
the loop at all: no runbook, and no action that could fix it (its cause is a flag,
not a revision, so `rollout_undo` is not merely wrong here — it is inapplicable).

The last section is the part Day36 could not have: after the executor reaches a
terminal state, this reads the case back and prints what the *next* run would be
handed. A loop that executes and verifies but writes nothing down is not a loop.

The drill flag, and why it is a real choice
-------------------------------------------
`--drill` (default) labels the alert `drill=true`. That keeps the run out of the
incident statistics — and, deliberately, out of the case memory: `remember_resolution`
and `_remember_failed_fix` both return early on a drill, because a rehearsal on a
fault somebody injected on purpose is not evidence about the real incident.

Which means a drill cannot exercise the learning half. On this cluster every
incident is injected, so "wait for a real one" is not a plan either. `--no-drill`
runs the same loop with the label off: the executor then treats it as a genuine
incident, `cases.resolution` gets written, and the ledger gains one row that says
an incident happened when a script caused it. That trade is not this script's to
make quietly, so it is a flag with a loud default, and the run prints which half
of the loop it is measuring.
"""

from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NS = "demo"
AGENT = "http://localhost:8000"
INCIDENT_SH = ROOT / "demo-services" / "scripts" / "incident.sh"
SCENARIO = "session-cache"
FLAG_CM = "user-flags"
FLAG = "user_session_cache_disabled"
# The flag file is projected from the ConfigMap; kubelet's sync period means the
# change is not visible to the process the moment kubectl returns.
PROJECTION_WAIT = 75


def sh(*args: str, check: bool = True) -> str:
    out = subprocess.run(args, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args)}\n{out.stderr.strip()}")
    return out.stdout.strip()


def http(
    method: str, url: str, body: dict | None = None, timeout: int = 30, headers: dict | None = None
) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw else {}


def log(msg: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def webhook_secret() -> str:
    raw = sh(
        "kubectl",
        "-n",
        NS,
        "get",
        "secret",
        "aiops-agent-secrets",
        "-o",
        "jsonpath={.data.webhook-secret}",
    )
    if not raw:
        raise SystemExit("aiops-agent-secrets has no webhook-secret; the webhook is disabled")
    return base64.b64decode(raw).decode().strip()


def flag_value() -> object:
    raw = sh(
        "kubectl", "-n", NS, "get", "configmap", FLAG_CM, "-o", r"jsonpath={.data.flags\.json}"
    )
    try:
        return json.loads(raw).get(FLAG)
    except json.JSONDecodeError:
        return None


# --- preflight --------------------------------------------------------------


def preflight() -> None:
    """Refuse to start a run whose result would not be worth trusting."""
    log("preflight: agent reachable?")
    health = http("GET", f"{AGENT}/healthz")
    log(f"  store: {health.get('store')}")

    act = health.get("actuation")
    if act is None:
        raise SystemExit(
            "preflight FAILED: /healthz has no actuation verdict — the deployed image "
            "predates the readiness probe. Rebuild and redeploy before running."
        )
    log(f"  actuation: proven_good={act['proven_good']} — {act['note']}")

    live = http("GET", f"{AGENT}/actions/readiness")
    if not live["verdict"]["proven_good"]:
        raise SystemExit(
            f"preflight FAILED: write credentials are not proven good ({live['verdict']['note']})."
        )
    log("  write credentials: live-probed OK")

    # The new action patches a ConfigMap, which the write SA could not do until
    # today's RBAC change. A deployment-only Role passes every check above and
    # then 403s at the one call this run exists to make.
    can = sh(
        "kubectl",
        "-n",
        NS,
        "auth",
        "can-i",
        "patch",
        f"configmap/{FLAG_CM}",
        "--as",
        f"system:serviceaccount:{NS}:aiops-agent-write",
        check=False,
    )
    if can.strip() != "yes":
        raise SystemExit(
            f"preflight FAILED: the write SA cannot patch configmap/{FLAG_CM} "
            f"(kubectl auth can-i said '{can.strip() or 'no'}'). Apply "
            "demo-services/k8s/15-aiops-agent.yaml — the flag action is a 403 without it."
        )
    log(f"  write SA may patch configmap/{FLAG_CM}")

    kill = sh(
        "kubectl",
        "-n",
        NS,
        "get",
        "deploy",
        "aiops-agent",
        "-o",
        "jsonpath={.spec.template.spec.containers[0].env[?(@.name=='ACTIONS_ENABLED')].value}",
    )
    if kill.lower() not in ("true", "1"):
        raise SystemExit(
            "preflight FAILED: ACTIONS_ENABLED is not true on the aiops-agent Deployment, "
            "so every execute terminates in REFUSED. Turn it on deliberately, run this, "
            "turn it off again. This script will not flip it for you."
        )
    log("  kill switch: ACTIONS_ENABLED=true (execution is live)")

    names = http("GET", f"{AGENT}/actions").get("actions", [])
    have = {a["name"] if isinstance(a, dict) else a for a in names}
    if "k8s.configmap_flag_set" not in have:
        raise SystemExit(
            "preflight FAILED: the deployed agent does not know k8s.configmap_flag_set. "
            "It is running an image from before today; rebuild and redeploy."
        )
    log("  deployed image knows k8s.configmap_flag_set")

    webhook_secret()
    log("  alert webhook secret: present")
    log(f"  {FLAG_CM}.{FLAG} is currently {flag_value()} (healthy = False)")


# --- traffic ----------------------------------------------------------------


class Traffic:
    """Requests through webapp for the whole run, because an idle cluster has no
    incident to remediate.

    The first run of this script had no traffic and still went green: no orders
    means no `orders_total`, no auth checks means no `user_auth_checks_total`,
    the verify query matched no series, and an empty result was read as zero.
    The fix for *that* is in the executor (an empty vector now fails closed);
    the fix for the drill is here. Both were needed — one of them stopped a
    false green, the other stopped a drill that proves nothing.
    """

    def __init__(self, rps: int = 5) -> None:
        self.rps = rps
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            ["bash", str(ROOT / "demo-services" / "scripts" / "load.sh"), str(self.rps)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log(f"traffic: ~{self.rps} rps through webapp (orders, carts, logins)")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            log("traffic: stopped")


def prom_has_series(metric: str, port: int = 9098) -> bool:
    """Is the symptom actually observable? Asked through a temporary
    port-forward, before the alert is posted rather than after the verify.

    A run whose metrics are missing can still produce a full green audit trail,
    which is precisely the thing not to discover from a passing drill."""
    pf = subprocess.Popen(
        ["kubectl", "-n", NS, "port-forward", "svc/prometheus", f"{port}:9090"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(4)
        with urllib.request.urlopen(
            f"http://localhost:{port}/api/v1/query?query={metric}", timeout=10
        ) as resp:
            data = json.load(resp)
        return bool(data.get("data", {}).get("result"))
    except Exception:
        return False
    finally:
        pf.terminate()


# --- the incident -----------------------------------------------------------


def inject() -> None:
    log(f"injecting {SCENARIO}: {FLAG}=true (auth checks fall through to the session store)")
    print(sh("bash", str(INCIDENT_SH), "start", SCENARIO))
    log(f"waiting {PROJECTION_WAIT}s for the projected flag file to land")
    time.sleep(PROJECTION_WAIT)
    if flag_value() is not True:
        raise SystemExit("the flag did not take; nothing to remediate")


def cleanup() -> None:
    log(f"cleanup: {FLAG}=false")
    print(sh("bash", str(INCIDENT_SH), "stop", SCENARIO))


def fire_alert(drill: bool) -> str:
    """Post a freshly-timestamped alert. Its own clock every time — a replayed
    startsAt turns the response-latency SLO into a count of how often somebody
    re-ran a script."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    labels = {
        "alertname": "order-cancel-rate-high",
        "service_name": "order-service",
        "severity": "critical",
        "namespace": NS,
    }
    if drill:
        labels |= {"drill": "true", "drill_scenario": SCENARIO}
    body = {
        "alerts": [
            {
                "status": "firing",
                "startsAt": now,
                "labels": labels,
                "annotations": {
                    "summary": "order-service cancellation rate above objective",
                    "description": "orders are being cancelled at the auth step",
                    "runbook_id": "session-cache-timeout",
                },
            }
        ]
    }
    http("POST", f"{AGENT}/webhook/alert", body, headers={"X-Webhook-Secret": webhook_secret()})
    log(f"alert posted (startsAt={now}, drill={drill})")
    return now


# --- driving ----------------------------------------------------------------


TERMINAL = {
    "succeeded",
    "verify_failed",
    "rolled_back",
    "rollback_failed",
    "failed",
    "aborted",
    "refused",
    "rejected",
    "expired",
}


def wait_for_request(since: str, timeout: int = 300) -> dict:
    log("waiting for the RCA to produce an ActionRequest…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        reqs = http("GET", f"{AGENT}/actions/requests").get("requests", [])
        fresh = [r for r in reqs if r.get("created_ts", "") >= since]
        if fresh:
            r = fresh[0]
            log(
                f"  request {r['request_id']} action={r['action']} "
                f"autonomy={r['autonomy']} status={r['status']}"
            )
            return r
        time.sleep(5)
    raise SystemExit(
        "no ActionRequest appeared. Check the agent logs: the RCA may have concluded "
        "without matching the runbook, or governance may have escalated instead."
    )


def drive(request_id: str, timeout: int = 600) -> dict:
    log(f"approving {request_id} (the human in human-in-the-loop)")
    http("POST", f"{AGENT}/actions/requests/{request_id}/approve", {"actor": "day41"})
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = http("GET", f"{AGENT}/actions/requests/{request_id}")
        req = r.get("request", r)
        if req.get("status") != last:
            last = req.get("status")
            log(f"  status: {last}")
        if last in TERMINAL:
            return req
        time.sleep(5)
    raise SystemExit("request never reached a terminal state — check the reconciler")


def show_evidence(request_id: str) -> None:
    trail = http("GET", f"{AGENT}/actions/audit?request_id={request_id}").get("audit", [])
    print("\n  phase          verdict      detail")
    print("  " + "-" * 72)
    for row in trail:
        detail = json.dumps(row.get("detail", {}), ensure_ascii=False)
        print(f"  {row['phase']:<14} {row['verdict']:<12} {detail[:84]}")
    print()


# --- the half Day36 could not check -----------------------------------------


def snapshot(tag: str) -> Path:
    pod = sh(
        "kubectl",
        "-n",
        NS,
        "get",
        "pod",
        "-l",
        "app=aiops-agent",
        "-o",
        "jsonpath={.items[0].metadata.name}",
    )
    out = HERE / f"store-{tag}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
    sh("kubectl", "-n", NS, "cp", f"{pod}:/data/aiops.db", str(out))
    log(f"snapshot: {out.name} ({out.stat().st_size} bytes)")
    return out


def what_the_case_learned(db: Path, request_id: str) -> None:
    """Read the incident back. The question is not "did it run" — the audit trail
    above answers that — it is whether anything is different the next time this
    alert fires."""
    print("\n---- what the incident learned " + "-" * 48 + "\n")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT case_key FROM action_requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    key = row["case_key"] if row else None
    print(f"  case key on the request: {key or '(none — the proposal was never keyed)'}")
    if not key:
        print("  Nothing can be written back without it; that is the finding.")
        return

    case = conn.execute("SELECT * FROM cases WHERE case_key = ?", (key,)).fetchone()
    if case is None:
        print("  No case row. The incident was investigated but never opened a case.")
        return
    res = case["resolution"]
    print(f"  occurrences: {case['occurrences']}   status: {case['status']}")
    print(f"  root_cause : {case['root_cause'] or '(none — nobody has confirmed one)'}")
    print(f"  resolution : {res or '(empty — nothing recorded what fixed it)'}")
    if res:
        r = json.loads(res)
        print(
            f"               action={r.get('action')} runbook={r.get('runbook_id')} "
            f"verified={r.get('verified')}"
        )
    # still_valid matters: a retracted dead end stays in the table as history and
    # is skipped by recall. Printing both without the distinction is how a run
    # reports nine live dead ends that nobody would ever be handed.
    ruled = conn.execute(
        "SELECT kind, subject, disproved_by, still_valid FROM case_ruled_out WHERE case_key = ?",
        (key,),
    ).fetchall()
    live = [r for r in ruled if r["still_valid"]]
    for r in live:
        print(f"  ruled out  : [{r['kind']}] {r['subject']} (by {r['disproved_by']})")
    retracted = len(ruled) - len(live)
    if retracted:
        print(f"  retracted  : {retracted} dead end(s) kept as history, not recalled")
    conn.close()


def next_run_context(service: str, alertname: str) -> None:
    """The recall block itself — what actually reaches the next prompt. Printed
    from the deployed agent, not recomputed here, because a local reconstruction
    would be a second implementation of the thing under test."""
    print("\n---- what the next run is handed " + "-" * 46 + "\n")
    try:
        out = http("GET", f"{AGENT}/cases/context?service={service}&alertname={alertname}")
    except Exception as e:
        print(f"  (no context endpoint on the deployed image: {type(e).__name__})")
        print("  Read it from the snapshot instead, or add the endpoint.")
        return
    text = out.get("context") or "(empty)"
    for line in text.splitlines():
        print(f"    {line}")


# --- entry point ------------------------------------------------------------


def run(drill: bool) -> int:
    preflight()
    before = snapshot("before")
    log(f"store snapshotted before the run: {before.name}")

    traffic = Traffic()
    traffic.start()

    try:
        inject()
        # Wait for the symptom to exist before paging anybody about it. Both
        # metrics have to be present: the alerting service's and the upstream
        # one the verify query reads, since it is the second that decides
        # whether this run ends in a real verdict or a vacuous one.
        for metric in ("orders_total", "user_auth_checks_total"):
            if not prom_has_series(metric):
                raise SystemExit(
                    f"preflight-after-injection FAILED: {metric} has no series in Prometheus. "
                    "The drill would run against an unobservable incident, which is how the "
                    "first run of this script went green while nothing was wrong."
                )
        log("symptom is observable: orders_total and user_auth_checks_total both have series")

        since = fire_alert(drill)
        req = wait_for_request(since)
        final = drive(req["request_id"])
        log(f"terminal state: {final['status']}  outcome={final.get('outcome', '')}")
        show_evidence(req["request_id"])

        after = snapshot("after")
        what_the_case_learned(after, req["request_id"])
        next_run_context("order-service", "order-cancel-rate-high")

        if drill:
            print("\n  This was a drill, so the learning half is expected to be empty:")
            print("  remember_resolution() returns early on drills by design. Re-run with")
            print("  --no-drill to exercise it, knowing that writes a real incident row.")

        expected = "succeeded"
        if final["status"] == expected:
            log(f"RESULT: as designed (expected {expected})")
            return 0
        log(f"RESULT: NOT as designed — expected {expected}, got {final['status']}")
        log("        That is a finding, not a script bug. Write it down before re-running.")
        return 1
    finally:
        traffic.stop()
        cleanup()


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight")
    r = sub.add_parser("run")
    r.add_argument(
        "--no-drill",
        dest="drill",
        action="store_false",
        default=True,
        help="run without the drill label, so the case memory records the fix",
    )
    sub.add_parser("cleanup")
    args = ap.parse_args()

    if args.cmd == "preflight":
        preflight()
        return 0
    if args.cmd == "cleanup":
        cleanup()
        return 0
    return run(args.drill)


if __name__ == "__main__":
    sys.exit(main())
