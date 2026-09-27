"""Approval package — pure, dependency-free approval state machine (Phase 8, plan 08-01).

Per D-01: the approval core is a pure state machine. It issues one-time
tokens, binds Telegram callbacks to plan identity, and resolves replays
to the existing approval row. The package imports only stdlib and
`src/domain/*` — no Telegram, no Binance SDK, no SQLAlchemy, no
Pydantic, no Polars.

Public surface (the only symbols downstream code uses):

  - `tokens.issue_one_time_token` — generate a URL-safe one-time token.
  - `tokens.token_hash_of` — SHA-256 hex digest of a raw token.
  - `tokens.verify_token_hash` — constant-time token-hash compare.
  - `binding.Callback` — frozen dataclass carrying the callback payload.
  - `binding.BindingCheck` — frozen dataclass carrying the gate result.
  - `binding.check_binding` — fixed-order gate (chat, expiry, hash,
    version, token).
  - `binding.ApprovalRejected` — exception carrying a RejectionReason.
  - `replay.resolve_callback` — replay-to-existing resolution with
    exactly-one-transition semantics.

The package owns the approval binding slice: token primitives live in
`tokens.py`, the gate order lives in `binding.py`, and the replay
resolution lives in `replay.py`. No ORM, no Telegram, no Binance SDK
enters this package; only these named sibling surfaces do.
"""

from __future__ import annotations

from .binding import (
    ApprovalRejected,
    BindingCheck,
    Callback,
    action_to_result,
    check_binding_full,
)
from .replay import resolve_callback
from .tokens import issue_one_time_token, token_hash_of, verify_token_hash

__all__ = [
    # tokens
    "issue_one_time_token",
    "token_hash_of",
    "verify_token_hash",
    # binding
    "Callback",
    "BindingCheck",
    "check_binding_full",
    "action_to_result",
    "ApprovalRejected",
    # replay
    "resolve_callback",
]
