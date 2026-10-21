"""Phase 20 plan 20-04: compare v2 (reverse pass, id predicates, vocabulary).

The three-source compare used to see only what local intent already knew about. Version 2 adds a
reverse pass over the exchange orders, so an order nobody local owns is a divergence (FOREIGN_ORDER
or UNTRACKED_SYSTEM_ORDER), never sweepable. The id predicates that tell a system id from a foreign
one live in `src.execution.order_ids`; `compare.py` carries no id-prefix literal of its own.

Pure unit tests over dataclass / namespace fixtures: no exchange, no database, no clock.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.execution import order_ids
from src.execution.order_ids import (
    derive_algo_client_id,
    derive_client_order_id,
    derive_close_order_id,
)
from src.reconcile.compare import (
    CompareDiff,
    LocalAlgoIntent,
    LocalOrderIntent,
    LocalPositionIntent,
    compare,
)

# `src.reconcile` re-exports the function `compare`, which shadows the submodule attribute.
compare_module = importlib.import_module("src.reconcile.compare")

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPARE_PATH = REPO_ROOT / "src" / "reconcile" / "compare.py"
ORDER_IDS_PATH = REPO_ROOT / "src" / "execution" / "order_ids.py"


def _plan_hash(n: int) -> str:
    return hashlib.sha256(f"plan-{n}".encode()).hexdigest()


PLAN_A = _plan_hash(1)
PLAN_B = _plan_hash(2)
SYMBOL = "BTCUSDT"


# --------------------------------------------------------------------------- #
# Builders.
# --------------------------------------------------------------------------- #


def _truth_order(client_order_id: str | None, symbol: str = SYMBOL) -> Any:
    return SimpleNamespace(
        symbol=symbol,
        client_order_id=client_order_id,
        side="BUY",
        position_side="BOTH",
        order_type="LIMIT",
    )


def _truth_algo(client_algo_id: str | None, symbol: str = SYMBOL, algo_status: str = "NEW") -> Any:
    return SimpleNamespace(
        symbol=symbol,
        client_algo_id=client_algo_id,
        algo_status=algo_status,
        side="SELL",
        position_side="BOTH",
        order_type="STOP_MARKET",
    )


def _truth_position(symbol: str, amount: Any, position_side: str = "BOTH") -> Any:
    return SimpleNamespace(symbol=symbol, position_side=position_side, position_amt=amount)


def _run(
    *,
    local_open_orders: Sequence[Any] = (),
    local_open_algos: Sequence[Any] = (),
    local_open_positions: Sequence[Any] = (),
    truth_normal_orders: Sequence[Any] = (),
    truth_algo_orders: Sequence[Any] = (),
    truth_positions: Sequence[Any] = (),
) -> CompareDiff:
    return compare(
        local_open_orders=list(local_open_orders),
        local_open_algos=list(local_open_algos),
        local_open_positions=list(local_open_positions),
        truth_normal_orders=list(truth_normal_orders),
        truth_algo_orders=list(truth_algo_orders),
        truth_positions=list(truth_positions),
    )


def _kinds(diff: CompareDiff) -> list[str]:
    return [d.kind for d in diff.divergences]


# --------------------------------------------------------------------------- #
# Task 1 - id predicates.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["ENTRY", "STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"])
def test_is_system_client_id_true_for_every_derived_id_family(role: str) -> None:
    assert order_ids.is_system_client_id(derive_client_order_id(plan_hash=PLAN_A, role=role))
    assert order_ids.is_system_client_id(derive_algo_client_id(plan_hash=PLAN_A, role=role))


def test_is_system_client_id_true_for_a_close_id() -> None:
    assert order_ids.is_system_client_id(derive_close_order_id(plan_hash=PLAN_A, attempt_no=1))


@pytest.mark.parametrize(
    "value",
    ["web_abc", "", "y-" + "a" * 34, "x-short", None, 123, b"x-" + b"a" * 34, ["x-"]],
)
def test_is_system_client_id_false_for_foreign_or_non_string(value: object) -> None:
    assert order_ids.is_system_client_id(value) is False  # type: ignore[arg-type]


def test_plan_hash_prefix_is_the_shared_29_chars_of_all_three_families() -> None:
    entry = derive_client_order_id(plan_hash=PLAN_A, role="ENTRY")
    stop = derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS")
    close = derive_close_order_id(plan_hash=PLAN_A, attempt_no=3)
    assert order_ids.plan_hash_prefix_of(entry) == PLAN_A[:29]
    assert order_ids.plan_hash_prefix_of(stop) == PLAN_A[:29]
    assert order_ids.plan_hash_prefix_of(close) == PLAN_A[:29]
    assert len(PLAN_A[:29]) == 29
    other = derive_client_order_id(plan_hash=PLAN_B, role="ENTRY")
    assert order_ids.plan_hash_prefix_of(other) != order_ids.plan_hash_prefix_of(entry)


@pytest.mark.parametrize("value", ["web_abc", "", None, 5, "y-" + "a" * 34])
def test_plan_hash_prefix_is_none_for_a_non_system_id(value: object) -> None:
    assert order_ids.plan_hash_prefix_of(value) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("role", ["ENTRY", "STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"])
def test_role_of_client_id_round_trips_normal_and_algo_ids(role: str) -> None:
    assert order_ids.role_of_client_id(derive_client_order_id(plan_hash=PLAN_A, role=role)) == role
    assert order_ids.role_of_client_id(derive_algo_client_id(plan_hash=PLAN_A, role=role)) == role


def test_role_of_client_id_is_none_for_a_close_or_foreign_id() -> None:
    assert (
        order_ids.role_of_client_id(derive_close_order_id(plan_hash=PLAN_A, attempt_no=1)) is None
    )
    assert order_ids.role_of_client_id("web_abc") is None
    assert order_ids.role_of_client_id(None) is None  # type: ignore[arg-type]
    unknown_code = "x-" + PLAN_A[:32] + "ZZ"
    assert order_ids.is_system_client_id(unknown_code)
    assert order_ids.role_of_client_id(unknown_code) is None


# --------------------------------------------------------------------------- #
# Task 1 - reverse pass.
# --------------------------------------------------------------------------- #


def test_a_foreign_normal_order_is_a_foreign_order_divergence_and_never_sweepable() -> None:
    diff = _run(truth_normal_orders=[_truth_order("web_manual_1")])
    assert diff.agreement is False
    assert _kinds(diff) == ["FOREIGN_ORDER"]
    assert diff.divergences[0].client_order_id == "web_manual_1"
    assert diff.divergences[0].symbol == SYMBOL
    assert diff.orphan_protectives == ()


def test_a_system_prefixed_normal_order_unknown_locally_is_untracked_system_order() -> None:
    cid = derive_client_order_id(plan_hash=PLAN_A, role="ENTRY")
    diff = _run(truth_normal_orders=[_truth_order(cid)])
    assert diff.agreement is False
    assert _kinds(diff) == ["UNTRACKED_SYSTEM_ORDER"]
    assert diff.divergences[0].client_order_id == cid
    assert diff.orphan_protectives == ()


def test_a_foreign_algo_order_is_a_foreign_order_divergence_and_never_sweepable() -> None:
    diff = _run(truth_algo_orders=[_truth_algo("ui_stop_9")])
    assert diff.agreement is False
    assert _kinds(diff) == ["FOREIGN_ORDER"]
    assert diff.divergences[0].client_algo_id == "ui_stop_9"
    assert diff.orphan_protectives == ()


def test_a_system_prefixed_algo_order_unknown_locally_is_untracked_system_order() -> None:
    aid = derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS")
    diff = _run(truth_algo_orders=[_truth_algo(aid)])
    assert _kinds(diff) == ["UNTRACKED_SYSTEM_ORDER"]
    assert diff.divergences[0].client_algo_id == aid
    assert diff.orphan_protectives == ()


def test_a_truth_order_without_any_id_is_a_foreign_order() -> None:
    diff = _run(truth_normal_orders=[_truth_order(None)])
    assert _kinds(diff) == ["FOREIGN_ORDER"]
    assert diff.divergences[0].client_order_id is None


def test_a_foreign_order_next_to_an_orphan_protective_keeps_only_the_orphan_sweepable() -> None:
    aid = derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS")
    diff = _run(
        local_open_algos=[
            LocalAlgoIntent(client_algo_id=aid, symbol=SYMBOL, order_role="STOP_LOSS", status="NEW")
        ],
        truth_algo_orders=[_truth_algo(aid)],
        truth_normal_orders=[_truth_order("web_manual_1")],
    )
    assert sorted(_kinds(diff)) == ["FOREIGN_ORDER", "ORPHAN_PROTECTIVE"]
    assert [o.client_algo_id for o in diff.orphan_protectives] == [aid]


def _clean_fixture() -> dict[str, Any]:
    """One open LONG position with its local stop and the matching exchange rows."""
    aid = derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS")
    return {
        "local_open_algos": [
            LocalAlgoIntent(client_algo_id=aid, symbol=SYMBOL, order_role="STOP_LOSS", status="NEW")
        ],
        "local_open_positions": [
            LocalPositionIntent(
                symbol=SYMBOL,
                position_side="BOTH",
                position_amt=Decimal("0.004"),
                plan_hash=PLAN_A,
                expected_side="LONG",
                max_abs_amount=Decimal("0.004"),
            )
        ],
        "truth_algo_orders": [_truth_algo(aid)],
        "truth_positions": [_truth_position(SYMBOL, Decimal("0.004"))],
    }


def test_a_clean_fixture_where_every_exchange_row_is_matched_still_agrees() -> None:
    diff = _run(**_clean_fixture())
    assert diff.divergences == ()
    assert diff.agreement is True


# --------------------------------------------------------------------------- #
# Task 1 - vocabulary, purity.
# --------------------------------------------------------------------------- #


def test_the_five_original_kind_constants_keep_their_string_values() -> None:
    assert compare_module.DIVERGENCE_KIND_ORPHAN_PROTECTIVE == "ORPHAN_PROTECTIVE"
    assert compare_module.DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE == "ENTRY_WITHOUT_PROTECTIVE"
    assert compare_module.DIVERGENCE_KIND_UNSYNCED_NORMAL == "UNSYNCED_NORMAL"
    assert compare_module.DIVERGENCE_KIND_UNSYNCED_ALGO == "UNSYNCED_ALGO"
    assert compare_module.DIVERGENCE_KIND_UNSYNCED_POSITION == "UNSYNCED_POSITION"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DIVERGENCE_KIND_FOREIGN_ORDER", "FOREIGN_ORDER"),
        ("DIVERGENCE_KIND_UNTRACKED_SYSTEM_ORDER", "UNTRACKED_SYSTEM_ORDER"),
        ("DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID", "DUPLICATE_EXCHANGE_ID"),
        ("DIVERGENCE_KIND_DOUBLED_POSITION", "DOUBLED_POSITION"),
        ("DIVERGENCE_KIND_SIGN_FLIPPED_POSITION", "SIGN_FLIPPED_POSITION"),
        ("DIVERGENCE_KIND_TP_ONLY_POSITION", "TP_ONLY_POSITION"),
        ("DIVERGENCE_KIND_POSITION_WITHOUT_STOP", "POSITION_WITHOUT_STOP"),
        ("DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER", "AMBIGUOUS_POSITION_OWNER"),
        ("DIVERGENCE_KIND_UNSUPPORTED_POSITION_SIDE", "UNSUPPORTED_POSITION_SIDE"),
        ("DIVERGENCE_KIND_STREAM_SINK_FAILURE", "STREAM_SINK_FAILURE"),
        ("DIVERGENCE_KIND_STREAM_TASK_DIED", "STREAM_TASK_DIED"),
    ],
)
def test_the_eleven_new_kinds_are_in_the_vocabulary(name: str, value: str) -> None:
    assert getattr(compare_module, name) == value
    div = compare_module.Divergence(
        kind=value,
        symbol=SYMBOL,
        order_role="UNKNOWN",
        client_order_id=None,
        client_algo_id=None,
        reason="vocabulary check",
    )
    assert div.kind == value


def test_compare_holds_no_id_prefix_literal_of_its_own() -> None:
    prefixes = tuple(order_ids.SYSTEM_ID_PREFIXES)
    assert len(prefixes) == 3
    tree = ast.parse(COMPARE_PATH.read_text(encoding="utf-8"))
    offenders = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(prefixes)
    ]
    assert offenders == []


def test_compare_imports_only_stdlib_domain_and_the_pure_id_predicates() -> None:
    from tests.support.ast_guards import forbidden_imports

    banned = [
        "polars",
        "pandas",
        "numpy",
        "pydantic",
        "sqlalchemy",
        "binance*",
        "src.adapters",
        "src.persistence",
        "src.paper",
        "src.risk",
        "src.core",
    ]
    assert forbidden_imports(COMPARE_PATH, banned) == []


# --------------------------------------------------------------------------- #
# Task 2 - positions: bound check, STOP requirement, ambiguity, Hedge rows, duplicates.
#
# D-01a: the signed amount is a BOUND check per symbol (sign = plan side, abs(exchange) <=
# intended quantity). It is not exact reconciliation; see the over-fill test below.
# --------------------------------------------------------------------------- #

INTENDED = Decimal("0.004")


def _owned_position(
    *,
    plan_hash: str | None = PLAN_A,
    expected_side: str | None = "LONG",
    max_abs_amount: Any = INTENDED,
    amount: Any = INTENDED,
    symbol: str = SYMBOL,
) -> LocalPositionIntent:
    return LocalPositionIntent(
        symbol=symbol,
        position_side="BOTH",
        position_amt=amount,
        plan_hash=plan_hash,
        expected_side=expected_side,
        max_abs_amount=max_abs_amount,
    )


def _scenario(
    *,
    exchange_amount: Any,
    local_positions: Sequence[Any] | None = None,
    truth_roles: Sequence[str] = ("STOP_LOSS",),
    stop_status: str = "NEW",
    position_side: str = "BOTH",
    extra_truth_algos: Sequence[Any] = (),
) -> CompareDiff:
    """One symbol with an exchange position, a local SL intent and the named exchange legs."""
    local_algos = [
        LocalAlgoIntent(
            client_algo_id=derive_algo_client_id(plan_hash=PLAN_A, role=role),
            symbol=SYMBOL,
            order_role=role,
            status="NEW",
        )
        for role in ("STOP_LOSS", *[r for r in truth_roles if r != "STOP_LOSS"])
    ]
    truth_algos = [
        _truth_algo(
            derive_algo_client_id(plan_hash=PLAN_A, role=role),
            algo_status=stop_status if role == "STOP_LOSS" else "NEW",
        )
        for role in truth_roles
    ]
    return _run(
        local_open_algos=local_algos,
        local_open_positions=(
            [_owned_position()] if local_positions is None else list(local_positions)
        ),
        truth_algo_orders=[*truth_algos, *extra_truth_algos],
        truth_positions=[_truth_position(SYMBOL, exchange_amount, position_side)],
    )


def test_a_protected_in_bound_long_position_agrees() -> None:
    diff = _scenario(exchange_amount=INTENDED)
    assert diff.divergences == ()
    assert diff.agreement is True


@pytest.mark.parametrize(
    ("side", "amount", "expected"),
    [
        ("LONG", Decimal("0.004"), []),
        ("LONG", Decimal("-0.004"), ["SIGN_FLIPPED_POSITION"]),
        ("SHORT", Decimal("-0.004"), []),
        ("SHORT", Decimal("0.004"), ["SIGN_FLIPPED_POSITION"]),
    ],
)
def test_sign_must_match_the_plan_side_long_and_short(
    side: str, amount: Decimal, expected: list[str]
) -> None:
    """D-01a: LONG needs a positive exchange amount, SHORT a negative one."""
    diff = _scenario(
        exchange_amount=amount,
        local_positions=[_owned_position(expected_side=side)],
    )
    assert _kinds(diff) == expected


def test_a_flipped_sign_that_also_exceeds_the_bound_is_sign_flipped_only() -> None:
    """One kind per position, documented order: the sign check comes before the bound."""
    diff = _scenario(exchange_amount=Decimal("-0.008"))
    assert _kinds(diff) == ["SIGN_FLIPPED_POSITION"]
    diff_short = _scenario(
        exchange_amount=Decimal("0.008"),
        local_positions=[_owned_position(expected_side="SHORT")],
    )
    assert _kinds(diff_short) == ["SIGN_FLIPPED_POSITION"]


@pytest.mark.parametrize(
    ("side", "amount", "expected"),
    [
        ("LONG", Decimal("0.004"), []),
        ("LONG", Decimal("0.005"), ["DOUBLED_POSITION"]),
        ("LONG", Decimal("0.008"), ["DOUBLED_POSITION"]),
        ("SHORT", Decimal("-0.004"), []),
        ("SHORT", Decimal("-0.005"), ["DOUBLED_POSITION"]),
        ("SHORT", Decimal("-0.008"), ["DOUBLED_POSITION"]),
    ],
)
def test_bound_is_abs_exchange_at_most_intended_quantity(
    side: str, amount: Decimal, expected: list[str]
) -> None:
    """D-01a: equality agrees, strictly greater is DOUBLED_POSITION (Decimal comparison)."""
    diff = _scenario(
        exchange_amount=amount,
        local_positions=[_owned_position(expected_side=side)],
    )
    assert _kinds(diff) == expected


def test_bound_check_cannot_see_an_overfill_below_the_intended_quantity() -> None:
    """D-01a limit [DESIGN]: +0.003 against an intended 0.004 is NOT detected.

    The bound check only knows the intended quantity, not what was filled. An over-fill that
    stays below the bound is invisible in Phase 20. Exact reconciliation against the fills
    ledger attributed by client order id is a Phase 24 dependency (D-13 deferred).
    """
    diff = _scenario(exchange_amount=Decimal("0.003"))
    assert diff.agreement is True
    assert diff.divergences == ()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"plan_hash": None}, id="no-plan-hash"),
        pytest.param({"plan_hash": ""}, id="empty-plan-hash"),
        pytest.param({"expected_side": None}, id="no-expected-side"),
        pytest.param({"expected_side": "BOTH"}, id="unknown-expected-side"),
        pytest.param({"max_abs_amount": None}, id="max-none"),
        pytest.param({"max_abs_amount": Decimal("0")}, id="max-zero"),
        pytest.param({"max_abs_amount": Decimal("-0.004")}, id="max-negative"),
        pytest.param({"max_abs_amount": "0.004"}, id="max-str"),
        pytest.param({"max_abs_amount": 0.004}, id="max-float"),
        pytest.param({"max_abs_amount": 4}, id="max-int"),
        pytest.param({"max_abs_amount": Decimal("NaN")}, id="max-nan"),
    ],
)
def test_missing_local_bound_data_fails_closed(overrides: dict[str, Any]) -> None:
    """T-20-68: exposure that cannot be tied to a plan with a checkable side and bound is never
    an agreement."""
    diff = _scenario(exchange_amount=INTENDED, local_positions=[_owned_position(**overrides)])
    assert diff.agreement is False
    assert _kinds(diff) == ["AMBIGUOUS_POSITION_OWNER"]


@pytest.mark.parametrize(
    "source",
    [
        "local_open_orders",
        "local_open_algos",
        "local_open_positions",
        "truth_normal_orders",
        "truth_algo_orders",
        "truth_positions",
    ],
)
def test_none_source_is_refused_not_read_as_empty(source: str) -> None:
    """A missing source must never read as 'nothing there' (F-711 family)."""
    sources: dict[str, Any] = {
        "local_open_orders": [],
        "local_open_algos": [],
        "local_open_positions": [],
        "truth_normal_orders": [],
        "truth_algo_orders": [],
        "truth_positions": [],
    }
    sources[source] = None
    with pytest.raises(TypeError, match=source):
        compare(**sources)


def test_two_local_plans_on_one_symbol_is_ambiguous_and_never_picks_one() -> None:
    diff = _scenario(
        exchange_amount=Decimal("0.008"),
        local_positions=[_owned_position(plan_hash=PLAN_A), _owned_position(plan_hash=PLAN_B)],
    )
    assert _kinds(diff) == ["AMBIGUOUS_POSITION_OWNER"]


def test_one_plan_hash_repeated_consistently_is_one_owner() -> None:
    diff = _scenario(
        exchange_amount=INTENDED,
        local_positions=[_owned_position(), _owned_position()],
    )
    assert diff.divergences == ()


def test_one_plan_hash_repeated_with_different_bounds_is_ambiguous() -> None:
    diff = _scenario(
        exchange_amount=INTENDED,
        local_positions=[_owned_position(), _owned_position(max_abs_amount=Decimal("0.010"))],
    )
    assert _kinds(diff) == ["AMBIGUOUS_POSITION_OWNER"]


def test_a_position_with_no_local_intent_is_still_unsynced_position() -> None:
    diff = _run(truth_positions=[_truth_position(SYMBOL, INTENDED)])
    assert "UNSYNCED_POSITION" in _kinds(diff)
    assert "AMBIGUOUS_POSITION_OWNER" not in _kinds(diff)


def test_a_flat_exchange_position_row_is_not_exposure() -> None:
    diff = _run(truth_positions=[_truth_position(SYMBOL, Decimal("0"))])
    assert diff.divergences == ()


@pytest.mark.parametrize("hedge_side", ["LONG", "SHORT"])
def test_hedge_rows_are_unsupported_position_side(hedge_side: str) -> None:
    diff = _run(truth_positions=[_truth_position(SYMBOL, INTENDED, hedge_side)])
    assert _kinds(diff) == ["UNSUPPORTED_POSITION_SIDE"]
    assert diff.agreement is False


def test_no_algo_order_at_all_is_position_without_stop() -> None:
    diff = _scenario(exchange_amount=INTENDED, truth_roles=())
    kinds = _kinds(diff)
    assert "POSITION_WITHOUT_STOP" in kinds
    assert "TP_ONLY_POSITION" not in kinds


def test_only_take_profit_legs_is_tp_only_position_and_not_also_without_stop() -> None:
    diff = _scenario(exchange_amount=INTENDED, truth_roles=("TAKE_PROFIT_1", "TAKE_PROFIT_2"))
    kinds = _kinds(diff)
    assert "TP_ONLY_POSITION" in kinds
    assert "POSITION_WITHOUT_STOP" not in kinds


@pytest.mark.parametrize("status", ["TRIGGERING", "TRIGGERED", "FINISHED", "CANCELED", "", "new"])
def test_a_stop_that_is_not_active_class_is_position_without_stop(status: str) -> None:
    diff = _scenario(exchange_amount=INTENDED, stop_status=status)
    kinds = _kinds(diff)
    assert "POSITION_WITHOUT_STOP" in kinds
    assert "TP_ONLY_POSITION" not in kinds


def test_a_foreign_active_stop_does_not_satisfy_the_stop_requirement() -> None:
    diff = _scenario(
        exchange_amount=INTENDED,
        truth_roles=(),
        extra_truth_algos=[_truth_algo("ui_stop_9")],
    )
    kinds = _kinds(diff)
    assert "POSITION_WITHOUT_STOP" in kinds
    assert "FOREIGN_ORDER" in kinds


@pytest.mark.parametrize("kind", ["normal", "algo"])
def test_a_duplicate_exchange_client_id_is_a_divergence(kind: str) -> None:
    if kind == "normal":
        cid = derive_client_order_id(plan_hash=PLAN_A, role="ENTRY")
        local = [
            LocalOrderIntent(client_order_id=cid, symbol=SYMBOL, order_role="ENTRY", status="NEW")
        ]
        diff = _run(
            local_open_orders=local,
            local_open_algos=[
                LocalAlgoIntent(
                    client_algo_id=derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS"),
                    symbol=SYMBOL,
                    order_role="STOP_LOSS",
                    status="NEW",
                )
            ],
            truth_algo_orders=[
                _truth_algo(derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS"))
            ],
            truth_normal_orders=[_truth_order(cid), _truth_order(cid)],
        )
    else:
        aid = derive_algo_client_id(plan_hash=PLAN_A, role="STOP_LOSS")
        diff = _run(
            local_open_algos=[
                LocalAlgoIntent(
                    client_algo_id=aid, symbol=SYMBOL, order_role="STOP_LOSS", status="NEW"
                )
            ],
            local_open_positions=[_owned_position()],
            truth_algo_orders=[_truth_algo(aid), _truth_algo(aid)],
            truth_positions=[_truth_position(SYMBOL, INTENDED)],
        )
    duplicates = [d for d in diff.divergences if d.kind == "DUPLICATE_EXCHANGE_ID"]
    assert len(duplicates) == 1
    assert diff.agreement is False
    if kind == "normal":
        assert duplicates[0].client_order_id is not None
    else:
        assert duplicates[0].client_algo_id is not None


@pytest.mark.parametrize("amount", ["0.004", 0.004, 1, None])
def test_a_non_decimal_exchange_position_amount_raises_type_error(amount: object) -> None:
    """Never converted through float or str: a non-Decimal amount is refused."""
    with pytest.raises(TypeError, match="position_amt"):
        _run(truth_positions=[_truth_position(SYMBOL, amount)])


def test_compare_v2_has_no_float_constructor_and_no_wall_clock() -> None:
    from tests.support.ast_guards import float_constructor_calls, wall_clock_calls

    for path in (COMPARE_PATH, ORDER_IDS_PATH):
        assert float_constructor_calls(path) == [], path
        assert wall_clock_calls(path) == [], path
