# Phase 18 user-data stream fixtures

Provenance of every user-data wire frame stored under this directory. Each
frame carries one label: SYNTHETIC_FROM_SDK_MODEL for a frame written by hand
from the field set and the Python types of the installed Binance SDK models,
or RECORDED_DEMO for a frame captured on the Binance demo environment. A
synthetic frame must never be presented as captured Binance data.

## Synthetic frames

The files under `synthetic/` were built from the SDK model aliases by the frame
builders of `tests/support/userdata_frames.py` (plan 18-03) and written as
sorted-key, 2-space-indented JSON with LF newlines. They were not recorded from
Binance: every id, time, price and quantity is a made-up value, the `rm`
text of `algo_update_rejected.json` is a made-up reason, and the listenKey of
`listen_key_expired.json` is an obvious dummy, not a credential.
`tests/test_userdata_fixtures.py` pins each file equal to its builder and checks
that the rows of this section and the files under `synthetic/` are the same set.
RECORDED_DEMO frames are added by plan 18-21 in their own section, not here.

| File | Event | Label |
|---|---|---|
| `order_trade_update_trade.json` | ORDER_TRADE_UPDATE, execution type TRADE | SYNTHETIC_FROM_SDK_MODEL |
| `order_trade_update_new.json` | ORDER_TRADE_UPDATE, execution type NEW | SYNTHETIC_FROM_SDK_MODEL |
| `algo_update_new.json` | ALGO_UPDATE, algo status NEW | SYNTHETIC_FROM_SDK_MODEL |
| `algo_update_rejected.json` | ALGO_UPDATE, algo status REJECTED with `rm` | SYNTHETIC_FROM_SDK_MODEL |
| `account_update_order.json` | ACCOUNT_UPDATE, reason ORDER | SYNTHETIC_FROM_SDK_MODEL |
| `listen_key_expired.json` | listenKeyExpired (dummy listenKey) | SYNTHETIC_FROM_SDK_MODEL |

## Recorded demo frames

The files under `recorded_demo/` were captured on the Binance Demo environment
(Demo, not mainnet) by the user-run tools, with the keys in the shell only, and
scrubbed by the tool before writing (no key, secret, signature or listenKey; the
scan is recorded in `evidence/18-smoke-check.txt` and `evidence/18-probe-check.txt`).
They are evidence and are never edited. The run that wrote them:

- `recorded_demo/smoke/`: the live Demo smoke of 2026-10-16T14:04:46Z (`scripts/user_data_smoke.py`,
  BTCUSDT 0.0008), 2 frames.
- `recorded_demo/probe/`: the second live Demo probe run of 2026-10-16T17:36:12Z
  (`scripts/demo_probe.py`, BTCUSDT 0.0008), 56 frames. The first run's frames of the same
  names were replaced by this run's; they stay in git history (commit 2a27afb).

`tests/test_userdata_recorded_frames.py` parses every file with the real parsers, pins this
table equal to the files present and to the `provenance.md` next to them. The synthetic frames
above stay: they complement the recorded ones and keep their own label.

| File | Event | Label |
|---|---|---|
| `recorded_demo/smoke/execute-001-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/smoke/execute-002-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type CANCELED, status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-001-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-002-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-003-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-004-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-005-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-006-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-007-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-008-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-009-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/below_min_notional_reduce_only_leg-010-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
| `recorded_demo/probe/duplicate_client_algo_id-001-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/duplicate_client_algo_id-002-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/entry_never_fills_protective_orphan-001-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/entry_never_fills_protective_orphan-002-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/entry_never_fills_protective_orphan-003-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type CANCELED, status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/entry_never_fills_protective_orphan-004-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-001-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-002-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-003-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-004-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-005-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-006-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-007-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-008-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-009-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/full_fill_protective_quantity-010-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_algo-001-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_algo-002-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_algo-003-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_algo-004-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_normal-001-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_normal-002-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type CANCELED, status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_normal-003-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_canceled_normal-004-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type CANCELED, status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-001-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-002-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-003-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-004-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-005-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-006-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type CANCELED, status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-007-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-008-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-009-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/id_reuse_after_filled-010-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
| `recorded_demo/probe/preplaced_stop_reduce_only_flat-001-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/preplaced_stop_reduce_only_flat-002-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-001-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-002-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-003-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-004-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-005-ALGO_UPDATE.json` | ALGO_UPDATE, algo status NEW | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-006-ALGO_UPDATE.json` | ALGO_UPDATE, algo status CANCELED | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-007-TRADE_LITE.json` | TRADE_LITE | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-008-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type NEW, status NEW | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-009-ACCOUNT_UPDATE.json` | ACCOUNT_UPDATE, reason ORDER | RECORDED_DEMO |
| `recorded_demo/probe/triggered_market_exit_lifecycle-010-ORDER_TRADE_UPDATE.json` | ORDER_TRADE_UPDATE, execution type TRADE, status FILLED | RECORDED_DEMO |
