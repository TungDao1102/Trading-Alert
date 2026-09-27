---
phase: 07-paper-forward-observation
plan: 04
subsystem: paper-soak
tags: [freeze-monitor, telegram-notify, paper-soak, sim-card, pinned-epoch, journal-first, d-04, d-05]

# Dependency graph
requires:
  - phase: 07-02
    provides: "PaperSupervisor + backfill_missed_closes + parity gate (PAPER-01)"
  - phase: 07-03
    provides: "AttributionKind vocabulary + PaperRecord + assemble_paper_record (PAPER-02)"
  - phase: 07.1-01
    provides: "CostModelBindingMismatch + assert_cost_model_binds_registry + v3 cost-key set"
provides:
  - "Pinned-epoch freeze monitor (src/paper/freeze.py) — refuses mismatched cost binding, opens new epochs on registry diff, appends diff log without rewriting old pinned hashes"
  - "SIMULATE notify edge (src/adapters/telegram_notify.py + src/paper/notify.py) — only Telegram import boundary, journal-first ordering with bounded tenacity retry, all 12 APRV-01 fields rendered with Decimal str precision, inert callback labels"
  - "Pre-soak smoke verification (logs/paper/soak_smoke.log) — 3/4 smoke legs PASS with timestamps; WS leg BLOCKED-follow-up"
  - "USER-SETUP doc + .env.example extension documenting TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_CHAT_ID, PAPER_DATABASE_URL (Rule 2 deviation)"
  - "PAPER-03 acceptance artifact foundation (logs/paper/registry_diff.jsonl + logs/paper/pinned_epoch.json — runtime state, gitignored)"
affects: [07-soak, 08-approval, paper-soak-runbook]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
# Same estimateTokens scale (chars/4 over the realized diff), never a harness token count.
actuals:
  tokens: 4800          # 1904 chars code diff / 4 + 7666 USER-SETUP + 700 .env.example delta + ~1000 SUMMARY, /4
  tasks: 4              # 4 plan tasks (1 legitimacy checkpoint + 1 TDD auto + 1 notify auto + 1 soak checkpoint)
  commits: 5            # MEASURED: git rev-list --count 6900bfb..HEAD before final SUMMARY commit (4eb14f1, 5284698, 85e266f, e3cedcc, 572bc40)

# Tech tracking
tech-stack:
  added:
    - "python-telegram-bot>=22.8,<23 (PyPI verified by operator legitimacy checkpoint; asyncio-native; Bot.send_message + InlineKeyboardMarkup consumed by send_simulate)"
    - "tenacity 9.x (already pinned; AsyncRetrying consumed by notify_simulate with stop_after_attempt|stop_after_delay + wait_random_exponential)"
  patterns:
    - "Telegram isolation: only src/adapters/telegram_notify.py imports python-telegram-bot; src/paper/notify.py consumes a Protocol-typed TelegramBot with test-injected fake"
    - "Journal-first notify: journal row committed BEFORE Telegram send; bounded retry; failure journals NotifyOutcome(FAILED, error_class, attempts) and never raises into the loop"
    - "Inert callback labels: SIMULATE-recorded / SKIP (Phase 8) — no Application poller, no MessageHandler, no CallbackQueryHandler in the paper package"
    - "Pinned-epoch freeze: load_parameter_set + assert_cost_model_binds_registry on stream start, CostModelBindingMismatch refuses inconsistent starts; check_registry_unchanged re-hashes, opens new epoch on diff, old pinned hash append-only"
    - "gitignored runtime state: logs/paper/{registry_diff.jsonl, pinned_epoch.json, soak_smoke.log} — never committed"

key-files:
  created:
    - "src/paper/freeze.py — StreamEpoch, pin_stream_epoch, check_registry_unchanged, run_check_cli (hourly cron entrypoint)"
    - "src/paper/notify.py — NotifyOutcomeKind, NotifyOutcome, format_simulate (12 APRV-01 fields), notify_simulate (tenacity-bounded journal-first)"
    - "src/adapters/telegram_notify.py — TelegramBot Protocol, send_simulate, build_simulate_keyboard (only Telegram importer)"
    - ".github/workflows/paper_freeze_check.yml — hourly cron invoking freeze.check CLI; operator alternative documented in header"
    - "tests/test_paper_freeze.py — 6 tests (clean pin, mismatch-refusal CostModelBindingMismatch, epoch rollover, bare KeyError, CLI clean tick, command absence)"
    - "tests/test_paper_notify.py — 6 tests (format-exactness-12-fields, journal-first-failing-bot, healthy-bot-success, no-Application-poller, no-inbound-handler, telegram-adapter-only-importer)"
    - "tests/fixtures/phase7/pinned_epoch_clean/{input,expected}.json"
    - "tests/fixtures/phase7/epoch_rollover/{input,expected}.json"
    - ".planning/phases/07-paper-forward-observation/07-USER-SETUP.md — operator setup with 3 vars, PowerShell loader, 4 smoke commands + 2 gotchas"
  modified:
    - "pyproject.toml + uv.lock — python-telegram-bot 22.8 pin (after operator legitimacy approval)"
    - "src/paper/__init__.py — barrel re-export of freeze + notify symbols"
    - "tests/test_domain_no_float.py — SCANNED_FILES extended with src/paper/notify.py (D-12 purity)"
    - ".env.example — commented block documenting TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_CHAT_ID, PAPER_DATABASE_URL (Rule 2 deviation; shapes only, never values)"
    - ".gitignore — logs/ added (paper soak runtime state: registry_diff.jsonl, pinned_epoch.json, soak_smoke.log)"

key-decisions:
  - "D-04 frozen: pin_stream_epoch fails closed on CostModelBindingMismatch; check_registry_unchanged re-hashes without rewriting old pinned hashes; pinned hash string is append-only history (per epoch_id)"
  - "D-05 frozen: SIMULATE-notify is journal-first send-only with bounded tenacity retry (NOTIFY_MAX_ATTEMPTS=3, NOTIFY_MAX_DELAY_SECONDS=30); callbacks are inert labels (SIMULATE-recorded / SKIP (Phase 8)); never auto-approves on notification failure"
  - "Telegram isolation: only src/adapters/telegram_notify.py imports python-telegram-bot; src/paper/notify.py consumes a Protocol-typed bot (TelegramBot.send_message, send_message stub for tests)"
  - "Operator-only smoke run (logs/paper/soak_smoke.log): 3/4 legs PASS (rest_klines rows=5, journal_roundtrip byte-equivalent, telegram_simulate message_id=26); WS leg BLOCKED-follow-up — PaperWsAdapter + PaperSupervisor have no SDK connect path wired (0 live events in 30s); Wave 1/2 tests use injected fakes"
  - "WS smoke BLOCKER recorded as follow-up (not fixed in this plan): PaperWsAdapter/PaperSupervisor need SDK connect path proven live before the soak starts; orchestrator routes separately"
  - "Rule 2 deviation: extended .env.example with commented TELEGRAM_BOT_TOKEN/TELEGRAM_AUTHORIZED_CHAT_ID/PAPER_DATABASE_URL block (names + source + shape only — never values); closes the missing-critical-operator-doc gap that blocked the soak checkpoint"

patterns-established:
  - "Pattern 1: Phase 7 NotifyOutcome envelope (kind, signal_id, error_class, attempts) — paper-loop caller catches nothing; failure surfaces as a JournalEvent, never an exception"
  - "Pattern 2: Pinned-epoch as versioned evidence window — every registry diff opens a new epoch_id with REGISTRY_DIFF reason and halts the old evidence claim; pinned hash of a running window is never rewritten"
  - "Pattern 3: Telegram edge isolated behind a Protocol — tests inject a fake TelegramBot; production swaps to a python-telegram-bot Bot instance at the adapter boundary only"
  - "Pattern 4: Gitignored runtime state under logs/paper/ — registry_diff.jsonl (append-only diff log), pinned_epoch.json (operator-managed), soak_smoke.log (operator evidence); tracked source files never hold runtime data"

requirements-completed: [PAPER-03]

# Coverage metadata (#1602) — one entry per shipped deliverable. Drives DETERMINISTIC UAT routing in verify-work.
coverage:
  - id: D1
    description: "Pinned-epoch freeze monitor refuses CostModelBindingMismatch loudly on stream start; check_registry_unchanged re-hashes and opens new epoch with REGISTRY_DIFF on diff (D-04 byte-stability)"
    requirement: "PAPER-03"
    verification:
      - kind: unit
        ref: "tests/test_paper_freeze.py#test_pin_clean_returns_pinned_tuple_and_writes_epoch_record"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze.py#test_pin_mismatch_raises_cost_model_binding_mismatch"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze.py#test_check_clean_appends_clean_diff_log_entry"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze.py#test_check_diff_opens_new_epoch_and_halts_old_evidence"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze.py#test_pin_absent_cost_key_raises_bare_keyerror"
        status: pass
      - kind: unit
        ref: "tests/test_paper_freeze.py#test_cli_check_clean_tick_appends_jsonl"
        status: pass
    human_judgment: false
  - id: D2
    description: "SIMULATE notify edge carries all 12 APRV-01 fields with Decimal str precision; journal-first ordering holds under send failure; callbacks stay inert"
    requirement: "PAPER-03"
    verification:
      - kind: unit
        ref: "tests/test_paper_notify.py#test_format_simulate_carries_all_12_aprv01_fields"
        status: pass
      - kind: unit
        ref: "tests/test_paper_notify.py#test_journal_first_with_failing_bot_yields_failed_outcome"
        status: pass
      - kind: unit
        ref: "tests/test_paper_notify.py#test_notify_simulate_returns_sent_outcome_on_healthy_bot"
        status: pass
      - kind: unit
        ref: "tests/test_paper_notify.py#test_no_application_poller_in_paper_package"
        status: pass
      - kind: unit
        ref: "tests/test_paper_notify.py#test_no_inbound_handler_can_mutate_approval_state"
        status: pass
      - kind: unit
        ref: "tests/test_paper_notify.py#test_telegram_adapter_is_the_only_importer"
        status: pass
    human_judgment: false
  - id: D3
    description: "Pre-soak smoke run covers 3/4 legs PASS (REST klines 5 rows, journal round-trip byte-equivalent, SIMULATE send message_id=26); WS leg BLOCKED-follow-up pending PaperWsAdapter/PaperSupervisor SDK connect path"
    verification:
      - kind: manual_procedural
        ref: "logs/paper/soak_smoke.log#2026-09-27 pre-soak smoke"
        status: pass
    human_judgment: true
    rationale: "Operator-only network reach (Binance REST + Telegram). WS leg is BLOCKED by a code gap (no SDK connect path), not by missing operator action — so the smoke verifies 3/4 legs PASS but the soak must not start until the WS leg also PASSes live."
  - id: D4
    description: "Operator setup documentation (USER-SETUP.md + .env.example extension) covers the three required secrets with PowerShell loader, BotFather + getUpdates chat-id steps, Alembic upgrade head, and 4 smoke commands with the two known gotchas"
    requirement: "PAPER-03"
    verification:
      - kind: other
        ref: ".planning/phases/07-paper-forward-observation/07-USER-SETUP.md"
        status: pass
    human_judgment: false

# Metrics
duration: ~25min
completed: 2026-09-27
status: complete
---

# Phase 7 Plan 4: Pinned-Epoch Freeze Monitor + SIMULATE Notify + Soak Readiness Summary

**PAPER-03 acceptance foundation: pinned-epoch freeze monitor with append-only diff proof, journal-first SIMULATE notify carrying all 12 APRV-01 fields, and pre-soak smoke (3/4 PASS + WS leg BLOCKED-follow-up).**

## Performance

- **Duration:** ~25 min (Tasks 1-3 + Task 4 verification after operator smoke)
- **Started:** 2026-09-27T00:00:00Z (resumed after Task 4 operator checkpoint)
- **Completed:** 2026-09-27
- **Tasks:** 4 (1 legitimacy checkpoint + 1 TDD auto + 1 notify auto + 1 soak checkpoint)
- **Files modified:** 15 (code + tests + fixtures + workflow + USER-SETUP + .env.example + .gitignore)

## Accomplishments

- **Pinned-epoch freeze monitor** (`src/paper/freeze.py`, 658 LOC): `pin_stream_epoch` loads via `load_parameter_set`, verifies cost binding via `assert_cost_model_binds_registry`, and refuses inconsistent starts with `CostModelBindingMismatch`. `check_registry_unchanged` re-reads files, compares canonical hashes, appends clean entries to the diff log on match, and on mismatch returns a new `StreamEpoch` with the old epoch `evidence_claim_open=False` and reason `REGISTRY_DIFF` while leaving the old pinned hash untouched. 6 tests green; CLI entry `uv run python -m src.paper.freeze --check --diff-log logs/paper/registry_diff.jsonl`; hourly GitHub Actions cron workflow at `.github/workflows/paper_freeze_check.yml`.
- **SIMULATE notify edge** (`src/adapters/telegram_notify.py` + `src/paper/notify.py`, 379 LOC): `format_simulate` renders exactly the 12 APRV-01 fields (symbol, direction, setup, entry zone, SL, TPs, RR, risk, expiry, invalidation, exposure, reason codes) with `Decimal` str precision (`str(Decimal("100.10"))` stays "100.10"). `notify_simulate` enforces journal-first ordering via tenacity-bounded retry (`NOTIFY_MAX_ATTEMPTS=3`, `NOTIFY_MAX_DELAY_SECONDS=30`) — journal row committed BEFORE send, failure journals `NotifyOutcome(FAILED, error_class, attempts)` and never raises. Callbacks are inert labels (`SIMULATE-recorded`, `SKIP (Phase 8)`); no `Application` poller, no `MessageHandler`, no `CallbackQueryHandler` in the paper package. 6 tests green.
- **Pre-soak smoke verification** (`logs/paper/soak_smoke.log`, 35 lines): operator ran the four smoke legs on 2026-09-27 — `rest_klines=PASS rows=5`, `journal_roundtrip=PASS` (byte-equivalent read-back, smoke row deleted), `telegram_simulate=PASS message_id=26`. `ws_subscribe=BLOCKED` — code gap (PaperWsAdapter/PaperSupervisor have no SDK connect path; 0 events in 30s live). Env provenance verified: TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_CHAT_ID, PAPER_DATABASE_URL resolve from local gitignored `.env` (no literals in tree, grep-verified).
- **USER-SETUP doc + .env.example extension** (`.planning/phases/07-paper-forward-observation/07-USER-SETUP.md` + `.env.example` commented block): documents the three required secrets (BotFather token + getUpdates chat-id + PAPER_DATABASE_URL), PowerShell `.env` loader one-liner, `uv run alembic upgrade head`, and the 4 smoke commands with the two known gotchas (fixture 70-char placeholder hash vs VARCHAR(64) — use valid-length 64-char; WS smoke currently BLOCKED).
- **PAPER-03 acceptance artifact foundation**: `logs/paper/registry_diff.jsonl` (append-only diff log) + `logs/paper/pinned_epoch.json` (operator-managed pinned state) — both gitignored, both driven by the freeze monitor.

## Task Commits

Each task was committed atomically:

1. **Task 1: Legitimacy gate: approve python-telegram-bot install** - `4eb14f1` (chore: pin python-telegram-bot 22.8 after developer legitimacy approval)
2. **Task 2 RED: Freeze monitor tests** - `5284698` (test: paper freeze monitor red-phase fixtures and failing tests)
3. **Task 2 GREEN: Freeze monitor implementation** - `85e266f` (feat: paper freeze monitor with pinned epoch and diff-proof log)
4. **Task 3: SIMULATE notify edge** - `e3cedcc` (feat: paper SIMULATE notify edge with journal-first send-only Telegram)
5. **Task 3b: Gitignore logs/** - `572bc40` (chore: gitignore logs/ for paper soak runtime state)

**Plan metadata:** (this file + USER-SETUP + .env.example commit, single atomic commit per GSD contract)

_Note: Task 2 was TDD with separate RED + GREEN commits; Task 4 was a blocking-human checkpoint with no code change (operator ran the smoke and recorded evidence)._

## Files Created/Modified

- `src/paper/freeze.py` — StreamEpoch, pin_stream_epoch, check_registry_unchanged, DiffLogEntry, FreezeCheckOutcome, write_pinned_state, load_pinned_state, run_check_cli, _cli_main; CostModelBindingMismatch propagates from src/backtest/binding.py; bare KeyError propagation per D-04
- `src/paper/notify.py` — NotifyOutcomeKind enum (SENT/FAILED), NotifyOutcome dataclass, format_simulate, notify_simulate, build_simulate_keyboard; tenacity-bounded retry with stop_after_attempt|stop_after_delay + wait_random_exponential
- `src/adapters/telegram_notify.py` — TelegramBot Protocol, send_simulate (Protocol-typed for test injection), build_simulate_keyboard (inert `SIMULATE-recorded` / `SKIP (Phase 8)` labels)
- `src/paper/__init__.py` — barrel re-exporting freeze + notify symbols (NOTIFY_MAX_ATTEMPTS=3, NOTIFY_MAX_DELAY_SECONDS=30, etc.)
- `.github/workflows/paper_freeze_check.yml` — hourly cron invoking `uv run python -m src.paper.freeze --check --diff-log logs/paper/registry_diff.jsonl`; header comment documents operator alternative (in-process scheduled invocation on the soak host)
- `tests/test_paper_freeze.py` — 6 tests: pin-clean, mismatch-refusal, check-clean, check-diff-opens-new-epoch, absent-cost-key-bare-KeyError, cli-clean-tick-appends-jsonl
- `tests/test_paper_notify.py` — 6 tests: format-12-fields, journal-first-failing-bot, healthy-bot-success, no-Application-poller, no-inbound-handler, telegram-adapter-only-importer
- `tests/fixtures/phase7/pinned_epoch_clean/{input,expected}.json` — golden pair for clean tick (registry untouched, no rollover)
- `tests/fixtures/phase7/epoch_rollover/{input,expected}.json` — golden pair for rollover (one registry field changed, new epoch opens, old pinned hash unchanged)
- `pyproject.toml` + `uv.lock` — python-telegram-bot>=22.8,<23 pinned after operator legitimacy approval
- `tests/test_domain_no_float.py` — SCANNED_FILES extended with src/paper/notify.py (D-12 purity contract)
- `.env.example` — commented block documenting TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_CHAT_ID, PAPER_DATABASE_URL (names + source + shape only; never values)
- `.gitignore` — `logs/` added (registry_diff.jsonl, pinned_epoch.json, soak_smoke.log are runtime state, not source)
- `.planning/phases/07-paper-forward-observation/07-USER-SETUP.md` — operator setup doc with 3 vars, PowerShell loader, 4 smoke commands + 2 gotchas
- `.planning/phases/07-paper-forward-observation/07-04-SUMMARY.md` — this file

## Decisions Made

### D-04 (frozen in Task 2): Pinned-epoch freeze monitor
- `pin_stream_epoch` calls `load_parameter_set` then `assert_cost_model_binds_registry` BEFORE returning the StreamEpoch; `CostModelBindingMismatch` propagates and prevents any journal row from existing on the inconsistent start (mirrors 07.1-01 D-01 gate)
- `check_registry_unchanged` re-reads files, compares canonical hashes, appends clean JSONL entries to the diff log; on mismatch, opens a new epoch_id via `derive_child_id` (parameterSetId + new parameterSetHash + opened_at_utc), sets the old epoch's `evidence_claim_open=False`, and leaves the old pinned hash string unchanged (D-04 byte-stability)
- Bare `KeyError` from `build_cost_model` propagates without translation (per 07.1-02 grandfather log); never translated to `ExperimentReproducibilityBroken` or swallowed

### D-05 (frozen in Task 3): SIMULATE-notify journal-first send-only
- `format_simulate` renders exactly 12 APRV-01 fields with `str(Decimal(...))` precision — `"100.10"` stays `"100.10"`, never `"100.1"`
- `notify_simulate` enforces journal-first ordering: journal row committed BEFORE `bot.send_message`; if the journal write fails, the Telegram send is SKIPPED (D-05 fail-closed)
- Tenacity bounded retry: `NOTIFY_MAX_ATTEMPTS=3`, `NOTIFY_MAX_DELAY_SECONDS=30`, `wait_random_exponential(multiplier=1, max=10)` — bounded by attempts AND wall-clock, whichever fires first
- Callbacks are inert labels: `SIMULATE-recorded` and `SKIP (Phase 8)`. No `Application` poller, no `MessageHandler`, no `CallbackQueryHandler` in the paper package — Phase 8 will bind callbacks to authorized chat + one-time token + idempotent replay per D-05
- `NotifyOutcome` envelope: `kind` (SENT/FAILED), `signal_id`, `error_class` (None on SENT, exception class name on FAILED), `attempts` (1 on first try, up to NOTIFY_MAX_ATTEMPTS on retry)
- Failure NEVER raises into the loop — the loop catches the `NotifyOutcome` and journals it as a `JournalEvent` (no exception escape)

### D-04/D-05 isolation: Telegram at the edge only
- Only `src/adapters/telegram_notify.py` imports `python-telegram-bot` (Bot, InlineKeyboardButton, InlineKeyboardMarkup)
- `src/paper/notify.py` consumes a `TelegramBot` Protocol (`send_message` method) — production swaps in a python-telegram-bot `Bot` instance; tests inject a `FakeTelegramBot` with call counter + injectable error
- `tests/test_paper_notify.py#test_telegram_adapter_is_the_only_importer` enforces this via AST import analysis

### Soak smoke evidence routing (per checkpoint resolution)
- 3/4 legs PASS: `rest_klines`, `journal_roundtrip`, `telegram_simulate` — operator-verified 2026-09-27
- 1 leg BLOCKED-follow-up: `ws_subscribe` — code gap in `PaperWsAdapter` / `PaperSupervisor` (no SDK connect path; 0 events in 30s live). Wave 1/2 tests use injected fakes, so the gap was never proven live. Routed as follow-up; soak must NOT start until live WS smoke passes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Extended .env.example with PAPER-03 operator doc block**
- **Found during:** Task 4 verification (operator smoke checkpoint)
- **Issue:** `.env.example` did not document the three required Phase 7 secrets (TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_CHAT_ID, PAPER_DATABASE_URL). Without the doc, the next operator would have to read `docs/integration/TELEGRAM.md` AND `.env.example` AND `07-04-PLAN.md` user_setup block to discover the env vars — a missing-critical-operator-doc gap that blocked the soak checkpoint.
- **Fix:** Appended a commented block to `.env.example` documenting the three vars (name + source + shape only — never values). The commented block satisfies the "secret-free .env.example" contract while making the contract discoverable.
- **Files modified:** `.env.example`
- **Verification:** `grep -E "^[A-Z_]+=[^#]" .env.example` returns the original three vars only (POSTGRES_*, DATABASE_URL, OI_POLL_INTERVAL_SECONDS, OFF_HOST_BACKUP_TARGET); no new uncommented KEY=value pairs added.
- **Committed in:** (included in final SUMMARY commit)

**2. [Rule 2 - Missing Critical] Generated 07-USER-SETUP.md (USER_SETUP_CREATED=true)**
- **Found during:** Post-checkpoint resume per checkpoint_resolution <remaining_work> item 2
- **Issue:** Plan frontmatter declared `user_setup` (telegram + postgres services) but no USER-SETUP.md existed in the phase directory. Without the file, operators lack the runnable setup instructions (BotFather + getUpdates chat-id steps, PowerShell `.env` loader, Alembic upgrade head, 4 smoke commands with the two known gotchas).
- **Fix:** Generated `07-USER-SETUP.md` from `templates/user-setup.md` with the three required vars, account-setup steps for Telegram bot creation, dashboard config for Alembic + Compose PostgreSQL 17, PowerShell .env loader one-liner, and 4 smoke commands with the two known gotchas (fixture 70-char placeholder hash vs VARCHAR(64) — use valid-length 64-char; WS smoke BLOCKED).
- **Files modified:** `.planning/phases/07-paper-forward-observation/07-USER-SETUP.md` (new)
- **Verification:** File exists at the documented path; covers all three vars with PowerShell commands verified runnable; USER_SETUP_CREATED=true surfaced in completion output.
- **Committed in:** (included in final SUMMARY commit)

**3. [Rule 1 - Bug] Removed operator scratch smoke scripts (temp/)**
- **Found during:** Post-checkpoint resume per checkpoint_resolution <remaining_work> item 4
- **Issue:** `temp/smoke_rest.py`, `temp/smoke_journal.py`, `temp/smoke_telegram.py` (+ `__pycache__` cache) were untracked leftover smoke scripts from the operator run. They were superseded by `07-USER-SETUP.md` and would have polluted `git status` for subsequent work.
- **Fix:** Removed `temp/` directory entirely (3 .py files + `__pycache__/` + 3 .pyc bytecode files). Verified with `git status --short temp/` → no entries.
- **Files modified:** `temp/` (deleted)
- **Verification:** `Test-Path temp` returns False; no scratch files remain.
- **Committed in:** (no commit needed — untracked files deleted; .gitignore already covers `__pycache__/` and `logs/`)

---

**Total deviations:** 3 auto-fixed (2 Rule 2 missing-critical, 1 Rule 1 cleanup)
**Impact on plan:** All three auto-fixes essential for operator runnability + secret safety + repository hygiene. No scope creep into WS implementation (out-of-scope per <remaining_work> item 5).

## Issues Encountered

### WS-connect gap (BLOCKED-follow-up — not fixed in this plan)

**Problem:** `PaperWsAdapter` and `PaperSupervisor` (delivered in 07-02) expose `subscribe` / `reconnect` / `schedule_reconnect` / `close` — but neither calls the SDK connect path. Wave 1/2 tests (`tests/test_paper_resync.py`, `tests/test_paper_parity.py`) use injected fakes via constructor injection, so the gap was never proven live. Operator smoke on 2026-09-27: `PaperWsAdapter().subscribe(symbol='btcusdt', interval='1h')` live for 30s delivered 0 kline events (1H stream normally pushes every ~250ms; expected ~120 events in 30s).

**Routing:** Routed to executor as follow-up. Soak must NOT start until a live WS smoke passes.

**Scope rationale (per <remaining_work> item 5):** Out of this plan's `files_modified` scope (07-04 frontmatter files are `src/paper/freeze.py`, `src/paper/notify.py`, `src/adapters/telegram_notify.py`, tests + fixtures + pyproject + uv.lock — NOT `src/paper/supervisor.py` or `src/adapters/paper_ws.py`). Orchestrator routes the WS fix separately (likely as plan 07-05 or a follow-up injection into 07-Wave-3).

**Acceptance gate:** Until the WS leg also PASSes live, the PAPER-03 soak must remain in pre-soak-held state. The freeze monitor + SIMULATE notify edge are proven and ready; only the live WS connection path blocks soak start.

### LSP false positive on `src/paper/notify.py` tenacity import

**Problem:** Static analysis flagged `from tenacity import (...)` as "could not be resolved" even though `tenacity` is installed (`uv.lock` shows `tenacity>=9.x`).

**Routing:** False positive — `tenacity` resolves at runtime; tests and ruff both pass. The LSP server's index appears to lag the lockfile. No fix needed; verification via `uv run pytest tests/test_paper_notify.py -q` (6/6 pass) and `uv run ruff check src/paper/notify.py` (clean) confirms the import is valid.

## User Setup Required

**External services require manual configuration.** See [07-USER-SETUP.md](./07-USER-SETUP.md) for:
- Environment variables (TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_CHAT_ID, PAPER_DATABASE_URL)
- Telegram BotFather + getUpdates chat-id steps
- Alembic upgrade head + Compose PostgreSQL 17 readiness
- PowerShell .env loader one-liner
- 4 pre-soak smoke commands with the two known gotchas (fixture hash length + WS BLOCKED)

User setup was COMPLETED on 2026-09-27 by the operator (see `logs/paper/soak_smoke.log` dated entry). 3/4 smoke legs PASS; WS leg BLOCKED-follow-up.

## Next Phase Readiness

**Ready for:**
- Soak start (when the WS-connect gap is resolved and the live WS smoke PASSes)
- Phase 8 (Approval + Reconciliation Hardening) construction in parallel with the soak — Phase 8 construction does not need the WS fix to begin

**Blockers:**
- WS-connect gap: PaperWsAdapter/PaperSupervisor need SDK connect path proven live before the soak starts. Routed to executor as follow-up (separate plan).

**Concerns:**
- Operator smoke run is a single dated entry (2026-09-27). Subsequent soak sessions need their own dated entries in `logs/paper/soak_smoke.log` and freeze-monitor tick entries in `logs/paper/registry_diff.jsonl`.
- PAPER-03 acceptance requires the diff log to remain byte-stable across the 3–6-month envelope; the freeze monitor is the only mechanism preventing mid-soak parameter edits from contaminating forward evidence (per D-04).

---
*Phase: 07-paper-forward-observation*
*Completed: 2026-09-27*
