# Phase 21 recorded-Demo account fixtures

Provenance of every file under `recorded_demo/`. Each file carries one label: RECORDED_DEMO,
meaning the values were captured on the Binance Demo environment (demo-observed, not mainnet).
Nothing here is typed by hand: `scripts/gen_phase21_fixtures.py` writes every file from the
owner-run Demo capture of 2026-10-22 (Phase 19 evidence, evidence commit 48a26473, see
`19-OWNER-GAPS.md` section 2a).

The Phase 19 capture files hold the flattened `observation.summary` map the probe wrote (keys
such as `assets.5.marginBalance`, every value text), not raw responses. The generator
unflattens that map into the SDK wire shape (digit key segments become list positions) so the
adapter tests build the real SDK models with `from_dict`.

| File | Source (under `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/`) | Endpoint | Label |
|---|---|---|---|
| `recorded_demo/account_information_v3.json` | `account_read_only_capture-rest-001-account_information.json` | `GET /fapi/v3/account` | RECORDED_DEMO |
| `recorded_demo/account_balance_v3.json` | `account_read_only_capture-rest-002-account_balance_all.json` | `GET /fapi/v3/balance` | RECORDED_DEMO |
| `recorded_demo/account_config.json` | `account_read_only_capture-rest-003-account_config.json` | `GET /fapi/v1/accountConfig` | RECORDED_DEMO |
| `recorded_demo/user_trades_commission_case.json` | `commission_vs_realized_pnl-rest-005-user_trades.json` then `-006-user_trades.json` (recorded order, a repeated trade id kept once) | `GET /fapi/v1/userTrades` | RECORDED_DEMO |
| `recorded_demo/user_trades_triggered_bracket.json` | `triggered_close_position_bracket-rest-015-user_trades.json` | `GET /fapi/v1/userTrades` | RECORDED_DEMO |
| `recorded_demo/income_funding_empty.json` | `commission_vs_realized_pnl-rest-007-income_history.json` and `-008-income_history.json` (both recorded with count `0`) | `GET /fapi/v1/income` | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-002-ORDER_TRADE_UPDATE-2.json` | `commission_vs_realized_pnl-002-ORDER_TRADE_UPDATE-2.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-002-ORDER_TRADE_UPDATE.json` | `commission_vs_realized_pnl-002-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-003-ACCOUNT_UPDATE-2.json` | `commission_vs_realized_pnl-003-ACCOUNT_UPDATE-2.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-003-ACCOUNT_UPDATE.json` | `commission_vs_realized_pnl-003-ACCOUNT_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-004-ORDER_TRADE_UPDATE-2.json` | `commission_vs_realized_pnl-004-ORDER_TRADE_UPDATE-2.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-004-ORDER_TRADE_UPDATE.json` | `commission_vs_realized_pnl-004-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-006-ORDER_TRADE_UPDATE.json` | `commission_vs_realized_pnl-006-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-007-ACCOUNT_UPDATE.json` | `commission_vs_realized_pnl-007-ACCOUNT_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-007-ORDER_TRADE_UPDATE.json` | `commission_vs_realized_pnl-007-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-008-ACCOUNT_UPDATE.json` | `commission_vs_realized_pnl-008-ACCOUNT_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-008-ORDER_TRADE_UPDATE.json` | `commission_vs_realized_pnl-008-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-009-ORDER_TRADE_UPDATE.json` | `commission_vs_realized_pnl-009-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-010-ACCOUNT_UPDATE.json` | `commission_vs_realized_pnl-010-ACCOUNT_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/commission_vs_realized_pnl-011-ORDER_TRADE_UPDATE.json` | `commission_vs_realized_pnl-011-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/triggered_close_position_bracket-002-ORDER_TRADE_UPDATE.json` | `triggered_close_position_bracket-002-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/triggered_close_position_bracket-003-ACCOUNT_UPDATE.json` | `triggered_close_position_bracket-003-ACCOUNT_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/triggered_close_position_bracket-004-ORDER_TRADE_UPDATE.json` | `triggered_close_position_bracket-004-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/triggered_close_position_bracket-008-ORDER_TRADE_UPDATE.json` | `triggered_close_position_bracket-008-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/triggered_close_position_bracket-009-ACCOUNT_UPDATE.json` | `triggered_close_position_bracket-009-ACCOUNT_UPDATE.json` | stream frame | RECORDED_DEMO |
| `recorded_demo/frames/triggered_close_position_bracket-010-ORDER_TRADE_UPDATE.json` | `triggered_close_position_bracket-010-ORDER_TRADE_UPDATE.json` | stream frame | RECORDED_DEMO |

## Conversions applied

The recorded summary has text for every value. The generator gives the non-string SDK fields
their JSON type (table `WIRE_TYPES` in the script, from the SDK 17.4.0 models): `updateTime`
(integer), and for the other two endpoints `feeTier`, `tradeGroupId` (integer) and
`marginAvailable`, `canDeposit`, `canTrade`, `canWithdraw`, `dualSidePosition`,
`multiAssetsMargin` (boolean). Any other text for such a field stops the run with a
`ValueError`. Amounts stay exchange text (strings) and are parsed to `Decimal` by the adapter.

## Trade rows, income answer and stream frames (plan 21-08)

The trade files are JSON lists of SDK-shaped `AccountTradeListResponseInner` rows. The probe wrote
`row_<n>_<field>` text; the generator renames each probe field to its SDK alias by the fixed table
`TRADE_FIELD_MAP` (`trade_id` to `id`, `order_id` to `orderId`, `commission_asset` to
`commissionAsset`, `realized_pnl` to `realizedPnl`, `margin_asset` to `marginAsset`,
`position_side` to `positionSide`, `quote_qty` to `quoteQty`, `time_ms` to `time`) and types `id`,
`orderId`, `time` (integer) and `buyer`, `maker` (boolean) by `TRADE_WIRE_TYPES`.
The probe summary has no symbol: `"symbol": "BTCUSDT"` is added from the documented case symbol
(19-OWNER-GAPS.md section 2a). It is a generator reconstruction, not a captured value. The
commission case keeps the recorded order of the two captures, which is not ascending in trade id
(`549732633`, `549732634`, `549732632`): a test sorts it before it serves it as one page.

`income_funding_empty.json` is `[]`: both recorded income reads of 2026-10-22 had zero rows, so the
funding source (FUNDING_FEE income) is unverified on Demo.

The frame files under `recorded_demo/frames/` are every ORDER_TRADE_UPDATE and ACCOUNT_UPDATE frame
file of the cases `triggered_close_position_bracket` and `commission_vs_realized_pnl`, copied byte
for byte by the generator for the user-data tests (plan 21-16). RECORDED_DEMO, demo-observed, not
mainnet, scrubbed by the probe tool, never edited.

## Removed fields

The account alias field of the balance endpoint is an account identifier. The generator drops
it from every object (constant `ALIAS_FIELD` in the script); no committed fixture carries it,
and `tests/test_phase21_fixtures.py` walks every key of every file to prove it.

## Regenerate

    uv run python scripts/gen_phase21_fixtures.py

The run is deterministic (sorted keys, 2-space indent, LF line endings, no clock) and reads
committed files only; it makes no network call.
