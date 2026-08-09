#!/usr/bin/env python3
"""Read a package's real import graph out of the AST, not out of a design doc.

Point it at the agent's `app/signals/` package. It reports, per module: who that
module imports inside the package, who imports it, and which modules nothing
inside the package imports at all (the entry points and the orphans).

    python3 ironman-2026/day13/importgraph.py <path-to-app/signals>

Deliberately AST-based rather than grep-based: a function-level `import` inside
a branch is still an edge, and grep for "^from" would miss it.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path


def local_imports(path: Path, siblings: set[str]) -> set[str]:
    """Sibling modules imported by `path`, at any nesting depth (module level,
    inside a function, inside a `try`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level == 0:
            continue
        # `from .topology import X` → module="topology"; `from ..config import X`
        # → level 2, which points outside the package, so skip it.
        head = (node.module or "").split(".")[0]
        if node.level == 1 and head in siblings:
            found.add(head)
    return found


def main(pkg: Path) -> int:
    mods = sorted(p.stem for p in pkg.glob("*.py") if p.stem != "__init__")
    if not mods:
        print(f"no modules under {pkg}")
        return 1
    siblings = set(mods)

    imports = {m: local_imports(pkg / f"{m}.py", siblings) for m in mods}
    importers: dict[str, set[str]] = defaultdict(set)
    for m, deps in imports.items():
        for d in deps:
            importers[d].add(m)

    width = max(len(m) for m in mods)
    print(f"# {pkg}  ({len(mods)} modules)\n")
    print(f"{'module':<{width}}  {'imports':<34}  imported by")
    print("-" * (width + 60))
    for m in mods:
        dep = ", ".join(sorted(imports[m])) or "—"
        by = ", ".join(sorted(importers[m])) or "—"
        print(f"{m:<{width}}  {dep:<34}  {by}")

    orphans = [m for m in mods if not importers[m]]
    print(f"\nnothing in this package imports: {', '.join(orphans)}")
    for m in orphans:
        has_main = "__main__" in (pkg / f"{m}.py").read_text(encoding="utf-8")
        print(f"  {m:<{width}}  runnable as a CLI: {'yes' if has_main else 'NO'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
