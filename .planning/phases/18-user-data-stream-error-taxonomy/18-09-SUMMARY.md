---
base: 85392f439a7030b718395301332bd60a6f6e601b
phase: 18-user-data-stream-error-taxonomy
plan: 09
subsystem: config/binance, adapters/binance-client, docs/decisions
status: complete
tags: [binance, limits, environments, credentials, O-18-01, O-18-04, OPS-02, EXEC-05, D072]
requires: [18-01, 18-02, 18-04, 18-07]
provides:
  - config/binance/binance-limits-v1.toml (the user's 27 values, provenance DECISION, sha256 9f522adcd35d56fa5dddbf79b42ab1f8c1d3f770bda7527caaf2cb28f8c43383 LF-normalized)
  - src/adapters/binance_client.py ENVIRONMENT_ROWS (DEMO ws_streams_url filled; DEMO ws_api_url and TESTNET NOT_CONFIGURED) and CREDENTIAL_SPECS (DEMO, LIVE)
  - tests/test_binance_limits_ratified_file.py (record-to-file, record-to-loader, record-to-rows, record-to-credentials, DECISIONS hash pin)
  - docs/DECISIONS.md D072
affects:
  - plans 18-10, 18-13 (RateLimitPolicy values now come from the ratified file)
  - plans 18-11, 18-14 (StreamLimits values; DEMO WebSocket Streams surface is now buildable)
  - plans 18-16, 18-17, 18-18 (scripts and the smoke load the file and the DEMO credential names)
tech-stack:
  added: []
  patterns:
    - parity tests that parse the decision record at test time; no expected value is a literal in the tests
    - limits file generated from the record's limit lines by a throwaway script, then checked by the parity tests
    - DECISIONS row found by title (not by number) so a merge-time renumber does not break the hash pin
key-files:
  created:
    - config/binance/binance-limits-v1.toml
    - tests/test_binance_limits_ratified_file.py
  modified:
    - src/adapters/binance_client.py
    - tests/test_binance_client_config.py
    - .gitattributes
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/integration/BINANCE.md
decisions:
  - "D-number D072: the next free number; D071 was the last row on phase-18, on the local develop branch, in the develop checkout and on every other local and remote branch checked at write time"
  - "config/binance/*.toml is marked -text in .gitattributes (the repository already uses -text for committed evidence files), so the ratified file is LF bytes on every checkout and its hash is stable"
  - "The host-literal scan of binance_client.py allows exactly one string constant, equal to the record's DEMO WebSocket Streams URL (the SDK has no constant for it), and still forbids every LIVE host"
metrics:
  duration: ~20min
  completed: 2026-10-16
  tasks: 3
  files: 8
actuals:
  tokens: 15200
  tasks: 3
  commits: 3
plan_head_before: 85392f439a7030b718395301332bd60a6f6e601b
plan_head_after: eb0c0cfd29d8d83b01a660368d434e96289ed279
---

# Phase 18 Plan 09: Ratified Binance limits, environment rows and credential names Summary

The user's record `decisions/18-DEC-O-18-01.md` is now in the repository verbatim: a 27-key limits file that the strict loader accepts, the DEMO streams row, the DEMO and LIVE credential names, and D072 pinning the file's sha256. Parity tests parse the record, so the repository cannot drift from it.

Plan revision: revised 2026-10-16 per `decisions/18-DEC-O-18-01.md` for the 27-key file (the user's split of the single rate-limit wait into a 418 key and a 429 key beside the cap).

## Record check (hard rule)

The record exists. It has `option: values`, `decided by: user` and date 2026-10-16. It has no `CODE CHANGE REQUESTED`, and its 27 `limit` lines match `CANONICAL_KEYS` exactly. A test (`test_the_record_has_exactly_the_canonical_limit_lines`) checks all of this. The executor chose no value.

## Record lines applied

Limits (`config/binance/binance-limits-v1.toml`, every key with provenance DECISION):

| Record line | File entry |
|---|---|
| limit client.rest_timeout_ms: 5000 | `[client] rest_timeout_ms = 5000` |
| limit client.sdk_retries: 0 | `[client] sdk_retries = 0` |
| limit client.sdk_backoff_ms: 0 | `[client] sdk_backoff_ms = 0` |
| limit signed_calls.recv_window_ms: 5000 | `[signed_calls] recv_window_ms = 5000` |
| limit signed_calls.rate_limit_418_no_retry_after_wait_seconds: 259200 | `rate_limit_418_no_retry_after_wait_seconds = 259200` |
| limit signed_calls.rate_limit_429_no_retry_after_wait_seconds: 120 | `rate_limit_429_no_retry_after_wait_seconds = 120` |
| limit signed_calls.rate_limit_retry_after_cap_seconds: 259200 | `rate_limit_retry_after_cap_seconds = 259200` |
| limit drift.ahead_limit_ms: 500 | `[drift] ahead_limit_ms = 500` |
| limit drift.behind_limit_ms: 1000 | `behind_limit_ms = 1000` |
| limit drift.include_measurement_uncertainty: true | `include_measurement_uncertainty = true` |
| limit drift.max_measurement_age_seconds: 300 | `max_measurement_age_seconds = 300` |
| limit drift.periodic_remeasure_interval_seconds: 60 | `periodic_remeasure_interval_seconds = 60` |
| limit stream.keepalive_interval_seconds: 1800 | `[stream] keepalive_interval_seconds = 1800` |
| limit stream.keepalive_failure_tolerance: 1 | `keepalive_failure_tolerance = 1` |
| limit stream.project_rotation_interval_seconds: none | `project_rotation_interval_seconds = "none"` |
| limit stream.reconnect_max_attempts: 7 | `reconnect_max_attempts = 7` |
| limit stream.reconnect_max_delay_seconds: 120 | `reconnect_max_delay_seconds = 120` |
| limit stream.reconnect_wait_multiplier_seconds: 1 | `reconnect_wait_multiplier_seconds = 1` |
| limit stream.reconnect_wait_max_seconds: 60 | `reconnect_wait_max_seconds = 60` |
| limit stream.sdk_reconnect_delay_ms: 5000 | `sdk_reconnect_delay_ms = 5000` |
| limit stream.sdk_reconnect_attempts: 3 | `sdk_reconnect_attempts = 3` |
| limit stream.snapshot_deadline_seconds: 20 | `snapshot_deadline_seconds = 20` |
| limit stream.snapshot_max_attempts: 7 | `snapshot_max_attempts = 7` |
| limit stream.snapshot_wait_multiplier_seconds: 1 | `snapshot_wait_multiplier_seconds = 1` |
| limit stream.snapshot_wait_max_seconds: 10 | `snapshot_wait_max_seconds = 10` |
| limit stream.max_liveness_age_seconds: none | `max_liveness_age_seconds = "none"` |
| limit stream.event_queue_max: 4096 | `event_queue_max = 4096` |

Environments and credentials (`src/adapters/binance_client.py`):

| Record line | Applied |
|---|---|
| probe environment: DEMO | checked: DEMO parses and its REST surface is configured (no code change) |
| env DEMO ws_streams_url: wss://demo-fstream.binance.com | `ENVIRONMENT_ROWS[DEMO].ws_streams_url`, with a comment naming record line 44 |
| env DEMO ws_api_url: NOT_CONFIGURED | `ws_api_url=None` (still raises `EnvironmentNotConfigured`) |
| env TESTNET: NOT_CONFIGURED | the whole TESTNET row stays None |
| credential DEMO key_variable / secret_variable | `CredentialSpec("BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET")` |
| credential LIVE key_variable / secret_variable | `CredentialSpec("BINANCE_LIVE_API_KEY", "BINANCE_LIVE_API_SECRET")` |
| (TESTNET has no credential line) | `credential_spec_for(TESTNET)` still raises `CredentialNamesNotRatified` |

Plan 18-06 already applied the `class` lines (the four UNKNOWN statuses). D072 restates them.

## D-number

D072. At write time I read the last row of `docs/DECISIONS.md` on `phase-18` (D071), on `git show develop:docs/DECISIONS.md` (D071), in the develop checkout `C:\Users\admin\Music\Trading` (D071) and on every other local and remote branch (`origin/develop` D069, `master` D067, `plan/phase-16` D062). The largest was D071, so the row is D072. The append script also checked contiguity (DC-02). Merge note: Phase 16 on develop also wants D072/D073. If develop takes D072 first, renumber this row's ID cell and the two `D072` mentions, in the DOC_STATUS 2026-10-16 line and the BINANCE.md subsection. `test_decisions_row_pins_the_limits_file_hash` finds the row by its title, not its number, so it survives the renumber. The hash does not change.

sha256 of the LF-normalized `config/binance/binance-limits-v1.toml`: `9f522adcd35d56fa5dddbf79b42ab1f8c1d3f770bda7527caaf2cb28f8c43383` (equal to `git show HEAD:config/binance/binance-limits-v1.toml | sha256sum`).

## Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 (tracer) | Record becomes the ratified limits file; real loader accepts it | a55638d | config/binance/binance-limits-v1.toml, tests/test_binance_limits_ratified_file.py, .gitattributes |
| 2 | Environment rows and credential names from the record | 88ae30c | src/adapters/binance_client.py, tests/test_binance_client_config.py, tests/test_binance_limits_ratified_file.py |
| 3 | D072 with the file hash, DOC_STATUS line, BINANCE.md subsection | eb0c0cf | docs/DECISIONS.md, docs/DOC_STATUS.md, docs/integration/BINANCE.md, tests/test_binance_limits_ratified_file.py |

## Verification

- Task 1: `pytest tests/test_binance_limits_ratified_file.py tests/test_binance_limits.py -x` passed. RED was confirmed first: 11 failed while the file was absent. After task 1, `git diff --name-status BASE..a55638d -- src` printed nothing.
- Task 2: `pytest tests/test_binance_client_config.py tests/test_binance_limits_ratified_file.py tests/test_binance_secret_redaction.py tests/test_demo_rehearsal_safety.py -x`: 133 passed. RED was confirmed first: 14 failed. `tests/test_demo_rehearsal_safety.py` was not changed.
- Task 3: `pytest tests/test_binance_limits_ratified_file.py tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_exchange.py -x`: 145 passed (the hash test failed first, as RED).
- `python scripts/verify_decision_alignment.py all`: ALL_PASS all. `python scripts/verify_decision_alignment.py docs`: ALL_PASS docs.
- `mypy src`: no issues in 193 source files. `ruff format --check`: 572 files already formatted. `ruff check` on this plan's files: all checks passed. The whole-repo `ruff check` reported one I001 in `tests/test_stream_records.py`, which is 18-08's uncommitted work in progress and not part of this plan.
- Every command ran with `UV_OFFLINE=1 uv run --frozen --extra dev`. No network, no `.env`, no database URL.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The host-literal scan rejected the user's DEMO streams URL**
- **Found during:** Task 2
- **Issue:** `test_client_module_has_no_host_literal` (plan 18-04) forbids any string constant containing the LIVE streams host `fstream.binance.com`, and the regex `fstream\.binance`. The record's `wss://demo-fstream.binance.com` contains that substring. The SDK has no Demo streams constant, so the row has to carry a literal.
- **Fix:** The scan now allows exactly one string constant, equal to the record's DEMO streams URL (parsed from the record), and still forbids every LIVE host in every other constant and in the rest of the source. I updated the module docstring and the row comment (comments only; no logic touched).
- **Files modified:** tests/test_binance_client_config.py, src/adapters/binance_client.py
- **Commit:** 88ae30c

**2. Placeholder tests of plan 18-04 replaced by record-driven ones**
- `test_credential_names_are_not_ratified_in_this_plan` (asserted `CREDENTIAL_SPECS == {}`) became `test_credential_names_exist_only_for_the_environments_the_record_names`.
- `test_demo_websocket_surface_is_not_configured` became `test_demo_websocket_surface_follows_the_record`. For WS_STREAMS it now builds and passes the guard with no request. WS_API still raises.
- `test_environment_rows_come_from_the_sdk_constants` became `..._and_the_record`.
- Removed asserts: `assert dict(bc.CREDENTIAL_SPECS) == {}` and `assert demo.ws_streams_url is None`. Assertions parsed from the record replace both.
- New tests: the DEMO streams near-miss matrix through `assert_endpoint_url` and `assert_environment`, mutation refusal, the SDK `/stream` suffix, the all-surfaces DEMO case, and the DEMO/LIVE name disjointness.

**3. Line endings of the limits file**
- The plan requires LF. The sibling config files are CRLF in the working tree because of `core.autocrlf=true`. The plan allows `-text` when the repository already uses it for evidence files, and it does, so `config/binance/*.toml -text` was added to `.gitattributes`. The file is LF bytes everywhere, and the LF test is strict (no CR at all). New test files are CRLF in the working tree like their siblings.

**4. SUMMARY layout**
- The plan asks for `base: <sha>` as the first line. It is the first key of the frontmatter, so the frontmatter stays parseable. `grep '^base:'` finds it.

**5. Commit count**
- The ledger range `85392f4..eb0c0cf` holds 4 commits. One of them, 231c996, is plan 18-08's tracer, committed concurrently on the same branch. The 3 commits of this plan were measured with `git rev-list --count --grep="(18-09)" 85392f4..HEAD`.

## Open issues

- The Phase 9 rehearsal (`scripts/demo_rehearsal.py`) and `.env.example` still use `BINANCE_TESTNET_API_KEY`/`BINANCE_TESTNET_API_SECRET` for the Demo key pair. The ratified DEMO names are `BINANCE_DEMO_API_KEY`/`BINANCE_DEMO_API_SECRET`, and `.env.example` has no `BINANCE_DEMO_*` entries. The plan forbids changing the rehearsal (its safety test must stay unchanged), so plans 18-16 and 18-17 (scripts) should align the names. Until then a key supplied under the old names will not be found by `credential_spec_for(DEMO)`, which fails closed.
- The DEMO WebSocket Streams URL is a single-source fact. `docs/SOURCES.md` "Facts read for Phase 18" item 3 is UNVERIFIED but does not contradict the record. Demo user-data support is still for the probe and smoke (18-18) to settle. The user did not approve running either.
- The D072 merge collision with Phase 16 is described above.
- STATE.md and ROADMAP.md were not updated (orchestrator instruction).

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema was added. The credential names are variable names only, and loading still goes through the existing `load_api_credentials`.

## Self-Check: PASSED

- FOUND: config/binance/binance-limits-v1.toml
- FOUND: tests/test_binance_limits_ratified_file.py
- FOUND: a55638d, 88ae30c, eb0c0cf
