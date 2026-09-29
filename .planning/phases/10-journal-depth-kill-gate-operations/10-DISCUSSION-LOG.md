# Phase 10: Journal Depth + Kill-Gate Operations - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-29
**Phase:** 10-Journal Depth + Kill-Gate Operations
**Areas discussed:** Analytics engine shape + determinism, Metric definitions (MFE/MAE, execution quality, approval delay, slices), Kill-gate state machine + terminal outcome, Dashboard delivery form, Persistence + provenance

---

## Analytics engine shape + determinism

| Option | Description | Selected |
|--------|-------------|----------|
| Pure deterministic read-only package, digest-stamped | stdlib+Decimal, frozen dataclasses, byte-identical reports, edge adapters for I/O | ✓ |
| Ad-hoc notebook/SQL queries | Faster to start, not reproducible, no digest, drifts from METRICS.md | |

**User's choice:** Pure deterministic package, digest-stamped, read-only (auto-selected recommended default, `--auto`)
**Notes:** Mirrors `src/backtest/report.py` and `paper_records_digest` contracts.

---

## Metric definitions

| Option | Description | Selected |
|--------|-------------|----------|
| METRICS.md-verbatim, full report always visible, INCOMPLETE bucket | Low-n flagged not hidden; uncertainty shown with every estimate | ✓ |
| Favorable-slice highlights | Contradicts METRICS §5 "full report must remain visible" | |

**User's choice:** METRICS.md-verbatim, full report always visible (auto-selected recommended default)
**Notes:** MFE/MAE in price and R; three METRICS §3 reports for approval-delay impact.

---

## Kill-gate state machine + terminal outcome

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic D013 evaluator, journaled terminal INSUFFICIENT_EDGE, fail-closed live-disabled | Both budgets exhausted with none passing; never auto-enables live | ✓ |
| Advisory dashboard number, manual interpretation | Not auditable; gate outcome not recorded | |

**User's choice:** Deterministic evaluator, journaled terminal outcome (auto-selected recommended default)
**Notes:** RESEARCH_PROTOCOL "OR" wording conflicts with D013; D013 authoritative — planner records the resolution as a DECISIONS entry.

---

## Dashboard delivery form

| Option | Description | Selected |
|--------|-------------|----------|
| Static deterministic generated report + JSON sidecar, dual-universe | CLI/PowerShell wrapper, no web server | ✓ |
| Live FastAPI-served dashboard | Adds edge surface + failure modes; not a measured need | |

**User's choice:** Static deterministic report (auto-selected recommended default)
**Notes:** Live-5 vs research universe shown side by side; empty slices labelled "no data".

---

## Persistence + provenance

| Option | Description | Selected |
|--------|-------------|----------|
| Derived views + append-only KILL_GATE_EVALUATION JournalEvents, full provenance, unpooled evidence | No new tables unless proven necessary | ✓ |
| New metrics tables with pooled headline numbers | Schema migration + hides evidence class | |

**User's choice:** Derived views, journaled gate events (auto-selected recommended default)
**Notes:** Backtest / paper / live evidence labelled separately.

---

## Claude's Discretion

Module layout, report field names, HTML vs Markdown, JSON schema, journal read adapter, CLI naming, low-n threshold, MFE/MAE bucketing, research-clock-start source, D013 resolution wording, plan slicing.

## Deferred Ideas

Live web dashboard, Telegram analytics commands, automated TP/SL tuning recommendations, REFN-01–05, multi-venue analytics.
