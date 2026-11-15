---
phase: quick-261114-ufz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  # Task 1 (docs, all CRLF in the working tree)
  - docs/operations/RUNBOOK.md
  - docs/DOC_STATUS.md
  - AGENTS.md            # conditional: only if tests/test_agents_md.py and the authority gate stay green
  # Task 2 (code, both CRLF in the working tree)
  - scripts/export_soak_evidence.py
  - tests/test_soak_evidence_export.py
  # Task 3
  - .planning/quick/261114-ufz-runbook-for-partial-restore-and-task-sta/261114-ufz-SUMMARY.md
autonomous: true
# Quick task: no REQUIREMENTS.md id is closed. The ids name the two owner-approved items.
requirements: [ufz-1-runbook, ufz-2-child-env]

estimate:
  tokens: 90000
  raw_tokens: 90000
  tasks: 3
  confidence: low   # estimate-calibration: factor 1, sample_count 0

must_haves:
  truths:
    - "RUNBOOK has a new section 21.6 that describes the partial restore after a restart as the code does it (D110): each restorable entry is rebuilt on its own, a bad row is skipped, the healthy plans stay supervised, SAFE_MODE RESTORE_INCONSISTENT; the process stays admitted in SAFE_MODE with RECOVERY degraded and that start never enables entries; ONE cancel request per unrestorable plan by its client order id, with the adapter's existing bounded idempotent STATUS_UNKNOWN retry stated; the five alert reasons (PROTECTION_HANDOFF_FAILED: UNRESTORED_CANCEL_UNVERIFIED / _FAILED / _REFUSED; DIVERGENCE: UNRESTORED_PLAN_POSITION / UNRESTORED_POSITION_UNKNOWN); what the operator checks and does; the system never closes the position"
    - "RUNBOOK has a new section 22.8 on TASK_STALLED (D111): what it means, the alert-only key scheduler.protection_stall_after_ms shipped NOT_CONFIGURED, watchdog off until the owner sets it, observe-only reaction (nothing is cancelled, stopped or re-sent), and the measurement procedure of the mp1 SUMMARY"
    - "Every new RUNBOOK statement is backed by a file:line cited in this plan or by the kxu/mp1 SUMMARYs; no behavior is added that the code does not have"
    - "No existing RUNBOOK heading is renumbered or renamed; every test and gate that pins RUNBOOK stays green; CRLF and LF byte counts are equal before and after in every CRLF file touched"
    - "docs/DOC_STATUS.md gains one dated change-log line for this documentation change; AGENTS.md 'Still open (owner)' names the stall key only if tests/test_agents_md.py and the authority gate stay green (otherwise it is reverted and the reason reported)"
    - "The rclone child of scripts/export_soak_evidence.py receives a whitelisted environment (child_env of src/ops/backup.py, prefixes RCLONE_, the mapped RCLONE_CONFIG_EVIDENCES3_* last): no BINANCE_*, TELEGRAM_*, DATABASE_URL, PG*, EVIDENCE_S3_*, BACKUP_*, GITHUB_*/GH_* or AWS_* name reaches it; PATH, SYSTEMROOT, HOME, USERPROFILE, TEMP, TMP, proxy, SSL_CERT_* and RCLONE_* names do; the explicit mapping wins over a parent RCLONE_* value; existing tests stay green"
    - "uv run ruff check, uv run ruff format --check, uv run mypy src and uv run python scripts/verify_decision_alignment.py all pass; two commits (Task 1, Task 2) with the trailer Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>; owner-modified and untracked files untouched"
  artifacts:
    - path: docs/operations/RUNBOOK.md
      provides: "### 21.6 (partial restore after a restart, D110) and ### 22.8 (TASK_STALLED and the protection stall bound, D111), pointers in 21.1a and 22.2, two open items in 22.7"
      contains: "UNRESTORED_POSITION_UNKNOWN"
    - path: docs/DOC_STATUS.md
      provides: "one 2026-11-14 change-log line naming quick task 261114-ufz"
    - path: scripts/export_soak_evidence.py
      provides: "_run_rclone passes child_env(prefixes=(\"RCLONE_\",), extra=env) to subprocess.run"
      contains: "from src.ops.backup import child_env"
    - path: tests/test_soak_evidence_export.py
      provides: "test that the rclone child gets a whitelisted environment"
  key_links:
    - from: scripts/export_soak_evidence.py::_run_rclone
      to: src/ops/backup.py::child_env
      via: "env= argument of subprocess.run (same call shape as make_rclone_runner, src/ops/backup_remote.py:285)"
    - from: docs/operations/RUNBOOK.md section 21.6
      to: src/live/scheduled_cancel.py::cancel_unrestored_entries
      via: "the five alert reasons and the one-cancel rule described in prose"
    - from: docs/operations/RUNBOOK.md section 22.8
      to: config/execution/execution-limits-v1.toml [scheduler] protection_stall_after_ms
      via: "the key name and its NOT_CONFIGURED state"
---

<objective>
Two owner-approved follow-ups of quick tasks 261114-kxu and 261114-mp1, one commit each, then a gates/SUMMARY step.

1. Document in docs/operations/RUNBOOK.md (sections 21 and 22, existing style and numbering) what D110 and D111 built: the partial restore after a restart (with the one cancel of an unrestorable plan's resting entry and its alerts) and the TASK_STALLED alert with its NOT_CONFIGURED bound key and the measurement procedure. Add the DOC_STATUS change-log line and, if its gates stay green, one AGENTS.md line.
2. Replace the full-environment spread of the rclone child in scripts/export_soak_evidence.py (line 848) with the existing whitelist helper `child_env` of src/ops/backup.py, test-first.

Purpose: the operator has a procedure for the two new behaviors; a parent secret can no longer reach the evidence exporter's rclone child.
Output: RUNBOOK 21.6 and 22.8 (+ pointers), DOC_STATUS line, optional AGENTS.md line, the whitelisted child env and its test, SUMMARY.

Shape: tracer-first does not apply (one documentation task and one single-function fix; no multi-layer slice). Task order follows the owner's numbering; the tasks share no file.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/quick/261114-kxu-harden-review-leads-restore-isolation-li/261114-kxu-SUMMARY.md
@.planning/quick/261114-mp1-follow-ups-to-kxu-cancel-resting-entry-o/261114-mp1-SUMMARY.md

Rules for the executor (from AGENTS.md and the owner brief):
- Run `codegraph explore "<symbol>"` first when locating code (`.codegraph/` exists; the MCP server may be down, the shell form works).
- Never push or merge. Stage explicit paths only. Leave `.planning/STATE.md`, `.planning/config.json`, `.planning/REQUIREMENTS.md`, `.planning/state.json` (owner-modified) and every untracked file alone.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Run only the affected tests named below plus `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv run python scripts/verify_decision_alignment.py all`. No full suite, no `-m demo`, no `--execute` script, no `*_pg.py` file (none is affected). `TEST_DATABASE_URL` is set in this machine's process environment, so the pg-fixture tests inside tests/test_soak_evidence_export.py run; report that.
- Do not edit tests/test_phase20_gate.py (invariant 6 fails before and after for a pre-existing reason, see mp1 SUMMARY Residuals).

CRLF (all five edited files are CRLF in the working tree; `core.autocrlf=true`, index LF). Baselines measured at HEAD 212161cf (CRLF count = LF count): docs/operations/RUNBOOK.md 1162/1162, AGENTS.md 218/218, docs/DOC_STATUS.md 93/93, scripts/export_soak_evidence.py 1265/1265, tests/test_soak_evidence_export.py 1912/1912. Edit bytes-aware: a throwaway helper script in the scratchpad (never in the repo) run with `uv run python`, which reads the file as bytes, asserts each anchor occurs exactly once, inserts the new text with every newline written as CRLF, and writes the bytes back. After each file: print `b.count(b"\r\n")` and `b.count(b"\n")`; they must be equal and the line delta must equal the lines you added.

Grep baselines at HEAD (all recorded): RUNBOOK `^### 21.6 ` 0, `^### 22.8 ` 0, `TASK_STALLED` 0, `UNRESTORED_CANCEL_UNVERIFIED` 0, `scheduler.protection_stall_after_ms` 0; AGENTS.md `scheduler.protection_stall_after_ms` 0; scripts/export_soak_evidence.py non-comment `**os.environ` 1, `child_env(` 0, `from src.ops.backup import child_env` 0.

RUNBOOK pins found (every one must stay green):
- scripts/decision_alignment/ops_risk.py:94-122 (gate OR-01b): the four SAFE_MODE_RUNBOOK_PHRASES must stay somewhere in RUNBOOK; no line may match a SAFE_MODE_RUNBOOK_FORBIDDEN pattern (:100-104, case-insensitive). Write "blocks new entries" style wording only.
- tests/test_soak_runbook.py: sections 19, 20, 20.7, 20.10 bodies and their headings (`^## 19\. `, `^## 20\. `); a DOC_STATUS line dated 2026-11-14 naming D109 (:1062). Do not touch sections 19 and 20.
- tests/test_deploy_docs.py: `_section` / `_subsection` regexes (:51-54, :465-468, :702-705) need `## N. ` / `### N.M ` headings; whole-text rules (:497-498, :501-507 no passwordless sudo keyword, :599-604 secrets rule and no bare compose-config command).
- tests/test_soak_compose.py:595-605: no unguarded compose-down-with-volumes line in a RUNBOOK fence.
- tests/test_phase24_gate.py:722: RUNBOOK must keep naming `src.live.runtime`.
- tests/test_deploy_guide_vi.py:265-273: RUNBOOK is part of a corpus (adding text only widens it).
- tests/test_agents_md.py: AGENTS.md at most 230 lines (now 218); every backticked path under src/, docs/, .planning/, scripts/, deploy/, tests/, config/, params/ must exist.
- scripts/decision_alignment/authority.py AU-01..AU-06: AGENTS.md Quantization bullet and FastAPI row byte-identical; untouched by this plan.
</context>

<!-- The three literals below are deliverables (positive gates: count goes from 0 at HEAD to 1 or 4), not negative greps. -->
<!-- planner-discipline-allow: child_env(prefixes=("RCLONE_",), extra=env) -->
<!-- planner-discipline-allow: from src.ops.backup import child_env -->
<!-- planner-discipline-allow: remote_env -->

<tasks>

<task type="auto">
  <name>Task 1: RUNBOOK 21.6 (partial restore, D110) and 22.8 (TASK_STALLED, D111), DOC_STATUS line, conditional AGENTS.md line</name>
  <files>docs/operations/RUNBOOK.md, docs/DOC_STATUS.md, AGENTS.md</files>
  <read_first>
    - docs/operations/RUNBOOK.md lines 1008-1162 (sections 21 and 22: style is one paragraph per physical line, `Status:` lead line, bold run-in labels, pipe tables, numbered operator steps)
    - docs/DECISIONS.md lines 114-115 (D110, D111 rows)
    - src/live/scheduled_cancel.py lines 255-400; src/live/startup.py lines 447-453, 600-657, 1000-1022, 1078-1091
    - mp1 SUMMARY lines 81-85 (one-cancel rule), 160-167 (design choices), 169-203 (measurement); kxu SUMMARY lines 80-93 (reports a and b)
  </read_first>
  <action>
Implements the documentation of D110 and D111 only; no code, decision row, parameter or test changes. Write English, no emojis, in the RUNBOOK's style. Every statement below carries its source; write nothing that is not on this list. The citations are for you: in the RUNBOOK name modules, functions, codes and decisions (as sections 21 and 22 already do), not line numbers.

A. Insert a new subsection `### 21.6 Partial restore after a restart (D110)` immediately before the line `## 22. Live process (Phase 24)` (after the 21.5 paragraph, one blank line on each side). Content, in this order:

1. Status line: built and tested with fakes (the Binance-semantics fake exchange) by quick tasks 261114-kxu and 261114-mp1, DECISIONS D110; not observed on Binance Demo or on a host; a real cancel answer and the real position read after a restart are owner-run (mp1 SUMMARY line 212).
2. What the restore does: at the RECOVERY step the coordinator rebuilds each restorable ENTRY row (the rows of section 21.1a) on its own (src/live/startup.py:600-657). A fault of one row, that is no persisted plan or constraint snapshot (`RestoreSourceMissing`, :609-612) or a value the rebuild refuses (`ValueError`, `TypeError`, `LookupError`, `ArithmeticError`; `_ROW_FAULTS` :447-453), skips that row; the log line `live.restore.entry_unrestorable` carries only `trade_plan_id`, `approval_id` and the fault class (:641-646). The healthy plans are restored and stay supervised, and the step `COORDINATOR_RESTORED` fails with SAFE_MODE `RESTORE_INCONSISTENT` (src/reconcile/startup.py:323-333). A fault of the store itself (any other exception class) restores nothing and enters SAFE_MODE `DB_FAILURE` with the restore incomplete (src/reconcile/startup.py:334-335; D110 item 1).
3. What the process does next: RECOVERY is not a hold step (src/live/startup.py:182-184), so it degrades (:825-830, :1018-1019): the process is admitted, in SAFE_MODE, with RECOVERY in its degraded steps (:1133, :1145); the stream, the reconcile tick, the bot and the scheduler start, so monitoring continues (kxu SUMMARY line 85); HEALTH and ENABLE are skipped, so that start never enables entries (:1078-1091; entries start disabled at every start, section 22.2). `--hold-on-refusal` does not apply because the start is admitted (kxu SUMMARY line 86). After a partial restore the restore counts as complete, so reconcile ticks run (kxu SUMMARY line 93).
4. The one cancel: for each unrestorable plan, one per distinct plan hash, the start sends ONE cancel request for its resting entry by its deterministic client order id through `expire_pending_entry` with the existing trigger `protection_handoff_failed`, and queries that order once afterwards (src/live/scheduled_cancel.py:255-281 and :346-355; src/execution/manager.py:2550-2571). The audit row is a journal `ENTRY_EXPIRY` row that carries that trigger (manager.py:2560-2570). This code never places, never closes and never sends a second cancel (scheduled_cancel.py:265-266). State plainly, as the mp1 SUMMARY does (lines 83-85): the adapter's `cancel_normal_order` keeps its existing bounded STATUS_UNKNOWN retry (`_cancel_retrying`, src/adapters/binance_usdm.py:918, at most `_RECONCILER_CANCEL_MAX_ATTEMPTS` = 3 attempts, :160-163), and an absent order counts as success, so one request can become a few identical requests on the wire, all idempotent by the client order id. A row whose plan hash equals the hash of a rebuilt plan is never cancelled, because the same id would hit the supervised order (scheduled_cancel.py:342-345).
5. A pipe table `| Alert (severity) | Reason | When |` with exactly these five rows: PROTECTION_HANDOFF_FAILED (CRITICAL, src/ops/alerts.py:111) with `UNRESTORED_CANCEL_UNVERIFIED` (the query after the cancel says still open or unknown, scheduled_cancel.py:366-367), `UNRESTORED_CANCEL_FAILED` (the cancel raised, :360-363), `UNRESTORED_CANCEL_REFUSED` (a symbol outside the live-5 universe or a malformed plan hash, refused before any call, or a plan hash shared with a rebuilt plan; :342-345, :356-359); DIVERGENCE (HIGH, alerts.py:104) with `UNRESTORED_PLAN_POSITION` (the one position read of the symbol shows a non-zero amount, or an amount that is not a Decimal; :394-399) and `UNRESTORED_POSITION_UNKNOWN` (the position read failed, or the symbol is outside the live-5 universe so nothing was read; :386-392). After the table: a cancelled entry, an entry that left the book by itself, or one that filled raises no cancel alert (a fill shows up through the position read, :364-369); a failing alert sink or a failure of the whole cancel step is logged by class name and never stops the start (src/live/startup.py:1011-1017; scheduled_cancel.py:300).
6. What stays the operator's: the unrestorable plan has no stop placed by the coordinator and its order ids are unknown to the stream router, so a fill of it is not protected by the system (kxu SUMMARY line 90; D110 item 2). The system never closes that position and does not decide whose it is (D110 item 5).
7. Numbered operator steps (owner brief; each step is an operator action, not system behavior):
   (1) Read the journal and the log: the `LIVE_STARTUP_STEP` row of RECOVERY (section 22.2), the `live.restore.entry_unrestorable` line (which row, which fault class), the `ENTRY_EXPIRY` rows with trigger `protection_handoff_failed`, and the alerts of the table.
   (2) Check the named symbol by hand on Binance: its position and its open orders. A position there has no stop from the system: protect or close it by hand if it needs it (an order made by hand is a foreign order to the reconcile, section 21.4). An entry that still rests after an `UNRESTORED_CANCEL_*` alert: cancel it by hand.
   (3) Fix the database row the log names (by `trade_plan_id` and `approval_id`): `RestoreSourceMissing` means its persisted plan or constraint snapshot is missing; the other classes mean a value the rebuild refuses. The repository has no tool for this: it is a manual correction in the database. Until it is fixed, every start repeats the partial restore, because the cancel does not rewrite the intent row (mp1 SUMMARY line 165) and the restore reads the same rows (section 21.1a), and every such start sends its own one cancel request (src/live/startup.py:1011-1015).
   (4) Restart the process (commands in section 21.1c; read section 22.5 on what a stop leaves resting).
   (5) Leave SAFE_MODE only through section 21.1 (`/safemode_exit` and `/confirm`, section 21.1a); its readiness rows decide.
   For a `DB_FAILURE` restore, fix the database or its connection first, then restart.
8. Last sentence: a single wire request for this cancel (bypassing the adapter retry) would be an adapter change with its own decision; not done (mp1 SUMMARY line 210).

B. Pointers (append one sentence each, same line, keep the line's CRLF): at the end of the 21.1a paragraph that starts "After a restart the coordinator is rebuilt from the intent rows" add "A row that cannot be rebuilt: section 21.6."; at the end of the 22.2 paragraph that starts "Each step is journaled as `LIVE_STARTUP_STEP`" add "A RECOVERY step that restores only part of the plans: section 21.6."

C. In 22.7, after the existing last bullet (R-26), add two bullets: the value of `scheduler.protection_stall_after_ms` is the owner's (shipped `NOT_CONFIGURED`, the stall watchdog is off; section 22.8, D111); a literal single wire request for the restart cancel needs an adapter change and its own decision (section 21.6).

D. Append at the end of the file a new subsection `### 22.8 TASK_STALLED and the protection stall bound (D111)`. Content, in this order:

1. Status line: built and tested with fakes by quick tasks 261114-kxu (watchdog) and 261114-mp1 (alert and key), DECISIONS D111; the shipped limits leave it off; nothing observed on Demo or a host.
2. Meaning: the scheduler runs the protection task `protection_step` (src/live/wiring.py:178, :1112-1118). When that task has a stall bound, a watchdog starts beside each run (src/live/scheduler.py:189-190); if the run is still going after the bound, it logs one error line naming the task and the bound in seconds (:209-212) and records one stall event for that run (:213-220). `LiveWiring._record_task` journals it as a `LIVE_TASK_EVENT` row (correlation `live_scheduler`, entity `protection_step`, payload `task`, `kind`, `error_class`; src/live/wiring_parts.py:53, :226; mp1 SUMMARY line 171) and then raises the HIGH alert `TASK_STALLED` whose header subject is the task name and whose reason is `STALL_BOUND_EXCEEDED`, also when the journal write failed (src/live/wiring.py:1028-1034; wiring_parts.py:56, :256-275; src/ops/alerts.py:129). Only the protection task has a bound (wiring.py:1117).
3. Observe only: the run is never cancelled, cut short, stopped or restarted, nothing is cancelled and nothing is re-sent (scheduler.py:191-198, :202-207; src/ops/alert_wording.py:427-429; D111 item 4).
4. The key: `scheduler.protection_stall_after_ms` in section `[scheduler]` of `config/execution/execution-limits-v1.toml` ships `NOT_CONFIGURED` for its value and its provenance (toml :22, :76-77). It is alert-only (src/execution/execution_limits.py:126-127): unlike a required key (section 22.1), unset it never refuses the start (:296-303); the watchdog is off, no stall row is written and no TASK_STALLED is raised (scheduler.py:286-307; wiring.py:1117). It stays off until the owner sets a value with its own DECISIONS row and the provenance `DECISION` (D111 item 5). An integer value needs STRUCTURAL, COST_GUARD, DECISION or EXPERIMENT; PLACEHOLDER refuses to load (execution_limits.py:39, :141, :362-367). To fire before the unprotected deadline it must stay below `protection.max_unprotected_ms` (D111 item 5). Limits are baked into the image (section 22.4, D106), so a set value is a rebuilt and re-pinned image.
5. How to react (the alert's own operator line, alert_wording.py:431-435): check the process log and the exchange position and its stop now; close or protect the position by hand if it needs it; restart the process only if the task does not finish (a restart never leaves SAFE_MODE, section 21.1; a stop leaves resting entries, section 22.5). Repeated stalls inside `alerts.dedupe_window_ms` are suppressed in Telegram and journaled as `ALERT_SUPPRESSED`, while every stall keeps its `LIVE_TASK_EVENT` row (mp1 SUMMARY line 200; src/ops/alerts.py:430, :514).
6. A run-in label "Measuring a bound (owner; no value is chosen here)." then, from mp1 SUMMARY lines 171-203: the journal holds no per-run duration (`protection_step` rows exist only for `first_run`, `failure`, `recovery` and, with a bound set, `stall`); read-only query 1 (the stall rows) and read-only query 2 (the protection transitions), copied verbatim from mp1 SUMMARY lines 176-184 and 187-193 into two `sql` fenced blocks (SQL only: no connection string, URL, user or password anywhere); the query-2 reading (per plan, the time from the transition to `UNPROTECTED` to the transition to `PROTECTED_ENTRY_OPEN` or `PROTECTED`; a lower bound only, and only when both rows come from the same run, because a gap across two runs includes the wait between runs and a fill also wakes the task); then the direct method as five numbered steps, owner-run on Demo only and never by an agent: no command-line flag selects the limits file (`default_limits_path`, src/live/config.py:128), so the owner edits the Demo host's copy for the measurement only (an image or checkout used only for that run) and never commits it; sets a trial bound with provenance EXPERIMENT; runs Demo sessions that exercise the protection step (fills, stop placement, restarts, take-profit attach) and counts the stall rows per trial bound, lowering it until the first stall rows appear; adopts the observed maximum plus a margin the owner chooses, below `protection.max_unprotected_ms`; records it with a DECISIONS row and provenance DECISION. End with: a per-run duration record would make this direct but needs a new decision; not built.

E. docs/DOC_STATUS.md: append one change-log line at the end of the file, after the D111 line, in its style: "- 2026-11-14 — quick task 261114-ufz (documentation of what quick tasks 261114-kxu and 261114-mp1 built; no decision changed, D110 and D111 unchanged): `operations/RUNBOOK.md` (new 21.6 partial restore after a restart, new 22.8 TASK_STALLED and the protection stall bound, pointers in 21.1a and 22.2, two open items in 22.7)" then, only if step F is kept, "and `AGENTS.md` (the stall key under 'Still open (owner)')", then ". No other canonical document changed."

F. AGENTS.md (conditional): in the bullet "Still open (owner)" insert one line after the line that ends with "`config/execution/execution-limits-v1.toml`;" reading: two spaces, then "the alert-only `NOT_CONFIGURED` key `scheduler.protection_stall_after_ms` (D111, RUNBOOK 22.8);". Then run `uv run pytest tests/test_agents_md.py -q` and `uv run python scripts/verify_decision_alignment.py all`. If either fails because of this line, restore AGENTS.md byte-for-byte (`git checkout -- AGENTS.md`), drop the AGENTS.md clause from the DOC_STATUS line, and record the exact failure in the SUMMARY.

Then run the verify command, check the CRLF counts of the three files, and commit only docs/operations/RUNBOOK.md, docs/DOC_STATUS.md and (if kept) AGENTS.md by explicit path with the message `docs(quick-261114-ufz): RUNBOOK for the partial restore after a restart and TASK_STALLED` and the Sonnet trailer.
  </action>
  <verify>
    <automated>uv run pytest tests/test_soak_runbook.py tests/test_deploy_docs.py tests/test_decision_alignment_ops_risk.py tests/test_decision_alignment_bookkeeping.py tests/test_agents_md.py tests/test_phase24_gate.py tests/test_soak_compose.py tests/test_deploy_guide_vi.py -m "not docker" -n 4 -q && uv run python scripts/verify_decision_alignment.py all</automated>
  </verify>
  <done>Verify set passes and the gate prints ALL_PASS. Greps (baselines 0): `grep -c "^### 21.6 Partial restore after a restart" docs/operations/RUNBOOK.md` = 1; `grep -c "^### 22.8 TASK_STALLED" docs/operations/RUNBOOK.md` = 1; in RUNBOOK each of `UNRESTORED_CANCEL_UNVERIFIED`, `UNRESTORED_CANCEL_FAILED`, `UNRESTORED_CANCEL_REFUSED`, `UNRESTORED_PLAN_POSITION`, `UNRESTORED_POSITION_UNKNOWN`, `scheduler.protection_stall_after_ms`, `_cancel_retrying` counts at least 1; `grep -c "section 21.6" docs/operations/RUNBOOK.md` at least 3; `grep -c "261114-ufz" docs/DOC_STATUS.md` = 1; the list of `^## ` and `^### ` headings that existed before is unchanged (compare `grep -n "^##" ` output minus the two new lines). CRLF count = LF count in RUNBOOK (1162 + added lines), DOC_STATUS (94) and AGENTS.md (219 if kept, 218 if reverted). One commit holding only these paths.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: whitelisted environment for the rclone child of scripts/export_soak_evidence.py</name>
  <files>tests/test_soak_evidence_export.py, scripts/export_soak_evidence.py</files>
  <read_first>
    - scripts/export_soak_evidence.py lines 121-150 (imports: `sys.path` insert, then `from src.ops import evidence_remote  # noqa: E402`), 835-921 (`_run_rclone`, `RcloneUploader`, `_publisher`), 943-1008 (`RcloneWitnessReader`)
    - src/ops/backup.py lines 910-969 (`_CHILD_ENV_NAMES`, `child_env(*, prefixes, extra, environ)`; environ defaults to os.environ read at call time; extra applied last)
    - src/ops/backup_remote.py:276-290 (`make_rclone_runner` uses `child_env(prefixes=("RCLONE_",), extra=...)`: the shape to copy)
    - src/ops/evidence_remote.py:111-125 (`rclone_env`: the RCLONE_CONFIG_EVIDENCES3_* mapping)
    - tests/test_soak_evidence_export.py lines 1430-1440 (SECRET_KEY, ACCESS_ID, EVIDENCE_ENV) and 1806-1848 (`test_publish_reaches_rclone_through_the_environment_only`, which monkeypatches `export._run_rclone` with the signature `(argv, stdin, env)`: keep that signature)
  </read_first>
  <behavior>
    - Calling `export._run_rclone(["lsf", "EVIDENCES3:b/p"], None, mapped)` with `subprocess.run` monkeypatched hands `subprocess.run` an `env` dict that holds none of: BINANCE_DEMO_API_SECRET, BINANCE_LIVE_API_KEY, TELEGRAM_LIVE_BOT_TOKEN, DATABASE_URL, PGPASSWORD, EVIDENCE_S3_SECRET_ACCESS_KEY, BACKUP_S3_SECRET_ACCESS_KEY, GITHUB_TOKEN, AWS_SECRET_ACCESS_KEY (all set in the parent by monkeypatch.setenv), and no key starting with BINANCE_, TELEGRAM_, EVIDENCE_S3_, BACKUP_, PG, GITHUB_, GH_ or AWS_, and no DATABASE_URL
    - The same env holds PATH, SYSTEMROOT, HOME, USERPROFILE, TEMP, TMP, HTTPS_PROXY, SSL_CERT_FILE and RCLONE_VERBOSE with the parent's values (all set by monkeypatch.setenv, so the test is platform independent)
    - Every key of `mapped` is present with its value, and a parent RCLONE_CONFIG_EVIDENCES3_SECRET_ACCESS_KEY set to a different value loses to the mapping
    - argv[0] is the parent's RCLONE_BIN when set (unchanged behavior); nothing is printed to stdout or stderr (capsys)
  </behavior>
  <action>
Determination of what the child needs (from code, recorded for the SUMMARY): the only child process the exporter starts is rclone (`subprocess.run` at scripts/export_soak_evidence.py:845; no other subprocess, Popen or os.system use in that script, in scripts/evaluate_trial_soak.py or in src/ops/evidence_remote.py; the script never calls `gh`, so no GitHub token is needed). rclone gets its remote only from the `env` mapping `RCLONE_CONFIG_EVIDENCES3_*` (evidence_remote.py:111-125), optional operator tuning from `RCLONE_*` names, and OS basics (PATH, SYSTEMROOT/WINDIR, HOME/USERPROFILE/APPDATA for its config lookup, TEMP/TMP/TMPDIR, proxy and SSL_CERT_* names), all of which are already in `_CHILD_ENV_NAMES` (src/ops/backup.py:910-943). It reads no PostgreSQL name and no DATABASE_URL. So the call is `child_env(prefixes=("RCLONE_",), extra=env)`, the same shape as `make_rclone_runner` (src/ops/backup_remote.py:285). Reuse is appropriate: `child_env` is public, already imported across modules by src/ops/backup_remote.py, and the script already loads src/ops/backup.py transitively (evidence_remote imports backup_remote, which imports backup), so no new import cost.

RED: add `import subprocess` to the test module's stdlib imports and a test named `test_the_rclone_child_gets_a_whitelisted_environment_never_the_whole_parent` after `test_publish_reaches_rclone_through_the_environment_only`, implementing the behavior block: monkeypatch.setenv for every listed name, monkeypatch.setattr(export.subprocess, "run", fake) where the fake records its positional args and its `env` keyword and returns `subprocess.CompletedProcess(args, 0, b"", b"")`; the mapping holds RCLONE_CONFIG_EVIDENCES3_TYPE "s3" and RCLONE_CONFIG_EVIDENCES3_SECRET_ACCESS_KEY = SECRET_KEY. Use obviously fake values (no real-looking secret). Run it: it must FAIL at HEAD (the unrelated BINANCE_* name reaches the child). Record the failing assertion line for the SUMMARY.

GREEN, in scripts/export_soak_evidence.py:
1. Add `from src.ops.backup import child_env  # noqa: E402` to the first-party import block, sorted where ruff's isort puts it (between `from src.ops import evidence_remote` and `from src.ops.redaction import ...`).
2. In `_run_rclone`, replace the full-environment spread of the `env=` argument (line 848) with `child_env(prefixes=("RCLONE_",), extra=env)`. Keep reading `RCLONE_BIN` from the process environment as now, keep the signature `(argv, stdin, env)` and every error message unchanged. Update its docstring in one sentence: rclone gets a whitelisted environment (`child_env` of src/ops/backup.py: the base OS names, every `RCLONE_*` name, then `env`), never the whole parent environment; the credentials reach it through `env` only, never argv. Do not quote the old spread expression in any docstring or comment.
3. Rename the local variable named `child_env` in `RcloneUploader.__init__` (lines 878 and 882) and in `RcloneWitnessReader.__init__` (lines 957 and 961) to `remote_env`, so no local shadows the imported function.
4. In the module docstring sentence "They are mapped to `RCLONE_CONFIG_EVIDENCES3_*` in the rclone child process only, ..." (lines 49-50) add: the rclone child gets a whitelisted environment, never the whole parent environment. Keep every other line of the docstring as it is.
No value of any variable is logged, printed or put in an exception text.

Run the verify command, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`; check CRLF counts of both files; commit only these two paths: `fix(quick-261114-ufz): whitelist the environment of the evidence exporter's rclone child` with the Sonnet trailer.
  </action>
  <verify>
    <automated>uv run pytest tests/test_soak_evidence_export.py tests/test_evidence_remote.py tests/test_soak_runbook.py -m "not docker" -n 4 -q</automated>
  </verify>
  <done>New test failed at HEAD (BINANCE_* reached the child) and passes after; every existing test of the three files passes (report the pg-fixture tests as run because TEST_DATABASE_URL is set). Greps: `grep -v '^\s*#' scripts/export_soak_evidence.py | grep -c '\*\*os.environ'` = 0 (baseline 1); `grep -c 'child_env(prefixes=("RCLONE_",), extra=env)' scripts/export_soak_evidence.py` = 1 (baseline 0); `grep -c "from src.ops.backup import child_env" scripts/export_soak_evidence.py` = 1 (baseline 0); `grep -c "remote_env" scripts/export_soak_evidence.py` = 4. CRLF count = LF count in both files. One commit holding only these two paths.</done>
</task>

<task type="auto">
  <name>Task 3: final gates and SUMMARY (no commit)</name>
  <files>.planning/quick/261114-ufz-runbook-for-partial-restore-and-task-sta/261114-ufz-SUMMARY.md</files>
  <read_first>
    - .planning/quick/261114-mp1-follow-ups-to-kxu-cancel-resting-entry-o/261114-mp1-SUMMARY.md (frontmatter and section layout to mirror)
  </read_first>
  <action>
Run once, after the second commit: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv run python scripts/verify_decision_alignment.py all`, and the union of the two verify sets in one command with `-m "not docker" -n 4`. Then write the SUMMARY in the mp1 layout: frontmatter (phase quick-261114-ufz, plan 01, commits 2, plan_head_before 212161cf, plan_head_after, actuals measured with git), commit table, per task what changed, the RED output of Task 2, gate results, the child-env determination (Task 2 action first paragraph), whether the AGENTS.md line was kept (and the failure text if not), CRLF counts before and after per file, what was not run (full suite, docker, `-m demo`, `--execute`, `*_pg.py`), the pre-existing tests/test_phase20_gate.py invariant 6 failure (not run, not edited), Self-Check (commits are ancestors of HEAD; owner-modified files still unstaged; untracked files untouched; `git status` shows nothing staged). Do not commit the SUMMARY or this PLAN: the orchestrator commits them.
  </action>
  <verify>
    <automated>uv run ruff check && uv run ruff format --check && uv run mypy src && uv run python scripts/verify_decision_alignment.py all</automated>
  </verify>
  <done>All four gates pass; the union test run passes; the SUMMARY exists with the sections listed; `git rev-list --count 212161cf..HEAD` = 2; `git status` shows no staged change and the four owner-modified files still modified and unstaged.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| exporter process -> rclone child | the parent environment may hold Binance, Telegram, database and backup secrets; the child needs only its remote mapping and OS basics |
| repository docs -> operator | the RUNBOOK tells the operator what to do on a live host; a wrong statement leads to a wrong manual action |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-ufz-01 | Information disclosure | scripts/export_soak_evidence.py `_run_rclone` | high | mitigate | `child_env(prefixes=("RCLONE_",), extra=env)` whitelist; the new test sets BINANCE_*, TELEGRAM_*, DATABASE_URL, PG*, EVIDENCE_S3_*, BACKUP_*, GITHUB_*, AWS_* in the parent and asserts none reaches the child; no value is logged |
| T-ufz-02 | Denial of service | rclone child after the whitelist | low | accept | the whitelist keeps PATH, SYSTEMROOT, HOME/USERPROFILE/APPDATA, TEMP/TMP/TMPDIR, proxy and SSL_CERT_* names and every RCLONE_* name (same set the backup rclone runner uses since kxu); a host-specific library path would be dropped, none is configured in this repository (kxu SUMMARY Task 3) |
| T-ufz-03 | Tampering (wrong procedure) | RUNBOOK 21.6 / 22.8 | medium | mitigate | every statement is tied to a file:line in this plan or to the kxu/mp1 SUMMARYs; the text says the system never closes, never re-sends, and that the watchdog only observes; operator steps are labelled as operator actions |
| T-ufz-04 | Information disclosure | RUNBOOK SQL blocks and examples | medium | mitigate | SQL only, no connection string, URL, user, password or key; test_deploy_docs secrets rule and the AGENTS.md secrets rule respected |
| T-ufz-SC | Tampering | npm/pip/cargo installs | high | accept | no package is installed or added by this plan (no `uv add`, `uv.lock` unchanged) |
</threat_model>

<verification>
- Task 1 verify set and the decision-alignment gate pass; RUNBOOK headings unchanged except the two new ones; CRLF preserved.
- Task 2 RED recorded, GREEN passes; the full-environment spread is gone from non-comment lines.
- Final gates (ruff check, ruff format --check, mypy src, decision alignment) pass once after both commits.
</verification>

<success_criteria>
- An operator can follow RUNBOOK 21.6 after a restart that logged `live.restore.entry_unrestorable` and RUNBOOK 22.8 after a TASK_STALLED alert, and every statement there matches the code.
- The evidence exporter's rclone child no longer inherits unrelated parent secrets.
- Two atomic commits with the Sonnet trailer; nothing pushed; owner files untouched.
</success_criteria>

<output>
Create `.planning/quick/261114-ufz-runbook-for-partial-restore-and-task-sta/261114-ufz-SUMMARY.md` when done (not committed by the executor).
</output>
