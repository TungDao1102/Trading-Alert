"""Replay inputs and the acceptance log of the paper runtime (Phase 16, plan 16-51).

User decision `16-DEC-PARITY` (option 1, 2026-10-10): the runtime records the inputs the parity
replay needs, so the trial evaluator (D061 item D, L-04: tolerance zero) rebuilds the replay from
an evidence bundle and nothing else. Two record payloads are built here:

- `PAPER_REPLAY_INPUTS` (`replay_inputs_payload`): per evaluated live 1h bar, what the risk stage
  read: the constraint snapshot, the account state, the four absolute portfolio thresholds, the
  open positions and daily loss the risk-inputs port returned at the close, the plan ttl, the
  digests of the whole `BarContext` and of both windows, and `window_accept_seq` (the last
  accepted bar the live windows were cut after). Schema /2 (16-DEC-EQUITY-BASE) records the
  resolved thresholds because the sizing equity (the current ledger equity) is no longer the base
  they were resolved on (the UTC day-start equity); schema /1 records carry no such group;
- `PAPER_HISTORY_BARS` (`history_log_payload`): every bar the pipeline accepted into its history,
  live bars included, each with its acceptance sequence `accept_seq`. The live windows depend on
  the ORDER in which bars entered the buffers (a bar backfilled after a later live bar is absent
  from that bar's window), so the replay feeds a fresh buffer set from this log in acceptance order.

`context_from_inputs` rebuilds the `BarContext` of a recorded bar the way `make_context_factory`
derived it (cost model from the registry slice of the pinned set; absolute thresholds from the
recorded group for /2, from the set's rates times the recorded equity for /1, the derivation that
wrote /1 records) and verifies the parameter set hash, the cost model hash and the recomputed
`context_digest`; any difference raises `ReplayInputsError` naming the field group.

Pure module: stdlib, Decimal, the canonical hash helper and project types. No clock, no float, no
adapter, no SQLAlchemy. It never implements the risk-inputs port (the replay builds `BarContext`
values from recorded data and nothing asks it for positions).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from src.backtest.costs import CostModel, build_cost_model, cost_slice
from src.core.types import AccountState, Candle
from src.domain.canonical import sha256_hex
from src.domain.registry import ParameterSet
from src.paper.loop import BarContext
from src.risk.portfolio import RATE_THRESHOLD_KEYS, resolve_absolute_thresholds
from src.risk.types import ConstraintSnapshot, OpenPosition

REPLAY_INPUTS_SCHEMA = "paper-replay-inputs/2"
_LEGACY_REPLAY_INPUTS_SCHEMA = "paper-replay-inputs/1"  # read-only: thresholds = rates x equity
HISTORY_LOG_SCHEMA = "paper-history-bars/1"
_CONTEXT_DIGEST_SCHEMA = "paper-context/1"
_WINDOW_DIGEST_SCHEMA = "paper-window/1"

_ONE_SECOND = timedelta(seconds=1)


class ReplayInputsError(ValueError):
    """A recorded replay-inputs or history payload is unreadable or inconsistent."""


# --------------------------------------------------------------------------- #
# Canonical forms (Decimal as text, instants as UTC ISO text; no float).
# --------------------------------------------------------------------------- #


def _instant_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def bar_form(candle: Candle) -> dict[str, str]:
    """The canonical form of one candle, as the heartbeat payload spells its `bar`."""
    return {
        "symbol": candle.symbol,
        "interval": candle.interval,
        "open_time_utc": _instant_text(candle.open_time_utc),
        "close_time_utc": _instant_text(candle.close_time_utc),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
    }


def _constraint_form(snapshot: ConstraintSnapshot) -> dict[str, str]:
    return {
        "symbol": snapshot.symbol,
        "price_tick_size": str(snapshot.price_tick_size),
        "quantity_step_size": str(snapshot.quantity_step_size),
        "min_quantity": str(snapshot.min_quantity),
        "min_notional": str(snapshot.min_notional),
        "metadata_observed_at_utc": _instant_text(snapshot.metadata_observed_at_utc),
    }


def _account_form(account: AccountState) -> dict[str, str]:
    return {"equity": str(account.equity), "risk_rate": str(account.risk_rate)}


def _position_form(position: OpenPosition) -> dict[str, str]:
    return {
        "symbol": position.symbol,
        "position_side": position.position_side,
        "open_risk": str(position.open_risk),
        "daily_pnl_contribution": str(position.daily_pnl_contribution),
    }


def _cost_model_form(model: CostModel) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in dataclasses.fields(model):
        value = getattr(model, item.name)
        out[item.name] = str(value) if isinstance(value, Decimal) else value
    return out


def _loss_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _thresholds_form(context: BarContext) -> dict[str, str]:
    """The four resolved absolute thresholds the risk stage read, as Decimal text (fail closed)."""
    form: dict[str, str] = {}
    for key in RATE_THRESHOLD_KEYS:
        value = context.absolute_thresholds.get(key)
        if not isinstance(value, Decimal):
            raise ReplayInputsError(f"absolute_thresholds.{key}: missing or not a Decimal")
        form[key] = str(value)
    return form


def _ttl_seconds(ttl: timedelta) -> int:
    if ttl % _ONE_SECOND != timedelta(0):
        raise ReplayInputsError(f"ttl {ttl!r} is not a whole number of seconds (fail closed)")
    return ttl // _ONE_SECOND


def context_digest(context: BarContext) -> str:
    """SHA-256 over the canonical form of every field of a `BarContext`."""
    return sha256_hex(
        {
            "schema": _CONTEXT_DIGEST_SCHEMA,
            "symbol": context.symbol,
            "strategy_version": context.strategy_version,
            "parameter_set_hash": context.parameter_set.parameter_set_hash,
            "account_state": _account_form(context.account_state),
            "constraint_snapshot": _constraint_form(context.constraint_snapshot),
            "cost_model": _cost_model_form(context.cost_model),
            "open_positions": [_position_form(p) for p in context.open_positions],
            "daily_loss_quote": _loss_text(context.daily_loss_quote),
            "ttl_seconds": _ttl_seconds(context.ttl),
            "absolute_thresholds": context.absolute_thresholds,
        }
    )


def window_digest(bars: Sequence[Candle]) -> str:
    """SHA-256 over the canonical bars of a window, in order."""
    return sha256_hex({"schema": _WINDOW_DIGEST_SCHEMA, "bars": [bar_form(c) for c in bars]})


# --------------------------------------------------------------------------- #
# PAPER_REPLAY_INPUTS.
# --------------------------------------------------------------------------- #


def replay_inputs_payload(
    context: BarContext,
    *,
    setup_window: Sequence[Candle],
    context_window: Sequence[Candle],
    window_accept_seq: int,
) -> dict[str, Any]:
    """The payload of the replay-inputs record of one evaluated bar (see the module docstring).

    Raises:
        ReplayInputsError: the ttl is not a whole number of seconds, or a threshold is not a
            Decimal (fail closed).
    """
    if isinstance(window_accept_seq, bool) or window_accept_seq < 0:
        raise ReplayInputsError("window_accept_seq must be a non-negative integer")
    return {
        "schema": REPLAY_INPUTS_SCHEMA,
        "strategy_version": context.strategy_version,
        "parameter_set_hash": context.parameter_set.parameter_set_hash,
        "cost_model_hash": context.cost_model.cost_model_hash,
        "constraint_snapshot": _constraint_form(context.constraint_snapshot),
        "account_state": _account_form(context.account_state),
        "absolute_thresholds": _thresholds_form(context),
        "open_positions": [_position_form(p) for p in context.open_positions],
        "daily_loss_quote": _loss_text(context.daily_loss_quote),
        "ttl_seconds": _ttl_seconds(context.ttl),
        "window_accept_seq": window_accept_seq,
        "context_digest": context_digest(context),
        "setup_window_digest": window_digest(setup_window),
        "context_window_digest": window_digest(context_window),
    }


def _mapping(value: object, group: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayInputsError(f"{group}: an entry is not an object")
    return value


def _group(payload: object, key: str, group: str) -> Mapping[str, Any]:
    value = payload.get(key) if isinstance(payload, Mapping) else None
    if not isinstance(value, Mapping):
        raise ReplayInputsError(f"{group}: missing or not an object")
    return value


def _text(mapping: Mapping[str, Any], key: str, group: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or value == "":
        raise ReplayInputsError(f"{group}.{key}: missing or not text")
    return value


def _decimal(mapping: Mapping[str, Any], key: str, group: str) -> Decimal:
    raw = _text(mapping, key, group)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ReplayInputsError(f"{group}.{key}: not a decimal") from None
    if not value.is_finite():
        raise ReplayInputsError(f"{group}.{key}: not finite")
    return value


def _instant(mapping: Mapping[str, Any], key: str, group: str) -> datetime:
    raw = _text(mapping, key, group)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise ReplayInputsError(f"{group}.{key}: not an ISO time") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReplayInputsError(f"{group}.{key}: not UTC-aware")
    return value.astimezone(UTC)


def _whole(mapping: Mapping[str, Any], key: str, group: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplayInputsError(f"{group}.{key}: missing or not a non-negative integer")
    return value


def window_accept_seq_of(payload: Mapping[str, Any]) -> int:
    """The recorded cut point of a replay-inputs payload."""
    return _whole(payload, "window_accept_seq", "replay_inputs")


def _rebuild_thresholds(
    payload: Mapping[str, Any], parameter_set: ParameterSet, account_state: AccountState
) -> dict[str, Any]:
    """The absolute thresholds of a recorded bar: the /2 group, else the /1 derivation."""
    if payload.get("schema") != REPLAY_INPUTS_SCHEMA:
        return resolve_absolute_thresholds(
            parameter_set=parameter_set.params, equity=account_state.equity
        )
    group = _group(payload, "absolute_thresholds", "absolute_thresholds")
    if set(group) != set(RATE_THRESHOLD_KEYS):
        raise ReplayInputsError(
            f"absolute_thresholds: must hold exactly {sorted(RATE_THRESHOLD_KEYS)}"
        )
    thresholds = dict(parameter_set.params)
    for key in RATE_THRESHOLD_KEYS:
        thresholds[key] = _decimal(group, key, "absolute_thresholds")
    return thresholds


def rebuild_context(
    payload: Mapping[str, Any], *, symbol: str, parameter_set: ParameterSet
) -> BarContext:
    """Rebuild the `BarContext` of a recorded bar WITHOUT checking any hash or digest.

    The derivation is the one `make_context_factory` uses: the cost model from the registry slice of
    the set. The absolute thresholds of a /2 record are the recorded group (the ledger's day-start
    thresholds the risk stage read, 16-DEC-EQUITY-BASE); a /1 record keeps the derivation that wrote
    it, the set's rates times the recorded equity. Use `context_from_inputs` to rebuild and verify.

    Raises:
        ReplayInputsError: a field group is missing or malformed.
    """
    constraint = _group(payload, "constraint_snapshot", "constraint_snapshot")
    account = _group(payload, "account_state", "account_state")
    positions = payload.get("open_positions")
    if not isinstance(positions, (list, tuple)):
        raise ReplayInputsError("open_positions: missing or not a list")
    try:
        snapshot = ConstraintSnapshot(
            symbol=_text(constraint, "symbol", "constraint_snapshot"),
            price_tick_size=_decimal(constraint, "price_tick_size", "constraint_snapshot"),
            quantity_step_size=_decimal(constraint, "quantity_step_size", "constraint_snapshot"),
            min_quantity=_decimal(constraint, "min_quantity", "constraint_snapshot"),
            min_notional=_decimal(constraint, "min_notional", "constraint_snapshot"),
            metadata_observed_at_utc=_instant(
                constraint, "metadata_observed_at_utc", "constraint_snapshot"
            ),
        )
        account_state = AccountState(
            equity=_decimal(account, "equity", "account_state"),
            risk_rate=_decimal(account, "risk_rate", "account_state"),
        )
        open_positions = tuple(
            OpenPosition(
                symbol=_text(item, "symbol", "open_positions"),
                position_side=_text(item, "position_side", "open_positions"),
                open_risk=_decimal(item, "open_risk", "open_positions"),
                daily_pnl_contribution=_decimal(item, "daily_pnl_contribution", "open_positions"),
            )
            for item in (_mapping(i, "open_positions") for i in positions)
        )
        loss_raw = payload.get("daily_loss_quote")
        daily_loss = None if loss_raw is None else _decimal(payload, "daily_loss_quote", "context")
        ttl = timedelta(seconds=_whole(payload, "ttl_seconds", "replay_inputs"))
        cost_model = build_cost_model(cost_slice(parameter_set.params))
        thresholds = _rebuild_thresholds(payload, parameter_set, account_state)
    except ReplayInputsError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise ReplayInputsError(f"the recorded inputs cannot form a context: {exc}") from None
    return BarContext(
        symbol=symbol,
        strategy_version=_text(payload, "strategy_version", "replay_inputs"),
        parameter_set=parameter_set,
        account_state=account_state,
        constraint_snapshot=snapshot,
        cost_model=cost_model,
        open_positions=open_positions,
        daily_loss_quote=daily_loss,
        ttl=ttl,
        absolute_thresholds=thresholds,
    )


def context_from_inputs(
    payload: Mapping[str, Any], *, symbol: str, parameter_set: ParameterSet
) -> BarContext:
    """Rebuild the `BarContext` of a recorded bar and verify it against the record.

    Raises:
        ReplayInputsError: the schema, the parameter set hash, the cost model hash or the
            recomputed `context_digest` differs from the record (the message names the group).
    """
    if payload.get("schema") not in (REPLAY_INPUTS_SCHEMA, _LEGACY_REPLAY_INPUTS_SCHEMA):
        raise ReplayInputsError(
            f"schema is not {REPLAY_INPUTS_SCHEMA!r} or {_LEGACY_REPLAY_INPUTS_SCHEMA!r}"
        )
    if payload.get("parameter_set_hash") != parameter_set.parameter_set_hash:
        raise ReplayInputsError("parameter_set_hash differs from the registry set")
    context = rebuild_context(payload, symbol=symbol, parameter_set=parameter_set)
    if payload.get("cost_model_hash") != context.cost_model.cost_model_hash:
        raise ReplayInputsError("cost_model_hash differs from the registry set's cost model")
    if payload.get("context_digest") != context_digest(context):
        raise ReplayInputsError(
            "context_digest differs: a recorded input was changed or is inconsistent"
        )
    return context


# --------------------------------------------------------------------------- #
# PAPER_HISTORY_BARS.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HistoryEntry:
    """One bar the pipeline accepted into its history, with its acceptance sequence.

    `fetched_for_close_utc` is set on a fetched 4h sibling: the close of the 1h bar it was
    fetched for (it is accepted right after that bar and before the windows are cut).
    """

    accept_seq: int
    source: str
    candle: Candle
    fetched_for_close_utc: datetime | None = None


def history_log_payload(entries: Sequence[HistoryEntry], *, history_seq: int) -> dict[str, Any]:
    """The payload of one history record: the entries in acceptance order."""
    if isinstance(history_seq, bool) or history_seq < 0:
        raise ReplayInputsError("history_seq must be a non-negative integer")
    return {
        "schema": HISTORY_LOG_SCHEMA,
        "history_seq": history_seq,
        "entries": [
            {
                "accept_seq": entry.accept_seq,
                "source": entry.source,
                **bar_form(entry.candle),
                "fetched_for_close_utc": (
                    None
                    if entry.fetched_for_close_utc is None
                    else _instant_text(entry.fetched_for_close_utc)
                ),
            }
            for entry in entries
        ],
    }


def candle_from_form(form: Mapping[str, Any], group: str) -> Candle:
    """A `Candle` from its canonical form (`bar_form`)."""
    try:
        return Candle(
            symbol=_text(form, "symbol", group),
            interval=_text(form, "interval", group),
            open_time_utc=_instant(form, "open_time_utc", group),
            close_time_utc=_instant(form, "close_time_utc", group),
            open=_decimal(form, "open", group),
            high=_decimal(form, "high", group),
            low=_decimal(form, "low", group),
            close=_decimal(form, "close", group),
            volume=_decimal(form, "volume", group),
        )
    except ReplayInputsError:
        raise
    except (ValueError, TypeError) as exc:
        raise ReplayInputsError(f"{group}: not a candle: {exc}") from None


def parse_history_payload(payload: Mapping[str, Any]) -> tuple[HistoryEntry, ...]:
    """The entries of one history record.

    Raises:
        ReplayInputsError: the schema is wrong or an entry is unreadable.
    """
    if payload.get("schema") != HISTORY_LOG_SCHEMA:
        raise ReplayInputsError(f"schema is not {HISTORY_LOG_SCHEMA!r}")
    raw = payload.get("entries")
    if not isinstance(raw, (list, tuple)):
        raise ReplayInputsError("entries: missing or not a list")
    entries: list[HistoryEntry] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ReplayInputsError("entries: an entry is not an object")
        fetched = item.get("fetched_for_close_utc")
        entries.append(
            HistoryEntry(
                accept_seq=_whole(item, "accept_seq", "entries"),
                source=_text(item, "source", "entries"),
                candle=candle_from_form(item, "entries"),
                fetched_for_close_utc=(
                    None if fetched is None else _instant(item, "fetched_for_close_utc", "entries")
                ),
            )
        )
    return tuple(entries)


__all__ = [
    "HISTORY_LOG_SCHEMA",
    "REPLAY_INPUTS_SCHEMA",
    "HistoryEntry",
    "ReplayInputsError",
    "bar_form",
    "candle_from_form",
    "context_digest",
    "context_from_inputs",
    "history_log_payload",
    "parse_history_payload",
    "rebuild_context",
    "replay_inputs_payload",
    "window_accept_seq_of",
    "window_digest",
]
