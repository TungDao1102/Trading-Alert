# Lane M06: live_composition

## Scope
`src/live/*` except `risk_inputs.py`, `reservation_release.py`, `commission.py`, `reconcile.py` (other lanes).
Snapshot `55885b9`. Questions: start sequence, one-loop scheduler and task failure, wiring completeness,
smoke injection reachability, operator commands, health/liveness truthfulness, Demo vs live endpoint selection.
Finding IDs G-0600..0699.

## Coverage
| File | Level | Note |
|---|---|---|
| src/live/runtime.py | DEEP_READ | CLI, probes, hold, production runner, shutdown order |
| src/live/config.py | DEEP_READ | admission, liveness stamp schema |
| src/live/scheduler.py | DEEP_READ | task loop, stall watchdog, cadences |
| src/live/wiring.py | DEEP_READ | composition root, specs, check_wiring |
| src/live/wiring_parts.py | DEEP_READ | small adapters, kill-gate sources, stall alert |
| src/live/startup.py | DEEP_READ | start sequence, restore glue |
| src/live/enablement.py | DEEP_READ | DEMO enable, kill-gate switch-off |
| src/live/smoke_injection.py | DEEP_READ | /demo_signal |
| src/live/exchange.py | DEEP_READ | exchange edge, one gate |
| src/live/operator.py | DEEP_READ | operator commands |
| src/live/health.py | DEEP_READ | health producer and tick |
| src/live/execution_service.py | DEEP_READ | CONFIRM to one `execute_approved_plan`; `outstanding` / `take_settling` |
| src/live/stream.py | DEEP_READ | fill fan-out, protection step body, stream assembly |
| src/live/feeds.py | DEEP_READ | mark book, feed source, divergence queue |
| src/live/order_index.py | DEEP_READ | client-id index |
| src/live/scheduled_cancel.py | DEEP_READ | expiry cancel, D110 restart cancel |
| src/live/signal_source.py | NORMAL_READ | lines 1-200 read (Protocol, request types); the smoke derivation arithmetic (200-648) NOT_READ |
| src/live/telegram_runner.py | NORMAL_READ | start/stop lifecycle only; press handling belongs to M08 |
| src/live/stream_persistence.py | NOT_READ | wiring call sites only (wiring.py:765-773, 795-801); see Open Questions |
| src/live/approval_sender.py | METADATA_ONLY | constructor wiring only (wiring.py:921-937); M08 scope |
| src/live/alerts.py | METADATA_ONLY | `build_alerts`, `drain_once`, `requeue_at_start` call sites only; M08 scope |
| src/live/__init__.py | METADATA_ONLY | 1 line |
| (excluded) risk_inputs.py, reservation_release.py, commission.py, reconcile.py | NOT_READ | other lanes |

Out-of-scope files read to trace callers: `src/paper/held_marker.py`, `src/ops/store_executor.py` (head), `src/execution/enablement.py`,
`src/adapters/binance_client.py:100-275`, `docker-compose.yml:225-245`, `24-DEFERRED.md` section D, installed `telegram/_bot.py:843-870`.
Probe: `tmp/live_composition/probe1.py` (output quoted in the findings).

## Verified Safe Areas
| Rule / behaviour | What was checked | Where | Why it holds |
|---|---|---|---|
| Mode is explicit, never inferred | `resolve_mode` accepts exactly `DEMO` / `LIVE`; a missing or other value is MODE_REFUSED | config.py:139-153 | dictionary lookup on the raw value, no strip, no URL sniffing |
| LIVE cannot start today (two independent guards) | (1) `parse_live_environment` refuses LIVE while `LiveEnablementController` defaults to disabled; (2) `build_exchange` passes `live_enablement=None` to `build_sdk_client`, which requires an enabled state for LIVE | config.py:126-128, 205-213; exchange.py:150-190; binance_client.py:24-25, 86 | the controller default is `_disabled=True` (execution/enablement.py:114) and nothing in `src/live` passes an enablement state to the SDK builder; LIVE needs a code change |
| Other mode's credentials refuse the start | `refuse_if_present=(credential_spec_for(_other_mode(mode)),)` | config.py:215-223 | a DEMO start with any `BINANCE_LIVE_*` name present is CREDENTIAL_REFUSED |
| Endpoint follows the mode | REST and WS URLs come from one `ENVIRONMENT_ROWS[mode]` row; the SDK object must report the same environment or the composition refuses | exchange.py:168-185; binance_client.py:153-172 | DEMO row = SDK demo REST constant + `wss://demo-fstream.binance.com`; LIVE row = SDK prod constants; TESTNET refused |
| Refusal texts carry names, not values | every `LiveRefusal` reason and `_refuse` print | config.py; runtime.py:236-252, 395-405 | fixed strings plus variable/key names or an exception class name |
| A hold never looks healthy | the marker is written before the wait; if it cannot be written the process exits instead of holding | runtime.py:196-229 | the probe reads the marker before the stamp (config.py:407-415) |
| Start order | CONFIG, GATE, ALEMBIC, SAFE_MODE, ENABLEMENT hold; later failures continue in SAFE_MODE; recovery before the stream; stream before the first tick; bot and scheduler after the tick; enable last and only with no degraded step, no journal failure and not in SAFE_MODE | startup.py:139-190, 880-1090 | `_enable` returns before `enable_demo` on `in_safe_mode or run.degraded or run.journal_failed` (startup.py:1077-1085) |
| Enablement never survives a restart | `start_disabled` always returns a fresh disabled controller and overwrites a stored "enabled" | enablement.py:166-204 | the stored snapshot is only probed, never used as the controller |
| No enable path besides `enable_demo` | grep of `.enable(` in `src` | enablement.py:253 only | `enable_demo` raises `LiveEnableForbidden` for any mode but DEMO before touching the controller |
| Kill gate only switches off | `on_kill_gate_verdict` calls `disable` only for INSUFFICIENT_EDGE | enablement.py:283-306 | no branch calls `enable` |
| Gate state is never re-initialised silently | flag + existing file = GATE_STATE_EXISTS; no flag + no file = GATE_STATE_MISSING; restore must be RESTORED_DURABLE | startup.py:905-945 | all three are HOLD outcomes |
| Wiring gate | `check_wiring` runs twice (step ENABLEMENT and after admission); the task-name set must equal `TASK_NAMES`; one REST gate object across 7 holders; one alert sink across 4 holders | wiring.py:652-656, 1388-1520; runtime.py:544-547 | identity (`is`) comparisons, not type checks only |
| `/demo_signal` exists in DEMO only | the builder returns None for non-DEMO or a non-smoke source; the constructor raises for non-DEMO; `check_wiring` fails if a non-DEMO wiring registers the command | smoke_injection.py:92-99, 288-300; wiring.py:1495-1503 | three independent checks; the command only queues a request, the APPROVE/CONFIRM flow still decides |
| `/demo_signal` authorisation | chat gate, then user id + private chat type, before any read | smoke_injection.py:206-237 | the same two gates as `on_callback`; a rejection is journaled with a fixed code |
| Operator commands | every handler calls `_authorize` first; two-step commands use a single-use token bound to the asking user, SHA-256 only in memory, TTL 60 s, at most 8 pending; no handler places an entry or enables | operator.py:226-330, 425-492 | `_take` checks hash, user, expiry, then deletes all same-kind asks; `enable` is not referenced in the module |
| `/disable_entries` acts before its audit row | `enablement.disable` flips first; the reply reports the real flag | operator.py:240-259 | the reply text is derived from `is_disabled` after the call |
| One placement call per CONFIRM | `_place` awaits `execute_approved_plan` once, no loop, no retry; ids are registered in the index before the await | execution_service.py:213-262 | single call site (also confirmed by lane exec_placement) |
| Scheduled cancel never cancels blind | expiry read, then a fresh REST read; only status NEW with executed quantity exactly 0 is cancelled; unknown / not found / partial is left to the coordinator | scheduled_cancel.py:186-240, 378-398 | `_left_reason` returns a reason for every non-resting case |
| A missed stream fill still gets a stop | `fills_reader=None` (wiring.py:802-810) means no REST fill replay, but the coordinator polls the entry by REST on every step (lane exec_protection: "AWAITING_FILL -> UNPROTECTED (stream fill or REST poll)") | wiring.py:802-810; exec_protection.md state table | worst case adds one protection period (15 s) to the unprotected window; not re-verified by this lane |
| Task isolation for ordinary exceptions | probe P2: 200 failing runs, the loop keeps going | scheduler.py:262-279 | `except Exception` per run; one asyncio task per spec |
| Stall watchdog does not cancel | `_watch_stall` only sleeps, logs, journals; the alert is raised in a `finally` so a journal failure does not lose it | scheduler.py:281-303; wiring.py:1029-1036 | consistent with "a placement is never re-sent" |

## Decision review
| Decision / doc rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D098 one process, one asyncio loop | SOUND | owner goals (single VPS, part-time), logic | one gate, one SAFE_MODE, one event order; the cost is that any synchronous call stalls everything (G-0607) and a dead scheduler ends all supervision (G-0601) |
| D094 stream before the first reconcile tick | SOUND | logic | the tick judges feed freshness; with the stream silent every clean start parked in SAFE_MODE; recovery still precedes the stream |
| D-08 hold vs degrade classes | SOUND, one exception | fail closed | no controller means no safe state to continue in; every later failure blocks entries and keeps monitoring. The BOT step is the doubtful member of the degrade class (G-0603) |
| D102 DEMO auto-enable at the end of a start; LIVE "keeps the human enable action" | DOUBTFUL | logic, owner goals | the DEMO part fits a rehearsal. The LIVE part names an action that does not exist (no command, no CLI; the row itself says "a LIVE enable path is not built"), and the row states a health gate after enable that is not built (G-0600) |
| D092 DEMO kill gate treated as WITHIN_BUDGET | SOUND for Demo only | owner goals | journaled on every enable; non-DEMO reads the persisted state and refuses when absent. Nothing writes that state yet, so LIVE could not enable: intended |
| D101 only the Demo smoke signal source | CANNOT_JUDGE, flagged | owner goals | the composition has never carried a strategy plan: `STRATEGY_ID`, `PARAMETER_SET_ID = "baseline-v5"`, `DEMO_SYMBOLS = ("BTCUSDT",)` are constants (runtime.py:422-424) and there is no bar feed. "21 of 21" proves the plumbing with a synthetic LONG (SL 1.5 %, back-solved equity), not the strategy path. Which phase builds it is undecided (D101 text) |
| D097 reconcile skipped while a placement is outstanding | DOUBTFUL | logic | it cures a real false positive by blinding the whole comparison (all symbols) with no upper bound (G-0604); lane reconcile_safemode G-0500 covers the underlying one-sighting rule |
| D104 operator command set and authentication | SOUND | practice, fail closed | risk-reducing commands need no second step, risk-raising ones do; no enable command; token bound to the user |
| D106 restart policy `no`, heartbeat per process | SOUND with a gap | owner goals | a dead live process is never restarted, so the external heartbeat is the only signal of a stopped process that holds a position; it is NOT_OBSERVED on a host and ignores task results (G-0602) |
| D111 / D114 stall watchdog observe-only, 60 000 ms | SOUND (mechanism); number CANNOT_JUDGE | arithmetic | not cancelling is right under the never-re-send rule; 60 s is one third of `max_unprotected_ms` 180 s, from about a dozen runs (max 886 ms). Only the protection task has a bound |
| D099 "every store call made on the event loop goes through StoreExecutor" | WRONG as written | code | false for the protection, close, placement, SAFE_MODE and operator paths (G-0607) |
| Liveness bound = `stale_feed.max_mark_price_age_ms` | DOUBTFUL | logic | a mark-price age is reused as the loop-liveness bound (runtime.py:258-267); 60 s against a 15 s stamp works, but lowering the mark age below about two ticks would make the heartbeat flap |

## Findings

### G-0600
- ID: G-0600
- Severity: LOW now (Demo, placement disabled on mainnet) / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED (grep + code trace)
- Classification: DRIFT (a canonical decision row states a gate that is not built)
- Category: health / enablement
- Component: `LiveHealthProducer`, `health_tick_once`, `LiveEnablementController`
- File: src/live/health.py; src/live/wiring.py; docs/DECISIONS.md
- Lines: health.py:358-360, 487-527; wiring.py:1091-1098; DECISIONS.md:60 (D056), 106 (D102)
- Rule: D056 item 1, D102
- Known-prior: KNOWN:24-22-SUMMARY.md:74 ("nothing in this plan disables an enabled DEMO controller on a RED health tick"); absent from 24-DEFERRED, and D102 says the opposite
- Evidence: D056 (1): "if the system is already enabled and health becomes DEGRADED, no new entry may be created until health returns to an allowed state". D102: "D056 rows as built ...: in LIVE a DEGRADED verdict cannot enable and blocks new entries once enabled". Code: `health_tick_once` stores the verdict (`producer._latest = verdict`), journals it and logs `live.health.not_ok`; `grep -rn "latest_verdict" src` returns only its definition (health.py:358). The enablement guard reads only the `_disabled` flag (execution/enablement.py). The health task body calls `kill_gate_tick_once` and nothing else (wiring.py:1091-1098). No alert is raised for a NO_TRADE verdict.
- Expected: after enable, a health verdict that is not OK blocks new entries.
- Actual: the verdict is consulted once, at the end of the start sequence. Afterwards a RED verdict changes nothing and alerts nobody. Most causes still block entries by another route (reconcile enters SAFE_MODE for a stale feed, a halted stream or a divergence; the manager has its own mark and equity checks), but `db_writes`, `rest_error_rate` and `telegram_delivery` have no second consumer.
- Reproduction: `grep -rn "latest_verdict\|health_tick_once" snapshot/src`.
- Impact: none now. On mainnet a process that was healthy at start keeps accepting CONFIRMs while 4 of 10 REST calls fail or while alerts cannot be delivered, and the owner who reads D102 believes health gates entries continuously.
- Why tests miss it: `tests/test_live_health.py` and `tests/test_live_enablement_wiring.py` test the verdict and the start-time enable; no test asserts a state change after a RED tick.
- Remediation: either build the second automatic caller toward `disable()` with a DECISIONS row, or correct D102 and add a 24-DEFERRED row; in both cases alert when the verdict changes to NO_TRADE.

### G-0601
- ID: G-0601
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED for the mechanism (probe P1); the trigger (a `CancelledError` raised inside a task body) was not observed
- Classification: DEFECT
- Category: scheduler / shutdown
- Component: `Scheduler._loop`, `shutdown_in_order`, `run_admitted`, `main`
- File: src/live/scheduler.py; src/live/runtime.py
- Lines: scheduler.py:229-242, 262-279; runtime.py:388-400, 497-500, 549-565, 598-604
- Rule: T-24-24 (failure isolation), D-03 (stop in order, hold instead of crash), runtime.py:482 "none is cancelled mid-send"
- Known-prior: none found
- Evidence: `_loop` catches `except Exception`; `run()` awaits `asyncio.gather(*loops)` without `return_exceptions`. `shutdown_in_order.step` catches `except Exception` around `asyncio.shield(task)`. `run_admitted` and `main` catch `except Exception`. Probe P1 output: `scheduler task done: True cancelled: True` / `protection_step runs before the scheduler died: 2` / `journal events: [('protection_step', 'first_run', None), ('mark_refresh', 'first_run', None)]` / `shutdown_in_order RAISED: CancelledError | steps run before it: []`.
- Expected: one task's failure never touches the others; an unexpected end of the scheduler stops the process in order and holds with the marker.
- Actual: a `CancelledError` (a `BaseException`) leaving any one of the 13 task bodies cancels all 13 loops and leaves no journal row. `_run_async` then calls `shutdown_in_order`, whose first step re-raises the same error: the bot, the stream supervisor (listen key), the queued stream writes, `service.drain()` and the executor close are all skipped. The error passes both `except Exception` handlers, so no refusal is printed and no held marker is written; `asyncio.run` then cancels whatever still runs, including a placement task in mid-send.
- Reproduction: `tmp/live_composition/probe1.py`, section P1.
- Impact: protection stepping, reconcile, scheduled cancel and alert delivery end at once and silently; with restart policy `no` nothing brings them back. An open position keeps only what already rests on the exchange; a resting entry is unwatched (the state R-22 describes for a deliberate stop, here without the owner knowing). The only signal is the external heartbeat going stale after 60 s (NOT_OBSERVED on a host).
- Why tests miss it: scheduler tests raise ordinary exceptions or cancel `run()` from outside; none raises `CancelledError` from inside a body, and none feeds a cancelled scheduler task to `shutdown_in_order`.
- Remediation: in `_loop`, treat a `CancelledError` that arrives while the loop task itself is not being cancelled as a task failure; in the scheduler step of `shutdown_in_order` catch `BaseException` (or gather with `return_exceptions=True`); raise a CRITICAL alert when the scheduler ends without a stop request.

### G-0602
- ID: G-0602
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED (probes P2, P3, P4)
- Classification: GAP
- Category: observability / health truthfulness
- Component: `Scheduler._note`, `alert_task_stall`, `ReconcileObserver`, `live_liveness_problem`
- File: src/live/scheduler.py; src/live/wiring_parts.py; src/live/health.py; src/live/config.py; src/live/wiring.py
- Lines: scheduler.py:305-336; wiring_parts.py:300-322; health.py:167-190; config.py:395-427; wiring.py:1179-1183
- Rule: OPS-04 (health truthfulness), D111
- Known-prior: partly KNOWN:24-DEFERRED R-28 / 24-REVIEW IN-03 (the liveness probe ignores the per-task PASS/FAIL). The missing alert and the stale reconcile check are not recorded.
- Evidence: P2: a task that raised on each of 200 runs produced exactly one journal event `('first_run', 'RuntimeError')`, and `alerts raised for first_run/failure/recovery events: 0`. P3: `ReconcileObserver` has two fields (`_latest`, `_compared`) and no time; `reconciled` stays True after the last clean tick for ever. P4: a stamp whose tasks are all FAIL gives `live_liveness_problem(...) -> None` (live). `_reconcile_tick` notes the observer only after `reconcile_tick_once` returns, so a tick that raises, hangs or is skipped (D097) leaves the old clean report in place.
- Expected: a supervision task that stops working is visible: an alert, a failing health check or a red heartbeat.
- Actual: when `reconcile_tick` (or `scheduled_cancel`, `day_risk_backfill`, `alert_drain`) raises on every run, or hangs in one run: one `LIVE_TASK_EVENT` row (none for a hang; only `protection_step` has a stall bound), no alert, `reconciliation_drift`, `unprotected_positions` and `orphaned_orders` PASS from the last good report, heartbeat green. `rest_error_rate` does turn FAIL for a raising task, but the verdict has no consumer (G-0600).
- Reproduction: `tmp/live_composition/probe1.py`, sections P2 to P4.
- Impact: reconcile is the backstop of the protection task (it turns a position without a stop into SAFE_MODE and an alert). If it dies quietly the owner keeps a green heartbeat and a clean health journal while nothing compares the exchange with the local state.
- Why tests miss it: the tests assert the journal contract (one row per outcome change), which is this behaviour; none asserts that a persistent failure reaches the owner.
- Remediation: alert (HIGH) at N consecutive failures of a task; give `ReconcileObserver` the time of the last compared tick and fail `reconciliation_drift` beyond about three intervals; let `--liveness` fail while `protection_step` or `reconcile_tick` is FAIL; give every REST-calling task a stall bound.

### G-0603
- ID: G-0603
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: PROBABLE (code trace against the installed PTB 22.8; not run)
- Classification: DESIGN
- Category: start sequence
- Component: start step BOT, `LiveTelegramRunner.start`
- File: src/live/startup.py; src/live/telegram_runner.py; src/live/runtime.py
- Lines: startup.py:185-187, 859-877, 1043-1049; telegram_runner.py:171-204; runtime.py:536-562
- Rule: D-08 failure classes; D104
- Known-prior: none found (24-REVIEW, 24-DEFERRED, 24-NOTES and RUNBOOK 22 searched for the BOT step)
- Evidence: BOT is not in `HOLD_STEPS`, so a failure calls `degrade` (SAFE_MODE `STARTUP_BOT_FAILED`) and the sequence goes on to SCHEDULER. `start()` runs `await application.initialize()` (one `getMe`, PTB `_bot.py:865`; `start_polling` default `bootstrap_retries=0`) and nothing calls `start()` again. If `initialize` raises, `self._application` stays None. If `start` or `start_polling` raises, `application.shutdown()` closes the bot's HTTP clients, after which a send through the bound proxy raises "This HTTPXRequest is not initialized!".
- Expected: a process without its operator channel either holds (visible: marker, red probe) or keeps retrying the bot.
- Actual: one failed Telegram call at start leaves the process running for its whole life with no polling: no APPROVE, no `/status`, no `/safemode_exit`, no `/close`. The SAFE_MODE it entered is durable, so the next start is in SAFE_MODE too and needs the bot to leave it. The liveness stamp is fresh, so the compose healthcheck and the heartbeat are green. In the `start_polling` branch no alert can be delivered either.
- Reproduction: trace `run.run(STEP_BOT, ...)` -> exception -> `degrade` -> next step; `_run_async` then waits on the stop event.
- Impact: the owner's network is recorded as flaky. A start during a short Telegram outage gives a process that looks healthy from outside and is deaf (possibly mute) while it may supervise a restored position; `/close` is unavailable exactly then.
- Why tests miss it: `tests/test_live_start_sequence.py` asserts the degrade class of a failing step, not what the running process can still do afterwards.
- Remediation: owner choice (Owner decisions 2): make BOT a hold step, or retry the bot start from a scheduler task and fail `--liveness` while the runner is not running.

### G-0604
- ID: G-0604
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: PROBABLE (code trace; the duration of a slow placement was not measured)
- Classification: DESIGN
- Category: reconcile cadence
- Component: scheduler `reconcile` body, `ExecutionService.outstanding`
- File: src/live/wiring.py; src/live/execution_service.py
- Lines: wiring.py:1064-1071; execution_service.py:162-205
- Rule: D097
- Known-prior: D097 is the decision; its bound is stated as a fact
- Evidence: `if service.outstanding or service.take_settling(): return`. `outstanding` is `len(self._tasks)`; `_tasks` holds every placement task until it finishes, plus the journal-row task of a failed placement. D097: "a placement delays the next compared tick by at most about two intervals".
- Expected: a bounded pause of the comparison, for the symbol being placed.
- Actual: the pause covers every symbol and lasts as long as any placement task is alive. "Two intervals" holds only when the placement ends within one tick; a placement that waits (signed-call retries, the ambiguous-result probe, a slow store call on the loop) extends the blind period by its whole duration, and a placement task that never returns stops reconcile for good with no alert (a skipped run is a successful run for the scheduler, G-0602).
- Reproduction: read wiring.py:1064-1071 with execution_service.py:191-194.
- Impact: with more than one symbol (Phase 25) a placement on symbol A suspends orphan sweeping, SAFE_MODE detection and pending-action handling for a position on symbol B.
- Why tests miss it: `tests/test_live_reconcile_settling.py` pins the skip and does not bound it.
- Remediation: cap the consecutive skipped ticks, or exclude only the symbol in flight; journal each skipped tick.

### G-0605
- ID: G-0605
- Severity: LOW now / LOW on mainnet (false-alarm direction)
- Confidence: CONFIRMED (probe P4 + grep)
- Classification: DEFECT
- Category: health probe
- Component: held marker lifecycle
- File: src/live/runtime.py; src/paper/held_marker.py
- Lines: runtime.py:196-229 (the only `remove_marker`); held_marker.py module docstring; src/paper/runtime.py:1691
- Rule: D-03 (the paper pattern the live runtime says it copies, runtime.py:3-6)
- Known-prior: none found
- Evidence: held_marker.py: "A successful start of the same container removes a marker left by a killed hold". P4: with a marker left behind and a fresh stamp, `live_liveness_problem` returns "the start was refused and this container is held (STARTUP_FAILED, exit 7)"; `remove_marker call sites in src/live/runtime.py: 1` (inside `_hold`'s `finally`). The paper runtime has the removal (paper/runtime.py:1691); the live runtime does not.
- Expected: a successful start clears a marker left by a hold that was killed (SIGKILL, OOM, power loss).
- Actual: after such a kill, `docker start` of the same container (same hostname, same marker file on the `livestate` volume) runs normally while `--liveness` and `--healthcheck` report held for ever.
- Reproduction: `tmp/live_composition/probe1.py`, section P4.
- Impact: a permanently red heartbeat on a healthy process; the owner learns to ignore it or deletes the file by hand.
- Why tests miss it: the live runtime tests cover a hold followed by a clean stop; none starts over a left-behind marker.
- Remediation: remove the own marker in `run_admitted` once the start sequence is admitted.

### G-0606
- ID: G-0606
- Severity: INFO now / LOW on mainnet
- Confidence: CONFIRMED (code read, probe P5)
- Classification: DEFECT
- Category: health probe
- Component: `main`, `parse_live_environment`
- File: src/live/runtime.py; src/live/config.py
- Lines: runtime.py:357, 361-377; config.py:268-272
- Rule: OPS-04
- Known-prior: none found
- Evidence: the running process anchors a relative `--state-dir` at the repository root (`directory = repo_root / directory`), while the probes and the admission-refusal hold use `args.state_dir` as given, relative to the caller's working directory (`state_dir: Path = args.state_dir`; default `logs/live`).
- Expected: the probe reads the directory the process writes.
- Actual: the two agree only when the probe's cwd is the repository root (true in the image). From another cwd the probe answers "no liveness stamp" (false red), and a hold after an admission refusal writes its marker where the anchored process directory is not.
- Reproduction: run `--liveness` from a directory other than the repository root while the process runs.
- Impact: misleading probe output during manual diagnosis on the dev machine; none in the container.
- Why tests miss it: the tests pass an absolute `--state-dir`.
- Remediation: anchor `args.state_dir` once in `main`, before both uses.

### G-0607
- ID: G-0607
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED (code trace); the stall durations are the engine bounds, not measured
- Classification: DRIFT
- Category: persistence on the event loop
- Component: composition root, D099
- File: src/live/wiring.py; docs/DECISIONS.md
- Lines: wiring.py:684-721, 747-761, 846-859, 1105-1113; DECISIONS.md:103
- Rule: D099
- Known-prior: KNOWN in part: 24-DEFERRED R-08 (reconcile loop, resolver), R-23 (operator, start-time glue), R-10 (alert sink), enablement.py "Known limit". Not recorded: the protection coordinator, the emergency closer, `execute_approved_plan` and the scheduled cancel. Wrongly described: D099 says the live process "ran every store call through the seam" and "What stays open: nothing for Phase 24".
- Evidence: the raw synchronous `PgJournalStore`, `PgExecutionStateStore` and `PgPendingActionStore` are handed to `ProtectionCoordinator`, `MarketEmergencyCloser`, `ExecutionService` (then `execute_approved_plan(journal=..., intent_store=...)`), `OperatorCommands` and `cancel_expired_entries_once`. Their calls are plain: `self._journal.record(event)` (protection.py:1406, 3202), `intent_store.consume_and_record_entry_intent(` and `intent_store.mark_sent(` (manager.py:1230, 1323), `self._persist(` (safe_mode.py:519-536), `journal.record(` (scheduled_cancel.py `_journal`).
- Expected: per D099, no store call runs on the loop thread.
- Actual: the most time-critical paths (stop placement after a fill, emergency close, the entry write-ahead) block the one loop for each database call. The bound per call is the engine's (24-DEFERRED R-23: lock 5 s, statement 10 s, connect 3 s, pool 5 s). In a database brown-out each call can cost seconds while the stream keepalive, the Telegram runner and all 13 tasks wait.
- Reproduction: `grep -n "self._journal.record(" snapshot/src/execution/protection.py`; compare wiring.py:700-712.
- Impact: against `max_unprotected_ms` = 180 000 a few 5 to 10 s stalls inside one protection run are survivable but use the margin; the owner-facing decision text says the matter is closed.
- Why tests miss it: composition tests use in-memory stores; nothing asserts the calling thread of a store call.
- Remediation: correct D099 and add a 24-DEFERRED row naming the coordinator, closer, manager and scheduled cancel; measure loop stall under a slow database in the Phase 25 soak before deciding whether to wrap them.

## Owner decisions
1. **Health after enable (G-0600).** Today a RED health reading after the start changes nothing. Option A: N consecutive NO_TRADE ticks disable entries and alert (N = 2 is 30 s at the 15 s tick). Option B: keep it journal-only and correct D102. Example: 4 of the last 10 REST calls fail at 10:00:15; with A a CONFIRM at 10:00:50 is refused `DISABLED`; with B it is placed if the manager's own checks pass.
2. **Telegram unreachable at start (G-0603).** Option A: hold (held marker, heartbeat red, nothing supervised until a restart). Option B: continue in SAFE_MODE, retry the bot every tick, heartbeat red until the bot runs. With a restored open position, A leaves it to its exchange stop only; B keeps the coordinator and reconcile running.
3. **Reconcile pause during a placement (G-0604).** Cap it? Example: tick 15 s; a placement that takes 70 s skips 5 ticks (75 s) on every symbol. A cap of 2 skipped ticks would compare at 30 s and may park the system in SAFE_MODE for the false positive D097 was written to avoid.
4. **Silent task failure (G-0602).** After how many consecutive failed runs of `reconcile_tick` or `protection_step` is the owner alerted and the heartbeat red? 3 runs = 45 s; 20 runs = 5 min.

## Open Questions
- (exec_protection / reconcile lanes) `src/live/stream_persistence.py` was not read by this lane; its two sinks are the only writers of exchange order and position rows from the stream. `status_hint_sink` and `algo_sink` are counters with no consumer (`_EvidenceSink`, wiring.py:373-386), and `on_snapshot` of `build_stream` is not bound (wiring.py:775-812), so the REST snapshot taken at a reconnect reaches no consumer in `src/live`. Whether the supervisor itself replays it was not checked.
- (M08) After a failed BOT step in the `start_polling` branch the bound bot is shut down: does `drain_once` keep failed alerts queued for the life of the process, and does anything else notice (G-0603)?
- (M08) `LiveBotProxy` is bound only at step BOT; alerts raised by RECOVERY and RECONCILE (steps 7 and 8) wait for `alert_drain` after the scheduler starts. Confirm that no alert is sent synchronously before the bind and dropped.
- (deploy lane) `stop_grace_period: 30s` (docker-compose.yml:37) against a shutdown that waits for the current run of every task and for `service.drain()`: an adapter cancel retry can last longer than 30 s (D114 text: 3 attempts, up to 30 s delay), so SIGKILL can land mid-run. Related to KNOWN R-22.
- (M07) the DEMO stream URL `wss://demo-fstream.binance.com` is "the user's recorded value", not an SDK constant (binance_client.py:149-158); verify it against the current Binance Demo documentation.
- (charter question 3) No strategy-driven signal reaches the live process and no phase owns it (D101). The Phase 25 Demo campaign as composed can only run `/demo_signal` plans.
- KNOWN and not re-reported: R-18 (the CLOCK_DRIFT step passes when the measurement works), R-22 (a stop leaves resting entries; shutdown order), R-23, R-25, R-28 IN-03 / IN-04.
- Not inspected: the smoke plan arithmetic in `signal_source.py:200-648`, `stream_persistence.py`, the press handling of `telegram_runner.py`, `approval_sender.py`, `alerts.py`; no test file of `tests/test_live_*` was run (their content is cited from grep only).

## DONE
