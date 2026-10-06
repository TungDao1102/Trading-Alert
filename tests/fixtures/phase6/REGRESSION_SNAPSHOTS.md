# Phase 6 fixtures are regression snapshots (Phase 14, D-25, F-608)

Plan 14-12 regenerated every case below as a case-input v2 (`"case_input_schema":
"backtest-case/2"`) with `scripts/gen_phase6_fixtures.py`. The 1m trade and mark minutes of a
case start at 10:00 UTC on 2026-09-11, the first minute after the 09:59:59 close of the
trigger bar (bar 249). No 1m row opens inside the signal bar (D-24, F-602); the geometry guard
`tests/test_phase6_fixture_geometry.py` asserts it.

Every case here is a regression snapshot, not a hand-derived golden. The old `expected.json`
sidecars were produced by the code under test and described v1 semantics, so none is kept.
What a test pins is the scenario tuple and a sha256 digest of the run output taken from the
v2 engine (`tests/test_backtest_simulator.py`, `REGRESSION_SNAPSHOTS`). The digest protects
against silent drift of the engine; it does not prove the engine is right. Hand-derived goldens
with a derivation note live in `tests/fixtures/phase14`.

| Case | Status | Scenario in the v2 engine and pinned digest |
| --- | --- | --- |
| `intrabar_both_touched` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | LONG limit 117.80 fills at 10:05, one mark minute touches stop 116.50 and TP1 123.20, stop first; digest `04db4983b254951ec0eba4946787d415b0d9471ed259e6aec5ce88bb664433c3` |
| `intrabar_both_touched_short` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | SHORT mirror: limit 132.20, stop 133.50, TP1 126.80, stop first; digest `0d50102b4b8a567bc014f6b015ebb796e51611dd6dfd43d53c0874f95c40ee94` |
| `intrabar_missing_fallback` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | fill at 10:05, mark series hole from 10:06, the rest of bar 250 resolves at its close from the bar range, stop first, `fallback_applied`; one record (the stop lies beyond the zone edge, so bar 250 raises no follow-up setup); digest `7c7b3bf2dcf231eaf7c7fee43e9bbf6857195b80027eb80e6d1f1b66b5516a30` |
| `limit_touch_no_fill` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | three minutes reach the limit exactly without a trade-through, plan EXPIRED at 13:59:59 with 3 touches; digest `7458ac0e6f34cb50317e225bb004b55edeac97720193347c5ae06209c7f50c8c` |
| `limit_partial_fill` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `partial_fill_fraction` 0.5, PARTIAL_FILL of 9.651 of 19.303, TP1 then TP2; digest `3a7039dcf55851952dcc57918983a457d49710e12dd5534979477b340597f24a` |
| `limit_expiry` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | the limit is never reached, EXPIRED at 13:59:59; digest `fb60c4d61514ba557659de1ec713f5f5579b8fd60b1ec9b64a4d4a9e47120002` |
| `invalidation_cancels_entry` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | bar 250 closes at 116.00 below the invalidation level while the plan rests, INVALIDATION_CANCEL at 10:59:59; one record; the 1m data has a hole from 10:50 because a real fall would fill the plan first, so this is a synthetic snapshot of the precedence rule fill, then invalidation, then expiry; digest `74cea2d2bce3fee34ead91b2e568db41492ff391212eb82c9505f211ec22833e` |
| `baselines/no_trade` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-no-trade-v4`: the planner rejects RR_TOO_LOW, no filled trade; digest `79621110930faa9a355d087849a301b9b0dee105330397206d9213efb8c766c1` |
| `baselines/simple_trend` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-simple-trend-v4`: LONG fills at 10:05 and is stopped at 10:06 (stop trigger 115.60); digest `15f56a1a524d3c2361ac6cf077c82478c03446380bdaf0ed702cb5fb95689a41` |

`tests/fixtures/phase7/parity_overlapping_history/input.json` is written by the same generator
(a copy of the `intrabar_both_touched` payload) and is also a regression snapshot.

## Phase 15 regeneration (D-19, D054)

Plan 15-12 regenerated every input above and the Phase 7 parity input from
`build_v6_payloads()` of `scripts/gen_phase6_fixtures.py` (built and proven in plan 15-10): the
Family A geometry is the corrected pivot geometry (a V-shaped dip gives a confirmed pivot low,
the stop sits beyond the outer zone edge), the candidate cases carry `baseline-v6` / `v5.0.0`
and the two baselines carry `baseline-no-trade-v4` / `baseline-simple-trend-v4` at `v5.0.0`.
Each scenario tuple in `REGRESSION_SNAPSHOTS` equals `V6_SCENARIOS` in
`tests/test_phase6_fixture_scenarios.py`, and every digest above was re-pinned only while that
module passed, so a digest is blessed only on a case proven to test its stated scenario. The
digests are regression pins from the engine, not hand-derived facts; the hand-derived facts are
in `15-10-SUMMARY.md` "v6 fixture facts". Two cases (`intrabar_missing_fallback`,
`invalidation_cancels_entry`) now produce one record instead of two: the stop lies beyond the
zone edge, so bar 250 cannot raise a follow-up setup. The two baseline cases were not pinned
before this plan; they are now.

`registry_identity` and `report_slices` in this folder are not simulator inputs: they feed the
experiment registry and the report tests (`tests/test_backtest_experiment.py`,
`tests/test_backtest_report.py`) and were not regenerated.

No file under `params/` changed. The funding sign convention (`MARK_NOTIONAL_SIGNED_V1`) is in
the cost slice of every case, as since plan 14-04.
