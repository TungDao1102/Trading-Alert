# Execution protection, pre-placement and reconcile limits

This directory holds the nineteen safety limits of the execution path, eighteen required and one
alert-only (the owner has chosen the number of four of them: the equity age of Phase 21, D084, and the three margin keys of Phase 22, D085): the seven of Phase 19 (D-07, D-13, the owner's
19-REVIEW WR-05 and WR-03 decisions and the last-price check of quick task 261020-l4p), the eight
of Phase 20 (plan 20-01; D-25, D-11, D-21, D-23, T-H; plan 20-28 added the alert-only
`reconcile.entry_stale_grace_ms`) the one of Phase 21 (plan 21-02; D-03) and the three of Phase 22 (plan 22-02; D-10, D-11, D-13).
The values file
`execution-limits-v1.toml` holds the word `NOT_CONFIGURED` for every key until the owner fills the number in (four are filled), after the Demo probes
listed in `19-NOTES.md` (OWNER-OPEN O-04 and O-05).
**This README lists the required keys and what they mean. It carries no value, and the code
carries no default for any of them.** `tests/test_no_unratified_defaults.py` scans `src/` and
`scripts/` so that no key name below is ever given a number in code.

The loader is `load_execution_limits(path)` in `src/execution/execution_limits.py`. It returns
an `ExecutionLimits` whose nineteen fields are `None` while the file says `NOT_CONFIGURED`.
`ExecutionLimits.require_live_ready()` raises `ExecutionLimitsNotConfigured` naming the unset
keys, so the live path refuses while any key is `NOT_CONFIGURED` (the manager gate and the
coordinator check that call it are wired by later Phase 19 plans). The loader refuses to load,
with `ExecutionLimitsInvalid` (or `ExecutionLimitsFileMissing` when the file does not exist), a
file that is not valid TOML, a missing key, an unknown key, an unknown section, a value of the
wrong kind, or a missing or invalid provenance label. Refusal messages name keys or sections
only, never a value or a path.

## Separation from the Binance limits file

`config/binance/binance-limits-v1.toml` is ratified and pinned by sha256 in the DECISIONS row
of Phase 18, and its loader and README tests demand exactly the keys of that file. The nineteen keys
here therefore live in a separate file with a separate loader; the Binance file and its README
are not edited.

## File format

- Exactly the sections `[protection]`, `[pre_placement]`, `[reconcile]`, `[stale_feed]`,
  `[alerts]`, `[account]`, `[margin]` and `[provenance]`.
- Exactly the nineteen keys below, each written once; nothing else is accepted.
- Every value is a TOML integer that is not a boolean, strictly positive (a float, a boolean,
  zero or a negative number is refused), or exactly the TOML string `"NOT_CONFIGURED"`, which
  loads as `None` and means "the owner has not chosen yet". No other string is accepted.
- The `ExecutionLimits` field of a Phase 19 key is the key text (`max_unprotected_ms`); the field
  of a Phase 20, Phase 21 or Phase 22 key is `<section>_<key>` (`reconcile_tick_interval_ms`,
  `account_max_equity_age_ms`, `margin_headroom_bps`), because
  `stale_feed.max_mark_price_age_ms` shares its key text with `pre_placement.max_mark_price_age_ms`.
  `EXECUTION_LIMIT_FIELDS` in the loader is the only place that mapping lives.
- The key `entry_terminal_timeout_ms` carries the `_ms` suffix for unit clarity; D-13 names the
  concept as the entry terminal timeout and keeps `max_unprotected_ms` verbatim.

## Provenance table

Every key carries a provenance label in `[provenance]`, addressed as `section.key`. While a
value is unset its label is `NOT_CONFIGURED`. After the owner sets a number the label becomes
DECISION, and the change needs a new DECISIONS row. The other project labels (STRUCTURAL,
COST_GUARD, EXPERIMENT) are also accepted for a set value. A PLACEHOLDER label refuses to load,
and so does an absent, unknown or misspelled label or a label for an unknown key: no placeholder
number is a decision. A set value cannot carry the `NOT_CONFIGURED` label and an unset value
cannot carry any other.

## Required keys

One key per line, so the checks of plan 19-01 can parse the list.

### `[protection]` (D-13; the grace key comes from the owner's 19-REVIEW WR-05 decision, the close poll key from WR-03)

- `protection.max_unprotected_ms` - the longest tolerated time an entry fill is open without a protective stop before the fail-closed response starts (milliseconds).
- `protection.entry_terminal_timeout_ms` - how long the entry order may stay non-terminal before it is treated as a timeout (milliseconds).
- `protection.entry_unknown_grace_ms` - how long past the GTD time of an entry left `ENTRY_STATE_UNKNOWN` (Q5) the protection coordinator keeps polling it every step before it marks the entry unresolved and polls it only every Nth step; the entry stays tracked and SAFE_MODE stays in force (19-REVIEW WR-05, milliseconds).
- `protection.emergency_close_poll_timeout_ms` - how long the emergency closer keeps polling a sent reduce-only MARKET close that is not terminal yet before it holds the close as UNKNOWN, keeps SAFE_MODE and raises one critical alert; it never sends an overlapping close to shorten the wait, and it is a separate number from `protection.max_unprotected_ms` (19-REVIEW WR-03, milliseconds).

### `[pre_placement]` (D-07; the last-price key comes from quick task 261020-l4p, the 19-REVIEW WR-06 work item)

- `pre_placement.min_remaining_validity_seconds` - the minimum remaining validity a plan must still have at placement time, otherwise the placement is refused (seconds).
- `pre_placement.max_mark_price_age_ms` - the maximum age of the mark price the pre-placement price check may use, otherwise the check fails closed (milliseconds).
- `pre_placement.max_last_price_age_ms` - the maximum age of the last price (the `time` of the Symbol Price Ticker answer) the pre-placement last-price check may use, otherwise the check fails closed; a separate number from `pre_placement.max_mark_price_age_ms` because the last price only moves on a trade (milliseconds).

### `[reconcile]` (Phase 20; D-25 for the tick, D-11 for the probes, D-21 for the lot filters)

- `reconcile.tick_interval_ms` - the cadence of the reconcile loop that replaces the hard-coded SAFE_MODE tick; it must be strictly below `protection.max_unprotected_ms`, which `check_reconcile_cadence` enforces once both are set (milliseconds).
- `reconcile.entry_unknown_probe_count` - how many consecutive clean not-found probes by client order id an `UNKNOWN` entry needs before reconciliation may close it (D-11, used by plan 20-10; a count).
- `reconcile.entry_unknown_probe_interval_ms` - the spacing between those probes (D-11, used by plan 20-10; milliseconds).
- `reconcile.lot_filter_refresh_interval_ms` - how often the lot-size filters used for quantization are refreshed from exchange information (D-21, used by plan 20-21; milliseconds).
- `reconcile.entry_stale_grace_ms` - ALERT ONLY (plan 20-28, owner request 2026-10-23): how long past the `goodTillDate` of a resting entry the reconcile loop waits before it raises the `STALE_ENTRY_ORDER` alert for an entry order that is still `NEW`; Binance Demo did not cancel a GTD order 780 s and 1500 s after `goodTillDate`. It enters no SAFE_MODE, cancels nothing and changes no state. Unlike the fifteen required keys it does not keep the live path refused: while it is `NOT_CONFIGURED` the check is skipped, one journal row `RECONCILE_STALE_ENTRY_CHECK_SKIPPED` says so, and `ExecutionLimits.unset_alert_only_keys()` lists it (milliseconds).

### `[stale_feed]` (Phase 20, D-25, D058)

- `stale_feed.max_mark_price_age_ms` - the maximum age of the mark price before the market feed counts as stale and entries are blocked; a separate number from `pre_placement.max_mark_price_age_ms` (D-25, used by plan 20-16; milliseconds).
- `stale_feed.max_user_data_silence_ms` - the maximum silence of the user-data stream before it counts as stale; it is not the paper runtime's `max_ws_message_silence_seconds` and never reuses it (D-25, used by plan 20-16; milliseconds).

### `[alerts]` (Phase 20, D-23)

- `alerts.dedupe_window_ms` - the window in which a repeated alert for the same event is deduplicated instead of sent again (D-23, used by plan 20-13; milliseconds).

### `[account]` (Phase 21, D-03; F-012)

- `account.max_equity_age_ms` - REQUIRED (it keeps the live path refused while it is `NOT_CONFIGURED`, like the other required keys): the maximum age of the account equity reading used for live sizing, for the daily-loss day-start base and for the approval reservation gate (milliseconds). The age is the injected now minus the injected clock reading taken before the REST request, so it is only over-estimated. An age greater than the value, or negative, is stale (NO_TRADE `UNCERTAIN_ACCOUNT_STATE`); an age exactly equal to the value passes. Used by plan 21-07 (`LiveEquitySource`) and plan 21-13 (the day-risk service). The owner set 15000 on 2026-10-23 (DECISIONS D084, provenance `DECISION`); the code carries no default.
- `account.max_daily_loss_age_ms` - REQUIRED: the maximum age of a known daily loss, counted on the injected clock from the completed backfill that made it known (milliseconds). The stream path never renews it, only a completed backfill does. An age greater than the value, or negative (a stamp in the future), makes the loss unknown (NO_TRADE); an age exactly equal to the value passes. Used by `LiveDayRiskService` (`src/execution/day_risk_service.py`). The owner set 300000 (300 seconds) on 2026-10-25 (DECISIONS D087, provenance `DECISION`); the code carries no default. The Phase 24 composition must run the backfill on a schedule shorter than this value while trading is possible.

### `[margin]` (Phase 22; D-10, D-11, D-13, amendment A4; OWNER-OPEN O-2, O-3)

All three keys are REQUIRED (they would keep the live path refused while they are `NOT_CONFIGURED`) and are positive integers only (basis points and milliseconds). The owner set all three on 2026-10-24 (DECISIONS D085, provenance `DECISION`): 300 basis points for the liquidation buffer, 60000 milliseconds for the bracket age and 1000 basis points for the headroom. The code carries no default for any of them, and the limits gate of the manager refuses every placement before the margin guard can run while one is unset. Setting them does not open the live path: fourteen required keys stay `NOT_CONFIGURED`.

- `margin.liquidation_buffer_bps` - the liquidation buffer, in basis points of the entry price; the margin guard compares it as a price distance beyond the stop (D-09, D-10, OWNER-OPEN O-2, decided by D085; used by plans 22-13 and 22-14; basis points). It stays an execution-limits key and is not a registry parameter; the owner accepted this deviation from RISK_MANAGEMENT section 9.
- `margin.max_bracket_age_ms` - the maximum age of the cached leverage-bracket set before the margin guard refuses it as stale (D-11, OWNER-OPEN O-3, decided by D085; used by plans 22-12 and 22-14; milliseconds).
- `margin.headroom_bps` - the headroom, in basis points of the margin the order needs, that the available balance must keep after the order (D-13, OWNER-OPEN O-3, decided by D085; used by plan 22-14; basis points).

## Phase 20 notes

Of the twenty keys, `reconcile.entry_stale_grace_ms` is alert only: `ExecutionLimits.unset_keys()` and
`require_live_ready()` leave it out (`ALERT_ONLY_LIMIT_KEYS` in the loader), so the sentence below
about the live path refusing covers the nineteen required keys, `account.max_equity_age_ms` and
`account.max_daily_loss_age_ms` (Phase 21, D-03 and D087) among them and the three `margin` keys (Phase 22) too.

`stale_feed.max_user_data_silence_ms` is not the paper runtime's `max_ws_message_silence_seconds`
(`src/paper/coverage.py`); the two are separate keys in separate files and neither reads the other.
A value for any of the nineteen keys is the owner's number (OWNER-OPEN O-04, decision O-G): setting
one needs a DECISIONS row and the provenance label `DECISION`. Until then each stays
`NOT_CONFIGURED` and the live path refuses, naming the key.
