---
phase: 18-user-data-stream-error-taxonomy
plan: 04
subsystem: adapters/binance-client, ops/redaction
status: complete
tags: [binance, environment, endpoint-guard, credentials, redaction, listenKey, OPS-02, D-12, D-13]
requires: []
provides:
  - src/adapters/binance_client.py (Environment, parse_environment, Surface, EnvironmentRow, ENVIRONMENT_ROWS, INERT_WS_URL, INERT_REST_URL, SDK_STREAMS_PATH_SUFFIX, ClientLimits, CredentialSpec, ApiCredentials, CREDENTIAL_SPECS, credential_spec_for, load_api_credentials, SdkClientBundle, build_sdk_client, assert_endpoint_url, assert_environment, LiveEnablementState, and the seven exceptions)
  - src/ops/redaction.py register_runtime_secret, clear_runtime_secrets, listenKey key-name parts and shape rules
affects:
  - scripts/demo_rehearsal.py (assert_demo_base_url delegates to assert_endpoint_url)
  - plans 18-09 (fills ENVIRONMENT_ROWS DEMO WebSocket URLs / TESTNET row, CREDENTIAL_SPECS, ClientLimits values), 18-11 (registers the listenKey with register_runtime_secret)
tech-stack:
  added: []
  patterns:
    - one environment row per environment; every URL an SDK constant; inert .invalid URL for unrequested surfaces
    - guard re-reads every SDK surface (REST via client.rest_api, WebSocket via private config attributes, pinned by a contract test)
    - runtime secrets merged into the active redactor as one longest-first alternation, recompiled only on change
key-files:
  created:
    - src/adapters/binance_client.py
    - tests/test_binance_client_config.py
    - tests/test_binance_secret_redaction.py
  modified:
    - src/ops/redaction.py
    - scripts/demo_rehearsal.py
    - tests/test_redaction.py
decisions:
  - "An unrequested REST surface gets INERT_REST_URL (https://surface-not-requested.invalid) and no credential, the REST counterpart of INERT_WS_URL, because the SDK's rest_api property also falls back to mainnet when base_path is None"
  - "assert_endpoint_url takes the allowed path from the expected row URL (not only '' or '/'), because the SDK WebSocket API constant carries the path /ws-fapi/v1"
  - "assert_environment accepts a WS_STREAMS URL with or without the SDK's own '/stream' suffix (WebSocketStreamBase.__init__ appends it when the lazy websocket_streams property is first read); any other path is refused"
metrics:
  duration: "about 15 minutes (2026-10-16T02:45Z to 03:00Z)"
  completed: 2026-10-16
  tasks: 3
  files: 6
actuals:
  tokens: 18000
  tasks: 3
  commits: 7
plan_head_before: b195db9037c57e0f92d9a1299cfb47d144e8d02b
plan_head_after: f669cb4fbc02e3f028e79d4b2abf5bb8661bcf49
---

# Phase 18 Plan 04: Explicit Binance environment, guarded single SDK client factory and secret redaction Summary

One factory (`build_sdk_client`) builds the Binance USD-M SDK client for an explicitly selected DEMO, TESTNET or LIVE environment. All three SDK configurations come from one environment row of SDK constants, and an unrequested surface gets an inert `.invalid` URL. A guard re-reads REST, WebSocket Streams and WebSocket API before use. Keys come only from environment variables or from `<NAME>_FILE` files outside the repository. Loaded keys, secrets and listenKeys are scrubbed from stdlib logging, structlog and exception text.

## Commits

`commits: 7` is measured as `git rev-list --count b195db9..f669cb4`. The worktree is shared with plan 18-01, so 4 of those 7 commits are 18-01 docs commits (fe12f45, a75343e, 5854085, a8f2580). This plan owns three task commits, plus the SUMMARY commit that follows:

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 3b6a3a3 | explicit environment selection and the single guarded SDK client factory; transport-level Demo-host test |
| 2 | bf1729d | the guard covers all surfaces and every near-miss URL; AST construction-site allow-list; SDK-internals contract test; the rehearsal guard now delegates |
| 3 | f669cb4 | file-based credential loading, `refuse_if_present`, runtime secret registration, listenKey redaction rules |

## Construction-site allow-list (scanned from the tree at the start of Task 2)

`tests/test_binance_client_config.py::ALLOWED_SDK_CONSTRUCTION_SITES` checks every call to `DerivativesTradingUsdsFutures(...)` under `src/` and `scripts/`. The set must match exactly:

| File | Enclosing scope | Why allowed |
|------|-----------------|-------------|
| `src/adapters/binance_client.py` | `build_sdk_client` | the single factory for a client that can sign (this plan) |
| `scripts/demo_rehearsal.py` | `build_demo_sdk_client` | Phase 9 rehearsal builder, Demo REST only, unchanged |
| `src/adapters/binance_public.py` | `_credential_free_client` | pre-existing public-data default (REST configuration with no key and no secret) |
| `src/adapters/binance_usdm.py` | `BinanceUsdmAdapter.__init__` | pre-existing no-argument default `sdk_client or DerivativesTradingUsdsFutures()` (no credentials) |

The scan found no other construction sites.

## What was built

- **Environment selection (D-12).** `parse_environment` accepts exactly `DEMO`, `TESTNET` or `LIVE`. A value that is None, blank, lower-case, padded with spaces, or not text raises `EnvironmentNotSelected` or `UnknownEnvironment`. `build_sdk_client` refuses a raw string. No environment is ever inferred from a host.
- **Environment rows.**
  - DEMO REST is the SDK Demo constant.
  - LIVE uses the three SDK PROD constants.
  - The DEMO WebSocket URLs and the whole TESTNET row are `None`. They are owner-open and plan 18-09 fills them, so selecting them raises `EnvironmentNotConfigured` before any SDK object exists.
  - `ENVIRONMENT_ROWS` is a read-only `MappingProxyType`.
  - The module contains no host literal (a test checks this).
- **`ClientLimits` (F-504).**
  - `rest_timeout_ms`, `sdk_retries` and `sdk_backoff_ms` are keyword-only and have no defaults.
  - The integer type is strict (bool and float are rejected), and out-of-range values raise.
  - The factory passes the three values to `ConfigurationRestAPI(timeout=..., retries=..., backoff=...)`.
  - The values used in tests are named `TEST_ONLY_*` constants.
- **LIVE.** Building for LIVE raises `LiveNotEnabled` unless the passed `LiveEnablementState.is_disabled` is exactly `False`. The default `LiveEnablementController` (disabled) is refused. Nothing here enables LIVE.
- **Guard.**
  - `assert_endpoint_url` requires an exact match with the row URL. It rejects a scheme downgrade or swap, a port, userinfo, a suffix or prefix on the host name, an upper-case host, a trailing slash or path, a query, a fragment, an empty value, None and non-strings. Error text names the environment and surface only, never a URL.
  - `assert_environment` re-reads REST through `client.rest_api.configuration.base_path`. It reads the WebSocket configurations from `_websocket_streams_config` and `_websocket_api_config` without triggering the lazy properties, and also checks any surface object that has already been built. If a configuration cannot be read, it fails closed.
- **Credentials (D-13).**
  - `load_api_credentials(environ, *, spec, repo_root, refuse_if_present=(), read_file=None)` reads either `<NAME>` or `<NAME>_FILE`.
  - The file must be absolute, existing, regular, outside `repo_root` after resolving, and non-blank. Surrounding whitespace is stripped.
  - Setting both `<NAME>` and `<NAME>_FILE` raises "ambiguous".
  - Only the spec's own names are looked up (a recording mapping proves no LIVE name is read for DEMO).
  - `refuse_if_present` refuses if another spec's variable, or its `_FILE` form, is present.
  - Errors name only the variable, never a value or a path.
  - `CREDENTIAL_SPECS` is empty, and `credential_spec_for` raises `CredentialNamesNotRatified` until plan 18-09.
  - No parameter of the loader or the factory carries a key or secret apart from `credentials` (a signature test checks this).
- **Redaction (OPS-02, research P3).**
  - `register_runtime_secret` is lock-guarded and idempotent, and ignores values shorter than `MIN_SECRET_LENGTH`. It stores the percent-encoded and JSON-escaped variants as well.
  - `_current()` merges the registered values into the active redactor, or into the redactor built from the environment. The merge produces one alternation, longest value first, and is cached until either side changes.
  - `clear_runtime_secrets` is the test helper that empties the registry.
  - `listenkey` and `listen_key` were added to `SECRET_KEY_NAME_PARTS`.
  - Two new shape rules cover `listenKey=<24+ alnum>` and `"listenKey": "<value>"` (also the single-quoted dict repr).
  - All existing rules and tests are unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Inert REST URL for an unrequested REST surface**
- **Found during:** Task 1.
- **Issue:** The plan gives inert URLs only for the WebSocket surfaces. But the SDK's `rest_api` property sets `base_path` to the mainnet REST URL whenever `base_path` is None, and the SDK creates a default REST configuration when none is passed. A client built for streams only would therefore carry a mainnet REST surface.
- **Fix:** Added `INERT_REST_URL = "https://surface-not-requested.invalid"`. An unrequested REST surface gets this URL and no credential, and the guard checks it.
- **Files:** src/adapters/binance_client.py. **Commit:** 3b6a3a3.

**2. [Rule 1 - Bug in the spec as written] The allowed path comes from the row URL**
- **Found during:** Task 1.
- **Issue:** The plan says the path must be "" or "/". The SDK constant for the LIVE WebSocket API is `.../ws-fapi/v1`, so the plan's rule would reject the correct LIVE WebSocket API URL.
- **Fix:** The path must equal the expected row URL's path. Combined with the exact-equality rule, any other path is still refused.
- **Files:** src/adapters/binance_client.py. **Commit:** 3b6a3a3.

**3. [Rule 1 - Bug] The SDK appends `/stream` to the streams URL**
- **Found during:** Task 2, while reading `binance_common/websocket.py` `WebSocketStreamBase.__init__`.
- **Issue:** When the lazy `websocket_streams` property is first read, the SDK changes `configuration.stream_url` to `<url>/stream`. With exact equality, the guard would fail on every streams client once it is in use, which is exactly when plan 18-11 needs the guard.
- **Fix:** For WS_STREAMS only, the guard accepts the row URL or the row URL plus the SDK suffix (`SDK_STREAMS_PATH_SUFFIX`). Any other path is refused. A test pins this SDK behaviour.
- **Files:** src/adapters/binance_client.py, tests/test_binance_client_config.py. **Commit:** bf1729d.

**4. [Rule 2] Credential file paths go through `Path.resolve(strict=True)`**
- **Found during:** Task 3.
- **Issue:** A `..` hop or a symlink must not get around the "inside the repository" check.
- **Fix:** The path is resolved strictly before the repository check (tested with `REPO_ROOT/src/../pyproject.toml`). Leading whitespace is stripped as well as trailing whitespace, matching the environment path.
- **Commit:** f669cb4.

**5. [Plan conflict, minimal adaptation] The construction-site allow-list uses qualified scopes**
- **Found during:** Task 2.
- **Issue:** The pre-existing default construction in `binance_usdm.py` sits inside a method, so a bare function name would be ambiguous.
- **Fix:** The AST visitor records `Class.method`, which gives the entry `BinanceUsdmAdapter.__init__`. The rehearsal's own AST test is unchanged and still passes.

The rehearsal change is limited to the guard internals as the plan asks. `assert_demo_base_url` keeps the message "missing or not text" and the message "not the Demo Trading host demo-fapi.binance.com". The unused `urlsplit` import was removed. `build_demo_sdk_client`, `SDK_TIMEOUT_MS`, the credential constants, the evidence code and the parser are untouched.

## Verification results

- `uv run pytest -m "not docker" tests/test_binance_client_config.py tests/test_binance_secret_redaction.py tests/test_redaction.py tests/test_demo_rehearsal_safety.py tests/test_demo_rehearsal_flow.py -x`: **161 passed**. Per file: test_binance_client_config 57, test_binance_secret_redaction 20, test_redaction 26 (21 existing + 5 added, no assertion removed), test_demo_rehearsal_safety 30, test_demo_rehearsal_flow 28.
- Tests outside the plan that also use the redactor: `tests/test_paper_ws_smoke_evidence.py tests/test_env_example.py tests/test_order_ids.py tests/test_execution_secret_posture.py`: 102 passed.
- `uv run mypy src`: Success, no issues in 186 source files.
- `uv run ruff check`: All checks passed.
- `uv run ruff format --check`: all files already formatted.
- The full suite was not run (memory limit; only the files named in the plan's verify blocks were run).
- Runs used `UV_OFFLINE=1 uv run --frozen --extra dev`, which created an untracked, git-ignored `.venv` in the worktree. There was no network access, no `.env` read and no database URL.

## TDD gate notes

Each task started red:
- Task 1: collection error, because the module was missing.
- Task 2: 2 failing tests, the `/stream` suffix and the rehearsal delegation.
- Task 3: 20 errors, because `clear_runtime_secrets` was missing.

Each task then went green before its commit. Tests and implementation share one commit per task, following the per-task commit rule of this plan.

## Known Stubs

None that block the plan goal. The following owner-open values are intentionally unconfigured, as the plan requires; plan 18-09 fills them from the owner's record:
- `ENVIRONMENT_ROWS[DEMO].ws_streams_url` and `ws_api_url` are None.
- `ENVIRONMENT_ROWS[TESTNET]` has every URL None.
- `CREDENTIAL_SPECS` is empty.
- `ClientLimits` has no values in `src`.

## Threat Flags

None beyond the plan's threat model:
- T-18-09 (mixed environment) is mitigated by the single factory, the inert URLs, the guard on all three surfaces, the AST test and the transport test.
- T-18-10 and T-18-11 (secret and listenKey disclosure) are mitigated by runtime registration, the shape and key-name rules, and capture tests over stdlib, structlog and a NetworkError.
- T-18-12 (cross-environment credentials) is mitigated by spec-only reads, `refuse_if_present` and the LIVE enablement requirement.
- T-18-SC: no package was installed or changed.

## Open issues for later plans

- Plan 18-11 must call `register_runtime_secret(listen_key)` when it receives a listenKey. The shape rules only cover the `listenKey=` and JSON forms. A bare key inside the SDK's `Subscribing to streams ... ['<key>']` line is masked only once the key is registered.
- `tests/conftest.py` does not clear runtime secrets between tests. The new test files clean up with their own fixtures. A future test that registers secrets without cleaning up could leak masking into later tests, which over-masks but never leaks a secret.

## Self-Check: PASSED

- FOUND: src/adapters/binance_client.py, tests/test_binance_client_config.py, tests/test_binance_secret_redaction.py (created); src/ops/redaction.py, scripts/demo_rehearsal.py, tests/test_redaction.py (modified)
- FOUND commits: 3b6a3a3, bf1729d, f669cb4
