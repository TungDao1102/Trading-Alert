"""The Phase 19 execution limits and their fail-closed loader (plan 19-01; D-07, D-13).

No number lives in this module. The eighteen required safety keys (seven of Phase 19, seven of
Phase 20, one of Phase 21, three of Phase 22; fourteen of them still without a number the owner
has chosen: the owner set the Phase 21 key by D084 and the three Phase 22 keys by D085) are
optional fields of a frozen dataclass that default to nothing: they reach the
process only through ``config/execution/execution-limits-v1.toml``, where each value is the word
``NOT_CONFIGURED`` until the owner sets it (OWNER-OPEN O-04). While any field is ``None`` the
live path refuses:
``ExecutionLimits.require_live_ready`` raises ``ExecutionLimitsNotConfigured`` naming the unset
keys. One further key (plan 20-28,
``reconcile.entry_stale_grace_ms``) only switches an alert on: it is an ALERT-ONLY key, loaded and
validated like the others but left out of ``unset_keys`` and ``require_live_ready``, so while it is
``NOT_CONFIGURED`` only that one check is skipped. A further key (plan 24-03, DECISIONS D083 item 4,
``rest_gate.ban_end_clock_margin_ms``) is an OPTIONAL REFINEMENT: unset, the 418 ban keeps the
fallback wait and nothing else changes, so it too is left out of ``unset_keys`` and
``require_live_ready`` and is listed by ``unset_optional_refinement_keys``; no number is chosen for
it. A last key (quick task 261114-mp1, DECISIONS D111, ``scheduler.protection_stall_after_ms``)
is a second ALERT-ONLY key: unset, the observe-only stall watchdog of the protection task is off
and nothing else changes; no number is chosen for it. ``tests/test_no_unratified_defaults.py``
scans ``src``
and ``scripts`` so that no numeric default for these names ever appears.

The file is separate from ``config/binance/binance-limits-v1.toml``: that file is sha256-pinned
by a DECISIONS row and its loader demands exactly 27 keys, so it is not extended.

The file format (``config/execution/README.md``):

* exactly the sections ``protection``, ``pre_placement``, ``reconcile``, ``stale_feed``,
  ``alerts``, ``account``, ``margin``, ``rest_gate``, ``scheduler`` and
  ``provenance`` (plan 20-01 adds
  ``reconcile``, ``stale_feed`` and ``alerts``, D-25; plan 21-02 adds ``account``, D-03; plan 22-02
  adds ``margin``, D-10, D-11, D-13; plan 24-03 adds ``rest_gate``, D083; quick 261114-mp1 adds
  ``scheduler``, D111);
* exactly the keys of ``EXECUTION_LIMIT_KEYS``; a missing or unknown key refuses to load;
* each value is a positive integer (not a boolean, not a float, not zero) or exactly the
  string ``NOT_CONFIGURED`` (read as ``None``);
* ``provenance.<section>.<key>`` gives every key a label: ``NOT_CONFIGURED`` for an unset value,
  one of STRUCTURAL, COST_GUARD, DECISION or EXPERIMENT for an integer. A PLACEHOLDER, unknown
  or absent label refuses to load: no placeholder number is a decision.

Every refusal raises ``ExecutionLimitsInvalid`` (``ExecutionLimitsFileMissing`` for a missing
file) with a message that names keys or sections only: never a value and never a path.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

NOT_CONFIGURED_WORD = "NOT_CONFIGURED"

EXECUTION_LIMIT_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "protection": (
            "max_unprotected_ms",
            "entry_terminal_timeout_ms",
            "entry_unknown_grace_ms",
            "emergency_close_poll_timeout_ms",
        ),
        "pre_placement": (
            "min_remaining_validity_seconds",
            "max_mark_price_age_ms",
            "max_last_price_age_ms",
        ),
        "reconcile": (
            "tick_interval_ms",
            "entry_unknown_probe_count",
            "entry_unknown_probe_interval_ms",
            "lot_filter_refresh_interval_ms",
            "entry_stale_grace_ms",
        ),
        "stale_feed": ("max_mark_price_age_ms", "max_user_data_silence_ms"),
        "alerts": ("dedupe_window_ms",),
        "account": ("max_equity_age_ms", "max_daily_loss_age_ms"),
        "margin": ("liquidation_buffer_bps", "max_bracket_age_ms", "headroom_bps"),
        "rest_gate": ("ban_end_clock_margin_ms",),
        "scheduler": ("protection_stall_after_ms",),
    }
)

# The dotted key -> the ExecutionLimits field name. This is the only place the mapping lives.
# The seven Phase 19 keys keep the field name equal to the key text (their consumers read
# ``limits.max_unprotected_ms`` and so on). Every Phase 20 key is ``<section>_<key>``, because
# ``stale_feed.max_mark_price_age_ms`` shares its key text with
# ``pre_placement.max_mark_price_age_ms`` (plan 20-01; D-25, T-H). The Phase 21 key follows the same
# ``<section>_<key>`` rule (plan 21-02; D-03), and so do the three Phase 22 keys (plan 22-02).
EXECUTION_LIMIT_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        "protection.max_unprotected_ms": "max_unprotected_ms",
        "protection.entry_terminal_timeout_ms": "entry_terminal_timeout_ms",
        "protection.entry_unknown_grace_ms": "entry_unknown_grace_ms",
        "protection.emergency_close_poll_timeout_ms": "emergency_close_poll_timeout_ms",
        "pre_placement.min_remaining_validity_seconds": "min_remaining_validity_seconds",
        "pre_placement.max_mark_price_age_ms": "max_mark_price_age_ms",
        "pre_placement.max_last_price_age_ms": "max_last_price_age_ms",
        "reconcile.tick_interval_ms": "reconcile_tick_interval_ms",
        "reconcile.entry_unknown_probe_count": "reconcile_entry_unknown_probe_count",
        "reconcile.entry_unknown_probe_interval_ms": "reconcile_entry_unknown_probe_interval_ms",
        "reconcile.lot_filter_refresh_interval_ms": "reconcile_lot_filter_refresh_interval_ms",
        "reconcile.entry_stale_grace_ms": "reconcile_entry_stale_grace_ms",
        "stale_feed.max_mark_price_age_ms": "stale_feed_max_mark_price_age_ms",
        "stale_feed.max_user_data_silence_ms": "stale_feed_max_user_data_silence_ms",
        "alerts.dedupe_window_ms": "alerts_dedupe_window_ms",
        "account.max_equity_age_ms": "account_max_equity_age_ms",
        "account.max_daily_loss_age_ms": "account_max_daily_loss_age_ms",
        "margin.liquidation_buffer_bps": "margin_liquidation_buffer_bps",
        "margin.max_bracket_age_ms": "margin_max_bracket_age_ms",
        "margin.headroom_bps": "margin_headroom_bps",
        "rest_gate.ban_end_clock_margin_ms": "rest_gate_ban_end_clock_margin_ms",
        "scheduler.protection_stall_after_ms": "scheduler_protection_stall_after_ms",
    }
)

# The keys that only switch an ALERT on (plan 20-28). While one is NOT_CONFIGURED the alert's
# check is skipped and says so; the key never keeps the live path refused (`unset_keys` and
# `require_live_ready` leave it out, `unset_alert_only_keys` lists it). It is still loaded,
# validated and given a provenance label like every other key, and no number is chosen for it.
# `scheduler.protection_stall_after_ms` (quick 261114-mp1, D111): unset, the observe-only stall
# watchdog of the protection task is off and nothing else changes; no number is chosen.
ALERT_ONLY_LIMIT_KEYS: frozenset[str] = frozenset(
    {"reconcile.entry_stale_grace_ms", "scheduler.protection_stall_after_ms"}
)

# The keys that only REFINE a behaviour that already has a safe fallback (plan 24-03, D083 item 4).
# While one is NOT_CONFIGURED the fallback applies (here: the 418 ban keeps its ratified fallback
# wait); the key never keeps the live path refused (`unset_keys` and `require_live_ready` leave it
# out, `unset_optional_refinement_keys` lists it). It is still loaded, validated and given a
# provenance label like every other key, and no number is chosen for it: the owner sets it
# (OWNER-OPEN O-1, plan 24-06).
OPTIONAL_REFINEMENT_LIMIT_KEYS: frozenset[str] = frozenset({"rest_gate.ban_end_clock_margin_ms"})

PROVENANCE_SECTION = "provenance"
ALLOWED_SECTIONS: frozenset[str] = frozenset((*EXECUTION_LIMIT_KEYS, PROVENANCE_SECTION))
PROJECT_PROVENANCE_LABELS: frozenset[str] = frozenset(
    {"STRUCTURAL", "COST_GUARD", "DECISION", "EXPERIMENT"}
)
ALLOWED_PROVENANCE_LABELS: frozenset[str] = PROJECT_PROVENANCE_LABELS | {NOT_CONFIGURED_WORD}


# --------------------------------------------------------------------------- #
# Errors.
# --------------------------------------------------------------------------- #


class ExecutionLimitsInvalid(Exception):
    """The limits file is unreadable or malformed; the message names keys or sections only."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("execution limits invalid: " + "; ".join(self.problems))


class ExecutionLimitsFileMissing(ExecutionLimitsInvalid):
    """The execution-limits file does not exist."""


class ExecutionLimitsNotConfigured(Exception):
    """At least one limit is NOT_CONFIGURED; the live path must refuse (names keys only)."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = tuple(keys)
        super().__init__("execution limits not configured: " + ", ".join(self.keys))


# --------------------------------------------------------------------------- #
# The structure. Every field is required and keyword-only; none has a default.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class ExecutionLimits:
    """The twenty-two execution limits; ``None`` means NOT_CONFIGURED (the owner has not chosen).

    ``max_unprotected_ms`` (D-13): the longest tolerated time an entry fill is open without a
    protective stop. ``entry_terminal_timeout_ms`` (D-13): how long the entry order may stay
    non-terminal. ``entry_unknown_grace_ms`` (19-REVIEW WR-05, owner): how long past the GTD
    time of an entry left ENTRY_STATE_UNKNOWN (Q5) the protection coordinator keeps polling it
    at full frequency before it marks the entry unresolved and polls it only every Nth step.
    ``emergency_close_poll_timeout_ms`` (19-REVIEW WR-03, owner): how long the emergency closer
    keeps polling a sent reduce-only MARKET close that is not terminal yet before it holds the
    close as unknown and raises one critical alert; it never sends an overlapping close to
    shorten the wait, and it is separate from ``max_unprotected_ms``.
    ``min_remaining_validity_seconds`` (D-07): the minimum remaining plan
    validity at placement. ``max_mark_price_age_ms`` (D-07): the maximum age of the mark
    price the price check uses. ``max_last_price_age_ms`` (D-07, quick task 261020-l4p, the
    19-REVIEW WR-06 work item): the maximum age of the last price the last-price check uses; it
    is separate from the mark bound because the last price moves only on a trade.
    ``reconcile_tick_interval_ms`` (plan 20-01, D-25, T-H): the cadence of the reconcile loop that
    replaces the hard-coded SAFE_MODE tick; it must stay strictly below ``max_unprotected_ms``.
    ``reconcile_entry_unknown_probe_count`` and ``reconcile_entry_unknown_probe_interval_ms``
    (D-11, consumer plan 20-10): how many consecutive clean not-found probes of an UNKNOWN
    entry are needed before it may close, and the spacing between them.
    ``reconcile_lot_filter_refresh_interval_ms`` (D-21, consumer plan 20-21): how often the
    lot-size filters are refreshed. ``stale_feed_max_mark_price_age_ms`` (D-25, consumer plan
    20-16): the maximum mark-price age before the feed counts as stale; it is not
    ``max_mark_price_age_ms`` of the pre-placement check. ``stale_feed_max_user_data_silence_ms``
    (D-25, D058, plan 20-16): the maximum silence of the user-data stream; it is not the paper
    runtime key ``max_ws_message_silence_seconds`` and never reuses it.
    ``alerts_dedupe_window_ms`` (D-23, consumer plan 20-13): the window in which a repeated alert
    is deduplicated. The Phase 20 fields are named ``<section>_<key>`` (``EXECUTION_LIMIT_FIELDS``).
    ``reconcile_entry_stale_grace_ms`` (plan 20-28, owner request 2026-10-23): how long past the
    ``goodTillDate`` of a resting entry the reconcile loop waits before it alerts that Binance did
    not expire it (alert only). It is an ALERT-ONLY key (``ALERT_ONLY_LIMIT_KEYS``): unset, it
    disables that one check and nothing else.
    ``account_max_equity_age_ms`` (plan 21-02, D-03, F-012; the owner set 15000 on 2026-10-23,
    DECISIONS D084): the maximum age, in milliseconds, of the account equity reading used for
    live sizing, for the daily-loss day-start base and for the approval reservation gate. The age
    is the injected now minus the injected clock reading taken before the REST request, so it is
    only over-estimated; an age greater than this value, or negative, is stale (NO_TRADE
    UNCERTAIN_ACCOUNT_STATE), and an age exactly equal to it passes. It is a REQUIRED key: it is
    not in ``ALERT_ONLY_LIMIT_KEYS``, so while it is unset the live path refuses.
    ``account_max_daily_loss_age_ms`` (Phase 21 review WR-05; the owner set 300000 on 2026-10-25,
    DECISIONS D087): the maximum age, in milliseconds, of a known daily loss, counted from the
    completed backfill that made it known. An older loss, or a stamp dated in the future, is
    unknown (NO_TRADE); an age exactly equal to it passes. REQUIRED, not alert-only.
    ``margin_liquidation_buffer_bps`` (plan 22-02, D-09, D-10, OWNER-OPEN O-2): the liquidation
    buffer, in basis points of the ENTRY price; the margin guard compares it as a price distance
    beyond the stop. ``margin_max_bracket_age_ms`` (plan 22-02, D-11, OWNER-OPEN O-3): the
    maximum age, in milliseconds, of the cached leverage-bracket set. ``margin_headroom_bps``
    (plan 22-02, D-13, OWNER-OPEN O-3): the headroom, in basis points of the margin the order
    needs, that the available balance must keep. All three are positive integers only
    (amendment A4) and REQUIRED (not in ``ALERT_ONLY_LIMIT_KEYS``). The owner set them on
    2026-10-24 (DECISIONS D085), provenance DECISION, in the values file. No number is chosen
    here, and the consumers (plans 22-12, 22-13 and 22-14)
    read them from a loaded object. With the three margin keys and the daily-loss age the file
    held twenty keys, nineteen required and one alert-only.
    ``rest_gate_ban_end_clock_margin_ms`` (plan 24-03, DECISIONS D083 item 4): the clock-difference
    margin, in milliseconds, added to the ban end time read from a 418 / -1003 body. It is an
    OPTIONAL REFINEMENT key (``OPTIONAL_REFINEMENT_LIMIT_KEYS``): unset, the body time is not used
    and the ratified 418 fallback wait applies. ``rest_gate_ban_end_clock_margin`` gives it as a
    ``timedelta``.
    ``scheduler_protection_stall_after_ms`` (quick task 261114-mp1, DECISIONS D111): the longest
    time, in milliseconds, one run of the protection task may take before the observe-only stall
    watchdog records a stall (a journal row and the TASK_STALLED alert); the run itself is never
    cancelled. It is an ALERT-ONLY key (``ALERT_ONLY_LIMIT_KEYS``): unset, the watchdog is off and
    nothing else changes. ``scheduler_protection_stall_after`` gives it as a ``timedelta``. The file
    holds twenty-two keys: nineteen required, two alert-only, one optional.
    """

    max_unprotected_ms: int | None
    entry_terminal_timeout_ms: int | None
    entry_unknown_grace_ms: int | None
    emergency_close_poll_timeout_ms: int | None
    min_remaining_validity_seconds: int | None
    max_mark_price_age_ms: int | None
    max_last_price_age_ms: int | None
    reconcile_tick_interval_ms: int | None
    reconcile_entry_unknown_probe_count: int | None
    reconcile_entry_unknown_probe_interval_ms: int | None
    reconcile_lot_filter_refresh_interval_ms: int | None
    stale_feed_max_mark_price_age_ms: int | None
    stale_feed_max_user_data_silence_ms: int | None
    alerts_dedupe_window_ms: int | None
    reconcile_entry_stale_grace_ms: int | None
    account_max_equity_age_ms: int | None
    account_max_daily_loss_age_ms: int | None
    margin_liquidation_buffer_bps: int | None
    margin_max_bracket_age_ms: int | None
    margin_headroom_bps: int | None
    rest_gate_ban_end_clock_margin_ms: int | None
    scheduler_protection_stall_after_ms: int | None

    @property
    def rest_gate_ban_end_clock_margin(self) -> timedelta | None:
        """The D083 clock margin as a ``timedelta``, or None while it is NOT_CONFIGURED."""
        value = self.rest_gate_ban_end_clock_margin_ms
        return None if value is None else timedelta(milliseconds=value)

    @property
    def scheduler_protection_stall_after(self) -> timedelta | None:
        """The D111 stall bound as a ``timedelta``, or None while it is NOT_CONFIGURED."""
        value = self.scheduler_protection_stall_after_ms
        return None if value is None else timedelta(milliseconds=value)

    def _unset(self, group: frozenset[str] | None) -> tuple[str, ...]:
        """The unset keys of one group: the required keys when ``group`` is None."""
        return tuple(
            dotted
            for section, keys in EXECUTION_LIMIT_KEYS.items()
            for key in keys
            for dotted in (f"{section}.{key}",)
            if (
                dotted in group
                if group is not None
                else dotted not in ALERT_ONLY_LIMIT_KEYS | OPTIONAL_REFINEMENT_LIMIT_KEYS
            )
            and getattr(self, EXECUTION_LIMIT_FIELDS[dotted]) is None
        )

    def unset_keys(self) -> tuple[str, ...]:
        """The dotted names of the REQUIRED keys still NOT_CONFIGURED, in the fixed file order.

        The alert-only keys (``ALERT_ONLY_LIMIT_KEYS``) and the optional refinement keys
        (``OPTIONAL_REFINEMENT_LIMIT_KEYS``) are not listed here: they never keep the live path
        refused. See ``unset_alert_only_keys`` and ``unset_optional_refinement_keys``.
        """
        return self._unset(None)

    def unset_alert_only_keys(self) -> tuple[str, ...]:
        """The dotted names of the alert-only keys still NOT_CONFIGURED, in file order."""
        return self._unset(ALERT_ONLY_LIMIT_KEYS)

    def unset_optional_refinement_keys(self) -> tuple[str, ...]:
        """The dotted names of the optional refinement keys still NOT_CONFIGURED, in file order."""
        return self._unset(OPTIONAL_REFINEMENT_LIMIT_KEYS)

    def require_live_ready(self) -> None:
        """Refuse while any limit is unset.

        Raises:
            ExecutionLimitsNotConfigured: naming every unset key (never a value).
        """
        unset = self.unset_keys()
        if unset:
            raise ExecutionLimitsNotConfigured(unset)


# --------------------------------------------------------------------------- #
# The loader.
# --------------------------------------------------------------------------- #

_INVALID = object()


def _table(raw: Mapping[str, Any], name: str, problems: list[str]) -> Mapping[str, Any]:
    if name not in raw:
        return {}
    section = raw[name]
    if not isinstance(section, dict):
        problems.append(f"{name} (must be a table)")
        return {}
    return section


def _read_value(section: Mapping[str, Any], dotted: str, key: str, problems: list[str]) -> Any:
    """The validated int, None (NOT_CONFIGURED) or the _INVALID marker after a problem."""
    if key not in section:
        problems.append(f"{dotted} (missing key)")
        return _INVALID
    value = section[key]
    if isinstance(value, str):
        if value == NOT_CONFIGURED_WORD:
            return None
        problems.append(f"{dotted} (must be a positive integer or the word {NOT_CONFIGURED_WORD})")
        return _INVALID
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{dotted} (must be an integer, not a boolean or a float)")
        return _INVALID
    if value <= 0:
        problems.append(f"{dotted} (must be a positive integer)")
        return _INVALID
    return value


def _check_label(dotted: str, value: object, label: object, problems: list[str]) -> None:
    if label == "PLACEHOLDER":
        problems.append(f"{dotted} (provenance PLACEHOLDER refuses to load)")
    elif not isinstance(label, str) or label not in ALLOWED_PROVENANCE_LABELS:
        problems.append(
            f"{dotted} (provenance label must be one of "
            + ", ".join(sorted(ALLOWED_PROVENANCE_LABELS))
            + ")"
        )
    elif value is _INVALID:
        return
    elif value is None and label != NOT_CONFIGURED_WORD:
        problems.append(f"{dotted} (an unset value needs provenance {NOT_CONFIGURED_WORD})")
    elif value is not None and label == NOT_CONFIGURED_WORD:
        problems.append(f"{dotted} (a set value cannot carry provenance {NOT_CONFIGURED_WORD})")


def _check_provenance(
    raw: Mapping[str, Any], values: Mapping[str, Mapping[str, object]], problems: list[str]
) -> None:
    if PROVENANCE_SECTION not in raw:
        problems.append(f"{PROVENANCE_SECTION} (missing table: every key needs a label)")
        return
    provenance = _table(raw, PROVENANCE_SECTION, problems)
    for section in sorted(set(provenance) - set(EXECUTION_LIMIT_KEYS)):
        problems.append(f"{PROVENANCE_SECTION}.{section} (unknown section)")
    for section, keys in EXECUTION_LIMIT_KEYS.items():
        labels = provenance.get(section, {})
        if not isinstance(labels, dict):
            problems.append(f"{PROVENANCE_SECTION}.{section} (must be a table)")
            labels = {}
        for key in sorted(set(labels) - set(keys)):
            problems.append(f"{PROVENANCE_SECTION}.{section}.{key} (unknown key)")
        for key in keys:
            dotted = f"{section}.{key}"
            if key not in labels:
                problems.append(f"{dotted} (missing provenance label)")
                continue
            _check_label(dotted, values[section][key], labels[key], problems)


def parse_execution_limits(raw: Mapping[str, Any]) -> ExecutionLimits:
    """Validate a parsed TOML document; every key is required and nothing else is allowed.

    Raises:
        ExecutionLimitsInvalid: naming every missing, unknown or invalid key or section.
    """
    problems: list[str] = []
    for section in sorted(set(raw) - ALLOWED_SECTIONS):
        problems.append(f"{section} (unknown section)")
    values: dict[str, dict[str, Any]] = {}
    for section, keys in EXECUTION_LIMIT_KEYS.items():
        body = _table(raw, section, problems)
        for key in sorted(set(body) - set(keys)):
            problems.append(f"{section}.{key} (unknown key)")
        values[section] = {
            key: _read_value(body, f"{section}.{key}", key, problems) for key in keys
        }
    _check_provenance(raw, values, problems)
    if problems:
        raise ExecutionLimitsInvalid(problems)

    flat: dict[str, Any] = {
        EXECUTION_LIMIT_FIELDS[f"{section}.{key}"]: value
        for section, body in values.items()
        for key, value in body.items()
    }
    return ExecutionLimits(**flat)


def load_execution_limits(path: Path | str) -> ExecutionLimits:
    """Load the execution-limits file. There is no default file and no default value.

    Raises:
        ExecutionLimitsFileMissing: the file does not exist (the message carries no path).
        ExecutionLimitsInvalid: the file is not valid TOML or any entry is missing or invalid.
    """
    file = Path(path)
    if not file.is_file():
        raise ExecutionLimitsFileMissing(["the execution limits file does not exist"])
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        raise ExecutionLimitsInvalid(["the execution limits file is not valid TOML"]) from None
    return parse_execution_limits(raw)


def check_reconcile_cadence(limits: ExecutionLimits) -> None:
    """Refuse a reconcile cadence that is not strictly below ``protection.max_unprotected_ms``.

    D-25: when both values are configured, ``reconcile.tick_interval_ms`` must be below
    ``protection.max_unprotected_ms``, otherwise a loop could not notice an unprotected position
    before its deadline. While either value is unset this does nothing: ``require_live_ready``
    refuses separately, and no default is chosen here so that the check can pass. The reconcile
    loop constructor calls it (plan 20-12); this module has no caller.

    Raises:
        ExecutionLimitsInvalid: naming both keys and neither value.
    """
    tick = limits.reconcile_tick_interval_ms
    deadline = limits.max_unprotected_ms
    if tick is None or deadline is None:
        return
    if tick >= deadline:
        raise ExecutionLimitsInvalid(
            ["reconcile.tick_interval_ms (must be strictly below protection.max_unprotected_ms)"]
        )


__all__ = [
    "ALERT_ONLY_LIMIT_KEYS",
    "ALLOWED_PROVENANCE_LABELS",
    "ALLOWED_SECTIONS",
    "EXECUTION_LIMIT_FIELDS",
    "EXECUTION_LIMIT_KEYS",
    "NOT_CONFIGURED_WORD",
    "OPTIONAL_REFINEMENT_LIMIT_KEYS",
    "PROJECT_PROVENANCE_LABELS",
    "ExecutionLimits",
    "ExecutionLimitsFileMissing",
    "ExecutionLimitsInvalid",
    "ExecutionLimitsNotConfigured",
    "check_reconcile_cadence",
    "load_execution_limits",
    "parse_execution_limits",
]
