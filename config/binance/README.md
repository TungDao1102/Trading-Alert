# Binance client and user-data stream limits

This directory holds the ratified safety thresholds of the Binance client, the signed calls,
the clock-drift guard and the user-data stream (Phase 18, D-14, O-18-01). The values file
`binance-limits-v1.toml` is written only by plan 18-09, copied from the user's decision record
`.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md` (plan 18-02).
**This README lists the required keys and what they mean. It carries no value, and the code
carries no default for any of them.** `tests/test_no_unratified_defaults.py` scans `src/` and
`scripts/` so that no key name below is ever given a number in code.

The loader is `load_binance_limits(path)` in `src/adapters/binance_limits.py`. It returns a
`BinanceLimits` (`client`, `signed`, `drift`, `stream`) and refuses to load, with
`LimitsNotRatified` (or `LimitsFileMissing` when the file does not exist), in every other case:
a missing file, a file that is not valid TOML, a missing key, an unknown key, an unknown
section, a value of the wrong kind, or a missing or invalid provenance label. Refusal messages
name keys or sections only, never a value or a path.

## File format

- Exactly the sections `[client]`, `[signed_calls]`, `[drift]`, `[stream]` and `[provenance]`.
- Exactly the 27 keys below, each written once; nothing else is accepted.
- Every value is a TOML integer that is not a boolean, strictly positive except
  `client.sdk_retries` and `client.sdk_backoff_ms`, which may be zero. A TOML float, a boolean
  in place of an integer, a negative number or a string is refused.
- `drift.include_measurement_uncertainty` is a TOML boolean (`true` or `false`).
- The three nullable keys (`drift.periodic_remeasure_interval_seconds`,
  `stream.project_rotation_interval_seconds`, `stream.max_liveness_age_seconds`) also accept the
  word none, written as the TOML string `"none"`; it means "not configured" (see each key). No
  other key accepts it.
- `drift.behind_limit_ms` must not exceed `signed_calls.recv_window_ms`: Binance rejects a
  request older than recvWindow, so a larger behind limit could never block before Binance does.
- The former single key `signed_calls.rate_limit_no_retry_after_wait_seconds` is retired (the
  user split it into a 418 key and a 429 key on 2026-10-16) and is refused as an unknown key.

## Provenance table

Every key carries a provenance label in `[provenance]`, addressed as `section.key`, for example
`[provenance.client]` followed by `rest_timeout_ms = "DECISION"`, or under `[provenance]` the
dotted form `client.rest_timeout_ms = "DECISION"` (both parse to the same table). The allowed
labels are STRUCTURAL, COST_GUARD, DECISION and EXPERIMENT. A PLACEHOLDER label refuses to
load, and so does an absent, unknown or misspelled label or a label for an unknown key.

## Required keys

One key per line, so the checks of plans 18-07 and 18-09 can parse the list.

### `[client]` (`ClientLimits`, `src/adapters/binance_client.py`)

- `client.rest_timeout_ms` - the one REST timeout the SDK applies to connect and read together, for every call kind (milliseconds).
- `client.sdk_retries` - the SDK's own retry count inside its request loop; zero leaves the project's retry as the only retry owner (count, zero allowed).
- `client.sdk_backoff_ms` - the SDK's delay unit between its own retries, the n-th retry waiting n times this value (milliseconds, zero allowed).

### `[signed_calls]` (`SignedCallPolicy` and `RateLimitPolicy`)

- `signed_calls.recv_window_ms` - the recvWindow sent explicitly on every signed call (milliseconds).
- `signed_calls.rate_limit_418_no_retry_after_wait_seconds` - the REST ban after an HTTP 418 whose Retry-After is absent or unparseable; the failing request is not retried; field `RateLimitPolicy.no_retry_after_wait_418_seconds` (seconds).
- `signed_calls.rate_limit_429_no_retry_after_wait_seconds` - the pause of every REST call of the process after an HTTP 429 whose Retry-After is absent or unparseable; no call is retried because of a 429; field `RateLimitPolicy.no_retry_after_wait_429_seconds` (seconds).
- `signed_calls.rate_limit_retry_after_cap_seconds` - the upper cap on a valid Retry-After and on both fallbacks; field `RateLimitPolicy.retry_after_cap_seconds` (seconds).

The three `RateLimitPolicy` field names are the keyword names of `rate_limit_decision`
(`src/domain/exchange_errors.py`). No rule relates the three values: each is the user's.

### `[drift]` (`DriftLimits`, `ClockDriftGuard` in `src/adapters/binance_clock.py`)

- `drift.ahead_limit_ms` - the largest host-ahead offset (host midpoint minus Binance server time) accepted before new entries are blocked (milliseconds).
- `drift.behind_limit_ms` - the largest host-behind offset accepted before new entries are blocked; not above `signed_calls.recv_window_ms` (milliseconds).
- `drift.include_measurement_uncertainty` - whether half the measurement round trip is added to the offset before it is compared with each limit (true or false).
- `drift.max_measurement_age_seconds` - the oldest good drift verdict that still allows new entries; an older one reports STALE (seconds).
- `drift.periodic_remeasure_interval_seconds` - the period of a scheduled drift re-measure; the word none means re-measure only on request (a -1021 or no verdict yet), the age rule still applying (seconds or none).

### `[stream]` (`StreamLimits`)

- `stream.keepalive_interval_seconds` - the period of the listenKey keepalive (seconds).
- `stream.keepalive_failure_tolerance` - consecutive keepalive failures tolerated before the stream becomes UNKNOWN and is re-keyed (count).
- `stream.project_rotation_interval_seconds` - a project-owned rotation of the private connection this long after a successful connect; the word none leaves rotation to the SDK (seconds or none).
- `stream.reconnect_max_attempts` - the supervisor's bounded rebuild attempts after a drop (count).
- `stream.reconnect_max_delay_seconds` - the total time bound of the supervisor rebuild retry (seconds).
- `stream.reconnect_wait_multiplier_seconds` - the backoff multiplier of the supervisor rebuild (seconds).
- `stream.reconnect_wait_max_seconds` - the cap on any single backoff wait of the supervisor rebuild (seconds).
- `stream.sdk_reconnect_delay_ms` - the SDK's own reconnect wait of the stream configuration (milliseconds).
- `stream.sdk_reconnect_attempts` - the SDK's own reconnect attempt count, within the SDK's allowed range (count).
- `stream.snapshot_deadline_seconds` - the time limit of one REST snapshot attempt after a stream gap (seconds).
- `stream.snapshot_max_attempts` - the bounded snapshot attempts after a gap (count).
- `stream.snapshot_wait_multiplier_seconds` - the backoff multiplier between snapshot attempts (seconds).
- `stream.snapshot_wait_max_seconds` - the cap on any single wait between snapshot attempts (seconds).
- `stream.max_liveness_age_seconds` - the age of the newest liveness signal (ping, pong, keepalive or entry into LIVE) beyond which the stream is stale; the word none defers the verdict to Phase 20 (seconds or none).
- `stream.event_queue_max` - the bound of the queue between the SDK message callback and the consumer; an overflow sets UNKNOWN (messages).
