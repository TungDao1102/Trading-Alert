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
