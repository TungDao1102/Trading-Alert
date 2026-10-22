# Phase 21: Account Equity + Daily Loss from Binance - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-22
**Phase:** 21-account-equity-daily-loss
**Areas discussed:** Equity source and field, Daily loss and persisted day state, DAILY_STOP behaviour, Portfolio caps and atomic reservation, Constraint snapshot and TP unblocking

Mode: `--auto`, single pass (no AskUserQuestion). Every area took the recommended option.

---

## Equity source and field
[auto] Selected all gray areas. Q: equity field? -> REST v3/account (margin-balance style total, not availableBalance) + ACCOUNT_UPDATE; REST arbiter. Alternative: availableBalance (rejected: Phase 22 margin check). Stale age stays NOT_CONFIGURED (owner number).

## Daily loss and persisted day state
[auto] Q: where does day state live? -> PostgreSQL via Phase 17 stores; missing state with exposure = fail closed. Alternative: in-memory (rejected: restart resets the day). Q: funding source? -> REST component labelled unverified on Demo (income returned 0 rows); owner decides trade-list-only counting (O-2).

## DAILY_STOP behaviour
[auto] Q: stop semantics? -> cancel pending entries, keep stops, alert; sticky until next UTC day. Alternative: lift on equity recovery (rejected).

## Portfolio caps and atomic reservation
[auto] Q: reservation? -> same DB transaction as the approval; released on every terminal state; rebuilt on restart. Alternative: in-memory counter (rejected).

## Constraint snapshot and TP unblocking
[auto] Q: snapshot? -> fill equity from the live source; COMPLETE only with Phase 22 inputs; add the test from 21-NOTES.

## Claude's Discretion
Module placement, table names, locking mechanism, test layout, plan split.

## Deferred Ideas
Margin/leverage/liquidation (22), live wiring (24), mainnet PnL semantics (24/26), Phase 20 review fixes.
