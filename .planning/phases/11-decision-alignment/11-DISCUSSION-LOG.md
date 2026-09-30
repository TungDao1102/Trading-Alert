# Phase 11: Decision Alignment - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-30
**Phase:** 11-decision-alignment
**Areas discussed:** Protocol v1.1.0 pre-registration, Parameter sets and universe, Doc amendment method, Exchange-fact corrections, GLOSSARY and F-116 requirements, Verification

Mode: `--auto --all`; no AskUserQuestion was used. The recommended option was chosen for each question.

---

## Protocol v1.1.0 pre-registration
- [auto] In-place edit of v1.0.1 vs new v1.1.0? → v1.1.0 with a Supersedes line (protocol §0 requires it for a semantic change).
- [auto] Numeric thresholds? → 100 trades, lower-95% bootstrap expectancy > 0 after costs, DD ≤ 20%, N=25 variants, Holm–Bonferroni α=0.05, last-20% single-use holdout. Defaults only; the planner checks feasibility before the freeze.
- [auto] Human override? → reject-only (D032).

## Parameter sets and universe
- [auto] Edit old sets vs new versions? → new versions, old untouched (F-810).
- [auto] Universe manifest now vs Phase 13? → rule and slots now as DRAFT; freeze in Phase 13 when volume data exists.

## Doc amendment method
- [auto] Rewrite vs targeted amendments? → targeted, each citing its decision ID, ordered by authority.

## Exchange-fact corrections
- [auto] Source of facts? → current official Binance docs, recorded in SOURCES.md; not from memory.

## GLOSSARY and F-116
- [auto] Rename code now? → no; record as a follow-up for the owning phase.
- [auto] Lost MUSTs? → new REQ-IDs with traceability, or an explicit DECISIONS exclusion.

## Verification
- [auto] How? → verify script + existing registry/hash tests + research-gate update.

## Claude's Discretion
File naming, wording, REQ-ID numbering, verify-script layout.

## Deferred Ideas
Code implementation of the decisions (phases 12–24), code enum renames, real-data universe freeze (Phase 13).
