"""The relationships between the shipped execution limits (Phase 24, plan 24-06; D-12, T-06, P-9).

The owner's values are in `config/execution/execution-limits-v1.toml` (DECISIONS D089). This
module reads the shipped file through the real loader, plus the ratified Binance limits and the
confirm TTL, and fails naming the keys when one of six rules breaks:

1. `reconcile.tick_interval_ms` is strictly below `protection.max_unprotected_ms`;
2. `protection.max_unprotected_ms` is above the ratified 429 pause plus two ticks;
3. `pre_placement.min_remaining_validity_seconds` is above the 600 s `goodTillDate` floor plus the
   confirm TTL plus the GTD clock margin;
4. `stale_feed.max_mark_price_age_ms` is above one tick;
5. `reconcile.entry_unknown_probe_count` times `reconcile.entry_unknown_probe_interval_ms` is
   below `protection.entry_unknown_grace_ms`;
6. a set `scheduler.protection_stall_after_ms` is strictly below `protection.max_unprotected_ms`
   (D114; an unset stall key is allowed: it is alert only, D111).

Nothing here is a default: a rule whose key is unset is itself a violation (the alert-only stall
key of rule 6 is the one exception). The negative controls
edit a copy under `tmp_path`, never the shipped file. No network, no database, no wall clock.
"""

from __future__ import annotations

import dataclasses
import math
import tomllib
from datetime import timedelta
from pathlib import Path

import pytest
from src.adapters.binance_limits import BinanceLimits, load_binance_limits
from src.approval.confirm_core import CONFIRM_TTL_SECONDS_DEFAULT
from src.execution.execution_limits import (
    ExecutionLimits,
    check_reconcile_cadence,
    load_execution_limits,
)
from src.execution.pre_placement import GTD_MIN_AHEAD_SECONDS
from src.live.scheduler import LiveCadences

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_LIMITS_FILE = ROOT / "config" / "execution" / "execution-limits-v1.toml"
BINANCE_LIMITS_FILE = ROOT / "config" / "binance" / "binance-limits-v1.toml"

_RELATIONSHIP_FIELDS = {
    "reconcile.tick_interval_ms": "reconcile_tick_interval_ms",
    "protection.max_unprotected_ms": "max_unprotected_ms",
    "pre_placement.min_remaining_validity_seconds": "min_remaining_validity_seconds",
    "stale_feed.max_mark_price_age_ms": "stale_feed_max_mark_price_age_ms",
    "reconcile.entry_unknown_probe_count": "reconcile_entry_unknown_probe_count",
    "reconcile.entry_unknown_probe_interval_ms": "reconcile_entry_unknown_probe_interval_ms",
    "protection.entry_unknown_grace_ms": "entry_unknown_grace_ms",
}


def _gtd_clock_margin_ms(binance: BinanceLimits) -> int:
    """The GTD clock margin as `scripts/demo_rehearsal.py` computes it: the larger drift limit."""
    return max(binance.drift.ahead_limit_ms, binance.drift.behind_limit_ms)


def relationship_violations(limits: ExecutionLimits, binance: BinanceLimits) -> list[str]:
    """Every broken rule, each message naming its keys and no value of a secret kind."""
    unset = [
        dotted for dotted, field in _RELATIONSHIP_FIELDS.items() if getattr(limits, field) is None
    ]
    if unset:
        return [f"{dotted} is NOT_CONFIGURED, so its relationship cannot hold" for dotted in unset]

    tick = limits.reconcile_tick_interval_ms
    unprotected = limits.max_unprotected_ms
    validity = limits.min_remaining_validity_seconds
    stale_mark = limits.stale_feed_max_mark_price_age_ms
    probes = limits.reconcile_entry_unknown_probe_count
    probe_interval = limits.reconcile_entry_unknown_probe_interval_ms
    unknown_grace = limits.entry_unknown_grace_ms
    assert tick is not None and unprotected is not None and validity is not None
    assert stale_mark is not None and probes is not None and probe_interval is not None
    assert unknown_grace is not None

    problems: list[str] = []
    if tick >= unprotected:
        problems.append(
            "reconcile.tick_interval_ms must be strictly below protection.max_unprotected_ms"
        )
    pause_429_ms = binance.signed.rate_limit.no_retry_after_wait_429_seconds * 1000
    if unprotected <= pause_429_ms + 2 * tick:
        problems.append(
            "protection.max_unprotected_ms must be above the ratified 429 pause "
            "(signed_calls.rate_limit_429_no_retry_after_wait_seconds) plus two "
            "reconcile.tick_interval_ms"
        )
    # Whole seconds: the GTD floor and the TTL are seconds, the margin is rounded up to a second.
    floor_seconds = (
        GTD_MIN_AHEAD_SECONDS
        + CONFIRM_TTL_SECONDS_DEFAULT
        + math.ceil(_gtd_clock_margin_ms(binance) / 1000)
    )
    if validity <= floor_seconds:
        problems.append(
            "pre_placement.min_remaining_validity_seconds must be above the 600 s goodTillDate "
            "floor plus the confirm TTL plus the GTD clock margin (drift limits)"
        )
    if stale_mark <= tick:
        problems.append(
            "stale_feed.max_mark_price_age_ms must be above one reconcile.tick_interval_ms"
        )
    if probes * probe_interval >= unknown_grace:
        problems.append(
            "reconcile.entry_unknown_probe_count times "
            "reconcile.entry_unknown_probe_interval_ms must be below "
            "protection.entry_unknown_grace_ms"
        )
    # Rule 6 (D114): the stall key is alert only, so unset is not a violation; a set bound must
    # fire before the unprotected deadline, otherwise TASK_STALLED could not warn in time.
    stall_after_ms = limits.scheduler_protection_stall_after_ms
    if stall_after_ms is not None and stall_after_ms >= unprotected:
        problems.append(
            "scheduler.protection_stall_after_ms must be strictly below "
            "protection.max_unprotected_ms (otherwise TASK_STALLED cannot fire before the "
            "unprotected deadline)"
        )
    return problems


@pytest.fixture(scope="module")
def binance() -> BinanceLimits:
    return load_binance_limits(BINANCE_LIMITS_FILE)


def test_the_shipped_limits_satisfy_every_relationship(binance: BinanceLimits) -> None:
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    assert relationship_violations(limits, binance) == []
    check_reconcile_cadence(limits)  # the loader-level guard of rule 1 agrees


def test_the_ratified_inputs_of_the_rules_are_what_the_rules_assume(
    binance: BinanceLimits,
) -> None:
    assert binance.signed.rate_limit.no_retry_after_wait_429_seconds == 120
    assert _gtd_clock_margin_ms(binance) == 1000
    assert GTD_MIN_AHEAD_SECONDS == 600
    assert CONFIRM_TTL_SECONDS_DEFAULT == 60


@pytest.mark.parametrize(
    ("section", "key", "value", "expected_keys"),
    [
        (
            "reconcile",
            "tick_interval_ms",
            180000,  # equal to protection.max_unprotected_ms
            ("reconcile.tick_interval_ms", "protection.max_unprotected_ms"),
        ),
        (
            "protection",
            "max_unprotected_ms",
            150000,  # 120000 + 2 * 15000 = 150000, not above
            ("protection.max_unprotected_ms", "reconcile.tick_interval_ms"),
        ),
        (
            "pre_placement",
            "min_remaining_validity_seconds",
            661,  # 600 + 60 + 1 = 661, not above
            (
                "pre_placement.min_remaining_validity_seconds",
                "goodTillDate",
                "confirm TTL",
            ),
        ),
        (
            "stale_feed",
            "max_mark_price_age_ms",
            15000,  # equal to the tick
            ("stale_feed.max_mark_price_age_ms", "reconcile.tick_interval_ms"),
        ),
        (
            "protection",
            "entry_unknown_grace_ms",
            15000,  # equal to 3 x 5000
            (
                "reconcile.entry_unknown_probe_count",
                "reconcile.entry_unknown_probe_interval_ms",
                "protection.entry_unknown_grace_ms",
            ),
        ),
        (
            "scheduler",
            "protection_stall_after_ms",
            180000,  # equal to protection.max_unprotected_ms
            ("scheduler.protection_stall_after_ms", "protection.max_unprotected_ms"),
        ),
    ],
)
def test_each_relationship_fails_naming_its_keys_on_a_copy(
    tmp_path: Path,
    binance: BinanceLimits,
    section: str,
    key: str,
    value: int,
    expected_keys: tuple[str, ...],
) -> None:
    """Negative control: a tmp copy with one value pushed to the boundary breaks that rule."""
    lines = EXECUTION_LIMITS_FILE.read_text(encoding="utf-8").splitlines()
    current: str | None = None
    edited = 0
    for index, line in enumerate(lines):
        if line.startswith("["):
            current = line.strip("[]")
        elif current == section and line.startswith(f"{key} = "):
            lines[index] = f"{key} = {value}"
            edited += 1
    assert edited == 1, "the negative control must edit exactly one line"
    copy = tmp_path / "execution-limits-v1.toml"
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8")

    problems = relationship_violations(load_execution_limits(copy), binance)

    assert problems, f"{section}.{key} = {value} must break a relationship"
    joined = "\n".join(problems)
    for name in expected_keys:
        assert name in joined, (name, problems)
    # The shipped file itself is untouched by the control.
    assert relationship_violations(load_execution_limits(EXECUTION_LIMITS_FILE), binance) == []


def test_the_loader_level_cadence_guard_agrees_with_rule_one(
    binance: BinanceLimits,
) -> None:
    from src.execution.execution_limits import ExecutionLimitsInvalid

    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    broken = dataclasses.replace(limits, reconcile_tick_interval_ms=limits.max_unprotected_ms)
    with pytest.raises(ExecutionLimitsInvalid):
        check_reconcile_cadence(broken)
    assert any("reconcile.tick_interval_ms" in p for p in relationship_violations(broken, binance))


def test_an_unset_relationship_key_is_itself_a_violation(binance: BinanceLimits) -> None:
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    unset = dataclasses.replace(limits, reconcile_tick_interval_ms=None)
    problems = relationship_violations(unset, binance)
    assert problems == [
        "reconcile.tick_interval_ms is NOT_CONFIGURED, so its relationship cannot hold"
    ]


def test_the_user_data_silence_key_is_d091_and_the_d083_margin_stays_unset() -> None:
    """D091: key 14 = 420000 ms from the Demo silence probe; key 16 stays unset."""
    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    assert document["stale_feed"]["max_user_data_silence_ms"] == 420000
    assert document["provenance"]["stale_feed"]["max_user_data_silence_ms"] == "DECISION"
    assert document["rest_gate"]["ban_end_clock_margin_ms"] == "NOT_CONFIGURED"
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    assert limits.unset_keys() == (), "DECISIONS D091 set the last required key"


def test_an_unset_stall_bound_is_not_a_violation_and_a_set_one_must_stay_below_the_deadline(
    binance: BinanceLimits,
) -> None:
    # Rule 6 (D114): the key is alert only, so unset is allowed; set, it is below the deadline.
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    unset = dataclasses.replace(limits, scheduler_protection_stall_after_ms=None)
    assert relationship_violations(unset, binance) == []
    assert limits.max_unprotected_ms is not None
    at_deadline = dataclasses.replace(
        limits, scheduler_protection_stall_after_ms=limits.max_unprotected_ms
    )
    assert any(
        "scheduler.protection_stall_after_ms" in p
        for p in relationship_violations(at_deadline, binance)
    )


def test_the_shipped_stall_bound_is_d114_and_feeds_a_sixty_second_watchdog(
    binance: BinanceLimits,
) -> None:
    # Quick 261115-pdb (D114, owner answer 2026-11-15): 60000 ms, provenance DECISION.
    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    assert document["scheduler"]["protection_stall_after_ms"] == 60000
    assert document["provenance"]["scheduler"]["protection_stall_after_ms"] == "DECISION"
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    assert limits.scheduler_protection_stall_after == timedelta(seconds=60)
    cadences = LiveCadences.from_limits(limits, binance)
    assert cadences.protection_stall_after == timedelta(seconds=60)
    assert cadences.protection_stall_after_seconds == 60  # compared with an int, no float()
    # The optional summary window is untouched: still unset.
    assert limits.scheduler_duration_summary_interval_ms is None
    assert cadences.duration_summary_interval is None
