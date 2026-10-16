---
phase: 18-user-data-stream-error-taxonomy
plan: 07
subsystem: adapters/binance-limits, adapters/binance-clock
status: complete
tags: [binance, limits, clock-drift, recvWindow, rate-limit, OPS-02, EXEC-05, D-14, O-18-01]
requires: [18-02, 18-03, 18-04]
provides:
  - src/adapters/binance_limits.py (CANONICAL_KEYS, RateLimitPolicy, SignedCallPolicy, DriftLimits, StreamLimits, BinanceLimits, parse_binance_limits, load_binance_limits, LimitsNotRatified, LimitsFileMissing)
  - src/adapters/binance_clock.py (DriftVerdict, evaluate_clock_drift, measure_clock_drift, DriftBlockReason, ClockDriftGuard)
  - config/binance/README.md (the 27 required keys, the file format, no value)
  - tests/support/limits.py (TEST_ONLY values, test_only_* builders, write_limits_toml)
affects:
  - plan 18-09 (writes config/binance/binance-limits-v1.toml in the format of config/binance/README.md; the loader must accept the user's values)
  - plan 18-10 (RestRateLimitGate holds RateLimitPolicy)
  - plan 18-11, 18-14 (StreamLimits, test_only_stream_limits)
  - plan 18-12, 18-13 (SignedCallPolicy, ClockDriftGuard.entries_allowed / blocked_reason / note_clock_skew_error, measure_clock_drift failure_type)
  - plan 18-16, 18-17 (scripts load BinanceLimits; the scan forbids numeric defaults in scripts)
tech-stack:
  added: []
  patterns:
    - frozen keyword-only dataclasses with no defaults for every safety threshold; ValueError for a bad value, TypeError for a wrong member type
    - strict tomllib loader collecting every problem and naming keys or sections only, never a value or a path
    - provenance as a nested table provenance.<section>.<key> (either [provenance.<section>] sub-tables or dotted keys under [provenance])
    - pure drift decision on injected integer readings; measurement coroutine takes its clock, UTC clock and server-time source as arguments
    - AST scan of src and scripts forbidding any numeric constant bound to a canonical key name
key-files:
  created:
    - src/adapters/binance_limits.py
    - src/adapters/binance_clock.py
    - config/binance/README.md
    - tests/support/limits.py
    - tests/test_binance_limits.py
    - tests/test_clock_drift.py
    - tests/test_no_unratified_defaults.py
  modified: []
decisions:
  - "A pending re-measure request (set by note_clock_skew_error on a -1021) makes the last in-limit verdict STALE until the next refresh records a fresh in-limit verdict: Binance has just contradicted the clock, so entries are blocked rather than allowed on the old verdict (fail closed; within the plan's set of four block reasons)"
  - "refresh clears the request BEFORE it measures, so a -1021 that arrives while the server-time call is in flight stays pending for the next refresh"
  - "evaluate_clock_drift takes an optional measured_at_utc (None default, no numeric default); ClockDriftGuard.record refuses a verdict without one, so the age rule can always be applied"
  - "DriftVerdict carries a failure_type field (exception type name, or one of the fixed words NAIVE_SERVER_TIME, NOT_A_DATETIME, HOST_CLOCK_BACKWARDS, INVALID_HOST_CLOCK_READING); a failed verdict has no offset and no uncertainty"
  - "A verdict whose measurement time lies after now_utc (the injected clock went backwards) counts as STALE; the age boundary is inclusive (age equal to max_measurement_age_seconds still allows)"
  - "LimitsFileMissing is a subclass of LimitsNotRatified, so a caller catching LimitsNotRatified fails closed on both"
  - "The behind-limit-not-above-recvWindow rule lives in BinanceLimits.__post_init__ (every construction enforces it) and the loader turns its ValueError into LimitsNotRatified"
  - "StreamLimits does not check the SDK's own range for sdk_reconnect_attempts (not in the plan's behavior); the SDK raises ValueError itself when plan 18-11 passes an out-of-range value"
  - "The test_only_* builders are marked __test__ = False so a test module importing one by name does not have pytest collect it"
metrics:
  duration: 12min
  completed: 2026-10-16
estimate:
  tokens: 78000
  tasks: 3
actuals:
  tokens: 26800
  tasks: 3
  commits: 4
plan_head_before: 9dc2cef3e41250938d7cc69674c93cd0ca82475c
plan_head_after: e148a32fa0bfc24185a3e8e2b31b5420625a69e4
---

# Phase 18 Plan 07: Binance Limits Structures and Clock-Drift Guard Summary

Every O-18-01 safety threshold now has a typed home with no default: frozen keyword-only `RateLimitPolicy` (418, 429, cap), `SignedCallPolicy`, `DriftLimits`, `StreamLimits` and `BinanceLimits`, a strict `tomllib` loader over exactly 27 keys with provenance labels that fails closed, a pure clock-drift decision with an injected-clock measurement, and a `ClockDriftGuard` that blocks new entries unless a fresh in-limit measurement exists. No number was chosen and none of the user's values were copied.

Plan revision: revised 2026-10-16 per `decisions/18-DEC-O-18-01.md` to 27 canonical keys and a three-field `RateLimitPolicy` (`no_retry_after_wait_418_seconds`, `no_retry_after_wait_429_seconds`, `retry_after_cap_seconds`, mapped from `signed_calls.rate_limit_418_no_retry_after_wait_seconds`, `signed_calls.rate_limit_429_no_retry_after_wait_seconds` and `signed_calls.rate_limit_retry_after_cap_seconds`); the former single key `signed_calls.rate_limit_no_retry_after_wait_seconds` refuses to load as an unknown key.

## Performance

- Duration: about 12 minutes
- Tasks: 3 of 3
- Files: 7 created, 0 modified

## Task Commits

1. Task 1 (tracer): limits structures, strict loader, pure drift verdict and the guard: `2979864`
2. Task 2: injected-clock measurement, re-measure scheduling, -1021 hook: `e750757`
3. Task 3: README of the required keys and the source scan: `e148a32`

The measured range `9dc2cef..e148a32` holds 4 commits because the concurrent plan 18-06 committed `d6dd4ea` (its SUMMARY) on the same branch between Task 1 and Task 2; plan 18-07 made 3 task commits.

## What Was Built

- `src/adapters/binance_limits.py`: `CANONICAL_KEYS` (read-only, sections of 3, 4, 5 and 15 keys), the five dataclasses (every int field rejects bool, non-int and non-positive values; `ClientLimits` keeps zero for `sdk_retries` and `sdk_backoff_ms`; the three nullable fields accept None; `include_measurement_uncertainty` accepts only a bool), `parse_binance_limits` and `load_binance_limits`. The loader refuses a missing file (`LimitsFileMissing`), an unparseable file, an unknown section, a section that is not a table, a missing or unknown key (the retired single rate-limit key included), a float, a boolean for an int key, a string other than none, none for a non-nullable key, a negative or zero value, a missing provenance table, section or label, a PLACEHOLDER or unknown label, a label for an unknown key, and a behind limit above recvWindow. No consistency rule relates the three rate-limit values.
- `src/adapters/binance_clock.py`: `evaluate_clock_drift` (offset = floored midpoint minus server time, positive when the host is ahead; uncertainty = half the round trip rounded up, added to the bound only when configured; ValueError for a non-int reading or a backwards pair), `measure_clock_drift` (one clock read before and after exactly one `await server_time()`, exact integer millisecond conversion by timedelta floor division, failed verdict with the type name only on any failure, no retry, cancellation propagates), and `ClockDriftGuard` (`record`, `blocked_reason`, `entries_allowed`, `request_remeasure`, `needs_remeasure`, `refresh`, `note_clock_skew_error`). Neither module reads a clock or calls `float(`.
- `config/binance/README.md`: one line per key with meaning and unit, the file format, the none rule, the provenance rule and the loader name; no value. `config/binance/binance-limits-v1.toml` does not exist (plan 18-09 writes it).
- `tests/support/limits.py`: `TEST_ONLY_` constants (none equals a value of the user's record; the three rate-limit values are pairwise different), the `test_only_*` builders and `write_limits_toml(path, *, overrides, drop, extra)`.

## Verification

- `uv run pytest -m "not docker" tests/test_binance_limits.py tests/test_clock_drift.py tests/test_no_unratified_defaults.py -x`: 321 passed (259 in test_binance_limits.py, 25 in test_clock_drift.py, 37 in test_no_unratified_defaults.py).
- `uv run mypy src`: no issues in 192 source files.
- `uv run ruff check`: all checks passed. `uv run ruff format --check`: 568 files already formatted.
- `uv lock --check`: resolved, unchanged.
- `test ! -e config/binance/binance-limits-v1.toml`: true.
- The source scan ran over every `.py` file of `src/` and `scripts/` and found no numeric constant for any of the 30 guarded names; the allow-list is empty.

All commands were run with `UV_OFFLINE=1 uv run --frozen --extra dev`; no network, no `.env`, no database URL. The full suite was not run (only the plan's verify commands).

## Deviations from Plan

None in behavior. Interpretation choices made inside the plan's wording are listed under `decisions` in the frontmatter; the one with a visible effect is that a pending -1021 re-measure request makes the last in-limit verdict STALE until a fresh in-limit measurement is recorded (the plan's tests only required that entries stay blocked when they were already blocked; this also blocks them when they were allowed).

TDD note: in Task 1 the tests and the implementation were written in one step and run together (the red state was not observed separately); Tasks 2 and 3 were observed red first (24 failed for Task 2, 4 README tests failed for Task 3) before the implementation.

## Issues Encountered

- The CodeGraph index belongs to the main checkout, not this worktree, so the Phase 18 symbols (`ClientLimits`, `rate_limit_decision`) were read from the worktree files directly.
- The concurrent 18-06 executor committed on the same branch during this plan; no file overlapped.

## Known Stubs

None.

## Next Phase Readiness

Plan 18-09 can write `config/binance/binance-limits-v1.toml` in the documented format (four value sections plus `[provenance.<section>]` tables or dotted keys under `[provenance]`, the string `"none"` for the three nullable keys). Plans 18-10 to 18-17 can import the structures and `tests/support/limits.py` builders.

## Self-Check: PASSED

All 7 created files exist; commits 2979864, e750757 and e148a32 are in the history.
