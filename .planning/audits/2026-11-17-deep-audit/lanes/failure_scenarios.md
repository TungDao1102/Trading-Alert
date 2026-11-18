# Lane X01: failure_scenarios

## Scope

FMEA over the order lifecycle (signal -> plan -> notify -> APPROVE -> CONFIRM -> intent -> POST entry
-> fill(s) -> stop -> TP -> exit -> journal -> reconcile) at snapshot `55885b9`. Not a module read:
end-to-end sequences across module boundaries and crash/outage windows. Builds on the finished
lanes M02 (G-02xx), M03 (G-03xx), M04 (G-04xx), M05 (G-05xx), X09 (G-21xx), M01 (G-01xx); their
IDs are cited, not re-reported. IDs of this lane: G-1800..G-1899.


## Progress notes (working, kept for a resumed run)

- Read: LANE_BRIEF, charter, LANES X01, the findings of M01-M05 and X09 (JSON summaries + G-0300,
  G-0301, G-0403, G-0502, G-2100 in full).
- Harness found: `tests/support/live_smoke_env.py::build_fake_smoke_env` (the REAL `build_wiring`
  composition over in-memory stores + `BinanceSemanticsFakeAdapter`, with `restart()`), driven by
  the project's Phase 25 scenario modules `tests/support/demo_scenarios/s01..s19` (the project's
  own FMEA twin: S07 restart cuts a/b/c, S08 stream loss, S11 DB outage, S12 daily stop, S16
  manual close, S18 unprotected). `tests/support/protection_doubles.py::make_rig` for the
  coordinator alone. The rig uses TEST_ONLY limits (max_unprotected 7777 ms, tick 1234 ms).
- Start sequence read (`src/live/startup.py:842-1128`): HOLD steps = CONFIG, GATE, ALEMBIC,
  SAFE_MODE, ENABLEMENT (nothing is started on a hold, protection included); every later step
  degrades into SAFE_MODE and monitoring continues. Compose `live`: `restart: "no"`,
  `--hold-on-refusal`, `depends_on: db-upgrade completed`.
- Probes planned (tmp/failure_scenarios): P1 crash while the entry rests + fill while down +
  restart; P2 lagging position reads end-to-end with the reconcile loop; P3 emergency close
  unknown, then owner flattens by hand / restart; P4 DB down at fill, then restart; P5 start hold
  with an open position; P6 DAILY_STOP with a resting entry (S12 twin exists).

- P1 done (`tmp/failure_scenarios/p1_crash_resting.py`, `p1.out`): crash while the entry rests,
  fill while down, restart after 5 s and after 3600 s: both restarts restore AWAITING_FILL, the
  first protection tick finds the fill by REST and places the stop; state COMPLETE two ticks later;
  the start's reconcile tick is not clean -> SAFE_MODE, entries not enabled. The unprotected
  deadline is counted from the detection, not from the fill (no market close after a long outage).
  During the outage: position, zero stops (G-2100 confirmed by probe).
- P2 done (`p2_lag_e2e.py`, `p2.out`): G-0300 on the composed process: lag 0.5 s and 3 s both end
  plan FLAT in the first tick, 3 cancels by the own sweep, reservation RELEASED, reconcile enters
  SAFE_MODE UNSYNCED_POSITION / POSITION_WITHOUT_STOP with ONE critical alert then
  ALERT_SUPPRESSED; after a restart the plan is not restored (None), position 0.006 with no stop.

- P3 / P3b done (`p3_close_unknown.py`, `p3b_after_manual.py`, `.out`): composed process, stop
  rejected -2021, close POST raises a timeout before send. Result: CLOSE_FAILED,
  PENDING_UNKNOWN/ABSENT_AFTER_AMBIGUOUS_SEND, 1 close POST for 300 ticks; reconcile re-alerts
  UNPROTECTED_POSITION once per dedupe window (44 alerts / 300 s at the rig's 6.5 s window; real
  window 300 s) - so the alert DOES repeat in the composed process (correction to G-0301 "one
  alert"); `/close` -> token, then CLOSE_ALREADY_REQUIRED; restart -> still CLOSE_FAILED
  (closer ATTEMPT_HISTORY_NOT_TERMINAL), no POST. NEW: after the owner flattens by hand the plan
  stays CLOSE_FAILED for 31 h and across a restart, reservation stays RESERVED, blocks entries,
  `/safemode_exit` refused (COMPARE_NOT_CLEAN, BLOCKING_PROTECTION_STATE). RUNBOOK has no
  procedure for it (grep CLOSE_FAILED / PENDING_UNKNOWN: only the exit row list, line 1034).
- Operator surface (`src/live/operator.py:195-205`): status, disable_entries, safemode_exit,
  close, confirm. `/close` works only on a plan the coordinator holds open (`_closable_plan`
  420-436); `emergency_manual_close` (manager.py:2826) has no live caller (only `src/ops/drills.py`).


## Coverage

This lane is a scenario lane: the files below were read for the paths the scenarios cross, not as
module reviews (those belong to M02-M06).

| File | Level | Note |
|---|---|---|
| `src/live/startup.py` | NORMAL_READ | 1-110, 182-190, 784-1128 (step order, HOLD steps, degrade vs hold, recovery, first tick, enable) |
| `src/live/runtime.py` | NORMAL_READ | 197-250, 548-644 (hold on refusal, what a hold starts, runtime failure -> refusal) |
| `src/live/scheduler.py` | NORMAL_READ | 196-262 (task loop, a failing task never ends the loop, stall watch is observe-only) |
| `src/live/operator.py` | NORMAL_READ | 195-360, 420-436 (the five commands, `/close` preconditions) |
| `src/execution/emergency_close.py` | NORMAL_READ | 472-545, 790-873 (pending attempt polled first, hold, restore_pending) |
| `src/execution/protection.py` | NORMAL_READ | 1190-1228, 1937-2015 (operator_close, stop placement and the pre-send refusal); the rest through probes and lane M03 |
| `src/adapters/binance_ratelimit_gate.py` | METADATA_ONLY | refusal classes only (98-141) |
| `docker-compose.yml` | NORMAL_READ | 198-246 (`live` service: restart "no", `--hold-on-refusal`, depends_on) |
| `config/execution/execution-limits-v1.toml` | NORMAL_READ | the committed limits used to translate rig time into real time |
| `docs/operations/RUNBOOK.md` | METADATA_ONLY | grep for the end states of the scenarios (22.5 line 1182; 21.1a line 1034; no entry for CLOSE_FAILED/PENDING_UNKNOWN, UNSYNCED_POSITION, POSITION_WITHOUT_STOP) |
| `.planning/phases/25-demo-integration-test-campaign/` (`25-DEFERRED.md`, `25-OWNER-DECISIONS.md`, `25-32-PLAN.md`, plan objectives 25-19..25-33) | NORMAL_READ | what the project already knows about its own scenarios |
| `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md` | METADATA_ONLY | rows Q4, WR-03 |
| `tests/support/live_composed_rig.py`, `live_smoke_env.py`, `fault_edge.py`, `protection_doubles.py`, `execution_limits.py` | NORMAL_READ | the harness the probes drive |
| `tests/support/demo_scenarios/` s04, s06, s07, s08, s11, s12, s16, harness | NORMAL_READ | docstrings and the helpers reused by the probes; s01-s03, s05, s09, s10, s13-s15, s17-s19 METADATA_ONLY |
| `tests/test_demo_twin_s02/s05/s06/s07/s08/s09/s10/s16_*.py` | RUN | all passed with one expected failure (x) in the snapshot (no cache, no database) |
| `src/reconcile/*`, `src/execution/manager.py`, `src/execution/daily_stop.py`, `src/risk/*`, `src/adapters/binance_usdm.py`, `src/adapters/binance_userdata_supervisor.py` | NOT_READ here | exercised through the composed process in the probes; read by M02-M07 |

Probes (all under `tmp/failure_scenarios/`, each with its `.out`): `p1_crash_resting.py`,
`p2_lag_e2e.py`, `p3_close_unknown.py`, `p3b_after_manual.py`, `p4_db_down_fill.py`,
`p5_restart_hold.py`, `p6_daily_stop.py`, `p7_close_lost_answer.py`. They drive
`build_fake_scenario_env` = the REAL `build_wiring` composition (coordinator, closer, reconcile
loop, safe mode, stream router, day risk, operator commands, start sequence) over in-memory
stores and the project's `BinanceSemanticsFakeAdapter`. Limits in the rig are TEST_ONLY
(`max_unprotected_ms` 7777, `emergency_close_poll_timeout_ms` 6161, alert dedupe 6543, one tick
= 1 virtual second); the committed values are 180000, 30000, 300000 and a 15000 ms tick. What a
probe shows is the SEQUENCE of states and sends, not real-time durations. SYNTHETIC evidence:
nothing here was observed on Binance.

## Scenario table (FMEA over the lifecycle)

Verdict: SAFE = money is protected and the system recovers or stops with an alert; EXPOSED = a
position can exist without a stop for an unbounded or human-bounded time; STUCK = safe for money,
but the system cannot return to work through any documented path; KNOWN = recorded by the
project. "probe" = driven in this lane; "twin" = the project's own scenario test, run here;
"cited" = taken from another lane after reading its evidence; "reasoned" = code read only.

| # | Trigger | Expected safe outcome | Actual outcome | Evidence | Verdict |
|---|---|---|---|---|---|
| 1 | Process dies while a GTD entry rests; the entry fills while it is down | A stop exists on the exchange, or the entry cannot fill | Position with zero stops for the whole outage. Loss bounded only by the isolated margin / liquidation (G-2100: about 17R at 5x). Restart: plan restored AWAITING_FILL, first protection tick finds the fill by REST, stop placed and confirmed, TP legs follow; SAFE_MODE from the not-clean start tick; entries not enabled. The unprotected deadline counts from detection, so a late restart protects instead of closing | probe P1 (5 s and 3600 s outage give the same sequence) | EXPOSED during the outage (G-2100); restart itself SAFE |
| 2 | Same as 1, and the database cannot be read when the process starts again | Protection of the existing position does not depend on anything but the exchange | ALEMBIC is a HOLD step: `admitted False`, nothing is started, no stream, no scheduler, no stop. With `--hold-on-refusal` the process then waits for a stop signal for ever; no retry | probe P5; `src/live/startup.py:182-184, 920-937`; `src/live/runtime.py:565-570, 644` | EXPOSED until a human acts: G-1800 |
| 3 | Graceful stop / deploy with a resting entry | The entry is cancelled or protected | Not cancelled (RUNBOOK 22.5 procedure instead) | cited: KNOWN:24-DEFERRED R-22, G-2100 | KNOWN, EXPOSED |
| 4 | Process killed after the intent row, before or during the entry POST | At most one entry; unknown stays unknown | One `place_entry` across both processes; found -> ACKED and tracked; not found or probe error -> UNKNOWN + SAFE_MODE, nothing re-sent | twin S07 cut a (run here, passes) | SAFE |
| 5 | Process killed between the fill and the stop | The second process protects | Rebuilt UNPROTECTED, stop placed under the same id; restart later than `max_unprotected_ms` -> market close | twin S07 cut b | SAFE (late restart leaves SAFE_MODE that needs 25-26, KNOWN:25-12-F1) |
| 6 | Process killed after the stop, before / after the TP legs | Nothing re-sent, state kept | Rehydrated in the same state, nothing sent, first tick clean | twin S07 cut c; P4 variant 2 | SAFE |
| 7 | Process killed during an emergency close whose order filled | Flat is recognised, no second close | The lost answer is resolved by the id query: FLAT, one close at the exchange; after a restart the plan is gone and the account flat | probe P7 | SAFE |
| 8 | Emergency close POST with unknown outcome that never reached the exchange | A reduce-only close is retried after a bounded wait, or the human can act through the system | CLOSE_FAILED / PENDING_UNKNOWN for ever (300 ticks, restart included): one close POST, zero stops. Reconcile repeats UNPROTECTED_POSITION once per dedupe window (300 s committed). `/close` + `/confirm` -> CLOSE_ALREADY_REQUIRED | probe P3; cited G-0301 | EXPOSED (G-0301). Added here: the alert does repeat in the composed process |
| 9 | Row 8, then the owner flattens by hand on the exchange | The plan ends FLAT, entries can be enabled again | The closer never reads the position while an attempt is held: plan stays CLOSE_FAILED for 31 h and across a restart, reservation stays RESERVED, `blocks_new_entries` True, `/safemode_exit` refused `COMPARE_NOT_CLEAN, BLOCKING_PROTECTION_STATE` | probe P3b; `src/execution/emergency_close.py:512-516, 815-819` | STUCK: G-1801 |
| 10 | Fill, then position reads that lag the fill (0.5 s and 3 s) | The position keeps its confirmed stop | First tick: PROTECTED -> FLAT, the own sweep cancels the stop (3 cancels), reservation RELEASED, `blocks_new_entries` False. Next reconcile tick: SAFE_MODE UNSYNCED_POSITION / POSITION_WITHOUT_STOP, ONE critical alert, then ALERT_SUPPRESSED until the window ends. Restart: the plan is not restored at all; position 0.006, no stop, nothing placed | probe P2; cited G-0300 | EXPOSED (G-0300). Added here: the reconcile detects it within one tick but only alerts; a restart does not heal it; `/close` has nothing to close |
| 11 | User-data stream silent or down around a fill | The fill is found by REST | Every AWAITING_FILL plan is queried by client id each protection tick (15 s committed); stream loss -> reconnect, snapshot, SAFE_MODE at the silence bound (420 s) | twin S08; P1 (fill found with no frame at all); cited M03 safe area | SAFE, bounded by one tick + one step |
| 12 | Database unavailable when the resting entry fills | The stop does not wait for the database | Stop placed and REST-confirmed in the first tick with all 86 store methods failing; SAFE_MODE on; plan PROTECTED (TP legs wait); after the database is back: TP legs placed, COMPLETE, `/safemode_exit` works. Crash during the outage + restart with the database back: plan restored, same stop id adopted, 3 algo orders in total, no duplicate, no close | probe P4 (both variants) | SAFE |
| 13 | SAFE_MODE entered while the database is unavailable, then restart | SAFE_MODE is still on | Lost when the journal write fails first | cited G-0502 (probe of M05). In P4 the restart came back in SAFE_MODE, but only because the start tick was not clean | cited, MEDIUM on mainnet |
| 14 | Database unavailable at approval / CONFIRM | No order | Not probed here | cited M02 (intent write precedes the POST) | reasoned |
| 15 | DAILY_STOP threshold passed while an entry rests | The entry is cancelled, an alert is sent | Loss 54.99 known to the day service against a threshold of 49.99: for 30 ticks nothing is latched, nothing cancelled, no alert; the entry then fills, is protected, and still nothing is latched | probe P6; cited G-0403, KNOWN:25-15-F1 (plan 25-28 not executed) | KNOWN, EXPOSED to one more full-risk position per resting entry |
| 16 | Partial fill, then GTD expiry / cancel race / fill after cancel | One closePosition stop covers whatever filled | As expected | twins S02, S05 | SAFE (cost: G-0302 TP_UNAVAILABLE on small partials) |
| 17 | Stop rejected (-2021 crossed, -4509) | Reduce-only market close | One close, FLAT | twins S03/S04 not re-run here; P7 uses the same path | SAFE |
| 18 | 429 / 418 while a position needs its stop or its close | Protective orders are not blocked by the system's own gate, or the residual is accepted with numbers | Stop and close are refused before send for the length of the ban (`PreSendRefusal`, `src/execution/protection.py:1983-1995`); a durable PENDING row; the deadline keeps running | reasoned; KNOWN:19-OWNER-GAPS Q4 / D081. The rig cannot show it (orders bypass the real gate) | KNOWN, EXPOSED for the ban length |
| 19 | Owner closes the position by hand while the plan is protected | FLAT recorded, legs swept, no orphan | As expected | twin S16 | SAFE |
| 20 | CONFIRM twice / replayed callback | One entry | One entry | twin S06 | SAFE |
| 21 | Clock skew, -1021 | Refused before send | As expected | twin S09 | SAFE (the approval is spent: G-0205) |
| 22 | APPROVE at the last second; approval while SAFE_MODE is being entered | No entry on a stale gate | Gates are read once, about ten awaits before the POST | cited G-0201 | cited, MEDIUM on mainnet |
| 23 | Two plans approved together | Both judged against the caps | The second is refused while any position is open | cited G-0401 | cited |
| 24 | Day roll at 00:00 UTC with an open position; funding settlement; liquidation of the position | Day base and loss stay correct; a vanished position ends FLAT | NOT TRACED in this lane (UTC only: no DST path exists) | - | not inspected |
| 25 | Leverage / margin type / position mode changed outside the system after the fill | Detected | Position mode and margin are read at placement only (M02); not part of the reconcile compare (M05 open question) | cited | not inspected further |
| 26 | Runtime failure of the process itself (scheduler ends, exception out of the run) | Restarted, or the positions stay protected | `shutdown_in_order`, then the same hold as a refused start: the process stays up, non-operational | reasoned: `src/live/runtime.py:593-594, 644` | part of G-1800 |

## Verified Safe Areas

| Rule or behaviour | What was checked | Where | Why it holds |
|---|---|---|---|
| A restart protects a position that was filled while the process was down, however long the outage | probe P1: 5 s and 3600 s | `src/live/startup.py:991-1028` (recovery), protection step | the plan is restored AWAITING_FILL, the entry is polled by id, `executedQty > 0` is a first fill; the deadline starts at detection, so the stop is placed, not a market close |
| A not-clean start still runs protection | P1, P4: `RECONCILE=FAILED` then `BOT=OK, SCHEDULER=OK` | `src/live/startup.py:1031-1066` | only CONFIG, GATE, ALEMBIC, SAFE_MODE, ENABLEMENT hold; every later failure degrades to SAFE_MODE and the scheduler is started |
| The stop does not wait for the database | P4: 86 store methods raising, stop placed and confirmed in the first tick, SAFE_MODE on | coordinator `_store_write` | store failures are swallowed into SAFE_MODE DB_FAILURE; the POST follows |
| No duplicate protective order across a crash and a database outage | P4 variant 2: 3 algo orders in total after the restart | deterministic ids, query-first | the restored plan adopts the stop it finds |
| A close whose answer is lost but which filled is recognised | P7, with and without a crash | `src/execution/emergency_close.py:790-835` | the attempt is queried by its id before anything else; FILLED -> CLOSED -> two zero reads -> FLAT |
| An unknown close is never re-sent, in the same process or after a restart | P3: one POST over 300 ticks, `/close`, a restart and 20 more ticks | `emergency_close.py:472-480, 512-516` | this is the documented rule (D080); whether the rule is right is G-0301 |
| One entry per approval across restart cuts, replays and double CONFIRM | twins S06, S07 (run here) | - | pass |
| A failing scheduler task does not stop the others | P4 (`confirm_ttl_sweep`, `reservation_release_sweep` raise each tick; protection and reconcile run) | `src/live/scheduler.py:239-262` | each task has its own loop and a catch-all |
| The exposure of rows 8 and 10 is not silent | P2, P3 | reconcile loop + alert dedupe | UNPROTECTED_POSITION is re-raised each tick and passes the dedupe once per window |

## Decision review

| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D-08 start order: recovery, then stream, then one reconcile tick, then scheduler | SOUND | probe P1/P4 | a restart with an unprotected position ends protected in the first protection tick |
| D-08 failure classes: ALEMBIC / SAFE_MODE / ENABLEMENT failures HOLD "nothing is started" | DOUBTFUL | logic; owner goal (part-time) | right for entries; wrong for an account that may hold a position without a stop, because the hold also withholds protection and never retries (G-1800) |
| D-03 `--hold-on-refusal`: hold instead of exit so no restart policy crash-loops | DOUBTFUL | logic | it also turns a transient start failure and any runtime failure into a permanent stop, which removes the benefit of `restart: unless-stopped` exactly when a position is open (G-1800) |
| D106 / O-2 `restart: "no"` for the live service | DOUBTFUL | arithmetic (G-2100: outage loss about 17R) | cited from X09; P1 shows the restart path is the one thing that works without a human |
| D080 applied to the emergency close (never a second close while one is unknown) | DOUBTFUL | cited G-0301; P3b | beyond G-0301: the same hold also stops the closer from seeing that the account is already flat (G-1801) |
| Unprotected deadline counted from detection after a restart | SOUND | probe P1 (3600 s) | closing a position at market because the process was away would add a loss; placing the stop is the smaller harm; a crossed stop is rejected and closes anyway (S03/S04) |
| Stop first, records after (R-24, `risk_first`) | SOUND | probe P4 | holds with the whole store set failing |
| D-02 "never cancel or close what the system cannot prove it owns" (reconcile alerts only) | SOUND as a rule, with a cost | P2 | after the false FLAT of G-0300 the system no longer "owns" its own position, so the one detector that sees it may not act |
| Plan 25-32 (not executed): `/close` on CLOSE_FAILED re-runs the coordinator's close step | DOUBTFUL as a cure for the unknown case | code read | the close step holds on the pending attempt (`emergency_close.py:513-516`), so the retry "that really acts" does not act when the attempt is PENDING_UNKNOWN; it helps only for definitive rejections (the S18 case) |

## Findings

### G-1800
- ID: G-1800
- Severity: LOW now (placement disabled, Demo, attended) / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED for the hold (probe P5 and code); PROBABLE for the host-reboot race (not observed on a host)
- Classification: DESIGN
- Category: crash/restart window / unprotected position
- Component: start sequence (`HOLD_STEPS`), `--hold-on-refusal`, compose `live` service
- File: src/live/startup.py
- Lines: 182-184, 920-937 (also 941-959); src/live/runtime.py:565-570, 593-594, 644; docker-compose.yml:207-209, 218-222, 232-235
- Rule: D-08 failure classes, D-03 (hold instead of crash-loop), D106 (restart policy), D042 condition 1; continuation of G-2100
- Known-prior: partly. G-2100 / KNOWN:20-DEFERRED and R-22 cover "an entry can fill while the process is down". Not recorded anywhere found: that the restart itself is refused when the database is not readable, and that a held process never tries again.
- Evidence: `HOLD_STEPS = frozenset({STEP_CONFIG, STEP_GATE, STEP_ALEMBIC, STEP_SAFE_MODE, STEP_ENABLEMENT})` (startup.py:182-184); the ALEMBIC step makes one read, `except Exception ... raise StartupRefused(CODE_ALEMBIC_UNREADABLE, ...)` (startup.py:921-928), and `if not await run.run(STEP_ALEMBIC, alembic): return` ends the sequence before RECOVERY, STREAM and SCHEDULER. `runtime.py:565-570`: `if not outcome.admitted: ... await shutdown_in_order(assembly); return _RunResult(LiveExitCode.STARTUP_FAILED, reason)`, then `return refuse(result.code, ...)` (644), which with `--hold-on-refusal` writes the held marker and waits for a stop signal. Compose comment: "the D-03 hold makes that safe: no code path exits 0 or crash-loops on a refusal, a refused start holds". The live service waits only for `db-upgrade` at `compose up` (`depends_on`, lines 233-235); whether a policy restart after a host reboot waits for PostgreSQL was not observed. Probe `tmp/failure_scenarios/p5_restart_hold.py` (entry rests, process dies, entry fills, restart with an unreadable database):
  ```
  admitted: False | held: ALEMBIC ALEMBIC_UNREADABLE | steps: CONFIG=OK, GATE=OK, ALEMBIC=HELD
  scheduler started: {'scheduler': 0, 'stream': 0} | assembly complete: False
  exchange: position [('BTCUSDT', '0.006')] | stops [] | stop POSTs 0
  ```
  The same restart with a readable database protects the position in the first tick (probe P1).
- Expected: whatever else is wrong, a process that starts on an account with an own position and no stop tries to protect it, or tries the start again; the remedy X09 names for G-2100 ("`restart: unless-stopped`, so the gap is seconds") should hold.
- Actual: one failed database read at start (PostgreSQL still starting after a host reboot, a connection limit, a revision mismatch after a deploy, an unreadable gate state file) parks the process for ever with nothing running. Protection needs the database at start because the plans live there. The same hold follows any runtime failure of the run ("the scheduler ended before a stop signal", an exception out of `asyncio.run`). The only signal is the held marker -> unhealthy probe -> the external heartbeat stops (alert to a person; RUNBOOK 11.9).
- Reproduction: `PYTHONPATH=<snapshot>;. python -B tmp/failure_scenarios/p5_restart_hold.py` (compare `p1_crash_resting.py`).
- Impact: mainnet example (X09's numbers): equity 1000, risk 5 USDT, notional about 440 USDT at 5x isolated. Host reboots at 02:00 with an entry resting; the entry fills at 02:10; the live container comes back before PostgreSQL accepts connections and holds. No stop exists until the owner reads the heartbeat alert and restarts by hand: the loss is bounded by the isolated margin (about 88 USDT, 17R), not by the plan. With `restart: "no"` (today) the outcome is the same by a shorter road.
- Why tests miss it: the restart tests and twins replace `alembic_revisions` with a stub that matches (`tests/support/live_smoke_env.py:148`); hold tests assert that nothing is started, which is the behaviour.
- Remediation (owner decision O-1): retry the read-only HOLD steps with a bounded backoff before holding; or let a hold that follows a failed dependency exit non-zero under a restart policy with a delay; or keep a minimal exchange-only safety pass for holds (alert with the position size). Together with G-2100: an exchange-side bound for a resting entry (countdown cancel, shorter GTD) removes the dependence on the restart.

### G-1801
- ID: G-1801
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED (probe)
- Classification: DEFECT
- Category: emergency close / stuck state / operator recovery
- Component: MarketEmergencyCloser (`close_position`, `_poll`, `restore_pending`), ProtectionCoordinator close flow, SAFE_MODE exit readiness
- File: src/execution/emergency_close.py
- Lines: 512-516, 815-819, 472-480 (also src/reconcile/safe_mode.py:954; src/live/operator.py:420-436)
- Rule: D080 item 1 (never re-send); 25-OWNER-DECISIONS.md:341 ("During CLOSE_FAILED the human action that works is a manual close on the exchange"); RUNBOOK 21.1a row 5; extends G-0301
- Known-prior: G-0301 (the unknown close is held for ever while the position is open) and KNOWN:25-11-F1 (`/close` answers CLOSE_ALREADY_REQUIRED). Not recorded: what happens after the human has flattened the account.
- Evidence: `pending = self._pending.get(entry.plan_hash); if pending is not None: kind = await self._poll(...); if kind is _Kind.PENDING: return self._hold(...)` (emergency_close.py:512-516) returns before `_read_position` (line 521). `_poll` answers PENDING for every `found is False` (815-819), and an order that never reached the exchange is never found. So the closer cannot learn that the position is zero. Probe `tmp/failure_scenarios/p3b_after_manual.py` (stop rejected -2021, the one close POST raises a timeout before send, then the owner closes by hand through the exchange):
  ```
  5 ticks after the failed close: plan CLOSE_FAILED | closer PENDING_UNKNOWN/ABSENT_AFTER_AMBIGUOUS_SEND | pos [('BTCUSDT', '0.006')] | stops 0
  +1 h after the manual flatten:  plan CLOSE_FAILED | closer PENDING_UNKNOWN/ABSENT_AFTER_AMBIGUOUS_SEND | pos [] | blocks_entries True | safe True
  +24 h after the manual flatten: plan CLOSE_FAILED | ... | pos [] | blocks_entries True | safe True
  reservations: ['RESERVED']
  after restart: plan CLOSE_FAILED | closer PENDING_UNKNOWN/ATTEMPT_HISTORY_NOT_TERMINAL | pos [] | blocks_entries True | safe True
  /safemode_exit -> Still in SAFE_MODE. Exit refused: COMPARE_NOT_CLEAN, BLOCKING_PROTECTION_STATE
  ```
  `p3_close_unknown.py` shows the same after `/close`, a restart and a manual close, and `/status` reading `protections: 1 open of 1 tracked` on a flat account.
- Expected: once the exchange shows no position (two zero reads, entry terminal), the plan ends FLAT, its reservation is released and the operator can leave SAFE_MODE; the manual close is the documented way out of CLOSE_FAILED.
- Actual: after the documented human action the system stays blocked for ever: the plan is CLOSE_FAILED, every later tick reports a divergence, the risk reservation stays RESERVED, `/safemode_exit` refuses, a restart restores the same state. No operator command or runbook step was found that ends it (`scripts/demo_clear.py` writes SAFE_MODE off directly, see G-0503; whether it touches the plan was not checked). The remaining exits are edits of journal / intent rows by hand.
- Reproduction: `PYTHONPATH=<snapshot>;. python -B tmp/failure_scenarios/p3b_after_manual.py`.
- Impact: money stays safe (entries blocked). The cost is that the first real incident of this kind ends trading until someone edits the operational database by hand, which is the kind of action the rest of the design forbids; on Demo it would stop a soak. Plan 25-32 (`/close` re-runs the close step) does not cure it: the re-run holds on the same pending attempt.
- Why tests miss it: S18 and the closer tests make the close fail with a definitive rejection (-2022), where the retry flattens; the unknown-outcome tests assert "nothing is re-sent" and stop there; no test flattens the account from outside while an attempt is held.
- Remediation: in `close_position`, when the pending attempt is UNKNOWN, still read the position; two zero reads with the entry terminal end the plan FLAT (nothing is sent, so D080 is untouched) and mark the attempt abandoned. Add the runbook step for CLOSE_FAILED.

## Additions to findings of other lanes (no new ID)

- **G-2100 (X09), by probe P1.** Confirmed end to end: position 0.006 with zero stops for the
  whole outage; the restart heals it in its first protection tick for a 5 s and a 3600 s outage
  alike and comes back in SAFE_MODE with entries disabled. So for a crash the unprotected time is
  exactly the downtime plus the start sequence; nothing else bounds it. G-1800 is the case where
  the restart does not heal it.
- **G-0300 (M03), by probe P2 on the composed process.** The reconcile loop sees the result on
  its next tick (SAFE_MODE UNSYNCED_POSITION, then POSITION_WITHOUT_STOP, one CRITICAL
  UNPROTECTED_POSITION alert, repeats suppressed inside the dedupe window), places nothing, and
  the plan's reservation is released. A restart does not restore the plan (state None), so the
  restart that heals row 1 does not heal this. `/close BTCUSDT` has no open plan to act on
  (`_closable_plan`, operator.py:420-436). The position stays naked until the owner closes it in
  the exchange UI. A 0.5 s lag is enough; the 3 s lag gives the same sequence. The trigger (a
  real position-read lag) remains unobserved, as M03 says.
- **G-0301 (M03), by probe P3.** Two corrections of detail: (1) in the composed process the
  alert is not single: the reconcile loop re-raises UNPROTECTED_POSITION every tick and one
  passes the dedupe per window (44 delivered in 300 rig seconds at the rig's 6.5 s window; one
  per 300 s at the committed value); (2) a restart keeps the hold under another code
  (`ATTEMPT_HISTORY_NOT_TERMINAL`). The finding itself stands: one close POST in total.
- **G-0403 (M04), by probe P6.** With a known day loss of 54.99 against a stop threshold of
  49.99 the live process, left to itself for 30 ticks, latches nothing, cancels nothing and
  alerts nothing; the resting entry then fills and is protected, and the day is still not
  latched. In the probe nothing but a CONFIRM (or, per M04, the day opening at start) evaluates.
- **G-0502 (M05).** Probe P4 did not reproduce the loss of SAFE_MODE, because a restart after an
  outage that overlapped a fill re-enters SAFE_MODE through the not-clean start tick. The gap
  remains for reasons that leave no divergence behind, as M05 says.

## Owner decisions

1. **O-1: what should a restart do when it cannot read the database (G-1800)?** Today: hold for
   ever, nothing running. Example: equity 1000, a 440 USDT position filled during a host reboot,
   PostgreSQL slower to come up than the live container: no stop until you restart by hand; the
   loss is bounded by about 88 USDT of isolated margin instead of 5 USDT of planned risk.
   Options: retry the start for N minutes; exit and let a restart policy with a delay retry;
   keep the hold but add an exchange-side bound for resting entries (see G-2100 O-1).
2. **O-2: may the system declare a plan FLAT after a manual close while a close attempt is
   unknown (G-1801)?** Today: never; the database must be edited. The alternative sends nothing:
   two zero position reads with the entry terminal end the plan.
3. **O-3 (from rows 8 and 10): is "alert every 5 minutes, human closes in the Binance UI" the
   accepted answer for a position the system holds without a stop?** It is the only answer the
   code has for the end states of G-0300 and G-0301, and no runbook section describing it was
   found. The part-time owner (D034: "cannot react quickly") is the only actor. The number to
   decide is the time you accept between the first alert and your action, against a loss bounded
   by the isolated margin.

## Open Questions

- (M06 / host) The real duration of the start sequence (clock drift, exchange info, recovery,
  stream LIVE, one reconcile tick, bot start) is the unprotected time added to every restart; it
  is NOT_OBSERVED on a host. Does `start_bot` block the SCHEDULER step when Telegram is
  unreachable, and for how long? Not traced.
- (M06 / M12) Does a Docker policy restart of `live` after a host reboot wait for PostgreSQL?
  `depends_on` names only `db-upgrade`; not observed. This decides how likely G-1800 is.
- (M07) Does the composed adapter refuse `place_algo_protective` / `place_market_close` through
  the real gate exactly as `PreSendRefusal`? The rig serves those calls from the fake, so row 18
  rests on code reading and on the project's own Q4 record.
- (M04) Row 24: day roll with an open position, funding during a position and a liquidation
  were not traced here.
- (X08) No runbook section was found for the alerts UNPROTECTED_POSITION /
  EMERGENCY_CLOSE_FAILED with the end states of rows 8-10 (grep of `docs/operations/RUNBOOK.md`).
- (M03) In probe P4 the TP legs were not placed while the database was down (the plan stayed
  PROTECTED with its stop) and were placed when it came back; which store call the TP step
  waits on was not traced. Safe for money.
- The probes use the rig's TEST_ONLY limits; no claim about real-time durations is made from
  them. Position-read lag (G-0300) and by-id query lag are exchange facts no probe here can show.
- `tests/test_demo_twin_s11/s12/s13/s14/s15/s17/s18/s19` and S01/S03/S04 were not re-run in this
  lane (S11 and S12 behaviour was reproduced by P4 and P6 instead).

## DONE
