---
phase: 24-live-runtime-composition-demo
plan: 17
subsystem: live-telegram
tags: [telegram, confirm-flow, on_callback, store-executor, D-17, R-2, P-1, D-25]
requires: [24-04, 24-05]
provides:
  - "LiveTelegramRunner (src/live/telegram_runner.py)"
  - "ConfirmFlow / make_confirm_flow optional run_sync seam"
  - "on_callback optional run_sync seam; RunSyncFn type"
affects: [24-27]
key-files:
  created:
    - src/live/telegram_runner.py
    - tests/test_live_telegram_runner.py
    - tests/test_confirm_flow_worker_thread.py
    - tests/test_telegram_dispatch_off_loop.py
  modified:
    - src/execution/confirm_flow.py
    - src/adapters/telegram_callbacks.py
decisions:
  - "ConfirmFlow.callback_kwargs adds run_sync only when the flow was built with it, so the DEMO/SHADOW keyword set is unchanged and one seam carries both handle_confirm and dispatch."
  - "The runner restates BOT_TOKEN_RULE (same text as shadow_runtime) instead of importing the 1400-line SHADOW module."
status: complete
requirements: [APRV-01, EXEC-03]
commits: 3
plan_head_before: cc6e912c979c531661c70b9981cc58ea457fcf9a
plan_head_after: 1eb1fd3e
actuals:
  tokens: 30000
  tasks: 3
  commits: 3
---

# Phase 24 Plan 17: Telegram runner (on_callback only, confirm off the loop) Summary

The live bot answers presses only through `on_callback` with a mandatory non-empty user allow-list, and `handle_confirm` plus the desk dispatch run on the store writer thread, so one CONFIRM press becomes exactly one scheduled placement without blocking the bot loop.

## What was built

- `src/live/telegram_runner.py`: `LiveTelegramRunner(*, application_factory, desk, stores, profile, clock, bot, sleep, service, executor, authorized_chat_id, authorized_user_ids, error_journal, mark_price, validity_rule, recheck, prefetch)`.
  - `start()` logs `BOT_TOKEN_RULE`, calls the zero-argument factory, registers exactly one `CallbackQueryHandler(partial(on_callback, **flow.callback_kwargs(...)))`, adds the application error handler, then initialize, start, `updater.start_polling(allowed_updates=["callback_query"], drop_pending_updates=False, error_callback=...)`; a failure shuts the application down. `stop()` reverses (updater.stop, stop, shutdown), idempotent. A second `start()` raises.
  - The flow is built with `on_confirmed=service.on_confirmed` and `run_sync=executor.write`; the prefetch coroutine and recheck are injected (plan 24-27 binds them to the plan 24-16 reader).
  - `authorized_user_ids` is validated at construction (empty, plain set, bool or str member raise `ValueError`).
  - `expire_on_restart(now)` and `async finalize_expired_once(now)` are the startup/scheduler hooks. Errors are counted by class name; a `Conflict` logs the token rule once.
  - The runner never closes the executor (the composition root owns it).
- `src/adapters/telegram_callbacks.py`: `RunSyncFn`, `_off_loop_dispatch`, and `on_callback(..., run_sync=None)`; the gates run first on the loop, then `dispatch` is awaited through `run_sync`. An async dispatcher is still awaited on the loop. Default unchanged.
- `src/execution/confirm_flow.py`: `ConfirmFlow(run_sync=None)` / `make_confirm_flow(run_sync=None)`; `_confirm` awaits `run_sync(self._book.handle_confirm, ...)` when set; `callback_kwargs` includes `run_sync` only then. Both files are CRLF in the working tree and were edited bytes-aware (diffs: +29 and +32/-10 lines).

## Tests

All pass (`uv run pytest -m "not docker"`): `test_live_telegram_runner.py` (14), `test_confirm_flow_worker_thread.py`, `test_telegram_dispatch_off_loop.py`, plus `test_confirm_flow.py`, `test_confirm_core.py`, `test_telegram_authorization.py`, `test_telegram_error_handler.py`, `test_paper_shadow_confirm.py`, `test_live_tracer.py`, `test_live_ast_guards.py`, `test_no_unratified_defaults.py`, `test_paper_closure_rule.py`, `test_paper_shadow_isolation.py`, `test_agents_md.py`. Scoped ruff check and format, `mypy src` (274 files) clean; `pyproject.toml` and `uv.lock` unchanged; `git grep "dispatch_callback(" -- src/live` empty.

- A6: a spy over `asyncio.get_running_loop/get_event_loop/create_task/ensure_future` records zero calls from the writer thread during a CONFIRM; the hook's `call_soon_threadsafe` hop schedules placement exactly once.
- Through the live rig the registered handler is the only entry: an authorized APPROVE then CONFIRM gives one `place_entry`, a redelivered CONFIRM gives no second one, a stranger's press gives none and a journaled `USER_NOT_AUTHORIZED` refusal.

## Deviations from Plan

**1. [Ordering] Tasks 2 and 3 were committed before Task 1.** The runner passes `run_sync` into `make_confirm_flow` and `on_callback`, so the two seams had to exist first. Commits: `9841becb` (Task 3), `8f02980d` (Task 2), `1eb1fd3e` (Task 1). Content unchanged from the plan.

**2. [Interpretation] Task 3 "an unauthorized press never reaches dispatch".** In `on_callback` a refused press still calls `dispatch`, because the dispatcher is what journals the refusal. With the seam that journal write also runs on the writer thread. The gate decision itself (the first `authorized_user_gate` call) runs on the loop before any dispatch, and no approval is decided; the test asserts exactly that.

**3. [Design] `callback_kwargs` carries `run_sync`** (when the flow has it) instead of the runner patching the dict; SHADOW/DEMO flows built without it get the identical key set.

No auth gates. No DECISIONS row needed from this plan beyond what 24-01 already recorded.

## Known gaps (for later plans, none block the plan goal)

- Still inline on the loop: `ConfirmFlow.handle_cancel`, the card `record_issued` / `abort_delivery` journal writes in the approved handler, `expire_due` inside `finalize_expired`, and the reply/finalize bookkeeping. The plan scoped only `handle_confirm` and `dispatch`; a CANCEL still journals on the loop. Suggest folding these into plan 24-27/24-28 or a follow-up (same `run_sync` pattern; `finalize_expired` needs the sweep split into expire and edit).
- `finalize_expired_once` has no scheduler cadence here (plan 24-27 gives it one).
- The runner's `application_factory` is zero-argument and must return an application whose token and handlers other than the ones the runner adds are already set; real `ApplicationBuilder` wiring and the `TELEGRAM_LIVE_BOT_TOKEN` read belong to plan 24-27 (not exercised: `build_application` is never called in tests).
- `build_execution_path` (plan 24-04) still builds its own `confirm_flow` without `run_sync`; 24-27 must use the runner's flow (`runner.flow`) as the single one, or the second flow is unused.
- No PostgreSQL (`*_pg.py`) tests were run (not allowed in this wave); none touch these files directly.

## Known Stubs

None.

## Threat Flags

None. T-24-47 (one handler, non-empty ids, wiring test, no `dispatch_callback` in `src/live`), T-24-48 (pending updates kept, redelivered CONFIRM places once), T-24-49 (writer-thread tests), T-24-50 (token rule logged) and T-24-SC (no dependency change) are covered.

## Self-Check: PASSED

- Files exist: src/live/telegram_runner.py, tests/test_live_telegram_runner.py, tests/test_confirm_flow_worker_thread.py, tests/test_telegram_dispatch_off_loop.py (created); confirm_flow.py and telegram_callbacks.py (modified).
- Commits present: 9841becb, 8f02980d, 1eb1fd3e.
