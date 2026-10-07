---
phase: 15-strategy-geometry-correction
verified: 2026-10-07T02:54:22Z
status: passed
score: 4/4 must-haves verified
covered_files:
  - .planning/phases/15-strategy-geometry-correction/15-01-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-01-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-02-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-02-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-03-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-03-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-04-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-04-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-05-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-05-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-06-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-06-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-07-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-07-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-08-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-08-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-09-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-09-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-10-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-10-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-11-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-11-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-12-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-12-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-13-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-13-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-14-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-14-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-15-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-15-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-16-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-16-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-17-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-17-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-18-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-18-SUMMARY.md
  - docs/research/GEOMETRY_AUDIT.md
  - params/breakout-retest/baseline-v6.toml
  - params/range-mr/baseline-v6.toml
  - params/trend-pullback/baseline-no-trade-v4.toml
  - params/trend-pullback/baseline-simple-trend-v4.toml
  - params/trend-pullback/baseline-v6.toml
  - src/core/pivots.py
  - src/core/planner.py
  - src/core/strategy.py
  - src/domain/rationale.py
  - src/domain/registry.py
  - src/paper/freeze.py
  - src/paper/loop.py
covered_digest: "v2:sha256:63409e6f2d12b6ed1bfc00a6ffa161d34b812b326180f4e5c7cbd38c2b0ac069"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 4/4
  gaps_closed:
    - "Human item 2 (-v4 override basis): user reply recorded verbatim in D054 (15-UAT.md test 10, plan 15-16)"
    - "Human item 3 (PLACEHOLDER sets / unwired gate, review IN-01): gate wired into run_paper_tick with an empty exact-hash allowlist by user decision (15-UAT.md test 11, checkpoint 15-17-01, plans 15-17 and 15-18)"
    - "Human item 1 (TP1 in far half of entry zone): user decision 'hoãn' recorded (15-UAT.md test 9, ROADMAP Backlog 999.1); current rule kept for now"
  gaps_remaining: []
  regressions: []
coincidental_reliance_items:
  - truth: "Criterion 3 enforcement: a set without rationale or with PLACEHOLDER keys cannot start a paper stream (run_paper_tick gate)"
    reason: undeclared-precondition
    harden: "The rationale/allowlist verdict is formed from the file under src.paper.freeze.REGISTRY_ROOT while the loop runs the set loaded under src.domain.registry.REGISTRY_ROOT. Both names bind the same Path object in production, and the loop's hash-equality check catches any [parameters] divergence, but nothing enforces that the two roots are equal; a file differing only in [rationale] tables under a rebound root would be judged on the other file (open Info IN-05 of 15-REVIEW-PAPER-GATE.md). Resolve the root at call time or pass the loaded path into pin_stream_epoch."
---

# Phase 15: Strategy Geometry Correction Verification Report

**Phase Goal:** Each family's implemented geometry matches its family sheet and is economically sane before any research run is trusted.
**Verified:** 2026-10-07T02:54:22Z
**Status:** passed
**Re-verification:** Yes. This report replaces the earlier one.

**Previous report (2026-10-06):** status human_needed, score 4/4. All four ROADMAP criteria were met in the code. Three decisions were left to the user: (1) TP1 in the far half of the entry zone, (2) the basis of the three -v4 override values, (3) accepting PLACEHOLDER-grade sets while the refusal gate had no production caller (review IN-01). Since then, gap-closure plans 15-16, 15-17 and 15-18 ran, and review fixes WR-01..WR-05 of the paper-gate review landed. This re-verification checks every new claim against the code and git, and does a regression check on the geometry code.

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Trend-pullback: SL outside the entry zone with a minimum ATR distance. Swings use confirmed pivots only, excluding the evaluated bar, so a setup cannot fire on a new 20-bar low (F-301) | VERIFIED | Regression check: `git diff cb8e0d6..HEAD` (cb8e0d6 = previous verification commit) shows no change under `src/core`, `src/domain/registry.py`, `src/risk`, `src/backtest`, `params`, `tests/fixtures` or `docs/research`. The full analysis from the previous report still applies (`pivot_at` candidates `t <= i - right`; `_pivot_geometry` stop beyond the outer zone edge; `_geometry_rejection` runs once per plan after quantization and before the RR gate). Re-run here, one process per file: test_core_pivots 17, test_core_strategy_geometry 7, test_planner_geometry 88, test_geometry_property 25, test_core_planner 17, test_prefix_invariance 3, test_no_lookahead 4. All passed. |
| 2 | Implemented geometries of all three families match the sheets' Stage baselines, or a DECISIONS entry records the deviation (F-113) | VERIFIED | GEOMETRY_AUDIT.md and the family sheets are unchanged since the previous verification. D054 item (a) still lists 5 MATCH, 8 FIX and 7 DEVIATION, each deviation with a reason. Re-run: test_geometry_audit_doc 20, test_core_strategy_breakout_retest 30, test_core_strategy_range_mr 36, test_phase6_fixture_geometry 119. All passed. |
| 3 | New versioned parameter sets record a rationale for every value; no fixture seed values are used (F-909) | VERIFIED | Rationale: test_rationale 34, test_registry 167, test_registry_gate 7, test_decision_alignment_params 58, and `python -m scripts.decision_alignment.params` PA-01..PA-08 all ok. "No fixture seed values" is defined by 15-CONTEXT D-16: no value may be inherited *silently*. A value with no basis must be marked PLACEHOLDER, and a PLACEHOLDER set cannot be frozen for paper. Some new sets do keep Phase 3 seed numbers (4-6 rationale entries per set say "Phase 3 seed value ... no empirical basis yet"), but each one is labelled PLACEHOLDER. The paper refusal of D-16 is now enforced at the real paper entry point. A live `pin_stream_epoch` sweep over all 25 committed sets refused 25, accepted 0, with 0 other errors. The five Phase 15 sets were refused for "PLACEHOLDER keys"; the 20 older sets were refused as "missing rationale tables and not in the approved allowlist". `PAPER_START_ALLOWLIST == ()`. `run_paper_tick` (src/paper/loop.py:338-363) runs `require_bool_flag`, `load_parameter_set`, the version check, `pin_stream_epoch` and the hash-equality check before any `_parse_account_state`, `build_cost_model` or `_parse_candle` (lines 368-375) and before the feed loop. The -v4 overrides are labelled as comparison reference points in D054 (see Decisions below). |
| 4 | A research re-run under protocol v2.0.0 is ready to start on the Phase-14 engine; the run itself is out of scope | VERIFIED | The readiness record (GEOMETRY_AUDIT.md "Re-run readiness", D054 item (h)) is unchanged. The machine-checkable parts were re-run: test_geometry_census 30, test_backtest_determinism 16, test_backtest_simulator 63, test_paper_parity 5, test_cost_parity 9. All passed. Not re-executed here: the real-data smoke runs and the census on BTCUSDT (UAT test 8, skipped; data-dependent, minutes of runtime). Their digests are the ones recorded in 15-15-SUMMARY.md and D054 (h). Per criterion 4, the research re-run itself is outside Phase 15 and was not started. |

**Score:** 4/4 truths verified (0 present but behavior-unverified)

### User Decisions on the Previous Report's Human Items (recorded, not decided by the verifier)

| # | Item | Recorded user decision (verbatim) | Where recorded | Verifier's check |
|---|------|-----------------------------------|----------------|------------------|
| 1 | TP1 on the profit side of the entry reference but inside the far half of the entry zone | "hoãn" (keep the current behaviour and defer) | 15-UAT.md test 9: `result: skipped`, `reason: "Deferred follow-up: hoãn" (user chose to keep current behavior and defer, after Claude's recommendation; the minimum-RR gate at the zone mid still applies)`. Deferred Follow-Ups: "hoãn — revisit whether to reject a TP1 inside the far half of the entry zone after the research re-run (D054 item g)". ROADMAP.md line 1082-1088, Phase 999.1 (BACKLOG). | This is a recorded decision to keep the current rule for now and revisit after the research re-run. It is **not** approval of a money-affecting tightening, and none was made: `_geometry_rejection` is unchanged since cb8e0d6 and still only requires TP1 strictly on the profit side of `entry_ref`. No ROADMAP criterion requires the tightening. Note: D054 item (g) still says "left for a user decision" and does not mention the deferral. The deferral lives in 15-UAT.md and ROADMAP 999.1 only (Info, see Anti-Patterns). |
| 2 | Basis of the three -v4 override values | "Là mốc đối chứng, ghi rõ" (they are comparison reference points, write it down clearly) | docs/DECISIONS.md D054 item (d) (commit 641da99): "User confirmation of what these three values are (2026-10-07, 15-UAT.md test 10, user reply verbatim: "Là mốc đối chứng, ghi rõ" ...) ... are comparison reference points for the RESEARCH_PROTOCOL Baselines comparison ..., not evidence-backed parameters; no data, backtest, research run or experiment supports them, they were not tuned". 15-UAT.md test 10. | D054 text read directly. The files are hash-locked and keep basis DECISION with ref D054 (baseline-no-trade-v4 `minimum_rr = 100`; baseline-simple-trend-v4 `zone_tolerance_atr = 1.0`, `minimum_rr = 0.5`, all read from the files). `git diff 3df767a..HEAD -- params tests/fixtures` is empty. test_kill_gate_docs (12, includes `test_d054_v4_overrides_are_comparison_reference_points`) passes. |
| 3 | PLACEHOLDER-grade sets and the unwired refusal gate (IN-01) | "Nối ngay trong Phase 15" (wire it now, in Phase 15). Checkpoint 15-17-01 Reply 1: "B — chỉ cho phép các tập tham số được chỉ định đích danh và gắn với hash của từng tập. ..."; Reply 2: "đồng ý cả hai, sửa plan 15-17 và chạy lại checker" | 15-UAT.md test 11; 15-17-SUMMARY.md "Decided-by: user (verbatim replies 2026-10-07)"; D054 item (i) (commit 549329b) | Verified in code and by a live run, see truth 3 and the spot-checks below. The allowlist is empty, so no committed set can start a paper stream today. That is the decided safe state. Phase 16 needs a fully rationalized set with no PLACEHOLDER key, or a new user checkpoint that adds an exact-hash entry. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/core/pivots.py`, `planner.py`, `strategy.py` | Corrected geometry | VERIFIED | Unchanged since the previous verification; tests re-run green |
| `src/domain/rationale.py` | Rationale check | VERIFIED | WR-05 added `check_rationale_text` and `placeholder_keys_text`; the path-based functions now delegate to them, one read each |
| `src/paper/freeze.py` | `PaperAllowlistEntry`, empty `PAPER_START_ALLOWLIST`, `require_bool_flag`, `_read_registry_file` (segment check + single read), `_require_rationalized` / `_require_allowlisted` | VERIFIED | Lines 312-447 and 484-573 read. Bypass only on `allow_unrationalized is True` (line 536) |
| `src/paper/loop.py` | Gate at the top of `run_paper_tick` | VERIFIED (WIRED) | Lines 338-363: the gate runs before any other `case_input` parse |
| `tests/test_paper_start_gate.py` | Gate, allowlist branch and AST guard tests | VERIFIED | 70 tests pass (16 from 15-17, the rest from WR-01..WR-05) |
| `docs/DECISIONS.md` D054 items (d), (i) | -v4 label; paper-start gate record | VERIFIED | Text read; doc tests pass |
| `15-REVIEW-DISPOSITION.md` | IN-01 fixed | VERIFIED | `IN-01 | info | fixed`, open 5 (IN-02..IN-06) |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `run_paper_tick` | `pin_stream_epoch` | loop.py:352, after load and version check, before line 365 onward | WIRED (production caller now exists; IN-01 closed) |
| `pin_stream_epoch` | `_require_rationalized` | freeze.py:536-543, skipped only when the flag `is True` | WIRED |
| `_require_rationalized` | `_require_allowlisted` / `check_rationale_text` + `placeholder_keys_text` | branches on a top-level `rationale` key (tomllib) | WIRED |
| `_require_allowlisted` | `PAPER_START_ALLOWLIST` | module attribute read at call time | WIRED |
| `run_paper_tick` | hash equality | loop.py:358-363, `ValueError` on mismatch | WIRED |
| `evaluate` / `plan` | `_detect_pivot_setup` / `_geometry_rejection` | unchanged since previous verification | WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Every committed set refused at paper start | live script calling `pin_stream_epoch` on all `params/*/*.toml` | total 25, refused 25 (UnrationalizedParameterSet), accepted 0, other 0 | PASS |
| Allowlist empty | `freeze.PAPER_START_ALLOWLIST` | `()` | PASS |
| Non-bool flag fails closed (WR-01) | `allow_unrationalized="False"`, `1`, `None`, `0` | TypeError for each | PASS |
| Path traversal refused (WR-04) | `strategy_id="../trend-pullback"` | UnregisteredParameterSet | PASS |
| src never enables the flag | `git grep -E "allow_unrationalized\s*=\s*True" -- src` | empty; flag appears only in freeze.py and loop.py | PASS |
| Allowlist not referenced outside its module | `git grep PAPER_START_ALLOWLIST -- src` | freeze.py only (definition, one read, docstrings) | PASS |
| Byte-identical outputs | `git diff 3df767a..HEAD -- params tests/fixtures`; `git status` | empty | PASS |
| Test files, one pytest process each | see list | all exit 0, 0 failed, 0 skipped | PASS |

Test files run (passed count): test_paper_start_gate 70, test_paper_freeze 10, test_paper_parity 5, test_paper_closed_candle 5, test_paper_feed_gates 5, test_paper_reviewfix_pins 9, test_cost_parity 9, test_kill_gate_docs 12, test_rationale 34, test_geometry_audit_doc 20, test_decision_alignment_params 58, test_decision_alignment_bookkeeping 46, test_core_pivots 17, test_core_strategy_geometry 7, test_planner_geometry 88, test_geometry_property 25, test_registry 167, test_registry_gate 7, test_core_strategy_breakout_retest 30, test_core_strategy_range_mr 36, test_core_planner 17, test_geometry_census 30, test_backtest_determinism 16, test_backtest_simulator 63, test_phase6_fixture_geometry 119, test_prefix_invariance 3, test_no_lookahead 4. Also `ruff check` passed, `ruff format --check` passed (428 files), and `mypy src` found no issues (149 files).

**Not run (CI-only or out of scope):** PostgreSQL tests (skip without `TEST_DATABASE_URL`), docker, bootstrap and deploy tests, the full suite in one process (Windows rule), the real-data smoke and census runs (UAT test 8), and the research re-run (outside Phase 15 per criterion 4).

### Probe Execution

No probe scripts are declared by the phase. Step 7c: SKIPPED.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| STRAT-01 | 15-03..06, 15-14, 15-15, 15-17 | Closed-candle features with warm-up gates | SATISFIED | REQUIREMENTS.md maps it to Phase 4 (Complete). Phase 15 re-touches the engine; prefix-invariance, no-lookahead and pivot confirmation tests pass. The paper gate refuses before any candle is parsed. |
| STRAT-02 | all 18 plans | Pure strategy function, deterministic SignalIds | SATISFIED | Determinism, parity and SignalId snapshot tests pass. Plans 15-16..15-18 changed no strategy output (no fixture or params diff). |

No orphaned requirement. REQUIREMENTS.md needs no change.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/paper/freeze.py, src/paper/loop.py, src/domain/rationale.py, tests/test_paper_start_gate.py | - | TBD/FIXME/XXX | none found | - |
| docs/DECISIONS.md | D054 (g) | Still says the TP1 far-half rule is "left for a user decision"; the user's "hoãn" deferral is recorded only in 15-UAT.md and ROADMAP 999.1 | Info | Doc consistency only. The current behaviour matches the decision. |
| src/paper/freeze.py / loop.py | - | Open Info IN-01..IN-05 of 15-REVIEW-PAPER-GATE.md (allowlist entry not self-validated; stale docstrings; per-tick gate and exception ordering; test nits; two REGISTRY_ROOT bindings) | Info | Open by the user's choice; all fail closed. IN-05 also listed under coincidental_reliance_items. |
| src/ | - | Open Info IN-02..IN-06 of 15-REVIEW.md | Info | Open by the user's choice; none blocks a criterion |

The paper-gate fix report marks WR-01 and WR-02 as "requires human verification (logic change in a fail-closed gate)". The verifier checked WR-01 live (TypeError for each non-bool flag value tried). WR-02 is covered by the seeded-violation guard tests in test_paper_start_gate (passing) and by the clean `git grep` of src/. The guard's documented blind spots (runtime-built names, `**kwargs` forwarding) remain an accepted residual (T-15-38).

### Human Verification Required

None open. All three items of the previous report have a recorded user decision (see the decisions table). Item 1 is a recorded decision to defer and keep the current rule (ROADMAP Backlog 999.1), not an approval of a change.

### Gaps Summary

No gaps. All four ROADMAP criteria hold in the current code, and targeted tests re-run green. The previous report's three human items each have a recorded user decision, quoted verbatim above with file citations. The only residuals are open Info findings (5 + 5, left open by the user's choice), one doc-consistency note on D054 (g), and the advisory IN-05 root-binding reliance. None of these blocks the phase goal. What was not run is listed above (PostgreSQL, docker, bootstrap and deploy tests in CI; the real-data smoke and census; the research re-run, which is out of scope).

---

_Verified: 2026-10-07T02:54:22Z_
_Verifier: Claude (gsd-verifier)_
