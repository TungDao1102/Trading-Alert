# Lane X09: decisions_trading_soundness

## Scope

Judge the decisions themselves (intent), not the code: `docs/DECISIONS.md` (D001-D114, focus
D031-D114), `docs/trading/*`, `docs/strategy/*`, `docs/backtest/*`,
`docs/research/RESEARCH_PROTOCOL.md`, `docs/00_PRODUCT_SCOPE.md`, phase CONTEXT / DISCUSSION-LOG /
OWNER-DECISIONS files of Phases 11-25, `params/**`, `config/**`. Snapshot `55885b9`.
Yardsticks: exchange fact, arithmetic (probe), accepted risk/research practice, owner goals.
No opinion on profitability.


## Coverage

| File | Level | Note |
|---|---|---|
| `docs/DECISIONS.md` | NORMAL_READ | D001-D030 first lines; D031-D114 each row to 1.7-2.3k characters; D046 in full; D051, D052, D054, D061, D063, D065 heads only |
| `docs/trading/RISK_MANAGEMENT.md` | DEEP_READ | all sections |
| `docs/trading/EXECUTION_SPEC.md` | NORMAL_READ | sections 4-6.3; rest by grep |
| `docs/trading/SIGNAL_AND_ALERTS.md` | NOT_READ | |
| `docs/strategy/TRADING_STRATEGY_SPEC.md` | NOT_READ | 2 KB pointer file |
| `docs/backtest/BACKTEST_SPEC.md`, `METRICS.md` | METADATA_ONLY | grep only |
| `docs/research/RESEARCH_PROTOCOL.md` | NORMAL_READ | sections 0, 1, 4, 5 (search discipline); 2, 3, 6 not read |
| `docs/research/experiments/research-run-1-v2-3-0/*.json` (240) | DEEP_READ (machine) | all aggregated by script |
| `docs/research/experiments/research-run-1/*.json` | METADATA_ONLY | count only |
| `docs/research/preregistration/*` | NORMAL_READ | constraints baseline, one grid (head), hypothesis by grep |
| `docs/research/holdout_consumed.json`, `kill_gate_decisions.json` | DEEP_READ | both empty |
| `docs/research/GEOMETRY_AUDIT.md`, `TRADING_STRATEGY_RESEARCH.md`, `families/*` | NOT_READ | strategy content |
| `docs/00_PRODUCT_SCOPE.md` | NORMAL_READ | sections 1-6 |
| `params/trend-pullback/baseline-v6.toml` | DEEP_READ | values and every rationale |
| other `params/**` | METADATA_ONLY | listing; grid values seen through the records |
| `config/execution/execution-limits-v1.toml` | DEEP_READ | |
| `config/binance/binance-limits-v1.toml` | METADATA_ONLY | timeout keys by grep |
| `config/paper/*` | NOT_READ | |
| Phase 16 `decisions/` | NORMAL_READ | candidate, EQUITY-BASE, RUN1-SUPERSEDED, G3 draft; others by name |
| Phase 16 `evidence/16-63-run-output.txt`, `16-46-run-output.txt`, `16-63-feasibility-table.md` | DEEP_READ (machine) | |
| Phase 19 `19-DEC-D055-DRAFT.md`, NOTES, CONTEXT, DISCUSSION-LOG, OWNER-GAPS | NORMAL_READ | draft read, others by grep |
| Phase 20 `20-DECISION-AUDIT.md`, `20-DEFERRED.md` | NORMAL_READ | |
| Phase 21, 22, 24 `*-OWNER-DECISIONS.md`, `24-LIMITS-CHECKPOINT.md`, `24-DEFERRED.md` | NORMAL_READ | first sections, keys 1-8 |
| Phases 11-15, 17, 18, 23, 25 CONTEXT / DISCUSSION-LOG | NOT_READ | time; their outcomes were read through the DECISIONS rows |
| `src/execution/protection.py` | NORMAL_READ | docstring, `_step_plan`, `_supervise_stop`, `_cross_check_stop`, `_on_stop_lost` (to check decisions, not to audit the code) |
| `src/risk/sizing.py`, `src/live/wiring.py:1055-1066`, `docker-compose.yml:195-235` | NORMAL_READ | |

Commands used for the tables: `grep -E "^\| D(0[3-9][0-9]|1[01][0-9]) " docs/DECISIONS.md | awk -F'|' '{print $2 "|" substr($4,1,230)}'` (Status column).

## Verified Safe Areas

- Sized loss never exceeds the budget → recomputed the RISK_MANAGEMENT section 2 formula for equity 500/1000, five symbols, stops 0.79-5 % → `viability.out` → flooring only lowers the quantity; utilisation stays 63-100 % or the plan is rejected.
- Cost ceiling claim of D046 item 6 ("0.15 is equivalent to a minimum stop of about 0.79 percent") → probe gives cost share 15.0 % at 0.79 % → the arithmetic in the decision is right.
- Leverage 5x ISOLATED is not what sizes the position → max notional about 0.54 x equity per position (two positions about 1.08 x) → leverage only sets the margin and the liquidation distance (about 19 %), so "leverage is not the starting point" (RISK_MANAGEMENT 1) holds.
- Trade floor G1 is reachable → `16-63-feasibility-table.md`: pooled 140-613 closed trades, 45 of 48 points without a shortfall → the fear recorded in D043 ("the floor may be unreachable") did not materialise; the protocol had enough power for a moderate edge (critical mean about 0.15R at n = 600).
- Holdout untouched → `docs/research/holdout_consumed.json` entries `[]`, run output "G5 floor not assessed (holdout untouched)" → the last 20 % (2026-05-10 onward) is still clean.
- Paper candidate not picked by result → `16-DEC-candidate.md`: first registered point with seed values → no cherry-picking; the opposite problem is G-2101.
- A fill is not missed when the user-data stream is silent → `src/execution/protection.py:1509-1514` polls the entry by REST on every step in AWAITING_FILL → D091's 420 s does not delay protection.
- Never re-send (D080) and "stop never widened" (RISK_MANAGEMENT 6) are conservative choices consistent with fail closed and with an absent operator.
- The project records honestly how each decision was accepted (Status column) and marks Demo observations as "demo-observed, not mainnet" throughout; the one place found where a mainnet behaviour is asserted without a sample is D096 (G-2106).

## Decision review

Yardsticks: EX = exchange fact (as recorded on Demo or in the official docs cited by the project; lane X10 verifies them), AR = arithmetic, RP = accepted risk-management or research practice, OG = owner goal. "Owner?" = did the record show a real choice among alternatives (Y), an accepted recommendation (R) or no question at all (N).

| Decision | One line | Verdict | Yardstick | Owner? | Reason |
|---|---|---|---|---|---|
| D001 | no LLM in the decision path | SOUND | OG, RP | Y | reproducibility; the planning process itself is LLM-made, which is what this audit checks |
| D005/D006/D011 | 4H/1H, limit-zone entries | CANNOT_JUDGE | OG | R | fits a part-time owner on paper; whether the owner can answer alerts valid 4 h is unmeasured (KNOWN:20-DECISION-AUDIT D005) |
| D008 | backtest before paper/live | SOUND, not followed in spirit | RP | Y | the order path was built before the run-1 verdict was read (G-2101) |
| D013/D030 | kill gate: 3 families and 6 months and none passing | SOUND | RP | R | stops endless tuning; two of three conditions are already met in fact (G-2101) |
| D032/D043 | pre-registered thresholds, Holm, single-use holdout | SOUND | RP | N (auto-mode numbers) | conventional and strict; power is adequate at the trade counts reached (236-613 pooled) |
| D033 | daily loss = realized + fees + funding vs UTC day-start equity, stop 1 % | SOUND | RP, AR | R | unrealized loss is excluded but the aggregate open-risk cap bounds it; 1 % = two losses |
| D034 | SAFE_MODE blocks entries only; no stop → close | SOUND | RP, OG | Y | protective actions must never be blocked for an absent operator |
| D035/D085 | ISOLATED, 5x, liquidation beyond SL plus buffer | SOUND | AR | Y (5x), R (300 bps) | max notional about 0.54 x equity per position, margin about 11 % of equity; isolation is the only bound in G-2100 |
| D036 | entry fee modeled as taker | SOUND | RP | R | conservative |
| D037 | SL/TP trigger on MARK_PRICE, same series in backtest | SOUND | EX, RP | Y | avoids last-price wicks and keeps backtest and live on one trigger series; fills still happen at last price |
| D038 | full fills in canonical cost sets | SOUND | RP | R | orders of 50-500 USDT in liquid books |
| D039/D049 | point-in-time universe with delisted symbols, 24 months of 1m | SOUND | RP | Y (1m depth) | removes survivorship bias |
| D040 | SHADOW → DEMO → CANARY → LIVE | SOUND | RP, OG | Y | canary of 50-100 USDT cannot trade BTC (G-2105, KNOWN) |
| D041 | APPROVE then CONFIRM, 60 s | SOUND | OG | Y | guards a mis-tap |
| D042 | single VPS with conditions | DOUBTFUL | AR, logic | Y | condition 1 is false since D079 (G-2100) |
| D046 | quote-per-unit costs, adverse-edge sizing, cost guards | SOUND (formula), DOUBTFUL (slippage numbers) | AR | N (auto-mode), ceiling ratified | probe reproduces 15.0 % at 0.79 %; 1 bp and 3 bps have no measurement |
| D052 | causal simulator (next-bar activation, stop-first tie-break, funding) | SOUND | RP | N mostly | conservative choices; read in part only |
| D054 | geometry correction, PLACEHOLDER values | CANNOT_JUDGE | - | R ("ratify") | strategy content; the set is research-only by its own header |
| D055/D079 | stop placed after the first fill; model (b) not built | DOUBTFUL | EX, AR | R | forced by -4509 for closePosition, but the Demo-accepted alternative and the outage risk were never compared (G-2100) |
| D056/D058 | DEGRADED cannot enable LIVE; stale mark fails closed | SOUND | RP | Y | fail closed |
| D057/D060 | G5 needs 30 holdout trades | DOUBTFUL | RP, AR | Y | a floor, not a test (G-2102) |
| D059 | deferrals; Phase 26 needs a passing candidate | SOUND | RP | Y | makes G-2101 decisive |
| D061/D063/D065/D109 | SHADOW soak evidence rules | SOUND | RP | mixed | strict evidence semantics; outside money path |
| D062/D064/D066 | backup integrity | SOUND | logic | Y (after a test) | D064 corrected a false premise by experiment: good practice |
| D067 | data manifest in experiment identity | SOUND | RP | R | reproducibility |
| D068 | constraints are a declared assumption, S1 stress | SOUND | RP | Y ("chọn C") | honest about extrapolation; baseline BTC min notional 50 vs 100 in S1 |
| D069 | one Holm over 48 hypotheses | SOUND within a run | RP | R | no rule across runs (G-2102) |
| D070 | delisted symbol settled at the adverse bound | SOUND | RP | Y | conservative, no proxy price |
| D073/D075 | warm-up fix, TP2 positivity | SOUND | logic | R | defect fixes applied to all candidates; made after results were visible (G-2102) |
| D077 | a confirmed stop later lost is never re-placed; exposure is closed | DOUBTFUL | EX, RP | Y (typed by the owner) | principle defensible, single read is not (G-2104) |
| D078/D108 | approved quantity bound; alert shows risk-stage figures | SOUND | logic | Y | never more than approved |
| D080 | a placement is never re-sent | SOUND | RP, OG | R | a duplicate order is worse than a missed trade; cost is a manual SAFE_MODE exit |
| D081 | 429/418 pause is not bypassed; stale filters for an emergency close | SOUND | RP | R | closing with stale filters beats leaving exposure; maximum age still unset |
| D082 | symbol ownership checked at reconcile only | DOUBTFUL | logic | R ("accept-narrow") | detection after the fact; KNOWN:20-DECISION-AUDIT; see Open Questions |
| D083 | parse the ban end from a 418 body, bounded | SOUND | logic | R | bounded and fail-safe |
| D084/D087 | equity age 15 s, daily-loss age 300 s | SOUND | AR | Y | stale inputs are NO_TRADE |
| D086 | equity = min(wallet, margin balance); multi-asset refused | SOUND | RP | R | unrealized profit never raises size |
| D088 | one decided approval per plan | SOUND | logic | R | - |
| D089 | fourteen execution limits | DOUBTFUL as a process, values plausible | AR | R (bulk) | G-2103; relationships between keys are pinned by a test |
| D091 | user-data silence 420 s | SOUND | EX (one Demo run) | R | fills are also polled by REST each step (`protection.py:1509-1514`) |
| D092 | Demo treats the kill gate as WITHIN_BUDGET | SOUND for Demo | logic | Y | must stay Demo-only; the true state is G-2101 |
| D093-D095 | REST bound edge, start order, reservation release | SOUND | logic | R | found by running Demo, fixed in the open |
| D096 | last-price age 5 s → 30 s | DOUBTFUL | EX | Y (3 options) | G-2106 |
| D097 | reconcile skips while a placement is in flight | SOUND | logic | R, confirmed later | bounded by `rest_timeout_ms` 5000 and no SDK retries; protection keeps its own deadlines |
| D098-D105 | one process, store executor, migrations, bot identity, operator commands | SOUND | logic | R (bulk) | no command raises risk |
| D106 | live service `restart: "no"` | DOUBTFUL | AR | R | lengthens the outage window of G-2100 from seconds to hours |
| D107 | env split; cancel confirmed by the open list | CANNOT_JUDGE | EX | N | exchange lag claim is X10's |
| D110 | unrestorable entry is cancelled once | SOUND | RP | Y | closes a naked-fill path after restart |
| D111/D112/D114 | stall watchdog, duration record, 60 s | SOUND | logic | Y | alert only by design; 60 s is an inference and says so |
| D113 | three rereads before TP_UNAVAILABLE | SOUND, incomplete | EX | Y | same weakness left in stop supervision (G-2104) |
| Funding policy `TRADES_WITH_UNVERIFIED_FUNDING` | zero income rows count as zero funding | SOUND at this size | AR | Y (option A) | funding on 100-500 USDT notional is cents against a daily stop of 5-10 USDT; mainnet check is on the canary list |
| TP ladder (EXECUTION_SPEC 5) | TP1 reduce-only quantity, TP2 closePosition, both TAKE_PROFIT_MARKET on mark | SOUND | EX, AR | - | taker exit is modeled at taker cost; TP1 below min notional was accepted on Demo (single sample) |
| D044, D045, D047, D048, D050, D051, D053, D071, D072, D074, D076, D090, D099, D100 | records, inventories, CI, persistence, client limits | not judged here | - | - | no trading-soundness content, or owned by other lanes (X10 for D072) |

### Numbers without derivation (what each controls, what a wrong value costs)

| Number | Where | Label | Controls | Cost of a wrong value |
|---|---|---|---|---|
| risk per trade 0.5 % | RISK_MANAGEMENT 1; account `risk_rate` | research baseline | size of every position | too high: drawdown; at 500 USDT lower values make BTC untradeable (G-2105) |
| daily stop 1 %, warning 0.5 % | params, D033 | DECISION ("thresholds stay as in the params") | entries blocked for the UTC day | 1 % = two losses; tighter blocks most days, looser lets a bad day run |
| max_open_positions 2, max_aggregate_open_risk 1 %, cluster_cap 0.5 % | params | PLACEHOLDER | which signals are taken | changes the trade set of research and live (G-2107) |
| minimum_risk_utilization_after_rounding 0.6 | params | STRUCTURAL (RISK_MANAGEMENT 11 itself says "not evidence-backed") | reject after flooring | too high: BTC rejected more often at small equity |
| expected_slippage 1 bp, exit_slippage_rate 3 bps | params, D046 | DECISION (auto-mode default, ratified) | every cost and R figure | understated slippage flatters research; stops in fast alt markets can slip more than 3 bps |
| max_cost_to_risk 0.15, min_stop_distance_rate 0.003 | params, D046 | COST_GUARD | minimum stop about 0.79 % | "derived from the audit maker-entry arithmetic" while entries are modeled as taker; shifts which setups exist |
| minimum_rr 2.0, signal_expiry_hours 4, pivot 3/3, ATR buffers | params | PLACEHOLDER | strategy geometry | research-only until validated; the set is refused for paper by design |
| G1 100 / 30 per fold, N = 25, alpha 0.05, split 40/40/20, G4 20 % | protocol 4, D043 | "Phase 11 auto-mode defaults" | the go/no-go | conventional and conservative values; SOUND |
| G5 floor 30 trades | D057 | DECISION | holdout eligibility | too weak as a test (G-2102) |
| max_unprotected_ms 180000 | D089 | DECISION (default accepted) | how long a filled entry may lack a confirmed stop | derived from the 120 s 429 pause; 3 minutes naked at 5x in a fast market can exceed 1R |
| entry_terminal_timeout_ms 900000 | D089 | DECISION (default accepted) | a part-filled entry whose cancel does not confirm is closed at market after 15 min | too short closes healthy protected positions |
| entry_unknown_grace_ms 1800000 | D089 | DECISION (default accepted) | entries blocked after an UNKNOWN entry | from one Demo observation (840 s) |
| max_last_price_age_ms 30000 | D096 | DECISION | price check at CONFIRM | G-2106 |
| max_user_data_silence_ms 420000 | D091 | DECISION | stale-feed SAFE_MODE | one 45-minute Demo observation; fills are also polled by REST each step, so the exposure is small |
| liquidation_buffer_bps 300, headroom_bps 1000, max_bracket_age_ms 60000 | D085 | DECISION (default accepted) | refuse a plan whose liquidation is near the stop | at 5x the liquidation is about 19 % away, so 300 bps only bites for stops wider than about 16 %; harmless |
| max_equity_age_ms 15000, max_daily_loss_age_ms 300000 | D084, D087 | DECISION | freshness of sizing and loss inputs | from Demo latency, not mainnet |
| protection_stall_after_ms 60000 | D114 | DECISION ("an INFERENCE ... not a measured maximum") | alert only | none for money; the alert may be late or noisy |
| confirm TTL 60 s, D113 rereads 3 x 0.5 s, REST bound 3 of 10, DB write age 60 s | D041, D113, D091 | defaults | operator window and health | usability, not money |

### Mutual consistency of the money/safety set

- Consistent: risk 0.5 %, aggregate cap 1 %, daily stop 1 %, max two positions, ISOLATED 5x, liquidation buffer, MARK_PRICE triggers in backtest and live, taker costs both sides, floor-only quantization. The probe shows no combination in which the sized loss at the stop exceeds the budget.
- Consistent: 420 s stream silence against a 180 s unprotected bound, because a fill is also found by the REST poll of each protection step (15 s tick).
- Inconsistent: D042 condition 1 with D079 and D106 (G-2100).
- Inconsistent in strictness: "flat" needs two reads, "stop lost" one (G-2104).
- Pointless as a whole unless resolved: an execution stack whose go-live gate needs a passing candidate, with a run 1 in which none can pass (G-2101).

## Findings

### G-2100 — D042 condition (1) "the SL always resides on the exchange" is false under D079; the outage window of a resting entry was named a Phase 24 blocker and then dropped
- Severity: now LOW (placement disabled, Demo only) / mainnet HIGH
- Confidence: CONFIRMED (documents and code read; no probe needed, absence of a mechanism)
- Classification: DESIGN (chain of decisions) + GAP (blocker lost between phases)
- Category: decision-consistency / unprotected position
- Component: execution model (D042, D079, D106), live process lifecycle
- File / Lines: `docs/DECISIONS.md` rows D042, D079, D106; `docker-compose.yml:232` (`restart: "no"` for `live`); `docs/operations/RUNBOOK.md:1182`; `.planning/phases/20-reconcile-safe-mode-hardening/20-DEFERRED.md:134`; `.planning/phases/20-reconcile-safe-mode-hardening/20-DECISION-AUDIT.md:21`; `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md:121` (R-22)
- Rule: D042 condition 1, D079 items 1-2, D034 rationale, D106 (Q15)
- Known-prior: KNOWN:20-DEFERRED "Blockers carried to Phase 24" row "VPS or process down while an entry rests" and KNOWN:24-DEFERRED R-22 (graceful stop only). Reported because it is wrongly closed: the blocker row does not appear in `24-CONTEXT.md`, `24-DEFERRED.md`, the Phase 25 scenario catalog or `25-DEFERRED.md` (grep for `countdown`, `down while`, `outage` finds only DB-outage scenarios), D042 was never amended, and no owner acceptance of the risk is recorded.
- Evidence:
  - D042: "Conditions: (1) the protective SL always resides on the exchange so a VPS outage never leaves a position unprotected".
  - D079 item 1: "the protective stop is STOP_MARKET `closePosition=true`, placed after the first fill with positive quantity"; the entry is a GTD LIMIT that rests up to the plan validity (`signal_expiry_hours` 4, grid points 8; minimum remaining validity 900 s).
  - RUNBOOK 22.5 line 1182: "The process does not cancel resting entries on stop, so a GTD LIMIT entry that is still resting can fill while the process is down or restarting and stay without a stop until the next start protects it."
  - `docker-compose.yml:232`: the live service has `restart: "no"`; D106: the owner "may switch the restart policy when ready; it has not been switched".
  - No exchange-side dead-man switch: `grep -ri "countdownCancel|dead.man" src` returns nothing. 20-DEFERRED line 134: "`POST /fapi/v1/countdownCancelAll` is in the official docs; whether it leaves algo orders alone is unverified `[DOC]`, `[NOT_TESTED]`".
  - D034 rationale: "the operator works full-time and cannot react quickly". The only detector of a dead process is the external heartbeat (grace 120 s, D089), which alerts a person; it cancels nothing.
- Expected: either the D042 condition holds (no position can exist without an exchange-resident stop when the host dies), or the residual risk is stated with numbers and accepted by the owner in a DECISIONS row.
- Actual: the two decisions contradict each other. While a GTD entry rests, a crash, host reboot, network partition or a kill leaves an order that can fill with nothing able to place its stop. With `restart: "no"` the gap lasts until the owner restarts by hand. Cancel-on-stop (R-22, Phase 25) covers a requested stop only, not a crash or a partition.
- Reproduction (arithmetic, RISK_MANAGEMENT section 2 formula; `tmp/decisions_trading_soundness/viability.py`): equity 1000, risk 0.5 % = 5 USDT, stop 1 % → notional about 440 USDT, isolated margin at 5x about 88 USDT. Unprotected, the loss is bounded only by the isolated margin: up to about 88 USDT = 8.8 % of equity = about 17 planned risks (17R), against the 1 % daily stop. At equity 500 the same ratios hold (about 44 USDT).
- Impact: mainnet: one outage while an entry rests can cost an order of magnitude more than the daily loss limit; the daily stop, the aggregate cap and SAFE_MODE do not act because the process is down. ISOLATED margin (D035) is the only bound, and it is the thing that makes this HIGH and not CRITICAL.
- Why tests miss it: every test starts from a running coordinator; Demo smokes are attended runs from the development machine (D106: host behaviour NOT_OBSERVED).
- Remediation (for the owner to choose, see Owner decisions O-1): (a) verify `countdownCancelAll` on Demo (does it cancel the resting LIMIT and leave algo protective orders alone) and arm it as a heartbeat while any entry rests; (b) shorten the resting time of an entry to the attended window; (c) set `restart: unless-stopped` for `live` before any unattended entry, so the gap is seconds, not hours; (d) amend D042 condition 1 so it states what is true and record the accepted residual risk with the numbers above.

- Addendum to G-2100 (was the alternative put to the owner?): model (b), a pre-placed `reduceOnly` STOP_MARKET with an explicit quantity, was accepted on Demo while flat and sized equal to the position after the fill (`docs/trading/EXECUTION_SPEC.md` section 6.1, Demo probe 2026-10-16; `19-NOTES.md:16` "Model (b) ... stays a future research direction; the Demo showed it accepted"). `19-DEC-D055-DRAFT.md`, `19-NOTES.md`, `19-CONTEXT.md` and `19-DISCUSSION-LOG.md` contain no word on outage, VPS or a process being down (grep), and D079 was accepted by "làm 1 và 2 trước đi" on the assistant's recommendation. `20-DECISION-AUDIT.md` row D055 already said "D079 never compared (a) and (b) on outage risk"; that comparison is still not written anywhere.

### G-2101 — The research verdict of run 1 is already determinable from committed evidence: no candidate of any of the three families can pass G2/G3; nothing records it, and the paper/Demo candidate a01 has a significantly negative pooled Validation mean
- Severity: now MEDIUM (wrong decision input for the whole roadmap; no money at risk) / mainnet MEDIUM (the go-live gate of Phase 26 has no passing candidate to stand on)
- Confidence: CONFIRMED for the numbers (read from the committed run output, tabulated by `tmp/decisions_trading_soundness/meanr.py`, output `meanr.out`); PROBABLE for "cannot pass G2/G3" (the block-bootstrap interval and the p-values were not computed by this lane; the naive arithmetic leaves no room)
- Classification: GAP (the decisive conclusion is not drawn or recorded) + DESIGN (sequencing: the executable gate was deferred to Phase 26 while Phases 17-24 were built)
- Category: research validity / planning
- Component: research run 1, kill gate D013, Phase 26 goal
- File / Lines: `.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt:121` onward (48 `plateau point` lines, 2.3.0 rerun, committed 2026-10-20); `.planning/phases/16-paper-runtime-composition/evidence/16-46-run-output.txt:108` (first run, committed 2026-10-16 08:23 +0700); `docs/research/kill_gate_decisions.json` (`"families": []`); `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-candidate.md`; `docs/research/RESEARCH_PROTOCOL.md` section 4 (G2, G3, G4)
- Rule: D032, D043, D069 (G1-G5), D013/D030 (kill gate), D008 ("Backtest before paper/live"), D059 item 5 ("Phase 26 requires a passing candidate")
- Known-prior: none found (grep of STATE.md, ROADMAP.md and docs/research for "mean_r", "no candidate", "cannot pass" finds nothing). That the G3 producer is unbuilt is KNOWN (protocol section 4, `16-DRAFT-G3-pvalue-producer-spec.md`).
- Evidence (pooled Validation closed trades, mean net R after costs, as the runner printed them; `closed_trades` equals the `pooled_closed` of the feasibility table `16-63-feasibility-table.md`, so this is the G2 population):
  - trend-pullback: 16 points, mean_r from -0.147 to +0.003. a01 (the designated paper candidate): n=613, mean_r=-0.1019, std 1.103, naive z = -2.29, `observed_max_drawdown_r=78.3`.
  - breakout-retest: 16 points, mean_r from -0.232 to +0.014 (b16: +0.0137, n=149; b16 also misses the G1 fold floor).
  - range-mr: 16 points, mean_r from -0.136 to -0.086.
  - 45 of 48 points have a negative mean; the three positive ones are +0.0027 (a05), +0.0007 (b12) and +0.0137 (b16); the best naive z over all 48 is +0.09. G2 needs the lower 95 % bound above 0 (about z > 1.96 before any dependence adjustment); the first Holm step of G3 needs p < 0.05/48 (z about 3.08).
  - `16-DRAFT-G3-pvalue-producer-spec.md` section 1: "G2 is therefore already computable"; section 0: "The owner of the executable G1-G5 gate code is Phase 26".
  - `16-DEC-candidate.md` (2026-10-16): a01 was designated because it is the first registered point with the seed values; "The assistant disclosed that a01 also has one of the highest closed-trade counts". Its mean R (-0.11 in the first run, printed the same morning) is not mentioned.
- Expected: once the pre-registered run exists, its outcome under the pre-registered gates is computed and recorded (pass or fail per candidate, family entries in `kill_gate_decisions.json`), and the roadmap is re-read against it before more execution work is built.
- Actual: the outcome sits in an evidence file under the label "plateau section: reporting only". Officially the state is WITHIN_BUDGET with no family tested. In fact three independently specified families were run under the frozen methodology and none can pass, which is two of the three D013 conditions (the third, six months, is met on 2027-03-19). Phases 17-24 (the whole order path) were built after 2026-10-16 with no passing candidate, and Phase 26 "requires a passing candidate produced by that work" (D059).
- Reproduction: `python -B -I tmp/decisions_trading_soundness/meanr.py snapshot/.planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt`.
- Impact: the owner is steering a 15-24 month project without the one fact that decides whether the execution half is needed: under the project's own rules, run 1 says no registered strategy is acceptable. This is the protocol's outcome, not this lane's opinion on profitability. The SHADOW soak and the Demo campaign stay valid as infrastructure tests, but they exercise a candidate that its own Validation rejects, so no paper result of a01 can support a go.
- Why tests miss it: tests check the machinery (identity, hashes, the multiplicity step on supplied p-values); no test or gate reads the outcome.
- Remediation: build the small G2/G3 producer now (the draft spec exists), run it once on the 240 records of `research-run-1-v2-3-0`, record the per-family result with a decision reference, and put the consequence to the owner (Owner decisions O-2) before Phase 25/26 work continues.

### G-2102 — The protocol controls false positives inside run 1 only; a second run on the same Validation data is uncontrolled, and G5 (holdout) has no significance requirement
- Severity: now LOW / mainnet MEDIUM (a false "go" would put real money behind noise)
- Confidence: PROBABLE (reading of the protocol text; no run 2 exists yet)
- Classification: DESIGN
- Category: research methodology
- Component: RESEARCH_PROTOCOL v2.6.0 section 4 (G3, G5), amendment procedure
- File / Lines: `docs/research/RESEARCH_PROTOCOL.md:281-285` (G3, G5), `:291` (lineage), `docs/DECISIONS.md` D043, D057, D069
- Rule: D032 ("the number of variants to be tried with a multiple-testing correction, and a single-use holdout")
- Known-prior: none
- Evidence:
  - G3: "one Holm-Bonferroni procedure ... over ONE set of 48 candidate-level p-values ... the set fixed by the three registered grids, never reset per family and never extended by a re-run". The bound covers these 48 only. "Every number below is fixed at freeze; a change forces a new protocol version and a new candidate lineage": a new version starts a new set of hypotheses with a fresh alpha of 0.05.
  - G5: "passes only when mean net R after full costs is above 0 and maximum drawdown is at most 20% on the holdout block", with a floor of 30 trades. No interval and no p-value.
  - The pooled Validation mean, median, std, wins and drawdown of all 48 points and of their grid neighbours are printed in committed evidence (G-2101), so any later grid is designed by people and agents who have seen the Validation outcome.
  - Timeline: first run output with `mean_r` committed 2026-10-16 08:23 +0700; D073 (v2.5.0, warm-up) user decisions of 2026-10-16, row of 2026-10-17; D075 (v2.6.0, TP2 positivity) 2026-10-17. Both amendments were made after Validation performance was visible.
- Expected: a rule for the family-wise error across successive runs on the same Development and Validation data (for example alpha spending across runs, or a fresh Validation period), and a holdout test that a zero-edge candidate fails most of the time.
- Actual: after a failed run 1 (G-2101) the natural next step is run 2 with new parameter sets. Each new protocol version gets a new alpha, the Validation data are no longer unseen, and the last line of defence passes a zero-edge candidate about half the time (a mean above 0 on 30 or more trades is a coin flip under the null; arithmetic, not a probe).
- Reproduction: text reading. Arithmetic: with k independent runs at alpha 0.05 each, P(at least one false Validation pass) = 1 - 0.95^k (k=3: 14 %), times about 0.5 for G5.
- Impact: the protocol is strict today and becomes permissive exactly when it matters, after a first failure. The two amendments made after the numbers were visible (v2.5.0, v2.6.0) are defensible on their own (a simulator defect that suppressed signals for every candidate alike; a plan that crashed the run), changed no threshold, and the rerun stayed negative, so no false pass came from them. They still show that the sentence "no value is ever changed after a result is seen" needs a recorded blind/unblind boundary.
- Why tests miss it: methodology, not code.
- Remediation: before any run 2 the owner decides (O-3) how alpha is spent across runs, whether data after 2026-10-03 become the Validation of run 2, and whether G5 gets a lower-bound condition. Stop printing performance figures in "reporting only" sections until the gate has been evaluated.

### G-2103 — Safety numbers carry the label `DECISION` and the words "the owner's choice" although the owner accepted the assistant's default in bulk; several money/safety decisions were never put to the owner as a choice with consequences in numbers
- Severity: now LOW / mainnet MEDIUM (a wrong number is trusted because it looks owner-ratified)
- Confidence: CONFIRMED (the Status column of DECISIONS and the owner packets say so themselves)
- Classification: DESIGN (decision process)
- Category: governance / numbers without derivation
- Component: `docs/DECISIONS.md` Status column, `config/execution/execution-limits-v1.toml` provenance tables
- File / Lines: `docs/DECISIONS.md` rows D043, D045-D047, D049-D052, D054, D079-D083, D085, D086, D088, D089, D090, D093-D095, D098-D107; `config/execution/execution-limits-v1.toml` `[provenance.*]`; `.planning/phases/24-live-runtime-composition-demo/24-LIMITS-CHECKPOINT.md`; `.planning/phases/22-leverage-margin-liquidation-guard/22-OWNER-DECISIONS.md` (O-2)
- Rule: AGENTS.md "Every parameter value carries a provenance label"; charter section 2.7
- Known-prior: partly self-declared (each row states how it was accepted); the consequence is not recorded anywhere.
- Evidence:
  - D089 Status: `owner answer "theo recommend của bạn hết đi, nếu có chỗ nào khó quyết, hãy thông báo với tôi"`: fourteen limits (among them `protection.max_unprotected_ms` 180000, `entry_terminal_timeout_ms` 900000, `entry_unknown_grace_ms` 1800000, `reconcile.tick_interval_ms` 15000) set in one sentence; every key then reads `DECISION` in the provenance table.
  - `22-OWNER-DECISIONS.md` O-2: "Owner answer: the assistant's recommendation, adopted ... The number is the owner's choice, not a Demo result" for `margin.liquidation_buffer_bps` = 300.
  - D098-D106: nine rows accepted by the same sentence; D090 and D107 state "the owner was not asked".
  - D043, D045, D046, D047, D049, D050, D051, D052, D054: "auto-mode defaults ... the user may override" (the research thresholds, the cost model, the causal simulator, the strategy geometry).
  - D079-D083: one instruction "làm 1 và 2 trước đi" for the execution model, never-re-send, the 429 policy, symbol ownership and the 418 parse.
  - `24-LIMITS-CHECKPOINT.md` gives for each key a meaning, a constraint, an evidence line and a reason, but no worked example of what a too-small or too-large value costs in USDT at the owner's equity.
- Expected: the label tells a reader who really chose. A value the owner picked among alternatives after seeing the cost of each is a different thing from a default the owner did not object to.
- Actual: both are `DECISION`. Of the money/safety rows D031-D114, the ones where the record shows the owner choosing between real alternatives are few: D037 (option b), D049 (1m depth), D052 (TP1 fraction), D064, D068 ("chọn C"), D077, D078 (option a), D084, D085 O-1, D087, D092, D096, D108, D109. The rest are assistant defaults.
- Reproduction: read the Status column (command in the Coverage notes).
- Impact: the next agent treats these numbers as owner-ratified and will not question them (AGENTS.md: "A set value needs a DECISIONS row"), so an under-derived default hardens into policy. The list of under-derived numbers is in "Numbers without derivation" below.
- Why tests miss it: tests pin the values and the label text, not their origin.
- Remediation: add a third label (for example `ASSISTANT_DEFAULT_ACCEPTED`) or a column "owner saw alternatives: yes/no"; re-present the handful of numbers that move money (list in O-4) with one example each.

### G-2104 — D077 makes one negative by-id read of a confirmed stop irreversible (market close + SAFE_MODE), while the same endpoint is recorded as answering "not found" for a resting stop; D113 added rereads only to the take-profit step
- Severity: now LOW / mainnet MEDIUM (a healthy, protected position is closed at market and entries stay blocked until a manual exit; fail-safe, costs spread, fees and the trade)
- Confidence: PROBABLE (code path traced; the false "not found" after a by-id sighting is recorded on Demo as the leading, unproven explanation, D113 item 2)
- Classification: DESIGN (interaction of D077 with the read behaviour recorded in D113 and plan 20-27)
- Category: decision-consistency / protection
- Component: `src/execution/protection.py` `_supervise_stop`, `_cross_check_stop`, `_on_stop_lost`
- File / Lines: `src/execution/protection.py:2316-2337` (one query per step, ABSENT or NOT_ACTIVE → `_on_stop_lost`), `:2372-2373` (`if tracked.stop_confirmed_at is not None and tracked.stop_by_id_seen: return answer`, the listing cross-check is skipped "so that D077 stays crisp"), `:2279-2284` (exposed → CLOSE_REQUIRED, B4); `docs/DECISIONS.md` D077, D113
- Rule: D077 items 1-2 ("The stop is NEVER re-placed ... never read, re-placed or trusted again"), D113
- Known-prior: KNOWN:20-DEFERRED "Stop-out looks like a lost stop (D077)" covers a stop that is mid-trigger; the false-negative read is KNOWN only for the take-profit step (D113). The combination for the supervision step is not recorded.
- Evidence:
  - D113 item 1-2: "PROTECTION_TRANSITION UNPROTECTED to PROTECTED with evidence REST_STOP_CONFIRMED at 08:33:34.51Z and, 0.53 s later ... `STOP_LOSS: not found`"; "Binance Demo answered the query by client id with not found for a stop that rested, as it did on 2026-10-22 (plan 20-27) and for TAKE_PROFIT_2 on 2026-11-01".
  - D113 changes only `_read_stop_by_rest` of `attach_protectives_to_fill` (3 rereads, 0.5 s apart). `_supervise_stop` runs on every protection step (every 15 s tick and on every fill wake) for the whole life of the position and acts on the first negative answer once the stop was seen by id.
- Expected: an irreversible, money-moving action rests on more than one read of an endpoint with a recorded false-negative history (for example the open-algo listing as a second witness, or N consecutive negatives), as the "flat" conclusion already does ("A flat conclusion still needs two consecutive zero position reads", D077 item 3).
- Actual: flat needs two reads; "stop lost, close at market" needs one.
- Reproduction: not run (the M03 lane owns the state-machine probes). Trace: PROTECTED → `_supervise_stop` → by-id `found=False` with `stop_by_id_seen` True → `_apply_stop_answer` ABSENT → `_on_stop_lost` → `_position_is_open` True → `_enter_close_required(B4_FILL_AFTER_STOP)`.
- Impact: with a position held for hours and a read every 15 s, one transient false negative in several hundred reads closes the trade at market. Loss per event is small (round-trip costs, about 0.15R at the cost ceiling, plus the forfeited trade) but each event also puts the system into SAFE_MODE until the owner exits it by hand, and it biases live results against the backtest.
- Why tests miss it: fakes answer consistently; the lag fake (`algo_cancel_query_lag`) models cancel lag, not a false negative on a resting stop.
- Remediation: owner decision O-5 (keep D077 as is and accept the cost, or require a second witness before B4). Measure the false-negative rate of the by-id algo query in the Phase 25 Demo campaign either way.

### G-2105 — Viability at 500-1000 USDT: the sizing works on four of the live-5, BTC is marginal, the canary of D040 cannot trade BTC, and the absolute money at stake is below plausible running costs
- Severity: INFO now / INFO mainnet
- Confidence: CONFIRMED (arithmetic probe `tmp/decisions_trading_soundness/viability.py`, output `viability.out`; prices are round assumptions, constraints from `docs/research/preregistration/research-run-1-constraints-baseline.json`)
- Classification: DESIGN (whole-design question)
- Category: viability
- Component: D035, D040, D046, RISK_MANAGEMENT sections 1-4 and 11
- File / Lines: `docs/trading/RISK_MANAGEMENT.md:11-13, 44, 130`; `docs/DECISIONS.md` D040; `params/trend-pullback/baseline-v6.toml:48-67`
- Rule: owner goal (capital 500-1000 USDT), D040 (canary 50-100 USD)
- Known-prior: KNOWN:20-DECISION-AUDIT section C row D040 (canary cannot reach 50 USDT minimum notional). The rest is new as a consolidated statement.
- Evidence (probe output, risk 0.5 %, fees 5 bps per side, slippage 1 bp in and 3 bps out):
  - 1R is 2.50 USDT at equity 500 and 5.00 USDT at 1000. The daily stop (1 %) is two full losses.
  - ETH, BNB, SOL, XRP: accepted for stops from 0.79 % to 5 %, utilisation 93-100 %.
  - BTC at 100,000 with step 0.001: equity 500 → stop 1 % gives 0.002 BTC (91 %), stop 2 % gives 0.001 BTC (86 %), stop 3 % → MIN_QTY_REJECT. Equity 1000 → stop 3 % gives 0.001 BTC at 63 % utilisation (just above the 60 % floor), stop 5 % → MIN_QTY_REJECT. At BTC 120,000 and equity 500 a 1 % stop is UTILIZATION_REJECT (55 %). So at 500 USDT BTC is tradeable only with stops under about 2.4 %.
  - Round-trip cost is 15.0 % of 1R at a 0.79 % stop (the D046 ceiling, reproduced), 12.2 % at 1 %, 6.5 % at 2 %, 4.4 % at 3 %.
  - Canary 50-100 USDT (D040): BTC always MIN_QTY_REJECT; ETH with a 3 % stop NOTIONAL_REJECT; the alts with min notional 5 are accepted.
  - Economics (assumptions stated): a01 produced 613 Validation trades in about 9.6 months on 12 symbols; if a strategy with a real edge of +0.10R per trade made 250 trades a year, that is 25R = 62 USDT a year at equity 500 and 125 USDT at 1000, before the hosting of one VPS and object storage (assumed 10-20 USD a month, not taken from the repo).
- Expected / Actual: not a defect. The sizing chain is internally consistent and safe at this size. What nobody states in the documents is that at this capital the system cannot pay for its own hosting unless the edge is far larger than the protocol could plausibly certify; its value is research and discipline, as `docs/00_PRODUCT_SCOPE.md` section 1 says ("not to guarantee daily income").
- Impact: expectation management for the owner; BTC behaviour differs between research equity and a 500 USDT account, so live trade sets will differ from the backtest sets for BTC.
- Why tests miss it: not testable.
- Remediation: put these numbers in front of the owner once (O-6).

### G-2106 — D096: a Demo artefact (quiet Demo book) loosened a bound that is shared with LIVE, on an unverified claim about mainnet
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED (text)
- Classification: DESIGN
- Category: numbers without derivation
- Component: `pre_placement.max_last_price_age_ms`
- File / Lines: `docs/DECISIONS.md` D096; `config/execution/execution-limits-v1.toml` (`max_last_price_age_ms = 30000`)
- Rule: D089 (5000), D096 (30000)
- Known-prior: none
- Evidence: D096: "The bound is shared with LIVE; on a liquid mainnet BTCUSDT book the price changes every second or faster, so the looser bound changes nothing there in practice". Three Demo samples (2.1, 1.8, 4.2 s) are the whole basis; the mainnet sentence is an assertion, and the live-5 include thinner books than BTCUSDT.
- Expected: a Demo-only relaxation stays Demo-only (a per-environment value), or the mainnet claim is measured.
- Actual: one value for both. The last-price check then accepts a price up to 30 s old on mainnet; the mark-price bound stays 5 s and the side-of-stop and zone checks remain, so the exposure is small.
- Impact: a slightly stale last price can pass the marketability check in a fast market; the entry is a LIMIT, so the damage is a fill at the limit, not worse.
- Remediation: split the key per environment or revert to 5000 for LIVE after a mainnet read-only measurement at the canary.

### G-2107 — The research run measures each family through the PLACEHOLDER portfolio caps, so most signals are never evaluated and the result depends on undecided numbers
- Severity: now LOW / mainnet LOW
- Confidence: PROBABLE (counts read from the records; a reject may be counted on several bars for one signal, so the ratio is an upper bound)
- Classification: DESIGN
- Category: research methodology
- Component: research runner, portfolio gates
- File / Lines: `docs/research/experiments/research-run-1-v2-3-0/*.json` (`no_trade_counts`), aggregated by `tmp/decisions_trading_soundness/recs.py`; `params/trend-pullback/baseline-v6.toml` rationale `max_open_positions`, `max_aggregate_open_risk`, `cluster_cap` = PLACEHOLDER
- Rule: protocol section 4 (gates on pooled closed trades), R1-R6
- Known-prior: none
- Evidence: trend-pullback Development, 16 points: AGGREGATE_CAP_REJECT 47,117, CLUSTER_CAP_REJECT 19,528, CONFLICT_WITH_OPEN_POSITION 47,161, MAX_POSITIONS_REJECT 3,661, against 171-570 closed trades per point (feasibility table). `cluster_cap` 0.005 equals one position of 0.5 % risk, so a second correlated signal is always refused; `max_aggregate_open_risk` 0.01 allows two.
- Expected: the edge of a setup is estimated on all its signals (per-trade R, portfolio-free), and the portfolio rules are simulated as a second layer.
- Actual: the first-in-time signals that find a free slot are the sample. This is realistic for live trading and not biased in an obvious direction, but it shrinks n, makes the verdict a joint test of setup and placeholder caps, and a later change of a cap changes which trades exist.
- Impact: lower power, and results that cannot be attributed to the setup alone. It does not rescue run 1 (G-2101): the means are negative, not merely imprecise.
- Remediation: report the cap-free per-signal R next to the gated result in any run 2 (a pre-registered descriptive figure, not a gate).

## Owner decisions

- O-1 (G-2100) Resting entry while the process is down. Example at equity 1000: planned loss 5 USDT; a fill with no process alive risks up to about 88 USDT (isolated margin at 5x). Options: (a) probe and arm the exchange auto-cancel timer for resting entries; (b) build the Demo-accepted pre-placed reduce-only stop; (c) accept the risk in writing, with `restart: unless-stopped` and a short entry lifetime; (d) entries only while the owner is reachable.
- O-2 (G-2101) What to do with run 1, where none of the 48 registered candidates can pass. Options: (a) record the result and stop execution work until a new research question is approved; (b) continue the Demo campaign as engineering only, stated as such, with no go-live date; (c) start run 2 only after O-3.
- O-3 (G-2102) Rules for a second research run: alpha across runs, a fresh Validation period, a real test on the holdout.
- O-4 (G-2103) Re-confirm, with one USDT example each: `max_unprotected_ms` 180 s, `entry_terminal_timeout_ms` 15 min, slippage 1 bp / 3 bps, `cluster_cap` 0.5 % (one position per cluster), `minimum_risk_utilization_after_rounding` 60 %.
- O-5 (G-2104) Stop supervision: keep "one negative read closes the position" or require a second witness.
- O-6 (G-2105) Accept that at 500-1000 USDT the system is a research instrument: 1R is 2.5-5 USDT, BTC is often rejected, the canary cannot trade BTC.
- O-7 (G-2106) Last-price age: one value for Demo and LIVE (30 s) or 5 s for LIVE.

## Open Questions

- For X10: does `POST /fapi/v1/countdownCancelAll` cancel a resting LIMIT and leave algo (conditional) orders in place; is a `reduceOnly` STOP_MARKET placed while flat kept on mainnet as it was on Demo; mainnet min notional and step of the live-5 (BTC 50 in the baseline file vs 100 in S1).
- For M03: false-negative rate and handling of the by-id algo query in `_supervise_stop` (G-2104); a stop that is mid-trigger read as lost (KNOWN:20-DEFERRED).
- For M02: D082, a second plan on a symbol with an active plan or position in One-way mode (the first plan's closePosition stop would close both); D101 says an open approval blocks its symbol only until the plan expires. Not traced here.
- For M09: confirm that `mean_r` of the `plateau point` lines is the pooled Validation mean after all costs, and compute the real block-bootstrap interval and p-values for G-2101.
- For X08: what the owner is told to do when the heartbeat reports the live process dead while an entry rests.
- Not judged: the content of the three strategy families (D054) and whether any of them is profitable; BACKTEST_SPEC and protocol sections 2-3 in detail; Phase 11-15 and 17-18 discussion logs.


## DONE
