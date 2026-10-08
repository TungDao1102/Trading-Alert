# Phase 16: Paper Runtime Composition + SHADOW Approval Mode - Pattern Map

**Mapped:** 2026-10-08
**Files analyzed:** 31 new/modified (plus 3 doc/protocol files listed for the amendment task)
**Analogs found:** 28 / 31 with a code analog; 3 have no analog (listed at the end)
**Method:** CONTEXT.md (D-01..D-35, L-01..L-17, REV-01..REV-18), RESEARCH.md (Existing Code Shape, Patterns 1-7, Validation Architecture, Gaps Resolution) and 16-CONTEXT-CONSISTENCY.md were read. Every analog below was read in the worktree on 2026-10-08. All analog paths are git-tracked source (`git ls-files` checked on the main ones: `src/adapters/paper_ws.py`, `src/paper/freeze.py`, `tests/test_paper_start_gate.py`, `tests/test_backtest_purity.py`, `deploy/lib.sh`, `scripts/demo_rehearsal.py`, `docker-compose.yml`, `src/analytics/killgate.py`). No `.gsd/` mirror path is used.
**Read-only:** no source file was changed, no trading code was run, no `.env` was read.

Note on stale facts: CONTEXT "code_context" says no `.codegraph` existed in the worktree; line numbers below were taken from the files as they are now and supersede the RESEARCH line numbers wherever they differ.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/adapters/paper_ws.py` (modify, D-08) | adapter | streaming | itself (current) + SDK signatures in RESEARCH WS section | exact (rewrite in place) |
| `tests/test_paper_ws_contract.py` (new, D-09) + rewrite `tests/test_paper_ws_connect.py`, `tests/test_paper_supervisor_backfill.py` | test | request-response | `tests/test_paper_ws_connect.py` (fakes to replace) | role-match |
| `src/paper/supervisor.py` (modify: async `WsAdapterLike`, gap/backfill sinks) | service | streaming / event-driven | itself | exact |
| `src/paper/resync.py` (modify: 1 ms close arithmetic, P1) | utility | batch | itself (`_expected_open_times`) | exact |
| `src/paper/loop.py` (modify: typed per-bar extraction, IN-fixes) | service | transform | itself (`run_paper_tick`) | exact |
| `src/paper/freeze.py` (modify: `PaperAllowlistEntry.__post_init__`, `--from-allowlist`, SKIPPED line, EVIDENCE_GAP line) | utility/CLI | file-I/O | itself (`DiffLogEntry`, `run_check_cli`, `_cli_main`) | exact |
| `.github/workflows/paper_freeze_check.yml` (modify) | config | batch (scheduled) | itself | exact |
| `src/paper/runtime.py` (new composition root, `python -m src.paper.runtime`) | service/entrypoint | event-driven + streaming | `src/data/collector.py` `main()` (entrypoint) + `PaperSupervisor` (composition target) | role-match |
| `src/paper/runtime_state.py`, `src/paper/bars.py` (new) | store port / pure util | CRUD / transform | `src/persistence/journal.py` `PgJournalStore.record` + `src/domain/journal.py` `correlated_event_id` | role-match |
| `src/paper/surface.py` (new `decision_surface`, D-20) | utility | transform | `tests/test_paper_parity.py` consumers + `src/paper/loop.py` body | partial |
| `src/paper/shadow.py` (new: `Mode`, SHADOW label, CONFIRM card/token/TTL, approval loop) | service | request-response (callbacks) | `src/approval/tokens.py`, `binding.py`, `replay.py` + `src/adapters/telegram_callbacks.py` | role-match |
| test-only rehearsal path (new, REV-03; e.g. `src/paper/rehearsal.py` + `scripts/shadow_rehearsal.py`) | service/script | event-driven | `scripts/demo_rehearsal.py` (`EvidenceRecorder`, dry-run vs execute split) | role-match |
| `src/paper/shadow_fill.py` (new live 1m source + fill driver, D-14/D-17) | service | streaming + transform | `src/backtest/engine.py` `_Engine._size_and_register` + `lifecycle.advance` + `series.ListMinuteSource` | role-match |
| `src/paper/coverage.py` (new: coverage fn, EVIDENCE_GAP reconciler, exit-criteria evaluator, D-07/D-22/D-23) | utility (pure) | transform / batch | `src/data/coverage.py` (report dataclasses) + `src/analytics/killgate.py` `evaluate` (pure evaluator) | role-match |
| `src/paper/attribution.py` + `src/paper/journal.py` (modify: measured delay, mode, `test_only`, confirm timestamps, D-15) | model | CRUD | itself | exact |
| `src/paper/notify.py` / `src/adapters/telegram_notify.py` (modify: functional APR/SKP buttons, SHADOW label, D-16) | adapter | request-response | `build_approve_keyboard` / `APR_PREFIX` in `telegram_notify.py` | exact |
| `scripts/` public-data WS smoke recorder (new, D-10, SC7) | script | streaming | `scripts/demo_rehearsal.py` `EvidenceRecorder` + `tests/test_demo_rehearsal_safety.py` | role-match |
| `tests/test_paper_shadow_isolation.py` (new, D-13) | test | static analysis | `tests/test_paper_start_gate.py` `_scan_src_violations` + `tests/test_backtest_purity.py` | exact |
| `src/research/` (`run.py`, `manifest.py`, `feasibility.py`, `plateau.py`, `register.py`; D-24..D-30) | service/CLI | batch | `scripts/smoke_backtest_realdata.py` + `src/data/case_input.py` + `src/backtest/experiment.py` `assemble` | role-match |
| `tests/test_research_runner.py`, `tests/test_research_feasibility.py` (new) | test | batch | `tests/test_backtest_experiment.py` | role-match |
| `src/analytics/killgate_guard.py` + versioned WR registry file + `tests/test_killgate_guard.py` (new, D-31/REV-11/REV-15) | utility/guard | request-response | `src/analytics/killgate.py` (`registration_allowed`) + `src/analytics/cli.py` `_run` | role-match |
| `src/analytics/cli.py` (modify: call guard before concluding) | CLI | request-response | itself (`_run`, `_fail`) | exact |
| `docker-compose.yml` `paper` service (modify) + soak compose overlay/project | config | n/a | `collector` service block | exact |
| soak `down -v` guard wrapper (`deploy/compose-soak.sh`) + `tests/test_soak_compose.py` | script + test | request-response | `deploy/lib.sh` + `tests/test_deploy_compose.py` | role-match |
| `docs/operations/RUNBOOK.md` (soak host, EC2 runbook, REV-08 study) | doc | n/a | RUNBOOK sections 11, 13, 17 + `tests/test_deploy_docs.py` | exact |
| `docs/GLOSSARY.md` (`CONTEXT_BAR`, `DUPLICATE_BAR`, `SHADOW`, `EVIDENCE_GAP`) | doc | n/a | existing glossary rows | exact |
| protocol v2.2.0 amendment task (REV-16): `docs/research/RESEARCH_PROTOCOL.md`, `docs/research/holdout_consumed.json`, `scripts/decision_alignment/protocol.py`, `tests/test_decision_alignment_protocol.py`, `.github/workflows/research-gate.yml` witnesses | config/doc/test | n/a | the v2.1.0 amendment (D057/D060) itself | exact |
| `src/backtest/report.py` (BKTS-03, only consumed; NOT modified, L-02) | n/a | n/a | n/a | reference |
| `tests/test_domain_no_float.py` (modify: add new modules to `SCANNED_FILES`) | test | static analysis | itself | exact |

---

## Pattern Assignments

### `src/adapters/paper_ws.py` (adapter, streaming) - D-08, D-09, SC2, SC7

**Analog:** current file `src/adapters/paper_ws.py` (359 lines). It is the only module allowed to import the SDK WS surface (docstring lines 3-7); keep that boundary.

**Imports to keep** (lines 22-39): `structlog`, `ConfigurationWebSocketStreams`, `DerivativesTradingUsdsFuturesWebSocketStreams`. Delete the `KlineCandlestickStreamsIntervalEnum` import and the `_INTERVAL_TO_ENUM` table (lines 35-37, 276-301); the SDK takes the plain string (`"1h"`, `"4h"`, `"1m"`). Keep an allowed-interval set so an unsupported interval still raises `ValueError`.

**Defects to fix (exact current lines):**
- `subscribe` (141-212): `self._ws.kline_candlestick_streams(...)` at 160 is a coroutine in the SDK and is not awaited; `hasattr(handle, "on_message")` at 196 is wrong, the handle exposes `.on("message", cb)` and `.unsubscribe()`.
- `connect` (214-233): `factory()` is returned un-awaited and `for entry in ("create_connection", "init_connection", "connect")` hides D1 behind `getattr`; replace with `await self._ws.create_connection()` then fail when `ws.connections` is empty (D4, swallowed connect failure).
- `__init__` (129-139): default `ConfigurationWebSocketStreams()` has no `stream_url`; pass the SDK PROD constant.
- `reconnect/schedule_reconnect/close` (235-268) use `hasattr` guards on methods the SDK handle does not have; replace with `async unsubscribe(handle)`, `async close()` (`close_connection()`), and connection-event hooks `on_connection(event, cb)` for `open|reconnect|close|error` (RESEARCH Pattern 1).

**Core pattern to copy (RESEARCH Pattern 1, values introspected from the installed SDK):**
```python
config = ConfigurationWebSocketStreams(stream_url=DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL)
ws = DerivativesTradingUsdsFuturesWebSocketStreams(config)
await ws.create_connection()
if not ws.connections:            # D4: the SDK swallowed a failed connect
    raise ConnectionError("WS connect produced no connection")
handle = await ws.kline_candlestick_streams(symbol="btcusdt", interval="1h")  # plain str
handle.on("message", lambda msg: queue.put_nowait(normalise(msg)))
ws.on_connection("reconnect", on_ws_reconnect)   # also "open", "close", "error"
```

**Keep unchanged** (byte-for-byte, they are well tested): `Kline` frozen dataclass (46-68), `_ms_to_utc` exact timedelta arithmetic (76-81), `_normalize_kline_payload` (84-108), `_as_dict`/`_extract_kline_payload` (304-356), and the hardened `_on_message` try/except shape with `paper_ws.extract_failed` / `unknown_envelope` / `normalize_failed` warnings (166-194). The callback must stay non-blocking: it only normalises and enqueues (RESEARCH Pattern 2).

**Error handling:** fail loud with `log.error(...)` then `raise` (lines 204-211 pattern), never a silent dead subscription.

---

### `tests/test_paper_ws_contract.py` (test, request-response, network-free) - D-09

**Analog:** RESEARCH "Contract test skeleton" plus the fake in `tests/test_paper_ws_connect.py` lines 36-70 (what NOT to keep: sync `create_connection`, sync `kline_candlestick_streams`, handle with `on_message`).

**Pattern:** introspect the installed SDK and assert the fakes mirror it.
```python
inspect.iscoroutinefunction(DerivativesTradingUsdsFuturesWebSocketStreams.create_connection)
inspect.iscoroutinefunction(DerivativesTradingUsdsFuturesWebSocketStreams.kline_candlestick_streams)
inspect.signature(...).parameters  # names: symbol, interval, id
# handle: RequestStreamHandle has .on / .unsubscribe, NOT on_message / reconnect
```
**Required negative control:** a deliberately synchronous fake must make the contract assertion fail (SC2 "must FAIL on"). Rewrite `tests/test_paper_ws_connect.py` and `tests/test_paper_supervisor_backfill.py`; they pin the fictional handle API today.
**Header convention to copy:** module docstring stating the Phase, the review id and "no network is touched" (`test_paper_ws_connect.py` lines 1-10).

---

### `src/paper/supervisor.py` (service, streaming/event-driven) - D-05, D-06

**Analog:** itself. Facts to keep: `_advance_last_close` monotonic check-and-set under `threading.Lock` (lines 142-157), `record_close` seeding path (132-140), the `_on_kline` closed-only gate and `duplicate_close_dropped` warning (187-208), tenacity-bounded retry with `reraise=True` (`_reconnect_with_retry`, 232-263), constants `SUPERVISOR_MAX_ATTEMPTS=7` etc. (52-55, not ratified, O-07).

**Changes:**
- `WsAdapterLike` (63-77) becomes `async` for `subscribe`/`close`/`reconnect`-or-rebuild; `start()` (159-185) becomes `async start()`, keeping the roll-back-on-failure block (`_close_all_handles()` then `raise`, 181-185) and the double-start guard (167-171).
- `on_disconnect` DISCARDS the `(backfilled, outage_gaps)` result of `_resubscribe_and_backfill` (Pitfall P9, RESEARCH 239). Add sinks: `on_backfill(...)` and `on_gap(...)` callables so the runtime journals gaps with a reason code (REV-01 reason codes; `PLANNED_RESTART` has its own code but stays uncovered).
- Source-tag bars `LIVE_WS` / `REST_WARMUP` / `REST_BACKFILL` (RESEARCH Pattern 6); only `LIVE_WS` bars that pass the closed gate may reach `evaluate` (structural L-11 rule, not the 60 s freshness constant).
- Cold start: `_last_close` starts empty (`no_last_close` log); the runtime seeds it through `record_close` from the persisted last close (D-04).

---

### `src/paper/resync.py` (utility, batch) - Pitfall P1

**Analog:** itself, `_expected_open_times` (lines 102-132) and `backfill_missed_closes` (134+). Expected slots start AT `last_close_utc`, wrong by 1 ms against real Binance close times (`close = open + interval - 1 ms`). Fix the slot arithmetic and add real-shaped fixture rows (RESEARCH Code Examples "Real-shaped fixture rows"; live `GET /fapi/v1/klines` row of 2026-10-07). Keep `RESYNC_MAX_ATTEMPTS=7`, `RESYNC_MAX_DELAY_SECONDS=120` and the bounded retry. Test must FAIL on the current code (3 returned bars, 3 phantom gaps).

---

### `src/paper/loop.py` (service, transform) - D-02, D-03, D-05, D-20

**Analog:** itself. The per-bar body is lines 462-579 (RESEARCH Pattern 4); gate at 344-363; `STALENESS_THRESHOLD_SECONDS=60` (175), `WARMUP_MIN_BARS=200` (181); `_event_to_candle` accepts only `"1h"`/`"4h"` (241).

**Pattern (RESEARCH Pattern 4):** extract the body into a function that returns a typed result (`closed candle`, `setup_result`, `plan_result`, `verdict` with `sized`, reason, stage) and have `run_paper_tick` project the result into exactly the same dict as today. Alternative: leave `run_paper_tick` untouched and add a sibling that reuses the same helpers.

**Byte-identity proof (must stay green after every edit):** `tests/test_paper_start_gate.py` (`_clean_run_digest`), `tests/test_paper_parity.py`, `tests/test_paper_reviewfix_pins.py`, `tests/test_paper_feed_gates.py`, `tests/test_paper_closed_candle.py`.

**IN-01..IN-05 (D-03):** docstring corrections, once-per-process gate naming, `REGISTRY_ROOT` bound once with the test `test_gate_and_loop_must_judge_the_same_file` (start_gate.py line 369) as the model for the new "never judge different files" test.

**Do not** use the `epoch` returned by `run_paper_tick`'s internal pin: `epoch_id` is a hash over `opened_at_utc` (freeze.py 256-278), so each call mints a new one. The runtime pins once.

---

### `src/paper/freeze.py` (utility/CLI, file-I/O) - D-03, D-21, REV-02, REV-18

**Analog:** itself.

**`PaperAllowlistEntry.__post_init__` (IN-01):** current class (lines 375-395) is a frozen dataclass with no validation. Model the validator on `DiffLogEntry.__post_init__` (162-166):
```python
def __post_init__(self) -> None:
    if self.checked_at_utc.tzinfo is None:
        raise ValueError("checked_at_utc must be UTC-aware")
    if self.outcome not in ("clean", "REGISTRY_DIFF"):
        raise ValueError(f"outcome must be 'clean' or 'REGISTRY_DIFF', got {self.outcome!r}")
```
Apply: 64 lowercase hex for `parameter_set_hash` (`re.fullmatch(r"[0-9a-f]{64}", ...)`), non-empty ids/`purpose`/`basis`, ISO date for `approved_at`. Keep `PAPER_START_ALLOWLIST: tuple[PaperAllowlistEntry, ...] = ()` as the single module-level tuple literal (line 402); `tests/test_paper_start_gate.py::_scan_src_violations` (537-577) rejects any other binding or any mention of the name outside `paper/freeze.py`, so the runtime must go through a function in freeze.py, never import the name. `require_bool_flag` (405-414) is the model for strict-typed safety flags.

**New line shapes (SKIPPED, EVIDENCE_GAP):** `DiffLogEntry` accepts only `("clean", "REGISTRY_DIFF")` (165) and renders canonical JSON (`sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False`, 168-182). Add the new outcomes without weakening the old validator (a sibling dataclass or extended allowed set with its own tests); `SKIPPED` carries `reason: "allowlist empty"`, an `EVIDENCE_GAP` line carries the missing slot. Never CLEAN for either.

**`--from-allowlist` mode (CLI):** extend `_cli_main` (805-867). Today `--strategy-id`, `--parameter-set-id` are `required=True` (827-836); with `--from-allowlist` they must be absent and derived from the allowlist. Empty allowlist: append one SKIPPED line, return 0, never CLEAN, never red, no fallback. Non-empty: check that exact pair and pinned hash via the existing `run_check_cli` (742-797). Keep exit codes 0 clean, 1 error, 2 missing pinned state, 3 rollover.
```python
return run_check_cli(
    strategy_id=args.strategy_id, parameter_set_id=args.parameter_set_id,
    pinned_state_path=args.pinned_state, diff_log_path=args.diff_log,
    registry_root=args.registry_root, now_utc=None,
)
```
Tests: new `tests/test_paper_freeze_allowlist_mode.py` modelled on `tests/test_paper_freeze.py` (empty path gives one SKIPPED line, exit 0, never `clean`; no `trend-pullback`/`baseline-v3` string in the workflow file).

---

### `.github/workflows/paper_freeze_check.yml` (config, scheduled batch) - D-21, REV-02, REV-18

**Analog:** itself (115 lines). Change only the "Run freeze check" step (lines 69-86): drop `--strategy-id trend-pullback` and `--parameter-set-id baseline-v3` (lines 80-81) and add `--from-allowlist`. Keep: SHA-pinned actions with version comments, `permissions: contents: read` (30-31), `persist-credentials: false`, `set +e` / `echo "exit_code=$?" >> "$GITHUB_OUTPUT"` / `exit 0` capture (76-86), the cache restore/save (61-67, 96-101), always-upload artifact (88-94), and the two alert steps (105-115).
```yaml
uv run python -m src.paper.freeze \
  --check \
  --from-allowlist \
  --diff-log "$PAPER_DIFF_LOG" \
  --pinned-state "$PAPER_PINNED_STATE" \
  --registry-root "$PAPER_REGISTRY_ROOT"
```
Research-only item (G15, not a semantic change): cron `"0 * * * *"` at line 25 is on the top of the hour; moving it off the hour is a candidate mitigation that must not be treated as proven. The Actions cache stays operational state (header comment lines 55-60). The workflow must be on `master`; code is on `develop` (RESEARCH risk list), so add a verification task. Style analog for workflow text tests: `tests/test_deploy_workflows.py`.

---

### `src/paper/runtime.py` (service/entrypoint, event-driven + streaming) - D-01, D-02, D-04, D-05, D-06, D-35

**Analog:** `src/data/collector.py` `main()` (lines 1145-1170+) for entrypoint shape; `PaperSupervisor` for what is composed; `scripts/demo_rehearsal.py` for the env-driven wiring.

**Entrypoint pattern to copy** (`collector.py` 1145-1167): `configure_logging()`, parse args, resolve inputs with a typed exception mapped to a return code, `--healthcheck` flag that exits 0/1 for the compose `healthcheck.test`, plain `return int` from `main` and `raise SystemExit(main())`:
```python
def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parse_collector_args(argv)
    try:
        universe = _resolve_universe(args)
    except CollectListError as exc:
        print(f"collector: collect list error: {exc}", file=sys.stderr)
        return 1 if args.healthcheck else 2
    ...
    if args.healthcheck:
        return _check_health(...)
```
For the runtime: `--healthcheck` (probe defined by Phase 16, see compose section), SKIPPED path (`log SKIPPED (allowlist empty)`, exit 0, no subscribe, before any `ws.connect`), runtime start gate separate from the per-call pin gate (RESEARCH Pattern 7: exact-hash check of strategy id, parameter set id, 64-hex hash against an allowlist entry; Q-A needs the user's confirmation, mark as blocking-human).

**Composition (RESEARCH Pattern 2):** WS callback only `put_nowait`s onto a bounded asyncio queue (called via `loop.call_soon_threadsafe` if the SDK thread is not the loop thread; RESEARCH D6 says callbacks run on the loop thread, the smoke must confirm); one consumer task drains, groups by close time, runs the tick in `asyncio.to_thread`; DB calls go through one small port (do not pre-empt Phase 24 decision G4-040). Only `is_closed` events enter the tick (SC7). 4h before 1h at shared closes (Pitfall P6). Graceful stop on SIGTERM inside `stop_grace_period: 30s` writing `RUNTIME_STOP`; start writes `RUNTIME_START`; WS reconnect writes `WS_DISCONNECT/RECONNECT` rows.

**Epoch:** once at start, `pin_stream_epoch(...)` then `write_pinned_state(epoch, path)` (freeze.py 484, 697-713), then a thin per-bar wrapper passes the already-pinned hash.

**Env isolation (D-13 layer 2):** build config from an allowlist of variable names; refuse to start when any `BINANCE_LIVE_*` or `BINANCE_TESTNET_*` or other trade-capable variable is present. Names pattern from `scripts/demo_rehearsal.py` 168-169 (`ENV_BINANCE_SECRET = "BINANCE_TESTNET_API_SECRET"  # noqa: S105 - a variable NAME, not a secret`) and its `need(...)` reader (line ~280). Never read or log values.

**Clock:** one injected UTC clock; chrony skew check logged at start (D-35, Pitfall P20).

**Deterministic journal ids (RESEARCH Pattern 3, REQUIRED):** use `correlated_event_id` (no clock) with correlation id `"paper:<epoch_id>:<symbol>:<interval>:<close_ms>"`:
```python
# src/domain/journal.py
def correlated_event_id(*, prefix, correlation_id, event_type, entity_id, step) -> str: ...
```
Do NOT use `content_hash_event_id` with `datetime.now`: it hashes `occurred_at_utc.isoformat()` into the id (`domain/journal.py` 40-48 body), so a post-crash retry would insert a duplicate (Pitfall P11). If it is used, set `occurred_at_utc` to the BAR CLOSE.

**Journal sink:** `PgJournalStore.record(event)` (`src/persistence/journal.py` 85-88) is sync, replay-idempotent (`ON CONFLICT (journal_event_id) DO NOTHING`, then `_verify_replay` raises `JournalConflict` on different content), and raises `ParentRowMissing` when a parent row is absent (insert parents first in one unit of work). Never call it from the SDK callback (Anti-Pattern).

---

### `src/paper/runtime_state.py` and `src/paper/bars.py` (store port / pure util)

**Analog:** `src/persistence/journal.py` + `src/persistence/uow.py` (`OperationalDatabase.transaction()`), `PgTradingEntityStore.insert_signal` (`entities.py:309`, replay no-op / `RowConflict` on different content), `PgApprovalStore` (`approvals.py:88`).

**Port pattern:** a small `Protocol` plus an in-memory fake and a PG implementation, so unit tests need no DB and `*_pg.py` tests use the disposable `_test` database (`TEST_DATABASE_URL`, `TRADING_CI_STRICT=1`; analog `tests/pg_support.py`, `tests/test_approval_replay_pg.py`).

**Constraint (Pitfall P12, Q-J):** `PgSystemStateStore` has a CHECK `state_key IN ('SAFE_MODE','LIVE_ENABLEMENT','KILL_GATE')` (`src/db/models.py:883`) and values only `str | bool | None`, so paper runtime state (pinned epoch, last close per pair, open sim positions) does not fit without a migration; the planner must raise this (blocking decision: new Alembic migration vs journal-rows-as-state). Runtime state via journal rows with deterministic ids is the no-migration option.

**`bars.py` (pure):** warm-up buffers per (symbol, interval), windows `STRATEGY_WINDOW_BARS=1000`, `CONTEXT_WINDOW_BARS=300` (`src/backtest/semantics.py` 48-49, must equal what `decision_surface` and the backtest use, Pitfall P7), dedup of seen open times, source tags. Add to `tests/test_domain_no_float.py::SCANNED_FILES` (Wave 0 gap).

---

### `src/paper/surface.py` (utility, transform) - D-20, L-02

**Analog:** the body of `run_paper_tick` (loop.py 462-579) and `tests/test_paper_parity.py` (trade-level parity, unchanged). `src/core` (`evaluate`, `plan`, features) plus `src/risk` verdict are the shared functions.

**Pattern:** pure function returning one record per closed bar `{bar, feature digest, signal or NO_TRADE reason, plan hash, risk verdict}`; digest via `src/domain/canonical.py` `sha256_hex` (same canonical-JSON route as `experiment.py:748`). Covers strategy-stage NO_TRADE (G2-008). Must not import the simulator or change its hashes; if impossible, stop and record a decision (L-02). Windows 1000/300 and 4h-before-1h ordering are the failure modes the replay test must catch (RESEARCH validation row "D-20 parity").

---

### `src/paper/shadow.py` (service, request-response) - D-12, D-16, L-13, REV-12

**Analog:** `src/approval/binding.py` (gate), `src/approval/tokens.py`, `src/approval/replay.py`, `src/adapters/telegram_callbacks.py`, `src/paper/notify.py`.

**Gate order to reuse (fixed, never reordered), `binding.py` lines 1-18:** chat id, expiry (`now_utc >= expiry_utc` is expired, boundary inclusive), plan hash, version/parameter-set, token hash. Expiry is the TradePlan expiry (REV-12): an APPROVE after expiry is journaled as `APPROVAL_EXPIRED` and never revives the signal. No new TTL parameter. The module is dependency-free (stdlib + `src/domain/enums.py`); keep the confirm-token logic equally pure.

**Token pattern:** `issue_one_time_token()` / `token_hash_of()` / `verify_token_hash()` (`tokens.py` 19, 30, 42); the raw token is never persisted. The CONFIRM token must be separate, single-use, bound to the same user id and plan hash, with a 60 s default TTL (L-13). A restart loses pending raw tokens (Pitfall P13): pending approvals must be expired on restart and journaled.

**Callback pipeline to wire, not rewrite:** `dispatch_callback` (`telegram_callbacks.py` 244-488, sync, takes `binding_context` with `plan_hash`, `strategy_version`, `parameter_set_id`, `parameter_set_hash`, `expiry_utc`, `raw_token`), `on_callback` (627-722, takes `binding_context_resolver(short_id)` returning the raw token), `authorized_chat_gate` (183-196, chat id only; user-id auth is Phase 23 and must be stated in the module docstring), `build_application` (735-768). No production code issues the one-time token, inserts the PENDING approval or implements the resolver (RESEARCH 271); the only in-memory book is `scripts/demo_rehearsal.py` lines ~927-955: build the production sender/resolver here.

**Button prefixes:** `APR_PREFIX = "APR:"`, `SKP_PREFIX = "SKP:"` are live; `SIM:`/`SKIP:` are inert (`telegram_notify.py` ~lines 94-132 `build_simulate_keyboard`, 64-byte callback_data limit check via `TELEGRAM_CALLBACK_DATA_MAX_BYTES`). SHADOW must send the APR/SKP keyboard backed by a PENDING approval row, not `build_simulate_keyboard` (F-961).

**Journal-first ordering (copy from `notify.py` `notify_simulate`, lines 202-331):** caller commits the journal row BEFORE the send; bounded tenacity retry (`stop_after_attempt(NOTIFY_MAX_ATTEMPTS) | stop_after_delay(...)`, `wait_random_exponential`, `retry_if_exception(lambda e: not isinstance(e, (ValueError, KeyError, TypeError)))`, `reraise=True`); send failures never raise into the loop and never auto-approve; the outcome goes to `on_outcome`, which is invoked inside its own try/except with `log.exception`.

**Mode and label:** a `Mode` enum (`SHADOW` constructible; `DEMO`, `LIVE` names only); every outgoing message contains the exact string `SHADOW — no real order` (em dash). Test row "SC5": a message without the label must fail.

---

### test-only rehearsal path (REV-03, O-11 iv) - new module + script

**Analog:** `scripts/demo_rehearsal.py` (2567 lines). Copy: the `RunMode` dry-run vs execute split, `EvidenceRecorder` (lines 400-533: all-in-memory record, `Redactor.from_environ(environ).scrub(text)`, temp file + `os.replace`, LF-only, post-write secret scan that deletes the file on failure), and the rule that a dry run cannot hold an exchange order record (`record_exchange_record` raises `TypeError`, 456-459).

**Requirements (REV-03, D-13):** a separate isolated path (own entrypoint, not `python -m src.paper.runtime`), own signal/test id, `test_only=True` in every record, explicit operator command (blocking-human), it exercises APPROVE then CONFIRM then journal/state transition only; it does not bypass `PAPER_START_ALLOWLIST` in the production path; the analytics reader excludes `test_only` from signal count, trade count, parity, G1..G5 and PAPER-03. Same D-13 isolation (no trade-capable key, no order adapter). The D-13 AST/env/spy tests must be extended to cover this module too (CONSISTENCY row 2 and 25). `PaperRecord` has no `test_only`/mode/confirm-timestamp fields today (journal.py 59-119, 15 fields), so adding them changes record digests: coordinate with `paper_records_digest` (425) pins (RESEARCH Q-K).

---

### `src/paper/shadow_fill.py` (service, streaming + transform) - D-14, D-17

**Analog:** `src/backtest/engine.py` `_Engine._size_and_register` (734-833) and `lifecycle.advance` (454+), `series.ListMinuteSource` (110) / `MinuteSource` protocol (37-51), `ledger.py`, `records.booking_for_event` (199), `funding.funding_events`.

**Rule: called, not copied** (RESEARCH Pattern 5, Anti-Pattern "importing `_Engine`"). Sequence to re-express in order: `risk_fn` inputs from the ledger (`open_positions_for_risk`, `daily_loss_quote`), `evaluate_risk` (already in the tick), `fill_quantity = floor_to_step(planned * cost_model.partial_fill_fraction)`, `protective_levels_for_fill`, `new_plan_state`, `register_exposure`; then per closed 1m: `advance(state, source=..., start_exclusive, end_inclusive, bar)`, `booking_for_event`, `apply_booking`.

**Key signature:**
```python
def advance(state: PlanState, *, source: MinuteSource, start_exclusive: datetime,
            end_inclusive: datetime, bar: Candle | None) -> tuple[PlanState, tuple[LifecycleEvent, ...]]
```
`start_exclusive` is clamped to at least `state.signal_close_utc` (lifecycle.py line ~485), so a later confirm-time start is expressible without changing the simulator (Q-B is a user/planner choice, not decided here).

**Live 1m source:** `ParquetMinuteSource` reads published per-day Parquet only; the REST `markPriceKlines` poll must feed a NEW in-memory `MinuteSource` validated by `validate_minute_series` (`series.py:67`). Existing REST methods: `BinanceUsdmAdapter.klines` (`binance_usdm.py:664`), `mark_klines` (694). Use only these public-data methods. `purity` analog: `tests/test_backtest_purity.py` forbids `src.data`/adapters imports inside `src/backtest`; `shadow_fill.py` lives in `src/paper` so it may adapt, but it must not touch `_Engine`.

**Equity (REV-07, O-09):** `Ledger.start(equity=...)` takes the exact intended initial live equity; if undecided it is a blocking-human checkpoint. Never default it, never use 800.

**Test (SC3):** a one-plan fixture equals the `simulate` trade for the same minutes, byte-equal payload, when eligibility start equals the signal close; spy on `advance`/`new_plan_state` to prove no reimplemented fill rule.

---

### `src/paper/coverage.py` (utility, pure) - D-07, D-22, D-23, REV-01, REV-02, REV-17, REV-18

**Analogs:** `src/analytics/killgate.py` `evaluate` (359-526) for a pure, deterministic, injected-clock evaluator that "never writes or infers"; `src/data/coverage.py` for frozen report dataclasses and UTC handling (UTC internally, Asia/Ho_Chi_Minh only at the print edge, D-06).

**Pattern to copy** (killgate.py 384-390): validate UTC-awareness on every datetime input up front, take priors/inputs as iterables, sort deterministically:
```python
_require_utc(evaluated_at_utc, "evaluated_at_utc")
priors = tuple(prior_evaluations)
for prior in priors:
    _require_utc(prior.evaluated_at_utc, "prior evaluated_at_utc")
```
**Contract (no thresholds invented):** constants carry their D061 label (14 days, 95 percent, tolerance zero; 319.2 h DERIVED = 336 x 0.95, REV-17, not a threshold). Denominator is the whole fixed window; only HEALTHY counts; DEGRADED/DISCONNECTED/PLANNED_RESTART/crash/unknown are uncovered; each gap has a reason code (REV-01). Freeze: a missing/invalid/evidence-less scheduled slot is `EVIDENCE_GAP`, never CLEAN, no interpolation, and the qualifying window restarts with a NEW epoch pin (REV-02, REV-18). Two separate evidence sets: freeze integrity and runtime health (REV-02). O-07 numbers (healthy-feed silence limits, maximum continuous DEGRADED) are inputs supplied by the user, never defaulted (L-09).

**Output:** PASS/FAIL per criterion with the evidence it read, plus `proof_class` so fake-adapter evidence can never yield PASS for SC1/SC2/SC7 (SC9 rule, `tests/test_paper_closure_rule.py`). Tests: `test_paper_coverage.py`, `test_paper_exit_evaluator.py` (constants equal D061 D; a changed constant without a DECISIONS change fails), `test_paper_closure_rule.py`.

**Mismatch to flag to the planner:** `src/paper/freeze.py` currently has no concept of a scheduled slot; `EVIDENCE_GAP` is reconstructed from the Actions run list (Real-vs-Fake table: "only a real run proves"), so the reconciler takes the run list as an input file, not a network call.

---

### `src/paper/attribution.py` + `src/paper/journal.py` (model, CRUD) - D-15, REV-03

**Analog:** itself. Constants: `APPROVAL_DELAY_LAG_SECONDS: int = 30` (attribution.py line 51), `AttributionKind` values `system`, `user-executed-sim`, `opportunity` are byte-exact and read by Phase 10 analytics (do not rename). `journal.py` `assemble_paper_record` (162-377) fixes `acted_at = signal_detected_at_utc + timedelta(seconds=APPROVAL_DELAY_LAG_SECONDS)` (229-231) and RAISES when the caller's `approval["acted_at_utc"]` differs (235-243). Change: when a real approval row exists use `acted_at_utc - requested_at_utc` (plus confirm timestamps); the 30 s constant stays only for records with no human action.

**Downstream pins to update together** (all import the constant): `src/analytics/approval_delay.py:61` (`SYNTHETIC_LAG_LABEL`, line 431-432 `synthetic_lag_seconds=APPROVAL_DELAY_LAG_SECONDS if is_paper else None`), `src/analytics/lifecycle.py:191-230,282,441` (`synthetic_lag` flag), `provenance.py`, `latency.py`. SHADOW measured delay must not carry the SYNTHETIC LAG label. Tests: `tests/test_paper_attribution.py`, `tests/test_analytics_approval_delay.py`, `test_analytics_lifecycle.py`, `test_analytics_latency.py`, plus the new `test_paper_approval_delay_measured.py` ("must FAIL on the assembler overriding a real timestamp with signal + 30 s").

---

### Public-data smoke recorder (script, streaming) - D-10, SC7

**Analog:** `scripts/demo_rehearsal.py` `EvidenceRecorder` (400-533) and `tests/test_demo_rehearsal_safety.py`. Evidence file must carry SDK + binance-common versions, per-interval closed-event counts, forced-disconnect result, the data.binance.vision fetch (G3-026), and pass the redaction scan before it is kept. Schema test only in CI (`tests/test_paper_ws_smoke_evidence.py`); the live run is blocking-human on the connected machine, no key, public market data only.

---

### `tests/test_paper_shadow_isolation.py` (test, static analysis) - D-13, SC6

**Analog (exact):** `tests/test_paper_start_gate.py` AST scan helpers (`_scan_src_violations`, 537-577; `_calls_with_scope`, 499-512; `_bound_names`, 441-467; seeded-violation tests `test_guard_helper_reports_every_seeded_violation`, 586-612; whole-tree assertion at 680-681) and `tests/test_backtest_purity.py` (glob-discover modules, reuse `find_violations` and forbidden sets from `tests/test_analytics_purity.py`).

**Pattern to copy:** a pure `_scan(root: Path) -> list[str]` that returns sorted violation strings, a `_write(tmp_path, rel, text)` helper, one test that seeds every violation form and asserts each is reported, one test that asserts allowed forms return `[]`, and one test that runs on the real tree:
```python
def test_no_module_under_src_enables_the_flag_or_touches_the_allowlist() -> None:
    assert _scan_src_violations(REPO_ROOT / "src") == []
```
**Three layers (D-13):**
1. Structure: AST import-graph over the runtime's module CLOSURE (follow `from src.x import` transitively) must not reach `src.execution.manager`, `src.execution.placement`. Pitfall P16: the order methods live in the same class as the public-data methods (`BinanceUsdmAdapter`, `place_entry` at `binance_usdm.py:1195`, `place_algo_protective` 1262) and the supervisor already imports `Kline` from `binance_usdm.py` (supervisor.py line 38), so a module ban fails; test the call/attribute names instead, or split a public-data adapter, and state which in the plan.
2. Environment: startup refuses when a `BINANCE_LIVE_*`/`BINANCE_TESTNET_*` variable is set (parametrize over prefixes; never print values).
3. Behavior: spy on `execute_approved_plan` and every order endpoint method, drive a full SHADOW APPROVE then CONFIRM, assert zero calls; negative control: the same spy must detect a deliberate call.

---

### `src/research/` runner (service/CLI, batch) - D-24..D-30, REV-04..REV-06, REV-09, REV-10

**Analogs:** `scripts/smoke_backtest_realdata.py` (real-data driver shape), `src/data/case_input.py`, `src/backtest/engine.py` `simulate` (867), `src/backtest/experiment.py` `assemble` (618-767), `src/adapters/code_version.py` (`read_code_version`).

**Input path to copy:** build case input from the collected datasets via `CaseInputData.to_case_input` (case_input.py:153) and bind identity with `dataset_identity` (252-263):
```python
payload = {"files": [{"path": rel, "sha256": entries[rel]} for rel in sorted(entries)]}
return sha256_hex(payload)
```
`assemble(...)` requires `run_summary["dataset_id"] == data_snapshot_id` (experiment.py 704-713) and `data_window == (time_range_start_utc, time_range_end_utc)` (699-703); `experiment_id = sha256_hex(identity_payload)` over 14 fields (732-748). REV-16 decision (redefine `data_snapshot_id` vs a seventh field) is the user's, brought by the protocol-amendment plan; the runner must be written so that field is a single injected value (do not hard-code either route). Tests that carry `data_snapshot_id`: `tests/backtest_case_helpers.py`, `test_backtest_binding.py`, `test_backtest_experiment.py`, `test_analytics_provenance.py`, `test_analytics_render.py`, `test_analytics_report.py`.

**Guard pattern (REV-04/05/06, automated + tested):** refuse to run unless a user-written authorization artifact records BOTH the hash of the parameter grid it is about to run AND the hash of the immutable dataset manifest it is about to use; refuse on a manifest or grid edited after registration; a new iteration is a new registration/experiment. Model the refusal on `assemble`'s fail-closed style: a dedicated exception class (`IncompleteExperimentRecord`-like, naming the cause) raised BEFORE any simulate call. Test must FAIL on: run without artifact; allowlist write; any `simulate` call over the holdout window from the feasibility gate (Q-O, Pitfall P21). `holdout_consumed.json` (schema `holdout-consumed/2`, `protocol_version`, `entries: []`) semantics are validated by `scripts/decision_alignment/protocol.py` (HOLDOUT_TOP_KEYS line 92, checks near 252); read-only for the runner here (Phase 26 owns holdout-once enforcement per `experiment.py` docstring 651).

**Reporting-only rules:** no verdict, no ranking, no allowlist write (grep-style test like start_gate); prints `modeled_costs_per_unit` limitation and count of mark-hole trades separately and unclassified (D-29, REV-09 guard test that None is never read as zero, plus consumer audit of every reader; RESEARCH S3 lists readers); plateau output replaces `PLATEAU_NOTE = "not computed (BKTS-03 pending)"` / `PLATEAU_STATUS_NOT_COMPUTED` (`src/backtest/report.py` 50-51), reporting only; G1 counting rule: closed filled trades with exit SL or TP2 (`_CLOSED_EXIT_KINDS = frozenset({EXIT_SL, EXIT_TP2})`, report.py line 48), `END_OF_DATA` counted apart.

**Candidate registration validator (D-28):** reuse `src/domain/registry.py` load path, `check_rationale_text` and `placeholder_keys_text` (used by `freeze.py:_require_rationalized`, 450-476) to implement "structurally valid, rationalized, preregistered, no PLACEHOLDER, registered and hashed"; print the exact 64-hex hash. Registration is a CI-gated repository change (Pitfall P22); the validator never edits `params/` or the allowlist.

---

### `src/analytics/killgate_guard.py` + registry file + tests (guard, request-response) - D-31, REV-11, REV-15, L-06

**Analogs:** `src/analytics/killgate.py` `registration_allowed` (331-339: pure predicate, `TypeError` on wrong type) and `src/analytics/cli.py` `_run` (714-736) / `_fail` (677-679) / `_EXPECTED_FAILURES` (754-755).

**Predicate shape to copy:**
```python
def registration_allowed(state: KillGateState) -> bool:
    if not isinstance(state, KillGateState):
        raise TypeError("registration_allowed requires a KillGateState")
    return state is not KillGateState.INSUFFICIENT_EDGE
```
**Integration point:** call the guard inside `cli._run` after resolving inputs and BEFORE `build_journal_depth_report(...)` concludes and before `_record_step` appends the `KILL_GATE_EVALUATION` event; a refusal returns exit code 1 via `_fail("...")` (`print(f"Report not produced: {reason}. {_FAILURE_TAIL}", file=sys.stderr)`), consistent with the existing "report not produced" contract. `killgate.evaluate` itself stays pure and untouched (Phase 26 owns the WR designs).

**Registry file (REV-15):** one small versioned file, five items WR-01, WR-06, WR-10, WR-12, WR-13, each `state: UNRESOLVED` (Phase 26 flips with its fix commit), `blocks_report` (WR-01, 06, 12, 13) and `blocks_live_enable` (WR-10). Report guard reads ONLY `blocks_report`. Style analog for a versioned machine-readable decision file: `docs/research/kill_gate_decisions.json` (`_DEFAULT_DECISIONS`, cli.py line 118) and `docs/research/holdout_consumed.json` (schema string + `protocol_version` + `entries`).

**`fixture` classification (REV-11, no existing analog):** there is NO existing real-vs-fixture marker in `src/analytics` (grep for fixture/synthetic returns only the `synthetic_lag` approval label). Design a machine-checkable explicit marker (for example a field in the analytics evidence file read via `src/adapters/analytics_files.py`); anything not explicitly marked fixture is real evidence. Do not reuse `synthetic_lag`.

**Tests (`tests/test_killgate_guard.py`):** refuses real evidence while any of the four is UNRESOLVED; passes fixture input; flipping any one of the four back blocks again; only WR-10 unresolved does NOT block the report guard; an enablement check with WR-10 unresolved IS blocked (Phase 16 supplies the registry reader and the scope test, `LiveEnablementController.enable` itself is Phase 26). Keep existing tests: `tests/test_analytics_cli.py`, `test_analytics_edge_guards.py`, `test_kill_gate_docs.py`.

---

### `docker-compose.yml` `paper` service + soak project - D-01, D-32, SC6

**Analog:** the `collector` service (lines 81-96) and the shared anchors `x-app` (16-28) and `x-database-env` (30-37).

**Current placeholder to replace** (lines 98-110): `profiles: ["paper"]`, `restart: "no"`, a `python -c "raise SystemExit(...)"` command, `healthcheck: disable: true`.

**Pattern to copy (collector):**
```yaml
collector:
  <<: *app
  environment: *database-env
  depends_on:
    db-upgrade:
      condition: service_completed_successfully
  volumes:
    - rawdata:/app/data/raw
    - logs:/app/logs
  command: ["/app/.venv/bin/python", "-m", "src.data.collector"]
  healthcheck:
    test: ["CMD", "/app/.venv/bin/python", "-m", "src.data.collector", "--healthcheck"]
    interval: 60s
    timeout: 15s
    start_period: 6m
    retries: 3
```
Paper: command `["/app/.venv/bin/python", "-m", "src.paper.runtime"]`, its own `--healthcheck` probe, a `logs` volume for `pinned_epoch.json`/`registry_diff.jsonl`, `restart` policy decided by the plan. **Problem to surface (SC6 / WR-06):** `x-app` gives EVERY service `env_file: ${TRADING_ENV_FILE:-.env}` (line 18), so the paper container inherits every variable in `.env`; the per-service split is WR-06 (Phase 24) but the paper service must still not receive a live key. Options for the planner: a dedicated `TRADING_ENV_FILE` for the soak project containing only `POSTGRES_*` and `TELEGRAM_*`, plus the runtime env-allowlist refusal (D-13 layer 2) as the second barrier. The plan must document the env-variable list the `paper` service reads (CONTEXT prerequisites).

**Soak project name:** compose top-level `name: trading` (line 14) can be overridden with `-p`; pick a distinct project (for example `trading-soak`) with its own `pgdata` volume. Pinned image, never a working-tree bind mount: the image tag `trading-alert:${IMAGE_TAG:-dev}` is built on the host by `db-upgrade` (line 17), no registry push exists (D050 deferred), so "digest-pinned image tag produced by CI" needs a recipe the plan must define (RESEARCH Pitfall P19).

**Tests:** `tests/test_deploy_compose.py` pattern: copy the compose file into a tmp project with a `.env` holding only random `POSTGRES_*` values (`_write_project`, lines 38-58), render `docker compose config --format json` with `compose_cli_available()`/`infra_skip` guards, never print the resolved config (it holds secrets). New `tests/test_soak_compose.py`: renders for the soak project; `paper` env lists no `BINANCE_*`; named volumes only (extend `test_all_volume_mounts_are_named_volumes_never_binds`, line 160, and `test_declared_volumes_are_only_the_four_named_volumes`, line 171).

---

### Soak `down -v` guard wrapper (script + test) - D-32

**Analog:** `deploy/lib.sh` (`set -Eeuo pipefail`, `die()`, `log()`, `run()` that prints `+ cmd` and skips under `DRY_RUN=1`, `p()` path prefix test seam) and the script tests `tests/test_deploy_scripts.py`, `tests/test_bootstrap.py` (run real bash through `find_bash`/`infra_skip`, `TRADING_ROOT_PREFIX` seam).

**Pattern:** a wrapper `deploy/compose-soak.sh` that `source`s `lib.sh`, resolves the compose project name the same ways compose does (`-p`, `COMPOSE_PROJECT_NAME`, top-level `name:`; RESEARCH validation row D-32), and `die`s when the subcommand is `down` with `-v`/`--volumes` against the soak project; every other command goes through `run`. The test greps the RUNBOOK and `deploy/` scripts for an unguarded `down -v` against the soak project (analog: the RUNBOOK-vs-files equality checks in `tests/test_deploy_docs.py`). Add a negative control (the guard must refuse a seeded `down -v`).

---

### `docs/operations/RUNBOOK.md`, `docs/GLOSSARY.md`

**Analog:** RUNBOOK sections 11 (backup/restore chain), 13 (bootstrap), 17 ("Only a real host can show"), 16 pin table (`tests/test_deploy_docs.py` parses section 16 and compares it with Dockerfile/compose/workflows, so any image/pin text added must keep that table consistent). Add: soak-host provisioning with the D042 acceptance per condition (EBS default encryption must be CHECKED with `get-ebs-encryption-by-default` in ap-southeast-1, RESEARCH A9/G12), deploys during the trial consume the 5 percent budget (CONSISTENCY row 5), REV-08 S3 versioning/Object Lock study text (Object Lock can be enabled on an existing versioned bucket, versioning must be enabled explicitly, G9), data-path commands over `deploy/restore.sh`, `deploy/migrate.sh`, `src/ops/backup_remote.py`. Re-read `backup_remote.py` first: D064/D066 replaced the `--size-only`/`--checksum` code the research text cites (Gaps Resolution note 2). Glossary: add `CONTEXT_BAR` (confirmed feed-gate reason code), `DUPLICATE_BAR`, `SHADOW`, `EVIDENCE_GAP`, `PLANNED_RESTART`.

---

### Protocol v2.2.0 amendment task (REV-16) - separate prerequisite, ordered BEFORE research run authorization

**Analog:** the v2.1.0 amendment itself (D057/D060). Files that carry the version and must move together: `docs/research/RESEARCH_PROTOCOL.md` header (`> **Protocol version:** vX.Y.Z`, `> **Status:** FROZEN`, `> **Frozen on:**`; parsed by the shell witnesses in `.github/workflows/research-gate.yml` lines 17-50), `docs/DECISIONS.md` row, `docs/DOC_STATUS.md`, `docs/research/holdout_consumed.json` (`"protocol_version": "v2.1.0"` and `"schema": "holdout-consumed/2"`), `scripts/decision_alignment/protocol.py` (HOLDOUT_PATH line 27, `HOLDOUT_TOP_KEYS` line 92, schema check ~252), `tests/test_decision_alignment_protocol.py` (e.g. `test_holdout_real_marker_is_valid`, `test_backtest_spec_pointer_follows_the_header_version` line 206), `tests/test_kill_gate_docs.py`, `docs/backtest/BACKTEST_SPEC.md` pointer. Experiment identity: `src/backtest/experiment.py` lines 236, 263, 296, 426, 623, 704-713, 736, 755, 983-996 (see runner section for the compatibility finding; the field choice goes to the user). No strategy-version bump (`protocol_version` appears nowhere in `src/` or `params/`).

---

## Shared Patterns

### Fail-closed gates and strict typing
**Source:** `src/paper/freeze.py` `require_bool_flag` (405-414), `_require_allowlisted` (422-447), `DiffLogEntry.__post_init__` (162-166).
**Apply to:** `PaperAllowlistEntry`, runtime start gate, runner authorization guard, killgate guard, SHADOW `Mode`.
```python
def require_bool_flag(value: object) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"allow_unrationalized must be a bool, got {type(value).__name__} ({value!r})")
```
An empty or refused state is a valid terminal state; no fallback parameter set.

### Deterministic ids, canonical JSON, injected clocks
**Source:** `src/domain/journal.py` `correlated_event_id` / `content_hash_event_id`; `src/domain/canonical.py` `sha256_hex`; `freeze.py` `to_jsonl` (`sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False`).
**Apply to:** runtime journal rows, `decision_surface` digests, evidence exports, manifests, EVIDENCE_GAP lines. No `datetime.now` in pure paths; every datetime validated UTC-aware (`_require_utc_aware` in `loop.py` 54, `binding.py` 33, `killgate.py` 193).

### Journal-first, then notify; replay idempotency
**Source:** `src/paper/notify.py` 202-331; `src/persistence/journal.py` 85-120; `src/approval/replay.py`.
**Apply to:** every Telegram send in SHADOW, every runtime state write. Journal row committed before the send; callbacks replay to existing state; send failure never raises into the loop and never approves.

### Thread/loop boundary
**Source:** `PaperSupervisor._last_close_lock` (supervisor.py 125-128, 152-157); RESEARCH Pattern 2.
**Apply to:** `runtime.py`. SDK callback only normalises and `put_nowait`s; DB and tick run off the loop (`asyncio.to_thread`); a slow fake DB must not delay queue draining (test).

### Domain boundary and Decimal-only
**Source:** `src/adapters/paper_ws.py` module docstring (SDK types never leak), `tests/test_domain_no_float.py::SCANNED_FILES`, `tests/test_backtest_purity.py`.
**Apply to:** all new `src/paper/*` and `src/research/*` modules: no float for money, SDK types only inside `src/adapters`, new modules added to `SCANNED_FILES` (Wave 0 gap); `src/core` imports only stdlib and Decimal.

### Evidence recording and redaction
**Source:** `scripts/demo_rehearsal.py` `EvidenceRecorder.write` (513-533), `src/ops/redaction.py`.
**Apply to:** smoke evidence, rehearsal evidence, exit-criteria evaluator output, exports. Scrub, atomic replace, LF-only, post-write scan; never print env values or secrets.

### Test conventions
**Source:** `pyproject.toml` (pytest 9.1.1, pytest-asyncio `asyncio_mode = "auto"`, marker `docker`), PG tests on the disposable `_test` DB (`tests/pg_support.py`, `TEST_DATABASE_URL`, `TRADING_CI_STRICT=1`), infra skips via `tests/infra_helpers.py`.
**Apply to:** all new tests; seeded-violation plus real-tree pattern for every static guard; every guard has a negative control. Per-file quick run: `PYTHONPATH=. uv run pytest tests/<file>.py -q -p no:cacheprovider`; repo gates `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` (line length 100, mypy strict on `src`).

### Pinned digests protected by every edit to the paper tick
`tests/test_paper_start_gate.py`, `tests/test_paper_parity.py`, `tests/test_paper_reviewfix_pins.py`, `tests/test_paper_feed_gates.py`, `tests/test_paper_closed_candle.py` (baseline 11 paper test files, 157 tests passed 2026-10-07).

---

## No Analog Found

| File / concern | Role | Data flow | Reason |
|---|---|---|---|
| Machine-checkable `fixture` vs real-evidence marker (REV-11) | guard input | transform | No existing marker in `src/analytics` or `analytics_files.py`; design new, anything unmarked is real |
| Live 1m trade/mark `MinuteSource` over REST polling (D-14) | source | streaming | Only `ListMinuteSource` (in-memory, validated) and `ParquetMinuteSource` (published partitions) exist; build an in-memory live source validated by `validate_minute_series`; mark-price KLINE WS stream existence is UNVERIFIED (A8/G4) |
| Production approval sender, `binding_context_resolver`, PENDING-approval insert and persisted confirm-token store | service | request-response | `issue_one_time_token` / `binding_context_resolver` appear only in `src/approval/tokens.py`, `telegram_callbacks.py` and the in-memory book of `scripts/demo_rehearsal.py` (~927-955); persistence stores exist (`PgApprovalStore`) but nothing calls them in production |
| Scheduled-slot reconstruction for EVIDENCE_GAP from the GitHub run list (REV-02/REV-18) | utility | batch | No existing consumer of Actions run history; GitHub scheduling behaviour is research item G15 (still UNVERIFIED for private repos) |

(Planner use RESEARCH Patterns 1-7 and the Open Questions Q-A..Q-P for these.)

## Open items the planner must carry as blocking-human (nothing in this map decides them)

O-01 durable location (REV-08), O-02 hypothesis/grid, O-03 data window and splits, O-04 allowlist entry, O-06 OQ-1 methodology, O-07 healthy-feed and DEGRADED ceiling numbers, O-09/REV-07 equity, O-10, O-11 commands, O-12 EC2 numbers, Q-A (does a rationalized set need an allowlist entry), Q-B (fill eligibility start), Q-C (exposure for pending plans), Q-D (backfilled bars after reconnect), Q-J (runtime state storage vs the `system_state` CHECK constraint), REV-16 field choice (`dataSnapshotId` redefinition vs seventh field).

## Metadata

**Analog search scope:** `src/adapters`, `src/paper`, `src/approval`, `src/analytics`, `src/backtest`, `src/data`, `src/persistence`, `src/domain`, `src/ops`, `scripts/`, `tests/`, `deploy/`, `.github/workflows/`, `docker-compose.yml`, `docs/research/`.
**Files read for excerpts:** paper_ws.py (full), freeze.py (140-200, 370-480, 690-880), supervisor.py (28-300), notify.py (200-343), killgate.py (325-404), analytics/cli.py (676-759), experiment.py (618-767), case_input.py (236-270), demo_rehearsal.py (396-540), collector.py (1095-1170), docker-compose.yml (full), paper_freeze_check.yml (full), test_paper_start_gate.py (536-690), test_paper_ws_connect.py (1-70), test_backtest_purity.py, test_deploy_compose.py (1-60), domain/journal.py, persistence/journal.py, approval/binding.py, deploy/lib.sh, backtest/lifecycle.py (454-500).
**Pattern extraction date:** 2026-10-08
