"""The Telegram operator commands of the live process (plan 24-23; R-4, OQ-5, 24-01 Q7; D-28).

Everything is real except the edges (the Binance-semantics fake exchange, the REST gate, the stream
state, the reply function). Commands are driven as PTB would drive them: an update with
`effective_chat` / `effective_user` and a context with `args`. Pinned here:

  * the gate: an unknown user, another chat, a group chat and an update without a user change
    nothing, are journaled as rejections with the presser's id, and are answered "Rejected";
  * `/status` reads and writes nothing but its audit row;
  * `/disable_entries` acts at once (no confirm), journals the user id and is idempotent;
  * `/close SYMBOL` is two steps; a replayed, expired, unknown or other-user confirm does nothing;
  * no command places an entry or touches leverage or margin type.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.execution.protection import ProtectionState
from src.live.operator import (
    COMMAND_CLOSE,
    COMMAND_CONFIRM,
    COMMAND_DISABLE_ENTRIES,
    COMMAND_SAFEMODE_EXIT,
    COMMAND_STATUS,
    EVENT_COMMAND,
    EVENT_COMMAND_REJECTED,
    OperatorCommands,
)

from tests.shadow_fakes import AUTHORIZED_USER_IDS, CHAT_ID, OTHER_USER_ID, USER_ID
from tests.support.live_rig import LiveRig, forbid_real_sleep, make_live_rig
from tests.support.reconcile_doubles import make_plan_protection
from tests.test_live_safe_mode_drill import (
    FakeRestGate,
    Replies,
    StreamHolder,
    make_ops,
    with_args,
)

OPERATOR_SOURCE = Path(__file__).resolve().parents[1] / "src" / "live" / "operator.py"
STRANGER_ID = 999_001


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def update_of(
    update_id: int,
    *,
    user_id: int | None = USER_ID,
    chat_id: int | None = CHAT_ID,
    chat_type: str | None = "private",
) -> Any:
    return SimpleNamespace(
        update_id=update_id,
        effective_chat=None if chat_id is None else SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=None if user_id is None else SimpleNamespace(id=user_id),
    )


class Harness:
    """A live rig, the operator commands over it, and a running update counter."""

    def __init__(self, rig: LiveRig) -> None:
        self.rig = rig
        self.ops, self.gate, self.stream, self.replies = make_ops(rig)
        self._n = 0

    def update(self, **kwargs: Any) -> Any:
        self._n += 1
        return update_of(self._n, **kwargs)

    def rows(self, event_type: str) -> list[dict[str, Any]]:
        return [json.loads(e.payload_json) for e in self.rig.journal.by_type(event_type)]

    async def protect_the_position(self) -> None:
        """APPROVE, CONFIRM, a fill and the coordinator steps: a PROTECTED BTCUSDT plan."""
        rig = self.rig
        await rig.approve_and_confirm()
        await rig.wiring.service.drain()
        rig.fake.fill(rig.entry_id, quantity=Decimal("0.004"))
        rig.route(rig.trade_frame())
        await rig.wiring.coordinator.step()
        await rig.clock.advance(1)
        await rig.wiring.coordinator.step()
        view = rig.wiring.coordinator.protection_of(rig.plan.plan_hash)
        assert view is not None and view.state is ProtectionState.PROTECTED

    async def ask_close(self, symbol: str = "BTCUSDT", **kwargs: Any) -> Any:
        return await self.ops.close(self.update(**kwargs), with_args(symbol))


async def harness() -> Harness:
    return Harness(await make_live_rig())


def token_in(replies: Replies) -> str:
    return replies.last_token()


# --------------------------------------------------------------------------- #
# The gate.
# --------------------------------------------------------------------------- #

REJECTIONS = {
    "unknown_user": {"user_id": STRANGER_ID},
    "other_chat": {"chat_id": CHAT_ID + 1},
    "group_chat": {"chat_type": "group"},
    "no_user": {"user_id": None},
}
COMMANDS = [
    (COMMAND_STATUS, ()),
    (COMMAND_DISABLE_ENTRIES, ()),
    (COMMAND_SAFEMODE_EXIT, ()),
    (COMMAND_CLOSE, ("BTCUSDT",)),
    (COMMAND_CONFIRM, ("some-token",)),
]


@pytest.mark.parametrize("case", sorted(REJECTIONS))
@pytest.mark.parametrize(("command", "args"), COMMANDS)
async def test_a_refused_command_changes_nothing_and_is_journaled_as_a_rejection(
    case: str, command: str, args: tuple[str, ...]
) -> None:
    h = await harness()
    h.rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=h.rig.clock.now())
    before = h.rig.safe_mode.state_snapshot()
    handler = h.ops.handlers()[command]

    result = await handler(h.update(**REJECTIONS[case]), with_args(*args))

    assert not result.ok and result.code == "REJECTED"
    assert not h.rig.enablement.is_disabled, "a stranger cannot disable entries"
    assert h.rig.safe_mode.state_snapshot() == before
    assert h.rig.journal.by_type("LIVE_ORDERS_DISABLED") == []
    assert h.rig.journal.by_type("SAFE_MODE_EXIT") == []
    assert h.rows(EVENT_COMMAND) == [], "no accepted-command row"
    (row,) = h.rows(EVENT_COMMAND_REJECTED)
    assert row["command"] == command
    expected_user = REJECTIONS[case].get("user_id", USER_ID)
    assert row["user_id"] == expected_user
    assert row["reason_code"] in {
        "USER_NOT_AUTHORIZED",
        "CHAT_NOT_AUTHORIZED",
        "CHAT_NOT_PRIVATE",
        "USER_ID_UNAVAILABLE",
    }
    assert [text for _chat, text in h.replies.sent] == ["Rejected"]
    assert not h.ops._pending, "a refused command issues no token"


async def test_a_refusal_names_its_reason_per_gate() -> None:
    h = await harness()
    await h.ops.status(h.update(user_id=STRANGER_ID), with_args())
    await h.ops.status(h.update(chat_id=CHAT_ID + 1), with_args())
    await h.ops.status(h.update(chat_type="supergroup"), with_args())
    await h.ops.status(h.update(user_id=None), with_args())
    reasons = [r["reason_code"] for r in h.rows(EVENT_COMMAND_REJECTED)]
    assert reasons == [
        "USER_NOT_AUTHORIZED",
        "CHAT_NOT_AUTHORIZED",
        "CHAT_NOT_PRIVATE",
        "USER_ID_UNAVAILABLE",
    ]


async def test_the_constructor_refuses_an_empty_or_mistyped_allow_list() -> None:
    rig = await make_live_rig()
    for bad in (frozenset(), {USER_ID}, frozenset({"7"}), frozenset({True})):
        with pytest.raises(ValueError):
            OperatorCommands(
                authorized_chat_id=CHAT_ID,
                authorized_user_ids=bad,  # type: ignore[arg-type]
                controller=rig.safe_mode,
                enablement=rig.enablement,
                coordinator=rig.wiring.coordinator,
                intent_store=rig.intents,
                pending_actions=None,
                gate=FakeRestGate(),
                stream_state=StreamHolder(),
                journal=rig.journal,
                clock=rig.clock.now,
                reply=Replies(),
            )


async def test_the_handlers_are_the_five_registered_commands() -> None:
    h = await harness()
    assert sorted(h.ops.handlers()) == sorted(
        [
            COMMAND_STATUS,
            COMMAND_DISABLE_ENTRIES,
            COMMAND_SAFEMODE_EXIT,
            COMMAND_CLOSE,
            COMMAND_CONFIRM,
        ]
    )


# --------------------------------------------------------------------------- #
# /status.
# --------------------------------------------------------------------------- #


async def test_status_reports_the_system_state_and_changes_nothing() -> None:
    h = await harness()
    before_snapshot = h.rig.safe_mode.state_snapshot()
    before_enablement = h.rig.enablement.state_snapshot()
    rows_before = len(h.rig.journal.calls)

    result = await h.ops.status(h.update(), with_args())

    assert result.ok
    text = h.replies.last
    assert "mode: NORMAL" in text
    assert "entries: ENABLED" in text
    assert "rest gate: OPEN, recovery RESTORED_DURABLE" in text
    assert "stream: LIVE" in text
    assert "protections: 0 open of 0 tracked" in text
    assert h.rig.safe_mode.state_snapshot() == before_snapshot
    assert h.rig.enablement.state_snapshot() == before_enablement
    assert [e.event_type for e in h.rig.journal.calls[rows_before:]] == [EVENT_COMMAND]
    (row,) = h.rows(EVENT_COMMAND)
    assert row == {"command": "status", "code": "STATUS", "user_id": USER_ID, "chat_id": CHAT_ID}


async def test_status_shows_safe_mode_with_its_reason_and_the_gate_and_stream() -> None:
    h = await harness()
    h.rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=h.rig.clock.now())
    h.gate.restriction_value = SimpleNamespace(reason="IP_BAN_418")
    h.stream.value = "SYNCING"

    await h.ops.status(h.update(), with_args())

    assert "mode: SAFE_MODE (reason DIVERGENCE)" in h.replies.last
    assert "rest gate: IP_BAN_418" in h.replies.last
    assert "stream: SYNCING" in h.replies.last


async def test_status_survives_an_unreadable_gate_and_stream() -> None:
    h = await harness()

    def broken() -> str:
        raise RuntimeError("secret connection text")

    h.gate.restriction = broken  # type: ignore[method-assign]
    h.ops._stream_state = broken

    result = await h.ops.status(h.update(), with_args())

    assert result.ok
    assert "rest gate: unreadable (RuntimeError)" in h.replies.last
    assert "stream: unreadable (RuntimeError)" in h.replies.last
    assert "secret" not in h.replies.last


# --------------------------------------------------------------------------- #
# /disable_entries.
# --------------------------------------------------------------------------- #


async def test_disable_entries_acts_at_once_journals_the_user_id_and_is_idempotent() -> None:
    h = await harness()
    assert not h.rig.enablement.is_disabled

    first = await h.ops.disable_entries(h.update(), with_args())

    assert first.ok and first.code == "ENTRIES_DISABLED"
    assert h.rig.enablement.is_disabled
    (disable_row,) = h.rows("LIVE_ORDERS_DISABLED")
    assert disable_row["operator_id"] == f"tg:{USER_ID}"
    assert "disabled" in h.replies.last
    assert not h.ops._pending, "no confirm step for a risk-reducing command"

    second = await h.ops.disable_entries(h.update(user_id=OTHER_USER_ID), with_args())

    assert second.ok and second.code == "ALREADY_DISABLED"
    assert len(h.rows("LIVE_ORDERS_DISABLED")) == 1
    audit = [r["code"] for r in h.rows(EVENT_COMMAND)]
    assert audit == ["ENTRIES_DISABLED", "ALREADY_DISABLED"]


async def test_disable_entries_blocks_the_next_confirm() -> None:
    h = await harness()
    await h.ops.disable_entries(h.update(), with_args())
    handle = await h.rig.issue_and_send()
    assert (await h.rig.press("APR", handle.short_id, query_id="q-a")).ok
    await h.rig.clock.advance(30)
    h.rig.set_prices()
    assert (await h.rig.press("CNF", handle.short_id, query_id="q-c")).ok
    await h.rig.wiring.service.drain()
    assert h.rig.fake.calls_to("place_entry") == []


async def test_a_failing_journal_does_not_undo_or_break_disable_entries() -> None:
    h = await harness()
    h.rig.journal.fail = True

    result = await h.ops.disable_entries(h.update(), with_args())

    assert h.rig.enablement.is_disabled, "the flag flips first (D-16)"
    assert result.ok


# --------------------------------------------------------------------------- #
# /close SYMBOL, two steps.
# --------------------------------------------------------------------------- #


async def test_close_asks_for_a_confirm_and_closes_once_after_it() -> None:
    h = await harness()
    await h.protect_the_position()
    coordinator = h.rig.wiring.coordinator

    asked = await h.ask_close()

    assert asked.ok and asked.code == "CONFIRM_REQUIRED"
    assert "/confirm " in h.replies.last and "PROTECTED" in h.replies.last
    view = coordinator.protection_of(h.rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.PROTECTED, "nothing closed yet"
    token = token_in(h.replies)

    done = await h.ops.confirm(h.update(), with_args(token))

    assert done.ok and done.code == "CLOSE_REQUESTED"
    view = coordinator.protection_of(h.rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.CLOSE_REQUIRED
    (operator_row,) = [
        e
        for e in h.rig.journal.calls
        if e.event_type == "OPERATOR_CLOSE_REQUESTED"  # the coordinator's own audit row
    ]
    assert json.loads(operator_row.payload_json)["operator_id"] == f"tg:{USER_ID}"
    assert len(h.rig.fake.calls_to("place_entry")) == 1, "the close places no entry"
    assert token not in json.dumps([e.payload_json for e in h.rig.journal.calls])


async def test_a_replayed_confirm_does_nothing() -> None:
    h = await harness()
    await h.protect_the_position()
    await h.ask_close()
    token = token_in(h.replies)

    first = await h.ops.confirm(h.update(), with_args(token))
    second = await h.ops.confirm(h.update(), with_args(token))

    assert first.ok
    assert not second.ok and second.code == "TOKEN_UNKNOWN"
    assert len([e for e in h.rig.journal.calls if e.event_type == "OPERATOR_CLOSE_REQUESTED"]) == 1
    assert "Not confirmed" in h.replies.last


async def test_an_expired_confirm_does_nothing() -> None:
    h = await harness()
    await h.protect_the_position()
    await h.ask_close()
    token = token_in(h.replies)
    await h.rig.clock.advance(61)

    result = await h.ops.confirm(h.update(), with_args(token))

    assert not result.ok and result.code == "TOKEN_EXPIRED"
    view = h.rig.wiring.coordinator.protection_of(h.rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.PROTECTED
    again = await h.ops.confirm(h.update(), with_args(token))
    assert again.code == "TOKEN_UNKNOWN", "an expired token is gone"


async def test_a_confirm_at_the_last_second_still_works() -> None:
    h = await harness()
    await h.protect_the_position()
    await h.ask_close()
    token = token_in(h.replies)
    await h.rig.clock.advance(59)

    result = await h.ops.confirm(h.update(), with_args(token))

    assert result.ok


async def test_another_authorized_users_confirm_does_nothing_and_keeps_the_token() -> None:
    h = await harness()
    await h.protect_the_position()
    await h.ask_close()
    token = token_in(h.replies)
    assert OTHER_USER_ID in AUTHORIZED_USER_IDS

    other = await h.ops.confirm(h.update(user_id=OTHER_USER_ID), with_args(token))

    assert not other.ok and other.code == "TOKEN_OTHER_USER"
    view = h.rig.wiring.coordinator.protection_of(h.rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.PROTECTED
    mine = await h.ops.confirm(h.update(), with_args(token))
    assert mine.ok, "the asking user can still confirm"


async def test_a_wrong_token_or_no_token_does_nothing() -> None:
    h = await harness()
    await h.protect_the_position()
    await h.ask_close()

    for args in ((), ("nope",), ("a", "b")):
        result = await h.ops.confirm(h.update(), with_args(*args))
        assert not result.ok and result.code == "TOKEN_UNKNOWN"
    view = h.rig.wiring.coordinator.protection_of(h.rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.PROTECTED


async def test_close_refuses_an_unknown_symbol_and_bad_usage_without_a_token() -> None:
    h = await harness()
    await h.protect_the_position()

    unknown = await h.ask_close("ETHUSDT")
    assert not unknown.ok and unknown.code == "UNKNOWN_SYMBOL"
    assert not h.ops._pending
    for bad in ("btcusdt", "BTC USDT", "BTCUSDT;DROP", ""):
        result = await h.ask_close(bad)
        assert not result.ok and result.code == "BAD_USAGE"
    no_args = await h.ops.close(h.update(), with_args())
    assert no_args.code == "BAD_USAGE"
    two_args = await h.ops.close(h.update(), with_args("BTCUSDT", "ETHUSDT"))
    assert two_args.code == "BAD_USAGE"
    assert not h.ops._pending


async def test_close_is_offered_for_an_entry_that_may_still_fill() -> None:
    h = await harness()
    await h.rig.approve_and_confirm()
    await h.rig.wiring.service.drain()

    asked = await h.ask_close()

    assert asked.ok, "an entry that may still fill is closable (the coordinator cancels it)"
    view = h.rig.wiring.coordinator.protection_of(h.rig.plan.plan_hash)
    assert view is not None and view.state is ProtectionState.AWAITING_FILL


class StubCoordinator:
    """`protections()` only: the close prompt reads nothing else."""

    def __init__(self, *plans: Any) -> None:
        self.plans = plans

    def protections(self) -> tuple[Any, ...]:
        return self.plans


async def test_close_refuses_a_finished_plan_and_an_ambiguous_symbol() -> None:
    rig = await make_live_rig()
    h = Harness(rig)
    h.ops._coordinator = StubCoordinator(make_plan_protection("a" * 64, state="FLAT"))
    finished = await h.ask_close()
    assert not finished.ok and finished.code == "NOTHING_TO_CLOSE"

    h.ops._coordinator = StubCoordinator(
        make_plan_protection("a" * 64, state="PROTECTED"),
        make_plan_protection("b" * 64, state="UNPROTECTED"),
    )
    ambiguous = await h.ask_close()
    assert not ambiguous.ok and ambiguous.code == "AMBIGUOUS_SYMBOL"
    assert not h.ops._pending

    h.ops._coordinator = StubCoordinator(
        make_plan_protection("a" * 64, state="FLAT"),
        make_plan_protection("b" * 64, state="PROTECTED"),
    )
    one_open = await h.ask_close()
    assert one_open.ok, "finished plans of the symbol are ignored"


async def test_close_in_safe_mode_is_allowed_because_it_reduces_risk() -> None:
    h = await harness()
    await h.protect_the_position()
    h.rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=h.rig.clock.now())

    await h.ask_close()
    result = await h.ops.confirm(h.update(), with_args(token_in(h.replies)))

    assert result.ok and result.code == "CLOSE_REQUESTED"


async def test_a_second_ask_replaces_the_first_token() -> None:
    h = await harness()
    await h.protect_the_position()
    await h.ask_close()
    first = token_in(h.replies)
    await h.ask_close()
    second = token_in(h.replies)

    stale = await h.ops.confirm(h.update(), with_args(first))
    fresh = await h.ops.confirm(h.update(), with_args(second))

    assert first != second
    assert stale.code == "TOKEN_UNKNOWN"
    assert fresh.ok


async def test_only_the_hash_of_a_token_is_kept_in_memory() -> None:
    h = await harness()
    await h.protect_the_position()
    await h.ask_close()
    token = token_in(h.replies)

    assert token not in h.ops._pending
    assert all(re.fullmatch(r"[0-9a-f]{64}", key) for key in h.ops._pending)


async def test_pending_confirmations_are_bounded() -> None:
    h = await harness()
    h.rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=h.rig.clock.now())
    # Different users ask, so the asks are not the same ask.
    for _ in range(12):
        await h.ops.safemode_exit(h.update(user_id=OTHER_USER_ID), with_args())
        await h.ops.safemode_exit(h.update(), with_args())
        await h.rig.clock.advance(1)
    assert len(h.ops._pending) <= 8


# --------------------------------------------------------------------------- #
# /safemode_exit entry cases (the drill is in tests/test_live_safe_mode_drill.py).
# --------------------------------------------------------------------------- #


async def test_safemode_exit_outside_safe_mode_issues_no_token() -> None:
    h = await harness()

    result = await h.ops.safemode_exit(h.update(), with_args())

    assert not result.ok and result.code == "NOT_IN_SAFE_MODE"
    assert not h.ops._pending
    assert "Not in SAFE_MODE" in h.replies.last


async def test_a_used_safemode_token_cannot_be_used_after_another_ask() -> None:
    h = await harness()
    h.rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=h.rig.clock.now())
    await h.ops.safemode_exit(h.update(), with_args())
    first = token_in(h.replies)
    await h.ops.safemode_exit(h.update(), with_args())
    second = token_in(h.replies)

    assert (await h.ops.confirm(h.update(), with_args(second))).ok
    again = await h.ops.confirm(h.update(), with_args(first))

    assert again.code == "TOKEN_UNKNOWN"
    assert len(h.rig.journal.by_type("SAFE_MODE_EXIT")) == 1


async def test_an_exit_confirmed_after_safe_mode_ended_elsewhere_does_nothing() -> None:
    h = await harness()
    h.rig.safe_mode.enter_safe_mode(reason="DIVERGENCE", now_utc=h.rig.clock.now())
    await h.ops.safemode_exit(h.update(), with_args())
    token = token_in(h.replies)
    assert (await h.ops.safemode_exit(h.update(user_id=OTHER_USER_ID), with_args())).ok
    other = token_in(h.replies)
    assert (await h.ops.confirm(h.update(user_id=OTHER_USER_ID), with_args(other))).ok

    result = await h.ops.confirm(h.update(), with_args(token))

    assert result.code in {"NOT_IN_SAFE_MODE", "TOKEN_UNKNOWN"}
    assert len(h.rig.journal.by_type("SAFE_MODE_EXIT")) == 1


# --------------------------------------------------------------------------- #
# What the commands never do.
# --------------------------------------------------------------------------- #


def test_the_module_names_no_placement_call_and_no_leverage_or_margin_command() -> None:
    source = OPERATOR_SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "place_entry",
        "execute_approved_plan",
        "place_algo_protective",
        "place_market_close",
        "set_leverage",
        "change_leverage",
        "margin_type",
        "change_margin",
    ):
        assert forbidden not in source, forbidden


async def test_no_command_places_anything_on_the_exchange() -> None:
    h = await harness()
    await h.protect_the_position()
    placed_before = len(h.rig.fake.calls_to("place_entry"))
    for handler_name, args in (
        (COMMAND_STATUS, ()),
        (COMMAND_DISABLE_ENTRIES, ()),
        (COMMAND_SAFEMODE_EXIT, ()),
        (COMMAND_CLOSE, ("BTCUSDT",)),
    ):
        await h.ops.handlers()[handler_name](h.update(), with_args(*args))
    assert len(h.rig.fake.calls_to("place_entry")) == placed_before
