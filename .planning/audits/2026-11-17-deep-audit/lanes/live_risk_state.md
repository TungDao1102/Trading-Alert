# Lane M04: live_risk_state

## Scope
`src/execution/{day_risk_service,daily_stop,margin_guard,symbol_config_guard,bracket_cache,account_equity,live_risk_inputs}.py`,
`src/risk/{daily_loss,live_equity,margin_check,liquidation,reservations,money_at_stake,live_commission}.py`,
`src/live/{risk_inputs,reservation_release,commission}.py`, `src/persistence/{risk_reservations,day_risk}.py`
(snapshot `55885b9`, 7,687 lines). Questions: equity source and staleness, daily loss (D033),
reservations life cycle, margin / leverage / liquidation guard, formulas probed with numbers.

## Coverage
| file | level | note |
|---|---|---|
| src/risk/liquidation.py | DEEP_READ | formula probed (P1) |
| src/risk/daily_loss.py | DEEP_READ | fold, latch, day-open table; probed (P5) |
| src/execution/day_risk_service.py | DEEP_READ | backfill, generation, expiry, late day open |
| src/execution/daily_stop.py | DEEP_READ | no production caller (KNOWN 25-15-F1), see G-0403 |
| src/risk/live_equity.py | DEEP_READ | identities, min(wallet, margin) |
| src/execution/account_equity.py | DEEP_READ | refresh / invalidate / generation |
| src/risk/margin_check.py | DEEP_READ | netting flag is True since D085 (LANES.md says "stays False": the brief is out of date, not the code); probed (P4) |
| src/execution/margin_guard.py | DEEP_READ | order of checks, three freshness re-judgements |
| src/execution/symbol_config_guard.py | DEEP_READ | |
| src/execution/bracket_cache.py | DEEP_READ | |
| src/risk/reservations.py | DEEP_READ | probed (P3) |
| src/persistence/risk_reservations.py | DEEP_READ | PG tests not run (TEST_DATABASE_URL unset by rule) |
| src/persistence/day_risk.py | DEEP_READ | same |
| src/live/reservation_release.py | DEEP_READ | |
| src/execution/live_risk_inputs.py | DEEP_READ | |
| src/live/risk_inputs.py | DEEP_READ | |
| src/risk/money_at_stake.py | NORMAL_READ | lines 1-400 read (builder and invariants); the JSON parser tail only skimmed; display values, no gate |
| src/risk/live_commission.py | DEEP_READ | |
| src/live/commission.py | DEEP_READ | |

Read outside the scope because the lane's claims rest on them: `src/risk/portfolio.py:79-107,169-320`
(`resolve_absolute_thresholds`, `check_portfolio`), `src/risk/sizing.py:30-95`, `src/live/stream.py:240-295,470-520`,
`src/live/stream_persistence.py:205-220`, `src/live/wiring.py` (task specs and call sites by grep),
`config/execution/execution-limits-v1.toml`, `params/breakout-retest/baseline-v*.toml` (risk keys).

Not done: the `*_pg.py` tests were not run (no database, by rule), so the SQL of the two stores (advisory lock,
`FOR UPDATE`, `on_conflict_do_nothing`) is judged by reading only. Official pages read: Account Information V3
(developers.binance.com) and the support FAQ "How to calculate liquidation price of USD-M futures contracts". The first
attempt failed (a usage limit on the fetch tool, then an empty HTTP 202 body by curl); the read after the pause worked.

Probe: `tmp/live_risk_state/probe1.py`, output `tmp/live_risk_state/probe1.out` (imports snapshot code; no network, no database).

## Verified Safe Areas

| Rule or behaviour | What was checked | Where | Why it holds |
|---|---|---|---|
| Isolated liquidation price formula | The official FAQ formula (general form, independent arithmetic in the probe) gives 1153.2565 and 26316.8933 for the two worked examples of the page (page: 1153.26 and 26316.89). The module's isolated closed form equals that formula with TMM = UPNL = 0 and WB = Q x EP x (1/L - f): LONG 64968.853735 (the Demo record is 64968.85373637); SHORT 96596.2367 both ways | `src/risk/liquidation.py:207-222,243-297`; probe P1 | Same algebra on both sides; exact `Fraction` arithmetic; tier chosen by the notional at the liquidation price; conservative pick at an edge |
| Liquidation buffer predicate | At 5x, LONG liquidation is 19.64 % below entry and SHORT 19.48 % above; with the 300 bps buffer a stop up to 16 % from entry passes and 17 % is `LIQUIDATION_TOO_CLOSE` | `liquidation.py:327-341,368-417`; probe P1 | Strict comparison, inverted stop geometry refused, no default for any number |
| Equity fails closed | No reading, age above 15000 ms, negative age, multi-asset mode, any of three identities not exact, missing quote row, equity <= 0: all give `UNCERTAIN_ACCOUNT_STATE` and no `AccountState` | `src/risk/live_equity.py:214-250`; `src/execution/account_equity.py:169-201` | Every branch returns `_no_equity()`; a failed refresh drops the previous reading (`self._reading = None` before the reads); an invalidate during a refresh discards its result (generation counter) |
| Equity is re-read for every placement | `_assemble` calls `equity.refresh()` and then reads the clock; the builder re-checks the age; the margin guard refreshes again and judges the reading three times | `src/live/risk_inputs.py:631-638`; `src/execution/live_risk_inputs.py:185-192`; `src/execution/margin_guard.py:341-343,394,454` | No path sizes on a cached reading older than the bound |
| Equity field | Official page: the top-level totals are "USDT only in single-asset mode"; multi-asset mode is refused | `live_equity.py:214-250` | The identity "total == USDT row" matches the documented single-asset meaning for a USDT account (the value equality on mainnet is still demo-observed only) |
| Daily loss fold | Realized PnL + (minus commission) + funding; one row per key at the most adverse amount; a foreign asset or incomplete sources give unknown, never zero | `src/risk/daily_loss.py:272-352`; probe P5 | Unknown is a `None` loss with `UNCERTAIN_ACCOUNT_STATE`; `check_portfolio` refuses a `None` loss |
| Latch is sticky and survives a restart | `stop_latched_at_utc` is written once (`WHERE column IS NULL`), read before the thresholds, and held in process when the write fails | `daily_loss.py:487-496`; `src/persistence/day_risk.py` `_stamp_once`; `day_risk_service.py:581-612` | A latched row answers DAILY_STOP whatever the loss does; `reserve_in` and `build_live_risk_inputs` both read the row's latch |
| A restart in the middle of a day keeps the base | `open_day` is insert-if-absent and returns the stored row | `persistence/day_risk.py` `open_day` | A second open never moves `equity_at_day_start` |
| A known loss expires | The loss is unknown 300 s after the backfill that made it known, on a generation bump, on a failed read, on a clock error | `day_risk_service.py:614-631` | Backfill cadence is `max_daily_loss_age / divisor`, divisor >= 2 enforced (`src/live/scheduler.py:427,461`) |
| Late day open after a morning gain | Base = equity now - net gain (most favorable amounts), so thresholds are not raised by the gain | `day_risk_service.py:512-517` | Needs a completed backfill first, else the day stays blocked |
| Approvals serialise | One fixed advisory lock, then the day row `FOR UPDATE`, then the plan row `FOR UPDATE`; the counted rows are read inside the same transaction | `src/persistence/risk_reservations.py:386-461` | Two concurrent approvals cannot both pass a cap that only one fits (by reading; PG tests not run) |
| No double count after a release | RELEASED is terminal: `mark_placed` / `mark_open` raise on it; a second release keeps the first reason | `risk_reservations.py:499-559` | No path returns a row to a counted status |
| A consumed plan is never released by plan expiry | The sweep takes the plan path only when no entry intent row exists | `src/live/reservation_release.py:126-142` | An executed plan stays APPROVED; only the outcome (REJECTED intent, FLAT, ENTRY_ENDED_NO_FILL) releases it |
| A margin claim cannot be understated | `required_margin` must equal the ceiling of quantity x price / leverage; the reader re-derives it and treats a mismatch or a missing trio as unknown | `src/risk/reservations.py:121-147,193-218`; `risk_reservations.py:195-213` | An unknown claim gives `UNCERTAIN_ACCOUNT_STATE` in `margin_verdict` |
| Symbol configuration | ISOLATED and 5x are verified by a read after at most one POST each; auto-add-margin refused; a non-flat symbol is never changed; the cap is enforced twice | `src/execution/symbol_config_guard.py`; `margin_guard.py:506-523` | Only the last read decides |
| Bracket cache | Stamp before the request, re-check after it, no stale fallback, a `notionalCoef` other than 1 refused | `src/execution/bracket_cache.py` | |
| Commission | Sizing fee = max(parameter, account taker); a missing, stale or wrong-symbol commission is NO_TRADE; an invalid response drops the previous reading | `src/risk/live_commission.py`; `src/live/commission.py` | |

## Decision review

| Decision / doc rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D033 daily loss = realized PnL + commissions + funding, UTC day, base = equity at day start, warning 0.5 %, stop 1 % | DOUBTFUL (the owner should see the numbers) | arithmetic, risk practice | Realized-only is a common definition and the code follows it. But the "1 % daily stop" does not cap the day at 1 %: with 0.99 % realized and two open positions (aggregate cap 1 %) the day can end near 2 % plus slippage, and a stop latched at 23:55 UTC is gone at 00:00 UTC (07:00 Vietnam). Owner decisions 1 |
| D033 action "cancel pending entries, alert" | SOUND as intent; NOT in the running process | code trace | G-0403 (known) |
| D084 equity age 15000 ms | SOUND | code trace | The bound matters little: every placement re-reads the equity. Its stated basis "any ACCOUNT_UPDATE invalidates" is not true in the composition (G-0402) |
| D086 equity = min(totalWalletBalance, totalMarginBalance) | SOUND | risk practice, official field meaning | An open profit never raises the size, an open loss lowers it |
| D086 multi-asset mode refused; hedge mode refused | SOUND | owner goal (simple, fail closed) | |
| D086 commission added on top of realizedPnl | SOUND | arithmetic | Can only overstate a loss; the mainnet semantics are still unverified (known) |
| D085 5x ISOLATED, buffer 300 bps | SOUND | arithmetic (probe P1) | Liquidation is about 19.5 % away; any stop within 16 % passes. The buffer rarely binds at 5x, which is the safe side |
| D085 netting flag True (`availableBalance` already nets resting orders) | SOUND (low stakes) | exchange behaviour | A wrong True can only end in the exchange rejecting the order (-2019); two Demo samples, mainnet unverified (known) |
| D085 headroom 1000 bps, bracket age 60000 ms | SOUND | arithmetic | Small cost, safe direction |
| D087 a loss expires after 300 s; "any earlier day" opens a new day | SOUND | code trace | The new day's base is always a fresh exchange read |
| Sizing on CURRENT equity, caps on DAY-START equity, with `cluster_cap` = `risk_rate` = 0.5 % | WRONG as a combination | arithmetic (probe P2) | G-0400 |
| No delete path and no operator release reason for a reservation | DOUBTFUL | owner goal (part-time operator) | A row stuck counted (UNKNOWN entry, ENTRY_UNRESOLVED, CLOSE_FAILED) can only be cleared by editing the table. Owner decisions 3 |
| One-shot `alerts_due` returned by `evaluate` | DOUBTFUL | logic | The alert is stamped as due-and-consumed by whoever calls `evaluate` first, even when that caller sends nothing (G-0403) |
| Funding policy `TRADES_WITH_UNVERIFIED_FUNDING` | CANNOT_JUDGE | exchange fact not observed | FUNDING_FEE income rows were never seen on Demo (known R-A9). Funding on a 4H/1H position is small against 0.5 % risk, so the default looks reasonable |

## Findings

### G-0400
- **Severity:** now LOW (paper and backtest results are affected; no order is placed) / mainnet MEDIUM (trades wrongly refused; never an oversize)
- **Confidence:** CONFIRMED for the gate arithmetic (probe); PROBABLE for how often it bites in real use (depends on the step size and on equity drift inside a day)
- **Classification:** DESIGN
- **Category:** risk caps / sizing
- **Component:** portfolio gate inputs (live, paper and backtest share the rule)
- **File:** `src/execution/live_risk_inputs.py`; `src/risk/portfolio.py`; `src/risk/sizing.py`
- **Lines:** live_risk_inputs.py:15-19, 195-212; portfolio.py:307-320; sizing.py:82-83
- **Rule:** RISK_MANAGEMENT section 4 (`cluster_cap` placeholder 0.5 %); params `risk_rate = 0.005`, `cluster_cap = 0.005`; old F-014; Phase 16 incident 16-43
- **Known-prior:** partly. F-014 (2026-09-29) noted that the cap equals one risk unit. Quick task 261108-voe fixed a base mismatch in PAPER after `CLUSTER_CAP_REJECT` on an empty book (loss side). The gain-side reject that remains is not recorded anywhere I found.
- **Evidence:** `live_risk_inputs.py:15-19`: "`account_state` holds the CURRENT resolved equity: it sizes the trade. `parameter_set` holds the thresholds resolved against the persisted DAY-START equity ... The backtest does the same". `sizing.py:82`: `allowed_risk = _mul(account_state.equity, account_state.risk_rate)`. `portfolio.py:315-316`: `cluster_sum = _add(cluster_open_risk, candidate_risk)` then `if cluster_sum > cluster_cap_quote:` reject. The two rates are equal (0.005), so a candidate fits only when current equity x utilization <= day-start equity.
- **Expected:** One full-size trade on an empty book is admitted whenever the account is healthy.
- **Actual:** Probe P2, day-start equity 1000 (cap 5.000), empty book, an XRP-like symbol (step 0.1, entry 2.5, stop 2.45): equity now 1000 -> risk 4.998, OK; 1003 -> 5.01375, `CLUSTER_CAP_REJECT`; 1010 -> 5.04525, `CLUSTER_CAP_REJECT`; 995 -> OK. BTC (step 0.001) at 1010 passes only because rounding leaves 87 % utilization.
- **Reproduction:** `tmp/live_risk_state/probe1.py`, section P2.
- **Impact:** After any net realized gain in the UTC day (or a deposit, or a position that was in unrealized loss at the day open and recovered, because the live base is min(wallet, margin)), a new plan on BTC/ETH/SOL/XRP in the same direction is refused for the rest of the day whenever rounding leaves the utilization above day-start/now. The system trades less after wins than after losses. Backtest and paper share the rule, so the research statistics already contain it (the second trade of a winning day is dropped). The owner reads a refusal named "cluster cap" on an empty book.
- **Why tests miss it:** Tests use one equity for both bases, or the loss side (the 261108-voe regression test). No test sizes on an equity above the day-start base.
- **Remediation:** Owner decision (Owner decisions 2): size against min(current equity, day-start base); or give the cap a margin above one risk unit; or resolve the cap on the same equity as the size. Any of these changes backtest results and needs a new parameter set or simulator version.

### G-0401
- **Severity:** now INFO / mainnet MEDIUM (availability; safe direction)
- **Confidence:** CONFIRMED (probe P3, P4 and call-site search)
- **Classification:** GAP
- **Category:** reservation life cycle
- **Component:** reservation status advance
- **File:** `src/risk/reservations.py`; `src/live/risk_inputs.py`; `src/persistence/risk_reservations.py`
- **Lines:** reservations.py:292-307; risk_inputs.py:645-658, 724-725; risk_reservations.py:463-497
- **Rule:** Phase 21 D-15 / D-16; 24-REVIEW WR-03
- **Known-prior:** KNOWN:24-DEFERRED R-21 (deferred to Phase 25; plan 25-23 not executed at the snapshot). Reported because the recorded effect is understated.
- **Evidence:** `mark_placed` has one caller (the sweep, just before a release, `reservation_release.py:146`) and `mark_open` has none, so a placed or filled plan stays RESERVED. R-21 records only "margin ... counted twice for any other plan (over-refusal)". But `open_positions_from_reservations` builds `explaining` from rows `if row.status in (ReservationStatus.PLACED, ReservationStatus.OPEN)` and returns `None` for an exchange position that no such row explains (reservations.py:292-306); `build_live_risk_inputs` turns `None` into `UNCERTAIN_ACCOUNT_STATE`. The comment at risk_inputs.py:724 ("The builder just explained every exchange exposure by a PLACED or OPEN row") describes a state the process never reaches.
- **Expected:** With one position open (`max_open_positions = 2`), a second plan on another symbol is judged by the caps.
- **Actual:** Probe P3: row RESERVED + exchange position -> `None` (UNCERTAIN_ACCOUNT_STATE); PLACED or OPEN -> judged. Probe P4: with the row RESERVED the margin of the filled plan is added again (required 882.2 against 600 available: INSUFFICIENT_MARGIN; with PLACED: 442.2, OK).
- **Reproduction:** probe sections P3 and P4.
- **Impact:** While any position of the system is open, every later placement is refused whatever the caps say: the system is single-position in fact. Hidden today because the Demo composition tracks one symbol and one plan per symbol. Safe direction. Plan 25-28 (daily-stop wiring) reads its "placed plans" from PLACED/OPEN rows, so it depends on this too.
- **Why tests miss it:** The rig's in-memory reservations and the builder tests set PLACED/OPEN by hand; no test drives a fill through the composition and then a second plan.
- **Remediation:** As R-21 (stamp PLACED at the acknowledgement, OPEN at the first fill), plus a composed test with two symbols.

### G-0402
- **Severity:** now LOW / mainnet LOW to MEDIUM
- **Confidence:** CONFIRMED (code trace)
- **Classification:** DRIFT
- **Category:** daily loss / equity freshness
- **Component:** user-data stream fan-out
- **File:** `src/live/stream.py`; `src/live/stream_persistence.py`; `src/live/wiring.py`
- **Lines:** stream.py:253-266, 481, 506-512; stream_persistence.py:213-220; wiring.py:801
- **Rule:** 24-CONTEXT D-14; Phase 21 D-01; DECISIONS D084
- **Known-prior:** none found
- **Evidence:** 24-CONTEXT D-14: "fills and `ACCOUNT_UPDATE` -> `LiveEquitySource` invalidation and the daily-loss service". `day_risk_service.py:371`: "Called for any ACCOUNT_UPDATE (FUNDING_FEE included) and every stream gap (Phase 24 wires both)". D084: "any ACCOUNT_UPDATE or stream gap invalidates the cached reading". In the composition the router's `account_sink` is `persistence.account_sink` (wiring.py:801), which only enqueues position rows (stream_persistence.py:213-220). `equity.invalidate` is called for a routed FILL and for a gap; `day_risk.invalidate` only for a gap or a failed fill write. No ACCOUNT_UPDATE reaches either.
- **Expected:** A funding fee, a transfer, a liquidation or ADL (an ACCOUNT_UPDATE with no fill the router can route) makes the equity and the day loss unknown until the next REST read.
- **Actual:** Nothing is invalidated; the day loss stays "known" until the next scheduled backfill (cadence at most 150 s, expiry 300 s).
- **Reproduction:** `grep -rn account_sink src` (the wiring hit passes the persistence sink; none calls `invalidate`).
- **Impact:** Bounded. Equity is re-read for every placement, so only the day loss lags, by at most one backfill period. An APPROVE inside that window is judged on a loss that misses a funding fee or a liquidation. The documents (D084, two docstrings, 24-18-SUMMARY) describe a stronger guarantee than the process gives.
- **Why tests miss it:** The live stream tests assert the fill and gap paths; no test sends an ACCOUNT_UPDATE and asserts an invalidation.
- **Remediation:** Call both `invalidate(reason="ACCOUNT_UPDATE")` from the account sink (and trigger a backfill), or correct the documents to "bounded by the backfill period".

### G-0403
- **Severity:** now LOW (placement disabled) / mainnet HIGH (an entry can fill after the daily stop; no stop alert)
- **Confidence:** CONFIRMED (no caller)
- **Classification:** GAP
- **Category:** daily stop enforcement
- **Component:** `enforce_daily_state`
- **File:** `src/execution/daily_stop.py`; `src/live/risk_inputs.py`; `src/execution/day_risk_service.py`
- **Lines:** daily_stop.py:229-325; risk_inputs.py:556-563, 627; day_risk_service.py:581-596
- **Rule:** D033; AGENTS.md ("On DAILY_STOP: cancel pending entries"); OPS-05
- **Known-prior:** KNOWN:25-15-SUMMARY F1 and 25-28-PLAN (owner question Q-J, 2026-11-08; not executed at the snapshot). Reported for the two points below, which the record does not contain.
- **Evidence:** `grep -rn enforce_daily_state src` finds only the module itself and comments in `src/ops/alerts.py`. (1) risk_inputs.py:558-560 says of `evaluate`: "the alert and entry cancels for those belong to the placement path, which keeps calling it". The placement path (`_assemble`, line 627) calls `evaluate` and uses only the verdict's state; nothing cancels and nothing alerts. (2) `evaluate` itself consumes the one-shot marks: it writes the latch and `mark_warning_alerted` (day_risk_service.py:581-596) and returns `alerts_due` only on that call. Both current callers (`open_day`, `_assemble`) drop `alerts_due`.
- **Expected:** At DAILY_STOP the resting entries of placed plans are cancelled, and DAILY_STOP / DAILY_LOSS_WARNING alerts are sent once.
- **Actual:** New approvals and placements are blocked (that part works: `reserve_in`, `build_live_risk_inputs`). A GTD LIMIT entry that already rests stays on the book and can fill after the latch; no daily alert is ever sent. After plan 25-28 adds a third caller, whichever caller evaluates first still takes the one-shot alert, so the alert is lost whenever `open_day` or a CONFIRM latches the day before the new task runs.
- **Reproduction:** read `LiveRiskInputProducer.open_day` and `_assemble`; search for importers of `src.execution.daily_stop`.
- **Impact:** Mainnet: after two stop-outs (1 % of equity) a third resting entry can still open a 0.5 % risk position, and the owner gets no message that the day is stopped.
- **Why tests miss it:** `tests/test_live_alerts_wiring.py:320` calls `enforce_daily_state` directly from the test, not through the composition.
- **Remediation:** Wire it (25-28), and make the alert decision independent of who called `evaluate` first (for example a persisted "alert sent" mark written by the sender, not by `evaluate`).

### G-0404
- **Severity:** now INFO / mainnet LOW to MEDIUM (availability; safe direction)
- **Confidence:** PROBABLE (the fold behaviour is CONFIRMED by probe P5; whether the owner's mainnet account pays fees in BNB is unknown)
- **Classification:** GAP
- **Category:** daily loss
- **Component:** asset check of the fold
- **File:** `src/risk/daily_loss.py`; `src/execution/day_risk_service.py`
- **Lines:** daily_loss.py:327-328; day_risk_service.py:185-193, 221-229
- **Rule:** Phase 21 D-11; old F-031
- **Known-prior:** none found for the operational consequence
- **Evidence:** `if any(row.asset != quote_asset for row in rows): return _unknown_loss()`; the commission component carries `asset=row.commission_asset`. Binance charges the futures commission in BNB when the account's fee-burn switch is on and BNB is in the futures wallet (general exchange behaviour, not re-read on an official page in this run). No code reads that switch (`grep -rn "feeBurn\|fee_burn" src` is empty).
- **Expected:** Either the account setting is checked at start with a plain refusal, or the case is in the runbook.
- **Actual:** Probe P5: one fill with a BNB commission makes the loss `None` (DAILY_LOSS_UNKNOWN). The stored component stays for the whole UTC day, so every approval and placement is refused until 00:00 UTC, with `last_error_type` None (nothing names the cause).
- **Reproduction:** probe section P5, last line.
- **Impact:** After the first fill of a day the system silently stops admitting trades for that day. Fail closed, no money risk; hard to diagnose.
- **Why tests miss it:** The foreign-asset test asserts "unknown", which is the designed result; no test covers the operator-facing consequence.
- **Remediation:** A start-time read of the fee-burn status (refuse or alert when on), or a named blocked reason plus a RUNBOOK line.

## Owner decisions

1. **What "daily stop 1 %" really limits.** The stop counts closed trades only. Example on 1000 USDT: two trades closed for -9.90 in total (state WARNING, not stopped), then two positions open, each risking 5: the day can end at about -19.90 (2 %), not -10. A stop reached at 23:55 UTC (06:55 Vietnam) is lifted at 00:00 UTC. Options: keep it (common practice, simplest); count open risk toward the stop (stricter, fewer trades); a rolling 24 h window.
2. **Trade refused after a winning morning (G-0400).** Example: the day starts at 1000, a trade wins +10, the next XRP plan is sized on 1010: risk 5.045 > cap 5.000, refused as "cluster cap" although nothing is open. Options: size on the smaller of current and day-start equity; raise the cluster cap slightly above one risk unit; compute cap and size on the same equity. Each changes backtest numbers.
3. **A reservation that never ends.** If an entry ends UNKNOWN or unresolved, its row stays counted and (cap = one risk unit) blocks every new entry of that direction until someone edits the database. Options: an audited operator command that releases a row after the owner checked the exchange; or keep the table edit as the documented procedure.
4. **Fees in BNB (G-0404).** If the mainnet account pays futures fees in BNB, the system stops trading after the first fill of each day. Options: switch fee-burn off on the account (simplest); or have the system check it at start.

## Open Questions

- (M03 exec_protection) `ReservationReleaser._executed_reason` releases on the FIRST journaled transition into FLAT or ENTRY_ENDED_NO_FILL for the plan (`reservation_release.py:170-187`). Can the coordinator leave either state again (a late fill found after ENTRY_ENDED_NO_FILL, a residual after FLAT)? If yes, an open position would be uncounted by the caps.
- (M02 exec_placement) Is the ENTRY intent row always written before the approval is consumed and before the POST? The sweep treats "no entry intent row" as "never placed" and releases a RESERVED row at plan expiry or invalidation (`reservation_release.py:133-137`). The 900 s minimum validity covers expiry; an invalidation between the pre-placement check and the intent write is the window to rule out.
- (M05 / M03) Which path, if any, ends an `ENTRY_UNRESOLVED` or `CLOSE_FAILED` plan so that its reservation is released without a table edit?
- (M01 exchange_facts) The paging of `income_in_window` / `user_trades_in_window` and the 1000-row limit decide whether the WR-09 cross-check can miss a row; not inspected here.
- (X09) The 2 % worst-case day (Owner decisions 1) and the cap/size base mismatch (G-0400) both come from decisions that are each reasonable alone.
- Mainnet only, not checkable here: exact equality `totalMarginBalance == totalWalletBalance + totalUnrealizedProfit` at 8 decimals with an open position. An exchange-side rounding difference of 1e-8 would make every reading unusable (fail closed, no trade).
- Docstring nit: `risk_reservations.py:633` calls the loss "realized-plus-unrealized"; the code passes the realized-only loss.

## DONE
