"""Rejected placements -1106, -4016, -4024: classification and what the table does not change.

Plan 18-26, owner decision of 2026-10-17 (decisions/18-DEC-TAXONOMY-CODES.md). A rejection by
one of these codes is REJECTED_DEFINITIVE on a placement and UNKNOWN_EXCHANGE_ERROR on every
other call kind. The taxonomy gives no placement a retry and never makes a rejected protective
order a protected one: the execution manager decides SAFE_MODE on ANY adapter exception of a
protective leg and does not read the taxonomy, and these tests assert that branch on the real
code path, not `safe_mode_eligible`.

The errors are SDK-shaped (`BadRequestError(error_message=..., status_code=<code>)`). The
Demo texts below are the ones recorded in evidence/18-probe-check.txt (2026-10-16); the page
texts are those of evidence/18-error-code-page-reread-20261017.txt. Synthetic, not live.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from src.adapters.binance_errors import error_facts_from_exception
from src.domain.enums import ExecutionIntentStatus
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    classify,
    retry_eligible,
    safe_mode_eligible,
)

from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.test_execution_manager import (
    FakeExecutionAdapter,
    FakeJournal,
    RecordingSafeModeController,
    _load_input,
    _run_plan,
)

_C = ExchangeErrorCategory
_K = CallKind

DEMO_1106 = "Parameter 'reduceonly' sent when not required."
PAGE_1106 = "A parameter was sent when not required."


def _sdk_error(code: int, text: str) -> BadRequestError:
    return BadRequestError(error_message=text, status_code=code)


# --------------------------------------------------------------------------- #
# Tracer: -1106 from the SDK error to the table.
# --------------------------------------------------------------------------- #


def test_tracer_1106_classifies_rejected_definitive_on_placement_only() -> None:
    facts = error_facts_from_exception(_sdk_error(-1106, DEMO_1106))
    assert facts == ErrorFacts(HttpClass.BAD_REQUEST, -1106, None)
    assert classify(facts, _K.PLACEMENT) is _C.REJECTED_DEFINITIVE
    for kind in (_K.QUERY, _K.CANCEL, _K.LISTEN_KEY, _K.TIME):
        assert classify(facts, kind) is _C.UNKNOWN_EXCHANGE_ERROR, kind
    # The message text is never read: the page wording and an empty text classify the same.
    for text in (PAGE_1106, "", "something else entirely"):
        same = error_facts_from_exception(_sdk_error(-1106, text))
        assert same == facts
        for kind in CallKind:
            assert classify(same, kind) is classify(facts, kind)
    for kind in CallKind:
        category = classify(facts, kind)
        assert retry_eligible(category, kind) is False, kind
        # The code alone does not prove a wrong position mode (owner point 1).
        assert category is not _C.POSITION_MODE, kind
    assert safe_mode_eligible(classify(facts, _K.PLACEMENT)) is False


# --------------------------------------------------------------------------- #
# Tracer: -1106 on the protective stop still ends in ENTRY_WITHOUT_PROTECTIVE.
# --------------------------------------------------------------------------- #


class _ProtectiveRaises(FakeExecutionAdapter):
    """A fake adapter whose protective placement raises the given SDK-shaped error."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        await super().place_algo_protective(**kwargs)
        raise self.error


class _NoOpTruth:
    async def snapshot_open_normal_orders(self, *, symbol: Any = None) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, *, symbol: Any = None) -> list[Any]:
        return []

    async def snapshot_positions(self, *, symbol: Any = None) -> list[Any]:
        return []


@pytest.mark.parametrize("controller_kind", ["recording_double", "real_controller"])
async def test_tracer_1106_on_the_protective_stop_is_entry_without_protective(
    controller_kind: str,
) -> None:
    """The SAFE_MODE decision belongs to the manager (any adapter exception of a protective
    leg is an unconfirmed leg), not to `safe_mode_eligible`, which is False for -1106."""
    from src.reconcile.safe_mode import SafeModeController

    recording = RecordingSafeModeController()
    real = SafeModeController(adapter=_NoOpTruth(), journal=FakeJournal())
    controller: Any = recording if controller_kind == "recording_double" else real
    adapter = _ProtectiveRaises(_sdk_error(-1106, DEMO_1106))
    journal = FakeJournal()
    store = InMemoryExecutionIntentStore()

    outcome = await _run_plan(
        adapter, safe_mode_controller=controller, journal=journal, intent_store=store
    )

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    if controller_kind == "recording_double":
        assert recording.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]
    else:
        assert real.in_safe_mode is True
        follow_up = FakeExecutionAdapter()
        blocked = await _run_plan(follow_up, safe_mode_controller=real)
        assert (blocked.is_no_trade, blocked.reason_code) == (True, "RECONCILIATION_REQUIRED")
        assert follow_up.calls == []
    methods = [call["method"] for call in adapter.calls]
    protective = [call for call in adapter.calls if call["method"] == "place_algo_protective"]
    assert len(protective) == 1
    assert protective[0]["kwargs"]["close_position"] is True  # the stop; no take profit exists
    assert methods[-1] == "cancel_normal_order"
    assert (
        adapter.calls[-1]["kwargs"]["orig_client_order_id"]
        == "x-33333333333333333333333333333333EN"
    )
    assert [json_phase(event) for event in journal.events] == ["pre_cancel", "post_cancel"]
    case_input = _load_input()
    stop_loss = store.get_intent(approval_id=case_input["approval_id"], role="STOP_LOSS")
    assert stop_loss is not None
    assert stop_loss.intent_status == ExecutionIntentStatus.UNKNOWN
    assert stop_loss.intent_status != ExecutionIntentStatus.ACKED
    entry = store.get_entry(approval_id=case_input["approval_id"])
    assert entry is not None and entry.outcome is not None
    assert entry.outcome.reason_code == "ENTRY_WITHOUT_PROTECTIVE"


def json_phase(event: Any) -> str:
    return str(json.loads(event.payload_json)["phase"])
