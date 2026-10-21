"""What a reconcile tick does with each divergence kind (Phase 20, plan 20-12; D-01, D-02, D-07).

A pure table, one `DivergencePolicy` per kind of `src.reconcile.compare`:

  * every kind enters SAFE_MODE (any divergence blocks new entries; the reason is the kind name,
    except STREAM_TASK_DIED which is the supervisor halt USER_DATA_STREAM_HALTED);
  * exactly one owner acts: `SWEEP_ORPHAN` (the cancel-only sweeper, ORPHAN_PROTECTIVE only),
    `DELEGATE_TO_COORDINATOR` (stop-related exposure goes to the protection coordinator, which
    decides by the position as in D077) or `ALERT_ONLY` (the operator is told, nothing is touched);
  * every kind raises one alert event.

A foreign or untracked order is `ALERT_ONLY` for good: this system never cancels or sweeps what
it did not prove it owns (D-02), and closing a position it did not open is the human's EXEC-06
action. No kind is mapped to a cancel of a foreign order, and `SWEEP_ORPHAN` belongs to
ORPHAN_PROTECTIVE alone (tests pin both).

The SAFE_MODE reasons named after the new kinds need their GLOSSARY 9.4 rows; plan 20-24 writes
them. The module is pure: stdlib and the kind constants of the compare only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from src.reconcile.compare import (
    DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER,
    DIVERGENCE_KIND_DOUBLED_POSITION,
    DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID,
    DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
    DIVERGENCE_KIND_FOREIGN_ORDER,
    DIVERGENCE_KIND_ORPHAN_PROTECTIVE,
    DIVERGENCE_KIND_POSITION_WITHOUT_STOP,
    DIVERGENCE_KIND_SIGN_FLIPPED_POSITION,
    DIVERGENCE_KIND_STREAM_SINK_FAILURE,
    DIVERGENCE_KIND_STREAM_TASK_DIED,
    DIVERGENCE_KIND_TP_ONLY_POSITION,
    DIVERGENCE_KIND_UNSUPPORTED_POSITION_SIDE,
    DIVERGENCE_KIND_UNSYNCED_ALGO,
    DIVERGENCE_KIND_UNSYNCED_NORMAL,
    DIVERGENCE_KIND_UNSYNCED_POSITION,
    DIVERGENCE_KIND_UNTRACKED_SYSTEM_ORDER,
)

# Alert event names (the OPS-05 vocabulary of plan 20-13's `ALERT_EVENTS`).
ALERT_UNPROTECTED_POSITION: str = "UNPROTECTED_POSITION"
ALERT_DIVERGENCE: str = "DIVERGENCE"
ALERT_FOREIGN_ORDER: str = "FOREIGN_ORDER"
ALERT_UNKNOWN_ORDER: str = "UNKNOWN_ORDER"
# Raised by the stale-feed work of plan 20-16; no divergence kind maps to it.
ALERT_STALE_DATA: str = "STALE_DATA"

#: The SAFE_MODE reason of the supervisor halt (Phase 18 TASK_DIED, D-04).
SAFE_MODE_USER_DATA_STREAM_HALTED: str = "USER_DATA_STREAM_HALTED"


class DivergenceAction(str, Enum):
    """The one owner that acts on a divergence besides SAFE_MODE and the alert."""

    SWEEP_ORPHAN = "SWEEP_ORPHAN"
    DELEGATE_TO_COORDINATOR = "DELEGATE_TO_COORDINATOR"
    ALERT_ONLY = "ALERT_ONLY"


@dataclass(frozen=True)
class DivergencePolicy:
    """SAFE_MODE reason, alert event and action of one divergence kind."""

    safe_mode_reason: str
    alert_event: str
    action: DivergenceAction


def _policy(
    kind: str, alert_event: str, action: DivergenceAction, *, safe_mode_reason: str | None = None
) -> tuple[str, DivergencePolicy]:
    return kind, DivergencePolicy(
        safe_mode_reason=kind if safe_mode_reason is None else safe_mode_reason,
        alert_event=alert_event,
        action=action,
    )


POLICY_BY_KIND: Mapping[str, DivergencePolicy] = MappingProxyType(
    dict(
        (
            _policy(
                DIVERGENCE_KIND_ORPHAN_PROTECTIVE,
                ALERT_DIVERGENCE,
                DivergenceAction.SWEEP_ORPHAN,
            ),
            _policy(
                DIVERGENCE_KIND_POSITION_WITHOUT_STOP,
                ALERT_UNPROTECTED_POSITION,
                DivergenceAction.DELEGATE_TO_COORDINATOR,
            ),
            _policy(
                DIVERGENCE_KIND_TP_ONLY_POSITION,
                ALERT_UNPROTECTED_POSITION,
                DivergenceAction.DELEGATE_TO_COORDINATOR,
            ),
            _policy(
                DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
                ALERT_UNPROTECTED_POSITION,
                DivergenceAction.DELEGATE_TO_COORDINATOR,
            ),
            _policy(
                DIVERGENCE_KIND_SIGN_FLIPPED_POSITION,
                ALERT_DIVERGENCE,
                DivergenceAction.DELEGATE_TO_COORDINATOR,
            ),
            _policy(
                DIVERGENCE_KIND_DOUBLED_POSITION,
                ALERT_DIVERGENCE,
                DivergenceAction.DELEGATE_TO_COORDINATOR,
            ),
            _policy(
                DIVERGENCE_KIND_FOREIGN_ORDER,
                ALERT_FOREIGN_ORDER,
                DivergenceAction.ALERT_ONLY,
            ),
            _policy(
                DIVERGENCE_KIND_UNTRACKED_SYSTEM_ORDER,
                ALERT_UNKNOWN_ORDER,
                DivergenceAction.ALERT_ONLY,
            ),
            _policy(DIVERGENCE_KIND_UNSYNCED_NORMAL, ALERT_DIVERGENCE, DivergenceAction.ALERT_ONLY),
            _policy(DIVERGENCE_KIND_UNSYNCED_ALGO, ALERT_DIVERGENCE, DivergenceAction.ALERT_ONLY),
            _policy(
                DIVERGENCE_KIND_UNSYNCED_POSITION, ALERT_DIVERGENCE, DivergenceAction.ALERT_ONLY
            ),
            _policy(
                DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID,
                ALERT_DIVERGENCE,
                DivergenceAction.ALERT_ONLY,
            ),
            _policy(
                DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER,
                ALERT_DIVERGENCE,
                DivergenceAction.ALERT_ONLY,
            ),
            _policy(
                DIVERGENCE_KIND_UNSUPPORTED_POSITION_SIDE,
                ALERT_DIVERGENCE,
                DivergenceAction.ALERT_ONLY,
            ),
            _policy(
                DIVERGENCE_KIND_STREAM_SINK_FAILURE,
                ALERT_DIVERGENCE,
                DivergenceAction.ALERT_ONLY,
            ),
            _policy(
                DIVERGENCE_KIND_STREAM_TASK_DIED,
                ALERT_DIVERGENCE,
                DivergenceAction.ALERT_ONLY,
                safe_mode_reason=SAFE_MODE_USER_DATA_STREAM_HALTED,
            ),
        )
    )
)


def classify(kind: str) -> DivergencePolicy:
    """The policy of one divergence kind.

    Raises:
        KeyError: `kind` is not a kind of the compare vocabulary (a new kind must be classified
            here before any tick can see it; nothing is ever defaulted).
    """
    return POLICY_BY_KIND[kind]


__all__ = [
    "ALERT_DIVERGENCE",
    "ALERT_FOREIGN_ORDER",
    "ALERT_STALE_DATA",
    "ALERT_UNKNOWN_ORDER",
    "ALERT_UNPROTECTED_POSITION",
    "POLICY_BY_KIND",
    "SAFE_MODE_USER_DATA_STREAM_HALTED",
    "DivergenceAction",
    "DivergencePolicy",
    "classify",
]
