---
phase: 22-leverage-margin-liquidation-guard
plan: 02
subsystem: execution
tags: [execution-limits, margin, liquidation-buffer, bracket-age, headroom, fail-closed, NOT_CONFIGURED]
requires:
  - phase: 21
    provides: "execution-limits-v1.toml loader, the <section>_<key> field rule, the plan 21-02 file list as precedent"
provides:
  - "[margin] section and [provenance.margin] in config/execution/execution-limits-v1.toml: liquidation_buffer_bps, max_bracket_age_ms, headroom_bps, all NOT_CONFIGURED"
  - "EXECUTION_LIMIT_KEYS['margin'] (last section), three EXECUTION_LIMIT_FIELDS entries, ExecutionLimits.margin_liquidation_buffer_bps / margin_max_bracket_age_ms / margin_headroom_bps (required, not alert-only)"
  - "TEST_ONLY values 137, 4141, 233 in tests/support/execution_limits.py"
affects: [22-12, 22-13, 22-14, 22-15, 22-16]
tech-stack:
  added: []
  patterns: ["required execution limit: loaded, validated, provenance-labelled, named by require_live_ready while NOT_CONFIGURED"]
key-files:
  created: []
  modified:
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - src/execution/execution_limits.py
    - tests/support/execution_limits.py
    - tests/test_execution_limits.py
    - tests/test_no_unratified_defaults.py
    - tests/test_phase18_gate.py
key-decisions:
  - "The three margin keys are REQUIRED (not in ALERT_ONLY_LIMIT_KEYS) and positive-integer-only (basis points, milliseconds; amendment A4). While unset, require_live_ready names them and gate 2b of the manager refuses every placement before the margin guard can run."
  - "Fields follow the <section>_<key> rule; both spellings of each key are in GUARDED_NAMES, 54 -> 60."
  - "Recorded deviation (D-10, O-2): docs/trading/RISK_MANAGEMENT.md section 9 calls the buffer a registry parameter; this plan builds the CONTEXT default (an execution-limits key). The owner's DECISIONS row settles the home; plan 22-16 records the deviation and edits the doc wording. Not edited here."
status: complete
requirements-addressed: [RISK-02]
duration: ~30 min
completed: 2026-10-24
commits: 4
plan_head_before: 5674ae056fbdc428a3e70ee343ed410d69ac5bdc
plan_head_after: c4844738928bd15d89cbfb49229c5189c846d3fd
actuals:
  tokens: 4300
  tasks: 2
  commits: 2
---

# Phase 22 Plan 02: margin execution limits Summary

**The liquidation buffer (basis points of the entry price), the maximum bracket age (milliseconds) and the margin headroom (basis points of the margin needed) exist as three REQUIRED, positive-integer-only, `NOT_CONFIGURED` execution limits with provenance. They load into `ExecutionLimits`, are named by `require_live_ready()`, cannot get a numeric default under either spelling, and carry no number anywhere outside the TEST_ONLY test support.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 4f0a7cd5 | TOML `[margin]` + `[provenance.margin]`, loader keys/fields/dataclass fields/docstrings, TEST_ONLY 137/4141/233, README `### [margin]`, tests |
| 2 | c4844738 | `GUARDED_NAMES` pins 54 -> 60 in `test_no_unratified_defaults.py` and `test_phase18_gate.py`, both-spelling assertion, six seeded forbidden forms |

`commits: 4` in the frontmatter is the measured `rev-list` count from the ledger base; the tree is shared with the wave-1 sibling plans, so two of the four commits (`6e4c7562`, `2be93a72`, both 22-04) are not mine. `actuals.commits: 2` counts this plan's own commits. `actuals.tokens` is chars/4 over this plan's added and removed lines.

## What was built

- `config/execution/execution-limits-v1.toml` (LF in the working tree, kept): `[margin]` after `[account]`, `[provenance.margin]` after `[provenance.account]`, all six entries the word `NOT_CONFIGURED`.
- `src/execution/execution_limits.py`: `"margin": ("liquidation_buffer_bps", "max_bracket_age_ms", "headroom_bps")` as the last section (file order = dict order = `unset_keys` order), the three field mappings, three `int | None` dataclass fields with no default, module and class docstrings (meaning, unit and consumers of each key, OWNER-OPEN O-2 and O-3, nineteen keys, eighteen required, one alert-only). `ALERT_ONLY_LIMIT_KEYS` untouched.
- `tests/support/execution_limits.py`: `margin.liquidation_buffer_bps` 137 (on an entry of 80000: 1096), `margin.max_bracket_age_ms` 4141, `margin.headroom_bps` 233; FAKE, odd-looking, unique among the TEST_ONLY values.
- `config/execution/README.md`: `### [margin]` subsection (one key per line, parsed by the README test), counts reworded to nineteen / eighteen required / one alert-only. The wording sets and suggests no value.
- `tests/test_execution_limits.py`: `EXPECTED_UNSET` kept as the fourteen Phase 19/20 keys, new `MARGIN_KEYS`, `COMMITTED_UNSET` (14 + 3 = 17 unset in the committed file, equity age set) and `ALL_REQUIRED_KEYS` (14 + account + 3 = 18, file order); counts 14 -> 17, `NOT_CONFIGURED` word count 30 -> 36; the "account is the last section" test now says account precedes margin; new tests: margin section last with the three keys in order and prefixed fields, keys required not alert-only, committed file unset with `NOT_CONFIGURED` labels, `require_live_ready` names the three keys with no digit, a set section loads, missing section / missing provenance / unknown key refuse by name, the full refusal matrix (missing key, bool, float, zero, negative, wrong strings, missing label, PLACEHOLDER, `NOT_CONFIGURED` with int, `DECISION` with unset, unknown label) for each of the three keys without echoing the value, the TEST_ONLY values, and one-field-None overrides leave exactly that key unset.
- `tests/test_no_unratified_defaults.py` / `tests/test_phase18_gate.py`: `len(GUARDED_NAMES) == 60` (printed from the code first: 60 = 54 + 3 key texts + 3 field names; no new text collides with an older one), six names asserted present, six seeded numeric-default forms (key text assignment, field-name assignment, parameter default, keyword, upper-case constant) found by the scanner. No `ALLOW_LIST` entry, no scan weakened.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] README key lines moved into Task 1.**
- **Found during:** Task 1
- **Issue:** `test_the_readme_lists_exactly_the_execution_limit_keys` (Task 1's verify file) fails as soon as `EXECUTION_LIMIT_KEYS` has the new keys unless the README lists them.
- **Fix:** the `### [margin]` subsection and the count wording went into the Task 1 commit (same as plan 21-02).
- **Files modified:** config/execution/README.md
- **Commit:** 4f0a7cd5

**2. [Process incident] Task 1 commit 4f0a7cd5 contains two foreign files.**
- **What happened:** between my `git add` of the five Task 1 paths and `git commit`, a parallel executor staged `src/domain/exchange_errors.py` and `tests/test_exchange_errors.py` (115 lines each, not part of this plan). The plain `git commit` took the whole index, so those two files are in my commit `4f0a7cd5` (`git show --stat` lists seven files). I noticed after the commit.
- **Not repaired:** undoing it needs a history rewrite (`reset`/`amend`), which the sequential-execution rules forbid while siblings commit on the same branch. The content is not lost or changed; it is only attributed to the wrong commit message. The sibling that owns those files (likely 22-03) will find nothing left to commit for them and should be told. Task 2 used `git commit -- <paths>` (path-limited) and contains only its two files.
- **Plan-owned files in that commit are correct;** nothing of this plan is missing.

**3. [Plan reference] Other pinned tuples.** `grep -rn "unset_keys()" tests/` and `grep -rn "alerts.dedupe_window_ms" tests/` found pins only in `tests/test_execution_limits.py` (updated). `tests/test_phase20_gate.py` is a subset check of the seven Phase 20 keys (still true, not edited); `tests/test_phase19_gate.py` and `tests/test_phase21_gate.py` iterate dynamically and passed unchanged; `tests/test_execution_manager.py:3282` only asserts `unset_keys() != ()`.

## Verification (executed unit tests [DESIGN]; no [DEMO] claim; LIVE stays blocked)

- `uv run pytest -m "not docker" tests/test_execution_limits.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py` -> all passed (0 failures).
- `uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_reconcile_stale_entry.py tests/test_demo_rehearsal_flow.py tests/test_alerts.py` -> all passed (exit 0).
- `uv run mypy src/execution/execution_limits.py` -> no issues; `uv run ruff check` and `ruff format --check` on the files touched in `src/` and `tests/` -> clean.
- `git diff --exit-code -- config/binance params docs/DECISIONS.md pyproject.toml uv.lock` -> exit 0.
- No full-suite run, no network, no Demo script. `scripts/verify_decision_alignment.py` was not run (no docs/DECISIONS/AGENTS.md edit in this plan).
- Line endings checked per file with `git ls-files --eol` and kept (`.py`, `.md` CRLF in the working tree; the TOML LF), edits done bytes-aware.

## Known Stubs

None. The TEST_ONLY values live only in `tests/support/execution_limits.py` and no production file imports it (guarded by `test_no_production_file_imports_the_test_only_limits`).

## Threat Flags

None. T-22-05 is mitigated as planned (three keys `NOT_CONFIGURED` and required; both spellings guarded, 60 names; loader refuses 0, floats, booleans, PLACEHOLDER). T-22-06: while any required key is unset `require_live_ready` names these three, and gate 2b already refuses placement (plan 22-15 tests the ordering). T-22-SC: no dependency change.

## For the owner

- O-2 (the liquidation buffer) and O-3 (the bracket age and the headroom) stay open. All three keys are `NOT_CONFIGURED` with provenance `NOT_CONFIGURED`. Setting any of them needs a DECISIONS row and the label `DECISION`; the units are basis points (buffer: of the entry price; headroom: of the margin the order needs) and milliseconds (bracket age).
- Until you decide, the live and Demo path refuses and `require_live_ready` names the three keys.
- The home of the buffer (an execution-limits key instead of a hash-locked registry parameter, as `docs/trading/RISK_MANAGEMENT.md` section 9 words it) is the CONTEXT default; plan 22-16 records the deviation. Moving it into the registry later costs a new parameter set, a new `strategy_version` and regenerated research records.
- No requirement was marked complete (RISK-02 is only listed under `requirements-addressed`).

## Self-Check: PASSED

- config/execution/execution-limits-v1.toml, config/execution/README.md, src/execution/execution_limits.py, tests/support/execution_limits.py, tests/test_execution_limits.py, tests/test_no_unratified_defaults.py, tests/test_phase18_gate.py exist and are committed.
- Commits 4f0a7cd5 and c4844738 exist on `develop`.
