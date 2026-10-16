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


class StoreFailure(PersistenceError):
    """PostgreSQL answered with an error that is not a connection loss or a constraint hit.

    Covers a read-only transaction after a failover (`InternalError`), a trigger
    `RAISE EXCEPTION` (`ProgrammingError`) and an out-of-range value (`DataError`).
    The message carries exception type names only, never SQL, parameters or a URL.
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


class EvidenceRequired(PersistenceError):
    """An Order or Position would leave UNKNOWN without recorded Binance evidence (G4-034).

    Raised when no `ExitEvidence` was supplied or the store has no journal to record it in;
    nothing is written (D051 item i, D-08).
    """


class ShortIdRebindingRefused(PersistenceError):
    """A short id is already bound to a different (signal, trade plan) pair (research C16)."""


class IntentStateConflict(PersistenceError):
    """An execution-intent write violated the allowed state machine or arbiter.

    Raised for a missing row, an illegal predecessor status, a second outcome
    record, or a uniqueness violation on a different arbiter than
    `(approval_id, role)` (for example a second approval for the same plan).
    The surrounding transaction rolls back, so no half-written intent survives.
    """
