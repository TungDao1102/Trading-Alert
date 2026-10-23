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

## Conversions applied

The recorded summary has text for every value. The generator gives the non-string SDK fields
their JSON type (table `WIRE_TYPES` in the script, from the SDK 17.4.0 models): `updateTime`
(integer), and for the other two endpoints `feeTier`, `tradeGroupId` (integer) and
`marginAvailable`, `canDeposit`, `canTrade`, `canWithdraw`, `dualSidePosition`,
`multiAssetsMargin` (boolean). Any other text for such a field stops the run with a
`ValueError`. Amounts stay exchange text (strings) and are parsed to `Decimal` by the adapter.

## Removed fields

The account alias field of the balance endpoint is an account identifier. The generator drops
it from every object (constant `ALIAS_FIELD` in the script); no committed fixture carries it,
and `tests/test_phase21_fixtures.py` walks every key of every file to prove it.

## Regenerate

    uv run python scripts/gen_phase21_fixtures.py

The run is deterministic (sorted keys, 2-space indent, LF line endings, no clock) and reads
committed files only; it makes no network call.
