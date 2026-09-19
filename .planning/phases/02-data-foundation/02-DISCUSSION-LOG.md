# Phase 2: Data Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-19
**Phase:** 2-Data Foundation
**Areas discussed:** Bootstrap scope, Storage layout, OI + funding capture, Quality + backup drill

---

## Gray-area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Bootstrap scope | Live-5 first vs research slice, depth, intervals | ✓ |
| Storage layout | Parquet partitioning, raw/derived, PG vs DuckDB | ✓ |
| OI + funding capture | Cadence, symbols, gap policy | ✓ |
| Quality + backup drill | Checks strictness, coverage query, drill scope | ✓ |

**User's choice:** All four areas selected.
**Notes:** No prior CONTEXT for Phase 2; Phase 1 CONTEXT + frozen RESEARCH_PROTOCOL v1.0.0 + DATA_PIPELINE used as grounding.

---

## Bootstrap scope

| Option | Description | Selected |
|--------|-------------|----------|
| Live-5 only first | BTC/ETH/BNB/SOL/XRP only, fastest to green (recommended) | ✓ (via bundle) |
| Full research slice | 10–15 symbols now, heavier 1m backfill | |
| Hybrid (5 full + rest light) | Live-5 full + 1H/4H only for rest | |

**User's choice:** "tôi không có kiến thức về phần này. bạn hay lựa chọn cái tốt nhất cho tôi" (I don't have knowledge about this part — you choose the best for me).
**Notes:** User delegated the choice to the agent. Agent applied the recommended option (live-5 first, bounded depth, all three intervals, official-SDK backfill) and confirmed it in the bundle gate below.

---

## Bundle confirmation (all four areas)

| Option | Description | Selected |
|--------|-------------|----------|
| OK — lock 4 nhóm theo đề xuất | Live-5 first, bounded depth; Parquet raw-immutable + derived-versioned, DuckDB + PG split; 5-min day-one OI + funding, flag-never-fabricate gaps; fail-closed quality + CLI/DuckDB coverage + automated backup drill | ✓ |
| Muốn nghe giải thích thêm | Detailed trade-off walkthrough per group | |

**User's choice:** OK — lock 4 nhóm theo đề xuất.
**Notes:** Single confirmation gate replaced the 16-question default flow after the user delegated. Decisions D-01–D-12 written to CONTEXT.md from this bundle.

---

## the agent's Discretion

- All four areas delegated by the user to the agent; agent locked recommended defaults and the user confirmed the bundle.
- CLI names, Parquet filename conventions, DuckDB view names, scheduler shape, and drill script layout left to planner/researcher discretion within D-01–D-12 semantics.

## Deferred Ideas

None — discussion stayed within phase scope. Research-universe expansion, 15m support, and OI/funding as strategy features stay in their scheduled phases.
