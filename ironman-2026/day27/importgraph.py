#!/usr/bin/env python3
"""Read a package's real import graph out of the AST — now including the edges
Day13's version could not see.

Day13's `local_imports()` only matched `from .mod import Name`. It parsed
`from . import mod` as ImportFrom(module=None), took `("" or "").split(".")[0]`,
got the empty string, and dropped the edge on the floor. On `app/signals/` that
never mattered (nothing there uses that style). On `app/` it hides a lot: nine
modules import `store` that way, and `breaker` gets reported as an orphan while
`main` and `execution` are both importing it.

Two shapes are edges and both are handled here:

    from .governance import Decision     # ImportFrom(module="governance")
    from . import store, audit           # ImportFrom(module=None, names=[...])

    python3 ironman-2026/day29/importgraph.py <pkg> [--focus a,b,c]

`--focus` keeps only the listed modules plus everything directly touching them,
so a 20-module package can be read one plane at a time.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path


def local_imports(path: Path, siblings: set[str]) -> set[str]:
    """Sibling modules imported by `path`, at any nesting depth (module level,
    inside a function, inside a `try`), in either import spelling."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        if node.module:
            # `from .topology import X` → the module is the edge.
            head = node.module.split(".")[0]
            if head in siblings:
                found.add(head)
        else:
            # `from . import store, audit` → every alias is its own edge. This
            # is the branch Day13 was missing.
            for alias in node.names:
                if alias.name in siblings:
                    found.add(alias.name)
    return found


def main(pkg: Path, focus: set[str]) -> int:
    mods = sorted(p.stem for p in pkg.glob("*.py") if p.stem != "__init__")
    if not mods:
        print(f"no modules under {pkg}")
        return 1
    siblings = set(mods)

    unknown = focus - siblings
    if unknown:
        print(f"not modules of this package: {', '.join(sorted(unknown))}")
        return 1

    imports = {m: local_imports(pkg / f"{m}.py", siblings) for m in mods}
    importers: dict[str, set[str]] = defaultdict(set)
    for m, deps in imports.items():
        for d in deps:
            importers[d].add(m)

    shown = mods
    if focus:
        # focus + anything they import + anything importing them
        keep = set(focus)
        for m in focus:
            keep |= imports[m] | importers[m]
        shown = [m for m in mods if m in keep]

    width = max(len(m) for m in shown)
    label = f"  (focus: {', '.join(sorted(focus))})" if focus else ""
    print(f"# {pkg}  ({len(mods)} modules, {len(shown)} shown){label}\n")
    print(f"{'module':<{width}}  {'imports':<40}  imported by")
    print("-" * (width + 66))
    for m in shown:
        mark = "*" if m in focus else " "
        dep = ", ".join(sorted(imports[m])) or "—"
        by = ", ".join(sorted(importers[m])) or "—"
        print(f"{m:<{width}}{mark} {dep:<40}  {by}")

    orphans = [m for m in mods if not importers[m]]
    if orphans:
        print(f"\nnothing in this package imports: {', '.join(orphans)}")
        for m in orphans:
            src = (pkg / f"{m}.py").read_text(encoding="utf-8")
            cli = "YES" if "__main__" in src else "NO"
            print(f"  {m:<{width}}  runnable as a CLI: {cli}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg", type=Path)
    ap.add_argument("--focus", default="", help="comma-separated module names")
    args = ap.parse_args()
    focus = {s for s in args.focus.split(",") if s}
    sys.exit(main(args.pkg, focus))
