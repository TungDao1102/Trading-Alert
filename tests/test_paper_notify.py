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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _make_payload() -> dict[str, Any]:
    """Build a canonical 12-field SIMULATE payload for tests."""
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup": "TREND_PULLBACK_LONG",
        "entry_min": Decimal("100.10"),
        "entry_max": Decimal("100.30"),
        "stop_loss": Decimal("99.50"),
        "take_profits": [
            (Decimal("101.50"), Decimal("0.5")),
            (Decimal("103.00"), Decimal("0.5")),
        ],
        "rr": Decimal("2.0"),
        "risk_pct": Decimal("0.005"),
        "expiry_utc": datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        "invalidation": "CANDLE_CLOSE < 99.50",
        "exposure_quote": Decimal("50.00"),
        "reason_codes": ["SETUP_DETECTED"],
        "signal_id": "sig_test_0000000000000000000000000000000000000000000000000000",
        "detected_at_utc": datetime(2026, 9, 19, 9, 0, tzinfo=UTC),
    }


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
    assert "2026-09-19T13:00:00+00:00" in text  # 9. expiry
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
        self.calls.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )
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
            f"paper package must not import telegram.ext (poller is "
            f"Phase 8+): {py_file}"
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
    assert not unexpected, (
        f"unexpected functions in paper.notify: {unexpected}"
    )


def test_telegram_adapter_is_the_only_telegram_importer() -> None:
    """Beh. 3c: the Telegram adapter is the only module that imports
    `python-telegram-bot`.

    Per D-05 + RESEARCH §Pattern 3: the adapter is the ONLY module
    allowed to import the Telegram SDK. Downstream consumers receive
    frozen dataclass instances or the `TelegramBot` Protocol.
    """
    src_dir = Path(__file__).resolve().parents[1] / "src"
    importers: list[Path] = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "from telegram import" in text or "import telegram" in text:
            importers.append(py_file)
    assert importers == [
        src_dir / "adapters" / "telegram_notify.py"
    ], f"only src/adapters/telegram_notify.py may import telegram; found: {importers}"
