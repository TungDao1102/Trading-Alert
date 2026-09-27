"""One-time token primitives (Phase 8, plan 08-01).

Per D-01: the token is the one-time secret that proves the human
pressed the button. The raw token is never persisted or logged — only
the SHA-256 hash form is stored on the Approval row. Token comparison
uses constant-time compare to prevent timing attacks.

The module is dependency-free: stdlib only (`hashlib`, `hmac`,
`secrets`). No Telegram, no Binance SDK, no SQLAlchemy, no Pydantic.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def issue_one_time_token() -> str:
    """Return a fresh URL-safe one-time token.

    Per D-01: the token is the one-time secret that proves the human
    pressed the button. It must be URL-safe (Telegram callback_data
    limit) and non-empty. Uses `secrets.token_urlsafe(32)` which
    produces a 43-character URL-safe string from 32 random bytes.
    """
    return secrets.token_urlsafe(32)


def token_hash_of(raw_token: str) -> str:
    """Return the SHA-256 hex digest of a raw token.

    Per D-01: the hash is the idempotency key stored on the Approval
    row. It must be a 64-char lowercase hex SHA-256 string. The raw
    token is never persisted or logged — only this hash form is stored.
    """
    if not isinstance(raw_token, str) or raw_token == "":
        raise ValueError("raw_token must be a non-empty string")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verify_token_hash(raw_token: str, expected_hash: str) -> bool:
    """Constant-time compare of a raw token against an expected hash.

    Per D-01: token comparison must be constant-time to prevent timing
    attacks. Uses `hmac.compare_digest` which compares two strings in
    time proportional to the length of the shorter string, regardless
    of where the first difference occurs.
    """
    if not isinstance(raw_token, str) or raw_token == "":
        return False
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        return False
    actual_hash = token_hash_of(raw_token)
    return hmac.compare_digest(actual_hash, expected_hash)


__all__ = [
    "issue_one_time_token",
    "token_hash_of",
    "verify_token_hash",
]
