#!/usr/bin/env python3
"""Run the governance gate over the actions that are actually registered.

`test_governance.py` covers every branch of `decide()`, but every AUTO-reaching
test builds its own `ActionSpec(requires_approval=False)` — a shape no shipped
action has. So the calibration gates that are the point of the module have never
been evaluated against a real action.

Four probes:

  1. sweep confidence over the real registry, with perfect calibration
  2. the same sweep on a copy with requires_approval flipped off
  3. 25 self-produced labels vs 20 grader labels (ARE §6.2 constraint 1)
  4. what the gate says on the real store, right now

No cluster, no LLM: a temp SQLite file and the real modules.

    python3 ironman-2026/day35/probe_governance.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[3] / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

import app.governance as gov  # noqa: E402
from app import store  # noqa: E402
from app.actions import ActionSpec, registry  # noqa: E402
from app.calibration import compute_calibration, load_records  # noqa: E402
from app.governance import decide  # noqa: E402

TMP = Path(tempfile.mkdtemp())
CLEAN = TMP / "clean.db"  # 25 grader labels: every earned-autonomy gate satisfied
SELF = TMP / "self.db"  # self-produced labels only

CONFIDENCES = (0.3, 0.6, 0.9, 1.0)


def seed(db: Path, n: int, source: str, *, correct: bool = True, confidence: float = 0.9) -> None:
    """Insert n labeled calibration records attributed to `source`."""
    now = datetime.now(UTC).isoformat()
    for i in range(n):
        run_id = f"{source}-{i}"
        store.cal_insert(
            run_id=run_id,
            ts=now,
            confidence=confidence,
            summary="probe",
            hypothesis="probe",
            suspected_version=None,
            services=["payment"],
            path=db,
        )
        store.cal_label(run_id, correct, score=1.0, source=source, path=db)


def sweep(label: str, specs: list[ActionSpec], calib: dict) -> None:
    print(label)
    for spec in specs:
        cells = []
        for c in CONFIDENCES:
            d = decide(spec, c, calib, path=CLEAN)
            cells.append(f"{c}->{d.autonomy.value:<8}")
        print(f"    {spec.name:<18} {' '.join(cells)}")


def main() -> None:
    print(f"[0] registered actions ({len(registry.names())})")
    for name in registry.names():
        s = registry.get(name)
        print(
            f"    {s.name:<18} reversible={s.reversible} "
            f"requires_approval={s.requires_approval} impl={'wired' if s.impl else 'None'}"
        )
    print()

    # A history the gate cannot fault: 25 grader labels, no self-produced ones.
    seed(CLEAN, 25, "grader")
    clean = compute_calibration(load_records(CLEAN))
    print(
        f"[baseline] {clean['labeled']} grader labels, "
        f"overconfidence {clean['overconfidence']} — every calibration gate satisfied\n"
    )

    specs = [registry.get(n) for n in registry.names()]
    sweep("[1] the real registry", specs, clean)
    print()

    relaxed = [s.model_copy(update={"requires_approval": False}) for s in specs]
    sweep("[2] the same actions with requires_approval flipped off", relaxed, clean)
    print()

    print("[3] self-produced labels vs grader labels, at confidence 0.9")
    spec = relaxed[0]
    for n, source in ((25, "remediation-verified"), (20, "grader")):
        seed(SELF, n, source)
        calib = compute_calibration(load_records(SELF))
        human = store.cal_count_by_source(exclude_sources=gov._SELF_LABEL_SOURCES, path=SELF)
        d = decide(spec, 0.9, calib, path=SELF)
        print(f"    after {n:>2} x {source:<21} labeled={calib['labeled']:<3} non-self={human:<3}")
        print(f"        -> {d.autonomy.value:<8} {d.calibration_note}")
    print()

    print("[4] the real store, right now")
    real = load_records()
    calib = compute_calibration(real)
    human = store.cal_count_by_source(exclude_sources=gov._SELF_LABEL_SOURCES)
    print(
        f"    recorded={calib['count']} labeled={calib['labeled']} "
        f"non-self={human} overconfidence={calib.get('overconfidence')}"
    )
    for name in registry.names():
        d = decide(registry.get(name), 0.9, calib)
        print(f"    {name:<18} -> {d.autonomy.value:<8} {d.reason}")
        print(f"    {'':<18}    {d.calibration_note}")


if __name__ == "__main__":
    main()
