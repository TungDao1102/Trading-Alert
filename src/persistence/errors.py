"""Typed persistence failures (Phase 17, interface-first for plans 02-13).

Every class here is pure Python (no SQLAlchemy import) so execution code and
test doubles can raise and catch them without touching a database driver.
Messages carry exception TYPE names and identifiers only, never a database URL,
a password or a raw token (ASVS V7, T-17-03).

Callers translate these to a fail-closed outcome (NO_TRADE or SAFE_MODE); there is
never a retry loop on the order path (D-04, F-406).
"""

from __future__ import annotations


class PersistenceError(Exception):
    """Base class for every operational-persistence failure."""


class StoreUnavailable(PersistenceError):
    """PostgreSQL could not be reached or answered at the connection level.

    Fail closed: the store never degrades to in-memory state (D-04, T-17-04).
    """


class SessionTimeZoneNotUtc(PersistenceError):
    """A pooled connection reported a TimeZone other than UTC (F-406, Pitfall 14)."""


class JournalConflict(PersistenceError):
    """A journal id already exists with a different payload (F-412)."""


class RowConflict(PersistenceError):
    """An idempotent insert met an existing row that is not identical."""


class ParentRowMissing(PersistenceError):
    """A child row was written before its parent (foreign key would be violated)."""


class PrecisionError(PersistenceError, ValueError):
    """A Decimal does not survive NUMERIC(38,18) unchanged (F-410)."""


class ShortIdRebindingRefused(PersistenceError):
    """A short id is already bound to a different (signal, trade plan) pair (research C16)."""


class IntentStateConflict(PersistenceError):
    """An execution-intent write violated the allowed state machine or arbiter.

    Raised for a missing row, an illegal predecessor status, a second outcome
    record, or a uniqueness violation on a different arbiter than
    `(approval_id, role)` (for example a second approval for the same plan).
    The surrounding transaction rolls back, so no half-written intent survives.
    """
