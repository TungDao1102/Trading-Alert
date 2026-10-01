---
phase: 07-paper-forward-observation
reviewed: 2026-09-27T00:00:00Z
depth: deep
files_reviewed: 22
files_reviewed_list:
  - src/paper/__init__.py
  - src/paper/loop.py
  - src/paper/resync.py
  - src/paper/supervisor.py
  - src/paper/attribution.py
  - src/paper/journal.py
  - src/paper/freeze.py
  - src/paper/notify.py
  - src/adapters/paper_ws.py
  - src/adapters/telegram_notify.py
  - tests/test_paper_closed_candle.py
  - tests/test_paper_feed_gates.py
  - tests/test_paper_resync.py
  - tests/test_paper_parity.py
  - tests/test_paper_attribution.py
  - tests/test_paper_freeze.py
  - tests/test_paper_notify.py
  - tests/test_domain_no_float.py
  - pyproject.toml
  - .env.example
  - .gitignore
  - .github/workflows/paper_freeze_check.yml
findings:
  critical: 9
  warning: 16
  info: 7
  total: 32
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-09-27T00:00:00Z
**Depth:** deep
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Deep review of the Phase 7 paper-forward-observation slice: WS realtime loop
(`src/paper/loop.py`), REST resync (`resync.py`), WS supervisor
(`supervisor.py`), three-way attribution journaling (`attribution.py`,
`journal.py`), freeze monitor (`freeze.py`), SIMULATE notify (`notify.py`),
both adapters, all 8 test files, plus packaging/ops surface (`pyproject.toml`,
`.env.example`, `.gitignore`, freeze-check workflow).

The per-module logic is carefully written and well-tested in isolation, but
cross-file tracing exposes structural breaks: **backfilled closes are only
logged, never dispatched to the loop**; **`record_close` has no caller so
resync is a permanent silent no-op**; **reconnect exhaustion aborts backfill
entirely**; the **WS adapter has no connect path and silently drops
non-dict messages**; the **loop cannot distinguish 1h from 4h events**;
Telegram `callback_data` **exceeds the 64-byte API limit** with real signal
ids; the **freeze CI workflow runs on an ephemeral runner that discards both
its inputs and its acceptance artifact**; and `notify_simulate` **invokes the
journal callback inside the retry attempt**, turning a journal failure into
duplicate sends. Purity docstrings in three modules also contradict their
actual imports. Nothing here questions intent — every finding below is tied
to exact lines and includes a concrete fix.

## Critical Issues

### CR-01: Resync fetches a single page with no pagination — long outages backfill incompletely

**File:** `src/paper/resync.py:167-173`
**Issue:** `_fetch` issues exactly one `adapter.klines(..., limit=1500)` call
and never pages. A 1h-stream outage longer than 1500 hours (~62 days) returns
a truncated prefix; the function still returns `(closes, gaps)` as if the
backfill were complete. The caller (`supervisor._resubscribe_and_backfill`)
cannot distinguish "complete" from "truncated" — there is no
`truncated: bool` signal, no `end_ms` bound, and no follow-up page from the
last returned close. For a forward-observation soak this silently converts an
unrecovered hole into apparent coverage.
**Fix:**
```python
# Page until the returned page no longer advances toward now_utc:
closes_all: list[Kline] = []
cursor_ms = start_ms
truncated = False
while True:
    page = await adapter.klines(symbol=symbol, interval=interval, start_ms=cursor_ms, limit=1500)
    if not page:
        break
    closes_all.extend(page)
    if len(page) < 1500:
        break
    cursor_ms = int(page[-1].open_time_utc.timestamp() * 1000) + step_ms
    if cursor_ms > int(now_utc.timestamp() * 1000):
        break
else_truncated = len(closes_all) >= 1500 and ...  # surface explicit flag
# Return (closes, gaps, truncated) or raise/journall when truncated.
```

### CR-02: Reconnect exhaustion raises out of `on_disconnect` — backfill never runs on the worst outages

**File:** `src/paper/supervisor.py:171-173,183-203`
**Issue:** `on_disconnect(scheduled=False)` awaits `_reconnect_with_retry()`,
which uses `tenacity.AsyncRetrying(..., reraise=True)`. When all 7 attempts /
120 s are exhausted, the retry raises — so `_resubscribe_and_backfill()` on
line 173 is never reached. The exact scenario that most needs REST backfill
(WS unrecoverable) is the one that skips it, and the exception escapes to
whatever drives the supervisor loop. The per-symbol isolation in
`_resubscribe_and_backfill` is bypassed entirely.
**Fix:**
```python
if not scheduled:
    try:
        await self._reconnect_with_retry()
    except Exception as exc:
        log.error("paper.supervisor.reconnect_exhausted", error=f"{type(exc).__name__}: {exc}")
        # Fall through to resubscribe + backfill regardless.
await self._resubscribe_and_backfill(journal_outage_gaps=True)
```
(For `scheduled=True` the current skip-reconnect path is correct and stays.)

### CR-03: Backfilled closes are log-only and `_last_close` has no producer — resync is a silent no-op end to end

**File:** `src/paper/supervisor.py:209-262`, `src/paper/loop.py:269-474`
**Issue:** Two halves of one break. (a) `_resubscribe_and_backfill` surfaces
backfilled `closes` only via `log.info("paper.supervisor.backfilled", ...)`
(lines 256-262) with an explicit comment that "the supervisor's job is to
surface them in the log so the journal layer can persist them" — but no code
persists them, journals them, or feeds them to `run_paper_tick`. The closes
are dropped on the floor. (b) Backfill is keyed on `self._last_close`, whose
only producer is `record_close()` — and nothing in `src/paper/loop.py` (or
anywhere else in the reviewed tree) calls `record_close`. Until something
wires the dispatch path to the supervisor, `last is None → continue`
(line 218-221) fires for every pair and backfill is skipped silently on every
rotation/disconnect. The whole D-01 resync story is currently unwired.
**Fix:**
```python
# (a) Return the backfilled closes per pair instead of only logging:
async def _resubscribe_and_backfill(...) -> dict[tuple[str, str], list[RestKline]]:
    ...
# (b) Wire the dispatch path — the kline handler must record closes:
def _make_kline_handler(self, symbol, interval):
    def _on_kline(kline):
        if kline.is_closed:
            self._last_close[(symbol, interval)] = kline.close_time_utc
            self._on_closed_candle(kline)
    ...
# ...and the loop entrypoint (or its caller) must convert backfilled
# REST klines into feed_events for run_paper_tick. Until that exists,
# log at ERROR (not silently skip) when last is None after start().
```

### CR-04: WS adapter has no connect path, drops non-dict messages silently, reconnect/close are silent no-ops

**File:** `src/adapters/paper_ws.py:135-184,220-235`
**Issue:** Four compounding defects: (a) `PaperWsAdapter.__init__` constructs
`DerivativesTradingUsdsFuturesWebSocketStreams` but no method ever connects —
`subscribe` calls `kline_candlestick_streams(...)` and registers `on_message`
only `if hasattr(handle, "on_message")`. There is no SDK connect path wired
(the known pre-soak-smoke BLOCKED gap). (b) `_extract_kline_payload` returns
`None` for anything that is not a `dict` — if the SDK delivers response
objects with attributes instead of raw dicts, **every** message is silently
dropped (`if payload is None: return`, line 162-163) with no counter or log.
(c) `_on_message` has no try/except: one malformed payload (`KeyError` on
`t`/`T`/`o`/...) propagates into the SDK dispatch thread and can kill the
stream. (d) `reconnect`/`close`/`schedule_reconnect` guard with `hasattr` and
silently do nothing when the handle lacks the method — the supervisor records
a successful reconnect that never happened (fail-open).
**Fix:**
```python
def _on_message(self, message):
    try:
        payload = _extract_kline_payload(message)
    except Exception as exc:
        log.warning("paper_ws.extract_failed", error=repr(exc))
        return
    if payload is None:
        log.warning("paper_ws.unknown_envelope", message_type=type(message).__name__)
        return
    try:
        kline = _normalize_kline_payload(symbol, interval, payload)
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("paper_ws.normalize_failed", error=repr(exc))
        return
    on_kline(kline)


def reconnect(self, handle):
    if hasattr(handle, "reconnect"):
        handle.reconnect()
    else:
        log.error("paper_ws.reconnect_unsupported", handle_type=type(handle).__name__)
        raise RuntimeError("WS handle has no reconnect; rotation impossible")


# Same fail-loud pattern for close(). Add explicit connect()/start() wiring
# per the installed SDK's lifecycle before the soak; extend
# _extract_kline_payload to attribute-style SDK models with a unit test.
```

### CR-05: Telegram `callback_data` exceeds the 64-byte API limit with real signal ids

**File:** `src/adapters/telegram_notify.py:79-90`
**Issue:** `build_simulate_keyboard` builds `callback_data=f"SIM:{signal_id}"`
and `f"SKIP:{signal_id}"`. Telegram enforces a 64-byte limit on
`callback_data`. The test payload's own signal id
(`sig_test_0000…0000`, ~61 chars) already yields 65 bytes for the `SIM:`
variant — `send_message` will be rejected by the Bot API, turning every
SIMULATE send with a real-length signal id into a FAILED outcome (and burning
the bounded-retry budget on a deterministic rejection).
**Fix:**
```python
def build_simulate_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    short = signal_id[-32:] if len(signal_id) > 32 else signal_id
    # Or: short = hashlib.sha256(signal_id.encode()).hexdigest()[:32]
    assert len(f"SIM:{short}".encode()) <= 64
    ...
```

### CR-06: Freeze CI workflow discards its inputs and its acceptance artifact — hourly ticks prove nothing

**File:** `.github/workflows/paper_freeze_check.yml:48-61`, `src/paper/freeze.py:537-575`
**Issue:** The workflow reads pinned state from
`$github.workspace/logs/paper/pinned_epoch.json` and appends to
`logs/paper/registry_diff.jsonl`, but `logs/` is gitignored (`.gitignore:26`)
and the runner is ephemeral: every hourly run checks out fresh with no
`pinned_epoch.json`, so `load_pinned_state` raises `FileNotFoundError`,
`run_check_cli` returns 2, and the step fails — or, if a bootstrap ever
writes state mid-run, it is discarded when the runner dies. The diff log
(the PAPER-03 acceptance artifact) is likewise never uploaded, committed, or
pushed anywhere. Additionally, `run_check_cli` returns 0 for both clean and
REGISTRY_DIFF rollovers, so a registry drift is green CI with no alert.
**Fix:**
```yaml
# Persist state: restore/save pinned_state + diff log via actions/cache,
# or push the diff-log line to persistent storage (artifact upload at
# minimum, plus a rollover alert):
- uses: actions/cache@v4  # or download/upload-artifact
  with: { path: logs/paper, key: paper-freeze-${{ github.run_id }} ... }
# And in run_check_cli: return a distinct code (e.g. 3) on rollover and
# add a workflow step that pages/alerts on it.
```

### CR-07: `on_outcome` runs inside the tenacity attempt — a journal failure causes duplicate Telegram sends

**File:** `src/paper/notify.py:240-255`
**Issue:** `on_outcome(outcome)` is invoked inside `with attempt:` on the
success path. If the caller's journal-commit callback raises, tenacity treats
it as a retryable failure and re-executes the block — re-sending an already
sent SIMULATE message (up to 3 attempts). Journal-first ordering is thus
inverted for the failure case: a journal fault multiplies sends. Separately,
payload construction (lines 205-221, `payload[...]` KeyErrors) sits outside
any try, so a malformed payload raises out of `notify_simulate` despite the
docstring promise that "send exceptions never raise into the loop".
**Fix:**
```python
sent = False
async for attempt in AsyncRetrying(...):
    with attempt:
        attempts += 1
        await send_simulate(bot, chat_id=chat_id, text=text, keyboard=keyboard)
        sent = True
        break  # exit retry loop BEFORE journaling
outcome = NotifyOutcome(kind=SENT, ...)
try:
    on_outcome(outcome)
except Exception:
    log.exception("paper.notify.on_outcome_failed")  # never retry the send
return outcome
# And validate payload keys up front, converting KeyError into a FAILED
# outcome (or a loud ValueError at format_simulate boundary — pick one
# contract and document it).
```

### CR-08: Feed events carry no interval — a 4h close is silently processed as a 1h bar

**File:** `src/paper/loop.py:193-216`, `src/paper/supervisor.py:132-155`
**Issue:** `_event_to_candle` hardcodes `interval="1h"` and
`run_paper_tick` appends every gated event to the 1h `closed_setup`
(`sorted_1h + [closed_candle]`, line 371). But `PaperSupervisor.start()`
subscribes both `("1h", "4h")` intervals into the same `on_closed_candle`
dispatch, and WS event dicts carry no interval field at all. If a 4h close
ever reaches this path it is mislabeled `1h`, appended to the setup series,
and feeds EMA/signal evaluation as a wrong-timeframe bar — a
wrong-decision defect, not a cosmetic label. The schema gap (no `interval`
on the event) makes the corruption silent.
**Fix:**
```python
def _event_to_candle(event, symbol, interval: str) -> Candle: ...
# Require event["interval"] (or a per-stream caller arg) at the gate:
interval = event.get("interval") or caller_supplied_interval
assert interval in ("1h", "4h")
if interval == "4h":
    # 4h closes update context only — never appended to setup series.
```

### CR-09: Forming-only slot yields neither a close nor a gap — a silent hole the tests bake in

**File:** `src/paper/resync.py:182-205`, `tests/test_paper_resync.py:253-258`
**Issue:** Gap detection diffs `expected_open_times` against
`actual_open_times` built from `raw_page` (line 192, **including** forming
candles), while `closes` is filtered to `close_time_utc <= now_utc` (line
182). A slot whose only exchange row is still forming therefore counts as
"covered" (no gap) yet contributes no close: downstream sees a missing bar
with no gap record. Test 3 (`test_forming_candle_in_page_is_dropped_before_use`)
asserts `len(gaps) == 0` for exactly this shape, pinning the hole as
"correct". The diff must be computed against **closed** rows, with forming
slots either journaled as `forming_at_observed_time` or explicitly deferred.
**Fix:**
```python
actual_open_times = {k.open_time_utc for k in closed}  # not raw_page
# Slots present in raw_page but absent from closed get reason
# "forming_at_observed_time" (retryable) rather than silence.
```

## Warnings

### WR-01: Millisecond→datetime conversion goes through binary float, invisible to the no-float guard

**File:** `src/paper/loop.py:188-190,204-205,257`, `src/adapters/paper_ws.py:73-75`, `src/paper/resync.py:154`
**Issue:** `datetime.fromtimestamp(ms / 1000, tz=...)` divides two ints with
true division, producing a binary float. Sub-millisecond precision loss is
possible on large epoch values, and the `test_domain_no_float` AST walker
cannot see it (no `float()` call, no float literal — `/` is unflagged). The
project's Decimal-only posture (D-12) intends exact time math on the
decision path; timestamps here gate determinism digests.
**Fix:**
```python
from datetime import timezone, timedelta


def _ms_to_utc(ms: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)


# Apply in loop.py (_is_closed_event, _event_to_candle, check_feed_freshness),
# paper_ws.py, and resync.py start_ms/interval arithmetic.
```

### WR-02: Resync and notify retry on *all* exceptions, including programming errors

**File:** `src/paper/resync.py:157`, `src/paper/notify.py:237`
**Issue:** `tenacity.retry_if_exception(lambda _e: True)` (resync) and
`retry_if_exception_type(Exception)` (notify) retry `ValueError`,
`KeyError`, `TypeError` — bugs that will never succeed on retry — burning up
to 120 s / 30 s of wall-clock and, worse, masking deterministic faults as
transient ones in logs. Contrast `fetch_page_with_retry` in
`src/data/backfill.py:205`, which correctly retries only rate-limit errors.
**Fix:**
```python
retry = tenacity.retry_if_exception_type((ConnectionError, TimeoutError))
# Plus the adapter's is_rate_limit_error where SDK types are available;
# let ValueError/KeyError/TypeError propagate immediately.
```

### WR-03: Warmup gate shadows the staleness gate — stale feeds misreport as WARMUP_INSUFFICIENT

**File:** `src/paper/loop.py:340-364`
**Issue:** `warmup_reject` is evaluated before `check_feed_freshness` per
event, so a feed that is both under-warmed and stale reports
`WARMUP_INSUFFICIENT` for every event. Operators triaging a DATA_STALE outage
during a fresh stream see the wrong reason code. Either order masks one
signal; the staleness (liveness) signal should win, or both codes should be
recorded.
**Fix:** Check `check_feed_freshness` first, or emit a combined record
(`reason_code="DATA_STALE"`, plus `warmup_insufficient: true` in the record).

### WR-04: Re-delivered bars are not deduplicated against warmed-up history

**File:** `src/paper/loop.py:371-372`
**Issue:** `closed_setup = sorted_1h + [closed_candle]` unconditionally
appends. After a reconnect, REST backfill or a WS duplicate can re-deliver an
`open_time_utc` already present in `sorted_1h` (the feed-gates test itself
works around this by slicing off the last warmed bar,
`test_paper_feed_gates.py:156`). In production a duplicate open_time enters
`evaluate()` — behavior then depends on whatever the feature layer's
duplicate-bar guard does, which this module does not verify.
**Fix:**
```python
if any(c.open_time_utc == closed_candle.open_time_utc for c in sorted_1h):
    no_trade_records.append(
        {"reason_code": "DUPLICATE_BAR", "bar_close_utc": ..., "stage": "feed_gate"}
    )
    continue
```

### WR-05: `assemble_paper_record` ignores half its inputs and has silent precedence rules

**File:** `src/paper/journal.py:218-343`
**Issue:** (a) The filled-simulation branch checks presence of
`approval`/`order`/`fill` but never reads `approval`'s contents — the
simulated `acted_at_utc` is `signal_time + lag`, so a caller-supplied
`approval["acted_at_utc"]` that disagrees is silently ignored. (b) A partial
leg (e.g. approval present, order None) falls through to the skip/expired
checks and raises the generic "requires either…" `ValueError` — a confusing
error for a shape that deserves its own `PARTIAL_LEG` rejection. (c) If both
`skip_reason` and `expired_at_utc` are set, skip wins silently (line 263
before 301). (d) `skip_reason=""` (empty) is accepted and yields an
opportunity row with an empty reason; `assemble_no_trade_record` likewise
accepts `reason_code=""` (lines 351-385, no validation).
**Fix:**
```python
if skip_reason is not None and expired_at_utc is not None:
    raise ValueError("ambiguous outcome: skip_reason and expired_at_utc both set")
if skip_reason is not None and not skip_reason:
    raise ValueError("skip_reason must be non-empty")
if not reason_code:  # assemble_no_trade_record
    raise ValueError("reason_code must be non-empty")
# Cross-check approval["acted_at_utc"] against simulated lag (warn or assert).
```

### WR-06: `assert` used for production validation; `__import__` hack for UTC

**File:** `src/paper/journal.py:130,215`
**Issue:** Line 215 uses `assert signal_detected_at_utc is not None` —
stripped under `python -O`, turning a fail-closed check into `None +
timedelta` → `TypeError` at best. Line 130 reaches UTC via
`__import__("datetime").UTC` instead of a module import, defeating static
analysis and readability for no reason.
**Fix:**
```python
from datetime import UTC

signal_detected_at_utc = _parse_utc(signal["detected_at_utc"])
if signal_detected_at_utc is None:
    raise ValueError("signal['detected_at_utc'] must be present")
```

### WR-07: Freeze computes the registry hash two different ways; `StreamEpoch` validation is asymmetric

**File:** `src/paper/freeze.py:227-296,99-115`
**Issue:** `pin_stream_epoch` hashes via `_load_parameter_set_with_root`
while `check_registry_unchanged` hashes via `_recompute_parameter_set_hash` —
two hand-rolled constructions of the same canonical payload that must stay
byte-identical forever. Any future field added to one path (but not the
other) converts every clean tick into a phantom REGISTRY_DIFF rollover.
Separately, `__post_init__` validates `parameter_set_hash` as 64-lower-hex
but never validates `epoch_id` shape, and `_make_epoch_id` accepts naive
`opened_at_utc` without complaint (naive vs aware same-wall-time produce
different hashes via `canonical_scalars`' naive-raise… actually raise — so a
naive open time crashes pin with an unrelated error message).
**Fix:** Single `_canonical_parameter_set_hash(strategy_version,
parameter_set_id, params)` helper used by both paths; validate `epoch_id`
as 64-hex; `_require_utc_aware(opened_at_utc)` at the top of
`pin_stream_epoch` and `_make_epoch_id`.

### WR-08: `start()` is not idempotent; close failures are swallowed unconditionally

**File:** `src/paper/supervisor.py:132-141,264-276`
**Issue:** Calling `start()` twice without `stop()` double-subscribes every
pair (handles list grows, two callbacks per close). `_resubscribe_and_backfill`
happens to close first, but any external double-start duplicates the stream.
`_close_all_handles` catches bare `Exception` and continues — correct
resilience, but the only record is a `log.warning` with `handle_id`; repeated
close failures across rotations are indistinguishable from one-offs.
**Fix:** Guard `start()` with `if self._handles: raise/log` (explicit
restart via `_resubscribe_and_backfill` only); include symbol/interval in the
close-failed log and count consecutive failures.

### WR-09: "Per-symbol isolation journals its gap" — it only logs; no gap record exists

**File:** `src/paper/supervisor.py:230-240`
**Issue:** The except path on backfill failure calls `log.warning(...)` and
`continue`s. No `CollectorGap`-shaped dict is built, returned, or persisted —
contradicting the module docstring ("one failing pair journals its gap")
and the D-01 resync contract. A failed pair leaves neither closes nor a gap
row: the hole is invisible to the journal.
**Fix:** Build the gap dict (same shape as `resync` gaps, reason
`backfill_exception:<ClassName>`) and return it alongside closes so the
caller persists it; only downgrade to log-only with an explicit comment.

### WR-10: Parity projection drops every signal-less record — strategy-stage divergence is invisible

**File:** `tests/test_paper_parity.py:108-124`, `src/paper/loop.py:387-395`
**Issue:** `_project_paper_verdicts` keeps only `no_trade_records` with
`signal_id is not None`, i.e. planner/risk stages. Strategy-stage NO_TRADEs
(no signal emitted — the common case) are excluded from both digests, so the
parity gate is vacuous for the strategy decision itself: paper and backtest
could disagree on every setup signal (both emitting nothing-projected) and
still match. The warmup window is likewise vacuous (paper emits
WARMUP_INSUFFICIENT with no signal_id; simulator behavior there is
unprojected).
**Fix:** Project `(bar_close_utc, signal_id_or_None, reason_code, stage)` for
*all* records on both sides (simulator: emit per-bar strategy outcomes, not
only trades), and assert equality on the full sequence.

### WR-11: `format_simulate` accepts naive datetimes and empty TP lists without complaint

**File:** `src/paper/notify.py:119-169`
**Issue:** `expiry_utc.astimezone(UTC)` on a naive datetime silently assumes
local system tz — on a soak host set to anything but UTC the rendered expiry
is wrong while looking canonical. `take_profits=[]` renders `"TPs:\n\n"`, a
malformed message no test covers. No field is validated (empty symbol,
negative risk, inverted entry_min/max all render happily).
**Fix:** `_require_utc_aware(expiry_utc/detected_at_utc)` (reuse the loop's
helper); `if not take_profits: raise ValueError`; light sanity checks
(entry_min <= entry_max, non-empty symbol/direction).

### WR-12: FAILED outcome reports the tenacity wrapper, not the root cause

**File:** `src/paper/notify.py:256-259`
**Issue:** On exhaustion `last_error` is the tenacity `RetryError`, so
`error_class="RetryError"` is journaled — the underlying
(e.g.) `TelegramError`/`TimeoutError` is lost. Triage of Telegram outages
from `JournalEvent` rows cannot see the real class.
**Fix:**
```python
except RetryError as exc:
    last_error = exc.last_attempt.exception() if exc.last_attempt else exc
```

### WR-13: Purity docstrings contradict actual imports in three modules

**File:** `src/paper/resync.py:11-14`, `src/paper/supervisor.py:16-19`, `src/paper/freeze.py:41-44`
**Issue:** `resync.py` claims "imports only stdlib + tenacity + structlog +
sibling modules" but imports `src.adapters.binance_usdm` (which imports the
Binance SDK) and `src.data.backfill`. `supervisor.py` makes the same claim
while importing both adapters. `freeze.py` claims "stdlib +
`src/core/_decimal.py` only" while importing `src.backtest.binding`,
`src.backtest.costs`, and `src.domain.registry`. The claims are load-bearing
for reviewers checking the adapter-boundary discipline — stale claims train
reviewers to skip the import block.
**Fix:** Correct each docstring to the real contract (e.g. resync:
"adapter-surface owner for REST backfill; SDK types enter only as `Kline`
values via `binance_usdm`"), or refactor to the claimed purity with Protocols.

### WR-14: Gate helpers parse `event["T"]` without validation; tz anchoring follows the caller

**File:** `src/paper/loop.py:178-190,244-261`
**Issue:** `_is_closed_event` does `int(event["T"])` — a missing `T` raises
bare `KeyError`, a non-numeric `T` raises unadorned `ValueError`, and a
missing `x` defaults to `False` (silent drop, uncounted distinctly from
future-close drops). `datetime.fromtimestamp(ms/1000, tz=now_utc.tzinfo)`
anchors conversion to whatever tz `now_utc` carries instead of UTC; today
callers pass UTC, but a non-UTC `now_utc` silently shifts the comparison
basis. `check_feed_freshness` repeats the same unvalidated parse (third parse
of `T` per event including `_event_to_candle`).
**Fix:** Single `_parse_event_close(event) -> datetime` helper with explicit
`KeyError→ValueError("event missing 'T'")` translation, UTC-anchored; count
malformed events separately from gated drops.

### WR-15: CLI `--strategy-id/--parameter-set-id` are decorative — pinned file wins silently

**File:** `src/paper/freeze.py:537-575`
**Issue:** `run_check_cli` accepts `strategy_id` and `parameter_set_id` but
never references them: the check uses `pinned_epoch.strategy_id /
parameter_set_id` from the state file. An operator invoking the CLI for pair
B against a state file pinned for pair A gets a check of A reported as
success, with no mismatch error.
**Fix:**
```python
if strategy_id != pinned_epoch.strategy_id or parameter_set_id != pinned_epoch.parameter_set_id:
    log.error(...)
    return 1
```

### WR-16: `pyproject.toml` mypy `files` key is not a valid mypy config option

**File:** `pyproject.toml:76-83`
**Issue:** `[tool.mypy] files = ["src"]` — mypy has no `files` configuration
option (source paths are CLI positionals / `mypy_path` is for imports). At
best the key is ignored with an "unrecognized option" warning and bare
`mypy` checks nothing; at worst it errors, depending on version. Either way
the intended `strict = true` over `src/` is not enforced the way the author
believes.
**Fix:** Remove `files`; enforce scope via CI invocation (`mypy src`) or
`[[tool.mypy.overrides]]` with `module = [...]`.

## Info

### IN-01: Dead identity helpers in journal.py

**File:** `src/paper/journal.py:133-156`
**Issue:** `_identity_from_signal` and `_identity_from_no_trade` are defined
but never called — `assemble_paper_record` builds the identity inline
(lines 204-212) with a different key layout (`signal_id` flat vs
`signal.signal_id` nested). Dead code with a divergent schema invites a
future caller to use the wrong shape.
**Fix:** Delete both helpers, or route the assembler through them so one
layout is canonical.

### IN-02: `__init__.py` barrel omits the resync/supervisor surface

**File:** `src/paper/__init__.py:14-61`
**Issue:** The barrel re-exports attribution, freeze, journal, loop, and
notify symbols but not `backfill_missed_closes`, `PaperSupervisor`, or the
resync/supervisor retry constants — the two modules with the most
operator-tunable ceilings. Consumers import from two depths inconsistently.
**Fix:** Export `backfill_missed_closes`, `PaperSupervisor`, and the
`RESYNC_*`/`SUPERVISOR_*` constants (or document that the barrel is
loop/journal-only by design).

### IN-03: Retry ceilings are duplicated between resync and supervisor

**File:** `src/paper/resync.py:44-47`, `src/paper/supervisor.py:45-48`
**Issue:** `RESYNC_*` and `SUPERVISOR_*` are identical value-for-value copies
with a comment asking humans to keep them in sync. The next tuning change
will update one and miss the other.
**Fix:** Define once (e.g. `src/paper/retry.py`) and import in both modules;
keep re-exports for the existing constant names.

### IN-04: Freeze workflow hardcodes the strategy pair

**File:** `.github/workflows/paper_freeze_check.yml:55-61`
**Issue:** `--strategy-id trend-pullback --parameter-set-id baseline-v3` are
baked into the workflow. Any soak on another pair requires editing CI rather
than workflow_dispatch inputs.
**Fix:** Add `workflow_dispatch.inputs.strategy_id/parameter_set_id` with the
current values as defaults.

### IN-05: SKIP button ships an operator-confusing label and a future-handler-shaped prefix

**File:** `src/adapters/telegram_notify.py:85-87`, `src/paper/notify.py:222`
**Issue:** The visible label `"SKIP (Phase 8)"` tells the operator about
internal phasing instead of consequence ("no action taken"), and
`callback_data="SKIP:<id>"` reserves a verb prefix a Phase-8 handler will
dispatch on — an accidental Phase-8 deploy could treat these inert Phase-7
messages as live SKIP commands.
**Fix:** Label `"SIMULATE only — no action"`; namespace Phase-7 callbacks
(e.g. `P7-SKIP:<id>`) so no future dispatcher matches them without migration.

### IN-06: `.env.example` and `.gitignore` secret posture is sound — keep it

**File:** `.env.example:1-60`, `.gitignore:35-37`
**Issue:** None found: Telegram token / chat id / paper DB URL are
comment-only placeholders, the Postgres password is an obvious
`change_me…` placeholder, and `.env`/`.env.local` plus `logs/` are ignored.
No secret material in tree. Positive note only — no action, but do not
regress: never paste a real `TELEGRAM_BOT_TOKEN` into the example even
temporarily.
**Fix:** No fix needed.

### IN-07: `test_domain_no_float` scan list is current for Phase 7 — extend as new pure modules land

**File:** `tests/test_domain_no_float.py:53-64`
**Issue:** The guard covers `src/paper/{__init__,loop,attribution,journal,freeze,notify}.py`
and `src/adapters/paper_ws.py` but not the new `resync.py`, `supervisor.py`,
or `telegram_notify.py`. `resync.py`/`supervisor.py` legitimately touch
adapter types, but the guard's value is precisely in forcing an explicit
decision per file.
**Fix:** Add the three files to `SCANNED_FILES` with a comment recording the
verdict for each (clean vs exempt-with-reason).

---

_Reviewed: 2026-09-27T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
