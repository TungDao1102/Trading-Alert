---
phase: "01"
slug: "research-formalization"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
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

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `docs/research/RESEARCH_PROTOCOL.md` — covers RSCH-01 (freeze header + §0–§6)
- [ ] `docs/research/families/{trend-pullback,breakout-retest,range-mr}.md` — covers RSCH-02 (identical 7-slot template + TBD footer)
- [ ] `.github/workflows/research-gate.yml` — executable gate for D-07 (freeze check + identity-tuple check + registry-path tripwire; required-status-check repo setting step included)
- [ ] DECISIONS rows D022–D028 (21 → 28) + DOC_STATUS.md bump — covers RSCH-03
- [ ] Gate negative-test evidence (failing scratch-PR run URL) — acceptance proof for D-07

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

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s (local) / < 5min (Actions)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
