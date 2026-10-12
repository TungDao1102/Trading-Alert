---
phase: 16-paper-runtime-composition
plan: 39
subsystem: paper runtime / test-only SHADOW rehearsal (REV-03)
tags: [shadow, rehearsal, test-only, rev-03, d061-item-d, d-13, d-14, d-19, paper-02]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-31: ShadowCoordinator, ShadowWiring seams; plan 16-35: PaperRecord test_only and measured approval fields; plan 16-36: export_shadow_evidence and the analytics exclusion of test_only rows"
provides:
  - "src/paper/rehearsal.py: run_rehearsal, RehearsalStores (TEST- guard and test_only stamp on every journal payload), RehearsalCoordinator (test_only on every paper record), RecordingBot, build_test_outcome, evidence_document, write_evidence, proof_class_for, RehearsalAlreadyRan"
  - "scripts/shadow_rehearsal.py: operator entrypoint with --dry-run (fakes, virtual clock) and --live-telegram --i-am-the-operator (real bot, live public minutes), exit codes 0 to 5"
  - "tests/test_paper_test_signal_rehearsal.py (27 tests incl. one PostgreSQL test)"
affects: [16-40 (runs the dry run and the live rehearsal and checks the 12 evidence keys), 16-38 (isolation proof over this path), 16-43 (clean soak database check)]

requirements-completed: [PAPER-02]

status: complete
actuals:
  tokens: 19650
  tasks: 3
  commits: 6
plan_head_before: 614e5ad2d0f2303c03be89fb6cfbf281c36396cb
plan_head_after: ea7339a9fe43093c447e9fa4c5515dd717085788
commits: 6

tech-stack:
  added: []
  patterns:
    - "Test-only marking by wrapping the stores (RehearsalStores) and subclassing the chain (RehearsalCoordinator) instead of changing the production coordinator: no production module sets test_only"
    - "Proof class is a function of the run mode (proof_class_for), never of a caller-supplied value"
    - "A failure while the chain runs still writes the partial evidence and is then raised with the exception class name only"

key-files:
  created:
    - src/paper/rehearsal.py
    - scripts/shadow_rehearsal.py
    - tests/test_paper_test_signal_rehearsal.py
  modified: []

key-decisions:
  - "The rehearsal subclasses ShadowCoordinator and wraps the stores; shadow_runtime.py (plan 16-31) is untouched and sets test_only nowhere"
  - "Once-only is decided by the fixed test signal id (TEST-REHEARSAL-SIGNAL-0001) through get_signal on the rehearsal database, before anything is written or sent"
  - "The persisted setup_type must be one of the six database values (ck_signals_setup_type), so the label TEST SIGNAL travels in the regime reason code of the alert and the TEST- ids"
  - "Live levels are fixed fractions of the observed mark price rounded to the exchange tick (not research output); dry run uses the same code path over scripted public minutes"
  - "BINANCE_ names are checked before the operator flag in live mode (same order as scripts/paper_ws_smoke.py)"

coverage:
  - id: D1
    description: "A dry run takes one TEST- signal through alert (SHADOW label and TEST SIGNAL), APPROVE, confirmation card, CONFIRM, journal transitions and a simulated position; every journal payload, record and id is test-only"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_test_signal_rehearsal.py#test_a_dry_run_takes_the_labelled_test_signal_through_the_whole_shadow_chain"
        status: pass
    human_judgment: false
  - id: D2
    description: "Evidence has exactly the 12 agreed keys, proof class FAKE in a dry run, REAL_REHEARSAL only in live mode, records_test_only equals records_written"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_test_signal_rehearsal.py#test_the_dry_run_evidence_has_exactly_the_agreed_keys_and_proof_class_fake"
        status: pass
      - kind: unit
        ref: "tests/test_paper_test_signal_rehearsal.py#test_live_mode_advances_the_position_on_public_minutes_and_writes_real_rehearsal_evidence"
        status: pass
      - kind: unit
        ref: "tests/test_paper_test_signal_rehearsal.py#test_a_dry_run_can_never_produce_the_real_rehearsal_proof_class"
        status: pass
    human_judgment: false
  - id: D3
    description: "Exported rehearsal rows count no signal and the report prints the exclusion line"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_test_signal_rehearsal.py#test_exporting_the_rehearsal_rows_counts_no_signal_and_reports_the_exclusion"
        status: pass
    human_judgment: false
  - id: D4
    description: "Separation from the production path (AST), allowlist name absent, only the rehearsal marks test_only, second run refuses and writes nothing"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_test_signal_rehearsal.py (AST tests and test_a_second_run_on_the_same_database_refuses_and_writes_nothing)"
        status: pass
      - kind: unit
        ref: "tests/test_paper_start_gate.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Live guards (operator flag, BINANCE_ refusal naming only names, allowed environment names only) and evidence scrubbing"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_test_signal_rehearsal.py (live guard and write_evidence tests)"
        status: pass
    human_judgment: false
  - id: D6
    description: "The real run with the operator's Telegram taps and live Binance public minutes, in the trading-rehearsal compose project"
    requirement: PAPER-02
    verification: []
    human_judgment: true
    rationale: "No network or Telegram on this machine and the plan forbids running live mode; plan 16-40 task 3 is the blocking-human run"

duration: ~1h 20min
completed: 2026-10-12
---

# Phase 16 Plan 39: Test-only SHADOW rehearsal Summary

**One labelled `TEST-` signal takes the real `ShadowCoordinator` chain once (alert, APPROVE, confirmation card, CONFIRM, journal transitions, simulated position through the same fill driver) with every store write and paper record marked `test_only`, refuses a second run on the same database, never touches the production start path, and writes a scrubbed 12-key evidence file whose proof class is `FAKE` in a dry run and `REAL_REHEARSAL` only in the operator's live mode.**

## Performance

- **Tasks:** 3 of 3 (Task 1 tracer, Tasks 2 and 3 auto, all `tdd="true"`, RED commit then GREEN commit each)
- **Files:** 3 created, none modified (`src/paper/shadow_runtime.py` and every other production module untouched)
- **Commits:** 6 measured (`plan_head_before..plan_head_after`: three RED, three GREEN); this SUMMARY commit is the seventh

## Accomplishments

- **Test-only marking without touching the chain.** `RehearsalStores` sits in front of the real stores: it refuses any row whose signal id is not a `TEST-` id and stamps `"test_only": true` into every journal payload; it counts rows written and rows carrying the mark, reading the mark back from the object it stores. `RehearsalCoordinator` subclasses `ShadowCoordinator` and rebuilds every assembled `PaperRecord` with `test_only=True`. The evidence reports `records_written == records_test_only` (16 and 16 in the dry run).
- **Labelled fixture.** `build_test_outcome` builds the signal, plan and sized verdict from a fixed fixture: `TEST-` ids, strategy `TEST-REHEARSAL`, fixed relative offsets around the observed mark price rounded to the exchange tick, a quantity of the smallest step multiple reaching twice the minimum notional. Nothing comes from a parameter-set candidate or research output.
- **Separation (REV-03, T-16-90).** AST tests prove the rehearsal module and script import nothing from `src.paper.runtime` or `src.paper.pipeline`, call none of the allowlist accessors or `pin_stream_epoch` / `write_pinned_state`, never write the allowlist name, and that in `src/paper` only `rehearsal.py` sets `test_only` to a literal `True` (`journal.py` only writes the flag of an already marked record into its canonical dict). `tests/test_paper_start_gate.py` still passes.
- **Once-only.** `run_rehearsal` looks for the fixed test signal id in the rehearsal database before anything else and raises `RehearsalAlreadyRan` ("rehearsal already ran on this database (REV-03: once)"); the script exits 4 and writes and sends nothing. An existing evidence file is never overwritten.
- **Live mode (built and tested with fakes only, never run).** `--live-telegram` needs `--i-am-the-operator` (exit 2), refuses any `BINANCE_` name (exit 3, names only), reads only the allowed environment names (`read_env`) and the ratified `PAPER_RUNTIME_CONFIG` (exit 5 listing names), takes constraints from the public `exchangeInfo` through `ConstraintProvider`, advances the position through the coordinator's `LiveMinutePoller` over the credential-free `BinancePublicMarketData`, and receives the operator's real presses through the application built by `build_application` (its bot is bound into the recording bot so `label_seen` is judged on delivered texts).
- **Evidence.** Exactly the 12 keys plan 16-40 checks; `proof_class_for(mode)` makes `REAL_REHEARSAL` impossible in a dry run; the file is scrubbed with `Redactor`, written atomically, re-scanned after the write and deleted when the scan fails. A live run that ends without presses or fill writes honest partial evidence and exits 1.

## Task Commits

| Task | Commit | What |
| --- | --- | --- |
| 1 RED | cade2f6 | test(16-39): RED tracer for the test-only rehearsal, TEST- records and FAKE evidence |
| 1 GREEN | a86509c | feat(16-39): test-only rehearsal runs the labelled test signal through the SHADOW chain |
| 2 RED | e742086 | test(16-39): RED for separation from the production path and the once-only rule |
| 2 GREEN | 218971d | feat(16-39): the rehearsal refuses a second run on the same database |
| 3 RED | 60a997a | test(16-39): RED for live mode guards, live minutes and REAL_REHEARSAL evidence |
| 3 GREEN | ea7339a | feat(16-39): live rehearsal mode with operator flag, BINANCE_ refusal and REAL_REHEARSAL evidence |

## RED Evidence

- **Task 1** (`cade2f6`): collection failed, `ImportError: cannot import name 'shadow_rehearsal' from 'scripts'`.
- **Task 2** (`e742086`): `test_a_second_run_on_the_same_database_refuses_and_writes_nothing` failed (`AttributeError ... EXIT_ALREADY_RAN`; the second run also stopped with "the labelled alert was not delivered"). The AST tests and the allowlist-name test pass before and after by design (they guard the property).
- **Task 3** (`60a997a`): collection failed, `ImportError: cannot import name 'proof_class_for'`.

## Verification

- `pytest tests/test_paper_test_signal_rehearsal.py tests/test_paper_start_gate.py -q -p no:cacheprovider` with `TEST_DATABASE_URL` set to the local PostgreSQL 17 test database: all passed (the PostgreSQL test ran, not skipped).
- `ruff check` (whole repo) and `ruff format --check` (520 files): clean. `mypy src` (182 files): clean; `mypy scripts/shadow_rehearsal.py`: clean. `uv lock --check`: clean.
- `.venv/Scripts/python scripts/shadow_rehearsal.py --dry-run --out <file>` run by hand: exit 0, 12-key evidence, `proof_class` FAKE, `measured_delay_seconds` 20.0, `position_opened` true.
- Full suite `pytest -m "not docker"` with `TEST_DATABASE_URL` set: exit 0, no failure (run with `tests/test_cost_parity.py` deselected, because `deferred-items.md` lists a known failure there; it was then run on its own and passed, 9 tests).
- No network, no Telegram, no Binance call; `.env` not read; no package installed.

## Decisions Made

See `key-decisions` above.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree base was stale**
- **Found during:** startup
- **Issue:** the worktree predated plan 16-31.
- **Fix:** `git merge --no-edit develop` (fast-forward), `uv sync --frozen --extra dev`; `src/paper/shadow_runtime.py` confirmed present.

**2. [Rule 1 - Bug] The label cannot be the persisted `setup_type`**
- **Found during:** Task 3, PostgreSQL run
- **Issue:** the first fixture used `setup_type="TEST SIGNAL"`. The in-memory stores accept it; PostgreSQL rejects it (`ck_signals_setup_type` allows only the six strategy setup names). The in-memory green had hidden this.
- **Fix:** `setup_type="TREND_PULLBACK_LONG"`, and the label `TEST SIGNAL` travels in the regime reason code of the alert (`REGIME_TEST SIGNAL`) and in the `TEST-` ids. A PostgreSQL test now guards this.
- **Files modified:** `src/paper/rehearsal.py`. **Commit:** ea7339a.

**3. [Interpretation] Plan names `run_rehearsal(*, mode, stores, bot, public, clock, out)`**
- The function takes the plan's keywords plus `settings`, `parameter_set`, `constraints`, `sleep`, `environ`, `press` and `application_factory`, because the chain needs the symbol, equity, timing, cost model, exchange constraints and the operator's presses. `RehearsalMode` has DRY_RUN and LIVE.

**4. [Interpretation] `--out` is a file path**
- Plan 16-40 calls `--out <path>.json`, so the argument is the evidence file, not a directory. It is never overwritten.

**5. [Interpretation] Dry run does not refuse `BINANCE_` variables**
- The plan puts the refusal on the live mode (as `scripts/paper_ws_smoke.py` does); a dry run touches no network, so it only reads nothing from the environment.

**6. [Interpretation] Once-only is judged by the fixed test signal id**
- The store port has no "list all signals" reader, so a different pre-existing test-only signal in the database is not detected; the fixed id is. Plan 16-33 (own compose project and database) and plan 16-43 (clean soak database check) cover the rest.

### TDD ordering

Each task has its RED commit before the GREEN commit. The tracer gate (auto mode, automated-only verify) was the same `<verify>` re-run end to end before Task 2: passed, expansion continued.

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug) plus 4 interpretations. **Impact:** none on behaviour outside the plan's intent.

## Known Stubs

None. The dry-run fixtures (`ScriptedPublic`, `FixedConstraints`) are the intended fakes of the dry-run mode and are not reachable from live mode.

## Threat Flags

None beyond the plan's register. T-16-89 (test signal counted as evidence): `TEST-` ids, `test_only` on every journal payload and paper record, analytics exclusion (16-36) and trial rejection (16-25), separate project and database. T-16-90 (bypassing the empty allowlist): AST tests, no pin, once-only. T-16-91 (evidence disclosure): scrub, atomic write, post-write scan, tested with seeded secrets. T-16-SC: no package installed.

## Not run

- **Live mode against real Telegram and Binance** (plan 16-40 task 3, blocking-human): built and covered with a fake bot, a scripted public adapter and injected presses only.
- `docker`-marked tests (excluded by `-m "not docker"`).

## Notes for later plans

- Plan 16-40 runs `scripts/shadow_rehearsal.py --dry-run --out <file>` and, as the operator, `--live-telegram --i-am-the-operator --out <file>` inside project `trading-rehearsal`; its jq-style check uses `measured_delay_seconds > 0`, `confirmed_within_ttl`, `position_opened` and `records_written == records_test_only`, all present.
- The live run waits `--wait-seconds` (default 900) after the alert for the presses and the fill; the first eligible minute is the minute after the CONFIRM (Q-B), so a fill needs about two minutes plus the close lag.
- `scripts/shadow_rehearsal.py --dry-run` imports `tests/shadow_fakes.py` lazily, so it needs the repository checkout (tests directory); live mode does not.

## Self-Check: PASSED

- Created files exist: `src/paper/rehearsal.py`, `scripts/shadow_rehearsal.py`, `tests/test_paper_test_signal_rehearsal.py` (checked with `[ -f ]`).
- Commits exist: cade2f6, a86509c, e742086, 218971d, 60a997a, ea7339a.
- Acceptance criteria of all three tasks re-run green (see Verification). STATE.md and ROADMAP.md were not touched, nor the files of plan 16-30.
