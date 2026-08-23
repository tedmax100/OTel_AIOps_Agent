#!/usr/bin/env python3
"""把 Day10 那個「分層 registry 查不到 base 屬性」的行為釘成一條斷言。

單獨拉出來是因為 regress.sh 要的是一句可以 grep 的輸出，不是完整的巡邏報告。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "day10"))

from mcp_probe import McpProbe  # noqa: E402

probe = McpProbe("ironman-2026/day09/team-orders")
print(probe.text("get_attribute", key="biz.user.id"))
probe.close()
