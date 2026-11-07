---
phase: 25-demo-integration-test-campaign
plan: 08
subsystem: demo-scenario-framework
tags: [D-04, D-05, scenario-harness, catalog, evidence-index, tdd, APRV-01, EXEC-01, OPS-02]
requires: [25-01, 25-02]
provides:
  - "tests/support/demo_scenarios/catalog.py: the pinned S01-S20 catalog (Scenario, SCENARIOS, by_id)"
  - "tests/support/demo_scenarios/harness.py: labels, ScenarioRecorder, EnvOptions, ScenarioEnv, build_fake_scenario_env, ensure_clean_start, account_clean, Demo fixture contract constants"
  - "tests/support/demo_scenarios/s01_happy.py: S01 as async run(env, recorder) -> str over run_composed_smoke"
  - "tests/support/demo_scenarios/evidence_index.py: write_session_index (per-session JSON + markdown index)"
affects: [25-09, 25-10, 25-11, 25-12, 25-13, 25-14, 25-15, 25-16, 25-17, 25-18, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "labels per step: SYNTHETIC forced on a synthetic env, DEMO_FAULT_INJECTED for an injected trigger, never DEMO_OBSERVED"
    - "evidence reuses EvidenceRecorder.write (scrub, atomic, post-write scan); no new JSON writer"
key-files:
  created:
    - tests/support/demo_scenarios/__init__.py
    - tests/support/demo_scenarios/catalog.py
    - tests/support/demo_scenarios/harness.py
    - tests/support/demo_scenarios/s01_happy.py
    - tests/support/demo_scenarios/evidence_index.py
    - tests/test_demo_twin_s01_happy.py
    - tests/test_demo_evidence_index.py
    - tests/test_demo_harness.py
  modified: []
key-decisions:
  - "ensure_clean_start runs in s01_happy before the smoke (the smoke records no precondition); the harness account_clean is NOT called by S01 because the smoke already records its own account_clean step (orders, algo orders, positions after the close). Later scenarios call both."
  - "Open approvals are counted by the harness, not by the live make_open_demo_approvals_reader: the in-memory shadow store of the twin writes no APPROVAL_MODE_RECORDED marker, so that reader never sees a PENDING approval on the fake. The harness reader is stricter (no marker check; the store is DEMO-scoped on Demo) and also stops counting a plan whose status is EXPIRED/INVALIDATED/SUPERSEDED or whose expiry time has passed (a refused plan stays APPROVED past expiry and then holds nothing)."
  - "A recorder whose default label is SYNTHETIC refuses any other label (ValueError), so a synthetic run can never hold a Demo-looking step (T-25-19)."
  - "build_fake_scenario_env refuses a non-zero clock_offset: it is a Demo-env option (the S09 twin uses the existing drift-test technique), and silently ignoring it would hide a wrong test."
requirements-completed: [APRV-01, EXEC-01, OPS-02]
status: complete
duration: 40min
completed: 2026-11-07
commits: 6
plan_head_before: 13a465d9555fecca8836dcbeeacd63b1558dd44f
plan_head_after: 34e776c6c9c83c86f338bbed65fcef56b7f2bd30
actuals:
  tokens: 13700
  tasks: 3
  commits: 6
---

# Phase 25 Plan 08: Scenario framework and S01 Summary

The catalog, harness and evidence format every later scenario plan uses, proven end to end by S01 (happy path) on the fake composed process: 20 pinned scenario ids, a labelled per-scenario evidence file (`demo-scenario-evidence/schema-1`), clean-start and cleanup helpers that stop with the `scripts/demo_clear.py` instruction, and a per-session evidence index. Nothing under `src`, `scripts`, `pyproject.toml` or `uv.lock` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): catalog, harness, S01 on the fake | 1549e853 | 9b90b68e |
| 2: per-session evidence index | 1fb08b6f | a8888a76 |
| 3: clean start, cleanup, harness unit tests | a94899ca | 34e776c6 |

## Harness API for plans 25-09 to 25-16

`tests/support/demo_scenarios/harness.py` (all names importable from it):

| Name | Signature / value |
|---|---|
| labels | `SYNTHETIC`, `DEMO_OBSERVED` (re-exported from `dr.EVIDENCE_KIND_*`), `DEMO_FAULT_INJECTED`, `NOT_OBSERVED`, `LABELS` |
| `label_for` | `label_for(env, *, injected: bool) -> str`: synthetic env gives SYNTHETIC always; Demo gives DEMO_FAULT_INJECTED if injected else DEMO_OBSERVED |
| `ScenarioRecorder` | `ScenarioRecorder(scenario_id, *, mode: dr.RunMode, environ=None, clock, default_label=None)`; subclass of `dr.EvidenceRecorder`; `scenario_id` must be in the catalog (KeyError otherwise); `default_label` defaults to SYNTHETIC for DRY_RUN, DEMO_OBSERVED for EXECUTE; attribute `default_label` is settable (S01 sets it from `env.label`) |
| `.add_step` | `(name, status, detail)`: adds `label = default_label` (what the smoke's `_smoke_record` calls) |
| `.add_labeled_step` | `(name, status, detail, *, label)`: unknown label ValueError; a SYNTHETIC-default recorder refuses non-SYNTHETIC |
| `.record_health` | `(verdict | None)`: appends `{is_no_trade, degraded, failing, at}` to `details["health"]`; facts only |
| document | `schema` = `demo-scenario-evidence/schema-1`, `scenario_id`, `evidence_kinds` (sorted distinct step labels); stem `25-DEMO-SCENARIO-<DRYRUN\|EVIDENCE>-<id>-<stamp>`; `write(dir)` inherited |
| `EnvOptions` | frozen: `faults: FaultEdge \| None`, `sdk_faults: SdkFaults \| None`, `store_faults: StoreFaults \| None`, `clock_offset: timedelta = 0` |
| `ScenarioEnv` | Protocol: SmokeEnv attributes + `faults`, `sdk_faults`, `store_faults`, `synthetic`, `label`, `wiring`, `async abandon()` |
| `build_fake_scenario_env` | `(tmp_path, options: EnvOptions) -> FakeScenarioEnv`; omitted fault objects are fresh; the env a `restart()` builds is a `FakeScenarioEnv` too; non-zero `clock_offset` raises ValueError; `abandon()` is a no-op |
| `ensure_clean_start` | `async (env, recorder) -> None`: step `precondition_clean` PASSED, or FAILED plus `ScenarioPrecondition` (message: counts only, `scripts/demo_clear.py` instruction) |
| `account_clean` | `async (env, recorder) -> bool`: step `account_clean` PASSED/FAILED with the same counts |
| `read_account_counts` / `AccountCounts` | `normal_orders, algo_orders, positions, open_approvals` for `dr.SYMBOL`; read before arming a fault (a fault armed on a snapshot method would be consumed) |
| Demo fixture contract | `FIXTURE_SCENARIO_RECORDER = "scenario_recorder"` -> callable `(scenario_id) -> ScenarioRecorder` (EXECUTE mode, phase evidence dir); `FIXTURE_MAKE_DEMO_ENV = "make_demo_env"` -> async callable `(recorder, options: EnvOptions) -> ScenarioEnv`; both implemented by plan 25-09 |

`catalog.py`: `Scenario(id, slug, title, roadmap_bullet, plan, requirements, module, twin_test, demo_test, observation_only, leaves_state)`, `SCENARIOS` (S01-S20), `by_id`. `leaves_state` is True for S12, S15, S16, S18. S20 is `observation_only` with no module, twin or demo test.

`evidence_index.write_session_index(evidence_dir, evidence_files, *, session_id, clock, environ) -> Path` writes `25-DEMO-SESSION-INDEX-<stamp>[-n].json` and a sibling `.md`: rows sorted by scenario id with outcome, label counts, demo order ids, client order ids, algo client ids; a non-scenario or unreadable file is a REJECTED row with its name; create-only; scrubbed with `Redactor` and re-scanned after writing; LF only, sorted keys.

A twin module defines `REUSES` (a tuple of `path::test_name` strings, resolved by plan 25-17's gate); S01's names the three `tests/test_live_demo_smoke.py` tests it builds on.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s01_happy.py tests/test_demo_evidence_index.py tests/test_demo_harness.py tests/test_live_demo_smoke.py tests/test_demo_marker_guard.py tests/test_demo_same_code_path.py tests/test_no_unratified_defaults.py -q`: all passed (about 240 tests).
- Scoped `ruff check` and `ruff format --check` on every file of this plan: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock` exits 0. The catalog acceptance one-liner exits 0.
- No `pytest -m demo`, no `--execute`, no network call, no `.env` read.

## Deviations from Plan

None in behavior. Choices inside the plan's latitude, recorded above under key-decisions: the harness reads approvals itself instead of `make_open_demo_approvals_reader` (a fidelity gap of the in-memory shadow store, Rule 1 in the test support layer); `account_clean` is not called from S01 (the smoke has its own identical step); `clock_offset` is refused by the fake factory.

## Not covered by an agent-run test

- Nothing ran against Binance Demo. `ensure_clean_start` / `account_clean` on a real Demo account (real `snapshot_*` reads, the PostgreSQL shadow store through `executor.read`) and the `ScenarioRecorder` in EXECUTE mode with `DEMO_OBSERVED` labels first run in the owner's session through plan 25-09's fixtures.
- The Demo fixture contract (`scenario_recorder`, `make_demo_env`) is only pinned here (constants and docstring); it is implemented and tested by plan 25-09.
- `_latest_health` reads `wiring.health.latest_verdict` of the env the caller passed (the first process of the smoke, not the restarted one); it records facts only and no test asserts a healthy verdict.
- Fidelity gap, not fixed here (the fake is not part of this plan): the in-memory shadow store records no `APPROVAL_MODE_RECORDED` marker, so the live `make_open_demo_approvals_reader` never lists a PENDING approval in the twin. Any twin that relies on the live sender's symbol-block for a PENDING card is not tested by that reader.

## Known Stubs

None.

## Threat Flags

None. T-25-18 (sentinel scrub: recorder write reused, index writer scans too, tests), T-25-19 (label rule, per-step labels, recorder refusal, tests), T-25-20 (clean start refuses with the demo_clear instruction, tests) and T-25-SC (no package added; pyproject.toml and uv.lock unchanged) mitigations hold.

## Self-Check: PASSED

All eight created files exist; commits 1549e853, 9b90b68e, 1fb08b6f, a8888a76, a94899ca and 34e776c6 are ancestors of HEAD; `git rev-list --count 13a465d9..34e776c6` is 6.
