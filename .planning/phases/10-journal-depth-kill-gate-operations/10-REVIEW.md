---
phase: 10-journal-depth-kill-gate-operations
reviewed: 2026-09-29T08:56:55Z
depth: standard
files_reviewed: 121
files_reviewed_list:
  - .gitattributes
  - docs/DECISIONS.md
  - docs/DOC_STATUS.md
  - docs/GLOSSARY.md
  - docs/research/kill_gate_decisions.json
  - docs/research/RESEARCH_PROTOCOL.md
  - scripts/dev/journal-report.ps1
  - scripts/dev/README.md
  - src/adapters/analytics_files.py
  - src/adapters/analytics_store.py
  - src/analytics/__init__.py
  - src/analytics/approval_delay.py
  - src/analytics/cli.py
  - src/analytics/clock.py
  - src/analytics/core_metrics.py
  - src/analytics/excursion.py
  - src/analytics/family.py
  - src/analytics/gates.py
  - src/analytics/inputs.py
  - src/analytics/killgate.py
  - src/analytics/latency.py
  - src/analytics/lifecycle.py
  - src/analytics/live_outcomes.py
  - src/analytics/no_trade.py
  - src/analytics/provenance.py
  - src/analytics/render.py
  - src/analytics/render_common.py
  - src/analytics/render_killgate.py
  - src/analytics/render_metrics.py
  - src/analytics/render_sidecar.py
  - src/analytics/report.py
  - src/analytics/slices.py
  - src/analytics/stats.py
  - src/analytics/types.py
  - src/analytics/universe.py
  - src/domain/enums.py
  - src/execution/enablement.py
  - tests/fixtures/phase10/approval_delay_three_reports/expected.json
  - tests/fixtures/phase10/approval_delay_three_reports/input.json
  - tests/fixtures/phase10/clock_start_provenance/expected.json
  - tests/fixtures/phase10/clock_start_provenance/input.json
  - tests/fixtures/phase10/complete_trade/expected.json
  - tests/fixtures/phase10/complete_trade/input.json
  - tests/fixtures/phase10/digest_regeneration/expected.json
  - tests/fixtures/phase10/digest_regeneration/input.json
  - tests/fixtures/phase10/empty_live5_slice/expected.json
  - tests/fixtures/phase10/empty_live5_slice/input.json
  - tests/fixtures/phase10/idempotent_replay/expected.json
  - tests/fixtures/phase10/idempotent_replay/input.json
  - tests/fixtures/phase10/incomplete_no_1m/expected.json
  - tests/fixtures/phase10/incomplete_no_1m/input.json
  - tests/fixtures/phase10/incomplete_no_fill/expected.json
  - tests/fixtures/phase10/incomplete_no_fill/input.json
  - tests/fixtures/phase10/kill_clock_boundary/expected.json
  - tests/fixtures/phase10/kill_clock_boundary/input.json
  - tests/fixtures/phase10/kill_insufficient_edge/expected.json
  - tests/fixtures/phase10/kill_insufficient_edge/input.json
  - tests/fixtures/phase10/kill_passing_candidate/expected.json
  - tests/fixtures/phase10/kill_passing_candidate/input.json
  - tests/fixtures/phase10/kill_sticky_reset/expected.json
  - tests/fixtures/phase10/kill_sticky_reset/input.json
  - tests/fixtures/phase10/kill_within_budget/expected.json
  - tests/fixtures/phase10/kill_within_budget/input.json
  - tests/fixtures/phase10/live_lifecycle/expected.json
  - tests/fixtures/phase10/live_lifecycle/input.json
  - tests/fixtures/phase10/live_net_r/expected.json
  - tests/fixtures/phase10/live_net_r/input.json
  - tests/fixtures/phase10/loaders/decisions_sample.json
  - tests/fixtures/phase10/loaders/evidence_sample.json
  - tests/fixtures/phase10/loaders/universe_sample.json
  - tests/fixtures/phase10/low_n_slices/expected.json
  - tests/fixtures/phase10/low_n_slices/input.json
  - tests/fixtures/phase10/no_trade_categories/expected.json
  - tests/fixtures/phase10/no_trade_categories/input.json
  - tests/fixtures/phase10/opportunity_skipped_expired/expected.json
  - tests/fixtures/phase10/opportunity_skipped_expired/input.json
  - tests/fixtures/phase10/paper_lifecycle/expected.json
  - tests/fixtures/phase10/paper_lifecycle/input.json
  - tests/fixtures/phase10/render_golden/expected.json
  - tests/fixtures/phase10/render_golden/expected.md
  - tests/fixtures/phase10/render_golden/expected_sections_0_2.md
  - tests/fixtures/phase10/report_composite/expected.json
  - tests/fixtures/phase10/report_composite/input.json
  - tests/fixtures/phase10/short_trade/expected.json
  - tests/fixtures/phase10/short_trade/input.json
  - tests/fixtures/phase10/zero_risk_excluded/expected.json
  - tests/fixtures/phase10/zero_risk_excluded/input.json
  - tests/phase10_helpers.py
  - tests/test_analytics_approval_delay.py
  - tests/test_analytics_cli.py
  - tests/test_analytics_digest.py
  - tests/test_analytics_dual_universe.py
  - tests/test_analytics_edge_guards.py
  - tests/test_analytics_excursion.py
  - tests/test_analytics_files.py
  - tests/test_analytics_incomplete.py
  - tests/test_analytics_latency.py
  - tests/test_analytics_lifecycle.py
  - tests/test_analytics_live_outcomes.py
  - tests/test_analytics_no_trade.py
  - tests/test_analytics_provenance.py
  - tests/test_analytics_purity.py
  - tests/test_analytics_render.py
  - tests/test_analytics_report.py
  - tests/test_analytics_sidecar.py
  - tests/test_analytics_slices.py
  - tests/test_analytics_store.py
  - tests/test_analytics_typing.py
  - tests/test_domain_enums.py
  - tests/test_domain_no_float.py
  - tests/test_execution_enablement.py
  - tests/test_execution_health.py
  - tests/test_execution_manager.py
  - tests/test_kill_gate_clock.py
  - tests/test_kill_gate_docs.py
  - tests/test_kill_gate_event.py
  - tests/test_kill_gate_families.py
  - tests/test_kill_gate_gates.py
  - tests/test_kill_gate_registration.py
  - tests/test_kill_gate_state.py
  - tests/test_kill_gate_sticky.py
findings:
  critical: 2
  warning: 15
  info: 10
  total: 27
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-09-29T08:56:55Z
**Depth:** standard. The resolver lowered this from deep because of the 121-file scope. Cross-file call chains were still traced for report -> killgate/family/gates/stats, cli -> adapters, and adapters -> registry/store.
**Files Reviewed:** 121. All source files were read in full. The tests were checked for flaky or destructive patterns. The fixtures were spot-checked only.
**Status:** issues_found

## Summary

The pure analytics core is careful work. It uses Decimal-only arithmetic, sorted-key digests, injected clocks, and it refuses to pool evidence kinds. I found no float leak and no wall-clock leak in the pure modules.

The defects are in the kill-gate governance path, which is the part that matters most for the D-03 "never auto-clears" invariant:

1. **The sticky terminal depends only on the database.** The committed `recorded_terminal` mirror is loaded and then ignored. Any run without a database (`--no-db`, `DATABASE_URL` unset, or a lost journal) silently turns a terminal INSUFFICIENT_EDGE back into WITHIN_BUDGET or PASSING_CANDIDATE.
2. **Recorded human decisions can be silently dropped.** A decision whose `family_id` does not exactly match a `params/` directory is discarded without an error, and the family shows as NOT_TESTED. I confirmed this with a probe: a TESTED_PASS decision for `trend_pullback` (underscore) was dropped.

Other concerns:

- **Independence test.** The parameter-set-hash half of the independence test is vacuous, because the hash embeds `strategy_id`. The result also depends on the alphabetical order of family ids.
- **`--record` safety.** It accepts a future-dated `--as-of`, and it accepts any decisions file.
- **Silent drops.** Unmapped CANDIDATE experiments and malformed kill-gate journal rows are dropped without any count.
- **Dead code paths.** Several paths are never reached in production: universe verification, the approval-delay OPPORTUNITY buckets, and the kill-gate argument to `enable()` (no production caller passes it).

## Critical Issues

### CR-01: The sticky INSUFFICIENT_EDGE terminal is lost whenever the database is not read; the committed `recorded_terminal` is never used

**File:** `src/analytics/cli.py:333-350`, `src/adapters/analytics_files.py:623-643`, `src/analytics/killgate.py:391-412`
**Issue:** `evaluate()` treats a state as sticky only when `prior_evaluations` contains a KILL_GATE_EVALUATION event. The CLI builds those priors from `database.journal_events` only (`priors_from_events(events)` with `events = ()` when `database is None`).

The decisions file does carry `recorded_terminal` (state INSUFFICIENT_EDGE, `recorded_at_utc`), which is the human-committed mirror of the terminal outcome. `load_decisions_file` parses it into `DecisionsFile.recorded_terminal`, but nothing in `src/` reads that field. Its only uses are the CI tripwire test and a reminder string.

As a result, with `-NoDb`, without `DATABASE_URL`, or after a journal restore that lost the event, the report evaluates the gate from scratch. If the family decisions no longer meet both budgets (for example, after a decision was edited or the evidence set changed), the report shows WITHIN_BUDGET or PASSING_CANDIDATE and the "does not clear itself" banner disappears.

This is fail-open on the one invariant D-03, D030 and GLOSSARY §8.2 call terminal and non-self-clearing. `recorded_at_utc` is also stored as a free string and never parsed as UTC, so it cannot be used even if it were wired in.
**Fix:**
```python
# analytics_files._load_terminal: parse the timestamp
recorded_at = _parse_utc(raw["recorded_at_utc"], "recorded_at_utc", DecisionsFileError, where)
# ... RecordedTerminal(recorded_at_utc=recorded_at, ...)

# cli._build_inputs: merge the committed mirror into the priors
file_priors = (
    ()
    if decisions.recorded_terminal is None
    else (
        PriorEvaluation(
            KillGateState.INSUFFICIENT_EDGE, decisions.recorded_terminal.recorded_at_utc
        ),
    )
)
prior_evaluations = tuple(
    sorted(
        {*priors_from_events(events), *file_priors},
        key=lambda p: (p.evaluated_at_utc, p.state.value),
    )
)
```

### CR-02: Human family decisions whose `family_id` is not a registry directory are silently discarded

**File:** `src/adapters/analytics_files.py:228, 248-278`
**Issue:** `scan_family_facts` iterates only over `_family_ids()` (the `params/` directories) and looks up `decision_by_family.get(family_id)`. It never checks for decisions that match no registry family.

A typo or rename (`trend_pullback` versus `trend-pullback`), or a family directory that was renamed after its decision was recorded, drops the recorded TESTED_PASS or TESTED_FAIL decision without any error. The family then evaluates as NOT_TESTED.

I verified this with a probe: `DecisionsFile(families=(FamilyDecision("trend_pullback", TESTED_PASS, ...),))` yields all three families as `NOT_TESTED`.

The effect is that a recorded pass can vanish (hiding PASSING_CANDIDATE), or a recorded fail can vanish (so the three-family budget is never met and INSUFFICIENT_EDGE never fires). Either way, a human decision input is dropped instead of failing closed.
**Fix:**
```python
unknown_decisions = sorted(set(decision_by_family) - set(candidate_hashes))
if unknown_decisions:
    raise DecisionsFileError(f"families: decisions for unregistered family ids {unknown_decisions}")
```

## Warnings

### WR-01: The family-independence test is partly vacuous and depends on order

**File:** `src/analytics/family.py:104-137`, `src/adapters/analytics_files.py:175-183`, `src/domain/registry.py:395-401`
**Issue:** Independence requires parameter-set hashes that are disjoint from every accepted family. However, `parameter_set_hash` is `sha256({"strategy_id": <directory name>, ...})`, so sets under different directories can never collide. The check is always true, and independence reduces to "distinct sheet bytes + 7 slot headings". A copied family with one edited character in its sheet counts as independently specified.

Families are also accepted greedily in lexicographic `family_id` order, and NOT_TESTED families take part. A new NOT_TESTED directory whose name sorts earlier and has a duplicate sheet therefore takes the sheet hash, and an existing tested family becomes `non_independent` and is no longer counted. Adding a directory can therefore stop the kill gate from firing.
**Fix:** Compare hashes of the `[parameters]` table with `strategy_id` and `parameter_set_id` excluded. Decide independence among TESTED families only, or mark every member of a duplicate group as non-independent instead of letting the first name alphabetically win.

### WR-02: Unmapped CANDIDATE experiments are silently dropped

**File:** `src/analytics/cli.py:326-332`, `src/adapters/analytics_files.py:236-244, 305-309`
**Issue:** `scan_family_facts` computes `unknown_experiment_ids` (CANDIDATE runs whose parameter-set hash matches no registered family), but `cli.py` never reads `scan.unknown_experiment_ids`. These experiments disappear from the family facts and from the INCOMPLETE ledger, which goes against the "counted, never silently skipped" contract.
**Fix:** In `_build_inputs`, add `InputNote("family_scan:unknown_experiments", "UNMATCHED_JOIN", len(scan.unknown_experiment_ids))` to the BACKTEST notes, or fail closed.

### WR-03: The CLI failure contract is broken by exceptions outside `_EXPECTED_FAILURES`

**File:** `src/analytics/cli.py:510-520, 608-609`; `src/adapters/analytics_files.py:165-183`
**Issue:** `scan_family_facts` calls `load_parameter_set`, which raises `UnregisteredParameterSet`, `RegistrySchemaMismatch`, `StrategyKeyOutsideRegistry` and `ParameterSetMutated`. All four are plain `Exception` subclasses, and some messages include the file path.

A malformed `.toml` file, or a `params/` directory name that fails `_check_registry_segment`, therefore escapes `main()` as a raw traceback. The documented behaviour is an "exit 1 + name-only reason" message. The same happens for `UnicodeDecodeError` from `read_protocol_text` and for the `ValueError` raised by `ClockStart` or `clock._require_utc`.
**Fix:** Add the registry exception classes, plus `ValueError` as a last resort that reports only the type name, to `_EXPECTED_FAILURES`. Have `_reason` emit `type(exc).__name__` for them.

### WR-04: `--record` accepts any `--as-of`, including future instants, and writes it into the append-only journal

**File:** `src/analytics/cli.py:571-590`
**Issue:** With `--record --as-of 2030-01-01T00:00:00+00:00`, the months budget is met, and the verdict can be INSUFFICIENT_EDGE. That verdict is appended with `occurred_at_utc = 2030-01-01`.

Evaluations before 2030 ignore it (`prior.evaluated_at_utc < evaluated_at_utc`). Once real time passes that date, it becomes a sticky terminal that nobody actually evaluated at that moment. A deliberately backdated `--as-of` can likewise append evaluations out of order.

For an append-only audit journal, the recorded evaluation instant must be the actual evaluation instant.
**Fix:** When `--record` is set, refuse an explicit `--as-of` (use the single edge clock read). Alternatively, require `as_of <= now` and within a small tolerance, where `now` is the one clock read done inside `_resolve_as_of`.

### WR-05: A failed record returns exit 1 after the report files are written and the success lines are printed

**File:** `src/analytics/cli.py:583-589`, `scripts/dev/journal-report.ps1:21-22`
**Issue:** The contract states "exit 1: the report could not be produced (nothing is written)". `_run` writes both files and prints `Report:`, `Sidecar:`, `Digest:` and `Kill gate:` before `_record_step`, so a record failure returns 1 with the files on disk. Automation that follows the documented exit codes will conclude that no report exists.
**Fix:** Use a distinct exit code (for example, 3 = "report produced, record failed") and document it. Alternatively, perform the record before the writes, and remove the pair if the record fails.

### WR-06: The BACKTEST block pools every experiment's trades into a single headline metric set

**File:** `src/analytics/cli.py:266-294`
**Issue:** `_backtest_inputs` concatenates trades from every evidence entry into one `EvidenceInputs(kind=BACKTEST)`. This includes baseline runs (`run_type != CANDIDATE`, which `scan_family_facts` skips for exactly that reason), every family, and both Development and Validation experiments.

Section 3 then shows one "Mean R / Win rate / Expectancy" for the mixture, and nothing in the slice dimensions separates them by family or parameter set. Baseline (simple-trend) trades are averaged together with candidate trades.
**Fix:** Exclude non-CANDIDATE runs from the headline outcomes, or add a family / parameter-set slice dimension and label the unsliced block as pooled across families.

### WR-07: Research-universe hash verification is never wired, so it always reports NOT_APPLICABLE

**File:** `src/analytics/cli.py:334-350`, `src/analytics/universe.py:73-83`
**Issue:** `ReportInputs.expected_universe_hash` defaults to `None`, and `_build_inputs` never sets it, although each `ExperimentRecord.universe_hash` is available. A `--universe` file that differs from the universe the experiments were run on is never flagged as `UNVERIFIED_UNIVERSE`.
**Fix:** Derive the expected hash from the CANDIDATE experiments' `universe_hash`. If they disagree with each other, show `UNVERIFIED_UNIVERSE`, and pass the result into `ReportInputs`.

### WR-08: The LIVE approval-delay buckets never contain skipped or expired (OPPORTUNITY) signals

**File:** `src/analytics/approval_delay.py:310-327`, `src/analytics/lifecycle.py:421-422`
**Issue:** `_live_record` sets `approved_at_utc` only for APPROVED decisions. `_build_delay` skips any record with `approved_at_utc is None`. So OPPORTUNITY records never reach the `else: _resolve_opportunity(...)` branch, which is dead code. The bucket table and the measured signal-to-approve distribution silently cover approvals only, even though the docstring says "USER_EXECUTED / OPPORTUNITY records ... enter".
**Fix:** Carry the decision time separately (for example, `decided_at_utc = approval.acted_at_utc` for every result) and bucket on that. Otherwise, correct the docstring and remove the dead branch.

### WR-09: The kill-gate verdict cannot be computed or recorded without a complete evidence file; the documented `-Record` usage fails

**File:** `src/analytics/family.py:84-92`, `src/analytics/cli.py:326-332`, `scripts/dev/journal-report.ps1:26`
**Issue:** `FamilyEvidence.__post_init__` requires the development and validation experiment ids of a TESTED family to be a subset of `experiment_ids`. The CLI takes those ids only from `--evidence`. As soon as any family has a recorded decision, `journal-report.ps1 -Record` (the documented usage, which has no `-Evidence`) fails with KillGateInputError.

The governance verdict thus depends on an optional research-evidence file that does not change the rule itself.
**Fix:** Validate the decision's experiment ids against the experiment registry instead of the ad-hoc evidence file. Otherwise, document `-Evidence` as mandatory for `-Record` and enforce it in `parse_args`.

### WR-10: `LiveEnablementController.enable` trusts a caller-supplied kill-gate state and does not journal it

**File:** `src/execution/enablement.py:147-208`
**Issue:** Any caller can pass `KillGateState.WITHIN_BUDGET`. The controller never reads the latest KILL_GATE_EVALUATION or the committed `recorded_terminal`. No production caller exists yet, so the check is advisory only. The kill-gate state that authorised the enable is also deliberately left out of the enable journal payload, so the audit trail cannot show which verdict was relied on.
**Fix:** Have `enable` take the verdict's `journal_event_id` (or the verdict itself), check that its state is not INSUFFICIENT_EDGE and that it is the latest evaluation, and include `kill_gate_event_id` / `kill_gate_state` in the enable event payload.

### WR-11: Malformed KILL_GATE_EVALUATION and QUESTION_APPROVED rows are dropped silently

**File:** `src/analytics/killgate.py:239-292`
**Issue:** `prior_from_event` and `reset_from_event` return `None` for bad JSON, an unknown state or a naive timestamp, and `priors_from_events` drops them. These rows are not counted anywhere: `journal_rows_to_events` counts only mapper failures. A corrupted terminal event therefore makes the sticky state disappear without a trace, which fails open.
**Fix:** Return the number of dropped events from `priors_from_events` and `resets_from_events`, and add it to the INCOMPLETE ledger. Consider failing closed when a KILL_GATE_EVALUATION event cannot be parsed.

### WR-12: `--record` accepts an arbitrary decisions file, and file-only resets bypass the journal reset event

**File:** `src/analytics/cli.py:179, 312-320, 553-568`, `src/analytics/killgate.py:295-328`
**Issue:** The recorded event is built from whatever `--decisions` path is supplied. That can be an uncommitted local copy with an added `resets` entry or an extra TESTED_PASS. The reset is merged in by `_merge_resets`, the sticky state clears, and a non-terminal KILL_GATE_EVALUATION is appended.

The event payload carries no digest or path of the decisions file used, so the recorded evaluation cannot be traced back to the committed human record. D-03 describes the reset as "a separate explicit human reset event", yet no production code ever writes KILL_GATE_QUESTION_APPROVED.
**Fix:** With `--record`, refuse a non-default `--decisions`, or add `decisions_sha256` (normalised bytes) to the verdict payload and evidence digest. Consider requiring resets to exist as journal events when recording.

### WR-13: Gate cells G07, G08 and G10 turn MET based on self-reported booleans in the evidence file

**File:** `src/adapters/analytics_files.py:462-475, 281-301`, `src/analytics/gates.py:84-99`
**Issue:** `reproducibility_verified`, `has_uncertainty_report` and `baseline_summaries_present` are free booleans in a user-supplied JSON file. Nothing ties them to an artifact such as a report hash or a reproducibility-run id. The module docstring says "Only gates whose evidence is a recorded fact can be MET", and family.py says "decided by facts, never by a free-text flag". A hand-edited flag prints MET in the governance matrix.
**Fix:** Require artifact references (for example, the uncertainty-report digest and the baseline experiment ids) and verify that they exist. Otherwise, render these cells as `NOT_EVALUATED (self-attested)`.

### WR-14: The PostgreSQL integration test drops every table on whatever `TEST_DATABASE_URL` points to, and uses the Proactor loop on Windows

**File:** `tests/test_analytics_store.py:529-560`
**Issue:** `Base.metadata.create_all(...)` and then `Base.metadata.drop_all(sync_engine)` run against the configured URL. If `TEST_DATABASE_URL` is set to the dev or operational database, the journal and all entity tables are dropped. The test also calls `asyncio.run(scenario())` without the `SelectorEventLoop` factory that `cli.py:368` documents as required for psycopg async on Windows, so it fails on the primary dev platform when enabled.
**Fix:** Create and drop inside a throwaway schema, or refuse to run unless the database name ends in `_test`. Use `asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)` on win32.

### WR-15: A negative `realized_risk` flips the sign of R in the core metrics, while the excursion engine calls it MALFORMED_ROW

**File:** `src/analytics/types.py:139`, `src/analytics/stats.py:48-50`, `src/analytics/excursion.py:199-200`, `src/adapters/analytics_files.py:402-411`
**Issue:** `TradeOutcome` accepts any finite `realized_risk`, and the evidence loader checks only that it is a valid decimal. `_r_multiple` divides by a negative risk, so a losing trade shows as a win in mean R, win rate and drawdown. For the same trade, `compute_trade_excursion` returns INCOMPLETE(MALFORMED_ROW). The two sections of one report disagree about the same input.
**Fix:** Reject `realized_risk < 0` in `TradeOutcome.__post_init__` (or in `_check_trade_fields`), or treat it as NOT_R_VALUED everywhere.

## Info

### IN-01: The live-posture tie-break favours ENABLED

**File:** `src/analytics/report.py:465-478`
**Issue:** With equal `occurred_at_utc`, the sort key compares `event_type`, and `LIVE_ORDERS_ENABLED` sorts after `LIVE_ORDERS_DISABLED`, so the header shows ENABLED. The value is display-only, but the tie-break should favour the safe posture.
**Fix:** Rank DISABLED after ENABLED at equal timestamps, or order by journal insertion (`created_at_utc`).

### IN-02: The Evidence Overview INCOMPLETE column adds up overlapping buckets

**File:** `src/analytics/render_killgate.py:369-384`
**Issue:** One unmeasured trade is counted under core `NOT_R_VALUED`, under excursion, under each latency leg and under approval-delay. The per-kind sum can therefore exceed the number of outcomes.
**Fix:** Rename the column to "INCOMPLETE entries (all sections)", or count distinct source ids.

### IN-03: TP2 exits are excluded from the "MAE (R) of take-profit exits" diagnostic

**File:** `src/analytics/excursion.py:319`
**Issue:** Only `exit_kind == "TP1"` is included. LIVE outcomes can be `TP2` (`live_outcomes.py:78-82`).
**Fix:** Use `e.exit_kind in {"TP1", "TP2"}`.

### IN-04: Static report copy asserts facts the code does not check, and some provenance fields are missing from the Markdown

**File:** `src/analytics/render_killgate.py:78-81, 97-100`, `src/analytics/render_metrics.py:812-831`
**Issue:**
- `SHARED_COMPONENT_NOTE` hard-codes "Families A and C share the regime detector".
- `LIVE_ROWS_ABSENT` says "Backtest and paper sections are complete" even when those sections are empty.
- The Markdown provenance table leaves out `live_net_pnl_semantics_verified` and `live_r_excludes`, which appear only in the sidecar.

**Fix:** Derive the notes from data or make them neutral. Add the two provenance rows.

### IN-05: `md_cell` leaves Markdown link and emphasis syntax active, and the truncation count can be spoofed

**File:** `src/analytics/render_common.py:82-131`, `src/analytics/render.py:59-61`
**Issue:**
- Journal or decision text such as `[docs](http://x)` renders as a live link. Only `<` and `>` are neutralised.
- `_count_truncations` counts the literal `...[truncated]` marker, so source text that contains the marker inflates TEXT_TRUNCATED.

**Fix:** Escape `[`, `]`, `*`, `_` and `(`. Count truncations with `md_cell_truncated` at call sites instead of scanning the output.

### IN-06: The registration tripwire checks only directory names, and it disagrees with `_family_ids`

**File:** `tests/test_kill_gate_registration.py:91-107`, `src/adapters/analytics_files.py:165-172`
**Issue:** Under a recorded terminal, new parameter sets (`.toml`) can still be added to existing families. `_family_ids` also ignores `_x` and `.x` directories, while the tripwire counts them, so a family named `_new` would be invisible to the kill gate.
**Fix:** Snapshot the sorted candidate parameter-set hashes in `recorded_terminal`, and apply the same directory filter in both places.

### IN-07: A new sticky terminal after a reset still reports the old reset as "Reopened by"

**File:** `src/analytics/killgate.py:408-424, 522-524`, `src/analytics/render_killgate.py:203-214`
**Issue:** For the sequence terminal T1, then reset R1, then terminal T2: `sticky=True`, yet `reopened_by_*` still shows R1, so the banner shows both the sticky note and "Reopened by ...".
**Fix:** Populate the `reopened_*` fields only when `not sticky`, or label them "last reopened".

### IN-08: The wrapper exports every `.env` secret to the analytics process

**File:** `scripts/dev/journal-report.ps1:43`
**Issue:** `Import-DotEnv` loads all keys, including exchange and Telegram credentials, although the CLI needs only `DATABASE_URL`.
**Fix:** Import only `DATABASE_URL` (a filtered Import-DotEnv).

### IN-09: The message "Replaying the same inputs is a no-op" is misleading without `--as-of`

**File:** `src/analytics/cli.py:562-565`
**Issue:** When `--as-of` is omitted, every run uses a new wall-clock second, so a replay appends a new event.
**Fix:** Print the no-op sentence only when `args.as_of` is set.

### IN-10: `_realized_r_by_signal` silently keeps the last value on duplicate signal ids

**File:** `src/analytics/cli.py:256-263`
**Issue:** If two outcomes share a `signal_id`, for example a re-run experiment of the same parameter set over overlapping ranges, the second R silently overwrites the first.
**Fix:** Raise AnalyticsInputError on a duplicate key.

---

_Reviewed: 2026-09-29T08:56:55Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
