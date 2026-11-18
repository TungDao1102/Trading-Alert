# Verification V1_protection
| ID | Outcome | Severity now | Severity mainnet | Duplicate of | One-line reason |
|---|---|---|---|---|---|
| G-0250 | DOWNGRADED | LOW | MEDIUM | - | Real: one -2013/-2011 by-id answer for a stop once seen by id skips the listing cross-check and, with exposure, market-closes the position (B4) + SAFE_MODE. But the result fails closed (an unneeded close, not lost protection): the stop is kept until flat and then swept, and a closePosition stop cannot reverse a position. |
| G-0300 | CONFIRMED | LOW | HIGH | - | Probe: PROTECTED, real position 0.010, two scripted empty reads in one step -> FLAT, SL/TP1/TP2 cancelled, position still open, blocks_new_entries False. The two reads run back to back in the 3rd woken pass right after the fill, and the stop read ACTIVE in the same step is ignored. How likely Binance is to return that empty read is not proven. |
| G-0301 | CONFIRMED | LOW | HIGH | - (related: G-2203 is a realistic trigger) | Probe: after one ambiguous send and found=False, every later close_position returns PENDING_UNKNOWN and sends nothing, with no time bound. The plan stays CLOSE_FAILED (it blocks entries) and never reads the position again, even after a manual flatten. operator_close and operator_protect both refuse in CLOSE_REQUIRED/CLOSE_FAILED. |
| G-2203 | CONFIRMED | LOW | HIGH | - (related: G-0301 holds the frozen state) | -4131, -4118, -2023, -2025 and -4045 are absent from ERROR_CODE_TABLE, and any 5xx is STATUS_UNKNOWN whatever the message. Probe: a -4131/-2023/-2025/-1008 refusal of the close gives 1 send, then PENDING_UNKNOWN for ever. A tabled -2022 is re-attempted on every call. |

## G-0250
- Outcome: DOWNGRADED. Severity now LOW (placement disabled), mainnet MEDIUM (claimed now MEDIUM / mainnet HIGH). DESIGN.
- Independent evidence:
  - `src/adapters/binance_usdm.py:1157-1174`: found=False is returned only for an ORDER_ABSENT error of the query (-2013/-2011); every other error raises and is read as UNREADABLE (`protection.py:2392-2405`, state kept).
  - `protection.py:2373-2374`: `if tracked.stop_confirmed_at is not None and tracked.stop_by_id_seen: return answer`. The open-algo listing cross-check is skipped for a stop that a by-id query has shown once, so ONE by-id found=False gives ABSENT (`:2406-2408`).
  - `protection.py:2333-2335`: ABSENT in PROTECTED/COMPLETE/TP_UNAVAILABLE -> `_on_stop_lost`. `:2279-2284` reads the position once; if exposed -> `_enter_close_required(B4_FILL_AFTER_STOP)`, and from there the MARKET close (`:2744`), SAFE_MODE and alert (`:2765-2775`). After flat + entry terminal -> FLAT -> sweep (`:2858-2868`). So "closes at market, SAFE_MODE, ends the plan" holds.
  - "Never read again" holds: `_on_stop_lost` docstring `:2263-2264`. `_settle_state` refuses once `stop_lost_at` is set (`:2481-2482`). `operator_protect` refuses (`:1315-1322`).
- Counter-checks:
  - `_enter_close_required` docstring `:2716-2717`: the stop is not cancelled before flat, so the position keeps its stop during the close. The stop is a closePosition STOP_MARKET (`:1978`), so it cannot open a reverse position after the market close; the sweep then cancels it.
  - A real loss (stop triggered/cancelled) with exposure is correctly closed. The defect is only that a spurious not-found is not cross-checked against the listing (which the code already does for unconfirmed stops, `:2375-2387`) before an irreversible action.
- Notes: the worst case is an unneeded market close (slippage, a lost trade) plus SAFE_MODE. Exposure is never left unprotected. Whether Binance answers -2013 for a live algo order once it has been seen by id is not documented; Demo showed it only right after placement (`:2348-2351`). MEDIUM on mainnet, not HIGH.

## G-0300
- Outcome: CONFIRMED (mechanism). Severity now LOW (no position can exist while placement is disabled), mainnet HIGH. The likelihood of the trigger (two empty REST position answers for an open position) is unproven.
- Independent evidence:
  - `protection.py:1525-1529`: in PROTECTED the step runs `_supervise_stop` (the stop read ACTIVE), then `_attach_take_profits`.
  - `protection.py:2579-2593`: `amount == 0` -> `_second_read_is_flat` (`:2552-2563`, a second `snapshot_positions` called immediately, no spacing) -> FLAT -> `_sweep`.
  - `_sweep` -> `cancel_untriggered_protectives` (`:2885-2899`) does no position check of its own (grep of `manager.py` found none).
  - Timing: `src/live/stream.py:30-33,78,395-407`: after a fill the scheduler runs `WOKEN_STEP_PASSES = 3` passes back to back (place; REST-confirm -> PROTECTED; then supervise + attach). So the two reads can come well under a second after the fill.
  - The fact that the stop was read ACTIVE in the same step, and that Binance auto-cancels a closePosition stop when the position closes (`:98`, A3), is not used to veto FLAT.
  - Probe `tmp/verify_V1_protection/probe_flat.py` (test rig `tests/test_protection_take_profits.py`, `script_empty_position_reads([True, True])`): `PROTECTED -> FLAT (POSITION_CLOSED)`; swept SL, T1, T2; `stop still open: False`; real fake position `0.010`; `blocks_new_entries: False`; the next step stays FLAT.
- Counter-checks: `_row_to_position_snapshot` now raises on a missing positionAmt (`binance_usdm.py:2144-2145`), so a None no longer reads as flat; only a genuinely empty/zero exchange answer triggers this. The reconcile loop classifies POSITION_WITHOUT_STOP -> alert UNPROTECTED_POSITION + DELEGATE_TO_COORDINATOR (`src/reconcile/classify.py`). But `notify_divergence` only sets `recheck_requested` (`protection.py:1124-1146`), and a FLAT plan's step does nothing more (`:1539`), so the position stays unprotected until a human acts.
- Notes: the guard's two reads are correlated (same instant, same server state), so they add little independence. The impact if it happens is a fully unprotected open position with new entries not blocked by the coordinator. What would settle the likelihood: Binance evidence of `/fapi/v3/positionRisk` returning no row for a just-filled position.

## G-0301
- Outcome: CONFIRMED. Severity now LOW, mainnet HIGH. DESIGN.
- Independent evidence:
  - `emergency_close.py:512-516`: a pending attempt is polled first; PENDING -> `_hold`, and nothing else runs (no position read).
  - `:814-819`: found=False always gives `mark_unknown(...)` and PENDING. No path drops the pending entry on found=False. `del self._pending` happens only at `:517` (non-PENDING), `:733`, `:741` and `:760`.
  - `:852-874`: an UNKNOWN attempt alerts once and then returns PENDING_UNKNOWN for ever, with no deadline.
  - `restore_pending` (`:472-497`) re-adopts it after a restart.
  - `protection.py:2837-2873`: `_close_flow` places no stop. `operator_close` refuses with CLOSE_ALREADY_REQUIRED (`:1216-1217`). `operator_protect` refuses with REPLACEMENT_FORBIDDEN_* (`:1317-1323`).
  - CLOSE_FAILED is in BLOCKING_STATES (`:478-484`).
  - Probe `tmp/verify_V1_protection/probe_close.py`: 4 calls over 40 virtual minutes give 1 send, every result `PENDING_UNKNOWN / ABSENT_AFTER_AMBIGUOUS_SEND`, 1 alert.
- Counter-checks: an alert + SAFE_MODE is raised once, so a human can flatten on the exchange. But because the closer never re-reads the position while an attempt is pending, even a manual flatten does not let the plan reach FLAT: the plan blocks new entries indefinitely, with no in-system way to clear it. A resend with a NEW attempt id as reduce-only MARKET cannot over-close (reduce-only), so a bounded retry would be low-risk, measured against Binance semantics rather than the project's Q5 rule.
- Notes: the trigger is realistic through G-2203 (a definitive refusal misread as ambiguous, then -2013 on the query). In branches with no resting stop (B2/B3/B5/B4/NO_POSITION_BUT_EXPOSED) the position stays unprotected until a human acts.

## G-2203
- Outcome: CONFIRMED. Severity now LOW, mainnet HIGH. GAP.
- Independent evidence:
  - The probe of `ERROR_CODE_TABLE` lists the keys present. -4131, -4118, -2023, -2025, -4045 and -1013 are absent. `classify` (`src/domain/exchange_errors.py:766-786`) maps a 400 with an untabled code to UNKNOWN_EXCHANGE_ERROR, and every 5xx to STATUS_UNKNOWN (`:756`) whatever the message. -1008 is SYSTEM_THROTTLED.
  - `emergency_close.py:182-187`: only REJECTED_DEFINITIVE and PRECONDITION_NO_POSITION count as definitive. Otherwise `:748` journals ambiguous, then `_poll` -> found=False -> UNKNOWN (G-0301).
  - Probe `probe_close.py` (BadRequestError with that status code on `place_market_close`):
    - -4131, -2023, -2025 and -1008 each give `sends: 1`, `PENDING_UNKNOWN / ABSENT_AFTER_AMBIGUOUS_SEND` on all 4 calls, phases `pre_send, ambiguous, failed`.
    - The tabled -2022 gives `sends: 4`, `CLOSE_FAILED / REJECTED_NOT_FLAT` (a new attempt on each call).
  - Official docs (developers.binance.com, read 2026-11-18):
    - -4131 MARKET_ORDER_REJECT "The counterparty's best price does not meet the PERCENT_PRICE filter limit".
    - -2023 "User in liquidation mode now".
    - -2025 "Reach max open order limit".
    - -4045 "Reach max stop order limit".
    - -4118 REDUCE_ONLY_MARGIN_CHECK_FAILED.
    - General info: HTTP 503 "Service Unavailable." and "Internal error; unable to process your request. Please try again." are documented as failures; only "Unknown error, please check your request or try again later." is unknown status.
    - -1008: "Close-position, reduce-only ... orders are exempt", so it cannot reach a reduce-only close on mainnet (the -1008 probe line is only illustrative).
- Counter-checks: the query after the refusal answers -2013, which the closer reads as UNKNOWN, never as absence. No later path resends. Classifying an unknown code as ambiguous is fail-closed for a new ENTRY, but for the emergency close it removes the only automatic exit.
- Notes: -4131 on a MARKET order is most likely in fast markets, exactly when an emergency close runs. The root of the freeze is G-0301; G-2203 is the classification gap that feeds it. Not duplicates: fixing either one alone reduces the risk differently.

## DONE
