# 16-REV-16 brief: how the frozen data manifest enters the experiment identity

Plan 16-28, Task 1 (tracer). Facts re-read on 2026-10-11 against the working tree at commit
c8332df (branch develop). This brief decides nothing, pre-selects nothing and recommends
nothing. The choice is the user's (D065 item 2). Task 2 records it in `16-DEC-REV-16.md`.

## 1. The question

Protocol v2.2.0 (REV-16, D065 item 2) must put the identity of the frozen data manifest into
the experiment identity before the first real research run. Two routes:

- Route A: redefine `dataSnapshotId` (`data_snapshot_id`) as the identity of the frozen manifest.
- Route B: keep `dataSnapshotId` as it is and add a seventh identity field holding the manifest
  identity.

D065 item 2, verbatim: "preferred design is dataSnapshotId equal to the identity of the
complete frozen manifest if that does not break existing semantics, and if it does the plan may
propose a seventh identity field and bring that choice to the user, who decides". D065 also
records its reading of the evidence: "redefining it as a richer manifest hash would force the
dataset_id formula and its fixtures to change, while a seventh field leaves that binding
untouched". Section 5 below checks that reading against the current code; it differs in places.

## 2. Re-verified facts (current line numbers)

Line numbers in `src/backtest/experiment.py` have not moved since the CONTEXT read of
2026-10-07; every cited line was re-read.

| Fact | Where (current) |
|------|-----------------|
| `ExperimentRecord` docstring: "The six identity fields are ... `data_snapshot_id` (64-hex SHA256 of the dataset version)" | `src/backtest/experiment.py:232-236` |
| field `data_snapshot_id: str` on the record | `experiment.py:263` |
| `__post_init__` requires a non-empty 64-hex string for `experiment_id`, `parameter_set_hash`, `data_snapshot_id`, `cost_model_hash`, `universe_hash` | `experiment.py:293-303` |
| `to_dict()` emits `data_snapshot_id` (the `analytics-evidence/2` shape) | `experiment.py:426` |
| `assemble(... data_snapshot_id: str ...)` parameter | `experiment.py:623` |
| `assemble` docstring: run refused when `dataset_id` "is absent or is not `data_snapshot_id`" | `experiment.py:646-651` |
| `assemble` reads `run_summary["dataset_id"]`; missing -> `IncompleteExperimentRecord` (WR-03) | `experiment.py:704-709` |
| `assemble` refuses when `dataset_id != data_snapshot_id` | `experiment.py:710-713` |
| `experiment_id = sha256_hex(identity_payload)`; payload carries `data_snapshot_id` plus strategy_id, strategy_version, parameter_set_hash, code_version, cost_model_hash, run_type, time range, universe_hash, simulator_semantics_version, split_role, split bounds | `experiment.py:732-748` (key at 736) |
| record is built with `data_snapshot_id=data_snapshot_id` | `experiment.py:755` |
| reproducibility check `_check_run_binds_record`: the re-run `dataset_id` must equal `record.data_snapshot_id`, else `ExperimentReproducibilityBroken` | `experiment.py:971-1002` (read at 983, compare at 994-998) |
| `dataset_identity(raw_root, files)`: sha256 of the sorted `{posix relative path, sha256 of file bytes}` list | `src/data/case_input.py:252-263` (formula documented at 23-30) |
| DATA_MODEL 2.13 (D-18): `dataset_id` "is carried as `ExperimentRecord.data_snapshot_id` so a research result names the exact bytes it was computed from" | `docs/data/DATA_MODEL.md:391` |
| engine `run_summary` carries `dataset_id` (optional 64-hex case key) | `src/backtest/engine.py:345`, `src/backtest/case.py:86,588-593` |
| manifest: `DatasetManifest` dataclass, field `dataset_id` (the `dataset_identity` of the published files over development start through validation end) | `src/research/manifest.py:72-100` |
| manifest identity: `canonical()` embeds `dataset_id`, symbols, universe_id, all six split boundaries, intervals, data source and version, excluded periods, known gaps, equity, risk_rate, constraint_source and its sha256 | `manifest.py:162-193` |
| manifest hash: a MODULE FUNCTION `manifest_hash(manifest) = sha256_hex(manifest.canonical())`, not a method (the plan text says `DatasetManifest.manifest_hash()`; the name is the same, the shape is not) | `manifest.py:235-237` |
| authorization stores `manifest_sha256` and the gate compares it with `manifest_hash(manifest)`, else `RunNotAuthorized("manifest_hash_mismatch")` | `src/research/authorization.py:88,106-107` |
| runner: the single seam `experiment_identity_inputs(manifest, dataset_id) -> {"data_snapshot_id": dataset_id}`, documented as the one place REV-16 is applied | `src/research/run.py:71-78` |
| runner: the store check compares the case `dataset_id` over the whole research window (development start to validation end) with `manifest.dataset_id` | `run.py:119-140` |
| runner: each split (`_run_split`) builds its OWN case over `window.start_utc..window.end_utc`, so `data.dataset_id` is a per-window id that differs from `manifest.dataset_id`; that per-window id is what `assemble` binds today | `run.py:143-199` (identity at 181, `**identity` at 197) |
| closed key set of the `analytics-evidence/2` experiment object: every key required, any extra key refused; `data_snapshot_id` is one of `_EXPERIMENT_PLAIN_KEYS` | `src/adapters/analytics_files.py:98-138`, enforced in `_load_experiment` at 599-640 |
| protocol section 5 "Experiment linkage tuple": experimentId, strategyVersion, parameterSetHash, dataSnapshotId, codeVersion, costModelHash; "not considered reproducible without all six"; `dataSnapshotId` "identifies the exact dataset snapshot used" | `docs/research/RESEARCH_PROTOCOL.md:325-338` |
| CONFIGURATION section 7 lists the same six; BACKTEST_SPEC calls it "the canonical six-field identity tuple" | `docs/configuration/CONFIGURATION.md:143-155`, `docs/backtest/BACKTEST_SPEC.md:156` |
| research-gate CI step checks the six camelCase names (`REQUIRED=(strategyVersion parameterSetId parameterSetHash dataSnapshotId codeVersion costModelHash)`) | `.github/workflows/research-gate.yml:81` |
| protocol header today: `Protocol version: v2.1.0`, FROZEN, Frozen on 2026-09-19, Amended on 2026-10-07 | `RESEARCH_PROTOCOL.md:3-7` |
| `holdout_consumed.json`: `protocol_version` v2.1.0, `entries: []` (no experiment consumed yet; v2.2.0 applies from the first real run, nothing backwards, D060) | `docs/research/holdout_consumed.json:3-4` |
| `protocol_version` does not appear in `src/` or `params/` as a strategy input (per D065; `feasibility.py` only cites "v2.1.0" in comments) | `src/research/feasibility.py:31,34,37` |

Files that pin `data_snapshot_id` values (the six named by D065 and CONTEXT, all confirmed
present):

1. `tests/backtest_case_helpers.py` (`DEFAULT_DATASET_ID = "1" * 64` at 370, `assemble_kwargs`
   default `"data_snapshot_id": "1" * 64` at 416, `strategy_run_summary` `dataset_id` at 389,
   `build_experiment` at ~365-380)
2. `tests/test_backtest_binding.py` (148, 183, 306)
3. `tests/test_backtest_experiment.py` (97, 127, 699, 918, and the binding test at 1126-1137)
4. `tests/test_analytics_provenance.py` (35, 88, 97)
5. `tests/test_analytics_render.py` (1355)
6. `tests/test_analytics_report.py` (121)

Further holders found on re-read (not in the D065 six): `tests/test_research_runner.py`
(279 and the seam test at 288-291), fixtures `tests/fixtures/phase6/registry_identity/{input,expected}.json`,
`tests/fixtures/phase7.1/{match,wrong_fee,wrong_funding,precision_drift}/input.json`,
`tests/fixtures/phase10/report_composite/input.json:128`,
`tests/fixtures/phase10/render_golden/{expected.md:632,expected.json}`,
`tests/fixtures/phase10/loaders/evidence_sample.json:30`, and the case-input tests that pin the
`dataset_identity` formula (`tests/test_case_input_builder.py:222-603`,
`tests/test_minute_source.py:365-398`).

## 3. Route A - redefine dataSnapshotId as the frozen-manifest identity

Meaning: `data_snapshot_id` of every record of a run equals `manifest_hash(manifest)`
(`src/research/manifest.py:235`), the same value the user's authorization artifact stores as
`manifest_sha256`. Protocol section 5 keeps six fields; the meaning of the fourth changes from
"the exact day files a run read" to "the complete frozen manifest".

Code consequences:

- `src/research/run.py:71-78`: `experiment_identity_inputs` returns
  `{"data_snapshot_id": manifest_hash(manifest)}`. The seam test
  `tests/test_research_runner.py:288-291` (`inputs == {"data_snapshot_id": "f" * 64}`) changes.
- The binding at `experiment.py:704-713` (`run_summary.dataset_id == data_snapshot_id`) can no
  longer hold as written, because the run summary carries the per-window `dataset_identity`
  while the record would carry the manifest hash. Two sub-variants exist, and the amendment
  owner must pick one inside the route:
  - A1: keep the D-18 `dataset_identity` formula; move the binding. The record then no longer
    names the per-window files directly, and the anchor that `_check_run_binds_record`
    (`experiment.py:994-998`) compares the re-run `dataset_id` against has to come from
    elsewhere (a new field, `result_summary_json`, or a recomputation from the manifest). Note
    a consequence of how the runner works today: all five split records of one run would share
    one `data_snapshot_id` (they differ today because each split has its own window and
    file set); they would still differ in `experiment_id` through `split_role` and the split
    bounds.
  - A2: change the `dataset_identity` formula itself so that the case `dataset_id` already is
    the manifest identity. This reaches `src/data/case_input.py:252-263`, DATA_MODEL 2.13
    (D-18), `tests/test_case_input_builder.py` (222, 267-285, 317-318, 527-603),
    `tests/test_minute_source.py` (365-398) and every `dataset_id` consumer, and conflicts with
    the manifest embedding `dataset_id` (the manifest hash would then have to contain its own
    identity); it needs a design that avoids that circularity.
- `ExperimentRecord` docstring (`experiment.py:236`) and DATA_MODEL 2.13 wording change;
  the `assemble` docstring (646-651) changes.
- Protocol section 5 / CONFIGURATION section 7: the definition of `dataSnapshotId` changes; the
  count stays six.
- Tests that pin or exercise the dataset binding and would be re-pinned or rewritten:
  - `tests/test_backtest_experiment.py` `test_assemble_refuses_a_run_over_another_or_no_dataset`
    (1126-1137) and the default binding via `tests/backtest_case_helpers.py` (370, 389, 416);
    these are the tests that fail first because they assert exactly the equality that moves.
  - `tests/test_backtest_binding.py` (148, 183, 306), which assembles from fixture
    `data_snapshot_id` values (fixtures `tests/fixtures/phase6/*`, `phase7.1/*`) with a matching
    `strategy_run_summary` `dataset_id`.
  - `tests/test_research_runner.py` (279, 288-291).
  - A2 only: the `dataset_identity` tests listed above.
- The analytics side: `tests/test_analytics_provenance.py` (35, 88, 97),
  `tests/test_analytics_render.py` (1355), `tests/test_analytics_report.py` (121) and the
  fixtures `phase10/report_composite/input.json:128`, `phase10/render_golden/expected.{md,json}`,
  `phase10/loaders/evidence_sample.json:30` carry opaque 64-hex strings. On the current code they
  do not fail merely because the meaning of the field changes (no analytics code validates the
  value against a manifest or a file set). They would be re-pinned only if the amendment chooses
  to give them manifest-shaped values, or if A moves a derived value (a computed
  `experiment_id`, which no file in the six pins as a literal; `registry_identity/expected.json`
  holds `PLACEHOLDER_FILLED_AT_GREEN`). The plan's item 4 and D065 expect these to be re-pinned
  under A and left alone under B; the re-check shows the analytics pins are re-pinned by
  decision rather than forced, while the dataset-binding tests are forced. Plan 16-05 marks the
  kill-gate fixtures `evidence_class: fixture`, so re-pinning them never changes a real result.
- D065 preference: stated above (preferred if it "does not break existing semantics"). It is
  recorded, not applied here.
- Landing rule (consistency item 4): any re-pin happens in the separate amendment task, never
  in a Phase 16 plan.

## 4. Route B - seventh identity field (manifest hash embedding dataset_id)

Meaning: `data_snapshot_id` stays the `dataset_identity` of the files a run read (D-18
unchanged); a new field (name to be chosen by the amendment, for example `data_manifest_hash`)
holds `manifest_hash(manifest)`. The manifest embeds `dataset_id`, so the seventh field equals
`manifest_hash(manifest)` directly (consistency item 5).

Code consequences:

- `experiment_identity_inputs` (`run.py:71-78`) returns both values; `**identity` at `run.py:197`
  already forwards a mapping, so `assemble` gains one keyword. The seam test at
  `tests/test_research_runner.py:288-291` changes.
- `ExperimentRecord` gains the field (`experiment.py:259-289`), `__post_init__` validates it as
  64-hex (293-303), `to_dict` emits it (426), `assemble` takes and records it (623, 755) and puts
  it in `identity_payload` (732-748) so it is part of `experiment_id`. Adding a key to the
  payload changes every computed `experiment_id` from then on (this is intended: it is the
  point of putting the manifest into the identity).
- The binding at `experiment.py:704-713` and `994-998` is unchanged: `data_snapshot_id` is still
  the per-window `dataset_identity`, so the per-window byte identity stays on every record.
  The `dataset_identity` formula, DATA_MODEL 2.13 and the case-input tests are untouched.
- The six pinned test files keep their `data_snapshot_id` values. What does change (a point the
  D065 reading does not mention): the `analytics-evidence/2` experiment object is a CLOSED key
  set in which every key is required and any extra key is refused
  (`src/adapters/analytics_files.py:98-138`, `_load_experiment` 599-640). A new record field
  therefore needs either (i) an optional key with a default in the loader, or (ii) a new key
  added to every experiment object in the evidence fixtures
  (`tests/fixtures/phase10/loaders/evidence_sample.json`, the `phase10/report_composite` input
  and any other fixture carrying an `experiment` object; `render_golden/expected.*` if the
  provenance rendering shows it) and possibly a schema bump
  (`analytics-evidence/3`). The analytics provenance block
  (`src/analytics/provenance.py`: `ExperimentIdentity` at ~63-93, `data_snapshot_ids` lists at
  111-232) and `src/analytics/render_metrics.py:801,820` list the identity fields and would
  need to decide whether to show the new one. Tests with a closed identity-field list
  (`tests/test_analytics_provenance.py:30-38`, `tests/test_backtest_experiment.py:954`,
  `tests/backtest_case_helpers.py` `make_experiment_record`) gain the new field.
- Protocol section 5 and CONFIGURATION section 7 gain a seventh entry; the phrases "all six",
  "six-field identity tuple" (`RESEARCH_PROTOCOL.md:338`, `BACKTEST_SPEC.md:156`,
  `experiment.py:232`, the `SIX_IDENTITY_FIELDS` name in `tests/test_analytics_provenance.py`)
  and the research-gate CI check (`.github/workflows/research-gate.yml:81`, REQUIRED list) need
  an owner decision about whether the seventh name is required there.
- Landing rule: the same separate amendment task; no Phase 16 code plan edits the protocol.

## 5. Where this brief's reading differs from the D065 / plan text

1. Plan text and D065 say "fixtures untouched" for route B. The six named test files and the
   byte-identity binding are untouched under B, but the closed evidence key set means B touches
   the evidence loader and, unless the key is optional, the evidence fixtures.
2. Plan text and D065 say route A "forces the dataset_id formula and its fixtures to change".
   That holds for sub-variant A2 only. Sub-variant A1 keeps the formula and instead moves the
   `assemble` and reproducibility bindings and needs a new anchor for the per-window check.
3. `manifest_hash` is a module function (`manifest.py:235`), not `DatasetManifest.manifest_hash()`.
   The identity object is the same either way.
4. The per-split `dataset_id` today is per window (`run.py:155-181`); the manifest `dataset_id`
   covers the whole research window (`run.py:125-140`). They are different values, which is why
   route A cannot simply reuse the existing equality.

## 6. Manifest-identity mapping (REV-16, D-25)

The D-25 authorization manifest hash (`RunAuthorization.manifest_hash`, stored by the user as
`manifest_sha256`, compared at `src/research/authorization.py:106`) and the v2.2.0 frozen-manifest
identity must be the same object: `manifest_hash(manifest)` = `sha256_hex(manifest.canonical())`
(`manifest.py:235-237`). The manifest already embeds `dataset_id` (`manifest.py:166`), so:

- Route A: `data_snapshot_id := manifest_hash(manifest)`; the `dataset_id == data_snapshot_id`
  binding of `assemble` moves (see section 3).
- Route B: seventh field `:= manifest_hash(manifest)`; `data_snapshot_id` stays the
  `dataset_identity` of the files read.

Either way a research record names, through one 64-hex value, exactly the manifest the user
authorized.

## 7. Files the separate amendment task touches (per 16-PATTERNS.md "Protocol v2.2.0 amendment task")

Common to both routes: `docs/research/RESEARCH_PROTOCOL.md` header (v2.2.0, FROZEN, amended
date) and section 5 and a changelog entry; `docs/DECISIONS.md` row ("protocol v2.2.0 frozen");
`docs/DOC_STATUS.md`; `docs/research/holdout_consumed.json` (`protocol_version` and, if the
marker schema changes, `schema`); `scripts/decision_alignment/protocol.py`;
`tests/test_decision_alignment_protocol.py`; `tests/test_kill_gate_docs.py`;
`.github/workflows/research-gate.yml` (version witnesses and the REQUIRED identity list);
`docs/backtest/BACKTEST_SPEC.md` pointer; `docs/configuration/CONFIGURATION.md` section 7;
the preregistration and license text; the "since v2.1.0" comments in
`src/research/feasibility.py:31,34,37` (to cite v2.2.0 where the amendment says so);
`src/backtest/experiment.py` (lines 232-236, 259-303, 426, 623-755, 971-1002 as applicable);
the schema and fixtures. G1 (100 pooled, 30 per fold) and G5 (30) sentences stay word for word
(`RESEARCH_PROTOCOL.md:240,244`); no `strategy_version` bumps; `entries` stays empty.
Route-specific additions are in sections 3 and 4. Plan 16-37 then adapts the runner seam
(`run.py:71-78`) to the recorded route and plan 16-46 authorizes the run.

## 8. The six planner consistency items, re-checked against the current files (2026-10-11)

1. v2.2.0 versus SC8: ROADMAP Phase 16 criterion 8 (`.planning/ROADMAP.md:710`) governs the
   paper trial (freeze ticks, coverage); the protocol governs research runs. No overlap; no
   mismatch. Holds.
2. v2.2.0 versus SC9: criterion 9 (`ROADMAP.md:711`, D061 item J) closes PAPER-01/02 and needs
   no G1-G5 result (CONTEXT L-10). The amendment only has to land before plan 16-46. Holds.
3. v2.2.0 versus PAPER-01/02/03 (`.planning/REQUIREMENTS.md:52-54`; traceability 143-145
   unchanged, PAPER-03 stays Phase 26): PAPER-03 excludes test events, planned restarts and gaps
   from evidence and says "no tuning"; the identity change does not touch paper evidence, and
   "a new iteration is a new registration" (`src/research/run.py:59-64`,
   `ExperimentAlreadyRecorded`) agrees. Holds.
4. v2.2.0 versus the WR registry (plan 16-05): the kill-gate path reads experiment records
   carrying `data_snapshot_id` (`tests/test_analytics_provenance.py`,
   `tests/test_analytics_render.py`, `tests/test_analytics_report.py`, plus the phase10
   fixtures). Route A: dataset-binding tests are forced to change, the analytics pins change by
   decision (section 3). Route B: those pins stay, the evidence key set changes (section 4).
   Either way the change belongs to the amendment task, never to a Phase 16 plan, and the
   fixtures are `evidence_class: fixture` (plan 16-05), so no real result moves. Holds, with
   the refinement in section 5.
5. Mapping required by REV-16: section 6. The manifest embeds `dataset_id`
   (`manifest.py:166`). Holds.
6. G1/G5 sentences keep their wording (`RESEARCH_PROTOCOL.md:240,244`; alignment test of plan
   16-12 would fail otherwise, intended); constants in `src/research/feasibility.py:31-37`
   currently cite "v2.1.0" and cite "since v2.1.0" after the amendment per the plan. Holds.

Additional re-checks: `docs/research/holdout_consumed.json` has `entries: []`, so v2.2.0
applies from the first real run and nothing is applied backwards (D060). The protocol header is
still v2.1.0 (no amendment has landed; Task 3 of this plan waits for it).

## 9. What the user decides (Task 2, not done here)

Choose `route-a-redefine` or `route-b-seventh-field`. For route A the amendment owner must also
choose A1 (move the binding, keep the D-18 formula) or A2 (change the formula); the user may
state that preference in the same reply. A reply outside the two ids is recorded as `other`
and the plan stops for re-planning.
