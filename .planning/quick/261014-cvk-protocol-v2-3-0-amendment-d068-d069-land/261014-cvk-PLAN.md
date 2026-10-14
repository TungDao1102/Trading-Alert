---
phase: quick-261014-cvk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/research/multiplicity.py
  - tests/test_research_multiplicity.py
  - docs/research/RESEARCH_PROTOCOL.md
  - docs/DECISIONS.md
  - docs/DOC_STATUS.md
  - docs/research/holdout_consumed.json
  - docs/backtest/BACKTEST_SPEC.md
  - docs/research/GEOMETRY_AUDIT.md
  - docs/research/preregistration/research-run-1-hypothesis-ADDENDUM-v2.3.0.md
  - .github/workflows/research-gate.yml
  - scripts/decision_alignment/protocol.py
  - tests/test_kill_gate_docs.py
  - tests/test_decision_alignment_protocol.py
  - tests/test_decision_alignment_bookkeeping.py
  - tests/test_research_run1_registration.py
  - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V230.md
autonomous: false
requirements:
  - QUICK-261014-cvk

estimate:
  tokens: 220000
  tasks: 5
  confidence: low

must_haves:
  truths:
    - "RESEARCH_PROTOCOL.md reads Protocol version v2.3.0, Status FROZEN, Frozen on 2026-09-19 (unchanged, the D013 clock is not restarted), Amended on <landing date>, Supersedes v2.2.0. The v2.2.0 text stays in git at the commit named in the migration paragraph; nothing of v2.2.0 is rewritten outside the sections this plan lists."
    - "G1 and G5 sentences of RESEARCH_PROTOCOL.md are byte-identical to the base commit; the split, the 40/40/20 proportions, the variant budget N = 25 per family, the seven-field identity tuple, the holdout rule and nothing under params/ change; no strategy_version moves; the 48 parameter sets and their hashes are untouched."
    - "G3 reads: one Holm-Bonferroni procedure at family-wise alpha = 0.05 over ONE set of 48 candidate-level one-sided p-values (16 per family, three families), the set fixed by the three registered grids, never reset per family and never extended by a re-run, a sensitivity scenario or a later look. The set always holds all 48 p-values, including candidates that fail G1; a candidate whose p-value cannot be computed because it has no closed Validation trade enters the set with p = 1 (conservative, still counted in m). A candidate passes G3 only when its adjusted p-value is below 0.05. G2 stays a separate conjunctive condition, uncorrected, and cannot make a pass easier. The power note is recomputed the same way as the existing one (critical value times sigma/sqrt(100 trades), sigma about 1.2 R): the smallest Holm threshold goes from 0.05/25 = 0.002 (z 2.878, about 0.35 R) to 0.05/48 = 0.00104 (z 3.078, about 0.37 R), and the note says it never changes the grid or a candidate choice. The old 'about 14%' sentence is removed and replaced by the statement that the family-wise bound now holds across the three families."
    - "src/research/multiplicity.py holds a pure, deterministic Holm step-down (stdlib only, no Polars/NumPy/SciPy) and the 48-hypothesis set builder; tests prove: textbook Holm values, monotone adjusted values capped at 1, tie handling independent of input order, global adjustment never smaller than per-family adjustment for the same p-values, refusal of a missing, duplicate or unknown hypothesis id and of a set that is not exactly the 48 ids of the three registered grids, and a seeded Monte Carlo of true-null p-values over 48 hypotheses whose family-wise false-pass rate is at most 0.05 (fixed seed, fixed tolerance stated in the test)."
    - "The protocol has a new subsection 'Exchange-constraint assumption (v2.3.0)' in section 2, new required reporting fields in section 4 (constraint file path and sha256, observed-at per symbol, extrapolated count and ratio, sensitivity record) and new search-discipline text in section 5 (constraint scenarios S0 and S1 pre-registered; S1 descriptive on Development/Validation only; never read the Holdout to compare scenarios; never select a scenario, candidate or parameter from S1). 100 percent of selections in the window being flagged extrapolated is stated as expected, and the claim is limited to 'valid only under the stated constraint assumption'."
    - "The protocol states, once, what lineage means after this amendment: v2.3.0 changes no detection, entry, SL, TP, invalidation, expiry or feature definition, so TRADING_STRATEGY_SPEC section 12 requires no new strategy version and strategy_version stays v5.0.0 for the 48 sets; 'registration lineage' is the set of experiment registrations made under a protocol version and is NOT the holdout lineage (strategy_id + strategy_version) of the holdout marker; the Holdout is unconsumed (entries empty), so no holdout lineage is affected."
    - "D068 (constraint assumption, S0/S1) and D069 (cross-family multiplicity) are each recorded once, directly after D067, with number collision re-checked at landing; exactly one DECISIONS row carries the phrase 'protocol v2.3.0 frozen' (D068; D069 says it is part of the same release); header, that row and the DOC_STATUS index line agree on v2.3.0; holdout_consumed.json names v2.3.0 with entries still empty."
    - "Every witness that binds the version in force moves to v2.3.0; mentions of v2.2.0 that record where a feature was introduced (the dataManifestHash field, D067, comments in experiment.py, analytics_files.py, run.py and their tests, DEPLOY_GUIDE.vi.md history) are NOT changed."
    - "research-run-1-hypothesis.md is not edited. An addendum file records that G3 is now the global Holm and that the constraint assumption applies; the user's re-affirmation of O-02 under these rules is a recorded user decision (16-DEC-V230.md) before the addendum is committed."
    - "GEOMETRY_AUDIT.md gains one reference sentence after the line-165 item; the old conclusion ('not valid for strategy evaluation') is unchanged."
    - "Decision-alignment gates (all PR gates, DC gates), tests/test_kill_gate_docs.py, the research-gate witness tests, ruff, mypy src, uv lock --check and the full 'uv run pytest -m \"not docker\"' pass on the real repository."
---

<objective>
Land research protocol v2.3.0 by the D032/D043 procedure (precedent: quick 261011-mi1, protocol v2.2.0).
Decisions come from the reviewer's answers, which the user accepted on 2026-10-14 ("đồng ý"), after
re-checking them against the repository (see `<verified_corrections>`). Two decisions, two sections, two
test groups, one release:

- D068: declared exchange-constraint assumption plus scenarios S0 (baseline file,
  sha256 4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f) and S1 (S0 with
  BTCUSDT.min_notional = 100, descriptive stress test only, file not created here).
- D069: cross-family multiplicity, one Holm-Bonferroni over the 48 candidate-level hypotheses.

Purpose: the first research run must not start under a rule the project already knows is weak
(per-family alpha, about 14 percent worst case across three families) or under an unstated assumption
about historical exchange constraints. The amendment must land before the O-03b manifest is frozen
(plan 16-37 Task 3) and before any run authorization (16-46). No experiment has been recorded
(`holdout_consumed.json` entries are empty), so nothing is applied backwards.

Out of scope (separate work, stated so nobody assumes it landed): the O-03b manifest and its freeze, the
S1 constraint file and hash, the REEF diagnostic, the seeded stationary block-bootstrap p-value producer
(it does not exist in `src/`; the multiplicity module takes p-values as input), any run or authorization,
the six S0/S1 execution bindings of plan 16-46 (its scope grows and goes to the roadmap batch), the
`gates.py` G-cell derivation (still PENDING_THRESHOLD_TBD by its own docstring; not changed here), the
grid-path fix in 16-37-PLAN.md Task 1 (`research-run-1-grid.json` does not exist; the grids are three
files).
</objective>

<verified_corrections>
Facts checked against the repository on 2026-10-14 that this plan relies on (do not re-litigate):
1. Grids: three files, 16 points each, 48 in total (docs/research/preregistration/research-run-1-grid-*.json).
2. strategy_version is v5.0.0 for all 48 sets (hypothesis file line 23); TRADING_STRATEGY_SPEC section 12 requires a new
   strategy version only for rule changes, so v2.3.0 does not need one. Protocol line 23 ("a semantic
   change ... triggers a new strategy-version lineage downstream") is the ambiguity this plan resolves in text.
3. The holdout marker defines lineage as strategy_id + strategy_version; "registration lineage" must be
   defined as a different thing.
4. Holm is documented in the protocol and pinned as text by three witnesses (tests/test_kill_gate_docs.py:163,
   scripts/decision_alignment/protocol.py REQUIRED_PREREGISTRATION_PHRASES incl. "about 14%"), but there is NO Holm,
   G2 or G3 computation anywhere in src/. G2/G3 are protocol text only today.
5. D067 is the last DECISIONS row; D068 and D069 appear only in the DRAFT amendment file.
6. Known gaps are one terminal declaration per symbol after plan 16-54 (not 30 GapRanges); irrelevant to this
   amendment except that nothing here touches them.
7. G2 is an uncorrected 95 percent interval bound. Because G3 (Holm) is a required conjunct of the pass, the
   family-wise bound is controlled by G3 alone; G2 can only make a pass harder. The amendment says so and does not
   put G2 into the correction.
</verified_corrections>

<context>
@docs/research/RESEARCH_PROTOCOL.md
@.planning/phases/16-paper-runtime-composition/decisions/16-AMEND-constraint-assumption-DRAFT.md
@.planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-03b-constraint.md
@.planning/phases/16-paper-runtime-composition/evidence/16-37-constraint-history.md
@.planning/quick/261011-mi1-protocol-v2-2-0-amendment-d065-item-2-ro/261011-mi1-PLAN.md
@.planning/quick/261011-mi1-protocol-v2-2-0-amendment-d065-item-2-ro/261011-mi1-SUMMARY.md
@docs/research/preregistration/research-run-1-hypothesis.md

Executor rules: run `codegraph explore` for any `src/` symbol before reading files; never read `.env`; no
network; Python is `.venv/Scripts/python`; Edit only the files in `files_modified`; the repo is on branch
`develop` while earlier 16-37 notes mention `master` - commit where the working branch is, do not switch
branches; line endings: keep LF in blobs (check `git show HEAD:<path>`), `.gitattributes` unchanged. Follow
the mi1 order: record the decision first, tests before code, documents last, gates at the end.
</context>

<tasks>

<task type="checkpoint:decision" gate="blocking-human">
  <name>Task 1: Record the user's acceptance and the O-02 re-affirmation (user words, never inferred)</name>
  <read_first>16-DEC-O-03b-constraint.md, research-run-1-hypothesis.md, the reviewer's answers pasted by the user on 2026-10-14 (quoted in 16-DEC-V230.md by the orchestrator)</read_first>
  <files>.planning/phases/16-paper-runtime-composition/decisions/16-DEC-V230.md</files>
  <decision>Two things only the user can state: (1) the user adopts reviewer decisions Q1 to Q4 (route a, v2.3.0 semantic, constraint and multiplicity in one release with separate sections/tests, no strategy_version bump, v2.2.0 kept as history) and the corrections in `<verified_corrections>`; (2) the user re-affirms hypothesis O-02 and the 48-point registration under the global Holm and the constraint assumption (the hypothesis was approved under per-family Holm; no result exists, so the change is allowed by the pre-registration rule, but only the user can keep O-02 approved).</decision>
  <action>Blocking-human. Write `16-DEC-V230.md` with `option: adopt` or `option: other`, `decided by: user`, `date: <UTC date>` and `words:` (the reply verbatim), then one line per item adopted. The orchestrator already holds the user's "đồng ý" of 2026-10-14 for planning only; it is quoted as context, NOT counted as the O-02 re-affirmation. If the reply is not `adopt`, stop the plan.</action>
  <acceptance_criteria>
    - The record has the option id, the user's words verbatim, the date and "decided by: user", and an explicit line for the O-02 re-affirmation.
  </acceptance_criteria>
  <verify>
    <automated>grep -E "^option: adopt$" .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V230.md</automated>
    <fails_when>non-zero exit</fails_when>
  </verify>
  <resume-signal>Reply "adopt" (and say you re-affirm O-02 under global Holm), or "other"</resume-signal>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Holm multiplicity module, the executable witness of D069 (tests first)</name>
  <read_first>docs/research/RESEARCH_PROTOCOL.md section 4 (G2, G3, Holm sentence), research-run-1-grid-*.json (strategy_id + points), src/research/manifest.py ParameterGrid and its loader, src/research/plateau.py (module style), pyproject.toml (ruff, mypy strict)</read_first>
  <files>src/research/multiplicity.py, tests/test_research_multiplicity.py</files>
  <behavior>
    - Test 1: the textbook step-down. p = (0.01, 0.04, 0.03, 0.005) over m = 4 gives adjusted (0.03, 0.06, 0.06, 0.02) in input order; the test comment shows the sorted derivation 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, max(0.04*1, 0.06)=0.06; adjusted values are non-decreasing in p order and never above 1.
    - Test 2: order independence and ties: shuffling the input mapping gives byte-equal output; equal p-values get equal adjusted values; ordering is by (p, hypothesis id).
    - Test 3: global is never smaller than per-family: for a fixed vector of 48 p-values split 16/16/16, every global adjusted value is at least the same hypothesis's per-family adjusted value.
    - Test 4: `confirmatory_hypothesis_ids()` reads the three registered grid files and returns exactly 48 distinct `(strategy_id, parameter_set_id)` ids, 16 per strategy_id; any other count raises.
    - Test 5: `holm_adjust_confirmatory(p_by_id)` refuses (raises a project error, fail closed) a mapping that has a missing, duplicate-after-normalization or unknown id, a p outside [0, 1], NaN, a non-float, or fewer or more than 48 entries; it never silently drops a hypothesis.
    - Test 6: `g3_passes(adjusted)` is true only for adjusted < 0.05 (strict); 0.05 exactly fails.
    - Test 7: seeded Monte Carlo: with a fixed seed, 2,000 repetitions of 48 independent uniform null p-values, using `random.Random(seed)` (never the global generator), the share of repetitions with at least one G3 pass is at most 0.065 (0.05 + 3*sqrt(0.05*0.95/2000), rounded; Holm under independent true nulls gives about 0.0488, so the expected count is about 98 of 2,000 with standard deviation about 9.6; state this reason in the test) and is greater than 0 (guards an always-reject bug). The same data under per-family Holm at 0.05 and independent families is shown for contrast in a comment, not asserted.
    - Test 8: `inspect.signature(holm_adjust_confirmatory)` has exactly one parameter (`p_by_id`), `__all__` equals the exact list of public names, and the module docstring says scenario results never enter the correction.
  </behavior>
  <action>Write the failing tests, then `src/research/multiplicity.py`: pure, stdlib only (it may use `float`; this is statistical code that never gates an order, per the stack rules). Public names: `confirmatory_hypothesis_ids`, `holm_adjust`, `holm_adjust_confirmatory`, `g3_passes`, `MultiplicityError`, the constants `FAMILY_WISE_ALPHA = 0.05` and `EXPECTED_HYPOTHESES = 48`. Grid reading reuses `load_grid(path)` of `src/research/manifest.py` (strict keys; `.strategy_id`, `.points[].parameter_set_id`); do not duplicate its parsing. The directory is resolved from the repo root as `Path(__file__).resolve().parents[2] / 'docs/research/preregistration'` with an injectable path for tests; the glob is `research-run-1-grid-*.json` and must match exactly 3 files, else raise (`research-run-1-constraints-baseline.json` sits in the same directory and does not match). `MultiplicityError` subclasses `ManifestError`. The mapping type check rejects bool and int explicitly (only float accepted), NaN via `math.isnan`; every function has an explicit `-> float`/typed return for mypy strict. Document in the module docstring: the p-value producer (seeded one-sided stationary block bootstrap on pooled Validation trades) does not exist yet and is a later plan; the module only corrects p-values it is given. STOP conditions (reviewer item 7, binding): the 48 ids do not match the three grids; a parameter-set hash would have to change to link to v2.3.0; the p-value convention for a candidate with no trades cannot be stated without a user decision; or, if the executor finds that the G3 claim as written cannot be represented by this procedure (for example the grid ids are not unique across families, or p-values are not one per candidate), stop before Task 3 and report; do not weaken the tests.</action>
  <acceptance_criteria>
    - Tests 1-8 fail first and pass after; `ruff check`, `ruff format --check` and `mypy src` pass; the module imports only stdlib and in-repo manifest code (manifest.py itself imports `src.domain.canonical`, which is fine; this module is not under `src/core`).
  </acceptance_criteria>
  <verify>
    <automated>.venv/Scripts/python -m pytest tests/test_research_multiplicity.py -q && .venv/Scripts/python -m mypy src</automated>
    <fails_when>non-zero exit</fails_when>
  </verify>
</task>

<task type="auto">
  <name>Task 3: Protocol v2.3.0 text, DECISIONS D068/D069, DOC_STATUS, holdout marker</name>
  <reversibility rating="costly">A frozen protocol version cannot be edited in place; a correction is another amendment (D032/D043).</reversibility>
  <read_first>docs/research/RESEARCH_PROTOCOL.md (header, section 0 amendment procedure, section 2 Quantization, section 4 whole, section 5 Search discipline, Appendix A and amendment log), docs/DECISIONS.md D043 and D067 rows, docs/DOC_STATUS.md lines 13 and 67, the DRAFT amendment sections 1 to 3, 16-DEC-V230.md</read_first>
  <files>docs/research/RESEARCH_PROTOCOL.md, docs/DECISIONS.md, docs/DOC_STATUS.md, docs/research/holdout_consumed.json, docs/backtest/BACKTEST_SPEC.md, docs/research/GEOMETRY_AUDIT.md</files>
  <action>
1. Run `git log -1 --format=%H -- docs/research/RESEARCH_PROTOCOL.md` and keep the hash for the migration paragraph; verify the number D068 and D069 are free (`grep -n "D068\|D069" docs/DECISIONS.md` must be empty outside this plan's files).
2. Header: `v2.3.0`, `FROZEN`, `Frozen on` unchanged, `Amended on` = landing date, `Supersedes: v2.2.0`. Add `### Migration (v2.2.0 to v2.3.0)` in the style of the existing migration paragraphs: semantic amendment per D032, D043, D068, D069; the v2.2.0 text is unchanged in git at the recorded hash and is superseded, not edited; what changes; what does not (G1, G4, G5 text, split, N = 25 per family, seven-field tuple, holdout rule, parameter sets, strategy_version).
3. Section 2: new subsection `Exchange-constraint assumption (v2.3.0)` using the DRAFT wording of section 1, edited so that it states: the baseline file and sha256 above; earliest row per symbol, real observed-at kept; all selections in the window are expected to carry the `extrapolated` flag; back-extrapolation does not show a historical order would have been accepted; a result is valid only under the stated assumption; the flag and its count are reported as the runner produces them.
4. Section 4: replace the G3 sentence and the 'about 14%' sentence per must_haves (one Holm over 48, never reset per family, set fixed by the registered grids, adjusted p below 0.05, G2 uncorrected conjunct, N = 25 per family kept, power note updated to say the smallest Holm threshold is 0.05/48). Add the constraint-assumption and constraint-sensitivity reporting fields to the required uncertainty fields. The replaced Holm and 'about 14%' phrases must be replaced in the witnesses in Task 4, not left dangling.
5. Section 5 Search discipline: the scenario text (S0 confirmatory, S1 descriptive on Development/Validation only, pre-registered, own file/hash/manifest/authorization, no selection, no Holdout comparison, a Holdout sensitivity method needs its own decision first, S1 p-values never enter the correction).
6. Section 0 / Appendix A: one paragraph resolving the lineage wording (must_haves truth 6) and correcting the sentence at protocol line 23 so it reads consistently; add the amendment-log line `v2.3.0 - <date> - D068, D069 (semantic)`. Also add v2.3.0 to the two precedent lists (protocol lines 21 and 416: 'v2.2.0 minor' -> '... v2.2.0 minor, v2.3.0 minor'). The lineage sentence (line 23) may be rewritten: no witness pins it; cite the full path `docs/strategy/TRADING_STRATEGY_SPEC.md` section 12. Keep the new G3 text on ONE line starting `3. **G3 (multiple testing)** -` (parsers split on `**G<n> (` prefixes). D069's text must NOT contain the exact string 'protocol v2.3.0 frozen' (the DC-03 test replaces that string and requires exactly one carrier).
7. DECISIONS: add D068 (constraint assumption; carries 'protocol v2.3.0 frozen'; DECIDED, UNCHANGED and OPEN parts as in the DRAFT section 2, citing 16-DEC-O-03b-constraint.md and 16-DEC-V230.md) and D069 (cross-family multiplicity; says it belongs to the same release; DECIDED: one Holm over 48, G2 conjunct, N = 25 per family; UNCHANGED: thresholds, holdout rule; OPEN: the p-value producer). D069 and the protocol must NOT claim that multiplicity is 'solved' or 'implemented' end to end: they record that the correction rule is adopted and its correction step is implemented and tested on supplied p-values, while the seeded one-sided stationary block-bootstrap p-value producer is still to be built (reviewer stop clause: no claim of resolution without full definition and test). Directly after D067, in this order.
8. DOC_STATUS: update the index line 13 (v2.3.0; add D068, D069) and append a dated log line like line 67. `holdout_consumed.json`: `protocol_version` v2.3.0, `entries` stays empty. This edit does not consume the Holdout; tests/test_decision_alignment_protocol.py:128 REQUIRES `protocol_version` to equal the header version. No ExperimentRecord is written and no Holdout file is read.
9. BACKTEST_SPEC lines 82 and 173: v2.2.0 to v2.3.0 (version in force). GEOMETRY_AUDIT: after the line-165 item add the single reference sentence from DRAFT section 4 as PROSE outside any table (tests/test_geometry_audit_doc.py counts table headers and cells; no table row may be added), with the D068 number and date; the existing sentence stays byte-identical.
10. Compare: `git diff` of the G1 and G5 sentences must be empty; `git diff --stat params/` must be empty.</action>
  <acceptance_criteria>
    - Header, D068 freeze row and DOC_STATUS agree on v2.3.0; exactly one row contains 'protocol v2.3.0 frozen'; the G1/G5 sentences and params/ are unchanged; the diff of the protocol shows only the sections listed.
  </acceptance_criteria>
  <verify>
    <automated>[ "$(grep -c 'protocol v2.3.0 frozen' docs/DECISIONS.md)" = 1 ] && git diff --quiet HEAD -- params</automated>
    <fails_when>count is not 1, or params changed</fails_when>
  </verify>
</task>

<task type="auto" tdd="true">
  <name>Task 4: Move the version witnesses, pin the new rules, add the hypothesis addendum</name>
  <read_first>tests/test_kill_gate_docs.py (lines 150-215), scripts/decision_alignment/protocol.py (REQUIRED_PREREGISTRATION_PHRASES, docstring), tests/test_decision_alignment_protocol.py, tests/test_decision_alignment_bookkeeping.py (DC-03 near line 386), tests/test_research_run1_registration.py, .github/workflows/research-gate.yml line 80, research-run-1-hypothesis.md</read_first>
  <files>.github/workflows/research-gate.yml, scripts/decision_alignment/protocol.py, tests/test_kill_gate_docs.py, tests/test_decision_alignment_protocol.py, tests/test_decision_alignment_bookkeeping.py, tests/test_research_run1_registration.py, docs/research/preregistration/research-run-1-hypothesis-ADDENDUM-v2.3.0.md</files>
  <behavior>
    - Test 1: `_header_version() == "v2.3.0"`; D067 stays exactly once and keeps 'protocol v2.2.0 frozen' as history; D068 and D069 each appear once, after D067 in that order; D068 contains 'protocol v2.3.0 frozen', D069 does not; both cite D032 and D043.
    - Test 2: the protocol contains the new G3 phrases (one Holm-Bonferroni, 48, 'across the three families', 'alpha = 0.05') and no longer contains 'about 14%'; `REQUIRED_PREREGISTRATION_PHRASES` lists the new phrases instead of 'about 14%'; the 'Holm-Bonferroni', 'alpha = 0.05' and 'N = 25' phrases stay.
    - Test 3: the protocol contains the subsection 'Exchange-constraint assumption (v2.3.0)', the sha256 of the baseline file, the words 'extrapolated', 'S0' and 'S1', and the sentence that the Holdout is never read to compare scenarios.
    - Test 4: the G1 and G5 sentences are byte-equal to constants pinned from the base commit.
    - Test 5 (in tests/test_research_run1_registration.py, the only change to that file): the addendum file exists, names v2.3.0, D068, D069, the global Holm and the constraint hash, and the original `research-run-1-hypothesis.md` is byte-equal to its pinned hash (it is not edited).
    - Test 6: DC-03 passes on the real repository with D068 as the freeze row: in `tests/test_decision_alignment_bookkeeping.py` (docstring and line ~389) change `bk._decision_row(text, "D067")` to "D068"; the test's string replacement of 'protocol v2.3.0 frozen' needs exactly one carrier, which is why D069 must not contain the phrase.
    - Test 7: `EXPECTED_SUPERSEDES` in `tests/test_kill_gate_docs.py` (line 79, asserted line 116) moves to "v2.2.0"; `test_header_version_is_the_d067_amendment` (lines 209-211) is renamed to the D068 amendment and asserts v2.3.0; line 225 keeps 'D067' in the DOC_STATUS index line and also expects D068 and D069; the module docstring (lines 6-15) gains a v2.3.0 mention.
  </behavior>
  <action>Order inside the plan: Task 4's witness tests are written against the new text and committed together with Task 3's documents (the docs land first, so 'fails first' holds only for tests that need the Task 2 module or the addendum; do not claim red-first for the phrase tests). Write the witness tests, then move the witnesses. Then move only witnesses that bind the VERSION IN FORCE: the research-gate comment, the `protocol.py` docstring and phrase tuple, the header-version assertion, the DC-03 row witness. Do NOT touch mentions that record where a feature was introduced (dataManifestHash, D067 text, comments in `experiment.py`, `analytics_files.py`, `run.py`, their tests, CONFIGURATION line 158, DEPLOY_GUIDE.vi.md). Write the addendum (what changes for the hypothesis: G3 is the global Holm over 48; the constraint assumption and S0/S1 apply; what does not change: the three families, 48 points, grid hashes, strategy_version, the hypothesis text itself) and commit it only after Task 1's O-02 re-affirmation exists. If a DC or PR gate needs a different freeze-row convention than D068, adapt to the gate (the gate is the authority) and record the choice in the SUMMARY.</action>
  <acceptance_criteria>
    - Tests 1-7 pass after (red-first only where stated); no historical v2.2.0 mention changed (verify by `git diff -U0` listing only version-in-force lines).
  </acceptance_criteria>
  <verify>
    <automated>.venv/Scripts/python -m pytest tests/test_kill_gate_docs.py tests/test_decision_alignment_protocol.py tests/test_decision_alignment_bookkeeping.py tests/test_research_run1_registration.py -q</automated>
    <fails_when>non-zero exit</fails_when>
  </verify>
</task>

<task type="auto">
  <name>Task 5: Full gates, evidence, tracker notes</name>
  <read_first>261011-mi1-SUMMARY.md (gate list), 16-28-amendment-check.txt (evidence layout)</read_first>
  <files>.planning/phases/16-paper-runtime-composition/evidence/16-V230-landing-check.txt</files>
  <action>Run and record in the evidence file: `.venv/Scripts/python scripts/verify_decision_alignment.py all` (expects ALL_PASS), `uv run pytest -m "not docker"`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check`, the byte-equality check of the G1/G5 sentences against the base commit, `git diff --stat -- params tests/fixtures` (empty), `git show HEAD:<path>` LF check for every edited text file. Then write the SUMMARY (status complete only if every command passed; otherwise incomplete with the failing output). No new PR/DC check is added, so `EXPECTED_MIN` in scripts/verify_decision_alignment.py stays; if an executor adds one, bump `EXPECTED_MIN["protocol"]` (currently 11). Do NOT edit STATE.md or ROADMAP.md except what the quick workflow itself does. Tracker notes for the orchestrator, not edits: (a) plan 16-37 Task 1 reads `research-run-1-grid.json` (three files exist), (b) plan 16-46 scope grows to six S0/S1 bindings and needs the p-value producer, (c) protocol-gate cells in `src/analytics/gates.py` still say PENDING_THRESHOLD_TBD, (d) the manifest freeze, S1 file and REEF diagnostic follow in the order: verify inventory and constraints, REEF diagnostic (Development, S0, no record), freeze manifest with one REEF terminal declaration, then O-03.</action>
  <acceptance_criteria>
    - The evidence file shows every command with its exit status; ALL_PASS is printed; the SUMMARY states exactly what ran and what did not.
  </acceptance_criteria>
  <verify>
    <automated>.venv/Scripts/python scripts/verify_decision_alignment.py all | grep -q ALL_PASS</automated>
    <fails_when>ALL_PASS is not printed</fails_when>
  </verify>
</task>

</tasks>

<threat_model>
- Silent weakening of a gate while editing the protocol: mitigated by byte-equality tests on the G1 and G5 sentences, the pinned phrase tuple, and the rule that G2 can only be a conjunct.
- Cross-family correction implemented as per-family by mistake: mitigated by tests 3 and 7 of Task 2 (global never below per-family; seeded family-wise rate over all 48).
- Scenario S1 used to pick a candidate or touch the Holdout: mitigated by the section 5 text, by the single-mapping signature of the Holm function, and by the out-of-scope list; the S1 file does not exist after this plan.
- Retroactive change of a pre-registration: no result exists; the user's O-02 re-affirmation is recorded before the addendum is committed; the original hypothesis file is hash-pinned.
- Historical record rewritten: v2.2.0 text stays in git at the recorded hash; historical v2.2.0 mentions are untouched; D067 stays.
</threat_model>

<output>
After completion create `.planning/quick/261014-cvk-protocol-v2-3-0-amendment-d068-d069-land/261014-cvk-SUMMARY.md`.
</output>
