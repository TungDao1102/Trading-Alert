---
phase: 01-research-formalization
plan: 03
subsystem: docs
tags: [glossary, decisions, doc-status, contradictions, renumber]

# Dependency graph
requires:
  - phase: 01-research-formalization
    plan: 01
    provides: Frozen research protocol v1.0.0 (DRAFT) + canonical decision framework + CONTEXT/RESEARCH alignment for C1-C7
  - phase: 01-research-formalization
    plan: 02
    provides: Three family sheets (Trend Pullback, Breakout+Retest, Range Mean-Reversion) in 7-slot template with D012 TBD footer
provides:
  - Seven known Core Docs v0.3 contradictions (C1-C7) resolved as explicit decisions D022-D028
  - DECISIONS.md extended from 21 rows (D001-D021) to 28 rows (D001-D028)
  - DOC_STATUS.md bumped with research/RESEARCH_PROTOCOL.md as pending-freeze entry plus change-log recording the C1-C7 edit set and every touched doc
  - Pure number-only section renumbers across 5 docs (BACKTEST_SPEC, DATA_PIPELINE, TRADINGVIEW, SECURITY, RESEARCH) preserving every title and content byte
affects: [phase-01-plan-04-freeze, phase-02-data-foundation, phase-03-domain-registry, phase-08-approval-reconciliation, phase-09-live-execution]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
# Same estimateTokens scale (chars/4 over the realized diff), never a harness token count.
actuals:
  tokens: 3827    # chars/4 over the realized diff (15306 chars total)
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "D-05 batching: renumbers + DECISIONS rows + DOC_STATUS bump land as one atomic commit when they belong to the same contradiction batch"
    - "Cross-reference style: title-based citations preferred over numeric section numbers (C6 risk mitigation)"
    - "D028 audit trail: literal `(D028)` token appended in all three mirror locations (GLOSSARY §2.1, DATA_MODEL §3, SIGNAL_AND_ALERTS §1) so grep verifies completeness"
    - "Checker rev-2 choice: token-free cross-references over region-scoped grep sweeps for C2 (signal-vs-execution enum separation)"

key-files:
  modified:
    - docs/00_PRODUCT_SCOPE.md
    - docs/trading/SIGNAL_AND_ALERTS.md
    - docs/trading/EXECUTION_SPEC.md
    - docs/testing/TESTING_STRATEGY.md
    - docs/research/TRADING_STRATEGY_RESEARCH.md
    - docs/GLOSSARY.md
    - docs/data/DATA_MODEL.md
    - docs/backtest/BACKTEST_SPEC.md
    - docs/architecture/DATA_PIPELINE.md
    - docs/integration/TRADINGVIEW.md
    - docs/operations/SECURITY_AND_OPERATIONS.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md

key-decisions:
  - "D022: SystemMode canonical list = GLOSSARY.md §8; scope §7 aligned (added SAFE_MODE; renamed unqualified autonomous entry to LIVE_AUTONOMOUS_DISABLED)"
  - "D023: SIGNAL_AND_ALERTS.md §4 carries canonical SignalStatus only (renamed 'Alert states' -> 'Signal states (canonical)'; trimmed to 8 GLOSSARY values; execution-lifecycle names replaced with token-free cross-reference)"
  - "D024: Order state machine has no approval state (EXECUTION_SPEC §3 chain is PLANNED -> SUBMITTING -> NEW; TESTING_STRATEGY §8 invalid-transition examples prefixed with owning-machine names)"
  - "D025: Asia/Ho_Chi_Minh is the canonical presentation timezone (research §9.3 corrected from Asia/Bangkok; added Windows tzdata-wheel note)"
  - "D026: research doc §12 uses canonical enums only (SignalStatus for signal states; OrderStatus/TradeStatus references for order/exit; removed casing-variant and invented synonyms; preserved two performance tables and four canonical timestamps)"
  - "D027: Section-number renumbers across docs are number-only (BACKTEST_SPEC duplicate gates header §11->§12; DATA_PIPELINE trailing duplicates §8/§9 -> §13/§14; TRADINGVIEW §8 -> §7; SECURITY §11 -> §10; research doc duplicate trailing §13/§14 -> §25/§26)"
  - "D028: Signal.APPROVED != TradePlan.APPROVED; both preserved (GLOSSARY §2.1 ownership note; mirrored in DATA_MODEL §3 and SIGNAL_AND_ALERTS §1 with `(D028)` token for grep-verifiable audit trail)"

patterns-established:
  - "One DECISIONS row per contradiction: scope-restricted edits land as auditable decisions, never silent renames"
  - "Pure number-only renumber verified by before/after numeric-reference sweep diff; every delta maps to an intended renumber or is fixed"
  - "Checker rev-2: token-free prose cross-references over region-scoped grep sweeps when a literal token would re-introduce the banned name"

requirements-completed: [RSCH-03]

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "C1 SystemMode naming: scope §7 aligned to GLOSSARY §8 six modes verbatim"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "git grep -n 'LIVE_AUTONOMOUS[^_]' -- docs/00_PRODUCT_SCOPE.md (exit 0, no output = pass)"
        status: pass
      - kind: other
        ref: "docs/00_PRODUCT_SCOPE.md §7 enumerated 6 modes (RESEARCH, BACKTEST, PAPER, LIVE_APPROVAL, SAFE_MODE, LIVE_AUTONOMOUS_DISABLED)"
        status: pass
    human_judgment: false
  - id: D2
    description: "C2 SIGNAL_AND_ALERTS §4 trimmed to 8 canonical SignalStatus values; execution-lifecycle names replaced with token-free cross-reference"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "git grep -n 'ORDER_PLACED' -- docs/trading/SIGNAL_AND_ALERTS.md (exit 0, no output = pass)"
        status: pass
      - kind: other
        ref: "docs/trading/SIGNAL_AND_ALERTS.md §4 enum contains exactly 8 canonical values matching GLOSSARY §2"
        status: pass
    human_judgment: false
  - id: D3
    description: "C3 EXECUTION_SPEC §3 order chain has no APPROVED node; TESTING_STRATEGY §8 invalid-transition examples prefixed with owning-machine names"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "Select-String -Path docs/trading/EXECUTION_SPEC.md -Pattern '^\\s*APPROVED\\s*$' (no output = pass)"
        status: pass
    human_judgment: false
  - id: D4
    description: "C4 research §9.3 timezone corrected to Asia/Ho_Chi_Minh; Windows tzdata-wheel note added"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "git grep -n 'Bangkok' -- docs/ (exit 0, no output = pass)"
        status: pass
    human_judgment: false
  - id: D5
    description: "C5 research §12 signal states rewritten to canonical SignalStatus; order/exit block to canonical OrderStatus + TradeStatus references; casing variants and invented synonyms removed"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "Section-12 region sweep: no OrderPlaced|PartiallyFilled|Skipped-Busy|^Generated$ in TRADING_STRATEGY_RESEARCH.md §12 region (exit 0, no output = pass)"
        status: pass
    human_judgment: false
  - id: D6
    description: "C6 pure renumber: BACKTEST_SPEC §11 duplicate gates -> §12; DATA_PIPELINE §8/§9 trailing -> §13/§14; TRADINGVIEW §8 -> §7; SECURITY §11 -> §10; research §13/§14 trailing -> §25/§26. Zero semantic change."
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "BACKTEST_SPEC: '^## 11\\.' count = 1 (dup-11 PASS)"
        status: pass
      - kind: other
        ref: "Before/after numeric-reference sweep diff: every delta maps to intended renumber"
        status: pass
    human_judgment: false
  - id: D7
    description: "D022-D028 rows appended to DECISIONS.md (21 -> 28 rows)"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "git grep '^| D0' -- docs/DECISIONS.md | Measure-Object -Line = 28 (rows PASS)"
        status: pass
    human_judgment: false
  - id: D8
    description: "DOC_STATUS.md bumped: research/RESEARCH_PROTOCOL.md added under Stable/canonical as pending-freeze entry; change-log records C1-C7 edit set and every touched doc"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "git grep -n 'RESEARCH_PROTOCOL' -- docs/DOC_STATUS.md | Select-Object -First 1 (line printed = pass)"
        status: pass
    human_judgment: false
  - id: D9
    description: "D028 ownership paragraph appended to GLOSSARY.md §2.1; mirrored into DATA_MODEL.md §3 and SIGNAL_AND_ALERTS.md §1 with `(D028)` token for grep-verifiable audit"
    requirement: RSCH-03
    verification:
      - kind: other
        ref: "git grep -n 'D028' -- docs/GLOSSARY.md docs/data/DATA_MODEL.md docs/trading/SIGNAL_AND_ALERTS.md | Measure-Object -Line >= 3 (4 = pass)"
        status: pass
    human_judgment: false

# Metrics
duration: 33min
completed: 2026-09-19
status: complete
---

# Phase 1 Plan 3: C1-C7 Contradiction Resolution Summary

**Seven Core Docs v0.3 contradictions resolved as auditable decisions D022-D028; scope-restricted edits land with zero silent renames; DECISIONS.md extended from 21 to 28 rows; DOC_STATUS.md bumped with every touched doc.**

## Performance

- **Duration:** 33 min
- **Started:** 2026-09-19T13:11:07Z
- **Completed:** 2026-09-19T13:44:39Z
- **Tasks:** 3 (all executed, no checkpoints hit)
- **Files modified:** 13 canonical docs (per the plan's `files_modified` list)

## Accomplishments

- Every known Core Docs v0.3 contradiction C1-C7 appears as an explicit resolved decision D022-D028 in `docs/DECISIONS.md` with no silent renames
- Each canonical doc edit preserved its own purpose and structure; only the contradiction-relevant slice changed (C6 renumbers were pure number-only)
- `docs/DOC_STATUS.md` lists every touched doc under its expected section and the new protocol file as pending-freeze
- DECISIONS row count moved from the session-verified baseline of 21 rows to 28 rows
- D028 ownership paragraph appended in GLOSSARY §2.1 plus mirrored into DATA_MODEL §3 and SIGNAL_AND_ALERTS §1 with `(D028)` token for grep-verifiable audit trail (4 D028 hits total)
- C6 renumbers verified by before/after numeric-reference sweep diff — every delta maps to an intended renumber or to a new DECISIONS-row cross-reference citation; no numeric cross-references to renumbered sections exist elsewhere

## Task Commits

Each task was committed atomically:

1. **Task 1: C1-C3 enum corrections across scope/signal/execution/testing docs** - `e1ec86a` (docs)
2. **Task 2: C4 timezone + C5 status enums + C7 ownership mirrors (D028)** - `562975b` (docs)
3. **Task 3: C6 renumbers + D022-D028 rows + DOC_STATUS bump** - `4b6d6c0` (docs)

**Plan metadata:** (recorded in this SUMMARY commit)

## Files Created/Modified

- `docs/00_PRODUCT_SCOPE.md` - §7 operating-modes list aligned to GLOSSARY §8 (added SAFE_MODE; renamed unqualified autonomous entry to LIVE_AUTONOMOUS_DISABLED)
- `docs/trading/SIGNAL_AND_ALERTS.md` - §1 D028 ownership mirror; §4 renamed to "Signal states (canonical)" and trimmed to 8 canonical SignalStatus values with token-free cross-reference to GLOSSARY OrderStatus/TradeStatus sections and DATA_MODEL §3
- `docs/trading/EXECUTION_SPEC.md` - §3 entry-order chain has no APPROVED node (PLANNED → SUBMITTING → NEW → …); added sentence stating order enters PLANNED only after plan approval
- `docs/testing/TESTING_STRATEGY.md` - §8 invalid-transition examples prefixed with owning-machine names (SignalStatus, TradePlanStatus, TradeStatus); noted order machine has no approval state
- `docs/research/TRADING_STRATEGY_RESEARCH.md` - §9.3 timezone corrected to Asia/Ho_Chi_Minh with Windows tzdata-wheel note; §12 signal-state block rewritten to canonical SignalStatus and order/exit block to canonical OrderStatus + TradeStatus references; trailing duplicate `# 13.` → `# 25.` and `## 14.` → `## 26.`
- `docs/GLOSSARY.md` - §2.1 D028 ownership paragraph appended
- `docs/data/DATA_MODEL.md` - §3 D028 mirror sentence appended
- `docs/backtest/BACKTEST_SPEC.md` - duplicate `## 11. Acceptance gates` header → `## 12. Acceptance gates`
- `docs/architecture/DATA_PIPELINE.md` - trailing `## 8. Storage architecture` → `## 13.` and `## 9. Python implementation rule` → `## 14.`
- `docs/integration/TRADINGVIEW.md` - `## 8. Python webhook adapter` → `## 7. Python webhook adapter`
- `docs/operations/SECURITY_AND_OPERATIONS.md` - `## 11. Python runtime operations` → `## 10. Python runtime operations`
- `docs/DECISIONS.md` - D022-D028 rows appended (21 → 28)
- `docs/DOC_STATUS.md` - `research/RESEARCH_PROTOCOL.md` added under Stable/canonical as pending-freeze entry; change-log section appended

## Decisions Made

- **D022 (C1):** `SystemMode` canonical list = GLOSSARY §8. Scope §7 aligned: added SAFE_MODE; renamed unqualified autonomous entry to LIVE_AUTONOMOUS_DISABLED; kept future-only/disabled-by-default qualifier. Authority: D016.
- **D023 (C2):** SIGNAL_AND_ALERTS §4 carries canonical SignalStatus only. Renamed "Alert states" → "Signal states (canonical)"; trimmed to 8 GLOSSARY values; replaced execution-lifecycle names with token-free cross-reference pointing at GLOSSARY OrderStatus/TradeStatus sections and DATA_MODEL §3. Checker rev-2 choice: token-free prose over region-scoped sweep (avoids re-introducing the banned name). Authority: GLOSSARY + D016.
- **D024 (C3):** Order state machine has no approval state. EXECUTION_SPEC §3 chain is PLANNED → SUBMITTING → NEW → …; APPROVED removed; added sentence stating order enters PLANNED only after plan approval (approval lives upstream on signal/plan machines). TESTING_STRATEGY §8 invalid-transition examples prefixed with owning-machine names (SignalStatus, TradePlanStatus, TradeStatus). Authority: GLOSSARY + D007 + D016.
- **D025 (C4):** Asia/Ho_Chi_Minh is the canonical presentation timezone. Research §9.3 corrected from Asia/Bangkok; added Windows tzdata-wheel note (zoneinfo absent on Windows OS; use zoneinfo.ZoneInfo() not hard-coded UTC+7 offset). Authority: engineering principles outrank research notes.
- **D026 (C5):** Research doc §12 uses canonical enums only. Signal-state block → canonical SignalStatus; order/exit block → canonical OrderStatus + TradeStatus references. Removed casing-variant and invented synonyms: Generated, Approved, Skipped-Busy, OrderPlaced, PartiallyFilled, Filled, Canceled, TP, SL, ManualExit. Preserved two performance tables (System / User Executed) and four canonical timestamps (SignalTime / ApproveTime / OrderTime / FillTime) unchanged. Authority: GLOSSARY + DATA_MODEL.
- **D027 (C6):** Section-number renumbers across docs are number-only. BACKTEST_SPEC duplicate gates header §11 → §12; DATA_PIPELINE trailing §8/§9 → §13/§14; TRADINGVIEW §8 → §7; SECURITY §11 → §10; research doc trailing duplicate §13/§14 → §25/§26. Titles and content unchanged; verified by before/after numeric-reference sweep diff. Authority: scope-restricted edits land as auditable decisions, never silent renames.
- **D028 (C7):** Signal.APPROVED ≠ TradePlan.APPROVED; both preserved. GLOSSARY §2.1 ownership paragraph: signal-level approval records user approval observed on the signal instance; plan-level approval authorizes execution handoff; order placement reads plan status; transition order is Signal APPROVED → TradePlan APPROVED → Order PLANNED. Mirrored into DATA_MODEL §3 and SIGNAL_AND_ALERTS §1 with `(D028)` token for grep-verifiable audit trail. No enum value changes — clarification only. Authority: D007 separation + D016 terminology.

## Deviations from Plan

### Checker rev-2 implementation choice (recorded)

The plan surfaced two acceptable approaches for the C2 cross-reference replacement and recorded the choice explicitly in the task action text: "checker rev-2 choice: token-free prose over a region-scoped sweep, recorded here". Executed as the token-free cross-reference pointing at GLOSSARY OrderStatus/TradeStatus sections plus DATA_MODEL §3 by title, without repeating any enum literal. Verified: no ORDER_PLACED/FILLED/CLOSED tokens remain in `docs/trading/SIGNAL_AND_ALERTS.md` (grep exit 0, no output).

### Auto-fixed: Explanatory paragraph in scope §7 (Task 1)

- **Found during:** Task 1 first edit pass on `docs/00_PRODUCT_SCOPE.md` §7
- **Issue:** Initial explanatory paragraph introduced the literal `LIVE_AUTONOMOUS` (without the `_DISABLED` suffix) when describing the future autonomous mode, which would have failed the contradiction-token sweep `git grep -n "LIVE_AUTONOMOUS[^_]" -- docs/00_PRODUCT_SCOPE.md`
- **Fix:** Rewrote the paragraph to use only `LIVE_AUTONOMOUS_DISABLED` (the canonical name) and describe the future-mode note via reference to `GLOSSARY.md` §8 rather than restating the unqualified name
- **Files modified:** `docs/00_PRODUCT_SCOPE.md` §7 only
- **Verification:** Sweep `git grep -n "LIVE_AUTONOMOUS[^_]" -- docs/00_PRODUCT_SCOPE.md` returns exit 0 with no output (PASS)
- **Committed in:** `e1ec86a` (Task 1 commit)

### Auto-fixed: GLOSSARY D028 paragraph persistence (Task 2)

- **Found during:** Task 2 verification of D028 mirror count
- **Issue:** The GLOSSARY.md edit applied at the start of Task 2 was not present in the working tree when verification ran (count was 2, not 3); investigation showed the Edit tool reported success but the file change did not persist to the working-tree copy the next read was performed against
- **Fix:** Re-applied the edit with the exact `oldString`/`newString` and confirmed the paragraph is now present via `git diff docs/GLOSSARY.md` showing the 4-line insertion at line 52; `(D028)` token added at the end of the paragraph
- **Files modified:** `docs/GLOSSARY.md` only
- **Verification:** `git grep -n "D028" -- docs/GLOSSARY.md docs/data/DATA_MODEL.md docs/trading/SIGNAL_AND_ALERTS.md | Measure-Object -Line` returns 4 lines (>= 3, PASS)
- **Committed in:** `562975b` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 token-collision in explanatory text, 1 edit-persistence re-apply)
**Impact on plan:** Both auto-fixes necessary for the contradiction-token sweeps to pass; no scope creep. The C2 cross-reference style (token-free prose) is the checker rev-2 choice explicitly anticipated by the plan.

## Issues Encountered

None beyond the deviations above. All three task `<verify>` blocks passed on first re-run after the auto-fixes.

## C6 Before/After Sweep Archive

### Before-state (captured before any renumber)

Pattern: `git grep -n "§ *1[123]\|section 1[123]\|Section [789]\|§ *[789]" -- docs/`

Categories of numeric cross-references observed in the before-sweep:

- `BACKTEST_SPEC.md §11` references (family sheets) — these point at "Acceptance gates" by number; the title "Acceptance gates" is preserved through the §11 → §12 renumber, so title-based citations remain stable. Safe.
- `§7 backtest path` / `§7` references in family sheets — these refer to per-family sheet's backtest-path slot (numbered §7 in the family sheets themselves), NOT BACKTEST_SPEC §7. Self-contained references; unaffected by C6.
- `§13`, `§14` references in family sheets to `TRADING_STRATEGY_RESEARCH.md` — original sections keep their numbers; only the duplicate trailing sections move to §25/§26. Unaffected.
- `RESEARCH_PROTOCOL.md §12` references — pointer at `TRADING_STRATEGY_SPEC.md` §12 (an external doc not in C6 scope).
- `CONFIGURATION.md §3`, `§9` references — external to C6 renumber scope.
- `§8` references to GLOSSARY.md — external to C6 renumber scope.

NO numeric cross-references to the specific sections being renumbered were observed in the before-sweep. After-sweep adds 5 lines for the new DECISIONS rows (D022-D028) cross-referencing the canonical scope-§-names (e.g., "§7", "§9.3", "§12") — these are intentional new citations, not renumber-breakage.

### After-state (captured after renumbers, before commit)

51 lines (down from 67 in my condensed before-summary, which double-counted some references). Every delta in the after-sweep is either:
1. An intended renumber result (none observed in this case — the renumbered section headers are not pointed at by other docs' prose), OR
2. A new DECISIONS-row cross-reference citation (D022-D028 append), OR
3. No-change references preserved by title (`§11` for `Acceptance gates` still references the now-renumbered §12 by its preserved title).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 1 plan 4 (Gate YAML + freeze beat) is unblocked and may proceed; it can flip the protocol header to FROZEN, append the freeze DECISIONS row, write `.github/workflows/research-gate.yml`, and apply the required-status-check setting per its `checkpoint:decision` task
- The protocol file is currently under `## Stable / canonical` in DOC_STATUS.md as pending-freeze entry; plan 4's freeze beat moves it to fully frozen
- Phase 2 (Data Foundation) and Phase 3 (Domain + Registry + Fixtures) may begin reading the corrected canonical docs (GLOSSARY §8 modes; canonical SignalStatus/OrderStatus/TradeStatus enums; canonical ownership clarifications D028; numbered section structure)
- D012 (Strategy V1 family TBD) is unchanged; no phase output may declare a winner

---

*Phase: 01-research-formalization*
*Completed: 2026-09-19*
