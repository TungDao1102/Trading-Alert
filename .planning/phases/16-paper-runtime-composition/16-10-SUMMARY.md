---
phase: 16-paper-runtime-composition
plan: 10
subsystem: paper-runtime / decision parity
tags: [paper-loop, evaluate-closed-bar, bar-buffers, decision-surface, parity, determinism]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-02 single registry root and per-call gate in run_paper_tick; 16-05 and 16-08 runtime vocabulary (not imported here)"
  - phase: 14-backtest-engine
    provides: "STRATEGY_WINDOW_BARS and CONTEXT_WINDOW_BARS engine windows and the bisect_right context rule"
provides:
  - "BarContext, BarOutcome, evaluate_closed_bar in src/paper/loop.py: the per-bar chain as a typed function; run_paper_tick output byte-identical"
  - "src/paper/bars.py: BarBuffers (engine windows, dedup by open time, bounded memory) and group_by_close (close time ascending, 4h before 1h, arrival-order independent)"
  - "src/paper/surface.py: DecisionSurfaceRecord, decision_surface, surface_digest (non-semantic observer, tolerance-zero replay, covers strategy-stage NO_TRADE and feed-gate bars)"
  - "tests/test_domain_no_float.py scans src/paper/*.py and src/research/*.py by glob with an explicit, justified exclusion set"
affects: [16-22 runtime composition, 16-shadow fill driver, D-20 parity check, later Phase 16 modules under src/paper and src/research]

actuals:
  tokens: 13600
  tasks: 3
  commits: 6
plan_head_before: e28354fa3085f5024d503c2b578cf54db15117e0
plan_head_after: 5ef1cd813a2b7f419adecd9d2a26ca465f01842c
commits: 6

tech-stack:
  added: []
  patterns:
    - "Typed per-bar outcome extracted from a dict-returning loop; the loop projects the typed value back into the unchanged dicts"
    - "Observer over shared functions (evaluate_closed_bar, compute_features) instead of a second engine; the simulator is never imported"
    - "Float scan by glob over whole packages with an explicit exclusion dict that needs a reason per entry"

key-files:
  created:
    - src/paper/bars.py
    - src/paper/surface.py
    - tests/test_paper_decision_surface.py
    - tests/test_paper_bars.py
  modified:
    - src/paper/loop.py
    - tests/test_domain_no_float.py

key-decisions:
  - "evaluate_closed_bar takes the setup and context candle lists from the caller (no window cut inside run_paper_tick); the runtime and decision_surface cut the engine windows through BarBuffers, so the tick keeps its whole-series behaviour and every pinned digest is unchanged"
  - "BarBuffers keep at most window plus one bar per (symbol, interval); a bar older than everything a full buffer holds is refused, so a late re-delivery cannot re-enter"
  - "decision_surface accepts a BarContext or a per-bar callable so the constraint snapshot can be stamped at each close (the same ttl-0 convention the parity replay and the engine use)"
  - "A duplicate open time with identical content yields a DUPLICATE_BAR feed-gate record; with different content it raises ValueError (fail closed) so arrival order can never pick the winner"
  - "src/paper/shadow.py is excluded from the float scan with a stated reason: its float use is tenacity retry-wait seconds, not a price, quantity or risk value"

patterns-established:
  - "Parity evidence is a digest over canonical JSON records (surface_digest), with a window-drift negative control that must change at least one feature digest"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "A typed per-bar function returns the closed candle, stage, reason, Signal, TradePlan and risk verdict, and run_paper_tick projects it into exactly today's dicts with every pinned paper digest unchanged"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_risk_passed_bar_returns_signal_plan_and_sized_verdict"
        status: pass
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_risk_passed_bar_matches_the_tick_record_ids"
        status: pass
      - kind: unit
        ref: "tests/test_paper_start_gate.py, tests/test_paper_parity.py, tests/test_paper_reviewfix_pins.py, tests/test_paper_feed_gates.py, tests/test_paper_closed_candle.py (unedited)"
        status: pass
    human_judgment: false
  - id: D2
    description: "decision_surface yields one record per closed 1h bar through shared src/core and src/risk functions without importing the Phase 14 simulator; strategy-stage NO_TRADE and signal-less bars are covered"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_strategy_stage_no_trade_and_signal_less_bars_have_records"
        status: pass
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_surface_agrees_with_the_paper_tick_on_every_1h_bar"
        status: pass
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_surface_module_never_imports_the_simulator"
        status: pass
    human_judgment: false
  - id: D3
    description: "Replaying the same recorded closed bars gives identical decision-surface digests, tolerance zero, independent of arrival order, and a window-drift negative control changes a feature digest"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_replay_and_arrival_order_give_the_same_digest"
        status: pass
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_window_drift_changes_a_feature_digest"
        status: pass
      - kind: unit
        ref: "tests/test_paper_decision_surface.py#test_permutations_of_a_small_bar_set_give_one_digest"
        status: pass
    human_judgment: false
  - id: D4
    description: "Runtime bar buffers use exactly the engine windows 1000 and 300 with the bisect_right context rule and order 4h before 1h at shared closes"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_bars.py#test_windows_equal_the_engine_rule_on_a_1500_bar_history"
        status: pass
      - kind: unit
        ref: "tests/test_paper_bars.py#test_group_by_close_orders_by_close_and_puts_4h_before_1h_for_any_permutation"
        status: pass
      - kind: unit
        ref: "tests/test_paper_bars.py#test_buffers_never_exceed_the_window_plus_one_bar_per_interval"
        status: pass
    human_judgment: false
  - id: D5
    description: "The float guard scans every src/paper and src/research module by glob, so later Phase 16 modules are covered automatically"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_domain_no_float.py#test_every_paper_and_research_module_is_scanned_by_the_float_guard"
        status: pass
      - kind: unit
        ref: "tests/test_domain_no_float.py#test_domain_mapper_registry_path_has_no_float_call"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 10: Typed bar outcome, bar buffers and decision surface Summary

**`evaluate_closed_bar` now gives the runtime a typed signal, plan and sized verdict per closed bar while `run_paper_tick` stays byte-identical; `BarBuffers` cut the engine's 1000/300 windows; and `decision_surface` replays recorded bars to a tolerance-zero digest without touching the Phase 14 simulator.**

## Performance

- **Duration:** 10 min (2026-10-09T05:20:09Z to about 05:30Z)
- **Tasks:** 3 (Task 1 tracer, Tasks 2 and 3 auto, all TDD)
- **Files modified:** 6 (4 created, 2 modified)
- **Commits:** 6 (three RED/GREEN pairs)

## Accomplishments

- Tracer (D-02): the per-bar body of `run_paper_tick` (snapshot, `evaluate`, `plan`, `evaluate_risk`) moved verbatim into `evaluate_closed_bar(context, closed_candle, setup_candles, context_candles) -> BarOutcome`. `BarContext` and `BarOutcome` are frozen dataclasses; `BarOutcome` carries the closed candle, stage (`strategy`, `planner`, `risk`, `risk_passed`), reason code, Signal, TradePlan, verdict and regime. `run_paper_tick` builds the same `closed_setup` and `closed_context` lists as before, calls the function and projects the outcome into exactly the old `signals`, `trade_plans` and `no_trade_records` dicts, in the same order and with the same key order. The gate, freshness and warm-up gates, CONTEXT_BAR and DUPLICATE_BAR handling were not touched.
- `src/paper/bars.py`: `BarBuffers` per (symbol, interval) with `add` (dedup by open time), `setup_window`, `context_window` and `size`; windows and the `bisect_right` rule equal `_Engine._setup_window` and `_context_window`, constants imported from `src.backtest.semantics`. `group_by_close` orders by close time and puts 4h before 1h, for any input permutation. No float, no import of the paper vocabulary.
- `src/paper/surface.py`: `decision_surface(bars, *, context, buffers_factory)` returns one `DecisionSurfaceRecord` per closed 1h bar (feature digest, signal id or reason, plan hash, risk reason, sized quantity, regime), context records for 4h bars, feed-gate records for warm-up and duplicates; `surface_digest` hashes the records through `sha256_hex`. Re-running and a shuffled arrival order give the same digest; a narrower window changes feature digests (negative control). On the parity fixture the surface agrees with the unchanged tick on stage, reason and signal id for all 250 bars.
- `tests/test_domain_no_float.py`: the paper entries of `SCANNED_FILES` became globs over `src/paper/*.py` and `src/research/*.py` (plus the explicit `src/adapters/paper_ws.py`), with an exclusion dict that needs a reason per entry.

## RED Evidence

- **Task 1** (`c876e0b`): collection failed with `ImportError: cannot import name 'BarContext' from 'src.paper.loop'`. After `9c922c6`: the new file plus the five byte-identity suites pass.
- **Task 2** (`cc771c8`): `ModuleNotFoundError: No module named 'src.paper.bars'`. After `8a27ec4`: 14 tests pass.
- **Task 3** (`9b3d8b3`): `ModuleNotFoundError: No module named 'src.paper.surface'`, and the new float-guard test referenced an undefined `FLOAT_SCAN_EXCLUDED`. After `5ef1cd8` all pass.

## Task Commits

1. **Task 1 (tracer): typed evaluate_closed_bar** - `c876e0b` (test, RED), `9c922c6` (feat, GREEN)
2. **Task 2: pure bar buffers** - `cc771c8` (test, RED), `8a27ec4` (feat, GREEN)
3. **Task 3: decision_surface and no-float glob** - `9b3d8b3` (test, RED), `5ef1cd8` (feat, GREEN)

**Plan metadata:** committed separately (docs: complete plan).

## Verification

- Tracer gate (`HUMAN_VERIFY_MODE` end-of-phase, automated-only verify, auto mode off): the Task 1 verify command passed, so the tracer was treated as verified end-to-end and expansion continued.
- Task 1 verify: `tests/test_paper_decision_surface.py` plus the five byte-identity suites pass.
- Task 3 verify: `tests/test_paper_decision_surface.py tests/test_paper_bars.py tests/test_domain_no_float.py tests/test_analytics_edge_guards.py tests/test_paper_parity.py` pass; `mypy src` clean (159 files).
- Also green, one process: `test_paper_start_gate`, `test_paper_reviewfix_pins`, `test_paper_feed_gates`, `test_paper_closed_candle`, `test_paper_freeze`, `test_paper_freeze_allowlist_mode`, `test_paper_attribution`, `test_paper_vocabulary`, `test_paper_notify`, `test_paper_resync`, `test_paper_shadow_messages`, `test_paper_shadow_buttons`, `test_backtest_purity`: 237 passed.
- `ruff check` (src/paper, tests) and `ruff format --check` (455 files) clean.
- `git diff e28354f -- src/backtest` is empty. `git diff e28354f -- tests/` shows only the three files this plan owns (two new, `test_domain_no_float.py` modified); no expected digest literal in any test file changed.
- The full `pytest -m "not docker"` suite was not run in one process (10 minute tool limit); targeted suites above replace it.

## Decisions Made

See key-decisions in the frontmatter. In short: the extracted function takes the candle lists from the caller; buffers are capped at window plus one; the surface takes a per-bar context callable; conflicting duplicate bars fail closed; `shadow.py` is excluded from the float scan with a reason.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] A current src/paper module fails the float scan once the scan is a glob**
- **Found during:** Task 3
- **Issue:** `src/paper/shadow.py` (plan 16-04 / 16-11 output) uses `float` and `0.0` in its tenacity wait functions (`_remaining_budget`, `_wait`); converting the paper entries to a glob made the whole-tree float test fail.
- **Fix:** Per the plan's own instruction (explicit exclusion with a one-line reason instead of weakening the scan), `FLOAT_SCAN_EXCLUDED` lists `src/paper/shadow.py` with the reason "tenacity retry-wait arithmetic in seconds; no price, quantity or risk value is computed with it". Two tests keep the set honest (every entry has a reason and names a real file; every other paper/research module is scanned). `src/paper/shadow.py` itself was not edited.
- **Files modified:** tests/test_domain_no_float.py
- **Committed in:** 5ef1cd8

**2. [Rule 1 - Bug in own test] Conflicting-duplicate fixture built an invalid candle**
- **Found during:** Task 3
- **Issue:** The first version of the test changed `close` above `high`, which `Candle.__post_init__` refuses before the surface code runs.
- **Fix:** The clash changes `volume` instead.
- **Files modified:** tests/test_paper_decision_surface.py
- **Committed in:** 5ef1cd8

---

**Total deviations:** 2 auto-fixed (1 Rule 3, 1 Rule 1). **Impact:** no production behaviour changed beyond the plan; the exclusion is the plan's stated fallback.

## Issues Encountered

- A heredoc with nested triple quotes failed to parse in the shell; the test additions were written through the Write tool instead. No effect on the repo.
- Working-tree files are CRLF (`core.autocrlf=true`); new files are written LF like other new files and git normalises them. Edits to existing CRLF files kept CRLF.

## Known Stubs

None.

## Threat Flags

None. T-16-24 (extraction tampering) is mitigated: the five pinned-digest suites pass with no expected digest edited. T-16-25 (parity evidence) is mitigated by `surface_digest` over canonical JSON, the replay and permutation tests and the window-drift negative control. T-16-SC accepted: no package installed, `uv.lock` unchanged.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The runtime composition (plan 16-22) can call `evaluate_closed_bar` with `BarBuffers` windows and `group_by_close` ordering, and use `decision_surface` as the D-20 parity check against a recorded run.
- Note for the runtime: `evaluate_closed_bar` expects the caller to have applied the feed, warm-up and duplicate gates; `decision_surface` shows the same gate order (warm-up via `check_feature_validity` on the windowed series).
- `src/paper/shadow.py` should either keep its float use confined to tenacity wait values or the exclusion should be revisited when that module changes.

---
*Phase: 16-paper-runtime-composition*
*Completed: 2026-10-09*

## Self-Check: PASSED

`src/paper/bars.py`, `src/paper/surface.py`, `src/paper/loop.py`, `tests/test_paper_decision_surface.py`, `tests/test_paper_bars.py`, `tests/test_domain_no_float.py` and this SUMMARY exist; commits c876e0b, 9c922c6, cc771c8, 8a27ec4, 9b3d8b3, 5ef1cd8 found in git log; `git rev-list --count e28354f..HEAD` was 6 at SUMMARY time; all plan verify commands, ruff and mypy clean; `src/backtest` diff empty.
