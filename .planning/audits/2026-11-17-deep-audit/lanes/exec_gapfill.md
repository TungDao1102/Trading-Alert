# Lane M02b: exec_gapfill

## Scope
Files the lanes exec_placement (M02) and exec_protection (M03) left unread:
`src/execution/manager.py` 1780-3076 (protective confirmation helpers, `attach_protectives_to_fill`,
the cancels, the manual controls), `execution_limits.py`, `constraint_snapshot.py`, `lot_split.py`,
`lot_filter_source.py`, `tp_sizing.py`. Finding IDs G-0250..G-0299. Built on `lanes/exec_placement.md`
and `lanes/exec_protection.md`; their findings (G-0201..0205, G-0300..0306) are not repeated.
Probes (fake exchange of the project's own test doubles, no network): `tmp/exec_gapfill/probe_stop_flap.py`,
`probe_attach.py`, `probe_lots.py`.

## Progress notes (working, kept for a resumed run)
- run 1: skeleton, all six files read, G-0250 probed and written. Stopped by a usage limit.
- run 2 (resumed): lot and attach probes, remaining findings, tables, JSON. Complete.

## Coverage
| File | Level | Note |
|---|---|---|
| src/execution/manager.py 1780-3076 | DEEP_READ | every line; 1-1780 belongs to exec_placement |
| src/execution/tp_sizing.py | DEEP_READ | all 202 lines, probed with numbers |
| src/execution/lot_split.py | DEEP_READ | all 266 lines, probed with numbers |
| src/execution/lot_filter_source.py | DEEP_READ | all 252 lines; the PostgreSQL store behind `LotFilterStore` not read |
| src/execution/constraint_snapshot.py | DEEP_READ | all 444 lines |
| src/execution/execution_limits.py | DEEP_READ | all 508 lines + `config/execution/execution-limits-v1.toml` + every caller of `require_live_ready` / `unset_keys` |
| src/execution/protection.py | NORMAL_READ 1515-1545, 2240-2475, 2565-2760 only | read as the caller of attach and for the D077 stop read; the file is M03's |
| src/execution/cancel_verification.py | NORMAL_READ | verdict table, used by the cancels in scope |
| src/execution/placement.py 213-440 | NORMAL_READ | the frozen TP sizing that gate 5d calls, for comparison |
| src/adapters/binance_usdm.py | METADATA_ONLY | only the not-found mapping of `query_algo_order_by_client` (1142-1176) |

## Verified Safe Areas
| Rule or behaviour | What was checked | Where | Why it holds |
|---|---|---|---|
| TP legs can only reduce | leg parameters | tp_sizing.py:171-192 | TP1: explicit quantity, `reduce_only=True` (One-way), TAKE_PROFIT_MARKET, working type from the plan snapshot; TP2: `close_position=True`, no quantity. Hedge mode is refused before sizing (manager.py:2204). Probe: `reduce_only True`, `tp2 close_position True None` |
| TP1 is floored, never up, never above the position | arithmetic probe | tp_sizing.py:163-165; lot_split.py:225-239 | `0.0025 -> 0.0020`, `0.0019999 -> 0.0010000`, `0.0005 -> 0`; `min(tp1_qty, position)`; TP2 takes the rest by closePosition, so the legs cannot under- or over-cover |
| TP triggers snap toward the entry | probe | tp_sizing.py:155-161 | SHORT raw 58000.07 on tick 0.1 -> 58000.1 (BUY) |
| Attach never places, re-places or cancels a stop | code read | manager.py:2207-2213, 1997-2037 | only `query_algo_order_by_client`; every non-ACTIVE answer is a hold |
| A TP leg is never POSTed twice | code + probe_attach (a), (b), (c) | manager.py:1924-1947; protection.py:2565 ("exactly once per plan") | query-first by deterministic id; after any hold the plan is TP_UNAVAILABLE and attach is not called again; a CancelledError between TP1 and TP2 leaves PROTECTED and the next step ADOPTS the resting TP1 (POSTs by role: STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2, one each) |
| Write-ahead for TP legs | code read | manager.py:2292-2315 | INTENDED and SENT rows before the POST; a failing intent write sends nothing; `record_protective_intent` is idempotent (`on_conflict_do_nothing`, persistence/execution_state.py:404) |
| A failing result write never undoes a leg | code read | manager.py:2262-2285 | SAFE_MODE DB_FAILURE once, leg kept |
| `cancel_untriggered_protectives` cannot be reached while the coordinator believes a position is open | callers | protection.py:2885 (`_sweep`, FLAT only); manager.py:2977 (manual close after two zero reads + terminal entry) | the only two callers; daily stop and scheduled cancel use `expire_pending_entry` only. The proof of "flat" is the weak point (G-0300 of M03; G-0253 here) |
| Cancels act first, are verified by a query, and "not found" is never read as cancelled for an entry | code read | manager.py:2435-2525; cancel_verification.py:82-107 | `found is not True` -> UNKNOWN; `post_cancel` only for CANCELED |
| Manual close blocks entries before anything else, each step isolated | code read | manager.py:2908-2920, 2934-3010 | disable + SAFE_MODE first, every later step in its own try |
| Unset required limit refuses, never defaults | callers of the gate | src/live/config.py:262-267 (process start), manager.py:835 (every placement), protection.py:869, emergency_close.py:433, reconcile/loop.py:492, intent_recovery.py:517-523, lot_filter_source.py:123-125 | each raises or returns NO_TRADE `LIMITS_NOT_CONFIGURED`; no numeric fallback found by grep; a value must be a positive int with a DECISION-type label, PLACEHOLDER refuses to load |
| The four non-required keys only switch an alert or a refinement | code read | execution_limits.py:132-147 | `reconcile.entry_stale_grace_ms`, `scheduler.protection_stall_after_ms` (alert only), `rest_gate.ban_end_clock_margin_ms`, `scheduler.duration_summary_interval_ms` (refinement); none gates an order |
| Constraint snapshot: unknown is explicit, staleness fails closed | code read | constraint_snapshot.py:197-214, 394-416 | any None -> INCOMPLETE -> not valid for live; `age > ttl or age < 0` is stale; parse rejects floats, unknown keys, foreign version |
| Close splitting arithmetic | probe_lots | lot_split.py:164-222 | 250.5 with market max 120 -> 120 + 120 + 10.5 (sum exact); 130 with min 50 / step 10 / max 120 -> 80 + 50 (no stranded tail); dust 0.0105 -> 0.0100 and `complete=False`; grids that never meet -> empty, nothing rounded up |
| Stale lot filters only for the emergency close | code read | lot_filter_source.py:166-183 | live first, then stored row, then plan snapshot, else `LotFiltersUnavailable`; flagged stale |

## Decision review
| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D-18: TP legs sized from the REST position after the entry is terminal | SOUND | exchange authority | the position is what must be closed; TP2 closePosition removes any rounding gap |
| D-19: floor onto LOT_SIZE ∩ MARKET_LOT_SIZE, never up | SOUND | arithmetic (probe) | closed-form grid, exact integers; a triggered TAKE_PROFIT_MARKET is a market order |
| D077 as implemented: ONE by-id read of a once-seen stop decides a market close; the listing cross-check is switched off "so that D077 stays crisp" | DOUBTFUL | exchange behaviour recorded by the project, cost asymmetry | G-0250. The rule "never re-place" is defensible; deciding it on one read of an endpoint the project has caught answering wrongly three times is not |
| D113: 3 rereads x 0.5 s for the stop read of attach | DOUBTFUL | derivation | reads-only and harmless, but the number is borrowed ("no new number"), not measured against the Demo lag; item 7 admits a longer lag still holds. The fix went to the path with the mild consequence (G-0250, G-0251) |
| "Attach runs exactly once per plan" (protection.py:2566) | DOUBTFUL | logic | right after a POST (never re-send); wrong for holds made before any POST, where a retry cannot duplicate anything (G-0251) |
| D080 applied to TP legs: ambiguous POST -> UNKNOWN, no probe | DOUBTFUL | the decision's own text ("probed once by client order id") | the entry gets its one probe, the TP leg gets none although a read is free (G-0252) |
| O-03: no single-TP fallback; MIN_NOTIONAL applied to the reduce-only TP1 | DOUBTFUL | official error text -4164 "(unless you choose reduce only)" (exchange_facts F14), DVM-05 Demo observations | KNOWN: DVM-05 keeps it "stricter than Demo". Stricter is not safer here: the refusal after a fill is SAFE_MODE with no take profit (M03 G-0302), before a fill it is a lost trade. Owner decision 2 |
| Q3: stale filters allowed for the emergency close only | SOUND | fail closed vs risk reduction | a close sized from hour-old lot filters beats no close |
| NOT_CONFIGURED = refuse, no defaults in code | SOUND | fail closed | verified at seven consumers |
| D-09: manual close never cancels the stop of a position that may be open | SOUND intent, weak proof | exchange behaviour | two back-to-back reads (G-0253) |
| D-17: a cancel counts only when a query shows CANCELED | SOUND | exchange behaviour (-2011 covers "already filled") | implemented as stated |
| `constraint_snapshot_ttl_seconds` = 3600 | CANNOT_JUDGE | - | exchange filter changes are announced days ahead; a stale value yields an exchange reject, not a wrong fill |

## Findings

### G-0250
- ID: G-0250
- Severity: MEDIUM now (Demo only, placement disabled) / HIGH on mainnet with placement enabled
- Confidence: PROBABLE (mechanism CONFIRMED by probe; the trigger, a false "not found" by client id for a stop that an earlier by-id read already showed, is not recorded: the recorded Demo cases are all consistent with a lag right after creation)
- Classification: DESIGN
- Category: protection supervision / forced market close on one read
- Component: ProtectionCoordinator (`_supervise_stop`, `_cross_check_stop`, `_on_stop_lost`); contrast `_read_stop_by_rest` (manager.py)
- File: src/execution/protection.py
- Lines: 2316-2337, 2373-2374, 2268-2284 (contrast src/execution/manager.py:1997-2037, 1758-1759)
- Rule: D077 (stop-lost branch), D113 (rereads for the take-profit step only), plan 20-27 (listing cross-check)
- Known-prior: partly. D113 item 7 records "attach does not use the listing cross-check"; nothing records that the supervision read, whose consequence is a market close, has neither a reread nor the cross-check.
- Evidence: `_supervise_stop`: "One REST query by the deterministic STOP_LOSS id on every step" then `if reading in (_StopReading.ABSENT, _StopReading.NOT_ACTIVE): await self._on_stop_lost(tracked)` (protection.py:2330-2336). `_cross_check_stop` skips the listing on purpose: `if tracked.stop_confirmed_at is not None and tracked.stop_by_id_seen: return answer` with the docstring "so that D077 stays crisp" (2373-2374, 2362-2364). `_on_stop_lost`: `exposed = await self._position_is_open(tracked); if exposed is True: await self._enter_close_required(tracked, BRANCH_B4_FILL_AFTER_STOP)` (2281-2284). The harmless neighbour got the protection instead: D113 gave `_read_stop_by_rest` 4 reads 0.5 s apart, and its only consequence is "no take profit + SAFE_MODE". The project's own records say the by-id query is not reliable on Demo: DECISIONS D113 (1)-(2) "0.53 s later ... `STOP_LOSS: not found` ... the Demo UI showed the reduce-only closePosition STOP_MARKET", plan 20-27 (-2013 for a NEW stop, 2026-10-22), TAKE_PROFIT_2 on 2026-11-01. The read runs every 15 s for the whole life of a position (a 24 h position = about 5,760 single reads; any one false answer is final).
- Probe output (`tmp/exec_gapfill/probe_stop_flap.py`, fake exchange, real closer): state COMPLETE after the fill and after 3 quiet ticks; ONE scripted `found=False` for the stop id; after that single step: `state: CLOSE_REQUIRED`, transition `COMPLETE -> CLOSE_REQUIRED B4_FILL_AFTER_STOP`, `REAL stop on the exchange right after the step: found=True status=NEW`, `REAL position rows: []` (the reduce-only MARKET close was sent and filled), alert `CLOSE_REQUIRED`.
- Expected (yardstick: exchange behaviour as recorded by the project, and the asymmetry of the two errors): before an irreversible market exit, the absence of a stop is established by more than one read and by a second source (the open-algo-orders listing the code already uses elsewhere), spaced in time. Waiting one more tick costs at most 15 s with a position that, if the answer was false, is in fact protected.
- Actual: one `found=False` by id closes the whole position at market, enters SAFE_MODE and ends the plan, while the real stop may still rest. The stop is not re-read afterwards ("never read again").
- Reproduction: `PYTHONPATH=<snapshot> python -B tmp/exec_gapfill/probe_stop_flap.py`.
- Impact: a healthy, protected trade is exited at market (taker fee, slippage, realised loss or lost profit versus the plan) and trading stops until the owner clears SAFE_MODE. Example: long 0.010 BTC at 60,000 with stop 59,000 and TP 62,000/64,000, price at 59,600 when the false answer arrives: realised -4 USDT plus fees instead of a trade still inside its plan; live results then diverge from the backtest for a reason the backtest cannot model. Not an unprotected position (the error is on the risk-reducing side), which is why "now" is MEDIUM.
- Why tests miss it: the tests pin the rule (a confirmed stop read absent once => CLOSE_REQUIRED) as the intended D077 behaviour; the fake never answers a false not-found for a resting order once it was seen.
- Remediation (owner decision, see Owner decisions): for a stop that reads ABSENT while the position is open, require N consecutive ABSENT answers on different ticks and a readable listing without the id before CLOSE_REQUIRED; a found=True with a non-ACTIVE status (TRIGGERED, CANCELED, EXPIRED) can keep acting at once. Keep "never re-place". Measure on Demo how often a by-id query of a resting algo order answers -2013.

### G-0251
- ID: G-0251
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED (code path traced; the first Demo smoke of 2026-11-15 is an instance)
- Classification: DESIGN
- Category: take-profit availability / one-shot step
- Component: `attach_protectives_to_fill` holds; ProtectionCoordinator `_attach_take_profits`, `_enter_tp_unavailable`
- File: src/execution/manager.py
- Lines: 2210-2228, 2309-2315 (also src/execution/protection.py:1525-1537, 2565-2566, 2603-2620, 2640-2658)
- Rule: D113 item 7; D-20; O-03
- Known-prior: partly (D113 item 7: "if the Demo by-id lag outlasts the four reads the hold still happens (fail closed)"). The permanence of every pre-send hold is not recorded as a choice.
- Evidence: holds that happen BEFORE any take-profit POST: `stop_detail = await _read_stop_by_rest(...); if stop_detail is not None: return hold(stop_detail)` (manager.py:2210-2212; an exception on one read, or four not-found answers inside 1.5 s); `elif live_lot_filters is None: return hold("plan snapshot is stale and no live filters were read", ...)` (2225-2228; the coordinator makes exactly one `symbol_lot_filters` read, protection.py:2607-2620, and the snapshot TTL is 3600 s while an entry can fill later than that); `except PersistenceError as exc: return hold(f"{role}: intent store ...")` (2309-2315). Every hold ends in `self._transition(tracked, ProtectionState.TP_UNAVAILABLE, ...)` (protection.py:2658), and from that state the step only runs `_supervise_stop` and `_watch_exit` (1530-1537): "PROTECTED -> COMPLETE or TP_UNAVAILABLE (exactly once per plan)". `operator_protect` places no take profit.
- Expected: a hold made before anything was sent is retried on a later tick (reads are free, nothing can be duplicated); only a hold after a POST is final.
- Actual: one transient failure (a 1.5 s read lag, one failed exchangeInfo read, one database hiccup) leaves the position for its whole life with a stop and no take profit, in SAFE_MODE, with one critical alert. DECISIONS D113 (1): the 2026-11-15 smoke "held SAFE_MODE ENTRY_WITHOUT_PROTECTIVE and stopped" on exactly this path while "the Demo UI showed" the stop.
- Reproduction: read the cited lines; or script `symbol_lot_filters` to raise once with a stale snapshot in the rig of `tests/support/protection_doubles.py`.
- Impact: the owner (part-time) must place both take profits by hand on the exchange or accept a trade that can only end at the stop; results diverge from the backtest (TP1 50 % / TP2). Not a safety loss: the stop is kept.
- Why tests miss it: tests assert the hold and the state; none asks whether a later tick could have completed the legs.
- Remediation: keep PROTECTED (bounded number of ticks, then TP_UNAVAILABLE) for holds that precede the first POST; use the open-algo-orders listing as the second source for the stop read (D113 item 7 leaves this to the owner).

### G-0252
- ID: G-0252
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED (probe)
- Classification: GAP
- Category: ambiguous placement result / take-profit legs
- Component: `_attempt_protective_leg`, `attach_protectives_to_fill` step 5
- File: src/execution/manager.py
- Lines: 1937-1947, 2316-2337
- Rule: D080 ("an ambiguous result is probed once by client order id"); attach docstring item 5 ("the leg counts as confirmed only when a REST query answers ACTIVE")
- Known-prior: null
- Evidence: `except Exception as exc: return _LegAttempt(confirmed=False, detail=f"{role}: {type(exc).__name__}", placement_error=exc)` (1943-1946); then `if attempt.confirmed: failure, exchange_status = await _confirm_leg_by_rest(...)` and `if failure is not None or not attempt.confirmed: store_result_write(role, _intent_result_status(...), None); return hold(...)` (2321-2337): the REST read runs only when the POST response already said ACTIVE. A timeout, a 5xx or a response without a usable `algoStatus` (`_is_leg_confirmed` False, 1947) skips the read. Probe (a), TP1 accepted by the exchange while the client sees `TimeoutError`: `state=TP_UNAVAILABLE open algo: ['STOP_LOSS', 'TAKE_PROFIT_1']`, intent `TAKE_PROFIT_1 ... UNKNOWN`, `TAKE_PROFIT_2 None`, POSTs by role `['STOP_LOSS', 'TAKE_PROFIT_1']`, unchanged after 4 more ticks.
- Expected: after an ambiguous POST the leg is read by its id (as the entry is, D080, and as the helper `_confirm_leg_by_rest` already does with rereads); when it reads ACTIVE the sequence goes on to TP2.
- Actual: TP1 rests on the exchange, the journal says UNKNOWN, TP2 is never sent, SAFE_MODE is entered. Half of the position has a take profit, the other half has none.
- Reproduction: `PYTHONPATH=<snapshot> python -B tmp/exec_gapfill/probe_attach.py` (scenario a).
- Impact: after TP1 fills, the remaining 50 % runs with the stop only until a human acts; the intent table disagrees with the exchange (an UNKNOWN row for a resting order), which reconciliation then has to explain. No duplicate order and no unprotected position.
- Why tests miss it: tests of a raising placement assert the hold; none lets the fake keep the order while raising.
- Remediation: on a placement exception that is not REJECTED_DEFINITIVE, run `_confirm_leg_by_rest` once; ACTIVE continues the sequence, anything else holds as today. Never a second POST.

### G-0253
- ID: G-0253
- Severity: LOW now / LOW on mainnet as wired today (MEDIUM if the control is ever bound to an operator command)
- Confidence: PROBABLE (traced, not probed; the control has no caller in the live process)
- Classification: GAP
- Category: manual control / stop cancelled on a lagging position read
- Component: `emergency_manual_close`, `_protectives_keep_reason`
- File: src/execution/manager.py
- Lines: 2758-2798, 2826-3010
- Rule: EXECUTION_SPEC 11 ("cancelling a protective stop is never part of any of these controls"); Phase 20 D-09; M03 G-0300
- Known-prior: the same read-lag weakness is M03 G-0300 for the coordinator; this path is not mentioned there ("not inspected").
- Evidence: `first = await _read_symbol_exposure(adapter, symbol)` ... `second = await _read_symbol_exposure(adapter, symbol)` with nothing between them (2775-2784), then `if again in PROVEN_GONE or (again is CancelVerdict.FILLED_OR_PARTIAL and detail.observed_status == "FILLED"): return None` (2792-2795) and `cancel_untriggered_protectives` cancels STOP_LOSS first (2668-2672, 2977). A FILLED entry with two zero position reads is read as "the position was closed"; it is equally what a just-filled entry looks like while positionRisk lags (the lag the project recorded in quick task 261114-kxu). Callers: none in `src/live`, `scripts`, `deploy`; `EXEC06_CONTROLS` (3045-3053) does not list it; only `src/ops/drills.py:824-839` takes it as a callable.
- Expected: a control that may cancel a stop proves flat with reads separated in time, or with the entry's executed quantity against closing fills.
- Actual: two reads milliseconds apart; and the function is exported and documented as "the EXECUTION_SPEC 11 manual emergency control sequence" while the running process never calls it.
- Reproduction: not run.
- Impact: none today. If a later phase binds it to a Telegram command, an operator pressing it seconds after a fill could strip the stop from a live position.
- Why tests miss it: the fakes have no read lag.
- Remediation: either delete it in favour of the five `EXEC06_CONTROLS`, or give `_protectives_keep_reason` the same time-separated proof M03 recommends for G-0300.

### G-0254
- ID: G-0254
- Severity: LOW now / LOW on mainnet
- Confidence: CONFIRMED for the arithmetic (probe, synthetic filters); UNVERIFIED that any live-5 symbol has differing LOT_SIZE and MARKET_LOT_SIZE grids
- Classification: DRIFT
- Category: pre-trade gate vs post-fill sizing
- Component: gate 5d (`size_protectives_to_filled_qty`) vs `size_take_profits`
- File: src/execution/manager.py
- Lines: 974-995 (also src/execution/placement.py:251-257; src/execution/tp_sizing.py:163-169; manager.py:2217-2230)
- Rule: O-03; D-19; research A7
- Known-prior: null (M02 asked in its Open Questions which of the two functions the live path uses: both, at different moments)
- Evidence: gate 5d sizes TP1 with the FROZEN function on LOT_SIZE only: `steps = raw_quantity // constraint_snapshot.quantity_step_size ... if rounded < constraint_snapshot.min_quantity` (placement.py:251-256). After the fill, `quantize_to_lot(quantity=raw_tp1, filters=filters, market_exit=True)` floors onto LOT_SIZE ∩ MARKET_LOT_SIZE, and with a stale snapshot uses the LIVE filters (manager.py:2229-2230). Probe with lot step 0.001 and market step/min 0.005: `0.004 floor 0`. A plan of 0.008 passes 5d (TP1 0.004 valid on LOT_SIZE) and is refused after a COMPLETE fill (MIN_QTY_REJECT -> TP_UNAVAILABLE + SAFE_MODE).
- Expected: the gate that promises "the plan needs a sizeable TP1 at the quantity it places" uses the rule the take-profit step will apply.
- Actual: two rules; the pre-trade one is the weaker.
- Reproduction: `probe_lots.py`, section "differing grids".
- Impact: a full fill that ends in SAFE_MODE without take profits, only for a symbol whose two lot filters differ or whose filters changed while the entry rested. On Demo BTCUSDT both grids were 0.0001 (DVM-06), so no effect was seen.
- Why tests miss it: the fixtures use equal grids.
- Remediation: call `size_take_profits` (with `lot_filters_from_plan_snapshot`) in gate 5d as well, keeping the frozen function for the backtest.

### G-0255
- ID: G-0255
- Severity: INFO now / INFO on mainnet
- Confidence: CONFIRMED
- Classification: DRIFT
- Category: documentation vs code; missing sanity bounds
- Component: `execution_limits` module docstring and loader
- File: src/execution/execution_limits.py
- Lines: 3-9, 363-380, 470-489
- Rule: D089, D084, D085, D087, D114
- Known-prior: null
- Evidence: module docstring: "The eighteen required safety keys ... fourteen of them still without a number the owner has chosen"; class docstring: "twenty-three keys: nineteen required, two alert-only, two optional"; the values file has every required key set. Validation is `value <= 0 -> problem` only (377-379); the single cross-key rule is `tick >= deadline` (486).
- Expected: one description; a loader that refuses obviously unsafe magnitudes (for example `max_unprotected_ms` of a day) or at least relations such as `entry_unknown_probe_count x interval < entry_unknown_grace_ms`.
- Actual: any positive integer with a DECISION label loads.
- Reproduction: read the lines.
- Impact: a typing slip in the owner-edited file (an extra zero) is accepted silently. The numbers themselves are judged by M03 (D089 DOUBTFUL).
- Why tests miss it: tests check the shape of the file, not magnitudes.
- Remediation: fix the docstring; add per-key upper bounds or a startup line that prints the effective values in human units for the owner to confirm.

### G-0256
- ID: G-0256
- Severity: INFO now / INFO on mainnet
- Confidence: CONFIRMED (grep over `src`, `scripts`, `deploy`)
- Classification: IMPROVEMENT
- Category: dead code / claims with no caller
- Component: `LotFilterSource.for_entry`, `is_valid_market_part`, `_place_protective_leg`, `emergency_manual_close`
- File: src/execution/lot_filter_source.py
- Lines: 160-164 (also lot_split.py:139-153; manager.py:1950-1962, 2826)
- Rule: Q3 / D-21 ("A NEW ENTRY NEVER MAY" use stored filters)
- Known-prior: null
- Evidence: no call site for any of the four outside their own module and docstrings. The module docstring presents `for_entry(symbol)` as the guard that entries read the exchange live; entries are in fact sized from the plan constraint snapshot (valid up to `constraint_snapshot_ttl_seconds` = 3600 s, params/breakout-retest/baseline-v6.toml:61), not through this method.
- Expected: the stated guard is on the path, or the text says what the path does.
- Actual: the guarantee "never a stored row for an entry" holds only because nothing calls the source for an entry at all.
- Reproduction: `grep -rn "for_entry(\|is_valid_market_part\|_place_protective_leg\|emergency_manual_close" src scripts deploy`.
- Impact: none at run time; a reader (or a later agent) may wire the wrong function, see G-0253.
- Why tests miss it: unit tests call the functions directly.
- Remediation: remove or mark as unused; state in the docstring where entry filters really come from.

## Owner decisions
1. **How sure must the system be that a stop is gone before it sells at market? (G-0250)** Today: one "not found" answer. Example: you are long 0.010 BTC from 60,000, stop 59,000, targets 62,000 / 64,000; price is 59,600. Binance answers one status query wrongly (it did this on Demo on 2026-10-22, 2026-11-01 and probably 2026-11-15, each time shortly after the order was created). The system sells at market: about -4 USDT plus fees, trading stops in SAFE_MODE, and the real stop was there all along. Options: (a) keep one read (fastest reaction if the stop is really gone); (b) require 2-3 "not found" answers on consecutive ticks plus the open-orders listing (a really lost stop is acted on 15-45 s later; a wrong answer no longer closes a good trade). The cap `max_unprotected_ms` (180 s) stays above either.
2. **Take profit below the minimum order value (O-03; M03 G-0302; G-0254).** Binance's own error text and two Demo runs say a reduce-only order is exempt from the minimum. The project still refuses, which after a fill means "no take profit + SAFE_MODE". Options: (a) keep the stricter rule and accept that small plans are never traded and partial fills end in SAFE_MODE (probe: with a 100 USDT minimum, a 0.003 BTC position at a 62,000 target is refused, 0.004 is the smallest that passes); (b) send the reduce-only TP1 anyway and treat a -4164 as the hold; (c) one closePosition take profit when TP1 cannot be sized (needs the same rule in the backtest).
3. **Should the take-profit step try again when nothing was sent yet? (G-0251, G-0252)** Today one failed read means no take profits for that trade. Retrying a read costs nothing and cannot duplicate an order.

## Open Questions
- (adapter lane) Can `query_algo_order_by_client` answer -2013 for an algo order that an earlier by-id query already returned? All recorded Demo cases fit "lag after creation"; a flap would make G-0250 fire in normal operation. Worth a Demo probe: poll a resting stop by id a few thousand times.
- (adapter lane) `next_close_part` and `quantize_to_lot` can return a Decimal with more trailing zeros than the step (`0.0019999 -> 0.0010000`, probe); `size_take_profits` trims it (`_match_step_exponent`), the emergency closer path was not checked for the same trim before the quantity is serialised (-1111 risk only for a position amount that carries extra digits).
- (M03 / reconcile) `_attach_take_profits` sizes TP1 from the whole symbol position (`abs(amount)`) with no upper bound against `entry.entry_quantity`; with two plans on one symbol (D082) or a manual position, TP1 is half of the aggregate and both closePosition legs cover everything. Reduce-only, so not an exposure risk; an attribution question.
- (live composition lane) `emergency_manual_close` is described in its docstring as the manual control sequence but nothing in `src/live` calls it; confirm the operator commands only use `EXEC06_CONTROLS`.
- Not inspected: the PostgreSQL `LotFilterStore`, the adapter body of `place_algo_protective` (which errors are ambiguous), `src/ops/drills.py`.

## DONE
