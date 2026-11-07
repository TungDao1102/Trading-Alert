# Phase 25 owner decisions (plan 25-18)

Written 2026-11-08 by the assistant (Claude Sonnet 5.5). Status of this packet: OPEN, no question is answered.
This file decides nothing. Every question below gives the facts, the options, one assistant recommendation
labelled as such, and what the answer gates. The answers are yours. Plans 25-19, 25-21 and 25-22 copy your
words verbatim into the last line of each question; no agent chooses an option, auto-selects one or writes an
Accepted `docs/DECISIONS.md` row for you.

Nothing here enables mainnet or LIVE. Live placement stays disabled (`LIVE_ORDERS_DISABLED`). Demo runs stay
owner-run (`25-OWNER-RUNBOOK.md`).

## How to read a question

Each question has: context (facts with their source), options (each with an id, pros and cons), the line
"Assistant recommendation (not a decision)", what it gates, and as its last line the answer line, which stays
`pending` until you reply. Reply with the question id and an option id (and any condition), for example
`Q-C: all-pass-except-candle`, or "follow your recommendation" for all of them, or list overrides.

Two groups. Q-AB to Q-G are the soak and campaign decisions that the plans 25-19 to 25-24 wait for. Q-H to Q-L
are the findings of the twin plans (25-08 to 25-16): three of them are strict-xfail twins that the research
order says must be closed before any Demo session, and the rest are observations you may accept.

## Informational, no decision

- OWNER-3 (P20-ERR1003, parsing the Binance -1003 ban text) is superseded: D083 (Accepted 2026-10-22) already
  carries the exception and `src/adapters/binance_ratelimit_gate.py` reads the ban end. The real -1003 body
  was never recorded (DVM-30 NOT_OBSERVED); only an accidental ban could show it. A real 418 or 429 is never
  provoked (owner decision 2026-10-22).
- `rest_gate.ban_end_clock_margin_ms` in `config/execution/execution-limits-v1.toml` stays optional and
  NOT_CONFIGURED; the margin is your number (D083 item 4). Owner-open, no plan needs it.
- R-22 (cancel-on-stop for the live process): owner-open. The interim is the `docs/operations/RUNBOOK.md` 22.5
  stop procedure. Every planned stop during the campaign and the soak follows it; an unplanned restart is a
  defect. Finding 25-13-F1 (Q-K) is a second reason that procedure is the only way out of a halted stream.
- R-23 and R-28 stay deferred (D-14): no scenario exposed them.
- Presses in the Demo suite go through the bot's own callback handler (the handler Telegram polling calls);
  set `TRADING_DEMO_OWNER=console` to tap on the real bot instead. Only S01 and the optional rehearsal re-run
  prove the Telegram transport.
- The single EC2 host also runs the Phase 16 paper soak. No step of this campaign deploys to, restarts or runs
  anything on it until you confirm that soak finished.
- Observations and twin-fidelity notes that need no decision and are answered by the Demo run (all in
  `25-DEFERRED.md`, section B, owner-open; ask to promote any to a question): 25-12-F2 (a restart that inherits
  SAFE_MODE is admitted with entries disabled; leave it with `/safemode_exit`), 25-13-F3 (a stale mark reaches
  SAFE_MODE only for symbols of active plans), 25-13-F4 (the twin's drift guard is driven by the test; the
  real server-time measurement is a Demo question), 25-14-F2 (`rest_gate_cli` has no running-process check),
  25-14-F4 (the twin does not exercise the real adapter's gate check on a placement), 25-15-F3 (a second
  request on the symbol is refused while an entry intent is unresolved; not a defect), 25-15-F4 (after the
  reconcile resolves an UNKNOWN entry the standing SAFE_MODE reason reads UNRESOLVED_EXECUTION_INTENT; the journal
  keeps ENTRY_STATE_UNKNOWN), 25-15-F5 (twin amounts are the recorded Demo account's, not mainnet figures),
  25-16-F3 (a foreign resting order is listed as source RESTING_ENTRY_ORDER; fail closed, inexact name) and
  25-16-F4 (the twin does not deliver the actor's fills to the stream; real leg statuses are a Demo question).

## Q-AB Soak shape: trade generation and symbols (D-09, research Open Questions 1 and 2, Pitfall 3)

Context. The only signal source of the live process is the owner-triggered `/demo_signal` injector
(`src/live/signal_source.py`: a strategy-driven Demo source "stays with the owner-named later phase and is NOT
built"); every entry needs your APPROVE and CONFIRM (APRV-02). `DEMO_SYMBOLS = ("BTCUSDT",)`
(`src/live/runtime.py`). A second symbol also needs R-21 (Q-F) and a wiring change. CONTEXT D-09 said the soak
runs the "live-5 universe": the code cannot do that today, so D-09 needs your revision whatever you answer. The
registration is hash-locked before the first soak order (plan 25-24), so changing the shape later restarts the
soak clock.

Options.

- `btc-owner-trips`: a process soak on BTCUSDT (uptime, reconcile clean every tick, health, stream cycles and
  the 24 h connection cut-offs, alerts) plus N owner round trips per week through `/demo_signal`, N chosen by
  you.
  - Pros: runs on today's code; proves the whole trade path N times a week and the process continuously.
  - Cons: the trade count depends on your time; one symbol only.
- `live5-owner-trips`: the live-5 symbols plus owner round trips.
  - Pros: exercises the multi-symbol margin and cluster rules.
  - Cons: needs R-21 (Q-F) and a `DEMO_SYMBOLS` wiring change first: new scope, and the soak waits.
- `strategy-source`: a strategy-driven Demo signal source.
  - Pros: continuous, owner-independent trade flow.
  - Cons: new strategy-path work outside Phase 25 ("no new strategy work"); the soak moves to a later phase.

Assistant recommendation (not a decision): `btc-owner-trips`, with N set by you in your answer. It is the only
shape the current code supports and it keeps R-21 off the critical path.

Gates: plan 25-24 (the registration: duration, symbols, round trips per week, pass criteria) and plan 25-25
(the soak). An answer that needs new scope blocks plan 25-24 until you approve a new plan or phase.

Owner answer: pending

## Q-C Healthy reading for D056 2(d) (research Open Question 3)

Context. The live process has no candle feed, so the check `last_closed_candle_time` is DEGRADED by construction
with the fixed detail "not applicable: the live process has no candle feed" (`src/live/health.py`), and DEMO
enables under `demo_degraded_allowed` (`src/live/wiring.py`). So every live-process Demo verdict is DEGRADED.
D056 says DEGRADED Demo runs are never evidence of live readiness and that scenarios and the soak must also run
healthy. Each scenario records the verdict facts without judging them (plan 25-08). Finding 25-13-F2 bears on
this: the verdict is observational at runtime.

Options.

- `all-pass-except-candle`: healthy means every check PASS except `last_closed_candle_time`, named as the one
  not-applicable check and journaled as such.
  - Pros: matches the code; no change; the exception is named.
  - Cons: an interpretation of D056 that you must accept explicitly.
- `strict-all-pass`: healthy means every check PASS.
  - Pros: the literal D056 reading.
  - Cons: needs a candle feed in the live process: new scope; campaign evidence and the soak wait.
- `other`: your own wording.
  - Pros: exactly your rule.
  - Cons: may need evaluator configuration beyond `healthy.allowed_degraded_checks`.

Assistant recommendation (not a decision): `all-pass-except-candle`, written into the soak registration as
`allowed_degraded_checks = [last_closed_candle_time]`. It is a reading, not a code change; you may overrule it.

Gates: plan 25-24 (the registration and the healthy judgement applied to the campaign evidence).

Owner answer: pending

## Q-D Account: campaign and soak on one Demo account (Pitfall 6, assumption A7)

Context. The user-data listenKey is an account-level singleton: a scenario run while the soak process is up
steals or closes the soak's stream, and any defect restarts the soak clock. Research assumption A7: a second
Demo key on the same Binance login may share the same singleton, so a second key might not allow overlap and a
real second login could be needed (not verified).

Options.

- `sequence-same-account`: campaign sessions first, then fixes, then the soak, all on one Demo account; they
  never overlap.
  - Pros: no second account; matches the research sequencing.
  - Cons: the soak cannot start until the campaign and its fixes are done; a defect found during the soak stops
    both.
- `second-key`: provision a second Demo key (or login) so scenarios can run next to the soak.
  - Pros: overlap possible if the second key really has its own stream.
  - Cons: A7 may be false for a key on the same login; more secrets to look after (never in the repo or in
    chat); a defect still restarts the soak clock.

Assistant recommendation (not a decision): `sequence-same-account`.

Gates: plan 25-22 records it; plans 25-24 and 25-25 schedule the soak after it.

Owner answer: pending

## Q-E Soak host and restart policy (Open Question 7, Pitfall 10)

Context. The 24-33 host steps (VPS bootstrap, keys, env files, heartbeat) are all NOT_OBSERVED in
`24-OWNER-RUNBOOK.md`; this phase does not close them. The `live` compose service ships with `restart: "no"`
(24-OWNER-RUNBOOK G2). The single EC2 host also runs the Phase 16 paper soak, so a live Demo soak there only
starts after you confirm that soak finished (or on a second host). R-22 is open, so every planned stop follows
RUNBOOK 22.5; the restart rule of the registration says any defect restarts the clock after the fix.
`deploy/update.sh` refuses while the live service runs.

Options.

- `vps-unless-stopped`: run the soak on the VPS as the `live` service, switch `restart: "no"` to
  `unless-stopped` only after one clean run, every planned stop per RUNBOOK 22.5, an unplanned restart is a soak
  defect.
  - Pros: survives a daemon or host restart; the refusal path still holds (`--hold-on-refusal`) instead of
    looping.
  - Cons: a restart can happen unseen with a resting entry (R-22); an unplanned restart resets the 21 day
    clock.
- `vps-restart-no`: run on the VPS with `restart: "no"` for the whole soak.
  - Pros: every restart is a visible human action; nothing restarts by itself.
  - Cons: a host reboot ends the soak until you start it again; that is a defect and a clock reset.
- `dev-pc`: run on the dev PC.
  - Pros: no host work.
  - Cons: not credible for 21 days (sleep, updates, network); listed only for completeness.

Assistant recommendation (not a decision): `vps-unless-stopped` after a clean run, with the planned-stop
procedure and the unplanned-restart-is-a-defect rule, on the host only after the Phase 16 soak finished.

Gates: plan 25-22 records it; plan 25-24 writes the "Soak (owner)" section of the runbook; the soak start in
plan 25-25 needs the 24-33 steps B to E.

Owner answer: pending

## Q-F R-21: when margin reservations advance (CONTEXT OWNER-1, WR-03)

Context. `mark_placed` and `mark_open` of `src/persistence/risk_reservations.py` have no production caller that
advances an executed plan, so an executed plan's reservation stays RESERVED and is counted for every other plan
(`24-DEFERRED.md` R-21). `21-DEFERRED` says to stamp before the POST; the store docstring and 22-REVIEW WR-06
say after the acknowledgement. A DECISIONS row is needed before any code (plan 25-21 writes it from your
answer; plan 25-23 implements it). While live tracks one symbol the effect is hidden over-refusal; any second
symbol needs it. Not on the BTCUSDT soak's critical path.

Options.

- `ack-then-first-fill`: stamp `mark_placed` at the exchange acknowledgement and `mark_open` at the coordinator's
  first fill, through `StoreExecutor.write` (the recommendation agreed with you on 2026-11-07).
  - Pros: a reservation never claims an order the exchange did not accept; follows D080 (never re-send).
  - Cons: a crash between the POST and the acknowledgement leaves the reservation RESERVED until recovery.
- `write-ahead`: stamp `mark_placed` before the POST.
  - Pros: the stamp always exists when an order might exist.
  - Cons: a refused or failed POST needs an undo; conflicts with the store's after-acknowledgement wording.
- `defer`: no change in Phase 25.
  - Pros: no code on the soak path.
  - Cons: blocks any second symbol; finding 25-14-F1 (a) shows a related stuck reservation.

Assistant recommendation (not a decision): `ack-then-first-fill`.

Gates: plan 25-21 (the DECISIONS row and DOC_STATUS line, unless deferred), plan 25-23 (implementation), any
second symbol (Q-AB `live5-owner-trips`).

Owner answer: pending

## Q-G Dates (OWNER-4)

Context. No plan sets a date. You give the session dates for the campaign (plan 25-20) and the soak start date
(plan 25-25). Sessions and the soak cannot share one Demo account (Q-D). A session needs P1 to P9 of the
runbook; S12 is the last step of its UTC day.

Options. None: this is information only. Reply with the date or date range of each session and the planned soak
start, or "later".

Assistant recommendation (not a decision): give session dates only after the runbook precondition P6 holds (no
strict-xfail twin open: Q-H, Q-I and Q-J answered and closed or waived) and after you confirmed the Phase 16
soak finished for any session that uses the EC2 host.

Gates: plans 25-20 and 25-25 (their owner checkpoints).

Owner answer: pending

## Q-H Finding 25-12-F1: SAFE_MODE CLOSE_REQUIRED cannot be left after a late restart (strict-xfail twin)

Context. After a restart later than `max_unprotected_ms` and the deadline close, the plan's STOP_LOSS intent
stays UNKNOWN and `/safemode_exit` refuses (UNKNOWN_INTENT_PRESENT, COMPARE_NOT_CLEAN), so SAFE_MODE
CLOSE_REQUIRED cannot be left through the operator path without handling the intent row by hand. Source:
`25-12-SUMMARY.md` (Findings F1); the strict xfail is `tests/test_demo_twin_s07_restart_cuts.py`
`test_cut_b_a_late_restart_close_lets_the_operator_leave_safe_mode`. It bears on S07 cut b on Demo.

Options.

- `resolve-stop-intent`: `src` resolves the STOP_LOSS intent of a FLAT plan.
  - Pros: one place; the exit gate keeps its full checks (fail closed).
  - Cons: a behaviour change in `src/execution` or `src/reconcile`; needs its own DECISIONS row and a gap plan
    before the campaign.
- `exit-tolerates`: the operator exit tolerates an UNKNOWN intent of a flat plan.
  - Pros: smaller code change.
  - Cons: loosens a safety gate; harder to reason about.
- `accept-and-document`: keep the behaviour; document the manual handling in RUNBOOK 21.1a; convert the xfail
  into an observation test.
  - Pros: no `src` change before the soak.
  - Cons: a late restart in the soak needs hand work on a database row.

Assistant recommendation (not a decision): `resolve-stop-intent`, as a gap plan before the campaign, because
the exit gate is the last operator safeguard and should not be loosened.

Gates: the gap-closure plan; P6 (no strict-xfail twin) for session steps S07 cut b.

Owner answer: pending

## Q-I Finding 25-14-F1: coordinator transition rows are not spilled while the journal is down (strict-xfail twin)

Context. The coordinator's PROTECTION_TRANSITION rows are not spilled while the journal is down and nothing
journals them again (RUNBOOK 21.2 states the limit, not its consequences). (a) The closed position's reservation
stays RESERVED, so after the database is back and the operator has left SAFE_MODE the next request is refused
CLUSTER_CAP_REJECT. (b) A restart rebuilds the plan as live, the reconcile enters SAFE_MODE and the process is
admitted but not enabled. The close itself is unaffected. Source: `25-14-SUMMARY.md` (Findings F1); the strict
xfail is `tests/test_demo_twin_s11_db_outage.py`
`test_after_the_database_returns_and_the_exit_a_new_request_is_placed`. Related to R-21 (Q-F). It bears on S11
on Demo.

Options.

- `spill-coordinator-rows`: spill the coordinator's rows like the other audit rows and replay them.
  - Pros: fixes (a) and (b) at the cause (the journal is the record both read).
  - Cons: touches the act-then-record path; needs a DECISIONS row and tests.
- `sweep-reads-coordinator`: let the reservation sweep read the coordinator state.
  - Pros: fixes (a) without touching the spill.
  - Cons: leaves (b); a second source of truth.
- `accept-and-document`: keep it, document the consequences next to RUNBOOK 21.2.
  - Pros: no `src` change.
  - Cons: after a DB outage the owner must wait or clear by hand; a restart enters SAFE_MODE.

Assistant recommendation (not a decision): `spill-coordinator-rows`, as a gap plan before the campaign.

Gates: the gap-closure plan; P6 for session step S11.

Owner answer: pending

## Q-J Finding 25-15-F1: `enforce_daily_state` is not wired into the live process (strict-xfail twin)

Context. `enforce_daily_state` (`src/execution/daily_stop.py`) is called by no live composition (only by a
test; checked by search of `src`). After the day is latched DAILY_STOP the persisted latch and the
DAILY_STOP_BLOCK refusal of new entries work, but an already resting entry stays on the exchange and no
DAILY_STOP alert is journaled (D033 says to cancel it, keep the stops and alert). Source: `25-15-SUMMARY.md`
(Findings F1); the strict xfail is `tests/test_demo_twin_s12_daily_stop.py`
`test_a_resting_entry_is_cancelled_at_daily_stop_and_the_alert_is_journaled`. It bears on S12 on Demo.

Options.

- `wire-daily-stop`: wire a scheduler or day-risk task that calls it with the placed plans from the reservation
  rows.
  - Pros: D033 behaviour in the live process.
  - Cons: new composition code with a DECISIONS row; it reads reservation rows, which is coupled to R-21 (Q-F),
    so it should follow that answer.
- `accept-and-document`: keep the gate at CONFIRM only; a resting entry ends by its own expiry; document it.
  - Pros: no `src` change.
  - Cons: a resting entry can fill after DAILY_STOP.
- `defer-to-phase-26`: leave it and list it as a canary precondition.
  - Pros: the soak is not delayed.
  - Cons: the behaviour stays unproven on Demo.

Assistant recommendation (not a decision): `wire-daily-stop` as a gap plan after Q-F is answered (it reads the
reservation rows), before the campaign step S12.

Gates: the gap-closure plan; P6 for session step S12.

Owner answer: pending

## Q-K Finding 25-13-F1: nothing requests a user-data stream resync

Context. Nothing in `src` calls `UserDataSupervisor.request_resync()` (checked by search). After a recovery halts
(reconnect exhausted, a ban, a hard listenKey failure) the stream stays UNKNOWN, SAFE_MODE
USER_DATA_STREAM_HALTED cannot be left (exit row 7, STREAM_NOT_LIVE) and the stream never recovers on its own;
only a process restart (RUNBOOK 22.5) is the way out. The soak will cycle the 24 h connection cut-off about 21
times, so expect it on a real outage. Source: `25-13-SUMMARY.md` (Findings F1); the S08 twin
`test_a_halted_stream_stays_down_until_a_resync_is_asked_for` pins the observed behaviour (not an xfail).

Options.

- `operator-resync`: a human-triggered resync request (an operator command or the reconcile loop on an
  operator action), never automatic after a ban.
  - Pros: recovery without a restart; a human decides after a ban.
  - Cons: new operator surface; needs a DECISIONS row.
- `loop-resync`: the reconcile loop requests a bounded resync on non-ban halts.
  - Pros: self-healing during the soak.
  - Cons: automatic retry near a rate-limit ban needs careful bounds.
- `accept-and-document`: restart per RUNBOOK 22.5 is the recovery.
  - Pros: no `src` change.
  - Cons: with R-22 open, a restart is a soak defect and a clock reset.

Assistant recommendation (not a decision): `operator-resync`.

Gates: the gap plan if any; S08 expectations; the soak restart rule.

Owner answer: pending

## Q-L Observations to confirm as intended or to change

Context. Each is code-defined behaviour recorded by a twin plan (`25-DEFERRED.md`, section B). Reply per item:
accept, or change (a gap plan and a DECISIONS row follow).

- 25-11-F1: `/close SYMBOL` then `/confirm` on a plan in CLOSE_REQUIRED or CLOSE_FAILED ends
  CLOSE_ALREADY_REQUIRED while the position is open and the closes keep failing, so the owner is asked to
  confirm something that cannot act. Options: keep; make `/close` an out-of-cadence retry; reword the reply.
  During CLOSE_FAILED the human action that works is a manual close on the exchange.
- 25-13-F2: the health verdict is observational at runtime (D056 item 1 and the D102 sentence that a DEGRADED
  verdict blocks new entries are carried by the verdict itself; its consumers are the start sequence and
  `enable_demo`). Entries in a degraded state are refused by other mechanisms. Options: accept; check or reword
  D102 before Phase 26.
- 25-14-F3: a 418 does not put the running process in SAFE_MODE; entries are refused because the equity refresh
  fails (UNCERTAIN_ACCOUNT_STATE); a restart under a persisted ban is admitted but enters SAFE_MODE and restores
  the same deadline. Options: accept as intended; change.
- 25-15-F2: with the day latched a new request still gets a card and its APPROVE succeeds; only the CONFIRM is
  refused (D033 puts the gate at placement). Options: accept; refuse earlier.
- 25-16-F1: after a plan's position is closed a new request on the symbol is refused (CONFLICT_WITH_OPEN_POSITION,
  source PENDING_OR_APPROVED_APPROVAL) until the closed plan's approval expires (about 26 minutes for a smoke
  plan) or `scripts/demo_clear.py` moves it to EXPIRED; the reason name says "open position" for a flat account.
  Options: accept; reword the reason; expire the approval when the plan closes.
- 25-16-F2: DOUBLED_POSITION makes the system alert and enter SAFE_MODE but act on nothing; the stop keeps
  covering the whole doubled position (closing a position the system did not open is the human's action).
  Options: accept as designed; change.

Assistant recommendation (not a decision): accept 25-13-F2 with a docs check of the D102 wording before Phase
26, 25-14-F3, 25-15-F2 and 25-16-F2 as designed; reword the reply of 25-11-F1 (the smallest change, no new
order path); reword the reason name of 25-16-F1 (a text change only).

Gates: gap plans if you choose change; none block the campaign unless you say so.

Owner answer: pending
