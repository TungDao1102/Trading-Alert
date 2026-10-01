"""Partial-fill folding tests (Phase 9, plan 09-02).

Per D-02: fill events arriving out of order or replayed reconcile to a
single position view. Entry-without-protective is a divergence that
forces SAFE_MODE via the Phase-8 reconciler (sweeper never places rescue
protection).

The four behaviors pinned here:

  1. Out-of-order fill events fold to the same FoldedPositionView as
     in-order events.
  2. Replayed events with identical order id plus exchange trade id
     count exactly once.
  3. Folded view sorts deterministically by symbol, order id, trade id.
  4. Entry fills with no protective attached yield
     ENTRY_WITHOUT_PROTECTIVE divergence for the reconciler path.

The tests load the golden fixture pair
(`tests/fixtures/phase9/partial_fills/{input,expected}.json`) and assert
the folded position view matches the expected view byte-for-byte.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import tenacity

PHASE9_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase9"
PARTIAL_FILLS_DIR = PHASE9_FIXTURES_DIR / "partial_fills"


# --------------------------------------------------------------------------- #
# Autouse no-retry-sleep fixture (mirrors test_paper_resync.py).
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: Any) -> None:
    """Bypass production retry sleeps (mirrors test_paper_resync.py)."""
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input() -> dict[str, Any]:
    return json.loads((PARTIAL_FILLS_DIR / "input.json").read_text(encoding="utf-8"))


def _load_expected() -> dict[str, Any]:
    return json.loads((PARTIAL_FILLS_DIR / "expected.json").read_text(encoding="utf-8"))


def _coerce_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(f"{field_name} must be Decimal/str/int, got {type(value).__name__}")


def _build_fill_events(case_input: dict[str, Any]) -> list[Any]:
    """Build fill event objects from the fixture input."""
    from datetime import datetime

    from src.execution.fill_monitor import FillEvent

    events = []
    for fe in case_input["fill_events"]:
        events.append(
            FillEvent(
                order_id=fe["order_id"],
                exchange_trade_id=fe["exchange_trade_id"],
                symbol=fe["symbol"],
                side=fe["side"],
                position_side=fe["position_side"],
                fill_price=_coerce_decimal(fe["fill_price"], "fill_price"),
                fill_quantity=_coerce_decimal(fe["fill_quantity"], "fill_quantity"),
                fill_time_utc=datetime.fromisoformat(fe["fill_time_utc"]),
            )
        )
    return events


def _build_current_position_view(case_input: dict[str, Any]) -> Any:
    """Build a current position view from the fixture input."""
    from src.execution.fill_monitor import CurrentPositionView

    cpv = case_input["current_position_view"]
    return CurrentPositionView(
        symbol=cpv["symbol"],
        position_side=cpv["position_side"],
        position_amt=_coerce_decimal(cpv["position_amt"], "position_amt"),
    )


# --------------------------------------------------------------------------- #
# Beh. 1 — out-of-order fill events fold to the same view as in-order.
# --------------------------------------------------------------------------- #


def test_out_of_order_fills_fold_to_same_view_as_in_order() -> None:
    """Beh. 1: out-of-order fill events fold to the same FoldedPositionView
    as in-order events.
    """
    from src.execution.fill_monitor import fold_fills

    case_input = _load_input()
    expected = _load_expected()

    fill_events = _build_fill_events(case_input)
    current_view = _build_current_position_view(case_input)

    # Fold the events as-given (out-of-order + replayed).
    result = fold_fills(
        fill_events=fill_events,
        current_position_view=current_view,
    )

    # The folded view should match the expected view.
    assert result.filled_quantity == _coerce_decimal(
        expected["folded_position_view"]["filled_quantity"], "filled_quantity"
    )
    assert result.fill_count == expected["folded_position_view"]["fill_count"]
    assert result.symbol == expected["folded_position_view"]["symbol"]
    assert result.position_side == expected["folded_position_view"]["position_side"]
    assert result.position_amt == _coerce_decimal(
        expected["folded_position_view"]["position_amt"], "position_amt"
    )

    # Fills are sorted deterministically by (order_id, exchange_trade_id).
    assert len(result.fills) == len(expected["folded_position_view"]["fills"])
    for actual, exp in zip(result.fills, expected["folded_position_view"]["fills"], strict=True):
        assert actual["order_id"] == exp["order_id"]
        assert actual["exchange_trade_id"] == exp["exchange_trade_id"]
        assert actual["fill_price"] == _coerce_decimal(exp["fill_price"], "fill_price")
        assert actual["fill_quantity"] == _coerce_decimal(exp["fill_quantity"], "fill_quantity")


# --------------------------------------------------------------------------- #
# Beh. 2 — replayed events with identical (order_id, exchange_trade_id) count once.
# --------------------------------------------------------------------------- #


def test_replayed_fills_count_exactly_once() -> None:
    """Beh. 2: replayed events with identical order id plus exchange
    trade id count exactly once.
    """
    from src.execution.fill_monitor import fold_fills

    case_input = _load_input()
    expected = _load_expected()

    fill_events = _build_fill_events(case_input)
    current_view = _build_current_position_view(case_input)

    result = fold_fills(
        fill_events=fill_events,
        current_position_view=current_view,
    )

    # The fixture has 4 events but trade_001 is replayed (2 copies).
    # Expected fill_count is 3 (deduplicated).
    assert result.fill_count == 3, (
        f"replayed fills must count once: got {result.fill_count}, expected 3"
    )
    assert result.fill_count == expected["folded_position_view"]["fill_count"]


# --------------------------------------------------------------------------- #
# Beh. 3 — folded view sorts deterministically by (symbol, order_id, trade_id).
# --------------------------------------------------------------------------- #


def test_folded_view_sorts_deterministically() -> None:
    """Beh. 3: folded view sorts deterministically by symbol, order id,
    trade id.
    """
    from src.execution.fill_monitor import fold_fills

    case_input = _load_input()
    expected = _load_expected()

    fill_events = _build_fill_events(case_input)
    current_view = _build_current_position_view(case_input)

    # Run fold_fills twice — must yield byte-identical views.
    result1 = fold_fills(
        fill_events=fill_events,
        current_position_view=current_view,
    )
    result2 = fold_fills(
        fill_events=fill_events,
        current_position_view=current_view,
    )

    # Byte-identical: same fill_count, same fills in same order.
    assert result1.fill_count == result2.fill_count
    assert len(result1.fills) == len(result2.fills)
    for f1, f2 in zip(result1.fills, result2.fills, strict=True):
        assert f1 == f2, f"non-deterministic fold: {f1} != {f2}"

    # The fills are sorted by (order_id, exchange_trade_id).
    expected_order = [
        (f["order_id"], f["exchange_trade_id"]) for f in expected["folded_position_view"]["fills"]
    ]
    actual_order = [(f["order_id"], f["exchange_trade_id"]) for f in result1.fills]
    assert actual_order == expected_order, (
        f"sort order mismatch: got {actual_order}, expected {expected_order}"
    )


# --------------------------------------------------------------------------- #
# Beh. 4 — entry-without-protective yields ENTRY_WITHOUT_PROTECTIVE divergence.
# --------------------------------------------------------------------------- #


def test_entry_without_protective_yields_divergence() -> None:
    """Beh. 4: entry fills with no protective attached yield
    ENTRY_WITHOUT_PROTECTIVE divergence for the reconciler path.
    """
    from datetime import datetime

    from src.execution.fill_monitor import FillEvent, fold_fills

    # Build a fill event with no protective attached.
    fill_event = FillEvent(
        order_id="ord_entry_001",
        exchange_trade_id="trade_entry_001",
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        fill_price=Decimal("100.00"),
        fill_quantity=Decimal("0.500"),
        fill_time_utc=datetime.fromisoformat("2026-09-19T10:30:00+00:00"),
    )

    from src.execution.fill_monitor import CurrentPositionView

    current_view = CurrentPositionView(
        symbol="BTCUSDT",
        position_side="BOTH",
        position_amt=Decimal("0.000"),
    )

    # No protective attached → divergence.
    result = fold_fills(
        fill_events=[fill_event],
        current_position_view=current_view,
        has_protective=False,
    )

    assert len(result.divergences) == 1
    assert result.divergences[0]["kind"] == "ENTRY_WITHOUT_PROTECTIVE"
    assert result.divergences[0]["symbol"] == "BTCUSDT"


# --------------------------------------------------------------------------- #
# Beh. 5 — purity: no Binance SDK / SQLAlchemy / Pydantic / Polars imports.
# --------------------------------------------------------------------------- #


def test_fill_monitor_module_purity() -> None:
    """Beh. 5: src/execution/fill_monitor.py does not import Binance SDK,
    SQLAlchemy, Pydantic, or Polars.
    """
    import re
    from pathlib import Path

    module_path = Path(__file__).resolve().parents[1] / "src" / "execution" / "fill_monitor.py"
    # 09-REVIEW WR-12: a missing module must FAIL the purity test, never
    # skip it (a silent skip is a false green).
    assert module_path.is_file(), f"purity target missing: {module_path}"
    source = module_path.read_text(encoding="utf-8")
    forbidden_patterns = [
        r"\bimport\s+binance_sdk\b",
        r"\bfrom\s+binance_sdk\b",
        r"\bimport\s+sqlalchemy\b",
        r"\bfrom\s+sqlalchemy\b",
        r"\bimport\s+pydantic\b",
        r"\bfrom\s+pydantic\b",
        r"\bimport\s+polars\b",
        r"\bfrom\s+polars\b",
    ]
    for pattern in forbidden_patterns:
        match = re.search(pattern, source)
        assert match is None, (
            f"forbidden import in {module_path}: pattern={pattern!r}, match={match.group(0)!r}"
        )


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-04 — flag, never fabricate: foreign / malformed fills raise.
# --------------------------------------------------------------------------- #


def _fill(**overrides: Any) -> Any:
    from datetime import datetime

    from src.execution.fill_monitor import FillEvent

    fields: dict[str, Any] = {
        "order_id": "ord_001",
        "exchange_trade_id": "trade_001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "fill_price": Decimal("100.00"),
        "fill_quantity": Decimal("0.100"),
        "fill_time_utc": datetime.fromisoformat("2026-09-19T10:30:01+00:00"),
    }
    fields.update(overrides)
    return FillEvent(**fields)


def _flat_view(position_amt: str = "0.000") -> Any:
    from src.execution.fill_monitor import CurrentPositionView

    return CurrentPositionView(
        symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal(position_amt)
    )


def test_exit_side_fill_is_rejected_not_summed() -> None:
    from src.execution.fill_monitor import fold_fills

    events = [_fill(), _fill(exchange_trade_id="trade_tp1", side="SELL")]
    with pytest.raises(ValueError, match="side"):
        fold_fills(
            fill_events=events,
            current_position_view=_flat_view(),
            expected_symbol="BTCUSDT",
            expected_side="BUY",
        )


def test_foreign_symbol_or_order_fill_is_rejected() -> None:
    from src.execution.fill_monitor import fold_fills

    with pytest.raises(ValueError, match="symbol"):
        fold_fills(
            fill_events=[_fill(symbol="ETHUSDT")],
            current_position_view=_flat_view(),
            expected_symbol="BTCUSDT",
        )
    with pytest.raises(ValueError, match="order_id"):
        fold_fills(
            fill_events=[_fill(order_id="ord_other")],
            current_position_view=_flat_view(),
            expected_order_id="ord_001",
        )


def test_raw_string_quantity_and_missing_identity_raise() -> None:
    from src.execution.fill_monitor import fold_fills

    raw_ws_event = {
        "order_id": "ord_001",
        "exchange_trade_id": "trade_001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "fill_quantity": "0.100",
    }
    with pytest.raises(TypeError, match="Decimal"):
        fold_fills(fill_events=[raw_ws_event], current_position_view=_flat_view())
    missing_id = dict(raw_ws_event, exchange_trade_id="", fill_quantity=Decimal("0.1"))
    with pytest.raises(ValueError, match="exchange_trade_id"):
        fold_fills(fill_events=[missing_id], current_position_view=_flat_view())


def test_short_fills_decrease_the_signed_position_amount() -> None:
    from src.execution.fill_monitor import fold_fills

    result = fold_fills(
        fill_events=[_fill(side="SELL", fill_quantity=Decimal("0.200"))],
        current_position_view=_flat_view("-0.100"),
    )
    assert result.filled_quantity == Decimal("0.200")
    assert result.position_amt == Decimal("-0.300")
