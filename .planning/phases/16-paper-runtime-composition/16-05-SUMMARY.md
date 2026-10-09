---
phase: 16-paper-runtime-composition
plan: 05
subsystem: analytics / kill-gate report guard
status: complete
tags: [kill-gate, review-registry, evidence-class, fixture-marker, fail-closed, d061-f]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "killgate.evaluate, the journal-depth report CLI, renderer and sidecar, review items WR-01/06/10/12/13 (10-VERIFICATION.md, 10-REVIEW-DISPOSITION.md)"
provides:
  - "docs/research/kill_gate_review_registry.json: schema kill-gate-review-registry/1, five items WR-01, WR-06, WR-10, WR-12, WR-13, all UNRESOLVED, with blocks_report and blocks_live_enable"
  - "src/analytics/killgate_guard.py: ReviewItem, EvidenceClass, KillGateReportBlocked, ReviewRegistryError, load_review_registry, unresolved_report_blockers, unresolved_live_enable_blockers, require_report_conclusion_allowed, live_enable_allowed, not_concluded_line"
  - "Evidence loader key evidence_class (absent = REAL, only the literal 'fixture' downgrades) exposed on EvidenceFile.evidence_class"
  - "CLI option --review-registry; NOT CONCLUDED output, header and section 1 marker, and sidecar redaction while a report blocker is unresolved on real evidence"
affects: [16-36 SHADOW journal report (runs through this CLI), Phase 26 (flips registry items with fix commits and binds LiveEnablementController.enable to live_enable_allowed)]

requirements-completed: [PAPER-02]

actuals:
  tokens: 11000
  tasks: 3
  commits: 3
plan_head_before: c737ec929137554688fbb4c2a92a8c2b36f02705
plan_head_after: a5069e360684363ac5b2a367d74a9200b62895aa
commits: 3

tech-stack:
  added: []
  patterns:
    - "Default-deny evidence class: anything not explicitly marked fixture is real"
    - "Registry loader fails closed: schema, duplicate ids, unknown state, missing scope field, RESOLVED without fix_commit, missing canonical item, canonical-scope tampering"
    - "Guard predicate modelled on killgate.registration_allowed; killgate.evaluate untouched"

key-files:
  created:
    - docs/research/kill_gate_review_registry.json
    - src/analytics/killgate_guard.py
    - tests/test_killgate_guard.py
    - tests/test_wr_registry_scopes.py
  modified:
    - src/analytics/cli.py
    - src/analytics/render.py
    - src/analytics/render_killgate.py
    - src/analytics/render_sidecar.py
    - src/adapters/analytics_files.py
    - tests/fixtures/phase10/loaders/evidence_sample.json
    - tests/test_domain_no_float.py

key-decisions:
  - "A blocked --record exits 1 before the database is read and before any file is written, instead of writing the report pair and then failing: exit 1 is documented as 'nothing was written', and the _fail tail says so. A blocked run without --record still writes the journal-depth report pair (D-18) with the kill-gate section NOT CONCLUDED"
  - "Withheld means the verdict, budget, clock, family acceptance table and gate matrix are removed from section 1 (the family 'Independent' column and the G07/G08/G10 cells are exactly what WR-01 and WR-13 make unreliable); NO_TRADE counts and decision references stay, sections 2 to 10 are unchanged"
  - "The sidecar replaces kill_gate.verdict.state with NOT CONCLUDED and adds a kill_gate_withheld object; verify_render takes blocked_by and checks both, so the pair cannot drift. The report digest is unchanged (it is a hash of the evaluated tree)"
  - "The loader enforces the REV-15 scope table for the five canonical ids and requires all five to be present, so deleting an item or editing a scope away cannot unblock a report; extra ids are allowed"

patterns-established:
  - "Phase 26 flips an item by setting state RESOLVED with a fix_commit in the registry; the guard, the CLI and live_enable_allowed read the same file"

coverage:
  - id: D1
    description: "One versioned registry lists WR-01, WR-06, WR-10, WR-12, WR-13, each UNRESOLVED, with machine-readable blocks_report and blocks_live_enable; WR-10 is live-enable scope only"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_killgate_guard.py#test_committed_registry_lists_the_five_unresolved_items"
        status: pass
      - kind: unit
        ref: "tests/test_wr_registry_scopes.py#test_committed_scope_equals_the_rev15_table"
        status: pass
    human_judgment: false
  - id: D2
    description: "No kill-gate conclusion is printed, rendered, sidecar-ed or journaled on real evidence while WR-01, WR-06, WR-12 or WR-13 is unresolved; the journal-depth report is still produced; flipping any one item back re-blocks"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_killgate_guard.py#test_cli_withholds_the_conclusion_on_unmarked_real_evidence"
        status: pass
      - kind: unit
        ref: "tests/test_killgate_guard.py#test_cli_record_on_real_evidence_exits_one_and_journals_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_killgate_guard.py#test_flipping_any_one_item_back_blocks_again"
        status: pass
    human_judgment: false
  - id: D3
    description: "Evidence is real unless explicitly marked fixture (REV-11); the committed evidence sample is marked fixture; any other marker value is refused"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_killgate_guard.py#test_loader_defaults_to_real_and_accepts_only_the_fixture_literal"
        status: pass
    human_judgment: false
  - id: D4
    description: "A report with only WR-10 unresolved is not blocked by the report guard, and live_enable_allowed refuses while WR-10 is unresolved (REV-15 scope test)"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_wr_registry_scopes.py#test_a_report_with_only_wr10_unresolved_is_not_blocked"
        status: pass
      - kind: unit
        ref: "tests/test_wr_registry_scopes.py#test_live_enable_is_refused_while_wr10_is_unresolved"
        status: pass
    human_judgment: false

duration: 9 min
completed: 2026-10-09
---

# Phase 16 Plan 05: Kill-gate report guard and review registry Summary

**Enforced D061 F guard: a five-item review registry (WR-01/06/10/12/13) and a default-deny fixture marker make the analytics CLI print, render and journal NOT CONCLUDED instead of a kill-gate verdict on real evidence, with `killgate.evaluate` untouched.**

## Performance

- **Duration:** 9 min (start 2026-10-09T03:58Z, end 2026-10-09T04:07Z)
- **Tasks:** 3 of 3 (task 1 is the tracer; its `<verify>` was re-run end to end before expansion and passed)
- **Files:** 4 created, 7 modified (825 insertions, 20 deletions outside `.planning`)

## Accomplishments

- Registry file `docs/research/kill_gate_review_registry.json` and `src/analytics/killgate_guard.py`: fail-closed loader, `unresolved_report_blockers`, `unresolved_live_enable_blockers`, `require_report_conclusion_allowed` (TypeError on wrong input types), `live_enable_allowed` for Phase 26.
- Evidence loader `evidence_class` key (REV-11): absent is REAL, only `"fixture"` downgrades, any other value raises `EvidenceFileError`. `tests/fixtures/phase10/loaders/evidence_sample.json` is marked fixture; the evidence documents built by `_write_evidence` in `tests/test_analytics_cli.py` inherit the marker because they copy that sample.
- CLI/renderer: with the committed registry a real-evidence run prints `Kill gate: NOT CONCLUDED (blocked by WR-01, WR-06, WR-12, WR-13; D061 F)`, exit 0, report pair still written; header row and section 1 carry the marker and no state value; sidecar state is redacted and `kill_gate_withheld` names the items. `--record` on real evidence exits 1 with nothing written or journaled. A run with no evidence file counts as real.
- Scope tests: each id's scope equals the REV-15 table; resolving WR-10 alone does not unblock the report; a report with only WR-10 unresolved is allowed.

## Task Commits

1. Task 1 (tracer): `2fdb8da` feat(16-05): kill-gate review registry and report guard (D061 F, REV-15)
2. Task 2: `e3f10f3` feat(16-05): fixture classification and withheld kill-gate conclusion (REV-11, D061 F)
3. Task 3: `a5069e3` feat(16-05): live-enable reader and WR scope tests (REV-15)

## Verification

- Task commands pass (targeted files: `test_killgate_guard`, `test_wr_registry_scopes`, `test_analytics_cli`, `test_analytics_edge_guards`, `test_kill_gate_docs`, `test_kill_gate_state`, `test_kill_gate_event`, `test_domain_no_float`; plus `test_analytics_files`, `test_analytics_render`, `test_analytics_sidecar`, `test_analytics_report`, `test_analytics_purity`, `test_analytics_digest`, `test_analytics_typing`, `test_kill_gate_gates`, `test_kill_gate_registration`, `test_kill_gate_sticky`: all green, 1 pre-existing skip).
- `ruff check`, `ruff format --check` and `mypy src` (152 files) pass.
- `git diff c737ec9 -- src/analytics/killgate.py src/execution` is empty.
- The whole `pytest -m "not docker"` suite was not run in one process (tool time limit); only the targeted and directly affected suites above.

## Re-pinned digests

None. The `evidence_class` key is not part of any hashed structure, so no pinned digest, golden, experiment id or report digest moved, and `REV-11 fixture marker` re-pins were not needed. The only fixture changed is `tests/fixtures/phase10/loaders/evidence_sample.json` (one added line). Re-running `grep -rl "analytics-evidence/2"` at execution time found only that sample, `tests/test_analytics_files.py` (reads the same sample; no change needed), `tests/test_kill_gate_docs.py` (a text assertion, no evidence file), `src/adapters/analytics_files.py` and `src/backtest/experiment.py`: no further evidence fixture reaches the kill-gate path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Sidecar and header also withhold the verdict**
- **Found during:** Task 2
- **Issue:** The plan names the printed line and the rendered kill-gate section, but the sidecar JSON (`kill_gate.verdict.state`) and the report header table row `Kill gate state` would still have emitted the evaluated state on real evidence, defeating "no conclusion is emitted".
- **Fix:** `render_header`, `render_markdown`, `build_sidecar` and `verify_render` take an optional `blocked_by`; the state is replaced by NOT CONCLUDED and the pair is cross-verified. Defaults leave existing output byte-identical.
- **Files modified:** src/analytics/render.py, src/analytics/render_killgate.py, src/analytics/render_sidecar.py, src/analytics/cli.py
- **Commit:** e3f10f3

**2. [Rule 1 - Consistency] Blocked `--record` fails before writing anything**
- **Found during:** Task 2
- **Issue:** The plan says a blocked `--record` run still writes the report pair and then returns `_fail(...)`; `_fail` prints "No file was written" and the CLI contract defines exit 1 as nothing written, so that would state something false.
- **Fix:** The registry guard runs before the database read and before any write; blocked `--record` returns `_fail` immediately. Blocked runs without `--record` still write the pair, which is what D-18 needs.
- **Commit:** e3f10f3

**3. [Rule 2 - Missing critical functionality] Registry loader enforces the canonical five items and scopes**
- **Found during:** Task 1
- **Issue:** Test 6 lists validation failures but a registry with an item deleted or a scope flipped to false would silently unblock reports (T-16-12).
- **Fix:** The loader requires all five canonical ids and refuses a scope that differs from the REV-15 table.
- **Commit:** 2fdb8da

### Process note

Task 2 and Task 3 production code was written before its tests (RED was verified for Task 1 only, by the missing module). The tests were added in the same task and assert the specified behaviour, but the strict RED-before-GREEN commit split of `tdd="true"` was not followed for Tasks 2 and 3, and each task has one commit instead of a test commit and a feat commit.

**Total deviations:** 3 auto-fixed (2 missing-critical, 1 consistency), 1 process note. **Impact:** all within the plan's intent; no WR design changed.

## Auth Gates

None.

## Known Stubs

None.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: operator-controlled-guard-input | src/analytics/cli.py | `--review-registry` lets an operator point the CLI at another registry file, which could mark every item RESOLVED. The loader still demands all five canonical ids, canonical scopes and a fix_commit per resolved item, but cannot verify the commit exists. Same class of risk as WR-12 (arbitrary decisions file); binding the CLI to the committed file only, or checking fix commits against git, belongs to Phase 26. |

## Next Phase Readiness

Ready for 16-06. Phase 26 owns flipping registry items (state RESOLVED plus fix_commit) and binding `LiveEnablementController.enable` to `live_enable_allowed`; the binding is not built here and `src/execution` is unchanged.

## Self-Check: PASSED

- Created files exist: docs/research/kill_gate_review_registry.json, src/analytics/killgate_guard.py, tests/test_killgate_guard.py, tests/test_wr_registry_scopes.py.
- Commits 2fdb8da, e3f10f3, a5069e3 exist on develop.
- Acceptance criteria re-run: Task 1, 2, 3 test commands green; `git diff c737ec9 -- src/analytics/killgate.py src/execution` empty; plan-level ruff and mypy green.
