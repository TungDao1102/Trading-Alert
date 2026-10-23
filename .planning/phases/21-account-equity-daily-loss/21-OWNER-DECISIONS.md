# Phase 21 owner decisions (plan 21-01)

Recorded on 2026-10-23. Each section has the lines "Status:", "Built default in Phase 21:", "Who decides:" and "Source:". Every default named below was checked against the code on 2026-10-23 before it was written. Demo facts are demo-observed, not mainnet.

## O-2 Daily-loss counting while income rows are unobserved (D-09)

Status: DECIDED (owner, 2026-10-23)

Owner answer, verbatim:

> option A

FundingPolicy member: `TRADES_WITH_UNVERIFIED_FUNDING` (`src/risk/daily_loss.py`). Realized PnL and commission come from the trade sources; FUNDING_FEE income rows are added when the REST income read returns them; zero income rows count as zero funding and the result carries the label `FUNDING_SOURCE_UNVERIFIED`; a failed income read makes the day loss unknown (NO_TRADE).

Built default in Phase 21: plan 21-05 builds both members (`TRADES_WITH_UNVERIFIED_FUNDING`, `REQUIRE_VERIFIED_FUNDING_SOURCE`) with no default; `LiveDayRiskService` (plan 21-13) takes `funding_policy` as a required constructor argument. No Phase 21 code starts a process; the Phase 24 composition passes `TRADES_WITH_UNVERIFIED_FUNDING`. The module constant `FUNDING_SOURCE_VERIFIED` stays False.

Who decides: the owner (decided above). The owner's answer did not mention any condition.

Not part of the owner's answer: the assistant recommended, in the same message, one check before real money (Phase 26 canary): observe at least one FUNDING_FEE row, or hold a small Demo position across a funding settlement, or reconcile the wallet balance against the sum of the loss components. The owner answered "option A" without accepting or declining it, so it is recorded here as an assistant recommendation, OPEN, and not as an owner decision. Evidence at the time: on 2026-10-23 the Demo income endpoint returned one COMMISSION row and no FUNDING_FEE row (`19-OWNER-GAPS.md` section 2b).

Source: `21-CONTEXT.md` D-09; `19-OWNER-GAPS.md` section 2b; plan 21-05 and 21-13 summaries.

## O-1 Retention and the equity-age number (D-03, D-07)

Status: OPEN

Built default in Phase 21: the limit key `account.max_equity_age_ms` stays `NOT_CONFIGURED` in `config/execution/execution-limits-v1.toml` (plan 21-02), so the live path refuses while it is unset. The persisted day-state tables have no delete or purge method (`src/persistence/day_risk.py`, plan 21-09) and no retention rule, so rows are kept until the owner sets a retention. No number is written here.

Who decides: the owner. The assistant did not decide it.

Source: `21-CONTEXT.md` OWNER-OPEN O-1.

## O-3 Multi-asset margin mode (D-02)

Status: OPEN

Built default in Phase 21: `multiAssetsMargin` true is refused (NO_TRADE `UNCERTAIN_ACCOUNT_STATE`, `src/risk/live_equity.py`, plan 21-04); support for it is not built. The Demo account is One-way, `multiAssetsMargin` false.

Who decides: the owner. The assistant did not decide it.

Source: `21-CONTEXT.md` D-02, OWNER-OPEN O-3.

## O-4 realizedPnl semantics on mainnet (D-10)

Status: OPEN

Built default in Phase 21: a DAILY_STOP from a day whose `realizedPnl` semantics are unverified on mainnet stays a hard stop (G2-042 is owned by Phase 24; `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False in `src/analytics/live_outcomes.py`). Adding commission explicitly can only overstate the loss if mainnet `realizedPnl` already includes it, which is the conservative direction. On Demo, `realizedPnl` did not include commission (`19-OWNER-GAPS.md` R-A9, one sample).

Who decides: the owner. The assistant did not decide it.

Source: `21-CONTEXT.md` D-10, OWNER-OPEN O-4.

## O-5 Equity basis versus the backtest (research Open Question 1, RISK-01 parity)

Status: OPEN

Built default in Phase 21: live equity is `totalMarginBalance` (wallet balance plus unrealized PnL) behind the single function `equity_basis` of plan 21-04, while the backtest ledger is realized-only, so the two agree only when unrealized PnL is zero. Alternatives the owner may pick later: wallet balance (`totalWalletBalance`) for backtest parity, or the smaller of the two. Nothing else is built.

Who decides: the owner. The assistant did not decide it.

Source: `21-RESEARCH.md` Open Question 1; plan 21-04 summary.

## O-6 Latched DAILY_STOP versus the backtest (D-14)

Status: OPEN

Built default in Phase 21: the live DAILY_STOP is latched for the rest of the UTC day (D-14), while the backtest derives the state per booking (`src/backtest/ledger.py`, simulator semantics 2.3.0 frozen, D075 and D076). The simulator is not changed.

Who decides: the owner. The assistant did not decide it.

Source: `21-CONTEXT.md` D-14; `src/backtest/ledger.py`.

The assistant recorded these items and decided none of them.
