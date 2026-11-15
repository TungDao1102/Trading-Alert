"""Clear the DEMO leftovers of a rehearsal so the next one need not wait for a plan to expire.

A plan whose placement was refused (or that nobody confirmed) stays APPROVED until its expiry
time, about 26 minutes for a smoke plan, and its approval blocks every new card of the symbol.
This script closes those plans the official way (the DOMN-04 transition APPROVED -> EXPIRED, one
journal row each) and leaves a persisted SAFE_MODE with an operator exit. The reservation that
belongs to a closed plan is released by the live process's own sweep at its next start.

DEMO only. It refuses unless LIVE_RUNTIME_MODE is DEMO and the typed phrase matches, and it
refuses while an execution intent is unresolved (an entry or a protective order may be live).
Close every position and order in the Binance Demo UI first. Run from the repo root:

    $env:PYTHONPATH = "."; uv run python scripts/demo_clear.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text  # noqa: E402
from src.domain.enums import SystemStateKey, TradePlanStatus  # noqa: E402
from src.domain.journal import JournalEvent, content_hash_event_id  # noqa: E402
from src.live.approval_sender import make_open_demo_approvals_reader  # noqa: E402

PHRASE = "DEMO IS FLAT"
OPERATOR_ID = "owner-demo-clear"
EVENT_STALE_PLAN_CLEARED = "DEMO_STALE_PLAN_CLEARED"
# The plan statuses the DOMN-04 table lets move to EXPIRED.
_CLOSABLE = frozenset(
    {TradePlanStatus.READY, TradePlanStatus.APPROVAL_PENDING, TradePlanStatus.APPROVED}
)


def clear_open_plans(*, shadow: Any, entities: Any, journal: Any, now_utc: datetime) -> list[str]:
    """Move every plan behind an open DEMO approval to EXPIRED; returns the closed plan ids."""
    closed: list[str] = []
    for item in make_open_demo_approvals_reader(shadow)():
        approval = shadow.get_approval(item.approval_id)
        if approval is None or approval.trade_plan_id in closed:
            continue
        plan = shadow.get_trade_plan(approval.trade_plan_id)
        if plan is None or plan.status not in _CLOSABLE:
            continue
        entities.transition_trade_plan(plan.trade_plan_id, TradePlanStatus.EXPIRED, now_utc=now_utc)
        body = json.dumps(
            {"from_status": plan.status.value, "operator_id": OPERATOR_ID, "symbol": item.symbol},
            sort_keys=True,
            separators=(",", ":"),
        )
        journal.record(
            JournalEvent(
                journal_event_id=content_hash_event_id(
                    prefix="dscl",
                    event_type=EVENT_STALE_PLAN_CLEARED,
                    entity_id=plan.plan_hash,
                    occurred_at_utc=now_utc,
                    payload_json=body,
                ),
                occurred_at_utc=now_utc,
                event_type=EVENT_STALE_PLAN_CLEARED,
                entity_type="TradePlan",
                entity_id=plan.plan_hash,
                correlation_id=f"demo_clear_{plan.plan_hash}",
                trade_plan_id=plan.trade_plan_id,
                payload_json=body,
            )
        )
        closed.append(plan.trade_plan_id)
    return closed


def exit_safe_mode(*, system_state: Any, now_utc: datetime) -> bool:
    """Record an operator exit of a persisted SAFE_MODE; False when it was not set."""
    latest = system_state.latest(SystemStateKey.SAFE_MODE)
    if latest is None or not latest.state.get("in_safe_mode"):
        return False
    system_state.append(
        SystemStateKey.SAFE_MODE,
        {
            "in_safe_mode": False,
            "entered_at_utc": None,
            "entered_reason": None,
            "last_exit_at_utc": now_utc.isoformat(),
            "last_exit_operator_id": OPERATOR_ID,
        },
        now_utc=now_utc,
    )
    return True


def main() -> int:
    from src.live.wiring import build_pg_stores
    from src.persistence.engine import make_sync_engine
    from src.persistence.uow import OperationalDatabase

    if os.environ.get("LIVE_RUNTIME_MODE") != "DEMO":
        print("refused: LIVE_RUNTIME_MODE must be DEMO")
        return 2
    if "DATABASE_URL" not in os.environ:
        print("refused: DATABASE_URL is not set")
        return 2
    if input(f"type {PHRASE!r} after the Demo account is flat: ").strip() != PHRASE:
        print("refused: phrase did not match")
        return 2

    engine = make_sync_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        unresolved = conn.execute(
            text("select count(*) from execution_intents where resolved_at_utc is null")
        ).scalar_one()
    if unresolved:
        print(
            f"refused: {unresolved} execution intent(s) are unresolved; an entry or a protective "
            "order may be live. Start the live process once so reconcile settles them, close "
            "everything in the Demo UI, then run this again."
        )
        return 2

    stores = build_pg_stores(OperationalDatabase(engine))
    now = datetime.now(UTC)
    closed = clear_open_plans(
        shadow=stores.shadow, entities=stores.entities, journal=stores.journal, now_utc=now
    )
    left = exit_safe_mode(system_state=stores.system_state, now_utc=now)
    print(f"plans closed: {len(closed)}")
    print(f"SAFE_MODE exited: {left}")
    print("done. The next live start releases the reservations of the closed plans itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
