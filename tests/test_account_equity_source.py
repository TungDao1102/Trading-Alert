"""LiveEquitySource (Phase 21, plan 21-07; F-012, D-01, D-02, D-03, D-20).

The tracer runs the committed recorded-Demo payloads (demo-observed, not mainnet) through the
REAL ``BinanceUsdmAdapter`` over a fake SDK, the source and the pure resolver. The rest of the
file pins the fail-closed behavior with a scripted reader.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.adapters.binance_ratelimit_gate import RateLimitPauseActive
from src.adapters.binance_usdm import (
    AccountAssetRow,
    AccountBalanceRow,
    AccountConfigSnapshot,
    AccountInformationSnapshot,
)
from src.domain.enums import RejectionReason
from src.execution.account_equity import (
    INVALIDATION_REASONS,
    LiveEquitySource,
    equity_reading_from_snapshots,
)
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from structlog.testing import capture_logs

from tests.support.account_fakes import (
    BALANCES,
    CONFIG,
    INFORMATION,
    ScriptedAccountReader,
    build_demo_adapter,
    demo_account_snapshots,
)
from tests.support.ast_guards import wall_clock_calls
from tests.support.execution_limits import test_only_execution_limits as only_limits
from tests.support.virtual_time import VirtualTime

RISK_RATE = Decimal("0.005")
UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
DEMO_EQUITY = Decimal("4999.09343961")
MODULE = Path(__file__).resolve().parent.parent / "src" / "execution" / "account_equity.py"
AGE_MS = 9137  # TEST_ONLY value of account.max_equity_age_ms


class MovingClock:
    """A plain mutable clock for the fake SDK (its calls are synchronous worker-thread calls)."""

    def __init__(self) -> None:
        self.value = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _source(
    reader: object, clock: object, *, quote_asset: str = "USDT", **limit_overrides: int | None
) -> LiveEquitySource:
    return LiveEquitySource(
        adapter=reader,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        limits=only_limits(**limit_overrides),
        quote_asset=quote_asset,
    )


async def _scripted_good(virtual_time: VirtualTime, **kwargs: int) -> ScriptedAccountReader:
    information, balances, config = await demo_account_snapshots()
    return ScriptedAccountReader(
        {CONFIG: [config], INFORMATION: [information], BALANCES: [balances]},
        virtual_time=virtual_time,
        **kwargs,
    )


# --------------------------------------------------------------------------- Task 1: tracer


async def test_recorded_demo_payloads_reach_account_state_through_the_real_adapter() -> None:
    clock = MovingClock()

    def advance(_: str) -> None:
        clock.value += timedelta(seconds=1)

    adapter, rest = build_demo_adapter(on_sdk_call=advance)
    start = clock()
    source = _source(adapter, clock)
    await source.refresh()
    assert source.last_error_type is None
    assert rest.called == [
        "futures_account_configuration",
        "account_information_v3",
        "futures_account_balance_v3",
    ]
    result = source.resolve(risk_rate=RISK_RATE, now_utc=clock())
    assert result.reason_code == "OK"
    assert result.account_state is not None
    assert result.account_state.equity == DEMO_EQUITY
    assert result.account_state.risk_rate == RISK_RATE
    # Stamped BEFORE the first request: the age is only over-estimated.
    assert result.observed_at_utc == start
    assert clock() - start == timedelta(seconds=3)


async def test_equity_is_no_trade_before_any_refresh() -> None:
    source = _source(ScriptedAccountReader({}), VirtualTime())
    result = source.resolve(risk_rate=RISK_RATE, now_utc=VirtualTime()())
    assert result.account_state is None
    assert result.reason_code == UNCERTAIN


async def test_reading_maps_the_quote_asset_rows_only() -> None:
    information, balances, config = await demo_account_snapshots()
    stamp = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
    usdt = equity_reading_from_snapshots(
        information=information,
        balances=balances,
        config=config,
        quote_asset="USDT",
        observed_at_utc=stamp,
    )
    assert usdt.quote_asset_margin_balance == DEMO_EQUITY
    assert usdt.balance_endpoint_wallet == DEMO_EQUITY
    assert usdt.total_margin_balance == DEMO_EQUITY
    assert usdt.multi_assets_margin is False
    assert usdt.observed_at_utc == stamp
    # Phase 22 (plan 22-10): the free-margin figures and the mode flag of the same reading.
    assert usdt.available_balance == DEMO_EQUITY
    assert usdt.total_open_order_initial_margin == Decimal("0.00000000")
    assert usdt.quote_asset_available_balance == DEMO_EQUITY
    assert usdt.dual_side_position is False
    usdc = equity_reading_from_snapshots(
        information=information,
        balances=balances,
        config=config,
        quote_asset="USDC",
        observed_at_utc=stamp,
    )
    assert usdc.quote_asset_margin_balance == Decimal("5000.00000000")
    assert usdc.quote_asset_margin_balance != usdt.quote_asset_margin_balance
    assert usdc.quote_asset_available_balance == Decimal("5000.00000000")
    assert usdc.available_balance == DEMO_EQUITY  # the account-level figure, not the row's


async def test_the_hedge_flag_comes_from_the_same_account_config_read() -> None:
    information, balances, _ = await demo_account_snapshots()
    reading = equity_reading_from_snapshots(
        information=information,
        balances=balances,
        config=AccountConfigSnapshot(multi_assets_margin=False, dual_side_position=True),
        quote_asset="USDT",
        observed_at_utc=datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC),
    )
    assert reading.dual_side_position is True
    with pytest.raises(TypeError, match="dual_side_position"):
        equity_reading_from_snapshots(
            information=information,
            balances=balances,
            config=AccountConfigSnapshot(multi_assets_margin=False, dual_side_position="no"),  # type: ignore[arg-type]
            quote_asset="USDT",
            observed_at_utc=datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC),
        )


async def test_a_missing_quote_row_maps_to_none_and_the_resolver_refuses() -> None:
    information, balances, config = await demo_account_snapshots()
    reading = equity_reading_from_snapshots(
        information=information,
        balances=balances,
        config=config,
        quote_asset="NOPE",
        observed_at_utc=datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC),
    )
    assert reading.quote_asset_margin_balance is None
    assert reading.balance_endpoint_wallet is None
    assert reading.quote_asset_available_balance is None
    clock = VirtualTime()
    source = _source(
        ScriptedAccountReader({CONFIG: [config], INFORMATION: [information], BALANCES: [balances]}),
        clock,
        quote_asset="NOPE",
    )
    await source.refresh()
    result = source.resolve(risk_rate=RISK_RATE, now_utc=clock())
    assert result.account_state is None
    assert result.reason_code == UNCERTAIN


async def test_two_quote_rows_or_a_wrong_type_is_a_failed_read() -> None:
    information, balances, config = await demo_account_snapshots()
    twice = (*balances, balances[0])
    clock = VirtualTime()
    source = _source(
        ScriptedAccountReader(
            {CONFIG: [config], INFORMATION: [information], BALANCES: [twice]},
        ),
        clock,
        quote_asset=balances[0].asset,
    )
    await source.refresh()
    assert source.last_error_type == "ValueError"
    assert source.resolve(risk_rate=RISK_RATE, now_utc=clock()).account_state is None

    float_info = AccountInformationSnapshot(
        total_margin_balance=1.5,  # type: ignore[arg-type]
        total_wallet_balance=Decimal("1"),
        total_unrealized_profit=Decimal("0"),
        available_balance=Decimal("1"),
        total_open_order_initial_margin=Decimal("0"),
        assets=(AccountAssetRow("USDT", Decimal("1"), Decimal("0"), Decimal("1"), Decimal("1")),),
    )
    source = _source(
        ScriptedAccountReader(
            {
                CONFIG: [AccountConfigSnapshot(False, False)],
                INFORMATION: [float_info],
                BALANCES: [(AccountBalanceRow("USDT", Decimal("1"), Decimal("0")),)],
            }
        ),
        clock,
    )
    await source.refresh()
    assert source.last_error_type == "TypeError"


async def test_freshness_contract_now_is_read_after_refresh() -> None:
    """Callers take now_utc AFTER refresh() returns (plans 21-11 and 21-13 rely on it).

    refresh() stamps the reading with the clock BEFORE its first request, and the fake reader
    moves the virtual clock by 1 s per call (3 s in total). A now_utc captured before
    refresh() can precede the stamp (here the clock moves 1 s between the capture and the
    refresh): a negative age, stale by design (D-03). A now_utc read after refresh() is OK
    with age 3 s.
    """
    clock = VirtualTime()
    reader = await _scripted_good(clock, advance_seconds_per_call=1)
    source = _source(reader, clock)
    now_before = clock()
    await clock.advance(1)
    stamp = clock()
    await source.refresh()
    now_after = clock()
    assert now_after - stamp == timedelta(seconds=3)

    early = source.resolve(risk_rate=RISK_RATE, now_utc=now_before)
    assert early.account_state is None
    assert early.reason_code == UNCERTAIN

    fresh = source.resolve(risk_rate=RISK_RATE, now_utc=now_after)
    assert fresh.account_state is not None
    assert fresh.account_state.equity == DEMO_EQUITY
    assert fresh.observed_at_utc == stamp  # stamped before the first request
    assert now_after - fresh.observed_at_utc == timedelta(seconds=3)


# --------------------------------------------------------------------------- Task 2: fail closed


@pytest.mark.parametrize("failing", [CONFIG, INFORMATION, BALANCES])
@pytest.mark.parametrize(
    "error", [RateLimitPauseActive(0), RuntimeError("boom 4999.09"), ValueError("bad field")]
)
async def test_any_failed_read_is_no_trade_recorded_by_type_and_never_retried(
    failing: str, error: BaseException
) -> None:
    clock = VirtualTime()
    good = await _scripted_good(clock)
    responses: dict[str, list[object | BaseException]] = {
        CONFIG: [await _value(good, CONFIG)],
        INFORMATION: [await _value(good, INFORMATION)],
        BALANCES: [await _value(good, BALANCES)],
    }
    responses[failing] = [error, error]
    reader = ScriptedAccountReader(responses)
    source = _source(reader, clock)
    await source.refresh()
    assert source.last_error_type == type(error).__name__
    result = source.resolve(risk_rate=RISK_RATE, now_utc=clock())
    assert result.account_state is None
    assert result.reason_code == UNCERTAIN
    assert all(reader.count(name) <= 1 for name in (CONFIG, INFORMATION, BALANCES))
    assert reader.count(failing) == 1


async def _value(reader: ScriptedAccountReader, name: str) -> object:
    return await getattr(reader, name)()


async def test_a_failed_refresh_drops_the_earlier_reading() -> None:
    clock = VirtualTime()
    information, balances, config = await demo_account_snapshots()
    reader = ScriptedAccountReader(
        {
            CONFIG: [config, RuntimeError("down")],
            INFORMATION: [information],
            BALANCES: [balances],
        }
    )
    source = _source(reader, clock)
    await source.refresh()
    assert source.resolve(risk_rate=RISK_RATE, now_utc=clock()).account_state is not None
    await source.refresh()
    assert source.last_error_type == "RuntimeError"
    assert source.resolve(risk_rate=RISK_RATE, now_utc=clock()).account_state is None


async def test_multi_assets_margin_is_refused() -> None:
    clock = VirtualTime()
    information, balances, _ = await demo_account_snapshots()
    reader = ScriptedAccountReader(
        {
            CONFIG: [AccountConfigSnapshot(multi_assets_margin=True, dual_side_position=False)],
            INFORMATION: [information],
            BALANCES: [balances],
        }
    )
    source = _source(reader, clock)
    await source.refresh()
    assert source.last_error_type is None
    result = source.resolve(risk_rate=RISK_RATE, now_utc=clock())
    assert result.account_state is None
    assert result.reason_code == UNCERTAIN


@pytest.mark.parametrize("reason", ["ACCOUNT_UPDATE", "STREAM_GAP"])
async def test_invalidate_drops_the_reading_until_the_next_successful_refresh(reason: str) -> None:
    clock = VirtualTime()
    information, balances, config = await demo_account_snapshots()
    reader = ScriptedAccountReader(
        {
            CONFIG: [config, config],
            INFORMATION: [information, information],
            BALANCES: [balances, balances],
        }
    )
    source = _source(reader, clock)
    await source.refresh()
    assert source.resolve(risk_rate=RISK_RATE, now_utc=clock()).account_state is not None
    assert source.last_invalidation_reason is None
    source.invalidate(reason=reason)
    assert source.last_invalidation_reason == reason
    gone = source.resolve(risk_rate=RISK_RATE, now_utc=clock())
    assert gone.account_state is None
    assert gone.reason_code == UNCERTAIN
    await source.refresh()
    assert source.resolve(risk_rate=RISK_RATE, now_utc=clock()).account_state is not None


def test_invalidate_refuses_an_unknown_reason() -> None:
    assert INVALIDATION_REASONS == frozenset({"ACCOUNT_UPDATE", "STREAM_GAP"})
    source = _source(ScriptedAccountReader({}), VirtualTime())
    with pytest.raises(ValueError):
        source.invalidate(reason="OTHER")


async def test_an_invalidate_during_a_refresh_discards_its_result() -> None:
    clock = VirtualTime()
    information, balances, config = await demo_account_snapshots()
    holder: dict[str, LiveEquitySource] = {}

    class _Racing(ScriptedAccountReader):
        async def account_information_snapshot(self) -> object:
            holder["source"].invalidate(reason="ACCOUNT_UPDATE")
            return await super().account_information_snapshot()

    reader = _Racing({CONFIG: [config], INFORMATION: [information], BALANCES: [balances]})
    source = _source(reader, clock)
    holder["source"] = source
    await source.refresh()
    assert source.resolve(risk_rate=RISK_RATE, now_utc=clock()).account_state is None


async def test_the_age_bound_comes_from_the_limit_key() -> None:
    clock = VirtualTime()
    reader = await _scripted_good(clock)
    source = _source(reader, clock)
    await source.refresh()
    stamp = clock()
    for delta_ms, expected_ok in ((AGE_MS, True), (AGE_MS + 1, False), (-1, False)):
        check = source.check(now_utc=stamp + timedelta(milliseconds=delta_ms))
        assert (check.equity is not None) is expected_ok, delta_ms
        resolved = source.resolve(
            risk_rate=RISK_RATE, now_utc=stamp + timedelta(milliseconds=delta_ms)
        )
        assert (resolved.account_state is not None) is expected_ok, delta_ms


async def test_a_different_limit_value_moves_the_bound() -> None:
    clock = VirtualTime()
    reader = await _scripted_good(clock)
    source = _source(reader, clock, account_max_equity_age_ms=500)
    await source.refresh()
    stamp = clock()
    assert source.check(now_utc=stamp + timedelta(milliseconds=500)).equity == DEMO_EQUITY
    assert source.check(now_utc=stamp + timedelta(milliseconds=501)).equity is None


def test_construction_refuses_while_the_age_limit_is_not_configured() -> None:
    with pytest.raises(ExecutionLimitsNotConfigured) as caught:
        _source(ScriptedAccountReader({}), VirtualTime(), account_max_equity_age_ms=None)
    assert caught.value.keys == ("account.max_equity_age_ms",)


async def test_logs_carry_no_balance_and_no_exception_text() -> None:
    clock = VirtualTime()
    good = await _scripted_good(clock)
    with capture_logs() as ok_logs:
        await _source(good, clock).refresh()
    information, balances, config = await demo_account_snapshots()
    failing = ScriptedAccountReader(
        {
            CONFIG: [config],
            INFORMATION: [RuntimeError("secret-token 4999.09343961")],
            BALANCES: [balances],
        }
    )
    with capture_logs() as bad_logs:
        await _source(failing, clock).refresh()
    rendered = repr(ok_logs) + repr(bad_logs)
    assert "4999" not in rendered
    assert "secret-token" not in rendered
    assert information is not None


def test_the_module_reads_no_wall_clock_and_imports_no_sdk_or_adapter() -> None:
    assert wall_clock_calls(MODULE) == []
    source = MODULE.read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert not any("src.adapters" in line or "binance" in line for line in imports)
    assert "float(" not in source
