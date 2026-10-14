# Quick 261014-nnl: S-B-interval implementation plan set (index)

Source of truth: `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-S-B-interval.md` (user decision, 2026-10-14) and `16-DRAFT-S-B-interval-design.md` rev3 sections 2-8; `16-DEC-GAP-REASON.md` (TerminalDeclaration keeps exactly four fields). Amendment mechanics follow quick 261011-mi1 and 261014-cvk (D032/D043/D052, D053 regeneration precedent).

Paths in all plans are repo-root-relative. Plan files: `261014-nnl-PLAN-01.md` ... `261014-nnl-PLAN-10.md`.

## Plans, order and dependencies

| Plan | Wave | Depends on | Autonomous | Scope | Design items |
|------|------|------------|------------|-------|--------------|
| 01 | 1 | - | false | user authorization of the implementation and evidence provenance (URLs of A, B, F); evidence commit; `.gitattributes -text`; pure recompute module | s2 evidence, test 9 |
| 08 | 1 | - | false | protocol v2.4.0 draft (exact text) and the user's adoption of the text; planning answers quoted, not re-asked | s4, s5 text |
| 03 | 2 | 01 | true | tracer: case key -> engine hook -> lifecycle SETTLEMENT -> ledger -> record; OPEN side; funding clip | s3.1-3.3, 3.7-3.9, tests 4, 5 |
| 02 | 3 | 01, 03 | true | manifest `terminal_settlements`, cross-validation, guard, canonical omission, loader; builder rows only for the window containing T; runner fail-closed evidence check | s2, s4 guard, test 2 |
| 04 | 3 | 03 | true | RESTING at T, `window.dropped`, DAILY_STOP non-rebook, no-plan rule (pinned label position), data-after-T raise, conditional `settlement_count` | s3.2, 3.4-3.6, s4, tests 6, 7, 8, 11 |
| 05 | 3 | 03 | true | consumers: report `_classify` (settlement apart from closed trades, inside the filled coverage population), feasibility, analytics lifecycle, analytics loader, validator, mark-hole count | s4 consumers |
| 06 | 4 | 02, 04, 05 | true | integration through `run_research`: two manifests lower/upper; Validation-only consumer test; pre-bump regression evidence | tests 1, 3, 10 (first half) |
| 07 | 5 | 06 | false | inventory of every version-derived artifact, user approval, bump 2.0.0 -> 2.1.0, regeneration from own build paths | s5, test 10 |
| 09 | 6 | 07, 08 | false | Task 1 blocking-human gate for the one-field holdout marker edit (refusal stops the plan); land adopted v2.4.0 text, D070, D071 (regeneration inventory), DOC_STATUS, BACKTEST_SPEC, witnesses, Validation-only invariant test, one landing commit | s4, s5 |
| 10 | 7 | 09 | true (runs only if plan 09 landed) | full gates (ALL_PASS, suite, ruff, ruff format, mypy, uv lock --check, G1/G5 bytes, params/src/paper untouched), evidence, tracker notes | s5 gates |

Same-wave file overlap: none (wave 1: plan 01 16-DEC-S-B-interval*.md, 16-DRAFT-S-B-interval-design.md, evidence folder, src/research/settlement_evidence.py + plan 08 16-AMEND-v2.4.0-DRAFT.md, 16-DEC-V240.md; wave 2: plan 03 alone; waves 4-7: one plan each; wave 3: plan 02 src/research/manifest.py, run.py; plan 04 src/backtest/engine.py; plan 05 src/backtest/report.py, src/research/feasibility.py, src/analytics/lifecycle.py, src/adapters/analytics_files.py).

## Why some plans are autonomous: false

- 01: 16-DEC-S-B-interval lists code changes and the commit of the two decision files as NOT authorized; the user's own words are recorded first. The request URLs of A, B and F are not in any scratch file (headers carry only the Date), so the user or the orchestrator's own transcript must supply them (or approve one re-fetch per URL). D and E are dropped (planning answer below), so they are not asked about.
- 07: version bump and regeneration are NOT authorized by the decision record; D053 pattern: inventory first, user approval in the user's words, then regeneration from each item's own build path, never typed.
- 08: protocol text is the user's and has not been shown yet; only its adoption is asked. Block 6, the D070/D071 numbering and the shape of block 12 are quoted from the planning answers, not re-asked.
- 09: `tests/test_decision_alignment_protocol.py` line 148 requires `holdout_consumed.json` `protocol_version` to equal the header version, and 16-DEC-S-B-interval lists editing that file as NOT authorized. The user accepted the one-field change at planning only if it runs behind a gated task, so plan 09 Task 1 is its own blocking-human checkpoint: the user's words there are recorded in `16-DEC-V240-marker.md` (`block-12-execution: authorized|refused`), Task 1's verify branches on that line (the refusal branch passes with the marker untouched), and on refusal plan 09 stops before the header bump and plan 10 does not run.

## Forbidden in every plan

Manifest freeze (16-37 Task 3), O-03 and plan 16-46, any Holdout read, any ExperimentRecord outside pytest tmp_path (no research run), editing `docs/research/holdout_consumed.json` (sole exception: plan 09 Task 1, protocol_version only, after the user's words at that checkpoint), git push, editing params/ or src/paper/. Tests that stay untouched in every plan: `tests/test_backtest_funding.py`, `tests/test_paper_shadow_fill.py` and every paper test (they pin no version-derived value); plans 01-06 edit no existing test file at all.

## Fixture-regeneration inventory approach (plan 07)

1. Plan 06 commits pre-bump evidence: full suite green at the old version string with only added test files since the plan-set base (proof that undeclared inputs behave identically).
2. Plan 07 Task 1 captures the 2.0.0 outputs (sha256) of the regression cases, applies the bump in the working tree only, runs the suite, and classifies every failure: VERSION_PIN, DERIVED_DIGEST (trade_id, experiment_id, trades_digest, result_summary_json, goldens), STORED_RECORD (artifacts ExperimentRecord refuses as non-current, e.g. tests/fixtures/phase10/loaders). Any other failure is a semantics leak: stop. Docs mentions of 2.0.0 are classed HISTORY and stay. The bump is reverted and only the inventory is committed.
3. Plan 07 Task 2: the user approves the inventory (sha256 bound into the record).
4. Plan 07 Task 3: bump, regenerate exactly the listed items with the listed commands, re-pin literals, add design test 10 (2.1.0 vs monkeypatched 2.0.0 differ only in the version string and trade_id; captured hashes match).
5. Plan 09 compiles D071 (D053 style) from the inventory and the plan 07 SUMMARY.

## User-confirmed at planning (user, 2026-10-14, words: "ok theo khuyến nghị")

These answers settle design choices only. They do not authorize code changes, commits, the version bump, the protocol text or the holdout marker edit; those stay gated by plans 01, 07, 08 and 09 Task 1.

- Evidence D (tardis access refusal) and E (per-second sample day) are dropped: not copied, not committed, no test reads them.
- The one-field `holdout_consumed.json` change (protocol_version only, entries stay empty) is accepted, but only executed behind the gated task (plan 09 Task 1, the user's words at that checkpoint).
- Design test 1 compares every field of the Validation experiment records except `data_manifest_hash` and `experiment_id`, which must differ (plan 06).
- Names: exit kind `SETTLEMENT`, entry kind `SETTLEMENT_CANCEL`, no-trade label `TERMINAL_BEFORE_ACTIVATION`.
- Label position: equity check -> (strategy evaluate) -> conflict check -> terminal check -> plan. Every existing label keeps its count.
- `settlement_count` in run_summary only when the case declares a settlement (plan 04).
- Bound side and values recorded in a fixed-format `coverage_note` piece; no new TradeRecord fields.
- Evidence folder `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/` (a hashed manifest path must not live in `.planning/`, which `/gsd-cleanup` archives).
- D070 = amendment and the only freeze row; D071 = regeneration inventory.
- v2.4.0 changes simulator semantics, not a strategy rule; `strategy_version` stays v5.0.0 (draft block 6).

## Planner choices still open (confirm or override)

- Report and feasibility show settlement figures only when non-zero: `CountsSection.settlement_count` and `IntrabarCoverage.settlement_trades` join their digest payloads only when non-zero, `development_settlement` is rendered only when non-zero (plan 05; no existing report digest or golden moves).
- Settlement trades are filled trades for the report's intrabar coverage population (total_trades, fallback_count, percent, coverage_notes), so their coverage_note surfaces; they stay out of every closed-trade figure (plan 05, from checker feedback).
- Design test 10 (plan 07) allows `trade_id` to differ besides the version string, because `trade_id` hashes the version (`test_trade_id_hashes_the_version`); the literal design wording names only the version string.
- Funding clip as keyword-only `terminal_at_utc=None` on `funding_events` / `check_funding_coverage` (paper callers unchanged).
- Manifest row stores no copy of T (bound window start only; T comes from the known_gaps declaration).
- Order changed from the suggestion: version bump (07) lands before the protocol text (09) so the frozen text never names a version the code lacks; the draft and adoption (08) run early in wave 1; the full gate run is its own plan (10) so plan 09 stays at three tasks after its marker gate was split out.

## Design clarifications found while planning

- Design test 1 says Validation experiment records are byte-equal; by D067 `data_manifest_hash` (and so `experiment_id`) includes the manifest, whose bounds differ. Plan 06 compares every other field and asserts these two differ.
- The scratch evidence lives in a session temp folder; copy it soon (plan 01 stops on a missing file or a hash mismatch).
- E (per-second sample day) and D (tardis access refusal) had no headers file; the user dropped both on 2026-10-14 (supporting evidence only; the bounds do not depend on them). F (sample-day index klines) stays supporting evidence and is committed only if Task 1 of plan 01 records its URL or a re-fetch.

## Coverage audit

| Source | Item | Plan | Status |
|--------|------|------|--------|
| DEC item 1 | union interval 0.000845 / 0.000887, no proxy | 01, 02, 03 | COVERED |
| DEC item 2 | T 09:00Z and URL confirmed (used in the declaration of tests; no manifest written) | 02 | COVERED |
| DEC item 3 | separate manifest entry, optional case key (no /3), SETTLEMENT apart, guard, one Holm over 48 (unchanged), 2.1.0, v2.4.0 separate | 02-09 | COVERED |
| GAP-REASON | TerminalDeclaration keeps four fields | 02 (forbidden to edit) | COVERED |
| s2 | evidence committed, recompute, `.gitattributes`, URL and fetch time hashed, KG4 host note | 01, 02 | COVERED |
| s2 | cross-validation, one per symbol, exact keys, posix sorted paths, canonical omission, builder rule, S1 carries entry | 02 (S1: tracker note, manifest freeze forbidden) | COVERED |
| s3.1 | funding loaded_end = min(data_end, T), kwarg default None | 03 | COVERED |
| s3.2 | hook advance(end=min(window_end,T)), leg, EXIT before _push_funding, dropped, ranks unchanged | 03, 04 | COVERED |
| s3.3 | adverse bound by side, TP1 remainder, fee, slippage 0 | 03 | COVERED |
| s3.4 | RESTING cancel, one new kind, consumers, exposure removed | 03, 04, 05 | COVERED |
| s3.5 | no-plan rule, pinned label, no 08:30 rule | 04 | COVERED |
| s3.6 | data after T raises, 4h context before T allowed | 04 | COVERED |
| s3.7 | no mark-hole marker to T | 03 | COVERED |
| s3.8 | booking and record share SETTLEMENT rule; sum test; note states side and values | 03 | COVERED |
| s3.9 | stop on 08:59 books before settlement | 03 | COVERED |
| s4 | Holm 48 unchanged; SETTLEMENT apart; consumers (settlement inside the filled coverage population, outside closed-trade figures); guard; Validation-only text and test; adverse-bound statement | 02, 05, 06, 08, 09 | COVERED |
| s5 | 2.1.0, ids change, inventory, protocol pins, DECISIONS, DOC_STATUS, BACKTEST_SPEC, gates, O-03 re-issue (tracker note) | 07, 08, 09, 10 | COVERED |
| s6 tests 1-11 | 1:06, 2:02, 3:06, 4:03, 5:03, 6:04, 7:04, 8:04, 9:01, 10:06+07, 11:04 | all | COVERED |
| s7 / not authorized | manifest freeze, O-03/16-46, Holdout, ExperimentRecord, holdout_consumed.json | every plan forbidden list | EXCLUDED by decision |

## Rollback

Every plan names its own `git revert` order. Whole set: revert 10 (evidence), 09 (landing commit), 07, 06, 05, 04, 02, 03, 01 code commits newest first; decision records stay as history.

## Verify-command conventions

Every `<automated>` command carries a `<fails_when>` sibling. Subset runs name explicit pytest node ids (plans 02 Task 2, 04 Tasks 1-2, 06 Task 1) instead of `-k` filters, so a renamed or missing test fails with exit 4 ("not found") instead of passing on zero selected tests (exit 5).
