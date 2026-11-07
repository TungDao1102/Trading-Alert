# Phase 24 deferred register

Written by plan 24-32 (D-35). One row per inherited item, per id the plan names from earlier phases and per
20-DEFERRED row assigned to Phase 24, each with a status. `tests/test_phase24_gate.py` parses the ROADMAP
Phase 24 entry and 20-DEFERRED.md and fails when an id or a row has no status here.

Status words: CLOSED (built and tested, or decided), OWNER (only the owner can do or decide it, see
24-OWNER-RUNBOOK.md), DEFERRED (a named later phase, review or owner number), ACCEPTED (a known limit kept on
purpose). Labels: [DESIGN] = tested with fakes or the project's own stores. `demo-observed (smoke 2026-11-06,
not mainnet)` is used only where the committed smoke evidence
`evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json` (21 of 21 steps PASSED) lists the step
OBSERVED. Anything that needs the owner's host, second Telegram account or healthchecks.io is NOT_OBSERVED
until plan 24-33 records it. No requirement is marked complete here: EXEC-01, EXEC-02 and OPS-02 stay Pending.

## A. ROADMAP Phase 24 inherited items

| ID | Item | Status | Evidence or reason | Source |
|---|---|---|---|---|
| P20-DEFERRED | About 30 items registered only in 20-DEFERRED.md | CLOSED [DESIGN] | Every Phase 24 row of 20-DEFERRED.md has its own status in section C (20D-01 to 20D-39). | ROADMAP Phase 24; 20-VERIFICATION W3 |
| D055 | The -4509 finding: protective legs after the entry fill is an observation, not a chosen model | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | Decided by D079 and D080 (GTD LIMIT, no entry-time stop, fill-driven protection); composed by 24-04 and 24-27; tests/test_live_composed_tracer.py, tests/test_live_demo_smoke.py. Smoke steps confirm_entry, stream_fill and stop_confirmed are OBSERVED. | docs/DECISIONS.md D055, D079, D080 |
| D056 | DEGRADED health policy (mainnet never; Demo only in an explicit Demo mode) | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | 24-22, D102: tests/test_live_health.py, tests/test_live_enablement_wiring.py. The smoke start enabled through the explicit DEGRADED flag (demo_enable OBSERVED). A DEGRADED Demo run is never evidence of live readiness. | docs/DECISIONS.md D056, D102 |
| D058 | Live mark-price gate: stale or missing mark refuses entry and enable | CLOSED [DESIGN] | 24-22 and 24-16: tests/test_live_enablement_wiring.py, tests/test_live_health.py. A stale mark price was not provoked on Demo [NOT_TESTED]. | docs/DECISIONS.md D058 |
| G2-014 | A tap from an unknown chat or user is rejected live with no state change and a journaled rejection | OWNER | Step in 24-OWNER-RUNBOOK.md (second Telegram account and a group chat): NOT_OBSERVED until the owner runs it. Library level: tests/test_telegram_authorization.py; live runner: tests/test_live_telegram_runner.py. | 09-DEMO-REHEARSAL-FINDINGS.md |
| P23-R1 | SHADOW approval stores and shows a money block | CLOSED [DESIGN] | 24-09, D-19: tests/test_paper_shadow_money.py. | ROADMAP Phase 23 R-1 |
| G2-042 | Does Binance realizedPnl exclude commission? Verify against docs and a Demo fill | DEFERRED | A fill sample is recorded in the smoke evidence (details.fill_pnl_sample: realized_pnl 0, commission 0.13037410 USDT, evidence only). It comes from an entry fill, which carries no realizedPnl, so it cannot show the semantics. LIVE_NET_PNL_SEMANTICS_VERIFIED stays False (D086). Needs a sample from a closing fill, Phase 25. | 10-VERIFICATION.md; src/analytics/live_outcomes.py |
| G3-008 | Live commission wiring (scheduler, cache, refresh, fail closed) | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | 24-15: tests/test_live_commission_refresh.py. The smoke evidence records the BTCUSDT account rates (maker 0.000200, taker 0.000400). | 12-fee-cost-model-correctness |
| G3-014 | Phase 12 review IN-01 (negative maker rate fails closed) and IN-05 folded into commission wiring | CLOSED [DESIGN] | 24-15: tests/test_live_commission_refresh.py. | 12-REVIEW.md |
| G3-029 | WR-06: per-service env allow-lists before real live keys enter .env | CLOSED [DESIGN] | 24-30 and 24-36: tests/test_live_compose_env_split.py (cutover and drills re-run, see 24-36-SUMMARY). Placing the real keys in the host env files: owner step in 24-OWNER-RUNBOOK.md. | 13.1-OPEN-DECISIONS.md |
| G3-033 | VPS built with deploy/bootstrap.sh, RUNBOOK 13 and 17 real-host rows, backup timer, one real migrate.sh | OWNER | Steps in 24-OWNER-RUNBOOK.md; NOT_OBSERVED until the owner returns the evidence. | 13.1-UAT.md |
| T-04 | OPS-04: health output carries the Python version and the git revision | CLOSED [DESIGN] | 24-11 and 24-25: tests/test_live_runtime_cli.py, tests/test_dockerfile_revision_stamp.py. | REQUIREMENTS OPS-04 |
| G4-029 | Startup intent recovery and the rehydrate paths are wired into the composition root | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | 24-26 and 24-27: tests/test_live_start_sequence.py, tests/test_live_restart_rehydrate.py. Smoke step restart_rehydrate is OBSERVED. | 17-12-SUMMARY |
| G4-040 | The sync PostgreSQL store runs on the event loop | CLOSED [DESIGN] | 24-05, D099 (owner Q2): tests/test_store_executor.py. The reconcile loop and the resolver still call sync stores directly, see R-08. | docs/DECISIONS.md D051 item (a) |
| P16R-03 | ShadowRuntime expire_due runs database reads on the event-loop thread | CLOSED [DESIGN] | 24-05: tests/test_paper_shadow_runtime.py. | src/paper/shadow_runtime.py |
| G3-005 | NO_FILL and HEALTH_CHECK_FAILED promoted into RejectionReason and GLOSSARY 9.1 | CLOSED [DESIGN] | 24-02: tests/test_phase23_gate.py (invariants 5g and 5h). | docs/DECISIONS.md D044 |
| G2-035 | Phase 9 review IN-01, IN-05, IN-06, IN-07 triage | CLOSED [DESIGN] | 24-02 (see 24-02-SUMMARY, G2-035 triage): IN-07 and the argument half of IN-06 fixed (tests/test_execution_health.py), IN-01 and IN-05 are won't-fix with the reasons recorded. | 09-REVIEW-DISPOSITION.md |
| T-02 | OPS-06: the WR-06 half belongs here, the disk-encryption half to Phase 26 | CLOSED [DESIGN] | WR-06 half closed by 24-30 and 24-36: tests/test_live_compose_env_split.py. The disk-encryption half is R-20 (Phase 26). | REQUIREMENTS OPS-06 |
| 16-50 | External heartbeat covers every long-running process (collector, paper, live) | CLOSED [DESIGN] | 24-24: tests/test_deploy_heartbeat.py (live and paper targets). The real healthchecks.io check, the timer on the host and its firing: owner steps in 24-OWNER-RUNBOOK.md, NOT_OBSERVED. | 16-50 plan |
| P20-GATE-WIRING | REST gate state store, first-install bootstrap, gate alert hook and supervisor wiring | CLOSED [DESIGN] | 24-03, 24-12, 24-26: tests/test_rest_gate_ban_end.py, tests/test_live_exchange_wiring.py, tests/test_live_start_sequence.py. The first-install command on the real host: owner step. | 20-DEFERRED |

## B. Ids the plan names from earlier ROADMAP sections

| ID | Item | Status | Evidence or reason | Source |
|---|---|---|---|---|
| G4-034 | Order and Position exits from UNKNOWN record the evidence source in the journal | CLOSED [DESIGN] | 24-19 and 24-34: tests/test_live_stream_persistence_pg.py, tests/test_live_unknown_entry_notify.py. | ROADMAP Phase 18 and 20 entries |
| G4-043 | update_position_snapshot and order exchange status updates have a store method | CLOSED [DESIGN] | 24-07 (migration 0015, D100): tests/test_persistence_event_time_pg.py. | 17-10-SUMMARY |
| G2-019 | Duplicate exchange client ids and skipped sweeper cancels are surfaced | CLOSED [DESIGN] | 24-20 and 24-34: tests/test_live_reconcile_divergences.py. | 08-REVIEW IN-14, IN-15 |
| T-05 | OPS-05 alerts: duplicate execution attempt, rejected protective action | CLOSED [DESIGN] | 24-13: tests/test_live_alerts_wiring.py. The daily-loss WARNING producer is covered by the day-state producers of 24-16 (tests/test_live_risk_input_producer.py). | REQUIREMENTS OPS-05 |
| T-06 | Reconcile cadence, stale-feed and WS-silence thresholds are registry values with provenance | CLOSED [DESIGN] | 24-06 and 24-10 (D089, D091): tests/test_live_limits_relationships.py, tests/test_live_scheduler.py. | ROADMAP Phase 20 entry |

## C. 20-DEFERRED rows assigned to Phase 24

The Item column quotes the first cell of the 20-DEFERRED row.

| ID | Item | Status | Evidence or reason |
|---|---|---|---|
| 20D-01 | Positions table, fills ledger, `Order` rows and `update_position_snapshot` (G4-043, D-13) | CLOSED [DESIGN] | 24-07 (store methods, migration 0015) and 24-19 (writers): tests/test_persistence_event_time_pg.py, tests/test_live_stream_persistence_pg.py. The position lifecycle from the stream is R-06. |
| 20D-02 | Exact signed-quantity compare of a position against the local intent (D-01a) | DEFERRED | Phase 25 (owner Q16, 2026-10-31): the D-01a bound check stays; the exact compare waits for Order and fill rows with real Demo data. 24-OWNER-DECISIONS.md Q16. |
| 20D-03 | Exchange event-time column and monotonic `Order` updates (D-29) | CLOSED [DESIGN] | 24-07, D100: tests/test_persistence_event_time_pg.py (monotonic update rule, UTC-aware event time). |
| 20D-04 | Operator authentication or allow-list before any LIVE path (D-15) | CLOSED [DESIGN] | 24-23, D104: allow-list on from_user.id, private chat, two-step confirm: tests/test_live_operator_commands.py. Not a password; ssh is no longer the only control. |
| 20D-05 | Alert producers are not wired in production until Phase 24 | CLOSED [DESIGN] | 24-13 and 24-27: tests/test_live_alerts_wiring.py, tests/test_live_wiring.py (one journal-first sink everywhere). |
| 20D-06 | Recovery caller wiring (G4-029) | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | 24-26 and 24-27: tests/test_live_start_sequence.py, tests/test_live_restart_rehydrate.py. Smoke step restart_rehydrate OBSERVED. |
| 20D-07 | Coordinator notification of a `RECONCILED_ABSENT` entry | CLOSED [DESIGN] | 24-34: tests/test_live_unknown_entry_notify.py (the resolver notifies the coordinator). |
| 20D-08 | Composition of the REST gate state store: `state_store`, `on_alert`, the first-install bootstrap call ... | CLOSED [DESIGN] | 24-12, 24-11, 24-26: durable gate state, first-install command, alert hook: tests/test_live_exchange_wiring.py, tests/test_live_start_sequence.py. First-install on the host: owner step. |
| 20D-09 | User-data supervisor and probe wiring to the REST gate | CLOSED [DESIGN] | 24-12 and 24-18: tests/test_live_exchange_wiring.py (probe adapter shares the gate), tests/test_live_stream_to_protection.py (a gate restriction delays the listen-key call). |
| 20D-10 | O-C option a1 consequence: a lost, corrupt or unreadable initialized gate state file blocks every REST call | ACCEPTED | Owner choice O-C a1, unchanged: a lost or corrupt gate state blocks every REST call until a human clears it (RUNBOOK 21, `src.ops.rest_gate_cli`). |
| 20D-11 | Remote operator interface (owner request 2026-10-21) | CLOSED [DESIGN] | 24-23, D104: status, disable_entries, safemode_exit, close and confirm on the live bot: tests/test_live_operator_commands.py. Clearing the REST gate stays an ssh command (D104). /safemode_exit is OBSERVED in the smoke drill; /status, /disable_entries and /close are NOT_OBSERVED until 24-33. |
| 20D-12 | Ban end time from the -1003 message text | CLOSED [DESIGN] | 24-03: tests/test_rest_gate_ban_end.py. The optional rest_gate.ban_end_clock_margin_ms key stays NOT_CONFIGURED (owner). |
| 20D-13 | O-D scope: reconcile-time detection only, no plan-ingress rejection | ACCEPTED | Owner accepted the narrow scope (reconcile-time detection only); unchanged in Phase 24. |
| 20D-14 | Protective-leg absence rule is unchanged for legs of a REJECTED entry (plan 20-10) | DEFERRED | Phase 25 (A2 probe): a GTD expiry is not proof of a terminal order; unchanged. |
| 20D-15 | Local intent is built from strictly listed states | DEFERRED | Seen on Demo 2026-11-06: UNTRACKED_SYSTEM_ORDER and SAFE_MODE when the owner closes by hand while TP1 rests (24-NOTES item 7, owner 2026-11-07: leave as is, decide after Phase 24). A resting xc- close order is CLOSED by commit 75a50fd3: tests/test_live_close_order_stream.py. |
| 20D-16 | Feed liveness source for `FeedSource` | CLOSED [DESIGN] | 24-19: tests/test_live_feed_source.py (liveness time is the newest of event, ping and pong). Mark time source: R-07. |
| 20D-17 | The persisted SAFE_MODE reason is the last one entered in a tick | DEFERRED | Phase 24 code review: nothing changed; every reason stays in the journal row safe_mode_reasons. |
| 20D-18 | `SAFE_MODE` controller has no spill | CLOSED [DESIGN] | 24-20: SafeModeController(spill=...) and load(spill=...): tests/test_safe_mode_persistence.py (7 spill cases), tests/test_live_reconcile_wiring.py. |
| 20D-19 | Coordinator does not spill its own `PROTECTION_TRANSITION` rows when the journal is down | DEFERRED | Phase 25 or a later plan: the coordinator still does not spill its own PROTECTION_TRANSITION rows when the journal is down. |
| 20D-20 | `LocalSpill.scan()` swallows an `OSError` from listing the directory (CLOSED by plan 20-29, CR-C1: only a missing directory is an empty ... | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | 24-26: the spill sentinel start step (a re-created empty spill volume is detected): tests/test_live_start_sequence.py. The smoke start shows SPILL_SENTINEL=OK. |
| 20D-21 | A plan restored UNPROTECTED from a journal ending in another state breaks the replay chain at the next restart | DEFERRED | Phase 24 code review: the replay chain after an UNPROTECTED restore is not repaired; it never becomes less safe. |
| 20D-22 | A forced-UNPROTECTED plan raises no critical alert of its own | DEFERRED | Phase 24 code review: the alert comes with CLOSE_REQUIRED; unchanged. |
| 20D-23 | `exit_safe_mode` has no production caller (plan 20-28 added the symbol-ownership check and `RESTORE_NOT_COMPLETE`; the composition must ... | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | 24-23 and 24-27: tests/test_live_safe_mode_drill.py (real stores, readiness rows, restart), tests/test_live_operator_commands.py. Smoke step safe_mode_drill OBSERVED (owner /safemode_exit and /confirm). |
| 20D-24 | Operator-controls not wired; protect and close cadence | DEFERRED | close is wired (24-23, tests/test_live_operator_commands.py); there is no protect command, the PROTECTION_SWEEP_UNVERIFIED and OPERATOR_* rows still have no alert, and a FLAT plan with a stuck stop is swept every step without backoff. Phase 25. |
| 20D-25 | Lot-filter wiring and the stored fallback age | CLOSED [DESIGN] | 24-20: build_lot_filters wires LotFilterSource into the closer: tests/test_live_reconcile_wiring.py. The stored fallback age is R-04. |
| 20D-26 | Pending protective-action rows | DEFERRED | Phase 24 code review: stricter than needed by design; unchanged. |
| 20D-27 | `emergency_manual_close` returns `None` after `MANUAL_CLOSE_ORPHAN_UNVERIFIED` | DEFERRED | Phase 24 code review: the alert sink is now wired (24-13, 24-27); the None return is unchanged. |
| 20D-28 | IN-A1, IN-A2, IN-A4 | DEFERRED | Phase 24 code review (IN-A1, IN-A2, IN-A4); nothing changed. |
| 20D-29 | WR-B6 | CLOSED [DESIGN] | 24-20: ReconcileLoop(feed_clock_skew=clock_skew_from_drift(...)) in src/live/reconcile.py; RUNBOOK section 7 carries the sentence on which clock stamps the user-data liveness time. |
| 20D-30 | WR-B7 | DEFERRED | Owner number (24-20-SUMMARY item 2): a timeout for the lot-filter refresh inside the tick lock is NOT built, see R-03. |
| 20D-31 | IN-B1, IN-B2, IN-B3 | DEFERRED | Phase 24 code review (IN-B1 to IN-B3); nothing changed. |
| 20D-32 | WR-C3 | CLOSED [DESIGN] | Closed by plan 20-30; the RUNBOOK sentence on the untrusted deadline is in section 21 (REST gate). The cap on the total wait needs an owner number and is not built. |
| 20D-33 | WR-C6 | DEFERRED | Owner decision, then a later plan (24-13-SUMMARY item 2): see R-02. |
| 20D-34 | IN-C1 to IN-C5 | DEFERRED | Phase 24 code review (IN-C1 to IN-C5); nothing changed. |
| 20D-35 | `max_unprotected_ms` (O-04) | CLOSED [DESIGN] + demo-observed (smoke 2026-11-06, not mainnet) | 24-06 (D089) and 24-20: the relationship rule keeps the tick interval below max_unprotected_ms: tests/test_live_limits_relationships.py, tests/test_live_reconcile_wiring.py. The smoke evidence records cancel_query_lag_observations (the by-id query lag after a stop cancel). |
| 20D-36 | Telegram operator commands (`[P20-OPS-REMOTE]`) | CLOSED [DESIGN] | 24-23, D104, owner-confirmed 2026-10-23: tests/test_live_operator_commands.py, tests/test_live_telegram_runner.py. |
| 20D-37 | `ENTRY_WITHOUT_PROTECTIVE` for resting entries | DEFERRED | Phase 24 code review: a natural GTD expiry not yet seen by the coordinator still shows ENTRY_WITHOUT_PROTECTIVE for about one tick. |
| 20D-38 | Items found while merging plans 20-27 / 20-28 / 20-29 | DEFERRED | Phase 25: the coordinator needs a tp1_filled signal (WR-B2); IN-A3 needs a SAFE_MODE reason and a GLOSSARY 9.4 row; the open-algo confirmation rule is D107 (Provisional, owner may override). |
| 20D-39 | Gate-restricted reconcile tick raises no alert | DEFERRED | Owner number (24-13-SUMMARY item 1): the ban start is alerted (REST_GATE_BAN_ENTERED, 24-13, tests/test_live_alerts_wiring.py); a repeated alert during a long skip is NOT built, see R-01. |

## D. Residuals recorded by the plan SUMMARYs and the rehearsals of 2026-11

| ID | Item | Status | Evidence or reason |
|---|---|---|---|
| R-01 | W8: a repeated alert during a long REST-gate skip needs an owner-set interval; the dedupe window can also hide an extended ban | DEFERRED | Owner number; 24-13-SUMMARY item 1. |
| R-02 | WR-C6: a CRITICAL alert whose send failed is not re-queued in process (only the start re-queue brings it back) | DEFERRED | Owner decision on a redelivery bound; 24-13-SUMMARY item 2. |
| R-03 | WR-B7: the lot-filter refresh has no timeout inside the reconcile tick lock | DEFERRED | Owner number; 24-20-SUMMARY item 2. |
| R-04 | A stored lot-filter fallback has no maximum age | DEFERRED | Owner number; 24-20-SUMMARY item 1. Fails closed meanwhile. |
| R-05 | CONDITIONAL_ORDER_TRIGGER_REJECT is relabelled through DEPRECATED_EVENT; its SAFE_MODE reason is imprecise | DEFERRED | Phase 25; 24-19-SUMMARY. |
| R-06 | Position lifecycle OPEN to CLOSING to CLOSED from the stream; flat positions never seen are not stored | DEFERRED | Phase 25 or a reconcile plan; 24-19-SUMMARY. |
| R-07 | Mark time source: the REST time is used, not the stream receive time; confirm on a Demo soak | DEFERRED | Phase 25 or 26; 24-19-SUMMARY. |
| R-08 | The reconcile loop and the resolver call sync stores on the event loop (not behind StoreExecutor) | DEFERRED | Needs a change in src/reconcile/loop.py and intent_recovery.py; 24-20-SUMMARY item 3. |
| R-09 | entry_good_till_by_plan_hash: an entry acknowledged before a restart has no known plan id, so its stale-entry alert is skipped | DEFERRED | Needs a plan lookup by hash in the entity store; 24-20-SUMMARY item 4. |
| R-10 | The alert sink journals synchronously on the calling thread (a gate hook can run on an SDK thread) | ACCEPTED | Alerts are rare; journal-first needs the row before the message is queued; 24-13-SUMMARY item 3. |
| R-11 | Leverage and margin type set from Telegram (the wish of D085) | DEFERRED | Not designed and not built; D104 excludes it from Phase 24; 22-DEFERRED. |
| R-12 | D-34 cancel confirmation by the open-algo list: DECISIONS status | ACCEPTED | D107 is Provisional; the owner may override. |
| R-13 | The raw entry_price conversion residual | CLOSED [DESIGN] | 24-21 (string to Decimal at the adapter boundary); the smoke evidence records entry_price_raw as Decimal. |
| R-14 | No re-issued CONFIRM card after a restart: an APPROVED plan whose confirm was expired by RUNTIME_RESTART waits for plan expiry and a new signal | OWNER | 24-28-SUMMARY finding 1; safe (no duplicate order); recommendation: accept for V1, build a re-issue path only if it hurts in use. Owner decision pending. |
| R-15 | UNTRACKED_SYSTEM_ORDER and SAFE_MODE when the owner closes by hand while TP1 rests | DEFERRED | 24-NOTES item 7; owner 2026-11-07: leave as is, decide after Phase 24. Candidate rule and test scope are written there (next DECISIONS id D108). |
| R-16 | Cosmetic: the INVALID_REASON text in the TP_UNAVAILABLE alert | DEFERRED | Seen in the 2026-11 rehearsals; wording only, no behavior. |
| R-17 | open_day evaluate may stamp a warning or latch without an alert on a mid-day restart before LIVE | DEFERRED | Seen in the 2026-11 review; no live path exists yet (Phase 25/26). |
| R-18 | The start sequence CLOCK_DRIFT step passes when the measurement works, not when the drift is inside the limits; only the rehearsal pre-flight stops on the limits | DEFERRED | The placement still refuses entries (EntriesBlocked); a candidate is to gate the start or the health surface earlier. |
| R-19 | The telegram_delivery warning at start (live.health.not_ok) is benign: no send has been observed yet at that moment | ACCEPTED | Seen in every rehearsal start; health turns OK after the first delivery. |
| R-20 | OPS-06 provider disk encryption on the real host (G3-032) | DEFERRED | Phase 26; T-02 second half. |
