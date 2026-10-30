# Phase 24 limits checkpoint (plan 24-01)

Written 2026-10-31 by the assistant (Claude Sonnet 5.5). Status: OPEN, no value is set.

## What this is

`config/execution/execution-limits-v1.toml` still holds the word `NOT_CONFIGURED` for fifteen keys: fourteen required and one alert-only. While any required key is unset the live path refuses to start (`require_live_ready()` in `src/execution/execution_limits.py`), so these numbers block the first Demo run, not only the schedule. The other keys are already set and are not asked again: `account.max_equity_age_ms` 15000 (D084), `account.max_daily_loss_age_ms` 300000 (D087), `margin.liquidation_buffer_bps` 300, `margin.max_bracket_age_ms` 60000, `margin.headroom_bps` 1000 (D085).

- Every value below marked ASSISTANT RECOMMENDATION is the assistant's suggestion and a reason. It is not a decision. You supply or confirm each number.
- Each value you set gets the provenance label `DECISION` and a `docs/DECISIONS.md` row, both written by plan 24-06 after your answer. Nothing is written to config by this plan (plan 24-01 edits no config file).
- Until you answer, code and tests use values labelled TEST_ONLY. You may answer the questions of `24-OWNER-DECISIONS.md` first and these numbers later; only plan 24-06 and the first Demo run wait for them.
- Time units: the key name says the unit (`_ms` is milliseconds, `_seconds` is seconds). 60000 ms is one minute.
- Evidence labels: demo-observed means seen on Binance Demo by the owner (not mainnet); ratified means a value already fixed in `config/binance/binance-limits-v1.toml` (sha256-pinned, not editable).

## Keys

### 1. protection.max_unprotected_ms

- Meaning: the longest time a filled entry may run without a confirmed stop. After this the position is closed at market (reduce-only).
- Read by: `ProtectionCoordinator` (D079 item 2, D-13).
- Constraint: `reconcile.tick_interval_ms` must be strictly below it; it must exceed several protection steps and the ratified 120 s pause after an HTTP 429 (D081: a pause is never bypassed), or a correctly protected position gets market-closed (20-DEFERRED, "Owner-configuration constraints").
- Evidence: a by-id stop query answered -2013 right after placement although the stop was NEW (demo-observed 2026-10-22, lag not measured); the confirmation therefore also reads the open-algo-orders list (plan 20-27).
- ASSISTANT RECOMMENDATION: 180000.
- Reason: three minutes is longer than the 120 s pause plus two protection steps, so a stop delayed by a 429 is not mistaken for a failure; a longer value leaves a filled entry without a confirmed stop for longer.
- Owner value: (blank)

### 2. protection.entry_terminal_timeout_ms

- Meaning: how long, counted from the first fill, an entry may stay non-final (not completely filled or ended) before the system acts.
- Read by: `ProtectionCoordinator`.
- Constraint: take-profit legs wait until the entry is final (D079 item 5), so this bounds how long a partly filled position runs with a stop but no take-profit; at the deadline the position is closed by a reduce-only market order (D079 item 2).
- Evidence: a GTD entry stayed NEW 840 s past `goodTillDate` on Demo (2026-10-22), so a GTD expiry is not proof of a final order (D079).
- ASSISTANT RECOMMENDATION: 900000.
- Reason: 15 minutes gives a slow partial fill time to complete without leaving a half-protected position open for long; it is the path the system relies on instead of GTD expiry.
- Owner value: (blank)

### 3. protection.entry_unknown_grace_ms

- Meaning: the grace after `goodTillDate` before an entry whose state is unknown may be treated as final; during it new entries stay blocked.
- Read by: `ProtectionCoordinator`, `UnknownEntryResolver`.
- Constraint: must be longer than the late GTD behaviour seen on Demo.
- Evidence: Demo kept a GTD entry NEW for 840 s past its `goodTillDate` (2026-10-22, demo-observed).
- ASSISTANT RECOMMENDATION: 1800000.
- Reason: 30 minutes exceeds the 840 s observation with a wide margin; a shorter grace could close the books on an entry that is still resting.
- Owner value: (blank)

### 4. protection.emergency_close_poll_timeout_ms

- Meaning: how long a sent emergency close is polled before it is held as UNKNOWN and alerted.
- Read by: `MarketEmergencyCloser`.
- Constraint: separate from `max_unprotected_ms`.
- Evidence: a reduce-only market close normally fills at once; no Demo timing was recorded for a slow close.
- ASSISTANT RECOMMENDATION: 30000.
- Reason: 30 s allows two reconcile ticks of polling (at the recommended tick) before the close is declared unknown.
- Owner value: (blank)

### 5. pre_placement.min_remaining_validity_seconds

- Meaning: the minimum remaining validity of a plan at the moment of placement.
- Read by: manager gate 5e and the confirm card text (`validity_rule`).
- Constraint: Binance refuses a `goodTillDate` earlier than now plus 600 s (error -5040); the confirm TTL (default 60 s, D041) and the clock margin `LivePlacementContext.gtd_clock_margin` come on top, so the value must exceed 600 + the confirm TTL + the margin.
- Evidence: Demo -5040 for a GTD below now plus 600 s (plan 20-27); error-code page of the USDS-M Futures docs.
- ASSISTANT RECOMMENDATION: 900.
- Reason: 900 s is 600 s for the exchange floor, 60 s for the confirm window, and leaves 240 s for the clock margin and slack.
- Owner value: (blank)

### 6. pre_placement.max_mark_price_age_ms

- Meaning: the oldest mark price the pre-placement price check may use.
- Read by: manager gate 5e and the CONFIRM recheck (the recheck rebinds the checked-at instants to the press instant, `confirm_recheck.py`).
- Constraint: the reading is a fresh REST read made just before placement; this is a different key from `stale_feed.max_mark_price_age_ms` and must never reuse it.
- Evidence: three sequential REST reads took 1 to 2 s on Demo (D084, demo-observed).
- ASSISTANT RECOMMENDATION: 5000.
- Reason: 5 s refuses a stuck read and does not refuse a normal one.
- Owner value: (blank)

### 7. pre_placement.max_last_price_age_ms

- Meaning: the oldest last price the last-price check may use (quick task 261020-l4p).
- Read by: manager gate 5e and the CONFIRM recheck.
- Constraint: same as the mark price key.
- Evidence: as in key 6.
- ASSISTANT RECOMMENDATION: 5000.
- Reason: same reason as key 6; both are fresh reads made together.
- Owner value: (blank)

### 8. reconcile.tick_interval_ms

- Meaning: how often the reconcile loop compares local state with the exchange (and, in this phase, the cadence of several other tasks, see the derived-cadence table).
- Read by: `ReconcileLoop`.
- Constraint: strictly below `protection.max_unprotected_ms` (the loop constructor raises `ExecutionLimitsInvalid` otherwise).
- Evidence: none on load. REST weight per tick, read from the docstrings of the installed SDK that the adapter wraps (not re-read on the current Binance REST pages, which the fetch tool does not render): open normal orders weight 1 for one symbol and 40 without a symbol; open algo orders the same (1 or 40); position information about 5; mark price weight 1 with a symbol. For five tracked symbols read one by one that is roughly 20 per tick; read for all symbols at once it is roughly 90 per tick. At the recommended value a minute holds four ticks, so roughly 80 to 360 per minute before any other holder of the shared gate. The REST ceiling per minute is not stated here; plan 24-20 must compare the tick weight with the `rateLimits` of the live `exchangeInfo` before the owner run.- ASSISTANT RECOMMENDATION: 15000.
- Reason: twelve ticks fit into the recommended 180000 ms, so a stop gets many chances to be confirmed; a shorter tick raises REST load against the rate-limit gate for little gain.
- Owner value: (blank)

### 9. reconcile.entry_unknown_probe_count

- Meaning: how many clean not-found probes of an UNKNOWN entry are needed before it may be closed out.
- Read by: `UnknownEntryResolver`.
- Constraint: the earlier "3 probes" suggestion was non-binding and must not appear in code (20-DEFERRED).
- Evidence: Demo answered -2013 for a stop that was NEW right after placement (demo-observed 2026-10-22), so one not-found answer is not proof.
- ASSISTANT RECOMMENDATION: 3.
- Reason: three agreeing answers are strong enough to treat an order as absent, and the cost of waiting is bounded by key 10 and key 3.
- Owner value: (blank)

### 10. reconcile.entry_unknown_probe_interval_ms

- Meaning: the spacing between those probes.
- Read by: `UnknownEntryResolver`.
- Constraint: probe count times interval must fit well inside `protection.entry_unknown_grace_ms`.
- Evidence: as in key 9.
- ASSISTANT RECOMMENDATION: 5000.
- Reason: five seconds apart is long enough for the exchange's listing lag seen on Demo and short enough that three probes finish within seconds.
- Owner value: (blank)

### 11. reconcile.lot_filter_refresh_interval_ms

- Meaning: how often the lot-size filters are refreshed.
- Read by: `LotFilterSource.refresh_if_due`, called by the loop once per tracked symbol at the end of a compared tick.
- Constraint: the refresh runs inside the tick lock with no timeout (WR-B7, Phase 24 item); keep it rare.
- Evidence: filters change rarely, and the emergency closer reads live filters first anyway (D081).
- ASSISTANT RECOMMENDATION: 3600000.
- Reason: one hour keeps filters current without adding REST load to every tick.
- Owner value: (blank)

### 12. reconcile.entry_stale_grace_ms (ALERT ONLY)

- Meaning: how long after `goodTillDate` an entry that is still NEW raises the STALE_ENTRY_ORDER alert.
- Read by: the stale-entry check (plan 20-28). Alert only: left unset, the check is skipped and nothing else changes (`ALERT_ONLY_LIMIT_KEYS`).
- Constraint: none beyond being positive.
- Evidence: the 840 s late GTD behaviour (demo-observed).
- ASSISTANT RECOMMENDATION: 900000.
- Reason: 15 minutes is just beyond the 840 s seen on Demo, so a normal late expiry does not alert and a stuck entry does.
- Owner value: (blank)

### 13. stale_feed.max_mark_price_age_ms

- Meaning: the oldest mark price before the feed counts as stale and the system enters SAFE_MODE (STALE_FEED).
- Read by: feed freshness (`assess_feeds`), D058.
- Constraint: a different key from `pre_placement.max_mark_price_age_ms`; must be larger than the reconcile tick. In the live process the mark price is read from REST once per tick (see Q5), so this key bounds how many missed reads are tolerated.
- Evidence: none on load.
- ASSISTANT RECOMMENDATION: 60000.
- Reason: with the recommended tick, four missed reads in a row mean the feed is stale; one or two are noise.
- Owner value: (blank)

### 14. stale_feed.max_user_data_silence_ms

- Meaning: the longest silence of the user-data stream before it counts as stale (D058).
- Read by: feed freshness. Silence is measured from the newest of last event, ping and pong (`supervisor.liveness()`, 20-DEFERRED), because Binance sends user-data events only on account activity. The ratified `stream.max_liveness_age_seconds` is the string "none", so this key is the only silence bound.
- Constraint: must be larger than the interval at which the connection shows life.
- Evidence: the rule was to take three times the server ping interval stated on the official Binance USDS-M user-data-streams page. Re-read on 2026-10-31 (the `.md` form of `.../derivatives-trading-usds-futures/user-data-streams`, HTTP 200, read in full; the websocket-market-streams page was also read once): neither page states a server ping interval. The user-data page states only that a listenKey is valid for 60 minutes, that a PUT extends it for 60 minutes and that a single connection is valid for 24 hours. The ratified keepalive is `stream.keepalive_interval_seconds` = 1800.
- ASSISTANT RECOMMENDATION: no number. Owner to choose after the page is read. The page does not state the ping interval, so I will not derive a figure from it. I suggest the owner Demo run (plan 24-29 or 24-33) also records the observed ping and pong times from `supervisor.liveness()`, so the value can be set from a measurement; that is a suggestion, not yet in those plans.
- Reason: a number invented without the ping interval could either raise false SAFE_MODE entries during a quiet account or hide a dead connection.
- Owner value: (blank)

### 15. alerts.dedupe_window_ms

- Meaning: the window in which an identical repeated alert is folded into one.
- Read by: `JournalFirstAlertSink` (no default; it raises when unset, which blocks every alert path including SAFE_MODE alerts).
- Constraint: WR-C6 is still open: a CRITICAL alert whose send failed is not re-queued, and the dedupe window then suppresses its repeats; a shorter window repeats sooner.
- Evidence: none.
- ASSISTANT RECOMMENDATION: 300000.
- Reason: five minutes folds a noisy repeat into one message and still repeats an unresolved alert; the open WR-C6 risk is recorded in the owner register.
- Owner value: (blank)

### 16. Optional: the D083 clock margin (plan 24-03)

- Meaning: the owner-set padding added to a ban end time taken from an HTTP 418 body (-1003), for the clock difference to Binance.
- Read by: the REST rate-limit gate (D083 point 4). It is an optional key, not required: unset, the ratified fallback of 259200 s applies.
- Constraint: D083 keeps it `NOT_CONFIGURED` until the owner sets it; the "IP banned until" text on Futures is unverified (a third-party report only).
- Evidence: the first real 418 body has not been seen and must not be provoked.
- ASSISTANT RECOMMENDATION: leave it NOT_CONFIGURED until a real Futures 418 body has been seen.
- Reason: a margin tuned to a text format nobody has observed on Futures could be wrong; the 3-day fallback is safe and already ratified.
- Owner value: (blank)

## Cadences that need no new key (derived)

| Task | Cadence | Source | Note |
|---|---|---|---|
| Protection step | the reconcile tick, plus an immediate wake when a fill arrives | `reconcile.tick_interval_ms` (assumption A1) | a periodic-only step would add its whole period to the unprotected window |
| Day-risk backfill | half of `account.max_daily_loss_age_ms`, that is 150 s | D087 | D087 requires the schedule to stay under 300 s |
| Commission refresh | when the cached rate is older than the registry `commission_rate_ttl_seconds` minus one tick | `commission_rate_ttl_seconds` (3600 in the parameter sets) | needs no owner number |
| Clock-drift re-measure | 60 s | ratified `drift.periodic_remeasure_interval_seconds` | |
| Confirm-TTL sweep, alert drain, health checks, liveness stamp, scheduled-cancel check | the reconcile tick | `reconcile.tick_interval_ms` | |

## Relationships plan 24-06 tests

Plan 24-06 writes your final numbers and adds one test that fails with the key names if any of these breaks:

1. `reconcile.tick_interval_ms` is strictly below `protection.max_unprotected_ms`.
2. `protection.max_unprotected_ms` is above the 120 s pause (ratified `rate_limit_429_no_retry_after_wait_seconds`) plus two ticks.
3. `pre_placement.min_remaining_validity_seconds` is above 600 s plus the confirm TTL plus the GTD clock margin.
4. `stale_feed.max_mark_price_age_ms` is above one tick.
5. `reconcile.entry_unknown_probe_count` times `reconcile.entry_unknown_probe_interval_ms` is below `protection.entry_unknown_grace_ms`.

With the recommended values: 15000 < 180000; 180000 > 120000 + 30000; 900 > 600 + 60 + margin (margin up to 239 s); 60000 > 15000; 3 x 5000 = 15000 < 1800000. All five hold.

## Heartbeat row (install argument, not a TOML key)

| Item | ASSISTANT RECOMMENDATION | Reason | Owner value |
|---|---|---|---|
| Live heartbeat check period and grace | period 60 s, grace 120 s | the same as the paper check you already chose (STATE.md, "second heartbeat check (period 60 s, grace 120 s)"); passed as `deploy/heartbeat.sh --target live --install-timer --interval-seconds 60`, no default exists | (blank) |

## Answer form

Reply "limits: follow your recommendation" or list overrides as `key = value`. For key 14 reply with a number once the ping interval is known, or "leave it for the owner run".
