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
| `intrabar_both_touched` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | LONG limit 117.80 fills at 10:05, one mark minute touches stop 116.50 and TP1 123.20, stop first; digest `e8c9d088237b8b6097a35953f3b76a8d1105aa1fbba0e5d644ba210650fe6628` |
| `intrabar_both_touched_short` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | SHORT mirror: limit 132.20, stop 133.50, TP1 126.80, stop first; digest `e8c0b476d80e94a5e643181d0e2be764a8ef379f5e615dfb23d39c1700857ae7` |
| `intrabar_missing_fallback` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | fill at 10:05, mark series hole from 10:06, the rest of bar 250 resolves at its close from the bar range, stop first, `fallback_applied`; one record (the stop lies beyond the zone edge, so bar 250 raises no follow-up setup); digest `82f5760925f2273d21f1193b37b4ef82c8a194046ecf7e703525e07e316efde7` |
| `limit_touch_no_fill` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | three minutes reach the limit exactly without a trade-through, plan EXPIRED at 13:59:59 with 3 touches; digest `96d7fce9fc6917ed0d7daa6a952cf8ff79abc63e2dc66433c041168989f098cd` |
| `limit_partial_fill` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `partial_fill_fraction` 0.5, PARTIAL_FILL of 9.651 of 19.303, TP1 then TP2; digest `0249a1fde92340bc0a58d86c839774065ccc12dfa7f0d7fe8f20add183bf7d23` |
| `limit_expiry` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | the limit is never reached, EXPIRED at 13:59:59; digest `3575aa670d667a37439f1cc9fd5cc93956c221107cdd254d5604cf9f9fc80208` |
| `invalidation_cancels_entry` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | bar 250 closes at 116.00 below the invalidation level while the plan rests, INVALIDATION_CANCEL at 10:59:59; one record; the 1m data has a hole from 10:50 because a real fall would fill the plan first, so this is a synthetic snapshot of the precedence rule fill, then invalidation, then expiry; digest `ff399025c794a381bdf2f0eeae4a72895d8b6092a6443bd4a24f8d2880577088` |
| `baselines/no_trade` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-no-trade-v4`: the planner rejects RR_TOO_LOW, no filled trade; digest `77c6ae78953b2aefec3d57dc79778dfa14d57ff4720b9dd36333a27df5b69f87` |
| `baselines/simple_trend` | regression snapshot (Phase 14 D-25, re-pinned Phase 15 D-19): outputs pinned from the v2 engine, not hand-derived; hand-derived goldens live in tests/fixtures/phase14 | `baseline-simple-trend-v4`: LONG fills at 10:05 and is stopped at 10:06 (stop trigger 115.60); digest `c2f666cf9ec82e72aedb32df70ca3c0c290538838fefbc64cb9c1c12384979af` |

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
