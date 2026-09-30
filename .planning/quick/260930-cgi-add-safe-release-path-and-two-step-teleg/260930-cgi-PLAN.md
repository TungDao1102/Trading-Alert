---
phase: quick-260930-cgi
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/DECISIONS.md
  - .planning/ROADMAP.md
  - .planning/phases/25-go-live-readiness-gate/.gitkeep
  - .planning/phases/26-configurable-quote-asset/.gitkeep
  - .planning/phases/25-demo-integration-test-campaign/.gitkeep
  - .planning/phases/26-go-live-readiness-gate/.gitkeep
  - .planning/phases/27-configurable-quote-asset/.gitkeep
  - .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-apply.cjs
  - .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs
autonomous: true
requirements:
  - QUICK-260930-cgi

estimate:
  tokens: 30000
  raw_tokens: 30000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "docs/DECISIONS.md gains exactly 2 lines and loses 0 versus 6a0d4aa: the INPUT Part A rows D040 (safe release path SHADOW → DEMO → CANARY → LIVE) and D041 (two-step Telegram APPROVE → CONFIRM), copied verbatim from the INPUT fence and placed directly after D039. Each row has 4 cells and no '|' inside a cell. The file keeps CRLF line endings, and its CR-stripped SHA-256 is 01e6868107de34f177141b858304d10dff5b7edcf187572f47c5ed0c062094b4"
    - ".planning/ROADMAP.md carries INPUT edits B1–B7: the overview says old 17 → 27 and that live enablement (26) follows the D040 release path; the Phase 16 and 23 list lines, headings, goals, new criteria (16: 5 and 6 for SHADOW, per D040/D041; 23: 4 for two-step confirm, per D041) and Audit refs are updated; the two Phase 24 bullets gain CONFIRM; the old 25/26 sections are replaced by the three INPUT sections 25 (Binance Demo Integration Test Campaign), 26 (Go-Live Readiness Gate) and 27 (Configurable Quote Asset); the execution-order line and progress rows are updated. The CR-stripped SHA-256 is 93b187ae4b1b1023ecaf8f913e906da067b803c4d1cd68f0326f5186d64688e7"
    - "Relative to 6a0d4aa, no git diff hunk of .planning/ROADMAP.md touches a line that belongs to Phases 1–15, 17–22 or 07.1 (detail sections, phase-list lines, progress rows)"
    - "gsd-tools roadmap.analyze reports 28 phases. Phase 25 is 'Binance Demo Integration Test Campaign' (depends on Phase 24), 26 is 'Go-Live Readiness Gate' (depends on Phase 25) and 27 is 'Configurable Quote Asset (USDC readiness)' (depends on Phase 26), each with the INPUT goal. Lines containing D041 >= 4 and lines containing D040 >= 5"
    - "find-phase 25, 26 and 27 resolve to 25-demo-integration-test-campaign, 26-go-live-readiness-gate and 27-configurable-quote-asset. Each holds an empty tracked .gitkeep, and exactly one directory exists per number 25–27"
    - "Three commits with the pinned subjects exist since 6a0d4aa. Each stages explicit paths only, touches only DECISIONS.md, ROADMAP.md, phase 25–27 .gitkeep files or the two 260930-cgi helper scripts, and ends with the Co-Authored-By trailer. .planning/state.json, .gsd/ and .planning/STATE.md are never staged"
  artifacts:
    - path: "docs/DECISIONS.md"
      provides: "Decision rows D040 (safe release path) and D041 (two-step Telegram confirm)"
      contains: "| D041 | Two-step Telegram confirmation."
    - path: ".planning/ROADMAP.md"
      provides: "New Phase 25 demo campaign, renumbered 26/27, SHADOW mode in Phase 16, two-step confirm in Phase 23"
      contains: "### Phase 25: Binance Demo Integration Test Campaign"
    - path: ".planning/phases/25-demo-integration-test-campaign/.gitkeep"
      provides: "Phase 25 directory resolvable by gsd-tools find-phase"
    - path: ".planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-apply.cjs"
      provides: "Anchor-exact, CRLF-preserving application of INPUT Part A and Part B (fenced text read from INPUT.md; refuses a second run)"
    - path: ".planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs"
      provides: "Read-only gates: decisions, roadmap, dirs, git, all (prints ALL_PASS <mode>)"
  key_links:
    - from: ".planning/ROADMAP.md Phase 16/23/25/26 text (D040, D041 citations)"
      to: "docs/DECISIONS.md rows D040 and D041"
      via: "Decision IDs cited in goals, criteria and Audit refs resolve to the new DECISIONS rows"
      pattern: "D04[01]"
    - from: ".planning/ROADMAP.md headings ### Phase 25 / 26 / 27"
      to: ".planning/phases/25-demo-integration-test-campaign, 26-go-live-readiness-gate, 27-configurable-quote-asset"
      via: "gsd-tools find-phase NN resolves the number prefix to exactly one directory"
      pattern: "^### Phase 2[567]: "
---

<objective>
Record the two user decisions of 2026-09-30 and fold them into the roadmap, exactly as INPUT.md specifies:
- D040: safe release path SHADOW → DEMO → CANARY → LIVE.
- D041: two-step Telegram confirmation (APPROVE → CONFIRM card).

Concretely:
- Append the D040/D041 rows to docs/DECISIONS.md (INPUT Part A).
- Apply ROADMAP edits B1–B7 (INPUT Part B). This inserts a new Phase 25 "Binance Demo Integration Test Campaign" and renumbers the old 25 → 26 and 26 → 27. It also adds SHADOW approval mode (D040) to Phase 16, the two-step confirm (D041) to Phase 23, and CONFIRM to the Phase 24 wiring.
- Remap the phase directories (INPUT Part C).

Purpose: the user wants the system proven bug-free on the Binance sandbox before any real-money order, an approve-without-real-order history recorded early (SHADOW), and a mis-tapped APPROVE that can never place an order. The roadmap must say so before anyone plans Phases 16, 23, 25 or 26.

Output: 2 new DECISIONS rows, a ROADMAP.md with 28 phases (1–15, 17–22 and 07.1 untouched), phase directories 25–27, and three scoped commits.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-INPUT.md

Paths used below:
- QUICK = .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg
- BASE = 6a0d4aa (HEAD at planning time; docs/DECISIONS.md and .planning/ROADMAP.md are unchanged since then)

Every command assumes cwd = repository root (C:/Users/admin/Music/Trading) in the Bash tool (Git Bash).

Facts observed at planning time (2026-09-30, HEAD 6a0d4aa):
- Both target files are stored LF in the index and checked out CRLF (global core.autocrlf=true).
  - docs/DECISIONS.md has 44 lines, and D039 is its last row.
  - .planning/ROADMAP.md has 818 lines.
  - git add prints "LF will be replaced by CRLF" warnings for the new .cjs files. These are expected and harmless.
- .planning/phases/25-go-live-readiness-gate and .planning/phases/26-configurable-quote-asset each hold only a tracked, empty .gitkeep.
- No tracked file outside ROADMAP.md, the audits and the quick directories refers to "Phase 25"/"Phase 26". STATE.md only mentions the historical "phases 11-26" task description. So the renumbering leaves no stale references.
- Two helper scripts already exist in QUICK. The planner wrote them and rehearsed them in a throwaway detached worktree (since removed), running the full flow of this plan: all three tasks gave 73 PASS gates and ALL_PASS all. Deliberate tampering was also rehearsed, and the gates failed as intended: a Phase 17 goal edit, a Phase 07.1 line edit and an extra DECISIONS line.
  - 260930-cgi-apply.cjs, modes `decisions` and `roadmap`, plus `--dry-run`. It reads every fenced block verbatim from INPUT.md (Part A, B2, B3, B4, B6, B7), and it asserts at runtime that each short inline replacement occurs verbatim between backticks in INPUT.md. For B5, INPUT writes the literal backticks around execute_approved_plan as \`; the script handles this. Every anchor must match exactly one line and must sit inside the right phase section. The script preserves CRLF. A second run exits 1 with APPLY_FAILED and writes nothing.
  - 260930-cgi-verify.cjs is read-only, with modes decisions | roadmap | dirs | git | all. It pins the CR-stripped SHA-256 of both results and the three commit subjects used below.
  Do not modify either script or INPUT.md. If a gate fails, fix the repo state, never the gate.
- .planning/state.json carries a pre-existing unrelated modification, and .gsd/ is untracked. Never stage either one, and never stage .planning/STATE.md (the orchestrator owns it). Never use git add -A, git add . or git commit -a.
- Do not edit src/, tests/, params/, .planning/REQUIREMENTS.md, .planning/STATE.md or any other docs/ file in this task.
- TDD does not apply (documentation and planning-structure work with pre-written gates; tdd_mode exempts documentation). The capability hooks were checked:
  - The API-coverage detector ran on INPUT.md and returned detected=false; the task integrates no external API.
  - Assumption-delta does not apply: this is a quick task, not a roadmap phase scope.
  - Schema push does not apply: there are no ORM schema files.
</context>

<tasks>

<task type="tracer">
  <name>Task 1: Tracer - D040/D041 rows into docs/DECISIONS.md end-to-end (apply script, gate, scoped commit)</name>
  <files>docs/DECISIONS.md, .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs (commit only; it already exists)</files>
  <precondition>QUICK contains 260930-cgi-INPUT.md, 260930-cgi-apply.cjs and 260930-cgi-verify.cjs, and `git diff --quiet 6a0d4aa -- docs/DECISIONS.md .planning/ROADMAP.md` exits 0. If either check fails, halt and report; do not recreate or patch anything.</precondition>
  <read_first>.planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-INPUT.md (Part A only; the script copies the rows, so do not re-type them)</read_first>
  <action>This task proves the whole path end to end on the smallest artifact: the rows are read verbatim from the INPUT fence, CRLF is preserved, the result passes the gate, and the commit stages explicit paths only. Implements INPUT Part A (D040 per the user's safe-release-path decision, D041 per the two-step-confirm decision).

1. Run `node .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-apply.cjs decisions --dry-run`. Expect DRY_RUN_OK decisions lines=47 eol=CRLF.

2. Run the same command without --dry-run, once. Expect APPLIED decisions lines=47 eol=CRLF.
   - If APPLY_FAILED appears, stop and report the message. Never add the rows by hand or with the Edit tool.

3. Run the decisions gate (see verify). It checks:
   - the pinned digest;
   - `git diff --numstat 6a0d4aa` = 2 added, 0 deleted;
   - the file equals the BASE content with the INPUT Part A rows inserted directly after D039;
   - each row has 4 cells and no "|" inside a cell;
   - both rows are "Accepted (2026-09-30, user)".
   On a FAIL, restore with `git checkout -- docs/DECISIONS.md` and re-run step 2.

4. Commit with explicit paths only:
   - `git add docs/DECISIONS.md .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs`
   - Confirm `git diff --cached --name-only` prints exactly those 2 paths.
   - `git commit -m "docs(quick-260930-cgi): record D040 safe release path and D041 two-step Telegram confirm" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`
   - The subject is pinned in the git gate, so use it exactly.</action>
  <verify>
    <automated>node .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs decisions</automated>
  </verify>
  <done>The gate prints ALL_PASS decisions (6 PASS lines). docs/DECISIONS.md has D040 and D041 as its last two rows, verbatim from INPUT Part A, with CRLF kept. The HEAD commit contains only docs/DECISIONS.md and 260930-cgi-verify.cjs and ends with the trailer. .planning/state.json is still an unstaged local modification.</done>
</task>

<task type="auto">
  <name>Task 2: Apply ROADMAP edits B1–B7 with the anchor-exact script</name>
  <files>.planning/ROADMAP.md, .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-apply.cjs (commit only; it already exists)</files>
  <precondition>`git diff --quiet 6a0d4aa -- .planning/ROADMAP.md` exits 0. If not, halt and report, because the pinned digest assumes that base.</precondition>
  <read_first>.planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-INPUT.md (Part B, to sanity-check the result; the script copies all text, so do not re-type any of it)</read_first>
  <action>Apply INPUT Part B only through the apply script. This inserts Phase 25 (DEMO stage of D040), renumbers the old 25 → 26 (CANARY per D040) and 26 → 27, adds SHADOW mode (D040) plus confirm (D041) to Phase 16, adds the two-step confirm (D041) to Phase 23, and adds CONFIRM to Phase 24. Never hand-edit ROADMAP.md, never re-type block text, and do not use gsd roadmap subcommands for this change.

1. Run `node .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-apply.cjs roadmap --dry-run`. Expect DRY_RUN_OK roadmap lines=861 eol=CRLF.

2. Run the same command without --dry-run, once. Expect APPLIED roadmap lines=861 eol=CRLF.
   - A second run exits 1 with APPLY_FAILED by design and changes nothing.
   - If APPLY_FAILED appears on the first run, stop and report. Do not patch anchors, INPUT.md or ROADMAP.md.

3. What the script does, so you can sanity-check `git diff .planning/ROADMAP.md`:
   - B1: overview lines "old 17 → 27", "Live enablement (26) … D040 release path …", and "Phases 11–27 below".
   - B2: new list lines for 16 and 23, and the old list lines 25/26 replaced by the 3 fenced lines 25/26/27.
   - B3: Phase 16 heading and goal; criteria 5–6 inserted after criterion 4; ", D040, D041" appended to its Audit refs.
   - B4: Phase 23 heading and goal; criterion 4 inserted after criterion 3; ", D041" appended to its Audit refs.
   - B5: the two Phase 24 bullets gain CONFIRM.
   - B6: everything from the old "### Phase 25" heading up to "## Progress" replaced by the three fenced sections.
   - B7: execution-order line changes; progress rows 16/23 renamed; rows 25/26 replaced by the 3 fenced rows.

4. Run the roadmap gate. It checks:
   - the pinned digest;
   - that no `git diff -U0 6a0d4aa` hunk touches a line of Phases 1–15, 17–22 or 07.1;
   - that every INPUT fence is present verbatim;
   - that each new inline line appears exactly once;
   - that the stale text is gone;
   - the D041 (>= 4) and D040 (>= 5) line counts;
   - 28 "### Phase" headings;
   - gsd-tools roadmap.analyze: 28 phases, and phases 25/26/27 with the INPUT names, goals and depends_on 24/25/26.
   On a FAIL, restore with `git checkout -- .planning/ROADMAP.md`, read the FAIL line and re-run step 2. Never edit ROADMAP.md by hand to make a gate pass.

5. Commit with explicit paths only:
   - `git add .planning/ROADMAP.md .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-apply.cjs`
   - Confirm `git diff --cached --name-only` prints exactly those 2 paths.
   - `git commit -m "docs(quick-260930-cgi): insert Phase 25 demo campaign and renumber phases 26-27 in ROADMAP" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"` (pinned subject).</action>
  <verify>
    <automated>node .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs roadmap</automated>
  </verify>
  <done>The gate prints ALL_PASS roadmap (39 PASS lines in the rehearsal):
- The CR-stripped SHA-256 is 93b187ae4b1b1023ecaf8f913e906da067b803c4d1cd68f0326f5186d64688e7.
- No hunk touches Phases 1–15, 17–22 or 07.1.
- roadmap.analyze reports 28 phases with 25 → Phase 24, 26 → Phase 25 and 27 → Phase 26.
The HEAD commit contains only .planning/ROADMAP.md and 260930-cgi-apply.cjs and ends with the trailer.</done>
</task>

<task type="auto">
  <name>Task 3: Remap phase directories 25–27 and run the full gate</name>
  <files>.planning/phases/25-go-live-readiness-gate/.gitkeep, .planning/phases/26-configurable-quote-asset/.gitkeep, .planning/phases/25-demo-integration-test-campaign/.gitkeep, .planning/phases/26-go-live-readiness-gate/.gitkeep, .planning/phases/27-configurable-quote-asset/.gitkeep</files>
  <read_first>.planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-INPUT.md (Part C)</read_first>
  <action>Apply INPUT Part C exactly, in this order, from the repo root. The order matters: 26 must move out before 25 can take its number.

1. `git mv .planning/phases/26-configurable-quote-asset .planning/phases/27-configurable-quote-asset` (FIRST, per INPUT).

2. `git mv .planning/phases/25-go-live-readiness-gate .planning/phases/26-go-live-readiness-gate`

3. Create the new phase-25 directory and stage it:
   - `mkdir -p .planning/phases/25-demo-integration-test-campaign`
   - Create an empty .gitkeep with `: > .planning/phases/25-demo-integration-test-campaign/.gitkeep`. It must be 0 bytes.
   - `git add .planning/phases/25-demo-integration-test-campaign/.gitkeep`

4. Run the dirs gate. It checks:
   - one directory per number 25–27;
   - an empty .gitkeep in each;
   - that both old directories are gone;
   - that find-phase 25/26/27 resolve to the new directories.
   On a FAIL, fix the directory state with git mv or git add, never the gate.

5. Confirm `git diff --cached --name-only` lists only .planning/phases/ paths (3 entries).
   - `--name-status` may pair the renames oddly (for example 25-go-live-readiness-gate → 25-demo-integration-test-campaign). Every .gitkeep is the same empty blob, so this is cosmetic.
   - Nothing else may be staged.

6. Commit: `git commit -m "docs(quick-260930-cgi): map phase directories 25-27 to the renumbered roadmap" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"` (pinned subject).

7. Run the full gate (mode all). It re-runs the decisions, roadmap and dirs gates and adds the git gates:
   - no uncommitted changes in DECISIONS.md, ROADMAP.md or .planning/phases;
   - the committed files match the pinned digests;
   - the new .gitkeep files are tracked and the old directories are untracked;
   - each of the three pinned-subject commits exists exactly once, touches only the allowed paths and ends with the trailer.</action>
  <verify>
    <automated>node .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs dirs && node .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs all</automated>
  </verify>
  <done>The dirs gate prints ALL_PASS dirs, and the full gate prints ALL_PASS all (73 PASS lines in the rehearsal).
- .planning/phases/ holds 25-demo-integration-test-campaign, 26-go-live-readiness-gate and 27-configurable-quote-asset, each with an empty tracked .gitkeep.
- 25-go-live-readiness-gate and 26-configurable-quote-asset no longer exist.
- The HEAD commit touches only .planning/phases/ paths and ends with the trailer.
- .planning/state.json, .gsd/ and .planning/STATE.md are untouched by all three commits.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| INPUT.md (user-approved text) → docs/DECISIONS.md and .planning/ROADMAP.md (planning authority read by gsd-tools and every later /gsd-plan-phase) | Transcription drift or collateral edits would silently change what the user decided and what later phases are planned against |
| local working tree → git history (staging) | The unrelated .planning/state.json modification, the untracked .gsd/ and the orchestrator-owned STATE.md must not cross |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-quick-260930-cgi-01 | Tampering | D040/D041 rows in docs/DECISIONS.md | medium | mitigate | The apply script copies the Part A fence programmatically and refuses a duplicate or misplaced insert. The decisions gate pins the CR-stripped SHA-256, requires numstat 2/0 versus 6a0d4aa and requires the file to equal BASE plus the fence rows after D039 |
| T-quick-260930-cgi-02 | Tampering | ROADMAP.md phases 1–15, 17–22 and 07.1, and the B1–B7 edits | medium | mitigate | Every anchor must match exactly once, inside its phase section, and every inline replacement must occur verbatim in INPUT. The roadmap gate maps every git diff -U0 hunk onto the base file and fails if it touches a protected phase. It also checks the fences are verbatim, pins the digest and cross-checks roadmap.analyze. Tampering with a Phase 17 and a 07.1 line was rehearsed and failed the gate as intended |
| T-quick-260930-cgi-03 | Information disclosure | git staging of .planning/state.json, .gsd/ and .planning/STATE.md | low | mitigate | Every task stages explicit paths and checks git diff --cached --name-only before committing. The git gate whitelists the files each pinned-subject commit may touch |
| T-quick-260930-cgi-04 | Denial of service | gsd-tools phase resolution for 25–27 | low | mitigate | The dirs gate requires exactly one directory per number 25–27 and runs find-phase for each. The 26 → 27 move runs first, so two directories never share a number at commit time |
| T-quick-260930-cgi-SC | Tampering | npm/pip/cargo installs | high | accept | No package installs. The helper scripts use only Node built-ins (fs, path, os, crypto, child_process) |
</threat_model>

<verification>
Overall checks after all three tasks (cwd = repo root):
- `node .planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-verify.cjs all` prints ALL_PASS all.
- `git log -3 --format=%s` shows the three docs(quick-260930-cgi) commits, newest first: map, insert, record.
- `git status --porcelain -- .planning/state.json` still prints " M .planning/state.json".
- Optional spot check: `node ~/.claude/gsd-core/bin/gsd-tools.cjs query find-phase 25` returns .planning/phases/25-demo-integration-test-campaign.

Multi-source coverage audit:

| Source item | Covered by |
|---|---|
| GOAL: add safe release path (D040) and two-step Telegram confirm (D041) to DECISIONS and roadmap | Tasks 1–3 |
| INPUT Part A: D040 row, verbatim, after D039 | Task 1, decisions gate |
| INPUT Part A: D041 row, verbatim, after D040; single-line rows, no pipe in a cell | Task 1, decisions gate |
| INPUT B1: old 17 → 27; live enablement (26) + D040 path; Phases 11–27 sentence | Task 2, roadmap gate (inline lines + overview sentence) |
| INPUT B2: list lines 25/26/27 (fence); Phase 16 and 23 list lines | Task 2, fence B2 + analyze names |
| INPUT B3: Phase 16 heading, goal, criteria 5–6 (fence), Audit refs + D040, D041 | Task 2, fence B3 + inline lines |
| INPUT B4: Phase 23 heading, goal, criterion 4 (fence), Audit refs + D041 | Task 2, fence B4 + inline lines |
| INPUT B5: Phase 24 bot-runner and smoke-path bullets | Task 2, inline lines + stale-text gate |
| INPUT B6: old 25/26 sections replaced by new 25/26/27 sections (fence) | Task 2, fence B6 + analyze names/goals/depends_on |
| INPUT B7: execution-order line; rows 16/23; rows 25/26/27 (fence) | Task 2, execution-order gate + fence B7 |
| INPUT Part C: 26 → 27 first, 25 → 26, new 25 with empty .gitkeep | Task 3, dirs gate + find-phase |
| INPUT Verification: DECISIONS 2 added / 0 deleted | Task 1 numstat gate |
| INPUT Verification: analyze 28 phases; 25/26/27 names, goals, depends_on | Task 2 analyze gates |
| INPUT Verification: find-phase 25/26/27 | Task 3 dirs gate |
| INPUT Verification: no changed line in Phases 1–15, 17–22, 07.1 | Task 2 hunk-ownership gate |
| INPUT Verification: D041 >= 4, D040 >= 5 | Task 2 count gates |
| INPUT constraints: CRLF kept; explicit git add; never stage state.json or .gsd/; trailer | Every commit step, apply script EOL handling, git gate |
| REQ / RESEARCH / CONTEXT | None exist for this quick task |
| Excluded (out of scope per INPUT/orchestrator) | STATE.md progress (total_phases 27 → 28) and quick-task table: orchestrator. New REQ-IDs for SHADOW/confirm: a later Phase 16/23 planning concern. Doc amendments beyond DECISIONS.md: not requested |
</verification>

<success_criteria>
- docs/DECISIONS.md = BASE + D040/D041 rows after D039 (CR-stripped SHA-256 01e68681…94b4), CRLF kept.
- .planning/ROADMAP.md CR-stripped SHA-256 = 93b187ae4b1b1023ecaf8f913e906da067b803c4d1cd68f0326f5186d64688e7. Phases 1–15, 17–22 and 07.1 are untouched.
- gsd-tools roadmap.analyze reports 28 phases, and phases 25/26/27 have the INPUT names, goals and depends_on.
- find-phase 25/26/27 resolve to the new directories, and the two old directories are gone.
- Three docs(quick-260930-cgi) commits with the pinned subjects carry the trailer and touch only the allowed paths.
</success_criteria>

<output>
Create `.planning/quick/260930-cgi-add-safe-release-path-and-two-step-teleg/260930-cgi-SUMMARY.md` when done (frontmatter `status: complete`).
</output>
