# Phase 22 recorded-Demo configuration fixtures

Provenance of every file under `recorded_demo/`. Each file carries one label: RECORDED_DEMO,
meaning the values were captured on the Binance Demo environment (demo-observed, not mainnet).
Nothing here is typed by hand: `scripts/gen_phase22_fixtures.py` writes every file from the
owner-run Demo capture of 2026-10-22 (Phase 19 evidence, evidence commit 48a26473, see
`19-OWNER-GAPS.md` section 2a).

The Phase 19 capture files hold the flattened `observation.summary` map the probe wrote (keys
such as `0.leverage`, every value text), not raw responses. The generator unflattens that map
into the SDK wire shape (digit key segments become list positions) so the adapter tests build
the real SDK models with `from_dict`.

| File | Source (under `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/`) | Endpoint | Label |
|---|---|---|---|
| `recorded_demo/symbol_config.json` | `account_read_only_capture-rest-004-symbol_config.json` | `GET /fapi/v1/symbolConfig` | RECORDED_DEMO |

## Conversions applied

The recorded summary has text for every value. The generator gives the non-string SDK fields
their JSON type (table `WIRE_TYPES` in the script, from the SDK 17.4.0 models): `leverage`
(integer) and `isAutoAddMargin` (boolean). Any other text for such a field stops the run with a
`ValueError`. `marginType` and `maxNotionalValue` stay text; the adapter parses the amount to
`Decimal`.

## What the Demo capture does not show

The recorded margin type is `CROSSED` with leverage 20. An ISOLATED answer has never been
recorded: its casing (`ISOLATED`) is assumed until the owner-run case of D-18 records it
(22-RESEARCH A5). Tests that need an ISOLATED answer derive it inside the test and say so.

## Regenerate

    uv run python scripts/gen_phase22_fixtures.py

The run is deterministic (sorted keys, 2-space indent, LF line endings, no clock) and reads
committed files only; it makes no network call.
