"""Read-only Demo probe of user-data stream silence (Phase 24, input for stale_feed key 14).

Run from the repository root::

    uv run python -m scripts.user_data_silence_probe --minutes 45 --execute

What it does. Opens ONE user-data stream on Binance Demo (listenKey + SDK subscription), places
NO order and changes no account state, keeps the listenKey alive, and records the time of every
signal the live process counts as liveness (`src/live/feeds.py`: the newest of event, ping and
pong). At the end it writes the longest gap between consecutive liveness signals, per signal and
combined. That combined gap is what `stale_feed.max_user_data_silence_ms` must exceed.

Safety: dry run by default (prints the plan, no network). `--execute` needs an interactive
terminal and the typed phrase ``DEMO SILENCE PROBE``. The environment is always DEMO; credentials
come from BINANCE_DEMO_*; any LIVE credential variable refuses the run. The evidence holds only
timestamps and counts. Run it on the owner machine with no other process on the same Demo account
(the listenKey is a singleton).

Exit codes: 0 done, 1 failed part-way, 2 refused before any network call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import user_data_smoke as smoke

PHRASE = "DEMO SILENCE PROBE"
KEEPALIVE_SECONDS = 25 * 60
DEFAULT_SMOKE_LIMITS = Path(
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-smoke-limits.toml"
)
DEFAULT_EVIDENCE_DIR = Path(".planning/phases/24-live-runtime-composition-demo/evidence")


def _now() -> datetime:
    return datetime.now(UTC)


def max_gap_ms(times: Sequence[datetime], start: datetime, end: datetime) -> int | None:
    """Longest gap between consecutive signals, counting the run start and end as bounds."""
    if not times:
        return None
    points = [start, *sorted(times), end]
    return max(
        int((b - a).total_seconds() * 1000) for a, b in zip(points, points[1:], strict=False)
    )


def summarize(signals: dict[str, list[datetime]], start: datetime, end: datetime) -> dict[str, Any]:
    combined = [t for times in signals.values() for t in times]
    return {
        "run_ms": int((end - start).total_seconds() * 1000),
        "counts": {name: len(times) for name, times in signals.items()},
        "max_gap_ms": {name: max_gap_ms(times, start, end) for name, times in signals.items()},
        "max_gap_ms_combined": max_gap_ms(combined, start, end),
    }


async def _run(minutes: int, evidence_dir: Path) -> int:
    config = smoke.parse_config(
        [
            "--environment",
            "DEMO",
            "--smoke-limits-file",
            str(DEFAULT_SMOKE_LIMITS),
            "--execute",
        ]
    )
    rig = smoke.build_live_rig(config, environ=os.environ)
    signals: dict[str, list[datetime]] = {"event": [], "ping": [], "pong": []}
    others: list[dict[str, Any]] = []
    started = _now()

    def on_message(_message: object) -> None:
        signals["event"].append(_now())

    def on_connection(name: str) -> None:
        if name in ("ping", "pong"):
            signals[name].append(_now())
        else:
            others.append({"t_ms": int((_now() - started).total_seconds() * 1000), "name": name})

    rig.transport.set_message_sink(on_message)
    rig.transport.set_connection_sink(on_connection)
    failure: str | None = None
    try:
        key = await rig.listen_keys.start()
        await rig.transport.connect(key)
        started = _now()
        deadline = started.timestamp() + minutes * 60
        next_keepalive = started.timestamp() + KEEPALIVE_SECONDS
        while _now().timestamp() < deadline:
            await asyncio.sleep(5)
            if _now().timestamp() >= next_keepalive:
                await rig.listen_keys.keepalive()
                next_keepalive += KEEPALIVE_SECONDS
    except Exception as exc:  # report, then clean up
        failure = type(exc).__name__
    finally:
        ended = _now()
        for closer in (rig.transport.close, rig.listen_keys.close):
            try:
                await closer()
            except Exception as exc:
                failure = failure or f"cleanup:{type(exc).__name__}"
    document = {
        "kind": "user_data_silence_probe",
        "environment": "DEMO",
        "started_utc": started.isoformat(),
        "minutes_requested": minutes,
        "keepalive_ok": rig.listen_keys.keepalive_ok,
        "listen_key_errors": rig.listen_keys.errors,
        "connection_events": others,
        "failure": failure,
        **summarize(signals, started, ended),
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"silence-probe-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: document[k] for k in ("counts", "max_gap_ms", "max_gap_ms_combined")}))
    print(f"evidence: {path}")
    return 1 if failure else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="user_data_silence_probe", allow_abbrev=False)
    parser.add_argument("--minutes", type=int, default=45)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not 5 <= args.minutes <= 240:
        print("refused: --minutes must be 5..240")
        return 2
    if not args.execute:
        print(
            f"dry run: would watch the DEMO user-data stream for {args.minutes} minutes, no order."
        )
        print(f"add --execute and type: {PHRASE}")
        return 0
    if not sys.stdin.isatty():
        print("refused: --execute needs an interactive terminal")
        return 2
    if input(f"type {PHRASE!r} to continue: ").strip() != PHRASE:
        print("refused: phrase did not match")
        return 2
    try:
        return asyncio.run(_run(args.minutes, args.evidence_dir))
    except Exception as exc:  # credential/env refusals land here before any network call
        print(f"refused: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
