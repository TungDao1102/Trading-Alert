---
phase: 24-live-runtime-composition-demo
plan: 11
subsystem: live-runtime
tags: [live-runtime, admission, cli, probes, ops-04, redaction, phase-24]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: "24-01 owner answers (Q5, Q6), 24-04 src/live package and AST guards"
provides:
  - "src/live/config.py: LiveExitCode, LiveRefusal, LiveConfig, parse_live_environment, the live liveness stamp"
  - "src/live/runtime.py: build_parser, main (probes, admission, hold-on-refusal, run_live seam), diagnostic_payload"
  - "src/adapters/code_version.py: read_build_revision(environ) and BuildRevisionError"
affects: [24-22, 24-25, 24-26, 24-27, 24-30]

tech-stack:
  added: []
  patterns:
    - "admission refuses by variable or limit-key name, mode in every message"
    - "probes read two small files plus the limits file and open no client"

key-files:
  created:
    - src/live/config.py
    - src/live/runtime.py
    - tests/test_live_config_refusal.py
    - tests/test_live_runtime_cli.py
  modified:
    - src/adapters/code_version.py
    - tests/test_code_version.py

key-decisions:
  - "Telegram variable names of the live process (Q6): TELEGRAM_LIVE_BOT_TOKEN, TELEGRAM_LIVE_AUTHORIZED_CHAT_ID, shared TELEGRAM_AUTHORIZED_USER_IDS; TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN_FILE (the SHADOW bot) refuse the start"
  - "The live process keeps its own copy of the user-id list parser: the paper module that holds the original has 'src.paper.runtime' as a prefix of its name and the plan's acceptance grep forbids that string under src/live"
  - "LIVE_ORDERS_DISABLED is read from the default state of LiveEnablementController, with a live_orders_disabled seam for tests"

requirements-completed: []  # OPS-02 and OPS-04 stay Pending until the runner (24-27) and image stamp (24-25) exist; the orchestrator owns requirement state

duration: 1 session
completed: 2026-10-31
status: complete
actuals:
  tokens: 31000
  tasks: 3
  commits: 3
plan_head_before: 18b04991
plan_head_after: 3537be96
---

# Phase 24 Plan 11: Live config, CLI and OPS-04 version output Summary

**The live process now has its admission edge: an explicit DEMO or LIVE mode, refusals by name for the other mode's credentials, the SHADOW bot variable and unset execution limits, a hold-on-refusal CLI, and probe verbs that report the Python version and a build-stamped revision without git or any client.**

## Accomplishments

- `parse_live_environment` refuses in the order mode, credentials, Telegram, limits. `LIVE_RUNTIME_MODE` must be exactly `DEMO` or `LIVE` (missing, `TESTNET`, `"demo "` and every other value are MODE_REFUSED, the value is never echoed). `LIVE` is MODE_REFUSED while live placement is disabled (`LIVE_ORDERS_DISABLED`, the default of `LiveEnablementController`). Credentials load through `load_api_credentials(..., refuse_if_present=(other_spec,))`, so any `BINANCE_<other>_*` name or `_FILE` form refuses the whole start. Loaded secrets (API key and secret, the bot token) are registered with the redactor.
- `main` holds a refusal under `--hold-on-refusal` with `src/paper/held_marker.py` (marker written before the wait, removed in `finally`, code returned only after the stop; a marker that cannot be written exits with the code instead of holding). Without the flag the refusal exits at once. An admitted start with no runner refuses STARTUP_FAILED "runner not composed" (fail closed); a runner that raises returns STARTUP_FAILED naming the exception class only.
- `--liveness` (exit 0 only with no held marker and a stamp younger than `stale_feed.max_mark_price_age_ms`) and `--healthcheck` (one JSON object, same exit rule). Held marker, missing, corrupt, wrong-schema, future-dated, stale stamps and an unset or unloadable bound all fail. Tests replace `socket.socket`, `socket.create_connection` and `sqlalchemy.create_engine` with functions that fail the test.
- OPS-04: `read_build_revision(environ)` validates `TRADING_APP_REVISION` (exactly 40 lowercase hex, no subprocess). `diagnostic_payload()` and `--healthcheck` carry `python_version = sys.version` and `app_revision`: the stamp, else `read_code_version` on a dev checkout, else `unknown`; a malformed stamp gives `unknown` plus `app_revision_problem` naming the variable only.

## Final exit-code table (`LiveExitCode`)

| Code | Name | Meaning |
|------|------|---------|
| 0 | OK | normal end |
| 2 | USAGE | bad command line (argparse errors also exit 2; `--liveness` with `--healthcheck`) |
| 3 | CREDENTIAL_REFUSED | other mode's Binance names present, own names missing or blank, SHADOW bot variable present, live Telegram variable missing or malformed |
| 4 | LIMITS_NOT_CONFIGURED | limits file missing or invalid, or a required key is NOT_CONFIGURED (keys named, no values) |
| 5 | MODE_REFUSED | `LIVE_RUNTIME_MODE` missing or not exactly DEMO or LIVE; LIVE while `LIVE_ORDERS_DISABLED` |
| 7 | STARTUP_FAILED | runner not composed, or the runner raised |

Codes 1 and 6 are unused on purpose: 1 is the probe failure status, and 6 and 8 belong to the paper runtime's epoch and lease refusals.

## Telegram variable names (24-01 Q6)

| Variable | Role |
|----------|------|
| `TELEGRAM_LIVE_BOT_TOKEN` | bot token of the live process (second bot), registered with the redactor |
| `TELEGRAM_LIVE_AUTHORIZED_CHAT_ID` | private owner chat id, positive integer |
| `TELEGRAM_AUTHORIZED_USER_IDS` | shared with SHADOW, comma-separated positive integers |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_TOKEN_FILE` | SHADOW bot names: presence refuses the start |

These names were not fixed by the owner answer ("live-only variable names"); plans 24-17 and 24-30 should use them. State paths: `--state-dir` (default `logs/live`) holds the held marker, `live-liveness-<container>.json`, `rest_gate_state.json` and `spill/`.

## Task Commits

1. Task 1 (tracer): `aeb61e79` feat - admission, refusals, hold-on-refusal, config and runtime modules
2. Task 2: `48aab65e` feat - probes and the live liveness stamp, CLI tests
3. Task 3: `3537be96` feat - `read_build_revision` and its tests

Task 1's commit already carries the probe and diagnostic code in `runtime.py` (written in one pass); Tasks 2 and 3 added their tests and the adapter helper.

## Deviations from Plan

**1. [Rule 3 - Blocking] User-id parser is a local copy.** The plan's acceptance grep `git grep -n "src.paper.runtime" -- src/live` matches `src.paper.runtime_config`, the module that owns `parse_authorized_user_ids`. `config.py` therefore has `parse_user_ids` with the same rule (comma-separated positive ASCII integers, no blanks or duplicates, error names the variable only). If the rule in the paper module changes, this copy must follow.

**2. [Seams added] `main` has `repo_root` and `limits_path` keyword seams and a `--state-dir` option** beyond the planned signature, so tests inject a TEST_ONLY limits file and a temporary state directory. Production passes none of them.

**3. [Design] Chat id must be a positive integer** (a private chat); a group id (negative) is refused, consistent with the private-chat gate.

No auth gates. Out-of-scope discoveries: none.

## Gaps and notes for the orchestrator

- The shipped `config/execution/execution-limits-v1.toml` still holds NOT_CONFIGURED values (plan 24-06 fills them; `stale_feed.max_user_data_silence_ms` is still owner-open, 24-01 key 14), so a real DEMO start is refused LIMITS_NOT_CONFIGURED. One test checks that and skips itself once the owner has filled the file.
- No PostgreSQL tests were run or needed. Full suite not run (parallel-worktree rule). Gates run: the four plan test files, `tests/test_no_unratified_defaults.py`, `test_paper_shadow_isolation.py`, `test_domain_no_float.py`, `test_agents_md.py`, `test_phase18_gate.py`; scoped ruff, ruff format, `mypy src/live src/adapters/code_version.py`, `uv lock --check` all clean; `pyproject.toml` and `uv.lock` unchanged.
- Plan 24-25 must stamp `TRADING_APP_REVISION` in the Dockerfile; plan 24-27 must call `write_live_liveness` from the scheduler's liveness task and supply `run_live`; plan 24-22 consumes `diagnostic_payload()`.
- `src/live/runtime.py` is on the wall-clock edge allow-list (`_utc_now`); `config.py` reads no clock.

## Known Stubs

None in the data sense. The deliberate fail-closed placeholder is `run_live=None` -> STARTUP_FAILED "runner not composed", resolved by plan 24-27.

## Threat Flags

None. T-24-27 to T-24-30 are mitigated and tested (other-mode and SHADOW refusals, LIVE refused while disabled, seeded-secret absence in stderr/stdout/repr, hold with marker). T-24-SC: `git diff --exit-code -- pyproject.toml uv.lock` exits 0.

## Self-Check: PASSED

- FOUND: src/live/config.py, src/live/runtime.py, tests/test_live_config_refusal.py, tests/test_live_runtime_cli.py, src/adapters/code_version.py
- FOUND commits aeb61e79, 48aab65e, 3537be96 (ancestors of HEAD)
