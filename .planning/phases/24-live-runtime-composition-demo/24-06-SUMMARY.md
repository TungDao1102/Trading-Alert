---
phase: 24-live-runtime-composition-demo
plan: 06
subsystem: execution-limits
tags: [execution-limits, owner-decisions, D089, relationship-test, phase-24]

requires:
  - phase: 24-live-runtime-composition-demo
    provides: 24-01 owner answers (limit table), 24-03 optional D083 key, 24-07 migration
provides:
  - "the owner's fourteen limit values in config/execution/execution-limits-v1.toml, provenance DECISION"
  - "tests/test_live_limits_relationships.py: the five P-9 relationship rules with negative controls"
  - "DECISIONS D089"
affects: [24-09, 24-22, 24-24, 24-29, 24-30]

actuals:
  tokens: 30000
  tasks: 3
  commits: 3
plan_head_before: 18b04991c750901f9ff1fcde643df585653bc267
plan_head_after: 639a91a751705f1f9e56ac86561b6fbcd839a50d  # last code/docs commit; the SUMMARY commit follows

key-files:
  created:
    - tests/test_live_limits_relationships.py
  modified:
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - docs/DECISIONS.md
    - tests/test_execution_limits.py
    - tests/test_phase20_gate.py
    - tests/test_phase22_gate.py
    - tests/test_reconcile_stale_entry.py

key-decisions:
  - "D089: the owner's limit values (2026-10-31); stale_feed.max_user_data_silence_ms not answered and left NOT_CONFIGURED; D083 clock margin left unset"

requirements-completed: []  # EXEC-01, EXEC-02, OPS-03 stay open: the live path still refuses until key 14 is answered

duration: 1 session
completed: 2026-10-31
status: complete
---

# Phase 24 Plan 06: Owner limit values, relationship test, D089 Summary

**Thirteen required execution-limit keys plus the alert-only stale-entry grace now carry the owner's numbers (provenance DECISION, row D089), five relationships between them are pinned by a test with negative controls, and the one unanswered key (`stale_feed.max_user_data_silence_ms`) stays NOT_CONFIGURED, so the live path still refuses, naming it.**

## Precondition note

The plan's precondition asks for a value for each of the fourteen required keys. The 24-01 SUMMARY records key 14 (`stale_feed.max_user_data_silence_ms`) as "NOT ANSWERED" and states that plan 24-06 "writes the other values and halts on key 14". The orchestrator's instruction repeated that. The plan was therefore executed for the thirteen answered required keys and the alert-only key; no number was written for key 14 and key 16 (the D083 margin) stays unset.

## Owner-value diff table (24-01-SUMMARY value versus shipped TOML line)

| Key | 24-01 owner value | Shipped TOML |
|-----|-------------------|--------------|
| `protection.max_unprotected_ms` | 180000 | 180000 |
| `protection.entry_terminal_timeout_ms` | 900000 | 900000 |
| `protection.entry_unknown_grace_ms` | 1800000 | 1800000 |
| `protection.emergency_close_poll_timeout_ms` | 30000 | 30000 |
| `pre_placement.min_remaining_validity_seconds` | 900 | 900 |
| `pre_placement.max_mark_price_age_ms` | 5000 | 5000 |
| `pre_placement.max_last_price_age_ms` | 5000 | 5000 |
| `reconcile.tick_interval_ms` | 15000 | 15000 |
| `reconcile.entry_unknown_probe_count` | 3 | 3 |
| `reconcile.entry_unknown_probe_interval_ms` | 5000 | 5000 |
| `reconcile.lot_filter_refresh_interval_ms` | 3600000 | 3600000 |
| `reconcile.entry_stale_grace_ms` (alert only) | 900000 | 900000 |
| `stale_feed.max_mark_price_age_ms` | 60000 | 60000 |
| `stale_feed.max_user_data_silence_ms` | NOT ANSWERED | `"NOT_CONFIGURED"` (provenance NOT_CONFIGURED) |
| `alerts.dedupe_window_ms` | 300000 | 300000 |
| D083 margin `rest_gate.ban_end_clock_margin_ms` | left NOT_CONFIGURED | `"NOT_CONFIGURED"` |

## Accomplishments

- TOML: fourteen values set, each provenance label `DECISION`; header comment names D089 and the two keys that stay unset. Account and margin keys untouched.
- README: a "Values set by DECISIONS D089" table (value in a separate cell so the existing "README carries no `key = value`" test still holds) and the reasons the two keys stay unset.
- `tests/test_live_limits_relationships.py`: `relationship_violations(limits, binance)` over the real loaders; five rules (tick < max_unprotected; max_unprotected > 120 s + 2 ticks; min_remaining_validity > 600 + confirm TTL 60 + GTD margin 1 s; stale-feed mark age > tick; probes x interval < entry_unknown_grace); parametrised negative controls on a `tmp_path` copy that assert the message names the keys; a test that an unset rule key is itself a violation; a pin that key 14 and the D083 margin carry no number.
- Existing pins updated: `COMMITTED_UNSET` is now `("stale_feed.max_user_data_silence_ms",)`; counts 14 -> 1; `NOT_CONFIGURED` word count 32 -> 4; phase 20 invariant 3, phase 22 invariant 5 and the stale-entry grace test follow. `ExecutionLimitsNotConfigured` is still asserted on the shipped file (one key) and on unset documents built in the tests.
- DECISIONS D089 appended (one row, 0 deleted lines, owner words verbatim with diacritics, "LIVE_ORDERS_DISABLED stays").

## Verification

- `uv run pytest -m "not docker"` over test_live_limits_relationships, test_execution_limits, test_execution_manager, test_phase19..22_gate, test_reconcile_stale_entry, test_no_unratified_defaults: all pass. Also test_decision_alignment_*, test_deploy_docs, test_binance_limits_ratified_file, test_phase18_gate, test_phase23_gate, test_agents_md: pass.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `uv run ruff check tests config`, `ruff format --check` on touched tests, `uv run mypy src`, `uv lock --check`: clean.
- `git diff 18b04991 HEAD -- config/binance params pyproject.toml uv.lock` is empty.
- `grep -c "^| D0" docs/DECISIONS.md`: baseline 88, now 89; `git diff --numstat` for the file: 1 added, 0 deleted.
- Not run (rules of this wave): the full suite and every `*_pg.py` / `TEST_DATABASE_URL` test. Gap: none of this plan's tests need PostgreSQL.

## Deviations from Plan

**1. [Rule 3 - precondition] Key 14 unanswered.** See "Precondition note"; sanctioned by the 24-01 SUMMARY and the orchestrator, no value invented.

**2. [Rule 1 - test shape] README bullets.** A first draft of the README section used `- \`key\` - ...` bullets, which the existing `test_the_readme_lists_exactly_the_execution_limit_keys` parser counted as duplicate key lines. Reworded to prose and committed in the second commit.

**3. Renames.** `test_the_real_file_loads_with_every_field_unset` -> `..._with_the_owner_numbers_and_one_required_key_unset`; phase 20 invariant 3 -> `..._is_decided_or_unset_and_guarded`; the stale-entry grace test -> `..._is_set_in_the_committed_file`. test_execution_manager.py and test_phase19_gate.py / test_phase21_gate.py needed no change (their assertions still hold with one unset key).

## Known Stubs

None. `stale_feed.max_user_data_silence_ms` is an intentionally unanswered owner key, not a stub; it is tracked as the open item below.

## Open item for the owner

`stale_feed.max_user_data_silence_ms` (required): no recommendation exists because the official user-data-streams page states no server ping interval. The live path refuses to start, naming this key, until the owner chooses a number, expected from the ping and pong times a Demo run observes. When set, update `COMMITTED_UNSET` in tests/test_execution_limits.py, the pin in tests/test_live_limits_relationships.py, the phase 20 gate constant and add a DECISIONS row.

## Threat Flags

None. T-24-15: values come from the recorded 24-01 table and the owner's words are quoted verbatim in D089. T-24-16: relationship test with negative controls. T-24-SC: pyproject.toml and uv.lock unchanged.

## Task Commits

1. Task 1 (tracer): `5fd4219d` feat - values, README table, relationship test
2. Task 2: `c6cf47dc` test - pins follow D089
3. Task 3: `639a91a7` docs - D089

STATE.md, ROADMAP.md and REQUIREMENTS.md were not touched (orchestrator-owned in this wave).

## Self-Check: PASSED

- FOUND: tests/test_live_limits_relationships.py, 24-06-SUMMARY.md
- FOUND commits 5fd4219d, c6cf47dc, 639a91a7 (ancestors of HEAD)
