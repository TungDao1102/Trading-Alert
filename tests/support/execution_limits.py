"""TEST_ONLY execution-limit values and a TOML writer (plan 19-01).

TEST_ONLY values are NOT ratified values and NOT the owner's choice (OWNER-OPEN O-04). They
never appear in `src` or `scripts`, no production code imports this module
(`tests/test_no_unratified_defaults.py` enforces it), and they exist only to build
`ExecutionLimits` objects and limits files in tests.

Every value is deliberately odd-looking so it cannot be mistaken for a chosen threshold.
Later plans (19-11 to 19-16) use exactly these values so their fixtures stay consistent: a
plan expiry 1800 s ahead of now passes the 777 s minimum remaining validity and the 600 s GTD
floor of plan 19-03.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from src.execution.execution_limits import (
    EXECUTION_LIMIT_FIELDS,
    EXECUTION_LIMIT_KEYS,
    NOT_CONFIGURED_WORD,
    ExecutionLimits,
)

TEST_ONLY_EXECUTION_LIMIT_VALUES: Mapping[str, int | None] = {
    "protection.max_unprotected_ms": 7777,
    "protection.entry_terminal_timeout_ms": 13333,
    # 19-REVIEW WR-05: a FAKE grace past the GTD time of an ENTRY_STATE_UNKNOWN entry.
    "protection.entry_unknown_grace_ms": 9191,
    # 19-REVIEW WR-03: a FAKE poll deadline of a sent emergency close (never max_unprotected_ms).
    "protection.emergency_close_poll_timeout_ms": 6161,
    "pre_placement.min_remaining_validity_seconds": 777,
    "pre_placement.max_mark_price_age_ms": 4321,
    # Quick task 261020-l4p: a FAKE last-price age bound, deliberately below the mark bound so a
    # test can tell the two apart.
    "pre_placement.max_last_price_age_ms": 2468,
    # Plan 20-01 (D-25): a FAKE reconcile cadence, deliberately below max_unprotected_ms (7777).
    "reconcile.tick_interval_ms": 1234,
    # D-11: FAKE consecutive-probe count and spacing for an UNKNOWN entry.
    "reconcile.entry_unknown_probe_count": 3,
    "reconcile.entry_unknown_probe_interval_ms": 2345,
    # D-21: a FAKE lot-filter refresh interval.
    "reconcile.lot_filter_refresh_interval_ms": 8642,
    # D-25: FAKE stale-feed bounds; the mark age differs from pre_placement's 4321 so a test
    # can tell the two apart.
    "stale_feed.max_mark_price_age_ms": 3579,
    "stale_feed.max_user_data_silence_ms": 5791,
    # D-23: a FAKE alert dedupe window.
    "alerts.dedupe_window_ms": 6543,
    # Plan 20-28: a FAKE grace past goodTillDate for the stale-entry alert (alert only).
    "reconcile.entry_stale_grace_ms": 4747,
    # Phase 21 (D-03): a FAKE equity age bound.
    "account.max_equity_age_ms": 9137,
    # Phase 21 review WR-05: a FAKE daily-loss age bound (the owner's number is 300000, D087).
    "account.max_daily_loss_age_ms": 7919,
    # Phase 22 (plan 22-02; D-10, D-11, D-13): FAKE margin numbers, never the owner's choice
    # (OWNER-OPEN O-2, O-3). On an entry of 80000 a buffer of 137 bps is a distance of 1096.
    "margin.liquidation_buffer_bps": 137,
    "margin.max_bracket_age_ms": 4141,
    "margin.headroom_bps": 233,
    # Plan 24-03 (D083 item 4): a FAKE clock margin for the 418 ban end; the real one is the owner's
    # (OWNER-OPEN O-1) and the shipped file keeps it NOT_CONFIGURED.
    "rest_gate.ban_end_clock_margin_ms": 4545,
    # Quick task 261114-mp1 (D111): the protection stall bound is ALERT ONLY. The shipped file sets
    # it since D114 (quick 261115-pdb); this TEST_ONLY value stays None on purpose, so every wiring
    # test keeps the stall watchdog off unless it sets a bound (override the field
    # `scheduler_protection_stall_after_ms`).
    "scheduler.protection_stall_after_ms": None,
    # Quick task 261115-kra (D112): the summary window is OPTIONAL and unset (None), like the
    # shipped file, so no wiring test writes window rows. A test that needs a window overrides
    # the field (`scheduler_duration_summary_interval_ms=...`).
    "scheduler.duration_summary_interval_ms": None,
}

TEST_ONLY_PROVENANCE_LABEL = "DECISION"


def test_only_execution_limits(**overrides: int | None) -> ExecutionLimits:
    """The TEST_ONLY limits; an override (by field name) may be None for "unset"."""
    fields: dict[str, int | None] = {
        EXECUTION_LIMIT_FIELDS[dotted]: value
        for dotted, value in TEST_ONLY_EXECUTION_LIMIT_VALUES.items()
    }
    unknown = set(overrides) - set(fields)
    if unknown:
        raise TypeError(f"unknown execution limit field: {sorted(unknown)}")
    fields.update(overrides)
    return ExecutionLimits(**fields)


def write_execution_limits_toml(
    path: Path,
    *,
    values: Mapping[str, int | None],
    provenance: Mapping[str, str] | None = None,
) -> Path:
    """Write a limits file. `values` maps `section.key` to an int or None (NOT_CONFIGURED).

    `provenance` maps `section.key` to a label; a key not named there gets DECISION for an int
    and NOT_CONFIGURED for None, so the default document is valid.
    """
    labels = dict(provenance or {})
    lines = ["# TEST_ONLY execution limits written by tests/support/execution_limits.py."]
    for section, keys in EXECUTION_LIMIT_KEYS.items():
        lines.append("")
        lines.append(f"[{section}]")
        for key in keys:
            value = values[f"{section}.{key}"]
            lines.append(
                f'{key} = "{NOT_CONFIGURED_WORD}"' if value is None else f"{key} = {value}"
            )
    for section, keys in EXECUTION_LIMIT_KEYS.items():
        lines.append("")
        lines.append(f"[provenance.{section}]")
        for key in keys:
            dotted = f"{section}.{key}"
            default = NOT_CONFIGURED_WORD if values[dotted] is None else TEST_ONLY_PROVENANCE_LABEL
            lines.append(f'{key} = "{labels.get(dotted, default)}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


__all__ = [
    "TEST_ONLY_EXECUTION_LIMIT_VALUES",
    "TEST_ONLY_PROVENANCE_LABEL",
    "test_only_execution_limits",
    "write_execution_limits_toml",
]
