"""Deterministic generator of the Phase 23 golden texts (plan 23-03; 23-09 and 23-12 add more).

`render_all()` builds every golden text from fixed inputs (a fixed UTC time, a fixed subject and
symbol, no clock, no network) and returns `{relative path: text}`. `main` writes them under
`tests/fixtures/phase23` (LF, UTF-8, one trailing newline) or, with `--check`, compares them with
the files on disk and returns 1 on any difference (a changed, a missing or an extra generated
file). Nothing is typed by hand (AGENTS.md); `DERIVATIONS.md` next to the files is documentation.

Sections, one function each so the later plans add theirs without touching this one:

- `_alerts_section()` (plan 23-03): the operator alert texts of `src/ops/alert_wording.py`, one
  file per CLOSE_REQUIRED branch code and per worded event, `alerts/<EVENT>[__<REASON>].txt`.
- `_messages_section()` (plan 23-09): the APPROVE texts of `src/adapters/telegram_notify.py`
  (`messages/approve_base.txt`, `approve_request_demo.txt`, `approve_request_live.txt`) and the
  SIMULATE text of `src/paper/notify.py` (`messages/simulate.txt`), built from the plan 23-02
  LONG fixture (`approve_fields()`, `fixture_money()`).
- `_confirm_section()` (plan 23-12): the DEMO confirmation card and its CONFIRMED and EXPIRED final
  texts (`messages/confirm_card_demo.txt`, `confirm_final_confirmed_demo.txt`,
  `confirm_final_expired_demo.txt`), from the same LONG fixture.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.adapters.telegram_notify import (
    format_approval_request,
    format_approve,
    format_live_confirm_card,
    format_live_confirm_final,
)
from src.execution.confirm_flow import PLACEMENT_NOT_RECORDED
from src.execution.pre_placement import check_remaining_validity
from src.ops.alert_wording import worded_alert_text
from src.ops.alerts import OperationalAlert
from src.paper.notify import format_simulate
from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
from src.risk.money_at_stake import (
    EQUITY_SOURCE_ACCOUNT_LIVE,
    LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT,
    MoneyAtStake,
    build_money_at_stake,
    money_canonical_json,
    parse_money_json,
)
from src.risk.types import SizedResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "phase23"
GENERATED_SUFFIX = ".txt"

FIXED_AT_UTC = datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC)
PLAN_SUBJECT = "plan-0001"
SYSTEM_SUBJECT = "SYSTEM"
FIXED_SYMBOL = "BTCUSDT"
FIXED_PLAN_HASH = "a" * 64
# Plan 24-13: the deadline of the REST gate ban golden (a whole second, 15 minutes after the time).
FIXED_BAN_UNTIL_UTC = FIXED_AT_UTC + timedelta(minutes=15)

# (file stem, event, reason, subject). The subject is the plan for the producers that know the
# plan and SYSTEM for the SAFE_MODE observer events (src/ops/alerts.py SafeModeAlertObserver).
ALERT_CASES: tuple[tuple[str, str, str, str], ...] = (
    *(
        (f"CLOSE_REQUIRED__{code}", "CLOSE_REQUIRED", code, PLAN_SUBJECT)
        for code in (
            "B1_ENTRY_NOT_TERMINAL",
            "B2_STOP_UNCONFIRMED",
            "B3_BOTH_AMBIGUOUS",
            "B4_FILL_AFTER_STOP",
            "B4_STOP_LOST_UNRESOLVED",
            "B5_STOP_REJECTED",
            "B6_LIQUIDATION_TOO_CLOSE",
            "NO_POSITION_ON_STOP_BUT_EXPOSED",
            "OPERATOR_CLOSE",
        )
    ),
    # Any other CLOSE_REQUIRED reason gets the generic wording.
    ("CLOSE_REQUIRED__GENERIC", "CLOSE_REQUIRED", "UNLISTED_REASON", PLAN_SUBJECT),
    # The producer's reason is the reason code since D113 (quick 261115-nnt); every refusal of
    # attach carries ENTRY_WITHOUT_PROTECTIVE, which is also the case of the 2026-11-15 smoke.
    ("TP_UNAVAILABLE", "TP_UNAVAILABLE", "ENTRY_WITHOUT_PROTECTIVE", PLAN_SUBJECT),
    # The reason of the closer's alert is the failure code; a pre-send refusal has one fixed code.
    ("EMERGENCY_CLOSE_FAILED", "EMERGENCY_CLOSE_FAILED", "POSITION_READ_FAILED", PLAN_SUBJECT),
    ("EMERGENCY_CLOSE_NOT_SENT", "EMERGENCY_CLOSE_NOT_SENT", "PRE_SEND_REFUSED", PLAN_SUBJECT),
    # The three entry-path events come from the SAFE_MODE observer: subject SYSTEM, reason = event.
    ("ENTRY_STATE_UNKNOWN", "ENTRY_STATE_UNKNOWN", "ENTRY_STATE_UNKNOWN", SYSTEM_SUBJECT),
    (
        "PROTECTION_HANDOFF_FAILED",
        "PROTECTION_HANDOFF_FAILED",
        "PROTECTION_HANDOFF_FAILED",
        SYSTEM_SUBJECT,
    ),
    ("DB_FAILURE", "DB_FAILURE", "DB_FAILURE", SYSTEM_SUBJECT),
    # Plan 24-13: the two REST gate events (subject SYSTEM, the gate's own reason code).
    ("REST_GATE_BAN_ENTERED", "REST_GATE_BAN_ENTERED", "IP_BAN_418", SYSTEM_SUBJECT),
    (
        "REST_GATE_RECOVERY_REQUIRED",
        "REST_GATE_RECOVERY_REQUIRED",
        "GATE_STATE_UNKNOWN",
        SYSTEM_SUBJECT,
    ),
    # Quick 261114-mp1 (D111): the scheduler stall alert; the subject is the task name.
    ("TASK_STALLED", "TASK_STALLED", "STALL_BOUND_EXCEEDED", "protection_step"),
)


def _alert(event: str, reason: str, subject: str) -> OperationalAlert:
    return OperationalAlert.create(
        event=event,
        subject=subject,
        reason=reason,
        occurred_at_utc=FIXED_AT_UTC,
        plan_hash=FIXED_PLAN_HASH,
        symbol=FIXED_SYMBOL,
        until_utc=FIXED_BAN_UNTIL_UTC if event == "REST_GATE_BAN_ENTERED" else None,
    )


def _alerts_section() -> dict[str, str]:
    """One worded alert text per case; a case without wording is a generator error."""
    rendered: dict[str, str] = {}
    for stem, event, reason, subject in ALERT_CASES:
        text = worded_alert_text(_alert(event, reason, subject))
        if text is None:
            raise ValueError(f"{event} / {reason} has no wording")
        rendered[f"alerts/{stem}{GENERATED_SUFFIX}"] = text + "\n"
    return rendered


# --------------------------------------------------------------------------- #
# Messages (plan 23-09): the plan 23-02 LONG fixture of tests/test_money_at_stake.py.
# --------------------------------------------------------------------------- #

_RATES = CostRates(
    fee_rate_entry=Decimal("0.0005"),
    entry_slippage_rate=Decimal("0.0002"),
    fee_rate_exit=Decimal("0.0005"),
    exit_slippage_rate=Decimal("0.0002"),
    fee_source=FEE_SOURCE_PARAMETER,
)
_FIXTURE_TAKE_PROFITS = [
    (Decimal("51000"), Decimal("0.5")),
    (Decimal("52000"), Decimal("0.5")),
]


def fixture_money() -> MoneyAtStake:
    """The money of the LONG fixture: entry 50100, stop 49500, quantity 0.08, leverage 5."""
    sized = SizedResult(
        is_no_trade=False,
        quantity=Decimal("0.08"),
        quantity_before_rounding=Decimal("0.0803"),
        quantity_after_rounding=Decimal("0.08"),
        quantization_decision="ACCEPTED",
        realized_risk=Decimal("53.5776"),
        modeled_costs_per_unit=Decimal("69.72"),
        sizing_entry_price=Decimal("50100"),
    )
    return build_money_at_stake(
        side="LONG",
        sized=sized,
        stop_loss_price=Decimal("49500"),
        take_profits=_FIXTURE_TAKE_PROFITS,
        cost_rates=_RATES,
        leverage=5,
        leverage_source=LEVERAGE_SOURCE_CONSTRAINT_SNAPSHOT,
        equity=Decimal("800"),
        equity_source=EQUITY_SOURCE_ACCOUNT_LIVE,
        equity_observed_at_utc=FIXED_AT_UTC,
    )


def fixture_money_json() -> str:
    """The stored form (`approvals.money_json`) of `fixture_money()`."""
    return money_canonical_json(fixture_money())


def approve_fields() -> dict[str, Any]:
    """The 12 APRV-01 fields and the quantity of the LONG fixture (no money)."""
    return {
        "symbol": FIXED_SYMBOL,
        "direction": "LONG",
        "setup": "TREND_PULLBACK_LONG",
        "entry_min": Decimal("50000"),
        "entry_max": Decimal("50100"),
        "stop_loss": Decimal("49500"),
        "take_profits": list(_FIXTURE_TAKE_PROFITS),
        "rr": Decimal("2.0"),
        "risk_pct": Decimal("0.005"),
        "expiry_utc": FIXED_AT_UTC + timedelta(hours=4),
        "invalidation": "CANDLE_CLOSE < 49500",
        "exposure_quote": Decimal("0"),
        "reason_codes": ["SETUP_DETECTED"],
        "signal_id": "sig-0001",
        "detected_at_utc": FIXED_AT_UTC,
        "approved_quantity": Decimal("0.08"),
    }


def _messages_section() -> dict[str, str]:
    """The APPROVE texts (plain, DEMO and LIVE request with money) and the SIMULATE text."""
    fields = approve_fields()
    money = parse_money_json(fixture_money_json())
    return {
        "messages/approve_base.txt": format_approve(**fields) + "\n",
        "messages/approve_request_demo.txt": format_approval_request(
            mode_label="DEMO", money=money, **fields
        )
        + "\n",
        "messages/approve_request_live.txt": format_approval_request(
            mode_label="LIVE", money=money, **fields
        )
        + "\n",
        "messages/simulate.txt": format_simulate(money=money, **fields) + "\n",
    }


# --------------------------------------------------------------------------- #
# Confirm card (plan 23-12): the DEMO confirmation card and its two final texts.
# --------------------------------------------------------------------------- #

CONFIRM_MARK_PRICE = Decimal("50050")
CONFIRM_MIN_REMAINING_VALIDITY_SECONDS = 600
CONFIRM_GTD_CLOCK_MARGIN = timedelta(seconds=2)
CONFIRM_TTL_SECONDS = 60
CONFIRM_USER_ID = 777001


def _confirm_section() -> dict[str, str]:
    """The card issued at 2026-10-09T03:00:00Z with a mark of 50050 and a 600 s minimum, the
    CONFIRMED final 30 s later (no entry intent recorded yet) and the TTL EXPIRED final at 61 s.

    The card is built by `format_live_confirm_card` from the stored form of the LONG fixture money
    and the verdict of `check_remaining_validity` (the placement gate's own rule); nothing here
    multiplies or rounds an amount.
    """
    fields = approve_fields()
    money = parse_money_json(fixture_money_json())
    expiry = fields["expiry_utc"]
    verdict = check_remaining_validity(
        expiry_utc=expiry,
        now_utc=FIXED_AT_UTC,
        min_remaining_validity_seconds=CONFIRM_MIN_REMAINING_VALIDITY_SECONDS,
        gtd_clock_margin=CONFIRM_GTD_CLOCK_MARGIN,
    )
    common: dict[str, Any] = {
        "mode_label": "DEMO",
        "symbol": FIXED_SYMBOL,
        "side": "LONG",
        "money": money,
    }
    card = format_live_confirm_card(
        **common,
        mark_price=CONFIRM_MARK_PRICE,
        plan_expiry_utc=expiry,
        validity_verdict=verdict,
        now_utc=FIXED_AT_UTC,
        ttl_seconds=CONFIRM_TTL_SECONDS,
    )
    confirmed = format_live_confirm_final(
        **common,
        outcome="CONFIRMED",
        at_utc=FIXED_AT_UTC + timedelta(seconds=30),
        user_id=CONFIRM_USER_ID,
        placement_lines=(PLACEMENT_NOT_RECORDED,),
    )
    expired = format_live_confirm_final(
        **common,
        outcome="EXPIRED",
        at_utc=FIXED_AT_UTC + timedelta(seconds=CONFIRM_TTL_SECONDS + 1),
        reason="CONFIRM_TTL_ELAPSED",
    )
    return {
        "messages/confirm_card_demo.txt": card + "\n",
        "messages/confirm_final_confirmed_demo.txt": confirmed + "\n",
        "messages/confirm_final_expired_demo.txt": expired + "\n",
    }


SECTIONS: tuple[Callable[[], dict[str, str]], ...] = (
    _alerts_section,
    _messages_section,
    _confirm_section,
)


def render_all() -> dict[str, str]:
    """Every generated golden text, keyed by its path relative to the fixture root."""
    rendered: dict[str, str] = {}
    for section in SECTIONS:
        for relative, text in section().items():
            if relative in rendered:
                raise ValueError(f"two sections render {relative}")
            rendered[relative] = text
    return rendered


def _write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _on_disk(out: Path) -> dict[str, str]:
    """The generated files under `out`; a CRLF a Windows checkout added is read as LF."""
    found: dict[str, str] = {}
    if not out.is_dir():
        return found
    for path in sorted(out.rglob(f"*{GENERATED_SUFFIX}")):
        relative = path.relative_to(out).as_posix()
        found[relative] = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    return found


def write_all(out: Path) -> list[Path]:
    """Write every golden text under `out`; return the paths written."""
    written: list[Path] = []
    for relative, text in sorted(render_all().items()):
        target = out / relative
        _write_text(target, text)
        written.append(target)
    return written


def differences(out: Path) -> list[str]:
    """The relative paths whose text on disk differs from a fresh render (missing or extra too)."""
    fresh = render_all()
    disk = _on_disk(out)
    return sorted(
        relative for relative in set(fresh) | set(disk) if fresh.get(relative) != disk.get(relative)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the Phase 23 golden texts.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output root directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; return 1 when any generated file differs from a fresh render",
    )
    args = parser.parse_args(argv)
    if args.check:
        changed = differences(args.out)
        for relative in changed:
            print(f"differs: {relative}")
        return 1 if changed else 0
    written = write_all(args.out)
    print(f"Phase 23 fixtures written: {len(written)} files under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
