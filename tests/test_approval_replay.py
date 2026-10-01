"""Approval binding + replay tests (Phase 8, plan 08-01).

Per D-01: the approval state machine is pure — issue a one-time token,
bind a callback to plan identity, resolve replays to the existing
approval. The 5x-replay proof is the canonical correctness gate: a
human pressing APPROVE once transitions exactly one PENDING approval
to APPROVED with acted_at_utc set; replaying the same callback 4 more
times returns the existing Approval unchanged with zero new
transitions.

The tests load the golden fixture pair (input.json + expected.json)
from `tests/fixtures/phase8/replay_5x/` and drive the approval core
modules (`src/approval/tokens.py`, `src/approval/binding.py`,
`src/approval/replay.py`) to assert:

  1. issue_one_time_token returns a non-empty URL-safe string;
     token_hash_of returns 64-char lowercase hex; verify_token_hash
     uses constant-time compare.
  2. resolve_callback(first APPROVE, valid binding) -> transition
     PENDING to APPROVED, acted_at_utc set.
  3. resolve_callback(same callback x4 more) -> returns existing
     Approval unchanged, zero new transitions (5x = 1 transition).
  4. resolve_callback(now_utc past expiry_utc) -> APPROVAL_EXPIRED,
     stays PENDING.
  5. resolve_callback(plan-hash mismatch) -> STALE_SETUP;
     version/parameterSet mismatch -> INVALIDATED; wrong chat ->
     rejected before state touch; wrong token -> rejected;
     notify-failure path -> stays PENDING.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

PHASE8_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase8"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


def _binding_context(case_input: dict[str, Any]) -> dict[str, Any]:
    """Build the binding context kwargs for resolve_callback.

    The binding context carries the authorized chat id, the expiry,
    and the approval's identity tuple (strategy_version,
    parameter_set_id, parameter_set_hash). These live on the parent
    TradePlan/Signal in production; in tests we inject them directly.
    """
    return {
        "authorized_chat_id": case_input["chat_id"],
        "expiry_utc": _parse_utc(case_input["expiry_utc"]),
        "approval_strategy_version": case_input["strategy_version"],
        "approval_parameter_set_id": case_input["parameter_set_id"],
        "approval_parameter_set_hash": case_input["parameter_set_hash"],
    }


def _make_pending_approval(case_input: dict[str, Any]) -> Any:
    """Build a PENDING Approval from the fixture input.

    Mirrors the canonical Approval construction (src/domain/approval.py)
    with acted_at_utc=None and status=PENDING.
    """
    from src.domain.approval import Approval
    from src.domain.enums import ApprovalAction, ApprovalResult

    return Approval(
        approval_id=case_input["approval_id"],
        trade_plan_id=case_input["trade_plan_id"],
        signal_id=case_input["signal_id"],
        action=ApprovalAction(case_input["action"]),
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash=case_input["token_hash"],
        requested_at_utc=_parse_utc(case_input["requested_at_utc"]),
        acted_at_utc=None,
        actor_id="",
        telegram_message_id=None,
        request_hash=case_input["plan_hash"],
    )


def _make_callback(case_input: dict[str, Any]) -> Any:
    """Build a Callback payload from the fixture input.

    The Callback carries the raw token (never persisted), the chat id,
    the plan identity tuple, and the callback timestamp.
    """
    from src.approval.binding import Callback

    return Callback(
        raw_token=case_input["raw_token"],
        chat_id=case_input["chat_id"],
        plan_hash=case_input["plan_hash"],
        strategy_version=case_input["strategy_version"],
        parameter_set_id=case_input["parameter_set_id"],
        parameter_set_hash=case_input["parameter_set_hash"],
        callback_at_utc=_parse_utc(case_input["callback_at_utc"]),
    )


# Module-level import for ApprovalRejected (used in pytest.raises).
from src.approval.binding import ApprovalRejected  # noqa: E402

# --------------------------------------------------------------------------- #
# Beh. 1 — token primitives: issue, hash, verify.
# --------------------------------------------------------------------------- #


def test_issue_one_time_token_returns_non_empty_urlsafe_string() -> None:
    """Beh. 1a: issue_one_time_token returns a non-empty URL-safe string."""
    from src.approval.tokens import issue_one_time_token

    token = issue_one_time_token()
    assert isinstance(token, str)
    assert token != ""
    import string

    allowed = set(string.ascii_letters + string.digits + "-_")
    assert all(c in allowed for c in token), f"token contains non-URL-safe chars: {token!r}"


def test_token_hash_of_returns_64_char_lowercase_hex() -> None:
    """Beh. 1b: token_hash_of returns 64-char lowercase hex."""
    from src.approval.tokens import token_hash_of

    h = token_hash_of("any-token-string")
    assert isinstance(h, str)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_verify_token_hash_uses_constant_time_compare() -> None:
    """Beh. 1c: verify_token_hash uses constant-time compare."""
    from src.approval.tokens import token_hash_of, verify_token_hash

    raw = "the-raw-token"
    h = token_hash_of(raw)
    assert verify_token_hash(raw, h) is True
    assert verify_token_hash("wrong-token", h) is False


# --------------------------------------------------------------------------- #
# Beh. 2 — 5x replay proof: one APPROVE, exactly one transition.
# --------------------------------------------------------------------------- #


def test_resolve_callback_5x_replay_produces_exactly_one_transition() -> None:
    """Beh. 2: replaying the same APPROVE callback 5 times produces
    exactly one PENDING-to-APPROVED transition.

    Per D-01: a human pressing APPROVE once transitions exactly one
    PENDING approval to APPROVED with acted_at_utc set. Replaying the
    same callback 4 more times returns the existing Approval unchanged
    with zero new transitions (5x = 1 transition).
    """
    from src.approval.replay import resolve_callback

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    # In-memory store keyed by token hash (the idempotency key).
    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    # Replay the same callback 5 times.
    results: list[Any] = []
    for _ in range(case_input["replay_count"]):
        result = resolve_callback(
            callback=callback,
            lookup_by_token_hash=_lookup,
            save=_save,
            **ctx,
        )
        results.append(result)

    # Exactly one transition occurred.
    assert len(transitions) == expected["transitions_count"], (
        f"expected {expected['transitions_count']} transitions, got {len(transitions)}"
    )

    # The final state is APPROVED with acted_at_utc set.
    final = results[-1]
    assert final.status.value == expected["final_status"]
    assert final.result.value == expected["final_result"]
    assert final.acted_at_utc == _parse_utc(expected["acted_at_utc"])
    assert final.approval_token_hash == expected["approval_token_hash"]

    # All 5 results are the same Approval object (replay returns existing).
    for r in results:
        assert r is results[0], "replay must return the same Approval object"


# --------------------------------------------------------------------------- #
# Beh. 3 — expired plan callback is rejected with APPROVAL_EXPIRED.
# --------------------------------------------------------------------------- #


def test_resolve_callback_expired_plan_returns_approval_expired() -> None:
    """Beh. 3: a callback for a past-expiry plan is rejected with
    APPROVAL_EXPIRED and the approval stays PENDING.
    """
    from src.approval.replay import resolve_callback
    from src.domain.enums import RejectionReason

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)

    # Override now_utc to be past expiry_utc.
    past_now = _parse_utc("2026-09-19T12:00:00+00:00")
    callback = _make_callback(case_input)

    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    with pytest.raises(Exception) as exc_info:
        resolve_callback(
            callback=callback,
            lookup_by_token_hash=_lookup,
            save=_save,
            now_utc=past_now,
            **ctx,
        )

    # The exception carries APPROVAL_EXPIRED reason code.
    assert (
        hasattr(exc_info.value, "reason_code")
        and exc_info.value.reason_code == RejectionReason.APPROVAL_EXPIRED
    ), f"expected APPROVAL_EXPIRED, got {exc_info.value}"

    # The approval row stays PENDING with acted_at_utc None.
    assert len(transitions) == 0
    assert pending.status.value == "PENDING"
    assert pending.acted_at_utc is None


# --------------------------------------------------------------------------- #
# Beh. 4 — plan-hash mismatch yields STALE_SETUP.
# --------------------------------------------------------------------------- #


def test_resolve_callback_plan_hash_mismatch_returns_stale_setup() -> None:
    """Beh. 4: a callback with a wrong plan hash yields STALE_SETUP."""
    from src.approval.binding import Callback
    from src.approval.replay import resolve_callback
    from src.domain.enums import RejectionReason

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    # Override plan_hash to a wrong value.
    wrong_hash_callback = Callback(
        raw_token=callback.raw_token,
        chat_id=callback.chat_id,
        plan_hash="0" * 64,  # wrong plan hash
        strategy_version=callback.strategy_version,
        parameter_set_id=callback.parameter_set_id,
        parameter_set_hash=callback.parameter_set_hash,
        callback_at_utc=callback.callback_at_utc,
    )

    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    with pytest.raises(Exception) as exc_info:
        resolve_callback(
            callback=wrong_hash_callback,
            lookup_by_token_hash=_lookup,
            save=_save,
            **ctx,
        )

    assert (
        hasattr(exc_info.value, "reason_code")
        and exc_info.value.reason_code == RejectionReason.STALE_SETUP
    ), f"expected STALE_SETUP, got {exc_info.value}"

    assert len(transitions) == 0
    assert pending.status.value == "PENDING"
    assert pending.acted_at_utc is None


# --------------------------------------------------------------------------- #
# Beh. 5 — version/parameterSet mismatch yields INVALIDATED.
# --------------------------------------------------------------------------- #


def test_resolve_callback_version_mismatch_returns_invalidated() -> None:
    """Beh. 5: a callback with a wrong strategy_version yields INVALIDATED."""
    from src.approval.binding import Callback
    from src.approval.replay import resolve_callback
    from src.domain.enums import RejectionReason

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    wrong_version_callback = Callback(
        raw_token=callback.raw_token,
        chat_id=callback.chat_id,
        plan_hash=callback.plan_hash,
        strategy_version="v9.9.9",  # wrong version
        parameter_set_id=callback.parameter_set_id,
        parameter_set_hash=callback.parameter_set_hash,
        callback_at_utc=callback.callback_at_utc,
    )

    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    with pytest.raises(Exception) as exc_info:
        resolve_callback(
            callback=wrong_version_callback,
            lookup_by_token_hash=_lookup,
            save=_save,
            **ctx,
        )

    assert (
        hasattr(exc_info.value, "reason_code")
        and exc_info.value.reason_code == RejectionReason.INVALIDATED
    ), f"expected INVALIDATED, got {exc_info.value}"

    assert len(transitions) == 0
    assert pending.status.value == "PENDING"
    assert pending.acted_at_utc is None


# --------------------------------------------------------------------------- #
# Beh. 6 — wrong chat is rejected before any state lookup.
# --------------------------------------------------------------------------- #


def test_resolve_callback_wrong_chat_rejected_before_state_lookup() -> None:
    """Beh. 6: a callback with a wrong chat id is rejected before any
    state lookup.
    """
    from src.approval.binding import Callback
    from src.approval.replay import resolve_callback

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    wrong_chat_callback = Callback(
        raw_token=callback.raw_token,
        chat_id=999999999,  # wrong chat
        plan_hash=callback.plan_hash,
        strategy_version=callback.strategy_version,
        parameter_set_id=callback.parameter_set_id,
        parameter_set_hash=callback.parameter_set_hash,
        callback_at_utc=callback.callback_at_utc,
    )

    lookup_called = False
    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        nonlocal lookup_called
        lookup_called = True
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    with pytest.raises(ApprovalRejected):
        resolve_callback(
            callback=wrong_chat_callback,
            lookup_by_token_hash=_lookup,
            save=_save,
            **ctx,
        )

    # The state lookup was never called (chat gate runs first).
    assert lookup_called is False, "chat gate must run before state lookup"
    assert len(transitions) == 0
    assert pending.status.value == "PENDING"
    assert pending.acted_at_utc is None


# --------------------------------------------------------------------------- #
# Beh. 7 — wrong token is rejected.
# --------------------------------------------------------------------------- #


def test_resolve_callback_wrong_token_rejected() -> None:
    """Beh. 7: a callback with a wrong token is rejected."""
    from src.approval.binding import Callback
    from src.approval.replay import resolve_callback

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    wrong_token_callback = Callback(
        raw_token="wrong-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        chat_id=callback.chat_id,
        plan_hash=callback.plan_hash,
        strategy_version=callback.strategy_version,
        parameter_set_id=callback.parameter_set_id,
        parameter_set_hash=callback.parameter_set_hash,
        callback_at_utc=callback.callback_at_utc,
    )

    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    with pytest.raises(ApprovalRejected):
        resolve_callback(
            callback=wrong_token_callback,
            lookup_by_token_hash=_lookup,
            save=_save,
            **ctx,
        )

    assert len(transitions) == 0
    assert pending.status.value == "PENDING"
    assert pending.acted_at_utc is None


# --------------------------------------------------------------------------- #
# Beh. 8 — exactly-at-expiry is unapprovable; one second before is approvable.
# --------------------------------------------------------------------------- #


def test_resolve_callback_exactly_at_expiry_is_unapprovable() -> None:
    """Beh. 8a: now_utc == expiry_utc is unapprovable (boundary rule)."""
    from src.approval.replay import resolve_callback
    from src.domain.enums import RejectionReason

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    # Exactly at expiry boundary.
    boundary_now = _parse_utc(case_input["expiry_utc"])

    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    with pytest.raises(Exception) as exc_info:
        resolve_callback(
            callback=callback,
            lookup_by_token_hash=_lookup,
            save=_save,
            now_utc=boundary_now,
            **ctx,
        )

    assert (
        hasattr(exc_info.value, "reason_code")
        and exc_info.value.reason_code == RejectionReason.APPROVAL_EXPIRED
    ), f"expected APPROVAL_EXPIRED, got {exc_info.value}"

    assert len(transitions) == 0
    assert pending.status.value == "PENDING"
    assert pending.acted_at_utc is None


def test_resolve_callback_one_second_before_expiry_is_approvable() -> None:
    """Beh. 8b: now_utc == expiry_utc - 1 second is approvable."""
    from src.approval.replay import resolve_callback

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    # One second before expiry.
    expiry = _parse_utc(case_input["expiry_utc"])
    just_before_now = expiry - timedelta(seconds=1)

    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save(approval: Any) -> None:
        store[approval.approval_token_hash] = approval
        transitions.append(approval)

    result = resolve_callback(
        callback=callback,
        lookup_by_token_hash=_lookup,
        save=_save,
        now_utc=just_before_now,
        **ctx,
    )

    assert result.status.value == "APPROVED"
    assert result.acted_at_utc is not None
    assert len(transitions) == 1


# --------------------------------------------------------------------------- #
# Beh. 9 — notify-failure path leaves approval PENDING.
# --------------------------------------------------------------------------- #


def test_resolve_callback_notify_failure_leaves_approval_pending() -> None:
    """Beh. 9: a failed notification leaves the approval PENDING and
    never auto-approves.
    """
    from src.approval.replay import resolve_callback

    case_dir = PHASE8_FIXTURES_DIR / "replay_5x"
    case_input = _load_input(case_dir)
    ctx = _binding_context(case_input)

    pending = _make_pending_approval(case_input)
    callback = _make_callback(case_input)

    # Simulate a notify-failure path: the save callback raises.
    store: dict[str, Any] = {pending.approval_token_hash: pending}
    transitions: list[Any] = []

    def _lookup(token_hash: str) -> Any | None:
        return store.get(token_hash)

    def _save_failing(approval: Any) -> None:
        raise RuntimeError("notify failed")

    with pytest.raises(RuntimeError):
        resolve_callback(
            callback=callback,
            lookup_by_token_hash=_lookup,
            save=_save_failing,
            **ctx,
        )

    # The approval row stays PENDING (no transition persisted).
    assert pending.status.value == "PENDING"
    assert pending.acted_at_utc is None
    assert len(transitions) == 0


# --------------------------------------------------------------------------- #
# Beh. 10 — no synonym reason strings invented outside src/domain/enums.py.
# --------------------------------------------------------------------------- #


def test_no_synonym_reason_strings_in_src_approval() -> None:
    """Beh. 10: no RejectionReason synonyms exist in src/approval/.

    Per GLOSSARY §9 + 05-01 D-05: the canonical RejectionReason enum
    lives in `src/domain/enums.py`. No module may invent synonyms such
    as `Skipped-User`, `USER_SKIPPED`, `WRONG_CHAT`, `WRONG_TOKEN`, or
    `NOT_FOUND` — they must reuse the canonical enum names.

    This test greps src/approval/ for any string literal that looks
    like a reason code but is NOT a canonical RejectionReason value,
    and asserts the grep finds zero matches.
    """
    import re
    from pathlib import Path

    from src.domain.enums import RejectionReason

    canonical = {r.value for r in RejectionReason}

    approval_dir = Path("src/approval")
    pattern = re.compile(r'"([A-Z][A-Z0-9_]{2,})"')

    suspicious: list[str] = []
    for py_file in approval_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # Skip comment-only lines and docstrings.
            if stripped.startswith("#"):
                continue
            for match in pattern.finditer(line):
                candidate = match.group(1)
                # Skip if it's a canonical RejectionReason value.
                if candidate in canonical:
                    continue
                # Skip common non-reason string constants.
                if candidate in (
                    "PENDING",
                    "APPROVED",
                    "SKIPPED",
                    "EXPIRED",
                    "INVALIDATED",
                    "STALE_SETUP",
                    "APPROVAL_EXPIRED",
                    "APPROVE",
                    "SIMULATE",
                    "SKIP_USER",
                    "SKIP_BUSY",
                    "CANCEL",
                    "UTF-8",
                ):
                    continue
                # Skip module export names (e.g. __all__ entries) — they
                # are vocabulary, not reason codes.
                if candidate in ("SHORT_ID_LENGTH",):
                    continue
                # Skip if it looks like a Python builtin or stdlib name.
                if candidate in ("TRUE", "FALSE", "NONE"):
                    continue
                suspicious.append(f"{py_file.name}:{line_num}:{candidate}")

    # If suspicious found, surface them so the test fails loudly.
    assert not suspicious, f"suspect reason-string literals in src/approval/: {suspicious}"


# --------------------------------------------------------------------------- #
# Phase 17 plan 09 (D-17, research C15): a lost cross-process race resolves to
# the STORED approval (same outcome) or an explicit INVALIDATED rejection.
# --------------------------------------------------------------------------- #


def _lost_race_setup(existing_action: str, existing_status: str) -> tuple[Any, Any, Any, Any]:
    from dataclasses import replace

    from src.approval.replay import ApprovalAlreadyDecided
    from src.domain.enums import ApprovalAction, ApprovalResult

    case_input = _load_input(PHASE8_FIXTURES_DIR / "replay_5x")
    pending = _make_pending_approval(case_input)
    decided_result = ApprovalResult(existing_status)
    existing = replace(
        pending,
        action=ApprovalAction(existing_action),
        result=decided_result,
        status=decided_result,
        acted_at_utc=_parse_utc("2026-09-19T10:20:00+00:00"),
        actor_id="other-process",
    )

    def _save(approval: Any) -> None:
        raise ApprovalAlreadyDecided(existing)

    return case_input, pending, existing, _save


def test_lost_race_with_matching_outcome_returns_stored_approval() -> None:
    from src.approval.replay import resolve_callback

    case_input, pending, existing, save = _lost_race_setup("APPROVE", "APPROVED")
    ctx = _binding_context(case_input)

    result = resolve_callback(
        callback=_make_callback(case_input),
        lookup_by_token_hash=lambda h: pending,
        save=save,
        **ctx,
    )

    assert result is existing
    assert result.actor_id == "other-process"


def test_lost_race_with_different_outcome_is_invalidated() -> None:
    from src.approval.replay import resolve_callback
    from src.domain.enums import RejectionReason

    case_input, pending, _existing, save = _lost_race_setup("SKIP_USER", "SKIPPED")
    ctx = _binding_context(case_input)

    with pytest.raises(ApprovalRejected) as excinfo:
        resolve_callback(
            callback=_make_callback(case_input),
            lookup_by_token_hash=lambda h: pending,
            save=save,
            **ctx,
        )

    assert excinfo.value.reason_code is RejectionReason.INVALIDATED


def test_approval_already_decided_carries_existing_and_is_exported() -> None:
    from src.approval import replay

    case_input = _load_input(PHASE8_FIXTURES_DIR / "replay_5x")
    pending = _make_pending_approval(case_input)
    exc = replay.ApprovalAlreadyDecided(pending)
    assert exc.existing is pending
    assert "ApprovalAlreadyDecided" in replay.__all__
