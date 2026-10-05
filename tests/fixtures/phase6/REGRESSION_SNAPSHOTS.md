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

| Case | Status | Scenario in the v2 engine |
| --- | --- | --- |
| `intrabar_both_touched` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | LONG limit 121.50 fills at 10:05, one mark minute touches stop 121.2 and TP1 125.60, stop first |
| `intrabar_both_touched_short` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | SHORT mirror: limit 128.50, stop 128.8, TP1 124.40, stop first |
| `intrabar_missing_fallback` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | fill at 10:05, mark series hole from 10:06, the rest of bar 250 resolves at its close from the bar range, stop first, `fallback_applied`; a follow-up setup at that close is still resting at the data end |
| `limit_touch_no_fill` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | three minutes reach the limit exactly without a trade-through, plan EXPIRED at 13:59:59 with 3 touches |
| `limit_partial_fill` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `partial_fill_fraction` 0.5, PARTIAL_FILL of 16.035 of 32.071, TP1 then TP2 |
| `limit_expiry` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | the limit is never reached, EXPIRED at 13:59:59 |
| `invalidation_cancels_entry` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | bar 250 closes at 120.80 below the invalidation level while the plan rests, INVALIDATION_CANCEL at 10:59:59; the 1m data has a hole from 10:50 because a real fall would fill the plan first, so this is a synthetic snapshot of the precedence rule fill, then invalidation, then expiry |
| `baselines/no_trade` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-no-trade-v3`: the planner rejects RR_TOO_LOW, no filled trade |
| `baselines/simple_trend` | regression snapshot (Phase 14 D-25): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-simple-trend-v3`: LONG fills at 10:05 and is stopped at 10:06 |

`tests/fixtures/phase7/parity_overlapping_history/input.json` is written by the same generator
(a copy of the `intrabar_both_touched` payload) and is also a regression snapshot.

`registry_identity` and `report_slices` in this folder are not simulator inputs: they feed the
experiment registry and the report tests (`tests/test_backtest_experiment.py`,
`tests/test_backtest_report.py`) and were not regenerated.

No file under `params/` changed. The funding sign convention (`MARK_NOTIONAL_SIGNED_V1`) is in
the cost slice of every case, as since plan 14-04.
