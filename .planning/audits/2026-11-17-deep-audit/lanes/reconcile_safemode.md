# Lane M05: reconcile_safemode

## Scope
`src/reconcile/*`, `src/live/reconcile.py`, `src/persistence/safe_mode_store.py`, `src/persistence/system_state.py` at snapshot `55885b9`. Finding IDs G-0500..0599.



## Coverage

| File | Level | Note |
|---|---|---|
| `src/reconcile/__init__.py` | DEEP_READ | re-exports only; docstring still describes the Phase 8 five-kind vocabulary |
| `src/reconcile/classify.py` | DEEP_READ | 16 kinds -> policy table, all read |
| `src/reconcile/compare.py` | DEEP_READ | all 1096 lines; probed (see findings) |
| `src/reconcile/local_intent.py` | DEEP_READ | state table vs compare inputs |
| `src/reconcile/feed_freshness.py` | DEEP_READ | pure predicates |
| `src/reconcile/loop.py` | DEEP_READ | all 1649 lines |
| `src/reconcile/sweeper.py` | DEEP_READ | all 667 lines |
| `src/reconcile/safe_mode.py` | DEEP_READ | all 1163 lines |
| `src/reconcile/startup.py` | DEEP_READ | all 449 lines |
| `src/live/reconcile.py` | DEEP_READ | composition glue |
| `src/persistence/safe_mode_store.py` | DEEP_READ | thin adapter |
| `src/persistence/system_state.py` | DEEP_READ | append-only versions; PG behaviour not executed (no DB in the audit) |

Out-of-scope files read only to trace callers (not covered here): parts of `src/live/*`, `src/execution/protection.py`, `src/execution/live_context.py`, config TOML.

## Findings

### G-0500
- **ID:** G-0500
- **Severity (now / mainnet):** MEDIUM / MEDIUM (availability and alert fatigue, not direct money loss; fail-closed direction)
- **Confidence:** CONFIRMED (probe + code trace); the frequency per trade is an estimate, not measured
- **Classification:** DESIGN
- **Category:** reconcile / SAFE_MODE latch / lifecycle transients
- **Component:** `ReconcileLoop` + `compare` + `derive_local_intent` + `SafeModeController`
- **File:** `src/reconcile/loop.py`, `src/reconcile/compare.py`, `src/reconcile/local_intent.py`, `src/live/wiring.py`
- **Lines:** loop.py:782-788 (every divergence kind enters SAFE_MODE at once), loop.py:590-610 (three awaited truth reads, then the local read; no lock shared with the protection task); compare.py:680-695 (POSITION_WITHOUT_STOP for any position without an ACTIVE system stop), compare.py:718-734 (any exchange order without an open local intent); local_intent.py:104-118 (state table); wiring.py:1062-1066 (the only mitigation: skip while a placement task is outstanding and one tick after), wiring.py:1126-1133 (protection and reconcile are two independent scheduler loops)
- **Rule:** D-03 "any divergence forces SAFE_MODE", D-15 "only the operator exits", D097 (skip while a placement is outstanding), 20-DEFERRED 20D-37, 24-DEFERRED R-15
- **Known-prior:** PARTLY KNOWN. Three single instances are recorded and each was handled alone: D097 (fill right at placement, patched by a skip), 20D-37 (GTD expiry, "still shows ENTRY_WITHOUT_PROTECTIVE for about one tick", deferred), R-15 / 24-NOTES item 7 (manual close while TP1 rests, deferred). The general cause is recorded nowhere, and 20D-37 understates the effect: it is not "one tick", SAFE_MODE latches until an operator exit.
- **Evidence:**
  - `loop.py:782-788`: `for divergence in diff.divergences: policy = classify(divergence.kind); ranked.setdefault(policy.safe_mode_reason, ...)` then `for reason in reasons: self._enter_safe_mode(reason, now_utc, failures)`. One compared tick with one divergence is enough; there is no second look, no minimum age, no "must stand N ticks".
  - `safe_mode.py:604-606`: "A boolean flip, a restart, a timer, a recovered feed and a closed intent never exit SAFE_MODE; this call is the only way."
  - The order lifecycle is not atomic between Binance and the coordinator, so a healthy trade passes through snapshots that the compare reports. Probe `tmp/reconcile_safemode/probe_transients.py` (real `derive_local_intent`, `compare`, `classify`; output in `probe_transients.out`):
    - S1 resting entry filled on the exchange, coordinator has not processed the fill: `POSITION_WITHOUT_STOP, UNSYNCED_POSITION, ENTRY_WITHOUT_PROTECTIVE, UNSYNCED_NORMAL`
    - S2 fill seen, stop POST in flight (intent SENT): `POSITION_WITHOUT_STOP, UNSYNCED_ALGO`
    - S3 stop on the exchange, intent resolved, `stop_confirmed_at_utc` not set yet: `ENTRY_WITHOUT_PROTECTIVE, UNTRACKED_SYSTEM_ORDER` (the exact moment the stop intent is resolved was not traced; S1 and S2 do not depend on it)
    - S4 PROTECTED, TP1 ACKED, TP2 in flight: `UNTRACKED_SYSTEM_ORDER, UNSYNCED_ALGO`. Code: `src/execution/manager.py:2338` records TP1 `ACKED` before TP2 is sent; ACKED is not returned by `list_unresolved_intents` (`src/persistence/execution_state.py:176-180`); the plan becomes COMPLETE only after both legs (`src/execution/protection.py:2631-2632`).
    - S5 stop or TP2 closed the position on the exchange, coordinator not yet FLAT: `UNSYNCED_ALGO` x3
    - S6 coordinator FLAT, its own leg sweep not finished: `UNTRACKED_SYSTEM_ORDER`
    - S7 GTD entry expired on the exchange, coordinator still AWAITING_FILL: `ENTRY_WITHOUT_PROTECTIVE, UNSYNCED_NORMAL`
    - the baselines S0, S0b, S0c and S8 are clean, so the probe inputs are well-formed.
  - D097 (docs/DECISIONS.md:101) records that this happened twice on the first Demo run: "it compared a healthy placement as UNSYNCED_NORMAL, UNSYNCED_ALGO and POSITION_WITHOUT_STOP and entered SAFE_MODE, which survives a restart and blocked the rest of the rehearsal". The fix is `wiring.py:1064`: `if service.outstanding or service.take_settling(): return`. It covers only an entry that fills while its placement task runs or within one tick after it. The designed entry is a resting GTD LIMIT (D079): its fill comes minutes or hours later, when no placement task is outstanding, and S1 to S7 are then covered by nothing. The flag is also read only at tick start: a placement that begins while a tick awaits its reads is not covered.
- **Expected:** a healthy trade (rest, fill, stop, take profits, exit, expiry) never needs an operator action; SAFE_MODE means "something is wrong".
- **Actual:** each lifecycle step has a window (fill to stop confirmed; TP1 ack to COMPLETE; exchange flat to coordinator FLAT and legs swept; GTD expiry to coordinator notice) in which one compared tick latches SAFE_MODE. Tick period 15 s (`config/execution/execution-limits-v1.toml`, `reconcile.tick_interval_ms = 15000`). Rough arithmetic, not a measurement: if the windows of one trade add up to W seconds, the chance that a tick lands inside is about W/15. D097's own timestamps show about 2 s for the fill window (CONFIRM 15:54:12.1, registration 15:54:14.2), and D113 allows up to 3 x 0.5 s of rereads in the take-profit step. W of 3 to 6 s gives roughly 20 to 40 percent of trades ending in a false SAFE_MODE; a stream gap (the coordinator then learns the fill by REST poll) makes W larger.
- **Reproduction:** cwd `AUDIT\tmp\reconcile_safemode`, `PYTHONPATH=AUDIT\snapshot`, `python -B probe_transients.py`.
- **Impact:** now: the Demo campaign (Phases 25/26) will be interrupted by SAFE_MODE after ordinary fills and exits, each needing `/safemode_exit` and `/confirm`. Mainnet: no new entry until the part-time owner reacts, and an `UNPROTECTED_POSITION` / `DIVERGENCE` alert that is false most of the time trains the operator to exit SAFE_MODE by habit. The exit re-runs the compare (safe_mode.py:690-695), so a habitual exit is not unsafe by itself; the loss is availability and trust in the one alarm that matters. Second order: it invites more patches of the D097 kind, and every skipped tick is a real blind interval.
- **Why tests miss it:** `tests/test_live_reconcile_settling.py` pins only the placement-task skip. The reconcile tests drive `tick()` with fakes in settled states; no test interleaves a protection step with a tick, and the Demo smoke uses an entry that fills at placement (the case D097 covers).
- **Remediation (options, not chosen here):** (a) a divergence must stand for two consecutive compared ticks (or a minimum age) before SAFE_MODE; the first sighting is journaled and delegated to the coordinator only; (b) make the local side transition-aware: a plan whose state changed, or that has a SENT intent, within the last N ms is "in transition" and its order/algo divergences wait one tick (position-without-stop is still handed to the coordinator, whose `max_unprotected_ms` deadline is the real guard); (c) one lock around the protection step and the reconcile reads, and ACKED legs of an active plan count as owned; (d) keep the latch for kinds that cannot be transient (foreign order, sign flip, doubled position, unknown intent) and let transient kinds be withdrawn by a later clean tick. Measure W on Demo first (journal times of fill, stop ACTIVE, COMPLETE, FLAT).

### G-0501
- **ID:** G-0501
- **Severity (now / mainnet):** MEDIUM / MEDIUM (availability; fail-closed direction)
- **Confidence:** CONFIRMED (code trace + config); failure rate of the reads is not measured
- **Classification:** DESIGN
- **Category:** reconcile / SAFE_MODE latch / single failed read
- **Component:** `ReconcileLoop._read_and_act`, `_exchange_read_failed`, `_step_unknown_entries`, `_check_feeds`
- **File:** `src/reconcile/loop.py`; `config/binance/binance-limits-v1.toml`
- **Lines:** loop.py:597-604, 701-727, 674-687, 1133-1143; binance-limits-v1.toml:12
- **Rule:** module docstring "Fail closed: a failed truth read ... is never agreement. The tick enters SAFE_MODE (API_DEGRADATION ...)"; D-15 (operator-only exit); D072 (`sdk_retries = 0`)
- **Known-prior:** none found
- **Evidence:** `loop.py:597-604`: `for source, reader in readers: try: rows = await reader() ... except Exception as exc: return self._exchange_read_failed(now_utc, source, exc, action_failures)`; `loop.py:720-727` enters `SAFE_MODE_API_DEGRADATION`. `config/binance/binance-limits-v1.toml:12`: `sdk_retries = 0`. A tick runs every 15 s with three signed GETs: 17,280 reads a day, none retried. The same latch follows one exception of the UNKNOWN-entry step (loop.py:686) and one unreadable feed reading (loop.py:1140-1143).
- **Expected:** a read (GET) that fails once is tried again on the next tick (or once more in the same tick) before the system is parked; "fail closed" for a failed read means "do not trust this tick", i.e. no compare and no sweep.
- **Actual:** one timeout or one 5xx on one of 17,280 daily reads puts the system in durable SAFE_MODE until `/safemode_exit` + `/confirm`. At 99.99 % read success that is about 1.7 latches a day; the project's own notes call the network flaky. Not comparing on that tick is right; latching on it is a separate choice that nobody derived.
- **Reproduction:** read the three lines above; `tests/test_reconcile_loop*.py` pin exactly this behaviour (a failing snapshot gives `TICK_READ_FAILED` and SAFE_MODE).
- **Impact:** same as G-0500: entries blocked until a human reacts, frequent false alarms, habit of exiting. Positions stay supervised by the coordinator, so no direct money loss.
- **Why tests miss it:** the tests assert the latch as the intended result; no test or soak measures how often a real network produces it.
- **Remediation (options):** count consecutive failed ticks and enter SAFE_MODE at N (an owner number, for example the number of ticks inside `max_unprotected_ms`); or keep the entry but let a later fully clean tick withdraw the reasons API_DEGRADATION / STALE_FEED automatically (they describe a condition, not an unexplained state). A read is safe to retry; the "never re-send" rule (D080) is about placements.

### G-0502
- **ID:** G-0502
- **Severity (now / mainnet):** LOW / MEDIUM
- **Confidence:** CONFIRMED (probe)
- **Classification:** DEFECT
- **Category:** SAFE_MODE durability / restart
- **Component:** `SafeModeController.enter_safe_mode`, `SafeModeController.load`
- **File:** `src/reconcile/safe_mode.py`
- **Lines:** 525-538 (journal first, then persist, in one `try`), 334-369 (`load` reads only the state store), 857-865 (spill on journal failure)
- **Rule:** D-14 / F-127 / F-606 "a restart must never read SAFE_MODE as off" (safe_mode.py:383; loop.py:489-490)
- **Known-prior:** none found (the module docstring describes the in-process retry only)
- **Evidence:** `safe_mode.py:530-536`: `try: self._journal_safe_mode_event(...); self._persist(now_utc=effective_now)`: when the journal write raises, `_persist` is not attempted. In the live wiring both are the same PostgreSQL (`src/live/wiring.py:653-654`: `journal=self.stores.journal, state_store=self.stores.safe_mode_state`), so a database outage fails both. The entry record goes to the local spill only. `load` (safe_mode.py:336) reads the state store and nothing else. Probe `tmp/reconcile_safemode/probe_persist.py`:
  `process A: in_safe_mode = True | persisted = None | spill = ['SAFE_MODE_ENTER']` then, after a restart with the database back, `process B after restart: in_safe_mode = False | reason = None`, `guard_new_entries blocks = False`.
- **Expected:** SAFE_MODE entered in process A is still on in process B.
- **Actual:** SAFE_MODE entered while the database could not be written is lost by a restart that happens before a later `enter_safe_mode` call succeeds in saving. The in-process retry (`_persist_pending`, safe_mode.py:522-523) only runs on the next enter call. The spill holds the `SAFE_MODE_ENTER` record and startup replays it into the journal (`src/reconcile/startup.py` step 6), but nothing turns it back into state.
- **Reproduction:** cwd `AUDIT\tmp\reconcile_safemode`, `python -B probe_persist.py`.
- **Impact:** now: small (Demo; the start sequence runs recovery and a full reconcile tick, which re-enter SAFE_MODE for anything that still shows as a divergence, a failed step or an unresolved intent). What is lost are reasons that leave no state behind: `STREAM_SINK_FAILURE` (which also carries the escalated "triggered stop was rejected" frame, `src/live/feeds.py` docstring), `AUTH_FAILURE`, `API_DEGRADATION`, `STALE_FEED`, `SYMBOL_OWNERSHIP_CONFLICT` seen once. Restarting a process that reports database errors is a natural operator reaction, and a container restart policy does it unasked. Mainnet: entries can resume without the operator exit that D-15 requires (on LIVE the enablement is human after every start, which narrows this, but the human sees mode NORMAL).
- **Why tests miss it:** the persistence tests (`tests/test_safe_mode_persistence_pg.py`, skipped in this audit) and the journal-failure tests check the in-memory flag and the retry inside one process; none restarts between the failed save and the retry.
- **Remediation:** attempt `_persist` even when the journal write failed (the store writes its own journal row in the same transaction), and at `load` start IN SAFE_MODE when the spill holds a `SAFE_MODE_ENTER` / `SAFE_MODE_REENTER` / `SAFE_MODE_STATE_UNREADABLE` record newer than the loaded state version.

### G-0503
- **ID:** G-0503
- **Severity (now / mainnet):** LOW / MEDIUM
- **Confidence:** CONFIRMED (code read; the script was not run)
- **Classification:** GAP
- **Category:** SAFE_MODE exit path outside the controller
- **Component:** `scripts/demo_clear.py::exit_safe_mode` (cross-lane: M13 owns the script)
- **File:** `scripts/demo_clear.py`
- **Lines:** 81-97, 105-126
- **Rule:** D-15 / safe_mode.py:604-606 "this call is the only way"; `src/reconcile/startup.py:27` "SAFE_MODE exit stays manual"
- **Known-prior:** none found as a finding; the script is documented as a Demo helper
- **Evidence:** `demo_clear.py:86-96` appends `{"in_safe_mode": False, ..., "last_exit_operator_id": "owner-demo-clear"}` straight to `system_state_events`. None of the seven exit rows runs: no Binance read, no compare, no gate, no stream, no restore check. Its guards are `os.environ.get("LIVE_RUNTIME_MODE") != "DEMO"` (an environment variable typed by the operator), a typed phrase, and `count(*) from execution_intents where resolved_at_utc is null`. Nothing checks that `DATABASE_URL` is a Demo database or that the account is flat (the operator is asked to make it flat in the UI).
- **Expected:** every persisted "SAFE_MODE off" comes from `SafeModeController.exit_safe_mode`, or the bypass is technically bound to Demo.
- **Actual:** a second writer of the SAFE_MODE key exists. Pointed at the mainnet database with `LIVE_RUNTIME_MODE=DEMO` in the shell, it clears a durable SAFE_MODE and expires approved plans without any exchange check; the next start then loads "not in SAFE_MODE".
- **Reproduction:** read the lines above.
- **Impact:** now: none beyond Demo convenience. Mainnet: the durable latch can be removed by a script that is one environment variable away; the start sequence's reconcile tick is then the only net.
- **Why tests miss it:** no test covers the script's guard against a non-Demo database.
- **Remediation:** bind the script to Demo by something the database itself holds (for example a persisted mode marker or the admitted-mode journal row), or remove the SAFE_MODE part and let the owner use `/safemode_exit` after the next start.

## Verified Safe Areas

| Rule or behaviour | What was checked | Where | Why it holds |
|---|---|---|---|
| A protective of a resting entry is never an orphan (old F-401) | `resting_entry_plans` from local NEW / PARTIALLY_FILLED entries and from every exchange open order whose id decodes to ENTRY; probe S0 clean | compare.py:447-460, 482-483 | the orphan branch needs `not entry_is_resting`; the exchange side alone is enough, so a stale local view cannot remove the exemption |
| The sweeper cannot cancel a leg of a live or in-flight position | orphan needs: local protective intent, no local position intent, no non-zero exchange position, entry not resting, the algo present; then two fresh position reads must both be zero, then a by-id probe, then cancel, then a verifying query | compare.py:483-512; sweeper.py:221-257, 263-301, 343-374; loop.py:1414-1426 | a stop is placed only after a fill is seen, and every post-fill state carries a local position intent (local_intent.py:108-114), so the orphan branch is unreachable while the plan holds exposure; an unreadable position raises and skips |
| The reconcile package places nothing and cancels only ORPHAN_PROTECTIVE algos | grep of adapter calls in `src/reconcile/*` | loop.py (reads only), sweeper.py:314 | the only mutating call is `cancel_algo_order` in the sweeper; foreign and untracked orders are ALERT_ONLY (classify.py:189-198) |
| Every divergence kind has a policy; an unknown kind cannot be defaulted | `POLICY_BY_KIND` against `_DIVERGENCE_KINDS` (16 = 16) | classify.py:156-243; compare.py:106-125, 233 | `classify` raises KeyError and `Divergence.__post_init__` raises ValueError |
| A missing source is never read as empty | `_require_sources`, `_require_decimal_amount`, the loop's `isinstance(rows, (list, tuple))`, restore-pending skip | compare.py:905-922; loop.py:600-601, 566-568 | None, a non-list answer or a non-Decimal amount ends in READ_FAILED and SAFE_MODE, never agreement |
| SAFE_MODE blocks the entry path | callers of `place_entry` and of `guard_new_entries` in `src` | `src/execution/manager.py:376` (only caller of `adapter.place_entry`), `manager.py:841-847` (gate 3, before risk and every adapter call) | one placement function, guarded before the approval is consumed. Protection, emergency close and operator close are not guarded, as intended (risk reducing) |
| No automatic path leaves SAFE_MODE inside the process | grep of `exit_safe_mode`, `_in_safe_mode = False`, writers of `SystemStateKey.SAFE_MODE` in `src` | safe_mode.py:732 only; callers: `src/live/operator.py:316`, `src/ops/drills.py:971` | the operator command is behind the Telegram allow-list, a one-time token bound to the user and a TTL (operator.py:239-256, 289-308). The one bypass outside `src` is G-0503 |
| The operator exit cannot pass on stale or missing inputs | the seven rows; `entered_meanwhile`; no await between the compare and the flip | safe_mode.py:661-739 | fresh Binance reads in the call, the same compare as the loop, unreadable = refusal, journal then store then memory |
| Startup order | recovery (restore plans, resolve intents) before the stream; stream before the first tick; the first tick before the bot and the scheduler; enable last and only when nothing degraded | `src/live/startup.py:986-1066`; `src/live/wiring.py:1175-1184` (marks refreshed before the first tick) | no fill event and no button press is handled before the plans are rebuilt; a not-clean first tick fails the step into SAFE_MODE |
| Feed freshness | user-data liveness = newest of event, ping, pong, LIVE entry; mark time from REST premiumIndex; future times beyond the ratified skew are stale; unset thresholds raise | feed_freshness.py:488-522; `src/live/feeds.py:153-169`; config: 60 s mark, 420 s user data (pings every 180 s, D091) | a quiet account does not read as silent; thresholds are a multiple of the refresh / ping period |
| System-state store | version = max+1 with a unique constraint; journal row and state row in one transaction; `latest` orders by version | system_state.py:176-213, 231-236 | a lost race raises RowConflict instead of overwriting (PostgreSQL behaviour read, not executed) |
| Position bound and ownership | probe S8 (TP1 filled: clean), S10 (stop not ACTIVE: POSITION_WITHOUT_STOP) | compare.py:929-971, 1003-1024, 786-821 | sign first, then bound; a stop that is not in the ACTIVE class does not count |

## Decision review

| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D-03: any divergence enters SAFE_MODE at once | DOUBTFUL | logic + probe; owner goal (part-time) | right for states that cannot be transient; wrong as a blanket rule because a healthy trade produces divergences for seconds (G-0500) |
| D-15: only the operator exits, seven fail-closed rows | SOUND for real divergences, DOUBTFUL for condition reasons | risk practice; owner goal | a latched alarm with a checked exit is standard practice; applying it to API_DEGRADATION / STALE_FEED after one failed read is not (G-0501) |
| D097: skip the tick while a placement task is outstanding and one tick after | DOUBTFUL | logic | treats one instance of G-0500; a skipped tick is a blind interval, and the resting-entry fill is not covered |
| D-02: never cancel or close what the system cannot prove it owns | SOUND | risk practice | a wrong cancel of a human's order is worse than an alert; foreign exposure stays the human's action |
| Cancel-only sweeper with two zero position reads and a verified cancel (D-17, T-8-30) | SOUND | exchange behaviour recorded on Demo (by-id query lags the list); logic | cannot open exposure; the two reads are milliseconds apart, so they guard against a bad read, not against time, which the orphan definition already covers |
| D-13: no local positions ledger; bound check `abs(exchange) <= plan quantity` | SOUND as a stopgap, known limit | arithmetic | a hand-reduced position (0.010 to 0.004 with all legs resting, probe S9) reads as agreement; the legs are reduce-only / closePosition so no exposure can open; exact compare deferred to Phase 25 (Q16) |
| D094: stream LIVE before the first reconcile tick | SOUND | logic | the other order parks every clean start in STALE_FEED; plans are restored before the stream starts |
| D091: user-data silence 420 s with a 180 s server ping | SOUND | recorded Demo observation (not reproduced) | two missed pings plus margin |
| D-14: SAFE_MODE durable in the append-only system-state log | SOUND; implementation gap G-0502 | logic | the hole is the save that is skipped when the journal write fails |
| `reconcile.tick_interval_ms = 15000` (provenance DECISION) | CANNOT_JUDGE | none given | no derivation in the config; it sets both the detection delay and, with G-0500, the false-alarm rate |
| Gate restricted: the tick reads nothing and enters no SAFE_MODE (D-18) | SOUND with a caveat | exchange rule (do not send during a ban) | entries need REST too, so they are blocked by the gate; the caveat is that a 418 can last days during which reconcile is blind (see Open Questions) |

## Owner decisions

1. **Should one sighting of a divergence park the system?** Example: a LONG 0.010 BTCUSDT entry rests for 3 hours and fills at 14:00:07.0; the stop reads ACTIVE at 14:00:09.0; the reconcile tick runs at 14:00:08. Today: SAFE_MODE `POSITION_WITHOUT_STOP`, an UNPROTECTED_POSITION alert, and no new entry until you send `/safemode_exit` and `/confirm`, although the stop was in place one second later. Options are in G-0500 (two consecutive ticks; transition-aware compare; a lock; latch only non-transient kinds).
2. **How many failed reads before SAFE_MODE?** Today: one failed GET out of about 17,280 a day (G-0501). Example: N = 4 consecutive failed ticks is 60 s without a compare, the same as the mark-price staleness bound.
3. **Should API_DEGRADATION and STALE_FEED clear themselves** after a clean tick, or stay operator-only like the divergence reasons?
4. **`scripts/demo_clear.py`** (G-0503): keep the direct SAFE_MODE write, bind it to a Demo database, or remove it before mainnet?

## Open Questions

- (M04) `notify_divergence` only sets `recheck_requested`, and the flag is consumed only in UNPROTECTED / PROTECTED_ENTRY_OPEN (`src/execution/protection.py:1507-1524`). For DOUBLED_POSITION and SIGN_FLIPPED_POSITION on a PROTECTED or COMPLETE plan, "DELEGATE_TO_COORDINATOR" then adds nothing to the coordinator's ordinary step. Is that the intended D077 path? Not traced to the end here.
- (M04) The exact moment the STOP_LOSS intent leaves SENT relative to `stop_confirmed_at_utc` (probe case S3) was not traced; S1, S2, S4-S7 do not depend on it.
- (M03 / adapter lane) During a REST gate restriction the tick is skipped without SAFE_MODE or its own alert (loop.py:650-666). Is the restriction itself alerted, and what supervises an open position during a multi-hour 418 ban?
- (M13) G-0503 belongs to the scripts lane for the full guard review.
- (M09 / persistence) `enter_safe_mode`, `list_unresolved_intents` and `list_open` are synchronous database calls on the event loop inside the tick (recorded by the project in `src/live/reconcile.py:30-32`); a slow database stalls the protection task too. Not measured.
- Leverage, margin type and position mode are not part of the three-source compare; whether another component re-checks them after start was not looked at here.
- Not inspected: PostgreSQL behaviour of `system_state.py` (no database in the audit), the Demo evidence JSON files, and the `*_pg.py` tests.
- `src/reconcile/__init__.py:1-20` still describes the Phase 8 package (five kinds); hygiene only.

## DONE
