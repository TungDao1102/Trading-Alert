# Phase 21 owner decisions (plan 21-01)

Recorded on 2026-10-23. Each section has the lines "Status:", "Built default in Phase 21:", "Who decides:" and "Source:". Every default named below was checked against the code on 2026-10-23 before it was written. Demo facts are demo-observed, not mainnet.

## O-2 Daily-loss counting while income rows are unobserved (D-09)

Status: DECIDED (owner, 2026-10-23)

Owner answer, verbatim:

> option A

FundingPolicy member: `TRADES_WITH_UNVERIFIED_FUNDING` (`src/risk/daily_loss.py`). Realized PnL and commission come from the trade sources; FUNDING_FEE income rows are added when the REST income read returns them; zero income rows count as zero funding and the result carries the label `FUNDING_SOURCE_UNVERIFIED`; a failed income read makes the day loss unknown (NO_TRADE).

Built default in Phase 21: plan 21-05 builds both members (`TRADES_WITH_UNVERIFIED_FUNDING`, `REQUIRE_VERIFIED_FUNDING_SOURCE`) with no default; `LiveDayRiskService` (plan 21-13) takes `funding_policy` as a required constructor argument. No Phase 21 code starts a process; the Phase 24 composition passes `TRADES_WITH_UNVERIFIED_FUNDING`. The module constant `FUNDING_SOURCE_VERIFIED` stays False.

Who decides: the owner (decided above). The owner's answer did not mention any condition.

Pre-canary FUNDING_FEE check: the assistant recommended, in the same message as option A, one check before real money (Phase 26 canary). The owner answered "option A" on 2026-10-23 without accepting or declining it; on 2026-10-24 the owner adopted all recommendations ("còn lại chọn hết theo recommend", DECISIONS D086), so the recommendation is ADOPTED and joins the Phase 26 canary checklist: hold a small mainnet position across a funding time, and at the end of the day reconcile the wallet change against the sum of the loss components. `FUNDING_SOURCE_VERIFIED` stays False until that check is done and a DECISIONS row says so. Evidence at the time: on 2026-10-23 the Demo income endpoint returned one COMMISSION row and no FUNDING_FEE row (`19-OWNER-GAPS.md` section 2b).

Source: `21-CONTEXT.md` D-09; `19-OWNER-GAPS.md` section 2b; plan 21-05 and 21-13 summaries.

## O-1 Retention and the equity-age number (D-03, D-07)

Status: DECIDED and APPLIED (owner answer 2026-10-23; the owner then asked the assistant to apply it). Recorded as DECISIONS D084; `account.max_equity_age_ms` = 15000 with provenance `DECISION` in `config/execution/execution-limits-v1.toml`; the tests that pinned the key at `NOT_CONFIGURED` were updated in the same change. Fourteen required keys stay `NOT_CONFIGURED`, so the live path still refuses.

Owner answer, verbatim:

> 1 để 15000, 2 giữ toàn bộ

Reading of the answer, as the assistant understands it (the owner's words above are the record): (1) `account.max_equity_age_ms` = 15000 (milliseconds, the unit of the key); (2) no retention rule for the persisted day state (`daily_risk_days`, `daily_loss_components`, `risk_reservations`): every row is kept. Both were the assistant's recommendation of the same day (15000 ms from the Demo timing of the three REST reads, observed at about 1 to 2 seconds in the probe runs; keep all because the rows are small and are the audit trail of each DAILY_STOP and refusal); the owner adopted them.

Built default in Phase 21 (before D084): the limit key `account.max_equity_age_ms` was `NOT_CONFIGURED` in `config/execution/execution-limits-v1.toml` (plan 21-02), so the live path refused while it was unset. The persisted day-state tables have no delete or purge method (`src/persistence/day_risk.py`, plan 21-09) and no retention rule, which already matches the answer to part 2: nothing to build.

Who decides: the owner (answered above). D084 was written by the assistant on the owner's instruction ("làm giúp tôi luôn", 2026-10-23); the wording is the draft `21-DEC-O1-DRAFT.md`.

Source: `21-CONTEXT.md` D-03, D-07, OWNER-OPEN O-1; `config/execution/execution-limits-v1.toml` header.

## O-3 Multi-asset margin mode (D-02)

Status: DECIDED (owner, 2026-10-24; DECISIONS D086): multi-asset margin is NOT supported in V1; the refusal stays.

Owner answer of 2026-10-24, verbatim (as relayed to the assistant that applied it; the whole message, which also answers Phase 22):

> O-1: đòn bẩy x5, isolated, có thể config thông qua telegram. còn lại chọn hết theo recommend

"The rest as recommended": the owner adopted the assistant's recommendation for this item. Recorded as DECISIONS D086.

Built default in Phase 21: `multiAssetsMargin` true is refused (NO_TRADE `UNCERTAIN_ACCOUNT_STATE`, `src/risk/live_equity.py`, plan 21-04); support for it is not built and, by this decision, not planned for V1. The Demo account is One-way, `multiAssetsMargin` false.

Who decides: the owner (decided above).

Source: `21-CONTEXT.md` D-02, OWNER-OPEN O-3.

## O-4 realizedPnl semantics on mainnet (D-10)

Status: DECIDED (owner, 2026-10-24; DECISIONS D086): the conservative built default is accepted; one small mainnet trade at the Phase 26 canary verifies the semantics. `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False.

Owner answer of 2026-10-24, verbatim (as relayed to the assistant that applied it; the whole message, which also answers Phase 22):

> O-1: đòn bẩy x5, isolated, có thể config thông qua telegram. còn lại chọn hết theo recommend

"The rest as recommended": the owner adopted the assistant's recommendation for this item. Recorded as DECISIONS D086.

Built default in Phase 21: a DAILY_STOP from a day whose `realizedPnl` semantics are unverified on mainnet stays a hard stop (G2-042 is owned by Phase 24; `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False in `src/analytics/live_outcomes.py`). Adding commission explicitly can only overstate the loss if mainnet `realizedPnl` already includes it, which is the conservative direction. On Demo, `realizedPnl` did not include commission (`19-OWNER-GAPS.md` R-A9, one sample).

Who decides: the owner (decided above). The mainnet evidence is still NOT collected.

Source: `21-CONTEXT.md` D-10, OWNER-OPEN O-4.

## O-5 Equity basis versus the backtest (research Open Question 1, RISK-01 parity)

Status: DECIDED and APPLIED (owner, 2026-10-24; DECISIONS D086): the equity used for sizing is the SMALLER of `totalWalletBalance` and `totalMarginBalance`.

Owner answer of 2026-10-24, verbatim (as relayed to the assistant that applied it; the whole message, which also answers Phase 22):

> O-1: đòn bẩy x5, isolated, có thể config thông qua telegram. còn lại chọn hết theo recommend

"The rest as recommended": the owner adopted the assistant's recommendation for this item. Recorded as DECISIONS D086.

Applied: the single function `equity_basis` of plan 21-04 (`src/risk/live_equity.py`) returns `min(total_wallet_balance, total_margin_balance)`. An unrealized profit never raises the position size; an unrealized loss lowers it. The identities that check the reading are unchanged. Tests: `tests/test_live_equity.py` (`test_equity_basis_is_the_smaller_of_wallet_and_margin_balance`, `test_a_positive_unrealized_pnl_does_not_raise_the_resolved_equity`) and `tests/test_live_risk_parity.py`.

Built default in Phase 21 (before D086): live equity was `totalMarginBalance` (wallet balance plus unrealized PnL) behind `equity_basis`, while the backtest ledger is realized-only.

Who decides: the owner (decided above).

Source: `21-RESEARCH.md` Open Question 1; plan 21-04 summary.

## O-6 Latched DAILY_STOP versus the backtest (D-14)

Status: DECIDED (owner, 2026-10-24; DECISIONS D086): the live latch is kept and the divergence from the backtest is accepted and recorded.

Owner answer of 2026-10-24, verbatim (as relayed to the assistant that applied it; the whole message, which also answers Phase 22):

> O-1: đòn bẩy x5, isolated, có thể config thông qua telegram. còn lại chọn hết theo recommend

"The rest as recommended": the owner adopted the assistant's recommendation for this item. Recorded as DECISIONS D086.

Built default in Phase 21: the live DAILY_STOP is latched for the rest of the UTC day (D-14), while the backtest derives the state per booking (`src/backtest/ledger.py`, simulator semantics 2.3.0 frozen, D075 and D076). The simulator is not changed.

Who decides: the owner (decided above).

Source: `21-CONTEXT.md` D-14; `src/backtest/ledger.py`.

The assistant recorded the owner's answers and applied them; it decided none of these items itself.

