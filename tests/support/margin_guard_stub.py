"""TEST_ONLY scripted margin guard for the execution manager tests (Phase 22, plan 22-15).

`StubMarginGuard` is the `MarginGuardPort` the manager tests inject: it answers a scripted
verdict (or raises a scripted exception), records every request it receives and appends a name
to an optional shared event log so a test can prove the order of the manager's calls (the
position-mode read, the guard, the entry placement). It judges nothing: the real composition is
`src/execution/margin_guard.py`, tested in `tests/test_margin_guard.py`.

The verdict values here are TEST DATA taken from the recorded Demo account (CROSSED x20 changed to
ISOLATED x5, equity 4999.09343961; demo-observed, not mainnet). Nothing here is a production
default.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.execution.margin_guard import MarginGuardRequest, MarginGuardVerdict

# TEST DATA: the verified configuration the recorded Demo account ends with (22-DEMO-RESULTS).
VERIFIED_MARGIN_TYPE = "ISOLATED"
VERIFIED_LEVERAGE = 5
VERIFIED_EQUITY = Decimal("4999.09343961")


def passing_verdict(**overrides: Any) -> MarginGuardVerdict:
    """A pass: ISOLATED, leverage 5, the recorded Demo equity, no configuration change."""
    values: dict[str, Any] = {
        "is_no_trade": False,
        "reason_code": "OK",
        "alert_reason": None,
        "margin_type": VERIFIED_MARGIN_TYPE,
        "leverage": VERIFIED_LEVERAGE,
        "equity_used": VERIFIED_EQUITY,
        "config_changed": False,
        "previous_margin_type": None,
        "previous_leverage": None,
    }
    values.update(overrides)
    return MarginGuardVerdict(**values)


def refusing_verdict(
    reason_code: str = "INSUFFICIENT_MARGIN", **overrides: Any
) -> MarginGuardVerdict:
    """A NO_TRADE verdict with one plain reason code (no verified figure)."""
    values: dict[str, Any] = {
        "is_no_trade": True,
        "reason_code": reason_code,
        "alert_reason": None,
        "margin_type": None,
        "leverage": None,
        "equity_used": None,
        "config_changed": False,
        "previous_margin_type": None,
        "previous_leverage": None,
    }
    values.update(overrides)
    return MarginGuardVerdict(**values)


class StubMarginGuard:
    """A `MarginGuardPort` with a scripted verdict, a request log and a shared event log."""

    def __init__(
        self,
        *,
        verdict: MarginGuardVerdict | None = None,
        exception: BaseException | None = None,
        event_log: list[str] | None = None,
    ) -> None:
        self.verdict = verdict if verdict is not None else passing_verdict()
        self.exception = exception
        self.event_log = event_log
        self.requests: list[MarginGuardRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    async def evaluate(self, request: MarginGuardRequest) -> MarginGuardVerdict:
        self.requests.append(request)
        if self.event_log is not None:
            self.event_log.append("guard.evaluate")
        if self.exception is not None:
            raise self.exception
        return self.verdict
