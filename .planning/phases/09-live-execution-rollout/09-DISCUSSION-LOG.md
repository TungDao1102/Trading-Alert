# Phase 9: Live Execution Rollout - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-28
**Phase:** 9-Live Execution Rollout
**Areas discussed:** Live entry + protective-exit wiring, Position modes + partial-fill protective sizing, Placement-time revalidation + DAILY_STOP + algo headroom, Live safety posture + rollout scope, Execution module shape + purity + journaling

---

## Live entry + protective-exit wiring

| Option | Description | Selected |
|--------|-------------|----------|
| LIMIT-zone + CONDITIONAL algo exits, re-verified SDK, no-blind-recovery | Entry on normal endpoint, SL/TP via POST /fapi/v1/algoOrder; SDK + changelog re-verified at plan time; user-data WS preferred + REST tick; query-by-ID before retry | ✓ |
| MARKET entry with assumed-legacy conditionals | Simpler fill, worse fit for swing setups and limited availability; legacy endpoint assumption violates Dec-2025 migration | |

**User's choice:** LIMIT-zone + CONDITIONAL algo exits, re-verified SDK, no-blind-recovery (auto-selected recommended default, `--auto` mode — no interactive prompt)
**Notes:** Follows EXECUTION_SPEC §§1–2/7/10 and the 08-04 SDK verification precedent (17.4.0, no REST signature change; Algo semantics WS-side).

---

## Position modes + partial-fill protective sizing

| Option | Description | Selected |
|--------|-------------|----------|
| Dynamic mode detection, mode-correct protectives, filled-quantity sizing | Detect one-way vs hedge at startup/placement; closePosition vs reduceOnly+positionSide per mode; protectives sized to actual fills; entry-without-protective → SAFE_MODE | ✓ |
| One-way-only template sized to planned quantity | Assumes mode, oversizes protection on partials — rejected: violates EXECUTION_SPEC §5/§8 | |

**User's choice:** Dynamic detection, mode-correct protectives, filled-quantity sizing (auto-selected recommended default, `--auto` mode — no interactive prompt)
**Notes:** Composes with Phase-8 reconciler divergence ENTRY_WITHOUT_PROTECTIVE → SAFE_MODE; sweeper never places rescue protection.

---

## Placement-time revalidation + DAILY_STOP + algo headroom

| Option | Description | Selected |
|--------|-------------|----------|
| Live exchangeInfo revalidation, reconciled-state gates, strict fail-closed | Tick/step/min/notional + 200-algo headroom rechecked at placement; caps + DAILY_STOP on live positions; stale/uncertain → NO_TRADE | ✓ |
| Plan-time snapshot with best-effort warnings | Cheaper, risks stale constraints placing invalid orders with money attached — rejected | |

**User's choice:** Live revalidation, reconciled-state gates, strict fail-closed (auto-selected recommended default, `--auto` mode — no interactive prompt)
**Notes:** Extends Phase-5 D-03/D-04 (registry TTL, enforcement order, reason-code vocabulary) to the live placement path; never depends on removed MAX_NUM_ALGO_ORDERS filter.

---

## Live safety posture + rollout scope

| Option | Description | Selected |
|--------|-------------|----------|
| Locked-down credentials, explicit enablement, smallest-capital live-5 | No-withdrawal + IP allowlist + off-source encrypted secrets; LIVE_ORDERS_DISABLED default; secret-free structured logs; health green; smallest capital live-5 only | ✓ |
| Permissive keys with orders enabled at deploy | Faster, violates SECURITY_AND_OPERATIONS §§1–2 — rejected | |

**User's choice:** Locked-down credentials, explicit enablement, smallest-capital live-5 (auto-selected recommended default, `--auto` mode — no interactive prompt)
**Notes:** Emergency controls (cancel pending, disable new orders, close per explicit action, SAFE_MODE) are acceptance gates for the first order per EXECUTION_SPEC §11.

---

## Execution module shape + purity + journaling

| Option | Description | Selected |
|--------|-------------|----------|
| Pure manager reusing canonical contracts, journaled | New src/execution/ manager calls identical src/risk + order_ids + approval gate + reconciler/SAFE_MODE; stdlib+Decimal only; SDK in adapters; every outcome a JournalEvent | ✓ |
| Standalone live-trading module with local sizing | Duplicates risk math — rejected: breaks backtest/paper/live parity, the core V1 guarantee | |

**User's choice:** Pure manager reusing canonical contracts, journaled (auto-selected recommended default, `--auto` mode — no interactive prompt)
**Notes:** Tracer-first precedent: placement slice first, then modes/partials/headroom; fixtures under tests/fixtures/phase9/.

---

## Agent's Discretion

- Module splits inside `src/execution/`, adapter method additions, reconciler tick cadence, limit-price policy (zone edge vs mid, TIF), TP1/TP2 mechanics, expiry/invalidation wiring, health-check mechanics, enablement-flag storage, plan slicing — at planner/researcher discretion within D-01–D-05.
- No user "you decide" turns occurred — `--auto` mode resolves all areas to recommended defaults by design (modes/auto.md).

## Deferred Ideas

- Journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10.
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements.
- FastAPI inbound webhook receiver for Telegram callbacks → deferred (V1 uses PTB polling).
- TWAP/VP execution algos (`binance-sdk-algo`) → Phase 3+ evaluation only, not V1.
