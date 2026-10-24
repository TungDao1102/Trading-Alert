# Phase 22 Demo results (owner run of 2026-10-24)

Recorded by the assistant from the three evidence files below. Every figure is **demo-observed, not mainnet**. The cases record facts; none of them sets a number, flips a flag or chooses a parameter. The owner decisions O-1 to O-4 stay with the owner (see `22-CONTEXT.md`).

Evidence (all `outcome: COMPLETE`; `acceptance: FAIL` is by design for an `--only` run):

- `evidence/demo-probe-EVIDENCE-20261024T043012Z.json`: `margin_type_change_with_resting_order`, `leverage_above_bracket_maximum`, `available_balance_with_resting_order` (account at CROSSED x20).
- `evidence/demo-probe-EVIDENCE-20261024T043055Z.json`: `symbol_config_change_to_isolated`.
- `evidence/demo-probe-EVIDENCE-20261024T043134Z.json`: `margin_insufficient_at_target_leverage`, `available_balance_with_resting_order` (second run, ISOLATED x5), `isolated_position_liquidation_price`.
- Raw answers: `evidence/fixtures/`.

Account state after the run: BTCUSDT is **ISOLATED x5** (it was CROSSED x20). The probe does not restore it; changing it back is the owner's choice.

## What the Demo showed

| # | Case | Observed |
|---|------|----------|
| R-1 | `symbol_config_change_to_isolated` | One margin-type request answered `200 success`, one leverage request answered leverage 5 (maxNotionalValue 100000000); read back `marginType` = `ISOLATED` (upper case) and leverage 5. Before: CROSSED, 20, maxNotionalValue 20000000. |
| R-2 | `margin_type_change_with_resting_order` | With one resting BUY LIMIT, the change to ISOLATED was refused: HTTP class BAD_REQUEST, code **-4047**, text "Margin type cannot be changed if there exists open orders.", category REJECTED_DEFINITIVE. The configuration stayed CROSSED x20. |
| R-3 | `leverage_above_bracket_maximum` | Bracket 1 `initialLeverage` read from the exchange: 125. A request for 126 was refused: BAD_REQUEST, code **-4028**, text "Leverage 126 is not valid", REJECTED_DEFINITIVE. The configuration stayed x20. (Assumption A6 named -4028 or -4209; -4028 was observed.) |
| R-4 | `available_balance_with_resting_order` at CROSSED x20 | One resting BUY 0.0014 at 77612.80: implied notional 108.657920, implied initial margin 5.432896. `availableBalance` 4998.22020068 to 4992.78730468 (delta **-5.43289600**); `totalOpenOrderInitialMargin` 0 to 5.43289600. |
| R-5 | `available_balance_with_resting_order` at ISOLATED x5 | Same order at 77621.90: implied initial margin 21.734132. `availableBalance` 4998.22020068 to 4976.48606868 (delta **-21.73413200**); `totalOpenOrderInitialMargin` 0 to 21.73413200. `totalWalletBalance` unchanged. |
| R-6 | `margin_insufficient_at_target_leverage` | 1 BTC at 77621.90, ISOLATED x5: implied margin 15524.38 against 4998.22 available. Refused: BAD_REQUEST, code **-2019**, text "Margin is insufficient.", REJECTED_DEFINITIVE. |
| R-7 | `isolated_position_liquidation_price` | BTCUSDT LONG 0.0014, entry 80845.8, ISOLATED x5, tier 1 (maintMarginRatio 0.004, cum 0): exchange `liquidationPrice` = **64968.85373637**. `isolatedWallet` 22.59155035, `isolatedMargin` 22.60189239, account `initialMargin` 22.63889241. The position was closed by the runner cleanup. |

## What this means for the assumptions (facts, not decisions)

- **A1, `availableBalance` and resting orders.** In both samples (CROSSED and ISOLATED) `availableBalance` fell by exactly the order's initial margin (notional / leverage) while the order rested. So on Demo the figure already nets the margin of a resting order. This is two samples on one host. `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` (plan 22-04) is still `False`: changing it needs the owner's DECISIONS row. While it is `False` the guard counts PLACED entries again, which can only over-refuse.
- **Codes for the guard.** -4047 (open orders) and -4028 (leverage not valid) and -2019 (margin insufficient) are now observed. -4048 (position open) and -4046 (no-op change), and the code for a leverage under a lower bracket, are still unobserved.
- **Casing.** The Demo returns `ISOLATED` in upper case, and `CROSSED` for cross.
- **A3, the liquidation formula (isolated, long).** Using the recorded inputs, the closed form of `src/risk/liquidation.py` reproduces the exchange value to about 4e-9 **only when the isolated wallet is the initial margin minus the entry fee**: 80845.8 x 0.0014 / 5 = 22.636824, minus 0.0004 x 113.18412 = 0.04527365, gives 22.59155035 = the recorded `isolatedWallet`. With the wallet equal to the initial margin (what plan 22-07 built, "no fees") the price is 64936.3855, about 32 USDT (0.05%) on the non-conservative side for a long. This is one long sample on tier 1; no short sample and no higher tier was observed. The fee rate 0.0004 is the Demo taker rate. Follow-up: an executor adds a required `entry_fee_rate` argument to the module (running now); plans 22-13 and 22-14 must pass it.

## Still not Demo-proven

- Criterion 1 is observed for BTCUSDT one way (set, read back, refusals). The guard itself (plan 22-11) is not built yet.
- Criterion 2: one long sample matches the formula once the entry fee is included. No short, no multi-tier sample.
- Criterion 3: the netting fact above is observed. The claims of other approved plans are not written by any Phase 22 code (Phase 24 does it), so that part is proven on fakes only.
- Nothing here is mainnet.
