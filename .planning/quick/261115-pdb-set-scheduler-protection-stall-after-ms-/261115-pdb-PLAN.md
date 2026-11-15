---
phase: quick-261115-pdb
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  # Task 1 (one commit: config, tests, comment-only src). Line endings measured 2026-11-15 with Python (CRLF/LF):
  - config/execution/execution-limits-v1.toml        # LF 0/123
  - config/execution/README.md                       # CRLF 157/157
  - src/execution/execution_limits.py                # CRLF 506/506, docstring and comment words only; the limit value is never written in src
  - tests/support/execution_limits.py                # CRLF 128/128, comment only, the TEST_ONLY value stays None
  - tests/test_execution_limits.py                   # LF 0/1315
  - tests/test_live_limits_relationships.py          # CRLF 234/234
  - tests/test_live_wiring.py                        # CRLF 718/718
  # Task 2 (one commit, docs, CRLF)
  - docs/DECISIONS.md                                # CRLF 117/117
  - docs/DOC_STATUS.md                               # CRLF 97/97
  - docs/GLOSSARY.md                                 # CRLF 652/652
  - docs/operations/RUNBOOK.md                       # CRLF 1267/1267
  - AGENTS.md                                        # CRLF 219/219, cap 230 lines; only if its gates stay green
  # Task 3 (no commit; the orchestrator commits it)
  - .planning/quick/261115-pdb-set-scheduler-protection-stall-after-ms-/261115-pdb-SUMMARY.md
autonomous: true
# Quick task: no REQUIREMENTS.md id is closed. The ids name the owner-approved deliverables.
requirements: [pdb-1-stall-bound-60000, pdb-2-decision-and-docs, pdb-3-runbook-22-6-to-22-8]

estimate:
  tokens: 40000
  raw_tokens: 40000
  tasks: 3
  confidence: low   # estimate-calibration is not available in this gsd-sdk (Unknown command); factor 1, sample_count 0

must_haves:
  truths:
    - "The shipped config/execution/execution-limits-v1.toml has protection_stall_after_ms = 60000 under [scheduler] and protection_stall_after_ms = \"DECISION\" under [provenance.scheduler]; load_execution_limits gives scheduler_protection_stall_after_ms == 60000, scheduler_protection_stall_after == timedelta(seconds=60), unset_alert_only_keys() == (), unset_keys() == (), and require_live_ready() still passes (the key stays ALERT ONLY: it is still in ALERT_ONLY_LIMIT_KEYS and is never named by require_live_ready)"
    - "End to end: the shipped file -> load_execution_limits -> LiveCadences.from_limits gives protection_stall_after == timedelta(seconds=60) and protection_stall_after_seconds == 60 (the existing total_seconds() property; no float() anywhere in src/live) -> the LiveWiring protection TaskSpec gets stall_after_seconds == 60 and every other task keeps None"
    - "scheduler.duration_summary_interval_ms is untouched: still NOT_CONFIGURED as value and provenance in the shipped file, unset_optional_refinement_keys() of the shipped file is still (rest_gate.ban_end_clock_margin_ms, scheduler.duration_summary_interval_ms)"
    - "The TEST_ONLY value of scheduler.protection_stall_after_ms in tests/support/execution_limits.py stays None, so every wiring test keeps the watchdog off unless the test sets a bound"
    - "No src behavior changes: git diff of the Task 1 commit touches no file under src/live, and src/execution/execution_limits.py changes only docstring and comment words (the limit value itself never appears in src: the module docstring says no number lives in it; tests/test_no_unratified_defaults.py forbids a numeric constant for the key names in src and scripts; a DECISIONS id and a date are allowed)"
    - "A sixth relationship holds and is tested on a tmp copy: a set scheduler.protection_stall_after_ms is strictly below protection.max_unprotected_ms (180000); an unset stall key is not a violation (alert only)"
    - "DECISIONS D114 (next free id after D113, verified) records the value 60000 as an OWNER ANSWER of 2026-11-15 with the honest basis: the owner-run Demo smoke 09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T104211Z.json (COMPLETE, 21 of 21) gave a longest protection_step run of 886 ms over about a dozen LIVE_TASK_DURATION runs with no rate limit or ban; the longest legitimate path is a cancel with the adapter's bounded STATUS_UNKNOWN retry (3 attempts, 30 s delay ceiling, src/adapters/binance_usdm.py:160-163) plus the 1.5 s stop reread of D113; the bound stays far below protection.max_unprotected_ms = 180000; 60000 is an INFERENCE from those facts, not a measured maximum, and may be tuned after more Demo runs"
    - "RUNBOOK 22.6 has one honest paragraph on the 2026-11-15 smokes (first run stopped at TP_UNAVAILABLE, D113 added, second run COMPLETE 21 of 21, cause of the first failure not proven, fix not proven to be why the second passed) and the manual-close procedure learned that day; 22.7 and 22.8 say the bound is 60000 ms since D114, the watchdog is on and TASK_STALLED can fire, with the measured figures, and 22.8 keeps the measuring procedure"
    - "All named gates pass; Task 1 and Task 2 are one commit each (unless a gate forces them together, recorded as a deviation) with the trailer Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; owner-modified .planning files and every untracked file (every evidence json) untouched; every touched file keeps its own line endings, measured with Python before and after"
  artifacts:
    - path: config/execution/execution-limits-v1.toml
      provides: "the D114 value and its DECISION provenance"
      contains: "protection_stall_after_ms = 60000"
    - path: tests/test_execution_limits.py
      provides: "pins moved from NOT_CONFIGURED to the D114 value; quoted NOT_CONFIGURED count 6 -> 4"
      contains: "STALL_DECIDED_MS"
    - path: tests/test_live_limits_relationships.py
      provides: "rule 6 (stall bound below max_unprotected_ms), its negative control, and the shipped-file -> LiveCadences 60 s test"
      contains: "scheduler.protection_stall_after_ms must be strictly below protection.max_unprotected_ms"
    - path: tests/test_live_wiring.py
      provides: "the shipped bound reaches only the protection TaskSpec as 60 s"
    - path: docs/DECISIONS.md
      provides: "row D114"
      contains: "| D114 |"
  key_links:
    - from: config/execution/execution-limits-v1.toml [scheduler] protection_stall_after_ms
      to: src/execution/execution_limits.py ExecutionLimits.scheduler_protection_stall_after (property, :290)
      via: "load_execution_limits; the DECISION label is required for an integer (PLACEHOLDER and NOT_CONFIGURED labels refuse)"
    - from: src/live/scheduler.py LiveCadences.from_limits (:464)
      to: src/live/wiring.py LiveWiring._specs protection TaskSpec (:1125-1131, stall_after_seconds=cadences.protection_stall_after_seconds)
      via: "protection_stall_after_seconds = bound.total_seconds() (:407-410), no float()"
    - from: src/live/scheduler.py _watch_stall
      to: src/live/wiring_parts.py alert_task_stall -> TASK_STALLED (HIGH)
      via: "LiveWiring._record_task journals the LIVE_TASK_EVENT stall row first, then alerts (D111); unchanged by this plan"
---

<objective>
Owner answer of 2026-11-15: set `scheduler.protection_stall_after_ms = 60000` with provenance DECISION in `config/execution/execution-limits-v1.toml` (today NOT_CONFIGURED), so the observe-only stall watchdog of the protection task and the `TASK_STALLED` alert are ON. Move every test pin that assumes the key is unset, add the end-to-end proof (shipped file -> loader -> LiveCadences -> protection TaskSpec = 60 s), record DECISIONS D114 with an honest basis, and update DOC_STATUS, GLOSSARY, RUNBOOK 22.6/22.7/22.8, the config README and (if its gates allow) AGENTS.md.

Purpose: the watchdog built by quick tasks 261114-kxu, 261114-mp1 and 261115-kra was dormant; the owner now has a first Demo duration sample and an argument for a bound. No code path changes: the loader, the cadence and the wiring already carry a set value (mp1, D111).

Output: one config/test commit, one docs commit, a SUMMARY (not committed).
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/STATE.md (read only; owner-modified, never stage it)
@.planning/quick/261114-mp1-follow-ups-to-kxu-cancel-resting-entry-o/261114-mp1-SUMMARY.md (how the key was added; "Measuring a value" section)
@.planning/quick/261115-kra-per-run-duration-record-for-live-schedul/261115-kra-SUMMARY.md (pins that moved last time; LF files; README stale sentences)
@.planning/quick/261115-nnt-bounded-stop-reread-in-attach-protective/261115-nnt-SUMMARY.md (D113; the first 2026-11-15 smoke)

Facts measured by the planner at HEAD f8634c2a (re-check, do not trust blindly):
- Shipped toml: line 81 `protection_stall_after_ms = "NOT_CONFIGURED"` under [scheduler], line 122 the same under [provenance.scheduler]; header comment lines 22 and 24-38 describe the key as unset. `grep -c '"NOT_CONFIGURED"'` on the file = 6 (rest_gate margin x2, stall x2, summary window x2); comment lines use the bare word without quotes.
- The code needs no change: `ALERT_ONLY_LIMIT_KEYS` (src/execution/execution_limits.py:130-132), property `scheduler_protection_stall_after` (:290), `LiveCadences.protection_stall_after_seconds` uses `total_seconds()` (src/live/scheduler.py:407-410), `from_limits` passes it (:464), `LiveWiring._specs` gives it to the protection TaskSpec only (src/live/wiring.py:1130). `grep -c "float(" src/live/scheduler.py src/live/wiring.py` = 0 and 0.
- No start-sequence or health rule depends on the key being unset (grep of src/live for the key: only scheduler.py and wiring.py). The live path's readiness uses `unset_keys()` only; the stall key is alert-only and never there.
- Conditional comments that stay TRUE and are NOT edited: src/live/scheduler.py:385-391, src/ops/alerts.py:126-128 and the TASK_STALLED `OPS05_MATRIX` row (:1013-1018; tests/test_alerts_ops05_matrix.py:205 REQUIRES the word NOT_CONFIGURED in it), docs/operations/SECURITY_AND_OPERATIONS.md:86, tests/fixtures/phase23/DERIVATIONS.md:83, the history rows D111/D112 and DOC_STATUS line 93. Never edit an old DECISIONS row.
- Pins that do NOT move (checked): `len(GUARDED_NAMES) == 68` in tests/test_no_unratified_defaults.py:227 and tests/test_phase18_gate.py:534 (no key added); `tests/test_phase20_gate.py` invariant 3 covers the Phase 20 keys only and invariant 6 accepts a consecutive tail after D107 (so D114 is fine); test_phase19_gate invariant 4 accepts a set value with label DECISION; test_phase21/22 gates only need some NOT_CONFIGURED word in the file (rest_gate and summary keep it); tests/test_live_scheduler.py stall tests use the TEST_ONLY None and stay as they are.
- Adapter cancel retry ceilings: src/adapters/binance_usdm.py:160-163 (`_RECONCILER_CANCEL_MAX_ATTEMPTS` 3, `_RECONCILER_CANCEL_MAX_DELAY_SECONDS` 30, wait multiplier 1, wait max 10). D113 reread: 3 x 0.5 s = 1.5 s.
- D113 is the last DECISIONS row (docs/DECISIONS.md:117); `grep -c '^| D114 |' docs/DECISIONS.md` = 0.
- Untracked owner evidence for 2026-11-15 exists under .planning/phases/24-live-runtime-composition-demo/evidence/ (083259Z FAILED run named by D113; 104211Z the COMPLETE run). Do NOT open, stage, move or edit any evidence file; cite only the two names the owner gave.
- `uv run pytest` already has `addopts = "-q"` (pyproject.toml:51): do not add another `-q`, or the summary line disappears.

Line-ending rule: the toml and tests/test_execution_limits.py are LF; every other touched file is CRLF in the working tree. Edit the LF files with the Edit tool; edit every CRLF file with a throwaway bytes-aware Python helper in the scratchpad (read bytes, replace one exact old block with the new block using CRLF, assert the old block occurs exactly once, write bytes). Measure CRLF and LF counts with Python before and after every file; CRLF must equal LF (or CRLF 0 for an LF file).
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Shipped stall bound 60000 end to end (toml -> loader -> LiveCadences -> protection TaskSpec), every pin moved, RED first</name>
  <files>config/execution/execution-limits-v1.toml, config/execution/README.md, src/execution/execution_limits.py, tests/support/execution_limits.py, tests/test_execution_limits.py, tests/test_live_limits_relationships.py, tests/test_live_wiring.py</files>
  <behavior>
    - The shipped file yields scheduler_protection_stall_after_ms == 60000 and scheduler_protection_stall_after == timedelta(seconds=60), provenance DECISION, unset_alert_only_keys() == (), unset_keys() == (), require_live_ready() passes.
    - LiveCadences.from_limits(shipped execution limits, shipped Binance limits) gives protection_stall_after == timedelta(seconds=60) and protection_stall_after_seconds == 60; duration_summary_interval stays None.
    - With the shipped bound, the LiveWiring protection_step TaskSpec has stall_after_seconds == 60 and every other TaskSpec has None.
    - Rule 6: a tmp copy with protection_stall_after_ms = 180000 (equal to protection.max_unprotected_ms) is a relationship violation naming both keys; the shipped file has no violation; an unset stall key is not a violation.
    - Quoted NOT_CONFIGURED strings in the shipped file: 4 (rest_gate margin and summary window, value and label each); the numeric-key list of the file ends with protection_stall_after_ms after headroom_bps.
    - Still true: TEST_ONLY stall value None; duration_summary_interval_ms NOT_CONFIGURED in the shipped file; the stall key alert-only and never named by require_live_ready.
  </behavior>
  <action>
Step 0 (record, no edit). Run `codegraph explore "LiveCadences.from_limits protection_stall_after_seconds scheduler_protection_stall_after"` first (`.codegraph/` exists). Measure CRLF/LF of the seven files with Python and record them. Baseline at HEAD: run the Task 1 verify set below and record the summary line.

Step 1 (tests first, RED). Change only tests:
(a) tests/test_execution_limits.py (LF, Edit tool). Next to STALL_KEY/STALL_FIELD (:103-104) add `STALL_DECIDED_MS = 60000` with a comment: owner answer 2026-11-15, DECISIONS D114, provenance DECISION, alert only. Then move these pins, each with a one-line history comment naming quick 261115-pdb / D114:
  - :499-525 `test_the_committed_file_names_only_not_configured_except_the_owner_numbers`: append "protection_stall_after_ms" as the last entry of the expected numeric list (after "headroom_bps"; [scheduler] is the last section) and change the quoted NOT_CONFIGURED count from 6 to 4 (extend the arithmetic comment: D114 sets the stall bound, a value and a label: 6 - 2 = 4).
  - :688-715 `test_the_real_file_has_every_section_and_label_unset_except_the_decided_keys`: add a branch before the final NOT_CONFIGURED asserts: when the dotted key is STALL_KEY, assert the value == STALL_DECIDED_MS and the label == "DECISION", then continue.
  - :812-813 and :930: `unset_alert_only_keys()` of the shipped file is now `()` (D089 set the grace, D114 the stall bound); fix the two comments.
  - :1126-1128 section comment: the key is set by D114 in the shipped file; unset it still leaves the watchdog off.
  - :1146-1160: rename to `test_the_committed_file_sets_the_stall_key_to_the_d114_value_with_the_decision_label` and assert: document value == STALL_DECIDED_MS, provenance "DECISION", limits ms == STALL_DECIDED_MS, `scheduler_protection_stall_after == timedelta(milliseconds=STALL_DECIDED_MS) == timedelta(seconds=60)`, `unset_alert_only_keys() == ()`, STALL_KEY not in unset_keys() and not in unset_optional_refinement_keys(), STALL_KEY still in el.ALERT_ONLY_LIMIT_KEYS, `require_live_ready()` passes, and the bound is strictly below `timedelta(milliseconds=limits.max_unprotected_ms)`.
  - Leave :1048-1060, :1241-1255 (ban margin and summary window still unset), :456 (all-unset kwargs), :255 (`_document()` from TEST_ONLY values) and :1175-1182 (TEST_ONLY None) unchanged: they must keep passing.
(b) tests/test_live_limits_relationships.py (CRLF, helper). Module docstring: "one of five rules" becomes six; add item 6: a set `scheduler.protection_stall_after_ms` is strictly below `protection.max_unprotected_ms` (D114; an unset stall key is allowed, it is alert only, D111). In `relationship_violations`, after the existing checks, read `limits.scheduler_protection_stall_after_ms`; when it is not None and >= the unprotected value, append the message "scheduler.protection_stall_after_ms must be strictly below protection.max_unprotected_ms" (you may add a clause that otherwise TASK_STALLED cannot fire before the unprotected deadline). Do NOT add the stall key to `_RELATIONSHIP_FIELDS` (that would make unset a violation). Add a negative-control parametrize entry: section "scheduler", key "protection_stall_after_ms", value 180000 (comment: equal to protection.max_unprotected_ms), expected keys ("scheduler.protection_stall_after_ms", "protection.max_unprotected_ms"); the control's line edit only matches inside `[scheduler]`, not `[provenance.scheduler]`. Add `test_the_shipped_stall_bound_is_d114_and_feeds_a_sixty_second_watchdog(binance)`: tomllib document value 60000 and label "DECISION"; `load_execution_limits` gives timedelta(seconds=60); `LiveCadences.from_limits(limits, binance)` (import from src.live.scheduler) gives `protection_stall_after == timedelta(seconds=60)` and `protection_stall_after_seconds == 60` (compare with the int 60, never call float()); `limits.scheduler_duration_summary_interval_ms is None` and `cadences.duration_summary_interval is None`.
(c) tests/test_live_wiring.py (CRLF, helper). Next to `test_a_set_stall_bound_reaches_only_the_protection_task` (:586-597) add `test_the_shipped_stall_bound_reaches_only_the_protection_task_as_sixty_seconds(handles)`: load the shipped file (`Path(__file__).resolve().parents[1] / "config" / "execution" / "execution-limits-v1.toml"`) with `load_execution_limits`, replace `handles.assembly.cadences` with `dataclasses.replace(..., protection_stall_after=shipped.scheduler_protection_stall_after)` BEFORE the first `complete_assembly(handles)` (complete_assembly caches the wiring, kra deviation 2), then assert `bounds.pop("protection_step") == 60` and every other bound is None. Keep `test_with_the_default_limits_no_task_has_a_stall_bound` unchanged (TEST_ONLY None).
Run `uv run pytest tests/test_execution_limits.py tests/test_live_limits_relationships.py tests/test_live_wiring.py -m "not docker" -n 4` and record RED: the failing test names and one reason line each (expected at least: the count 4 vs 6 and the numeric list, the decided-keys loop, the two `unset_alert_only_keys` pins, the renamed committed-file test, the new shipped-cadence test, the new negative control erroring because a NOT_CONFIGURED label with an integer refuses to load, and the new wiring test seeing None).

Step 2 (GREEN, config and words).
(a) Toml (LF, Edit tool): line 81 becomes `protection_stall_after_ms = 60000`; line 122 becomes `protection_stall_after_ms = "DECISION"`. Header comments: line 22 says the bound is set by DECISIONS D114 (owner answer 2026-11-15) and that unset would leave the watchdog off; in the "Set so far" sentence (24-28) add that scheduler.protection_stall_after_ms was set by DECISIONS D114 (owner answer 2026-11-15) from the 2026-11-15 Demo smoke and the longest legitimate protection path; keep the alert-only explanation at 33-35 (it is conditional and stays true). Comments must not contain the quoted form of the NOT_CONFIGURED word and no comment line may start with a key name. Do not touch `duration_summary_interval_ms` (lines 82 and 123) or `ban_end_clock_margin_ms`.
(b) config/execution/README.md (CRLF, helper): in the `[scheduler]` bullet for the stall key (:115) replace the parenthetical that calls unset "the shipped state" with: unset, the watchdog is off and nothing else changes; the shipped file sets it since D114 (owner answer 2026-11-15), so the watchdog is on. Keep the line prefix `- `scheduler.protection_stall_after_ms` - ` byte-identical (tests/test_execution_limits.py `_KEY_LINE`). Add one row to the values table after the `alerts.dedupe_window_ms` row: key `scheduler.protection_stall_after_ms` (alert only), value 60000, unit ms, row D114 (the D096 row is the precedent for a non-D089 row). Delete the stall-key bullet from the "Still `NOT_CONFIGURED`, on purpose" list (:156) and leave the other three bullets. NEVER write the key name followed by an optional backtick and then `=` or `:` and a digit (`test_the_readme_carries_no_value_and_states_the_rules`). Leave the README's older stale sentences (line 9 "four are filled", "Of the twenty keys", the REQUIRED user-data bullet) alone and list them in the SUMMARY as pre-existing.
(c) src/execution/execution_limits.py (CRLF, helper; words only, the limit value is never written here, a DECISIONS id and a date are fine): the module docstring sentence ending "no number is chosen for it" for the D111 key (:18-20) and the comment above ALERT_ONLY_LIMIT_KEYS (:128-129) now say the owner set its value by DECISIONS D114 (2026-11-15) in the limits file; unset, the watchdog is off and nothing else changes. Keep lines at most 100 characters. Change nothing else in src.
(d) tests/support/execution_limits.py (CRLF, helper; comment only): the comment above the stall entry (:65-67) says the shipped file sets the bound since D114, and TEST_ONLY keeps None on purpose so every wiring test keeps the watchdog off unless it sets a bound. The value stays None.

Step 3 (green and sweep for missed pins). Run the Task 1 verify set. Then, because pinned tests in other files were missed three times before, run `grep -rn "protection_stall_after\|STALL_KEY\|unset_alert_only_keys" tests/ src/ scripts/ config/` and `grep -rln "execution-limits-v1" tests/ scripts/`; every file listed must be in the verify set (add it and re-run if not). Then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv run python scripts/verify_decision_alignment.py all`. If the alignment gate fails only because D114 is cited before its row exists, move the DECISIONS row (Task 2 step a) into this commit and record it as a deviation. Measure CRLF/LF again. Stage the seven files by explicit path and commit: `feat(quick-261115-pdb): set scheduler.protection_stall_after_ms to 60000 (D114), stall watchdog on` with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never `git add -A` or `git add .`.
  </action>
  <verify>
    <automated>uv run pytest tests/test_execution_limits.py tests/test_live_limits_relationships.py tests/test_live_wiring.py tests/test_live_scheduler.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py tests/test_phase22_gate.py tests/test_phase24_gate.py tests/test_reconcile_stale_entry.py tests/test_execution_manager.py tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py tests/test_feed_freshness_skew.py tests/test_user_data_smoke_dry_run.py tests/test_binance_limits_ratified_file.py tests/test_dockerfile_revision_stamp.py tests/test_alerts_ops05_matrix.py tests/test_live_config_refusal.py -m "not docker" -n 4</automated>
  </verify>
  <done>
- RED recorded before any config edit; GREEN on the verify set with 0 failed and 0 skipped; the count of passed tests is the baseline plus the new tests.
- `grep -v '^#' config/execution/execution-limits-v1.toml | grep -c 'protection_stall_after_ms = 60000'` = 1 (HEAD 0); `grep -v '^#' config/execution/execution-limits-v1.toml | grep -c 'protection_stall_after_ms = "DECISION"'` = 1 (HEAD 0); `grep -c '"NOT_CONFIGURED"' config/execution/execution-limits-v1.toml` = 4 (HEAD 6); `grep -v '^#' config/execution/execution-limits-v1.toml | grep -c 'duration_summary_interval_ms = "NOT_CONFIGURED"'` = 2 (HEAD 2, unchanged).
- `git show --stat HEAD -- src/live` prints nothing; `git show HEAD -- src | grep '^+' | grep -v '^+++' | grep -c '60000'` = 0 (the value lives only in the toml, README and docs); `grep -c "float(" src/live/scheduler.py src/live/wiring.py` = 0 and 0.
- `grep -c '"scheduler.protection_stall_after_ms": None' tests/support/execution_limits.py` = 1.
- ruff check, ruff format --check, mypy src, decision alignment: pass. Every touched file has CRLF == LF (or CRLF 0 for the two LF files).
  </done>
</task>

<task type="auto">
  <name>Task 2: D114, DOC_STATUS, GLOSSARY, RUNBOOK 22 / 22.6 / 22.7 / 22.8 and the AGENTS.md open item</name>
  <files>docs/DECISIONS.md, docs/DOC_STATUS.md, docs/GLOSSARY.md, docs/operations/RUNBOOK.md, AGENTS.md</files>
  <action>
All five files are CRLF: edit with the bytes-aware helper, measure before and after. Write in plain English, short sentences, no claim that is not backed by the code, the plan facts or the owner's statements below. Verify every path and line you cite.

(a) docs/DECISIONS.md: confirm the last row is D113 and that `| D114 |` does not exist, then append one row directly after the D113 row with the same four columns as D113 (three ` | ` separators between the cells). Decision cell: `scheduler.protection_stall_after_ms` = 60000 with provenance DECISION in `config/execution/execution-limits-v1.toml`; the observe-only stall watchdog of the protection task and its `TASK_STALLED` alert are on. Status cell: Accepted (2026-11-15, owner answer; quick task 261115-pdb). Rationale cell, numbered items: (1) Measured: the owner-run Demo smoke of 2026-11-15 (`09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T104211Z.json`, untracked, outcome COMPLETE, 21 of 21 steps) gave a longest `protection_step` run of 886 ms in its `LIVE_TASK_DURATION` rows, a sample of about a dozen runs, with no rate limit and no ban in it. (2) Longest legitimate path: a cancel that meets the adapter's bounded STATUS_UNKNOWN retry (`_RECONCILER_CANCEL_MAX_ATTEMPTS` 3, `_RECONCILER_CANCEL_MAX_DELAY_SECONDS` 30, `src/adapters/binance_usdm.py:160-163`) plus the 1.5 s stop reread of D113 (3 x 0.5 s). (3) The bound must stay far below `protection.max_unprotected_ms` = 180000 (D089) so the alert fires well before the unprotected deadline; 60000 is one third of it. (4) 60000 is an inference from (1) and (2), not a measured maximum; it may be tuned after more Demo runs with the RUNBOOK 22.8 procedure and a new DECISIONS row. (5) Effect: a protection run still going after 60 s writes one `LIVE_TASK_EVENT` stall row and raises `TASK_STALLED` (HIGH, reason `STALL_BOUND_EXCEEDED`); observe only: the run is never cancelled, nothing is re-sent, SAFE_MODE is not entered; repeats inside `alerts.dedupe_window_ms` are suppressed in Telegram and journaled. (6) Unchanged: no code changed; the key stays alert only and never refuses the start; the TEST_ONLY value stays None; `scheduler.duration_summary_interval_ms` stays NOT_CONFIGURED; `LIVE_ORDERS_DISABLED` stays. (7) The value takes effect in a process started from a tree or image that carries this commit; a host image is rebuilt and re-pinned (D106). No run with the bound set has been observed yet. (8) This row is the DECISIONS row that D111 requires for a value; D111 and D112 are not edited.

(b) docs/DOC_STATUS.md: one change-log line after the D113 line (:97), same shape: date 2026-11-15, D114 recorded (owner answer 2026-11-15, quick task 261115-pdb), one sentence on the value and that it is an inference that may be tuned; documents amended: `GLOSSARY.md` (the `TASK_STALLED` row) and `operations/RUNBOOK.md` (sections 22, 22.6, 22.7, 22.8); say whether AGENTS.md changed. No other canonical document changed.

(c) docs/GLOSSARY.md: in the `TASK_STALLED` row (:326) replace the clause that says the key is shipped unset with: set to 60000 ms by D114 (owner answer 2026-11-15); while it is unset the watchdog is off and nothing produces this alert (D111). Change nothing else in the row or the file.

(d) docs/operations/RUNBOOK.md:
- Section 22 status line (:1148): it says the process was observed on Demo once. Before editing, `grep -rn` tests/ and scripts/ for its exact words; if no test or gate pins it, say it was observed on Binance Demo by the owner-run smoke rehearsals of 2026-11-06 and 2026-11-15 (section 22.6). If pinned, leave it and note it in the SUMMARY.
- 22.6: replace the 2026-11-15 paragraph (:1197) with ONE honest paragraph: the first run (`09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T083259Z.json`, outcome FAILED) stopped at TP_UNAVAILABLE: the take-profit step read the STOP_LOSS by client id as not found 0.5 s after the REST stop confirmation while the stop was on the exchange (keep the times and the stop at `restart_enable` from the old paragraph); D113 then added the bounded stop reread and the reason code in the alert; a second smoke (`09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T104211Z.json`) reached COMPLETE, 21 of 21 steps; the cause of the first failure is not proven (Demo lag on queries by id is the leading explanation) and it is not proven that the fix is why the second run passed. Then add a short "After a failed run" procedure as owner-run steps, as the owner observed on 2026-11-15: close the position and the orders by hand on the Demo account; start the rehearsal once so the process sweeps the stale plan (it stops at step `demo_enable` on SAFE_MODE raised by an `UNSYNCED_ALGO` divergence, the section 21.4 case of a close made by hand); run `scripts/demo_clear.py` (step 2 above); run the rehearsal again, without `--initialize-gate-state` once the gate state exists (otherwise it is held with `GATE_STATE_EXISTS`). Before writing, check in the code that `demo_enable` (scripts/demo_rehearsal.py), `--initialize-gate-state` (scripts/demo_rehearsal.py) and `GATE_STATE_EXISTS` exist and how an `UNSYNCED_ALGO` divergence reaches SAFE_MODE (src/reconcile/compare.py, src/reconcile/classify.py); if the code names the SAFE_MODE reason differently, write the code's name and say the owner saw it as UNSYNCED_ALGO. Do not invent a mechanism.
- 22.7 (:1207): replace the stall-key bullet: the bound is 60000 ms since D114 (owner answer 2026-11-15), the watchdog is on and `TASK_STALLED` can fire; the value is an inference, not a measured maximum, and tuning it after more Demo runs is the owner's (section 22.8). Leave the duration-window bullet (:1208) as it is.
- 22.8: keep the heading text unchanged. Status line (:1212): since D114 the shipped limits set the bound to 60000 ms, so the watchdog is on; the duration window stays unset; the duration record was observed on the owner-run Demo smoke of 2026-11-15; no stall and no `TASK_STALLED` have been observed and no run with the bound set has been observed yet. "The key." paragraph (:1218): the key is set to 60000 with provenance DECISION by D114; it stays alert only (unset it never refuses the start and the watchdog is off); keep the label rule, the below-180000 rule and the image rebuild sentence. Add one paragraph "Measured figures (2026-11-15)" before the procedure with the same facts as D114 items (1) to (4), stating plainly that 60000 is an inference and may be tuned. Keep queries 1 to 3 and the procedure; procedure step 4 becomes: change it with a new DECISIONS row and the provenance DECISION, then rebuild and re-pin the image. Replace the last line (:1267) so it says the bound is set by D114 and no number is proposed here for the window.

(e) AGENTS.md "Still open (owner)" (:122-126): replace only the line naming the stall key with one line that names the still-open optional `NOT_CONFIGURED` key `scheduler.duration_summary_interval_ms` (D112, RUNBOOK 22.8) instead, keeping the line count unchanged (219, cap 230). Name no new path. Then run `uv run pytest tests/test_agents_md.py -m "not docker"` and `uv run python scripts/verify_decision_alignment.py all`; if either fails, run `git checkout -- AGENTS.md` and report it in the SUMMARY instead of committing it.

Run the verify command, measure CRLF/LF, stage these files by explicit path (AGENTS.md only if kept) and commit `docs(quick-261115-pdb): D114 protection stall bound 60000 ms, RUNBOOK 22.6-22.8 and the 2026-11-15 smokes` with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
  </action>
  <verify>
    <automated>uv run python scripts/verify_decision_alignment.py all && uv run pytest tests/test_agents_md.py tests/test_decision_alignment.py tests/test_decision_alignment_authority.py tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_ops_risk.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase24_gate.py tests/test_execution_limits.py -m "not docker" -n 4</automated>
  </verify>
  <done>
- `grep -c '^| D114 |' docs/DECISIONS.md` = 1 (HEAD 0), and the row has the same separator count as the D113 row; `grep -c '261115-pdb' docs/DOC_STATUS.md` = 1 (HEAD 0).
- The old unset wording is gone: `grep -c 'protection_stall_after_ms`, shipped' docs/GLOSSARY.md` = 0 (HEAD 1); the 22.7 stall bullet no longer says the key ships unset (`grep -c 'the stall watchdog is off and no' docs/operations/RUNBOOK.md` = 0, HEAD 1).
- RUNBOOK names both 2026-11-15 evidence files (`grep -c '20261115T104211Z' docs/operations/RUNBOOK.md` >= 1) and says "not proven" for the cause and for the fix; 22.8 still contains the three SQL queries (`grep -c 'FROM journal_events' docs/operations/RUNBOOK.md` = 4, HEAD 4).
- AGENTS.md: either committed with tests/test_agents_md.py and the alignment gate green and 219 lines, or restored with `git checkout -- AGENTS.md` and reported.
- Verify command passes; every file CRLF == LF; `git show --stat HEAD -- src tests scripts config` prints nothing.
  </done>
</task>

<task type="auto">
  <name>Task 3: Final gates and SUMMARY (no commit)</name>
  <files>.planning/quick/261115-pdb-set-scheduler-protection-stall-after-ms-/261115-pdb-SUMMARY.md</files>
  <action>
Run once, after both commits: `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src`; `uv run python scripts/verify_decision_alignment.py all`; the Task 1 verify set; the Task 2 verify set; and the live sweep `uv run pytest tests/test_live_*.py -m "not docker" -n 4`. TEST_DATABASE_URL is set in the process environment: never read, echo or print its value; report that the `*_pg.py` files of the sweep ran (passed counts) rather than skipped. Never run the full suite, `-m demo`, any `--execute` script, or any Demo, live or network call. If a failure appears, check it at the parent commit before calling it pre-existing (a `git archive` copy in the scratchpad, as kra and nnt did).

Write the SUMMARY with the usual frontmatter (plan_head_before, plan_head_after, commits, actuals) and: the commits table; RED and GREEN evidence with the failing test names; a "Pins changed (old -> new)" table (every pin, file and line); the list of pins checked and NOT changed (the facts list in the plan context, each re-confirmed); the CRLF/LF table before and after per file; a claim table mapping every new sentence of D114 and the RUNBOOK to a file:line or to the owner statement; the README stale sentences left alone; the AGENTS.md outcome; Residuals for the owner (the bound is an inference to tune after more Demo runs; no run with the bound set observed yet; the image must carry the commit; the untracked 2026-11-15 evidence files remain the owner's to commit). Do not commit the SUMMARY or STATE.md: the orchestrator does.
  </action>
  <verify>
    <automated>uv run ruff check && uv run ruff format --check && uv run mypy src && uv run python scripts/verify_decision_alignment.py all && uv run pytest tests/test_live_*.py -m "not docker" -n 4</automated>
  </verify>
  <done>
- Every gate passes (or a failure is shown pre-existing at the parent commit and recorded); `git rev-list --count <plan_head_before>..HEAD` = 2 (or 1 if a gate forced one commit, recorded as a deviation); `git diff --cached --name-only` is empty.
- `.planning/STATE.md`, `.planning/config.json`, `.planning/REQUIREMENTS.md`, `.planning/state.json` are still modified and unstaged; every untracked file (all evidence json) is untouched; nothing pushed; branch `develop`.
- The SUMMARY exists with the sections listed above.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| limits file -> live process | the shipped toml is read at start; a value turns the stall watchdog and its alert on |
| live process -> Telegram | TASK_STALLED reaches the operator through the existing alert sink (dedupe, codes only) |
| repo docs -> operator | RUNBOOK steps are followed on the Demo account by the owner |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-pdb-01 | Tampering | config/execution/execution-limits-v1.toml stall value | medium | mitigate | provenance DECISION required by the loader for an integer; D114 row; phase 19 invariant 4 and the new committed-file test pin 60000 and DECISION; rule 6 keeps it below max_unprotected_ms |
| T-pdb-02 | Elevation of Privilege | a set bound changing trading behavior | high | mitigate | no code change; the watchdog is observe only (never cancels, never re-sends, no SAFE_MODE) as built in D111; the wiring test proves only the protection task gets a bound; the key stays alert-only so the start is never refused or enabled by it |
| T-pdb-03 | Denial of Service | alert noise from repeated stalls | low | accept | repeats inside alerts.dedupe_window_ms are suppressed in Telegram and journaled (existing D111 behavior); 60000 ms is far above the observed 886 ms |
| T-pdb-04 | Information Disclosure | SUMMARY, docs, test output | medium | mitigate | never read .env or print TEST_DATABASE_URL; docs carry only file names, key names, numbers and read-only SQL text; evidence files are not opened |
| T-pdb-05 | Repudiation | why 60000 | low | mitigate | D114 states the basis and that it is an inference, not a measured maximum; RUNBOOK 22.8 keeps the measuring procedure |
| T-pdb-SC | Tampering | npm/pip/cargo installs | low | accept | no package is installed or added; uv.lock untouched |
</threat_model>

<verification>
- Shipped file: stall bound 60000 with DECISION; summary window and ban margin still NOT_CONFIGURED; four quoted NOT_CONFIGURED strings.
- End to end: shipped file -> loader -> LiveCadences (60 s, total_seconds based) -> protection TaskSpec stall_after_seconds 60, other tasks None.
- Every grep-found test file and the named gates green; the live sweep green; ruff, format, mypy, decision alignment pass.
- D114, DOC_STATUS line, GLOSSARY row, RUNBOOK 22/22.6/22.7/22.8 updated honestly; AGENTS.md updated only with its gates green.
</verification>

<success_criteria>
- The watchdog is ON for the protection task in the shipped configuration (60000 ms, DECISION), with no change to src behavior, no float() in src/live, and the TEST_ONLY value still None.
- Two commits (config/tests, docs) with the Sonnet trailer, explicit-path staging, no push; owner-modified and untracked files untouched; each file keeps its line endings.
- The SUMMARY records RED/GREEN, every moved and unmoved pin, CRLF/LF counts, the claim table and the residuals.
</success_criteria>

<output>
Create `.planning/quick/261115-pdb-set-scheduler-protection-stall-after-ms-/261115-pdb-SUMMARY.md` when done (not committed by the executor).
</output>
