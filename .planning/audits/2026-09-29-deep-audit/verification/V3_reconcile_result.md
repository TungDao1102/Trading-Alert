# Verification V3_reconcile
| ID | Outcome | Final severity | Duplicate of | One-line reason |
|---|---|---|---|---|
| F-401 | CONFIRMED | HIGH | - | Probe: resting ENTRY + its entry-time SL + zero position gives ORPHAN_PROTECTIVE for the SL. The sweeper's only guard is two zero-position reads, which a resting entry always passes. Nothing re-places the SL after the entry fills. |
| F-701 | CONFIRMED | HIGH | - | Probe: a doubled position, a sign-flipped position, foreign normal/algo orders, and a TP-only protected position each return agreement=True. This clean compare is the only SAFE_MODE exit gate. |
| F-952 | DOWNGRADED | MEDIUM | - | The facts are accurate: the reconciler is cancel-only by design, WR-07 was skipped, and no phase 10-17 picks it up. But the required behaviours in the claim ("Rule 14/24", automatic rescue, reduce-only close on SL reject) are not in snapshot docs. The unprotected window is bounded by the operator. |
| F-009 | DOWNGRADED | MEDIUM | - | The contradiction between SECURITY_AND_OPERATIONS §7 and RUNBOOK §3 is real. But the code already reads SAFE_MODE as entry-only: `guard_new_entries` is called only on the entry path, and the attach path is unguarded. RUNBOOK §3 and §9 exempt protection explicitly. |

## F-401
- Outcome / final severity: CONFIRMED / HIGH. The code is not wired into the live runtime yet (see Notes), so the defect is latent. It would activate as soon as the reconciler tick is composed.
- Independent evidence:
  - `src/execution/manager.py:535-560`: `execute_approved_plan` places the entry LIMIT GTC. It then places an entry-time SL straight away ("the pre-fill safety net"), with `close_position: True` and the deterministic id `derive_algo_client_id(plan_hash, STOP_LOSS)`.
  - `src/reconcile/compare.py:301-342` (Pass 1): `has_position` looks only at local position keys and exchange positions. A protective with `not has_position` that is present on the exchange is emitted as `ORPHAN_PROTECTIVE`. `local_normal_by_client_id` (the resting ENTRY) is never consulted in Pass 1.
  - `.planning/STATE.md:190` (08-04 D-02) states the rule on purpose: "ORPHAN_PROTECTIVE classification: local algo protective ... with no matching local position AND no exchange position — regardless of whether the algo still matches the exchange truth". This contradicts `08-CONTEXT.md:24` D-03: "An orphan (protective **without a live entry**, ...)".
  - `src/reconcile/sweeper.py:190-199`: the only guard before the cancel is two consecutive zero position reads. A resting, unfilled entry always has zero position, so the cancel proceeds (`sweeper.py:262`).
  - Probe (`tmp/verify_V3_reconcile/probe.py`) with local ENTRY xe-1 (NEW), local SL xa-sl, both present on the exchange, and no positions: `agreement=False, ['ORPHAN_PROTECTIVE'], orphan_protectives=(xa-sl STOP_LOSS)`.
  - After the fill, `_place_protective_leg` (`manager.py:741-750`) probes by the same deterministic id. If the probe finds the leg with a non-NEW status (CANCELED), it returns unconfirmed and never re-places the leg: "an existing NON-active leg ... is never re-placed (no rescue placement, D-02)". Result: the position is live with no stop, SAFE_MODE is entered, and there is no automatic remedy.
- Counter-checks:
  - Searched compare.py for any consultation of a pending entry in the orphan path: there is none.
  - The sweeper has no plan or entry check.
  - `attach_protectives_to_fill` does not re-place a canceled SL.
  - One partial mitigation exists: the cancel of the protective when the entry is merely resting also produces a divergence, so SAFE_MODE blocks new entries whenever any entry is resting (a secondary effect, not a mitigation of the missing stop).
- Notes:
  - Runtime wiring: `compare` and `OrphanSweeper.sweep` are called only from `src/ops/drills.py:805-827`, `SafeModeController.exit_safe_mode` (`safe_mode.py:291`) and tests.
  - `SafeModeController(` is not instantiated anywhere in `src/` or `scripts/`.
  - Severity is kept at HIGH because this is the designed reconciler for live operation, and the failure mode is an unprotected fill.

## F-701
- Outcome / final severity: CONFIRMED / HIGH.
- Independent evidence (compare.py):
  - Truth normal and algo orders are only indexed (228-233) and looked up from the local side (314, 344, 413, 419). No pass iterates the truth orders to find exchange-only orders.
  - Pass 3 (453-470) keys positions by `(symbol, position_side)` only. `position_amt` is never compared between local and exchange. In one-way mode `position_side` is "BOTH", so a sign flip is invisible.
  - Pass 1b (383-392) accepts any protective role (SL, TP1 or TP2) from the local algo intents. It does not require a STOP_LOSS, and it does not require that the order is present on the exchange.
- Probe output:
  - Doubled position (local 1, exchange 2, SL present): `agreement=True`.
  - Sign-flipped position (local 1, exchange -1): `agreement=True`.
  - Foreign normal order and foreign algo order, with no local intent: `agreement=True`.
  - Position protected only by TP1 (local and exchange): `agreement=True`.
- Consequence: `SafeModeController.exit_safe_mode` (`safe_mode.py:291-310`) exits SAFE_MODE on `diff.agreement` alone. Each of these states therefore clears SAFE_MODE, which contradicts SECURITY_AND_OPERATIONS §5 ("position exists without expected protective stop", "unknown order event" are high-priority alerts).
- Counter-checks: I looked for other validators of amounts, unknown orders or SL presence in `src/reconcile/*` and found none. `exit_safe_mode` also defaults local intent to `[]` when none is supplied (`safe_mode.py:292-294`).
- Notes:
  - A local SL row that is missing on the exchange IS caught as UNSYNCED_ALGO (Pass 1, 344-358). The TP-only gap therefore needs the local intent to lack the SL as well, for example after the SL triggered or was canceled and its row was closed.
  - Same wiring caveat as F-401.
  - Not a duplicate of F-401: that is a different code path and the opposite failure (a false positive there, false negatives here).

## F-952
- Outcome / final severity: DOWNGRADED / MEDIUM.
- Independent evidence:
  - The cancel-only design is explicit: `08-CONTEXT.md:24` D-03 says "the reconciler never places orders", and `09-CONTEXT.md:19` D-02 says "sweeper never places rescue protection". It is also in `STATE.md:209-210` and `manager.py:590-593`.
  - `09-REVIEW.md:282-286` (WR-07) says `expire_pending_entry` leaves the close-all SL live, and that `emergency_manual_close` cancels SL/TP before the operator closes the position.
  - `09-REVIEW-FIX.md:268-276` and `09-REVIEW-DISPOSITION.md:70-73,147` record WR-07 as "skipped" because it "needs a design decision".
  - The current code still has both defects:
    - `expire_pending_entry` (`manager.py:1046+`) cancels only the `x-` entry.
    - `emergency_manual_close` (`manager.py:1230+`, steps 3-4) cancels the protectives. The operator closes the position via the exchange UI.
  - ROADMAP phases 11-17 cover fees, equity, leverage, margin, price check, notifications and quote asset. None of them covers WR-07. A grep of phases 10-17 for WR-07/expire/emergency found nothing relevant.
- Why downgraded:
  - "Rule 14" and "Rule 24" do not exist anywhere in snapshot `docs/` or `.planning/`.
  - EXECUTION_SPEC §6 requires only "ALERT HIGH PRIORITY → do not assume position is protected", which the code does (SAFE_MODE plus ENTRY_WITHOUT_PROTECTIVE).
  - RUNBOOK §3 says "submit protection only after risk validation → otherwise require explicit manual intervention". That is permissive, not a mandate for automatic re-placement.
  - The expiry-orphan half would be swept by the (unwired) reconciler, since the SL has no position.
  - The emergency-close half is a real unprotected window, but the operator starts it and closes the position manually, so the window is operator-bounded, not unbounded by the system.
  - Nothing is wired into live runtime yet: 09-04 is blocked, and 09-REVIEW-FIX.md:32 says "nothing in `src/` calls these functions yet".
- Notes:
  - Real residual risks:
    - The emergency-close ordering.
    - No owner or phase for WR-07.
    - The no-rescue policy combines with F-401 to make an unprotected fill unrecoverable without manual action.
  - Related to F-401 and F-009, but a different root cause, so not a duplicate.

## F-009
- Outcome / final severity: DOWNGRADED / MEDIUM.
- Independent evidence:
  - `docs/operations/SECURITY_AND_OPERATIONS.md:76-82`: "When SAFE_MODE is active: - no new live order placement; - existing exchange-side protective orders remain active; ...". It has no exemption for protective or reduce-only orders.
  - `docs/operations/RUNBOOK.md` §3 (lines ~36-42): "SAFE_MODE → ... → if stop is absent, submit protection only after risk validation". RUNBOOK §2 says "Block new live orders", and §9 says "preserve existing exchange-side protection".
  - The docs contradict each other when read literally.
- Why downgraded:
  - The implementation already uses the narrow reading. `SafeModeController.guard_new_entries` is the only SAFE_MODE check in the execution layer (`manager.py:407`, the entry path). `attach_protectives_to_fill` and the cancel paths have no SAFE_MODE gate.
  - The more specific operational document (RUNBOOK §3) explicitly authorizes submitting protection.
  - `REQUIREMENTS.md` OPS-01 and ROADMAP line 260 phrase SAFE_MODE as "blocks new entries".
  - The practical harm is therefore spec ambiguity that could mislead a future implementer. No current behavior blocks a stop.
- Notes: this is a documentation fix, for example "no new exposure-increasing orders; protective/reduce-only orders permitted".
