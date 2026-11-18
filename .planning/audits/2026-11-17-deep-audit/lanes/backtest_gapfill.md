# Lane M09b: backtest_gapfill

## Scope
Files lane M09 left unread: `src/backtest/funding.py`, `ledger.py`, `lifecycle.py`, `case.py`;
`src/research/manifest_build.py`, `register.py`, `settlement_evidence.py`; `src/analytics/*` except `render_*.py`;
one end-to-end engine probe on a committed fixture. Findings G-0950..G-0999. Snapshot `55885b9`.
Builds on `lanes/backtest_research_analytics.md` (G-0901..G-0905 not repeated). G-1102 (funding gap tolerance) not repeated.

## Progress log
- [done] research group, analytics group, findings JSON written and validated (5 findings)
- [done] backtest group (funding, ledger, lifecycle, case) + e2e strategy-path probe (`tmp/backtest_gapfill/e2e_probe.py`, outputs `e2e_probe.out`, `e2e_probe_neg.out`, `funding_sign.out`)

## Coverage
| File | Level | Note |
|---|---|---|
| `src/backtest/funding.py` | DEEP_READ | sign, window, coverage, mark fallback; probed |
| `src/backtest/ledger.py` | DEEP_READ | equity, day roll, exposures; probed through e2e |
| `src/backtest/lifecycle.py` | DEEP_READ | states, expiry, invalidation, fallback, terminal settlement |
| `src/backtest/case.py` | DEEP_READ | parser; leakage checked together with the `engine.py` windows |
| `src/backtest/engine.py` | NORMAL_READ | lines 186-220, 336-960 (window, drain, funding push, signal path) |
| `src/research/register.py` | DEEP_READ | candidate check; grid path is caller-supplied (G-0951) |
| `src/research/manifest_build.py` | DEEP_READ | values from the decision record; split proportions not checked in code, data holds 292/292/146 days = 40/40/20 |
| `src/research/settlement_evidence.py` | DEEP_READ | interval recompute; exact Fraction arithmetic |
| `src/research/authorization.py` | NORMAL_READ | binds grid, manifest, semantics version; no holdout rule |
| `src/research/manifest.py` | NORMAL_READ | lines 367-470, 511-594 (manifest invariants, grid) |
| `src/analytics/core_metrics.py` | DEEP_READ | probed (`analytics_probe.out`) |
| `src/analytics/types.py` | DEEP_READ | validation, negative risk refused |
| `src/analytics/inputs.py` | DEEP_READ | backtest normalizer (no exit-kind filter, G-0952) |
| `src/analytics/excursion.py` | DEEP_READ | probed (G-0954) |
| `src/analytics/slices.py` | DEEP_READ | stable order, no favourability sort |
| `src/analytics/approval_delay.py` | DEEP_READ | bucket edges probed |
| `src/analytics/latency.py` | NORMAL_READ | legs and signed deviation read (lines 168-300) |
| `src/analytics/live_outcomes.py` | DEEP_READ | net PnL rule, fail-closed flag, exit roles (G-0953) |
| `src/analytics/killgate_guard.py` | DEEP_READ | registry loader fail-closed |
| `src/analytics/clock.py` | NORMAL_READ | clock start = protocol `Frozen on` 2026-09-19 (unchanged by amendments) |
| `src/analytics/report.py` | NORMAL_READ | `build_evidence_block`, `build_kill_gate_section` (lines 427-580) |
| `src/analytics/cli.py` | NORMAL_READ | `_backtest_inputs` (299-342), outline |
| `src/analytics/lifecycle.py` | NORMAL_READ | outline and vocabularies; normalizers not traced line by line |
| `src/analytics/universe.py`, `no_trade.py` | NORMAL_READ | headers and structure only |
| `src/analytics/provenance.py`, `__init__.py` | METADATA_ONLY | not read beyond grep |
| `src/analytics/stats.py`, `gates.py`, `family.py`, `killgate.py` | (M09) | read by M09; `ordered_r_values` re-read here |

## Verified Safe Areas
- **Funding sign.** `src/backtest/funding.py:146-147` `return -notional_rate if direction == "LONG" else notional_rate`. Probe `funding_sign.out`: qty 2, mark 50000, rate +0.0001: LONG -10, SHORT +10; rate -0.0001: LONG +10, SHORT -10. A long pays a positive rate, as Binance defines it. The signed amount is added to net PnL (`records.py:393` `... + funding`).
- **Funding at the entry and exit minute is charged consistently.** Entries and exits are dated at the 1m close (`lifecycle.py:252`, `exits.py:110`); segments are half-open `[start, end)` (`funding.py:392`). E2E probe (`e2e_probe.out`): funding rows at 10:10:00.003 (inside the fill minute), 10:20:00 and 10:30:00.003 (inside the stop minute): the first is not charged, the other two are (count 2, each -1.9303 = 19.303 x 100 x 0.001). Since Binance funding instants sit in the first milliseconds of the hour minute, a fill or exit detected inside that minute almost surely happened after the instant, so this attribution is right at minute granularity. Windows partition time (`[advanced_to, window_end)`, `engine.py:186-220`): no instant is charged twice or skipped between windows. Negative rate (`e2e_probe_neg.out`): the long receives +3.8606.
- **Ledger arithmetic.** E2E probe: ledger delta -32.117875640 = sum of bookings = record `realized_pnl`. Hand check: gross (116.50-117.80) x 19.303 = -25.0939; entry fee 117.80 x 19.303 x 0.0005 = 1.13695; entry slippage 1 bp = 0.22739; exit fee 1.12440; exit slippage 3 bp = 0.67464; funding -3.8606; total -32.11788. Exact match.
- **Equity is realized-only; daily loss uses the UTC day and re-resolves thresholds at the day start** (`ledger.py:140-157, 172-198`); a booking at 00:00:00.000 belongs to the new day; non-decreasing booking order is enforced; exhausted equity resolves the thresholds to 0 and `equity_positive` blocks new plans (`engine.py` `_evaluate_scripted` / `_evaluate_strategy`).
- **Exposure after TP1** scales as initial x remaining / filled (`ledger.py:308`); with the stop unchanged after TP1 (`lifecycle.py:281-288`, D-11) that equals remainder x stop distance, exact. Resting plans count with their full sized risk (conservative).
- **Lifecycle precedence** fill > invalidation > expiry (`lifecycle.py:505-557`); minutes closing after expiry are never eligible; a RESTING plan at data end becomes PENDING_AT_DATA_END, never EXPIRED; DAILY_STOP cannot cancel an OPEN position (`cancel_plan` raises), its stop stays; the fill minute is not walked twice (`lifecycle.py:572` skips mark minutes opening before the entry time, which is the fill-minute close).
- **No look-ahead in case construction.** `case.py` only parses and validates; the engine slices setup and context windows with `bisect_right(closes, close)` (`engine.py:802-810`), so a 4h bar is used only once its close is at or before the 1h signal close. Constraint rows are point-in-time (`select_constraints(..., bar_close_utc=close)`, `engine.py:858`). `_terminal_blocks` uses the declared delisting instant T only to refuse a plan that could not become active before T (`close + 1 min > T`, `engine.py:342-349`), so it removes no trade that could have filled. Floats are refused anywhere in the case (`case.py:218-227`).
- **E2E strategy path** (phase-6 trigger fixture via `tests/test_backtest_engine_strategy.py:trigger_case`, real `evaluate_risk`): one LONG trade, fill 11 minutes after the signal close at the limit 117.80, SL 116.50, R = -32.118 / 49.999 = -0.64 (consistent with M09's ~-0.68 R stop-out; sizing uses the worst entry of the zone, 118.84).

- **Manifest invariants.** `DatasetManifest.__post_init__` (`src/research/manifest.py:367-420`) requires contiguous Development -> Validation -> Holdout on day boundaries, positive equity and risk rate, and a terminal settlement strictly inside Development (`_check_terminal_settlements`), so a settlement can never reach Validation or Holdout. `build_manifest` builds the case data only up to `validation_end` (`manifest_build.py:330-341`), so the dataset identity never reads the Holdout. The committed manifest's split is 2024-10-03 / 2025-07-22 / 2026-05-10 / 2026-10-03 = 292 / 292 / 146 days = 40 / 40 / 20 %, as the protocol fixes (no code check, but the data holds).
- **Settlement bounds** (`settlement_evidence.py`): the mean of minute lows is a true lower bound of a per-second mean (each second's index value is at least its minute's low), and vice versa; tick widening and the union with the trade candle only widen; the engine applies the adverse bound per side (`lifecycle.py:719`). Arithmetic is exact (`Fraction`), floats refused at JSON parse. Conservative and recomputable.
- **Analytics formulas, hand-checked** (`analytics_probe.out`): R values -0.7, +2.0, +0.5, -0.9 give mean 0.225, win rate 0.5, max drawdown 0.9 R (peak 1.8 to 0.9), longest loss streak 1 (`core_metrics.py:80-123`); approval-delay buckets are half-open at 60 / 300 / 1800 s and a negative delay is excluded (`approval_delay.py:delay_bucket_for`); entry deviation is signed "positive = worse" for both sides (`latency.py:280-296`). No float anywhere on the analytics path read here: every input field is checked `Decimal` and finite (`types.py:_require_decimal`), negative risk is refused (`types.py:143`), and division goes through `src.core._decimal`.
- **Evidence kinds are never pooled** (every section builder checks the kind; `report.py:416-424`); slice rows are ordered by fixed label keys, never by a metric (`slices.py:157-211`).
- **Live R fails closed** while Binance `realizedPnl`/`commission` semantics are unverified (`live_outcomes.py` `LIVE_NET_PNL_SEMANTICS_VERIFIED = False`); a non-USDT commission makes the outcome INCOMPLETE rather than converted; the R denominator is the same `realized_risk_for_fill` as the backtest. Funding is excluded from live R and the docstring says so.
- **Kill-gate review guard** (`killgate_guard.py`) fails closed on any malformed or scope-edited registry; clock start is the protocol header `Frozen on: 2026-09-19`, which the seven amendments did not move, so the six-month clock was not reset.
- **Run authorization** binds grid hash, manifest hash and simulator semantics version (`authorization.py:110-125`), so a simulator-version mismatch or an unauthorised grid point cannot be run by `src.research.run`.

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D-14 funding sign `MARK_NOTIONAL_SIGNED_V1`, booked at actual fundingTime, half-open window | SOUND | Binance funding definition, probe | sign and attribution verified with numbers |
| D-18 realized-only equity, UTC-day daily loss | SOUND | practice, probe | same rule as the risk engine; equity matches bookings exactly |
| D-11 stop unchanged after TP1 | CANNOT_JUDGE | practice | a strategy choice; consistent between ledger and lifecycle; live parity is another lane's |
| D-34 RESTING at data end = PENDING_AT_DATA_END, OPEN = flagged END_OF_DATA exit | SOUND | research practice | does not invent outcomes |
| D070 terminal settlement at the adverse bound of a recomputed interval | SOUND | arithmetic | bounds provably contain the stated settlement rule; adverse side chosen |
| Protocol §4 holdout lock: lineage = strategy_id + strategy_version, marker "makes erosion countable" | DOUBTFUL | research practice | a new version is a new lineage, so the holdout can be re-used without limit and no code enforces even the marker (G-0950) |
| D-28 candidate registration check (`register.py`) | SOUND with a gap | logic | the checks are right, but the grid it compares with is whatever file the caller names (G-0951) |

## Findings

### G-0950 — The single-use holdout is protected only by procedure: no code writes the consumed marker or refuses a later window that reuses the holdout period, and a new strategy_version is a new lineage
- Severity: now LOW / mainnet MEDIUM
- Confidence: CONFIRMED (code search; no producer exists)
- Classification: DESIGN (with a GAP part)
- Category: research integrity, holdout
- Component: research manifest, authorization, protocol §4
- File: `src/research/authorization.py`; `src/research/manifest.py`; `src/research/manifest_build.py`; `docs/research/RESEARCH_PROTOCOL.md`
- Lines: `authorization.py:110-125`; `manifest.py:367-403`; `manifest_build.py:296-386`; protocol §4 lines 285 and 293
- Rule: RESEARCH_PROTOCOL §1 ("the final holdout must not be used to choose parameters ... single-use per candidate lineage"), §4 G5 and "Holdout consumed marker"; D032, D043
- Known-prior: the missing G1-G5 code is KNOWN:G3-004 (ROADMAP). The reuse path below is not in the registers I read.
- Evidence: `grep -rn holdout_consumed src` returns nothing: no harness writes `docs/research/holdout_consumed.json` and no code reads it. `require_authorized` checks only `grid_hash`, `manifest_hash` and `simulator_semantics_version`. `DatasetManifest.__post_init__` checks that one manifest's three blocks are contiguous; nothing compares a new manifest with the committed one, so a later manifest whose Development or Validation covers 2026-05-10..2026-10-03 (the run-1 holdout) is accepted and authorised by the same mechanism. Protocol line 293: "Lineage means a `strategy_id` plus its `strategy_version` line; successive lineages on one holdout window erode it, which the marker makes countable." AGENTS: any behaviour change "ships as a NEW set plus a NEW strategy_version", i.e. a new lineage.
- Expected: a holdout that is used once, or at least a machine-enforced count and limit, and a refusal when a later research window overlaps a holdout already designated.
- Actual: the lock depends on people remembering; the protocol itself allows any number of lineages to evaluate the same holdout, each counted at most.
- Reproduction: `grep -rn "holdout_consumed" src scripts`; read `require_authorized`.
- Impact: none today (the holdout is untouched, `holdout_consumed.json` is empty). Once candidates are iterated (new versions after run 1 failed, see G-0901), the 146-day holdout becomes one more validation set and a G5 pass loses its meaning as an out-of-sample check, which is the evidence the go-live gate (D059) rests on.
- Why tests miss it: there is no G5 harness to test; manifest tests check one manifest at a time.
- Remediation: owner decision O-1b. Then a G5 harness that writes the marker before reading holdout data, and a manifest check that refuses any research window overlapping a designated holdout.

### G-0951 — `register.py` reports VALID against whatever grid file the caller names; the "approved, preregistered grid" is not checked against an authorization
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED (code read)
- Classification: GAP
- Category: candidate registration
- Component: `python -m src.research.register`
- File: `src/research/register.py`
- Lines: 127-131, 173-189, 282
- Rule: D-28 / D059-5 ("equals exactly one point of the approved, preregistered grid")
- Known-prior: none found
- Evidence: `--grid` is a required free path (`register.py:282`); `_grid_reason` only parses it (`load_grid`); `_matching_points` compares id and hash with that file. No `grid_hash` is compared with a committed authorization (`authorization.py` binds the grid hash for runs only). The pin file default is the same file `registry-gate.yml` re-hashes, so a new TOML plus a new pin entry plus a hand-written grid JSON yields VALID.
- Expected: VALID only for a point of a grid whose hash a committed authorization names.
- Actual: the check is as strong as the grid file passed to it. It is a manual tool, not called by the paper or live start path (no caller in `src/`), so its output is advisory.
- Reproduction: read the file; `grep -rn validate_candidate src` shows no caller.
- Impact: a wrong "VALID" could be shown to the owner as the value to authorise (O-04). No runtime effect.
- Why tests miss it: tests pass the committed grid.
- Remediation: require `--authorization` and compare `grid_hash(load_grid(grid))` with it.

### G-0952 — The analytics "core metrics" use a different trade population than the protocol: END_OF_DATA and SETTLEMENT exits count, and all passed experiments are pooled
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED (probe)
- Classification: DRIFT
- Category: report input
- Component: analytics core metrics, backtest evidence block
- File: `src/analytics/inputs.py`; `src/analytics/stats.py`; `src/analytics/core_metrics.py`; `src/analytics/cli.py`
- Lines: `inputs.py:49-84` (every non-REJECT record becomes an outcome); `stats.py:180-189` (any outcome with R and an exit time is R-valued); `core_metrics.py:110-120`; `cli.py:309-342` (all `--evidence` experiments merged into one block)
- Rule: RESEARCH_PROTOCOL §4 / line 309 ("a `SETTLEMENT` exit is never a closed trade", closed = exit by SL or TP2); `docs/backtest/METRICS.md` §2 "wins / closed trades"
- Known-prior: none found
- Evidence: probe `analytics_probe.out`: outcomes SL -0.7 R, TP2 +2.0 R, END_OF_DATA +0.5 R, SETTLEMENT -0.9 R. Analytics: n 4, mean 0.225 R, win rate 0.5. Protocol population (SL, TP2): n 2, mean 0.65 R. `_backtest_inputs` concatenates the trades of every experiment passed, so one BACKTEST block pools grid points, folds and Development windows; slices split by `strategy_version` but not by `parameter_set_hash` or split role.
- Expected: the dashboard's BACKTEST mean R / win rate either use the protocol's closed-trade definition or say they do not, and are per parameter set.
- Actual: a headline figure that cannot be compared with the run output (`src/research/report.py`) or the gates.
- Reproduction: `python -B analytics_probe.py` (PYTHONPATH = snapshot).
- Impact: a misleading descriptive number if the owner reads the analytics report as research evidence. Gates do not use it.
- Why tests miss it: tests feed SL/TP outcomes of one parameter set.
- Remediation: filter or label END_OF_DATA / SETTLEMENT in the core block; refuse or split multi-parameter-set BACKTEST evidence.

### G-0953 — Live outcomes count only exits by SL/TP1/TP2 plan orders; an emergency, manual or liquidation close never closes the outcome, so the worst live trades would be missing from live R
- Severity: now LOW / mainnet MEDIUM
- Confidence: PROBABLE (analytics side confirmed; that emergency/manual close fills never carry a plan exit role is from a grep of `src/execution/emergency_close.py` and `src/live/stream_persistence.py`, not a full trace)
- Classification: GAP
- Category: live evidence, survivorship
- Component: `normalize_live_outcomes`
- File: `src/analytics/live_outcomes.py`
- Lines: `_EXIT_KINDS` (STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2) and the `exit_fills` / `closed` block; `src/domain/enums.py:249-255` (OrderRole has only ENTRY, STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2); `src/live/stream_persistence.py:403-412` (persisted orders come from intents with `order_role=intent.role`)
- Rule: METRICS §3 user execution report; D-02 "nothing imputed" (the rule is followed, the population is not complete)
- Known-prior: none found
- Evidence: `closed = bool(exit_fills) and _total_quantity(exit_fills) >= entry_quantity`, with `exit_fills` taken only from orders whose role is in `_EXIT_KINDS`. `OrderRole` has no close role; `emergency_close.py` contains no `role`/`OrderRole` reference; the operator path `emergency_manual_close` and an exchange liquidation produce no plan-role order either.
- Expected: any fill that reduces the plan's position to flat ends the outcome with its true net PnL.
- Actual: such a trade stays INCOMPLETE(OPEN_POSITION) for ever and drops out of n and mean R.
- Reproduction: build `normalize_live_outcomes` input with an ENTRY fill and a fill of an order with no plan role: the outcome reports OPEN_POSITION (by reading; not run).
- Impact: none now (live R is INCOMPLETE anyway while the semantics flag is False, and placement is disabled). With live placement on, the positions closed by the last-line-of-defence path, which are typically the worst outcomes, are excluded from the measured live expectancy, biasing it upward.
- Why tests miss it: test fixtures close positions with SL/TP orders.
- Remediation: map close orders (emergency, manual) to the plan and count them as exits; treat an unexplained flat position as INCOMPLETE with its own reason instead of OPEN_POSITION.

### G-0954 — MFE/MAE use the whole entry minute and the whole exit minute, so prices before the fill and after the exit enter the excursions
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED (probe)
- Classification: DESIGN
- Category: descriptive metric
- Component: excursion engine
- File: `src/analytics/excursion.py`
- Lines: 3-7 (convention), 204-232
- Rule: METRICS §6 diagnostics ("MFE of SL exits", "MAE of TP exits", give-back); RESEARCH assumption A6
- Known-prior: documented as a convention in the module docstring
- Evidence: probe: LONG filled at 100 (backtest fill dated at the minute close 10:00:59.999), entry-minute low 98 (the trade-through that produced the fill), later high 106: MAE 2 = 1.0 R reported, MFE 6. In the backtest, a fill needs a trade one tick through the limit (`entry.py:is_trade_through`), so the entry minute always contributes an adverse excursion of at least one tick and possibly the whole drop that preceded the fill; its high may precede the fill and inflate MFE.
- Expected: excursions measured from the fill onward (in the backtest the fill time is the minute close, so the window could start at the next minute; in live the fill timestamp is known to the millisecond).
- Actual: the diagnostics that are meant to judge stop and target placement (for example "how far did SL exits go in our favour first") are biased by up to one minute of range at each end.
- Reproduction: `python -B analytics_probe.py`.
- Impact: descriptive only; could mislead a later stop/target discussion. No gate uses it.
- Why tests miss it: the convention is the spec.
- Remediation: start the window after the fill minute for backtest evidence, or report the entry-minute range separately.

## Owner decisions
- O-1b (G-0950): how strictly the holdout is single-use. Example: run 1's holdout is 2026-05-10..2026-10-03 (146 days). Under the present text a strategy v5.0.0 candidate may evaluate it once, a v5.1.0 candidate (one parameter changed after seeing v5.0.0 fail) once more, and so on; each look raises the chance that a lucky pass is accepted. Options: (a) one evaluation per holdout window in total, after which a fresh, later window is needed; (b) a fixed small number of lineages per window, enforced in code; (c) keep the present rule (count only). Also: should a later manifest be refused when its Development/Validation overlaps a used or designated holdout?

## Open Questions
- For the live/execution lanes: are emergency-close and manual-close orders persisted with a plan id and any role (G-0953)? I only grepped.
- Backtest R includes funding while live R excludes it (documented in `live_outcomes.py`); on a 2-day hold at 0.01 % per 8 h for a 1.5 % stop the difference is about 0.04 R per trade. A parity comparison must use zero-funding trades, as the docstring says.
- Not read: `src/analytics/provenance.py` in full, the paper and live lifecycle normalizers line by line.
- The funding coverage rule looks up to window end + 8 h 60 s past the exit to validate data; that is data after the decision, used only to refuse a run, never to change a trade (G-1102 covers the constant).

## DONE
