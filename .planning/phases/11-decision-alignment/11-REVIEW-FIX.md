---
phase: 11-decision-alignment
fixed_at: 2026-09-30T00:00:00Z
review_path: .planning/phases/11-decision-alignment/11-REVIEW.md
iteration: 1
findings_in_scope: 12
fixed: 11
skipped: 1
status: partial
---

# Phase 11: Code Review Fix Report

**Fixed at:** 2026-09-30
**Source review:** .planning/phases/11-decision-alignment/11-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 12 (0 Critical, 12 Warning; Info excluded by `fix_scope: critical_warning`)
- Fixed: 11
- Skipped: 1

**Verification environment:** `workflow.use_worktrees` is `false`, so all edits, commits and gates ran in the main checkout (no worktree, no recovery sentinel). After the last commit, `python scripts/verify_decision_alignment.py all` printed ALL_PASS. The pytest run covered `tests/test_decision_alignment*.py`, `tests/test_registry.py`, `tests/test_kill_gate_docs.py` and `tests/test_research_gate_negative.py`. It passed with zero skips, so the baseline-commit negative tests now run locally as well as in CI. The pre-existing unrelated modifications (`.planning/milestone.lock`, `.planning/state.json`, `.gsd/`) were not staged.

## Fixed Issues

### WR-01: CI shallow clone silently skips the phase's negative tests

**Files modified:** `.github/workflows/registry-gate.yml`, `tests/test_decision_alignment_authority.py`, `tests/test_decision_alignment_bookkeeping.py`, `tests/test_decision_alignment_exchange.py`, `tests/test_decision_alignment_ops_risk.py`
**Commit:** 6b9c3d9
**Applied fix:** The checkout step now uses `fetch-depth: 0`, so `git show <baseline>:<file>` works in CI. The four test modules use the full 40-character baseline SHA instead of the abbreviated `679825c`. The optional "fail on skips" CI guard was not added.

### WR-02: Gates pin the 2026-09-30 snapshot and will fail on legitimate follow-up work

**Files modified:** `scripts/decision_alignment/bookkeeping.py`, `scripts/decision_alignment/protocol.py`, `scripts/decision_alignment/authority.py`, `tests/test_decision_alignment_bookkeeping.py`, `tests/test_decision_alignment_protocol.py`, `tests/test_decision_alignment_authority.py`
**Commits:** f73917f (bookkeeping and protocol), 16ccc10 (AU `.planning` skip)
**Applied fix:**
- RQ-01 no longer pins the `Pending` status; the phase mapping is still checked.
- RQ-02 checks that the coverage counts are consistent with the list and table, with a floor of 43 IDs.
- RQ-05 requires a footer date on or after 2026-09-30, not exactly that date.
- DC-02 requires contiguous IDs from D001 that reach at least D045, so an appended D046 passes.
- PR-02 accepts any `vX.Y.Z` in `Supersedes`.
- The emptiness assertion on `holdout_consumed.json` is removed, and so is the "all new requirements are not Complete" test.
- `run_reqs()` and the AU `run()` return explicit `SKIP:` results for the `.planning`-dependent gates (RQ-01 to RQ-05, AU-03 to AU-05) when `.planning` files are absent. Tests were added for each new behaviour.
- Not changed: GL-03 (alias set equals the enum) and the v1.1.0-specific `test_protocol_freeze_witnesses_intact` in `tests/test_kill_gate_docs.py`. Both are deliberate contract checks that the phase changing the contract should update in the same change. The Phase 12 enum cleanup must update GL-03.

**Status note:** fixed: requires human verification. The new invariants are logic changes, so confirm they are strict enough.

### WR-03: EX-06 counts "Not fetched" rows as grounded sources

**Files modified:** `scripts/decision_alignment/exchange.py`, `docs/SOURCES.md`, `tests/test_decision_alignment_exchange.py`
**Commit:** 4f9267b
**Applied fix:** EX-06 now reads the register's Method cell. A URL registered as "Not fetched" is accepted only when the citing paragraph of EXECUTION_SPEC carries `verify against current Binance docs`. The SOURCES register column is renamed "Checked on", and the three unfetched rows read `2026-09-30 (not fetched)`, so they no longer look like fetch dates. Positive and negative tests were added.

**Status note:** fixed: requires human verification.

### WR-04: The old quantization order is still in AGENTS.md and STACK.md, and AU-06 cannot see it

**Files modified:** `AGENTS.md`, `.planning/research/STACK.md`, `scripts/decision_alignment/authority.py`, `tests/test_decision_alignment_authority.py`
**Commit:** faebc62
**Applied fix:** The float row in both files now reads "quantization floor → min-qty/min-notional rejects → realized-risk utilization check" (D031 order). `OLD_ORDER_PHRASE` is widened to a clause-bounded regex. It catches any `realized-risk … → … min-qty|min-quantity|min-notional` sequence and still catches the old exact phrase. AU-06 now also scans STACK.md. Tests were added for the float-row wording, for the canonical wording passing, and for the pre-change STACK and AGENTS text failing.

### WR-05: Several "phrase present anywhere in the section" gates cannot fail on the defects they are named for

**Files modified:** `scripts/decision_alignment/authority.py`, `scripts/decision_alignment/exchange.py`, `scripts/decision_alignment/ops_risk.py`, and the three matching test files
**Commits:** 16ccc10 (AU-01), 4f9267b (EX-02), db70b51 (OR-09 and OR-10a)
**Applied fix:**
- AU-01 detects the variants "HMAC verified", "HMAC checked", "HMAC signature check" and similar. A sentence that negates the claim ("HMAC signature is not available") is not flagged; the exact legacy phrase is always flagged. The real docs contain two such negated statements.
- EX-02 requires each status to be a first-cell row of the section 6.1 status table. The other phrases stay as substring checks.
- OR-09 reads only the first fenced `text` block of DATA_MODEL section 2.4.
- OR-10a is scoped to CONFIGURATION section 10. All phrases are already in that section.
- Tests were added for each.

**Status note:** fixed: requires human verification.

### WR-06: The frozen universe manifest is self-hashed only, so a post-freeze edit is not tamper-evident

**Files modified:** `scripts/decision_alignment/universe.py`, `docs/research/universe/research-universe-v1.toml`, `tests/test_decision_alignment_universe.py`
**Commit:** 7628b9a
**Applied fix:** Added `FROZEN_CONTENT_SHA256` (`None` while DRAFT) and `check_second_witness()`, wired into UN-02. A FROZEN manifest must have that constant set, equal to the manifest hash. A DRAFT manifest must have it unset. Editing `symbols` and refreshing the in-file hash now fails UN-02. The Phase 13 freeze procedure (in the module docstring and the TOML comment) gains a step to record the hash in the constant in the same commit. Tests cover the tamper case.

### WR-07: The RUNBOOK and SECURITY_AND_OPERATIONS describe the D034 ladder in the present tense, but the code does the opposite

**Files modified:** `docs/operations/RUNBOOK.md`, `docs/operations/SECURITY_AND_OPERATIONS.md`
**Commit:** d323bba
**Applied fix:** Added an "Implementation status" paragraph to both documents. The D034 ladder is the target behaviour, built in Phase 20 (EXEC-06, OPS-05). Until then the system enters SAFE_MODE and alerts but does not re-place the stop or close the position, so the operator must act manually. The OR-01 gate phrases are untouched, so the caveat coexists with the gate and no gate change was needed. I confirmed `src/execution/fill_monitor.py` says it "never places rescue protection". I did not re-read `src/execution/manager.py` myself; that part of the claim rests on the review.

### WR-08: `working_type` is accepted and hashed into parameter-set identity, but no code honours it

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`, `tests/test_decision_alignment_params.py`, `docs/configuration/CONFIGURATION.md`, `docs/DECISIONS.md`
**Commit:** db9bf96
**Applied fix:** `WORKING_TYPE_VALUES` is now `{"MARK_PRICE"}`, with a comment saying to widen it only together with the consumers. CONFIGURATION section 10 states that `CONTRACT_PRICE` is rejected at load. D044 gains follow-up (11): the Phase 14 simulator and Phase 19 placement and paper own the consumers. The registry test now expects `CONTRACT_PRICE` to be rejected, and the PA-04 wrong-working-type test accepts the new load-failure wording. The five baseline sets already use `MARK_PRICE`, so no hash changed, and the byte-lock and pin gates still pass.

**Status note:** fixed: requires human verification. This narrows a registry contract.

### WR-09: EXECUTION_SPEC section 11 lists "cancel pending strategy orders" without excluding protective stops

**Files modified:** `docs/trading/EXECUTION_SPEC.md`, `scripts/decision_alignment/exchange.py`, `tests/test_decision_alignment_exchange.py`
**Commit:** 95d77bf
**Applied fix:** The bullet now reads "cancel pending entry orders (protective stops and take-profits are never cancelled by this control)". The sentence below it states that a disable never blocks or cancels a protective or reduce-only order, and that close and protect are separate explicit actions. EX-05 now requires both new phrases, with tests.

### WR-11: The alert example depends on an unstated reference price

**Files modified:** `docs/trading/SIGNAL_AND_ALERTS.md`
**Commit:** 6b0f3bd
**Applied fix:** Stated that the Expected R:R uses the zone-midpoint reference entry (103925), which matches `entry_ref` in `src/core/planner.py`. The `minimum_rr` gate is evaluated at that midpoint, not at the worst-case fill, and a fill at the upper edge gives about 1.53 to TP1. The OR-10b phrases are unchanged.

### WR-12: `params.run()` mislabels and aborts on non-`ValueError` load errors

**Files modified:** `scripts/decision_alignment/params.py`, `tests/test_decision_alignment_params.py`
**Commit:** 347bf43
**Applied fix:** `check_pins` now catches any exception per file and records `load failed: <Type>: <msg>`, then keeps scanning. A malformed TOML no longer skips PA-02 to PA-06 or shows up as "pin file unreadable". A regression test covers a syntax-error TOML.

## Skipped Issues

### WR-10: Protocol G5 has no trade-count floor, so a lucky handful of trades can pass the single-use holdout

**File:** `docs/research/RESEARCH_PROTOCOL.md:225`
**Reason:** Skipped because this is a research-design decision, not a code or doc defect. The fix needs the owner to choose the G5 rule. The options are a holdout trade-count floor tied to the Validation rate, or a bootstrap lower bound above 0. It also needs a protocol version bump (v1.1.1 or v1.2.0). The bump touches the frozen header, the D043 or new DECISIONS witness row, the DOC_STATUS index line, the kill-gate docs tests and `research-gate.yml`, and it must happen before the first Validation run. The D043 override-procedure wording should be aligned in the same change. Recommend handling it through a discussion or decision step, not an automated fix.
**Original issue:** G5 passes on mean net R above 0 and drawdown at most 20% with "(trade count reported, no floor)", so one or two winning trades pass the single-use holdout.

---

_Fixed: 2026-09-30_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
