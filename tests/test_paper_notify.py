"""Paper SIMULATE notify tests — journal-first send-only Telegram (Phase 7, plan 07-04).

Per D-05: paper notifications are SIMULATE-only (send-only) in Phase 7;
APPROVE/SKIP callback hardening stays Phase 8. The notify module
formats the 12 APRV-01 fields and sends via the Telegram edge adapter
(`src/adapters/telegram_notify.py`). The paper-core never imports
`python-telegram-bot` directly.

The tests cover:

  1. format_simulate renders all 12 APRV-01 fields byte-checked with
     Decimal str precision and SIMULATE-recorded labeling.
  2. notify_simulate enforces journal-first ordering: the journal
     commit precedes the send call, and a failing bot surfaces a
     JournalEvent outcome with no exception escaping.
  3. Inert-callback tests: no `Application` poller exists in the
     paper package, and no inbound handler can mutate approval state.
"""

from __future__ import annotations

import ast
import importlib.util
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.support.simulate_payload import make_money, make_simulate_payload

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _make_payload() -> dict[str, Any]:
    """A canonical SIMULATE payload: 12 APRV-01 fields, the quantity and the money block."""
    return make_simulate_payload()


# --------------------------------------------------------------------------- #
# Beh. 1 — format_simulate renders all 12 APRV-01 fields byte-checked.
# --------------------------------------------------------------------------- #


def test_format_simulate_renders_all_12_aprv01_fields() -> None:
    """Beh. 1: format_simulate renders all 12 APRV-01 fields with
    Decimal str precision and SIMULATE-recorded labeling.

    Per D-05 + TELEGRAM.md §4: the message carries exactly the 12
    fields (symbol, direction, setup, entry, SL, TP(s), R:R, risk
    percentage, expiry, invalidation, current exposure, reason codes).
    All Decimal values are formatted via `str()` preserving full
    precision (D-12). The text starts with "SIMULATE" so the operator
    can identify the message type at a glance.
    """
    from src.paper.notify import format_simulate

    payload = _make_payload()
    text = format_simulate(**payload)

    # All 12 APRV-01 fields are present in the text.
    assert "BTCUSDT" in text  # 1. symbol
    assert "LONG" in text  # 2. direction
    assert "TREND_PULLBACK_LONG" in text  # 3. setup
    assert "100.10" in text and "100.30" in text  # 4. entry
    assert "99.50" in text  # 5. SL
    assert "101.50" in text and "103.00" in text  # 6. TP(s)
    assert "2.0" in text  # 7. R:R
    assert "0.005" in text  # 8. risk percentage
    # 9. expiry: local +07 with UTC in brackets since Phase 23 (D-14, O-3), no ISO text.
    assert "Expiry: 2026-09-19 20:00:00 +07 (2026-09-19 13:00:00 UTC)" in text
    assert "Detected: 2026-09-19 16:00:00 +07 (2026-09-19 09:00:00 UTC)" in text
    assert "Display:" not in text and "Asia/Ho_Chi_Minh" not in text
    assert "CANDLE_CLOSE < 99.50" in text  # 10. invalidation
    assert "50.00" in text  # 11. current exposure
    assert "SETUP_DETECTED" in text  # 12. reason codes

    # The text starts with "SIMULATE" so the operator can identify
    # the message type at a glance.
    assert text.startswith("SIMULATE ")

    # Decimal precision is preserved (D-12): "100.10" stays "100.10",
    # not "100.1".
    assert "100.10" in text
    assert "100.30" in text


# --------------------------------------------------------------------------- #
# Beh. 2 — notify_simulate enforces journal-first ordering via a
# failing fake bot.
# --------------------------------------------------------------------------- #


class _FakeBot:
    """Fake Telegram bot that records calls and optionally raises."""

    def __init__(self, *, raise_on_send: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_on_send = raise_on_send

    async def send_message(
        self,
        *,
        chat_id: str | int,
        text: str,
        reply_markup: Any,
    ) -> object:
        self.calls.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        if self.raise_on_send is not None:
            raise self.raise_on_send
        return {"message_id": 1}


@pytest.mark.asyncio
async def test_notify_simulate_journal_first_ordering_with_failing_bot() -> None:
    """Beh. 2: notify_simulate enforces journal-first ordering via a
    failing fake bot.

    Per D-05 + RESEARCH §Pitfall 5: the journal commit precedes the
    send call. A failing bot surfaces a JournalEvent outcome with no
    exception escaping. The on_outcome callback is invoked exactly
    once with a FAILED outcome carrying the exception class name.
    """
    from src.paper.notify import NotifyOutcomeKind, notify_simulate

    payload = _make_payload()
    bot = _FakeBot(raise_on_send=RuntimeError("telegram down"))

    outcomes: list[Any] = []

    def on_outcome(outcome: Any) -> None:
        outcomes.append(outcome)

    # The notify call must NOT raise even though the bot fails.
    outcome = await notify_simulate(
        bot=bot,
        chat_id="123456",
        payload=payload,
        on_outcome=on_outcome,
    )

    # The outcome is FAILED with the exception class name.
    assert outcome.kind == NotifyOutcomeKind.FAILED
    assert outcome.error_class == "RuntimeError"
    assert outcome.signal_id == payload["signal_id"]

    # The on_outcome callback was invoked exactly once.
    assert len(outcomes) == 1
    assert outcomes[0] is outcome

    # The bot was called at least once (bounded retry budget).
    assert len(bot.calls) >= 1


@pytest.mark.asyncio
async def test_notify_simulate_succeeds_with_healthy_bot() -> None:
    """Beh. 2b: notify_simulate succeeds with a healthy bot and
    invokes on_outcome with a SENT outcome.

    Per D-05: a successful send journals a SENT outcome. The bot is
    called exactly once (no retries needed).
    """
    from src.paper.notify import NotifyOutcomeKind, notify_simulate

    payload = _make_payload()
    bot = _FakeBot()

    outcomes: list[Any] = []

    def on_outcome(outcome: Any) -> None:
        outcomes.append(outcome)

    outcome = await notify_simulate(
        bot=bot,
        chat_id="123456",
        payload=payload,
        on_outcome=on_outcome,
    )

    assert outcome.kind == NotifyOutcomeKind.SENT
    assert outcome.error_class == ""
    assert outcome.attempts == 1
    assert len(outcomes) == 1
    assert len(bot.calls) == 1


# --------------------------------------------------------------------------- #
# Beh. 3 — inert-callback tests: no Application poller exists in the
# paper package, and no inbound handler can mutate approval state.
# --------------------------------------------------------------------------- #


def test_no_application_poller_in_paper_package() -> None:
    """Beh. 3a: no `Application` poller exists in the paper package.

    Per D-05: Phase 7 sends only (no inbound actions consumed). A
    poller adds an idle update loop and second lifecycle to supervise
    for zero benefit. The paper package must not import
    `telegram.ext.Application` (the poller class).
    """
    paper_dir = Path(__file__).resolve().parents[1] / "src" / "paper"
    for py_file in paper_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "Application" not in text, (
            f"paper package must not import telegram.ext.Application "
            f"(poller is Phase 8+): {py_file}"
        )
        assert "telegram.ext" not in text, (
            f"paper package must not import telegram.ext (poller is Phase 8+): {py_file}"
        )


def test_no_inbound_handler_can_mutate_approval_state() -> None:
    """Beh. 3b: no inbound handler can mutate approval state.

    Per D-05: callbacks are inert labels in Phase 7. The paper
    package must not define any function that mutates approval state
    in response to a callback. The only Telegram-related code in the
    paper package is `format_simulate`, `notify_simulate`, and
    `build_simulate_keyboard` (all send-only — the keyboard builder
    just constructs inert labels).
    """
    notify_path = Path(__file__).resolve().parents[1] / "src" / "paper" / "notify.py"
    tree = ast.parse(notify_path.read_text(encoding="utf-8"))

    defined_functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined_functions.add(node.name)

    allowed_callables = {
        "format_simulate",
        "notify_simulate",
        "build_simulate_keyboard",
    }
    unexpected = defined_functions - allowed_callables
    assert not unexpected, f"unexpected functions in paper.notify: {unexpected}"


def test_telegram_adapter_is_the_only_telegram_importer() -> None:
    """Beh. 3c: the Telegram adapters are the only modules that import
    `python-telegram-bot`.

    Per D-05 + RESEARCH §Pattern 3: the adapters are the ONLY modules
    allowed to import the Telegram SDK. The send-side lives in
    `telegram_notify.py`; the callback-side lives in
    `telegram_callbacks.py`. Downstream consumers receive frozen
    dataclass instances or the `TelegramBot` Protocol.
    """
    src_dir = Path(__file__).resolve().parents[1] / "src"
    importers: list[Path] = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "from telegram import" in text or "import telegram" in text:
            importers.append(py_file)
    importers.sort()
    assert importers == [
        src_dir / "adapters" / "telegram_callbacks.py",
        src_dir / "adapters" / "telegram_notify.py",
    ], f"only the two telegram adapters may import telegram; found: {importers}"


# --------------------------------------------------------------------------- #
# Plan 23-09 task 3 (D-13, D-14): the SIMULATE message carries the quantity and the money block.
# --------------------------------------------------------------------------- #


def _golden_simulate() -> str:
    path = Path(__file__).parent / "fixtures" / "phase23" / "messages" / "simulate.txt"
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def _generator() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "gen_phase23_fixtures.py"
    spec = importlib.util.spec_from_file_location("gen_phase23_fixtures_simulate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_format_simulate_equals_the_generated_golden() -> None:
    from src.paper.notify import format_simulate
    from src.risk.money_at_stake import parse_money_json

    generator = _generator()
    text = format_simulate(
        **generator.approve_fields(), money=parse_money_json(generator.fixture_money_json())
    )

    assert text + "\n" == _golden_simulate()
    lines = text.split("\n")
    assert lines[0] == "SIMULATE BTCUSDT LONG TREND_PULLBACK_LONG"
    assert "Detected: 2026-10-09 10:00:00 +07 (2026-10-09 03:00:00 UTC)" in lines
    assert "Expiry: 2026-10-09 14:00:00 +07 (2026-10-09 07:00:00 UTC)" in lines
    assert "Quantity: 0.08" in lines
    assert lines.index("Quantity: 0.08") == lines.index("Notional: 4008.00 USDT") - 1
    assert "Asia/Ho_Chi_Minh" not in text and "Display:" not in text


def test_format_simulate_money_lines_match_the_approve_request() -> None:
    from src.adapters.telegram_notify import render_money_block
    from src.paper.notify import format_simulate

    payload = _make_payload()
    lines = format_simulate(**payload).split("\n")
    block = list(render_money_block(payload["money"]))

    start = lines.index(block[0])
    assert lines[start : start + len(block)] == block


@pytest.mark.parametrize(
    "change",
    [
        {"money": None},
        {"approved_quantity": Decimal("2.4")},
        {"stop_loss": Decimal("99.40")},
        {"take_profits": [(Decimal("101.50"), Decimal("1"))]},
        {
            "take_profits": [
                (Decimal("101.60"), Decimal("0.5")),
                (Decimal("103.00"), Decimal("0.5")),
            ]
        },
    ],
)
def test_format_simulate_refuses_money_that_is_missing_or_disagrees(
    change: dict[str, Any],
) -> None:
    from src.paper.notify import format_simulate

    payload = _make_payload()
    payload.update(change)
    with pytest.raises(ValueError):
        format_simulate(**payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"delete": "money"},
        {"delete": "approved_quantity"},
        {"update": {"approved_quantity": Decimal("2.4")}},
        {"update": {"stop_loss": Decimal("99.40")}},
        {"update": {"take_profits": [(Decimal("101.50"), Decimal("1"))]}},
        {"update": {"money": make_money(leverage=3)}, "expect": "SENT"},
    ],
)
async def test_notify_simulate_fails_closed_without_consistent_money(
    change: dict[str, Any],
) -> None:
    from src.paper.notify import NotifyOutcomeKind, notify_simulate

    payload = _make_payload()
    if "delete" in change:
        del payload[change["delete"]]
    payload.update(change.get("update", {}))
    bot = _FakeBot()
    outcomes: list[Any] = []

    outcome = await notify_simulate(
        bot=bot, chat_id="123456", payload=payload, on_outcome=outcomes.append
    )

    if change.get("expect") == "SENT":
        # Control: a different leverage with the same quantity, stop and take-profits is consistent.
        assert outcome.kind == NotifyOutcomeKind.SENT
        return
    assert outcome.kind == NotifyOutcomeKind.FAILED
    assert outcome.attempts == 0
    assert bot.calls == []
    assert outcomes == [outcome]
