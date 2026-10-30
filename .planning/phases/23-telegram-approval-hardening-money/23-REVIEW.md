---
phase: 23-telegram-approval-hardening-money
reviewed: 2026-10-30T00:00:00Z
depth: deep
files_reviewed: 23
files_reviewed_list:
  - scripts/gen_phase23_fixtures.py
  - src/adapters/telegram_callbacks.py
  - src/adapters/telegram_notify.py
  - src/approval/confirm_core.py
  - src/approval/reason_codes.py
  - src/approval/replay.py
  - src/db/alembic/versions/0013_approval_money.py
  - src/db/alembic/versions/0014_decided_excl_expired.py
  - src/domain/approval.py
  - src/execution/approval_desk.py
  - src/execution/confirm_flow.py
  - src/execution/confirm_recheck.py
  - src/execution/prior_outcome.py
  - src/ops/alert_wording.py
  - src/paper/notify.py
  - src/paper/rehearsal.py
  - src/paper/runtime.py
  - src/paper/runtime_config.py
  - src/paper/shadow.py
  - src/paper/shadow_confirm.py
  - src/paper/shadow_runtime.py
  - src/persistence/approvals.py
  - src/risk/money_at_stake.py
findings:
  critical: 0
  warning: 11
  info: 6
  total: 17
status: issues_found
---

# Phase 23: Code Review Report

**Reviewed:** 2026-10-30
**Depth:** deep (cross-file call chains traced: `on_callback` -> `_answer_press` -> `desk.dispatch` / `ShadowApprovalBook.dispatch` -> `dispatch_callback` -> `resolve_callback` -> `PgApprovalStore._decide`; `ConfirmFlow` -> `ConfirmBook` -> `confirm_recheck`)
**Files Reviewed:** 23
**Status:** issues_found

## Summary

The authorization design holds up. I traced every production path from the Telegram edge to a state
change. The chat gate runs first, then the user and chat-type gate (`authorized_user_gate`), and only
then any short-id, token or confirm lookup. `on_callback` and `build_application` both require a
validated non-empty frozenset of int user ids, and `on_callback` re-runs the user gate itself, so an
injected dispatcher that ignores the new keywords cannot weaken it. The only two real callers of
`dispatch_callback` (`ApprovalDesk.dispatch`, `ShadowApprovalBook.dispatch`) forward the keywords that
`_answer_press` always supplies. Confirm replay is state based (a terminal entry replays and never
reaches `on_confirmed` twice), the TTL and plan-expiry boundaries are inclusive and consistent, and the
`_in_section` lock order is sound. No float is used on any money path (`money_at_stake`, card and
request renderers, `confirm_core` all use Decimal / integer milliseconds), and `parse_money_json` is
strict. Migrations 0013 and 0014 match `models.py` (index predicate and CHECK text are identical) and
both have real downgrades; the 0014 downgrade guard query is correct.

I found no BLOCKER that I can prove from the code. The 11 warnings are fail-open defaults, places where
the safety design is weaker than its documentation claims, and operator-facing statements that can be
untrue on a money decision. The ones most worth fixing before Phase 24 composes this into a running
process are WR-01, WR-03, WR-04 and WR-08.

## Warnings

### WR-01: `dispatch_callback` skips the user gate when `authorized_user_ids` is omitted (fail-open default)

**File:** `src/adapters/telegram_callbacks.py:381` and `:438`
**Issue:** `authorized_user_ids: frozenset[int] | None = None` and `if authorized_user_ids is not None:`
make the Phase 23 user and chat-type gate opt-in. D-02 says "never allow-all", but a direct caller of
`dispatch_callback`, of `ApprovalDesk.dispatch(parsed, **kwargs)` or of `ShadowApprovalBook.dispatch`
that forgets the three keywords gets an approval decided with `actor_id=""` and no user check at all.
Today's wiring is safe only because `_answer_press` happens to pass them: `ApprovalDesk.dispatch` and
`ShadowApprovalBook.dispatch` are public methods that Phase 24 will compose, and nothing in their
signatures forces the gate. The module docstring even documents the omission as supported ("only direct
library callers omit it, which skips this step").
**Fix:** Make the gate mandatory in the pure function and let tests pass an explicit allow-list:
```python
def dispatch_callback(..., from_user_id: int | None, chat_type: str | None,
                      authorized_user_ids: frozenset[int]) -> DispatchResult:
    ...  # no `if authorized_user_ids is not None:` branch
```
If a deprecation path is needed, raise `ValueError("authorized_user_ids is required")` when it is
`None` instead of silently skipping. Do the same in the `dispatch` wrappers (they take `**kwargs`).

### WR-02: Confirm token is bound to the pressing user of the replay press, not to the stored approver

**File:** `src/execution/confirm_flow.py:274-281` (same pattern in `src/paper/shadow_confirm.py:653-660`)
**Issue:** `_approved` calls `self._book.issue(..., approving_user_id=press.from_user_id, ...)`
whenever no entry exists yet, including for a REPLAYED APPROVE (`result.already_decided is True`).
`result.approval` is the stored row and carries the real approver in `actor_id`. If the first press's
handler failed before `issue` ran (any exception after `desk.dispatch` committed, e.g. the
post-dispatch `lookup_by_token_hash` in `ApprovalDesk.dispatch`, or an error in `approved_handler`
itself), the approval is APPROVED in the store with no entry. The next APPROVE tap from any other
allow-listed user then becomes the "approving user" and is the only person who can CONFIRM. This breaks
the D041 rule "bound to the user that pressed APPROVE". Reachability is narrow (needs more than one
allow-listed user and a handler failure), but it is the exact binding the phase exists to enforce.
**Fix:** Bind to the stored actor and refuse a mismatch:
```python
stored_actor = result.approval.actor_id
if not stored_actor.isdigit() or int(stored_actor) != press.from_user_id:
    return False  # a replay by someone else never creates the confirm
entry = self._book.issue(..., approving_user_id=int(stored_actor), ...)
```

### WR-03: `_later()` launders a stale pre-fetched snapshot into a "fresh" one

**File:** `src/execution/confirm_recheck.py:80-102` (with `src/execution/confirm_flow.py:410-436`)
**Issue:** `prefetched_provider` moves `mark_checked_at_utc` and `last_checked_at_utc` forward to the
press instant `now_utc`. That is safe only if the snapshot was fetched for THIS press. The holder
(`PrefetchedConfirmInputs`) keeps an unconsumed snapshot until `take`, and `_prefetch_for` swallows a
prefetch error ("the recheck then refuses"). If an earlier CONFIRM put a snapshot and then did not reach
the recheck (the body raised in `_reconcile_unknown`, or in the journal write inside `_expire_ttl` or
`_reject_terminal`, i.e. exactly when the store is flaky), a second CONFIRM inside the same 60 s
window whose own prefetch fails (exchange down) will `take` the OLD snapshot. `_later` then restamps
its checked-at instants to now, so `evaluate_pre_placement` sees a zero-age price. The comment says
"never backwards", but it also erases the real age. The fail-closed contract "no snapshot =
CONFIRM_INPUTS_UNAVAILABLE" is defeated for up to the TTL.
**Fix:** Do not rewrite checked-at instants. Keep the fetch instant on `ConfirmInputs`
(`fetched_at_utc`), have `provide` return `None` when `now_utc - fetched_at_utc` exceeds the owner's
price-age bound, and also drop any leftover before a fetch:
```python
def provide(signal, plan, now_utc):
    snapshot = holder.take(plan.trade_plan_id)
    if snapshot is None or now_utc - snapshot.fetched_at_utc > max_snapshot_age:
        return None
    return snapshot  # original checked_at instants untouched
```
and call `holder.take(plan.trade_plan_id)` (discard) at the start of `ConfirmFlow._prefetch_for`.

### WR-04: The confirmation card shows the stored money block without re-checking it against the plan and approval

**File:** `src/execution/confirm_flow.py:221-234`, `src/adapters/telegram_notify.py:878-916` and `:1001-1019`
**Issue:** F-015 ("message and card cannot disagree") is enforced at issue time only, by
`require_money_consistent` inside `format_approval_request`. The card is built later from
`desk.money_for()`, which re-reads `approvals.money_json` and only runs `parse_money_json`.
`_live_confirm_head` checks `money.side` and nothing else, so `Quantity:`, `Notional:`, `Loss at SL` and
the entry/SL on the "Mark price" line come from the stored JSON, while the order that CONFIRM hands to
placement uses `approval.approved_quantity` and the plan. `parse_money_json` accepts any positive
decimals (no `notional == quantity * entry` or `margin == notional / leverage` cross-check, no tie to
the plan), and the money text is deliberately outside the plan hash. A corrupted, hand-edited or
buggy-written row therefore shows the operator figures that differ from what will be placed, on the
very screen meant to be the last human check. Separately, `require_money_consistent` never compares
`money.entry_price` with `[entry_min, entry_max]`, so even at issue time an entry price outside the
plan's zone passes.
**Fix:** In `ConfirmFlow._render_card` (and `_final_text`) call
`require_money_consistent(money, direction=signal.direction, approved_quantity=approval.approved_quantity, stop_loss=plan.stop_loss_price, take_profits=...)`
and refuse (raise, which already fails closed to CARD_DELIVERY_FAILED) on any difference. Extend
`require_money_consistent` with `entry_min <= money.entry_price <= entry_max`, and have
`MoneyAtStake.__post_init__` check `notional == quantity * entry_price` and
`sum(leg.leg_quantity) == quantity`.

### WR-05: Check-then-act in `PgApprovalStore._decide` for the EXPIRED path now guards what the unique index used to guard

**File:** `src/persistence/approvals.py:254-274` (with `0014_decided_excl_expired.py:47-55`)
**Issue:** Migration 0014 removes EXPIRED rows from `uq_approvals_one_decided_per_plan`, so the database
no longer stops "sibling expired while the plan is APPROVED". The replacement rule is a plain
`SELECT` (`_decided_row_of_plan`) followed by a separate `UPDATE`, under READ COMMITTED with no row
lock. An APPROVE committing between the two statements leaves APPROVED + EXPIRED rows on one plan, which
is exactly the case the docstring says "the store does" prevent (it would release the Phase 21
reservation as APPROVAL_EXPIRED). Today the only EXPIRED writer is the startup sweep, and the instance
lease makes a concurrent process unlikely, so I rate it WARNING; the plan 24 expiry policy adds more
writers.
**Fix:** Serialize on the plan inside the savepoint before the check:
```python
session.execute(
    select(ApprovalRow.approval_id)
    .where(ApprovalRow.trade_plan_id == approval.trade_plan_id)
    .with_for_update()
).all()
already = _decided_row_of_plan(session, approval.trade_plan_id)
```
and make the APPROVE/SKIP decision path take the same lock (or add a trigger / constraint that
refuses an EXPIRED row next to a decided one).

### WR-06: Orphan sweep and stranded-approval assertion are not scoped to the book's mode

**File:** `src/approval/confirm_core.py:1288-1326` and `:1329-1355`; `src/persistence/shadow_stores.py:83-88`
**Issue:** `ConfirmStores.list_approved_approvals()` returns every APPROVED approval of the database.
Before Phase 23 only the SHADOW book used it. The core is now mode independent (DEMO and LIVE profiles),
and `_sweep_orphans` / `expire_on_restart` / `assert_no_stranded_approvals` decide "no terminal event
for MY profile" from the profile-prefixed correlation id only. If DEMO/LIVE and SHADOW approvals ever
live in one database (the stores are the same `approvals` table), a DEMO book writes
`DEMO_CONFIRM_EXPIRED` (reason CARD_DELIVERY_FAILED, `swept: true`) for every SHADOW approval, and
`assert_no_stranded_approvals` raises `StrandedApprovals` for approvals that never belonged to it. The
sweep also journals a terminal event for an approval that another live process may be about to issue a
card for.
**Fix:** Scope the reader to the mode, e.g. `list_approved_approvals(self, *, mode_label: str)` filtered
on a stored mode or on the `*_APPROVAL_REQUEST_ISSUED` / alert journal row of that mode, and pass
`self._profile.mode_label` from `_sweep_orphans` and `assert_no_stranded_approvals`. Until then document
that one database must serve one mode.

### WR-07: The "single-use confirm token" is dead state, and raw tokens sit in dataclass reprs

**File:** `src/approval/confirm_core.py:275-290` and `:512-523`; `src/execution/approval_desk.py:210-226`; `src/approval/binding.py:63`
**Issue:** `ConfirmEntry.raw_token` is generated by `issue_one_time_token()` and held in memory, but
nothing compares it with anything: `CNF:`/`CXL:` carry only the short id (which is
`sha256(signal_id)[:32]`, not a secret), and `handle_confirm` finds the entry by short id. Replay
protection is the entry state, not a token. That works, but the module docstring and D041 text describe
a token capability that does not exist, and the unused secret is still kept in a plain `@dataclass`
whose generated `__repr__` prints it (as do `_Request.approve_token` / `skip_token`, which ARE live
capabilities, and `Callback.raw_token`). Any `log.error(..., entry=entry)`, assertion message or pytest
failure diff that formats these objects writes one-time tokens (and the card text) to logs, against the
"secrets never in logs" rule.
**Fix:** Either delete `raw_token` and state in the docstrings that the capability is the in-memory
entry, or really bind it (put a short token into the callback data). In both cases mark every secret
field `field(repr=False)`:
```python
raw_token: str = field(repr=False)
approve_token: str = field(repr=False)
skip_token: str = field(repr=False)
```

### WR-08: The CONFIRMED final text states "handed to the execution step" even when `on_confirmed` raised

**File:** `src/execution/confirm_flow.py:118` and `:496-510`; `src/approval/confirm_core.py:931-943`
**Issue:** `PLACEMENT_NOT_RECORDED = "Placement: handed to the execution step; no entry recorded yet"`
is emitted for every CONFIRMED entry that has no stored entry intent. When the injected `on_confirmed`
hook raises, `_in_section` re-raises after the entry is already CONFIRMED and journaled;
`on_callback` answers "internal error ... Do not tap again", the finalize hook is skipped, and later
replays and the TTL/finalize paths render the CONFIRMED final with that exact sentence. The system
cannot know the plan was handed over, so the operator is told a placement is in flight when none may
exist (or, worse, may exist if the hook failed after sending). On a money screen the text must not
assert more than is known.
**Fix:** Record the hook outcome on the entry (e.g. `entry.hand_off: Literal["OK", "FAILED"]`, set in
`_run_confirmed_hooks`) and word the line from it: "handed to the execution step" only on OK, and
"HAND-OFF FAILED, nothing was confirmed as sent; check the journal" on FAILED, together with
`reconciliation_required_text()`.

### WR-09: `ACKED` is described as "already executed"

**File:** `src/execution/prior_outcome.py:36-48`, shown to the operator by `approval_desk.py:707-714`
**Issue:** `ExecutionIntentStatus.ACKED` means the exchange acknowledged the entry order. Since Phase 19
the entry is a GTD LIMIT that may rest, partially fill or expire unfilled. The reply "The plan has
expired, but it was approved before: the entry is already executed." is false for a resting or unfilled
entry and can lead the operator to believe a position exists (or to skip the reconciliation check).
**Fix:** Label it by what is known: `PriorOutcome.ALREADY_EXECUTED -> "already placed (acknowledged by
the exchange); fill state is in the journal"`, or rename the member to `ENTRY_ACKNOWLEDGED`.

### WR-10: Missing invalidation fields are rendered as "None at None" in the approval request

**File:** `src/execution/approval_desk.py:473`
**Issue:** `invalidation=f"{rule.get('basis')} at {rule.get('level')}"` formats whatever the plan JSON
holds. A plan whose `invalidation_rule_json` lacks `basis` or `level` sends an APPROVE request with the
line "Invalidation: None at None". Everything else in `_request_text_for` is validated fail closed
(`_json_decimal`, `require_money_consistent`), and the invalidation line is one of the 12 mandatory
APRV-01 fields. A malformed rule should refuse the request, not be shown to the operator as a valid one.
**Fix:**
```python
basis, level = rule.get("basis"), rule.get("level")
if not isinstance(basis, str) or not basis or not isinstance(level, str) or not level:
    raise ValueError("invalidation_rule_json needs a text basis and level")
invalidation = f"{basis} at {level}"
```

### WR-11: TTL, plan expiry and re-check are evaluated at the press-receipt instant, not after the awaited prefetch

**File:** `src/execution/confirm_flow.py:383-392`, `src/adapters/telegram_callbacks.py:1096`
**Issue:** `callback_at_utc` is read once in `on_callback`. `ConfirmFlow._confirm` then awaits the
composition's `prefetch` (an exchange round trip) and calls `handle_confirm(now_utc=press.callback_at_utc)`.
The latency of the prefetch is therefore not charged against the 60 s TTL, the plan expiry
(`now_utc >= plan.expiry_utc`), or the remaining-validity check in `evaluate_pre_placement`, and
`on_confirmed` receives a `confirmed_at_utc` earlier than the real instant. A tap at second 59.9 with a
5 s prefetch is CONFIRMED at real second ~65 and its validity is judged as of second 59.9. The error is
bounded by the prefetch timeout, but D041 presents 60 s as a hard limit.
**Fix:** Take a fresh `now = self._clock()` after the prefetch and pass `max(press.callback_at_utc, now)`
to `handle_confirm`; keep `callback_at_utc` only for journaling the tap time.

## Info

### IN-01: A group chat id passes startup but every press is then refused

**File:** `src/paper/runtime.py:518`
**Issue:** `TELEGRAM_AUTHORIZED_CHAT_ID` is only checked to be an int. The new gate requires
`chat_type == "private"`, so a negative (group/supergroup) id starts cleanly and refuses every button
tap at run time (`CHAT_NOT_PRIVATE`). The failure shows up in the journal, not at start.
**Fix:** Refuse `chat_id <= 0` in `_shadow_from_env` with `ConfigNotRatified(["TELEGRAM_AUTHORIZED_CHAT_ID (must be a private chat id, a positive integer)"])`.

### IN-02: Two application error handlers log every escaped error twice

**File:** `src/adapters/telegram_callbacks.py:1385` and `src/paper/shadow_runtime.py:1274`
**Issue:** `build_application` registers `make_application_error_handler()` and `ShadowCoordinator.start`
adds `on_telegram_error` on the same application. Both run for each error (two log lines, and only one
of them is counted). Neither logs text, so it is not a leak, just duplicated noise and inconsistent
counting.
**Fix:** Keep one handler (have `make_application_error_handler` accept an optional counter callback).

### IN-03: `ApprovalDesk.issue` does not check that the signal and plan belong together

**File:** `src/execution/approval_desk.py:348-380`
**Issue:** The mapping, both approval rows and the journal use `signal.signal_id` and `plan.trade_plan_id`
without asserting `plan.signal_id == signal.signal_id`. A mismatched pair would be written and sent; it is
only caught at CONFIRM by `_binding_gate` (`INVALIDATED`), after the operator already approved.
**Fix:** Raise `ValueError` before any write when `plan.signal_id != signal.signal_id`.

### IN-04: `ConfirmFlow.__init__` mutates the desk it is given

**File:** `src/execution/confirm_flow.py:192`
**Issue:** `desk.confirmation_attached = True` is set as a constructor side effect. It only changes
wording ("Nothing was placed." vs "no confirmation card handler is attached"), but a flow that is built
and discarded (or a second flow on the same desk) leaves the desk claiming a handler is attached.
**Fix:** Pass the flag through an explicit `desk.attach_confirmation()` called by the composition, or
derive it from a registered flow object.

### IN-05: A refused reservation still leaves a CONFIRMED entry that later replays as "confirmed"

**File:** `src/approval/confirm_core.py:1117-1135` and `:719-720`
**Issue:** In `_finish_confirm`, when `reserve()` returns `reserved=False` the first press is reported as
`REJECTED_OTHER`, but the entry is already CONFIRMED (terminal event journaled) and `on_confirmed` was
not called. A repeat tap goes through `_replay`, which answers `CONFIRMED` / "Already confirmed". The
operator is told the plan is confirmed when its reservation was refused. Logic is carried over from
Phase 16 unchanged; the SHADOW-only `ReservationPort` makes it unreachable for DEMO/LIVE.
**Fix:** Record the refusal on the entry (`entry.outcome = REJECTED_OTHER`, `entry.reason = outcome.reason_code`)
and have `_replay` answer from `entry.outcome` for a CONFIRMED entry whose hand-off did not happen.

### IN-06: Replies to an unauthorized chat disclose the mode and that the bot is live

**File:** `src/adapters/telegram_callbacks.py:1215-1218`, `src/execution/approval_desk.py:735-745`
**Issue:** After a chat-gate failure the handler still replies to `query.message.chat_id`, and with the
desk's reply function the text is "Mode: LIVE\nRefused. Nothing changed.". The refused party learns the
mode label and that the bot processes callbacks. Impact is small (only a chat that already holds one of
the bot's messages can tap), but T-8-10 asks for "rejected and journaled", not for an answer.
**Fix:** For `GATE_REFUSED` records send no text, or send a mode-free "Rejected."; the callback has
already been answered (spinner cleared) by `answer_callback_safely`.

---

_Reviewed: 2026-10-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
