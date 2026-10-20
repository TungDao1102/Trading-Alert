# Phase 18 Traceability (plan 18-22)

base: d7be0a57b19f34b7dbd8285844b32cc7a0b44173 (HEAD when plan 18-22 started, branch `phase-18-smoke`, worktree `Trading-Alert-p18`)

Scope: every ROADMAP criterion, requirement id, CONTEXT decision, folded inherited item, owner-only item, research finding and pitfall is mapped to the plan that built it and to the test or evidence that covers it. Evidence levels used below:

- **library-proven offline**: proven by tests against fakes, SDK-shaped fakes, the installed SDK objects or synthetic frames (label `SYNTHETIC_FROM_SDK_MODEL`). Nothing was sent to Binance.
- **Demo-observed**: seen on Binance Demo (`demo-fapi.binance.com`, `wss://demo-fstream.binance.com`) by the user-run smoke or probe on 2026-10-16. Demo is not mainnet; nothing here was used to choose a trading parameter.
- **not yet observed**: no evidence exists. Stated as such, never filled in.

No requirement, ROADMAP, STATE or DECISIONS file is edited by this plan. D055 stays OPEN.

Plans 18-01 to 18-21, 18-23 and 18-24 had a SUMMARY when this file was written. Plan 18-25 (documents and the D055 evidence draft for the user) was not executed then, so the statements below that depend on it were marked "18-25 pending". Plan 18-25 is done (commits afcfe5e, aedb3b5, fc1c255; `18-25-SUMMARY.md`): where a row below says "18-25 pending", read it as done by 18-25 and see that SUMMARY; the Demo-observed document rows are in `docs/SOURCES.md` and the D055 draft is `decisions/18-DRAFT-D055-evidence-for-user.md`.

## 1. Goal and ROADMAP success criteria

| Item | Plans | Test or evidence | Evidence level |
|---|---|---|---|
| GOAL: fills, order and algo state, and account changes learned in real time; errors read by code; Demo targetable | 18-03, 18-05, 18-11, 18-14, 18-15, 18-04, 18-09 | `tests/test_phase18_gate.py` (inventory, symbols, requirement tests, nine invariants) | library-proven offline; Demo-observed for delivery (see EXEC-05) |
| Criterion 1: user-data stream (listenKey lifecycle, ORDER_TRADE_UPDATE, ALGO_UPDATE with `o.rm`, ACCOUNT_UPDATE, `/private` URL), feeds `fold_fills` and reconciliation, REST is fallback (F-104, F-054) | 18-03 (events, parsers, `to_fill_event`), 18-11 (adapter, listenKey port), 18-14 (supervisor), 18-15 (router, replay), 18-24 (fixtures), 18-16 (smoke script), 18-18 (live smoke) | `tests/test_userdata_events.py`, `test_userdata_parsers.py`, `test_userdata_adapter.py`, `test_userdata_contract.py`, `test_userdata_supervisor.py`, `test_userdata_router.py`, `test_userdata_replay.py`, `test_userdata_rig.py`, `test_userdata_fixtures.py`, `test_userdata_recorded_frames.py`; `evidence/18-smoke-check.txt` | library-proven offline; Demo-observed: the SDK `user_data` route delivered typed ORDER_TRADE_UPDATE NEW and CANCELED, keepalive and a forced drop (UNKNOWN, SYNCING, LIVE) worked. The `/private` URL form (path form against `?listenKey=&events=`) is NOT settled: the SDK worked, the form it uses was not captured |
| Criterion 2: probe records not-found codes for GET order and GET algoOrder, duplicate `clientAlgoId` code, id reuse after FILLED and CANCELED; fake corrected; adapter mappings keyed on `status_code` (-2011, -2013, -2019, -4164, -1021, -2021; F-501, F-205, F-503, F-502) | 18-05 (taxonomy), 18-10 (not-found routing), 18-12 (probe adapter), 18-17 and 18-23 (probe), 18-20 (live probe), 18-21 (fake corrected, table marks) | `tests/test_exchange_errors.py`, `test_sdk_error_mapping_contract.py`, `test_adapter_not_found_mapping.py`, `test_binance_usdm_error_routing.py`, `test_fake_binance_semantics.py`, `test_demo_probe_cases.py`; `evidence/18-probe-check.txt` | Demo-observed: GET order and GET algoOrder -2013, cancel order and cancel algo -2011, duplicate `clientAlgoId` -4116, id reuse accepted after CANCELED (normal and algo) and after FILLED (normal, second run). Table codes -2019, -4164, -1021 are documented and offline-proven only (not observed on Demo) |
| Criterion 2, D055 probe cases | 18-17, 18-23, 18-20 | `evidence/18-probe-check.txt` (16 required cases) | Demo-observed for 14 of 16 after the second run; **not observed**: `partial_fill` (every marketable entry filled completely) and `triggered_market_exit_lifecycle` (trigger not reached within `case_timeout_seconds`). D055 stays OPEN |
| Criterion 3: explicit REST timeouts, API key loading, Demo/testnet/live selection, recvWindow with fail-closed drift check, no retry on 418 and `retry_after` honored (F-504, F-128, F-505, F-706, F-506) | 18-04 (environment, factory, redaction), 18-07 (limits structures, drift guard), 18-09 (ratified file), 18-10 (shared rate-limit gate), 18-13 (recvWindow on every signed call, drift guard on entries) | `tests/test_binance_client_config.py`, `test_binance_secret_redaction.py`, `test_binance_limits.py`, `test_binance_limits_ratified_file.py`, `test_clock_drift.py`, `test_no_unratified_defaults.py`, `test_binance_ratelimit_gate.py`, `test_binance_usdm_signed_calls.py` | library-proven offline. Demo-observed only that the smoke read a clock offset of -298 ms (within limits) and that Demo accepts the explicit environment; no 418 or 429 was ever observed |

## 2. Requirements and evidence level

| Requirement | Plans | Automated tests (resolved by `test_phase18_requirement_tests_exist`) | Evidence level (state it, do not round up) |
|---|---|---|---|
| EXEC-05 (user-data stream drives fills and state, REST fallback) | 18-03, 18-11, 18-14, 18-15, 18-16, 18-18, 18-19, 18-21, 18-24 | `test_userdata_adapter.py::test_tracer_sdk_order_trade_update_becomes_queued_event_and_fill`, `test_userdata_supervisor.py::test_tracer_start_live_close_unknown_rebuild_snapshot_live_after_gap`, `test_userdata_replay.py::test_every_ordering_of_duplicates_and_reorders_gives_one_view`, `test_userdata_router.py::test_fill_total_mismatch_journals_surfaces_and_calls_the_fallback_once`, `test_userdata_recorded_frames.py::test_every_recorded_frame_parses_to_the_expected_outcome`, fixture and contract tests | Library-proven offline (fakes, SDK-shaped fakes, synthetic frames, replay and reorder proof). **Demo-observed** by the user-run smoke 2026-10-16T14:04:46Z (`REAL_SMOKE`, `sdk_route_delivery` PASS, 58 `RECORDED_DEMO` frames parse with no anomaly). Transport decision `sdk` (18-19). Not mainnet; not composed into a running process (Phases 24 and 25) |
| EXEC-01 (execution manager, protective algo orders, partial-fill sizing) | 18-06, 18-10, 18-12, 18-13, 18-17, 18-20, 18-21, 18-23 | `test_algo_status.py`, `test_execution_attach.py`, `test_binance_usdm_error_routing.py::test_placement_calls_the_sdk_exactly_once`, `test_binance_usdm_signed_calls.py`, `test_binance_probe.py`, `test_demo_probe_cases.py` | Library-proven offline (only `NEW` confirms protection; placement is single-attempt; a protective order blocked by a 429 pause or 418 ban surfaces as an unprotected position). Demo-observed protective-stop facts: a pre-placed reduce-only STOP_MARKET with explicit quantity is accepted while flat; `closePosition` while flat is rejected -4509; a protective leg placed while the entry rests stays `NEW` after the entry is cancelled (orphan) and cancels cleanly; on a full fill its quantity equals the position. **Not observed**: partial fill, triggered `*_MARKET` exit lifecycle, MARKET_LOT_SIZE out-of-range (optional case off). REQUIREMENTS keeps "Demo-proven evidence stays with Phases 24 to 26"; D055 execution model OPEN |
| EXEC-02 (reconciliation, orphan sweep, SAFE_MODE on divergence) | 18-05, 18-08, 18-10, 18-21 | `test_exchange_errors.py`, `test_sdk_error_mapping_contract.py`, `test_adapter_not_found_mapping.py`, `test_persistence_exit_evidence_pg.py::test_unknown_exit_without_evidence_raises_and_writes_nothing`, `test_stream_records.py`, `test_fake_binance_semantics.py` | Library-proven offline, including the PostgreSQL evidence gate for UNKNOWN exits. Demo-observed error codes as in section 1. No live reconcile loop has run (Phase 20 composes it); Demo-proven evidence stays with Phases 24 to 26 |
| OPS-02 (credentials, redaction, explicit environment, ratified limits) | 18-04, 18-07, 18-09, 18-13 | `test_binance_client_config.py`, `test_binance_secret_redaction.py`, `test_binance_limits.py`, `test_binance_limits_ratified_file.py`, `test_clock_drift.py`, `test_no_unratified_defaults.py` | Library-proven offline: key loading from environment or file outside the repository, redaction of key, secret, signature and listenKey (also grepped in the committed Demo evidence and fixtures: zero hits), explicit environment with the endpoint guard, 27 ratified limits with no default in code. **Attestation of no-withdrawal keys and the IP allowlist is not code and stays a Phase 24 to 26 human item** |

## 3. CONTEXT decisions D-01 to D-22

| Decision | Plan (task) | Test or evidence |
|---|---|---|
| D-01 event types in `binance_userdata.py` and SDK-free frozen dataclasses (amended by `18-DEC-D01-event-types.md`) | 18-03, 18-11 | `test_userdata_events.py`, `test_userdata_adapter.py`; gate invariant 3 (pure modules) |
| D-02 official SDK, contract pins | 18-11, 18-19 | `test_userdata_contract.py`, `test_binance_client_config.py::test_sdk_client_is_constructed_only_at_the_allowed_sites` (gate invariant 1); `evidence/18-transport-decision.txt` (`transport: sdk`; direct transport not built) |
| D-03 supervisor (connect, keepalive, rotation, reconnect, gap-then-snapshot) | 18-14 | `test_userdata_supervisor.py`, `test_userdata_rig.py` |
| D-04 no composition into a process; library, rig, smoke script | 18-11, 18-14, 18-16 | gate invariant 2 (no `src` module imports the supervisor); `test_user_data_smoke_*` |
| D-05 stream is hint plus evidence, anomalies are journaled | 18-03, 18-08, 18-14, 18-15 | `test_userdata_router.py`, `test_stream_records.py`, `test_userdata_parsers.py` |
| D-06 `ORDER_TRADE_UPDATE` to `FillEvent`, commission carried | 18-03, 18-15, 18-24 | `test_userdata_events.py::test_to_fill_event_maps_the_trade_and_carries_commission`, `test_userdata_replay.py` |
| D-07 `ALGO_UPDATE` and status table (amended: only `NEW` ACTIVE) | 18-03, 18-06, 18-15 | `test_algo_status.py`, `test_userdata_parsers.py`, `test_userdata_router.py` |
| D-08 `ACCOUNT_UPDATE` events only; evidence source on UNKNOWN exits; exchange state store methods | 18-03, 18-08, 18-15 | `test_persistence_exit_evidence_pg.py`, `test_stream_records.py` |
| D-09 taxonomy keyed on int code with source and read date | 18-05 | `test_exchange_errors.py` (`test_table_has_exactly_the_required_codes`) |
| D-10 classification by code only, message regexes removed | 18-05, 18-10 | `test_adapter_not_found_mapping.py`, `test_binance_usdm_source_guard.py` (gate invariant 6) |
| D-11 placement never retried; 418 and 429 no retry, shared gate (amended 2026-10-16) | 18-05, 18-10, 18-13, 18-14 | `test_binance_ratelimit_gate.py`, `test_binance_usdm_error_routing.py`, `test_binance_usdm_signed_calls.py` (gate invariants 6 and 9) |
| D-12 explicit environment value, Demo hosts, LIVE not enabled here | 18-04, 18-09 | `test_binance_client_config.py`, `test_demo_rehearsal_safety.py` |
| D-13 key loading, redaction, attestation stays human | 18-04, 18-09 | `test_binance_secret_redaction.py`, `test_redaction.py` |
| D-14 recvWindow, drift guard fail closed, ratified safety numbers | 18-02, 18-07, 18-09, 18-13 | `test_binance_limits.py`, `test_binance_limits_ratified_file.py`, `test_clock_drift.py`, `test_no_unratified_defaults.py` (gate invariants 4, 5, 7) |
| D-15 probe script safety envelope | 18-12, 18-16, 18-17 | `test_demo_probe_cli.py`, `test_demo_probe_evidence.py`, `test_operator_evidence.py` |
| D-16 probe case order | 18-17, 18-23, 18-20 | `test_demo_probe_cases.py::test_case_order_is_the_d16_order_of_risk`; `evidence/18-probe-check.txt` |
| D-17 probe records facts, D055 stays OPEN, fake corrected from evidence | 18-17, 18-20, 18-21 | `test_fake_binance_semantics.py`; gate invariant 8 (D055 row still says "stays OPEN") |
| D-18 offline plans plus blocking-human plans | 18-02, 18-03, 18-18, 18-19, 18-20, 18-22 | decision records under `decisions/`, evidence under `evidence/` |
| D-19 documentation re-read first | 18-01, 18-18 | `test_sources_phase18_section.py`; every executor re-read UNVERIFIED (no fetch tool, WAF challenge); orchestrator WebFetch summaries recorded in SOURCES by 18-18, not verified live |
| D-20 document updates | 18-01 (first part), 18-09, 18-25 | `test_sources_phase18_section.py`, `test_decision_alignment_exchange.py`; the Demo-observed document rows were **18-25 pending**; 18-25 is done (afcfe5e, aedb3b5, fc1c255) |
| D-21 test strategy (pure, parser, supervisor, replay, redaction) | 18-03 to 18-15, 18-24 | the listed test files; `test_userdata_replay.py` for reorder and duplicate |
| D-22 determinism, no float, no wall clock in pure code, UTC | all | gate invariant 3 (`float_constructor_calls`, `wall_clock_calls`) for seven pure modules |

## 4. Folded inherited items

| Item | Plans | Test or evidence | Status |
|---|---|---|---|
| G3-001 re-confirm ALGO_UPDATE status list, 24 h WS lifetime, Change-Position-Mode wording on the official pages | 18-01, 18-18 | `test_sources_phase18_section.py`; SOURCES Phase 18 section | Executor re-read UNVERIFIED (no fetch tool). Orchestrator WebFetch summaries recorded 2026-10-16 (60-minute key, 24-hour connection, -1125 confirmed; payload field tables never rendered). The status meanings were Demo-observed only for `NEW` and `CANCELED` |
| G2-028 `algoStatus` classification table | 18-06, 18-15 | `test_algo_status.py`, `test_userdata_router.py` | Done (offline). REST and frames showed only `NEW` and `CANCELED` on Demo; `CANCELED` is UNKNOWN by the user's record |
| G2-029 below-minimum-notional reduce-only leg; MARKET_LOT_SIZE for a triggered `*_MARKET` exit | 18-17, 18-23, 18-20 | `evidence/18-probe-check.txt` | Below-minimum case Demo-observed: a reduce-only STOP_MARKET of quantity 0.0001 (notional 7.890670 against min_notional 50) was ACCEPTED. MARKET_LOT_SIZE out-of-range **not observed** (optional case off); lot filters read (min 0.0001, max 120, step 0.0001). BINANCE.md corrections: done by 18-25 (aedb3b5). Phase 19 criterion 4 correction: was **18-25 pending**; 18-25 is done and proposed it in `18-25-SUMMARY.md`, and ROADMAP.md was corrected separately (7e73606) |
| G3-009 commission and commissionAsset parsed | 18-03, 18-24 | `test_userdata_events.py::test_to_fill_event_maps_the_trade_and_carries_commission` | Done offline; Demo frames carry the fields and parse |
| G4-034 evidence source on UNKNOWN exits | 18-08 | `test_persistence_exit_evidence_pg.py` (PostgreSQL, strict run) | Done offline |
| G4-043 Order `exchange_status` and `exchange_order_id` store methods | 18-08 | `test_persistence_exit_evidence_pg.py`, `test_stream_records.py` | Done offline |
| D055 probe cases | 18-17, 18-23, 18-20, 18-21 | `evidence/18-probe-check.txt` | 14 of 16 observed; 2 not observed (above). D055 execution model OPEN |

## 5. Owner-only items

| Item | Decision record | Outcome |
|---|---|---|
| O-18-01 safety thresholds | `decisions/18-DEC-O-18-01.md` (27 `limit` lines, four algo classes UNKNOWN, amendment "429 semantics"), `decisions/18-O-18-01-table.md` | Recorded by the user 2026-10-16; written verbatim to `config/binance/binance-limits-v1.toml` by 18-09; pinned by the DECISIONS row (gate invariant 7) |
| O-18-02 D055 execution model | none (stays open) | **OPEN**. The probe supplied evidence only. The draft for the user (`decisions/18-DRAFT-D055-evidence-for-user.md`) was 18-25 pending; 18-25 is done (fc1c255) |
| O-18-03 probe authorization | `decisions/18-DEC-O-18-03-smoke.md` (smoke, option values), `decisions/18-DEC-O-18-03.md` (probe, option authorize, plus addendum for the second run) | Both user-run live on Demo 2026-10-16; no agent ran `--execute` |
| O-18-04 environment choice | `decisions/18-DEC-O-18-01.md` (`probe environment: DEMO`, TESTNET NOT_CONFIGURED) | DEMO; LIVE never used |

## 6. Research findings, pitfalls and the UNVERIFIED register

| Item | Plan and test | Final status |
|---|---|---|
| F1 stream mechanism and SDK surface | 18-11 (`test_userdata_contract.py`, `test_userdata_adapter.py`), 18-19 | SDK route delivers on Demo; the URL form conflict stays open |
| F2 event schemas and the mapping | 18-03, 18-24, 18-21 | 58 recorded Demo frames parse with no anomaly; ignored wire keys are named in the test |
| F3 ALGO_UPDATE status table | 18-06 | Only `NEW` and `CANCELED` seen on Demo |
| F4 error taxonomy inputs | 18-05, 18-10, 18-21 | Section 1 criterion 2 |
| F5 environments and configuration | 18-04, 18-09, 18-13 | offline |
| F6 probe design | 18-12, 18-17, 18-23, 18-20 | 14 of 16 cases observed |
| F7 integration map | 18-06 (manager, sweeper), 18-10 (adapters) | offline |
| P1 mixed REST and WebSocket environment | 18-04 `test_binance_client_config.py` | covered offline |
| P2 bare listenKey SUBSCRIBE | 18-11, 18-18 | Demo-observed: SDK route delivered (A6 held on Demo) |
| P3 listenKey in logs | 18-04, 18-11 `test_binance_secret_redaction.py`, `test_userdata_adapter.py` | covered offline; grep of Demo artifacts zero hits |
| P4 and P17 strict models, Decimal strictness | 18-03 `test_userdata_parsers.py`, `test_userdata_events.py` | covered offline |
| P5 swallowed callback exceptions | 18-11 `test_userdata_adapter.py::test_parser_exception_becomes_a_malformed_payload_anomaly` | covered offline |
| P6 and P8 stale names, resubscribe after a drop | 18-14 `test_userdata_supervisor.py` | covered offline; the forced drop was Demo-observed |
| P7 listenKey is an account singleton | 18-16, 18-20 (the probe refuses to send unless the symbol is flat, exit 3; the user confirmed a dedicated Demo account) | process rule, not a test of the singleton itself; not observed |
| P9 SDK timeouts and retries | 18-04, 18-07 `test_binance_client_config.py`, `test_binance_limits.py` | covered offline |
| P10 `status_code` is not the HTTP status | 18-05 `test_sdk_error_mapping_contract.py` | covered offline against the installed SDK |
| P11 recvWindow and the clock | 18-07, 18-13 `test_clock_drift.py`, `test_binance_usdm_signed_calls.py` | covered offline; offset -298 ms observed |
| P12 silence is not staleness | 18-14 `test_userdata_supervisor.py` | covered offline |
| P13 two fill key spaces | 18-15 (the router reports a `FillSource` per fill) | by design; no dedicated test is claimed here |
| P14 child identity of a triggered algo order | 18-17, 18-20 | **not observed** (no `ai` or `aq` in any frame, no child ORDER_TRADE_UPDATE) |
| P15 ACCOUNT_UPDATE ordering | 18-15 (both are hints; REST decides) | not observed; no dedicated test is claimed here |
| P16 hedge mode and `ps` | 18-03 `test_userdata_parsers.py` | offline only; hedge mode not observed on Demo |
| P22 event kinds the project did not place | 18-03 `test_userdata_parsers.py` | offline only |
| P23 `rm` is free text | 18-03, 18-15 | journaled verbatim, nothing derived |
| P24 cancel retry predicate | 18-05, 18-10 `test_exchange_errors.py`, `test_binance_usdm_error_routing.py` | covered offline |
| P25 document gates pin wording | 18-01, 18-25 | `verify_decision_alignment.py all` ALL_PASS (Gate run below) |
| UNVERIFIED 1 payload pages | 18-18 | still not rendered; real frames now exist (58) |
| UNVERIFIED 2 SUBSCRIBE parameter format and envelope | 18-18 | SDK route worked; format not captured |
| UNVERIFIED 3 Demo serves listenKey and socket | 18-18 | **resolved on Demo** (observed) |
| UNVERIFIED 4 REST `algoStatus` list | 18-20 | only `NEW` seen; list not verified |
| UNVERIFIED 5 -1125, duplicate `clientAlgoId`, id reuse, D055 cases | 18-18, 18-20 | -1125 observed; -4116 observed; id reuse observed; D055 cases per section 4 |
| UNVERIFIED 6 child identity | 18-20 | **not observed** |
| UNVERIFIED 7 new-connection limit, ACCOUNT order, `Retry-After`, max recvWindow | none | not observed |
| UNVERIFIED 8 bare number in money fields | 18-03 | rejected by the parser; never seen on the wire |
| UNVERIFIED 9 Demo key provisioning steps | none | not observed |

### Codes seen by the smoke and probe: decided by the owner on 2026-10-17 (plan 18-26)

The owner's decision is in `decisions/18-DEC-TAXONOMY-CODES.md` (option adopt-with-addition: -4024 added with -4016). The error-code page was read again on 2026-10-17 (`evidence/18-error-code-page-reread-20261017.txt`, page last modified 2026-10-16 as the page shows). The tests are in `tests/test_exchange_error_rejections.py` and `tests/test_exchange_errors.py`; for example `test_exchange_error_rejections.py::test_each_owner_code_classifies_rejected_definitive_on_placement_only`, `test_exchange_error_rejections.py::test_tracer_1106_on_the_protective_stop_after_a_fill_goes_close_required` (renamed by Phase 19 plan 19-15, the stop is now decided by the protection coordinator) and `test_exchange_errors.py::test_1125_keeps_its_mapping_and_records_the_smoke_observation`.

| Code | Seen in | Class at the time of the evidence | Class now |
|---|---|---|---|
| -1106 `Parameter 'reduceonly' sent when not required.` | probe case `rejected_protective_variants` (Demo, 2026-10-16) | UNKNOWN_EXCHANGE_ERROR | REJECTED_DEFINITIVE on PLACEMENT, UNKNOWN elsewhere; documented (page re-read 2026-10-17), `demo_observed_on` 2026-10-16; never POSITION_MODE |
| -4016 `Limit price can't be higher than 86305.10.` | probe first run, `id_reuse_after_filled` (Demo, 2026-10-16) | UNKNOWN_EXCHANGE_ERROR | REJECTED_DEFINITIVE on PLACEMENT, UNKNOWN elsewhere; documented (page wording PRICE_HIGHTER_THAN_MULTIPLIER_UP kept apart from the Demo wording), `demo_observed_on` 2026-10-16 |
| -4024 `Price is lower than mark price multiplier floor.` (page text) | not seen on Demo; added by the owner with -4016 | not in the table (UNKNOWN_EXCHANGE_ERROR) | REJECTED_DEFINITIVE on PLACEMENT, UNKNOWN elsewhere; documented on the page re-read 2026-10-17, no `demo_observed_on` |
| -1125 INVALID_LISTEN_KEY | smoke item f (`PUT after DELETE`, Demo, 2026-10-16) | in the table, note said "assumed", not marked `demo_observed_on` | unchanged mapping (INVALID_LISTEN_KEY on LISTEN_KEY); the note says observed on Demo (smoke); `demo_observed_on` 2026-10-16; evidence stays documented |

Not added: -4131, -4183 and -4184 (listed by the same page). Open items for Phase 19 and 20 (recorded in the decision file, not implemented): the consumer refreshes mark price and filter data after -4016 or -4024 and fails closed if it cannot; a consumer does not derive SAFE_MODE for a rejected protective order from `safe_mode_eligible`; the manager's bounded query-first entry re-send does not consult the taxonomy.

## 7. Deferred ideas confirmed not built

- Composing the supervisor into a running process and soak: no `src` module imports the supervisor (gate invariant 2).
- `ACCOUNT_UPDATE` as equity, margin or position truth: events only (D-08).
- Symbol, side and quantity binding and the live-price check: not present.
- `binance-sdk-algo` TWAP and VP: not in `pyproject.toml`; `uv lock --check` exit 0.
- Closing D055 or reordering `execute_approved_plan`: no change (gate invariant 8).
- A direct documented-URL transport: not built (18-19 tasks 2 to 4 skipped by design, `transport: sdk`).

## Gate run

Commands were run in the worktree `Trading-Alert-p18` at HEAD with `TEST_DATABASE_URL` set (connection check passed) after the gate test commit.

- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" -q -rs`: exit 0 (10090 passed, 6 skipped, none deselected-by-error; the 6 skips are Windows platform skips: symlinks unavailable, NTFS file modes, deploy heartbeat file modes; no PostgreSQL test was skipped). This run started at commit b7c6a62 (the gate test with its 23 first tests); the two traceability tests added afterwards were run separately: `uv run pytest tests/test_phase18_gate.py`: exit 0 (25 passed)
- `uv run ruff check`: exit 0
- `uv run ruff format --check`: exit 0 (621 files already formatted)
- `uv run mypy src`: exit 0 (no issues in 202 source files)
- `uv lock --check`: exit 0
- `uv run python scripts/verify_decision_alignment.py all`: exit 0 (ends `ALL_PASS all`)

## Merge check against develop

READ-ONLY. No rebase, merge, reset, checkout of another branch, push or force option was run; the reflog was not touched by this task.

- `git rev-parse develop`: f51a5e18aa170cf40ab58b085f3643643802736b
- merge base of HEAD and develop: f332cc782ce72626ed137fa5d2acf9eda8524636
- `git merge-tree --write-tree HEAD develop`: exit 0, printed the tree id e3ca91146fb12fa1fff9b6adb886f0d50091bcf3 and no conflicted file names. So git predicts a clean merge today. Phase 16 can still move `develop` before the integration, and the clean result says nothing about the gates on the integrated tree (Task 4).

## Gate run after integration with develop

Method: `git merge --no-ff phase-18-smoke` on `develop`, run by the session on the user's instruction (`decisions/18-DEC-INTEGRATION.md`, `option: integrated`); nothing pushed. `develop` merge commit: dde100b. The gate ran on `develop` at HEAD aeff99585c9289ed503caae0f80421814353bfda (dde100b is an ancestor). This tree also holds the plan 18-26 commits (d881ab2..aeff995), which came after the merge. Run on 2026-10-18 with PostgreSQL reachable (container `trading-postgres-1`, `TEST_DATABASE_URL` exported, connection check `select 1` passed).

- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" -q -rs`: exit 0 (10303 passed, 6 skipped, 0 failed; the 6 skips are Windows platform skips: symlinks unavailable, NTFS file modes, deploy heartbeat file modes; no PostgreSQL test was skipped. The summary line is suppressed by the double `-q` in `addopts`, so the counts come from the progress lines)
- `uv run ruff check`: exit 0
- `uv run ruff format --check`: exit 0 (629 files already formatted)
- `uv run mypy src`: exit 0 (no issues in 202 source files)
- `uv lock --check`: exit 0
- `uv run python scripts/verify_decision_alignment.py all`: exit 0 (ends `ALL_PASS all`)
- `uv run pytest tests/test_phase18_gate.py -q` (the Phase 18 gate file, also covered by the full run): exit 0 (25 passed)
