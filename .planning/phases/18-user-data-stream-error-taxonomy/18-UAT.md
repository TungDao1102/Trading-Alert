---
status: partial
phase: 18-user-data-stream-error-taxonomy
source: 18-01-SUMMARY.md to 18-26-SUMMARY.md, 18-VERIFICATION.md, 18-REVIEW-FIX.md
started: 2026-10-19T00:00:00Z
updated: 2026-10-19T00:00:00Z
---

## Current Test

[testing paused - 4 items outstanding: 3 blocked (owner or Demo credentials), 1 known issue]

## How this UAT was run

Run by Claude on the owner's request, offline on the owner's machine at HEAD c689f2f: no network, no credentials, no order sent. Each result below is something Claude executed and read, not a copy of a SUMMARY. Anything that needs Binance Demo, a real key or the owner's own act is `blocked`, never `pass`.

## Tests

### 1. Dry-run smoke on DEMO walks the whole stream lifecycle
expected: `scripts/user_data_smoke.py --environment DEMO` (dry run, the default) exits 0 and writes one DRYRUN evidence file; all 13 steps PASSED (preflight, stream_start, keepalive, order_place, order_new_event, order_cancel, order_canceled_event, forced_drop, stop_and_delete_then_put, log_scan, evidence_write and the rest).
result: pass
observed: exit 0, 1 evidence file `user-data-smoke-DRYRUN-...json`, 13 of 13 steps PASSED, mode dry-run, environment DEMO.

### 2. LIVE cannot be selected
expected: `--environment LIVE` is refused before anything runs.
result: pass
observed: exit 2, `refused (UsageError): argument --environment: invalid choice: 'LIVE' (choose from 'DEMO', 'TESTNET')`.

### 3. `--execute` is refused without an interactive terminal
expected: no run against Binance, no evidence directory created.
result: pass
observed: exit 2, `refused (ConfirmationRefused): --execute needs an interactive terminal`, evidence directory not created.

### 4. Errors are classified by code and call kind
expected: -2013 on a query and -2011 on a cancel are ORDER_ABSENT; -2011 on a placement is not; -1021 is CLOCK_SKEW; HTTP 429 is RATE_LIMITED.
result: pass
observed: ORDER_ABSENT, ORDER_ABSENT, UNKNOWN_EXCHANGE_ERROR (placement), CLOCK_SKEW, RATE_LIMITED.

### 5. An unexplained answer fails closed and message text never decides
expected: an unlisted or missing code on a 400 is UNKNOWN_EXCHANGE_ERROR; only that category is SAFE_MODE eligible; a non-SDK exception whose text says "-2013" is not ORDER_ABSENT.
result: pass
observed: unlisted code and missing code both UNKNOWN_EXCHANGE_ERROR; the SAFE_MODE-eligible set is exactly [UNKNOWN_EXCHANGE_ERROR]; the text-only exception gave UNKNOWN_EXCHANGE_ERROR.

### 6. Retry rules
expected: a status-unknown failure is retryable for query/cancel/time/listenKey only, never for a placement; 418 and 429 are never retried.
result: pass
observed: STATUS_UNKNOWN placement False, query True; RATE_LIMITED False; IP_BANNED False.

### 7. Secrets are redacted from text
expected: a signature, a registered API key and a registered listenKey in a URL path or query never survive `scrub`.
result: pass
observed: `signature=[REDACTED]`, the registered key `[REDACTED]`, and after `register_runtime_secret` the listenKey is `[REDACTED]` in both the `/private/ws/<key>` path and `?listenKey=`. An unregistered key in a path is not recognised; the listenKey port registers the key when it obtains it (`binance_userdata.py:262` and `:270`).

### 8. The ratified Binance limits file loads
expected: `config/binance/binance-limits-v1.toml` loads into `BinanceLimits` with the stream limits (keepalive, reconnect, queue, liveness, snapshot deadline).
result: pass
observed: loads; the stream section exposes event_queue_max, keepalive_interval_seconds, keepalive_failure_tolerance, max_liveness_age_seconds, reconnect_*, sdk_reconnect_*, snapshot_deadline_seconds and more.

### 9. The whole suite is green, including the PostgreSQL tests
expected: `pytest -m "not docker"` passes against the local PostgreSQL 17.11.
result: pass
observed: exit 0, no failure or error; the 14 PostgreSQL files (about 295 tests) ran with none skipped; the only skips are platform ones (symlinks, POSIX modes, shellcheck absent).

### 10. Review fix holds (CR-01 position amount)
expected: a position row without `positionAmt` raises instead of reading as flat; covered by a committed test.
result: pass
observed: commit `ef90072`, suite green after it (test 9). Claude did not re-derive it separately in this UAT.

### 11. Live Demo smoke with real user-data events
expected: `--execute` on Binance Demo with the owner's Demo keys: listenKey, subscription, NEW and CANCELED order events arrive, account flat afterwards.
result: blocked
blocked_by: third-party
reason: needs the owner's `BINANCE_DEMO_API_KEY` and `BINANCE_DEMO_API_SECRET`, network, an interactive terminal and the typed phrase. Existing evidence: the Demo run of 2026-10-16 (`user-data-smoke-EVIDENCE-20261016T140446Z.json`, `sdk_route_delivery` PASS). It has not been rerun after the 26 review-fix commits, and CR-01 and CR-02 touched code on that path.

### 12. No-withdrawal key and IP-allowlist attestation (OPS-02)
expected: the owner records that the Demo and live keys have no withdrawal right and are IP-restricted.
result: blocked
blocked_by: third-party
reason: a human act, not code; stays a Phase 24 to 26 item (`18-TRACEABILITY.md`).

### 13. D055 execution-model decision
expected: a new DECISIONS row, or a deliberate deferral, after reading `decisions/18-DRAFT-D055-evidence-for-user.md`.
result: blocked
blocked_by: prior-phase
reason: open by design; the owner decides. The direction is noted, not decided, in `19-NOTES.md`.

### 14. A dead stream is noticed promptly
expected: if the subscription is rejected or the connection dies silently, the stream leaves LIVE soon after (no long silent window).
result: issue
reported: "src/CR-02 remainder from the deep review: a rejected SUBSCRIBE is only logged, error events on an open socket are ignored by design, stream_is_stale is never called in production and max_liveness_age_seconds is ratified as none, so the silent window lasts until the next keepalive failure (up to 30 minutes)."
severity: major

## Summary

total: 14
passed: 10
issues: 1
pending: 0
skipped: 0
blocked: 3

## Gaps

- truth: "A dead or unsubscribed user-data stream leaves LIVE soon after, so the system does not trust a stale view"
  status: failed
  reason: "Deep review src/CR-02 (remainder): the stream can be LIVE with no working subscription for up to one keepalive interval; no liveness verdict is enforced because max_liveness_age_seconds is ratified as none."
  severity: major
  test: 14
  root_cause: "Design choice recorded as a ratified value (max_liveness_age_seconds = none) plus an SDK SUBSCRIBE that does not acknowledge; stream_is_stale exists and is tested but no production caller enforces it. Partly mitigated by fix f41cb79 (rebuild proves the stored listenKey with a keepalive)."
  artifacts:
    - path: "src/adapters/binance_userdata_supervisor.py"
      issue: "stream_is_stale unused by production code; error on an open connection ignored"
    - path: "src/adapters/binance_userdata.py"
      issue: "SUBSCRIBE fire-and-forget; a rejection is only logged"
    - path: "config/binance/binance-limits-v1.toml"
      issue: "max_liveness_age_seconds = none (ratified DECISION value)"
  missing:
    - "Owner decision: ratify a liveness limit and say where the verdict is enforced"
    - "Confirm the SDK SUBSCRIBE acknowledgement (list_subscribe) and treat a rejected subscription as not LIVE"
  debug_session: ".planning/phases/18-user-data-stream-error-taxonomy/18-REVIEW.md (src/CR-02) and 19-NOTES.md"
