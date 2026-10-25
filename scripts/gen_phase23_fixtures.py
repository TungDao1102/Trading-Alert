"""Deterministic generator of the Phase 23 golden texts (plan 23-03; 23-09 and 23-12 add more).

`render_all()` builds every golden text from fixed inputs (a fixed UTC time, a fixed subject and
symbol, no clock, no network) and returns `{relative path: text}`. `main` writes them under
`tests/fixtures/phase23` (LF, UTF-8, one trailing newline) or, with `--check`, compares them with
the files on disk and returns 1 on any difference (a changed, a missing or an extra generated
file). Nothing is typed by hand (AGENTS.md); `DERIVATIONS.md` next to the files is documentation.

Sections, one function each so the later plans add theirs without touching this one:

- `_alerts_section()` (plan 23-03): the operator alert texts of `src/ops/alert_wording.py`, one
  file per CLOSE_REQUIRED branch code and per worded event, `alerts/<EVENT>[__<REASON>].txt`.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from src.ops.alert_wording import worded_alert_text
from src.ops.alerts import OperationalAlert

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "phase23"
GENERATED_SUFFIX = ".txt"

FIXED_AT_UTC = datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC)
PLAN_SUBJECT = "plan-0001"
SYSTEM_SUBJECT = "SYSTEM"
FIXED_SYMBOL = "BTCUSDT"
FIXED_PLAN_HASH = "a" * 64

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
    ("TP_UNAVAILABLE", "TP_UNAVAILABLE", "TP_UNAVAILABLE", PLAN_SUBJECT),
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
)


def _alert(event: str, reason: str, subject: str) -> OperationalAlert:
    return OperationalAlert.create(
        event=event,
        subject=subject,
        reason=reason,
        occurred_at_utc=FIXED_AT_UTC,
        plan_hash=FIXED_PLAN_HASH,
        symbol=FIXED_SYMBOL,
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


SECTIONS: tuple[Callable[[], dict[str, str]], ...] = (_alerts_section,)


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
