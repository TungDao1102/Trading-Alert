# Owner approval of the Demo probe limits files

Status: APPROVED by the owner on 2026-10-25.

Owner message, verbatim (Vietnamese, the whole instruction): "làm phần gap của phase 20, duyệt file giới hạn probe (22-probe-limits-sj3.toml và hai file liên quan). và sửa mục 15 trong 21-UAT.md"

The assistant recorded the approval. The owner did not list the two related files by name. The assistant reads "two related files" as the two earlier files that 22-probe-limits-sj3.toml says it follows and shares its quantity pair with (see the table). If the owner meant other files, say so and this note is amended.

## What is approved

Each file only bounds how much the Demo probe may send or how long it waits (D-17). None is a trading parameter. All five files carry the header "PROPOSED BY THE ASSISTANT, NOT APPROVED"; the headers are not edited, because earlier evidence files refer to these files by hash. This note is the approval record that the headers ask for.

| File | SHA-256 | Use |
|---|---|---|
| `.planning/phases/22-leverage-margin-liquidation-guard/decisions/22-probe-limits-sj3.toml` | `b668ce4b977deda3eba44435f8edd7fa872ecc061b1771f48f64723ca52f261f` | The six Phase 22 cases (evidence 20261024T043012Z, T043055Z, T043134Z) |
| `.planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits-sj2.toml` | `45f4b53438aa1c7b330c64c4e32627bb2bc444cd91d1f46b64fcffeeebecf9fc` | The eight sj2 cases that sj3 follows |
| `.planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits-sj2-retest.toml` | `7f9dbdd71cfef597014d13926a399988f237591a9e5e447d83e99deefc0d0b87` | The retest of two sj2 cases; same quantity pair as sj3 (0.0014 and a 150 USDT notional cap) |

A change to any of these files after today needs a new approval and a new hash.

## Values of 22-probe-limits-sj3.toml that the approval covers

| Key | Value | Meaning |
|---|---|---|
| `order.symbol` | `BTCUSDT` | The only symbol the probe touches |
| `order.quantity` | `0.0014` | Probe order size (about 114.6 USDT at 81845, above the Demo minimum notional of 50) |
| `order.max_notional_quote` | `150` | Cap on the notional of a probe order |
| `order.far_price_fraction` | `0.96` | A resting BUY LIMIT 4% under the market, so it cannot fill |
| `order.insufficient_margin_quantity` | `1` | 1 BTC, deliberately more than the available margin; not held to the notional cap |
| `order.config_target_leverage` | `5` | The leverage cap of D035 and the owner answer O-1 (D085: x5 ISOLATED) |
| `waits.case_timeout_seconds` | `90` | Per case |
| `waits.cleanup_timeout_seconds` | `60` | Cleanup |

All optional cases other than the six Phase 22 ones stay off.

## Facts the owner should know (not decisions)

- The 22-probe-limits-sj3 run already happened on 2026-10-24 (three evidence files), so this approval is recorded after the fact. The values it approves are the values that ran.
- Section 24 of the plan changed the Demo account: BTCUSDT went from CROSSED x20 to ISOLATED x5 and was not restored. This matches D085.
- `insufficient_margin_quantity = "1"` needs the available balance to stay below about 15700 USDT at x5. If the Demo balance grows past that, the case will not be refused and the value must be raised.
- Nothing here is mainnet and nothing here sets a live trading parameter.
