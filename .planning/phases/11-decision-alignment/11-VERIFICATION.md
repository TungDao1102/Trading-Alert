---
phase: 11-decision-alignment
verified: 2026-09-30T00:00:00Z
status: human_needed
score: 5/5 must-haves verified (with 5 human-confirmation items and 4 noted warnings)
covered_files:
  - docs/DECISIONS.md
  - docs/DOC_STATUS.md
  - docs/GLOSSARY.md
  - docs/SOURCES.md
  - docs/integration/BINANCE.md
  - docs/integration/TRADINGVIEW.md
  - docs/operations/RUNBOOK.md
  - docs/operations/SECURITY_AND_OPERATIONS.md
  - docs/research/RESEARCH_PROTOCOL.md
  - docs/research/universe/research-universe-v1.toml
  - docs/trading/EXECUTION_SPEC.md
  - docs/trading/RISK_MANAGEMENT.md
  - params/breakout-retest/baseline-v4.toml
  - params/range-mr/baseline-v4.toml
  - params/trend-pullback/baseline-no-trade-v2.toml
  - params/trend-pullback/baseline-simple-trend-v2.toml
  - params/trend-pullback/baseline-v4.toml
  - scripts/verify_decision_alignment.py
  - src/domain/registry.py
covered_digest: "v2:sha256:84bc9577b238072db34c5880dbfc016f92b06890f041c91af152f25b91469951"
behavior_unverified: 0
overrides_applied: 0
gaps: []
deferred:
  - truth: "Research universe manifest is hashed (content_sha256 filled, status FROZEN, symbols listed)"
    addressed_in: "Phase 13"
    evidence: "Phase 13 success criterion 2: 'Before any evaluation it freezes and hashes docs/research/universe/research-universe-v1.toml (DRAFT to FROZEN, D-09)'. Phase 11 CONTEXT D-09 explicitly allows shipping the manifest as DRAFT when volume data does not exist yet."
human_verification:
  - test: "Open the official Binance page Event-Algo-Order-Update in a browser and compare the ALGO_UPDATE status list (NEW / TRIGGERING / FINISHED / REJECTED / EXPIRED) and the o.rm field with EXECUTION_SPEC.md section 6.1"
    expected: "Status meanings and field names match the docs; if not, amend EXECUTION_SPEC.md 6.1 and SOURCES.md"
    why_human: "WebFetch returned only the JS documentation shell. The wording is taken from the installed SDK model (field descriptions) plus a search summary. Tracked for re-confirmation before Phase 18 (11-VALIDATION manual-only row, D044 follow-up 7)."
  - test: "Confirm on current Binance docs that a market-data WebSocket connection has a 24-hour lifetime, and that the user-data-streams landing page says what BINANCE.md / ARCHITECTURE.md / SECURITY_AND_OPERATIONS.md attribute to it"
    expected: "24h lifetime figure confirmed (or corrected), verify markers removed or figure amended"
    why_human: "Both pages returned 302 then HTTP 202 empty body to curl; SOURCES.md records them as NOT fetched. The docs now say 'believed to' and carry verify markers, so nothing false is asserted, but the figure is unconfirmed."
  - test: "User review of the D043 auto-mode pre-registered numbers (N = 25 variants, G1 >= 100 trades pooled and >= 30 per fold, G2 lower 95% bootstrap bound > 0, G3 Holm at alpha 0.05, G4 drawdown <= 20%, G5 last-20% single-use holdout, 40/40/20 split)"
    expected: "User accepts or overrides each number BEFORE the first Validation run; any change after freeze forces v1.2.0 and a new lineage"
    why_human: "D043 states these are Claude's auto-mode recommended defaults and 'the user may override any number before the first Validation run'. The protocol's own power note admits the 100-trade floor may be unreachable at the decided dataset depth (trade rate unmeasured until the Phase 14 simulator; Phase 13 SC2 reports the shortfall). A pre-registration is a judgment call the owner should ratify."
  - test: "User ratification of the ApprovalResult value set PENDING / APPROVED / SKIPPED / EXPIRED recorded in GLOSSARY section 10"
    expected: "User confirms or edits the set (GLOSSARY says 'pending user ratification'; D044 follow-up 9; STATE blocker)"
    why_human: "The set was a Phase 3 planner assumption (D-10); the glossary is the enum source of truth (D016) so the owner must ratify it."
  - test: "Spot-check three orchestrator-fetched exchange facts against the live Binance pages: 200 conditional orders account-wide (change-log 2025-12-29), WebSocket /public /market /private split and 2026-04-23 legacy decommission, workingType API default CONTRACT_PRICE"
    expected: "All three match the docs"
    why_human: "Fetched through WebFetch whose small summariser model produced the extracts (SOURCES.md rates them MEDIUM confidence). Docs keep 'verify against current Binance docs before implementation' markers. The change-log entry is the only evidence for the account-wide 200 limit and it contradicts the still-stale common-definition page."
---

# Phase 11: Decision Alignment (docs + params) Verification Report

**Phase Goal:** The canonical docs and the versioned parameter sets say what the user decided in D031-D039. Under D031, DECISIONS.md outranks docs, so conflicting doc text must be amended and no later phase may be planned against stale rules.
**Verified:** 2026-09-30
**Status:** human_needed
**Re-verification:** No, initial verification
**Base commit for diffs:** 679825c (HEAD f9def56, 37 commits, 72 files)

## Goal Achievement

The phase goal is achieved in the repository. Every ROADMAP success criterion has direct evidence in the files, the dispatcher and the full test suite are green, the 10 old parameter files and every old hash are untouched, and `src/` changed only in `src/domain/registry.py` (the `working_type` loader key). The status is `human_needed` rather than `passed` because five items cannot be closed by grep or test: two Binance facts that no fetched page confirms (ALGO_UPDATE status wording, 24h WebSocket lifetime), the auto-mode pre-registration numbers awaiting owner ratification, the ApprovalResult set awaiting ratification, and MEDIUM-confidence summarised fetches. None is a FAILED truth.

### Observable Truths (ROADMAP success criteria, the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | RESEARCH_PROTOCOL v1.1.0 pre-registers numeric thresholds, variant count with multiple-testing correction, single-use holdout; forbids human "pass" override | VERIFIED | Header `Protocol version: v1.1.0`, `Status: FROZEN`, `Frozen on: 2026-09-19` (unchanged, D013 clock not restarted), `Amended on: 2026-09-30`, `Supersedes: v1.0.1`, migration paragraph in section 0. Section 4 "Pre-registered thresholds (v1.1.0)": N = 25 per family; G1 >= 100 pooled trades and >= 30 per fold; G2 mean net R > 0 with lower 95% block-bootstrap bound > 0; G3 Holm-Bonferroni alpha 0.05 over counted variants; G4 drawdown <= 20%; G5 single-use last-20% holdout. Line 229: "A human may reject a candidate that passes; a human may never pass a candidate that fails (D032, D043)." Repeated in kill-gate paragraph. Holdout marker `docs/research/holdout_consumed.json` (schema `holdout-consumed/1`, `entries: []`, append-only rule in protocol). Three witnesses agree: header v1.1.0, DECISIONS row D043 "Research protocol v1.1.0 frozen", DOC_STATUS line names v1.1.0 (log entry 2026-09-30). `research-gate.yml` now derives V from the header and requires `protocol vV frozen` and `vV` in DOC_STATUS; negative test `tests/test_research_gate_negative.py` runs the real workflow step against synthetic triplets and passes. D030 firing rule text intact (PR-03 PASS; "fewer than three" absent). BACKTEST_SPEC "TBD" sentence replaced by pointer to protocol section 4. No remaining "thresholds remain TBD" / "human pass" wording in docs. |
| 2 | SAFE_MODE is entries-only with protective re-placement and close fallback (SECURITY_AND_OPERATIONS / RUNBOOK / EXECUTION_SPEC); daily loss matches D033; margin rules match D035 | VERIFIED | SECURITY_AND_OPERATIONS section 7: "blocks new entry orders only", protective and reduce-only always allowed, missing/canceled SL re-placed at original plan SL never wider, rejected/unacknowledged SL leads to reduce-only market close then HIGH alert, DB failure must not block risk reduction, supersedes "no new live order placement" and the cancel-only reconciler decision (Phase 08 D-03 / Phase 09 D-02). RUNBOOK sections 1, 3, 6, 8 updated the same way. EXECUTION_SPEC section 9 re-place/close ladder, section 11 emergency controls include a protect action. Grep for "no new live order", "block new live order", "disable new live order", "NO NEW ORDERS", "block new orders" over docs/, AGENTS.md, PROJECT.md returns only the deliberate "supersedes" sentences. RISK_MANAGEMENT section 8: UTC day (00:00 UTC = 07:00 Asia/Ho_Chi_Minh), loss = realized PnL + commissions + funding, base = equity at UTC day start, WARNING 0.5% / DAILY_STOP 1.0%, DAILY_STOP cancels pending entries and keeps SLs (matches D033 row verbatim in substance; the old `daily loss stop: TBD` is gone). Section 9: ISOLATED, 5x cap, marginType and leverage set explicitly, liquidation beyond SL with buffer (value deferred to Phase 22, D035 fixes none), available-margin check includes resting entries (matches D035). Canonical quantization order in section 11 matches `src/risk/quantization.py` (floor, MIN_QTY_REJECT, NOTIONAL_REJECT, UTILIZATION_REJECT) and AGENTS.md / PROJECT.md / protocol section 2 now restate it by pointer. |
| 3 | Exchange facts corrected: 200 conditional orders account-wide; algo trigger-time semantics (FINISHED not filled; REJECTED/EXPIRED at trigger); WS URL split; MARKET_LOT_SIZE / PERCENT_PRICE; "HMAC-checked" removed for TradingView | VERIFIED (source confidence MEDIUM, see human items 1, 2, 5) | EXECUTION_SPEC section 12: 200 open conditional orders across all symbols, `MAX_NUM_ALGO_ORDERS` filter removed 2025-12-29, notes the stale common-definition page. No "per symbol" residue. Section 6.1 (new): status table, "FINISHED does not mean filled", REJECTED/EXPIRED can occur at trigger, failure reason in `o.rm`, no margin check before trigger. BINANCE.md section 3: `/public`, `/market`, `/private` paths, legacy `/ws` retired 2026-04-23; section 6: `workingType` sent explicitly as MARK_PRICE because API default is CONTRACT_PRICE; section 7: MARKET_LOT_SIZE and PERCENT_PRICE; unverified F-056 audit claims explicitly labelled unverified. RISK_MANAGEMENT section 12 constraint snapshot lists market_lot_size, percent_price, working_type, margin_type, leverage, equity_used. Grep "HMAC" across docs/, AGENTS.md, STACK.md, PROJECT.md: no "HMAC-checked" remains; the only hits say HMAC is NOT available (TRADINGVIEW.md section 5, SECURITY_AND_OPERATIONS). AGENTS.md and `.planning/research/STACK.md` FastAPI row now reads "secret URL path + source-IP allow-list; TradingView cannot sign requests". Wrong coin-futures citations replaced (grep `coin-futures` over docs/, AGENTS.md, PROJECT.md returns 0 hits). SOURCES.md has a dated register (2026-09-30) with retrieval method and confidence per page; unretrieved pages are recorded as "Not fetched" and their statements keep verify markers. |
| 4 | New versioned param sets: partial_fill_fraction = 1.0, taker entry fee, working_type = MARK_PRICE; point-in-time universe defined and hashed; old sets never edited | VERIFIED for sets; universe hash DEFERRED (see Deferred / Warnings) | Five new files: `params/trend-pullback/baseline-v4.toml`, `params/breakout-retest/baseline-v4.toml`, `params/range-mr/baseline-v4.toml`, `params/trend-pullback/baseline-no-trade-v2.toml`, `params/trend-pullback/baseline-simple-trend-v2.toml`. Each has `fee_rate_entry = 0.0005` (taker), `partial_fill_fraction = 1.0`, `working_type = "MARK_PRICE"`, `strategy_version = "v3.0.0"`. Diff against the v3 sets changes only these keys plus the version (verified by `diff` of comment-stripped files). `git diff --name-status 679825c HEAD -- params` shows only `A` entries: the ten old parameter files have zero modifications. Pins appended only (`tests/fixtures/phase4/parameters.json` 72 insertions, 0 deletions); `_EXPECTED_CANDIDATE_IDS` updated. `src/domain/registry.py`: `working_type` added to STRATEGY_KEYS / STRING_KEYS with closed set {MARK_PRICE, CONTRACT_PRICE}, not a cost key so `cost_model_hash` is unaffected; loader tests added (189 lines in tests/test_registry.py). Universe manifest `docs/research/universe/research-universe-v1.toml`: status DRAFT, top_n 12, rule = trailing 30d mean daily quote volume at dataset start date, include_delisted = true, freeze procedure documented, live-5 stated as a separate list, placed outside `params/` so family scans do not pick it up. It lists NO symbols and `content_sha256 = ""` because the ranking data does not exist yet. D-09 explicitly permits a DRAFT manifest with the freeze owned by Phase 13, and Phase 13 SC2 states the freeze-and-hash step. Hashing tooling exists (`python -m scripts.decision_alignment.universe`). So the "defined point-in-time and hashed" clause is met as rule + tooling, with the actual hash deferred by design. |
| 5 | GLOSSARY synonym codes resolved; ApprovalResult and emitted reason codes listed | VERIFIED (with follow-up warning) | GLOSSARY section 9.1: one canonical code per concept (17 codes referenced from `src/` plus reserved INSUFFICIENT_MARGIN); 9.2 table of five deprecated aliases (QUANTIZATION_REJECT, MIN_NOTIONAL_REJECT, RISK_LIMIT, CORRELATED_RISK_LIMIT, DAILY_STOP as rejection reason) each mapped to its canonical replacement; 9.3 plain-string codes emitted outside the enum with emitting files; 9.4 SAFE_MODE entry reasons; section 10 ApprovalResult PENDING / APPROVED / SKIPPED / EXPIRED with the `action_to_result` mapping. I cross-checked against the code: `RejectionReason` has 23 members and every one appears in section 9 (script check, none missing); `ApprovalResult` is exactly [PENDING, APPROVED, SKIPPED, EXPIRED]; `action_to_result` in `src/approval/binding.py:129` matches the documented mapping. Per D-15 the code enum is not renamed in this phase. |

**Score:** 5/5 truths verified (0 behavior-dependent truths; this is a documentation and parameter phase, no runtime state-transition invariants asserted).

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|--------------|----------|
| 1 | Universe manifest FROZEN with symbols, selection_date and content_sha256 | Phase 13 | Phase 13 SC2: "freezes and hashes docs/research/universe/research-universe-v1.toml (DRAFT to FROZEN, D-09)" |
| 2 | Enum cleanup of five deprecated RejectionReason aliases | Phase 12 (per D044) | See Warning W2: assigned in DECISIONS but not written into Phase 12's ROADMAP success criteria |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `docs/research/RESEARCH_PROTOCOL.md` | v1.1.0 frozen with G1-G5 | VERIFIED | Substantive, cross-witnessed, gate-tested |
| `docs/research/holdout_consumed.json` | append-only consumed marker | VERIFIED | schema `holdout-consumed/1`, empty entries; writer is a Phase 26 item (D044 follow-up 3), not claimed here |
| `.github/workflows/research-gate.yml` | version-bound freeze check | VERIFIED | Header-derived V, witnesses 2 and 3 bound to V; executed by `tests/test_research_gate_negative.py` |
| `.github/workflows/registry-gate.yml` | runs alignment gates + tests | VERIFIED | New step `verify_decision_alignment.py all`; pytest list extended |
| `params/**/baseline-v4 / no-trade-v2 / simple-trend-v2` (5 files) | new sets | VERIFIED | See truth 4 |
| `docs/research/universe/research-universe-v1.toml` | DRAFT manifest | VERIFIED as DRAFT | Deliberately empty symbols and hash |
| `src/domain/registry.py` | `working_type` key | VERIFIED | Loader + closed set, tests, mypy clean |
| `scripts/verify_decision_alignment.py` + `scripts/decision_alignment/*.py` (7 modules) | read-only gates | VERIFIED | Run below |
| `docs/GLOSSARY.md`, `docs/SOURCES.md`, `docs/DECISIONS.md` (D043-D045), `docs/DOC_STATUS.md` | bookkeeping | VERIFIED | Content read, see truths |
| `.planning/REQUIREMENTS.md` | 13 new REQ-IDs | VERIFIED | See requirements table |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| protocol header version | DECISIONS D043 + DOC_STATUS line | research-gate.yml witnesses | WIRED | Real workflow step exercised by negative tests |
| new param TOML | `src/domain/registry.py` loader | `load` + closed-set check | WIRED | tests/test_registry.py, pins in phase4 fixtures |
| GLOSSARY section 9 | `RejectionReason` enum | GL-02/GL-03 gates + my independent script | WIRED | 23/23 members present |
| alignment gates | CI | registry-gate.yml step | WIRED | Also invoked locally below |
| RISK_MANAGEMENT section 11 | `src/risk/quantization.py` | documented order equals code order | WIRED | MIN_QTY, NOTIONAL, UTILIZATION reject order confirmed in source |
| new REQ-IDs | ROADMAP phases 13-26 | Requirements lines + traceability rows | WIRED | see below |

### Data-Flow Trace (Level 4)

Not applicable: no rendering of dynamic data. The only data-consuming code change (`working_type`) is a loader key exercised by tests.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All decision-alignment gates | `.venv/Scripts/python scripts/verify_decision_alignment.py all` | 64 PASS lines (PR-01..10, PA-01..06, UN-01..05, OR-01..10b, EX-01..08 incl. EX-06a, AU-01..06, GL-01..06, RQ-01..05, DC-01..06), final line `ALL_PASS all`, exit 0 | PASS |
| Targeted suites (freeze, clock, negative, registry, paper-freeze, binding, alignment) | `pytest tests/test_kill_gate_docs.py ... tests/test_decision_alignment*.py tests/test_paper_freeze.py tests/test_backtest_binding.py -q` | all passed (1 skipped) | PASS |
| Full suite (run once) | `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider -x` | exit clean, reached 100% with no failure | PASS |
| Lint / types on phase files | `ruff check scripts/decision_alignment ... tests/test_decision_alignment*.py`; `mypy src/domain/registry.py` | "All checks passed!" / "no issues found" | PASS |
| Old params untouched | `git diff --name-status 679825c HEAD -- params` | five `A`, zero `M` | PASS |
| GLOSSARY vs enum | Python script comparing `RejectionReason` names with section 9 text | 23 members, none missing | PASS |

The dispatcher is a project-authored checker over the same files it verifies, so I did not rely on it alone: I re-derived truths 1-5 from the documents, the parameter files and the code directly, as shown in the evidence column.

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes are declared or present for this phase. SKIPPED (not applicable).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RSCH-01 | 11-01, 11-02, 11-03, 11-08 | Research protocol frozen before parameter work | SATISFIED | v1.1.0 frozen, three witnesses, gate; marked `[x]` in REQUIREMENTS.md |
| RSCH-02 | 11-01, 11-02, 11-03, 11-08 | Three candidate families specified independently | SATISFIED | Family param sets v4 for all three families; marked `[x]` |
| RISK-02 | 11-04, 11-05, 11-06, 11-08 | Portfolio limits, DAILY_STOP states, fail closed | SATISFIED (docs); see W3 | D033 definition and D035 margin rules in RISK_MANAGEMENT; marked `[x]` |
| EXEC-02 | 11-04, 11-05, 11-06, 11-08 | Reconciliation, orphan sweeps, SAFE_MODE | SATISFIED (docs); see W3 | Entries-only ladder, orphan-with-working-entry carve-out; marked `[x]` |
| OPS-01 | 11-04, 11-05, 11-08 | SAFE_MODE blocks entries, RUNBOOK | SATISFIED | RUNBOOK + SECURITY_AND_OPERATIONS; already `[x]`, traceability row Complete |
| RISK-03 | 11-07 | SL never loosened; re-place restores original | REGISTERED, Pending | Phase 20, `[ ]` |
| RISK-04 | 11-07 | No averaging down / no revenge sizing | REGISTERED, Pending | Phase 19, `[ ]` |
| BKTS-04 | 11-07 | Experiment record fields | REGISTERED, Pending | Phase 14, `[ ]` |
| EXEC-04 | 11-07 | Constraint snapshot persisted per plan | REGISTERED, Pending | Phase 17, `[ ]` |
| EXEC-05 | 11-07 | User-data stream drives fills | REGISTERED, Pending | Phase 18, `[ ]` |
| EXEC-06 | 11-07 | Manual emergency controls | REGISTERED, Pending | Phase 20, `[ ]` |
| EXEC-07 | 11-07 | Protective-order assumptions as registry params | REGISTERED, Pending | Phase 19, `[ ]` |
| DOMN-04 | 11-07 | State transition validation | REGISTERED, Pending | Phase 17, `[ ]` |
| OPS-03 | 11-07 | Restart sequence | REGISTERED, Pending | Phase 24, `[ ]` |
| OPS-04 | 11-07 | Python version + git revision in health | REGISTERED, Pending | Phase 24, `[ ]` |
| OPS-05 | 11-07 | Operational alerts incl. daily-loss | REGISTERED, Pending | Phase 20, `[ ]` |
| OPS-06 | 11-07 | Secrets handling (.env 0600 + disk encryption, D042) | REGISTERED, Pending | Phase 13, `[ ]` |
| GOV-02 | 11-07 | Affirmative live-enable prerequisites | REGISTERED, Pending | Phase 26, `[ ]` |

All 13 new IDs exist in the v1 list, in the traceability table with a target phase, and in the `**Requirements**:` line of the target ROADMAP phases (14, 17, 18, 19, 20, 24, 26, 13). None is marked complete. Coverage counts read 43 total / 43 mapped (30 + 13). Dispositions for the audit's F-116 items, including the deliberately dropped ones (DATA_MODEL `trades`, `feature_snapshots`, `experiment_runs` not built; application-level secret encryption not required in V1; F-128 covered by OPS-02), are recorded in DECISIONS D045, so nothing was dropped silently. No orphaned requirements: ROADMAP Phase 11 maps exactly RSCH-01, RSCH-02, RISK-02, EXEC-02, OPS-01.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `docs/trading/RISK_MANAGEMENT.md` | 52 | `max risk for one correlated cluster: TBD` | Info | Pre-existing placeholder in a file this phase modified; not introduced by Phase 11 and not a D031-D039 topic (the cluster cap is enforced in code already). Not treated as an unreferenced debt marker in the FIXME/XXX sense; noted for completeness. |
| `docs/research/RESEARCH_PROTOCOL.md` | 369 | `regime taxonomy (TBD until the SPEC is frozen)` | Info | Pre-existing, unrelated to thresholds. |
| `docs/research/families/*.md` | 143/155/160 | "value is TBD until exercised on real data per RESEARCH_PROTOCOL.md section 0" | Info | Refers to strategy parameter values, which v1.1.0 explicitly leaves as registry values (section 0 last paragraph). Slightly dated cross-reference, no conflict. |
| `scripts/decision_alignment/*.py`, tests | various | strings `TBD` / `F-XXX` | Info | Forbidden-phrase constants and test fixtures, not debt markers. |

No FIXME/XXX debt markers introduced. No stub or empty implementations found in the new scripts (each gate module returns real `(name, ok, detail)` results, backed by unit and negative tests).

### Human Verification Required

See the `human_verification` frontmatter; five items:

1. **ALGO_UPDATE status wording** (known open item): re-confirm on the official Binance page before Phase 18. Docs are honest about the provenance and keep verify markers, so this does not block Phase 12 planning.
2. **24h market WebSocket lifetime** (known open item) and the user-data-streams page: unconfirmed; docs say "believed to".
3. **Owner ratification of D043's auto-mode numbers** before the first Validation run, with awareness that the 100-trade floor may be unreachable.
4. **ApprovalResult value set** ratification (GLOSSARY section 10, STATE blocker).
5. **Spot-check of MEDIUM-confidence summarised fetches** (200 account-wide, WS split, workingType default).

### Warnings (not blockers)

- **W1 Universe not yet hashed.** SC4's "hashed" is met only as rule plus tooling; the manifest is DRAFT with empty `symbols` and `content_sha256`. Intentional (D-09) and explicitly scheduled in Phase 13 SC2, so classified as deferred, not a gap.
- **W2 Alias-cleanup ownership is not in Phase 12's ROADMAP text.** DECISIONS D044 and GLOSSARY 9.2 assign the five deprecated `RejectionReason` alias removals and the `tests/test_domain_enums.py` update to Phase 12, but Phase 12's Goal and Success Criteria in ROADMAP.md do not mention it (grep for RejectionReason / alias / enum cleanup finds nothing in Phase 12). The Phase 12 planner must pick it up from D044, or ROADMAP should be amended. Until then SC5's "synonym codes resolved" holds at documentation level only; the code enum still carries the aliases (by design, D-15).
- **W3 Requirement completion is documentation-level for RISK-02 and EXEC-02.** They are marked Complete, consistent with the phase's declared requirements and the GSD workflow, but the code still implements the older behaviour (cancel-only reconciler, no D033 daily-loss-from-Binance, no D035 margin guard); those are Phases 20-22. Docs now lead code, which D031 and the phase boundary accept. Reviewers should not read `[x]` as "D033/D034/D035 implemented".
- **W4 ROADMAP.md top-of-file Phase 11 checkbox is still `[ ]`** (line for "Phase 11" in the phase list) while its eight plan lines are `[x]`. Bookkeeping for the orchestrator on phase close, not a phase deliverable.

### Gaps Summary

No gaps. All five ROADMAP success criteria are delivered and independently confirmed: the documents say what D031-D039 decided, the five new parameter sets carry the decided values, and the old sets and hashes are byte-identical. The single literal shortfall (universe hash) is a documented deferral to Phase 13. The phase is left at `human_needed` because of the two known unconfirmed Binance facts, the unratified auto-mode pre-registration numbers, and the unratified ApprovalResult set.

---

_Verified: 2026-09-30_
_Verifier: Claude (gsd-verifier)_
