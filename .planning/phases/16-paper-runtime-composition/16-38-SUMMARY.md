---
phase: 16-paper-runtime-composition
plan: 38
subsystem: SHADOW isolation proof (SC6, D-13 layers 1 to 3)
tags: [shadow, isolation, sc6, d-13, d040, ast, spies, negative-control, paper-02]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plans 16-22 (BINANCE_ refusal), 16-26/16-29/16-31 (composed runtime, ShadowCoordinator), 16-39 (test-only rehearsal and its entrypoint)"
provides:
  - "tests/test_paper_shadow_isolation.py (32 tests): layer 1 import closure and order-surface name scan, layer 2 BINANCE_ refusal of runtime and rehearsal, layer 3 behaviour spies over a full APPROVE then CONFIRM, each with a negative control"
affects: [16-40 (rehearsal run), 16-43 (soak start)]

requirements-completed: [PAPER-02]

status: complete
actuals:
  tokens: 6400
  tasks: 3
  commits: 3
plan_head_before: 3c47acfe0f686bff934dd893d34e0d609d3750ee
plan_head_after: ad43cd14e478ae7ee67071fb2151635f0c9b727f
commits: 3

tech-stack:
  added: []
  patterns:
    - "Pure ast import closure (no scanned module is imported): lazy imports followed, TYPE_CHECKING-only imports skipped, parent package __init__ included, unresolved names recorded so a banned import cannot hide behind a missing file"
    - "Class-level spies that record and raise, installed on the order adapter and on every module holding execute_approved_plan"
    - "Construction spies (adapters, bot application, database engine) that prove a refusal happens before anything is built"

key-files:
  created:
    - tests/test_paper_shadow_isolation.py
  modified: []

key-decisions:
  - "Layer 1 bans every src.execution module except an explicit allowlist of four dependency-free helpers (the package barrel, order_ids, placement, enablement) that the backtest and the journal type-check already share; the manager, fill_monitor, intent_recovery, intent_store and constraint_snapshot stay banned, as does src.adapters.binance_usdm"
  - "Layer 2 for the rehearsal entrypoint exercises the live mode, the only mode that runs the BINANCE_ refusal and the only one that could build a bot, a network feed or a database engine"
  - "A drift guard compares the spied method list with the public async methods of BinanceUsdmAdapter, so a new order method cannot escape the spies"

patterns-established:
  - "Negative controls beside every guard: seeded trees for the scan, a deliberate constructor call and a deliberate order call for the spies, the same environment minus the variable for the refusal"

coverage:
  - deliverable: "Layer 1: the transitive src import closure of src.paper.runtime, src.paper.shadow_runtime, src.paper.rehearsal and scripts/shadow_rehearsal.py has no order module and no order-surface name"
    verification:
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py::test_the_closure_of_every_shadow_entrypoint_has_no_order_module", status: pass}
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py::test_no_module_of_the_closure_names_an_order_surface_method", status: pass}
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py (negative controls: seeded import, seeded call, from-import of the adapter module, allowlist, TYPE_CHECKING)", status: pass}
    human_judgment: false
  - deliverable: "Layer 2: runtime and rehearsal refuse any BINANCE_ name (five names, empty and non-empty) with exit 3, print names only, and build no adapter, bot, engine"
    verification:
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py::test_a_binance_variable_refuses_with_code_3_and_builds_nothing (20 cases)", status: pass}
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py::test_the_refusal_lists_names_only_and_every_present_name", status: pass}
      - {kind: pytest, ref: "tests/test_paper_runtime_env.py", status: pass}
    human_judgment: false
  - deliverable: "Layer 3: a full SHADOW APPROVE then CONFIRM to a simulated position, in the runtime wiring and in the dry-run rehearsal, calls no spied order method and no execute_approved_plan; the spies are proven live"
    verification:
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py::test_a_full_shadow_approve_then_confirm_in_the_runtime_wiring_reaches_no_order_surface", status: pass}
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py::test_the_rehearsal_path_in_dry_run_reaches_no_order_surface", status: pass}
      - {kind: pytest, ref: "tests/test_paper_shadow_isolation.py::test_negative_control_a_deliberate_call_is_recorded_by_the_spies", status: pass}
    human_judgment: false

duration: ~35 min
completed: 2026-10-12
---

# Phase 16 Plan 38: SHADOW isolation proof Summary

**`tests/test_paper_shadow_isolation.py` proves SC6 in three independent, negative-controlled layers over the composed runtime and the REV-03 rehearsal: a pure AST import closure reaches no order module and names no order method, a `BINANCE_` variable refuses both entrypoints with exit 3 before anything is built, and a full APPROVE then CONFIRM calls no spied order method.**

## Performance

- **Duration:** about 35 min
- **Tasks:** 3 of 3 (Task 1 tracer, Tasks 2 and 3 auto, all `tdd="true"`)
- **Files:** 1 created, 0 modified; no `src` change was needed
- **Commits:** 3 measured (`plan_head_before..plan_head_after`)

## Accomplishments

- **Layer 1 (Task 1, tracer).** `_closure` walks `import` and `from ... import` statements (relative ones too) from the four entrypoints over `src`, `scripts` and `tests`, pure `ast`. `_violations` reports a banned module in the closure and any attribute, name, import alias, string constant or function definition equal to an order-surface name (the eleven adapter methods plus `execute_approved_plan`). The real-tree assertions also require `src.paper.loop` and `src.adapters.binance_public` in the closure, so a scan that stopped early cannot pass. Seeded temporary trees prove it reports a banned import, a seeded `place_entry` call, a `from src.adapters import binance_usdm`, that market data (`binance_public`) is not banned, and how `TYPE_CHECKING`, lazy and `else` imports are treated.
- **Layer 2 (Task 2).** Both entrypoints are run with five names (`BINANCE_LIVE_API_KEY`, `..._SECRET`, `BINANCE_TESTNET_API_KEY`, `..._SECRET`, `BINANCE_FOO`) each with an empty and a non-empty value, plus all five at once. Construction spies on `PaperWsAdapter`, `BinancePublicMarketData`, `BinanceUsdmAdapter`, `build_application`, the Telegram `ApplicationBuilder.build`, `make_sync_engine` and both `create_engine` bindings record and fail on any construction. Result: exit 3, the name on stderr, the seeded value in no stdout, stderr or log capture, nothing built, no evidence file. Negative controls: the spies fire on a deliberate constructor call, and the same runtime environment without the variable is not refused.
- **Layer 3 (Task 3).** Class-level spies on all eleven order methods of `BinanceUsdmAdapter` and on every loaded reference to `execute_approved_plan`. The runtime wiring (`ShadowCoordinator` through the Rig of plan 16-31: alert, APR, confirmation card, CNF, poll to a filled simulated position) and `run_dry_rehearsal` both complete (the tests assert the journal confirm, the opened position and the rehearsal evidence, so the zero-call result is not vacuous) with zero spy calls. Negative controls: a deliberate call of every spied method is recorded, and a drift guard requires the spied list to equal the adapter's public async methods minus the seven market-data ones.

## Task Commits

| Task | Commit | What |
| --- | --- | --- |
| 1 (tracer) | f465f6e | test(16-38): SHADOW isolation layer 1, import closure and order-surface scan with negative controls |
| 2 | 48b8f75 | test(16-38): SHADOW isolation layer 2, BINANCE_ refusal of the runtime and the rehearsal builds nothing |
| 3 | ad43cd1 | test(16-38): SHADOW isolation layer 3, behaviour spies over a full APPROVE then CONFIRM |

No `feat(16-38)` commit exists: the plan lists only the test file and no `src` change was required.

## RED evidence

The first run of the Task 1 tests on the real tree failed (both closure tests), which is the RED state the plan anticipated. The cause was the scan, not the isolation: the transitive closure legitimately reaches `src.execution` through dependency-free shared helpers and through type-check-only imports (see Deviations 1 and 2). The negative controls were written against seeded trees and fail the scan as designed.

## Verification (plan level, re-run at SUMMARY time)

- `.venv/Scripts/python -m pytest tests/test_paper_shadow_isolation.py tests/test_paper_runtime_env.py -q -p no:cacheprovider -rs`: 47 passed, 0 skipped, 0 xfail (the isolation file alone: 36 tests passing incl. 20 refusal cases).
- `uv run ruff check`: pass. `uv run ruff format --check`: 523 files already formatted. `uv run mypy src`: no issues in 182 source files. `mypy tests/test_paper_shadow_isolation.py` reports no error in the new file (errors listed in other test files it imports are pre-existing and out of scope; CI checks `src` only).
- The whole test suite was NOT run (memory limit on this machine, as instructed).

## Deviations from Plan

**1. [Rule 1 - Bug in the plan's assumption] `src.execution` is not wholly absent from the closure**
- **Found during:** Task 1 (RED run)
- **Issue:** the plan truth "reaches no module under `src.execution`" is false for four modules that are pure and shared on purpose: `src.execution` (barrel that re-exports `order_ids` only), `order_ids`, `placement` (limit and protective sizing arithmetic that `src/backtest/entry.py` and `exits.py` call "never re-derived", reached through `src.backtest.costs` from the rehearsal) and `enablement` (value types reached from the journal). None imports an adapter or the manager.
- **Fix:** the ban is "every `src.execution` module except an explicit four-name allowlist, plus `src.adapters.binance_usdm`". The scan still reads the source of the allowlisted modules, so a helper that grew an order import would pull the manager into the closure and fail; a negative-control test pins the allowlist and the banned names (`manager`, `fill_monitor`, `intent_recovery`, `intent_store`, `constraint_snapshot`, a prefix lookalike). Changing the backtest to avoid the shared helpers would be an architectural change and was not made.
- **Files:** `tests/test_paper_shadow_isolation.py`. **Commit:** f465f6e.

**2. [Rule 1 - Bug in the scan] `TYPE_CHECKING` imports are not followed**
- **Found during:** Task 1 (RED run)
- **Issue:** `src/persistence/journal.py` imports `src.reconcile.sweeper` and `safe_mode` (which declare order-port Protocols with the order method names) only inside an `if TYPE_CHECKING:` block. They never execute, so they are not part of any real import closure.
- **Fix:** the closure skips the body of `if TYPE_CHECKING:` (the `else` branch and function-local lazy imports are still followed); a seeded test pins all three cases.
- **Commit:** f465f6e.

**3. [Plan reading] Layer 2 of the rehearsal entrypoint covers the live mode**
- **Found during:** Task 2
- **Issue:** `scripts/shadow_rehearsal.py` runs the `BINANCE_` refusal (exit 3) only in `--live-telegram` mode; `--dry-run` does not run it (plan 16-39, by design: fakes only). The plan says both entrypoints "refuse".
- **Fix:** the refusal test drives `--live-telegram --i-am-the-operator` (the only mode that could build a bot, a network feed or a database engine), and a separate test shows the dry run exits 0 and constructs none of the real classes. The source was not changed (the plan lists only the test file). If the user wants the dry run to refuse a `BINANCE_` variable too, that is a one-line move of the check in `main()` and an extra test, as a follow-up.
- **Commit:** 48b8f75.

**Total deviations:** 3 (2 auto-fixed in the test design, 1 reading of the plan). **Impact:** SC6 is still proven in all three layers; layer 1 is slightly narrower than the plan wording (an explicit, test-pinned allowlist of four pure modules).

## Authentication Gates

None. No network, no credential, no `.env` read; every secret in the tests is a fake sentinel.

## Known Stubs

None.

## Threat Flags

None. The plan adds a test file only.

## Self-Check: PASSED

- Created files exist: `tests/test_paper_shadow_isolation.py`, `.planning/phases/16-paper-runtime-composition/16-38-SUMMARY.md`.
- Commits exist: f465f6e, 48b8f75, ad43cd1.
- `<verify>` command of Task 3 re-run green with no skipped or xfail test. STATE.md and ROADMAP.md were not touched.
