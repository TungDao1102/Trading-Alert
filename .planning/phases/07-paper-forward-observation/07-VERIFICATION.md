---
phase: 07-paper-forward-observation
verified: 2026-10-03T00:00:00Z
status: passed
score: 1/3 success criteria fully verified (SC2); SC1 and SC3 verified at module and fake level only, live and wall-clock halves deferred to Phase 16 or open
covered_files:
  - .planning/phases/07-paper-forward-observation/07-01-PLAN.md
  - .planning/phases/07-paper-forward-observation/07-01-SUMMARY.md
  - .planning/phases/07-paper-forward-observation/07-02-PLAN.md
  - .planning/phases/07-paper-forward-observation/07-02-SUMMARY.md
  - .planning/phases/07-paper-forward-observation/07-03-PLAN.md
  - .planning/phases/07-paper-forward-observation/07-03-SUMMARY.md
  - .planning/phases/07-paper-forward-observation/07-04-PLAN.md
  - .planning/phases/07-paper-forward-observation/07-04-SUMMARY.md
  - src/adapters/paper_ws.py
  - src/adapters/telegram_notify.py
  - src/paper/__init__.py
  - src/paper/attribution.py
  - src/paper/freeze.py
  - src/paper/journal.py
  - src/paper/loop.py
  - src/paper/notify.py
  - src/paper/resync.py
  - src/paper/supervisor.py
covered_digest: "v2:sha256:827ddb2f51eab6ef29aa01e0537f5d9dad3227c14ba4b4fe0800fb0c8e2998d6"
behavior_unverified: 1
overrides_applied: 0
gaps: []
deferred:
  - truth: "Paper engine ingests live WS market data (subscribe against a live connection delivers closed-candle events to the supervisor)"
    addressed_in: "Phase 16"
    evidence: "Phase 16 SC1 'supervisor -> tick -> journal writer chain is composed and runnable as a process (M3) (F-201)' and SC2 'The WS adapter awaits the async SDK call. Fakes are contract-bound to the SDK's async signatures (F-125, F-607)'"
  - truth: "A runnable paper process exists so forward observation can start"
    addressed_in: "Phase 16"
    evidence: "Phase 16 goal 'A runnable paper process observes the corrected families forward, so the wall-clock-bound soak can finally start'"
behavior_unverified_items:
  - truth: "SC3: forward observation accumulates over the 3-6 month wall-clock envelope with zero tuning (registry diff proves no parameter change touched the running stream)"
    test: "After Phase 16 starts the soak: pin the stream epoch (pin_stream_epoch), run the hourly `python -m src.paper.freeze` check for the soak window, then inspect logs/paper/registry_diff.jsonl and pinned_epoch.json"
    expected: "One epoch_id for the whole window, every diff-log line CLEAN, no REGISTRY_DIFF epoch rollover, pinned hash unchanged"
    why_human: "Wall-clock property. The freeze monitor logic is unit-tested on fixtures, but no stream has ever been pinned (logs/paper holds only soak_smoke.log, no pinned_epoch.json or registry_diff.jsonl), so no accumulation exists to inspect."
human_verification: []
---

# Phase 7: Paper Forward Observation Verification Report

**Phase Goal:** Forward evidence accumulates over wall-clock time. The schedule long pole runs without contaminating itself.
**Verified:** 2026-10-03
**Status:** passed (closed by operator decision on 2026-10-04 with the goal only partly achieved; see the final section)
**Re-verification:** No, initial verification

## Goal Achievement

The goal as written (evidence accumulating over wall-clock time) is **not yet achieved**: no paper process exists, the live WS path is broken, and no stream epoch has been pinned. What Phase 7 did deliver is the pure, tested library layer that a runnable soak needs. That layer is real and substantive (3,659 lines in 10 source files, 9 test files), not stubs. The plans themselves declared the WS leg "BLOCKED-follow-up" in 07-04-SUMMARY.md, and the audit re-plan moved the fix to Phase 16.

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Paper engine ingests WS market data with warm-up/reconnect/resync, evaluates closed candles only, and journals gaps without fabricating signals | VERIFIED at module level with fakes; live ingestion NOT achieved (deferred to Phase 16) | Present and tested: double closed-candle gate and warm-up/staleness gates (`src/paper/loop.py`, `STALENESS_THRESHOLD_SECONDS=60`, `WARMUP_MIN_BARS=200`), tenacity-bounded reconnect, 24h rotation as scheduled resubscribe, REST backfill with explicit gap dicts and no fabrication (`src/paper/resync.py`, `src/paper/supervisor.py`), parity digest vs `simulator.run` (`tests/test_paper_parity.py`). Not achieved live: `src/adapters/paper_ws.py:160` calls `self._ws.kline_candlestick_streams(...)` without `await`, but the installed SDK method is a coroutine function (checked here: `iscoroutinefunction` is True), and `subscribe` raises `RuntimeError("dispatch unwired")` when the handle has no `on_message`. `logs/paper/soak_smoke.log` records `ws_subscribe=BLOCKED`, 0 events in 30s. Nothing outside tests and `__init__` constructs `PaperSupervisor`, `PaperWsAdapter` or calls `run_paper_tick` (grep over `src` and `scripts`): there is no `__main__`/composition. |
| SC2 | Paper loop records system vs user-executed vs opportunity attribution with signal/approve/order/fill timestamps | VERIFIED | `src/paper/attribution.py` (`AttributionKind` = system, user-executed-sim, opportunity) and `src/paper/journal.py` (`assemble_paper_record`: filled gives system plus user-executed-sim, skipped and expired give system plus opportunity with reason code, no delete path). 16 tests in `tests/test_paper_attribution.py` including ORM round-trips onto existing SignalRow/TradePlanRow/ApprovalRow/JournalEventRow; pinned golden digests. Operator smoke log shows a real Postgres journal round-trip PASS. Caveat: fill timestamps come from the caller, since the paper loop does not yet simulate fills, and the approval lag is a fixed 30 s constant (`APPROVAL_DELAY_LAG_SECONDS`); both are scheduled for Phase 16 SC3. |
| SC3 | Forward observation accumulates over the 3-6 month wall-clock envelope with zero tuning (registry diff proves no parameter change touched the stream) | PRESENT_BEHAVIOR_UNVERIFIED (mechanism verified on fixtures; accumulation not started) | `src/paper/freeze.py` (713 lines): `pin_stream_epoch` refuses `CostModelBindingMismatch`, `check_registry_unchanged` re-hashes and opens a new epoch on diff while keeping the old pinned hash append-only, hourly CLI, `.github/workflows/paper_freeze_check.yml`. 6 tests in `tests/test_paper_freeze.py` pass. But no soak has run: `logs/paper/` contains only `soak_smoke.log`. The criterion is a wall-clock outcome that cannot exist before Phase 16 lets the soak start. |

**Score:** 1/3 fully verified (SC2). SC1 partial with live half deferred; SC3 counted as behavior-unverified, excluded from the verified score.

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|--------------|----------|
| 1 | Live WS ingestion (await of async SDK call, dispatch wiring, live smoke) | Phase 16 | SC2 "The WS adapter awaits the async SDK call (F-125, F-607)" |
| 2 | Runnable paper process composing supervisor, tick and journal writer | Phase 16 | SC1 "composed and runnable as a process (M3) (F-201)" and goal "so the wall-clock-bound soak can finally start" |
| 3 | Simulated fills with Phase-14 semantics, measured approval delay, functional SIMULATE buttons | Phase 16 | SC3 (F-961) |
| 4 | Pre-registered quantitative paper exit criteria | Phase 16 | SC4 (F-023) |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/paper/loop.py` | Closed-candle dispatch through shared evaluate, plan, evaluate_risk | VERIFIED | 562 lines; called only from tests (no production caller) |
| `src/paper/supervisor.py` | Rotation, bounded reconnect, per-symbol isolation | VERIFIED (library) | 464 lines; no production constructor |
| `src/paper/resync.py` | REST backfill and gap records | VERIFIED | 287 lines; paginated, integer-ms arithmetic |
| `src/paper/attribution.py`, `src/paper/journal.py` | Three-way attribution and record assembly | VERIFIED | 54 and 488 lines |
| `src/paper/freeze.py` | Pinned-epoch freeze monitor | VERIFIED (library) | 713 lines; never run against a real stream |
| `src/paper/notify.py`, `src/adapters/telegram_notify.py` | Journal-first SIMULATE notify, inert callbacks | VERIFIED | Operator smoke: message_id=26 delivered |
| `src/adapters/paper_ws.py` | Live WS adapter | ORPHANED / BROKEN LIVE | No production caller; missing `await` on coroutine SDK method; handle dispatch unwired |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| paper_ws adapter | supervisor / loop | `on_kline` callback | NOT_WIRED live | Only injected fakes in tests |
| supervisor | loop `run_paper_tick` | `on_closed_candle` | NOT_WIRED in production | No composition module |
| loop outcome | journal / notify | `assemble_paper_record`, `notify_simulate` | NOT_WIRED in production | Tested through unit and smoke scripts under `temp/` only |
| freeze monitor | cost binding | `assert_cost_model_binds_registry` | WIRED | `test_pin_mismatch_raises_cost_model_binding_mismatch` passes |
| paper loop | backtest engine | shared `evaluate`/`plan`/`evaluate_risk` | WIRED | Parity test passes |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| paper_ws `subscribe` | kline events | Binance WS | No (0 events in 30 s live) | DISCONNECTED live |
| resync | missed closes | `BinanceUsdmAdapter.klines` (REST) | Yes (smoke rows=5) | FLOWING |
| journal | PaperRecord rows | caller-supplied outcome | Yes (smoke Postgres round-trip) | FLOWING |

### Behavioral Spot-Checks and Command Results

| Check | Command | Result | Status |
|-------|---------|--------|--------|
| Phase 7 test files | `python -m pytest tests/test_paper_closed_candle.py tests/test_paper_feed_gates.py tests/test_paper_resync.py tests/test_paper_parity.py tests/test_paper_attribution.py tests/test_paper_freeze.py tests/test_paper_notify.py tests/test_paper_supervisor_backfill.py tests/test_domain_no_float.py -q` | all pass | PASS |
| Review-fix pins and WS connect tests | `python -m pytest tests/test_paper_ws_connect.py tests/test_paper_reviewfix_pins.py -q` | all pass | PASS |
| ruff | `python -m ruff check src/paper src/adapters/paper_ws.py src/adapters/telegram_notify.py tests/test_paper_*.py` | All checks passed | PASS |
| mypy | `python -m mypy src/paper src/adapters/paper_ws.py src/adapters/telegram_notify.py` | no issues in 10 source files | PASS |
| SDK coroutine check | `inspect.iscoroutinefunction(...kline_candlestick_streams)` (offline import) | True, adapter does not await | Confirms live defect |

No network, Docker, or database was used.

### Probe Execution

SKIPPED: no probe scripts declared for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PAPER-01 | 07-01, 07-02 | Realtime paper engine ingests WS data with warm-up/reconnect/resync, closed candles only, gaps journaled | PARTIAL | Logic verified with fakes; live WS broken and unwired (Phase 16) |
| PAPER-02 | 07-03 | system vs user vs opportunity attribution with timestamps | SATISFIED in library | Fill simulation and measured delay come in Phase 16 |
| PAPER-03 | 07-04 | Evidence accumulates 3-6 months with no tuning | NOT YET (mechanism only) | Freeze monitor tested; no soak running |

REQUIREMENTS.md still lists PAPER-01..03 as Pending, which is consistent with this finding. ROADMAP.md line 43 shows Phase 7 as unchecked while 4/4 plans are checked.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/adapters/paper_ws.py` | 160 | Un-awaited coroutine call to SDK | Warning (live blocker, deferred to Phase 16 F-125) | Live subscribe cannot work |
| `src/adapters/paper_ws.py` | ~203 | `RuntimeError` "dispatch unwired (pre-soak wiring required)" | Warning | Fail-loud by design, still unfinished |
| `src/paper/*` | n/a | No TBD/FIXME/XXX markers | None | Debt-marker gate clean |

### Human Verification Required

1. **Scope acceptance.** Confirm that Phase 7 stays closed as the library layer while PAPER-01..03 remain Pending and are delivered end to end in Phase 16. Expected: an explicit operator decision, since REQUIREMENTS.md and ROADMAP.md disagree on completion today.
2. **SC3 soak evidence (after Phase 16).** Pin the epoch, run the hourly freeze check for the soak window, then confirm that `logs/paper/registry_diff.jsonl` is all CLEAN with one epoch_id. Cannot be observed now.

### Gaps Summary

No success criterion fails in a way that Phase 7 alone could still fix: the unmet halves (live WS, composed process, soak start) are explicitly Phase 16 scope, so they are recorded as deferred rather than gaps. The phase goal itself, wall-clock accumulation, is not achieved and should not be read as complete evidence. Until Phase 16 lands, no forward paper evidence exists, and nothing in Phase 7 should be cited as such.

---

_Verified: 2026-10-03_
_Verifier: Claude (gsd-verifier)_

## Closed by Operator Decision (2026-10-04)

The operator chose to close Phase 7 as delivered at library and fake level. **The phase goal is not achieved in practice.** No paper process runs, and no forward evidence accumulates yet.

| What is done | What is NOT done (and who owns it) |
|--------------|------------------------------------|
| Closed-candle tick, supervisor, REST resync, backtest parity gate, three-way attribution journaling, freeze monitor and SIMULATE notification, all tested with fakes (SC2 attribution fully verified). | Live WS ingestion: `PaperWsAdapter` calls the async `kline_candlestick_streams` without `await`; `soak_smoke.log` records `ws_subscribe=BLOCKED` with 0 events. **Phase 16.** |
| | Process composition: nothing in `src` or `scripts` outside tests constructs the supervisor, WS adapter or loop. **Phase 16.** |
| | SC3 wall-clock soak: no `pinned_epoch.json` or `registry_diff.jsonl` exists; the registry diff log must be checked after the Phase 16 soak. **Phase 16.** |

Requirements PAPER-01, PAPER-02 and PAPER-03 stay **Pending** in REQUIREMENTS.md until Phase 16 delivers them. Marking Phase 7 done must not be read as these requirements being met.
