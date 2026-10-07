---
phase: 14-backtest-causality-rewrite
fixed_at: 2026-10-07T00:00:00Z
review_path: .planning/phases/14-backtest-causality-rewrite/14-REVIEW-MARK-HOLES.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 14 (plan 14-17): Mark-Hole Coverage Notes - Code Review Fix Report

**Fixed at:** 2026-10-07
**Source review:** `.planning/phases/14-backtest-causality-rewrite/14-REVIEW-MARK-HOLES.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (WR-01..WR-05; no Critical; Info IN-01..IN-03 deliberately not touched)
- Fixed: 5
- Skipped: 0

**Where it ran:** `workflow.use_worktrees` is `false` in `.planning/config.json`, so edits and commits were made in the main checkout on `develop` (no worktree, no recovery sentinel). All gates below ran in the main checkout, so they are reproducible from it.

**Annotate-only guard-rails held.** Only `coverage_note` text and internal, never-recorded state (`note_entries`, `mark_settled_through_utc`) were touched. No event, leg, price, time, cost, `fallback_applied`, fallback count, intrabar coverage percent or `run_summary` value changed. `SIMULATOR_SEMANTICS_VERSION` stays `2.0.0`. Nothing under `params/`, `tests/fixtures/`, `docs/DECISIONS.md` or `docs/research/` was edited (checked with `git diff --stat` over the range), and no digest or golden was re-pinned or regenerated: every pinned test passed unchanged. `.planning/config.json`, `.planning/state.json`, `.gsd/` and `milestone.lock` were never staged.

## Fixed Issues

### WR-01: coverage_note grows without bound

**Status:** fixed: requires human verification (output-text logic)
**Files modified:** `src/backtest/lifecycle.py`, `tests/test_backtest_mark_hole_coverage.py`
**Commits:** RED `f7aa000`, fix `62db545`, test-expectation correction `3ae0b45`
**Applied fix:** The note is now rendered from a structured, internal tuple `PlanState.note_entries` (excluded from equality, never copied to a record; `coverage_note` is a pure function of it) by `_render_notes`. The first `MAX_LISTED_MARK_HOLE_SPANS = 20` hole spans are written out in time order; every further span is only counted in one closing piece, `mark_price_1m_missing_<K>_further_spans_not_listed; stop and targets not evaluated minute by minute for those minutes`. Bar-close fallback notes are never capped. **Cap value: N = 20** (an annotation-text constant, not a strategy parameter, not covered by the semantics version); worst case about 3.5 KB of hole text per position. Output is deterministic, window-cut independent (stepped hour windows equal one window) and prefix-invariant (the 20 spans listed after hour 11 equal the first 20 listed after hour 13). Hole counts up to 20 render byte-identically to before.
**TDD:** RED test committed first (3 tests failing: 60 holes bound and count, path independence plus prefix invariance, exactly-cap versus cap+1), then the fix. One test expectation was corrected after the fix (a hole is only noted once a later minute is walked, so 29 spans are known after hour 11, not 30); that was my test arithmetic, the code behaved as designed.

### WR-02: boundary arithmetic only partly proven by tests

**Status:** fixed (tests only; no source change)
**Files modified:** `tests/test_backtest_mark_hole_coverage.py`
**Commit:** `e587c50`
**Applied fix:** New tests pin (a) data end `10:59:59.999` with the last minute missing -> noted, and covered / `10:59:59.998` / early-completed minute -> no note (the `+1 ms` term); (b) a hole ending exactly at a `:59.999` data end is one trailing span; (c) a hole cut through its middle by a window end, parametrised over six cut points (before, first minute, middle, second half, last minute, just after), must give a state equal to the single-window run; (d) a closing-bar fallback followed by a trailing hole at END_OF_DATA notes only the trailing minutes.
**Honesty note:** these tests were green from the start against the correct code (they add coverage, not a behaviour change), so there is no RED commit for WR-02.
**Mutation checks (done locally, each reverted afterwards; `git status` clean for `src/`):**
- Drop the `+ timedelta(milliseconds=1)` term: the two `:59.999` data-end tests fail. (Before this fix the whole file passed under that mutation, as the reviewer derived.)
- Do not carry the settle marker between windows (`settled = None` at window start): all the window-cut tests except "just after the hole" fail, plus three older tests.
- Do not move the marker after a fallback: the fallback-plus-trailing-hole test fails, plus four others.

### WR-03: double note contradicts path independence

**Status:** fixed: requires human verification (note-content logic)
**Files modified:** `src/backtest/lifecycle.py`, `tests/test_backtest_mark_hole_coverage.py`
**Commits:** RED `a9e55a8`, fix `d129dc3`
**Applied fix:** This was possible without touching any non-note field, so it was not skipped. The closing-bar fallback now calls `_without_claimed_spans(entries, first_missing)` before adding its note: an earlier hole span that starts at or after `first_missing` is dropped, one that straddles it is cut back to the minutes before it, spans wholly before it and earlier fallback notes stay. The result equals what a single closing-bar window records (asserted by whole-state equality against the direct run). The test that pinned the double note was **replaced** (it documented the inconsistency); the SUMMARY claim "same notes however windows are cut" is now true for positions that stay open until the bar close. The docstrings and the BACKTEST_SPEC paragraph state the one remaining window-cut dependence, which is not a note matter: a position stopped out inside a mid-bar window never meets the fallback, so its stop resolves at that minute (existing engine decision D-33).
**TDD:** RED commit with two failing tests (mid-bar then closing bar; straddling the bar open) and one regression guard that was already green (a span wholly before the bar region is kept).
**Decision for the user:** the old plan-14-17 SUMMARY text and `deferred-items.md` still describe the double note as accepted behaviour; they were not edited (planning docs, out of scope), so they are now stale on that one point.

### WR-04: BACKTEST_SPEC paragraph misdescribes the fill-minute rule

**Status:** fixed
**Files modified:** `docs/backtest/BACKTEST_SPEC.md`
**Commit:** `7696ccd`
**Applied fix:** The paragraph now says the fill minute counts as walked when its mark price exists (stop checked, targets not) and as missing when it does not; the misleading "minute before the fill minute" wording is gone. It also states that a hole inside a strategy bar goes to the fallback while minutes before the bar's region are noted separately, and (for WR-01 and WR-03, in the same paragraph rather than a separate commit) the 20-span cap and the single-note rule.

### WR-05: digest consequence not stated where the identity is defined

**Status:** fixed (documentation and comments only)
**Files modified:** `docs/backtest/BACKTEST_SPEC.md`, `src/backtest/semantics.py`, `src/backtest/lifecycle.py`
**Commit:** `712cced`
**Applied fix:** Section 4 now ends with the digest consequence (hole-free input: nothing changes; input with a hole inside a position's life: only `coverage_note` text moves, and with it the trade payload bytes and derived hashes; the version stays `2.0.0` because nothing priced or booked changes). Section 10 gets a pointer naming that as the one documented exception to "a record from the old simulator can never be compared with a new one". `semantics.py` gets the same statement as a comment next to `SIMULATOR_SEMANTICS_VERSION` (no value change) and the `lifecycle.py` module docstring the same paragraph. The version was not bumped, as instructed.

## Skipped Issues

None.

## Not in scope (left as is)

IN-01 (test D marker reset), IN-02 (`finalize_at_data_end` on a non-advanced state), IN-03 (trailing wording does not say the END_OF_DATA price is stale).

## Verification

Run in the main checkout, one pytest process per file (Windows), all green with no digest, golden or fixture touched:
`test_backtest_mark_hole_coverage` (27 tests), `test_backtest_exits` (36), `test_backtest_simulator` (63), `test_backtest_expiry_clock` (10), `test_backtest_determinism` (16), `test_backtest_engine_strategy` (11), `test_backtest_report` (27), `test_backtest_records` (24), `test_backtest_experiment` (14), `test_phase6_fixture_scenarios` (48), `test_phase6_fixture_geometry` (47), `test_cost_parity` (9), `test_paper_parity` (5), `test_kill_gate_docs` (12), `test_decision_alignment_bookkeeping` (46).
Also: `ruff check src tests` clean, `ruff format --check` clean (429 files), `mypy src` clean (149 files), `python scripts/verify_decision_alignment.py all` -> `ALL_PASS`. Pytest was run through `uv run` (the bare `python` has no project dependencies). Docker/PostgreSQL tests were not run (CI only). No backtest, census, research or smoke run; Phase 16 not run.

## Commits (oldest first)

| Commit | Content |
|--------|---------|
| `f7aa000` | test: WR-01 RED |
| `62db545` | fix: WR-01 span cap (structured entries) |
| `3ae0b45` | test: WR-01 expectation correction |
| `a9e55a8` | test: WR-03 RED (replaces the double-note test) |
| `d129dc3` | fix: WR-03 fallback claims earlier hole spans |
| `e587c50` | test: WR-02 boundary and window-cut tests |
| `7696ccd` | docs: WR-04 spec paragraph |
| `712cced` | docs: WR-05 digest consequence |

Design note for review: `PlanState` gained one internal field, `note_entries` (default empty, `compare=False`), so every hole-free state and every existing state-equality test is unchanged. `coverage_note` on a `PlanState` must now only be written through the lifecycle code (nothing else in `src/` or `tests/` sets it on a `PlanState`).

---

_Fixed: 2026-10-07_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
