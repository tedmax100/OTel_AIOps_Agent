#!/usr/bin/env python3
"""Game Day: drive one real execution through execute → settle → verify → rollback.

    uv run python ironman-2026/day36/gameday.py plan
    uv run python ironman-2026/day36/gameday.py run --scenario a
    uv run python ironman-2026/day36/gameday.py run --scenario b
    uv run python ironman-2026/day36/gameday.py cleanup

Why this script exists
----------------------
The executor's whole back half — settle window, verify query, auto-rollback,
outcome → calibration — has been code-complete and unit-tested for weeks, and has
never once been run by a real input. The `executions` ledger holds exactly one
row, `success=0`, and that failure was a 401 from Kubernetes. So ARR, DQ-SLO and
AE-SLO are not "hard to measure" — their denominators are zero, and a system that
has never successfully executed anything is a proposal system.

The only way to move that is to make the thing happen on purpose, under
supervision, with the outcome recorded. That is what a game day is.

Two scenarios, and the second one matters more
----------------------------------------------
Both produce the *same symptom* (a decline-rate spike on payment-service) from
*different root causes*, and `k8s.rollout_undo` can only fix one of them:

  a. bad-deploy      the bad flag file arrives via the pod template (a new
                     ReplicaSet), so rolling back the Deployment removes it.
                     Expected terminal state: SUCCEEDED (verify passes).

  b. bad-config      the bad flag arrives via the `payment-flags` ConfigMap,
                     which a Deployment rollback does not touch. The rollback
                     runs, the symptom persists, verify fails, auto-rollback
                     puts the revision back.
                     Expected terminal state: ROLLED_BACK.

A drill that only runs (a) proves nothing: an AE-SLO of 100% measured on
hand-picked successes is exactly as uninformative as the 0% we have now. (b) is
the one that shows the safety net catching a *correct-looking but wrong* action.

What this script will and will not do
-------------------------------------
It never flips the kill switch. `actions_enabled` lives in the Deployment's env,
so turning execution on is a deliberate, visible, human change (see README).
This script refuses to run if it is off, rather than helpfully enabling it.

Everything it changes in the cluster is reverted by `cleanup`, and it snapshots
the store before and after, because the thing being measured lives in that
database.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

AGENT = "http://localhost:8000"
PAYMENT = "http://localhost:8001"
NS = "demo"
DEPLOY = "payment-service"
HERE = Path(__file__).parent
BAD_FLAGS_MANIFEST = HERE / "k8s" / "payment-flags-bad.yaml"
# The canonical template for the service under test. Cleanup re-applies this
# instead of trying to reverse its own patches.
PAYMENT_MANIFEST = HERE.parents[2] / "demo-services" / "k8s" / "20-payment-service.yaml"
# What the deployment looked like before we touched it. `cleanup` runs as a
# separate invocation, so "put it back" has to survive process exit — and it must
# put back what was actually there. The cluster is currently sitting on
# git_version v2.5.0 from an older hand-run incident, so a cleanup that restored
# a hardcoded v2.4.1 would quietly "fix" something this drill never broke.
STATE = HERE / ".drill-state.json"


def drill_version() -> str:
    """A distinct version per drill run, because each run really is a distinct
    deploy.

    The incident fingerprint is `alertname|service|git_version`, and idempotency
    keys on it: two drills sharing a version are, correctly, the same incident,
    and the second one gets refused as a duplicate of the first. Rather than
    weakening the guard for the convenience of the rehearsal, give the rehearsal
    what it actually is — a new bad version each time.
    """
    return f"v2.5.1-drill-{datetime.now(UTC).strftime('%H%M%S')}"


# Enough odd-cent charges that a 2-minute rate() has something to say, and few
# enough that we are not the load test.
TRAFFIC_RPS = 5


# --- small helpers ---------------------------------------------------------


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


def webhook_secret() -> str:
    """The alert webhook is fail-closed: no secret, no RCA. Read it from the
    cluster at run time rather than taking it as an argument, so the drill can't
    be run against a stale copy of it and so it never lands in shell history."""
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


def log(msg: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


# --- traffic ---------------------------------------------------------------


class Traffic(threading.Thread):
    """Odd-cent charges, which is the only input the new validator declines.

    The demo's own `load.sh` always sends even amounts, so a drill that reused it
    would inject a broken deploy and then measure a decline rate of zero — the
    incident would be real and completely invisible.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()
        self.sent = 0
        self.declined = 0

    def run(self) -> None:
        n = 0
        while not self.stop_flag.is_set():
            n += 1
            try:
                http(
                    "POST",
                    f"{PAYMENT}/charge",
                    {
                        "order_id": f"drill-{n}",
                        "user_id": "drill",
                        "amount_cents": 2 * n + 1,  # always odd
                        "currency": "TWD",
                    },
                    timeout=5,
                )
            except urllib.error.HTTPError as e:
                if e.code == 402:
                    self.declined += 1
            except Exception:
                pass
            self.sent += 1
            time.sleep(1 / TRAFFIC_RPS)


# --- preflight -------------------------------------------------------------


def preflight() -> None:
    """Refuse to start a drill whose result we would not be able to trust."""
    log("preflight: agent reachable?")
    health = http("GET", f"{AGENT}/healthz")
    log(f"  store: {health.get('store')}")

    act = health.get("actuation")
    if act is None:
        raise SystemExit(
            "preflight FAILED: /healthz has no actuation verdict — the deployed image "
            "predates the readiness probe. Rebuild and redeploy (aiops-agent/scripts/deploy.sh) "
            "before drilling; the last real execution died on exactly this blind spot."
        )
    log(f"  actuation: proven_good={act['proven_good']} — {act['note']}")

    live = http("GET", f"{AGENT}/actions/readiness")
    if not live["verdict"]["proven_good"]:
        raise SystemExit(
            f"preflight FAILED: write credentials are not proven good "
            f"({live['verdict']['note']}). Fix the credential first — a drill that "
            f"401s measures the token, not the pipeline."
        )
    log("  write credentials: live-probed OK")

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
            "so every execute will terminate in REFUSED. Turn it on deliberately (README), "
            "run the drill, turn it off again. This script will not flip it for you."
        )
    log("  kill switch: ACTIONS_ENABLED=true (execution is live)")
    webhook_secret()  # fail here, not after the incident is already injected
    log("  alert webhook secret: present")


# --- injection -------------------------------------------------------------


def git_version() -> str:
    return sh(
        "kubectl",
        "-n",
        NS,
        "get",
        "deploy",
        DEPLOY,
        "-o",
        "jsonpath={.spec.template.metadata.labels.git_version}",
    )


def flags_json() -> str:
    return sh(
        "kubectl",
        "-n",
        NS,
        "get",
        "configmap",
        "payment-flags",
        "-o",
        "jsonpath={.data.flags\\.json}",
    )


def save_state() -> None:
    STATE.write_text(
        json.dumps(
            {
                "git_version": git_version(),
                "flags_json": flags_json(),
                "flags_path": sh(
                    "kubectl",
                    "-n",
                    NS,
                    "get",
                    "deploy",
                    DEPLOY,
                    "-o",
                    "jsonpath={.spec.template.spec.containers[0]"
                    ".env[?(@.name=='FEATURE_FLAGS_PATH')].value}",
                ),
                "revision": current_revision(),
                # Re-applying the manifest resets `replicas` to whatever the file
                # says, silently undoing any scale the cluster was actually
                # running. That happened: the deployment went 2 → 1, and the next
                # action was refused because a single-replica target is a
                # singleton and policy refuses those. Cleanup restores what was
                # there, not what the file wishes were there.
                "replicas": sh(
                    "kubectl",
                    "-n",
                    NS,
                    "get",
                    "deploy",
                    DEPLOY,
                    "-o",
                    "jsonpath={.spec.replicas}",
                ),
                # Recorded before injection so the alert, the injection and the
                # cleanup all agree on which version this drill created.
                "drill_version": drill_version(),
            },
            indent=2,
        )
    )


def current_revision() -> str:
    return sh(
        "kubectl",
        "-n",
        NS,
        "get",
        "deploy",
        DEPLOY,
        "-o",
        "jsonpath={.metadata.annotations.deployment\\.kubernetes\\.io/revision}",
    )


def inject_a() -> None:
    """Bad deploy: the bad flag file ships *in the pod template*.


    Mount a second ConfigMap and repoint FEATURE_FLAGS_PATH at it, plus the
    version bump that makes this look like a deploy. All of it lives in the
    template, so the previous ReplicaSet is genuinely a good state to go back to
    — which is what makes `rollout undo` the right fix here."""
    sh("kubectl", "apply", "-f", str(BAD_FLAGS_MANIFEST))
    version = json.loads(STATE.read_text())["drill_version"]
    patch = {
        "spec": {
            "template": {
                "metadata": {"labels": {"git_version": version}},
                "spec": {
                    "containers": [
                        {
                            "name": "payment",
                            "env": [
                                {
                                    "name": "FEATURE_FLAGS_PATH",
                                    "value": "/etc/demo-bad/flags.json",
                                }
                            ],
                            "volumeMounts": [{"name": "bad-flags", "mountPath": "/etc/demo-bad"}],
                        }
                    ],
                    "volumes": [{"name": "bad-flags", "configMap": {"name": "payment-flags-bad"}}],
                },
            }
        }
    }
    sh("kubectl", "-n", NS, "patch", "deploy", DEPLOY, "--type=strategic", "-p", json.dumps(patch))
    sh("kubectl", "-n", NS, "rollout", "status", f"deploy/{DEPLOY}", "--timeout=120s")


def inject_b() -> None:
    """Bad config: the bad flag ships in the ConfigMap the *good* template mounts.

    `rollout undo` will faithfully restore the previous pod template and change
    nothing about the symptom, because the symptom was never in the template.
    This is the case the verify step exists for."""
    sh(
        "kubectl",
        "-n",
        NS,
        "patch",
        "configmap",
        "payment-flags",
        "--type=merge",
        "-p",
        json.dumps({"data": {"flags.json": '{"payment_use_new_validator": true}'}}),
    )
    # Flags are read at startup, so the ConfigMap change alone changes nothing.
    # The version bump is only here to give this drill its own fingerprint; the
    # bad state is still entirely in the ConfigMap, which is the whole point.
    version = json.loads(STATE.read_text())["drill_version"]
    sh(
        "kubectl",
        "-n",
        NS,
        "patch",
        "deploy",
        DEPLOY,
        "--type=strategic",
        "-p",
        json.dumps({"spec": {"template": {"metadata": {"labels": {"git_version": version}}}}}),
    )
    sh("kubectl", "-n", NS, "rollout", "status", f"deploy/{DEPLOY}", "--timeout=120s")


def cleanup() -> None:
    """Put payment-service back, by re-applying its manifest rather than by
    un-patching it.

    The first version of this un-patched what it had patched, which cannot remove
    a list entry: `kubectl delete configmap payment-flags-bad` succeeded, the
    `bad-flags` *volume* stayed in the pod template, and every pod created after
    that sat in ContainerCreating with FailedMount forever. The running pods were
    fine, so the Deployment looked healthy — right up until something needed a new
    one.

    Worse, cleanup reported success anyway, because `rollout status` was called
    with check=False. A cleanup that cannot fail is not a cleanup. It is checked
    now, and the manifest is the source of truth for the template.
    """
    if not STATE.exists():
        raise SystemExit(
            f"no {STATE.name}: this drill never recorded a pre-injection state, so "
            "cleanup would be guessing what to restore. Check the cluster by hand."
        )
    before = json.loads(STATE.read_text())
    log(f"cleanup: restoring git_version={before['git_version']} flags={before['flags_json']}")

    # `kubectl apply` will NOT drop the injected volume: three-way merge only
    # removes fields present in last-applied-configuration, and this one arrived
    # by patch, so apply does not own it. A list entry has to be deleted by name,
    # explicitly, with the strategic-merge `$patch: delete` directive.
    sh(
        "kubectl",
        "-n",
        NS,
        "patch",
        "deploy",
        DEPLOY,
        "--type=strategic",
        "-p",
        json.dumps(
            {
                "spec": {
                    "template": {
                        "spec": {
                            "volumes": [{"name": "bad-flags", "$patch": "delete"}],
                            "containers": [
                                {
                                    "name": "payment",
                                    # volumeMounts merge on mountPath, not name.
                                    "volumeMounts": [
                                        {"mountPath": "/etc/demo-bad", "$patch": "delete"}
                                    ],
                                }
                            ],
                        }
                    }
                }
            }
        ),
    )
    sh("kubectl", "apply", "-f", str(PAYMENT_MANIFEST))
    sh(
        "kubectl",
        "-n",
        NS,
        "patch",
        "configmap",
        "payment-flags",
        "--type=merge",
        "-p",
        json.dumps({"data": {"flags.json": before["flags_json"]}}),
    )
    sh(
        "kubectl",
        "-n",
        NS,
        "patch",
        "deploy",
        DEPLOY,
        "--type=strategic",
        "-p",
        json.dumps(
            {"spec": {"template": {"metadata": {"labels": {"git_version": before["git_version"]}}}}}
        ),
    )
    sh("kubectl", "-n", NS, "delete", "configmap", "payment-flags-bad", "--ignore-not-found")
    # A state file written by an older run has no replica count; leaving the
    # scale alone is the honest fallback, and it must not abort a cleanup that
    # has already re-applied the manifest.
    if before.get("replicas"):
        sh("kubectl", "-n", NS, "scale", "deploy", DEPLOY, f"--replicas={before['replicas']}")
    sh("kubectl", "-n", NS, "rollout", "restart", f"deploy/{DEPLOY}")
    sh("kubectl", "-n", NS, "rollout", "status", f"deploy/{DEPLOY}", "--timeout=180s")
    replicas = before.get("replicas", "unchanged")
    log(f"cleanup: done (git_version={git_version()}, replicas={replicas}, flags={flags_json()})")


# --- the alert -------------------------------------------------------------


def fire_alert(scenario: str) -> str:
    """Post a freshly-timestamped alert to the agent's webhook.

    Deliberately *not* a replay of the alert JSON that has been sitting in this
    repo since June: eight of the eleven RL-SLO samples share one `startsAt`
    because that file kept getting replayed, so the latency SLO ended up
    measuring how many times someone re-ran a script. Every drill gets its own
    clock, and a `drill` label so these rows can be excluded from incident stats.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "alerts": [
            {
                "status": "firing",
                "startsAt": now,
                "labels": {
                    "alertname": "payment-decline-rate-high",
                    "service_name": "payment-service",
                    "git_version": json.loads(STATE.read_text())["drill_version"],
                    "severity": "critical",
                    "namespace": NS,
                    "drill": "true",
                    "drill_scenario": scenario,
                },
                "annotations": {
                    "summary": "payment-service decline rate above objective",
                    "description": "declined charges spiked after the most recent change",
                    "runbook_id": "payment-bad-deploy",
                },
            }
        ]
    }
    http("POST", f"{AGENT}/webhook/alert", body, headers={"X-Webhook-Secret": webhook_secret()})
    log(f"alert posted (startsAt={now}, drill_scenario={scenario})")
    return now


# --- driving the request ---------------------------------------------------


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
        "no ActionRequest appeared within the timeout. Check the agent logs: the RCA "
        "may have concluded without matching the runbook, or governance escalated."
    )


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


def drive(request_id: str, timeout: int = 600) -> dict:
    log(f"approving {request_id} (this is the human in human-in-the-loop)")
    http("POST", f"{AGENT}/actions/requests/{request_id}/approve", {"actor": "gameday"})
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = http("GET", f"{AGENT}/actions/requests/{request_id}")
        status = r.get("request", r).get("status")
        if status != last:
            log(f"  status: {status}")
            last = status
        if status in TERMINAL:
            return r.get("request", r)
        time.sleep(5)
    raise SystemExit("request never reached a terminal state — check the reconciler")


def show_evidence(request_id: str) -> None:
    trail = http("GET", f"{AGENT}/actions/audit?request_id={request_id}").get("audit", [])
    print("\n  phase          verdict      detail")
    print("  " + "-" * 68)
    for row in trail:
        detail = json.dumps(row.get("detail", {}), ensure_ascii=False)
        print(f"  {row['phase']:<14} {row['verdict']:<12} {detail[:80]}")
    print()


def grade(request_id: str, resolved: bool, note: str) -> None:
    """Record the drill's own verdict on whether the incident actually ended.

    A scripted grade is only defensible because a drill knows the ground truth in
    advance — we chose the root cause, so we know whether `rollout undo` could
    possibly have fixed it. For a real incident this call belongs to the person
    who was paged, and `actor` says which of the two it was so the two kinds of
    label never get silently pooled.
    """
    out = http(
        "POST",
        f"{AGENT}/actions/requests/{request_id}/outcome",
        {"resolved": resolved, "actor": "gameday-drill", "note": note},
    )
    log(
        f"graded: resolved={resolved} "
        f"(verify_said={out.get('verify_said')}, drill={out.get('drill')})"
    )
    if out.get("verify_said") is not None and out["verify_said"] != resolved:
        log("  NOTE: the machine check and the drill's ground truth disagree — that is the finding")


def snapshot(tag: str) -> None:
    """Copy the store out of the pod. The numbers this drill exists to move live
    in that file, and `kubectl cp` after the fact is how the last one got lost."""
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
    out = HERE / f"snapshot-{tag}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
    sh("kubectl", "-n", NS, "cp", f"{pod}:/data/aiops.db", str(out))
    log(f"snapshot: {out.name} ({out.stat().st_size} bytes)")


# --- entry points ----------------------------------------------------------


EXPECTED = {"a": "succeeded", "b": "rolled_back"}
# Only a request that actually touched the cluster has an outcome to grade.
GRADABLE = {"succeeded", "failed", "verify_failed", "rolled_back", "rollback_failed"}


def run(scenario: str) -> int:
    preflight()
    snapshot(f"before-{scenario}")

    traffic = Traffic()
    traffic.start()
    log(f"traffic: {TRAFFIC_RPS} odd-cent charges/s (declines only happen on odd amounts)")

    try:
        save_state()
        log(f"pre-injection state saved to {STATE.name}: {STATE.read_text()}")
        log(f"injecting scenario {scenario}")
        (inject_a if scenario == "a" else inject_b)()
        log(f"deployment revision after injection: {current_revision()}")

        # Let the symptom become visible to a 5m rate() before alerting on it.
        log("waiting 90s for the decline rate to show up in Prometheus…")
        time.sleep(90)

        since = fire_alert(scenario)
        req = wait_for_request(since)
        final = drive(req["request_id"])

        log(f"terminal status: {final['status']} — {final.get('outcome', '')}")
        show_evidence(req["request_id"])
        log(f"traffic sent={traffic.sent} declined={traffic.declined}")

        # Grade it while the evidence is on screen. Scenario (a) is designed to be
        # fixed by the rollback; (b) is designed not to be.
        if final["status"] in GRADABLE:
            grade(
                req["request_id"],
                resolved=(scenario == "a" and final["status"] == "succeeded"),
                note=f"drill scenario {scenario}: {final.get('outcome', '')}",
            )
            slo = http("GET", f"{AGENT}/actions/ae-slo")
            log(f"AE-SLO now: incidents={slo['incidents']['raw']} drills={slo['drills']['raw']}")

        expected = EXPECTED[scenario]
        if final["status"] == expected:
            log(f"RESULT: as designed (expected {expected})")
            return 0
        log(f"RESULT: NOT as designed — expected {expected}, got {final['status']}")
        log("        That is a finding, not a script bug. Write it down before re-running.")
        return 1
    finally:
        traffic.stop_flag.set()
        snapshot(f"after-{scenario}")


def plan() -> int:
    print(__doc__)
    print("Cluster state right now:")
    print(f"  deployment revision : {current_revision()}")
    print(
        "  git_version label   : "
        + sh(
            "kubectl",
            "-n",
            NS,
            "get",
            "deploy",
            DEPLOY,
            "-o",
            "jsonpath={.spec.template.metadata.labels.git_version}",
        )
    )
    print(
        "  flags ConfigMap     : "
        + sh(
            "kubectl",
            "-n",
            NS,
            "get",
            "configmap",
            "payment-flags",
            "-o",
            "jsonpath={.data.flags\\.json}",
        )
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="print the drill plan + current cluster state; change nothing")
    r = sub.add_parser("run", help="run one drill end to end")
    r.add_argument("--scenario", choices=["a", "b"], required=True)
    sub.add_parser("cleanup", help="revert everything the drill changed")
    args = ap.parse_args()

    if shutil.which("kubectl") is None:
        raise SystemExit("kubectl not on PATH")
    if args.cmd == "plan":
        return plan()
    if args.cmd == "cleanup":
        cleanup()
        return 0
    return run(args.scenario)


if __name__ == "__main__":
    sys.exit(main())
