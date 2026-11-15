"""The smoke plan must outlive the owner's minimum remaining validity (first Demo run).

CONFIRM was refused VALIDITY_TOO_SHORT: the plan lived `approval_timeout + 10 min` = 15 min while
`pre_placement.min_remaining_validity_seconds` is 900, so no moment after detection could pass.
"""

from __future__ import annotations

from datetime import timedelta

from src.execution.pre_placement import check_remaining_validity
from src.live.signal_source import DemoSmokeSignalSource

from tests.test_live_approval_sender import PARAMETER_SET, derive

MIN_REMAINING = 900
CLOCK_MARGIN = timedelta(seconds=1)


def _lifetime(source: DemoSmokeSignalSource) -> timedelta:
    request = derive(source)
    return request.plan.expiry_utc - request.signal.detected_at_utc


def test_without_an_owner_minimum_the_lifetime_is_unchanged() -> None:
    source = DemoSmokeSignalSource(run_id="r", parameter_set=PARAMETER_SET)
    assert _lifetime(source) == timedelta(seconds=300) + timedelta(minutes=10)


def test_the_old_lifetime_could_never_pass_the_owner_minimum() -> None:
    source = DemoSmokeSignalSource(run_id="r", parameter_set=PARAMETER_SET)
    request = derive(source)
    refusal = check_remaining_validity(
        expiry_utc=request.plan.expiry_utc,
        now_utc=request.signal.detected_at_utc,
        min_remaining_validity_seconds=MIN_REMAINING,
        gtd_clock_margin=CLOCK_MARGIN,
    )
    assert refusal == "VALIDITY_TOO_SHORT"


def test_with_the_owner_minimum_confirm_passes_after_both_taps_take_the_full_timeout() -> None:
    source = DemoSmokeSignalSource(
        run_id="r", parameter_set=PARAMETER_SET, min_remaining_validity_seconds=MIN_REMAINING
    )
    request = derive(source)
    after_both_taps = request.signal.detected_at_utc + timedelta(seconds=2 * 300)
    assert (
        check_remaining_validity(
            expiry_utc=request.plan.expiry_utc,
            now_utc=after_both_taps,
            min_remaining_validity_seconds=MIN_REMAINING,
            gtd_clock_margin=CLOCK_MARGIN,
        )
        is None
    )
