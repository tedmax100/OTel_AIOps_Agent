"""Tiny in-process feature flag reader.

Two sources, env wins over file:
  1. Environment variables: `FLAG_<UPPERCASE_NAME>=true|false|...`
  2. Optional JSON file at `FEATURE_FLAGS_PATH` (refreshed on each read with
     mtime check — no watcher thread, just lazy reload).

Designed for demo: not for production. No remote backend, no caching layer,
no targeting rules. The point is to let an incident scenario flip a flag
mid-run and have services observe it on next request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class FeatureFlags:
    def __init__(self, file_path: str | None = None) -> None:
        self._path = Path(file_path) if file_path else None
        self._mtime: float | None = None
        self._cache: dict[str, Any] = {}

    def _refresh(self) -> None:
        if not self._path or not self._path.exists():
            return
        mtime = self._path.stat().st_mtime
        if self._mtime == mtime:
            return
        try:
            self._cache = json.loads(self._path.read_text())
            self._mtime = mtime
        except (json.JSONDecodeError, OSError):
            self._cache = {}

    def get(self, name: str, default: Any = None) -> Any:
        env_key = f"FLAG_{name.upper()}"
        if env_key in os.environ:
            return _coerce(os.environ[env_key])

        self._refresh()
        if name in self._cache:
            return self._cache[name]
        return default

    def bool(self, name: str, default: bool = False) -> bool:
        value = self.get(name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"true", "1", "yes", "on"}
        return bool(value)


def _coerce(raw: str) -> Any:
    low = raw.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def default_flags() -> FeatureFlags:
    return FeatureFlags(file_path=os.environ.get("FEATURE_FLAGS_PATH"))
