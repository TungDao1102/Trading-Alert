# Lane X04: evidence_reproducibility

## Progress log (partial-run marker)
- [started] 2026-11-17 skeleton written.
- [done] Parameter hashes: probe `tmp/evidence_reproducibility/rehash.py` (output `rehash.out`).
- [done] Determinism by execution across PYTHONHASHSEED 0 / 1 / 987654: probe `det.py` (outputs `det_<seed>.out`).
- [done] Identity fields of the 480 committed research records: probe `records.py` (output `records.out`).
- [done] kill-gate / holdout files (see Verified Safe Areas).
- [run 2, 2026-11-18] resumed: read the three Phase 24 smoke evidence JSONs (2026-11-06 16:03, 2026-11-15 08:32 FAILED, 2026-11-15 10:42).
- [done] smoke step-by-step table vs `scripts/demo_rehearsal.py` + `src/live/smoke_injection.py` + `src/live/signal_source.py`; probe `smoke_check.py` (output `smoke_check.out`).
- [done] gate records 16-65 / 16-66 re-checked with git; findings G-1501..G-1508 written; JSON written and validated (8 objects).

## Scope
Re-derive, do not trust: parameter hashes, determinism by execution, gate/evidence records versus STATE.md / SUMMARY claims,
and what the Demo smoke evidence of 2026-11-06 and 2026-11-15 proves step by step.
Not redone (other lane): research records hold only a `trades_digest` (G-0901 / G-0902).

## Coverage
| File | Level | Note |
|---|---|---|
| `params/**/*.toml` (73) | DEEP_READ (machine) | every file loaded, hashed and verified against the pin list |
| `tests/fixtures/phase4/parameters.json` | DEEP_READ (machine) | 73 pins; its 13 commits scanned for a changed or removed pin |
| `src/domain/registry.py` | NORMAL_READ | `load_parameter_set`, `verify_parameter_set`, `_parse_and_validate` |
| `.github/workflows/registry-gate.yml` | NORMAL_READ | trigger and re-hash step |
| `tests/test_backtest_determinism.py` | NORMAL_READ | its case builders reused by my probe |
| `src/backtest/experiment.py` | NORMAL_READ | identity payload (755-800), value pairs, digest helpers |
| `docs/research/experiments/research-run-1-v2-3-0/*.json` (240), `research-run-1/*.json` (240) | DEEP_READ (machine) | identity recomputed for all 480 |
| `docs/research/preregistration/research-run-1-manifest.json` | NORMAL_READ | fields listed |
| `docs/research/kill_gate_decisions.json`, `holdout_consumed.json` | DEEP_READ | both empty |
| `.planning/phases/24-live-runtime-composition-demo/evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-*.json` (3) | DEEP_READ (+ machine) | every field; fee/qty arithmetic re-derived by `smoke_check.py` |
| `.planning/phases/24-live-runtime-composition-demo/evidence/silence-probe-20261031T114816Z.json` | DEEP_READ | 15 server pings, 0 pongs, max gap 180374 ms |
| `scripts/demo_rehearsal.py` | NORMAL_READ (DEEP for 2270-3200) | the composed smoke: `_SMOKE_STEPS`, `_bring_up`, `_smoke_sequence`, `_safe_mode_drill`, `_replays`, `_record_cancel_lag`, attestation |
| `src/live/smoke_injection.py` | DEEP_READ | `/demo_signal` injector |
| `src/live/signal_source.py` | NORMAL_READ (86-132, 378-620) | `DemoSmokeSignalSource.derive_request` geometry and sizing |
| `src/live/startup.py` | NORMAL_READ (1078-1127) | HEALTH / ENABLE step outcome and code |
| `src/live/enablement.py` | METADATA_ONLY | `enable_demo` kill-gate refusal names via codegraph |
| `.planning/phases/16-paper-runtime-composition/evidence/16-65-gate.txt`, `16-66-gate-post-phase19.txt` | DEEP_READ + git re-check | IMAGE_COMMIT and tree-under-test claims re-derived |
| `.planning/STATE.md` (status block, gate lines) | NORMAL_READ | claims compared with evidence |
| `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md` (rows citing the smoke) | NORMAL_READ | "demo-observed" closures |
| `docs/DECISIONS.md` D113, D114 | NORMAL_READ | cite the 2026-11-15 smokes |
| `config/execution/execution-limits-v1.toml` header + `[stale_feed]` | NORMAL_READ | D091/D114 provenance |
| other `.planning/phases/*/evidence/` files (Phases 16, 18, 22, 23) | METADATA_ONLY | listed; only the gate records and Phase 24 smoke files were in my brief |

## Verified Safe Areas
- **Parameter sets match their pins (D-04/D-05).** All 73 `params/**/*.toml` load, hash and `verify_parameter_set` against
  `tests/fixtures/phase4/parameters.json`: 73 ok, 0 bad, no file without a pin, no pin without a file, no two sets with one hash
  (`tmp/evidence_reproducibility/rehash.out`). The hash covers the normalized `[params]` values, as `src/domain/registry.py:188-194` says.
- **No parameter file was edited in place since the first audit.** `git log` per file: only the five `*-v1` baselines have more than
  one commit, all dated 2026-09-22..26 (before the 2026-09-29 audit). The pin file's history (13 commits) shows two changed pins, both
  on 2026-09-25 (`1c3c1876`, the two `baseline-v1` sets of that week), none removed, none changed after.
- **The simulator is deterministic across processes and hash seeds.** `det.py` runs the multi-symbol scripted case, its shuffled
  variant, its prefix cut and the 250-bar phase 6 strategy case in three separate interpreters with `PYTHONHASHSEED` 0, 1 and 987654:
  the result line is byte-identical in all three (sha256 `ec30683cfa8b...`); shuffled input gives the same digest
  (`f09ec50f...`); the 3 terminal records of the prefix run are byte-identical in the extended run. The project's own tests cover the
  in-process rerun only; the cross-process, cross-seed run is new evidence. Limit: synthetic fixture cases, not the research data.
- **The committed research records are internally consistent.** For all 240 records of run 1 at 2.3.0 (and the 240 superseded 2.1.0
  ones): the file name equals `experiment_id`, and `experiment_id` is reproduced by `sha256_hex` over the identity payload of
  `src/backtest/experiment.py:770-787` from the record's own fields; `parameter_set_hash` is a pinned hash of the named set;
  `parameter_values` equals the TOML loaded today; 48 candidates x 5 windows (1 DEVELOPMENT, 4 VALIDATION), no HOLDOUT record;
  one `data_manifest_hash` and one `cost_model_hash`; `code_commit` `58a5374a` exists, is an ancestor of the snapshot HEAD and
  `code_dirty` is false (`records.out`). This proves the records are what the runner writes for those identities; it proves
  nothing about the trades (G-0901 / G-0902 of lane M09).
- **`holdout_consumed.json` and `kill_gate_decisions.json` agree with the records**: no HOLDOUT-role record exists and the holdout
  file has no entry; the decisions file is empty (the consequence of that emptiness is G-0901/G-0903 of lane M09, not repeated).

- **The two recorded gates name a real tree.** `16-65-gate.txt` (HEAD ce79193 -> IMAGE_COMMIT 9b27da5) and `16-66-gate-post-phase19.txt`
  (HEAD ee8a2aa -> IMAGE_COMMIT 36dcad8): re-running `git log -1 --format=%H <HEAD> -- <the listed paths>` gives exactly the recorded
  IMAGE_COMMIT in both cases, and both are ancestors of the snapshot HEAD 55885b9. The records say what they ran on. (Their age is G-1508.)
- **The smoke evidence is real Demo traffic where it says so.** The three files name `https://demo-fapi.binance.com`, carry Demo order ids
  (28668586471, 28681033217, 28681168442), mode EXECUTE, `evidence_kind` DEMO_OBSERVED; the attestation map is derived only from recorded
  step statuses (`scripts/demo_rehearsal.py:3134-3145`) and the FAILED run of 08:32Z was committed next to the passing one, not dropped
  (commit 55885b93). The recorded fill commission equals quantity x position entry price x the recorded taker rate to the 8th decimal in all
  three runs (`smoke_check.out`), so the fee and price fields are internally consistent.
- **The smoke cannot run against LIVE.** `demo_guarded_sdk_factory` (`scripts/demo_rehearsal.py:2345-2358`) refuses any non-DEMO
  environment and re-checks the client host; `admit_smoke_environment` (2364-2378) refuses a non-DEMO config; `build_demo_signal_command`
  (`src/live/smoke_injection.py:287-300`) returns None outside DEMO.
- **No pong in the evidence is expected, not a defect.** The 2026-10-31 silence probe counted 15 server pings and 0 pongs in 45 min
  (`silence-probe-20261031T114816Z.json`); the smoke liveness samples show a server ping every ~180 s and `last_pong_at_utc` null. The
  supervisor records a pong only on a `pong` event (`src/adapters/binance_userdata_supervisor.py:583-584`), which the client does not
  originate, so the pings are the liveness signal (D091 used them).
- **A real restart over the same stores was exercised once per passing run**: `restart` start sequence admitted with `plans_restored` 1,
  `restart_rehydrate` requires state COMPLETE (`scripts/demo_rehearsal.py:2826-2833`), and the replay presses changed neither open orders nor
  position amount (`_replays`, 3023-3040).

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D-04/D-05 + `registry-gate.yml`: parameter sets hash-locked, never edited in place | SOUND | re-hash of all 73 sets, pin history | holds by machine check and by git history (see Safe Areas) |
| D075/D076: research records carry identity + digest, regenerated on semantics change | SOUND (identity) / see G-0901 | recomputed `experiment_id` for 480 records | identity reproducible; trade content not (other lane) |
| AGENTS.md "recorded gate" rule (sequential, clean tree, PG, saved under evidence/) | SOUND as a rule, not applied since 2026-10-20 | git count of later code commits | G-1508 |
| D-33 composed smoke as the Phase 24 proof; 24-DEFERRED "demo-observed" = "the smoke lists the step OBSERVED" | DOUBTFUL | what each step asserts in code vs what the label is used to close | a step name is treated as a proven behaviour; several steps are injected, single-sample or assert less than their name (G-1503..G-1506) |
| Smoke evidence schema `demo-rehearsal-evidence/schema-1` (no code identity, ids only) | DOUBTFUL | accepted test-evidence practice: a record names the build it ran on and keeps the raw responses it judged | G-1501, G-1502 |
| D113 (bounded stop reread, 3 x 0.5 s) shown by the 10:42Z run | CANNOT_JUDGE (from evidence) | one sample after the fix; the evidence does not say whether a reread happened | G-1507 |
| D114 `protection_stall_after_ms` = 60000 from "886 ms longest run" | DOUBTFUL (provenance); value plausible | the 886 ms is in no committed file | G-1507; 60000 = max_unprotected_ms / 3 is plain arithmetic, fine for an alert-only bound |
| D091 `max_user_data_silence_ms` = 420000 from one 45-min probe | SOUND as order of magnitude, single sample | probe JSON; both later smokes show the same ~180 s ping cadence | 420000 > 2 x 180374 |

## Smoke 21/21 step by step (what each step really asserts)
Code: `scripts/demo_rehearsal.py` `_smoke_sequence` (2676-2880), `_safe_mode_drill` (2893-2960), `_replays` (3023-3040).
Request source: `/demo_signal` (`src/live/smoke_injection.py`) -> `DemoSmokeSignalSource.derive_request` (`src/live/signal_source.py:378-620`).
Kind: EX = real Demo exchange behaviour observed; OWN = the owner's real Telegram press; INJ = the smoke injects the cause; INT = internal
process state read from the project's own stores/objects. Every passing path is one sample per run; two passing runs exist
(2026-11-06 and 2026-11-15 10:42Z), on different code.

| # | Step | What the code checks | Kind | Not shown |
|---|---|---|---|---|
| 1 | start | `run_start_sequence` admitted; evidence keeps `name=outcome` only (2569) | INT + EX reads | step codes dropped: HEALTH=OK is written for OK and NO_TRADE alike (`src/live/startup.py:1108`); kill-gate state and degraded checks not recorded (G-1505) |
| 2 | wiring_check | `check_wiring` empty | INT | - |
| 3 | demo_enable | start outcome enabled, not SAFE_MODE, drift guard clear | INT | which ENABLE reason / health verdict |
| 4 | signal | `/demo_signal fill` queued a request | INJ | no strategy and no bar: `setup_type` DEMO_SMOKE, `latest_closed_bar_close = now.replace(minute=0, ...)` (`smoke_injection.py:172`), `bar_close_price` = the mark (`signal_source.py:144-148`) |
| 5 | card | plan row exists and the pump took the request | INT (+ Telegram send) | card content not recorded |
| 6 | approve | plan row status APPROVED | OWN | - |
| 7 | confirm_entry | the ENTRY intent row is ACKED | OWN + EX | "no entry-time stop (D079)" is not checked: `open_algo_orders_at_ack` = 1 in all three runs (G-1504); limit price, GTD time and quantity not recorded (G-1502) |
| 8 | stream_fill | coordinator state left AWAITING_FILL | EX (user-data stream) | the fill is IMMEDIATE: the fill-scenario LONG limit is `mark*(1+(up-1)*0.5)`, above the mark (`signal_source.py:405-408`), so it crossed the book; fee = qty x price x TAKER rate in all runs (`smoke_check.out`). Resting fill, partial fill, GTD expiry: never |
| 9 | stop_confirmed | `stop_confirmed_at_utc` set; one by-id read of the SL algo | EX | stop price and flags not recorded; the 08:32Z run shows the by-id read answering "not found" 0.53 s later (D113) |
| 10 | tp_legs | protection state COMPLETE (NOT_REHEARSED does not halt; COMPLETE_WITH_GAPS exits 0) | EX | TP prices / quantities not recorded |
| 11 | reconcile_clean | one `reconcile_tick_once`: agreement, 0 divergences | EX + INT | passed in the FAILED 08:32Z run while the process held SAFE_MODE ENTRY_WITHOUT_PROTECTIVE (D113 row); the step does not look at SAFE_MODE |
| 12 | restart | second wiring admitted | INT | orderly `shutdown_in_order` (2817) in the same Python process, seconds apart, position unchanged: no crash, no fill during downtime |
| 13 | restart_enable | enabled after restart | INT | - |
| 14 | restart_rehydrate | protection of the plan COMPLETE in the new wiring | INT | - |
| 15 | replays_place_nothing | owner re-presses; open normal orders empty and position amounts equal (`env.placements` is None in a real run) | OWN + EX | a replayed algo placement would not be seen (only normal orders and the position are compared) |
| 16 | close_cleanup | `operator_close_position` accepted, plan FLAT | EX | exit is an operator close: no stop trigger, no TP fill, no emergency close; SL and TP2 read EXPIRED (exchange side), TP1 CANCELED |
| 17 | reservation_released_on_close | reservation RELEASED with POSITION_CLOSED | INT | - |
| 18 | account_clean | 0 open orders, 0 algos, 0 positions on BTCUSDT | EX | other symbols not read |
| 19 | safe_mode_drill_signal | `/demo_signal far` queued | INJ | the main plan was first moved APPROVED -> EXPIRED by a direct store write (2902-2909), not by the runtime |
| 20 | safe_mode_drill | SAFE_MODE entered by `wiring.safe_mode.enter_safe_mode(reason="DEMO_SMOKE_DRILL")` (2929); owner CONFIRM placed nothing; `/safemode_exit` left it | INJ + OWN | no real SAFE_MODE trigger in a passing run |
| 21 | drill_reservation_released | after the plan expiry, reservation RELEASED with PLAN_EXPIRED | INT | - |

Never exercised by any of the three runs: a strategy-generated signal; a maker or resting fill; a partial fill; GTD expiry of a placed
entry; a stop trigger; a TP1 fill then stop resize; a TP2 fill; an emergency close; a real-cause SAFE_MODE in a passing run (the 08:32Z run
had one and failed); a crash restart; stream loss / listenKey expiry; a second symbol; any mainnet behaviour.

## Findings

### G-1501
- Severity: MEDIUM (now) / HIGH (mainnet with placement enabled)
- Confidence: CONFIRMED
- Classification: GAP
- Category: evidence integrity
- Component: Demo smoke evidence recorder
- File: `scripts/demo_rehearsal.py`; evidence under `.planning/phases/24-live-runtime-composition-demo/evidence/`
- Lines: 584-606 (`EvidenceRecorder.to_dict`)
- Rule: AGENTS.md "recorded gate ... fixes an IMAGE_COMMIT"; charter §5
- Known-prior: none
- Evidence: the top-level keys of all three smoke files are `attestation_map, base_url, constraints, details, exchange_orders, failures, mode, observations, outcome, planned_requests, runner_clock_utc, scenario, schema, steps, symbol, synthetic_inputs`: no commit, no dirty-tree flag, no limits-file or parameter-set hash, no alembic head, no kill-gate state (`smoke_check.out`: "top-level keys with code identity: NONE"). Git timeline: the 10:42Z run (17:42 +07) came 16 min after the D113 fix `d1c971c7` (17:26 +07) and about 1 h 40 before `75104781` (19:24 +07) changed `config/execution/execution-limits-v1.toml` (stall watchdog on). The 2026-11-06 run is still cited as the Phase 24 proof (`STATE.md:38`, AGENTS.md "passed 21/21 steps on 2026-11-06", 24-DEFERRED:9-12) although 26 `src` commits (+2109 / -207 lines in src, config and the smoke script) landed between its evidence commit e97198f2 and HEAD, and the 08:32Z run on later code FAILED.
- Expected: an evidence record that closes items names the exact tree (commit + clean flag) and configuration it ran on, as the gate records do.
- Actual: which code produced "21 of 21" cannot be established from the repository.
- Reproduction: `python -B -I tmp/evidence_reproducibility/smoke_check.py <evidence dir>`; `git log --since=2026-11-15 --format="%h %ad %s" --date=iso-strict`.
- Impact: a go-live judgement could rest on smoke results for code that is no longer the code; a regression between run and HEAD is invisible.
- Why tests miss it: the smoke tests check the step logic on fakes, not the identity fields of the evidence.
- Remediation: record `git rev-parse HEAD`, an empty `git status --porcelain`, the limits-file and parameter-set hashes and the alembic head; cite a smoke only for that commit.

### G-1502
- Severity: MEDIUM (now) / MEDIUM (mainnet)
- Confidence: CONFIRMED
- Classification: GAP
- Category: evidence integrity
- Component: Demo smoke evidence recorder
- File: `scripts/demo_rehearsal.py`
- Lines: 2514-2538 (`_record_order_ids`); 552 (`record_exchange_record`) and 567 (`set_constraints`) are not called by the composed smoke
- Rule: D-33, D079, RISK_MANAGEMENT §11
- Known-prior: none
- Evidence: in all three EXECUTE runs `exchange_orders: []`, `planned_requests: []`, `observations: []`, `constraints: {}`. Per step only ids are kept (`record_ids(order_ids, client_order_ids, algo_client_ids)`); the one algo status read in `stop_confirmed` is reduced to the word NEW. No limit price, GTD time, order quantity, stop price, TP prices / quantities, reduceOnly / closePosition flags, exchange filters, or the plan's entry / stop / TP levels are in the evidence.
- Expected: evidence that says "stop confirmed" and "TP1 and TP2 placed" lets a reader check that the exchange orders equal the plan and the quantization rules.
- Actual: the step texts are assertions of the script; the exchange answers they judged are not kept.
- Reproduction: open any of the three files.
- Impact: plan binding (price, side, quantity <= approved) and the TP split on the exchange cannot be audited from the Demo record.
- Why tests miss it: the fakes assert the fields in memory; nothing asserts what the evidence file must contain.
- Remediation: record the exchange echo of the entry, stop and TP placements (price, qty, flags, status) and the filters used, as the Phase 9 rehearsal's `leg_echoes` did.

### G-1503
- Severity: MEDIUM (now) / HIGH (mainnet with placement enabled)
- Confidence: CONFIRMED
- Classification: DESIGN
- Category: evidence scope / closure by relabelling
- Component: Phase 24 closure (24-DEFERRED, STATE, AGENTS.md) vs the composed smoke
- File: `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md`
- Lines: 9-12, 20, 31, 61, 78
- Rule: charter §2.7; D055 / D079 / D080; G4-029; 20D-23
- Known-prior: none
- Evidence: "demo-observed" is defined as "the committed smoke evidence ... lists the step OBSERVED" (24-DEFERRED:9-12) and closes D055 ("confirm_entry, stream_fill and stop_confirmed are OBSERVED"), G4-029 / 20D-06 (restart_rehydrate) and 20D-23 (safe_mode_drill). What those steps exercise (table above): the signal is injected (`smoke_injection.py:172`); the LONG limit sits above the mark (`signal_source.py:405-408`) and fills at once as taker (fee = qty x price x 0.0004 in all runs); the restart is an orderly shutdown in the same process; SAFE_MODE is entered by a direct call (`demo_rehearsal.py:2929`); the position is closed by the operator. The sizing geometry is not the real one either: risk is sized at `entry_max = 2*entry - entry_min` with `entry_min = 0.995*mark` (`signal_source.py:419-425`) while the fill is near the mark; with an assumed PERCENT_PRICE multiplierUp of 1.05 the sized risk per unit is about 0.0749 x mark against a real 0.0199 x mark, so the position carries about 27% of the risk budget.
- Expected: "demo-observed" closes only the behaviour the step exercised, with the unexercised branches listed.
- Actual: the fill-driven protection model (D055) is labelled demo-observed though no resting fill, partial fill, stop trigger, TP fill or emergency close has happened on Demo; every passing path is one sample.
- Reproduction: read `_smoke_sequence` (2676-2880) and `derive_request` (378-460); `smoke_check.out` fee lines.
- Impact: "21/21" can be read as "the protection life cycle works on the exchange". The paths most likely to lose money (stop trigger after a partial TP, a resting fill hours later, emergency close) are unobserved.
- Why tests miss it: the smoke tests run the same sequence on the Binance-semantics fake; they cannot show what the sequence leaves out.
- Remediation: label per behaviour, not per step name; add a resting-fill scenario, a stop-trigger exit and a TP1-fill-then-stop-resize run before Phase 26; list the unexercised paths in 24-DEFERRED.

### G-1504
- Severity: LOW (now) / LOW (mainnet)
- Confidence: CONFIRMED (claim unchecked); what the open algo order was: UNVERIFIED
- Classification: DEFECT
- Category: evidence assertion
- Component: smoke step `confirm_entry`
- File: `scripts/demo_rehearsal.py`
- Lines: 2729-2745
- Rule: D079 (no entry-time stop)
- Known-prior: none
- Evidence: the step records `"open_algo_orders_at_ack": len(open_algos)` and then always writes "one GTD LIMIT entry acknowledged; no entry-time stop (D079)". All three runs recorded `open_algo_orders_at_ack: 1`; in the 08:32Z run the protection state at that moment was already TP_UNAVAILABLE.
- Expected: the text is backed by a check (zero algo orders, or the one algo order is the coordinator's post-fill stop by client id).
- Actual: no check; because the entry fills at once the count cannot tell an entry-time stop from the post-fill stop or a leftover.
- Reproduction: `smoke_check.out`, "entry_acked" lines.
- Impact: the D079 statement in the evidence is not evidence.
- Why tests miss it: no test compares the detail text with the measured count.
- Remediation: record the client ids of the open algo orders at ack and assert none is an entry-time leg, or drop the claim.

### G-1505
- Severity: LOW (now) / MEDIUM (mainnet)
- Confidence: CONFIRMED
- Classification: DRIFT
- Category: evidence vs closure claim
- Component: 24-DEFERRED row D056; smoke `_bring_up`; start sequence HEALTH step
- File: `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md`; `scripts/demo_rehearsal.py`; `src/live/startup.py`
- Lines: 24-DEFERRED.md:21; demo_rehearsal.py:2569; startup.py:1108
- Rule: D056, D102
- Known-prior: none
- Evidence: 24-DEFERRED:21 closes D056 with "The smoke start enabled through the explicit DEGRADED flag (demo_enable OBSERVED)". The evidence keeps `f"{s.name}={s.outcome}"` only (2569), and HEALTH writes outcome OK for a clean and a NO_TRADE verdict alike (`run.note(STEP_HEALTH, OUTCOME_OK, "NO_TRADE" if verdict.is_no_trade else "OK")`, startup.py:1108). No health check names, DEGRADED list, ENABLE reason or kill-gate state are recorded.
- Expected: the closure cites a recorded fact that DEGRADED probes were present and accepted under the Demo flag.
- Actual: the evidence cannot show whether the verdict was clean, DEGRADED or NO_TRADE.
- Reproduction: `smoke_check.out`, "start HEALTH/ENABLE codes recorded".
- Impact: D056's Demo-only DEGRADED acceptance is unobserved; the same blind spot would hide a degraded start later.
- Why tests miss it: start-sequence tests check codes in memory; the evidence writer is not tested for them.
- Remediation: record `StepRecord.code`, `degraded_steps`, the health check names and the ENABLE reason.

### G-1506
- Severity: LOW (now) / LOW (mainnet)
- Confidence: CONFIRMED
- Classification: DEFECT
- Category: measurement that cannot measure
- Component: smoke `_record_cancel_lag`; 24-DEFERRED row 20D-35
- File: `scripts/demo_rehearsal.py`; `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md`
- Lines: demo_rehearsal.py:2851-2853 and 3077-3097; 24-DEFERRED.md:90
- Rule: D-34 ("how long a cancelled algo order still reads NEW by client id"); D089
- Known-prior: none
- Evidence: the lag polls start only after `_wait_until(second, flat)` (2851), and every first poll (t = 0.0 s) already reads a terminal status (SL EXPIRED, TP1 CANCELED, TP2 EXPIRED) in both passing runs. 24-DEFERRED:90 cites these observations as Demo evidence when closing 20D-35 (`max_unprotected_ms`).
- Expected: polls start right after each cancel request so a NEW-after-cancel window can be seen; the observation is not used for an unrelated limit.
- Actual: the measurement can only report "no lag"; the 08:32Z run showed the opposite lag (a resting stop read "not found" 0.53 s after placement, D113).
- Reproduction: `smoke_check.out`, "cancel lag first poll statuses".
- Impact: false comfort about by-id read consistency, the effect that failed the 08:32Z run.
- Why tests miss it: the fake answers instantly.
- Remediation: poll from the moment of each cancel and after each placement; remove the 20D-35 citation.

### G-1507
- Severity: LOW (now) / MEDIUM (mainnet)
- Confidence: CONFIRMED
- Classification: GAP
- Category: decision provenance / single sample
- Component: DECISIONS D113, D114; STATE.md status block
- File: `docs/DECISIONS.md`; `.planning/STATE.md`
- Lines: DECISIONS.md:117-118; STATE.md:38-39
- Rule: AGENTS.md source-of-truth order; charter §2.7
- Known-prior: none
- Evidence: D114 rests on "a longest `protection_step` run of 886 ms ... The 886 ms figure comes from a read-only query of those journal rows made on 2026-11-15 by the agent"; no committed file holds those `LIVE_TASK_DURATION` rows (a search for 886 finds only DECISIONS, RUNBOOK and the quick-task plan/summary text). D113's fix (3 rereads x 0.5 s) is followed by exactly one passing run whose evidence does not say whether a reread happened, i.e. whether the Demo read lag occurred at all. STATE.md:38-39 still reads "Demo smoke 21/21 on 2026-11-06" / "Last activity: 2026-11-07" and does not mention the FAILED 2026-11-15 run.
- Expected: a measured number behind a DECISIONS row is committed as evidence; a fix for an intermittent exchange read is shown by a run in which the condition occurred, or by repeated runs.
- Actual: D114's input is not reproducible from the repository; D113's efficacy is unshown; STATE lags.
- Reproduction: `grep -rn "886" docs .planning`; the 104211Z file has no duration rows.
- Impact: small now (alert-only bound); on mainnet the stop reread is on the protection path and 1.5 s is unproven against a lag of unknown size.
- Why tests miss it: the tests pin the chosen numbers, not their provenance.
- Remediation: export the duration rows and reread counters into the smoke evidence; count TP_UNAVAILABLE / reread events over several runs before calling D113 sufficient; update STATE.

### G-1508
- Severity: MEDIUM (now) / HIGH (mainnet with placement enabled)
- Confidence: CONFIRMED
- Classification: GAP
- Category: recorded gate age
- Component: release evidence (`.planning/phases/*/evidence/*gate*`)
- File: `.planning/phases/16-paper-runtime-composition/evidence/16-66-gate-post-phase19.txt`
- Lines: 1-30
- Rule: AGENTS.md "A recorded gate ... runs sequentially, on a clean tracked tree, with TEST_DATABASE_URL set"
- Known-prior: STATE.md:47 (the owner was to run a fresh gate after Phase 19)
- Evidence: the newest recorded gate is 2026-10-20, IMAGE_COMMIT 36dcad8 (re-verified). `git rev-list --count 36dcad8..55885b9 -- <gate paths>` = 572 commits, 306 touching `src`; `git diff --shortstat 36dcad8 55885b9 -- src` = 139 files, +43096 / -2037. No `IMAGE_COMMIT=` record exists for Phases 20-25 (23-VERIFICATION cites only a targeted `-n 4` subset of 899 tests; Phase 24 has no VERIFICATION file). The audit's own suite run (`tool-output/pytest.txt`) skipped the PostgreSQL tests (TEST_DATABASE_URL unset).
- Expected: the live composition (all of `src/live/`) has a recorded sequential gate with PostgreSQL on the tree the smoke and the owner runbook use.
- Actual: none; every live-process `_pg` test is unproven on any recorded tree.
- Reproduction: the git commands above, cwd = repository.
- Impact: the code that would place real orders has no recorded full-suite evidence including its database tests.
- Why tests miss it: process gap.
- Remediation: run and record the sequential PG gate on the current tree; tie the next smoke to that IMAGE_COMMIT (G-1501).

## Owner decisions
- **What counts as "Demo-proven" before Phase 26.** Today one immediate taker fill, closed by hand, stands for the whole fill-driven
  protection model. Example: a LONG limit 1% below the market that fills 3 hours later for 40% of its quantity, after which the stop
  triggers: none of these steps has run on Demo. Options: (a) accept the composed smoke as is; (b) require one Demo run each of resting
  fill, partial fill, stop trigger and TP1-then-stop-resize before go-live; (c) (b) plus N repeated runs (e.g. 5) of the basic sequence
  to catch intermittent Demo read lags like the 08:32Z failure.
- **Evidence must name its commit.** Whether a Demo run without a commit hash may close an item (G-1501).

## Open Questions
- Lane exec_protection: in the 08:32Z run the first process held SAFE_MODE ENTRY_WITHOUT_PROTECTIVE (per D113) while the stop rested on the
  exchange, and the smoke's `reconcile_clean` passed in that state. Is a by-id "not found" for a just-placed algo order enough to declare a
  position unprotected, and is 3 x 0.5 s of rereads enough?
- Lane live_composition: after a position closes the main plan stays APPROVED (D051 item i) and the smoke expires it by a direct store
  write (`demo_rehearsal.py:2902-2909`); in production the symbol stays blocked until plan expiry. Intended?
- Lane live_risk_state: the kill-gate state `enable_demo` accepted on Demo comes from the database, while
  `docs/research/kill_gate_decisions.json` is empty; which row enabled the Demo runs is recorded nowhere in the evidence.
- The FAILED 08:32Z run left a position and a stop on Demo (account_clean NOT_OBSERVED); how it was cleaned before the 10:42Z run is not
  recorded.

## DONE
