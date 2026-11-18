# Lane M03: exec_protection

## Scope

`src/execution/{protection,emergency_close,protection_rebuild,protection_replay,pending_actions,fill_monitor,cancel_verification,liquidation_watch,live_context}.py`,
`src/persistence/pending_actions.py` at snapshot `55885b9`. Fill-driven protection (D079), stop
and take-profit placement after fills, emergency close, GTD expiry, cancel verification,
replay/rebuild after restart, liquidation watch.

The run was interrupted once (usage limit) and resumed. Probes are in
`tmp/exec_protection/probe_lag.py` and `tmp/exec_protection/probe_close.py`; they import snapshot
code and the project's own test doubles (`tests/support/protection_doubles.py`), no network.

## Coverage

| File | Level | Note |
|---|---|---|
| src/execution/protection.py | DEEP_READ | all 3305 lines |
| src/execution/emergency_close.py | DEEP_READ | all 1199 lines |
| src/execution/protection_replay.py | DEEP_READ | all |
| src/execution/protection_rebuild.py | DEEP_READ | all |
| src/execution/cancel_verification.py | DEEP_READ | all |
| src/execution/liquidation_watch.py | DEEP_READ | all; the formula `src/risk/liquidation.py` belongs to lane M04 |
| src/execution/live_context.py | DEEP_READ | a validated dataclass, no logic of its own |
| src/execution/fill_monitor.py | DEEP_READ | `fold_fills` has no caller in `src`; only `FillEvent` is used |
| src/execution/pending_actions.py | DEEP_READ | all |
| src/persistence/pending_actions.py | NORMAL_READ | lines 30-281; not run (PostgreSQL) |

Read outside the scope, for wiring only (the cited lines):
`config/execution/execution-limits-v1.toml`, `src/live/stream.py:76-78,392-408`,
`src/live/scheduler.py:375-460`, `src/live/wiring.py:685-735`, `src/execution/tp_sizing.py:1-30,140-175`,
`src/execution/manager.py:2222-2256`, `src/domain/algo_status.py` (class table),
`docs/DECISIONS.md` rows D077, D079, D080, D082, D089, D113, D114,
`.planning/phases/24-live-runtime-composition-demo/24-LIMITS-CHECKPOINT.md:17-56`,
`.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md` rows O-04, WR-03, A4.
Not inspected: `attach_protectives_to_fill` beyond its sizing branch, `cancel_untriggered_protectives`,
`emergency_manual_close` (all in `src/execution/manager.py`), the adapter, the reconcile loop.

## State machine as found (protection.py)

States (`ProtectionState`, protection.py:438-449): AWAITING_FILL, ENTRY_UNRESOLVED, UNPROTECTED,
PROTECTED_ENTRY_OPEN, PROTECTED, COMPLETE, TP_UNAVAILABLE, CLOSE_REQUIRED, CLOSE_FAILED, FLAT,
ENTRY_ENDED_NO_FILL. New entries are blocked by UNPROTECTED, CLOSE_REQUIRED, CLOSE_FAILED, by any
PENDING pending-action row, and before `restore` has run (protection.py:1032-1055).

Transitions (handler in brackets):
- NONE -> AWAITING_FILL (`register_resting_entry`, `_install_restored`)
- AWAITING_FILL -> UNPROTECTED (stream fill or REST poll, `_on_first_fill`) / ENTRY_ENDED_NO_FILL
  (`_poll_entry`, `note_entry_resolved`) / ENTRY_UNRESOLVED (`_mark_unknown_entry_unresolved`) /
  CLOSE_REQUIRED (`operator_close`)
- ENTRY_UNRESOLVED -> UNPROTECTED / ENTRY_ENDED_NO_FILL / AWAITING_FILL (`_poll_unresolved_entry`)
- UNPROTECTED -> PROTECTED_ENTRY_OPEN / PROTECTED (`_settle_state`, evidence REST_STOP_CONFIRMED) /
  CLOSE_REQUIRED (B2, B3, B5, B4, NO_POSITION_BUT_EXPOSED) / FLAT (two zero reads + terminal entry)
- PROTECTED_ENTRY_OPEN -> PROTECTED / UNPROTECTED (stop lost) / CLOSE_REQUIRED (B1, B4, B6) / FLAT
- PROTECTED -> COMPLETE / TP_UNAVAILABLE (`_attach_take_profits`) / FLAT / UNPROTECTED / CLOSE_REQUIRED
- COMPLETE, TP_UNAVAILABLE -> FLAT (`_watch_exit`) / UNPROTECTED / CLOSE_REQUIRED
- CLOSE_REQUIRED <-> CLOSE_FAILED -> FLAT (`_close_flow`)
- FLAT: sweep of the three legs until every cancel verifies, then nothing.

Facts that answer the lane questions:
- The stop is ONE `closePosition=True` STOP_MARKET with `quantity=None`, `working_type` from the
  plan snapshot (protection.py:1980-1991). It never has to equal the filled quantity, so a full
  fill, a partial fill, several partials and a late fill are covered by the same order.
- The first fill of any size also cancels the entry remainder (protection.py:1553-1557) and the
  cancel is re-issued every step until REST shows the entry terminal (protection.py:2196-2199).
- Step cadence: `reconcile.tick_interval_ms` = 15000 ms; a tick that follows a stream fill runs
  3 passes back to back with no delay (`WOKEN_STEP_PASSES`, src/live/stream.py:78, 392-408).
- Deadlines: `max_unprotected_ms` 180000, `entry_terminal_timeout_ms` 900000,
  `emergency_close_poll_timeout_ms` 30000, `protection_stall_after_ms` 60000 (alert only).
- Liquidation watch: ACTIVE in the composition (src/live/wiring.py:709-727), policy
  `CLOSE_POSITION` (src/live/risk_inputs.py:362). It runs once per plan, after the stop is confirmed.
- `fill_monitor.fold_fills` and its ENTRY_WITHOUT_PROTECTIVE divergence: INERT (no caller in `src`).

Dead ends / transitions with no handler:
- FLAT (after the sweep) and ENTRY_ENDED_NO_FILL do nothing on later steps, ignore stream fills
  (protection.py:1492-1495) and ignore `notify_divergence` (`recheck_requested` is read by
  `_confirm` only). A wrong FLAT is therefore final for the coordinator (see G-0300).
- CLOSE_FAILED with a close attempt held UNKNOWN has no exit inside the coordinator (see G-0301).
- An entry whose REST status is outside `TERMINAL_ENTRY_STATUSES` / `FILLED_ENTRY_STATUSES`
  (for example `REJECTED`, protection.py:403-406) stays AWAITING_FILL (Open Questions).

## Verified Safe Areas

| Rule or behaviour | What was checked | Where | Why it holds |
|---|---|---|---|
| Stop covers exactly the position after any fill pattern | order parameters | protection.py:1980-1991 | `closePosition=True`, no quantity; nothing is sized from a fill |
| A second / duplicate / out-of-order fill never places a second stop | fill routing | protection.py:1476-1495 | only AWAITING_FILL / ENTRY_UNRESOLVED take a fill as evidence; the stop id is deterministic per plan and query-first |
| A fill missed by the stream is found by REST | `_poll_entry` | protection.py:1637-1688 | every AWAITING_FILL plan is queried by client id every tick; `executedQty > 0` or status PARTIALLY_FILLED/FILLED is a first fill. Cost: up to one tick (15 s) without a stop |
| GTD expiry with a partial fill | same | protection.py:1669-1688 | `executed > 0` wins over the terminal status, so EXPIRED with fills goes to UNPROTECTED and gets a stop |
| A late fill after the cancel | `_confirm`, `_attach_take_profits` | protection.py:2150-2260, 2550-2600 | the entry is read until REST says terminal; take-profits are sized from the REST position only after that; the stop is closePosition |
| "Not found" is never proof of absence for an entry | `_poll_entry`, `confirm_entry_cancel` | protection.py:1661-1663; cancel_verification.py:86-107 | `found is not True` keeps waiting / UNKNOWN |
| Only a REST ACTIVE answer is protection | `_apply_stop_answer`, `_place_stop` | protection.py:2406-2452, 1946-2032 | a placement response never moves the state; -4116 is "exists, awaiting REST"; only status NEW is class ACTIVE (src/domain/algo_status.py) |
| Stop rejected (for example -2021) is never resent | `_on_place_outcome` | protection.py:1563-1580 | REJECTED_DEFINITIVE goes to CLOSE_REQUIRED (B5) and a reduce-only MARKET close |
| A stop proven absent before it was ever confirmed is re-placed under the same id, at most once per step | `_confirm` | protection.py:2216-2226 | needs found=False by id AND a readable listing without the id (`_cross_check_stop`) |
| A confirmed stop that disappears is never re-placed (D077) | `_on_stop_lost`, `_settle_state`, `clearing_violation` | protection.py:2268-2318, 2476-2484; protection_replay.py:95-117 | decided by the position; the transition guard refuses UNPROTECTED -> PROTECTED for a stop-lost plan |
| No new stop in CLOSE_REQUIRED / CLOSE_FAILED / FLAT | `_place_stop` | protection.py:1953-1957 | early return SKIPPED |
| The close never sends a guessed quantity and never two overlapping closes | `close_position`, `_send_part`, `_poll` | emergency_close.py:498-690, 696-835 | each part is sized from a fresh REST position; a pending attempt is polled first; attempt ids are never reused (`discover_next_attempt_no`) |
| Close is reduce-only | adapter docstring only | src/adapters/binance_usdm.py:1403-1408 | One-way sends `reduceOnly=true` (the adapter body belongs to the adapter lane) |
| Journal / store failure never blocks the stop or the close | `_store_write`, `_record_journal`, WR-C8 ordering | protection.py:3205-3231, 2695-2730 | failures enter SAFE_MODE DB_FAILURE once; the close runs before its audit rows |
| Illegal state moves fail closed | `_transition` | protection.py:3021-3090 | table + clearing rules, refusal journaled, SAFE_MODE PROTECTION_STATE_INVALID |
| Restart: nothing is sent by `restore`; unknown history is never read as protected | `restore`, `rebuild_plan` | protection.py:1081-1179; protection_rebuild.py:236-338 | invalid replay or contradicting intent row gives UNPROTECTED with `stop_lost_at`; entries are blocked until `restore` ran |
| Restart: a never-confirmed stop that reads ACTIVE on the first step is adopted, not closed by an expired deadline | `_confirm` order of checks | protection.py:2227-2236 | the deadline branch runs only while `stop_confirmed_at is None` after this step's read |
| Pending-action rows carry no payload and are never replayed as a send | both pending_actions modules | execution/pending_actions.py:108-150; persistence/pending_actions.py:90-160 | no price/qty/side column; the step decides from current exchange state |
| Liquidation check fails closed on unknown values | `LiquidationWatch.check` | liquidation_watch.py:226-262 | None / 0 / negative / inverted geometry -> CLOSE under the wired policy |
| Hedge mode refused | `register_resting_entry`, `restore`, closer | protection.py:985-990, 1115; emergency_close.py:505 | ValueError |

## Decision review

| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D079: no entry-time stop; closePosition STOP_MARKET placed on the first fill, confirmed by REST | SOUND | exchange behaviour (Demo-observed -4509 for a conditional close with no position), practice | The alternative (a sized, non-reduce-only stop resting beside an unfilled entry) can open a position by itself. The cost is a stop-less window of stream latency + one POST, or up to 15 s when the stream misses the fill. |
| D079 item: first fill cancels the entry remainder | DOUBTFUL | arithmetic, owner goals | Safe direction (smaller position), but it turns every partial fill into a smaller trade and, with TP1 = 50 % and the min-notional refusal, into TP_UNAVAILABLE + SAFE_MODE (G-0302). The stop is closePosition, so the cancel is not needed for protection. |
| D077: a confirmed stop that is lost is never re-placed; exposure is closed by MARKET | SOUND (with a cost) | practice, fail closed | Avoids a re-place loop on a stop the exchange keeps removing; the cost is a forced market exit and SAFE_MODE. It makes the close the only protection, so it depends on G-0301. |
| D080 applied to the emergency close: an ambiguous close that REST does not show is never followed by another close | WRONG for a reduce-only order | exchange behaviour, arithmetic of the two risks | A duplicate reduce-only MARKET cannot open or flip a position; a missing close leaves an unprotected position for an unbounded time (G-0301). The rule copies the entry rule to an order with the opposite risk. |
| Two consecutive zero position reads prove flat (T-8-30 as used in protection.py and emergency_close.py) | DOUBTFUL | exchange behaviour | The two reads are issued back to back (milliseconds apart), so they are not independent; a REST view that lags a fill defeats both (G-0300). The project already recorded read-after-write lag on Demo (D113: stop "not found" 0.53 s after its confirmation; plan 261114-kxu: "the read can lag a fill and show flat"). |
| D089 `max_unprotected_ms` = 180000 | DOUBTFUL | arithmetic | Derived only from "longer than the 120 s 429 pause + two ticks" (24-LIMITS-CHECKPOINT.md:22-24); no price-move bound was considered. Owner answer was "follow the recommendation". See Owner decisions. |
| D089 `entry_terminal_timeout_ms` = 900000 (B1) | DOUBTFUL (recorded rationale WRONG) | logic vs code | The recorded reason, "15 minutes gives a slow partial fill time to complete" (24-LIMITS-CHECKPOINT.md:33), contradicts the code, which cancels the remainder on the first fill and again every tick. B1 can only fire when the cancel fails for 15 minutes, and then it market-closes a position that has a confirmed closePosition stop (G-0305). |
| D089 `emergency_close_poll_timeout_ms` = 30000 | CANNOT_JUDGE | - | Only alerts; no Demo timing of a slow close exists (stated in the checkpoint). |
| D114 stall watchdog 60000 ms, alert only | SOUND | measurement | Observe-only; derived from a measured 886 ms maximum. |
| Restart with an unknown stop history: restore UNPROTECTED with `stop_lost_at`, so an open position is market-closed even when its stop is ACTIVE on the exchange | DOUBTFUL | exchange authority | A REST read of the stop by its deterministic id would establish the fact; the rule prefers the journal over the exchange here. Fail closed, rare, costs one forced exit per affected plan. |
| Liquidation watch after the fill, exchange value decides, CLOSE on unknown | SOUND | fail closed | The local price never decides; unknown fails closed. |
| Fill attribution by symbol + side when the exchange order id is unknown | DOUBTFUL | logic | See G-0303; D082 allows two plans on one symbol. |

## Findings

### G-0300
- ID: G-0300
- Severity: MEDIUM now (Demo only, placement disabled) / HIGH on mainnet with placement enabled
- Confidence: PROBABLE (mechanism CONFIRMED by probe; the trigger, a positionRisk answer that still shows no position 0.5-1 s after the fill, is not recorded on Demo)
- Classification: DEFECT
- Category: unprotected position / protection state machine
- Component: ProtectionCoordinator (`_attach_take_profits`, `_second_read_is_flat`, `_sweep`); MarketEmergencyCloser (`_refuse_unconfirmed_flat`)
- File: src/execution/protection.py
- Lines: 2571-2584 (also 2523-2548, 2855-2868; emergency_close.py:531-541, 873-893)
- Rule: D079 invariant "no position without a stop"; T-8-30 / 19-REVIEW CR-03 ("one empty REST answer can therefore never cancel the protection of an open position")
- Known-prior: partly. Quick task 261114-kxu fixed the same lag for the liquidation check only; its summary (`261114-kxu-SUMMARY.md:112,223`) notes that "the attach-take-profits step also reads positionRisk" and that with a flat read "the plan goes FLAT"; no item was opened for it.
- Evidence: `_attach_take_profits`: `if amount == _ZERO: if await self._second_read_is_flat(tracked): if self._transition(tracked, ProtectionState.FLAT, REASON_POSITION_CLOSED, ...): await self._sweep(tracked)` (protection.py:2571-2584). `_second_read_is_flat` issues the second read immediately (protection.py:2523-2548). `make_protection_step` runs 3 passes with no delay after a fill (src/live/stream.py:392-408), so this read happens in the third pass, under a second after the fill (D114 measured a whole protection run at 886 ms at most). The project's own comment: "A flat row can precede the position (positionRisk lags the fill)" (protection.py:1794-1796). Probe `tmp/exec_protection/probe_lag.py` (position reads return no row during the 3 woken passes; the fake's real position and stop stay open):
  ```
  pass 1 state UNPROTECTED
  pass 2 state PROTECTED
  pass 3 state FLAT
  REAL position rows: [('BTCUSDT', '0.004')]
  open algo orders after: []
     UNPROTECTED -> PROTECTED STOP_CONFIRMED_ENTRY_TERMINAL REST_STOP_CONFIRMED
     PROTECTED -> FLAT POSITION_CLOSED REST_FLAT_TWO_READS_ENTRY_TERMINAL
  blocks_new_entries: False
  after 3 more ticks: state FLAT
  ```
- Expected: a position that exists keeps its confirmed stop; a zero read taken a fraction of a second after the fill that created the position is not proof of flat.
- Actual: two back-to-back zero reads right after the fill end the plan FLAT, the sweep cancels the REST-confirmed stop, the plan stops blocking entries and is never looked at again (FLAT has no handler; `notify_divergence` is ignored there).
- Second path, traced not probed: stop definitively rejected on the first pass (B5) -> `_enter_close_required` -> closer reads 0 twice -> "already_flat" True (emergency_close.py:531-541) -> next pass `_close_flow` reads the entry terminal and the closer flat again -> FLAT (protection.py:2855-2868). That position never had a stop.
- Reproduction: `PYTHONPATH=<snapshot> python -B tmp/exec_protection/probe_lag.py`.
- Impact: a filled position with no stop and no take-profit, not tracked by the coordinator. Only the reconcile loop (lane M05) can still notice it, and by project rule it never places rescue protection, so the position stays open until a human acts.
- Why tests miss it: `tests/test_protection_liquidation.py::_PositionReads` scripts only the FIRST position read of a step on purpose ("later reads of the same step (the take-profit attach) see the real rows", lines 426-434); the fake exchange has no read lag; the T-8-30 tests feed a zero then a non-zero read, never two lagging zeros.
- Remediation: do not accept "flat" from reads taken inside the lag window of a fill the plan itself just saw: require the two zero reads on different ticks (or a minimum time since `first_fill_at`), and/or require agreement with the entry's `executedQty` (an entry with executed > 0 and no closing fill cannot be flat). Apply the same rule to the closer's `already_flat` answer. Measure the real lag in Phase 25.

### G-0301
- ID: G-0301
- Severity: LOW now / HIGH on mainnet with placement enabled
- Confidence: CONFIRMED (probe)
- Classification: DESIGN
- Category: emergency close / unbounded unprotected exposure
- Component: MarketEmergencyCloser (`_poll`, `_hold`), ProtectionCoordinator (`_close_flow`, operator controls)
- File: src/execution/emergency_close.py
- Lines: 794-834, 836-873 (also 513-516; protection.py:1953-1957, 1197-1200, 1314-1321)
- Rule: D080 (Q5 "a placement is never re-sent", item 1 covers closes); 19-OWNER-GAPS.md row WR-03; D034 (reduce-only close when the stop is missing)
- Known-prior: KNOWN:19-OWNER-GAPS WR-03 / D080, recorded as "the owner accepts the position may stay open longer, even without a stop". Reported because it is more severe than recorded: the wait is unbounded, not "longer", and D080 was accepted as "the assistant's recommendation ... as written".
- Evidence: `_poll`: `if found is False: pending.mark_unknown(CODE_NOT_FOUND_AFTER_ACK if pending.seen else CODE_ABSENT_AFTER_AMBIGUOUS_SEND); return _Kind.PENDING` (emergency_close.py:807-812); `close_position` returns `_hold(...)` for every PENDING answer before anything else is read or sent (emergency_close.py:513-516). `unknown_code` is only left by a query that finds the order terminal, which cannot happen for an order that never reached the exchange. Probe `tmp/exec_protection/probe_close.py` (the stop is never placed; the first close POST raises a timeout and never reaches the exchange; the exchange is healthy from then on; ticks of 15 s):
  ```
  after ~ 0.25 h: close POSTs=1 state=CLOSE_FAILED closer=PENDING_UNKNOWN/ABSENT_AFTER_AMBIGUOUS_SEND position=[('BTCUSDT', '0.004')]
  after ~    1 h: close POSTs=1 state=CLOSE_FAILED ...
  after ~    8 h: close POSTs=1 state=CLOSE_FAILED ...
  after ~   24 h: close POSTs=1 state=CLOSE_FAILED closer=PENDING_UNKNOWN/ABSENT_AFTER_AMBIGUOUS_SEND position=[('BTCUSDT', '0.004')]
  open stops: 0
  ```
- Expected (yardstick, not the documented intent): an order that can only reduce a position is retried after a bounded wait, because a duplicate is refused or harmless, while a missing close is the largest loss the system can take.
- Actual: one timeout on the one close POST ends all automatic risk reduction for the plan. In CLOSE_REQUIRED / CLOSE_FAILED no stop is placed either (`_NO_NEW_STOP_STATES`), `operator_close` answers `CLOSE_ALREADY_REQUIRED` and `operator_protect` answers `REPLACEMENT_FORBIDDEN_CLOSE_REQUIRED`. One critical alert per pending attempt (`pending.alerted`), then nothing new. A restart keeps the state (`restore_pending`).
- Reproduction: `PYTHONPATH=<snapshot> python -B tmp/exec_protection/probe_close.py`.
- Impact: example: long 0.02 BTC at 60,000 (1,200 USDT notional, 5x isolated, 240 USDT margin) whose stop was never confirmed. A POST timeout during the market stress that caused the failure leaves it open with no stop until the part-time owner reacts to one Telegram alert. The loss is bounded by the isolated margin (240 USDT, a quarter to a half of the stated capital), not by the planned risk (for example 1 % = 5-10 USDT).
- Why tests miss it: the tests assert exactly this behaviour (found=False after an ambiguous send is UNKNOWN, no new attempt); they pin the rule and do not question it.
- Remediation (owner decision): for the reduce-only close only, allow a new attempt under a NEW id after N clean found=False answers spread over a stated time and a fresh non-zero position read; keep the never-resend rule for entries. Until then: repeat the alert while the state lasts, and give the operator a coordinator-level command that works in CLOSE_FAILED.

### G-0302
- ID: G-0302
- Severity: LOW now / MEDIUM on mainnet with placement enabled
- Confidence: CONFIRMED (code path traced; not probed)
- Classification: DESIGN
- Category: partial fill / take-profit availability
- Component: ProtectionCoordinator (`_on_first_fill`, `_attach_take_profits`), `size_take_profits`
- File: src/execution/protection.py
- Lines: 1549-1561 (also src/execution/tp_sizing.py:163-169; src/execution/manager.py:2249-2256; protection.py:2620-2665)
- Rule: D079 items 2 and 5; O-03 (no single-TP fallback)
- Known-prior: the single pieces are known (O-03, D052); their combination with a partial fill is not recorded.
- Evidence: `results = await asyncio.gather(self._place_stop(tracked), self._cancel_entry_remainder(tracked), ...)` on the first fill of any size (protection.py:1553-1557); `if _mul(tp1_qty, tp1_trigger) < filters.min_notional: return _refusal(_NOTIONAL_REJECT)` (tp_sizing.py:168-169, with "No MIN_NOTIONAL exemption is assumed for reduce-only legs"); the refusal becomes TP_UNAVAILABLE with SAFE_MODE ENTRY_WITHOUT_PROTECTIVE and a critical alert (protection.py:2620-2665). `TP1_QUANTITY_FRACTION = Decimal("0.5")` (src/backtest/semantics.py:34).
- Expected: a partial fill is either allowed to complete (the stop is closePosition and already covers every later fill) or still gets a usable exit plan.
- Actual: the position is frozen at whatever filled before the cancel landed. With TP1 = 50 %, any frozen position below 2 x MIN_NOTIONAL at the TP1 price has no take-profit at all, and trading stops in SAFE_MODE until the owner clears it.
- Reproduction (arithmetic): min notional 100 USDT (BTCUSDT mainnet value from memory; read it from exchangeInfo), plan 0.005 BTC at 60,000 = 300 USDT. First fill 0.002 BTC = 120 USDT, remainder cancelled. TP1 = 0.002 x 0.5 = 0.001 BTC x ~61,000 = 61 USDT < 100 -> NOTIONAL_REJECT -> TP_UNAVAILABLE + SAFE_MODE. The position keeps its stop only.
- Impact: live results differ from the backtest (whole fill, TP1/TP2) exactly on small-capital plans; a SAFE_MODE stop for an ordinary market event; fees paid on a fraction-sized trade.
- Why tests miss it: no test combines a partial first fill with the notional refusal.
- Remediation: owner choice among (a) keep the entry working until GTD/terminal instead of cancelling on the first fill, (b) keep the cancel and add a single-TP (closePosition TP2 only) fallback in backtest and live together, (c) keep as is and state the minimum plan notional (4 x MIN_NOTIONAL survives a 50 % partial).

### G-0303
- ID: G-0303
- Severity: LOW now / LOW on mainnet
- Confidence: PROBABLE (code path traced; needs two plans on one symbol, or a re-entry within 60 s)
- Classification: DEFECT
- Category: fill attribution
- Component: ProtectionCoordinator (`_owner_of`, `_adopt_orphan_fills`)
- File: src/execution/protection.py
- Lines: 1497-1511, 1004-1030
- Rule: D082 (more than one plan per symbol is not refused at ingress)
- Known-prior: null
- Evidence: `candidates = [t for t in self._tracked.values() if t.entry_exchange_order_id is None and t.entry.symbol == fill.symbol and t.entry.entry_side == fill.side]; if len(candidates) == 1: candidates[0].entry_exchange_order_id = fill.order_id; return candidates[0]`. The fill carries no client order id (`FillEvent`, fill_monitor.py:66-84) and `RestingEntry` carries no exchange order id, so until the first REST poll answers, ANY fill on the same symbol and side is taken as the plan's first fill: a stop, take-profit or emergency-close fill of an older LONG plan is a SELL and matches a new SHORT plan's entry side. The orphan buffer hands the same kind of fill to a plan registered up to 60 s later.
- Expected: a fill is attributed by the entry's own order id or client order id.
- Actual: a foreign fill moves the new plan to UNPROTECTED, cancels its unfilled entry and places a closePosition stop on the symbol; the wrong order id is stored for the plan.
- Reproduction: not run. Register plan B (SHORT, entry SELL) on a symbol while plan A (LONG) is COMPLETE on it; deliver A's TP1 SELL fill before B's first `_poll_entry` answer.
- Impact: fail-safe direction (a missed entry, a stray stop that the FLAT sweep removes), plus misleading journal rows. No extra exposure found.
- Why tests miss it: `tests/test_protection_orphan_fill.py` covers one plan only; no test has two plans on one symbol.
- Remediation: carry the exchange order id from the placement response into `RestingEntry`, or the client order id on `FillEvent`, and match on it; drop the symbol+side guess.

### G-0304
- ID: G-0304
- Severity: LOW now / LOW on mainnet
- Confidence: PROBABLE (traced, not probed)
- Classification: DEFECT
- Category: false SAFE_MODE
- Component: ProtectionCoordinator (`_confirm`, `_apply_stop_answer`)
- File: src/execution/protection.py
- Lines: 2203-2237, 2437-2452
- Rule: D079 item 2 (B2), D077
- Known-prior: null
- Evidence: a stop that was placed and then triggered before its first REST confirmation reads found=True with a status that is not ACTIVE: `_apply_stop_answer` returns NOT_ACTIVE and records the intent UNKNOWN (protection.py:2437-2452). In `_confirm`, `was_confirmed` is False, so it is not "lost"; the reading is not ABSENT, so nothing is re-placed; the plan waits in UNPROTECTED (blocking entries) until `max_unprotected_ms` and then enters CLOSE_REQUIRED (B2) with SAFE_MODE and a critical alert, although the stop did its job and the position is flat. The same false alarm exists when a tick lands between a stop trigger and the position reaching zero (B4, protection.py:2289-2292).
- Expected: a triggered stop with a flat position (two reads, entry terminal) ends the plan FLAT without SAFE_MODE.
- Actual: 180 s of blocked entries, then SAFE_MODE CLOSE_REQUIRED and a critical alert for a normal stop-out.
- Reproduction: not run.
- Impact: an operator page and a manual SAFE_MODE clear for a non-event; rare with stops far from the entry.
- Why tests miss it: the fakes confirm the stop on the next step; no test triggers it before confirmation.
- Remediation: in UNPROTECTED with a never-confirmed stop that reads TRIGGERED/FINISHED, decide by the position as `_on_stop_lost` does.

### G-0305
- ID: G-0305
- Severity: LOW now / LOW on mainnet
- Confidence: CONFIRMED
- Classification: DRIFT
- Category: decision rationale vs code
- Component: D089 / 24-LIMITS-CHECKPOINT section 2, branch B1
- File: .planning/phases/24-live-runtime-composition-demo/24-LIMITS-CHECKPOINT.md
- Lines: 27-34 (code: src/execution/protection.py:1553-1557, 2196-2199, 2211-2214)
- Rule: D089, D079 item 2
- Known-prior: null
- Evidence: checkpoint: "Reason: 15 minutes gives a slow partial fill time to complete without leaving a half-protected position open for long". Code: the remainder is cancelled on the first fill and "cancelled again on every step until REST says it is terminal". The owner chose 900000 with "follow the recommendation".
- Expected: the number the owner accepted means what he was told.
- Actual: no partial fill is ever given time to complete; the value only decides when a position that HAS a confirmed stop is market-closed because its entry cancel kept failing for 15 minutes (B1).
- Reproduction: read both texts.
- Impact: the owner's picture of partial fills is wrong; the real trade-off of B1 (force-close a protected position, or keep it and rely on B4) was not put to him.
- Why tests miss it: not testable.
- Remediation: restate the key's meaning to the owner and let him confirm or change B1.

### G-0306
- ID: G-0306
- Severity: INFO now / INFO on mainnet
- Confidence: CONFIRMED
- Classification: IMPROVEMENT
- Category: dead code
- Component: `fold_fills`
- File: src/execution/fill_monitor.py
- Lines: 150-290
- Rule: Phase 9 D-02
- Known-prior: null
- Evidence: `grep -rn "fold_fills" src` finds only docstring mentions outside the module; the live process uses `FillEvent` only.
- Expected: the module docstring describes what runs.
- Actual: the "idempotent fill folding" and its ENTRY_WITHOUT_PROTECTIVE divergence are not part of the running system.
- Reproduction: the grep above.
- Impact: none at run time; misleading documentation.
- Why tests miss it: unit tests call the function directly.
- Remediation: mark the function as unused by the live composition or remove it.

## Owner decisions

1. Emergency close after an unknown send (G-0301). Today one close order is sent; if its answer
   is lost and Binance does not show the order, nothing more is ever sent. Example: 0.02 BTC long at
   60,000, 5x isolated (240 USDT margin), no stop. Option A (today): wait for a human; worst case
   the loss is the whole 240 USDT margin. Option B: after, say, 3 "not found" answers over 30 s and
   a fresh position read, send a new reduce-only close; worst case is one extra order that Binance
   refuses or that closes the same position.
2. `max_unprotected_ms` = 180000: the time a filled position may sit without a confirmed stop
   before the market close. It was derived from the 120 s rate-limit pause, not from price risk.
   Example: a 1.5 % adverse move in 3 minutes on a 1,200 USDT position is 18 USDT, against a
   planned risk of perhaps 5-10 USDT. A shorter value closes sooner but also closes healthy
   positions during a 429 pause.
3. Partial fills (G-0302): cancel the remainder on the first fill (today) or let the order work
   until its GTD time; and whether a position too small for TP1 gets a single take-profit.
4. B1 (G-0305): whether a position with a confirmed stop is market-closed when its entry cannot
   be cancelled for 15 minutes.
5. Restart with an unknown stop history: market-close (today) or first read the stop on Binance.

## Open Questions

- (adapter / exchange) How long can `position_information_v3` show no position after a fill, on
  Demo and on mainnet? Not recorded in the repository. One attempt to re-read the official page in
  this run returned a truncated page, so no official text on its timeliness is quoted here. This
  decides the real frequency of G-0300; Phase 25 should measure it.
- (lane M05) Does the reconcile loop act on a position whose plan the coordinator holds FLAT, and
  can anything re-open that plan? `notify_divergence` has no effect on a FLAT plan.
- (adapter) Does `query_order_by_client` ever answer `found=True, status="REJECTED"` or another
  status outside `TERMINAL_ENTRY_STATUSES`? Such an entry stays AWAITING_FILL for ever
  (protection.py:403-406, 1659-1688).
- (adapter) Which failures of `place_market_close` are classified ambiguous (HTTP 503, -1007,
  -1008, connect errors before send)? Each ambiguous one arms G-0301.
- (concurrency lane) The coordinator calls the synchronous intent store and pending-action store
  on the event loop (`_write_stop_intent` runs before the stop POST, protection.py:1917-1944,
  1549-1553); a slow database delays the stop by up to the statement/connect timeout. Not measured.
- (A4/A8, known) Whether Binance refuses a reduce-only MARKET close while the reduce-only TP1 and
  the closePosition legs rest is Demo knowledge only; not verifiable here.
- `emergency_manual_close` and the Telegram operator commands were not inspected in this lane;
  the statement in G-0301 that no coordinator-level control works in CLOSE_FAILED covers
  `operator_close` / `operator_protect` only.

## DONE
