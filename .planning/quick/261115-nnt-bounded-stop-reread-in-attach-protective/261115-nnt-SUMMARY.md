---
phase: quick-261115-nnt
plan: 01
subsystem: execution-protection, alerts, runbook
tags: [d113, attach-protectives, stop-reread, tp-unavailable, alert-reason-code, demo-lag, runbook-22-6]
requires: [quick-261115-kra, quick-261115-k46]
provides:
  - "attach_protectives_to_fill reads the stop by id up to 1 + 3 times (0.5 s apart) while it answers not found or a status that is neither ACTIVE nor TERMINAL_FAILED; every fail-closed hold and its detail text is unchanged"
  - "The TP_UNAVAILABLE alert reason is the reason code (ENTRY_WITHOUT_PROTECTIVE, PLAN_SYMBOL_MISMATCH, POSITION_SIDE_MISMATCH) instead of INVALID_REASON; the journal note keeps the detail and the code"
  - "D113, DOC_STATUS line, GLOSSARY 9.3 POSITION_SIDE_MISMATCH and 9.4 TP_UNAVAILABLE rows, RUNBOOK section 3 note with a read-only journal query, RUNBOOK 22.6 sentence on the 2026-11-15 smoke"
affects: [src/execution/manager.py, src/execution/protection.py, scripts/gen_phase23_fixtures.py, tests/fixtures/phase23, docs/DECISIONS.md, docs/operations/RUNBOOK.md]
tech-stack:
  added: []
  patterns: ["bounded reread that reuses existing constants (no new number, D-12)", "alert reason = enum-like code, free detail in the journal"]
key-files:
  created: []
  modified:
    - src/execution/manager.py
    - src/execution/protection.py
    - tests/test_execution_attach.py
    - tests/test_protection_take_profits.py
    - tests/test_protection_demo_shapes.py
    - scripts/gen_phase23_fixtures.py
    - tests/fixtures/phase23/alerts/TP_UNAVAILABLE.txt
    - tests/fixtures/phase23/DERIVATIONS.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/GLOSSARY.md
    - docs/operations/RUNBOOK.md
decisions:
  - "D113: the stop read of the take-profit step is read again at most 3 times, 0.5 s apart (the constants of the TP-leg confirmation); the TP_UNAVAILABLE alert reason is the reason code; reads only"
metrics:
  tasks: 3
  files: 12
status: complete
commits: 2
plan_head_before: 527455adb1cfefbf90c5a3a943126be989b059d9
plan_head_after: ecfb27904f26092609c113d1c11b7d8f26a07d70
actuals:
  tokens: 6650    # chars/4 over the added lines of the two commits (26,593 chars; code, tests, docs)
  tasks: 3
  commits: 2      # measured: git rev-list --count 527455ad..HEAD
---

# Phase quick-261115-nnt Plan 01: Bounded stop reread in attach and the reason code in the TP_UNAVAILABLE alert Summary

The take-profit step no longer holds a stop on the first "not found" of a by-id read: it reads the stop again, at most 3 times 0.5 s apart (the constants and the wait of the TP-leg confirmation), and the TP_UNAVAILABLE alert now carries a reason code the operator can search instead of INVALID_REASON. Reads only; fail-closed paths are unchanged. The Demo lag explanation is the leading one, not proven, and the fix is tested with fakes only, not re-observed on Demo.

## Commits

| Task | Commit | Message | Files |
|---|---|---|---|
| 1 | `d1c971c7` | fix(quick-261115-nnt): bounded reread of the stop in attach_protectives_to_fill and the reason code in the TP_UNAVAILABLE alert | the 8 code, test, generator, golden and DERIVATIONS files |
| 2 | `ecfb2790` | docs(quick-261115-nnt): D113 bounded stop reread and the TP_UNAVAILABLE reason code | docs/DECISIONS.md, docs/DOC_STATUS.md, docs/GLOSSARY.md, docs/operations/RUNBOOK.md |
| 3 | (none) | final gates and this SUMMARY; the orchestrator commits the SUMMARY | |

Both commits carry `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. `git show --stat d1c971c7` lists exactly the 8 Task 1 files; `git show --stat ecfb2790 -- src tests scripts` prints nothing. No file was deleted by either commit.

## Design as built

- **Helper** `_read_stop_by_rest(*, adapter, client_algo_id) -> str | None` (`src/execution/manager.py:1997`), directly after `_confirm_leg_by_rest` (`:1965`, unchanged: the AST comparison against 527455ad passed). Loop `for attempt in range(1 + _CONFIRM_REREADS)`. An exception on any read returns `STOP_LOSS: probe <ExcType>` at once (`:2021`); a `found` that is neither True nor False returns `STOP_LOSS: probe outcome unknown` at once (`:2024`); found True and `is_protection_confirmed(status)` returns None (adopted); found True otherwise sets `STOP_LOSS: existing leg status <repr>` (`:2030`) and the TERMINAL_FAILED class (REJECTED, EXPIRED) breaks at once; found False sets `STOP_LOSS: not found` (`:2033`). The loop ends after the last attempt and returns that read's detail; otherwise `await asyncio.sleep(_CONFIRM_REREAD_DELAY_SECONDS)` (`:2036`).
- **Constants**: `_CONFIRM_REREADS = 3` (`:1758`) and `_CONFIRM_REREAD_DELAY_SECONDS = 0.5` (`:1759`) are reused; no new constant, no limit key (`grep -cE '^_[A-Z_]+ = [0-9]' src/execution/manager.py` is 2 before and after).
- **Attach step 2** is now one call: `stop_detail = await _read_stop_by_rest(...)` (`:2210`), `return hold(stop_detail)` when it is not None (`:2212`), then `confirmed_roles` as before (`:2213`). The attach docstring item 2 names the bounded reread and keeps the words D034, `emergency_close` and `emergency_manual_close`.
- **Alert reason**: `_enter_tp_unavailable` (`src/execution/protection.py:2641`) passes `reason=reason_code` (`:2677`); the journal note still carries `failure_detail` and `reason_code` (`:2662`); docstring sentence at `:2652-2654`. Callers: `POSITION_SIDE_MISMATCH` (`:2597`) and `outcome.reason_code` (`:2636`).
- **Golden**: generator case `("TP_UNAVAILABLE", "TP_UNAVAILABLE", "ENTRY_WITHOUT_PROTECTIVE", PLAN_SUBJECT)` (`scripts/gen_phase23_fixtures.py:86`, comment `:84-85`); `tests/fixtures/phase23/alerts/TP_UNAVAILABLE.txt:3` reads `reason: ENTRY_WITHOUT_PROTECTIVE`; the alert wording text is unchanged.
- **Found-and-class rule (DC-3)**: the TERMINAL_FAILED test is applied only when `found is True`; a found=False answer with a stray status is still just "not found" and is read again.

## Task 1: RED and GREEN evidence

- **Baseline** (see deviation 6): the Task 1 verify set (55 files found by the grep, plus the 19 `tests/test_demo_twin_*.py` files and the 4 named files) on a `git archive 527455ad` copy outside the repository: `2489 passed, 1 skipped, 3 xfailed`. The one skip is `tests/test_phase19_gate.py:830` ("commit fffdb6e is not in this clone"), caused by the archive having no git history; in the repository the same set at HEAD is 2490 passed, 3 xfailed.
- **RED** (tests and pins only, `tests/test_execution_attach.py`, `tests/test_protection_take_profits.py`, `tests/test_protection_demo_shapes.py`): `19 failed, 84 passed`. Failing: status table for TRIGGERING, TRIGGERED, FINISHED, CANCELED; the absent-stop count test; `test_a_stop_not_found_once_then_active_is_adopted_on_the_reread`; `test_a_stop_never_found_holds_after_one_read_and_three_rereads`; `test_a_stop_probe_exception_on_a_reread_holds_at_once`; `test_an_unknown_stop_answer_is_never_read_again[after_not_found]`; `test_a_found_stop_without_a_status_then_active_is_adopted`; `test_a_stop_that_is_not_active_yet_is_adopted_once_it_shows_active`; `test_the_detail_after_the_last_reread_is_the_one_of_the_last_read`; the five `_assert_tp_unavailable_and_nothing_else` callers (stale snapshot, incomplete snapshot, unsizeable TP1, rejected leg, wrong-side position); both coordinator tests. As the plan expected, these passed at RED (characterisation): exception on the first read, unknown answer on the first read, terminal at once (REJECTED, EXPIRED), and the OperationalAlert.create tests. At RED the coordinator by-id count was 2 for the lagging shape (supervision read plus a single attach read), which matches the plan's math of 1 + 1 before the fix and 1 + 4 after.
- **GREEN** on the three files: `103 passed`. Then the full Task 1 verify set, `-m "not docker" -n 4`: **2507 passed, 3 xfailed, 0 failed, 0 skipped** (baseline 2490 in-repo, so +17 tests, no test removed). The 3 xfails are present at baseline too.
- Greps: `def _read_stop_by_rest` 1 (HEAD 0); `reason=detail` 0 (HEAD 1); `reason=reason_code` 1; `"TP_UNAVAILABLE", "TP_UNAVAILABLE", "TP_UNAVAILABLE"` in the generator 0 (HEAD 1); golden `reason: ENTRY_WITHOUT_PROTECTIVE` 1 (HEAD 0); `float(` in manager.py 0; `_CONFIRM_REREAD_DELAY_SECONDS` 5 (HEAD 2; the definition and its uses, no new definition, see deviation 5).
- `uv run ruff check`, `uv run ruff format --check` (1029 files), `uv run mypy src` (291 files), `PYTHONPATH=. uv run python scripts/gen_phase23_fixtures.py --check` (exit 0): pass. `ruff format` re-wrapped one assertion in `tests/test_protection_demo_shapes.py` (CRLF kept: 454/454).

Tests added (17): attach (11): a stop not found once then ACTIVE is adopted (2 reads, one 0.5 s wait, SAFE_MODE not entered, TP1 and TP2 placed); never found holds after 1 + 3 reads with three waits, one SAFE_MODE entry, no intent row; exception on the first read holds at once (1 read, no wait); exception on a reread holds at once (2 reads); an unknown answer is never read again (parametrised: first read, after a not found); a terminal status is never read again (REJECTED and EXPIRED, derived with `classify_algo_status`); found with no status then ACTIVE is adopted; TRIGGERING then not found then ACTIVE is adopted (3 reads); the detail after the last reread is the last read's. Coordinator (2, `tests/test_protection_demo_shapes.py`): the 2026-11-15 shape with `DemoLag(by_id_absent=3)` ends COMPLETE (stop placed once, TP1 and TP2 once each, one wait, no alert, no SAFE_MODE, no close, no cancel); with `by_id_absent=99` it ends TP_UNAVAILABLE after exactly 1 supervision read + 4 attach reads, alerts `[("TP_UNAVAILABLE", "ENTRY_WITHOUT_PROTECTIVE")]`, journal note `failure_detail` `STOP_LOSS: not found` and `reason_code` ENTRY_WITHOUT_PROTECTIVE, SAFE_MODE once, stop placed once, no close. Alert (4, `tests/test_protection_take_profits.py`): `OperationalAlert.create(event="TP_UNAVAILABLE", reason=X).reason == X` for the three codes, and the old free detail gives `INVALID_REASON`.

All of these use a recording replacement of `asyncio.sleep` (virtual wait; only non-zero delays are recorded), so none waits for real. Every attach test still goes through `run_attach`, which asserts attach never placed the stop and never cancelled anything.

## Pins changed (old -> new)

| File | Pin | Old | New |
|---|---|---|---|
| tests/test_execution_attach.py | `script_algo_status` | returned None | returns the list of reads of that id (backward compatible; the TP1 caller ignores it) |
| tests/test_execution_attach.py | `test_existing_stop_adoption_follows_the_status_table` | no read or wait count | read count 1 when `is_protection_confirmed(status)` or class TERMINAL_FAILED, else 4; waits `[0.5] * (reads - 1)`; derived with `classify_algo_status`, never a status list |
| tests/test_execution_attach.py | `test_absent_stop_holds_without_placing_a_stop_or_a_take_profit` | no count | 4 stop reads from `rig.fake.calls_to("query_algo_order_by_client")` filtered by STOP_ID, three waits of 0.5 |
| tests/test_protection_take_profits.py | `_assert_tp_unavailable_and_nothing_else` | `(rig, detail)`, alert pair `("TP_UNAVAILABLE", detail)`, note `failure_detail` only | `(rig, detail, *, reason_code=HOLD)`, alert pair `("TP_UNAVAILABLE", reason_code)`, note `failure_detail` and `reason_code` |
| tests/test_protection_take_profits.py | wrong-side caller | `(rig, "position side does not match the plan")` | adds `reason_code="POSITION_SIDE_MISMATCH"` |
| scripts/gen_phase23_fixtures.py | TP_UNAVAILABLE case reason | `TP_UNAVAILABLE` | `ENTRY_WITHOUT_PROTECTIVE` |
| tests/fixtures/phase23/alerts/TP_UNAVAILABLE.txt | line 3 | `reason: TP_UNAVAILABLE` | `reason: ENTRY_WITHOUT_PROTECTIVE` (regenerated by the script only) |
| tests/fixtures/phase23/DERIVATIONS.md | the TP_UNAVAILABLE row and lines 17-18 | reason described as the free detail; stale line numbers | reason is the reason code, golden uses ENTRY_WITHOUT_PROTECTIVE, free detail in the journal note, D113; lines `protection.py` 2641-2681, callers 2595 and 2634 |

The 4-read and 0.5 s values are pinned as literals in the attach tests with a comment naming the two constants, like the existing `1 + 1 + 3` of the TP1 test.

## Line endings (CRLF / LF counts, measured with Python on the bytes)

| File | Before | After |
|---|---|---|
| src/execution/manager.py | 3037/3037 | 3076/3076 |
| src/execution/protection.py | 3301/3301 | 3305/3305 |
| tests/test_execution_attach.py | 839/839 | 1064/1064 |
| tests/test_protection_take_profits.py | 466/466 | 507/507 |
| tests/test_protection_demo_shapes.py | 364/364 | 454/454 |
| scripts/gen_phase23_fixtures.py | 357/357 | 359/359 |
| tests/fixtures/phase23/alerts/TP_UNAVAILABLE.txt | 8/8 | 0/8 (LF, written by the generator) |
| tests/fixtures/phase23/DERIVATIONS.md | 163/163 | 164/164 |
| docs/DECISIONS.md | 116/116 | 117/117 |
| docs/DOC_STATUS.md | 96/96 | 97/97 |
| docs/GLOSSARY.md | 650/650 | 652/652 |
| docs/operations/RUNBOOK.md | 1253/1253 | 1267/1267 |

Format is CRLF = LF (or LF only) everywhere, no mixed endings. Edits used throwaway scripts in the scratchpad (a bytes-aware replace that keeps each file's own ending); nothing was added to the repository besides the intended files. The LF golden is the script's own output; the blob in the index was already LF (`git ls-files --eol` says `i/lf`).

## Claim table (code, D113, GLOSSARY rows, RUNBOOK additions)

| Claim | Backed by |
|---|---|
| Attach reads the stop at most 1 + 3 times, 0.5 s apart, with the constants of the TP-leg confirmation | `src/execution/manager.py:1758-1759` (constants), `:2017-2037` (loop and `asyncio.sleep` at `:2036`); same constants and wait at `:1993`; tests `test_a_stop_never_found_holds_after_one_read_and_three_rereads`, status-table test |
| No new number | `grep -cE '^_[A-Z_]+ = [0-9]'` = 2 before and after; no limit key added (`git show --stat d1c971c7` has no config file) |
| Not found and a not-yet-ACTIVE, non-terminal status are read again | `src/execution/manager.py:2030-2036` (found True, not confirmed, class not TERMINAL_FAILED, not last attempt) and `:2033`; tests for not-found-then-ACTIVE, TRIGGERING-then-ACTIVE, None-then-ACTIVE |
| Exception, unknown shape and TERMINAL_FAILED hold at once | `:2021` (exception), `:2024` (unknown), `:2031` and `:2034-2035` (terminal break); tests `..._exception_on_the_first_read_...`, `..._on_a_reread_...`, `test_an_unknown_stop_answer_is_never_read_again`, `test_a_terminal_stop_status_is_never_read_again` |
| The four detail texts are unchanged | `:2016`, `:2021`, `:2024`, `:2030`; the pins at `tests/test_execution_attach.py` (not found, probe TimeoutError, probe outcome unknown, existing leg status) pass unchanged |
| Every hold enters SAFE_MODE ENTRY_WITHOUT_PROTECTIVE once and places no take profit | `hold()` of attach, `src/execution/manager.py:2168`, called at `:2212`; `assert_held` and `placed_ids(rig) == []` in the new tests |
| Reads only: never places or cancels | helper calls only `adapter.query_algo_order_by_client` (`:2019`); `run_attach` asserts `assert_stop_untouched` for every attach test; coordinator tests assert `cancel_algo_order == []` and one stop placement |
| `_confirm_leg_by_rest` is unchanged | AST comparison with `git show 527455ad:src/execution/manager.py` printed `_confirm_leg_by_rest unchanged` |
| 2026-11-15 shape now ends COMPLETE; a lag longer than 4 reads still holds | `tests/test_protection_demo_shapes.py` `test_the_2026_11_15_shape_a_lagging_by_id_read_at_the_tp_step_now_completes` and `test_a_by_id_read_that_keeps_lagging_holds_tp_unavailable_with_a_readable_reason` |
| The TP_UNAVAILABLE alert reason is the reason code | `src/execution/protection.py:2677`; callers `:2597` and `:2636`; `tests/test_protection_take_profits.py` helper and the wrong-side caller |
| The sanitiser turns free text into INVALID_REASON and keeps a code | `src/ops/alerts.py:145` (`_CODE_RE`), `:152` (`_is_reason`), `:269` (`safe_reason`); `test_tp_unavailable_alert_keeps_a_reason_code`, `test_tp_unavailable_alert_turns_the_free_detail_into_invalid_reason` |
| The journal note keeps both the detail and the code | `src/execution/protection.py:2662`; the helper in `tests/test_protection_take_profits.py` and the demo-shapes test assert both keys (the note also carries `symbol` and `trade_plan_id`, deviation 2) |
| attach's refusal codes are ENTRY_WITHOUT_PROTECTIVE and PLAN_SYMBOL_MISMATCH; NO_FILL is excluded | `src/execution/manager.py` `hold()` default `reason_code`, the bind check, the `NO_FILL` return; `src/execution/protection.py:2633-2636` |
| D113 row, same 4 columns as D112 | `docs/DECISIONS.md:117` (after D112 at `:116`); 3 ` | ` separators in both rows |
| D113 evidence times (08:33:34.51Z, 08:33:35.04Z, 0.53 s, Demo UI 08:33:34Z, INVALID_REASON, outcome FAILED, stopped at restart_enable) | the owner evidence recorded in the plan context (journal rows, Demo UI, the untracked evidence file `09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T083259Z.json`); read from the plan, not re-run, and the evidence file was not opened or staged by this task |
| Earlier Demo lag: 2026-10-22 (plan 20-27) and TAKE_PROFIT_2 on 2026-11-01 | `tests/test_protection_demo_shapes.py:1-15`; `src/execution/manager.py:1972-1973` (docstring of `_confirm_leg_by_rest`) |
| The listing cross-check is not used in attach | `attach_protectives_to_fill` calls only `query_algo_order_by_client` (via the helper); the cross-check is `src/execution/protection.py` coordinator code (plan 20-27) |
| DOC_STATUS line | `docs/DOC_STATUS.md:97` (after the D112 line at `:96`); `grep -c 261115-nnt` = 1 |
| GLOSSARY `POSITION_SIDE_MISMATCH` (9.3) | `docs/GLOSSARY.md:286` (after the `LIVE_TASK_DURATION` row at `:285`); emitted at `src/execution/protection.py:2597` |
| GLOSSARY `TP_UNAVAILABLE` (9.4): alert event of OPS05_MATRIX, not a SAFE_MODE reason | `docs/GLOSSARY.md:327` (after `TASK_STALLED` at `:325` and the existing row); alert event `ALERT_TP_UNAVAILABLE` at `src/execution/protection.py:259`; severity HIGH at `src/ops/alerts.py:100`; journal event `PROTECTION_TP_UNAVAILABLE` at `src/execution/protection.py:303` |
| RUNBOOK section 3 note | `docs/operations/RUNBOOK.md:51` (paragraph) with the SQL block at `:53-59`; read-only `SELECT` over `journal_events` with the columns `occurred_at_utc`, `entity_id`, `payload_json` used by the 22.8 queries; the operator exit is section 21.1 (`:1012`) |
| RUNBOOK 22.6 sentence says leading explanation, not proven; fakes only; not re-observed on Demo | `docs/operations/RUNBOOK.md:1197` |

The new RUNBOOK SQL was not run (no PostgreSQL journal with a TP_UNAVAILABLE row here, and an agent never runs the Demo). It is text only; the column names are those of the 22.8 queries.

## Final gates (after both commits)

| Gate | Result |
|---|---|
| `uv run ruff check` | pass |
| `uv run ruff format --check` | pass (1029 files) |
| `uv run mypy src` | pass (291 files) |
| `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS |
| `PYTHONPATH=. uv run python scripts/gen_phase23_fixtures.py --check` | exit 0 |
| Task 1 verify set (the grep set of 55 files plus `tests/test_demo_twin_*.py` and the 4 named files, `-m "not docker" -n 4`) | 2507 passed, 3 xfailed, 0 failed, 0 skipped (baseline 2490 in-repo / 2489 + 1 skip on the archive copy) |
| Task 2 set (phase 19, 20, 22, 23, 24 gates, bookkeeping, enums, transitions, agents_md) | 366 passed |
| phase 18, no_unratified_defaults, phase 20, phase 24 gates | 210 passed |
| Live sweep `uv run pytest tests/test_live_*.py -m "not docker" -n 4` | **1228 passed, 0 failed, 0 skipped** |
| `tests/test_live_*pg.py` alone (TEST_DATABASE_URL is set; the value was not read or printed) | 21 passed, so the PostgreSQL files ran |
| `git rev-list --count 527455ad..HEAD` | 2 |
| `git diff --cached --name-only` | empty |

The sweep has no failure. The one failure that the kra SUMMARY reported (`tests/test_live_demo_smoke.py::test_a_restart_that_finds_no_snapshot_row_fails_closed`) is gone: it was fixed by commit `5a7aeb9f` (the HEAD parent chain of this task), not by this task. No test file of the sweep, and none of the 40+ files that forbid real sleeps, reached the new `asyncio.sleep`.

## Deviations from Plan

1. **[Premise corrected] The generator needs `PYTHONPATH=.`.** `uv run python scripts/gen_phase23_fixtures.py` (the plan's command, with and without `--check`) fails with `ModuleNotFoundError: No module named 'src'` when run as a script. I ran it as `PYTHONPATH=. uv run python scripts/gen_phase23_fixtures.py` (the same form the RUNBOOK uses for `demo_clear.py`). No repository file was changed for this.
2. **[Plan detail corrected] The journal note carries more than two keys.** `_journal_note` adds `symbol` and `trade_plan_id`, so the note payload is not exactly `{failure_detail, reason_code}`. The tests compare the two keys (`failure_detail`, `reason_code`); the production note is unchanged.
3. **[Working tree] The generator rewrote all 26 goldens with LF.** `git status --short` then listed 18 of them as modified although `git diff` was empty (`i/lf w/lf`, `autocrlf=true`). To follow the plan's stop condition literally I restored the 17 unintended files with `git checkout -- <path>` (explicit per-file paths, each only touched by the script) and they are CRLF again; `git status` then lists only `tests/fixtures/phase23/alerts/TP_UNAVAILABLE.txt` there. That file stays LF (the script's output).
4. **[Protected-branch guard] The SDK query for the default branch was not available** in this shell. I used `git symbolic-ref refs/remotes/origin/HEAD` (master) and the orchestrator's `<sequential_execution>` instruction: develop is the working branch, not the default branch, and the previous quick task committed there. `git.allow_default_branch_commits` is not set and was not needed.
5. **[Grep baseline] `grep -c "_CONFIRM_REREAD_DELAY_SECONDS" src/execution/manager.py` is 5, not 2.** It counts the definition, the use in `_confirm_leg_by_rest`, the new use in the helper and two mentions in docstrings. No definition was added; the numeric-constant grep stays at 2.
6. **[Order] The Step A baseline summary line was taken after the fact, on a copy.** I ran the verify set at HEAD only after the change (on a `git archive 527455ad` copy in the scratchpad, since I had already edited the repository), so the baseline line is 2489 passed, 1 skipped, 3 xfailed with the one skip explained above. The copy was left in the scratchpad.
7. **[Optional item skipped] The module docstring line `protection.py:107-108` was not changed** (the plan marked it optional); only the `_enter_tp_unavailable` docstring has the new sentence.
8. **[Scope note] RUNBOOK additions are separate paragraphs.** The 22.6 sentence is its own paragraph after the 2026-11-06 "Observed on Demo" paragraph, with no heading change.

## Auth gates

None.

## Known Stubs

None.

## Threat Flags

None. The only change in what an alert shows is the reason, which moves from a sanitised placeholder to a fixed code; no endpoint, auth path or file access was added. T-nnt-01 to T-nnt-05 are covered by the tests above.

## Not run

The full suite, docker-marked tests, `pytest -m demo`, any `--execute` script, any Demo or live call, the new RUNBOOK SQL.

## Residuals for the owner

- The fix is tested with fakes only and was not re-observed on Demo; the 2026-11-15 explanation (Demo lag on by-id queries) is the leading one, not proven. The shipped image must carry these commits before a Demo smoke can show it.
- Whether 4 reads over 1.5 s cover Demo's by-id lag is unknown; if the lag lasts longer the hold still happens (fail closed), now with a readable reason code.
- Attach has no listing cross-check (DC-6, D113 item 7); adding one is an owner decision.
- The untracked 2026-11-15 smoke evidence files under `.planning/phases/24-live-runtime-composition-demo/evidence/` are the owner's to commit; this task did not open, stage or move them.
- `restart_enable` of the smoke rehearsal stopped on that SAFE_MODE; a repeat run on Demo is the owner's.

## Self-Check: PASSED

- `d1c971c7` and `ecfb2790` are ancestors of HEAD; `git rev-list --count 527455ad..HEAD` = 2; `plan_head_before` and `plan_head_after` match the ledger (`.git/gsd-plan-head-before-quick-261115-nnt-01`) and `git rev-parse HEAD`.
- All created and modified files exist; `git diff --cached` is empty; `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/config.json` and `.planning/state.json` are still modified and unstaged; untracked files (including the demo evidence json files) are untouched.
- No file deleted by either commit; nothing pushed; branch `develop` unchanged; `.planning/STATE.md` and this SUMMARY were not committed.
