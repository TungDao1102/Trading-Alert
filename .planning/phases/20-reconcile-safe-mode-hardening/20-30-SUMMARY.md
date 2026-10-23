---
phase: 20-reconcile-safe-mode-hardening
plan: 30
subsystem: reconcile
tags: [reconcile, stale-feed, rest-gate, restart-recovery, user-data-supervisor, gap-closure]
requires: [20-16, 20-27, 20-28, 20-29]
provides:
  - "assess_feeds(max_clock_skew=): a mark or user-data time ahead of now_utc by more than the skew is stale; no skew means no allowance (WR-B6)"
  - "feed_freshness.clock_skew_from_drift(drift): the larger of the two ratified drift limits (the margin placement already uses)"
  - "ReconcileLoop(feed_clock_skew=): passes the skew on; a non-timedelta or negative value is refused (ValueError)"
  - "RestRateLimitGate.restore(): a persisted ban/pause deadline beyond recorded_at_utc plus the largest policy wait is untrusted (GATE_STATE_UNKNOWN, REST_GATE_RECOVERY_REQUIRED once, nothing saved) (WR-C3)"
  - "UserDataSupervisor._await_rest_allowed: one sleep on a timed pause is at most StreamLimits.reconnect_wait_max_seconds, the gate re-checked after each slice (WR-C3)"
affects: [Phase 24 composition]
gap_closure: true
requirements-addressed: []
status: complete
commits: 3
plan_head_before: 27d68d1a5a7b00e9ad9d6e54683d7b8574da7e85
plan_head_after: 67859346e4d80ef0970b03fc1282a5648ec10920
actuals:
  tokens: 9408   # chars/4 over `git diff 27d68d1a 67859346` (37631 chars)
  tasks: 2
  commits: 3     # MEASURED: git rev-list --count 27d68d1a..67859346 (1 plan + 2 task commits; this summary is committed after)
key-files:
  created:
    - tests/test_feed_freshness_skew.py
    - tests/test_gate_restore_bounds.py
    - tests/test_userdata_supervisor_pause_slices.py
  modified:
    - src/reconcile/feed_freshness.py
    - src/reconcile/loop.py
    - src/adapters/binance_ratelimit_gate.py
    - src/adapters/binance_userdata_supervisor.py
    - tests/test_feed_freshness.py
    - tests/test_userdata_supervisor.py
    - tests/support/reconcile_rig.py
key-decisions:
  - "WR-B6 reuses the ratified [drift] limits of config/binance/binance-limits-v1.toml (the larger of ahead_limit_ms and behind_limit_ms, 1000 ms in the committed file), the same margin the placement path uses as gtd_clock_margin. No stale_feed.* key was added, so no NOT_CONFIGURED key, no GUARDED_NAMES change."
  - "With no skew handed in, any feed time ahead of now_utc is stale (zero allowance). A forgotten composition therefore fails closed instead of open."
  - "WR-C3 adds zero extra allowance to the restore bound: a genuine record never exceeds recorded_at_utc plus the largest wait, because recorded_at_utc is read at save time and a deadline is set at or before it."
  - "The supervisor slice uses the existing StreamLimits.reconnect_wait_max_seconds; no number was added."
---

# Phase 20 Plan 30: reconcile gap closure (WR-B6, WR-C3) Summary

Two review findings of `20-REVIEW.md` are fixed, each re-checked against the code first. Nothing is marked complete (`requirements-addressed: []`). Evidence is executed tests with fakes and a local PostgreSQL run of the exit-evidence test; nothing is [DEMO]. Plans 20-27, 20-28 and 20-29 were read and not redone.

## Verification of each finding against the source

| Finding | Verdict | How it was checked |
|---|---|---|
| WR-B6 | Confirmed | Old `assess_feeds` run on a mark price and a user-data time in year 2100 returned `FeedVerdict(stale_symbols=(), user_data_silent=False)` (`/tmp/p20/30/b6_old.py`, output `b6_old.txt`). The module docstring and `tests/test_feed_freshness.py` even pinned "ahead of now counts as fresh". |
| WR-C3 | Confirmed | RED tests below: old `restore()` adopted a ban/pause 1 microsecond past the largest wait and a year-9999 deadline (`RESTORED_DURABLE`); old `_await_rest_allowed` slept `[999]` in one call for a 999 s pause. |

No finding was rejected. One part of a suggested fix was changed: the review proposes `min(remaining, 60)`; the code uses the existing `reconnect_wait_max_seconds` (60 in the committed `config/binance/binance-limits-v1.toml`, 17 in the TEST_ONLY limits) so the slice is a ratified number and not a literal.

## What was built

- **WR-B6 (`src/reconcile/feed_freshness.py`, `src/reconcile/loop.py`).** `assess_feeds(..., max_clock_skew: timedelta | None = None)`. A feed time with `seen - now_utc > skew` is stale (mark price per symbol and user data alike); the age rule and the missing-time rule are unchanged. `None` means zero allowance, so any time ahead of `now_utc` is stale. A skew that is neither `None` nor a non-negative `timedelta` (a bool, an int, a negative value) is a `ValueError`. `clock_skew_from_drift(drift)` returns `timedelta(ms=max(ahead_limit_ms, behind_limit_ms))` over a small Protocol (the module keeps its stdlib-only imports). `ReconcileLoop(feed_clock_skew=None)` validates the value at construction and hands it to `assess_feeds`; the loop's existing fail-closed branch turns a stale verdict into SAFE_MODE `STALE_FEED` plus a `STALE_DATA` alert.
- **Which ratified bound.** The review says to reuse the ratified pre-placement drift bound. That bound is not an execution-limits key: it is the `[drift]` section of the sha256-pinned `config/binance/binance-limits-v1.toml`, passed into placement as `gtd_clock_margin` (the demo rehearsal builds it as the larger of `ahead_limit_ms` and `behind_limit_ms`, test `tests/test_demo_rehearsal_flow.py`). The same derivation is reused, so a time the placement path accepts as not-future is not judged stale here. The direction that matters for a future feed time is Binance ahead of the host (`behind_limit_ms`); taking the larger of the two follows the existing precedent and was not tightened on purpose.
- **WR-C3 (`src/adapters/binance_ratelimit_gate.py`).** `restore()` now also treats a record as untrusted when `ban_until_utc` or `pause_until_utc` is later than `recorded_at_utc + max(retry_after_cap_seconds, no_retry_after_wait_418_seconds, no_retry_after_wait_429_seconds)`, with zero extra allowance. It takes the same path as a missing or unreadable record: `_unknown_state` set, restore done, `REST_GATE_RECOVERY_REQUIRED` once, status `RESTORED_UNKNOWN_STATE`, `restriction()` reports `GATE_STATE_UNKNOWN`, nothing is saved. A deadline exactly at the bound, and a deadline the gate wrote itself (including a Retry-After far above the cap, which is capped at record time), stay trusted; tests pin both.
- **WR-C3 (`src/adapters/binance_userdata_supervisor.py`).** `_await_rest_allowed` sleeps `min(remaining, StreamLimits.reconnect_wait_max_seconds)` and asks the gate again after every slice. A short pause is still slept in one piece; the pause still ends exactly when the gate opens and nothing is sent in between.

## RED evidence (honest)

- **WR-B6.** `tests/test_feed_freshness_skew.py` before the fix: 19 of 19 failed, `/tmp/p20/30/red-b6.txt`. Most of them fail on the missing `max_clock_skew` / `feed_clock_skew` keyword or the missing helper (`TypeError`), which proves the new interface, not the behavior. The behavior is shown by the old-code probe above (year 2100 judged fresh). Because the tests were written before the interface existed, "equal to now is fresh" and "age rule unchanged" were not seen failing for the right reason; they pass on the new code and pin behavior that held before.
- **WR-C3 gate.** `tests/test_gate_restore_bounds.py` before the fix: 7 of 12 failed on the behavior (untrusted deadline adopted as `RESTORED_DURABLE`), `/tmp/p20/30/red-c3-gate.txt`. The other 5 passed already by design (boundary at exactly the bound, the test-values sanity check, the gate's own round trip): they pin what must not regress.
- **WR-C3 supervisor.** `tests/test_userdata_supervisor_pause_slices.py` before the fix: the long-pause test failed with `assert [999] == [17]`, `/tmp/p20/30/red-c3-sup.txt`; the short-pause test passed already (pin).
- The TDD commits are not split into test-then-implementation commits; the tests and the implementation of each task are committed together after the RED runs above.

## Verification actually run

- The plan's new tests and the touched files' tests, plus every test file that mentions `binance_ratelimit_gate`, `binance_userdata_supervisor`, `feed_freshness`, `ReconcileLoop`, `build_rig`, `RestRateLimitGate` or `UserDataSupervisor` (63 files), plus `tests/test_execution_limits.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_persistence_exit_evidence_pg.py tests/test_agents_md.py`, `-m "not docker" -n 4`, `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set: **2616 passed, 1 skipped** (a symlink test that cannot run on Windows, `tests/test_user_data_smoke_dry_run.py:383`), 0 failed. Output in `/tmp/p20/30/verify.txt` (first run) and the terminal.
- `uv run mypy src`: no issues (235 files). `uv run ruff check`: clean. `uv run ruff format --check`: 736 files already formatted. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- The full suite was not run (orchestrator's job). `uv sync --frozen --extra dev` was needed once to build the worktree's `.venv`; `pyproject.toml` and `uv.lock` are untouched.

## Pins changed

- `tests/test_feed_freshness.py`: the test that pinned "a mark time ahead of now is clock skew and counts as fresh" now pins the opposite (stale unless a bound allows it); the full cases live in `tests/test_feed_freshness_skew.py`.
- `tests/test_userdata_supervisor.py`: two tests asserted `WAIT_429 in rig.vt.sleeps` and `CAP in rig.vt.sleeps` (one whole-pause sleep). They now assert the slice (`reconnect_wait_max_seconds in sleeps`) and that the whole value is not slept at once.
- `tests/support/reconcile_rig.py`: `build_rig(feed_clock_skew=)`.
- No limits key changed, so the `GUARDED_NAMES` counts (52), the key table and the TOML/README are unchanged.

## Deviations from Plan

**1. [Interpretation] Branch name.** The executor started on `worktree-agent-a8bc2243d3248f084`, which was based on an older commit (239 commits behind `develop`); the coordinator re-created the work in `.claude/worktrees/p20-30` on branch `p20-30` at `27d68d1a`. The per-commit agent-branch allow-list in the executor protocol does not match `p20-30`; commits were made there on the coordinator's explicit instruction. The branch is not a protected one.

**2. [Interpretation] The WR-B6 bound is passed in, not read from a config key.** The loop has no handle on the Binance limits file, and `src/reconcile` must not import `src.adapters`. The skew is therefore a constructor argument defaulting to `None` (zero allowance, fail closed), with `clock_skew_from_drift` as the one derivation. No composition builds `ReconcileLoop` yet (none in `src/` or `scripts/`), so nothing else needed to change.

**3. [Limit stated] The supervisor's total wait is not capped.** Slicing bounds one sleep, not the sum. The sum equals the pause, which the policy bounds (at most `retry_after_cap_seconds`) and which `restore()` no longer lets exceed that. A separate overall cap would need a number that no existing `StreamLimits` key provides (the policy cap itself is the legal maximum), so none was added.

**4. [Docs] `docs/operations/RUNBOOK.md` and `docs/GLOSSARY.md` were not edited.** RUNBOOK line 130 describes the stale-feed thresholds without mentioning the skew; it needs one sentence in a later docs plan ("a feed time ahead of now by more than the ratified drift counts as stale"). The REST-gate recovery text there does not yet say that an implausible persisted deadline gives `GATE_STATE_UNKNOWN` and the operator clears it with the existing `clear --force` path.

## Findings for later plans

1. **Composition (Phase 24).** Build `ReconcileLoop(..., feed_clock_skew=clock_skew_from_drift(binance_limits.drift))` whenever `feeds=` is given. Without it every feed time ahead of the tick time is stale (safe, but a mark price stamped a few hundred milliseconds ahead by Binance would put the loop in SAFE_MODE). Add this to the Phase 24 composition note of `20-DEFERRED.md`.
2. **Which clock stamps the user-data time.** If the `FeedSource` stamps the user-data liveness with the local receive time, the skew only guards a local clock jump; if it stamps Binance event time, the bound is the Binance-ahead case. Phase 24 should say which in the source's docstring.
3. **Restore bound and a failed save.** The bound is measured from `recorded_at_utc`. If a save fails and later saves succeed, the file keeps the older record, which is still internally consistent. A restart after the clock stepped backwards by more than the policy wait between two saves would read a record whose `recorded_at_utc` is earlier than its deadline's origin; that gives the fail-closed unknown state and the operator clears it. Not expected in normal operation.
4. **Operator note.** A host clock jump forward that makes the file's `recorded_at_utc` run ahead is harmless for this check (the bound only grows); a jump backward is the case that now needs `clear --force`.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema; the new restriction reuses the existing `GATE_STATE_UNKNOWN` reason and the existing alert event, and no log line carries a value.

## Self-Check: PASSED

- Files present: `20-30-PLAN.md`, this summary, the three new test files.
- Commits reachable from HEAD: fe2844ee, b2207e01, 67859346.
