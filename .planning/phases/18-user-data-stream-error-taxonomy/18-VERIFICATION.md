---
phase: 18-user-data-stream-error-taxonomy
verified: 2026-10-18T00:00:00Z
status: human_needed
score: 3/3 criteria verified at library level (criterion 2: core verified, D055 sub-bullet partial 14 of 16 cases observed)
verified_at_head: fea8e2e
covered_files:
  - src/adapters/binance_userdata.py
  - src/adapters/binance_userdata_events.py
  - src/adapters/binance_userdata_router.py
  - src/adapters/binance_userdata_supervisor.py
  - src/domain/exchange_errors.py
  - src/adapters/binance_client.py
  - src/adapters/binance_clock.py
  - src/adapters/binance_ratelimit_gate.py
  - src/adapters/binance_usdm.py
  - config/binance/binance-limits-v1.toml
covered_digest: "not computed: `verification.fingerprint` is not available in the installed gsd-tools"
behavior_unverified: 0
overrides_applied: 0
gaps: []
human_verification:
  - test: "Sign off 18-VALIDATION.md (nyquist_compliant, wave_0_complete, Approval)"
    expected: "The user sets the frontmatter flags and the approval line; they are still draft/false/pending"
    why_human: "The file says the user sets them, not the planner or verifier"
  - test: "Attest no-withdrawal API keys and the IP allowlist for the Demo/live keys"
    expected: "Recorded attestation (OPS-02 human part)"
    why_human: "Not code; stays a Phase 24 to 26 item per 18-TRACEABILITY.md"
  - test: "Decide D055 (execution model) after reading decisions/18-DRAFT-D055-evidence-for-user.md"
    expected: "A new DECISIONS row, or a deliberate deferral"
    why_human: "Open by design; the probe supplied evidence only"
---

# Phase 18: Binance User-Data Stream + Exchange Error Taxonomy - Verification Report

**Phase goal:** The system learns fills, order and algo state, and account changes from Binance in real time. It interprets exchange errors by code, not by message text, and it can target Binance Demo Trading.
**Verified:** 2026-10-18 at HEAD fea8e2e (branch develop), initial verification (no previous VERIFICATION.md).
**Status:** human_needed (no BLOCKER; no FAILED truth; three human items below, none blocks Phase 19).

Method: code read directly (not from SUMMARYs), the cheap tests re-run in this session, the Demo evidence JSON files opened and their verdict fields read. The full strict gate (10317 passed, 6 platform skips at fea8e2e) was NOT rerun, by instruction.

## Tests run in this session

`uv run pytest <18 files> -o addopts="" -p no:cacheprovider`: `test_phase18_gate`, `test_exchange_errors`, `test_exchange_error_rejections`, `test_userdata_{adapter,contract,events,parsers,recorded_frames,replay,router,supervisor,rig,fixtures}`, `test_clock_drift`, `test_binance_ratelimit_gate`, `test_binance_limits_ratified_file`, `test_binance_client_config`, `test_algo_status`: **1226 passed, 0 failed, 0 skipped, 0 errors** (36.7 s).
Second batch: `test_env_example`, `test_paper_runtime_env`, `test_demo_rehearsal_safety`, `test_binance_probe`, `test_demo_probe_cases`, `test_fake_binance_semantics`, `test_binance_usdm_signed_calls`, `test_binance_usdm_error_routing`, `test_adapter_not_found_mapping`, `test_binance_secret_redaction`: **717 passed**.
Not run here: the PostgreSQL tests (`test_persistence_exit_evidence_pg.py`); they are covered by the strict gate recorded in 18-TRACEABILITY.md, not by this session.

## Per-criterion verdicts

### Criterion 1: user-data stream (listenKey, ORDER_TRADE_UPDATE, ALGO_UPDATE incl. `o.rm`, ACCOUNT_UPDATE, `/private`), feeds `fold_fills` and reconciliation, REST fallback - **VERIFIED** (library level + Demo-observed delivery; two stated limits)

| Piece | Evidence in code |
|---|---|
| listenKey lifecycle | `SdkListenKeyPort` start/keepalive/close, one SDK call each, never retried, gate checked first, key registered with the redactor: `src/adapters/binance_userdata.py:215-274`. Errors are classified with `CallKind.LISTEN_KEY` (`:249`), -1125 maps to `ListenKeyInvalid` which triggers rekey (`:164`, `:712-724`). |
| `/private` connection | `PRIVATE_URL_PATH = "private"` (`:71`); `SdkUserDataTransport.connect` creates connections, refuses if no private connection exists, then subscribes the bare key via `ws.user_data(listen_key)` (`:544-558`); `rebuild`/`resubscribe` handle SDK stale-name behaviour (`:560-615`). |
| Bounded, non-raising ingestion | `UserDataAdapter._on_raw_message` parses and enqueues, never raises; overflow sets a flag and counts (`:777-797`). |
| ORDER_TRADE_UPDATE / ALGO_UPDATE / ACCOUNT_UPDATE typing | Event constants `src/adapters/binance_userdata_events.py:97-99`; `OrderUpdateEvent` with `commission`/`commission_asset` (`:397-398`); `AlgoUpdateEvent.reject_reason` from `o.rm`, verbatim, bounded (`:518`, `:1068-1070`); `AccountUpdateEvent` deltas only (`:619`); dispatcher `parse_stream_message` (`:1328`). |
| Feeds `fold_fills` | `to_fill_event` maps TRADE to `FillEvent` keyed (order id, trade id) with commission (`:1419-1448`); router hands a `RoutedFill` to `fill_sink` (`src/adapters/binance_userdata_router.py:578-584`); `tests/test_userdata_replay.py:118,211,221` and `tests/test_userdata_rig.py:164` run the real `fold_fills` on the router's output, including every duplicate/reorder ordering. |
| Feeds reconciliation | Status hints carry `ExitEvidence(source=USER_DATA_EVENT)` (`router.py:559-574`); ALGO_UPDATE routed with the ratified `AlgoStatusClass`, `rm` journaled scrubbed, TERMINAL_FAILED raises a divergence (`router.py:645-735`); store methods `update_order_exchange_state` / evidence gate in `src/persistence/entities.py:465,518`. |
| REST fallback | Fill-total mismatch journals an anomaly and calls `fills_fallback` once (`router.py:590-641`); supervisor gap-then-REST-snapshot before delivering held events `after_gap` (`src/adapters/binance_userdata_supervisor.py:1-30`, `:729-780`). |
| Demo observation | Smoke 2026-10-16T14:04:46Z, `proof_class REAL_SMOKE`, `outcome COMPLETE`, `end_state FLAT` (read from `evidence/user-data-smoke-EVIDENCE-20261016T140446Z.json`); SDK route delivered typed ORDER_TRADE_UPDATE NEW and CANCELED, keepalive worked, forced drop went UNKNOWN, SYNCING, LIVE (`evidence/18-smoke-check.txt` items a-e); 58 recorded Demo frames parse (`test_userdata_recorded_frames`, passed here). |

Stated limits (not hidden by this verdict):
- The exact `/private` URL form (path form `/private/ws/<key>` against the `?listenKey=&events=` form) is **not settled**: the SDK built it, the form was not captured (18-TRACEABILITY.md criterion 1, UNVERIFIED 2). The code never builds the URL itself.
- The stream is a library; no `src` module imports the supervisor (gate invariant 2, `tests/test_phase18_gate.py:422`), by D-04. "Feeds `fold_fills` and reconciliation" is proven through rig and replay tests, not in a running process (Phases 24 and 25).
- ALGO_UPDATE statuses: only `NEW` and `CANCELED` were seen on Demo; the other classes (`src/domain/algo_status.py`) rest on documentation plus the owner's recorded UNKNOWN classes. `ia` double-delivery and the child order identity (`ai`/`aq`) were **not observed**.

### Criterion 2: Demo probe records not-found codes, duplicate `clientAlgoId`, id reuse; fake corrected; mappings keyed on `status_code` - **VERIFIED** for the core; **PARTIAL** for the D055 probe-case sub-bullet

Core (VERIFIED, Demo-observed 2026-10-16, not mainnet). Evidence: `evidence/18-probe-check.txt` and `evidence/demo-probe-EVIDENCE-20261016T173612Z.json` (read: `proof_class REAL_DEMO`, `outcome COMPLETE`, `environment DEMO`, 14 cases OBSERVED, 2 NOT_OBSERVED, `ban None`).
- GET order and GET algoOrder not found: -2013; cancel order and cancel algo: -2011; duplicate `clientAlgoId` while open: -4116; id reused after CANCELED (normal and algo) and after FILLED (normal, second run): accepted.
- Code table keyed on int code, `src/domain/exchange_errors.py:205-564`: -1021 CLOCK_SKEW (`:249`), -2011 (`:300`) and -2013 (`:309`) ORDER_ABSENT on QUERY and CANCEL only, -4116 (`:320`), -2019 (`:414`), -4164 (`:428`), -2021 (`:477`), -1125 on LISTEN_KEY only (`:286`). `classify` uses (SDK class, int code, call kind) only (`:584-604`); the normalizer reads only class, `status_code`, `retry_after` (`src/adapters/binance_errors.py:55-76`); `tests/test_exchange_errors.py:111,131` pin that message text is never read.
- Plan 18-26 codes (owner decision 2026-10-17): -1106 (`:363`), -4016 (`:382`), -4024 (`:400`) are REJECTED_DEFINITIVE on PLACEMENT only (UNKNOWN on other kinds, via `_REJECT_ON_PLACEMENT` `:202`), none retry-eligible, never POSITION_MODE; -1125 keeps its mapping with `demo_observed_on` 2026-10-16 and `read_date` 2026-10-17 (`:286-298`); -4024 has no Demo date (not observed). Page wording and Demo wording are kept apart in the notes. Tests passed here: `test_exchange_error_rejections.py` (tracer: -1106 on the protective stop becomes entry-without-protective; SAFE_MODE branch fires although `safe_mode_eligible` is False) and `test_exchange_errors.py:752,776,795`.
- Fake corrected from evidence: `tests/support/fake_binance_exchange.py` docstring (SDK-shaped -4116, three assumptions labelled agrees/not observed); `tests/test_fake_binance_semantics.py` passed.
- Table codes seen **only in documentation, not on Demo**: -2019, -4164, -1021, -4024. Offline-proven only.

D055 probe-case sub-bullet (PARTIAL, as the phase documents state): 14 of 16 required cases observed. **Not observed:** `partial_fill` (every marketable entry filled completely) and `triggered_market_exit_lifecycle` (trigger not reached within `case_timeout_seconds`); child identity of a triggered algo order and MARKET_LOT_SIZE out-of-range also not observed. Demo-observed protective facts that did land: pre-placed reduce-only STOP_MARKET with explicit quantity accepted while flat; `closePosition` while flat rejected -4509; a protective leg placed while the entry rests stays `NEW` after the entry is cancelled and cancels cleanly; on a full fill its quantity equals the position; reduce-only below min notional accepted. D055 stays OPEN (`tests/test_phase18_gate.py:472`, passed).

### Criterion 3: client configuration - **VERIFIED** (offline-proven; Demo-observed only for the environment, the clock offset and absence of any 418/429)

| Item | Evidence |
|---|---|
| Explicit REST timeout, retries, backoff, no defaults | `ClientLimits` `src/adapters/binance_client.py:204-223`, passed to `ConfigurationRestAPI(timeout, retries, backoff)` (`:457-464`); ratified `rest_timeout_ms=5000`, `sdk_retries=0`, `sdk_backoff_ms=0` (`config/binance/binance-limits-v1.toml:10-13`). |
| API key loading | `load_api_credentials` (`:348-382`): env or `_FILE` outside the repo, ambiguity refused, other environment's names refused, key and secret registered with the redactor; `ApiCredentials` masks repr. |
| Demo / live selection, TESTNET NOT_CONFIGURED | `parse_environment` has no default (`:118-127`); `ENVIRONMENT_ROWS` (`:151-175`): DEMO REST = SDK constant, confirmed `https://demo-fapi.binance.com`; DEMO streams `wss://demo-fstream.binance.com`; DEMO ws_api None; TESTNET all None; LIVE requires an enabled enablement state (`:406-408`); `assert_environment` re-reads every surface (`:549-586`). Credential names `BINANCE_DEMO_API_KEY/SECRET`, `BINANCE_LIVE_API_KEY/SECRET`, none for TESTNET (`:265-276`); grep of `src scripts config tests .env.example` finds no `BINANCE_TESTNET_*` credential name except the stale-name refusal test (`tests/test_paper_runtime_env.py:51`) and its pin (`tests/test_env_example.py:96-98`); `test_env_example` and `test_paper_runtime_env` passed here. |
| recvWindow on every signed call | `BinanceUsdmAdapter._sdk_call` passes `recv_window=policy.recv_window_ms` explicitly, refuses without a policy (`SignedCallPolicyMissing`) before any SDK call (`src/adapters/binance_usdm.py:626-677`); `recv_window_ms=5000` (`toml:16`). |
| Drift check fails closed | `evaluate_clock_drift` / `measure_clock_drift` / `ClockDriftGuard` (`src/adapters/binance_clock.py:100-300`): never measured, failed measurement, out-of-limit, stale, or pending -1021 all block new entries; -1021 only requests a re-measure, never retries (`:290-299`); enforced on `place_entry` via `_require_entries_allowed` (`binance_usdm.py:634-647`). Smoke read offset -298 ms (uncertainty 139) within limits. |
| No retry on 418, `retry_after` honored | `rate_limit_decision` always `retry=False`, wait = valid Retry-After capped (`exchange_errors.py:653-688`); one process-wide `RestRateLimitGate` refuses every REST call during a 418 ban or 429 pause (`binance_ratelimit_gate.py:109-210`), used by the listenKey port (`binance_userdata.py:244-253`) and the signed-call path (`binance_usdm.py:660-667`); placement is single-attempt (`test_binance_usdm_error_routing.py::test_placement_calls_the_sdk_exactly_once`, passed). No 418/429 was ever observed live. |
| 27 ratified limits | 3 client + 4 signed_calls + 5 drift + 15 stream = 27 keys in `config/binance/binance-limits-v1.toml` with provenance `DECISION`; the record `decisions/18-DEC-O-18-01.md` has 27 `limit` lines (counted); `test_binance_limits_ratified_file.py` and `test_no_unratified_defaults` pin file to record and forbid defaults (passed). |

## Evidence integrity

- Smoke evidence: `REAL_SMOKE`, `COMPLETE`, `DEMO`, `FLAT`. Probe second run: `REAL_DEMO`, `COMPLETE`, `DEMO`, 14 OBSERVED / 2 NOT_OBSERVED, matching `18-probe-check.txt` claims. Seven evidence files are git-tracked; 67 fixture files tracked under `tests/fixtures/phase18`.
- Secret scan of `evidence/` and `tests/fixtures/phase18`: only a `SYNTHETIC-DUMMY-LISTEN-KEY` literal and SHA-256 payload hashes; no key, secret, signature or live listenKey found.
- All evidence is **Demo-observed, not mainnet**. Nothing was used to choose a trading parameter.

## Requirements coverage

| Requirement | Status | Evidence level |
|---|---|---|
| EXEC-05 (user-data stream drives fills and state, REST fallback) | Satisfied at library level; Demo-observed delivery | Not composed into a running process (Phases 24, 25). REQUIREMENTS.md still shows it Pending (stale; phase-closing step). |
| EXEC-01 (Phase 18 part: algo status classification, probe facts) | Pending by design | Partial fill and triggered-stop lifecycle not observed; D055 OPEN. |
| EXEC-02 (Phase 18 part: error taxonomy, not-found routing, evidence gate) | Pending by design | Offline plus Demo codes; no live reconcile loop has run (Phase 20). |
| OPS-02 (credentials, redaction, explicit environment, ratified limits) | Pending by design | Code part proven offline; key/IP attestation is a human Phase 24-26 item. |

## Anti-patterns

Grepped the Phase 18 production modules and both scripts for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER`: the only hits are the provenance-label validator in `src/adapters/binance_limits.py:20,343-344` (it refuses a PLACEHOLDER label), not debt markers. No stub returns found in the files read. No debt-marker blocker.

## Findings

No BLOCKER. Warnings and notes (none changes a criterion verdict):

1. **WARNING (for Phases 24/25): the drift guard is opt-in at the adapter.** `BinanceUsdmAdapter(drift_guard=None)` is valid and then `place_entry` is not blocked on drift (`binance_usdm.py:634-640`). No production site constructs a `ClockDriftGuard` or passes `drift_guard=` yet (grep of `src scripts`: no hit). The guard itself fails closed and is tested; the composition must pass it, and a composition test should assert it.
2. **WARNING: `/private` URL form unsettled** (see criterion 1). Low risk while the SDK builds it; relevant only if a direct transport is ever needed (18-19 skipped by design, `transport: sdk`).
3. **NOTE: gate not applied to every REST holder.** The gate module records that the data jobs, the Phase 16 paper runtime and two scripts do not hold it (`binance_ratelimit_gate.py:28-31`); left to the composing phases.
4. **NOTE: Phase 19/20 follow-ups recorded, not implemented:** refresh mark price and filters after -4016/-4024; do not derive SAFE_MODE from `safe_mode_eligible` for a rejected protective order; the manager's bounded query-first re-send does not consult the taxonomy (18-TRACEABILITY.md section 6).
5. **NOTE: stale text to refresh in the phase-closing step (not edited here):** ROADMAP Phase 18 plan checkboxes for 18-18 to 18-22, 18-25, 18-26 and the "2 executed" line (`ROADMAP.md:906,926-934`); REQUIREMENTS EXEC-05 "Pending" (`REQUIREMENTS.md:67,158`); `18-TRACEABILITY.md` sentences marking 18-25 "pending" (18-25 is complete, commits afcfe5e, aedb3b5, fc1c255); `docs/DECISIONS.md` D050 (d) still names `BINANCE_TESTNET_*` (historical text, left by rule).
6. **NOTE: `18-VALIDATION.md` is still `status: draft`, `nyquist_compliant: false`, `Approval: pending`.** The user signs these; listed as a human item.

## Human items

1. Sign off `18-VALIDATION.md` (draft/false/pending).
2. Attest no-withdrawal keys and the IP allowlist (OPS-02; Phase 24-26).
3. D055 stays OPEN: decision pending the user, informed by `decisions/18-DRAFT-D055-evidence-for-user.md` and `19-NOTES.md`. Partial-fill and triggered-stop behaviour on Demo remain unobserved and should be probed before relying on them.

---

_Verified: 2026-10-18_
_Verifier: Claude (gsd-verifier)_
