---
phase: 20-reconcile-safe-mode-hardening
plan: 16
subsystem: reconcile
tags: [stale-feed, user-data-stream, auth-failure, safe-mode, fail-closed, tdd]

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "20-01 stale_feed.* limits, 20-04 compare vocabulary (STREAM_SINK_FAILURE, STREAM_TASK_DIED), 20-12 ReconcileLoop and classify"
provides:
  - "src.reconcile.feed_freshness: FeedReading, FeedVerdict, StaleFeedLimits, assess_feeds (pure)"
  - "src.reconcile.loop: FeedSource and StreamDivergenceSource Protocols, ReconcileLoop(feeds=, stream=), AUTH_FAILURE classification of failed truth reads, RECONCILE_STREAM_QUERY journal row, TickReport.stale_symbols / user_data_silent"
  - "src.reconcile.classify: ALERT_AUTH_FAILURE; STREAM_TASK_DIED now alerts STALE_DATA"
  - "tests/support/reconcile_rig.py: build_rig, FakeFeedSource, FakeStreamSource, QueryingAdapter"
affects: [20-19, 20-20, 20-22, 20-24, 20-25]

tech-stack:
  added: []
  patterns:
    - "pre-steps (feeds, stream) run before the truth reads and are folded into every report by _with_pre, so a failed read cannot hide them"
    - "stream kinds and the supervisor halt matched by string value, pinned to the adapter by a parity test (src.reconcile imports no adapter)"
    - "classification of a failed read from adapter.error_facts + classify(CallKind.QUERY), never message text"

key-files:
  created:
    - src/reconcile/feed_freshness.py
    - tests/test_feed_freshness.py
    - tests/test_reconcile_stream_divergences.py
    - tests/support/reconcile_rig.py
  modified:
    - src/reconcile/loop.py
    - src/reconcile/classify.py
    - tests/test_reconcile_classify.py
    - tests/test_reconcile_loop.py

key-decisions:
  - "A mark time ahead of now counts as fresh in assess_feeds: it is clock skew, staleness means older than, and the ratified drift bound lives in pre-placement; no skew bound is invented here."
  - "Any supervisor halt reason (TASK_DIED, KEEPALIVE_FAILURES, a rate-limit ban, ...) and a stream source that raises are read as STREAM_TASK_DIED: while halted the stream is not trusted; recovery (halted_reason None) adds nothing and never exits SAFE_MODE."
  - "The feed and stream steps come after the gate and restore checks: a gate restriction or a pending restore reads nothing, not the feeds and not the stream queue (drain() is not called, items stay queued)."
  - "A failed exchange read journals category AUTH_OR_SIGNATURE, another category, or UNCLASSIFIED (adapter has no error_facts, or classification raised); only AUTH_OR_SIGNATURE is AUTH_FAILURE."

requirements-addressed: [EXEC-02, OPS-05, OPS-01]

duration: about 70min
completed: 2026-10-21
status: complete
actuals:
  tokens: 21528   # chars/4 over `git diff 87c82ce0 HEAD -- src tests` (86114 chars), taken before this SUMMARY commit
  tasks: 3
  commits: 2      # MEASURED: git rev-list --count 87c82ce0..HEAD, taken before this SUMMARY commit
plan_head_before: 87c82ce04e3e2abc25d49846b820920d2386d868
plan_head_after: 52af2fc94c6d03dade823f1dbe47b7c4f70744ab
---

# Phase 20 Plan 16: Feed health, stream health and auth failure Summary

**The reconcile tick now judges the mark-price and user-data feeds (stale means SAFE_MODE STALE_FEED plus a STALE_DATA alert), acts on the user-data stream's SINK_FAILURE and on any supervisor halt (STREAM_SINK_FAILURE / STREAM_TASK_DIED divergences, with a targeted REST query of every id a stream item names), and turns a truth read that fails with AUTH_OR_SIGNATURE into SAFE_MODE AUTH_FAILURE plus an AUTH_FAILURE alert.**

Evidence label: executed unit tests with fakes. The feed and stream sources are injected doubles and are NOT wired to a running supervisor, router or mark-price reader (Phase 24); nothing was run against Binance or Telegram; nothing is `[DEMO]`. EXEC-02, OPS-05 and OPS-01 are not marked complete (`requirements-addressed` only). Live placement stays disabled. No owner checkpoint is in this plan.

Base `87c82ce0` (develop), branch `p20-16`, final code commit `52af2fc9`. `commits: 2` is the measured `git rev-list --count 87c82ce0..HEAD` at SUMMARY write.

## What was built

- `src/reconcile/feed_freshness.py` (pure, standard library only): `assess_feeds(reading, *, symbols, now_utc, limits) -> FeedVerdict`. Missing time = stale; symbol absent from the reading = stale; stale means strictly older than the limit (compared as `timedelta`, so a sub-millisecond excess is stale); a naive datetime is a ValueError; a `NOT_CONFIGURED` (None) threshold is a ValueError that names the key, never a default. The thresholds are read only from `stale_feed_max_mark_price_age_ms` and `stale_feed_max_user_data_silence_ms` (a `StaleFeedLimits` Protocol, so the module imports nothing from `src.execution`). No clock read, no float.
- `ReconcileLoop` gained `feeds=` and `stream=` (both optional, default None = not judged). Tick order: gate, restore check, feeds, stream, UNKNOWN-entry step, three truth reads, local read, compare, act. The feed and stream outcome is a `_Pre` folded into the report and the RECONCILE_TICK row whatever the outcome (compared or read failed).
  - Feeds: tracked symbols = plans not FLAT / ENTRY_ENDED_NO_FILL. A stale verdict enters SAFE_MODE `STALE_FEED` and alerts `STALE_DATA` once per stale symbol (reason `MARK_PRICE_STALE`) and once for the user-data feed (subject `USER_DATA`, reason `USER_DATA_SILENT`). A source that raises, or a reading `assess_feeds` refuses, counts as stale for every tracked symbol and for user data. Reconciliation still runs in the same tick. A later fresh reading never calls `exit_safe_mode`.
  - Stream: `SINK_FAILURE` items become `STREAM_SINK_FAILURE` divergences (SAFE_MODE STREAM_SINK_FAILURE, alert DIVERGENCE); any halt reason becomes `STREAM_TASK_DIED` (SAFE_MODE USER_DATA_STREAM_HALTED, alert STALE_DATA; the reason text is the halt reason only when it is plain `[A-Z][A-Z0-9_]*` project text, else `UNKNOWN`); a `drain()` or `halted_reason()` that raises is the same halt (fail closed). Every other kind (STREAM_ANOMALY, STREAM_FILL_TOTAL_MISMATCH, UNKNOWN_STREAM_ORDER, UNKNOWN_STREAM_ALGO, STREAM_ALGO_TERMINAL_FAILED) gets only the targeted queries. Each distinct id is queried once per tick, before the truth reads: `query_order_by_client(symbol, id)` for an order id (skipped, journaled `NO_SYMBOL`, when the item has no symbol), `query_algo_order_by_client(id)` for an algo id. A failed query is journaled `RECONCILE_ACTION_FAILED` with `stream_query` and the exception class name. The mapping table is in the `_check_stream` docstring; the policy itself stays in `classify.POLICY_BY_KIND`.
  - Auth: a failed truth read is classified by `adapter.error_facts(exc)` and `classify(facts, CallKind.QUERY)`. `AUTH_OR_SIGNATURE` enters SAFE_MODE `AUTH_FAILURE` and alerts `AUTH_FAILURE` (subject `SYSTEM`, reason `AUTH_OR_SIGNATURE`). Everything else stays `API_DEGRADATION`. `RECONCILE_READ_FAILED` now also carries `category` (the category name, or `UNCLASSIFIED`); error text never appears.
- `src/reconcile/classify.py`: `ALERT_AUTH_FAILURE`; `STREAM_TASK_DIED` now alerts `STALE_DATA` (the plan's interface note said it already did; the 20-12 table had DIVERGENCE).

## Task commits

| Task | Commit | Type | Description |
|---|---|---|---|
| 1 (tracer) | `9d55e7d8` | feat | feed_freshness.py, feed step in the loop, tests/test_feed_freshness.py, tests/support/reconcile_rig.py |
| 2 + 3 | `52af2fc9` | feat | stream intake, targeted queries, auth classification, classify changes, tests/test_reconcile_stream_divergences.py, two updated pins |

Tasks 2 and 3 share one commit: their code is interleaved in `loop.py` (`_read_failed`, `_Pre`, the Protocol) and was written and verified together. This departs from "one commit per task".

## TDD Gate Compliance

`gsd_run check tdd-red-evidence` does not parse pytest output and was not run. RED evidence, stated honestly:
- Task 1: RED was a collection failure (`ModuleNotFoundError: No module named 'src.reconcile.feed_freshness'`), not an assertion failure on behavior. The tests were not committed separately (the rig imports the new module).
- Tasks 2 and 3: first run was a collection `ImportError` (`RECONCILE_STREAM_QUERY`). For a behavioral RED I temporarily appended that one constant to `loop.py` and re-ran: 29 of the 35 tests then in the file failed on missing behavior (the 6 that passed are import-level, error-path and no-op checks that hold without the feature); the alert-vocabulary test was added afterwards, then the file was restored byte-for-byte (`diff` against the backup) and the implementation applied. One test of mine had a wrong expectation (a `sorted()` of ids where `'w' < 'x'`), found on the first GREEN run and fixed in the test, not the code.
- Tracer feedback gate (Task 1 has no `gate="blocking-human"`): the Task 1 verify plus the 20-12 loop and classify files were re-run after the tracer commit and passed before Task 2.

## Deviations from Plan

**1. [Rule 3 - Blocking, pins] Two existing test assertions changed.**
- `tests/test_reconcile_classify.py` `EXPECTED_POLICY["STREAM_TASK_DIED"]`: alert `DIVERGENCE` -> `STALE_DATA`, as the plan's Task 2 behavior requires ("alert STALE_DATA").
- `tests/test_reconcile_loop.py::test_a_failed_truth_read_enters_api_degradation_and_compares_nothing`: the pinned `RECONCILE_READ_FAILED` payload gained `"category": "UNCLASSIFIED"` (its adapter double has no `error_facts`). Behavior of the test (API_DEGRADATION, no alert, no compare, no message text) is unchanged.

**2. [Plan text vs code] `ReconcileAdapter` Protocol extended** with `query_order_by_client`, `query_algo_order_by_client` and `error_facts` (the real adapter has all three). The 20-12 `FakeReconcileAdapter` lacks the first and third; it still works because the loop treats a missing `error_facts` as an unclassified failure. I did NOT edit `tests/support/reconcile_doubles.py`; the new `QueryingAdapter` in `tests/support/reconcile_rig.py` subclasses it.

**3. [Files beyond the plan's list]** New `tests/support/reconcile_rig.py` (shared builder and doubles for the two new test files; the plan lists only the two test files). `tests/test_reconcile_classify.py` and `tests/test_reconcile_loop.py` (pins above).

**4. [Plan text vs code] `feed_freshness.py` does not import `src.execution`.** The plan signature takes `limits`; `ExecutionLimits` lives in `src.execution`, and the plan forbids imports outside stdlib and `src.domain`, so `limits` is typed by the `StaleFeedLimits` Protocol.

**5. [Process]** `uv sync --frozen --extra dev` was needed to build the worktree venv (documented env setup, lockfile unchanged). The `codegraph explore` first step was skipped: the worktree has no `.codegraph/` index.

## Findings for the orchestrator and later plans

1. **20-12 finding 1 (compare Pass 2 flags ENTRY_WITHOUT_PROTECTIVE for a resting entry with no fill): this plan does not meet it.** Every test here uses a PROTECTED plan whose exchange state agrees, or a foreign order; no AWAITING_FILL plan is used and compare.py is untouched. It will still bite a composed loop: a stale feed plus a pending GTD entry gives STALE_FEED and ENTRY_WITHOUT_PROTECTIVE together.
2. **Pre-existing lint failure on the base:** `uv run ruff check` fails on `src/execution/protection.py:72` (E501, 141 > 100) at develop `87c82ce0`, a file this plan does not touch. Not fixed (scope boundary). Every file this plan changed is clean.
3. **User-data silence is judged unconditionally** (also with no tracked plan), as the plan's truth states. Binance sends user-data events only on account activity, so the Phase 24 `FeedSource` must report a liveness time (the supervisor's `LivenessSnapshot` has last event, ping and pong times; take the newest), not the last account event, or a quiet account will sit in SAFE_MODE. Same for the feed time of a mark price: it must be the stream's receive time.
4. **No cap on targeted queries per tick.** Ids are deduplicated within a tick, but `drain()` can hand over many distinct ids and each costs one REST call. No ratified limit key exists and none was invented. The REST gate still applies to each call; a cap needs an owner-set key (T-06 style).
5. **The persisted SAFE_MODE reason is the last one entered in the tick** (20-12 behavior). STALE_FEED and the stream reasons are entered first, so a divergence found by the compare later in the same tick replaces them as the persisted reason; every reason stays in the journal row `safe_mode_reasons` and in the report.
6. **A gate-restricted tick judges no feed.** The plan puts the feed step after the gate check, so during a 418/429 pause a stale mark price is not noticed until the pause ends (pre-placement still checks the mark age itself at placement). Moving the feed step before the gate check is a small change if the owner prefers.
7. **Documentation still to do (plan 20-24):** GLOSSARY 9.4 rows for `AUTH_FAILURE`, `USER_DATA_STREAM_HALTED`, `STREAM_SINK_FAILURE` (and the 20-12 list); `STALE_FEED` already has a row.
8. **Plan 20-22:** the real `JournalFirstAlertSink` must accept the events `STALE_DATA` and `AUTH_FAILURE` (both are in `src.ops.alerts.ALERT_EVENTS`; a test pins that) with the subjects `USER_DATA` and `SYSTEM`.

## Verification (only this plan's tests, tests of touched files, and the gate files)

- `uv run pytest -m "not docker"` over tests/test_feed_freshness.py (31), tests/test_reconcile_stream_divergences.py (36), tests/test_reconcile_loop.py, tests/test_reconcile_classify.py, tests/test_reconcile.py, tests/test_reconcile_compare_v2.py, tests/test_alerts.py, tests/test_protection_supervision.py, tests/test_cancel_verification.py, tests/test_manual_controls.py, tests/test_risk_first_spill.py, tests/test_intent_recovery_unknown_entry.py, tests/test_intent_recovery_pg.py, tests/test_agents_md.py: 559 passed, 4 warnings (python-telegram-bot deprecation), 0 skipped, with `TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` set from the environment.
- `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_persistence_exit_evidence_pg.py`: 88 passed, 0 skipped.
- `uv run mypy src`: no issues in 230 source files. `uv run ruff format --check`: 709 files already formatted. `uv run ruff check`: one error, the pre-existing E501 in `src/execution/protection.py` (finding 2); none in this plan's files.
- `uv lock --check` resolves; `git diff --exit-code -- pyproject.toml uv.lock` exits 0 (T-20-SC). `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- Plan acceptance: `grep -nE "^[[:space:]]*(from|import) src[.]adapters" src/reconcile/loop.py src/reconcile/classify.py` prints nothing; the AST guards for feed_freshness (stdlib only, no clock, no float, no `src.paper`) and the 20-12 guards (no placement, cancel, exit or row writer in loop / classify) pass; `exit_safe_mode` is never called in any loop test (autouse fixture of 20-12 and the raising `SpyingSafeMode`).
- The full suite was not run (orchestrator).

## Acceptance criteria

| Criterion | Result |
|---|---|
| test_feed_freshness.py asserts no forbidden imports, wall clock or float in feed_freshness.py | yes (`test_feed_freshness_is_pure_stdlib_and_domain_only`) |
| assess_feeds reads its thresholds only from the stale_feed_* fields; src.paper not imported | yes (two threshold tests, `test_the_reconcile_package_does_not_import_the_paper_coverage_module`) |
| a named test per Task 2 behavior bullet; no `src.adapters` import line in loop / classify | yes |
| `test_auth_failure_on_read_alerts_and_enters_safe_mode` passes | yes |
| ruff clean on this plan's files | yes (repo-wide check has the one pre-existing error above) |

## Known Stubs

None. `feeds` and `stream` are optional by design; binding them to the supervisor, the router and the mark-price reader is Phase 24.

## Threat Flags

None new. T-20-40 is mitigated by `assess_feeds` every tick (missing = stale, SAFE_MODE STALE_FEED); T-20-41 by the AUTH_OR_SIGNATURE classification, SAFE_MODE AUTH_FAILURE and the alert, with only class and category names in payloads (a poisoned-message test shows `apikey=XYZ` never reaches a journal row or an alert); T-20-SC by the unchanged dependency files.

## Self-Check: PASSED

- FOUND: src/reconcile/feed_freshness.py, src/reconcile/loop.py, src/reconcile/classify.py, tests/test_feed_freshness.py, tests/test_reconcile_stream_divergences.py, tests/support/reconcile_rig.py
- FOUND commits: 9d55e7d8, 52af2fc9
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, config/binance/, params/, pyproject.toml, uv.lock, `.gsd/`, `.planning/config.json`, `.planning/state.json`, `.planning/milestone.lock`
