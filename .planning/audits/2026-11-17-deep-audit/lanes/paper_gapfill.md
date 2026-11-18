# Lane M10b: paper_gapfill

## Scope
Gap-fill of files left unread by M10 (paper_runtime) and M06 (live_composition), snapshot `55885b9`:
`src/paper/shadow.py`, `shadow_confirm.py` (bodies), reservation lifecycle of `src/paper/shadow_ledger.py`,
`journal.py`, `notify.py`, `surface.py`, `replay_inputs.py`, `evidence_bundle.py`, `evidence_export.py`,
`attribution.py`, freeze-tick half of `coverage.py` (717-1563), `src/adapters/paper_ws.py` 1-189;
`src/live/stream_persistence.py`, `src/live/signal_source.py` 200-648. Finding IDs G-1050..G-1099.
Builds on G-1001..G-1008 and G-0600..G-0607 (not repeated). No probe script was needed: every claim below is a
code trace; no test file was run, no network call made. Out-of-scope code read to trace callers:
`src/adapters/telegram_callbacks.py:365-653`, `src/approval/confirm_core.py:888-1030`, `scripts/export_soak_evidence.py`
(1-140, 340-420), `src/paper/exit_criteria.py` (340-365, 405-475, 1280-1440), `src/paper/shadow_runtime.py` (826-925,
1105-1200), `src/paper/live_minutes.py` (settled watermark), `src/ops/store_executor.py`, `src/persistence/entities.py`
(517-626, 799-868), `src/persistence/execution_state.py:250-262`, `src/adapters/binance_userdata_router.py:544-590`,
`src/live/order_index.py:119-136`, `src/live/stream.py:200-300, 392-408`, `src/live/wiring.py` (715-812, 1095-1135, 1335-1376),
`src/adapters/analytics_store.py:195-232`, `src/analytics/cli.py:578-580`, ROADMAP Phase 25/26, 24-01-SUMMARY Q4.

## Coverage
| file | level | note |
|---|---|---|
| src/paper/shadow.py | DEEP_READ | all 1302 lines |
| src/paper/shadow_confirm.py | DEEP_READ | all 814 lines; the state machine itself is the shared `src/approval/confirm_core.py` (handle_confirm 888-1030 read) |
| src/paper/shadow_ledger.py | DEEP_READ | 1-80, 260-1022 (ledger ops + reservation lifecycle); 1022-1225 by M10 |
| src/paper/journal.py | DEEP_READ | all 746 lines (pure PaperRecord assembler) |
| src/paper/attribution.py | DEEP_READ | all |
| src/paper/evidence_export.py | DEEP_READ | all |
| src/paper/evidence_bundle.py | DEEP_READ | all 571 lines |
| src/paper/notify.py | DEEP_READ | all |
| src/paper/surface.py | DEEP_READ | all |
| src/paper/replay_inputs.py | DEEP_READ | all |
| src/paper/coverage.py | DEEP_READ | 717-1420 (freeze-tick grid, host witness, reconciler); 1420-1563 outline (statement text, tick timing) |
| src/adapters/paper_ws.py | DEEP_READ | 1-189 (kline normalisation, SDK log bridge); 190-843 by M10 |
| src/live/stream_persistence.py | DEEP_READ | all 484 lines |
| src/live/signal_source.py | DEEP_READ | 1-60, 200-648 (1-200 by M06) |
| src/paper/__init__.py | METADATA_ONLY | re-exports only |

## Verified Safe Areas
| rule or behaviour | what was checked | where | why it holds |
|---|---|---|---|
| SHADOW approval follows the live rules (chat, user id, private chat, expiry, one-time token, replay) | SHADOW dispatch path to the shared dispatcher | shadow.py:766-801; telegram_callbacks.py:365-620 | `ShadowApprovalBook.dispatch` refuses a call without `authorized_user_ids`, then calls the same `dispatch_callback` the DEMO desk uses: chat gate, `authorized_user_gate` (empty allow-list raises), journal-first receipt, short-id mapping, binding gate (plan hash, strategy version, parameter set id/hash, plan expiry), token by hash, replay-to-existing; `actor_id` = `from_user_id` (telegram_callbacks.py:615-619) |
| SHADOW approval expiry = plan expiry; restart expires PENDING | binding context and restart sweep | shadow.py:738, 1215-1274 | `expiry_utc = plan.expiry_utc`; raw tokens are memory-only, so every PENDING row is decided EXPIRED (RUNTIME_RESTART) at start |
| SHADOW CONFIRM: same core as DEMO, bound to the approving user, single use, 60 s TTL | subclass + handler | shadow_confirm.py:208-262, 664-700 (check at 681); confirm_core.py:888-958 | the SHADOW book is `CoreConfirmBook` with the SHADOW profile; a card is issued only when `result.approval.actor_id == str(press.from_user_id)`; `on_confirmed` runs once per finished CONFIRM after the lock |
| No SHADOW path to an order endpoint | imports of shadow.py / shadow_confirm.py / shadow_ledger.py / journal / attribution / evidence_* | module heads | no `src.execution` order module, no signed adapter, no `src.live`; the only side effect of CONFIRMED is the injected `on_confirmed` (fill driver). Consistent with M10's import probe |
| Reservation lifecycle is journal-first, idempotent and replay-safe | check / reserve / refuse / release / open | shadow_ledger.py:706-1020 | check+journal+reserve in one serialized section; reserve idempotent on `plan_hash:approval_id`; every lifecycle event id is `correlated_event_id` of stable data with a stable occurred time (plan expiry, confirm instant, fill time), so a repeated recovery writes the same id |
| No false SHADOW_PLAN_EXPIRED_UNFILLED | release horizon vs fill horizon | shadow_runtime.py:831-850, 913-920; live_minutes.py:19-22, 277-281 | drivers advance to the poller's `settled_through_utc` = `now - close_lag`, the same instant `release_expired` receives; a FILL for an ended key raises `ReservationEndedError` (fail closed) |
| Paper record assembly never guesses | attribution + assembler | attribution.py:110-159; journal.py:392-447 | APPROVE without terminal confirm raises; filled legs need a human APPROVE with measured times; partial legs raise |
| SHADOW fills use the backtest's cost and lifecycle functions | imports (M10) + replay | shadow_fill.py:38-61 (M10); replay_inputs.py:357-384 | same `advance`/`booking_for_event`/cost model; attribution compares outcome classes only, the money comparison is in src/analytics (other lane) |
| Evidence bundle integrity | loader | evidence_bundle.py:208-229, 471-524 | every listed file hashed before parse, unknown names refused, floats refused, schema /1 vs /2 strict |
| Bundle cannot pass with another epoch's data inside the window | evaluator | exit_criteria.py:439-447, 1364, 1404-1409, 788-791, 345-363 | manifest epoch must equal pinned epoch; only records of the epoch are judged; a foreign-epoch record inside (pin, end] is a failure; window must start at the pin and last 14 days |
| A missing freeze tick is never read as clean | reconciler | coverage.py:1040-1060, 1144-1176, 1206-1330 | hourly cron only (else raises); grace < 3600 s so one run serves one slot; re-run attempt != 1 is not tick evidence; a non-CLEAN line ends continuity; a missing slot is an EVIDENCE_GAP with a reason |
| Host witness ticks judged by server time | `_host_verdict` | coverage.py:906-955 | provider ModTime decides lateness; epoch id and both hashes must equal the pin; a duplicate tick id or sha256 is refused |
| Parity replay rebuilds the same context or refuses | replay inputs | replay_inputs.py:357-384 | cost model rebuilt from the registry slice of the pinned set; parameter_set_hash, cost_model_hash and context_digest compared |
| Kline normalisation is exact | paper_ws | paper_ws.py:91-126 | `Decimal(str(...))` for every price/volume; ms -> UTC by timedelta, no float |
| Stream persistence keeps arrival order and never moves state backwards | executor + monotonic event time | store_executor.py:66-81; stream_persistence.py:222-226; entities.py:592-598, 844-846 | one writer thread; submission is synchronous inside `write`, so tasks submit in creation order; an older `E` is a no-op; `local_status` only leaves UNKNOWN with USER_DATA_EVENT evidence |
| Stream persistence writes only project entry orders | router + index | binance_userdata_router.py:548-581; order_index.py:119-136 | only `known_order` (registered entry ids) reaches the sink; emergency closes are ignored; algo updates go to a counter |
| Smoke signal source cannot reach LIVE and is not the final risk gate | wiring + manager | smoke_injection.py:288-300 (M06); manager.py:875 | `/demo_signal` exists in DEMO only; placement re-runs `evaluate_risk` with live inputs, so the smoke derivation's `open_positions=[]`, `daily_loss_quote=0` (signal_source.py:255-256) does not decide |

## Decision review
| decision / rule | verdict | yardstick | reason |
|---|---|---|---|
| D041 two-step APPROVE + CONFIRM in SHADOW (measure the human delay) | SOUND | owner goal (realistic paper) | same core as DEMO, so the measured delay is the one live will have |
| REV-12: approval expiry = plan expiry, no new TTL | SOUND | logic | one clock for validity; an APPROVE after expiry is journaled and never revives a plan |
| 16-DEC-Q-C reserve-at-confirm | SOUND (stated trade-off) | logic | exposure only after a valid CONFIRM is journaled; paper verdicts may differ from the backtest while a plan waits, and the module says so |
| Q-J journal-only recovery of reservations | SOUND | logic | deterministic ids make re-recovery idempotent; the cross-epoch scope problem is M10 G-1002 |
| Pending approvals expire at restart (no durable tokens) | SOUND | fail closed | a restart can never leave a pressable stale card; KNOWN IN-07 covers its attribution side effect |
| 16-30 "analytics rows come from an optional hand-supplied file" | DOUBTFUL | evidence provenance practice | the attribution file is sealed into the bundle like journal-derived files but is not derived from the journal (G-1050) |
| 24-01 Q4 / OQ-2: only the Demo-smoke signal source; "later owner phase for strategy-driven signals to be named" | DOUBTFUL | process logic (owner goal: Demo proves the live path) | the phase was never named; neither Phase 25 nor 26 builds it, so the Demo campaign cannot cover the strategy-to-order path (G-1052) |
| 24-19: stream persistence enqueues and journals failures by class name, no retry | DOUBTFUL | persistence practice | a failed write is lost for good and invisible to health; acceptable only while no live decision reads the tables (G-1051) |
| D-12/L-12: only `Mode.SHADOW` constructible in paper code | SOUND | code trace | every composer and sender calls `require_shadow` |

## Findings

### G-1050
- ID: G-1050 · Severity: LOW now / MEDIUM mainnet (the soak attribution is a go-live input) · Confidence: CONFIRMED (absence shown) · Classification: GAP · Category: evidence provenance / attribution
- Component: SHADOW analytics evidence · File: scripts/export_soak_evidence.py, src/paper/evidence_export.py, src/paper/shadow_runtime.py · Lines: export_soak_evidence.py:110-112, 391-418; evidence_export.py:82-114; shadow_runtime.py:1112-1127; rehearsal.py:753
- Rule: D-15 / PAPER-02 (system, user-executed-sim, opportunity attribution of the soak), D-18 (soak decisions into the Phase 10 reports) · Known-prior: stated only in `16-30-SUMMARY.md:45,151` ("building ShadowRow from the journal ... is open work"); not in `deferred-items.md`, STATE or ROADMAP
- Evidence: `rows = [_shadow_row(raw) for raw in document["rows"] if raw["epoch_id"] == epoch_id]` then `export_shadow_evidence(rows, research_universe=document["research_universe"], backtest_entries=document["backtest"])` (export_soak_evidence.py:410-415). `ShadowCoordinator.paper_records` ("every plan this process alerted", from `self._alert_order`, memory) has one caller, the rehearsal (rehearsal.py:753). No code in `src/` or `scripts/` builds `ShadowRow` from the journal.
- Expected: the attribution file of a soak bundle is derived from the journaled SHADOW rows of the epoch, and its backtest part is tied to the same parameter set, so a paper-vs-backtest comparison compares like with like.
- Actual: the file is whatever JSON the operator passes as `--analytics-inputs`; the exporter filters it by the file's own `epoch_id` field and checks neither the rows against the bundle's journal nor the `backtest` entries against the pinned `parameter_set_hash`; the result is then sha256-listed in the manifest exactly like `runtime_records.jsonl`. The in-process builder covers only plans alerted since the last restart.
- Reproduction: read the lines cited; `grep -rn "ShadowRow(" src scripts` -> only rehearsal.py:636 and export_soak_evidence.py:392 (the latter parses the hand-supplied file).
- Impact: the soak's three-way attribution and its backtest comparison have no reproducible path from the evidence; someone must hand-assemble it, and the bundle then presents it with the same integrity marks as journal-derived data. The 14-day verdict itself does not read it (exit criteria use the runtime records), so the trial is unaffected.
- Why tests miss it: the exporter test builds the file from Phase 7 fixtures (16-30-SUMMARY:151).
- Remediation: build `ShadowRow` from the epoch's approval/confirm/reservation journal in the exporter (restart-safe), check `backtest` entries against the pinned set, or label the file in the manifest as operator-supplied.

### G-1051
- ID: G-1051 · Severity: LOW now / MEDIUM mainnet · Confidence: CONFIRMED (code path), PROBABLE (analytics impact) · Classification: DESIGN · Category: persistence / user-data stream
- Component: live stream persistence · File: src/live/stream_persistence.py · Lines: 222-236, 248-253, 297-306, 368-400; wiring.py:767-801; analytics/cli.py:578-580
- Rule: 24-19 / D-10 / G4-043 (exchange state of our orders and positions persisted from the stream) · Known-prior: M06 Open Question (file not read); 24-DEFERRED covers only the reopened-position lifecycle
- Evidence: each event becomes one `executor.write` job; `_write_order` catches every exception and calls `_fail(...)`, which journals `STREAM_PERSISTENCE_FAILURE` through the same database and, if that fails too, only logs (`live.stream_persistence.journal_failed`). There is no retry, no requeue and no repair: `on_snapshot` of the stream is not bound (M06), and `WriterStats.failures` has no reader in `src` (grep). The `orders` rows feed `normalize_live_outcomes(rows.signals, rows.plans, rows.orders, rows.fills)` (analytics/cli.py:580).
- Expected: an exchange event that could not be stored is either stored later or makes the gap visible (health, alert, a durable marker).
- Actual: with PostgreSQL down or timing out (statement 10 s, pool 5 s), every ORDER_TRADE_UPDATE / ACCOUNT_UPDATE of that period is dropped from `orders` / `positions` for good; the row keeps its last state until a newer event of the same order or (symbol, side) arrives. For an entry whose last event (FILLED, EXPIRED, CANCELED) was lost, no newer event comes. Events are not reordered (FIFO writer, monotonic `E`) and not duplicated (an equal-`E` identical update is a no-op).
- Reproduction: not run (needs PostgreSQL). Trace: router sink -> `exchange_state_sink` -> `_spawn` -> `_write_order` -> exception -> `_fail` -> journal raises -> log only.
- Impact: today nothing in the live decision path reads these tables (protection, day risk and reconcile use the in-memory fan-out and REST), so trading safety is unaffected. The live outcome analytics (and any later kill-gate or go-live evidence built on `orders`) can carry an entry as NEW/PARTIALLY_FILLED forever, silently. The same single writer thread also serves `day_risk.ingest_fill` (stream.py:288), so a slow database makes the day-loss ingest of a fill wait behind queued persistence jobs (see Open Questions).
- Why tests miss it: `test_a_store_failure_is_journaled_by_class_name_only` asserts the journal row with a working journal; no test makes both the store and the journal fail, and none checks the row after an outage.
- Remediation: keep a backlog of failed jobs replayed after the store recovers (they are idempotent by `E`), surface `failures` in health, and/or bind the reconnect snapshot to a repair writer.

### G-1052
- ID: G-1052 · Severity: MEDIUM now / MEDIUM mainnet · Confidence: CONFIRMED · Classification: DESIGN · Category: process / wiring completeness (go-live path)
- Component: live signal source · File: src/live/signal_source.py, src/live/wiring.py, .planning/ROADMAP.md · Lines: signal_source.py:1-12; wiring.py:1341-1358; ROADMAP Phase 25 (1382-1420) and Phase 26 (1498-1530); 24-01-SUMMARY.md:81
- Rule: 24-01 Q4 / OQ-2 (owner accepted the recommendation "later owner phase for strategy-driven signals to be named"); Phase 25 criterion 2 ("APPROVE -> CONFIRM places real orders on the Demo account through the same code path as live") · Known-prior: none recorded as open
- Evidence: "Per the owner's answer only ONE implementation ships here, the Demo-smoke injector. A strategy-driven DEMO source ... stays with the owner-named later phase and is NOT built or imported here" (signal_source.py:6-9). `build_live_assembly` defaults `signal_source` to `DemoSmokeSignalSource(...)` and `src/live/runtime.py` passes none. In LIVE mode the smoke command is not registered (M06), so the live process has no signal producer at all. ROADMAP Phase 25 and Phase 26 (goals, criteria, inherited items) contain no item that builds a strategy-driven source; 24-01-SUMMARY records the later phase as "to be named".
- Expected: the go-live plan names the phase that connects the strategy (the SHADOW detector / paper pipeline) to the live approval sender, and the Demo campaign exercises that path before go-live.
- Actual: the only signals the live process can carry are synthetic smoke plans (fixed LONG, minimum quantity, back-solved or account equity, BTCUSDT by default, `open_positions=[]` at derivation). The Phase 25 Demo soak and failure suite can therefore only run on smoke plans; the strategy-to-order path (bar-close timing, sizing from live state, several symbols, signal-to-approval latency, plan expiry vs `min_remaining_validity_seconds`) will be built after the Demo campaign or not at all, and Phase 26's canary has no producer.
- Reproduction: `grep -rn "SignalSource\b\|DemoSmokeSignalSource(" src scripts` -> only signal_source.py, smoke_injection.py, wiring.py.
- Impact: no money effect today (placement disabled, no producer). The risk is to the go-live evidence: a Demo campaign that passes on smoke plans does not cover the component that will create every real plan. A typical AI-plan fault: a problem closed by deferring it to a phase that was never named.
- Why tests miss it: the wiring tests check that a source exists and the smoke flows; no gate checks that a strategy source is planned.
- Remediation: owner decision (below): name the phase (before Phase 25's soak) that builds a strategy-driven `SignalSource` for DEMO, and add "strategy-driven plans placed on Demo" to Phase 25's criteria.

### G-1053
- ID: G-1053 · Severity: INFO now / INFO mainnet · Confidence: CONFIRMED · Classification: DRIFT · Category: documentation in code
- Component: SHADOW approval and confirm docstrings · File: src/paper/shadow.py, src/paper/shadow_confirm.py · Lines: shadow.py:31-33; shadow_confirm.py:26-28
- Rule: Phase 23 D-01..D-03 (user-id gate) · Known-prior: none
- Evidence: shadow.py:31-33 "User-id authorization is Phase 23 and is NOT implemented here; the actor recorded on a decision is the callback chat id." shadow_confirm.py:26-28 "Authorizing user ids against an allow-list, money amounts on the card and keyboard removal are Phase 23." The code does all of it: `dispatch` requires `authorized_user_ids` (shadow.py:772-773), `dispatch_callback` runs `authorized_user_gate` and stamps `actor_id = from_user_id` (telegram_callbacks.py:440-465, 615-619); keyboard removal exists (shadow_confirm.py:545-592).
- Expected / Actual: the module text says the gate is missing; the gate is present.
- Impact: a reader (or an agent planning from the docstring) may conclude SHADOW approvals are not user-gated, or re-implement the gate.
- Why tests miss it: docstrings are not tested.
- Remediation: update the two docstrings.

## Owner decisions
1. Strategy signals in the live process (G-1052). Today the live process can only carry smoke plans (one LONG of minimum size on BTCUSDT). Options: (a) name a phase before the Phase 25 Demo soak that feeds the SHADOW detector's plans into the live approval sender in DEMO, and make "strategy plans placed on Demo" a Phase 25 criterion; (b) keep the smoke source for Phase 25 and accept that the first strategy-driven orders happen in the Phase 26 canary with real money (USD 50-100 sub-account); (c) other. Example of what (b) leaves unproven: a 1h bar closes at 10:00:00, the plan must reach Telegram, be approved and confirmed, and still have 900 s of validity left at placement; that timing has never run with a real plan.
2. Soak attribution file (G-1050): accept a hand-supplied analytics file (then the manifest should say so), or require it to be built from the journal before the soak evidence is used.
3. Stream persistence losses (G-1051): accept "analytics only, may be stale after a DB outage", or require a replay of failed writes before the live outcome report is used as evidence.

## Open Questions
- live_risk_state / exec lanes: `StoreExecutor` is one writer thread shared by stream persistence jobs, `day_risk.ingest_fill` (stream.py:288), the execution service (`run_sync`), reservations and the journal (wiring.py:513, 623, 763, 795). With PostgreSQL slow but up (statement timeout 10 s), each queued persistence job ahead of an ingest can delay the fill's entry into the day loss by up to about 10-15 s; meanwhile `day_risk` is not invalidated (only on a failed or unscheduled ingest, stream.py:270-273, 286-291). Is a CONFIRM evaluated in that window against a day loss that misses the fill? Not traced here.
- binance_adapters / exec_protection: when a protective algo order triggers, the resulting ORDER_TRADE_UPDATE carries a client id the index does not register as an entry (`known_order` holds entry ids; algo ids are in `_algos`), so it would surface as `UNKNOWN_STREAM_ORDER`; whether that is the observed Demo behaviour was not checked here.
- `_single_epoch` (exit_criteria.py:428-450) passes when some CLEAN freeze lines carry no `epoch_id` as long as one stamped line exists; the hash criterion still applies, so the effect is small. Not raised as a finding.
- paper_ws.py:106-126 takes `symbol`/`interval` from the subscription, not from the payload `s`/`i`; correct only if the SDK invokes the callback per stream (binance_adapters lane).
- KNOWN and not re-reported: 16-REVIEW B2 IN-07 (restart sweep changes the attribution of already-expired untouched plans), 24-DEFERRED reopened-position lifecycle in the position snapshot writer.

## Working notes (appended as groups finish)

### Group 1 notes (shadow.py DEEP, shadow_confirm.py DEEP, shadow_ledger.py 450-1022 DEEP)
- SHADOW approval: `ShadowApprovalBook.dispatch` refuses a call without `authorized_user_ids` (shadow.py:766-772) and
  delegates to the shared `dispatch_callback` (telegram_callbacks.py:365-620): chat gate, then `authorized_user_gate`
  (user id + private chat type, empty allow-list raises), journal-first receipt, short-id mapping, binding gate
  (plan hash, strategy version, parameter set id/hash, plan expiry), one-time token by hash, replay-to-existing.
  actor_id = from_user_id (telegram_callbacks.py:615-619); the `_save` chat-id stamp (shadow.py:779-781) is only a fallback.
  Same function the live path uses (approval_desk.py) -> same rules. Module docstring (shadow.py:31-33) still says
  "User-id authorization is Phase 23 and is NOT implemented here; the actor ... is the callback chat id" -> stale (DRIFT, INFO).
- Expiry: approval expiry = plan expiry (binding context `expiry_utc`, shadow.py:668-669); restart expires every PENDING
  (shadow.py:1206-1265), raw tokens memory only.
- CONFIRM: SHADOW `ConfirmBook` subclasses the shared `src.approval.confirm_core.ConfirmBook` (shadow_confirm.py:226-262);
  confirm bound to the approving user (`result.approval.actor_id != str(press.from_user_id)` -> no card, shadow_confirm.py:676-677),
  60 s TTL, single use; core lane owns confirm_core.
- No order path: shadow.py / shadow_confirm.py import nothing from src.execution or a signed adapter (imports read);
  the only side effect of CONFIRMED is the injected `on_confirmed` (M10 imp_probe confirms the module set).
- Reservation lifecycle: check+journal+reserve in one serialized section (ledger lock); reserve idempotent by
  plan_hash:approval_id; refusal journaled then `_ended`; release at DATA horizon (not wall clock) so no false
  EXPIRED_UNFILLED; a FILL for an ended key raises `ReservationEndedError` (fail closed); journal-first everywhere;
  event ids deterministic (plan expiry / confirm instant as occurred time) -> replay-safe.

### Group 2 notes (journal.py DEEP, attribution.py DEEP, evidence_export.py DEEP, evidence_bundle.py DEEP; exporter script lines 1-140, 340-420; exit_criteria.py 340-365, 1280-1440)
- journal.py is a pure record ASSEMBLER (PaperRecord), not the journal store. Append-only journal = PG journal_events via
  `record_journal` with deterministic `correlated_event_id`; reservation events use plan expiry / confirm instant as time
  (shadow_ledger.py:536-562, 832-848) -> a repeated recovery writes the same id (replay-safe by construction).
- attribution.py: pure 3-way classification of journaled outcomes; an APPROVE without a terminal confirm raises (no guess).
  It does NOT compare PnL or costs with the backtest; the comparison lives in src/analytics (other lane).
- evidence_bundle.py: every file hashed before parse; unknown file names refused; float refused; schema /1 vs /2 strict.
  The loader does not check record epoch == manifest epoch, but `evaluate_trial` does: manifest vs pinned epoch
  (exit_criteria.py:439-442), records filtered to the epoch (1364), foreign-epoch records inside the window reported
  as a failure (1404-1409, 788-791), earlier-epoch records listed as auxiliary (1280-1306). Window = pin + 14 d checked (345-363).
- CANDIDATE G-1050: `analytics_evidence.json` is built from a hand-supplied `--analytics-inputs` JSON; no code builds
  ShadowRow from the journal (16-30-SUMMARY line 151 says so; not in deferred-items); `paper_records()` is called only by
  the rehearsal (rehearsal.py:753), and holds only plans of the current process (`_alert_order`, memory). The exporter
  filters rows by the file's own `epoch_id` field and does not cross-check rows or `backtest` entries against the
  bundle's journal or the pinned parameter set; the file is then hashed into the manifest like the journal-derived files.

### Group 3 notes (notify.py DEEP, surface.py DEEP, replay_inputs.py DEEP, coverage.py 717-1420 DEEP, 1420-1563 outline, paper_ws.py 1-189 DEEP)
- notify.py: SIMULATE send-only (Phase 7); `notify_simulate` has no production caller (only re-exported in __init__);
  its constants are reused by the SHADOW sender. Retries a Telegram send up to 3 times / 30 s: a timed-out but delivered
  message can appear twice (harmless: inert SIM keyboard; for SHADOW the same short id).
- surface.py: observer; every decision via `evaluate_closed_bar`; duplicate bar -> DUPLICATE_BAR record, conflicting copy raises.
- replay_inputs.py: cost model rebuilt from the registry slice of the pinned set, then parameter_set_hash, cost_model_hash
  and context_digest are compared (replay_inputs.py:367-384) -> a changed recorded input is refused; no float.
- coverage freeze half: hourly cron only (else raises); grace must be < 3600 s; a run serves one slot; re-run attempt
  != 1 is not tick evidence; non-CLEAN line ends continuity; host ticks judged by provider server time, epoch id and
  both hashes, duplicates by tick id and sha256. Exit criteria add: manifest vs pinned epoch, foreign epoch_id on lines,
  CLEAN lines must carry the pinned hash (exit_criteria.py:428-475). GitHub-path `_line_verdict` does not itself read
  epoch_id/hash; the separate criteria cover it. A CLEAN line with no epoch_id passes `_single_epoch` as long as
  another stamped line exists (minor; hash criterion still applies).
- paper_ws 1-189: Decimal(str(...)) for all prices, exact ms->UTC via timedelta, `x` flag verbatim; symbol/interval
  are taken from the subscription, not from the payload `s`/`i` (relies on per-stream callbacks of the SDK);
  SDK log bridge forwards SDK messages verbatim (public market streams only, no key in the paper process).

## DONE
