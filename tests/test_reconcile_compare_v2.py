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
            LocalPositionIntent(symbol=SYMBOL, position_side="BOTH", position_amt=Decimal("0.004"))
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
