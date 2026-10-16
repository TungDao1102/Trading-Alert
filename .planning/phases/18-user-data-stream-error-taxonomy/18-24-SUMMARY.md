---
phase: 18-user-data-stream-error-taxonomy
plan: 24
subsystem: tests/fixtures (user-data stream frames)
status: complete
tags: [binance, user-data-stream, fixtures, synthetic, provenance, listenKey, redaction, EXEC-05, D-21, D-22]
requires:
  - 18-03 (frame builders in tests/support/userdata_frames.py, parsers and to_fill_event in src/adapters/binance_userdata_events.py)
  - 18-04 (listenKey shape and key-name rules in src/ops/redaction.py)
provides:
  - tests/fixtures/phase18/synthetic/*.json (six SYNTHETIC_FROM_SDK_MODEL wire frames, byte-equal to their builders)
  - tests/fixtures/phase18/README.md ("Synthetic frames" provenance section; plan 18-21 adds its RECORDED_DEMO section)
  - tests/test_userdata_fixtures.py (FIXTURE_BUILDERS, builder-equality, parse, fold, README-set and secret-shape tests)
affects:
  - plan 18-21 (adds RECORDED_DEMO frames and its own README section; the README-set test reads only the "Synthetic frames" section)
tech-stack:
  added: []
  patterns:
    - fixture file pinned byte-equal to the builder output (sorted keys, 2-space indent, one trailing LF), so file and builder cannot drift
    - README section rows compared to the directory listing in both directions, with tmp_path negative controls
key-files:
  created:
    - tests/test_userdata_fixtures.py
    - tests/fixtures/phase18/README.md
    - tests/fixtures/phase18/synthetic/order_trade_update_trade.json
    - tests/fixtures/phase18/synthetic/order_trade_update_new.json
    - tests/fixtures/phase18/synthetic/algo_update_new.json
    - tests/fixtures/phase18/synthetic/algo_update_rejected.json
    - tests/fixtures/phase18/synthetic/account_update_order.json
    - tests/fixtures/phase18/synthetic/listen_key_expired.json
  modified:
    - .gitattributes
decisions:
  - "The synthetic JSON fixtures carry the git attribute `text eol=lf`, because core.autocrlf=true on this machine would turn them into CRLF on a fresh checkout and break the LF-only builder-equality test"
  - "The secret-shape test pins the exact redactor output instead of 'unchanged' for the listenKey fixture: the plan 18-04 JSON key-name rule masks the value of any \"listenKey\" key whatever it is, so every other value must come out unchanged and the listenKey value must become [REDACTED]"
metrics:
  duration: "about 15 minutes (2026-10-16, ending 05:16Z)"
  completed: 2026-10-16
  tasks: 2
  files: 9
actuals:
  tokens: 4400
  tasks: 2
  commits: 4
plan_head_before: ddda6e685a763bd3f2ec421fbc4d2e13473f635f
plan_head_after: 16a7974811e8de73b36f3e55d6581dc21e222b58
---

# Phase 18 Plan 24: Synthetic user-data fixture files with provenance labels Summary

Six synthetic user-data wire frames now exist as JSON files under `tests/fixtures/phase18/synthetic/`: ORDER_TRADE_UPDATE TRADE and NEW, ALGO_UPDATE NEW and REJECTED (with `rm`), ACCOUNT_UPDATE reason ORDER, and listenKeyExpired. Each file is written from a plan 18-03 frame builder and a test pins it byte-equal to that builder. Every file parses to its typed event, and the TRADE file folds through the unchanged `fold_fills` to one unique fill, including when the same fill is replayed. A README labels every file SYNTHETIC_FROM_SDK_MODEL, and a test keeps its rows and the files present in step. Nothing here was recorded from Binance.

## Commits

`commits: 4` is measured as `git rev-list --count ddda6e6..16a7974`. The worktree is shared with other agents, so 2 of those 4 commits belong to plan 18-02 (1056b19, f174811). This plan owns two task commits, plus the SUMMARY commit that follows:

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 154ecdf | the TRADE fixture equals its builder, parses, converts and folds once and twice; the README provenance rule with tmp_path negative controls; `.gitattributes` LF rule |
| 2 | 16a7974 | the other five fixtures, the README rows, one parse expectation per kind, the secret-shape check with a realistic-key negative control |

## Verification

- `uv run pytest -m "not docker" tests/test_userdata_fixtures.py tests/test_userdata_events.py -x`: passed (Task 1 gate).
- `uv run pytest -m "not docker" tests/test_userdata_fixtures.py tests/test_userdata_events.py tests/test_userdata_parsers.py -x`: 379 passed. `tests/test_userdata_fixtures.py` alone has 24 tests.
- `uv run ruff check`: all checks passed. `uv run ruff format --check`: 556 files already formatted. `uv run mypy src`: no issues in 188 source files.
- Red runs before each green: Task 1 had 6 failures (fixture and README absent), Task 2 had 16 failures (five files absent).
- No network was used. The builders, the parsers and `fold_fills` were not edited.

## Fixture to builder map (FIXTURE_BUILDERS)

| File | Builder call |
|------|--------------|
| order_trade_update_trade.json | `order_trade_update_frame()` |
| order_trade_update_new.json | `order_trade_update_frame(x="NEW", X="NEW", l="0", z="0", L="0")` (the plan 18-03 non-TRADE overrides) |
| algo_update_new.json | `algo_update_frame()` |
| algo_update_rejected.json | `algo_update_frame(X="REJECTED", rm="Reduce Only reject")` (the plan 18-03 test reason) |
| account_update_order.json | `account_update_frame()` |
| listen_key_expired.json | `listen_key_expired_frame()` (dummy key `SYNTHETIC-DUMMY-LISTEN-KEY-not-a-credential-0000`) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] LF-only fixtures would turn into CRLF on a fresh Windows checkout**
- **Found during:** Task 1
- **Issue:** `core.autocrlf=true` converts LF text files to CRLF in the working tree on checkout. The builder-equality test requires LF-only bytes, so it would fail after a clone or a merge into the main checkout.
- **Fix:** added `tests/fixtures/phase18/synthetic/*.json text eol=lf` to `.gitattributes` (`git ls-files --eol` shows `i/lf w/lf attr/text eol=lf`). `.gitattributes` is not in the plan's `files_modified`.
- **Files modified:** .gitattributes
- **Commit:** 154ecdf

**2. [Plan conflict] The redactor always changes the listenKey fixture text**
- **Found during:** Task 2
- **Issue:** The plan asks that `scrub` leave every fixture text unchanged. It also says that if `scrub` changes a text, the fix belongs in the builder's synthetic value and never in an allow-list. Plan 18-04 added a JSON key-name rule, `"listenKey": "<value>"`, that masks any non-empty value in JSON text. So no builder value can leave `listen_key_expired.json` unchanged, apart from degenerate ones (an empty string, a leading space, or no key at all) that would make the frame less faithful. Measured: `scrub` turns the file's value into `[REDACTED]`, but leaves `listenKey=SYNTHETIC-DUMMY-...` (query form) and the bare value unchanged.
- **Fix:** the test does not skip or exempt any file. For every fixture it asserts that `scrub(text)` equals the canonical text with the value under every listenKey-named key replaced by `[REDACTED]`. This mirrors the redactor's own key-name rule, so every other value must come out unchanged. Fixtures without a listenKey are also asserted fully unchanged. Separately, the dummy value is checked to be not listenKey-shaped outside the JSON rule (bare, `listenKey=`, `listen_key=`, query string). A negative control shows a realistic 64-alphanumeric key is changed in both query and JSON form. The builder and the redactor were not edited.
- **For the plan owner:** if "unchanged" must hold literally, then either the plan 18-03 listenKeyExpired builder needs a value the redactor ignores, or the plan 18-04 JSON rule needs narrowing. Neither is in this plan's scope.
- **Files modified:** tests/test_userdata_fixtures.py
- **Commit:** 16a7974

## Known Stubs

None. The fixtures are deliberately synthetic and labelled so. RECORDED_DEMO frames are plan 18-21's scope.

## Threat Flags

None. No new endpoint, auth path or schema. T-18-73 is mitigated as planned: builder-equality, the redactor check above, the dummy listenKey with its negative control, and the README label.

## Self-Check: PASSED

- FOUND: tests/test_userdata_fixtures.py, tests/fixtures/phase18/README.md and all six files under tests/fixtures/phase18/synthetic/
- FOUND: commits 154ecdf and 16a7974 in `git log`
