# Verification V3_ops_evidence
| ID | Outcome | Severity now | Severity mainnet | Duplicate of | One-line reason |
|---|---|---|---|---|---|
| G-1101 | CONFIRMED | MEDIUM | HIGH | - | `record_fill` has zero production callers; local_status only leaves UNKNOWN, a NEW order is never moved to FILLED/CANCELED; 20D-01 says CLOSED incl. "fills ledger". |
| G-0801 | CONFIRMED | MEDIUM | HIGH | - | Failed send is journaled ALERT_SEND_FAILED and not re-queued; producers alert once per transition; dedupe key (event, symbol, reason) omits plan_hash. Probe reproduces. |
| G-1302 | CONFIRMED | MEDIUM | HIGH | - | Probe: a 2-row journal 21 days apart with no tick, health, order or trade row returns overall PASS; image_commit is parsed and never compared; export window is free. |
| G-1501 | DOWNGRADED | MEDIUM | MEDIUM | - | Real: evidence dict has no commit, dirty flag or config hash, and src+limits changed after both runs (75104781 at 12:24Z after the 10:42Z run); but it is an evidence-provenance gap, the HEAD is recoverable approximately from timestamps, no runtime effect. |
| G-1503 | DOWNGRADED | LOW | MEDIUM | - | Facts true (marketable LONG limit above mark, direct enter_safe_mode, operator close; no stop/TP trigger, resting or partial fill, emergency close), but each demo-observed row names only the steps observed, base status stays [DESIGN], and Phase 25 plans the campaign for the rest. |
| G-1508 | CONFIRMED | MEDIUM | HIGH | - | Last file with IMAGE_COMMIT= under evidence is 16-66 (36dcad8, 2026-10-20); git: 572 commits on the gate path set, src +43,096/-2,037 lines, src/live (26 files, +12,539) entirely new; later runs are targeted or -n 4 unrecorded, two with a known failure. |

## G-1101
- Outcome: CONFIRMED. Severity now MEDIUM (placement disabled, Demo only), mainnet HIGH (live analytics / kill-gate input empty while trades happen).
- Independent evidence:
  - `src/persistence/entities.py:682` `def record_fill(...)` is the only insert path into `FillRow`; grep over `src/` and `scripts/` for `record_fill|insert(FillRow|FillRow(` finds only the definition, the mapper (`src/db/mappers.py:294`) and `scripts/demo_rehearsal.py:2804` `_record_fill_sample` (evidence JSON, not the table). No production caller.
  - `src/persistence/entities.py:550` `update_order_exchange_state`: "`local_status` is never touched".
  - `src/persistence/entities.py:628` `transition_order` has exactly one production caller, `src/live/stream_persistence.py:284`, guarded by `if result.entity.local_status is OrderStatus.UNKNOWN and target is not None` (line 283). Rows are inserted NEW (`stream_persistence.py:428`). So a NEW order stays NEW forever; only an UNKNOWN order is moved.
  - Live fills go to memory only: `src/live/stream.py:257` `self._coordinator.fill_sink(routed)`; `src/execution/protection.py:1422` fill_sink is an in-memory enqueue.
  - Analytics read the table: `src/adapters/analytics_store.py:210-211` `select(FillRow)`; `src/analytics/live_outcomes.py` `normalize_live_outcomes`: "One candidate per TradePlan with at least one ENTRY-role order that has a fill" -> `if not entry_fills: continue`. Empty fills table => zero live outcomes.
  - `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md:56`: `20D-01 | Positions table, fills ledger, Order rows and update_position_snapshot ... | CLOSED [DESIGN] | 24-07 ... and 24-19 (writers)`. The 24-19 writers (stream_persistence) write orders and positions, not fills.
- Counter-checks: searched for any other writer of `local_status` (only `transition_order` and inserts); searched src/live, src/execution for `record_fill`/fill persistence (none; `wiring.py:808` comment notes a reader needs a new adapter). R-06 in 24-DEFERRED defers only the position lifecycle, not fills; 20D-02 (line 57) itself says it "waits for Order and fill rows", implicitly admitting they do not exist yet.
- Notes: precise wording: local_status does leave UNKNOWN (to a mapped status) — the claim "never leaves NEW" is accurate for NEW rows. Protection/safety does not depend on these rows, hence not CRITICAL.

## G-0801
- Outcome: CONFIRMED. Severity now MEDIUM, mainnet HIGH (the operator is the human in a semi-automated loop; SAFE_MODE latching and the automatic close keep it below CRITICAL).
- Independent evidence:
  - `src/ops/alerts.py:740-772` `TelegramAlertSender.drain`: `alert = self._queue.popleft()`; on failure only `_outcome_event(EVENT_ALERT_SEND_FAILED ...)` is recorded; re-queue happens only on `BaseException` (cancellation). Budget `src/paper/notify.py:115-116` `NOTIFY_MAX_ATTEMPTS = 3`, `NOTIFY_MAX_DELAY_SECONDS = 30`.
  - `src/ops/alerts.py:503-530` `_accept`: key `(alert.event, alert.subject, alert.reason)`; `critical()` (532-543) passes `subject=symbol`, so `plan_hash` is not in the key. `config/execution/execution-limits-v1.toml:68` `dedupe_window_ms = 300000`.
  - `src/live/alerts.py:30-31` (the project's own note): "WR-C6: a CRITICAL alert whose send failed is journaled `ALERT_SEND_FAILED` and is not queued again in the process; only a restart re-queues it."
  - Producers alert once per transition, not periodically: `src/execution/protection.py:2673` (TP_UNAVAILABLE), `2769` / `2780` (CLOSE_REQUIRED / PROTECTIVE_REJECTED), each in a one-shot branch.
  - Probe `tmp/verify_V3_ops_evidence/probe_alerts.py` (failing bot, no-op sleep): `drain1 SendReport(delivered=0, failed=1, audit_lost=0) bot calls 3 queue after 0`; a second CRITICAL with a different plan_hash on the same symbol at +2 min -> queue 0, journal `ALERT_SUPPRESSED`; only at +5m01s is a repeat queued again. Journal sequence: OPERATIONAL_ALERT, ALERT_SEND_FAILED, ALERT_SUPPRESSED, OPERATIONAL_ALERT.
- Counter-checks: searched for a consumer of `ALERT_SEND_FAILED` that re-sends (none in src outside alerts.py); `requeue_undelivered` runs once at start (`src/live/alerts.py:123-135`, guarded by `AlertsAlreadyRequeued`). Mitigations: the alert is journaled; SAFE_MODE is entered before the alert, so no new entry opens; the emergency close runs whether or not the alert goes out.
- Notes: "dropped for the life of the process" is exact for the failed alert instance; a new occurrence of the same key after 5 min would be queued again, but the producers do not re-raise by themselves.

## G-1302
- Outcome: CONFIRMED. Severity now MEDIUM (the soak has not run; the tool is the planned go/no-go evidence for Phase 25), mainnet HIGH (a soak "PASS" could be produced from a journal that does not show the system ran or traded).
- Independent evidence:
  - `scripts/evaluate_demo_soak.py:658-671` `compute_window`: `start = events[0].occurred_at_utc` ... `end = events[-1].occurred_at_utc`; duration is end-start only. No criterion reads row density, heartbeat/health cadence or gaps (criteria list `evaluate_journal` 880-901).
  - `:620-630` `check_order_after_registration`: `if not orders: return ... STATUS_PASS ... "no order event in the journal"`.
  - `:819-829` `check_round_trips`: `if required is None: ... STATUS_SKIPPED`; `Evaluation.passed` (876) treats SKIPPED as not FAIL.
  - `image_commit` appears only at 27, 220, 289, 345-358 (parse/validate format); never compared to anything (no git call, no journal field).
  - `export` (`:1039-1067`): `--since`/`--until` are free operator inputs, only `since < until` checked; not tied to `registered_at_utc` or the registration.
  - Probe `tmp/verify_V3_ops_evidence/probe_soak.py`: two rows of a dummy event type 21 days + 1 s apart, `owner_round_trips_per_week: null` -> `PASSED: True`; order_after_registration PASS "no order event", duration PASS 21.0000, round_trips SKIPPED, all other criteria PASS (no RECONCILE_TICK or HEALTH_VERDICT rows at all).
- Counter-checks: looked for a minimum-row / coverage / heartbeat criterion and for a check that the journal is from the registered host/image: none. `registration_hash` only binds the registration file, not the journal. 25-DEFERRED D056 says soak must run healthy, but nothing in the evaluator requires the presence of health rows.
- Notes: mitigated only by owner discipline (owner runs export and evaluate); the "null round trips" path is a registration choice, but the evaluator still reports overall PASS rather than INCONCLUSIVE.

## G-1501
- Outcome: DOWNGRADED. Severity now MEDIUM, mainnet MEDIUM (provenance of evidence, not a runtime defect; it matters only if the smoke is cited as release evidence for a later image).
- Independent evidence:
  - `scripts/demo_rehearsal.py:584-606` `EvidenceRecorder.to_dict` keys: schema, mode, scenario, symbol, base_url, runner_clock_utc, constraints, steps, exchange_orders, observations, planned_requests, failures, synthetic_inputs, details, attestation_map, outcome. No commit / tree state / config hash. `grep -n "commit|git|dirty|config_hash"` over the script: no hit (only sha256 of ids and chat fingerprints).
  - The three committed evidence files (`.planning/phases/24-live-runtime-composition-demo/evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json`, `...20261115T083259Z.json`, `...20261115T104211Z.json`): no commit/dirty/config/limits field.
  - Git (read-only, snapshot): 25 commits touching `src`/`config` between the 2026-11-06 16:03Z run and the 2026-11-15 10:42Z run; after the 10:42Z (17:42 +07) run, `75104781 2026-11-15T19:24:25+07:00 feat(quick-261115-pdb): set scheduler.protection_stall_after_ms to 60000` changed `config/execution/execution-limits-v1.toml` and `src/execution/execution_limits.py`. So HEAD (55885b9) differs in code and limits from both runs.
- Counter-checks: looked for the HEAD being recorded elsewhere (the commit message of 55885b93 and the 24 SUMMARY files): none states the commit or tree state of the run. The commit that ran can be bracketed from timestamps (between d1c971c7 17:26 +07 and 75104781 19:24 +07 for the 21/21 run), but whether the tree was dirty cannot be recovered.
- Notes: severity downgraded from HIGH mainnet because the gap does not change runtime behaviour; the fix (record `git rev-parse HEAD`, `git status --porcelain` non-empty flag and a sha256 of the limits file in `details`) is cheap. Related to G-1503 (what the smoke proves) but a distinct root defect.

## G-1503
- Outcome: DOWNGRADED. Severity now LOW, mainnet MEDIUM (a coverage gap of exchange-observed behaviour, not an over-claim; becomes material only if placement were enabled before the Phase 25 campaign).
- Independent evidence (facts of the claim, all true):
  - Smoke evidence `evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json` steps: start, wiring_check, demo_enable, signal ("fill request queued by the Demo injector"), card, approve, confirm_entry, stream_fill, stop_confirmed ("algo status NEW"), tp_legs ("placed"), reconcile_clean, restart, restart_enable, restart_rehydrate, replays_place_nothing, close_cleanup ("closed by the operator close"), reservation_released_on_close, account_clean, safe_mode_drill_signal, safe_mode_drill, drill_reservation_released. No step for a stop or TP trigger, a resting/partial fill or an emergency close.
  - `scripts/demo_rehearsal.py:1684-1687, 1737`: for `fill` the LONG entry is `mark_price * (1 + (up-1)*FAR_BAND_FRACTION)` and must be `> mark_price` -> a marketable limit, i.e. an immediate (taker) fill.
  - `scripts/demo_rehearsal.py:2929`: `wiring.safe_mode.enter_safe_mode(reason="DEMO_SMOKE_DRILL", ...)` (direct call, not a natural trigger).
  - `scripts/demo_rehearsal.py:~2839-2855`: `operator_close_position(...)` closes the position; stop placed below `entry_min`, TPs above the mark (1714-1735: "neither can trigger on placement").
  - The restart is the script's own second wiring (orderly), not a crash.
- Counter-checks (why downgraded): `24-DEFERRED.md:9-13` defines the label: used "only where the committed smoke evidence ... lists the step OBSERVED"; every demo-observed row keeps `CLOSED [DESIGN]` as its basis and names the exact steps (e.g. line 20 D055: "confirm_entry, stream_fill and stop_confirmed are OBSERVED"; line 78 20D-23: "safe_mode_drill OBSERVED (owner /safemode_exit and /confirm)"; line 66 lists /status, /disable_entries, /close as NOT_OBSERVED). None of the rows claims a stop trigger, partial fill or emergency close was observed. EXEC-01/EXEC-02/OPS-02 stay Pending (line 13). Phase 25 (`.planning/phases/25-demo-integration-test-campaign/`, 33 plans plus SCENARIO-INVENTORY) is the Demo campaign; plans 25-06/08/10/17/18/20/28 mention partial fills and 25-07/11/14/32 emergency close.
- Notes: the residual real point: "demo-observed" can be read more broadly than its definition; the restart row (G4-029, 20D-06) is observed for an orderly restart only. Not a duplicate of G-1501 (provenance) though both concern the same smoke.

## G-1508
- Outcome: CONFIRMED. Severity now MEDIUM (placement disabled, Demo only), mainnet HIGH (no recorded whole-suite evidence binds any commit containing src/live; a mainnet image would have no gate).
- Independent evidence:
  - `.planning/phases/16-paper-runtime-composition/evidence/16-66-gate-post-phase19.txt:1-27`: run 2026-10-20, sequential, `TEST_DATABASE_URL set`, `11557 passed, 7 skipped`, `IMAGE_COMMIT=36dcad846f19e0214d80803669994007fd87d131`.
  - `grep -rl "IMAGE_COMMIT="` over `.planning` and `docs` outside phase 16: only `.planning/quick/261020-bkp-.../261020-bkp-SUMMARY.md` (2026-10-20) and `.planning/STATE.md` (which itself says, line 46, "no recorded sequential gate exists for Phase 21 yet"). Phases 20-24 have no gate file in an `evidence/` directory (24 holds only the smoke JSON and a silence probe; 22 only Demo probes).
  - Git (read-only, snapshot): `git rev-list --count 36dcad846f19..55885b93 -- <the IMAGE_COMMIT path set of 16-66>` = 572 (306 touching src); `git diff --shortstat 36dcad846f19 55885b93 -- src` = 139 files, +43,096 / -2,037; `src/live` does not exist at 36dcad8 and is 26 files / +12,539 at HEAD.
- Counter-checks: searched phase 20-24 SUMMARY/VERIFICATION/UAT files and quick tasks for a full-suite record: 20-VERIFICATION:151, 21-VERIFICATION:106, 22-VERIFICATION:125, 22-UAT:11 are targeted runs ("The full suite was not run"); STATE.md:46 records a Phase 21 `-n 4` strict PostgreSQL full run with one failure, fixed, "not re-run after that fix"; 23-VERIFICATION:286 notes a full suite with one known failure (`test_phase21_fixtures` CRLF); 261114-mp1-SUMMARY:116/124 report `test_phase20_gate.py` invariant 6 failing (pre-existing). None is a sequential, recorded, clean-tree gate with an IMAGE_COMMIT. git log since 2026-10-21 shows no added gate evidence file.
- Notes: the AGENTS.md rule defines a recorded gate as sequential + clean tree + TEST_DATABASE_URL + saved under evidence/; by that definition the claim is exact. Unrecorded parallel full runs did occur, so the code is not untested, but no run is bound to a commit, and the known invariant-6 failure means a gate at HEAD would not be clean as recorded.

## DONE
