---
phase: 18-user-data-stream-error-taxonomy
plan: 05
subsystem: domain/exchange-errors, adapters/binance-errors
status: complete
tags: [binance, error-taxonomy, rate-limit, retry, EXEC-02, EXEC-01, D-09, D-10, D-11, O-18-01]
requires: [18-01, 18-03]
provides:
  - src/domain/exchange_errors.py (HttpClass, CallKind, ExchangeErrorCategory, ErrorFacts, CodeEntry, EVIDENCE_LABELS, ERROR_CODE_TABLE, ERROR_TABLE_SOURCE, ERROR_TABLE_READ_DATE, classify, retry_eligible, safe_mode_eligible, RateLimitDecision, rate_limit_decision)
  - src/adapters/binance_errors.py (error_facts_from_exception)
  - tests/test_sdk_error_mapping_contract.py (offline pin of the installed SDK's HTTP-status to exception mapping and its retry loop)
affects:
  - plan 18-10 (routes binance_usdm.py not-found, cancel retry and rate-limit helpers through classify / retry_eligible / rate_limit_decision; rewrites tests/test_adapter_not_found_mapping.py legacy message test)
  - plans 18-07 / 18-09 (supply the three rate-limit keyword arguments from configuration)
  - plan 18-13 (consumes RateLimitDecision for the shared REST gate)
  - plan 18-20 (live probe of the codes)
tech-stack:
  added: []
  patterns:
    - classification keyed on the triple (SDK class, int body code, call kind); the class rule overrides the code
    - read-only MappingProxyType code table with per-entry source, read date and evidence label, checked against docs/SOURCES.md
    - required keyword-only wait arguments with no defaults; an AST test forbids any number other than 0 in rate_limit_decision
    - stub requests-like session driving the installed binance_common send_request, with sockets refused
key-files:
  created:
    - src/domain/exchange_errors.py
    - src/adapters/binance_errors.py
    - tests/test_exchange_errors.py
    - tests/test_sdk_error_mapping_contract.py
  modified: []
decisions:
  - "rate_limit_decision has no call-kind parameter: after the user's amendment of 2026-10-16 no call kind may retry a 418 or a 429, so it would decide nothing (planner's choice, kept)"
  - "A code met on a call kind it is not expected on classifies UNKNOWN_EXCHANGE_ERROR: placement rejections (-2010, -2018, -2019, -2021, -2022, -2024, -2026, -4003, -4004, -4005, -4014, -4120, -4137, -4138, -4142, -4164, -4400, -4401, -1111), -4116 and -4509 are mapped on PLACEMENT only; -1121 on PLACEMENT, CANCEL, QUERY; -1125 on LISTEN_KEY only; -2011/-2013 on QUERY and CANCEL only; rate-limit, status-unknown, clock, auth and position-mode codes on every call kind"
  - "Every entry carries read_date 2026-10-16 (the latest 'Checked on' date of the SOURCES error-code row, as the plan requires); codes quoted by the 2026-10-16 re-read say 're-read 2026-10-16' in their note, the other documented codes say they come from research baseline B7 (2026-10-15), and a test proves the re-read set equals the codes quoted in the SOURCES row"
  - "-1121 carries evidence 'documented-elsewhere': it is not on the Phase 18 error-code reads; it is recorded in the SOURCES Phase 13 Kline delisted-symbol row (a production live probe, not a page read)"
  - "RequiredError (SDK, raised before any request for a missing parameter) normalizes to NON_SDK and so classifies UNKNOWN_EXCHANGE_ERROR"
metrics:
  duration: 35min
  completed: 2026-10-16
estimate:
  tokens: 74000
  tasks: 3
actuals:
  tokens: 16300
  tasks: 3
  commits: 3
plan_head_before: 36d7fd6dc2e0e207577b0731f71dc94fa36e3bfc
plan_head_after: 5261171c1c9031ede2483cd7bf8cf721397cc7ee
---

# Phase 18 Plan 05: Exchange Error Taxonomy Summary

Pure (class, int code, call kind) taxonomy with a 37-code dated table, retry only for status-unknown reads/cancels/time/listenKey, a never-retry rate-limit decision whose 418/429 fallbacks and cap are required arguments, and an SDK normalizer pinned offline against the installed `send_request`.

Plan revision: revised 2026-10-16 per `decisions/18-DEC-O-18-01.md` and its amendment of the same day: separate 418 and 429 fallback arguments, retry always False on 418 and 429, `retry_eligible` limited to STATUS_UNKNOWN, no call-kind parameter in `rate_limit_decision` because it would decide nothing.

## Performance

- Duration: about 35 minutes
- Tasks: 3 of 3
- Files: 4 created, 0 modified

## Accomplishments

- A real SDK `BadRequestError(-2013)` produced by the installed `send_request` from a stubbed 400 is ORDER_ABSENT for a query and UNKNOWN_EXCHANGE_ERROR for a placement; a `RuntimeError("-2013 NO_SUCH_ORDER")` is NON_SDK and UNKNOWN for every call kind (message text is never read; an AST test forbids `str`, `repr`, f-strings, `.args`, `.error_message`, `.msg` in the normalizer).
- 37 required codes with name, per-call-kind category, source, read date and evidence; class rules (418 IP_BANNED, 429 RATE_LIMITED, 5xx/408/network STATUS_UNKNOWN, 401/403 AUTH_OR_SIGNATURE, NON_SDK UNKNOWN) override the code.
- `retry_eligible` is True only for STATUS_UNKNOWN on QUERY, CANCEL, TIME, LISTEN_KEY (full cross-product test); `safe_mode_eligible` only for UNKNOWN_EXCHANGE_ERROR.
- `rate_limit_decision` returns `RateLimitDecision(retry=False, wait_seconds)`; the three wait keywords are required (TypeError when missing), positive non-bool ints (ValueError otherwise); tests use `TEST_ONLY_418_FALLBACK_SECONDS = 11`, `TEST_ONLY_429_FALLBACK_SECONDS = 5`, `TEST_ONLY_CAP_SECONDS = 13`, so a swapped fallback fails; the user's numbers (259200, 120) are asserted absent from the module.
- Contract test: ten HTTP status rows, non-JSON 400 and 5xx bodies, Retry-After `7` / missing / `soon` / `-5` for 418 and 429, ConnectTimeout, the SDK retry pin and the installed error-class set; sockets are refused by an autouse fixture.

## Task Commits

1. Task 1 (tracer): `68c0f89` feat(18-05): tracer - a real SDK BadRequestError(-2013) is normalized and classified by class, code and call kind
2. Task 2: `6dc3cbd` feat(18-05): complete the code table, class rules, retry and SAFE_MODE eligibility and the rate-limit decision
3. Task 3: `5261171` test(18-05): pin the installed SDK's HTTP-status to exception mapping and its retry loop offline

## Verification

- `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_sdk_error_mapping_contract.py -x`: 286 passed (tracer step 6 passed; Task 2 step 262 passed in test_exchange_errors.py)
- `uv run mypy src`: no issues in 190 source files
- `uv run ruff check`: all checks passed; `uv run ruff format --check`: 560 files already formatted
- `uv lock --check`: exit 0 (no dependency changed)

## SDK delta

- Retry loop: with `retries=2` the installed `send_request` sends 2 requests for a GET or DELETE that keeps raising `ConnectTimeout`, not 3 as the plan expected. The loop increments `attempt` and asks `should_retry_request(e, method, retries - attempt)`, which refuses when `retries - attempt` is 0, so `retries=N` gives N requests (N >= 1) and N-1 sleeps of `backoff * attempt`. The test pins 2 calls and sleeps `[1.0]` for `retries=2`, 3 calls and `[1.0, 2.0]` for `retries=3`, and 1 call with no sleep for a POST. The research P9 figure ("up to 3 SDK requests" per tenacity try with the default `retries=3`) still holds for the default; only the plan's `retries=2 -> 3 calls` reading differs.
- Additionally pinned (consistent with research): an HTTP error answer (503, 418, 429) is never retried by the SDK, because only `requests.RequestException` enters the retry branch; a 503 non-JSON body and a JSON body give the same `ServerError(status_code=503)`.
- A `Retry-After: -5` header comes through the SDK as `retry_after == -5` (`int("-5")`); the normalizer turns it into None.
- The installed `binance_common.errors` also defines `RequiredError` (not in the plan's list); it is mapped to NON_SDK and the full class set is pinned.

## Deviations from Plan

### Auto-fixed Issues

None to the code under test. Two test-side adjustments:

**1. [Rule 1 - Test expectation] SDK retry-pin call count**
- Found during: Task 3
- Issue: the plan expected 3 session calls for `retries=2`; the installed SDK makes 2 (see SDK delta).
- Fix: the test records the installed behavior (as the plan instructs when the SDK differs) and adds a `retries=3` case.
- Files modified: tests/test_sdk_error_mapping_contract.py
- Commit: 5261171

**2. [Rule 2 - Hardening] Extra guards**
- `CodeEntry` validates its evidence label against `EVIDENCE_LABELS`; `classify`, `retry_eligible`, `safe_mode_eligible` and `rate_limit_decision` raise TypeError on a non-enum argument; the bad-keyword test also covers `None` and a string, and the ValueError is raised for every category, not only the two rate-limit ones.
- Commits: 6dc3cbd

## Open Issues (facts that depend on unverified Binance documentation)

- All table text is from WebFetch summaries (not character-exact, not verified live). 13 codes were quoted by the 2026-10-16 re-read (-1003, -1015, -1021, -1022, -1125, -2011, -2013, -2019, -2021, -4067, -4068, -4116, -4164); 22 others (-1006, -1007, -1008, -1111, -2010, -2014, -2015, -2017, -2018, -2022, -2024, -2026, -4003, -4004, -4005, -4014, -4120, -4137, -4138, -4142, -4400, -4401) rest on research baseline B7 of 2026-10-15 only, yet carry read_date 2026-10-16 because the plan ties every entry to the row's latest date; their notes say so. The names of -4014, -4067, -4068, -4400 and -4401 are descriptive, not page names.
- -4509 is Demo-observed only (absent from the page). -1121 is a production live-probe observation recorded in SOURCES Phase 13, not a page read ("documented-elsewhere").
- -1125 as the answer to a keepalive of an expired listenKey is assumed (the listenKey pages list no errors).
- The duplicate `clientAlgoId` code and the not-found code of `GET /fapi/v1/algoOrder` on production are not on the page (probe, plan 18-20).
- Whether Binance sends `Retry-After` on 418/429 is unknown (absent from every page read); the fallbacks are the expected path.
- 403 is documented (baseline B8) as a WAF limit, but the plan maps it to AUTH_OR_SIGNATURE; both are never retried, so the difference matters only for diagnostics.
- -1008 is described by B8 as a definite failure that may be retried with backoff; the plan maps it to RATE_LIMITED, which is never retried.
- The research 503 variants ("execution may have succeeded" versus "definite failure") cannot be told apart because the SDK discards the 5xx body; all 5xx are STATUS_UNKNOWN (fail-closed).

## Known Stubs

None. `src/adapters/binance_usdm.py` is intentionally untouched; its message-text fallbacks stay until plan 18-10 reroutes it.

## Threat Flags

None: no new endpoint, auth path or file access; the normalizer exposes only class, int code and retry_after (T-18-13, T-18-14, T-18-15 mitigated as planned).

## Self-Check: PASSED

- FOUND: src/domain/exchange_errors.py, src/adapters/binance_errors.py, tests/test_exchange_errors.py, tests/test_sdk_error_mapping_contract.py
- FOUND commits: 68c0f89, 6dc3cbd, 5261171
