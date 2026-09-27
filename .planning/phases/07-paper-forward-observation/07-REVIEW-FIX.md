---
phase: 07-paper-forward-observation
fixed_at: 2026-09-27T09:56:43Z
review_path: C:\Users\daotu\OneDrive\Documents\Trading-Alert\.planning\phases\07-paper-forward-observation\07-REVIEW.md
iteration: 1
findings_in_scope: 25
fixed: 25
skipped: 0
status: all_fixed
---

# Phase 07: Code Review Fix Report

**Fixed at:** 2026-09-27T09:56:43Z
**Source review:** `.planning/phases/07-paper-forward-observation/07-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 25 (9 Critical + 16 Warning; 7 Info out of scope under `critical_warning`)
- Fixed: 25
- Skipped: 0

**Verification (where it ran):** `workflow.use_worktrees` is `false` in
`.planning/config.json`, so all edits, tests, and commits ran directly in the
main checkout (no isolated worktree). Per-fix: Tier 1 re-read always; Tier 2
`ast.parse` syntax check on every edited Python file plus targeted pytest runs
after each fix. Final gate: all 8 Phase-7 test files green (48 passed,
including 1 new test), `ruff check` clean on all touched files. The analyzer's
"structlog/tenacity/binance_sdk unresolved import" LSP notices are a
missing-deps artifact of the lint environment, not the code (the `.venv`
test runs import everything fine). `ruff format --check` deviations in these
files are pre-existing repo style (present at baseline, including lines never
touched here), so no reformatting churn was introduced. Commits used plain
`git` (the `gsd-tools.cjs` shim / `gsd_run` entrypoint is not installed on
this machine); messages follow the `fix(07): {id} {description}` convention.

**Commit grouping note:** one commit per finding, except where fixes to the
same function are textually interdependent (shared helpers / single control
flow) — those share one atomic commit and the shared hash is recorded under
each finding. Grouped: loop.py (CR-08 + WR-01 + WR-03 + WR-04 + WR-14),
paper_ws.py (CR-04 + WR-01), notify.py (CR-07 + WR-02 + WR-11 + WR-12),
journal.py (WR-05 + WR-06), freeze.py code (WR-07 + WR-13 + WR-15 + CR-06
exit-code).

## Fixed Issues

### CR-01: Resync fetches a single page with no pagination

**Files modified:** `src/paper/resync.py`
**Commit:** `1bf76b3`
**Applied fix:** `backfill_missed_closes` now pages `adapter.klines` from
`start_ms`, advancing the cursor past each full page's last `open_time_utc`
until a short/empty page or the cursor passes `now_utc`. Each page fetch keeps
the bounded tenacity retry. A 200-page safety cap prevents infinite spin on a
misbehaving adapter and emits a `paper.resync.truncated` warning (never
silent coverage). Return shape unchanged (`closes, gaps`).

### CR-02: Reconnect exhaustion raises out of `on_disconnect`

**Files modified:** `src/paper/supervisor.py`
**Commit:** `49636f7`
**Applied fix:** `on_disconnect(scheduled=False)` wraps
`_reconnect_with_retry()` in try/except, logs
`paper.supervisor.reconnect_exhausted` with the exception class, and always
falls through to `_resubscribe_and_backfill`. The scheduled path is untouched.

### CR-03: Backfilled closes are log-only and `_last_close` has no producer

**Files modified:** `src/paper/supervisor.py`
**Commit:** `9d636c2` — status: **fixed: requires human verification**
**Applied fix:** `_resubscribe_and_backfill` now returns backfilled closes per
`(symbol, interval)` pair (later extended by WR-09 to also return outage
gaps) instead of only logging them, and logs `paper.supervisor.no_last_close`
at ERROR when a pair has no recorded close. On part (b): inspection showed the
dispatch path is already wired — `_make_kline_handler` records
`_last_close[(symbol, interval)]` inline on every closed kline, so
`record_close`'s inline equivalent has a live caller; no change needed there.
Residual for a human to confirm: the caller-side conversion of returned REST
klines into the loop's `feed_events` path is still future wiring (the returns
are now available for it).

### CR-04: WS adapter has no connect path, drops non-dict messages silently

**Files modified:** `src/adapters/paper_ws.py`
**Commit:** `5f4723f` — status: **fixed: requires human verification**
**Applied fix:** `_on_message` now try/excepts extraction (logs
`paper_ws.extract_failed`) and normalization (logs `paper_ws.normalize_failed`
on KeyError/TypeError/ValueError), and logs `paper_ws.unknown_envelope` with
the message type instead of silently returning. `reconnect` / `close` /
`schedule_reconnect` fail loud (error log + `RuntimeError`) when the handle
lacks the method — verified against the installed SDK that the real
`RequestStreamHandle` exposes only `on`/`unsubscribe`, so the old
`hasattr`-guarded silence would have faked successful rotations.
`subscribe` raises loudly when the handle offers no `on_message` dispatch
instead of returning a dead subscription. Added `connect()` delegating to the
SDK client's `create_connection()` entrypoint (signature verified on the
installed SDK), raising loudly otherwise. Added `_as_dict` coercion so
attribute-style SDK models (`to_dict` / `model_dump` / `__dict__`) are
unwrapped, never dropped; envelope semantics for plain dicts are unchanged
plus acceptance of bare kline-shaped payloads (verified with a throwaway
check script: envelope/k/bare/ack/junk/attribute cases). Full
subscribe-against-live-connection smoke verification remains pre-soak work
(the known BLOCKED gap) — the path is now explicit instead of absent.

### CR-05: Telegram `callback_data` exceeds the 64-byte API limit

**Files modified:** `src/adapters/telegram_notify.py`
**Commit:** `3070383`
**Applied fix:** `callback_data` now carries `SIM:<sha256(signal_id)[:32]>` /
`SKIP:<sha256(signal_id)[:32]>` (36/37 bytes, asserted `<= 64`). The digest
prefix is deterministic so duplicate sends stay idempotent. Docstring records
that Phase-7 callbacks are inert labels and Phase 8 must keep a short→full
mapping when binding real handlers. No test pinned the old values; notify
suite green.

### CR-06: Freeze CI workflow discards its inputs and its acceptance artifact

**Files modified:** `src/paper/freeze.py`, `.github/workflows/paper_freeze_check.yml`
**Commits:** `2dd630e` (code: rollover exit code), `8605f9a` (workflow)
**Applied fix:** `run_check_cli` returns `3` on a REGISTRY_DIFF rollover
(distinct from 0 clean / 2 missing-state / 1 error) so drift is no longer
green CI. The workflow restores `logs/paper` from cache (`paper-freeze-state`
+ `paper-freeze-` restore-keys) before the tick, captures the exit code
without short-circuiting, always uploads `registry_diff.jsonl` as the
`registry-diff-<run_id>` artifact (the PAPER-03 acceptance artifact), always
saves state forward (`paper-freeze-<run_id>`), fails loudly on rollover
(exit 3 → `::error::` + exit 1), and fails on any other non-zero code.
Workflow YAML verified by re-read (no YAML checker in this env — Tier 1+3).

### CR-07: `on_outcome` runs inside the tenacity attempt

**Files modified:** `src/paper/notify.py`
**Commit:** `d50f99f`
**Applied fix:** The send-only block is inside the retry; `on_outcome` runs
after the loop exits (success or exhaustion) wrapped in its own try/except
that logs `paper.notify.on_outcome_failed` — a journal fault can never
trigger a resend. Malformed payloads (missing keys / `format_simulate`
ValueError) return a `FAILED` outcome with `attempts=0` via `on_outcome`,
never raise, never retry. Restructured without nested defs to preserve the
`test_no_inbound_handler_can_mutate_approval_state` function-set contract.

### CR-08: Feed events carry no interval

**Files modified:** `src/paper/loop.py`
**Commit:** `f33189e` — status: **fixed: requires human verification**
**Applied fix:** `_event_to_candle(event, symbol, interval)` takes an explicit
interval; `run_paper_tick` reads `event.get("interval", "1h")` (back-compatible
default — all existing fixtures carry no interval and behave exactly as
before, digests intact) and rejects anything outside `1h`/`4h` loudly.
`4h` closes append a `CONTEXT_BAR` feed-gate record and extend a per-call
`extra_context` list that feeds subsequent 1h evaluations — they never enter
the setup series. Human check: confirm `CONTEXT_BAR` as a feed-gate reason
code fits the downstream journal vocabulary, and that the WS→`feed_events`
producer will populate `event["interval"]` per stream.

### CR-09: Forming-only slot yields neither a close nor a gap

**Files modified:** `src/paper/resync.py`, `tests/test_paper_resync.py`
**Commit:** `e726f79`
**Applied fix:** Gap diff is computed against CLOSED rows; slots present in
the raw page but absent from closed get reason `forming_at_observed_time`
(retryable) instead of silence; genuinely missing slots keep
`exchange_returned_no_candle_for_expected_close`. Updated Test 3
(`test_forming_candle_in_page_is_dropped_before_use`), which had pinned the
hole as correct (`len(gaps) == 0`), to expect the one forming gap.

### WR-01: Millisecond→datetime conversion goes through binary float

**Files modified:** `src/paper/resync.py`, `src/paper/loop.py`, `src/adapters/paper_ws.py`
**Commits:** `a05b49c` (resync), `f33189e` (loop), `5f4723f` (paper_ws)
**Applied fix:** Exact integer/timedelta arithmetic everywhere on the decision
path: `_datetime_to_ms` (resync, via epoch-delta day/second/microsecond
math), `_ms_to_utc` (loop + paper_ws, epoch + `timedelta(milliseconds=ms)`).
All `timestamp() * 1000` and `fromtimestamp(ms / 1000)` conversions on these
paths are gone.

### WR-02: Resync and notify retry on *all* exceptions

**Files modified:** `src/paper/resync.py`, `src/paper/notify.py`
**Commits:** `08037ec` (resync), `d50f99f` (notify)
**Applied fix:** Both retry predicates now exclude programming errors
(`ValueError`, `KeyError`, `TypeError`), which propagate immediately instead
of burning the 120 s / 30 s budgets and masking deterministic faults as
transient. Mirrors `fetch_page_with_retry`'s selective-retry posture.

### WR-03: Warmup gate shadows the staleness gate

**Files modified:** `src/paper/loop.py`
**Commit:** `f33189e`
**Applied fix:** Per-event order is now staleness → warmup, so a feed that is
both under-warmed and stale reports `DATA_STALE`. Existing golden digests
unchanged (no fixture hits both gates).

### WR-04: Re-delivered bars are not deduplicated

**Files modified:** `src/paper/loop.py`
**Commit:** `f33189e`
**Applied fix:** A `seen_open_times` set seeded from warmed history (extended
with each accepted 1h close) rejects re-delivered bars with a `DUPLICATE_BAR`
feed-gate record instead of re-entering `evaluate()`. Existing digests
unchanged (no fixture duplicates).

### WR-05: `assemble_paper_record` ignores half its inputs

**Files modified:** `src/paper/journal.py`
**Commit:** `82d6ad2`
**Applied fix:** skip+expired together → `ValueError` (ambiguous outcome);
empty `skip_reason` → `ValueError`; filled legs combined with skip/expired →
`ValueError`; partial legs (some of approval/order/fill present) → dedicated
`PARTIAL_LEG` `ValueError` instead of the generic message; a
caller-supplied `approval["acted_at_utc"]` disagreeing with the simulated
signal+lag time → `ValueError` (ownership of approval timing stays with the
assembler; verified the fixture's acted time equals signal+lag so existing
tests hold); `assemble_no_trade_record` rejects empty `reason_code`.

### WR-06: `assert` used for production validation; `__import__` hack

**Files modified:** `src/paper/journal.py`
**Commit:** `82d6ad2`
**Applied fix:** `assert signal_detected_at_utc is not None` → explicit
`ValueError`; `__import__("datetime").UTC` → direct `from datetime import UTC`
import.

### WR-07: Freeze computes the registry hash two different ways

**Files modified:** `src/paper/freeze.py`
**Commit:** `2dd630e`
**Applied fix:** Single `_canonical_parameter_set_hash` helper used by both
the pin path and the check path. `StreamEpoch.__post_init__` now validates
`epoch_id` as 64-char lowercase hex (was: non-empty). `_require_utc_aware`
enforced at the top of `pin_stream_epoch` and `_make_epoch_id` (naive input
now fails with a clear message instead of an unrelated canonicalization
error).

### WR-08: `start()` is not idempotent; close failures swallowed

**Files modified:** `src/paper/supervisor.py`
**Commit:** `796b703`
**Applied fix:** `start()` raises `RuntimeError` on double-start without
`stop()` (restarts go through `_resubscribe_and_backfill`, which closes
first — verified it clears handles before calling `start()`). Close failures
log symbol, interval, handle id, and a consecutive-failure counter
(`_close_failures`, reset on a clean sweep) so repeated rotation failures are
distinguishable from one-offs.

### WR-09: Per-symbol isolation journals its gap only in prose

**Files modified:** `src/paper/supervisor.py`
**Commit:** `2d731e5`
**Applied fix:** Backfill exceptions build a `CollectorGap`-shaped dict
(reason `backfill_exception:<ClassName>`, `expected_utc` = last close,
`observed_utc` = now) collected into an outage-gaps list returned alongside
per-pair closes — the hole is now data, not just a log line.

### WR-10: Parity projection drops every signal-less record

**Files modified:** `tests/test_paper_parity.py`
**Commit:** `995c530` — status: **fixed: requires human verification**
**Applied fix:** Added `_project_paper_verdicts_full` projecting
`(bar_close_utc, signal_id_or_None, reason_code, stage)` for ALL records in
replay order, plus `test_paper_full_projection_covers_every_bar` asserting
one entry per bar, replay-order preservation, known stages, and (anti-vacuity)
at least one signal-less entry. Existing signal-level projections and pinned
digests untouched. Residual for a human: the simulator emits trades only, so
true cross-side strategy-stage equality still needs per-bar simulator
outcomes (engine work, not a paper call-site fix) — documented in the test
module's `_project_paper_verdicts` docstring.

### WR-11: `format_simulate` accepts naive datetimes and empty TP lists

**Files modified:** `src/paper/notify.py`
**Commit:** `d50f99f`
**Applied fix:** `format_simulate` raises loudly on empty symbol/direction/
setup, inverted entry bounds, empty TP list, non-datetime or naive
`expiry_utc`/`detected_at_utc`. `notify_simulate` converts these to `FAILED`
outcomes (never raises into the loop).

### WR-12: FAILED outcome reports the tenacity wrapper

**Files modified:** `src/paper/notify.py`
**Commit:** `d50f99f`
**Applied fix:** `RetryError` is unwrapped via `last_attempt.exception()` so
the journaled `error_class` is the root cause (e.g. `TelegramError`), not
`RetryError`.

### WR-13: Purity docstrings contradict actual imports

**Files modified:** `src/paper/resync.py`, `src/paper/supervisor.py`, `src/paper/freeze.py`
**Commits:** `4105484` (resync), `c7080c3` (supervisor), `2dd630e` (freeze)
**Applied fix:** Each docstring now names the real contract (resync:
adapter-surface owner, SDK types enter only as `Kline` values;
supervisor: WS/REST lifecycle owner behind both adapters; freeze:
registry/backtest/canonical sibling surfaces) instead of the stale
"stdlib-only" claim. No import changes — the contracts were already the
intended boundaries.

### WR-14: Gate helpers parse `event["T"]` without validation

**Files modified:** `src/paper/loop.py`
**Commit:** `f33189e`
**Applied fix:** Single `_parse_event_close(event) -> datetime` helper owns the
`T` parse (was: three unvalidated parses per event), translating missing/
non-numeric `T` into explicit `ValueError`, anchored to UTC (no longer to
`now_utc.tzinfo`). `_is_closed_event` drops malformed events through the
counted gate; `check_feed_freshness` reuses the helper.

### WR-15: CLI `--strategy-id/--parameter-set-id` are decorative

**Files modified:** `src/paper/freeze.py`
**Commit:** `2dd630e`
**Applied fix:** `run_check_cli` compares CLI args against the pinned file and
returns 1 with a `paper.freeze.cli_id_mismatch` error log on divergence —
checking pair B against pair A's state can no longer report success.

### WR-16: `pyproject.toml` mypy `files` key is not valid

**Files modified:** `pyproject.toml`
**Commit:** `f6c72c7`
**Applied fix:** Removed the invalid `files = ["src"]` key (replaced with a
one-line guard comment); scope is passed on the command line (e.g. `mypy
src`). Verified no CI workflow invokes mypy, so no workflow change was needed.

---

*Fixed: 2026-09-27T09:56:43Z*
*Fixer: the agent (gsd-code-fixer)*
*Iteration: 1*
