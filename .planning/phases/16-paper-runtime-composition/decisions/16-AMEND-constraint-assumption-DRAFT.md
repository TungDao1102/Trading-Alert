# DRAFT: amendment text for the declared exchange-constraint assumption (research-run-1)

status: DRAFT for reviewer and user. Nothing here is in force. No protocol, DECISIONS, DOC_STATUS, GEOMETRY_AUDIT or test file has been edited. Drafted 2026-10-13 by the orchestrator after the user's decision "chọn C" (decisions/16-DEC-O-03b-constraint.md).

## 0. Questions the user (and reviewer) must answer before anything lands

Q1. Route.
- (a) A protocol amendment v2.2.0 to v2.3.0 by the D032/D043 procedure, landed as its own quick task like v2.2.0 (quick 261011-mi1: seven commits).
- (b) A supplementary DECISIONS row only (the protocol header stays v2.2.0).
- Facts: Appendix A of the protocol says a semantic change to the cost model, execution simulation or acceptance reporting bumps a minor version; a wording fix bumps a patch version. Either bump moves every witness that hard-codes the header version: tests/test_kill_gate_docs.py (`_header_version() == "v2.2.0"`, test_header_version_is_the_d067_amendment), tests/test_decision_alignment_protocol.py, tests/test_decision_alignment_bookkeeping.py, scripts/decision_alignment/protocol.py, .github/workflows/research-gate.yml, docs/DOC_STATUS.md, docs/DECISIONS.md, docs/research/holdout_consumed.json (names the version), the two run-1 hypothesis files, and mentions in docs/backtest/BACKTEST_SPEC.md, docs/configuration/CONFIGURATION.md and docs/operations/DEPLOY_GUIDE.vi.md.
- Route (b) moves none of them but leaves a mandatory reporting rule outside the "frozen contract".

Q2. Bundling. The cross-family multiplicity blocker (RESEARCH_PROTOCOL.md section 4, about 14 percent worst case) very likely also needs a protocol change. Two separate bumps (v2.3.0, v2.4.0) cost two landings; one bundled v2.3.0 costs one. This is an orchestrator observation, not a decision.

Q3. Lineage. Appendix A: "a semantic change to the protocol triggers a new strategy-version lineage" (TRADING_STRATEGY_SPEC section 12). Whether v2.3.0 restarts the lineage must be stated by the amendment owner (read the D067 precedent for v2.2.0 first). The 48 immutable parameter sets of research-run-1 (O-02) must not change.

Q4. Classification. D052(e) and D-30 already describe back-extrapolation of the earliest row, flagged and counted; D052(h) already used "today's constraints applied to the whole window" for plumbing runs. What is new here is using extrapolated constraints for strategy evidence, with a mandatory sensitivity and reporting rule. Semantic (minor bump) or clarification (patch)? Orchestrator view: semantic, because it adds a mandatory field to every experiment report and a scenario rule to the search discipline.

## 1. Proposed protocol text (usable for route (a); for route (b) it becomes the DECIDED clause of the DECISIONS row)

### New subsection in section 2 (Cost model), after "Quantization": "Exchange-constraint assumption (v2.3.0)"

> The point-in-time exchange constraints (tick size, step size, minimum quantity, minimum notional) of a research run are a declared research assumption, not a reconstruction of the exchange's history. A run reads them from one immutable constraint file named by the manifest (`constraint_source`) and bound by its sha256 (`constraint_sha256`). When every row of that file was observed after a bar closed, the simulator selects the earliest row for that bar and flags the selection `extrapolated` (D-30, D052 item (e)). Back-extrapolation does not establish that a historical order of that size would have been accepted by the exchange at that time. A result is valid only under the stated constraint assumption. The assumption, the observation time of each row and the provenance of the file (what is in the snapshot, which source the collector is designed to read, and what is not independently verified) are recorded with the run.

### Addition to section 4 "Uncertainty reporting - required fields"

> - Constraint assumption: the constraint file path and sha256, the observation time of each symbol's row, the count and the ratio of constraint selections flagged `extrapolated` (reported as produced by the runner, never hidden or reinterpreted), and the fields (tick, step, minimum quantity, minimum notional) through which the assumption can change sizing or rejection.
> - Constraint sensitivity: for every pre-registered sensitivity scenario (section 3 below), the same record produced under that scenario, reported next to the baseline and labelled as a stress test.

### Addition to section 5 "Search discipline"

> Constraint scenarios are pre-registered before the first run: a scenario is a separate constraint file with its own hash, manifest and authorization. A scenario is never chosen, added, dropped or re-valued after a result is seen, and sensitivity results are never used to select among scenarios, candidates or parameters. The Holdout is never read to compare scenarios. If a Holdout sensitivity method is wanted, it needs its own decision before the Holdout is touched.

### Migration paragraph (route (a))

"This is a semantic amendment (cost model inputs and acceptance reporting, sections 2, 4 and 5) per D032, D043 and the decision of 2026-10-13 (user: `chọn C`). The v2.2.0 text is unchanged in git history at commit <HASH-AT-LANDING> and is superseded, not edited. What changes: the declared constraint assumption, its reporting fields and the scenario pre-registration rule above. What does not change: G1 to G5 (word for word), the split, the variant budget, the Holm-Bonferroni rule, the D030 rule, the holdout rule, the experiment identity tuple (seven fields) and the parameter sets of research-run-1. Lineage consequence: <TO BE STATED BY THE AMENDMENT OWNER, Q3>."

### Amendment log line (route (a))

`- **v2.3.0 - <DATE> - D068 (semantic).** Declared exchange-constraint assumption for research runs, constraint reporting fields and pre-registered constraint scenarios; no gate, threshold, split or identity change.`

D068 is the next free number after D067; re-check at landing.

## 2. Draft DECISIONS row (D068) and DOC_STATUS line

- Row title (route (a)): "Research protocol v2.3.0 frozen: declared exchange-constraint assumption and constraint scenarios". Route (b): "Declared exchange-constraint assumption for research-run-1 (supplement to protocol v2.2.0)".
- Status: "Accepted (<DATE>, implements the user decision `chọn C` of 2026-10-13 recorded in .planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-03b-constraint.md)".
- DECIDED: baseline file docs/research/preregistration/research-run-1-constraints-baseline.json, sha256 4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f (earliest row per symbol, 12 symbols, all observed 2026-10-03T03:11:57.803909Z, so 100 percent of selections in the window are extrapolated); the clauses of section 1 above; the sensitivity plan of section 3.
- UNCHANGED: as in the migration paragraph.
- OPEN, not decided: cross-family multiplicity, Q1 to Q4, the REEFUSDT diagnostic, the O-03 authorization.
- DOC_STATUS line: the existing `research/RESEARCH_PROTOCOL.md` index line gains the new version and D068 (route (a)); no change in route (b).

## 3. Sensitivity plan (for the reviewer to approve before any real research run)

Scenarios (pre-registered; nothing else is run):
- S0 baseline: the file above.
- S1 stress: identical to S0 except BTCUSDT.min_notional = 100 (USDT). Basis: one secondary report that the BTCUSDT minimum notional was 100 until 2026-04-14 (not an official source; see evidence/16-37-constraint-history.md). Labelled a stress-test assumption, not verified history. S1 needs its own constraint file and sha256, created at freeze time; the file does not exist yet.

Not quantified (no historical source, no invented values): tick, step and minimum quantity for all 12 symbols; minimum notional for the 11 other symbols (ETH's official change on 2023-11-02 is before the window).

Runs: the runner takes one grid and one authorization per run (evidence/16-37-consistency.md). Three families x two scenarios = six (manifest, grid, authorization) pairs. The 48 parameter sets and the grids do not change; only `constraint_source` and `constraint_sha256` (hence `manifest_hash`, hence `data_manifest_hash` in every record) differ.

Data: Development and Validation folds only. The Holdout is not read for S1 or for any comparison; the single-use rule is unchanged (S0 only, per the existing protocol). Whether the Holdout run is repeated under S1 is a separate decision.

Reporting: for each family, S1 next to S0, per record: the fields listed in section 1 above, plus the count of BTCUSDT plans rejected for notional or minimum quantity and the BTCUSDT trade count, as information. No ranking, no selection, no "better scenario". If S1 changes a family's pass or fail state on a gate, that is reported as a limit of the evidence, not used to pick a candidate.

Independent items: the REEFUSDT diagnostic (Development only, no record) and the KG-1 to KG-4 declaration do not depend on this plan.

## 4. GEOMETRY_AUDIT reference (to be added by the amendment owner)

docs/research/GEOMETRY_AUDIT.md lines 133 and 165 state that the back-extrapolated BTCUSDT row is "not valid for strategy evaluation" for a 30-day plumbing check. That conclusion stays as written. Proposed sentence after line 165: "Since <DATE> a research run may use back-extrapolated constraints only as the declared assumption of D068 (or of decision 16-DEC-O-03b-constraint), with the extrapolated count reported and the sensitivity scenarios pre-registered; the plumbing-check conclusion of this audit is unchanged." The wording is a proposal.

## 5. Landing checklist (route (a)), for the plan that will do it

1. The user answers Q1 to Q4; the reviewer approves this text and section 3.
2. A quick task (like 261011-mi1) changes in one go: the protocol (header, migration, section text, amendment log), the DECISIONS row, DOC_STATUS, the hard-coded version witnesses listed in Q1, the hypothesis-file version mentions if they bind the version, and GEOMETRY_AUDIT. It runs tests/test_decision_alignment*.py, tests/test_kill_gate_docs.py, tests/test_research_feasibility.py and `scripts/verify_decision_alignment.py all` (expects ALL_PASS).
3. An evidence file like evidence/16-28-amendment-check.txt.
4. Only then 16-37 Task 3 builds the S0 manifest and the S1 constraint file and manifest.
