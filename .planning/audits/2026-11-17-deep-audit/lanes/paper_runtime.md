# Lane M10: paper_runtime

## Scope
`src/paper/*` (31 files, ~21.5k lines), `src/adapters/paper_ws.py`, `config/paper/*` at snapshot `55885b9`.
Questions: BINANCE_* refusal; SHADOW has no order path; closed-candle detection / reconnect gap / duplicates / restart;
freeze + pin epoch; shadow fills vs backtest semantics; exit criteria computation.
Probes (all under `tmp/paper_runtime/`): `imp_probe.py` (transitive imports), `poll_probe.py` (minute poller page budget),
`cov_probe.py` (coverage ceiling and missing-row scenarios). No test file was run. No network call was made.

## Coverage
| file | level | note |
|---|---|---|
| src/paper/runtime.py | DEEP_READ | all 1738 lines |
| src/paper/supervisor.py | DEEP_READ | all |
| src/paper/resync.py | DEEP_READ | all |
| src/paper/pipeline.py | DEEP_READ | all |
| src/paper/restart.py | DEEP_READ | lines 40-497 |
| src/paper/freeze.py | DEEP_READ | all |
| src/paper/shadow_fill.py | DEEP_READ | all |
| src/paper/live_minutes.py | DEEP_READ | all |
| src/paper/bars.py | DEEP_READ | all |
| src/paper/market_inputs.py | DEEP_READ | all |
| src/paper/coverage.py | DEEP_READ | 1-716 (health and coverage); 717-1563 (freeze-tick continuity, host witness) outline only |
| src/paper/exit_criteria.py | DEEP_READ | 1-140, 340-810, 1071-1130, 1195-1256; rest outline (closure verdict, evidence items) |
| src/paper/shadow_runtime.py | DEEP_READ | 160-262, 520-1119, 1247-1310, 1353-1395; rest outline |
| src/paper/shadow_ledger.py | NORMAL_READ | 150-260, 410-450, 1022-1225; reservation lifecycle (612-1020) outline only |
| src/paper/runtime_config.py | NORMAL_READ | 1-120 + outline; parser bodies not read line by line |
| src/paper/runtime_state.py | NORMAL_READ | 96-132, 469-498 + outline |
| src/paper/loop.py | NORMAL_READ | 150-330 (gates); `evaluate_closed_bar` body and `run_paper_tick` not read (the strategy chain belongs to another lane) |
| src/paper/liveness.py | NORMAL_READ | 60-130 |
| src/paper/shadow.py | METADATA_ONLY | outline + Mode / require_shadow (136-160); Telegram text and send retry belong to the telegram lane |
| src/paper/shadow_confirm.py | METADATA_ONLY | outline |
| src/paper/rehearsal.py | METADATA_ONLY | docstring 1-40; its entry script was checked for the BINANCE_ refusal |
| src/paper/held_marker.py | METADATA_ONLY | seen through runtime.py call sites |
| src/paper/vocabulary.py | METADATA_ONLY | enums seen through use |
| src/paper/journal.py | NOT_READ | paper record assembly |
| src/paper/notify.py | NOT_READ | Telegram notify |
| src/paper/surface.py | NOT_READ | decision-surface record |
| src/paper/replay_inputs.py | NOT_READ | replay payloads |
| src/paper/evidence_bundle.py | NOT_READ | bundle verification |
| src/paper/evidence_export.py | NOT_READ | |
| src/paper/attribution.py | NOT_READ | |
| src/paper/__init__.py | NOT_READ | 61 lines |
| src/adapters/paper_ws.py | DEEP_READ | 190-843; 1-189 (kline normalisation, log bridge) not read |
| config/paper/README.md | DEEP_READ | first 80 lines (keys, identity) |
| config/paper/paper-runtime-v2.toml | DEEP_READ | all values |
| config/paper/paper-runtime-v1.toml | DEEP_READ | by diff against v2 (one key added) |

## Verified Safe Areas
| rule or behaviour | what was checked | where | why it holds |
|---|---|---|---|
| Paper refuses any `BINANCE_*` name | order of checks in `main`, the probe, alternate entries | runtime_config.py:113-119; runtime.py:1524-1529, 1383-1385; scripts/shadow_rehearsal.py:522; scripts/paper_ws_smoke.py:1747 | first check after the two read-only probes, before allowlist, DB engine and Telegram; presence alone refuses; only `os.environ` is read (no dotenv in src/paper) |
| SHADOW has no order path | probe `imp_probe.py`: import all 31 `src.paper` modules + paper_ws + telegram_callbacks + shadow stores, list `sys.modules` | output: flagged = binance_client, binance_errors, binance_limits, binance_public, binance_ratelimit_gate, `src.execution`, `src.execution.order_ids`, `src.execution.placement` | `src.execution.placement` is the pure price-derivation module that src/backtest/entry.py:32 imports; no `src.live`, no `src.reconcile`, no manager / protection / emergency_close module; the public adapter is built with `api_key=None, api_secret=None` (binance_public.py:413); `require_shadow` refuses any other mode (shadow.py:153-158) |
| Only closed candles reach the pipeline | live path | supervisor.py:335; pipeline.py:304-315 | forming klines dropped; a close later than the tick time is dropped |
| No duplicate bar across a reconnect seam | cursor | supervisor.py:246-260, 349-356, 610-614; pipeline.py:352-360 | monotonic cursor under a lock; a second copy is a duplicate; a differing copy raises and the loop exits 7 |
| Reconnect gap is backfilled, never fabricated | drop path and resync | supervisor.py:483-499; resync.py:300-344 | missing closes become GapRecords; an exhausted rebuild runs the backfill, then `on_fatal` -> exit 7 |
| A backfilled or warm-up bar never produces a signal | source-tag rule | pipeline.py:380-384; restart.py:466-477 | REST_WARMUP returns before any record; REST_BACKFILL becomes one PAPER_GAP |
| No evaluation over a hole | continuity gate | pipeline.py:514-517, 550-563 | 201 contiguous 1h bars and 200 contiguous 4h bars required, else a HISTORY_DISCONTINUITY heartbeat |
| Loop fails closed | queue full, record write error, pipeline error, lost lease | runtime.py:859-863, 870-874, 1009-1012, 983-991, 1166-1171, 1720-1724 | exit 7 with no RUNTIME_STOP, so the next start reads a crash |
| A start never mints or changes an epoch | pin file vs stored pin vs config identity vs allowlist hash | runtime.py:1654-1671; restart.py:394-458; runtime.py:404-433 | independent comparisons, each refuses with exit 6 |
| Registry drift after the pin | freeze tick + start gate | freeze.py:838-898, 1010-1018, 1030-1032; pipeline.py:257-261 | a changed file gives REGISTRY_DIFF and a rewritten pin that the allowlist hash then refuses |
| SHADOW fills are the backtest engine, not a fork | imports and call sites | shadow_fill.py:38-61, 346-357, 371-380, 416-425 | `advance`, `booking_for_event`, `funding_events`, `build_trade_record`, `protective_levels_for_fill`, `new_plan_state` come from src/backtest; only the eligibility start differs (127-175) |
| No fill from a price before the operator acted | eligibility | shadow_fill.py:166-175, 346-351 | start = confirm instant floored to the minute + 1 minute, used as `start_exclusive` |
| Minute series integrity | append rules | live_minutes.py:83-134, 273-277 | forming minute refused, stored minute never overwritten, both kinds fetched before either is stored |
| Exit criteria do not edit evidence | evaluator | exit_criteria.py:583-640, 703-772; coverage.py:310-319 | flags REST-sourced processed rows, duplicates and missing rows; coverage compared on integer microseconds |

## Decision review
| decision / rule | verdict | yardstick | reason |
|---|---|---|---|
| D040 / SC6: paper holds no trade-capable variable | SOUND | owner goal (fail closed), code trace | name-prefix refusal before any client exists; all three entry points apply it |
| Q-D "history-only": a REST-recovered bar is never evaluated | SOUND | fail closed; no late signal | costs evaluations, but each is a recorded PAPER_GAP and uncovered time |
| Q-B `confirm-plus-one` fill eligibility | SOUND | arithmetic | the first readable minute opens after the confirm instant, so no look-back fill |
| L-02: SHADOW fill = Phase 14 lifecycle functions | SOUND | code trace | same functions; four private helpers are imported by name from `src.backtest.engine` (shadow_fill.py:39), a coupling to watch |
| 16-DEC-CONFIG-PIN: identity of validated values, not file bytes | SOUND | logic | a value change refuses, a comment edit does not |
| 16-DEC-PIN-COMMAND / REV-18: one-shot pin, a start never mints | SOUND for parameters and configuration, DOUBTFUL in scope | logic | the pin names no code build (G-1005) |
| O-07 `continuous_uncovered_ceiling_seconds = 900` | DOUBTFUL | arithmetic (probe) | health evidence is hourly, so a start or restart more than 15 min before an hour close breaks the ceiling (G-1003); the same decision record moved the silence value 15 -> 3900 for this reason and left the ceiling |
| O-07 `max_ws_message_silence_seconds = 3900` | SOUND (weak) | arithmetic | fits hourly journaled evidence; it cannot see a silence shorter than about an hour (the in-process 120 s watchdog covers that) |
| 16-DEC-WS-WATCHDOG `feed_silence_timeout_seconds = 120` | SOUND | exchange behaviour (kline streams push forming updates continuously) | ten streams silent for 120 s is a dead feed; the recovery is bounded, then exit 7 |
| D-35: clock skew logged at start, no threshold | DOUBTFUL | arithmetic | a host behind by more than the delivery latency drops every closed bar (KNOWN IN-01); a host ahead accepts a forming REST row as closed (G-1008) |
| D061 item D: 14 days, coverage >= 95 %, parity tolerance 0 | SOUND as a plumbing trial; the label "parity" is DOUBTFUL | logic | "parity" replays the runtime's own recorded inputs with the evaluator's code (exit_criteria.py:1071-1081): it proves reproducibility, not agreement with the backtest on exchange data, and not PnL parity |
| 16-DEC-EQUITY-BASE: size with the SHADOW ledger "as the backtest engine reads it" | DOUBTFUL at the edge | code trace | the ledger at a bar close has not yet seen the last minute(s) (G-1006) |
| Live-minute page cap 20 x 1500 ("ratify current", 16-DEC-O-07) | WRONG for a soak longer than 20.8 days | arithmetic (probe) | the restore replays from the first fill of the symbol (G-1001) |
| Staleness 60 s (loop.py:187) vs 4h sibling wait 15 s | SOUND | arithmetic | a held bar is re-submitted at close + 15 s, inside the 60 s gate |

## Findings

### G-1001
- ID: G-1001 · Severity: MEDIUM now / MEDIUM mainnet (the paper soak is the go-live input; no order is involved) · Confidence: CONFIRMED · Classification: DEFECT · Category: restart / availability of evidence
- Component: SHADOW restore + live minute poller · File: src/paper/shadow_runtime.py, src/paper/live_minutes.py · Lines: shadow_runtime.py:1062-1083; live_minutes.py:51-52, 309-335; shadow_ledger.py:1022-1029
- Rule: D-15 (a restart rebuilds simulated positions); 16-DEC-O-07 "ratify current" page cap · Known-prior: KNOWN:16-REVIEW-batch1 IN-07 names only the request weight and "never trimmed", rated Info; this consequence is not recorded
- Evidence: `opened = [Reservation.from_payload(...) for e in records if e.event_type == EVENT_SHADOW_POSITION_OPENED]`, then `since = min(r.eligibility_start_utc for r in opened if r.symbol == symbol)` and `await self._poller.poll_once(symbol, now_utc=now, since_utc=since)` (shadow_runtime.py:1070-1079). `records` are the journal events of every approved SHADOW approval (`load_records`), closed positions included. `_fetch` ends with `raise LiveMinutePollError(f"{kind} minutes of {symbol} are more than {self._max_pages} pages behind ...")` after `_MAX_PAGES = 20` pages of `_PAGE_LIMIT = 1500`.
- Expected: a restart at any age of the trial rebuilds the ledger and continues.
- Actual: once the first filled SHADOW position of a symbol is older than 30,000 minutes (20.83 days), `shadow.start` raises, `run` maps it to `RuntimeFailClosed("the SHADOW chain failed to start ...")` (runtime.py:1120-1125), exit 7, and `restart: unless-stopped` repeats it. The same budget applies in-run when a symbol's last stored minute is older than 20.83 days (cursor = last stored minute + 1, live_minutes.py:312-313): the poller error fails the loop, and the restart then fails as above.
- Reproduction: `tmp/paper_runtime/poll_probe.py` -> `20 days: OK added 28799 {'trade': 20, 'mark': 20}`; `21 days: LiveMinutePollError: trade minutes of BTCUSDT are more than 20 pages behind 2026-11-30T23:59:55+00:00`.
- Impact: the 14-day trial is not affected. The planned 3-6 month paper observation stops at the first restart (deploy, crash, host reboot, any exit 7) after about day 21 from the first fill and cannot be restarted without a code change, which means a new image. Each failed start also sends up to 20 requests of limit 1500 per symbol before it fails.
- Why tests miss it: tests/test_paper_live_minutes.py exercises the page cap as a guard; no test restores a ledger whose first position is older than the cap.
- Remediation: bound the replay (persist ledger checkpoints, or replay only positions not yet closed and book closed ones from their journaled SHADOW_POSITION_CLOSED trade record); trim `LiveMinuteSource`; make the page budget a function of the span requested.

### G-1002
- ID: G-1002 · Severity: MEDIUM now / MEDIUM mainnet · Confidence: PROBABLE (traced, not executed) · Classification: DEFECT · Category: epoch isolation
- Component: SHADOW ledger restore · File: src/paper/shadow_ledger.py · Lines: 1022-1029, 1162-1199; src/persistence/shadow_stores.py:193-221; src/backtest/ledger.py:140-148; src/paper/shadow_runtime.py:1389-1393
- Rule: "one instance per paper epoch" (shadow_ledger.py:156); REV-18 "a new pin starts a new trial" · Known-prior: none found
- Evidence: the ledger starts with `started_at_utc=epoch.opened_at_utc` and `initial_equity`; `load_records` iterates `self._stores.list_approved_approvals()`, which filters by mode only, not by epoch; `_replay_positions` applies every booking through `self._ledger.apply(booking)`; `_roll` raises `ValueError("cannot roll the ledger backwards ...")` for a booking in a UTC day before the ledger's day start.
- Expected: a new epoch starts from the configured initial equity with no position of an earlier epoch.
- Actual: on a database that holds a filled SHADOW position of an earlier epoch, the new epoch's start replays that position. A booking dated before the new epoch's first UTC day raises inside the rebuild (start fails, exit 7, loop). A booking on the same UTC day is added to the new epoch's equity and day PnL.
- Reproduction: not run (needs journal fixtures). Trace: runtime.py:1121 -> shadow_runtime.py:986 -> 1063, 1094-1101 -> shadow_ledger.py:1139-1141, 1196-1199 -> backtest/ledger.py:144.
- Impact: the documented way to change a configuration value or to repeat a failed trial is "a new pin" (RUNBOOK section 20, line 726). On the same soak database that new epoch either cannot start or starts with foreign PnL. Example: epoch 1 ends +18 USDT with one position still open; epoch 2 pinned the same day would size with 618 instead of 600 and count that open position against `max_open_positions`.
- Why tests miss it: the restore tests use one epoch per store.
- Remediation: scope `load_records` to the epoch (approvals whose signal close is at or after the pin, or an epoch id on the reservation), and state in the RUNBOOK whether a new pin needs an empty database.

### G-1003
- ID: G-1003 · Severity: MEDIUM now / MEDIUM mainnet · Confidence: CONFIRMED · Classification: DESIGN · Category: exit criteria
- Component: coverage ceiling vs health evidence · File: src/paper/coverage.py, src/paper/runtime.py, config/paper/paper-runtime-v2.toml · Lines: coverage.py:318-319, 643-653, 686-711; runtime.py:852-858, 1071-1077; toml key `continuous_uncovered_ceiling_seconds = 900`
- Rule: 16-DEC-O-07 (ceiling 900 s), D061 item D · Known-prior: RUNBOOK line 709 names only the pin-to-start time
- Evidence: every start records `HEALTH_STATE_CHANGED DISCONNECTED` at the start time and `HEALTHY` only at "the first live closed event after the warm-up"; coverage also adds `run.start -> run_messages[0]` as DISCONNECTED. The first live closed bar is the next hourly close. `ceiling_pass = block is None or block.length_seconds <= Decimal(ceiling)`.
- Expected: the ceiling measures real outages; a 60 s restart is a 60 s outage.
- Actual (probe `cov_probe.py`, 5 symbols, 14-day window): pin 10:00:00, start 10:00:30, no restart -> longest uncovered 3600.299 s, `ceiling_pass=False` (coverage 0.99702 passes). Pin 10:50 -> 600.299 s, pass. One 60 s planned restart at 12:20 -> 2400.299 s `[PLANNED_RESTART, WS_RECONNECT_WINDOW]`, fail. The same restart at 12:50 -> pass.
- Reproduction: run `tmp/paper_runtime/cov_probe.py` (records built with `health_record` and `RuntimeRecord.bar_processed`, judged by `derive_health_intervals` and `coverage_report`).
- Impact: the trial verdict depends on the minute of the hour at which the process starts. Any crash restart (an exit 7 path, a host reboot) more than 15 minutes before an hour close fails "continuous uncovered time", and the documented consequence is a new pin and 14 more days. The error is on the safe side (a false FAIL), but it makes a PASS depend on timing and invites loosening the number without a derivation.
- Why tests miss it: the coverage tests place HEALTHY evidence at chosen instants; no test derives the ceiling from a real start sequence.
- Remediation: an owner decision (below): journal a feed-proof record sooner after a start (the supervisor sees forming frames within seconds), or set the ceiling from the evidence cadence (at least 3600 s plus the start time), or exempt the start window explicitly.

### G-1004
- ID: G-1004 · Severity: LOW now / LOW mainnet · Confidence: CONFIRMED · Classification: DEFECT · Category: exit criteria / restart
- Component: downtime gaps · File: src/paper/restart.py · Lines: 172-174; src/paper/exit_criteria.py:748-772
- Rule: "each expected close has exactly one record or one explained gap" (restart.py:160-162) · Known-prior: none found
- Evidence: `last = restored.last_closes.get((symbol, interval)); if last is None: continue`. The evaluator expects every close from the pin (`_expected_closes(interval, inputs.window_start_utc, ...)`).
- Expected: a close between the pin and the first processed bar has a gap record.
- Actual: it has neither a processed nor a gap record, and "no missing journal row" fails. Probe scenario C (pin 10:58:00, start 11:00:30): `rows without record=5`; `downtime_gaps` with no processed bar prints `()`. The same holds per pair when a run crashes before its first processed bar of that pair (a 4h pair can take up to 4 h).
- Reproduction: `tmp/paper_runtime/cov_probe.py`, scenario C and its last line.
- Impact: a trial pinned a few minutes before an hour close, or one that crashes in its first hours, fails a criterion for a reason the records do not explain.
- Why tests miss it: the restart tests start from a restored last close.
- Remediation: use the pin instant as the baseline when a pair has no processed bar.

### G-1005
- ID: G-1005 · Severity: MEDIUM now / MEDIUM mainnet · Confidence: CONFIRMED (absence shown by search) · Classification: GAP · Category: freeze / evidence provenance
- Component: epoch pin and runtime records · File: src/paper/runtime.py, src/paper/freeze.py, src/paper/exit_criteria.py · Lines: runtime.py:551-567, 1696-1713; freeze.py:373-395; runtime_config.py:70-86
- Rule: PAPER-03 freeze (D-04); 16-DEC-Q-I `host-build-recorded` · Known-prior: none found
- Evidence: the epoch id hashes `strategy_id, parameter_set_id, parameter_set_hash, opened_at_utc` only. RUNTIME_START carries those three fields, the configuration identity and `clock_skew_ms`. A case-insensitive search for `IMAGE_COMMIT|code_version|commit|revision|image` over src/paper/*.py, scripts/evaluate_trial_soak.py and scripts/export_soak_evidence.py finds no build field. The image has a stamp (`TRADING_APP_REVISION`, src/adapters/code_version.py:36) that only src/live/runtime.py reads; the name is not in `ALLOWED_ENV_NAMES`. The build is recorded only in a host file (`.deploy/soak-image.env`, header of deploy/soak-image.sh).
- Expected: the evidence bundle can show which build produced each run of the trial.
- Actual: a service restarted with another `IMAGE_TAG` writes the same RUNTIME_START as before; the freeze tick checks the parameter file only. The parity criterion replays recorded inputs with the evaluator's own code, so it notices a change of strategy / planner / risk code between builds and nothing else (supervisor, pipeline gates, fill driver, ledger, cost code).
- Reproduction: the searches above; read runtime.py:1696-1713.
- Impact: the answer to "can the soak evidence be produced from a build other than the pinned one?" is yes, and the bundle cannot show it. With one operator this is an integrity gap, not an attack path; it matters because a later phase uses this evidence as a go-live input.
- Why tests miss it: no test asserts a build field on RUNTIME_START or EPOCH_PINNED.
- Remediation: record the build stamp on EPOCH_PINNED and on every RUNTIME_START, and add a criterion "one build per trial" (or list the builds).

### G-1006
- ID: G-1006 · Severity: LOW now / LOW mainnet · Confidence: PROBABLE · Classification: DESIGN · Category: paper vs backtest semantics
- Component: risk inputs at the bar close · File: src/paper/market_inputs.py, src/paper/shadow_ledger.py, src/paper/shadow_runtime.py · Lines: market_inputs.py:186-212; shadow_ledger.py:410-435; shadow_runtime.py:831-850; live_minutes.py:273
- Rule: 16-DEC-EQUITY-BASE; D052 (e) order "advance, book, evaluate" · Known-prior: none found
- Evidence: `factory(candle)` reads `risk_inputs.equity_and_thresholds(close)` and `open_positions(close)`; `_view_at(now_utc)` only rolls the day on a copy and "the stored ledger moves only through bookings". Bookings arrive from the minute poller, which settles minutes closed at or before `now - close_lag` (5 s) every 2 s. A 1h bar that is not on a 4h boundary is evaluated as soon as it is dequeued (about its close), so the minute that closes with the bar is never booked at evaluation time.
- Expected (documented): "the SHADOW ledger as the backtest engine reads it ... judge the same numbers" (market_inputs.py:193-196).
- Actual: an SL/TP exit in the last minute of the hour (about 1 in 60 exits if uniform) is still an open position, and its PnL is missing from equity and the daily loss, when the bar's signal is sized and gated. The backtest books it first.
- Reproduction: not run; the timing follows from `minute_close_lag_seconds = 5`, `minute_poll_interval_seconds = 2` and pipeline.py:362-406.
- Impact: in those cases paper takes or refuses a different trade or size than the backtest of the same data (symbol conflict, `max_open_positions`, daily stop, equity off by one trade's PnL, for example 3 USDT at 0.5 % of 600). The parity criterion cannot see it because it replays the recorded inputs.
- Why tests miss it: the tracer test compares one plan's record, not the ledger timing around a bar close.
- Remediation: wait for the settled watermark to reach the bar close before evaluating (costs about 5-7 s), or document the difference as intended and count the affected bars.

### G-1007
- ID: G-1007 · Severity: LOW now / LOW mainnet · Confidence: PROBABLE · Classification: DEFECT · Category: reconnect seam
- Component: supervisor held bars · File: src/paper/supervisor.py · Lines: 337-341, 372-379, 546-550, 610-614, 349-356
- Rule: Q-D (only a bar that was not received live is history-only) · Known-prior: none found
- Evidence: during a pending recovery a live closed kline is appended to `_held`; `_backfill_pairs` keeps a REST copy with `self._advance_last_close(...)`; `_flush_held` then calls `_deliver_live`, where `_advance_last_close` returns False and the live copy is logged as `duplicate_close_dropped`.
- Expected: a bar received live is evaluated.
- Actual: when the REST backfill of the same recovery also returns that close, the REST copy wins, the pipeline records a PAPER_GAP and the bar is never evaluated. The window is every recovery, including `verify_start_seam` at each start and the SDK's daily connection rotation.
- Reproduction: not run.
- Impact: a missed evaluation, recorded as a gap (fail closed); a few seconds of exposure per recovery, so rare.
- Why tests miss it: the seam tests assert no duplicate and no gap for a held bar, with a backfill that does not return the held close.
- Remediation: drop from the backfill result any close that is in `_held`.

### G-1008
- ID: G-1008 · Severity: LOW now / LOW mainnet · Confidence: PROBABLE · Classification: DESIGN · Category: clock
- Component: closed-bar filter by host clock · File: src/paper/resync.py, src/paper/restart.py, src/paper/market_inputs.py · Lines: resync.py:300; restart.py:292-294; market_inputs.py:216-226; pipeline.py:304-313
- Rule: D-35 (skew logged, no threshold) · Known-prior: KNOWN:16-REVIEW-batch1 IN-01 covers the host-behind side (FUTURE_CLOSE drop, lockout), deferred as Info; the host-ahead side is not recorded
- Evidence: `closed = [k for k in raw_page if k.close_time_utc <= now_utc]` with `now` from the host clock; `measure_clock_skew` docstring: "logged, no threshold".
- Expected: a REST row counts as closed only when the exchange closed it.
- Actual: with the host ahead by s seconds, a backfill or warm-up in the last s seconds of a bar stores the still-forming row as history; the later live copy differs and `_conflict` raises (pipeline.py:354-355), exit 7; the restart warm-up then reads the closed row. With the host behind by more than the delivery latency every live closed bar is dropped (IN-01) and evaluation locks out for 200 bars.
- Reproduction: not run.
- Impact: one restart in the host-ahead case; a silent no-evaluation period in the host-behind case, visible only as an unhealthy probe after 3900 s and as HISTORY_DISCONTINUITY heartbeats.
- Why tests miss it: the tests inject one clock for both the exchange and the host.
- Remediation: refuse the start above a skew bound, re-measure periodically, and decide closed-ness from the next row or from the server time.

## Owner decisions
1. Ceiling of continuous uncovered time (G-1003). Today a 60-second restart at 12:20 counts as 2400 s uncovered and fails the 900 s ceiling; at 12:50 it passes. Options: (a) keep 900 s and accept that any restart more than 15 minutes before an hour close ends the trial; (b) record feed proof within seconds of a start so the ceiling measures the real outage; (c) raise the ceiling to at least one bar interval plus the start time.
2. New pin on the same database (G-1002). Either every new epoch needs an empty soak database (then the earlier epoch's records must be exported first), or the code scopes the ledger to the epoch.
3. Soak longer than 21 days (G-1001). As the code stands, the long paper observation cannot restart after about day 21 from the first fill; fixing it changes the image, which under the current rules is a new trial.
4. Build identity in the trial evidence (G-1005): accept the host file as the only witness, or require the build on every start record.
5. Clock skew bound (G-1008): the value above which a start is refused (for example 500 ms) is an owner number.

## Open Questions
- binance_adapters / exchange_facts: `DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL` (paper_ws.py:336) comes from the SDK constant; whether that URL and the one-socket-per-path behaviour still match the exchange was not checked here.
- binance_adapters: a failed SHADOW restore (G-1001) spends up to 20 pages x limit 1500 per symbol per start under `restart: unless-stopped`; does the public adapter's rate-limit gate hold across process restarts?
- ops_deploy: the container healthcheck turns unhealthy after 3900 s without a processed bar (runtime.py:1422-1434); nothing in this lane shows who acts on an unhealthy paper container.
- KNOWN and not re-reported: 16-REVIEW-batch1 IN-01 (FUTURE_CLOSE drop), IN-02 (non-atomic `write_pinned_state`, freeze.py:933), IN-04, IN-06, IN-07 (request weight), B1-WR-04 (shutdown order); all are in `.planning/phases/16-paper-runtime-composition/deferred-items.md`.
- Not inspected, so no verdict: journal.py, notify.py, surface.py, replay_inputs.py, evidence_bundle.py, evidence_export.py, attribution.py, the reservation lifecycle of shadow_ledger.py (612-1020), the freeze-tick half of coverage.py (717-1563), the bodies of shadow.py and shadow_confirm.py, paper_ws.py 1-189.
- `load_pinned_state` does not recompute `epoch_id` from the tuple (freeze.py:936-951). The start compares the file with the stored pin record field by field (restart.py:429-444), so a hand-edited file is refused there, but the freeze CLI alone would accept it.

## Appendix: working notes of the run (kept as written)
### Working notes (group 1: runtime, runtime_config, paper_ws, supervisor, resync, pipeline, bars, market_inputs, config/paper)
Coverage so far: runtime.py DEEP, runtime_config.py NORMAL (head + outline), adapters/paper_ws.py DEEP (190-843), supervisor.py DEEP,
resync.py DEEP, pipeline.py DEEP, bars.py DEEP, market_inputs.py DEEP, config/paper/* DEEP.

Safe (verified):
- BINANCE_* refusal: `refuse_trade_capable_env` (runtime_config.py:113-119) is the first check of `main` after the two read-only probes
  (runtime.py:1524-1529), before allowlist, DB engine, Telegram; `_healthcheck` repeats it (1383-1385). Only os.environ is read (no dotenv in src/paper).
- No order path by imports: probe `tmp/paper_runtime/imp_probe.py` imports all 31 src.paper modules + paper_ws + telegram_callbacks + shadow stores:
  the only `src.execution*` modules loaded are `src.execution` (__init__, order-id derivation, pure) and `src.execution.placement`
  (pure price derivation imported by src/backtest/entry.py:32 and exits.py:28). No src.live, no src.reconcile, no signed adapter module
  (binance_client is imported by binance_public but constructed with api_key=None, api_secret=None at binance_public.py:413).
- WS adapter: public PROD market stream only (paper_ws.py:336), never an account/order endpoint.
- Closed-candle only: supervisor.py:335 drops forming klines; cursor is monotonic under a lock (246-260); duplicates dropped (349-356).
- Reconnect: drop -> WS_DISCONNECT -> bounded rebuild -> REST backfill from cursor; exhausted rebuild -> backfill -> on_fatal -> exit 7 (483-499).
- Backfilled bars never evaluated (pipeline.py:382-384), each is one PAPER_GAP; resync never fabricates (resync.py:313-344).
- Pipeline conflicting duplicate raises -> consumer fails closed (pipeline.py:337,354; runtime.py:1011).
- History continuity gate before any evaluation (pipeline.py:514, 550-563).
- Full queue / failed write / pipeline error -> exit 7 without RUNTIME_STOP (runtime.py:861-863, 873, 1169-1171, 1722-1724).

Candidate findings:
- KNOWN:16-REVIEW-batch1 IN-01 FUTURE_CLOSE drop (pipeline.py:304-313): cursor already advanced, no PAPER_GAP, no re-queue; D-35 skew has no threshold
  (market_inputs.py:216-226). Consequence beyond what the review says: next live bars fail `_history_is_continuous` for WARMUP_MIN_BARS=200 bars (loop.py:193).
- Live closed bar that arrives while a recovery is pending is held (supervisor.py:337-341); if the backfill also returned it the backfill copy wins the cursor
  (610-614) and the held live copy is dropped as duplicate (349) -> bar is REST_BACKFILL -> never evaluated. Includes verify_start_seam at every start.
- REST backfill/warm-up "closed" filter uses the HOST clock (resync.py:300) -> host ahead of exchange accepts a forming row as closed.

### Working notes (group 2: freeze.py DEEP)
- Frozen by the pin: (strategy_id, parameter_set_id, parameter_set_hash, opened_at_utc) -> epoch_id (freeze.py:373-395), plus the config identity in
  EPOCH_PINNED (runtime.py:1613-1620). `_admit` re-hashes the registry file at every start (runtime.py:422-432); pipeline refuses a set whose hash
  differs from the epoch (pipeline.py:257-261). Rollover in `run_check_cli` rewrites the pinned file with the new hash (freeze.py:1030-1032), after
  which the runtime refuses (hash != allowlist entry, runtime.py:1663-1671) and the allowlist CLI returns 1 (freeze.py:1010-1018): fail closed.
- Candidate: the pin carries NO code/build identity; no src/paper record names a commit or image (grep IMAGE_COMMIT|code_version|commit over src/paper
  and scripts/evaluate_trial_soak.py, scripts/export_soak_evidence.py: no hit). To confirm against TRADING_APP_REVISION use.
- KNOWN IN-02: write_pinned_state non-atomic (freeze.py:933).

### Working notes (group 3: restart.py DEEP, loop.py NORMAL (gates 150-330), shadow_fill.py DEEP, live_minutes.py DEEP, shadow_runtime.py DEEP 520-1310)
Safe:
- Restart: start never mints an epoch; pin file must equal the latest EPOCH_PINNED across all epochs + same config identity (restart.py:394-458).
  Downtime closes become PAPER_GAP (PLANNED_RESTART/CRASH/EXCHANGE_NO_CANDLE) (149-193); warm-up bars are history only; fence at snapshot (466-477).
- SHADOW fills are the SAME engine functions as the backtest, not a fork: `advance`, `booking_for_event`, `funding_events`, `build_trade_record`,
  `protective_levels_for_fill`, `new_plan_state` imported from src/backtest (shadow_fill.py:38-61). Only difference: eligibility start = confirm
  instant floored + 1 minute (127-175), an intended human-delay difference.
- Minute source: forming minute refused, stored minute never overwritten, holes stay holes (live_minutes.py:83-134); settled watermark = now - close_lag.
- Restart of SHADOW: pending approvals/confirms expired with RUNTIME_RESTART; lost risk-passed signals journaled, never alerted (shadow_runtime.py:969-1060).

FINDING CANDIDATE G-1001 (CONFIRMED by probe tmp/paper_runtime/poll_probe.py):
- `_restore_positions` (shadow_runtime.py:1070-1079) takes EVERY SHADOW_POSITION_OPENED record of every approved SHADOW approval in the database
  (`load_records`, shadow_ledger.py:1022-1029; `list_approved_approvals` is mode-scoped, not epoch-scoped, persistence/shadow_stores.py:193-221),
  closed positions included, and polls 1m trade+mark minutes from the EARLIEST eligibility start per symbol.
- `LiveMinutePoller._fetch` raises `LiveMinutePollError` after `_MAX_PAGES = 20` pages of 1500 (live_minutes.py:51-52, 320-335) = 30,000 minutes = 20.83 days.
- Probe output: 20 days OK (20 pages), 21 days -> "LiveMinutePollError: trade minutes of BTCUSDT are more than 20 pages behind".
- So: once the first filled SHADOW position of a symbol is older than 20.83 days, every start fails in `shadow.start` -> RuntimeFailClosed
  ("the SHADOW chain failed to start", runtime.py:1120-1125) -> exit 7 -> restart policy loops. Each failed start spends up to 20 pages x weight 10 per symbol.
- Same budget in-run: a new position on a symbol whose last stored minute is > 20.83 days old (cursor = last stored + 1 min, live_minutes.py:312-313).
- KNOWN partially: 16-REVIEW-batch1 IN-07 names the weight and "never trimmed" only, rated Info "none changes ... the 14-day trial"; the permanent
  start failure and the cross-epoch replay are not recorded.
- Also not epoch-scoped: a new pin on the same database replays the earlier epoch's positions into the new epoch's ledger (to verify).

### Working notes (group 4: exit_criteria.py DEEP 1-810 + outline, coverage.py DEEP 1-716, shadow_ledger.py NORMAL (restore 1022-1225, head))
Safe:
- Exit criteria read one bundle, no clock; freeze and runtime evidence kept apart; REST_BACKFILL/REST_WARMUP processed rows are flagged as fabricated
  (exit_criteria.py:605-627); duplicates flagged (703-730); every expected close needs a processed or gap record (748-772).
- Coverage: only HEALTHY time counts; a gap with a reason is still uncovered (coverage.py:655-683); integer-microsecond comparison (316).

FINDING CANDIDATE G-1002 (PROBABLE, traced): `load_records` is not epoch-scoped; a booking of an earlier UTC day than the new epoch's ledger start raises
  "cannot roll the ledger backwards" (src/backtest/ledger.py:144-148) inside `rebuild_from_records` -> `_replay_positions` (shadow_ledger.py:1196-1199)
  -> shadow.start fails -> exit 7 at every start of a NEW epoch pinned on a database that holds a filled SHADOW position of an earlier epoch.
  Same UTC day: the old epoch's PnL is booked into the new epoch's equity. RUNBOOK 20 (line 726) tells the owner a changed value "needs a new pin", no fresh DB.

FINDING CANDIDATE G-1003 (CONFIRMED by probe tmp/paper_runtime/cov_probe.py): ceiling 900 s vs hourly health evidence.
  runtime declares DISCONNECTED at every start (runtime.py:1071-1077) and HEALTHY only at the first LIVE closed bar (852-858); coverage step 4 also
  counts run.start -> first message as uncovered (coverage.py:650). Probe (5 symbols, 14 d window, ceiling 900):
   A pin 10:00:00 start 10:00:30, no restart      -> longest uncovered 3600.299 s, ceiling_pass=False (coverage 0.99702 pass)
   B pin 10:50:00 start 10:50:30, no restart      -> 600.299 s, ceiling_pass=True
   D as B + one 60 s planned restart at 12:20     -> 2400.299 s [PLANNED_RESTART, WS_RECONNECT_WINDOW], ceiling_pass=False
   E as B + one 60 s planned restart at 12:50     -> ceiling_pass=True
  RUNBOOK 709 names only the pin->start time. 16-DEC-O-07 line 7 shows the silence value was moved 15 -> 3900 for exactly this hourly cadence; the ceiling was not.
FINDING CANDIDATE G-1004 (CONFIRMED by same probe, scenario C): a close between the pin and the first RUNTIME_START has neither a processed nor a gap
  record (downtime_gaps skips a pair with no processed bar, restart.py:172-174; probe prints `()`), so "no missing journal row" fails (5 rows).

## DONE
