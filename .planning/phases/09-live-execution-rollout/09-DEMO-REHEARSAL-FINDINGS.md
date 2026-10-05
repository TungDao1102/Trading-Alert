# Phase 9 Demo rehearsal: findings and open work (2026-10-05)

Handoff note so nothing is lost. Runner: `scripts/demo_rehearsal.py` (quick 261005-tx9). Host: `demo-fapi.binance.com` only. Evidence files: `09-DEMO-REHEARSAL-*.json` in this folder.

## What was run

| Run | Evidence | Result |
|-----|----------|--------|
| dry-run `taps` | `...DRYRUN-taps-20261005T152213Z.json` | COMPLETE_WITH_GAPS: SKIP and APPROVE passed; unknown-chat tap NOT_REHEARSED |
| dry-run `far` #1 | `...DRYRUN-far-20261005T152705Z.json` | FAILED: algo not-found probe raised (see finding 1) |
| dry-run `far` #2 | `...DRYRUN-far-20261005T154443Z.json` | COMPLETE, account clean (after finding 1 fix) |
| `--execute far` #1 | `...EVIDENCE-far-20261005T154619Z.json` | FAILED at SL placement (type only recorded) |
| `--execute far` #2 | `...EVIDENCE-far-20261005T154847Z.json` | FAILED at SL placement, code -4509 captured |

In both executed runs the LIMIT entry (BTCUSDT 0.0012, about 2.5% below mark) was accepted, then cancelled by the system after the SL was rejected. Nothing left on the account; the cancelled order shows in the Demo UI (for example order 28619378029). The Telegram "Query is too old" message in run 1 only means the APPROVE tap came late; the approval itself resolved.

## Finding 1 (fixed, commits e6d3c07, 4a0add7): not-found code is -2013

Read-only probe: `GET /fapi/v1/algoOrder` for a missing client id returns `BadRequestError(status_code=-2013, 'Order does not exist.')`. The adapter only mapped -2011 / `UNKNOWN_ORDER`, so every entry would end ENTRY_WITHOUT_PROTECTIVE. Now keyed on int `status_code` in {-2013, -2011}; other codes still raise. Query Order (`GET /fapi/v1/order`) is mapped on documentation only, not Demo-observed (one more read-only probe would close it). Audit findings F-501 / F-503.

## Finding 2 (OPEN, blocks go-live): SL before fill is rejected, -4509

Placing a `closePosition=true` STOP_MARKET algo order while the entry is unfilled and no position exists fails with `binance code -4509: Time in Force (TIF) GTE can only be used with open positions.` (Fact 6, now observed.) The current flow places entry then SL immediately, so live placement would always end ENTRY_WITHOUT_PROTECTIVE and SAFE_MODE. It fails closed correctly; the design is what is wrong.

Options (decision needed, new GSD task because it changes the core of `execute_approved_plan`, `src/execution/manager.py`):
1. Recommended: entry alone first, then `attach_protectives_to_fill` places SL, TP1 and TP2 from the filled quantity. Accept a short unprotected window after fill that must fail into SAFE_MODE if the SL is not confirmed.
2. SL with explicit quantity and `reduceOnly` before the fill. Unverified on Demo; the exchange may reject it too.
3. Probe first, then decide. The `fill` scenario currently hits the same placement step, so it cannot run until this is fixed.

The runner's own flow (`place_entry_and_stop` step, `far` and `fill` scenarios) must follow whatever the manager does.

## Still open for Phase 9

- Fix finding 2, then rerun `far` dry-run, then `--execute far`, then `--execute fill` (entry fills, TP1/TP2 acceptance; closes attestation items 1 and 2).
- Unknown-chat tap: add the bot to a group or use a second account, send `/start` within 120 s of a `taps` run; otherwise leave NOT_REHEARSED.
- Attestation 3 (ALGO_UPDATE.o.rm) needs Phase 18; item 4 (live key provisioning) is HUMAN_ONLY.
- Fill the remaining "Demo cross-check" lines in `09-EXCHANGE-FACTS.md` (Facts 2, 4, 5, Addendum A, B), then update `09-04-SUMMARY.md`. EXEC-01 and OPS-02 stay Pending until real Demo evidence exists.
- Never run `--execute` without the user's go-ahead; the user types `DEMO FAR BTCUSDT` themselves.

## Other cleanup noted earlier

Stale `KNOWN GAP` comment on `HEADROOM_LIMIT = 200` in `src/execution/gates.py`; `src/ops/drills.py` ruff F401; WR-07; `plan.scenario` label shows `far` in the `taps` evidence; Phase 14 and 13.1 still need `/gsd-execute-phase` for VERIFICATION.md.
