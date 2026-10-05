"""Case-input v2 contract (Phase 14, plan 14-08, RED skeleton).

The real parser lands with the GREEN commit; this skeleton pins the public names so the
tracer tests fail on assertions, not on imports.
"""

from __future__ import annotations

from typing import Any

CASE_INPUT_SCHEMA = "backtest-case/2"
REMOVED_V1_KEYS: tuple[str, ...] = (
    "intrabar_1m_map",
    "constraint_snapshot",
    "open_positions",
    "daily_loss_quote",
    "now_utc",
    "ttl_seconds",
    "mark_price_bars",
)


def parse_case_input(case_input: dict[str, Any]) -> dict[str, Any]:
    return case_input
