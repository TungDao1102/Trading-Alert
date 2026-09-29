---
phase: 10-journal-depth-kill-gate-operations
fixed_at: 2026-09-29T09:33:14Z
review_path: .planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW.md
iteration: 1
findings_in_scope: 17
fixed: 12
skipped: 5
status: partial
---

# Phase 10: Code Review Fix Report

**Fixed at:** 2026-09-29T09:33:14Z
**Source review:** .planning/phases/10-journal-depth-kill-gate-operations/10-REVIEW.md
**Iteration:** 1
**Scope:** critical_warning (CR-*, WR-*); the 10 Info findings were not in scope.

**Summary:**
- Findings in scope: 17
- Fixed: 12 (7 of them are marked "requires human verification" because they change a contract or a semantic choice)
- Skipped: 5 (each needs a methodology, governance or API decision from a human)

**Verification:** `workflow.use_worktrees` is `false`, so every edit, commit and gate ran in the main checkout. The numbers below can be reproduced from the current `master` tree.
- `uv run pytest` (full suite, `TEST_DATABASE_URL` and `DATABASE_URL` unset): all passed. The only skips are the existing PostgreSQL-gated and platform-gated tests.
- `uv run ruff check` and `uv run ruff format --check` on every touched Python file: clean.
- `uv run mypy src`: 5 errors in 4 files (`telegram_notify.py`, `ops/drills.py`, `paper/supervisor.py`, `reconcile/compare.py`). The same 5 errors are present on the pre-fix tree, and none are in touched files. `tests/test_analytics_store.py` has 3 `comparison-overlap` errors that were also there before the fix.
- Golden fixtures: no fixture under `tests/fixtures/phase10/` changed. Every fix leaves the pure-core outputs byte-identical for the existing inputs.
- Each fix has regression tests, written first and seen failing before the fix was applied.

## Fixed Issues

### CR-01: The sticky INSUFFICIENT_EDGE terminal is lost whenever the database is not read

**Status:** fixed: requires human verification (sticky-state logic)
**Files modified:** `src/adapters/analytics_files.py`, `src/analytics/cli.py`, `tests/test_analytics_cli.py`, `tests/test_analytics_files.py`
**Commit:** 894cdfd
**Applied fix:**
- `RecordedTerminal.recorded_at_utc` is now parsed as a UTC datetime. The loader fails closed on naive, non-UTC or unparseable values.
- The new `cli._merge_priors` adds the committed mirror to the journal priors as a `PriorEvaluation(INSUFFICIENT_EDGE, recorded_at_utc)`. It de-duplicates by value and sorts by `(evaluated_at_utc, state)`.
- The evaluator's existing rules still apply: only priors strictly earlier than the evaluation count, and a recorded reset after the terminal clears it.
- Tests: `--no-db` with only the committed terminal stays INSUFFICIENT_EDGE. The same terminal in the database and in the file counts once. A later reset in the file reopens.

### CR-02: Human family decisions whose `family_id` is not a registry directory are silently discarded

**Files modified:** `src/adapters/analytics_files.py`, `tests/test_analytics_files.py`
**Commit:** de6df08
**Applied fix:** `scan_family_facts` now raises `DecisionsFileError("families: decisions for unregistered family ids [...]")` when a decision matches no `params/` directory. Tests cover `trend_pullback`, `Trend-Pullback` and `retired-family`.

### WR-02: Unmapped CANDIDATE experiments are silently dropped

**Files modified:** `src/analytics/cli.py`, `tests/test_analytics_cli.py`
**Commit:** b143abb
**Applied fix:** `scan.unknown_experiment_ids` now becomes the BACKTEST ledger note `InputNote("family_scan:unknown_experiments", "UNMATCHED_JOIN", n)`, passed through a new `extra_notes` argument of `_backtest_inputs`.

### WR-03: The CLI failure contract is broken by exceptions outside `_EXPECTED_FAILURES`

**Files modified:** `src/analytics/cli.py`, `tests/test_analytics_cli.py`
**Commit:** 0a5a0eb
**Applied fix:**
- These now count as expected failures: the four registry exceptions (`UnregisteredParameterSet`, `ParameterSetMutated`, `RegistrySchemaMismatch`, `StrategyKeyOutsideRegistry`), plus `ValueError` as a last resort. The last resort covers `UnicodeDecodeError`, `TOMLDecodeError` and the clock's UTC checks.
- `_reason` still prints the fixed messages of the project's own errors. Everything else becomes `input could not be read (<TypeName>)`, so no path or content leaks.
- Tests assert exit 1, the type name only, no "secret" text, and no files written.

### WR-04: `--record` accepts any `--as-of`, including future instants

**Status:** fixed: requires human verification (CLI clock contract changed)
**Files modified:** `src/analytics/cli.py`, `tests/test_analytics_cli.py`, `scripts/dev/journal-report.ps1`
**Commit:** 72416d4
**Applied fix:**
- With `--record`, `_resolve_as_of` now also reads the clock once when `--as-of` is given. An `--as-of` later than that reading exits 2 before any read or write.
- A backdated `--as-of` is still accepted, so idempotent replays keep working.
- The module docstring and the wrapper comments are updated. The record tests now inject `now_fn` (`RECORD_NOW`) so they never read the real clock.

### WR-05: A failed record returns exit 1 after the report files are written

**Status:** fixed: requires human verification (a new exit code in the documented contract)
**Files modified:** `src/analytics/cli.py`, `tests/test_analytics_cli.py`, `scripts/dev/journal-report.ps1`
**Commit:** ca139ba
**Applied fix:**
- A failed append now returns a new exit code 3 ("report produced, record failed"). Exit 1 still means that nothing was written.
- The CLI docstring, `main` and the wrapper's exit-code header document the new code.
- The existing test now expects 3.
- The UI-SPEC in `.planning/` was not edited. A human may want to add exit 3 to the Interaction Contract there.

### WR-07: Research-universe hash verification is never wired

**Status:** fixed: requires human verification (the expected hash comes from CANDIDATE runs only)
**Files modified:** `src/analytics/cli.py`, `tests/test_analytics_cli.py`
**Commit:** 1b12c8e
**Applied fix:**
- `_expected_universe_hash` returns the single `universe_hash` recorded by the CANDIDATE experiments.
- It returns `None` (NOT_APPLICABLE) when there are no CANDIDATE runs.
- If CANDIDATE runs disagree, it returns a non-hex sentinel that can never verify, so the status becomes UNVERIFIED_UNIVERSE.
- The result is passed as `ReportInputs.expected_universe_hash`.
- Tests: the default run is VERIFIED, `--universe ["BTCUSDT"]` is UNVERIFIED_UNIVERSE, mixed universes are UNVERIFIED_UNIVERSE, and no experiments is NOT_APPLICABLE.

### WR-08: The LIVE approval-delay buckets never contain skipped or expired signals

**Status:** fixed: requires human verification (the metric-definition choice is kept as approvals-only)
**Files modified:** `src/analytics/approval_delay.py`, `tests/test_analytics_approval_delay.py`
**Commit:** 30c3992
**Applied fix:**
- I took the reviewer's second option: correct the docs and remove the dead branch.
- The existing design and tests treat the table as signal-to-approve, and `test_measured_delay_uses_approved_live_rows_only` asserts that a skip is not a delay sample.
- `_build_delay` now takes USER_EXECUTED records only. The dead OPPORTUNITY branch and its unused `hypothetical` parameter are removed, and both docstrings say so.
- Output for records produced by the normaliser is unchanged.
- Bucketing skips and expiries by a "decision time" would change a D-02 metric definition. That is a separate human decision.

### WR-09: The kill-gate verdict cannot be computed or recorded without a complete evidence file

**Status:** fixed: requires human verification (the `-Record` usage contract changed)
**Files modified:** `src/analytics/cli.py`, `tests/test_analytics_cli.py`, `scripts/dev/journal-report.ps1`
**Commit:** 0b82c6e
**Applied fix:**
- No persisted experiment registry exists to validate against, so I took the reviewer's fallback: `--record` now requires `--evidence` (exit 2 before any read or write).
- A report run whose decisions include a TESTED_* family but has no `--evidence` now fails with a reason that names `--evidence`, instead of the opaque subset error.
- The wrapper documents `-Evidence` as required with `-Record`, and its usage example is updated.

### WR-11: Malformed KILL_GATE_EVALUATION and QUESTION_APPROVED rows are dropped silently

**Status:** fixed: requires human verification (a fail-closed policy choice)
**Files modified:** `src/analytics/cli.py`, `tests/test_analytics_cli.py`
**Commit:** 1a91de9
**Applied fix:**
- Any KILL_GATE_EVALUATION event that `prior_from_event` cannot parse now stops the report (`AnalyticsInputError`, exit 1, nothing written). Such an event may have been a terminal.
- A KILL_GATE_QUESTION_APPROVED event that cannot be parsed is counted in the LIVE ledger as `journal_events:KILL_GATE_QUESTION_APPROVED` / MALFORMED_ROW. Dropping a reset keeps the gate sticky, which is the safe direction, so it is counted rather than fatal.

### WR-14: The PostgreSQL integration test drops every table on whatever `TEST_DATABASE_URL` points to

**Files modified:** `tests/test_analytics_store.py`
**Commit:** d0cc1c4
**Applied fix:**
- `test_pg_append_and_reread_one_kill_gate_event` now calls `pytest.fail` before connecting unless the database name (read with `make_url`) ends in `_test`.
- It runs `asyncio.run(..., loop_factory=SelectorEventLoop)` on win32.
- The guard has its own unit test, which needs no database.
- Not run against a real database, as instructed.
- Note: `tests/test_domain_mappers_pg.py` uses the same unguarded `create_all`/`drop_all` pattern. It is outside this finding's scope and still needs the same guard.

### WR-15: A negative `realized_risk` flips the sign of R in the core metrics

**Files modified:** `src/analytics/types.py`, `src/adapters/analytics_files.py`, `tests/test_analytics_incomplete.py`, `tests/test_analytics_files.py`
**Commit:** d4a6242
**Applied fix:**
- `TradeOutcome.__post_init__` rejects `realized_risk < 0` with `AnalyticsInputError`.
- The evidence loader rejects it at the edge with `EvidenceFileError` naming `realized_risk`.
- Zero risk keeps its existing ZERO_RISK exclusion.
- The live normaliser already maps `risk_budget <= 0` to None, so live reports are unaffected.

## Skipped Issues

### WR-01: The family-independence test is partly vacuous and depends on order

**File:** `src/analytics/family.py:104-137`
**Reason:** Needs a methodology decision. I confirmed the finding is real:
- `parameter_set_hash` embeds `strategy_id` (`src/domain/registry.py:393-399`), so the disjoint-hash check can never fail across directories.
- Acceptance is greedy in lexicographic order.

Fixing it means redefining what "independently specified" means for the D013/D030 kill gate. The open choices are:
- which fields to hash for parameter identity;
- whether NOT_TESTED families take part;
- whether a duplicate group marks every member as non-independent.

A human must decide these. They also change which families count toward the 3-family budget.

**Original issue:** Independence reduces to "distinct sheet bytes + 7 slot headings", and adding a directory whose name sorts earlier can stop the kill gate from firing.

### WR-06: The BACKTEST block pools every experiment's trades into a single headline metric set

**File:** `src/analytics/cli.py:266-294`
**Reason:** Skipped as instructed. This is a pooling-semantics decision: exclude non-CANDIDATE runs, or add a family / parameter-set slice dimension and label the block as pooled. It changes the D-02 reporting contract.
**Original issue:** Baseline, all-family and Development plus Validation trades are averaged into one Mean R / Win rate / Expectancy.

### WR-10: `LiveEnablementController.enable` trusts a caller-supplied kill-gate state and does not journal it

**File:** `src/execution/enablement.py:147-208`
**Reason:** Needs a design decision. The `enable` docstring deliberately says that "the kill-gate state is deliberately not added to the enable journal payload (the Phase 9 event vocabulary is unchanged)". The module is also intentionally dependency-free and cannot read the journal.

The suggested fix changes:
- the `enable` API (a verdict or event id instead of a state);
- the Phase 9 LIVE_ORDERS_ENABLED payload vocabulary;
- where the "latest evaluation" check lives.

No production caller exists yet, so the operator enable flow should decide this.

**Original issue:** Any caller can pass WITHIN_BUDGET, and the audit trail cannot show which verdict authorised the enable.

### WR-12: `--record` accepts an arbitrary decisions file, and file-only resets bypass the journal reset event

**File:** `src/analytics/cli.py:179, 312-320, 553-568`
**Reason:** Needs a governance decision. The three suggested options each change a contract:
- Refusing a non-default `--decisions` still allows an uncommitted edit of the default file. That is a partial fix that could give false assurance.
- Adding `decisions_sha256` changes the KILL_GATE_EVALUATION payload key set, which is documented as a constant one-way contract.
- Requiring resets to be journal events changes the D-03 design, in which `resets` is part of the committed decision record.

A human should choose one.

**Original issue:** A recorded evaluation cannot be traced to the committed human record, and no production code writes KILL_GATE_QUESTION_APPROVED.

### WR-13: Gate cells G07, G08 and G10 turn MET based on self-reported booleans in the evidence file

**File:** `src/adapters/analytics_files.py:462-475`, `src/analytics/gates.py:84-99`
**Reason:** Needs an evidence-schema and governance-matrix decision. There are two ways to fix it:
- Require artifact references (uncertainty-report digest, reproducibility-run id, baseline experiment ids), which changes the `analytics-evidence/1` schema.
- Render the cells as "NOT_EVALUATED (self-attested)", which changes the gate-status vocabulary and the render goldens.

Both change the reporting contract that kill-gate evidence cites.

**Original issue:** A hand-edited flag prints MET in the governance matrix.

## Notes

- **Commit method:** Commits were made with `git commit`, staging only the explicit paths of each fix. The pre-existing changes in `.planning/config.json` and `.planning/state.json` were never staged.
- **Stash side effect on `config.json`:** A `git stash` / `git stash pop` pair was used once to compare the mypy baseline. The stash covered only those two `.planning` files.
  - After the pop, `.planning/config.json` no longer shows as modified. Its only earlier difference was a line-ending/stat difference: `git diff` was empty, and the content matches HEAD, including `use_worktrees: false`.
  - `.planning/state.json` keeps its modification.
- **Info findings for follow-up:** The out-of-scope Info findings IN-01 to IN-10 are untouched.

---

_Fixed: 2026-09-29T09:33:14Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
