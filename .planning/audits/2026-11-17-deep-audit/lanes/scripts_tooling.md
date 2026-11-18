# Lane M13: scripts_tooling

## Scope
`scripts/**` and `tests/demo/**` of snapshot `55885b9` (read only; no Demo script was run, no `--execute`, no `pytest -m demo`).
Questions: mainnet guards of the owner-run Demo scripts; what they can cancel/close; the decision-alignment gate; fixture generators (self-confirming goldens); soak/evidence evaluators.

## Coverage
| File | Level | Note |
|---|---|---|
| scripts/demo_clear.py | DEEP_READ | whole file; guards = env var + typed phrase + unresolved-intent count |
| scripts/demo_rehearsal.py | NORMAL_READ | header, credentials, host guard (l.375-460), argparse/--execute gate (l.1082-1135), smoke admission (l.2345-2400), smoke sequence (l.2557-2880); taps scenario and evidence writer skimmed |
| scripts/demo_probe.py | NORMAL_READ | header/safety posture, cleanup_symbol (l.1104-1160), order_bound_refusal / margin_order_refusal (l.1310-1400), build_live_rig (l.6591-6700); 60+ case handlers skimmed by grep only |
| scripts/user_data_smoke.py | NORMAL_READ | guards by grep (environment choices l.171, phrase l.319, stream URL guard l.404, build_live_rig l.792-826); shares the guard design of demo_probe |
| scripts/user_data_silence_probe.py | DEEP_READ | whole file; DEMO forced through user_data_smoke.parse_config/build_live_rig |
| scripts/verify_decision_alignment.py | DEEP_READ | dispatcher, EXPECTED_MIN gate counts |
| scripts/decision_alignment/ops_risk.py | DEEP_READ | OR-01..OR-11: phrase presence / forbidden regex over docs only |
| scripts/decision_alignment/bookkeeping.py | NORMAL_READ | DC-01..DC-06 (table shape, D043-D045 tokens), glossary reason codes vs `src/domain/enums` (the one code-reading check), reqs |
| scripts/decision_alignment/authority.py | NORMAL_READ | AGENTS.md / PROJECT.md / STACK.md byte rows and quantization order line |
| scripts/decision_alignment/exchange.py | NORMAL_READ | EX gates: phrases + cited-URL register over docs |
| scripts/decision_alignment/params.py | NORMAL_READ | imports `src.domain.registry` and re-hashes sets: real code check |
| scripts/decision_alignment/protocol.py | NORMAL_READ | protocol header/witness rows; candidate hash recomputed with `sha256_hex` |
| scripts/decision_alignment/universe.py | METADATA_ONLY | content hash of the universe file |
| scripts/evaluate_demo_soak.py | DEEP_READ | criteria l.573-870, evaluate_journal l.880-912, _cmd_evaluate l.1009-1036; export l.1039-1077 skimmed |
| scripts/evaluate_trial_soak.py | DEEP_READ | whole file; the criteria live in `src/paper/exit_criteria.py` (paper lane) |
| scripts/export_soak_evidence.py | NORMAL_READ | header (bundle layout, publish, host witness), source/proof-class handling l.208, 698-800; rclone publish code skimmed |
| scripts/soak_host_acceptance.py | DEEP_READ | whole file: a form validator of owner-typed PASS lines (documented as such) |
| scripts/_compute_phase4_fixtures.py | NORMAL_READ | imports `src.core.*` to compute expectations ("hand-verified then committed") |
| scripts/_regen_phase4_expectations.py | NORMAL_READ | header: regression snapshots of planner output, never writes parameters.json |
| scripts/_extend_phase4_candles.py | METADATA_ONLY | additive CSV input builder, no src import |
| scripts/gen_phase6_fixtures.py | NORMAL_READ | inputs only, no src import; expected = engine snapshots (labelled so, REGRESSION_SNAPSHOTS.md) |
| scripts/gen_phase14_fixtures.py | NORMAL_READ | inputs only; verified no `src`/`tests` import; expected.json hand-derived per DERIVATIONS.md (not re-derived here: X04's job) |
| scripts/gen_phase21_fixtures.py | METADATA_ONLY | unflattens recorded Demo captures; no src import |
| scripts/gen_phase22_fixtures.py | METADATA_ONLY | same, configuration reads |
| scripts/gen_phase23_fixtures.py | NORMAL_READ | renders golden texts by calling the src formatters themselves (self-confirming wording goldens) |
| scripts/geometry_census.py | METADATA_ONLY | header: counts only, neutral constraint snapshot, own invariant checker |
| scripts/smoke_backtest_realdata.py | METADATA_ONLY | header: runs simulator twice, compares digests |
| scripts/shadow_rehearsal.py | METADATA_ONLY | header: SHADOW only, refuses BINANCE_*, operator flag for live Telegram |
| scripts/check_image_paths.py | METADATA_ONLY | header: in-image load check, no network |
| scripts/repair_parquet_scale.py | DEEP_READ | whole file: dry run default, copies only, exactness round-trip guard |
| scripts/backup-drill.ps1 | NOT_READ | ops lane |
| scripts/dev/*.ps1, scripts/dev/README.md, scripts/dev/pytest_timing.py | NOT_READ | developer helpers, no money path |
| tests/demo/conftest.py | DEEP_READ | session guard via `tests/support/demo_guard.py` (read too) |
| tests/demo/test_demo_s01_happy.py, test_demo_s13_margin_liquidation.py | NORMAL_READ | thin wrappers over `tests/support/demo_scenarios/*` |
| tests/demo/test_demo_s00, s02-s12, s14-s19 | METADATA_ONLY | same wrapper shape (22-69 lines each); scenario bodies are in tests/support (X03 lane) |
| tests/demo/__init__.py | METADATA_ONLY | empty |
| scripts/paper_ws_smoke.py | METADATA_ONLY | header: public data only, refuses any BINANCE_* variable, no order adapter |

## Verified Safe Areas
- **Demo rehearsal cannot reach mainnet REST.** `scripts/demo_rehearsal.py:190` pins `DEMO_BASE_URL` to the SDK constant; `build_demo_sdk_client` (l.397-410) has no host parameter and re-checks the built client through `assert_endpoint_url` against `ENVIRONMENT_ROWS[DEMO]` (l.375-394); the composed smoke goes through `demo_guarded_sdk_factory` (l.2345-2358), which raises unless `environment is Environment.DEMO` and re-reads the host after the build; `admit_smoke_environment` (l.2364-2383) reuses the live process's own `parse_live_environment` (refuses LIVE credentials next to DEMO mode) and refuses any mode other than DEMO. No `--host`, `--base-url` or `--symbol` option exists (`_build_parser` l.1082-1112, `allow_abbrev=False`).
- **`--execute` gate.** demo_rehearsal (`_confirm_execute` l.1119-1132), demo_probe (l.520, l.7085-7098), user_data_smoke (l.319, l.2485) and user_data_silence_probe (l.149-153) all need `isatty()` AND an exact typed phrase before any network call; dry runs use fakes.
- **demo_probe / user_data_smoke credentials.** `build_live_rig` loads only the selected environment's credential spec with `refuse_if_present=(credential_spec_for(Environment.LIVE),)` (demo_probe l.6650-6654); `ENVIRONMENT_CHOICES` is only DEMO/TESTNET (l.222); the REST guard `assert_environment` and the WS `assert_stream_url` run before every call (l.6667-6671).
- **demo_probe order size.** Every write case passes `order_bound_refusal` (l.1310-1345): positive, on step grid, <= the owner-approved quantity, notional <= `max_notional_quote` (refuses when the cap is unset). The two documented exceptions (`market_lot_probe_quantity` exact match; `insufficient_margin_quantity` as a far LIMIT BUY strictly below mark, l.4393-4420) are owner-keyed and cannot fill at once.
- **demo_probe cleanup** (`cleanup_symbol` l.1104-1160) cancels orders and algo orders of the probe symbol only and closes residual positions reduce-only (one-way) or by position side (hedge); unknown position mode sends no close (fail closed).
- **Demo pytest suite** (`tests/demo/conftest.py` + `tests/support/demo_guard.py`): refuses any `BINANCE_LIVE_*` name, an xdist worker, `TRADING_DEMO_RUN != "1"`, then reuses `admit_smoke_environment` (DEMO only); the env builder wraps `dr.demo_guarded_sdk_factory` (`tests/support/demo_scenarios/demo_env.py:230-234`). Collection-time skip unless `-m demo` (pyproject marker l.57).
- **Hand-derived goldens are independent where claimed.** `gen_phase14_fixtures.py` imports only stdlib (l.30-37); `gen_phase6_fixtures.py` writes inputs only and labels its expectations as engine regression snapshots (l.29-33). The self-confirming generators (`_regen_phase4_expectations.py`, `gen_phase23_fixtures.py`) are documented as regression/wording snapshots, not correctness proofs.
- **repair_parquet_scale.py** never writes in place: output root must be outside and empty (l.72-75), each cast is round-trip checked (l.82).
- **soak_host_acceptance.py** says plainly that it "never decides whether a check really passed" (l.19-21); it only refuses incomplete forms and secret-looking values.
- **user_data_silence_probe** places no order; DEMO is hard-coded in the argv it passes to `user_data_smoke.parse_config` (l.69-77); `--minutes` bounded 5..240.

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| Owner-run Demo tools: dry run by default, `--execute` = TTY + exact typed phrase, no host option, host re-checked after client build | SOUND | accepted practice for tools that touch a real account | the guard is in code at the single client-building point, not only in docs |
| Demo/LIVE separation by credential names + `LIVE_RUNTIME_MODE` env var (scripts reuse `parse_live_environment`) | SOUND for REST/WS host; DOUBTFUL for the database | what the guard binds | the exchange host is bound by code; the database is bound only by the operator's env (G-0503, G-1301) |
| `verify_decision_alignment.py` as the "docs<->code gate" (AGENTS.md) | DOUBTFUL | what the checks read (probe P1) | a doc-wording lint; only params/protocol/reason codes touch code; nothing for D076-D114 (G-1300) |
| Demo soak judged from the journal only, window = first..last row (plan 25-07) | DOUBTFUL | D061/D063 paper-soak rule (coverage >= 95 %, gaps break the window); probe P2 | no coverage criterion; export window chosen freely; image_commit unchecked (G-1302) |
| Soak duplicate_entry from LIVE_PLACEMENT_OUTCOME rows | WRONG | producer id is deterministic per approval + ON CONFLICT DO NOTHING | the main duplicate mode cannot produce a second row (G-1303) |
| Proof class follows the bundle `source` only; a FAKE bundle may still exit 0 with a note | DOUBTFUL | fail-closed principle | a fixture bundle exits 0; only the text says it cannot close a requirement (G-1304) |
| Fixture policy: hand-derived goldens for the simulator (phase14), labelled engine regression snapshots elsewhere | SOUND | testing practice | the labels are honest; regression snapshots are not sold as correctness |
| demo_probe owner-keyed exceptions to the notional cap (MARKET_LOT_SIZE exact qty; -2019 far LIMIT BUY below mark) | SOUND | order cannot fill at once; quantity is owner-typed | bounded, documented, per-case flag |
| Clearing stale Demo approvals by a side script instead of the process (demo_clear) | DOUBTFUL | single-writer principle of the state machine | second writer of plan status and SAFE_MODE; no process-down check (G-0503, G-1301) |

## Findings

### G-1300
- **ID:** G-1300
- **Severity (now / mainnet):** MEDIUM / MEDIUM
- **Confidence:** CONFIRMED (probe `tmp/scripts_tooling/p1_gate_strings.py`)
- **Classification:** DESIGN
- **Category:** assurance gate checks words, not meaning; no coverage of the execution model
- **Component:** `scripts/verify_decision_alignment.py`, `scripts/decision_alignment/*`
- **File:** `scripts/decision_alignment/ops_risk.py` (representative)
- **Lines:** ops_risk.py:57-76, 107-123, 280-283, 378-398; bookkeeping.py:432-528
- **Rule:** AGENTS.md "Commands": `verify_decision_alignment.py all    # docs<->code gate`; D031 source-of-truth order
- **Known-prior:** none found
- **Evidence:** `_missing(text, phrases)` is `[p for p in phrases if p not in text]`-style presence; `check_sl_and_compensation` passes when `"never a wider"`, `"averaging down"`, `"D034"` occur anywhere in RISK_MANAGEMENT sections 6-7. Probe output: a section that reads "The restored stop may be wider ... averaging down is fine. D034" returns `('OR-08', True, 'ok')`; a SECURITY_AND_OPERATIONS section 7 that says "It is false that SAFE_MODE blocks new entry orders only ..." returns `('OR-01a', True, 'ok')`. Only three modules touch code at all: `params.py` (re-hashes parameter sets through `src.domain.registry`), `bookkeeping.referenced_reason_codes` (reason codes vs enums) and `protocol.py` (candidate hash). The D-numbers referenced by any gate stop at D075 (grep of `scripts/decision_alignment/*.py`: D042-D075); no gate mentions D076-D114, i.e. the whole Phase 19-24 execution model (D079 GTD entry without stop, D080 no re-send, D098-D107 live composition, D114 stall bound). `tool-output/decision-alignment.txt`: 68 PASS, `ALL_PASS all`.
- **Expected:** a gate described as "docs<->code" checks that the code does what the doc row says (e.g. reads the constant, enum or config the row governs), or is described honestly as a doc-wording lint.
- **Actual:** it is a doc-wording lint frozen at the Phase 11 decisions; `ALL_PASS` says nothing about whether `src/` follows D031-D114, and nothing at all about D076-D114.
- **Reproduction:** `PYTHONPATH=<snapshot> python -B tmp/scripts_tooling/p1_gate_strings.py`.
- **Impact:** the owner (who cannot judge the code) may read `ALL_PASS all` as proof that docs and code agree. Drift between the execution docs and `src/execution`, `src/live` is never caught by it; only unit tests stand there.
- **Why tests miss it:** `tests/test_decision_alignment*` test that the gates detect a removed phrase, i.e. they test the lint, not the alignment.
- **Remediation:** rename/describe it as a doc-consistency lint in AGENTS.md and RUNBOOK; for money/safety rows add code-reading checks (constant/enum/config value read through import, as `params.py` already does) and extend coverage to D076+.

### G-1301
- **ID:** G-1301
- **Severity (now / mainnet):** LOW / INFO
- **Confidence:** CONFIRMED (code read; script not run)
- **Classification:** GAP
- **Category:** owner tool can run against a live process; check and writes not atomic
- **Component:** `scripts/demo_clear.py`
- **File:** `scripts/demo_clear.py`
- **Lines:** 100-137 (main), 43-78 (clear_open_plans)
- **Rule:** RUNBOOK section 22 rehearsal procedure step 2; module docstring "refuses while an execution intent is unresolved"
- **Known-prior:** the direct SAFE_MODE write and the env-var-only Demo guard are G-0503 (lane reconcile_safemode); not repeated here
- **Evidence:** the unresolved-intent check is a separate `engine.connect()` read (l.116-119) closed before any write; the plan transitions (l.53) and the journal rows (l.59) are separate store calls with no shared transaction and no lock; nothing checks that the live process (or its Telegram bot) is stopped. RUNBOOK step list for the rehearsal (steps 1-3) asks to flatten the Demo account, then run demo_clear, then the rehearsal; it does not say to stop the `live` service before demo_clear (only the rehearsal docstring, l.27, says "Stop the live service first").
- **Expected:** the tool refuses unless the live process is down (e.g. its liveness stamp is stale or the held marker is present), or does check and writes in one transaction.
- **Actual:** with the live process running, an owner CONFIRM between the intent check and `transition_trade_plan(... EXPIRED)` can create an intent (and send a Demo entry) for a plan the script then expires; the running process also keeps SAFE_MODE in memory while the database row now says off.
- **Reproduction:** read-only: l.115-133 show the sequence; no lock or liveness check exists in the file.
- **Impact:** Demo only (the script is DEMO-gated). Worst case is a Demo entry whose plan is EXPIRED in the database, i.e. an inconsistent rehearsal state and a void smoke; no mainnet path.
- **Why tests miss it:** `tests/test_demo_clear.py` drives `clear_open_plans` / `exit_safe_mode` with fakes; `main()` and concurrency are not exercised.
- **Remediation:** refuse when the live liveness stamp is fresh; add "stop the live service" to RUNBOOK step 2.

### G-1302
- **ID:** G-1302
- **Severity (now / mainnet):** MEDIUM / HIGH
- **Confidence:** CONFIRMED (probe `tmp/scripts_tooling/p2_soak_two_rows.py`)
- **Classification:** DESIGN
- **Category:** soak evaluator passes on a journal that does not show a soak
- **Component:** `scripts/evaluate_demo_soak.py` (Phase 25 criterion 3, the evidence the mainnet step will rest on)
- **File:** `scripts/evaluate_demo_soak.py`
- **Lines:** 620-646 (order_after_registration), 658-684 (window/duration), 819-860 (round trips), 880-912 (evaluate_journal), 1009-1036 (`_cmd_evaluate`)
- **Rule:** plan 25-07 / 25-24 / 25-25 (multi-week Demo soak, D040); compare D061/D063 (paper trial soak: >= 95 % HEALTHY coverage, any gap is uncovered and breaks the window)
- **Known-prior:** none; 25-DEFERRED.md 25-07-C1 records only the payload-key pinning
- **Evidence:** `compute_window` = first journal row to last journal row (l.658-671); `check_duration` compares only that span with `duration_days`. No criterion reads the spacing of rows: there is no coverage / uptime / heartbeat-gap criterion. `check_order_after_registration` returns PASS with "no order event in the journal" (l.622-628); `check_round_trips` is SKIPPED when `owner_round_trips_per_week` is null (l.822-829). Probe: a journal of two healthy `HEALTH_VERDICT` rows 22 days apart, registration `duration_days=21`, round trips null -> `passed: True`, every criterion PASS, round_trips SKIPPED. Further: the journal is whatever `export --since T1 --until T2` wrote (l.1039-1077); the evaluator never checks that T1 is at or before the registration commit, so exporting from a later T1 drops early bad rows without any defect annotation (the restart rule of l.32-38 is bypassable by the export window). `registration.image_commit`, `symbols`, `account`, `host` are parsed but never compared with anything in the journal (e.g. the application revision of the start rows). `--registration-committed-at` is typed by the owner, not read from git.
- **Expected:** a soak verdict that, like the paper trial (D063), fails when the process was down for a material part of the window (e.g. HEALTH_VERDICT / reconcile-tick spacing above a ratified gap), requires the journal to start at the registration, and checks the running revision against `image_commit`.
- **Actual:** PASS is possible for a process that ran one hour at the start and one hour at the end of 22 days, or for an export that starts after the bad week, or for a different image.
- **Reproduction:** `PYTHONPATH=<snapshot> python -B tmp/scripts_tooling/p2_soak_two_rows.py`.
- **Impact:** now: the soak has not run, nothing is wrong yet. Mainnet: the Demo soak PASS is the gate evidence before real money; a PASS that does not prove continuous healthy operation could let an unproven process go to mainnet. Note: the owner is the one exporting, so this is about accident and self-deception, not an attacker.
- **Why tests miss it:** `tests/test_evaluate_demo_soak.py` builds journals with dense rows; no test feeds a sparse journal or a late `--since`.
- **Remediation:** add a coverage criterion (max gap between consecutive reconcile ticks / health verdicts, threshold ratified like D061), require `first_event_utc <= registration commit + start grace`, compare the start rows' revision with `image_commit`; make round_trips mandatory (> 0) or record SKIPPED as not-PASS for the gate.

### G-1303
- **ID:** G-1303
- **Severity (now / mainnet):** LOW / MEDIUM
- **Confidence:** CONFIRMED (code read of producer, journal store and evaluator)
- **Classification:** DESIGN
- **Category:** a soak criterion that cannot see the defect it is named after
- **Component:** `scripts/evaluate_demo_soak.py::check_duplicate_entry` vs `src/live/execution_service.py`, `src/persistence/journal.py`
- **File:** `scripts/evaluate_demo_soak.py`
- **Lines:** 740-769; producer `src/live/execution_service.py:264-272, 301-329, 338-346`; store `src/persistence/journal.py:98-115`
- **Rule:** owner rule "a placement is never re-sent" (AGENTS.md, D080); soak criterion duplicate_entry (docstring l.48-52)
- **Known-prior:** none
- **Evidence:** the outcome row's id is `correlated_event_id(prefix, correlation_id="demo-send:<approval_id>", event_type, entity_id=approval_id, step="outcome")` - a pure function of the approval. `PgJournalStore.append` inserts with `on_conflict_do_nothing(index_elements=["journal_event_id"])` and then `_verify_replay` (a second row for the same approval is a no-op or a `JournalConflict`), and `_arecord` swallows any journal exception (`log.warning(... journal_failed ...)`). So a second `LIVE_PLACEMENT_OUTCOME` for the same approval can never appear in the journal; the evaluator groups by `trade_plan_id or approval_id or entity_id` (l.744-746), so it can only see two outcomes for one plan when the plan had two approvals. The remaining duplicate signal is the reconcile counts `DOUBLED_POSITION` / `DUPLICATE_EXCHANGE_ID`, which see a duplicate only if it filled or is still open at a tick.
- **Expected:** the duplicate-entry criterion counts placements at the source of truth for sends (execution_intents rows per approval, or the exchange order list per client id prefix), or says honestly that it relies on the reconcile kinds.
- **Actual:** the journal half of the criterion is structurally always 0 for the main failure mode (one approval, two sends); a journal write failure also makes any row vanish silently.
- **Reproduction:** read the three cited places; no probe needed (deterministic id + ON CONFLICT DO NOTHING).
- **Impact:** a duplicate entry that was cancelled or expired unfilled before a reconcile tick leaves no trace the evaluator reads; the soak PASS overstates the evidence for D080.
- **Why tests miss it:** the evaluator tests write two outcome rows with different ids by hand, which the real producer cannot do.
- **Remediation:** count placements from `execution_intents` (export them with the journal) or from the exchange's order history per approval-derived client id; journal per-send rows with a send counter in the id.

### G-1304
- **ID:** G-1304
- **Severity (now / mainnet):** LOW / LOW
- **Confidence:** CONFIRMED (code read)
- **Classification:** DESIGN
- **Category:** evaluator exit code ignores the proof class
- **Component:** `scripts/evaluate_trial_soak.py` + `src/paper/exit_criteria.py` (`passed`, `render`)
- **File:** `scripts/evaluate_trial_soak.py`
- **Lines:** 150-161; `src/paper/exit_criteria.py:174-188`
- **Rule:** SC9 "fake-level evidence never closes PAPER-01"; fail closed
- **Known-prior:** none
- **Evidence:** `passed` is `all(r.passed for g in self.groups for r in g.results)` (exit_criteria.py:174-175); the proof class only adds the text line "note: this evidence is not REAL_SOAK; it can never close a requirement (SC9)." (l.185-188). `main` returns `EXIT_PASS if evaluation.passed` (evaluate_trial_soak.py:161). A bundle exported with `--source fixture --records <file>` (export_soak_evidence.py:3, 716-736) therefore exits 0. The manifest `source` field is written by the exporter and covered only by the bundle's own manifest, so it is not a tamper-proof attribute.
- **Expected:** a non-REAL_SOAK bundle exits with a distinct non-zero code (or a NOT_QUALIFYING verdict line).
- **Actual:** exit 0 for a fixture bundle that satisfies the criteria.
- **Reproduction:** read the cited lines.
- **Impact:** low: the owner runs it by hand and the text carries the note; a wrapper or CI step keyed on the exit code would accept fixture evidence.
- **Why tests miss it:** tests assert the note, not the exit code for FAKE (not exhaustively checked).
- **Remediation:** return a dedicated exit code when `proof_class is not REAL_SOAK`.

## Owner decisions
- **Demo soak gap rule (G-1302).** Decide the maximum silent gap the soak tolerates, as for the paper trial (D061: >= 95 % of 14 days covered = 319.2 h of 336 h). Example: for `duration_days=21` (504 h) the same 95 % rule allows 25.2 h of total downtime; today the evaluator would also pass about 502 h of downtime (probe P2). Also decide whether `owner_round_trips_per_week` may be null (today: criterion SKIPPED, verdict still PASS with zero trades).
- **Demo database identity (G-0503/G-1301).** Decide whether the operational database must carry a mode marker (DEMO / LIVE) that every owner script and the live process compare with `LIVE_RUNTIME_MODE`, instead of trusting the shell variable.

## Open Questions
- (live_composition lane) `src/live/wiring.py:379` builds `PgShadowStores(db, confirm_mode="DEMO")` unconditionally in `build_pg_stores`; is LIVE mode composed with a DEMO-scoped approval store, or is LIVE not composable yet?
- (live_composition / reconcile lanes) `scripts/demo_rehearsal.py:2617-2631` comments that the start sequence's CLOCK_DRIFT step "passes when the MEASUREMENT works, not when the clock is inside the limits"; the smoke then checks the drift guard itself. Does a production start enable entries with the host clock outside the drift limit, leaving only the per-placement guard?
- (X04) `_compute_phase4_fixtures.py` says outputs "are hand-verified then committed" but computes them with `src.core.*`; whether that hand verification exists was not checked.
- (X03) The Demo pytest suite presses APPROVE/CONFIRM programmatically (`tests/support/demo_scenarios`); its evidence proves the process, not the human approval path (test_demo_s01 docstring says the 2026-11-06 smoke stays the Telegram-tap proof).
- The smoke's failure path (`run_composed_smoke` finally: `shutdown_in_order`) stops the process but does not flatten; a stop between `stream_fill` and `stop_confirmed` leaves a Demo position whose protection depends on the next start. RUNBOOK step 4 asks the owner to check the account is flat; acceptable for Demo, noted only.
- Not inspected: the 60+ individual demo_probe case handlers beyond the bound functions, user_data_smoke observation steps, export_soak_evidence publish/witness code paths, backup-drill.ps1, scripts/dev/*.

## DONE
