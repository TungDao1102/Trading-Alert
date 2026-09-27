---
phase: 08-approval-reconciliation-hardening
reviewed: 2026-09-27T12:00:00Z
depth: deep
files_reviewed: 24
files_reviewed_list:
  - src/adapters/binance_usdm.py
  - src/adapters/telegram_callbacks.py
  - src/adapters/telegram_notify.py
  - src/approval/__init__.py
  - src/approval/binding.py
  - src/approval/mapping.py
  - src/approval/replay.py
  - src/approval/tokens.py
  - src/db/alembic/versions/0003_callback_mapping.py
  - src/db/mappers.py
  - src/db/models.py
  - src/execution/__init__.py
  - src/execution/order_ids.py
  - src/ops/__init__.py
  - src/ops/drills.py
  - src/reconcile/__init__.py
  - src/reconcile/compare.py
  - src/reconcile/safe_mode.py
  - src/reconcile/sweeper.py
  - tests/test_approval_message.py
  - tests/test_approval_replay.py
  - tests/test_drills.py
  - tests/test_order_ids.py
  - tests/test_reconcile.py
findings:
  critical: 3
  warning: 31
  info: 16
  total: 50
status: issues_found
---

# Phase 08: Code Review Report

**Reviewed:** 2026-09-27T12:00:00Z
**Depth:** deep
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Deep review of the Phase 8 approval + reconciliation slice (approval core,
Telegram callback receiver, deterministic order IDs, short-id mapping,
three-source compare, cancel-only sweeper, SAFE_MODE, drill harness, and
their tests), cross-referenced against `src/domain/enums.py`,
`src/domain/approval.py`, and `src/domain/journal.py`.

Three blockers must be fixed before this code gates real orders:

1. **The SKIP button cannot produce a SKIP.** `dispatch_callback` discards
   `parsed.kind` for APR/SKP paths and `resolve_callback` derives the result
   from the *stored* `approval.action`, so the pressed button never influences
   the outcome. Pressing SKIP on an APPROVE-action plan approves it.
2. **`guard_new_entries` crashes on the PASS path.** It returns
   `reason_code="OK"`, but `SafeModeVerdict.__post_init__` only accepts
   `RejectionReason` values — and `RejectionReason` has no `OK`. Every guard
   call outside SAFE_MODE raises `ValueError`. No test covers the PASS path.
3. **A naked position is invisible to the reconciler.** `compare` has no
   local-position-without-protective rule: once the ENTRY order fills (and
   leaves local intent, as required), a position with zero protective algos
   yields `agreement=True`. The most dangerous state — position without stop —
   reads as clean. The unprotected drill masks this by keeping a synthetic
   `NEW` ENTRY in intent.

Below those, 31 warnings (threat-model ordering violations, audit gaps,
unhandled crash paths on normal operator flows, sweeper contract violations,
vacuous tests) and 16 info items. No source files were modified.

## Critical Issues

### CR-01: Pressed button (APPROVE vs SKIP) never determines the outcome

**File:** `src/adapters/telegram_callbacks.py:306-379` + `src/approval/replay.py:156-163` + `src/approval/binding.py:44-63`
**Issue:** `dispatch_callback` early-returns only for `SIMULATE_RECORDED`
(line 308). For `APPROVE` and `SKIP` kinds it builds an identical `Callback`
(lines 329-337) — `Callback` has no kind/action field — and `resolve_callback`
derives the result from the *stored* row via `action_to_result(approval.action)`
(replay.py:157). The resolver call in `on_callback` (line 510) passes only
`parsed.short_id`, discarding the `APR:`/`SKP:` prefix too. Net effect: both
buttons confirm whatever `action` was stored at alert time. If the stored action
is `APPROVE` (the normal case), pressing SKIP approves the plan. No test presses
SKP against an APPROVE-action approval (tests 8g/8h only use APPROVE/approve).
**Fix:**
```python
# binding.py — carry the human's decision in the callback payload
@dataclass(frozen=True)
class Callback:
    raw_token: str
    chat_id: int
    action: ApprovalAction  # APPROVE vs SKIP_*, from the pressed button
    ...

# replay.py — map the callback's action, not the stored row's action
new_result = action_to_result(callback.action)
# and reject a stored-action/callback-action mismatch explicitly
if callback.action != approval.action:
    raise ApprovalRejected(reason_code=RejectionReason.INVALIDATED,
                           message="callback action != approval action")
```
Alternatively, mint one token per (plan, button) and store two approvals — but
the current single-token wiring must then be replaced, not patched. Either way,
add a test: SKP callback against an APPROVE-action PENDING approval must yield
`SKIPPED`, and vice versa.

### CR-02: `guard_new_entries` raises on the non-SAFE_MODE path (`"OK"` is not a `RejectionReason`)

**File:** `src/reconcile/safe_mode.py:206-231`
**Issue:** `SafeModeVerdict.__post_init__` (lines 100-109) requires
`reason_code in {r.value for r in RejectionReason}`. `RejectionReason`
(`src/domain/enums.py:122-156`) has no `OK` member, so the PASS verdict at
lines 228-231 (`is_no_trade=False, reason_code="OK"`) raises `ValueError` on
every call made while *not* in SAFE_MODE — i.e. the entire normal-operation
path. All callers in tests/drills enter SAFE_MODE first, so the PASS path is
never exercised and the bug is hidden. In production this breaks the
`evaluate_risk` composition the module docstring promises (exception instead of
verdict).
**Fix:**
```python
# Option A (preferred): introduce a first-class PASS verdict that cannot be
# confused with a rejection reason.
@dataclass(frozen=True)
class SafeModeVerdict:
    is_no_trade: bool
    reason_code: str | None  # None == PASS; RECONCILIATION_REQUIRED == block
# guard:
return SafeModeVerdict(is_no_trade=False, reason_code=None)
```
Update all `guard_new_entries` call sites and add a test that calls the guard
while *not* in SAFE_MODE and asserts a non-blocking verdict.

### CR-03: Post-fill unprotected position yields `agreement=True` (no local-position-without-protective rule)

**File:** `src/reconcile/compare.py:194-406`
**Issue:** The three passes cover (1) local algos, (2) local normal orders,
(3) exchange positions with no local match. Nothing covers a *local* position
with no protective algo. After an ENTRY fills, the ENTRY row must leave local
intent (`_LOCAL_OPEN_STATUSES` excludes `FILLED`, lines 184-191, and the
docstring forbids FILLED rows), so a position whose SL/TP algos are all gone
iterates zero times in Pass 1, zero times in Pass 2, and matches in Pass 3
(key match → no divergence). Result: `agreement=True` on a naked position —
the exact state RUNBOOK §3 exists to catch. The unprotected drill
(`src/ops/drills.py:422-478`) masks this by keeping a synthetic `NEW` ENTRY in
intent, which the real post-fill system never has.
**Fix:** Add Pass 1b — for each local position intent with non-zero amount,
require at least one open protective (local algo intent in an open status) for
the same symbol (and same position_side — see WR-11):
```python
for pos in local_open_positions:
    if _is_zero_like(_get_field(pos, "position_amt")):
        continue
    symbol = _get_field(pos, "symbol")
    has_protective = any(
        _get_field(a, "symbol") == symbol
        and _is_protective_role(_get_field(a, "order_role"))
        for a in local_algo_by_client_id.values()
    )
    if not has_protective:
        divergences.append(Divergence(
            kind=DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE, ...))
```
Add a regression test with local intent = position only (no orders, no algos)
and matching exchange truth, asserting a protective-missing divergence.

## Warnings

### WR-01: `on_callback` performs state lookup before the chat gate (T-8-10 ordering violation)

**File:** `src/adapters/telegram_callbacks.py:506-523`
**Issue:** The module's own threat model (lines 10-11) and `dispatch_callback`
(line 279) require the authorized-chat gate *before any state lookup*, but
`on_callback` calls `binding_context_resolver(parsed.short_id)` (line 510 — a
DB read by short id) *before* invoking `dispatch`, where the gate runs. An
unauthorized chat triggers a DB lookup, creating a timing/error oracle (known
vs unknown short_id behave differently pre-gate).
**Fix:** Run `authorized_chat_gate` in `on_callback` before the resolver; on
mismatch, journal the reject receipt and return without resolving:
```python
if not authorized_chat_gate(callback_chat_id=callback_chat_id,
                             authorized_chat_id=authorized_chat_id):
    # journal reject receipt, optionally no reply (see WR-02), return
```

### WR-02: Reason-specific rejection text is sent to the unauthorized chat

**File:** `src/adapters/telegram_callbacks.py:525-533`
**Issue:** After a chat-gate rejection, `reply_text_fn` still sends
`_render_outcome_text` output (`"Rejected (APPROVAL_EXPIRED): APPROVE"` etc.)
to `query.message.chat_id` — the attacker's chat. Distinct reasons
(`APPROVAL_EXPIRED` vs `STALE_SETUP` vs `INVALIDATED`) give an unauthorized
party a plan-state oracle, contradicting the T-8-13 disclosure mitigation
claimed in the module header.
**Fix:** Skip the reply entirely on chat-gate failure, or send a constant
generic string (`"Rejected"`) with no reason code, kind, or status.

### WR-03: Unknown/stale short_id crashes the handler instead of graceful INVALIDATED

**File:** `src/adapters/telegram_callbacks.py:510-523`, `322-337`
**Issue:** Three unhandled paths on normal operator flows (stale buttons after
a re-plan are common): (a) `binding` is `None` → `raw_token=""` → `Callback(...)`
raises `ValueError` (binding.py:66); (b) `binding_context=None` → explicit
`ValueError` (line 322); (c) resolver dict missing `plan_hash`/etc. keys →
bare `KeyError` (lines 332-336). None is mapped to `DispatchResult(ok=False,
INVALIDATED)`; the PTB handler raises after the spinner clear, so the operator
gets silence. The receipt was already journaled, but no outcome is recorded.
**Fix:** Validate the binding up front in `dispatch_callback` / `on_callback`
and return `DispatchResult(ok=False, kind=parsed.kind,
reason_code=RejectionReason.INVALIDATED)`; wrap `Callback(...)` construction in
try/except `ValueError`/`KeyError` with the same mapping.

### WR-04: `CALLBACK_RESOLVED` / `CALLBACK_REJECTED` outcomes are never journaled

**File:** `src/adapters/telegram_callbacks.py:88-92`, `241-379`
**Issue:** The outcome-rendering event types are defined and the module header
(lines 12, 88-92) promises a post-resolve journal entry, but `dispatch_callback`
emits only `CALLBACK_RECEIVED` (receipt + chat-reject). Success, replay,
unknown-short-id, and binding-gate failures leave no outcome event, so the
T-8-12 repudiation trail is receipt-only and `EVENT_TYPE_CALLBACK_RESOLVED` /
`EVENT_TYPE_CALLBACK_REJECTED` are dead constants.
**Fix:** After the `resolve_callback` try/except and on each early return,
journal a `CALLBACK_RESOLVED` (ok) or `CALLBACK_REJECTED` (with `reason_code`)
event carrying `short_id`, `kind`, and `correlation_id`. Make `journal_receipt`
failures fail closed (propagate — never resolve without a receipt).

### WR-05: No short_id consistency check; mapping PK collisions unhandled

**File:** `src/adapters/telegram_callbacks.py:339-358`
**Issue:** `new_mapping` is derived from the looked-up `(signal_id,
trade_plan_id)` but never checked against `parsed.short_id`. A stale mapping
row (re-plan changed the trade plan for the same signal — same short, new plan)
silently persists a divergent row. If the short already exists with different
content, the atomic insert raises an integrity error with no handling, turning
an approval into a 500. The replay path avoids the insert only incidentally
(resolve returns before `save`; fragile coupling noted in the comment at
lines 349-358).
**Fix:** Assert `new_mapping.short_id == parsed.short_id` (fail to INVALIDATED
on mismatch); make `save_atomic` an upsert-or-verify (insert if absent, verify
equality if present, never overwrite a different plan binding); add a test for
the re-plan-same-signal case.

### WR-06: Expiry gate uses attacker-influenced `callback_at_utc` when `now_utc` is omitted

**File:** `src/approval/replay.py:93-94`
**Issue:** `effective_now = now_utc or callback.callback_at_utc`. In
`on_callback` the timestamp is server-set (safe), but `dispatch_callback`
accepts caller-supplied `callback_at_utc` and forwards `now_utc=None` by
default, so any other caller (or future wiring) lets the callback's own
timestamp decide expiry. A stale callback replayed with an old `callback_at_utc`
passes the Gate-2 check (`now_utc >= expiry_utc`) and also backdates
`acted_at_utc` (line 162).
**Fix:** Require an explicit server-side `now_utc` in `resolve_callback`
(no `None` default at the `dispatch_callback` layer — default to
`datetime.now(UTC)` at the adapter edge, never to the callback's timestamp);
validate `callback_at_utc` freshness (e.g. reject skew > N minutes) as
defense-in-depth.

### WR-07: Sweeper raises on single-item failure despite the "NEVER raises" contract

**File:** `src/reconcile/sweeper.py:195-230`
**Issue:** The docstring (lines 156-159) promises the sweeper never raises on a
single cancel failure (journal-and-continue), but there is no try/except around
`query_algo_order_by_client`, `cancel_algo_order`, or the journal records. One
transient cancel error aborts the remaining orphans mid-batch, and the pre-image
already journaled for the failed item has no matching post-image (audit gap).
**Fix:** Wrap the per-orphan probe→pre→cancel→post sequence in try/except
`Exception`, journal a failure event, append `SweepSkip(reason=...)`, and
continue. Add a test with a cancel that raises on the first of two orphans.

### WR-08: `found=False` probes counted as `cancelled` with zero journal trail

**File:** `src/reconcile/sweeper.py:199-205`
**Issue:** A not-found probe appends to `cancelled` (inflating `swept_count`)
without pre/post `ORPHAN_SWEEP` events. `cancelled` therefore mixes "we
cancelled X" with "X was already gone", and the journal-first invariant claimed
for every sweep (lines 10-14) does not hold for this path.
**Fix:** Track already-gone items separately (`SweepOutcome` gains an
`already_gone` tuple, or count them in `skipped` with reason
`"already_gone_no_cancel_needed"`), and journal a single informational event.

### WR-09: Sweeper timestamp frozen at construction goes stale on reuse

**File:** `src/reconcile/sweeper.py:129-138`, `161-163`
**Issue:** `effective_now` prefers `self._now_utc` pinned in `__init__`. A
long-lived sweeper (the scheduled tick owns one) reuses the same timestamp for
every sweep: `cancelled_at_utc` payloads lie, and `journal_event_id`s
(`orphan_sweep_pre/post_{algo}_{ms}`) collide across ticks on re-sweep,
causing journal PK conflicts or silently overwritten audit rows.
**Fix:** Default `now_utc=None` per `sweep()` call (resolve `datetime.now(UTC)`
inside `sweep`, not `__init__`); keep the constructor parameter only as a
test hook, or remove it.

### WR-10: Concurrent same-token deliveries can double-transition (no compare-and-set)

**File:** `src/approval/replay.py:144-167`
**Issue:** Exactly-once rests on read-then-write with no concurrency control:
two concurrent `resolve_callback` calls can both read PENDING, both build a
transition, both call `save`. There is no row version, no `WHERE
status=PENDING` conditional update, and no unique constraint on
(post-transition) state in `ApprovalRow` (`src/db/models.py:244-267`). The
5x test is sequential; Telegram double-taps plus PTB handler concurrency make
simultaneous delivery realistic, and a double transition means a duplicate
execution intent downstream.
**Fix:** Make `save` a conditional write (update-only-if-still-PENDING, e.g.
`UPDATE approvals SET ... WHERE approval_id=:id AND status='PENDING'`, treat
0-rows as replay-return-existing), or serialize per token hash (per-key lock)
in the receiver. Add a concurrent-replay test (threads racing `resolve_callback`
against a shared store with a check-and-set save).

### WR-11: Orphan classification ignores `position_side`; zero-amount local positions mask orphans

**File:** `src/reconcile/compare.py:258-281`
**Issue:** (a) `has_local_position`/`has_exchange_position` compare symbol only
(line 279-280): a SHORT position satisfies a LONG protective's existence check.
(b) `local_position_keys` (lines 258-264) includes every local position row
regardless of amount — a zero-amount (flat) local row counts as "has position"
and suppresses `ORPHAN_PROTECTIVE`. The adapter filters zero amounts, but
`compare` is also called with caller-built intent where that invariant may not
hold.
**Fix:** Match on `(symbol, position_side)` in both checks and ignore
zero-amount local positions when building `local_position_keys`.

### WR-12: Exchange-missing orphan skips the UNSYNCED check (misclassified, then miscounted)

**File:** `src/reconcile/compare.py:283-301`
**Issue:** The `continue` at line 301 means an orphan protective absent from
exchange truth is classified `ORPHAN_PROTECTIVE` rather than also/instead
`UNSYNCED_ALGO`. The sweeper probe then returns `found=False` and — via WR-08 —
reports it as successfully swept. A protective the exchange never had is
indistinguishable in outcomes from one actually cancelled.
**Fix:** Emit `UNSYNCED_ALGO` when the algo has no exchange row (regardless of
position state) and reserve `ORPHAN_PROTECTIVE` for algos confirmed present on
the exchange; or keep one divergence but stop counting `found=False` as swept
(WR-08 fix covers the metric side).

### WR-13: `ENTRY_WITHOUT_PROTECTIVE` masked by orphaned or exchange-missing protectives

**File:** `src/reconcile/compare.py:341-363`
**Issue:** The protective-existence check (lines 345-349) counts *any* local
algo with a protective role for the symbol — including an algo that is itself
an unsynced/orphan divergence (no exchange row, no position). An ENTRY "with
protection" that exists only as a doomed local row suppresses the
entry-without-protective signal. Additionally, the check is skipped entirely
when the ENTRY's own truth row is missing (`continue` at line 339 yields only
`UNSYNCED_NORMAL`).
**Fix:** Count only protectives that have a matching exchange truth row (and,
strictly, a position to protect); evaluate the protective check before the
truth-`continue`, so a missing ENTRY with no protective yields both divergences.

### WR-14: Malformed local-intent rows abort the whole tick instead of diverging

**File:** `src/reconcile/compare.py:238-256`, `449-454`
**Issue:** A missing `client_order_id`/`client_algo_id`/`status` raises
`ValueError`, aborting the entire three-source compare. One corrupt local row
means no diff, no SAFE_MODE entry, no sweep — the safety net fails open on
unexpected input shape. A reconciler must be total over its inputs.
**Fix:** Convert malformed rows into divergences (e.g. `UNSYNCED_NORMAL` /
`UNSYNCED_ALGO` with reason `"local intent missing identity field"`) or skip +
journal, never raise. Add a test with a status-less dict in intent asserting a
divergence (not an exception).

### WR-15: `position_verifier` sync contract vs async adapter reality; `asyncio.run` in drills breaks under a loop

**File:** `src/reconcile/sweeper.py:62-69`, `src/ops/drills.py:511`, `774`, `849`
**Issue:** The sweeper demands a *synchronous* position reader, but the only
production truth source (`BinanceUsdmAdapter.snapshot_positions`) is async —
there is no sanctioned sync bridge, inviting a forgotten-`await` (coroutine
object is never `== 0`, so `_is_zero_like` returns falsy → perpetual skip, i.e.
orphans never swept) or a blocking call inside the event loop. The drills paper
over this with `asyncio.run()` inside `assert_outcome`, which raises
`RuntimeError` if the harness ever runs under a live loop (pytest-asyncio,
FastAPI lifespan), making the rehearsal harness unusable exactly where it would
be embedded.
**Fix:** Make the verifier interface async (`await position_verifier(symbol=...)`)
with the fake as `async def`; make drill `assert_outcome` async (or run the
whole harness with `asyncio`) instead of nested `asyncio.run`.

### WR-16: `exit_safe_mode` trusts caller-supplied local intent (stale input → false clean exit)

**File:** `src/reconcile/safe_mode.py:233-281`
**Issue:** Truth is re-fetched fresh, but local intent arrives as caller
arguments defaulting to `[]`. Passing stale/empty intent against an empty (or
stale) truth yields `agreement=True` and a journaled exit — SAFE_MODE drops on
a vacuous compare. Pitfall 4 demands a *fresh* three-source compare; half the
inputs are caller-asserted fresh with no verification.
**Fix:** Source local intent inside the exit path (inject a `local_intent_fn`
the controller calls at exit time, same tick as the truth fetch), or require
explicit non-`None` intent plus a freshness token (e.g. caller passes the
intent's `as_of_utc` and exit rejects skew beyond the tick cadence).

### WR-17: Callback receipt IDs have one-second resolution (double-tap PK collision)

**File:** `src/adapters/telegram_callbacks.py:404-415`, `442-450`, `503-504`
**Issue:** `journal_event_id = f"cb-receipt:{short}:{correlation_id}"` with
`correlation_id = f"cb:{short}:{int(timestamp)}"` (second resolution). Telegram
retries and human double-taps routinely land two receipts in the same second →
identical PKs → the second receipt insert fails (or overwrites), losing audit
rows in exactly the at-least-once scenario the journal-first design centers on
(the ID also redundantly embeds the short_id twice).
**Fix:** Use millisecond timestamps plus a random/sequence suffix
(`f"cb-receipt:{short}:{ms}:{uuid4hex8}"`), matching the ms practice used by
the sweeper/safe_mode journal IDs.

### WR-18: `plan_hash` accepted without 64-hex enforcement (prefix-only identity)

**File:** `src/execution/order_ids.py:54-62`
**Issue:** `_require_plan_hash` checks only non-empty string, while the module
docstring pins a 64-char SHA-256 identity. Derivation slices `hash[:32]` /
`[:31]`, so two plans sharing a 32-char prefix (or short test hashes like
`"abc"`) mint identical `client_order_id`s for the same role — the
exchange-dedupe identity collides across *different* plans, risking
cancel/query cross-talk in the sweeper. Malformed hashes fail nowhere loudly.
**Fix:** Enforce `len == 64` and hex charset in `_require_plan_hash`
(`ValueError` otherwise); keep a lenient internal helper only for explicitly
marked test fixtures if needed.

### WR-19: Snapshot projection fabricates epoch-0 timestamps and zero quantities (D-09 violation)

**File:** `src/adapters/binance_usdm.py:957-959`, `1002-1004`, `970-972`, `1019-1021`, `1089-1098`
**Issue:** Rows missing `orig_qty`/`quantity` become `Decimal("0")` and rows
missing `update_time` become 1970-epoch via `_epoch_utc()` — plausible-looking
fabrications the module otherwise forbids (identity fields raise, lines
940-947). A zero-quantity order or epoch-dated algo can poison downstream
ordering/age logic while wearing real-data clothes; the `_epoch_utc` docstring
acknowledges the tension but keeps the fabrication.
**Fix:** Raise `ValueError` on missing `orig_qty`/`quantity`/`update_time`
like the identity fields, or propagate `None` with an explicit
`update_time_utc: datetime | None` contract so consumers must handle absence.

### WR-20: Cancel retry budget burns on already-canceled errors

**File:** `src/adapters/binance_usdm.py:798-808`, `861-871`, `109-117`
**Issue:** `_is_transient_reconcile` returns True for everything except
`ValueError`/`KeyError`/`TypeError` — including the `-2011/UNKNOWN_ORDER`
already-canceled error the outer handler maps to success. A cancel for a gone
order therefore retries up to 3 attempts / 30s before succeeding, tripling
exchange load on the commonest idempotent path and delaying the sweep.
**Fix:** Exclude already-canceled messages from the retry predicate:
```python
def _cancel_retry_predicate(exc: BaseException) -> bool:
    if _is_already_canceled_message(str(exc)):
        return False
    return _is_transient_reconcile(exc)
```

### WR-21: 64-byte ceiling enforced with `assert` (stripped under `python -O`)

**File:** `src/adapters/telegram_notify.py:111-112`
**Issue:** `build_simulate_keyboard` guards Telegram's hard 64-byte
`callback_data` limit with bare `assert`s, which vanish under `python -O`.
An over-long payload would then fail at the Telegram API call instead of at
build time. (The Phase-8 builders in the same file correctly raise.)
**Fix:** Replace both asserts with an explicit `ValueError` like
`_short_signal_id_with_prefix` does.

### WR-22: `format_approve` fail-closed validation is partial (WR-11 over-claimed)

**File:** `src/adapters/telegram_notify.py:244-264`
**Issue:** The docstring claims fail-closed rendering, but only
symbol/direction/setup/entry-order/TP-nonempty/datetimes are checked.
Unchecked: `stop_loss` (None/negative), `rr`/`risk_pct`/`exposure_quote`
(negative, NaN, non-Decimal), `take_profits` *items* (None price, negative
fraction — renders garbage silently), `invalidation` (empty → blank operator
field), `reason_codes` entries (non-strings raise bare `TypeError` from join;
embedded newlines allow message-shape spoofing).
**Fix:** Validate each TP `(price, fraction)` pair (Decimal, positive,
fraction in (0,1]), require non-empty `invalidation`, require `reason_codes:
list[str]` with no newlines, and bound `risk_pct >= 0`. Add tests per field.

### WR-23: Top-level PTB imports contradict the pure/PTB-free isolation claims

**File:** `src/adapters/telegram_callbacks.py:63-69`, `src/adapters/telegram_notify.py:37`
**Issue:** `telegram_callbacks` claims (lines 21-28, 609-612) the PTB imports
are "guarded" and pure surfaces are independently usable, but `Update`,
`Application`, `CallbackQueryHandler`, `ContextTypes`,
`InlineKeyboardMarkup` are imported at module top level — importing
`parse_callback_data` in an env without `python-telegram-bot` crashes.
Likewise `format_approve` is advertised PTB-free for `src/paper/notify.py`
reuse, yet lives in a module that imports `telegram` at line 37.
**Fix:** Move PTB imports behind function scope (`build_application`,
`on_callback`, keyboard builders) or split pure surfaces (`parse.py`,
`render_approve.py`) into genuinely dependency-free modules; add an import
test asserting the pure modules load with `telegram` blocked (`sys.modules`
poisoning).

### WR-24: Vacuous test — synonym-reason guard can never fire

**File:** `tests/test_approval_replay.py:650-697`
**Issue:** The loop collects candidates into `suspicious` but the body has no
`suspicious.append(...)` on the fall-through path — every non-canonical,
non-skipped literal is simply ignored, so `assert not suspicious` passes
unconditionally. The GLOSSARY-§9 canonical-vocabulary gate provides zero
protection (reliability defect in test code, in scope per review rules).
**Fix:** Append the candidate (with file + line number) when it survives the
canonical/allow-list filters; verify the test fails when a probe synonym (e.g.
`"WRONG_CHAT"`) is temporarily added.

### WR-25: Vacuous test — no-place-order invariant test asserts nothing

**File:** `tests/test_drills.py:941-970`
**Issue:** `test_no_place_order_invariant_across_all_drills` runs the suite
then ends in comments — zero assertions (the fakes it would check are
function-local and inaccessible). The D-03/EXEC-02 runtime invariant is claimed
but not verified; only the static grep (which allow-lists generously) runs.
**Fix:** Thread the fake adapters out (return them from
`_build_all_drill_declarations` or record into a shared registry) and assert
`place_order_calls == 0` on every adapter; extend the fake `place_order` to
log-then-raise so accidental calls are visible even if swallowed (cf. WR-26).

### WR-26: api_down / db_failure drills swallow programming errors as degradation

**File:** `src/ops/drills.py:639-653`, `725-737`
**Issue:** Bare `except Exception: pass` around the injected call means a
`TypeError`/`AttributeError` *in the harness wiring itself* is misread as
"transient degradation" and the drill passes. The rehearsal then certifies a
broken setup path.
**Fix:** Catch only the injected transient type (e.g. `RuntimeError` with an
expected marker, or a dedicated `TransientFault` exception), let anything else
propagate.

### WR-27: Restore drill falls back to wall-clock time

**File:** `src/ops/drills.py:836-841`
**Issue:** `assert_outcome` uses `datetime.now(UTC)` when the constructor
`now_utc` is `None`, violating the module's own "never wall-clock;
caller-injected timestamps" determinism contract (lines 32-38). The
`SAFE_MODE_ENTER` journal timestamp then varies run to run.
**Fix:** Require `now_utc` (keyword-only, no default) in `make_restore_drill`,
or thread the harness `now_utc` through `context` instead of the constructor.

### WR-28: `make_manual_close_drill` ignores the injected `compare_fn`

**File:** `src/ops/drills.py:776-791`
**Issue:** Unlike `make_orphan_drill`/`make_unprotected_drill`, the manual-close
factory imports `compare` directly (`_compare_default`) instead of using an
injected callable — there is no `compare_fn` parameter at all. A caller
rehearsing against a configured compare (filters, thresholds) silently
rehearses against a different function; drill and reality diverge.
**Fix:** Add a `compare_fn` parameter (same shape as the orphan factory) and
use it; add a test passing a sentinel compare that records invocation.

### WR-29: `DrillLog` has no concurrency control despite parallel-run ordering claims

**File:** `src/ops/drills.py:199-230`
**Issue:** The log is a bare list with append/clear and no lock, yet the
contract (lines 56-59, and the determinism test narrative) claims parallel /
interrupted re-runs "must NEVER reorder" entries. Concurrent `run_drill` calls
interleave arbitrarily; `reset()` mid-run drops rows.
**Fix:** Either scope the claim to sequential runs (document
single-writer-only, make `run_all_drills` the sole writer) or add a lock and
make `record` atomic w.r.t. outcome sequencing (sequence numbers assigned at
`run_drill` dispatch, not at journal time).

### WR-30: Mapping table has no FK, TTL, or cleanup (stale + unbounded rows)

**File:** `src/db/alembic/versions/0003_callback_mapping.py:35-55`, `src/db/models.py:404-428`
**Issue:** `short_id_mapping` references `(signal_id, trade_plan_id)` with no
foreign keys, no expiry, and no cleanup path. Re-plans leave stale rows
pointing at superseded plans (the receiver resolves them without complaint —
see WR-05), and every alert inserts a row that lives forever (unbounded growth
on a per-signal table).
**Fix:** Decide the lifecycle explicitly: either FK to `trade_plans` with
`ON DELETE` handling plus a reconciler that purges mappings for
decided/expired approvals, or a TTL column + scheduled purge. At minimum,
document the retention contract in the migration header and add a uniqueness
guard on `(signal_id, trade_plan_id)`.

### WR-31: SIMULATE-action approval reaching replay raises a confusing `ValueError`

**File:** `src/approval/replay.py:156-163`, `src/approval/binding.py:116-133`
**Issue:** `action_to_result(SIMULATE)` returns `PENDING`, so `replace(approval,
result=PENDING, status=PENDING, acted_at_utc=effective_now)` violates the
WR-07 invariant (`PENDING ⟺ acted_at_utc is None`, enforced in
`src/domain/approval.py:66-67`) and raises a bare `ValueError`. The only thing
preventing this is the receiver routing SIM away — one refactor from a crash
with a misleading message on a live callback path.
**Fix:** Reject explicitly at the top of the transition block:
```python
if approval.action == ApprovalAction.SIMULATE:
    raise ApprovalRejected(reason_code=RejectionReason.INVALIDATED,
                           message="SIMULATE never transitions approval state")
```

## Info

### IN-01: Stale docstring references nonexistent `binding.check_binding`

**File:** `src/approval/__init__.py:16`
**Issue:** Package docstring names `binding.check_binding`; the actual symbol
is `check_binding_full`. Copy-paste drift; misleads new readers about the
public surface.
**Fix:** Update the docstring to `check_binding_full`.

### IN-02: `__all__` omits `DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE`

**File:** `src/reconcile/compare.py:471-483`
**Issue:** All four sibling kind constants are exported except
`ENTRY_WITHOUT_PROTECTIVE`, though `src/reconcile/__init__.py` imports it
directly. Star-imports and programmatic `__all__`-based checks silently miss
one of the five canonical kinds.
**Fix:** Add `"DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE"` to `__all__`.

### IN-03: `_is_already_canceled_response` is dead code (always `False`)

**File:** `src/adapters/binance_usdm.py:920-927`, `822`, `884`
**Issue:** The helper unconditionally returns `False`, so both
`if _is_already_canceled_response(result)` branches never take. The indirection
suggests a decision point that does not exist.
**Fix:** Inline the comment at the call sites and delete the helper, or
implement the future "noop status" check it promises.

### IN-04: `_row_to_*` projections claim `| None` but never return `None`

**File:** `src/adapters/binance_usdm.py:930-932`, `976-978`, `1025-1027`
**Issue:** All three projectors return `X | None` but every path either raises
or returns a snapshot. Callers (`snapshot_*`, lines 673-675 etc.) null-check
for a case that cannot occur, suggesting optional semantics that do not exist.
**Fix:** Narrow the return types to non-optional.

### IN-05: `ROLE_CODES` is a mutable module-level dict

**File:** `src/execution/order_ids.py:37-42`
**Issue:** Any importer can mutate the canonical vocabulary at runtime
(`ROLE_CODES["ENTRY"] = "XX"`), silently changing every subsequently derived
exchange-dedupe ID. The module header calls this table the single source of
truth but does not protect it.
**Fix:** Expose as `MappingProxyType` (keep a private mutable copy only if
tests need patching).

### IN-06: `_symbols_for_position_side` is dead code

**File:** `src/reconcile/compare.py:464-468`
**Issue:** Defined, never called. (Notably, its existence suggests the
symbol+side matching WR-11 asks for was once intended.)
**Fix:** Delete it, or use it as the basis for the WR-11 fix.

### IN-07: `Callback` validates hash lengths but not hex charset

**File:** `src/approval/binding.py:81-87`
**Issue:** `plan_hash`/`parameter_set_hash` require length 64 but accept any
characters. Non-hex identities still compare by equality, so this is cosmetic
— but the 64-char shape claim ("64-char string") is weaker than the
"SHA-256 hex" identity used for token hashes and short ids.
**Fix:** Add a hex-charset check consistent with `ShortIdMapping` validation.

### IN-08: Two canonical drill outcomes are never emitted

**File:** `src/ops/drills.py:99-114`
**Issue:** `OUTCOME_SAFE_MODE_BLOCKED` and
`OUTCOME_NO_PLACE_ORDER_INVARIANT` are in `ALL_OUTCOMES` but no factory
returns them. The vocabulary claims rehearsal coverage the harness never
produces; containment-style tests cannot tell.
**Fix:** Either emit them (blocked-entries drill; invariant drill) or remove
them from the canonical set.

### IN-09: `is_rate_limit_error` name-sniff fallback is overbroad

**File:** `src/adapters/binance_usdm.py:330-342`
**Issue:** Any exception class with "TooManyRequests"/"RateLimit" in its name
— including unrelated user/test doubles — is classified as a rate-limit error.
The isinstance primary is correct; the fallback trades a loud failure for a
silent misclassification.
**Fix:** Restrict the fallback to SDK-module-owned types (check
`type(exc).__module__`) or drop it and fail loudly on wrapped errors.

### IN-10: `-2011` substring matching risks false positives

**File:** `src/adapters/binance_usdm.py:760`, `917`
**Issue:** `"-2011" in str(exc)` also matches `"-20110"`, `"-20111"`, etc.
(and any message embedding that digit run). A different error code containing
the substring would be misread as already-canceled/not-found → treated as
success.
**Fix:** Match with a regex on a code boundary (`r"(?<!\d)-2011(?!\d)"`) and,
where possible, prefer a structured `code` attribute over message scraping.

### IN-11: UTC discipline is inconsistent across the callback path

**File:** `src/adapters/telegram_callbacks.py:395-396`, `432-433`, `src/adapters/telegram_notify.py:254-261`
**Issue:** Domain types (`Approval`, `JournalEvent`, `ShortIdMapping`,
binding gates) require UTC offset exactly 0; the receipt builders and
`format_approve` accept any tz-aware datetime. A `+07:00` input either crashes
at `JournalEvent` construction (unhandled, mid-dispatch) or renders a
converted time the approval logic never saw.
**Fix:** Apply the strict `_require_utc_aware` (offset-0) check at every
adapter-edge entry point (`dispatch_callback`, `format_approve`).

### IN-12: `ShortIdMapping` round-trip breaks on naive-datetime drivers

**File:** `src/db/mappers.py:456-468`
**Issue:** `short_id_mapping_from_row` re-runs `__post_init__`, which rejects
naive datetimes. PostgreSQL returns aware datetimes (fine), but any SQLite
test/dev driver returns naive ones → round-trip raises. The mapper is
silently PG-only.
**Fix:** Normalize in `from_row` (`r.created_at_utc.replace(tzinfo=UTC)` when
naive, with a comment), or document the PG-only contract on the mapper.

### IN-13: `enter_safe_mode` accepts an empty reason

**File:** `src/reconcile/safe_mode.py:168-204`
**Issue:** `reason=""` is journaled without complaint, producing meaningless
`SAFE_MODE_ENTER` audit rows. Drills always pass real reasons, so nothing
catches it.
**Fix:** `if not reason: raise ValueError(...)`.

### IN-14: Skipped cancels leave no journal trace

**File:** `src/reconcile/sweeper.py:181-193`
**Issue:** The transient-position-gap skip builds a `SweepSkip` returned to the
caller but journals nothing, so the audit trail cannot distinguish "no orphans"
from "orphan seen, deliberately deferred". The next tick re-derives the same
skip with no history.
**Fix:** Journal an informational event for each skip (or a single per-tick
summary carrying the skip reasons).

### IN-15: Duplicate truth client IDs silently collapse in the compare index

**File:** `src/reconcile/compare.py:228-233`
**Issue:** Dict-comprehension indexing keeps the last row per
`client_order_id`/`client_algo_id`. A duplicated exchange identifier (data bug
or partial-fill row split) is silently deduped instead of surfaced.
**Fix:** Detect duplicates at index build and emit an `UNSYNCED_*` divergence
(or raise a dedicated `DuplicateTruthId` error the tick journals).

### IN-16: Dead/confused WR-07 guard in `resolve_callback`

**File:** `src/approval/replay.py:147-154`
**Issue:** After `if approval.status != PENDING: return approval`, the remaining
code provably has `status == PENDING`, which (per `Approval.__post_init__`)
implies `acted_at_utc is None` — so the `if acted_at_utc is not None` branch
is unreachable, and its comment ("a non-PENDING approval must have acted_at
set… treat as PENDING") describes the opposite case. Dead code with an
inverted explanation.
**Fix:** Delete the branch; optionally assert the invariant explicitly:
```python
assert approval.status == ApprovalResult.PENDING
assert approval.acted_at_utc is None
```

---

_Reviewed: 2026-09-27T12:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
