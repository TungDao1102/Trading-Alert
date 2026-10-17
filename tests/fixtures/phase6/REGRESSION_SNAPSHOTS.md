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
| `intrabar_both_touched` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | LONG limit 117.80 fills at 10:05, one mark minute touches stop 116.50 and TP1 123.20, stop first; digest `d680ad5c27b7fdb9282fed770d248a1afd4fd1d80d80d969cd53318363edf7c6` |
| `intrabar_both_touched_short` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | SHORT mirror: limit 132.20, stop 133.50, TP1 126.80, stop first; digest `9d3b70d6b873b5b2b50726ddf08f7552200c8276c736d897e3c727211ca64426` |
| `intrabar_missing_fallback` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | fill at 10:05, mark series hole from 10:06, the rest of bar 250 resolves at its close from the bar range, stop first, `fallback_applied`; one record (the stop lies beyond the zone edge, so bar 250 raises no follow-up setup); digest `f15cf66d1a9d44183135973206de38a54bf112fcc6d11f6d208576cd9066c92a` |
| `limit_touch_no_fill` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | three minutes reach the limit exactly without a trade-through, plan EXPIRED at 13:59:59 with 3 touches; digest `895714437aee40eda63f1c31be3eadbb32f15e553e87cced900a2826c27e1117` |
| `limit_partial_fill` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `partial_fill_fraction` 0.5, PARTIAL_FILL of 9.651 of 19.303, TP1 then TP2; digest `b9e0894ee38f0f10478f3b4779f1a6ffa24c9baedbeb9ca11e5affe4445b5816` |
| `limit_expiry` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | the limit is never reached, EXPIRED at 13:59:59; digest `8659ac4b3eb923796be57243009f5852834e0c822ceb90fcb8c9370a3a8974f2` |
| `invalidation_cancels_entry` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | bar 250 closes at 116.00 below the invalidation level while the plan rests, INVALIDATION_CANCEL at 10:59:59; one record; the 1m data has a hole from 10:50 because a real fall would fill the plan first, so this is a synthetic snapshot of the precedence rule fill, then invalidation, then expiry; digest `1bd01918f0ce151205b2225fb58381c2704f4f690ea2f4115c8665d9b4bf914a` |
| `baselines/no_trade` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-no-trade-v4`: the planner rejects RR_TOO_LOW, no filled trade; digest `9196d272105b43c7215cb66e9a1d76f66e997e2151ff71f32a288708632caaae` |
| `baselines/simple_trend` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-simple-trend-v4`: LONG fills at 10:05 and is stopped at 10:06 (stop trigger 115.60); digest `8eafebff30096d51d8657ae6f98aaa1806209dddd8966bdfe1a339fbd5bb5995` |

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
