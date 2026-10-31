---
phase: 24-live-runtime-composition-demo
plan: 23
subsystem: live-operator
tags: [telegram, operator-commands, safe-mode, exit_safe_mode, allow-list, two-step-confirm, R-4, OQ-5, D-28]
requires: [24-13, 24-17, 24-20]
provides:
  - "src/live/operator.py: OperatorCommands (status, disable_entries, safemode_exit, close, confirm, handlers())"
  - "tests/test_live_safe_mode_drill.py: the fake-level SAFE_MODE drill and the real-store ExitReadiness contract"
affects: [24-27]
key-files:
  created:
    - src/live/operator.py
    - tests/test_live_operator_commands.py
    - tests/test_live_safe_mode_drill.py
  modified:
    - tests/test_safe_mode_exit_operator.py
requirements: [EXEC-02, OPS-03]
status: complete
commits: 3
plan_head_before: 17307cd08288d97d6bc482e258b1380955ec41f5
plan_head_after: a102efde6118868de957df715c0cf1858f72361c
actuals:
  tokens: 42000
  tasks: 3
  commits: 3
---

# Phase 24 Plan 23: Operator commands over Telegram and the SAFE_MODE drill Summary

`OperatorCommands` gives the owner `/status`, `/disable_entries`, `/safemode_exit` and `/close SYMBOL` (two-step `/confirm <token>`), behind the same chat, private-chat and user-id allow-list gate as `on_callback`; `/safemode_exit` runs `SafeModeController.exit_safe_mode` in process with closures over the live coordinator, intent store, REST gate and stream state, and the drill proves SAFE_MODE blocks a CONFIRM, a failing exit row keeps it, and a satisfied exit lets exactly one entry through.

## What was built

- `src/live/operator.py`
  - `OperatorCommands(*, authorized_chat_id, authorized_user_ids, controller, enablement, coordinator, intent_store, pending_actions, gate, stream_state, journal, clock, reply, ttl_seconds=CONFIRM_TTL_SECONDS_DEFAULT)`. Handlers are `async (update, context)` returning `OperatorResult(ok, code)`; `handlers()` maps the five command names (no slash) to them for plan 24-27's `CommandHandler` registration. They read only `update.update_id`, `update.effective_chat`, `update.effective_user` and `context.args`.
  - Gate (T-24-69, D-28): `authorized_chat_gate` then `authorized_user_gate` (user id present, chat type exactly "private", id in the allow-list), the same functions `on_callback` uses; the allow-list is validated at construction with `_validate_authorized_user_ids` (empty, plain set, bool or str member raise). A refusal changes nothing, writes `OPERATOR_COMMAND_REJECTED` (command, fixed reason code, user id, chat id; never message text) and answers "Rejected".
  - `/status`: read only. Mode (and the SAFE_MODE reason from the controller), entries ENABLED/DISABLED, REST gate restriction and recovery status, stream state, protections open of tracked. An unreadable gate or stream is reported by class name.
  - `/disable_entries`: no confirm; `enablement.disable(operator_id="tg:<user id>")` (flag first, journal after, D-16); idempotent (`ALREADY_DISABLED`, no second enablement row).
  - `/safemode_exit` then `/confirm`: refused outright when not in SAFE_MODE (no token). The confirm calls `controller.exit_safe_mode` with `local_intent_fn = derive_local_intent(coordinator.protections(), intent_store.list_unresolved_intents())`, `readiness = build_exit_readiness(unresolved_intents_fn, protections_fn, open_pending_fn=pending_actions.list_open, restore_complete_fn=lambda: coordinator.restore_complete)`, `gate_status` = ONE `gate.restriction()` read plus `gate.recovery_status().value`, `stream_state` = the stream state's value, `now_utc` = the injected clock. A refusal is answered with the controller's own row codes (for example `STREAM_NOT_LIVE`); an exception from the EXIT journal row or the state save is answered by class name and leaves SAFE_MODE.
  - `/close SYMBOL` then `/confirm`: the symbol must be 1-20 upper-case ASCII letters or digits; exactly one open plan (state not FLAT / ENTRY_ENDED_NO_FILL) must carry it, else `UNKNOWN_SYMBOL`, `NOTHING_TO_CLOSE` or `AMBIGUOUS_SYMBOL` and no token. After the confirm it calls `operator_close_position(coordinator=..., plan_hash=..., operator_id="tg:<id>")` once (the coordinator's own close flow; the quantity is read by the closer). Allowed in SAFE_MODE (it reduces risk).
  - Confirm token: `issue_one_time_token()`, only its SHA-256 kept in memory, bound to the asking user, `CONFIRM_TTL_SECONDS_DEFAULT` (60 s), single use (a used token also removes every other waiting ask of the same user, action and plan), bounded to 8 waiting asks, expired entries purged on each issue. An unknown, expired, replayed or other-user confirm does nothing and answers one neutral text. An other-user confirm does not burn the token.
  - Audit (T-24-71): every accepted command writes an `OPERATOR_COMMAND` row with the user id and a fixed code; the controllers' own rows carry `tg:<user id>` as operator id. A failing journal or reply is logged by class name and never undoes or breaks a command.
  - No placement call, leverage or margin command exists in the module (a source test and the live AST guards pin it).
- `tests/test_live_safe_mode_drill.py`: the drill on the real live rig (desk, confirm flow, service, manager, controller, coordinator; fakes only at the edges), a per-row refusal test (gate not open, gate not restored, one restriction read per attempt), an open-pending-action refusal, the failed-state-save case (separate durable controller: EXIT row written, save raises, SAFE_MODE stays, `/status` says SAFE_MODE, reply names the class and not the text), and the PostgreSQL contract test of `ExitReadiness` (see Verification).
- `tests/test_live_operator_commands.py`: 47 cases: the gate for all five commands times four refusals (unknown user, another chat, group chat, no user) with reason codes, constructor refusals, `/status` read-only and degraded, `/disable_entries` (idempotence, blocks the next CONFIRM, journal down), `/close` (confirm once, replay, expiry at 61 s, last-second confirm at 59 s, other-user, wrong token, bad usage, finished plan, ambiguous symbol, SAFE_MODE, second ask replaces the first), token hashing and bounds, and the "no placement / leverage / margin" source and behaviour tests.

## Verification run

- `uv run pytest -m "not docker"` (TEST_DATABASE_URL unset): test_live_operator_commands, test_live_safe_mode_drill, test_safe_mode_exit_operator, test_telegram_authorization, test_live_ast_guards all pass (the real-store case skips); test_no_unratified_defaults, test_agents_md, test_phase20_gate, test_phase23_gate, test_live_tracer pass.
- Scoped `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src/live` (20 files) clean. `git diff -- pyproject.toml uv.lock` empty. `git grep -n -e place_entry -e execute_approved_plan -- src/live/operator.py` prints nothing.

## Deviations from Plan

**1. [Interface] Constructor differs from the sketch.** Added `pending_actions` (the readiness list needs `PendingActionStore.list_open`; the sketch had no source for it) and `ttl_seconds`; dropped `adapter` (the controller already owns the three exchange reads and `operator_close_position` has no adapter call). Plan 24-27 passes the coordinator, the pending action store, the REST gate (`RestRateLimitGate` has `restriction()` and `recovery_status()`), and `lambda: supervisor.state`.

**2. [Rule 3 - Blocking] `tests/test_safe_mode_exit_operator.py::test_only_the_operator_path_calls_exit`** pinned the callers of `exit_safe_mode` to `{"src/ops/drills.py"}`. The plan's own verify command runs that file and the plan adds a caller, so the set is now `{"src/ops/drills.py", "src/live/operator.py"}` (CRLF file, edited bytes-aware; 3 insertions, 2 deletions). Not in the plan's file list.

**3. [Test design] The drill's last CONFIRM uses a second signal.** A consumed approval is never re-sent (a replayed CONFIRM places nothing, as `tests/test_live_tracer.py` pins), and the rig issues one request per signal. The drill therefore blocks the first approval's CONFIRM in SAFE_MODE and, after the exit, approves and confirms a second signal (`make_shadow_signal(2)`, `rig.inputs.signal` pointed at it) to prove one entry is placed. No rig file was edited.

**4. [Test design] The failed-state-save case uses a standalone durable controller** (the rig's controller has no state store) over the rig's fake exchange, coordinator and intents.

**5. Real-store test executed once by mistake.** `TEST_DATABASE_URL` was set in this shell. The instruction for this wave is to run no PostgreSQL test; I ran `tests/test_live_safe_mode_drill.py` (twice, the second time `-k real_stores`) before noticing, and the real-store case passed on the throwaway clone database the fixtures create and drop. Every later run used `env -u TEST_DATABASE_URL`. The orchestrator should treat the Pg case as run once, outside the wave rule, and re-run it in its own gate (`TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_live_safe_mode_drill.py`).

Otherwise the plan executed as written.

## Items for 24-27 (hand-off)

1. Build `OperatorCommands` with the live objects: `controller` = the durable `SafeModeController`, `enablement`, `coordinator`, `intent_store`, `pending_actions` = `PgPendingActionStore`, `gate` = `ExchangeBundle.gate`, `stream_state` = `lambda: supervisor.state` (a `StreamState` or its string; `.value` is taken), the shared `journal`, the clock, and `reply` = the runner's text sender (`async (chat_id, text)`).
2. Register on the live `Application`: `for name, fn in ops.handlers().items(): app.add_handler(CommandHandler(name, fn))`. `LiveTelegramRunner` today registers exactly one `CallbackQueryHandler` (T-24-47) and builds its own application through a zero-argument factory; the factory (or a runner hook) must add these `CommandHandler`s and the runner's `allowed_updates=["callback_query"]` must become `["callback_query", "message"]`, otherwise command messages never arrive. That is a change to 24-17's file, so it belongs to 24-27 or a follow-up.
3. The confirm token travels as text: `/confirm <token>` (43 characters, `secrets.token_urlsafe(32)`). Telegram clients copy it from the reply; no callback button is used so the single-handler guarantee of the runner holds.
4. The handlers call the coordinator, the intent store and the pending store synchronously on the event loop (as the reconcile loop does, 24-20 deferred item 3); the command rate is human, so nothing moves behind the `StoreExecutor` here.

## Items for 24-DEFERRED / owner

1. D085 owner wish (leverage and margin-type commands) stays deferred; nothing is built.
2. Pending confirmations are memory only: a restart forgets them (safe direction, documented in the module).
3. No command rate limit; only allow-listed users in the private chat reach the handlers.
4. A DECISIONS row is not required by this plan (no closed contract changed). If the owner wants the Q7 command set pinned in `docs/DECISIONS.md`, D091 is the next free id; the RUNBOOK (section on SAFE_MODE exit) should name `/safemode_exit` and `/confirm` once 24-27 registers them (docs edit not in this plan's files).

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-24-69 (gate and two-step confirm, tests), T-24-70 (the controller's rows decide; refusal tests per row), T-24-71 (user id on every row), T-24-72 (single-use token with TTL, replay / expiry / other-user tests) and T-24-SC (`pyproject.toml`, `uv.lock` unchanged) are covered.

## Task Commits

1. Task 1 (operator module, drill, caller-set guard): `c25f9082`
2. Task 2 (command gate, status, disable, close tests): `6b2115a7`
3. Task 3 (ExitReadiness against the real stores): `a102efde`

## Self-Check: PASSED

- FOUND: src/live/operator.py, tests/test_live_operator_commands.py, tests/test_live_safe_mode_drill.py, tests/test_safe_mode_exit_operator.py.
- FOUND commits c25f9082, 6b2115a7, a102efde (ancestors of HEAD).
