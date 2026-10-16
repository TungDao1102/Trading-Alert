---
phase: 16-paper-runtime-composition
batch: 3
reviewed: 2026-10-16T00:00:00Z
depth: deep
files_reviewed: 40
files_reviewed_list:
  - src/research/__init__.py
  - src/research/authorization.py
  - src/research/feasibility.py
  - src/research/manifest.py
  - src/research/manifest_build.py
  - src/research/multiplicity.py
  - src/research/plateau.py
  - src/research/register.py
  - src/research/report.py
  - src/research/run.py
  - src/research/settlement_evidence.py
  - src/backtest/case.py
  - src/backtest/engine.py
  - src/backtest/experiment.py
  - src/backtest/funding.py
  - src/backtest/lifecycle.py
  - src/backtest/records.py
  - src/backtest/report.py
  - src/backtest/semantics.py
  - src/core/features.py
  - src/core/pivots.py
  - src/core/planner.py
  - src/core/strategy.py
  - src/domain/rationale.py
  - src/domain/registry.py
  - src/execution/gates.py
  - src/data/case_input.py
  - src/analytics/approval_delay.py
  - src/analytics/cli.py
  - src/analytics/killgate_guard.py
  - src/analytics/latency.py
  - src/analytics/lifecycle.py
  - src/analytics/render.py
  - src/analytics/render_killgate.py
  - src/analytics/render_sidecar.py
  - src/analytics/report.py
  - src/adapters/analytics_files.py
  - src/adapters/binance_public.py
  - src/adapters/binance_usdm.py
  - src/ops/backup_remote.py
findings:
  critical: 2
  warning: 5
  info: 7
  total: 14
status: issues_found
---

# Phase 16 (batch 3): Code Review Report

**Reviewed:** 2026-10-16
**Depth:** deep (import graph and call chains traced: run -> case_input -> simulator/engine -> lifecycle/funding -> experiment.assemble; analytics cli -> killgate_guard -> render/render_sidecar)
**Files Reviewed:** research stack, Phase-16-changed backtest modules, core strategy path, registry/rationale, execution gates, case input, analytics, Binance adapters, backup_remote
**Status:** issues_found

## Summary

Counts: 2 Critical, 5 Warning, 7 Info.

The highest-impact defect is in the research runner: every research window (Development and each of
the four Validation folds) is simulated from a case that holds no bars before the window start,
although the engine supports warm-up bars before `data_window.start_utc`. The 4H EMA200 therefore
cannot clear for the first ~800 hours of every window. The committed research-run-1 records confirm
it: a 73-day Validation fold record (`docs/research/experiments/research-run-1/02584e47...json`,
`research-run-1-b01`, fold starting 2025-12-15) carries `WARMUP_INSUFFICIENT = 8756`, about 796
hourly evaluations for each of the 11 symbols with data, so ~45% of every fold yields no trade. Up to
~1200 h into each window the 1000/300-bar strategy/context windows are also shorter than the ones the
paper runtime always uses, so indicator values differ from paper for most of each fold. This affects
the G1 per-fold floor, every pooled Validation figure and backtest/paper parity. No document says
that folds start cold. The protocol describes them as "walk-forward test folds (anchored training
window from the dataset start)".

The second Critical is in the D061 F kill-gate guard. When a conclusion is withheld, the JSON
sidecar replaces only `verdict.state`. `any_pass`, `pass_count`, both budget flags, `sticky` and the
full family gate matrices stay in the sidecar, so the withheld conclusion can be rebuilt from the
file. This contradicts the Markdown's own statement that these are withheld.

Verified as correct (no finding):
- `compute_features` last-bar optimisation. Operand order, pinned precision, warm-up/gap ordering
  and exception order are identical to the old full-series path. The only theoretical difference is
  that `abs()` used to run in the ambient context; it is now pinned. Under the default context that
  changes nothing.
- Holm step-down arithmetic, including ties and m=48.
- Plateau neighbour selection.
- Feasibility counting: SL/TP2 closed, END_OF_DATA and SETTLEMENT counted apart.
- Settlement-evidence recomputation (exact Fractions, tick widening, union).
- Terminal-settlement handling in engine/lifecycle/funding: advance to T, settle, funding clipped at
  T, DAILY_STOP drop.
- Holdout isolation: `as_of_day_utc = validation_end.date()` refuses any day at or after the
  holdout start, and nothing in `src/research` writes `holdout_consumed.json`.
- Checkpoint header/body hashing.
- The `binance_usdm` -> `binance_public` delegation.

## Critical Issues

### CR-01: Research windows are simulated cold. Validation folds and Development get no warm-up history, so ~45% of each fold is WARMUP_INSUFFICIENT and indicators diverge from paper

**File:** `src/research/run.py:295-305` (`_simulate_split`), with `src/backtest/engine.py:354-359` (the engine already supports warm-up closes before `data_start`) and `src/backtest/engine.py:801-810` (1000/300 trailing windows)

**Issue:** `_simulate_split` builds every case with `build_case_input_data(start_utc=window.start_utc, end_utc=window.end_utc, ...)`, so neither strategy nor context bars exist before the window start. `strategy.evaluate` needs EMA200 on the 4H context stream (`src/core/strategy.py:730-774`), which takes 200 closed 4H bars (800 h, about 33 days). In every 73-day Validation fold the first ~33 days produce only `WARMUP_INSUFFICIENT`. The stored records confirm this: 8756 warm-up counts in a single fold record is about 796 per symbol for 11 symbols.

Until ~1000 h (setup) and ~1200 h (context) into the window, `_setup_window` and `_context_window` also return fewer than 1000/300 bars. The SMA-seeded EMAs are then seeded at the fold start instead of 1000/300 bars back, so features differ from what the paper runtime computes with its full REST warm-up (D-02, 16-RESEARCH "REST warm-up with the 1000/300 engine windows"). Only the last ~23 days of each fold match paper semantics.

**Failure scenario:** The G1 floor of 30 closed trades per fold and 100 pooled is judged on ~55% of the intended Validation time. A candidate that would pass G1 fails it, or G2/G3 statistics come from a sample biased toward the end of each fold. The paper soak then runs a feature definition that research never evaluated for most of each fold. All 240 research-run-1 records carry this.

**Fix:** Load warm-up history before each window and let the engine skip it, which it already does for closes before `data_start`. For example, build strategy/context bars from `window.start_utc - warmup_span`, where the span covers `STRATEGY_WINDOW_BARS` 1h bars and `CONTEXT_WINDOW_BARS` 4h bars (at least 50 days, rounded to whole days). Keep `data_window` and the minute source at the window, and include the warm-up files in `dataset_id`:
```python
WARMUP_DAYS = 50  # >= max(1000 h, 300 x 4 h) rounded up, a STRUCTURAL value
data = build_case_input_data(raw_root, ..., start_utc=window.start_utc - timedelta(days=WARMUP_DAYS),
                             end_utc=window.end_utc, ...)
case = data.to_case_input(...)
case["data_window"]["start_utc"] = window.start_utc.isoformat()  # engine skips earlier closes
```
For the first Development window the warm-up must come from before `development_start_utc`, so the manifest needs a recorded warm-up start. Development warm-up may read Development data, but Validation warm-up must not read the holdout. This is a semantics change: it needs a decision record, a new run, and a regression test that asserts no fold records `WARMUP_INSUFFICIENT` once warm-up data exists. Untested today.

### CR-02: The D061 F withheld kill-gate conclusion leaks through the JSON sidecar

**File:** `src/analytics/render_sidecar.py:100-105` (`_report_plain`), `src/analytics/render_sidecar.py:121`

**Issue:** With `blocked_by` non-empty, `_report_plain` replaces only `plain["kill_gate"]["verdict"]["state"]`. The rest of `to_plain(report)` is written unchanged:
- `kill_gate.verdict.any_pass`, `pass_count`, `families_budget_met`, `months_budget_met`, `whole_months`, `sticky` and `verdict.families`;
- `kill_gate.families`, the per-family gate matrix.

The state is a deterministic function of these fields. The Markdown says "The verdict, budget, clock and family matrices are withheld" (`src/analytics/render_killgate.py:327-331`), and D061 F says no kill-gate conclusion may be shown on real evidence while WR-01/06/12/13 are unresolved.

**Failure scenario:** An operator runs `python -m src.analytics.cli` on real evidence without `--record`. The Markdown shows NOT CONCLUDED, but `report.sidecar.json` holds `"any_pass": false, "families_budget_met": true, "months_budget_met": true`. That is an INSUFFICIENT_EDGE conclusion in all but name, available to anyone who opens the file. `verify_render` accepts the pair because it compares against the same partial redaction. Untested: `tests/test_killgate_guard.py` checks only `kill_gate_withheld` and the state.

**Fix:** Redact the whole conclusion subtree when blocked, and verify the redaction:
```python
def _report_plain(report, blocked_by):
    plain = to_plain(report)
    if blocked_by:
        plain["kill_gate"]["verdict"] = {"state": NOT_CONCLUDED, "rule_ref": RULE_REF}
        plain["kill_gate"]["families"] = []
    return plain
```
The report digest still commits to the full report, which is acceptable because it reveals nothing. Add a test asserting that `any_pass`, `pass_count`, `*_budget_met` and the family rows are absent from a blocked sidecar.

## Warnings

### WR-01: Fixture evidence downgrades a report that also reads real database rows, and the verdict can then be journaled

**File:** `src/analytics/cli.py:741-756`, `src/analytics/cli.py:769-791`

**Issue:** `_report_blockers` takes the evidence class only from the evidence file. `_build_inputs` also reads the live journal rows from `DATABASE_URL` (`live=_live_inputs(database, ...)`, `journal_events=events`). An evidence file marked `"evidence_class": "fixture"` therefore makes the whole report FIXTURE, even though its LIVE section and journal events are real.

**Failure scenario:** `--evidence fixture.json --record` with `DATABASE_URL` set to the production database gives `blocked_by == ()`. The full verdict is rendered, and `_record_step` appends a `KILL_GATE_EVALUATION` to the real journal. This is the exact action D061 F forbids. "Default-deny" fails open on mixed inputs.

**Fix:** Treat the run as REAL whenever any non-fixture source is read:
```python
evidence_class = EvidenceClass.REAL
if args.evidence is not None and _database_url(args) is None:
    evidence_class = load_evidence_file(args.evidence).evidence_class
```
At minimum, refuse `--record` with fixture evidence. Load the evidence file once and pass the same object to both `_report_blockers` and `_build_inputs`; today it is read twice, a TOCTOU. Untested.

### WR-02: Research records attest no trades. Every research record has `result_summary_json="{}"`, so drift and resume integrity cannot be checked

**File:** `src/research/run.py:342-358` (`_assemble_split` never passes `result_summary_json`), `src/research/run.py:511-532`, `src/backtest/experiment.py:1089-1104`

**Issue:** `assemble` defaults `result_summary_json` to `"{}"`, so `stored_trades_digest(record)` is `None` for all 240 research records. The trade lists exist only in memory, or in the optional external checkpoint directory, which the docs say to keep outside the repository. As a result:
1. `verify_experiment` cannot detect cross-version drift for any research record, because its stored-digest branch is skipped.
2. In `--checkpoint-dir` mode a record file is accepted as `present` when its bytes equal the newly built record. That record carries only counts, so a resumed run whose reused windows hold different trades than a fresh run would still compare equal.
3. The future G3 bootstrap producer must re-simulate, and nothing binds its trades to the recorded experiment ids.

**Failure scenario:** A checkpoint window was produced before an uncommitted local change was reverted with an amend under the same commit text, or a non-deterministic engine path exists. The resumed run writes byte-identical records while feasibility, plateau and G1 counts come from different trades. No artifact can show it.

**Fix:** Persist `trades_digest` (and the closed/end-of-data counts) in `result_summary_json` when assembling. This changes the experiment record bytes, so it needs a decision and a regeneration inventory:
```python
result_summary_json=_canonical_json({"trades_digest": sha256_hex({"trades": output["trades"]})})
```
Alternatively, write the trade lists next to the records under a digest named in the record.

### WR-03: The runner resolves `constraint_source` against the process CWD, while the manifest builder resolves it against the repository root

**File:** `src/research/run.py:94-101` (`Path(manifest.constraint_source)`), compared with `src/research/manifest_build.py:339-340` (`repo_root / values["constraint_source"]`)

**Issue:** The two code paths read the same hashed field from different base directories. The runner ignores `--repo-root` for this file. It also accepts an absolute or `..` path from a hand-written manifest, because `load_manifest` never applies `_require_relative_posix` to `constraint_source`, unlike evidence paths.

**Failure scenario:** `python -m src.research.run --repo-root /opt/trading ...` started from another directory refuses with "constraint source unreadable". Worse, an identically named file under the CWD with matching bytes is read from outside the repository. The sha check keeps it fail-closed on content, but the file read is not the one the manifest names relative to the repository.

**Fix:** Validate `constraint_source` as a clean relative posix path in `DatasetManifest.__post_init__` (reuse `EvidenceFile`'s rule), and read it as `(repo_root / manifest.constraint_source)` with the same `is_relative_to(root)` confinement as `_evidence_bytes`.

### WR-04: `--repo-root` decouples `code_version` and the dirty-tree check from the code and registry that actually run

**File:** `src/research/run.py:582-594`, `src/research/run.py:786`

**Issue:** `read_code_version(repo_root)` and `_code_paths_dirty(repo_root)` inspect the tree named by `--repo-root`. The simulator, strategy and `load_parameter_set` execute from the imported package and read `REGISTRY_ROOT` from the module location (`src/domain/registry.py:41`), not from `repo_root`.

**Failure scenario:** Run from a working copy with uncommitted edits to `src/core` or `params/`, passing `--repo-root` that points at a clean checkout of the same commit (for example the frozen image path). Records claim `code_dirty=false` and the checkpoint guard passes, while the results come from modified code or parameters. That is an identity gap: different code, same experiment id.

**Fix:** Drop the option, or require `Path(repo_root).resolve() == _REPO_ROOT` and refuse otherwise. Code version must describe the tree the code was imported from.

### WR-05: Duplicate grid points are accepted, leading to a partial record write in normal mode and double counting in checkpoint mode

**File:** `src/research/manifest.py:523-532` (`ParameterGrid.__post_init__`), `src/research/run.py:658-669`, `src/research/run.py:511-526`

**Issue:** Nothing refuses two grid points with the same `parameter_set_id` or the same varied tuple. Two identical points produce identical `experiment_id`s:
- Without a checkpoint, `_refuse_if_recorded` passes for both because neither file exists yet. The write loop then writes the first record and raises `ExperimentAlreadyRecorded` on the duplicate. This leaves a partial record set, contradicting "a rerun ... writes nothing" and the all-or-nothing intent.
- With a checkpoint, the duplicate is silently reported `present` and its trades are counted twice in feasibility and plateau. `_find` in plateau returns the first match.

`multiplicity.confirmatory_hypothesis_ids` refuses duplicates, but the runner does not.

**Fix:** In `ParameterGrid.__post_init__`, refuse duplicate `parameter_set_id`s and duplicate `varied` tuples, and require every point to vary the same key sequence:
```python
ids = [p.parameter_set_id for p in self.points]
if len(set(ids)) != len(ids):
    raise ManifestError("grid points must have unique parameter_set_id")
```

## Info

### IN-01: Holm arithmetic runs in the ambient Decimal context

**File:** `src/research/multiplicity.py:105-108`

**Issue:** `Decimal(m - index) * p` is not under the pinned `localcontext(prec=28)` that D-10 requires elsewhere. A p-value that is a non-terminating rational, for example (k+1)/(B+1) with B+1 = 960, is already rounded. The product with (m - i) can then land 1 ulp below or above 0.05, and `g3_passes` uses a strict `<`. Any caller that changes the thread context changes the result.

**Fix:** Wrap `holm_adjust` in a pinned `localcontext()`. Preferably accept p-values as `Fraction` (or as `(k, B)` integers) and compare exactly against `Fraction(1, 20)`.

### IN-02: The confirmatory hypothesis set is read from whatever grid files are on disk, not pinned to the authorized grid hashes

**File:** `src/research/multiplicity.py:45-69`

**Issue:** The correction set is "fixed by the three registered grid files", but nothing compares those files' `grid_hash` with the three committed `research-run-1-authorization-*.json` files. An edited grid file silently changes the 48 ids.

**Fix:** Load each authorization and require `grid_hash(load_grid(path)) == authorization.grid_hash` before returning ids.

### IN-03: The kill-gate review registry accepts unknown item ids, despite the docstring

**File:** `src/analytics/killgate_guard.py:13-14`, `src/analytics/killgate_guard.py:160-163`

**Issue:** The module docstring says an "unknown" registry entry raises. In the code, `_CANONICAL_SCOPES.get(item.id)` returns `None` for an unknown id and the item is accepted with any scope. This does not unblock anything, but it is a doc/code disagreement in a fail-closed loader.

**Fix:** Refuse ids not in `_CANONICAL_SCOPES`, or correct the docstring.

### IN-04: `run.main` returns exit 2 only for four exception types; other refusals end in a traceback with exit 1

**File:** `src/research/run.py:825-837`

**Issue:** The following are not mapped to "run refused" with exit 2: `CaseInputError`/`CaseInputGapError` from `_check_manifest_against_store`, `UnregisteredParameterSet`, `FeasibilityError`, `PlateauError`, `FundingCoverageError`, the engine's terminal-input `ValueError`, `subprocess.CalledProcessError` from `git status`, and an `OSError` from `os.link`. Behaviour stays fail-closed, but the CLI contract "exit 2, cause on stderr" does not hold for them.

**Fix:** Catch `CaseInputError`, `UnregisteredParameterSet`, `FeasibilityError`, `PlateauError` and `subprocess.SubprocessError` explicitly and map them to `EXIT_REFUSED` with a one-line cause.

### IN-05: `_create_exclusive` assumes the filesystem supports hard links

**File:** `src/research/run.py:480-496`, `src/research/manifest_build.py:430-435`

**Issue:** On FAT/exFAT or some SMB shares, `os.link` raises `OSError` (not `FileExistsError`). The run then aborts after its checkpoints were written, with no `run refused` message.

**Fix:** Fall back to `open(path, "x")` plus write plus fsync when `os.link` raises `OSError` with errno `EPERM` or `ENOTSUP`, or refuse up front with a clear message.

### IN-06: JSON duplicate keys are silently last-wins in the manifest, grid and authorization loaders

**File:** `src/research/manifest.py:571-585`, `src/research/authorization.py:66`

**Issue:** A manifest, grid or authorization file holding a key twice is hashed and authorized on the parsed (last) value. A human reviewing the committed file can read the first value.

**Fix:** Pass `object_pairs_hook` to `json.loads` and refuse duplicate keys.

### IN-07: The backup provider check normalises case and whitespace, but rclone receives the raw value

**File:** `src/ops/backup_remote.py:138-149`

**Issue:** `BACKUP_S3_PROVIDER=" aws"` or `"aws"` exempts the endpoint requirement (`.strip().lower()`), but rclone receives the raw string, and the docs spell it `AWS`. If rclone does not recognise the lowercase or padded spelling, the backup fails at run time rather than at configuration validation.

**Fix:** Validate the provider against the exact set {`AWS`, `Wasabi`, `Other`}, or pass the normalised canonical spelling to rclone.

---

_Reviewed: 2026-10-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
