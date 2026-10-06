---
phase: 15-strategy-geometry-correction
plan: 07
subsystem: strategy-core
tags: [geometry, census, property-test, counts-only, worked-examples, tdd]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-03..15-06 corrected Family A, B and C geometry behind geometry_version, the shared planner validator, hand-derived windows (tests/geometry_builders.py)"
provides:
  - "scripts/geometry_census.py: counts-only census CLI plus pure census_window, geometry_violations, CensusCounts, exit_code_for"
  - "tests/test_geometry_census.py: 29 census core and CLI tests"
  - "tests/test_geometry_property.py: D-06 invariant property test over a 972-cell grid for Families A, B, C, LONG and SHORT, with permanent vacuity tests"
  - "Census counts on draft geometry_version 1 sets and on the legacy v5 sets, and per-family before/after worked examples at equity 500 and 1,000, as information-only input of the 15-08 checkpoint"
affects: [15-08, 15-13]

actuals:
  tokens: 11358
  tasks: 3
  commits: 3
plan_head_before: b972107ea01651a3c74e993ee36426f2a0ef4cbf
plan_head_after: 1f542b5d84afb59e6704896169333e38f9977a49

tech-stack:
  added: []
  patterns:
    - "Census calls the same public functions the engine calls (evaluate, plan, size_and_quantize) on the same window sizes (STRATEGY_WINDOW_BARS 1000 1H bars, CONTEXT_WINDOW_BARS 300 4H bars)"
    - "Invariant checker compares stored plan fields with literal Decimal comparisons and never imports the planner validator (F8)"
    - "Property grid is explicit, sorted and cached per module; hand-derived constant-range windows are rescaled by a positive factor so ATR takes each grid value exactly"

key-files:
  created:
    - scripts/geometry_census.py
    - tests/test_geometry_census.py
    - tests/test_geometry_property.py
  modified: []

key-decisions:
  - "The census reports counts only (no PnL, fills, exits, win rates) and was run exactly once per draft set at the plan's draft values and once per legacy set; no alternative value of any key was run (D-17)"
  - "Guard stage uses a NEUTRAL constraint snapshot (all 0.00000001) so only the two pre-quantization guards can fire; any other rejection is counted under guard_other, never as a pass"
  - "Draft sets lived only in the session scratchpad registry root; nothing under params/ changed"

requirements-completed: [STRAT-02]

duration: ~1h30m
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 07: Geometry Census, D-06 Property Test and Worked Examples Summary

**A counts-only census (`scripts/geometry_census.py`) over local closed 1H and 4H bars with an independent literal invariant checker, a 972-cell D-06 property test for Families A, B and C with a permanent vacuity proof, and real-data counts plus per-family worked examples for the 15-08 checkpoint: zero invariant violations on every draft geometry_version 1 set and 323 of 323 on legacy Family A (the F-301 defect), proving the checker detects it.**

## TDD record

The plan is `type: tdd` with a tracer first task. `gsd_run check tdd-red-evidence` only parses node:test TAP and Surefire XML, so pytest RED evidence is recorded by failure mode (same note as 15-02..15-06).

**Task 1 (tracer)**
- RED `674c711`: `tests/test_geometry_census.py` (29 tests) failed at collection with `ImportError: cannot import name 'geometry_census' from 'scripts'` (the module did not exist). Collection errors, not behavior failures, because the whole unit under test is new.
- GREEN `38f7db9`: `scripts/geometry_census.py`. Tracer gate: `<verify>` (29 passed), ruff and mypy clean, then one real-data end-to-end run of the finished CLI on legacy trend-pullback baseline-v5, BTCUSDT, 2 days (48 bars, exit 1 with `stop_inside_zone` found) before expanding. That smoke run was a pipeline check on the legacy set, not a census run and not recorded as a result.
- One defect found and fixed during GREEN (Rule 1, see Deviations).

**Task 2** `1f542b5`: all property tests passed on the first run (no planner defect found). Teeth check done by hand: the same Family A window evaluated with the legacy set (`a_long_legacy_contrast`, no `geometry_version`) gives stop 97.60 against entry_min 96.80 (the unscaled base case), so the assertion `stop < entry_min` would fail for it. The grid distribution (plans per family and direction, 87 to 102 each, planner rejections RR_TOO_LOW and, for Family C, STOP_TOO_TIGHT) shows the checks are not vacuous.

**Task 3** (no commit: census and worked examples are results, recorded here; only `scripts/geometry_census.py` was allowed to change and it did not need to).

## Accomplishments

- `geometry_violations(trade_plan, direction) -> list[str]`: LONG `stop < entry_min`, SHORT `stop > entry_max`, TP1 parsed from `take_profit_json` strictly on the profit side of the zone midpoint, an inverted zone and an unreadable TP1 named. Literal Decimal comparisons only; the file never contains the planner validator's name (acceptance grep prints 0 and a test pins it).
- `census_window(...)`: per evaluated bar slices the trailing 1000 setup bars and trailing 300 context bars closed at or before the bar (bisect, like the engine), runs `evaluate`, `plan` (`created_at_utc` = bar close, like the engine) and `size_and_quantize`, and counts setups, strategy NO_TRADE reasons, planner NO_TRADE reasons, guard rejects (STOP_TOO_TIGHT, COST_TO_RISK_EXCEEDED), guard pass, other guard-stage rejects and invariant violations, with a per-direction split.
- CLI: `--strategy-id`, `--parameter-set-id`, `--registry-root` (scratch registry, restored afterwards), `--symbols`, `--days`, `--end-day`, `--warmup-days` (default 50), `--raw-root`, `--stride`, `--equity`; one JSON line per symbol and one total line with sorted keys; exit 0 (zero violations), 1 (a violation), 2 (usage or unusable set), 3 (store or run failure, exception type name only). structlog decision-lineage events are silenced so stdout carries only the JSON lines.
- Property test: families A, B, C x LONG, SHORT x `zone_tolerance_atr` {0.25, 0.5, 1.0} x `entry_buffer_atr` {0, 0.1, 0.3} x `sl_buffer_atr` {0.05, 0.2, 0.5} x ATR {0.5, 2, 8} x `min_stop_atr` {absent, 0.5} = 972 cells, all of them evaluated (no sampling, nothing dropped). Measured runtime: 26.5 s for the file (25 s for the shared grid in the first test; limit 60 s). Plans produced per family and direction: A 102 each, B 90 each, C 87 each; planner rejections seen: RR_TOO_LOW (all families) and STOP_TOO_TIGHT (Family C, 21 per direction); no other reason appears.
- Vacuity tests (permanent): a plan exists for every family, direction and ATR; every tolerance, entry buffer and sl buffer value and the absent `min_stop_atr` setting occurs among the plans; the `min_stop_atr` branch is exercised; the grid size is pinned at 972.

## Census results

Counts are information only; no value is chosen or changed from them (D-17).

Window: 30 whole UTC days ending 2026-10-01 (2026-09-02 to 2026-10-01), every closed 1H bar evaluated (stride 1, 720 bars per symbol), 50 warm-up days read before it so every evaluated bar sees the full 1000 setup and 300 context bars. Equity 1,000, risk_rate 0.005 from the set. Guard stage on a NEUTRAL constraint snapshot (no exchange constraint values invented; quantization never rejects), so only STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED can appear. `guard_other` was empty in every run. Each draft set and each legacy set was run once; no set was run at any other value. Local data only, no network. The first run measured 2 min 10 s and the others were of the same order, so no `--stride` fallback was needed.

"strategy NO_TRADE" is `evaluate` returning no setup (reason NO_TRADE_REGIME is the strategy's generic no-setup code). "planner rejects" is `plan` returning NO_TRADE for a signal. "guard rejects" is the Phase 12 verdict on a produced plan.

### trend-pullback / draft-v6 (geometry_version 1, min_stop_atr 0.5, pivot 3/3)

| symbol | bars | setups | plans | strategy NO_TRADE | planner rejects | guard rejects | guard pass | invariant_violations |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 720 | 148 | 123 | NO_TRADE_REGIME 572 | RR_TOO_LOW 24, STALE_SETUP 1 | COST_TO_RISK_EXCEEDED 68, STOP_TOO_TIGHT 1 | 54 | 0 |
| ETHUSDT | 720 | 155 | 112 | NO_TRADE_REGIME 565 | RR_TOO_LOW 42, STALE_SETUP 1 | COST_TO_RISK_EXCEEDED 8 | 104 | 0 |
| SOLUSDT | 720 | 143 | 96 | NO_TRADE_REGIME 577 | RR_TOO_LOW 40, STALE_SETUP 7 | COST_TO_RISK_EXCEEDED 3 | 93 | 0 |
| TOTAL | 2160 | 446 | 331 | NO_TRADE_REGIME 1714 | RR_TOO_LOW 106, STALE_SETUP 9 | COST_TO_RISK_EXCEEDED 79, STOP_TOO_TIGHT 1 | 251 | 0 |

By direction (total): LONG setups 284, plans 198, guard pass 154, guard reject 44; SHORT setups 162, plans 133, guard pass 97, guard reject 36. Violations 0.

### trend-pullback / baseline-v5 (legacy)

| symbol | bars | setups | plans | strategy NO_TRADE | planner rejects | guard rejects | guard pass | invariant_violations |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 720 | 87 | 87 | NO_TRADE_REGIME 633 | none | COST_TO_RISK_EXCEEDED 69, STOP_TOO_TIGHT 18 | 0 | 87 |
| ETHUSDT | 720 | 112 | 112 | NO_TRADE_REGIME 608 | none | COST_TO_RISK_EXCEEDED 100, STOP_TOO_TIGHT 5 | 7 | 112 |
| SOLUSDT | 720 | 124 | 124 | NO_TRADE_REGIME 596 | none | COST_TO_RISK_EXCEEDED 76 | 48 | 124 |
| TOTAL | 2160 | 323 | 323 | NO_TRADE_REGIME 1837 | none | COST_TO_RISK_EXCEEDED 245, STOP_TOO_TIGHT 23 | 55 | 323 |

Every legacy Family A plan (323 of 323, 205 LONG and 118 SHORT) has its stop inside the entry zone: violation kind `stop_inside_zone` 323. This is the F-301 defect and proves the independent checker detects it. The run exits 1; that is the expected and recorded outcome, not a failure.

### breakout-retest / draft-v6 (geometry_version 1, min_stop_atr 0.5, breakout_confirmation_bars 1)

| symbol | bars | setups | plans | strategy NO_TRADE | planner rejects | guard rejects | guard pass | invariant_violations |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 720 | 20 | 20 | NO_TRADE_REGIME 700 | none | COST_TO_RISK_EXCEEDED 16, STOP_TOO_TIGHT 1 | 3 | 0 |
| ETHUSDT | 720 | 12 | 12 | NO_TRADE_REGIME 708 | none | COST_TO_RISK_EXCEEDED 5 | 7 | 0 |
| SOLUSDT | 720 | 19 | 19 | NO_TRADE_REGIME 701 | none | COST_TO_RISK_EXCEEDED 4 | 15 | 0 |
| TOTAL | 2160 | 51 | 51 | NO_TRADE_REGIME 2109 | none | COST_TO_RISK_EXCEEDED 25, STOP_TOO_TIGHT 1 | 25 | 0 |

By direction (total): LONG setups 34, plans 34, guard pass 20, guard reject 14; SHORT setups 17, plans 17, guard pass 5, guard reject 12. Violations 0.

### breakout-retest / baseline-v5 (legacy, breakout_confirmation_bars 3)

| symbol | bars | setups | plans | strategy NO_TRADE | planner rejects | guard rejects | guard pass | invariant_violations |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 720 | 720 | 720 | none | none | STOP_TOO_TIGHT 720 | 0 | 0 |
| ETHUSDT | 720 | 720 | 720 | none | none | COST_TO_RISK_EXCEEDED 42, STOP_TOO_TIGHT 678 | 0 | 0 |
| SOLUSDT | 720 | 720 | 720 | none | none | COST_TO_RISK_EXCEEDED 218, STOP_TOO_TIGHT 502 | 0 | 0 |
| TOTAL | 2160 | 2160 | 2160 | none | none | COST_TO_RISK_EXCEEDED 260, STOP_TOO_TIGHT 1900 | 0 | 0 |

The legacy detector produced a setup on every one of the 2,160 bars (1,351 LONG, 809 SHORT), which is the audit's anchoring defect (F2, GEOMETRY_AUDIT.md row B anchoring: any breakout plus retest anywhere in the 1000-bar window signals). Its stop is outside its own (rolling-swing) zone, so the invariant count is 0, and every plan is rejected by a Phase 12 guard. This legacy-versus-draft contrast is a geometry change reference, not a comparison of `breakout_confirmation_bars` values: the legacy set carries 3, the draft 1, and no run varied that key on its own.

### range-mr / draft-v6 (geometry_version 1, min_stop_atr 0.5, pivot 3/3, tp_mode T_MID)

| symbol | bars | setups | plans | strategy NO_TRADE | planner rejects | guard rejects | guard pass | invariant_violations |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 720 | 19 | 14 | NO_TRADE_REGIME 701 | RR_TOO_LOW 5 | COST_TO_RISK_EXCEEDED 12, STOP_TOO_TIGHT 2 | 0 | 0 |
| ETHUSDT | 720 | 32 | 29 | NO_TRADE_REGIME 688 | RR_TOO_LOW 3 | COST_TO_RISK_EXCEEDED 28, STOP_TOO_TIGHT 1 | 0 | 0 |
| SOLUSDT | 720 | 15 | 10 | NO_TRADE_REGIME 705 | RR_TOO_LOW 5 | COST_TO_RISK_EXCEEDED 4 | 6 | 0 |
| TOTAL | 2160 | 66 | 53 | NO_TRADE_REGIME 2094 | RR_TOO_LOW 13 | COST_TO_RISK_EXCEEDED 44, STOP_TOO_TIGHT 3 | 6 | 0 |

Family C plans lost to the T-mid RR gate (D-10): 13 of 66 setups (BTCUSDT 5 of 19, ETHUSDT 3 of 32, SOLUSDT 5 of 15) are `RR_TOO_LOW` at the planner under `tp_mode` T_MID with `minimum_rr` 2. By direction (total): LONG setups 30, plans 24, guard pass 4, guard reject 20; SHORT setups 36, plans 29, guard pass 2, guard reject 27. Violations 0.

### range-mr / baseline-v5 (legacy)

| symbol | bars | setups | plans | strategy NO_TRADE | planner rejects | guard rejects | guard pass | invariant_violations |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 720 | 0 | 0 | NO_TRADE_REGIME 720 | none | none | 0 | 0 |
| ETHUSDT | 720 | 0 | 0 | NO_TRADE_REGIME 720 | none | none | 0 | 0 |
| SOLUSDT | 720 | 0 | 0 | NO_TRADE_REGIME 720 | none | none | 0 | 0 |
| TOTAL | 2160 | 0 | 0 | NO_TRADE_REGIME 2160 | none | none | 0 | 0 |

The legacy Family C regime needs the 4H close to equal EMA50 exactly, which real data never does (the 15-06 note), so legacy range-mr produced no setup on 2,160 bars.

### Counts in one line each (information only)

| family | draft setups | draft plans | Phase 12 guard survivors of plans | draft invariant violations | legacy invariant violations |
|---|---|---|---|---|---|
| trend-pullback (A) | 446 | 331 | 251 of 331 (BTC 54/123, ETH 104/112, SOL 93/96) | 0 | 323 of 323 |
| breakout-retest (B) | 51 | 51 | 25 of 51 (BTC 3/20, ETH 7/12, SOL 15/19) | 0 | 0 of 2160 (setup every bar, 0 survive) |
| range-mr (C) | 66 | 53 (13 lost to RR_TOO_LOW under T_MID) | 6 of 53 (BTC 0/14, ETH 0/29, SOL 6/10) | 0 | 0 (no setups) |

The Family B and C survival is low and COST_TO_RISK_EXCEEDED is the dominant guard verdict for both (B 25 of 26 rejects, C 44 of 47). Per D-11 nothing was loosened, no guard value was touched and no key was changed because of these counts; they are reported so the user sees them before any value is frozen.

## Checkpoint inputs

Input of the 15-08 checkpoint. Nothing here recommends a value. Provenance labels are descriptive: STRUCTURAL = selects or defines the geometry, COST_GUARD = the Phase 12 guards (unchanged here), DECISION = a choice the user makes at 15-08, PLACEHOLDER = proposed or inherited with no empirical evidence behind it. None of these values is evidence-backed.

### Draft values used (scratch registry only, `draft-v6`, never under params/)

All three drafts are the baseline-v5 content with `strategy_version` "v5.0.0" plus the keys below.

| key | trend-pullback | breakout-retest | range-mr | label |
|---|---|---|---|---|
| geometry_version | 1 | 1 | 1 | STRUCTURAL |
| min_stop_atr | 0.5 | 0.5 | 0.5 | PLACEHOLDER (proposed bound, RESEARCH A8; not tuned) |
| pivot_left_bars / pivot_right_bars | 3 / 3 | not used | 3 / 3 | PLACEHOLDER (proposed, D-02) |
| tp_mode | not used | not used | "T_MID" | DECISION (D-10, user decides at 15-08) |
| breakout_confirmation_bars | 3 inherited, unused by A | 1 (proposed baseline, sheet B1; the legacy implementation value is 3) | 3 inherited, unused by C | PLACEHOLDER (neither 1 nor 3 chosen from any count) |
| zone_tolerance_atr, entry_buffer_atr, sl_buffer_atr | 0.5, 0.1, 0.2 | 0.5, 0.1, 0.2 | 0.5, 0.1, 0.2 | PLACEHOLDER (inherited v5) |
| minimum_rr, swing_lookback | 2, 20 | 2, 20 | 2, 20 | PLACEHOLDER (inherited v5) |
| retest_window_bars, retest_depth_atr | not used | 5, 0.3 | not used | PLACEHOLDER (inherited v5) |
| regime_filter_lookback, touch_tolerance_atr | not used | not used | 50, 0.3 | PLACEHOLDER (inherited v5; regime_filter_lookback now sizes the pivot window for C) |
| min_stop_distance_rate, max_cost_to_risk | 0.003, 0.15 | 0.003, 0.15 | 0.003, 0.15 | COST_GUARD (Phase 12, unchanged) |
| fee_rate_entry / exit, expected_slippage, exit_slippage_rate | 0.0005 / 0.0005, 0.0001, 0.0003 | same | same | cost model inputs (Phase 12, unchanged) |

### Confirmation timing for pivot widths 3/3

A pivot at bar t is confirmed when bar t+3 closes: 3 hours after the pivot candle closes on the 1H series (Families A and C setup pivots) and 12 hours after it closes on the 4H series (the Family C regime). The tie rule is non-strict on the left and strict on the right: of two equal highs (or lows) in one window the right one is the pivot, and a flat series has no pivot (15-03). Larger widths mean later confirmation by that many bars.

### Worked examples (real `plan()` and `size_and_quantize`, hand-built BTC-like windows)

Setup: equity 500 and 1,000, risk_rate 0.005 (allowed risk 2.50 and 5.00), costs entry 0.0005 fee + 0.0001 slippage, exit 0.0005 fee + 0.0003 slippage, BTCUSDT constraints from 14-14-SUMMARY (tick 0.10, step 0.001, min_qty 0.001, min_notional 50). LONG, constant-range 1H bars (ATR is ATR14 on the 1H setup series and equals the bar range exactly), 250 bars, evaluated bar the last. Sizing entry is the adverse zone edge (entry_max); notional is quantity x zone midpoint. The cost-to-risk figures are observed consequences of the geometry, never a rationale for any value. "Before" is the same window under the same keys without `geometry_version` (legacy code path). The three examples are not like-for-like: ATR-to-price differs.

ATR is ATR14 on the 1H setup series: A is 400 at price 60,000, an ATR-to-price ratio of 0.67 percent; B is 600 at 60,600 (swing high), about 0.99 percent; C is 600 at 59,000 (range low), about 1.02 percent.

**Family A (trend-pullback), pivot low 60,000, ATR 400** (window `family_a_long_audit_60000_window`)

| | zone (entry_min..entry_max) | stop | TP1 | RR | stop distance rate | cost-to-risk | verdict |
|---|---|---|---|---|---|---|---|
| before | 59,560..60,040 | 59,720 (inside the zone) | 61,400 | 20.0 | 0.5330 percent | 0.2075 | COST_TO_RISK_EXCEEDED at both equities (raw quantity 0.00619 and 0.01238 never sized) |
| after | 59,760..60,240 | 59,680 | 61,400 | 4.375 | 0.9296 percent | 0.1303 | passes both guards |

| equity | after: quantity (raw) | realized risk (share of allowed) | notional |
|---|---|---|---|
| 500 | 0.003 (0.003883) | 1.9317 (77.3 percent) | 180 |
| 1,000 | 0.007 (0.007765) | 4.5072 (90.1 percent) | 420 |

Geometry check: entry zone and stop from pivot 60,000, 0.5 x 400 = 200 tolerance, 0.1 x 400 = 40 buffer, 0.2 x 400 = 80 stop buffer: 59,760, 60,240, 59,680. The research note quoted RR 5.00 with TP1 61,600; the real window's structure gives TP1 61,400 (the hand-derived sidecar `a_long_audit_60000` value), so the RR is 4.375. Every other research figure matches.

**Family B (breakout-retest), swing high 60,600, ATR 600, edge 60,900** (window `family_b_long_window` mapped p to 300 p + 30,300, `breakout_confirmation_bars` 1)

| | zone (entry_min..entry_max) | stop | TP1 | RR | stop distance rate | cost-to-risk | verdict |
|---|---|---|---|---|---|---|---|
| before | 61,140..61,260 | 61,080 | 63,000 | 15.0 | 0.2938 percent | 0.3223 | STOP_TOO_TIGHT at both equities (raw quantity 0.00941 and 0.01882 never sized) |
| after | 60,840..60,960 | 60,180 | 62,400 | 2.0833 | 1.2795 percent | 0.0980 | passes both guards |

| equity | after: quantity (raw) | realized risk (share of allowed) | notional |
|---|---|---|---|
| 500 | 0.002 (0.002891) | 1.7294 (69.2 percent) | 121.8 |
| 1,000 | 0.005 (0.005782) | 4.3236 (86.5 percent) | 304.5 |

Geometry check: edge = 60,600 + 0.5 x 600 = 60,900, entry 60,900 +- 0.1 x 600, far edge 60,600 - 300 = 60,300, stop 60,300 - 0.2 x 600 = 60,180. The research note quoted the old stop as 60,780 (the corrected edge minus the old buffer); the real legacy code on this window anchors on a rolling swing with edge 61,200 (the F2 anchoring defect) and stops at 61,080. The verdict is the same: STOP_TOO_TIGHT.

**Family C (range-mr), range 59,000..61,000, ATR 600, regime NEUTRAL on pivot structure** (hand-built closes 59,300..60,700 in steps of 280, evaluated bar on a trough; 4H context from the 15-06 NEUTRAL pivot window scaled by 300; `tp_mode` T_MID; the legacy example uses the flat 4H window the legacy EMA50 gate needs)

| | zone (entry_min..entry_max) | stop | TP1 | RR | stop distance rate | cost-to-risk | verdict |
|---|---|---|---|---|---|---|---|
| before | 58,940..59,060 | 58,880 | 61,000 (zone upper) | 16.67 | 0.3048 percent | 0.3144 | COST_TO_RISK_EXCEEDED at both equities (raw quantity 0.00952 and 0.01904 never sized) |
| after | 58,940..59,060 | 58,580 | 60,000 (T-mid; TP2 61,000) | 2.381 | 0.8127 percent | 0.1464 | passes both guards |

| equity | after: quantity (raw) | realized risk (share of allowed) | notional |
|---|---|---|---|
| 500 | 0.004 (0.004446) | 2.2492 (90.0 percent) | 236 |
| 1,000 | 0.008 (0.008892) | 4.4984 (90.0 percent) | 472 |

Geometry check: far edge of the narrow S/R zone 59,000 - 0.5 x 600 = 58,700, stop 58,700 - 0.2 x 600 = 58,580, T-mid (59,000 + 61,000) / 2 = 60,000, RR (60,000 - 59,000) / (59,000 - 58,580) = 2.381, legacy stop 59,000 - 0.2 x 600 = 58,880. All match the research figures.

### Standalone verification (independent Decimal one-liners, all agree with the real functions)

Costs and sizing formula used in each: `c = entry x 0.0006 + stop x 0.0008`, `r = entry - stop + c`, quantity `floor(equity x 0.005 / r, 0.001)`, cost-to-risk `c / r`.

```
A after geometry : python -c "from decimal import Decimal as D;p=D(60000);a=D(400);zl=p-D('0.5')*a;zu=p+D('0.5')*a;emin=zl-D('0.1')*a;emax=zu+D('0.1')*a;stop=emin-D('0.2')*a;print(emin,emax,stop)"   -> 59760.0 60240.0 59680.0
A after sizing   : python -c "from decimal import Decimal as D;e=D('60240');s=D('59680');c=e*D('0.0006')+s*D('0.0008');r=e-s+c;print(c,round(c/r,4),(D(500)*D('0.005')/r)//D('0.001')*D('0.001'),(D(1000)*D('0.005')/r)//D('0.001')*D('0.001'))"   -> 83.8880 0.1303 0.003 0.007
A before sizing  : same with e=D('60040') s=D('59720')   -> 83.8000 0.2075 (raw 0.006 / 0.012 before the guard rejects)
B after geometry : python -c "from decimal import Decimal as D;sh=D(60600);a=D(600);edge=sh+D('0.5')*a;sr=sh-D('0.5')*a;emin=edge-D('0.1')*a;emax=edge+D('0.1')*a;stop=sr-D('0.2')*a;print(edge,emin,emax,stop)"   -> 60900.0 60840.0 60960.0 60180.0
B after sizing   : same formula with e=D('60960') s=D('60180')   -> 84.7200 0.0980 0.002 0.005
B before sizing  : same with e=D('61260') s=D('61080')   -> 85.6200 0.3223 (stop rate 0.002938 below 0.003)
C after geometry : python -c "from decimal import Decimal as D;zl=D(59000);zu=D(61000);a=D(600);sr=zl-D('0.5')*a;stop=sr-D('0.2')*a;emin=zl-D('0.1')*a;emax=zl+D('0.1')*a;tp=(zl+zu)/2;print(emin,emax,stop,tp,round((tp-zl)/(zl-stop),4))"   -> 58940.0 59060.0 58580.0 60000 2.3810
C after sizing   : same formula with e=D('59060') s=D('58580')   -> 82.3000 0.1464 0.004 0.008
C before sizing  : same with e=D('59060') s=D('58880')   -> 82.5400 0.3144 (raw 0.009 / 0.019 before the guard rejects)
```

## Regeneration inventory

None. All three files are new; no committed parameter set, fixture, golden file or `parameter_set_hash` was touched. The draft sets lived only in the session scratchpad registry root and are not committed. `git status` shows no `params/` path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] structlog level filter rejected `CRITICAL + 1`**
- **Found during:** Task 1 GREEN (first CLI test run: exit 3 `KeyError`)
- **Issue:** `structlog.make_filtering_bound_logger(logging.CRITICAL + 1)` raises `KeyError: 51`; only the standard levels exist.
- **Fix:** use `logging.CRITICAL`, which still drops the `info` decision-lineage events the risk stage emits (they would otherwise interleave with the JSON lines on stdout).
- **Files modified:** scripts/geometry_census.py
- **Commit:** 38f7db9 (fixed before the GREEN commit)

### Notes

**1. [Addition] Options and categories beyond the plan text.** `--warmup-days`, `--equity` and the `guard_other` and `violation_kinds` counters were added to the specified options and counters: the warm-up is needed so the first evaluated bar sees full windows (the engine reads its warm-up bars from the same case), `--equity` is the equity of the guard stage, and `guard_other` keeps a rejection that is not one of the two guards from being counted as a pass. `main` restores `registry.REGISTRY_ROOT` and resets the structlog configuration in a `finally` so repeated in-process calls (tests) are independent.

**2. [Property vacuity strengthened]** the plan required one plan per family and direction; the permanent test also requires one per ATR value, and the grid pins its own size at 972.

**3. [Research figures that differ from the real functions]** Family A RR is 4.375, not 5.00 (TP1 61,400 from the window's structure, not 61,600); Family B legacy stop is 61,080 on the real legacy code, not 60,780 (legacy rolling-swing anchor, zone 61,140..61,260). Verdicts agree. Both are recorded above for the checkpoint; the real functions are the authority.

**4. [Pre-existing, out of scope]** `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` (CRLF vs LF) not touched; already in `deferred-items.md`.

## Observations for later plans (not fixed here)

- **Family C guard survival is 6 of 53 plans on this window** (0 of 14 BTCUSDT, 0 of 29 ETHUSDT, 6 of 10 SOLUSDT), and 13 of 66 setups are lost to the T-mid RR gate. Both are information for the 15-08 decision on `tp_mode`, `zone_tolerance_atr` and `sl_buffer_atr`; nothing was changed. SOLUSDT has the highest guard survival of the three symbols in every family on this window (A 93 of 96, B 15 of 19, C 6 of 10); the reason was not investigated here.
- **Family B draft: 51 setups in 2,160 bars** (about 2.4 percent of bars), versus one per bar legacy: the corrected anchor makes it a rare setup.
- **The census exit code treats only invariant violations as failure.** Legacy Family A exits 1 by design; 15-13 (universal geometry) should expect exit 0 on every set.
- **A guard stage on real exchange constraints is not run here.** Quantization rejects (min quantity, min notional, utilization) at equity 500 are not in these counts; the worked examples above show them on BTCUSDT constraints only.

## Verification

- `pytest tests/test_geometry_census.py tests/test_geometry_property.py tests/test_planner_geometry.py`: all pass (census 29 tests; property file 11 tests in 26.5 s; planner geometry unchanged).
- `ruff check src tests scripts`: clean; `ruff format --check src tests scripts`: 387 files already formatted; `mypy src`: no issues in 149 files.
- Targeted suites only, foreground; no broad full-suite run. No background process was left running.

## Known Stubs

None.

## Threat Flags

None. No network, auth or schema surface added; the census reads only local Parquet files and the registry. T-15-13 mitigated: counts only (a test pins the absence of outcome keys), each set run once at the plan's values, no alternative-value run, the 15-08 checkpoint states counts are informational. T-15-14 mitigated: literal field comparisons, the script never names the planner validator (grep prints 0 and a test pins it), and the checker was shown to catch the legacy Family A defect (323 of 323). T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: scripts/geometry_census.py (`def geometry_violations`, `def census_window`), tests/test_geometry_census.py, tests/test_geometry_property.py
- FOUND: `grep -c "_geometry_rejection" scripts/geometry_census.py` prints 0; docstring states the counts-only rule and the exit codes
- FOUND: test names containing `vacuity` in tests/test_geometry_property.py covering trend-pullback, breakout-retest and range-mr
- FOUND: commits 674c711, 38f7db9, 1f542b5
- FOUND: "## Census results", "## Checkpoint inputs", "## Regeneration inventory" in this file; every draft-v6 table shows invariant_violations 0
- No path under params/ changed
