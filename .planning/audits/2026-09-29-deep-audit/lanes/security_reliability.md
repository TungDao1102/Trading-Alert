# Lane 7: security_reliability

Stage C code lane. Code is judged against the corrected rules in `lanes/docs_trading_soundness.md` ("Corrected Rules for Code Audit"), the exchange facts in `lanes/docs_exchange_facts.md`, and the planning-lane verdicts. Prior findings are cited and not re-reported as new.

## Scope

- **Secrets:**
  - `.env.example`, `.gitignore`, `docker-compose.yml`, `Dockerfile`
  - DB-URL handling: `src/db/models.py` `make_engine`, `src/db/alembic/env.py`, `src/data/collector.py` `_resolve_database_url`, `src/ops/backup.py` `_prod_pg_dump_runner`
  - Logging and exception-text sinks across `src/`
  - A git-history scan for committed credentials
- **Auth:**
  - Telegram callback intake (`src/adapters/telegram_callbacks.py`, `telegram_notify.py`)
  - Approval tokens, binding and replay (`src/approval/*.py`)
  - Webhook surface (none exists)
- **Fail-closed on the order path:**
  - `src/execution/manager.py`: every except, None and timeout branch, `execute_approved_plan`, `_place_entry_no_blind_retry`, `_place_protective_leg`, `attach_protectives_to_fill`, `expire_pending_entry`, `cancel_untriggered_protectives`, `emergency_manual_close`
  - `src/execution/enablement.py`
  - `src/reconcile/safe_mode.py`, `compare.py`, `sweeper.py`
  - Adapter error mapping in `src/adapters/binance_usdm.py`
- **Clock and staleness:**
  - SDK timestamping (`binance_common/utils.py` in `.venv`, read-only)
  - `src/paper/loop.py` `check_feed_freshness`
  - `src/ops/health.py`
- **Ops:**
  - `src/ops/backup.py`, `src/ops/health.py`, `scripts/backup-drill.ps1`
  - `docs/operations/RUNBOOK.md`, `SECURITY_AND_OPERATIONS.md`, `docs/integration/TELEGRAM.md`
  - Dockerfile and compose
- **Dependencies:** `pyproject.toml` vs `uv.lock` (all 60 locked packages listed).
- **Restart/recovery:**
  - Crash between entry acknowledgement and SL acknowledgement
  - Restart with open exposure
  - Persistence of SAFE_MODE and enablement state

Probes live in `tmp/security_reliability/`:
- `probe_compare.py`
- `probe_journal_first.py`
- inline one-liners for `make_engine` and the client-ID format

## Coverage

| File | Level | Note |
|---|---|---|
| src/adapters/telegram_callbacks.py | DEEP_READ | full; chat gate, dispatch, on_callback, build_application |
| src/adapters/telegram_notify.py | NORMAL_READ | send path, keyboards, callback_data limits |
| src/approval/tokens.py | DEEP_READ | entropy (token_urlsafe(32)), sha256, compare_digest |
| src/approval/binding.py | DEEP_READ | gate order, token gate |
| src/approval/replay.py | DEEP_READ | in-process per-token lock, transition |
| src/approval/mapping.py | DEEP_READ | deterministic short id |
| src/execution/manager.py | DEEP_READ | all 1350 lines; fail-closed branches |
| src/execution/enablement.py | DEEP_READ | enable/disable journal-first |
| src/execution/order_ids.py | NORMAL_READ | probe: 36-char IDs match the Binance regex |
| src/reconcile/compare.py | DEEP_READ | full, plus probe |
| src/reconcile/safe_mode.py | DEEP_READ | enter/guard/exit |
| src/reconcile/sweeper.py | DEEP_READ | cancel-only path, failure journaling |
| src/adapters/binance_usdm.py | NORMAL_READ | L82-150, 517-531, 660-725, 843-1260 (retry policy, error mapping, placement) |
| src/ops/backup.py | DEEP_READ | runner, CLI, drill |
| src/ops/health.py | NORMAL_READ | probe semantics, Telegram probe redaction |
| src/ops/drills.py | METADATA_ONLY | covered by F-127(b) |
| src/data/collector.py | NORMAL_READ | DB URL resolution, main loop, healthcheck |
| src/db/models.py | NORMAL_READ | make_engine (L439-470) |
| src/db/alembic/env.py | DEEP_READ | |
| src/paper/loop.py | NORMAL_READ | staleness gate L160-300 |
| src/paper/supervisor.py | NORMAL_READ | reconnect retry, handle close |
| src/paper/notify.py | METADATA_ONLY | grep of log.exception sinks |
| src/execution/gates.py | METADATA_ONLY | covered by F-127(c) |
| .env.example | DEEP_READ | |
| .gitignore | DEEP_READ | |
| Dockerfile | DEEP_READ | |
| docker-compose.yml | DEEP_READ | |
| pyproject.toml | DEEP_READ | |
| uv.lock | NORMAL_READ | parsed with tomllib; all package versions listed |
| scripts/backup-drill.ps1 | DEEP_READ | |
| docs/operations/RUNBOOK.md | DEEP_READ | |
| docs/operations/SECURITY_AND_OPERATIONS.md | DEEP_READ | |
| docs/integration/TELEGRAM.md | DEEP_READ | |
| .planning/phases/08-*/08-REVIEW.md | NORMAL_READ | CR-03, WR-10..WR-17 (prior compare findings) |
| .planning/phases/08-*/08-CONTEXT.md | METADATA_ONLY | grep D-01..D-03 |
| .planning/phases/09-*/09-REVIEW.md, 09-REVIEW-FIX.md | METADATA_ONLY | grep for -2013 / not-found mapping |
| .venv binance_common/utils.py, errors.py (not repo) | NORMAL_READ | error message construction, timestamp source |
| .venv binance_sdk_...usds_futures/rest_api/rest_api.py (not repo) | METADATA_ONLY | query_algo_order docstring |
| tests/test_execution_manager.py | METADATA_ONLY | fake algo probe (not-found is simulated) |
| git history (snapshot) | METADATA_ONLY | secret-pattern scan over `git log --all -p` |

## Verified Safe Areas

- **Approval token entropy and comparison (INV-048 area).**
  - `src/approval/tokens.py:27` uses `secrets.token_urlsafe(32)` (256-bit).
  - `:55` compares with `hmac.compare_digest` over sha256 hex, and `:52` length-checks the expected hash.
  - Correct as a primitive. Its usefulness is undermined by F-127(d) (KNOWN), not by the primitive.
- **Authorized-chat gate runs before any state lookup.**
  - `telegram_callbacks.py:653-672` (on_callback) and `:306-329` (dispatch) check the chat id before the binding resolver or the mapping lookup.
  - An unauthorized chat receives only "Rejected" (`:670`), with no reason code.
  - Malformed `callback_data` raises before any state change (`:640`).
- **No webhook surface exists.**
  - There is no FastAPI/HTTP server in `src/` (grep for FastAPI/uvicorn: none).
  - So there is no unauthenticated inbound endpoint and no HMAC to get wrong. F-052 (TradingView HMAC impossible) remains a doc issue only.
- **No committed secrets.**
  - `git log --all -p` scan for bot-token, DB-URL-with-password, API-key and PEM patterns found only placeholders and test fixtures: `change_me_in_local_env_only`, `placeholder`, `s3cr3t-pw`/`hunter2` in `tests/test_execution_secret_posture.py`, `USER:PASS`.
  - The only `.env*` file ever added is `.env.example`.
  - `.env` is gitignored.
- **Telegram token is not logged.**
  - `check_telegram_delivery` records only the exception type (`health.py:500-520`).
  - `build_application` never logs the token.
  - No `logging.basicConfig` is configured, so the httpx INFO request lines (which would contain `bot<TOKEN>` URLs) are not emitted by default. See Open Question 3.
- **Placement is never blind-retried (EXECUTION_SPEC §10).**
  - `binance_usdm.py:112-126` and `:1060-1075` make a single attempt, and the SDK never retries POST.
  - `manager.py:183-201` retries only after a definitive `found is False` probe; any probe exception becomes `ENTRY_STATE_UNKNOWN` → SAFE_MODE.
  - This is fail-closed, but see F-710.
- **Unknown position mode means no order.**
  - `manager.py:496-502`: a `get_position_mode` exception → `UNCERTAIN_ACCOUNT_STATE`.
  - `resolve_position_mode` rejects non-bool values.
- **An unconfirmed protective leg is never assumed protected.**
  - Allow-list `{"NEW"}` (`manager.py:688`).
  - Adapter exceptions and unknown probe results → unconfirmed → SAFE_MODE (`:741-763`).
- **Live-5 scope guard** runs before any adapter call on every live entry point (`manager.py:56`, called at `:457`, `:867`, `:1084`, `:1164`, `:1290`).
- **Client IDs.**
  - Probe: `x-…EN` and `xa-…SL/T1/T2` are exactly 36 chars and match `^[\.A-Z\:/a-z0-9_-]{1,36}$`.
  - Derived from 128 bits of `plan_hash`, so collision risk is negligible.
- **Enablement defaults.**
  - `LiveEnablementController._disabled = True` (`enablement.py:101`), and the flag is in memory, so a restart returns to LIVE_ORDERS_DISABLED (a safe default).
  - `enable()` refuses a missing or failing health verdict and an INSUFFICIENT_EDGE kill gate. Its weakness (negative-only) is KNOWN F-953.
- **Dockerfile runs as non-root** (`useradd appuser`, `USER appuser`) and installs with `uv sync --frozen --no-dev` from the lockfile.
- **Dependency hygiene (INV-117).**
  - All `pyproject.toml` ranges are satisfied by `uv.lock`: binance-sdk-derivatives-trading-usds-futures 17.4.0, sqlalchemy 2.0.54, polars 1.44.2, pydantic 2.13.5, python-telegram-bot 22.8, httpx 0.28.1, psycopg 3.3.6, alembic 1.20.0, duckdb 1.5.5.
  - No archived `binance-connector` / `binance-futures-connector`, and no pre-release lines.
  - h11 0.16.0 is at or above the version that fixed the 2025 request-smuggling CVE.
  - Known-vulnerability status of the other versions is UNVERIFIED (offline; no advisory DB).
- **Backup refuses a silent empty dump.**
  - `backup.py:467-471` refuses when no DB URL is set, and `check=True` makes pg_dump failures loud.
  - `:185-190` refuses when every parquet root is missing.

## Findings

### F-701: Reconciliation compare cannot see a doubled or reversed position, unknown exchange orders, or an SL-less position that has a TP
- **Severity:** HIGH
- **Confidence:** CONFIRMED (probe)
- **Classification:** DEFECT
- **Category:** reliability / fail-closed
- **Component:** reconcile
- **File:** `src/reconcile/compare.py`
- **Lines:** 228-233, 283-406, 453-468
- **Invariant:** INV-093 (unknown exchange orders flagged; any divergence → SAFE_MODE), INV-092, INV-075. Corrected rule 27 (unexplained position deltas → EXTERNAL; unexpected increase → SAFE_MODE).
- **Phase/commit:** Phase 8 (08-03) plus the 08-REVIEW-FIX CR-03 fix.
- **Known-prior:**
  - Partly related to 08-REVIEW CR-03 (naked position) and WR-13 (any-protective masking). Neither covers quantity or sign, or unknown exchange orders.
  - The consequence compounds F-126 / F-951 (a duplicate entry would go undetected).
- **Evidence:**
  - `truth_normal_orders` and `truth_algo_orders` are used only as lookup dicts (`:228-233`). No pass iterates the exchange orders to find ones missing from local intent.
  - Pass 3 (`:453-468`) checks only that the key `(symbol, position_side)` is present: `if key not in local_position_keys:`. `position_amt` magnitude and sign are never compared.
  - Pass 1b (`:360-406`) accepts any protective role (`_is_protective_role` = SL, TP1 or TP2) as protection.
  - `probe_compare.py` output, with the local position BTCUSDT BOTH 0.010 and a local SL present on the exchange:
    ```
    qty_doubled: agreement=True kinds=[]                (exchange 0.020)
    sign_flipped: agreement=True kinds=[]               (exchange -0.010)
    unknown_exchange_order: agreement=True kinds=[]     (extra resting entry xe-dup)
    unknown_exchange_algo: agreement=True kinds=[]      (extra algo on ETHUSDT)
    tp_only_no_sl: agreement=True kinds=[]              (only TP1, no SL anywhere)
    empty_local_unknown_entry: agreement=True kinds=[]  (exit_safe_mode default [] intent vs a resting exchange entry)
    ```
- **Expected:**
  - Any exchange normal or algo order not in local intent → divergence (unknown order).
  - Any position amount or sign different from local intent → divergence (EXTERNAL / unexpected increase → SAFE_MODE).
  - A position without an SL specifically (not just any TP) → ENTRY_WITHOUT_PROTECTIVE.
- **Actual:** All six cases report `agreement=True`.
- **Reproduction:** `PYTHONPATH=<snapshot> python -B tmp/security_reliability/probe_compare.py`
- **Impact:**
  - The reconciler is the last safety net and also gates SAFE_MODE exit (`safe_mode.py:291-300`).
  - A duplicate fill from an at-least-once replay (F-126), a manual or foreign order, a stray algo order, an ADL or liquidation that flips or reduces size, or a position whose SL was lost while a TP survived all read as clean.
  - SAFE_MODE can be exited automatically in those states (F-711).
- **Why tests miss it:** The fixtures model only the planned divergence kinds. No test injects an exchange-only order or a quantity/sign mismatch.
- **Remediation:**
  - Add a reverse pass over the truth normal and algo orders, flagging UNKNOWN_EXCHANGE_ORDER for any ID not in local intent. Scope it to the project's `x-`/`xa-` prefixes plus "any other order on a live-5 symbol".
  - Compare signed `position_amt` per `(symbol, side)` (EXTERNAL_DELTA / UNEXPECTED_INCREASE).
  - Require a STOP_LOSS role (present on the exchange) for every non-zero position.

### F-702: Journal-first ordering lets a DB/journal outage block every risk-reducing action, including the kill switch and emergency close
- **Severity:** HIGH
- **Confidence:** CONFIRMED (probe)
- **Classification:** DEFECT
- **Category:** fail-closed / reliability
- **Component:** execution, reconcile, enablement
- **File:** `src/execution/manager.py`
- **Lines:** 561-584, 1046-1130, 1132-1210, 1230-1330. Also `src/execution/enablement.py:221-245` and `src/reconcile/safe_mode.py:176-212`.
- **Invariant:** INV-074, INV-075, INV-091. RUNBOOK §9 ("DB failure → block new orders, preserve protection"). Corrected rule 24 (reduce-only/protective actions always allowed).
- **Phase/commit:** Phases 8-9 (D-05 "journal-first").
- **Known-prior:** None. F-952 covers "no re-placement"; this is a different mechanism.
- **Evidence:**
  - `expire_pending_entry` calls `journal.record(pre_cancel)` (`:1092`) before `adapter.cancel_normal_order` (`:1104`). A raising journal means the cancel is never sent.
  - `cancel_untriggered_protectives` has the same pattern per leg (journal `:1172`, cancel `:1184`).
  - `LiveEnablementController.disable` calls `_journal_enablement_event` (`enablement.py:236`) before `self._disabled = True` (`:242`).
  - `SafeModeController.enter_safe_mode` sets `_in_safe_mode=True` (`safe_mode.py:205`) and then journals (`:208-212`), so it raises on journal failure.
  - In `execute_approved_plan`, when the SL is unconfirmed (`manager.py:561`), `safe_mode_controller.enter_safe_mode(...)` (`:568`) runs first, outside the try that starts at `:569`. If the journal raises, the exception escapes and `expire_pending_entry` for the acknowledged entry is never called.
  - `probe_journal_first.py` output:
    ```
    expire_pending_entry raised: ConnectionError
    adapter cancel calls: []
    enter_safe_mode raised: ConnectionError | in_safe_mode = True
    emergency_manual_close raised: ExceptionGroup ['ConnectionError', 'ConnectionError', 'ConnectionError']
    emergency adapter calls: []
    ```
- **Expected:** Exposure-reducing actions (cancel a resting entry, disable live orders, emergency close) proceed even when the journal is unavailable. The journal write is best-effort, buffered locally, and reconciled later. The audit write must never gate the safety action.
- **Actual:** A journal outage turns every cancel and the kill switch into no-ops that raise. An acknowledged entry whose SL could not be confirmed keeps resting on the exchange with no stop.
- **Reproduction:** `PYTHONPATH=<snapshot> python -B tmp/security_reliability/probe_journal_first.py`
- **Impact:**
  - During a PostgreSQL outage (a listed SAFE_MODE trigger), the operator's emergency close and disable do nothing on the exchange.
  - If an SL placement also fails, the GTC entry (no GTD, F-959) can fill into a naked position.
- **Why tests miss it:** All journals in the tests are in-memory fakes that never raise.
- **Remediation:**
  - Issue the cancel or disable first (or in parallel), and journal the outcome with a local durable fallback (append-only file) when the DB fails.
  - In `enter_safe_mode` and `disable`, flip the flag first and never let journaling raise out of a safety transition.
  - Wrap `enter_safe_mode` in `execute_approved_plan` so the entry cancel always runs.

### F-703: No write-ahead order intent, so a crash between entry ACK and SL ACK leaves an exchange entry the system cannot know about after restart
- **Severity:** MEDIUM
- **Confidence:** PROBABLE
- **Classification:** GAP
- **Category:** restart/recovery
- **Component:** execution
- **File:** `src/execution/manager.py`
- **Lines:** 459-584
- **Invariant:** INV-079 (restart: reconcile, then verify no duplicate action), INV-093, INV-096.
- **Phase/commit:** Phase 9.
- **Known-prior:**
  - Related: F-956 (no runtime composition, M1-M4), F-104 (no user-data stream), F-126 (approval consumption not persisted).
  - None of these names the missing persist-before-send intent row.
- **Evidence:**
  - `execute_approved_plan` performs no journal or DB write before `_place_entry_no_blind_retry` (`:509`) or between the entry and the SL `_place_protective_leg` call (`:540-560`).
  - The only journal writes on this path are inside `expire_pending_entry` (failure path).
  - Local intent for `compare()` (`LocalOrderIntent` rows) therefore has no producer for live orders.
- **Expected:** Persist an order intent (PLANNED/SUBMITTING, with a deterministic client ID) before each send. On restart, reconcile those intents by client ID (query order / query algo), then attach or cancel.
- **Actual:**
  - A crash, kill or host loss after the entry is acknowledged but before the SL is acknowledged leaves a resting entry with no SL and no local record.
  - The next reconciliation cannot flag it because compare ignores exchange-only orders (F-701).
  - A later fill yields an unprotected position.
- **Reproduction:** Code reading: `grep -n "journal" src/execution/manager.py` shows no record before placement.
- **Impact:** Unprotected exposure after a crash. The window is small (sub-second to seconds), but restarts, deploys and Windows host reboots make it recur.
- **Why tests miss it:** The tests call the manager in one process with fakes. There is no crash-injection or restart test.
- **Remediation:**
  - Write-ahead intent row per order (client ID, role, plan_hash, SUBMITTING) committed before the POST.
  - Startup reconciliation resolves every SUBMITTING row by client-ID query.
  - Alternatively, place the closePosition SL before the entry (it is quantity-independent).

### F-704: The production backup runner hands pg_dump a SQLAlchemy URL and puts the DB password on the command line
- **Severity:** MEDIUM
- **Confidence:** PROBABLE
- **Classification:** DEFECT
- **Category:** ops / secrets
- **Component:** ops/backup
- **File:** `src/ops/backup.py`
- **Lines:** 455-477
- **Invariant:** INV-115 (automated backup; restore verified), INV-111 (secrets not exposed).
- **Phase/commit:** Phase 2 (02-REVIEW-FIX.iter2 CR-06 introduced `_prod_pg_dump_runner`).
- **Known-prior:**
  - F-108 (not off-host, not encrypted), F-121 (drill never restores), F-910. KNOWN in that area, but this mechanism is new.
- **Evidence:**
  - `db_url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")` then `subprocess.run([pg_bin, "--format=custom", "-f", str(out), db_url], check=True)`.
  - `.env.example:21` documents only `DATABASE_URL=postgresql+psycopg://trading:…@localhost:5432/trading`. `DATABASE_URL_SYNC` appears nowhere in `.env.example`.
  - libpq expands the positional dbname as a connection string only when it starts with `postgresql://` or `postgres://`, or contains `=`. `postgresql+psycopg://…` is neither, so pg_dump treats the whole string as a database name on the default host and fails.
  - The app image (`python:3.13-slim-bookworm`) installs no `postgresql-client`, so pg_dump is also absent in-container.
  - The password is passed as argv, which is readable via the process list or `/proc/<pid>/cmdline`.
- **Expected:**
  - A backup that works with the documented configuration.
  - Credentials passed via `PGPASSWORD`/`.pgpass`/a service file (not argv).
  - A URL normalised to libpq form.
- **Actual:** With the documented env, `backup` fails (loudly, via CalledProcessError), so no automated PG backup can succeed without an undocumented `DATABASE_URL_SYNC` in libpq form.
- **Reproduction:** Set `DATABASE_URL` as in `.env.example`, then run `python -m src.ops.backup backup`. Not executed here (no DB connections allowed); the conclusion rests on libpq connection-string rules.
- **Impact:** The operational journal and approval state have no working backup. The "backup-OK" evidence came only from the SQLite fake (F-121).
- **Why tests miss it:** `tests/test_backup.py` always injects `_sqlite_fake_pg_dump_runner`.
- **Remediation:**
  - Strip the `+driver` suffix (`sqlalchemy.engine.make_url(...).set(drivername="postgresql")`).
  - Pass the password via env.
  - Document `DATABASE_URL_SYNC`, and install the pg client in a dedicated backup image.
  - Run one real `pg_restore` drill.

### F-705: The Docker HEALTHCHECK runs the system interpreter instead of the uv venv, so the collector container is permanently "unhealthy"
- **Severity:** LOW
- **Confidence:** PROBABLE (static; the image was never built, per F-107)
- **Classification:** DEFECT
- **Category:** ops / monitoring
- **Component:** Dockerfile
- **File:** `Dockerfile`
- **Lines:** 8-9, 16, 31-34
- **Invariant:** INV-113 (meaningful health checks), INV-110.
- **Phase/commit:** afa2e74 (02 WR-06 / iter3 fix).
- **Known-prior:** None. 02-REVIEW.iter3 wanted a real freshness probe, and the fix introduced this.
- **Evidence:**
  - Dependencies install into `UV_PROJECT_ENVIRONMENT=/app/.venv` (`uv sync --frozen --no-dev`), and `PATH` is never extended.
  - `HEALTHCHECK … CMD python -m src.data.collector --healthcheck || exit 1` resolves `python` to `/usr/local/bin/python` (base image), which lacks polars and sqlalchemy.
  - `src/data/collector.py:53-56` imports `polars` and `sqlalchemy` at module import, so this raises ModuleNotFoundError and exits 1.
  - The CMD uses `uv run`, which is why the collector itself would run.
- **Expected:** `CMD uv run --frozen python -m src.data.collector --healthcheck`, or `ENV PATH=/app/.venv/bin:$PATH`.
- **Actual:** The healthcheck always fails, so a real watermark wedge is indistinguishable from the constant false alarm.
- **Reproduction:** `docker build` then `docker inspect --format '{{.State.Health.Status}}'`. Not executed (no Docker in audit scope).
- **Impact:** Monitoring of the irreplaceable OI collector is noise. Operators learn to ignore "unhealthy".
- **Why tests miss it:** The collector's `--healthcheck` is unit-tested in the dev venv, never through the image.
- **Remediation:** Fix the PATH or command, and add a container smoke test.

### F-706: No clock validation; signed requests, approval expiry and feed staleness all trust the unchecked local clock
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (code trace)
- **Classification:** GAP
- **Category:** reliability / time
- **Component:** adapters, approval, paper
- **File:** `src/adapters/binance_usdm.py`
- **Lines:** 526-527. Also `src/adapters/telegram_callbacks.py:649`, `src/paper/loop.py:284-298`, and `.venv/binance_common/utils.py:116-118,413`.
- **Invariant:** INV-079 ("load config → validate time → …"), INV-095 ("refresh server time"), INV-076.
- **Phase/commit:** Phases 2, 7 and 9.
- **Known-prior:** None. F-128 covers credentials and testnet config, not time.
- **Evidence:**
  - `grep -rn "server_time|check_server_time|skew|recv_window" src` finds only docstrings.
  - The SDK signs with `get_timestamp()` = local `time.time()` and has no offset option.
  - The approval `callback_at_utc = datetime.now(UTC)` is used as `now_utc` for the expiry gate.
  - `check_feed_freshness` rejects only `gap_seconds > 60`. A negative gap (event close in the "future" because the local clock is behind) passes as fresh, whereas `ops/health.py:309,343,473` treats `age < 0` as FAIL (inconsistent).
- **Expected:**
  - At startup and on reconnect, query `GET /fapi/v1/time` and measure the offset.
  - Refuse new orders and approvals when `|offset|` exceeds a threshold (e.g. > 500 ms, since Binance rejects timestamps > serverTime+1000 ms).
  - Treat negative staleness as stale.
- **Actual:**
  - A host clock that runs ahead makes every signed request fail with -1021, and each ambiguous placement probe then forces SAFE_MODE.
  - A clock that runs behind accepts approvals past the true expiry and treats future-dated events as fresh.
- **Reproduction:** Code reading of the cited lines.
- **Impact:**
  - Windows hosts drift routinely, so live trading silently degrades into SAFE_MODE loops.
  - The expiry and staleness safety gates are off by the skew.
- **Why tests miss it:** All tests inject `now_utc`, and no test models an exchange/local clock offset.
- **Remediation:** Add a clock-offset health probe (part of the INV-079 restart sequence) and a gate on it. Make the loop treat `gap < 0` as DATA_STALE.

### F-707: Telegram approval authority is chat-only, with no user-identity check, and group chats are explicitly supported
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** auth
- **Component:** adapters/telegram_callbacks
- **File:** `src/adapters/telegram_callbacks.py`
- **Lines:** 184-197, 642-656. Also `.env.example:47-51`.
- **Invariant:** INV-048/INV-050 area. TELEGRAM.md §3 ("bound to … user identity / authorized chat").
- **Phase/commit:** Phase 8 (08-CONTEXT D-02).
- **Known-prior:** F-127(d) (the one-time token is resolved server-side, so it adds no authentication). This finding is the complementary gap: the only remaining factor is chat id.
- **Evidence:**
  - `authorized_chat_gate` returns `callback_chat_id == authorized_chat_id`.
  - There is no `update.effective_user` / `from_user` check anywhere in `src/` (grep: none).
  - `.env.example` says the chat id "may be negative for groups".
  - The token and version gates compare server data with itself (F-127(d)).
- **Expected:** Allowlist the approving Telegram user ID(s) as well as the chat, or require a private chat (`chat.type == "private"`, so chat id == user id).
- **Actual:** In a group chat, any member (including a compromised or added account) can press APPROVE and place a live order.
- **Reproduction:** Code reading.
- **Impact:** Unauthorized approval of real orders if the operator ever uses a group.
- **Why tests miss it:** The tests exercise only chat-id equality.
- **Remediation:** Add `authorized_user_ids` and check `update.effective_user.id`. Reject non-private chats unless explicitly configured. Record `user_id` in the receipt journal.

### F-708: Secret-bearing strings can reach exception text and the journal
- **Severity:** LOW
- **Confidence:** CONFIRMED (make_engine probe) / PROBABLE (sweeper)
- **Classification:** DEFECT
- **Category:** secrets
- **Component:** db, reconcile
- **File:** `src/db/models.py`
- **Lines:** 450-454. Also `src/reconcile/sweeper.py:226,279`.
- **Invariant:** INV-111 ("keys and signatures are never logged"), INV-114.
- **Phase/commit:** Phases 3/10 (make_engine) and Phase 8 (sweeper).
- **Known-prior:** None.
- **Evidence:**
  - `make_engine` raises `ValueError(f"refusing engine: {database_url!r} …")`. Probe: `make_engine('postgres://trading:TopSecretPw@db:5432/trading')` → `ValueError: refusing engine: 'postgres://trading:TopSecretPw@db:5432/trading' names no async driver`. `analytics/cli.py:752` prints such errors to stderr.
  - The sweeper journals `reason=f"probe_failed: {type(exc).__name__}: {exc}"` and `cancel_failed: …{exc}` into JournalEvent payloads.
  - `binance_common` `NetworkError` embeds `str(requests exception)`, which includes the request URL. For signed GET/DELETE requests, that URL carries the query string with `timestamp` and `signature`.
  - By contrast, `manager.py` deliberately records the exception type only ("never the message, which may carry request material").
- **Expected:** Redact URLs with `sqlalchemy.engine.make_url(url).render_as_string(hide_password=True)`. Record only the exception type or code on signed paths.
- **Actual:** The password appears in the error text. Per-request signatures can be persisted in journal rows.
- **Reproduction:** One-liner in the lane notes. The sweeper path is by code reading.
- **Impact:** Low: signatures are single-use within recvWindow. The DB password leaks to the console or logs on a misconfiguration.
- **Why tests miss it:** The secret-posture tests check the source for literal secrets, not runtime message content.
- **Remediation:** As in Expected. Add a redaction processor to structlog and configure it once.

### F-709: Container and compose hardening gaps (DB exposed on all interfaces, unpinned build inputs, over-broad env)
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** IMPROVEMENT
- **Category:** infra / supply-chain
- **Component:** Dockerfile, docker-compose.yml
- **File:** `docker-compose.yml`
- **Lines:** 21-22, 34. Also `Dockerfile:1,4` and `.gitignore:33-34`.
- **Invariant:** INV-117 (locked, reproducible build), INV-111.
- **Phase/commit:** Phase 2.
- **Known-prior:** None.
- **Evidence:**
  - `ports: - "${POSTGRES_PORT:-5432}:5432"` publishes Postgres on 0.0.0.0. Compose enforces presence but not strength of `POSTGRES_PASSWORD`, and `.env.example` ships `change_me_in_local_env_only`.
  - `env_file: .env` injects the whole `.env` into the collector, which needs only the DB URL. That includes the Telegram token and future Binance keys.
  - `COPY --from=ghcr.io/astral-sh/uv:latest` and `FROM python:3.13-slim-bookworm` are not version- or digest-pinned.
  - `.gitignore` ignores only `.env` and `.env.local`, so `.env.live` or `.env.production` would be committable.
- **Expected:**
  - Bind the DB port to `127.0.0.1:` (or omit it).
  - Pass per-service env vars explicitly.
  - Pin uv by version and base images by digest.
  - Ignore `.env*` except `.env.example`.
- **Actual:** As in Evidence.
- **Reproduction:** Read the files.
- **Impact:** A LAN-reachable DB holding approval/journal state. Non-reproducible images. Accidental secret commits.
- **Why tests miss it:** Infra is not tested.
- **Remediation:** As in Expected.

### F-710: Protective placement probes by client ID before every SL, and the "not found" mapping for algo queries is unverified
- **Severity:** MEDIUM
- **Confidence:** UNVERIFIED
- **Classification:** AMBIGUITY
- **Category:** integration / fail-closed
- **Component:** adapter, execution
- **File:** `src/adapters/binance_usdm.py`
- **Lines:** 857-876. Also `src/execution/manager.py:722-763`.
- **Invariant:** INV-084/INV-085 (protective placed and confirmed).
- **Phase/commit:** Phase 9 (09-REVIEW CR-04 fix).
- **Known-prior:**
  - KNOWN: 09-REVIEW-FIX verification item 1 ("the existing -2011/UNKNOWN_ORDER mapping in … query_algo_order_by_client should be re-checked too"). The entry side (`-2013` unmapped, so every rejected entry → SAFE_MODE) is also KNOWN there.
  - This finding records the consequence on the SL path, which the prior note does not spell out.
- **Evidence:**
  - `_place_protective_leg` always calls `query_algo_order_by_client` first (`manager.py:741-744`). Any exception → `(False, "probe …")` → SL unconfirmed.
  - The adapter maps not-found only if `"UNKNOWN_ORDER" in str(exc) or "-2011" in str(exc)`, and otherwise re-raises.
  - The test fakes synthesize `found=False` (`tests/test_execution_manager.py:143-154`). Real Binance behaviour for an unknown `clientAlgoId` on `GET /fapi/v1/algoOrder` is not recorded in fixtures or the A2 facts. The Binance error-code table lists `-2013` "no such order" for queries.
- **Expected:** A verified not-found code for algo queries, backed by a recorded fixture, or placement that does not depend on the probe's not-found shape (for example, place, then confirm by the placement response).
- **Actual:** If the real code is not -2011, every live trade does this: entry placed → SL probe raises → SL never placed → entry cancelled → SAFE_MODE. An entry that is marketable and filled before the cancel becomes a naked position (no re-placement, F-952).
- **Reproduction:** Needs a testnet call (out of audit scope).
- **Impact:** Either the live path is unusable, or it produces naked positions for immediately-filled entries.
- **Why tests miss it:** The fakes return `found=False` directly.
- **Remediation:** Record the real testnet error for an unknown clientAlgoId and add it as an adapter fixture. Map it explicitly.

### F-711: SAFE_MODE exit is automatic on a "clean" compare, needs no operator, and inherits F-701's blind spots
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DEFECT (root cause: doc silent; corrected rule 25)
- **Category:** fail-closed
- **Component:** reconcile/safe_mode
- **File:** `src/reconcile/safe_mode.py`
- **Lines:** 123-131, 241-310
- **Invariant:** INV-074, INV-075. Corrected rule 25 ("exit from SAFE_MODE is manual only, and the mode persists across restart").
- **Phase/commit:** Phase 8.
- **Known-prior:**
  - F-127(a) (SAFE_MODE is in-memory; a restart clears it) is KNOWN.
  - 08-REVIEW WR-16 (stale intent) was "fixed" by adding an optional `local_intent_fn`, but local intent still defaults to `[]`.
- **Evidence:**
  - The class docstring says "The scheduled reconciler tick calls `enter_safe_mode` on any divergence and `exit_safe_mode` only after a fresh clean three-source compare".
  - `exit_safe_mode` takes no operator id and uses `local_open_orders or []` etc. (`:292-294`).
  - With empty intent and an exchange that shows only an unknown resting entry, compare is clean (F-701 probe case 6), so SAFE_MODE exits.
- **Expected:** Exit only by an explicit, journaled operator action (with operator id) after a clean compare. The SAFE_MODE flag is persisted.
- **Actual:** Exit can be automatic, and a vacuous compare suffices.
- **Reproduction:** `probe_compare.py` case 6, plus code reading.
- **Impact:** New entries resume while unknown exposure exists.
- **Why tests miss it:** The tests assert that a clean compare exits, not that exit requires an operator.
- **Remediation:** Add `operator_id` to `exit_safe_mode`. Require non-None, freshly fetched local intent. Persist and rehydrate the flag.

## Open Questions

1. **L5 integrations:** confirm the real Binance error for `GET /fapi/v1/algoOrder` with an unknown `clientAlgoId` (F-710) and for `GET /fapi/v1/order` (expected -2013). Also: does `cancel_order` by `origClientOrderId` act on the open order when a filled order with the same ID exists (F-126 interplay)?
2. **L4 data/concurrency:** `_TOKEN_LOCKS` in `approval/replay.py:55-65` grows without bound and is in-process only. Cross-process dedup is KNOWN (F-126 / WR-10).
3. **Logging config:** no `structlog.configure` or `logging` configuration exists anywhere in `src/`, so logs are structlog's default console renderer, not the JSON decision-lineage schema (INV-114). If a later runtime enables stdlib INFO logging, httpx will log `https://api.telegram.org/bot<TOKEN>/…` URLs. A `logging.getLogger("httpx").setLevel(WARNING)` guard is advisable when the PTB application is composed.
4. **Operator process:** `LiveEnablementController.enable` accepts any duck-typed object with `is_no_trade False` and `reason_code "OK"` as a health verdict (`enablement.py:176-185`). The structural completeness promised in the docstring is only enforced if the caller used `run_health_checks`. Covered in spirit by F-953; flagged for L2/L3.
5. **Health probes** (`ops/health.py`) are caller-fed booleans (`connected`, `positions_reconciled`). With no user-data stream (F-104), `check_user_data_stream_state` has no truthful input source.
6. **Sweeper robustness:** a journal failure inside the sweeper's `except` path (`sweeper.py:275-282`) raises out of `sweep`, contradicting its "NEVER raises" contract. This is the same root cause as F-702.
