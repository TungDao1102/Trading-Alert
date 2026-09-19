---
phase: "01"
slug: "research-formalization"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-09-19"
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> DOCUMENTS-AND-GATES-ONLY phase: zero product code, zero test framework.
> Verification = git + grep + one GitHub Actions CI YAML gate + human doc review.
> Source: `01-RESEARCH.md` → `## Validation Architecture` (all commands below are quoted from there).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | none — no code under test; doc-review + grep checks + one CI YAML gate |
| **Config file** | `.github/workflows/research-gate.yml` (created this phase — Wave 0 gap) |
| **Quick run command** | `grep -n "Status.*FROZEN" docs/research/RESEARCH_PROTOCOL.md && grep -c "^\| D0" docs/DECISIONS.md` |
| **Full suite command** | Full research-gate workflow on a scratch PR: freeze check + identity-tuple check + registry-path tripwire + contradiction-token grep sweep |
| **Estimated runtime** | ~2 s local (quick); ~5 s checks locally, ~1–3 min via GitHub Actions (full) |

---

## Sampling Rate

- **After every task commit:** Run the quick check relevant to that plan's scope (see RESEARCH `## Validation Architecture` → `### Sampling Rate` per-plan greps)
- **After every plan wave:** Run the full sweep — all four `## Code Examples` grep blocks + DECISIONS row-count check (baseline 21 rows D001–D021 → post-phase 28 rows D022–D028) + existence of `docs/research/RESEARCH_PROTOCOL.md`, three family sheets, `.github/workflows/research-gate.yml`
- **Before `/gsd-verify-work`:** Research-gate workflow green as required status check + human reviewer confirms (a) no winner declared, (b) SPEC still TBD where unvalidated, (c) DOC_STATUS bump lists every touched doc
- **Max feedback latency:** seconds (local grep) / minutes (one Actions run)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| *rows authored by gsd-planner per plan — each doc/gate task gets a grep or CI-check command from RESEARCH `## Validation Architecture` → `### Automated vs Manual Verification`* | | | | | | | | | |

| 01-01-T1 | 01-01 | 1 | RSCH-01 | T-01-01 | Three-witness freeze specified; DRAFT only, no premature freeze | doc-review + grep | Select-String header DRAFT + 8-token presence sweep | docs/research/RESEARCH_PROTOCOL.md | ✅ green |
| 01-01-T2 | 01-01 | 1 | RSCH-01 | T-01-02 | No numeric parameter stated as fact; citations spot-checked | doc-review + grep | numeric-value region sweep returns empty | docs/research/RESEARCH_PROTOCOL.md | ✅ green |
| 01-02-T1 | 01-02 | 1 | RSCH-02 | T-01-04 | Transcribed rules only; unvalidated stays TBD | doc-review + grep | 7-slot presence + D012 footer match | docs/research/families/trend-pullback.md | ✅ green |
| 01-02-T2 | 01-02 | 1 | RSCH-02 | T-01-04 | Transcribed rules only; entry-quality metrics pre-committed | doc-review + grep | 7-slot presence + D012 footer match | docs/research/families/breakout-retest.md | ✅ green |
| 01-02-T3 | 01-02 | 1 | RSCH-02 | T-01-03 | No family selected; footer count 3; zero unqualified selection language | doc-review + grep | footer count exactly 3 + language sweep empty | docs/research/families/range-mr.md | ✅ green |
| 01-03-T1 | 01-03 | 1 | RSCH-03 | T-01-05 | Scope §7 and signal/execution/testing docs align to GLOSSARY with structures preserved | doc-review + grep | unqualified-autonomy-name and signal-context lifecycle sweeps empty | docs/00_PRODUCT_SCOPE.md | ✅ green |
| 01-03-T2 | 01-03 | 1 | RSCH-03 | T-01-05 | Timezone canonical; section-12 enums canonical; ownership clarified without enum change | doc-review + grep | stale-zone sweep empty + section-12 region sweep empty + D028 in 3 mirrors | docs/research/TRADING_STRATEGY_RESEARCH.md | ✅ green¹ |
| 01-03-T3 | 01-03 | 1 | RSCH-03 | T-01-06 | Numbers only; 28 DECISIONS rows; DOC_STATUS bump lists protocol | doc-review + grep | dup-header count 1 + row count 28 + DOC_STATUS entry present | docs/DECISIONS.md | ✅ green |
| 01-04-T1 | 01-04 | 2 | RSCH-01 | T-01-08 | Explicit human choice on required-status and gate-as-code exception before any external change | manual / human-decision | Decision recorded in SUMMARY (no automated command; checkpoints excluded from automated gates by convention) | n/a | ✅ green |
| 01-04-T2 | 01-04 | 2 | RSCH-01 | T-01-08 | Freeze is three-witness; gate checks freeze plus identity plus tripwire | CI + grep | FROZEN header plus freeze row plus workflow file present | .github/workflows/research-gate.yml | ✅ green |
| 01-04-T3 | 01-04 | 2 | RSCH-01 | T-01-07 | Decoy unregistered file fails the gate; tree clean after | CI negative test | non-zero with decoys, zero after cleanup, evidence recorded | .github/workflows/research-gate.yml | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*¹ 01-03-T2 check-note: the plan's stale-zone sweep (`git grep -n "Bangkok" -- docs/`) returns one hit — `docs/DECISIONS.md:30`, the D025 row recording "corrected from `Asia/Bangkok` to `Asia/Ho_Chi_Minh`". Append-only audit history, not a live zone; §9.3 canonical confirmed. Substance green; the sweep as written is over-strict. See 01-VERIFICATION.md orchestrator addendum.*

---

## Wave 0 Requirements

- [x] `docs/research/RESEARCH_PROTOCOL.md` — covers RSCH-01 (freeze header + §0–§6)
- [x] `docs/research/families/{trend-pullback,breakout-retest,range-mr}.md` — covers RSCH-02 (identical 7-slot template + TBD footer)
- [x] `.github/workflows/research-gate.yml` — executable gate for D-07 (freeze check + identity-tuple check + registry-path tripwire; required-status-check repo setting step included)
- [x] DECISIONS rows D022–D028 (21 → 28) + DOC_STATUS.md bump — covers RSCH-03
- [x] Gate negative-test evidence (failing scratch-PR run URL) — acceptance proof for D-07

*"Existing infrastructure covers all phase requirements" is NOT true for this phase — the stubs above are the Wave 0 work.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Family sheets genuinely comparable, no de-facto winner language | RSCH-02 | Judgment — greps pass on synonyms like "natural default" | Read all three sheets side by side; flag comparative adjectives without backtest+OOS qualifiers |
| Protocol freezes methodology, pins no parameter values | RSCH-01 | Judgment — no ATR/RR/expiry value stated as fact | Read protocol §5; any numeric parameter stated as fact fails |
| C1–C7 edits preserve each doc's purpose | RSCH-03 | Judgment — scope-creep check | Diff review restricted to contradiction scope; out-of-scope renames reverted or get own DECISIONS row |
| C7 ownership note reads as clarification | RSCH-03 | Judgment — Signal.APPROVED → Plan.APPROVED → Order.PLANNED must be applicable by future implementer | Read GLOSSARY §2/§3 note; must not introduce a new enum |
| Freeze-timing decision recorded | RSCH-01 | Judgment — batch vs separate beat | Reviewer confirms; DECISIONS freeze row records which |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s (local) / < 5min (Actions)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-09-19 (orchestrator direct audit; no auditor subagent spawned — docs-only mechanical fill per user direction)

## Validation Audit 2026-09-19
| Metric | Count |
|--------|-------|
| Gaps found | 4 (map rows missing, Wave-0 stale, frontmatter draft, sign-off pending) |
| Resolved | 4 |
| Escalated | 0 |
