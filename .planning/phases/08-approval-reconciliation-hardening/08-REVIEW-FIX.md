---
phase: 08-approval-reconciliation-hardening
fixed_at: 2026-09-27T12:45:00Z
review_path: C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/08-approval-reconciliation-hardening/08-REVIEW.md
iteration: 1
findings_in_scope: 34
fixed: 34
skipped: 0
status: all_fixed
---

# Phase 08: Code Review Fix Report

**Fixed at:** 2026-09-27T12:45:00Z
**Source review:** `08-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 34 (3 critical + 31 warnings; 16 info out of scope)
- Fixed: 34
- Skipped: 0

**Verification environment:** main checkout (no worktree — `workflow.use_worktrees` is
`false`). Per-fix verification: Tier 1 re-read for every edit; Tier 2 `ast.parse`
syntax check for every edited file; functional spot-checks for the approval replay
(5x = 1 transition preserved), the compare matrix (clean/orphan/unprotected/missing-entry),
and the sweeper gone/boom paths. The full pytest suite could not run here
(`structlog`/`tenacity`/Binance SDK not installed in this environment — pre-existing,
unrelated to these fixes); Tier 2 failures confined to those missing third-party
imports were treated as pre-existing and did not block commits. Entries marked
`fixed: requires human verification` are reconciler-logic changes the verifier phase
should re-exercise with the full suite.

## Fixed Issues

### CR-01: Pressed button (APPROVE vs SKIP) never determines the outcome

**Files modified:** `src/approval/binding.py`, `src/approval/replay.py`, `src/adapters/telegram_callbacks.py`
**Commit:** 2fbcbca
**Applied fix:** `Callback` carries the pressed-button decision (`action: ApprovalAction | None`,
default `None` for backward compatibility); `dispatch_callback` populates it from the
parsed kind (`APPROVE` → `APPROVE`, `SKIP` → `SKIP_USER`); `resolve_callback` maps the
callback's action (falling back to the stored row only when absent) and rejects a
stored/callback mismatch with `INVALIDATED`. Also rejects `SIMULATE` explicitly (WR-31,
co-fixed here).

### CR-02: `guard_new_entries` raises on the non-SAFE_MODE path

**Files modified:** `src/reconcile/safe_mode.py`
**Commit:** 74e1566
**Applied fix:** `SafeModeVerdict.reason_code` is now `str | None` — `None` is the PASS
verdict (`is_no_trade=False`); `RECONCILIATION_REQUIRED` still gates `is_no_trade=True`.
`guard_new_entries` returns `reason_code=None` off the SAFE_MODE path. No other
`SafeModeVerdict` consumers compare against `"OK"`.

### CR-03: Post-fill unprotected position yields `agreement=True`

**Files modified:** `src/reconcile/compare.py`
**Commit:** 53f06cc
**Applied fix:** Added Pass 1b — every non-zero local position requires at least one open
local protective algo for the same symbol (side-aware where the algo carries a side),
else an `ENTRY_WITHOUT_PROTECTIVE` divergence. Zero-amount (flat) locals stay clean.
**Status:** fixed: requires human verification (reconciler logic; simulation-checked:
naked → diverges, flat → clean, protected → clean).

### WR-01: `on_callback` performs state lookup before the chat gate

**Files modified:** `src/adapters/telegram_callbacks.py`
**Commit:** 45d512a
**Applied fix:** `on_callback` runs `authorized_chat_gate` before
`binding_context_resolver`; on gate failure it dispatches with empty credentials and no
resolver read (the injected dispatch still journals the reject receipt via its own gate
path). No DB lookup on unauthorized chats.

### WR-02: Reason-specific rejection text is sent to the unauthorized chat

**Files modified:** `src/adapters/telegram_callbacks.py`
**Commit:** ece6932
**Applied fix:** The chat-gate-failure branch replies with the constant `"Rejected"` —
no reason code, kind, or status leaks to the unauthorized chat.

### WR-03: Unknown/stale short_id crashes the handler instead of graceful INVALIDATED

**Files modified:** `src/adapters/telegram_callbacks.py`
**Commit:** 4c67759
**Applied fix:** Missing `binding_context` returns `INVALIDATED` instead of raising;
`Callback` construction is wrapped (`ValueError`/`KeyError`/`TypeError` → `INVALIDATED`);
the `resolve_callback` call site also maps `ValueError`/`KeyError`/`TypeError` to
`INVALIDATED`. No unhandled crash on stale-button flows.

### WR-04: `CALLBACK_RESOLVED` / `CALLBACK_REJECTED` outcomes are never journaled

**Files modified:** `src/adapters/telegram_callbacks.py`
**Commit:** 9292e6d
**Applied fix:** New `_journal_outcome` helper journals `CALLBACK_RESOLVED` (ok) or
`CALLBACK_REJECTED` (with `reason_code`) on every dispatch path — chat reject, SIMULATE,
unknown short, binding failures, replay rejects, and success. Outcome IDs use
millisecond + random suffixes. Journal failures propagate (fail closed).

### WR-05: No short_id consistency check; mapping PK collisions unhandled

**Files modified:** `src/adapters/telegram_callbacks.py`
**Commit:** 8b3e0cb
**Applied fix:** `dispatch_callback` rejects (`INVALIDATED` + outcome journal) when the
derived mapping's `short_id` differs from the parsed one, and maps any unexpected
exception from the resolve/save path (e.g. mapping PK conflict on re-plan) to
`INVALIDATED` fail-closed instead of a 500.

### WR-06: Expiry gate uses attacker-influenced `callback_at_utc` when `now_utc` is omitted

**Files modified:** `src/adapters/telegram_callbacks.py`
**Commit:** 801d218
**Applied fix:** `dispatch_callback` resolves `now_utc=None` to `datetime.now(UTC)` at the
adapter edge and passes server time explicitly to `resolve_callback`, never delegating
to the callback's own timestamp. (`on_callback` already sets `callback_at_utc`
server-side.)

### WR-07: Sweeper raises on single-item failure despite the "NEVER raises" contract

**Files modified:** `src/reconcile/sweeper.py`
**Commit:** 455abb8
**Applied fix:** The per-orphan probe and pre→cancel→post sequences are each wrapped in
`try/except Exception`: failures journal an `ORPHAN_SWEEP` failure event, append a
`SweepSkip`, and continue with the next orphan. Functionally verified (cancel-raise →
skipped, no raise).

### WR-08: `found=False` probes counted as `cancelled` with zero journal trail

**Files modified:** `src/reconcile/sweeper.py`
**Commit:** b9b99a4
**Applied fix:** `SweepOutcome` gains `already_gone` (default `()`, backward compatible);
`found=False` probes journal an informational `already_gone` event and land there —
`swept_count`/`cancelled` now mean real cancels only. Functionally verified.

### WR-09: Sweeper timestamp frozen at construction goes stale on reuse

**Files modified:** `src/reconcile/sweeper.py`
**Commit:** ee95a96
**Applied fix:** `sweep()` takes per-call `now_utc=None` (explicit value wins, else the
constructor test hook, else `datetime.now(UTC)`). Long-lived sweepers no longer reuse a
pinned timestamp. Same commit adds awaiting of async `position_verifier` results
(WR-15 sweeper half).

### WR-10: Concurrent same-token deliveries can double-transition

**Files modified:** `src/approval/replay.py`
**Commit:** 989ef79
**Applied fix:** Per-token in-process locks serialize `resolve_callback` from token-hash
lookup through save (lookup/gate/transition moved into `_resolve_locked` under the
lock). Docstring records the residual need: cross-process races still require a
conditional store write (`UPDATE ... WHERE status='PENDING'`). 5x-replay behavior
re-verified (1 transition).

### WR-11: Orphan classification ignores `position_side`; zero-amount local positions mask orphans

**Files modified:** `src/reconcile/compare.py`
**Commit:** 7d47f18
**Applied fix:** `local_position_keys` excludes zero-amount locals; orphan checks match on
`(symbol, position_side)` when the algo carries a side (symbol-only fallback otherwise);
exchange-position existence ignores zero-amount truth rows; Pass 3 skips zero-amount
truth positions.
**Status:** fixed: requires human verification (reconciler logic; simulation-checked).

### WR-12: Exchange-missing orphan skips the UNSYNCED check

**Files modified:** `src/reconcile/compare.py`
**Commit:** 3e55369
**Applied fix:** A position-less protective with no exchange truth row emits
`UNSYNCED_ALGO`; `ORPHAN_PROTECTIVE` is reserved for algos confirmed present on the
exchange (the only ones the sweeper may cancel). Orphan-drill scenario (algo present in
truth) still classifies `ORPHAN_PROTECTIVE`.
**Status:** fixed: requires human verification (reconciler logic; simulation-checked).

### WR-13: `ENTRY_WITHOUT_PROTECTIVE` masked by orphaned or exchange-missing protectives

**Files modified:** `src/reconcile/compare.py`
**Commit:** 48557e8
**Applied fix:** The Pass-2 protective check counts only algos with a matching exchange
truth row, and runs before the missing-truth `continue`, so a missing ENTRY with no
real protection yields both `ENTRY_WITHOUT_PROTECTIVE` and `UNSYNCED_NORMAL`.
Simulation-checked (missing ENTRY → both kinds; clean fixture → agreement).
**Status:** fixed: requires human verification (reconciler logic).

### WR-14: Malformed local-intent rows abort the whole tick instead of diverging

**Files modified:** `src/reconcile/compare.py`
**Commit:** 61d791f
**Applied fix:** Missing `client_order_id`/`client_algo_id`/`status` no longer raise:
status-less rows are treated as open (fail closed) and identity-less rows become
`UNSYNCED_NORMAL`/`UNSYNCED_ALGO` divergences with symbol fallback (`"UNKNOWN"`).
Simulation-checked (status-less dict → divergence, not exception).
**Status:** fixed: requires human verification (reconciler logic).

### WR-15: `position_verifier` sync contract vs async adapter reality; `asyncio.run` in drills breaks under a loop

**Files modified:** `src/ops/drills.py`, `src/reconcile/sweeper.py` (sweeper half in WR-09 commit ee95a96)
**Commit:** 4284055
**Applied fix:** Sweeper awaits async verifier results (dual sync/async support). Drills
use a `_run_coro` helper: `asyncio.run` when no loop is running, otherwise a fresh
loop in a worker thread — no nested-`asyncio.run` `RuntimeError` under pytest-asyncio /
FastAPI lifespan. All three call sites (orphan, manual-close, restore) converted.

### WR-16: `exit_safe_mode` trusts caller-supplied local intent

**Files modified:** `src/reconcile/safe_mode.py`
**Commit:** eda6341
**Applied fix:** New optional `local_intent_fn` callable returning
`(orders, algos, positions)` at exit time (same tick as the truth fetch); when supplied
it takes precedence over the list arguments, so a stale/empty caller snapshot cannot
produce a vacuous clean exit. List arguments remain for backward compatibility
(restore drill unchanged).

### WR-17: Callback receipt IDs have one-second resolution

**Files modified:** `src/adapters/telegram_callbacks.py`
**Commit:** 67f0f20
**Applied fix:** `correlation_id` is now `cb:{short}:{ms}:{uuid8}`; receipt/reject journal
IDs derive from the unique correlation (`cb-receipt:{correlation}`, `cb-reject:{...}`) —
no more double-tap PK collisions, no duplicated short embedding.

### WR-18: `plan_hash` accepted without 64-hex enforcement

**Files modified:** `src/execution/order_ids.py`
**Commit:** db126ff
**Applied fix:** `_require_plan_hash` enforces 64-char lowercase hex (SHA-256 identity).
Existing fixtures use 64-hex hashes (`"1"*64`, `"0"*64`), so no fixture breakage.

### WR-19: Snapshot projection fabricates epoch-0 timestamps and zero quantities

**Files modified:** `src/adapters/binance_usdm.py`
**Commit:** 8370718
**Applied fix:** New `_require_quantity` / `_require_update_time_utc` helpers raise on
missing `orig_qty`/`quantity`/`update_time` in all three projectors (normal, algo,
position) instead of fabricating `Decimal("0")` / 1970-epoch. Optional price/trigger
fields still propagate `None`.

### WR-20: Cancel retry budget burns on already-canceled errors

**Files modified:** `src/adapters/binance_usdm.py`
**Commit:** 1ed7c56
**Applied fix:** New `_cancel_retry_predicate` returns `False` for already-canceled
messages (via `_is_already_canceled_message`) and delegates the rest to
`_is_transient_reconcile`; both cancel paths (`cancel_normal_order`,
`cancel_algo_order`) use it — gone orders succeed without 3-attempt/30s retry burn.

### WR-21: 64-byte ceiling enforced with `assert`

**Files modified:** `src/adapters/telegram_notify.py`
**Commit:** 48929a6
**Applied fix:** Both bare asserts in `build_simulate_keyboard` replaced with explicit
`ValueError` raises that survive `python -O`.

### WR-22: `format_approve` fail-closed validation is partial

**Files modified:** `src/adapters/telegram_notify.py`
**Commit:** e671079
**Applied fix:** Added validation: `stop_loss` positive `Decimal`; `rr`/`risk_pct`/
`exposure_quote` non-negative `Decimal`; each TP `(price, fraction)` pair checked
(price positive `Decimal`, fraction `Decimal` in `(0, 1]`); `invalidation` non-empty;
`reason_codes` must be `list[str]` with no embedded newlines.

### WR-23: Top-level PTB imports contradict the pure/PTB-free isolation claims

**Files modified:** `src/adapters/telegram_callbacks.py`, `src/adapters/telegram_notify.py`
**Commit:** 4b50674
**Applied fix:** PTB imports moved to function scope (`build_application` handler wiring;
all three keyboard builders) with `TYPE_CHECKING` imports for annotations; the
`InlineKeyboardMarkup` re-export in `telegram_callbacks` is now a lazy
`__getattr__`. Pure surfaces (`parse_callback_data`, `dispatch_callback`,
`format_approve`) import without `python-telegram-bot` installed.

### WR-24: Vacuous test — synonym-reason guard can never fire

**Files modified:** `tests/test_approval_replay.py`
**Commit:** 03fb63d
**Applied fix:** The loop now appends surviving candidates (`file:line:literal`) to
`suspicious`, so the guard actually fires; also fixed the shadowed `_line_num` → used
`line_num`. (Remaining LSP notes on `reason_code` attribute access are pre-existing
`hasattr`-guarded patterns, untouched.)

### WR-25: Vacuous test — no-place-order invariant test asserts nothing

**Files modified:** `tests/test_drills.py`
**Commit:** a8e0ca7
**Applied fix:** `_build_all_drill_declarations` registers every fake adapter in the
`BUILT_DRILL_ADAPTERS` registry; the invariant test now asserts `place_order_calls == 0`
on all of them. Fake `place_order`/`place_algo_order` log-then-raise so swallowed calls
stay visible.

### WR-26: api_down / db_failure drills swallow programming errors as degradation

**Files modified:** `src/ops/drills.py`
**Commit:** f3f4e2f
**Applied fix:** Both drills catch only `RuntimeError` (the injected transient type);
`TypeError`/`AttributeError` in harness wiring now propagate instead of passing as
"degradation".

### WR-27: Restore drill falls back to wall-clock time

**Files modified:** `src/ops/drills.py`
**Commit:** 59363fe
**Applied fix:** `make_restore_drill` requires keyword-only `now_utc: datetime` (no
default, no `datetime.now(UTC)` fallback); the sole caller already injects it.

### WR-28: `make_manual_close_drill` ignores the injected `compare_fn`

**Files modified:** `src/ops/drills.py`
**Commit:** 9dbef80
**Applied fix:** Added optional `compare_fn` parameter (defaults to the canonical
compare for backward compatibility) and used it in `assert_outcome`; a sentinel compare
can now verify invocation.

### WR-29: `DrillLog` has no concurrency control despite parallel-run ordering claims

**Files modified:** `src/ops/drills.py`
**Commit:** 29760ad
**Applied fix:** `DrillLog` guards `record`/`reset`/readers with a `threading.Lock`,
tracks a monotonic `_sequence`, and documents single-writer scope (`run_all_drills`).

### WR-30: Mapping table has no FK, TTL, or cleanup

**Files modified:** `src/db/alembic/versions/0003_callback_mapping.py`
**Commit:** 0bf2fdf
**Applied fix:** Migration header now documents the retention contract (rows live until
their approval is decided and past expiry, then a scheduled purge deletes them; no FK
so mappings survive plan supersede for audit replay) and adds a unique guard on
`(signal_id, trade_plan_id)` (plus matching downgrade) so divergent re-bindings fail
closed. (AST-checked; SQLAlchemy not installed in this env — migration not executed
here.)

### WR-31: SIMULATE-action approval reaching replay raises a confusing `ValueError`

**Files modified:** `src/approval/replay.py` (co-fixed with CR-01)
**Commit:** 2fbcbca
**Applied fix:** Explicit `ApprovalRejected(INVALIDATED, "SIMULATE never transitions
approval state")` for stored-action `SIMULATE`, callback-action `SIMULATE`, and any
action mapping to `PENDING` — no more bare `ValueError` from the `Approval` invariant
one refactor away.

---

_Fixed: 2026-09-27T12:45:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
