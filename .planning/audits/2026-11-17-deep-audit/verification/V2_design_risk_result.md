# Verification V2_design_risk
| ID | Outcome | Severity now | Severity mainnet | Duplicate of | One-line reason |
|---|---|---|---|---|---|
| G-2100 | CONFIRMED | LOW | HIGH | - | Entry rests with no exchange stop; crash/partition/reboot with live `restart: "no"` leaves a later fill unprotected until a human restarts; the only tracked follow-up (R-22) covers a requested stop, not a crash; the documented dead-man switch countdownCancelAll is OPT-OUT |
| G-2201 | DOWNGRADED | LOW | MEDIUM | G-2100 (same root) | Facts true (-4509 only for closePosition; Demo accepted a flat pre-placed reduceOnly explicit-qty stop; no reason for rejecting (b) recorded), but (b) has its own trade-offs; the material risk is the outage window of G-2100 |
| G-0403 | DOWNGRADED | LOW | MEDIUM | - | No caller of enforce_daily_state (twin strict xfail reproduces: entry stays, no alert); comment in risk_inputs.py:559-562 is false; evaluate() consumes WARNING stamp and the DAILY_STOP latch call; but new entries are blocked and a late fill still gets its stop, so the overshoot is bounded |

## G-2100
- Outcome: CONFIRMED. Now LOW (LIVE_ORDERS_DISABLED), mainnet HIGH.
- Independent evidence:
  - `docs/DECISIONS.md:46` D042 condition (1): "the protective SL always resides on the exchange so a VPS outage never leaves a position unprotected".
  - `docs/DECISIONS.md:83` D079 (1): "the protective stop is STOP_MARKET `closePosition=true`, placed after the first fill ... Model (b) is not built." `docs/trading/EXECUTION_SPEC.md:231`: "no stop is placed before the first fill; the entry rests without one".
  - `docker-compose.yml:218-232` live service: `restart: "no"` (O-2, 24-01 Q15, "stays off until the owner has seen the first clean Demo run"). Still "no" at 55885b9.
  - `.planning/phases/20-*/20-DEFERRED.md` "Blockers carried to Phase 24": "VPS or process down while an entry rests | After D079 no stop exists until a fill is seen. `POST /fapi/v1/countdownCancelAll` is in the official docs; whether it leaves algo orders alone is unverified".
  - `.planning/phases/24-*/24-DEFERRED.md`: the 20D-01..20D-39 carry-over has no row for this blocker; only R-22 (line 121) covers a *requested* stop ("stopping the live process leaves resting GTD entries ... with nothing watching them"), deferred to an owner decision; crash/partition is not covered. `.planning/phases/25-*/COVERAGE.md:52`: "countdown_cancel_all_open_orders (auto-cancel timer) | OPT-OUT | ... expiry is the project scheduler (24-21) and the GTD backstop" -- both of which need the process alive (scheduler) or are unconfirmed (GTD did not expire on Demo after 840 s, D079 (6), 19-DEC-D055-DRAFT A2).
  - Official doc (developers.binance.com, USDⓈ-M "Auto-Cancel All Open Orders", read 2026-11-18): `POST /fapi/v1/countdownCancelAll` "Cancel all open orders of the specified symbol at the end of the specified countdown"; recommended heartbeat every 30 s with 120000 ms. This is exactly the exchange-side mitigation for an entry resting during an outage; not used.
  - Demo evidence (18-DRAFT-D055-evidence-for-user.md, model (b) table): a pre-placed explicit-quantity reduceOnly STOP_MARKET while flat was accepted (NEW, qty 0.0008), equalled the position after a full fill, and cancelled cleanly after an entry cancel.
- Counter-checks: restart rehydrate exists (24-DEFERRED 20D-06, `tests/test_live_restart_rehydrate.py`) so a *restarted* process will find the fill and place the stop -- but nothing restarts it automatically (restart "no") and a partition with a live process cannot place the stop either. External heartbeat (D042) only alerts a part-time operator. GTD bounds the window only if mainnet honours it (unverified). No outage comparison of (a) vs (b) found in 19-NOTES, 19-DEC-D055-DRAFT, 19-RESEARCH/CONTEXT ("Model (b) ... Demo accepted it; not built").
- Notes: impact on mainnet is an unprotected leveraged position for an unbounded time; probability needs an outage during the resting window and a fill during the outage. HIGH is appropriate for mainnet with placement enabled. Fixes: countdownCancelAll heartbeat (verify it does not cancel algo stops of other plans), enable restart, or model (b).

## G-2201
- Outcome: DOWNGRADED; now LOW, mainnet MEDIUM; DUPLICATE_OF G-2100 (same root: the stop is absent until the process sees a fill).
- Independent evidence:
  - `docs/DECISIONS.md:59` D055: the -4509 observation is for "a closePosition=true STOP_MARKET algo order while ... no position exists"; D055 item (3) explicitly listed the explicit-quantity reduceOnly probe.
  - 18-DRAFT-D055-evidence-for-user.md: "Pre-placed explicit-quantity reduce-only STOP_MARKET while flat: accepted (status NEW, quantity 0.0008)"; "-4509 ... Time in Force (TIF) GTE can only be used with open positions" for closePosition while flat only.
  - `docs/DECISIONS.md:83` D079 text itself does not cite -4509 and gives no reason for rejecting (b); 19-NOTES.md:16: "Model (b) ... stays a future research direction; the Demo showed it accepted and sized equal to the position [DEMO], but it is not built." No rationale anywhere searched (19-NOTES, 19-DEC-D055-DRAFT, 19-RESEARCH, 19-CONTEXT).
- Counter-checks / why downgraded: (b) is not free of risk -- orphan stop must be cancelled when the entry is cancelled (Demo: stayed NEW after cancel), partial fills leave a stop larger than the position (Demo A8 shows reduceOnly clipped to the position, mitigating), a MARK_PRICE trigger can fire while still flat on mark/last divergence, it consumes conditional-order headroom. Choosing (a) is a defensible engineering choice; the defect is an unrecorded trade-off whose material consequence is G-2100. A missing rationale on its own is MEDIUM at most.

## G-0403
- Outcome: DOWNGRADED; now LOW, mainnet MEDIUM (claimed HIGH).
- Independent evidence:
  - grep over `src` and `scripts` for `enforce_daily_state`: only its definition in `src/execution/daily_stop.py` and docstrings in `src/ops/alerts.py:21,877,1070`. No call site in `src/live/*`.
  - `src/live/risk_inputs.py:557-563` (day-risk refresh task): "`evaluate` also latches a stop and stamps a warning, and the alert and entry cancels for those belong to the placement path, which keeps calling it." The placement path (`_assemble`, `src/live/risk_inputs.py:627`) calls `self._day_risk.evaluate(...)` and only passes the verdict to `build_live_risk_inputs` (refusal `DAILY_STOP_BLOCK`); it cancels nothing and alerts nothing. The comment is false.
  - One-shot consumption: `src/execution/day_risk_service.py:582-595`: `evaluate()` persists the latch when `latch_now` and calls `self._store.mark_warning_alerted(...)` when WARNING is in `alerts_due`; `src/risk/daily_loss.py:512-515`: the DAILY_STOP alert is due only together with the new latch, WARNING only while `warning_alerted_at_utc is None`. Both live callers (refresh task :563, placement :627) discard `alerts_due`, so a later caller of `enforce_daily_state` that evaluates again would see empty `alerts_due`: the alerts are lost, not delayed.
  - Probe: snapshot `tests/test_demo_twin_s12_daily_stop.py` run on the composed fake process (PYTHONPATH=snapshot, no DB, no network): observation test passes; strict xfail `test_a_resting_entry_is_cancelled_at_daily_stop_and_the_alert_is_journaled` XFAILs ("the resting entry stays and no DAILY_STOP alert is journaled").
  - `src/execution/daily_stop.py:47-48`: "This producer is NOT wired in a running process until Phase 24"; still unwired at 55885b9.
- Counter-checks / why downgraded: new entries are refused (`DAILY_STOP_BLOCK` at CONFIRM, observed in the twin); a resting entry that fills after DAILY_STOP is still handed to the protection coordinator and gets its stop, so the daily-stop overshoot is bounded by the per-plan risk of entries already resting (and the concurrent-plan caps). Plus a missing operator alert. A bounded risk-limit overshoot with a missing alert is MEDIUM on mainnet, not HIGH.
- Notes: both "new" parts (false comment; one-shot marks consumed by callers that send nothing) are confirmed.

## G-0700
- Outcome: DOWNGRADED; now LOW, mainnet MEDIUM (claimed HIGH). The sub-claim "nothing can clear it" is wrong.
- Independent evidence:
  - `config/binance/binance-limits-v1.toml:17,19`: `rate_limit_418_no_retry_after_wait_seconds = 259200`, cap `259200`.
  - `src/adapters/binance_ratelimit_gate.py:334-348` `_body_ban_end`: returns None when `margin is None`; `config/execution/execution-limits-v1.toml:80,121`: `ban_end_clock_margin_ms = "NOT_CONFIGURED"` (optional key, not required by `require_live_ready`), so the D083 body time is never used in the shipped config; `record()` (:350-393) then sets `end = now + 259200 s` for IP_BANNED and persists it.
  - Every signed call: `src/adapters/binance_usdm.py:883-895` `_sdk_call` runs `gate.check()` first; public calls `binance_public.py:352-357`; user-data (listenKey) `binance_userdata.py:249`. `binance_ratelimit_gate.py:41`: "There is no exemption for any request category." `src/execution/emergency_close.py:57`: "No exemption is added". RUNBOOK (line 1095) states the same for emergency closes and protective actions.
  - Official doc (USDⓈ-M General Info, read 2026-11-18): "IP bans are tracked and scale in duration for repeat offenders, from 2 minutes to 3 days"; the page does not mention a Retry-After header for Futures. So a first 418 is likely a short ban, and the no-Retry-After fallback (3 days) is the likely path -- the 3-day lock-out is very probably far longer than the real ban.
- Counter-checks / refutations:
  - Not "nothing can clear it": `src/ops/rest_gate_cli.py` `clear --path STATE_FILE --operator-id ID --reason TEXT --force` writes a fresh record with no deadline; it takes effect at the next restart through `restore()` (operator must stop the process first, `_STOP_FIRST`). RUNBOOK 1100-1101 documents it. In-process the gate cannot be cleared (`binance_ratelimit_gate.py:33,444`), which is the narrow true part.
  - The ban start alerts the operator (`REST_GATE_BAN_ENTERED until_utc=...`, :392).
  - Stops already resting on the exchange stay active; the exposure is a resting entry that fills during the lock-out (it cannot be cancelled, its stop cannot be placed, the emergency close is refused) and the user-data stream dying when keepalive is refused.
  - A 418 needs prior ignored 429s; the gate pauses all REST on a 429, making a 418 unlikely.
- Notes: real design defect (fallback ≫ documented minimum ban, no in-process recovery, body time switched off), but low probability, operator-recoverable with ssh plus restart, and alerted: MEDIUM on mainnet. It interacts with G-2100 (an entry filling while the process cannot place a stop).

## DONE
