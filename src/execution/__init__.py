"""Execution package — order identifier derivation (Phase 8, plan 08-03).

Per D-04: a retry, restart, or replay of an approved plan must reuse the
exchange-deduped identifier instead of minting a new one. The derivation
is a pure function of `(plan_hash, role)` over stdlib `hashlib` only.

Public surface (the only symbols downstream code uses):

  - `ROLE_CODES` — canonical role-to-code table (the single import site
    for role codes used by derivation, sweeper, and fixtures).
  - `derive_client_order_id(plan_hash, role)` — Binance client_order_id.
  - `derive_algo_client_id(plan_hash, role)` — Binance algo_client_id.

The package is dependency-free: stdlib + `src/domain/enums.py` only.
No Telegram, no Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from .order_ids import (
    ROLE_CODES,
    derive_algo_client_id,
    derive_client_order_id,
)

__all__ = [
    "ROLE_CODES",
    "derive_client_order_id",
    "derive_algo_client_id",
]
