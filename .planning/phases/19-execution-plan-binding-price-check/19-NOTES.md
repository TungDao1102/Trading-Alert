# Phase 19 notes (carried from Phase 18): the D055 execution-model direction

Input for `/gsd-discuss-phase 19` and the planner. NOT a decision record and NOT a DECISIONS row.
D055 stays OPEN and LIVE stays blocked. Written 2026-10-18.

Where this came from: the Phase 18 Demo probe evidence (`.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DRAFT-D055-evidence-for-user.md`, `evidence/18-probe-check.txt`) was given to the reviewer, whose four replies the user relayed in the session. After checking them against the repository and the official pages, the user answered, in these words:

> adopt kèm các điểm trên

The user then asked for this to be NOTED for Phase 19 only, and for Phase 18 to be completed first. So no `19-DEC-*` record, no DECISIONS row, no ROADMAP change and no code or probe plan exist yet. Phase 19 discussion turns this note into a decision record (a new DECISIONS row, expected D077 or later) before any plan is written.

Labels: [DOC] official USDⓈ-M page (read through WebFetch, a small-model summary, not a verbatim copy); [DEMO] observed on Demo, not mainnet; [DESIGN] reasoning, not verified Binance behavior.

## Direction adopted (model (a): protection after the entry fill)

- [DESIGN] V1 supports one model only: STOP_MARKET `closePosition=true`, placed after the first fill with positive quantity (from the user-data stream or REST). No `quantity`, no `reduceOnly` on that leg. Model (b) (pre-placed explicit-quantity stop) stays a future research direction; the Demo showed it accepted and sized equal to the position [DEMO], but it is not built.
- [DOC] `closePosition` cannot be sent with `quantity` or `reduceOnly`; `reduceOnly` cannot be sent in Hedge Mode; `positionSide` must be sent in Hedge Mode. [DEMO] reduceOnly together with closePosition answered -1106.
- [DEMO] `closePosition` while flat answered -4509. [DOC] silent on whether an open position is required; [DEMO] has not tried `closePosition` with a position open (probe 1 below).
- A position is not protected or healthy until Binance confirms the stop (REST query); `NEW`, HTTP success and `ALGO_UPDATE FINISHED` alone are not evidence. No new entry while any position is unprotected.

## Fill, stop and entry remainder

- [DESIGN] On the first fill (stream or REST; PARTIALLY_FILLED counts) start BOTH the stop placement and the cancel of the entry remainder at once; the stop is not delayed by the cancel and the cancel does not wait for the stop. Reconcile both until the stop is confirmed and the entry is terminal at Binance.
- [DESIGN] Stop confirmed first, entry not terminal before `entry_terminal_timeout`: keep the stop, SAFE_MODE and CLOSE_REQUIRED, alert, no TP, emergency close, keep watching until the entry is terminal and the position is flat. (Accepted knowingly: this closes a position that has a good stop because a cancel was slow; mitigate by measuring a wide enough timeout, never a short one. Journal the reason.)
- [DESIGN] Entry terminal first, stop not confirmed: keep querying the stop, no TP, not protected; if not confirmed before deadline N, CLOSE_REQUIRED and emergency close.
- [DESIGN] Both fail or are ambiguous: internal state is not the truth; reconcile over REST, keep cancelling, CLOSE_REQUIRED if protection cannot be confirmed in time.
- [DESIGN] A new fill after the stop triggered: default CLOSE_REQUIRED, cancel the rest, close the new exposure by MARKET; do not re-place the stop and carry on. Keep monitoring until the entry is terminal and the position is flat.
- [DESIGN] `-2021` after a fill is a definitive rejection of the stop ([DEMO]: -2021 was observed for a wrong-side trigger); never resent blindly; it leads to CLOSE_REQUIRED.

## Emergency close (D034 already approves the principle)

- D034 (2026-09-30, user) approves closing with a reduce-only order when the SL is rejected or unconfirmed. The parameters are what is open.
- [DESIGN] MARKET order. One-way: `reduceOnly=true` and the closing side. Hedge: no `reduceOnly`, explicit `positionSide`, closing side. A deterministic client order id per attempt; an ambiguous result is queried by that id before anything is resent; never a duplicate close.
- [DESIGN] Above the symbol's MARKET_LOT_SIZE max: close in valid parts, check the position after each part, then compute the next; every part respects the live exchangeInfo filters. If no valid quantity can be built or a part fails or is ambiguous: SAFE_MODE, critical alert, keep reconciling, manual intervention. Offline test with fake filters is enough for the splitting (Demo max 120 BTC is far above the intended size); mainnet and other symbols are not verified.
- A failed emergency close never declares the position safe.
- Code gap: `ExecutionAdapter` has no close or MARKET method (`place_entry` is LIMIT only, no `reduce_only`); `emergency_manual_close` leaves the closing to the operator; `attach_protectives_to_fill` states "no rescue placement is ever issued (D-02)" although D034 supersedes D-02; `attach_protectives_to_fill` is called only from `scripts/demo_rehearsal.py`, so no fill detection drives protection in `src`.

## TP legs

- [DESIGN] No continuous TP1 resizing for late fills (this settles G2-032 for the normal flow). TP1 and TP2 are placed only after the entry is terminal and the final quantity is reconciled with the real position. TP1 quantity from the real exposure, floored to stepSize, never above the closable position; TP2 `closePosition=true` without quantity or reduceOnly. TP1 payloads differ between One-way and Hedge and are tested separately.
- [DESIGN] If a valid TP1 quantity cannot be built: the existing CR-03 branch (keep the confirmed stop, SAFE_MODE, alert, not a normal completion). No automatic flatten for that reason alone.
- After any exit: reconcile the position and sweep orphan TP/SL.
- The partial fill may leave a quantity under the minimum risk utilization or minimum notional; decide whether that is normal completion or an exception.

## Two deadlines, not yet numbers

- `max_unprotected_ms` (from the first detected fill to a confirmed stop) and `entry_terminal_timeout` are separate; the second must not stretch the first.
- [DESIGN] Add both to the Binance limits file as `NOT_CONFIGURED`; the code refuses the live path while they are unset (the repo has a test that forbids numeric defaults for the ratified keys). The user fills them after the probe results. No placeholder is a decision.

## Probes before D055 can be closed (the user runs every `--execute`)

1. `closePosition` STOP_MARKET with a position open (One-way).
2. Trigger a real stop on Demo; check the child order, the fill and REST position flat.
3. Partial fill, the remainder and the protection lifecycle. [open question: whether Demo can produce a partial fill at all]
4. Entry rejected, canceled, expired, timed out.
5. Stop rejected or timed out, and reconciliation when the user-data stream is lost or late.
6. Close the position by another mechanism while the stop is open (is the stop orphaned, does it trigger and reopen anything).
7. Fill, cancel and trigger race.
8. `-2021` after a fill.
9. Emergency MARKET close (reduce-only, One-way) and its answer.
10. TP1 quantity from the real fill.
11. Cleanup: account flat, no unexpected algo order.

Hedge Mode: not in the required set. Hedge stays unverified and must not be enabled in V1; changing the Demo account position mode is the user's action and would need its own decision.

## Phase 19 ROADMAP lines that this changes later (not edited now)

Criterion 1 and criterion 3 (stop after fill, N from the probe, Hedge, alert); the inherited item `[D055]` (placement right after the entry, near `manager.py` gate 6 and the SL intent); `[G2-032]` (TP1 resize); `[T-04]`/`[G4-006]` (TP1 split) only if the TP flow changes them. Criterion 4 and Phase 18 criterion 3 were already corrected on 2026-10-18 (commit 7e73606).

## What the reviewer got wrong along the way (kept so it is not repeated)

- The probe did NOT meet a MARKET quantity limit: the MARKET_LOT_SIZE case was off (`evidence/18-probe-check.txt` line 46: Demo market lot min 0.0001, max 120, step 0.0001, out-of-range NOT_OBSERVED).
- Auto-flatten principle needs no new approval: D034 already gives it. Only the parameters are open.

## Phase 18 code review: items skipped as owner decisions (2026-10-19)

Source: `18-user-data-stream-error-taxonomy/18-REVIEW.md` (deep, three parts; ids are `<part>/<id>`) and `18-REVIEW-FIX.md` (26 of 33 critical and warning findings fixed, 7 skipped, nothing in `config/`, `params/` or `docs/DECISIONS.md` touched). These are NOT decided; each needs the owner before it is changed. The reviewer's text is a claim; the orchestrator confirmed only src/CR-01 and the stale-code facts of src/CR-02 and src/WR-02 against the source.

- **src/WR-02, manager and taxonomy (belongs here).** `src/execution/manager.py` never reads the exchange-error taxonomy. `place_entry` is re-sent (`_ENTRY_MAX_ATTEMPTS = 2`), but only after a probe reports definitive absence, so the duplicate-order risk is lower than the review says. What is real: a refusal raised before anything is sent (rate-limit gate, `EntriesBlocked`, `SignedCallPolicyMissing`) is treated like an ambiguous send, which can give a spurious SAFE_MODE or an UNKNOWN intent. Wire the taxonomy here, together with the pre-placement checks.
- **src/WR-08, `ClientError` class rule.** Every 4xx other than 400/401/403/404/418/429 maps `CLIENT_OTHER -> STATUS_UNKNOWN` (retryable). The rule is ratified in plan 18-05 and pinned by tests; the review says only 408 should be unknown. Changing it needs a new decision.
- **src/WR-01, retry after a 429.** The supervisor waits out a pause and resends listenKey and snapshot calls (plan 18-14 does this on purpose); the 2026-10-16 amendment says no 429 retry. The two texts disagree; the owner picks one.
- **src/WR-10, rate-limit response headers.** `ApiResponse.rate_limits` is never read, so the gate is purely reactive. Reading it needs a new limits key in `binance-limits-v1.toml` (a ratified file) and a decision.
- **src/CR-02 remainder, liveness.** Fixed: `rebuild()` now proves the stored listenKey with a keepalive and starts a new key when it is invalid. Left open: (a) `max_liveness_age_seconds = "none"` is a ratified DECISION value and `stream_is_stale` is called by no production code, so a silent dead stream is detected only by the next keepalive failure (up to 30 min); (b) the SUBSCRIBE acknowledgement check was not confirmable from the SDK source. Decide whether a liveness limit is ratified and where the verdict is enforced.
