---
phase: 18-user-data-stream-error-taxonomy
plan: 21
subsystem: evidence consumption
status: complete
tags: [recorded-frames, RECORDED_DEMO, semantics-fake, error-taxonomy, D-17, D-21, EXEC-01, EXEC-02, EXEC-05]
requires: [18-05, 18-06, 18-11, 18-15, 18-20, 18-24]
provides:
  - "tests/test_userdata_recorded_frames.py: all 58 RECORDED_DEMO frames through the real parsers, the replay proof and the router"
  - "tests/support/fake_binance_exchange.py: SDK-shaped errors (BadRequestError, int status_code -4116) and the evidence status of every assumption"
  - "tests/test_fake_binance_semantics.py: one test per assumption with its Demo evidence status"
  - "src/domain/exchange_errors.py: CodeEntry.demo_observed_on for the five probe-observed table codes"
affects: [18-22, 18-25]
key-files:
  created:
    - tests/test_userdata_recorded_frames.py
    - tests/test_fake_binance_semantics.py
  modified:
    - tests/fixtures/phase18/README.md
    - tests/support/fake_binance_exchange.py
    - tests/test_exchange_errors.py
    - tests/test_execution_exactly_once_pg.py
    - src/domain/exchange_errors.py
decisions:
  - "SMOKE_RAN and PROBE_RAN are both true (decided from the files). Neither 'smoke postponed' nor 'probe postponed' applies."
  - "A Demo observation of an already documented code is recorded in a new additive field CodeEntry.demo_observed_on, not by changing the single-label evidence field (see Deviations)."
  - "D055 stays OPEN; no document and no decision file was edited."
metrics:
  tasks: 2
  commits: 2
  completed: 2026-10-17
commits: 2
plan_head_before: 9223378ddbd7fccb182d4aa25cdd30311a4041fd
plan_head_after: bdb8e92
actuals:
  tokens: 40000
  tasks: 2
  commits: 2
---

# Phase 18 Plan 21: Consume the Demo evidence Summary

The recorded Demo frames now run through the real parsers, the replay proof and the router; the semantics fake raises SDK-shaped `BadRequestError` with the observed code -4116 and states the Demo evidence status of each assumption; the taxonomy marks the five probe-observed codes. All results are Demo evidence, not mainnet. D055 stays OPEN.

## Which evidence existed (decided from the files)

- SMOKE_RAN true: `decisions/18-DEC-O-18-03-smoke.md` records `option: values`; `evidence/18-smoke-check.txt` has no postponement line; evidence `user-data-smoke-EVIDENCE-20261016T140446Z.json` (REAL_SMOKE); 2 frames under `recorded_demo/smoke/`.
- PROBE_RAN true: `decisions/18-DEC-O-18-03.md` records `option: authorize`; `evidence/18-probe-check.txt` has no postponement line; two REAL_DEMO evidence files; 56 frames under `recorded_demo/probe/` (the second run, 2026-10-16T17:36:12Z).
- Neither "smoke postponed" nor "probe postponed" applies. Nothing was skipped by design.

## Task 1: recorded frames (commit 8b627f6)

`tests/test_userdata_recorded_frames.py` (18 tests) loads every `*.json` under `recorded_demo/`, and:

- pins every file to a `provenance.md` row with label RECORDED_DEMO, and to a row in the new "Recorded demo frames" section of `tests/fixtures/phase18/README.md` (the synthetic section and `tests/test_userdata_fixtures.py` are untouched and still pass);
- parses each frame: 26 ORDER_TRADE_UPDATE, 16 ALGO_UPDATE, 8 ACCOUNT_UPDATE give typed events; 8 TRADE_LITE give `IgnoredEvent`. `KNOWN_RECORDED_ANOMALIES` is empty because there is no anomaly;
- compares the wire keys with the keys the parsers read; keys named in `IGNORED_WIRE_FIELDS` with a reason: `o.a`, `o.b`, `o.si`, `o.ss` of ORDER_TRADE_UPDATE and `ma` of the ACCOUNT_UPDATE position row (a field the parsers have never read; the frames show it as a new field name, harmless);
- pins the real types as regression tests: integer `i`, `t`, `aid`; `ai` is an empty string (parsed to `actual_order_id None`); amounts are strings;
- folds the recorded BUY and SELL fills of the full-fill scenario in all 2520 orderings of the four frames with duplicates: one view, zero fallback calls, zero journal records;
- routes all 58 frames: 8 fills (all `USER_DATA_EVENT`), 26 status hints, 16 algo routes, 8 account events, no divergence and no anomaly; with an empty lookup the same frames give 26 UNKNOWN_STREAM_ORDER and 16 UNKNOWN_STREAM_ALGO divergences.

**TRADE_LITE.** The real stream sends TRADE_LITE (8 frames, one per fill, about 1 ms before the ORDER_TRADE_UPDATE of the same fill). The parser already ignores it by design (single fill source, `18-DEC-D01`). The new test shows that every recorded TRADE_LITE matches an ORDER_TRADE_UPDATE TRADE of the same trade id, client id, order id, side, last quantity and last price, so ignoring it loses no fill in the evidence. No parser change, and no event type was added. Whether to use TRADE_LITE for anything is not a plan 18-21 question.

**No parser defect.** All 58 frames parsed on the first run; no source file of `src/adapters/binance_userdata_events.py` was changed.

**Algo status CANCELED (observation, no change).** The Demo sent only NEW and CANCELED in ALGO_UPDATE. The router classes CANCELED as UNKNOWN, which is the user's recorded decision (`decisions/18-DEC-O-18-01.md`); the test pins it and the evidence does not change it.

## Task 2: the fake and the table (commit bdb8e92)

**SDK-shaped errors.** `BinanceSemanticsFakeAdapter` raises `BadRequestError(error_message, status_code=-4116)` for a duplicate open client order id and for a duplicate open clientAlgoId. `error_facts_from_exception` then `classify(PLACEMENT)` gives DUPLICATE_CLIENT_ID for both (tested). `tests/test_execution_exactly_once_pg.py` now asserts the exception class and code instead of the text.

**The three assumptions** (each with a test in `tests/test_fake_binance_semantics.py` and a comment citing `evidence/18-probe-check.txt` lines):

| Assumption (check-file wording, second run lines 66 to 69) | Status |
| --- | --- |
| 1 a client id is unique among OPEN orders | Algo: confirmed on Demo 2026-10-16 (-4116 while the first is open). Normal order: NOT validated against Demo, not observed. Behavior unchanged. |
| 2 a CANCELED order frees its client id | confirmed on Demo, normal and algo order. |
| 3 a FILLED order frees its client id | confirmed on Demo for a normal order (second run, `id_reuse_after_filled`). The first run could not observe it (-4016 before any fill). |
| duplicate algo id code (plan item 3) | corrected: the fake raised an undocumented-code error; the probe observed -4116 "ClientOrderId is duplicated." |
| 3-day retention rule | NOT validated against Demo (the probe does not test it). Behavior unchanged. |

**Table labels.** `src/domain/exchange_errors.py` marks `demo_observed_on = "2026-10-16"` on the five codes the probe observed that were already in `ERROR_CODE_TABLE`: -2011, -2013, -4116 (DUPLICATE_CLIENT_ID on PLACEMENT, already the category), -2021, -4509. `read_date` is unchanged. `tests/test_exchange_errors.py` gained four tests (the demo-observed list, the probe answers' categories, no relabeling, date validation).

## Codes observed by the probe and not in the table

Not added; for the user to decide.

| Code | Case | Class | Message |
| --- | --- | --- | --- |
| -1106 | rejected_protective_variants (reduce-only together with close position) | UNKNOWN_EXCHANGE_ERROR | "Parameter 'reduceonly' sent when not required." |
| -4016 | id_reuse_after_filled, first run (limit price above the exchange cap) | UNKNOWN_EXCHANGE_ERROR | "Limit price can't be higher than 86305.10." |

Also for the user: **-1125 INVALID_LISTEN_KEY** is in the table and was observed by the live smoke (check item f, PUT after DELETE), not by the probe. The plan limits the label to probe-observed codes, so -1125 was NOT marked; its table note still says "assumed". Marking it is a small follow-up if the user wants it.

## Deviations from Plan

**1. [Rule 2 - integrity] Demo observation in a new field, not in `evidence`.** The plan says the `evidence` of an observed code "includes demo-observed". `CodeEntry.evidence` holds exactly one label, `demo-observed` is defined as "seen only on the Demo host, absent from the page", and two existing tests pin it (`test_evidence_vocabulary` is an exact set, `test_reread_codes_match_the_sources_row` requires "documented" for the re-read codes). Relabeling -2011, -2013, -4116 and -2021 would have called documented codes undocumented. Instead an additive field `demo_observed_on` (ISO date, default None) carries the observation; `evidence` is unchanged for all five codes (-4509 was already `demo-observed`). The -4116 note now records the duplicate clientAlgoId observation. Commit bdb8e92.

**2. [Plan scope] New field and notes in `src/domain/exchange_errors.py`.** Beyond the `evidence` field the plan allowed, the dataclass gained one field with a date check, and the notes of the five codes gained one sentence each saying what the Demo answered. No code and no category was added or changed.

**3. [Plan note] `tests/test_fake_binance_semantics.py` and `tests/test_userdata_recorded_frames.py` are new files** (declared in `files_modified`).

No other test file needed a change; the other fake and manager tests pass unchanged.

## Verification

Results are in the "Verification results" section below.

## Open items

- `partial_fill` and `triggered_market_exit_lifecycle` stay NOT_OBSERVED (18-20); the child order identity of a triggered algo order is still unknown. Not in this plan.
- The fake's normal-order duplicate (-4116) is documented but never observed on Demo.
- -1106, -4016 (and -1125 labelling) as above.
- Branch `phase-18-smoke` is not merged into `develop`; STATE.md and ROADMAP.md are untouched by this plan.

## Verification results

Run in the worktree `Trading-Alert-p18`, after both task commits (plan_head_after bdb8e92):

- `uv run pytest -m "not docker" -q -rs`: 10067 passed, 6 skipped, 28 deselected, exit 0 (949 s). The 6 skips are platform skips (symlinks unavailable, NTFS file modes, Windows file modes). `TEST_DATABASE_URL` was set and the Postgres container was up, so the `*_pg` tests (`test_execution_exactly_once_pg`, `test_execution_write_ahead_pg`, `test_approval_replay_pg`, `test_callback_redelivery_pg`, `test_intent_recovery_pg`) ran and were not skipped.
- Task 1 verify command (recorded frames, parsers, events, replay, router, fixtures): passed. Task 2 verify command (fake, taxonomy, manager and the Phase 17 fake users) with `-x -rs`: passed, no SKIPPED line.
- `uv run mypy src`: no issues in 202 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 620 files already formatted. `uv lock --check`: passed.

## Self-Check: PASSED

- `tests/test_userdata_recorded_frames.py`, `tests/test_fake_binance_semantics.py`: present.
- Commits 8b627f6 and bdb8e92: present on `phase-18-smoke`.
- No file under `docs/`, no `STATE.md`, no `ROADMAP.md` and no decision file was edited; the recorded frames are untouched.

