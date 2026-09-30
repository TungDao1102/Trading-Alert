---
phase: quick-260930-bvi
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/audits/2026-09-29-deep-audit/README.md
  - .planning/audits/2026-09-29-deep-audit/BAO_CAO_TONG_HOP.md
  - .planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md
  - .planning/audits/2026-09-29-deep-audit/findings.json
  - .planning/audits/2026-09-29-deep-audit/INVARIANTS.md
  - .planning/audits/2026-09-29-deep-audit/FILE_COVERAGE.md
  - .planning/audits/2026-09-29-deep-audit/MANIFEST.md
  - .planning/audits/2026-09-29-deep-audit/AUDIT_CHARTER.md
  - .planning/audits/2026-09-29-deep-audit/LANE_BRIEF.md
  - .planning/audits/2026-09-29-deep-audit/LANES.md
  - .planning/audits/2026-09-29-deep-audit/VERIFIER_BRIEF.md
  - .planning/audits/2026-09-29-deep-audit/TODO.md
  - .planning/audits/2026-09-29-deep-audit/OUTPUT_HASHES.txt
  - .planning/audits/2026-09-29-deep-audit/lanes/
  - .planning/audits/2026-09-29-deep-audit/verification/
  - .planning/audits/2026-09-29-deep-audit/tool-output/
  - .planning/ROADMAP.md
  - .planning/phases/11-fee-units-and-real-commission/.gitkeep
  - .planning/phases/12-account-equity-from-binance/.gitkeep
  - .planning/phases/13-leverage-margin-liquidation-guard/.gitkeep
  - .planning/phases/14-available-margin-check/.gitkeep
  - .planning/phases/15-pre-placement-price-check/.gitkeep
  - .planning/phases/16-notification-money-amounts/.gitkeep
  - .planning/phases/17-configurable-quote-asset/.gitkeep
  - .planning/phases/11-decision-alignment/.gitkeep
  - .planning/phases/12-fee-cost-model-correctness/.gitkeep
  - .planning/phases/13-research-data-foundation-fixes/.gitkeep
  - .planning/phases/14-backtest-causality-rewrite/.gitkeep
  - .planning/phases/15-strategy-geometry-correction/.gitkeep
  - .planning/phases/16-paper-runtime-composition/.gitkeep
  - .planning/phases/17-operational-persistence-layer/.gitkeep
  - .planning/phases/18-user-data-stream-error-taxonomy/.gitkeep
  - .planning/phases/19-execution-plan-binding-price-check/.gitkeep
  - .planning/phases/20-reconcile-safe-mode-hardening/.gitkeep
  - .planning/phases/21-account-equity-daily-loss/.gitkeep
  - .planning/phases/22-leverage-margin-liquidation-guard/.gitkeep
  - .planning/phases/23-telegram-approval-hardening-money/.gitkeep
  - .planning/phases/24-live-runtime-composition-demo/.gitkeep
  - .planning/phases/25-go-live-readiness-gate/.gitkeep
  - .planning/phases/26-configurable-quote-asset/.gitkeep
  - .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs
  - .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-apply-roadmap.cjs
autonomous: true
requirements:
  - QUICK-260930-bvi

estimate:
  tokens: 30000
  raw_tokens: 30000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "The audit directory .planning/audits/2026-09-29-deep-audit/ holds exactly the 51 listed audit files: 12 top-level files, 24 in lanes/, 10 in verification/ and 5 in tool-output/. Their content matches the out-of-repo source byte for byte once CR bytes are ignored. The directory also holds README.md and nothing else; snapshot/, tmp/ and baseline/ are absent"
    - "README.md is a short English index (60 lines or fewer). It states the identity (snapshot 63ca176, read-only, 2026-09-29) and the reading order BAO_CAO_TONG_HOP.md -> DEEP_AUDIT_REPORT.md (§19 remediation, §20 decisions) -> findings.json. It points to D031–D039 in docs/DECISIONS.md and says phases 11–26 were re-planned on 2026-09-30. It says the OUTPUT_HASHES.txt hashes refer to the original out-of-repo copy and may change under line-ending normalization. It says snapshot/ and tmp/ were not imported and names the original out-of-repo path"
    - ".planning/ROADMAP.md equals its 63ca176 content with BLOCK 1, 2, 3, 4a and 4b of 260930-bvi-ROADMAP-SECTIONS.md applied verbatim. Every other line, including all phase 1–10 and 07.1 list lines, details and progress rows, is byte-identical once CR bytes are ignored. The CR-stripped SHA-256 is 1af9525ed5a72dc0bbe8fa92fcaa21cba40398354bb6c2be0a682b3345d85373"
    - "gsd-tools roadmap.analyze reports 27 phases. Phases 11–26 carry the BLOCK 2 names, non-empty goals and depends_on, and phases 1–10 and 07.1 are still present with goals"
    - "find-phase 11 through find-phase 26 each resolve to the directory named in the SECTIONS mapping table, and exactly one directory exists per phase number 11–26. The seven old directories are gone, and 14-available-margin-check was removed with git rm"
    - "Every commit of this task stages explicit paths only and ends with the Co-Authored-By trailer. No 260930-bvi commit touches .planning/state.json, .gsd/, docs/, src/, tests/, params/ or .planning/REQUIREMENTS.md"
  artifacts:
    - path: ".planning/audits/2026-09-29-deep-audit/README.md"
      provides: "English index of the imported deep audit: identity, reading order, decision and roadmap pointers, hash and not-imported caveats"
      contains: "63ca176"
    - path: ".planning/audits/2026-09-29-deep-audit/findings.json"
      provides: "Finding records (F-xxx) that ROADMAP phases 11–26 cite in their Audit refs"
    - path: ".planning/ROADMAP.md"
      provides: "Re-planned phases 11–26 (list, details, execution order, progress rows) with phases 1–10 and 07.1 untouched"
      contains: "### Phase 26: Configurable Quote Asset (USDC readiness)"
    - path: ".planning/phases/11-decision-alignment/.gitkeep"
      provides: "Phase 11 directory resolvable by gsd-tools find-phase (same pattern for all 16 directories 11–26)"
    - path: ".planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-apply-roadmap.cjs"
      provides: "Deterministic verbatim splice of the SECTIONS blocks into ROADMAP.md (anchor-guarded, refuses a second application)"
    - path: ".planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs"
      provides: "Read-only gates: audit, roadmap, dirs, git, all (prints ALL_PASS <mode>)"
  key_links:
    - from: ".planning/ROADMAP.md BLOCK 1 (Overview re-plan paragraph)"
      to: ".planning/audits/2026-09-29-deep-audit/findings.json"
      via: "Finding IDs (F-xxx) in every phase 11–26 Audit refs line resolve against the imported findings.json"
      pattern: "Finding IDs \\(F-xxx\\) refer to `\\.planning/audits/2026-09-29-deep-audit/findings\\.json`"
    - from: ".planning/ROADMAP.md headings ### Phase 11 … ### Phase 26"
      to: ".planning/phases/NN-slug/ directories"
      via: "gsd-tools find-phase NN resolves the number prefix to exactly one directory"
      pattern: "^### Phase (1[1-9]|2[0-6]): "
    - from: ".planning/audits/2026-09-29-deep-audit/README.md"
      to: "docs/DECISIONS.md rows D031–D039"
      via: "README tells the reader that the §20 decisions were recorded as D031–D039"
      pattern: "D031"
---

<objective>
Import the read-only 2026-09-29 deep audit of snapshot 63ca176 into the repo at .planning/audits/2026-09-29-deep-audit/ and give it a short English README index. Then re-plan ROADMAP.md phases 11+ from that audit. The four SECTIONS blocks replace the backlog-promoted phases 11–17 with phases 11–26, and the .planning/phases/ directories are remapped so every new phase resolves in gsd-tools. The milestone stays v0.3, as the coordinator chose in INPUT.md.

Purpose: the audit is the evidence behind D031–D039 and behind every phase 11–26 success criterion, so it must live in the repo where the Audit refs (F-xxx) can be resolved. The roadmap must stop pointing at the superseded 11–17 plan before anyone plans Phase 11.

Output: 52 files under .planning/audits/2026-09-29-deep-audit/ (51 copied plus README.md), a re-planned .planning/ROADMAP.md (phases 1–10 and 07.1 byte-identical), 16 phase directories 11–26, and three scoped commits.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-INPUT.md

Paths used below:
- QUICK = .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa
- SRC = C:/Users/admin/Music/project-audit/2026-09-29_63ca176 (outside the repo, read-only for this task)
- DEST = .planning/audits/2026-09-29-deep-audit

Every command assumes cwd = repository root (C:/Users/admin/Music/Trading) in the Bash tool (Git Bash).

Facts observed at planning time (2026-09-30, HEAD 929f88e):
- The ROADMAP.md content is unchanged since 63ca176, the last commit that touched it. It has 455 lines, is stored LF in the index and is checked out CRLF (core.autocrlf=true).
- SRC holds the 12 named top-level files, lanes/ (24 files), verification/ (10 files) and tool-output/ (5 files), 51 files in total.
  - tool-output/snapshot-status-after-tools.txt is an empty file. Copy it anyway.
  - Some tool-output/*.txt files have mixed CRLF/LF line endings, and every other file is LF.
  - A secret-pattern scan of those 51 files found nothing, and no destination path is gitignored.
- When git add stages the imported files, it prints "LF will be replaced by CRLF the next time Git touches it" warnings. These are expected (autocrlf) and harmless. All content gates ignore CR bytes.
- The old phase directories 11–17 each hold only a tracked, empty .gitkeep.
- After the directory mapping, git diff --cached --name-status pairs the renames by position (for example it shows 11-fee-units-and-real-commission → 11-decision-alignment). Every .gitkeep is the same empty blob, so this display is cosmetic. The gates check the resulting tree, not the rename pairing.
- The quick directory name ends in "-roa" (the user noticed the missing "d"). GSD caps quick-task slugs at 40 characters (gsd-core/bin/lib/init.cjs, substring(0, 40)), and the previous quick directory 260930-bku-…-d03 was cut the same way. Do NOT rename the directory in this task: the orchestrator, INPUT.md and STATE.md bookkeeping point at this exact path. Both helper scripts locate their inputs relative to their own directory, so a later rename by the orchestrator would not break them.
- Two helper scripts already exist in QUICK. The planner wrote them and rehearsed them in a throwaway detached worktree, running the full flow of this plan: all three tasks gave 147 PASS gates and ALL_PASS all.
  - 260930-bvi-apply-roadmap.cjs copies the SECTIONS blocks verbatim. Running it a second time fails with APPLY_FAILED, so the blocks can never be applied twice.
  - 260930-bvi-verify.cjs is read-only, with modes audit | roadmap | dirs | git | all.
  Do not modify either script. If a gate fails, fix the repo state, never the gate.
- .planning/state.json carries a pre-existing unrelated modification, and .gsd/ is untracked. Never stage either. Never use git add -A, git add . or git commit -a.
- Do not edit docs/, src/, tests/, params/, .planning/REQUIREMENTS.md or .planning/STATE.md in this task. New REQ-IDs are deferred to Phase 11, and STATE.md is the orchestrator's job.
- TDD does not apply: this is documentation and planning-structure work with pre-written gates. The API-coverage, assumption-delta and schema-push detectors do not fire, because there is no external API integration, no core-assumption change and no ORM schema.
</context>

<tasks>

<task type="tracer">
  <name>Task 1: Tracer - import the audit artifacts plus README end-to-end (copy, gate, scoped commit)</name>
  <files>.planning/audits/2026-09-29-deep-audit/ (12 top-level files, lanes/, verification/, tool-output/, README.md), .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs (commit only; it already exists)</files>
  <precondition>SRC exists, and QUICK contains 260930-bvi-verify.cjs, 260930-bvi-apply-roadmap.cjs and 260930-bvi-ROADMAP-SECTIONS.md. If any is missing, halt and report; do not recreate them.</precondition>
  <read_first>.planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-INPUT.md (section "Task A")</read_first>
  <action>This task proves the whole path end to end on the first artifact set: byte copy from outside the repo, CR-insensitive gate, and a commit that stages explicit paths only.

1. Create DEST with mkdir -p .planning/audits/2026-09-29-deep-audit.

2. Copy the 12 top-level files byte for byte with cp, one file at a time, from SRC to DEST: BAO_CAO_TONG_HOP.md, DEEP_AUDIT_REPORT.md, findings.json, INVARIANTS.md, FILE_COVERAGE.md, MANIFEST.md, AUDIT_CHARTER.md, LANE_BRIEF.md, LANES.md, VERIFIER_BRIEF.md, TODO.md, OUTPUT_HASHES.txt.
   - Do not open and re-save them with Read/Write/Edit or any editor. Their content must stay unmodified.

3. Copy the three directories recursively in one command whose target is DEST itself: cp -r "C:/Users/admin/Music/project-audit/2026-09-29_63ca176/lanes" "C:/Users/admin/Music/project-audit/2026-09-29_63ca176/verification" "C:/Users/admin/Music/project-audit/2026-09-29_63ca176/tool-output" .planning/audits/2026-09-29-deep-audit/
   - Because the target is the parent directory, a re-run cannot nest lanes/lanes.
   - Never copy SRC as a whole or with a wildcard. snapshot/ (a full repo clone), tmp/ (about 106 MB of probes) and baseline/ (a local diff of an uncommitted file) must not enter the repo, per INPUT Task A.

4. Write .planning/audits/2026-09-29-deep-audit/README.md with the Write tool: plain English, 60 lines or fewer, no emojis. It must contain, in this order:
   - (a) A title and an identity line: snapshot `63ca176`, read-only, 2026-09-29.
   - (b) Directly after the identity, a "Reading order" list:
     1. `BAO_CAO_TONG_HOP.md` (Vietnamese summary)
     2. `DEEP_AUDIT_REPORT.md` (§19 remediation plan, §20 human decisions)
     3. `findings.json`
     Do not mention any of these three file names above this list, because the gate checks first-mention order.
   - (c) A notes section with these points:
     - The user decisions resulting from §20 are D031–D039 in `docs/DECISIONS.md`.
     - Phases 11–26 in `.planning/ROADMAP.md` were re-planned from this audit on 2026-09-30.
     - `OUTPUT_HASHES.txt` hashes refer to the original out-of-repo copy, and git line-ending normalization may change them.
     - `snapshot/` and `tmp/` probe scripts (and `baseline/`) were intentionally not imported. They remain at the original out-of-repo path `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\`.
   - Optionally (your discretion), a one-line description each of lanes/, verification/ and tool-output/.
   - Either an en dash or a hyphen in "11–26" passes the gate.

5. Run the automated gate and fix any FAIL by correcting the copy or the README, never the script. Recovery rules:
   - A "differs" line means the file was modified: re-copy it with cp.
   - An "extras" line means something outside the list was copied: delete that path from DEST.

6. Commit with explicit paths only:
   - git add .planning/audits/2026-09-29-deep-audit .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs
   - Confirm git diff --cached --name-only prints exactly 53 paths, all under DEST plus that one script. It must not include .planning/state.json or anything under .gsd/.
   - git commit -m "docs(quick-260930-bvi): import 2026-09-29 deep-audit report into .planning/audits" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"</action>
  <verify>
    <automated>node .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs audit</automated>
  </verify>
  <done>The gate prints ALL_PASS audit:
- 51 files are identical to SRC (CR-insensitive), and DEST holds nothing extra besides README.md.
- snapshot/, tmp/ and baseline/ are absent, and no secret-shaped strings are present.
- Every README requirement is present, the reading order is right and the README is 60 lines or fewer.
The HEAD commit "docs(quick-260930-bvi): import 2026-09-29 deep-audit report into .planning/audits" contains exactly 53 files and ends with the Co-Authored-By trailer. .planning/state.json is still an unstaged local modification.</done>
</task>

<task type="auto">
  <name>Task 2: Apply ROADMAP BLOCK 1, 2, 3, 4a, 4b verbatim with the anchor-guarded splice script</name>
  <files>.planning/ROADMAP.md, .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-apply-roadmap.cjs (commit only; it already exists)</files>
  <precondition>.planning/ROADMAP.md is unchanged relative to 63ca176 (git diff --quiet 63ca176 -- .planning/ROADMAP.md exits 0). If not, halt and report, because the pinned digest assumes that base.</precondition>
  <read_first>.planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-ROADMAP-SECTIONS.md lines 1-63 and 469-479 (block placement rules only; the script copies the block text, so do not read or re-type the block bodies), .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-INPUT.md (section "Task B")</read_first>
  <action>Apply INPUT Task B (BLOCK 1, BLOCK 2, BLOCK 3, BLOCK 4a, BLOCK 4b) only through the splice script. Never hand-edit ROADMAP.md, never re-type block text, and do not use gsd roadmap subcommands for this change.

1. Run node .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-apply-roadmap.cjs --dry-run.
   - Expect DRY_RUN_OK lines=819 eol=CRLF (nothing is written).

2. Run the same command without --dry-run.
   - Expect APPLIED lines=819 eol=CRLF.
   - Run it once only. A second run exits 1 with APPLY_FAILED by design and changes nothing.

3. If APPLY_FAILED appears on the first run, stop and report the message. Do not patch the anchors, the SECTIONS file or ROADMAP.md.

4. What the script does, so you can sanity-check the result:
   - It inserts BLOCK 1 as a new paragraph between the Overview paragraph and "## Phases", with one blank line on each side.
   - It replaces the seven old phase-list lines 11–17 with the 16 BLOCK 2 lines.
   - It replaces the old Phase 11–17 details, up to but not including "## Progress", with BLOCK 3.
   - It replaces the execution-order sentence with BLOCK 4a.
   - It replaces the seven old progress rows with the 16 BLOCK 4b rows.
   - It keeps the file's CRLF line endings.

5. Run the automated gate. It checks:
   - the pinned CR-stripped digest;
   - each preserved segment and each block, one by one, against 63ca176 and the SECTIONS file;
   - that no old phase 11–17 text is left;
   - 27 "### Phase" headings;
   - gsd-tools roadmap.analyze (27 phases; phases 11–26 with the BLOCK 2 names, goals and depends_on).
   If any roadmap gate fails, restore with git checkout -- .planning/ROADMAP.md, re-read the FAIL line (it names the segment and the first differing line), and re-run step 2. Never edit ROADMAP.md by hand to make the digest match.

6. Commit with explicit paths only:
   - git add .planning/ROADMAP.md .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-apply-roadmap.cjs
   - Confirm git diff --cached --name-only prints exactly those 2 paths.
   - git commit -m "docs(quick-260930-bvi): re-plan ROADMAP phases 11-26 from the deep audit" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"</action>
  <verify>
    <automated>node .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs roadmap</automated>
  </verify>
  <done>The gate prints ALL_PASS roadmap:
- The CR-stripped SHA-256 of .planning/ROADMAP.md is 1af9525ed5a72dc0bbe8fa92fcaa21cba40398354bb6c2be0a682b3345d85373.
- All 11 segment checks pass. The preserved title and overview, phase list 1–10, details 1–10 and 07.1, the progress heading, and progress rows 1–10 and 07.1 are verbatim, and so are BLOCK 1/2/3/4a/4b.
- roadmap.analyze reports 27 phases, and phases 11–26 have goals.
The HEAD commit contains only .planning/ROADMAP.md and the apply script and ends with the trailer.</done>
</task>

<task type="auto">
  <name>Task 3: Remap .planning/phases/ directories 11–26 and run the full gate</name>
  <files>.planning/phases/11-fee-units-and-real-commission/.gitkeep, .planning/phases/12-account-equity-from-binance/.gitkeep, .planning/phases/13-leverage-margin-liquidation-guard/.gitkeep, .planning/phases/14-available-margin-check/.gitkeep, .planning/phases/15-pre-placement-price-check/.gitkeep, .planning/phases/16-notification-money-amounts/.gitkeep, .planning/phases/17-configurable-quote-asset/.gitkeep, plus the 16 new .planning/phases/NN-slug/.gitkeep files listed in files_modified</files>
  <read_first>.planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-ROADMAP-SECTIONS.md lines 502-525 (the "Phase directory mapping" table, which is authoritative)</read_first>
  <action>Apply the SECTIONS directory mapping (INPUT Task B, last paragraph) exactly. Run the commands in this order, all from the repo root.

1. Six renames with git mv (the whole directory; git stages them):
   - git mv .planning/phases/11-fee-units-and-real-commission .planning/phases/12-fee-cost-model-correctness
   - git mv .planning/phases/12-account-equity-from-binance .planning/phases/21-account-equity-daily-loss
   - git mv .planning/phases/13-leverage-margin-liquidation-guard .planning/phases/22-leverage-margin-liquidation-guard
   - git mv .planning/phases/15-pre-placement-price-check .planning/phases/19-execution-plan-binding-price-check
   - git mv .planning/phases/16-notification-money-amounts .planning/phases/23-telegram-approval-hardening-money
   - git mv .planning/phases/17-configurable-quote-asset .planning/phases/26-configurable-quote-asset

2. Remove the merged directory: git rm -r -q .planning/phases/14-available-margin-check. Its scope is merged into phase 22. Confirm the directory no longer exists on disk.

3. Create the ten new directories. For each one: mkdir -p the directory, create an empty .gitkeep inside it (for example with a bare redirection ": > DIR/.gitkeep"; the file must be 0 bytes), then git add that exact .gitkeep path. The directory names are: 11-decision-alignment, 13-research-data-foundation-fixes, 14-backtest-causality-rewrite, 15-strategy-geometry-correction, 16-paper-runtime-composition, 17-operational-persistence-layer, 18-user-data-stream-error-taxonomy, 20-reconcile-safe-mode-hardening, 24-live-runtime-composition-demo, 25-go-live-readiness-gate.

4. Run the dirs gate. It checks:
   - one directory per number 11–26;
   - an empty .gitkeep in each;
   - that the seven old directories are gone;
   - gsd-tools find-phase 11 … 26 resolving to the mapped directories.
   On a FAIL, fix the directory state with git mv, git rm or git add, never the gate.

5. Confirm git diff --cached --name-only lists only paths under .planning/phases/ (23 entries).
   - Rename pairing in --name-status may look shuffled, because every .gitkeep is the same empty blob. That is cosmetic.
   - Nothing else may be staged, especially not .planning/state.json or .gsd/.

6. Commit: git commit -m "docs(quick-260930-bvi): map phase directories 11-26 to the re-planned roadmap" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"

7. Run the full gate (mode all). It re-runs the audit, roadmap and dirs gates and adds the git gates:
   - 52 audit files are tracked, and there are no uncommitted changes in DEST, ROADMAP.md or .planning/phases;
   - the committed ROADMAP.md matches the pinned digest;
   - the new .gitkeep files are tracked and the old directories are untracked;
   - at least 3 260930-bvi commits exist since 929f88e;
   - none of them touches .planning/state.json, .gsd/, docs/, src/, tests/, params/ or REQUIREMENTS.md;
   - every one of them ends with the trailer.</action>
  <verify>
    <automated>node .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs dirs && node .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs all</automated>
  </verify>
  <done>The dirs gate prints ALL_PASS dirs and the full gate prints ALL_PASS all (147 PASS lines in the planning-time rehearsal).
- .planning/phases/ holds exactly one directory per phase 11–26, named as in the SECTIONS mapping table, each with an empty tracked .gitkeep.
- 11-fee-units-and-real-commission, 12-account-equity-from-binance, 13-leverage-margin-liquidation-guard, 14-available-margin-check, 15-pre-placement-price-check, 16-notification-money-amounts and 17-configurable-quote-asset no longer exist.
- find-phase 11 … 26 resolve to the new directories.
- The HEAD commit touches only .planning/phases/ paths and ends with the trailer.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| out-of-repo audit directory (SRC) → git history | Files cross from a local scratch area into versioned (and potentially pushed) history. Only the whitelisted artifacts may cross; the probes, the repo clone and the local uncommitted diff must not |
| SECTIONS replacement blocks → ROADMAP.md (planning authority read by gsd-tools and every later /gsd-plan-phase) | Transcription drift or collateral edits here silently change what later phases are planned against |
| local working tree → git history (staging) | The unrelated .planning/state.json modification and the untracked .gsd/ must not cross |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-quick-260930-bvi-01 | Information disclosure | Imported audit files in DEST | medium | mitigate | Task 1 copies only the 12 named files and 3 named directories with the directory target set to DEST, never SRC as a whole. The audit gate fails on any extra path in DEST, asserts that snapshot/, tmp/ and baseline/ are absent, and scans every imported file for Telegram-token, private-key and API-key/secret assignment shapes (clean at planning time) |
| T-quick-260930-bvi-02 | Tampering | Content of the 51 imported audit files | low | mitigate | Byte copy via cp (no editor round-trip). The audit gate compares every file against SRC byte for byte with CR bytes stripped, so an autocrlf checkout does not cause false failures while any real content change fails |
| T-quick-260930-bvi-03 | Tampering | .planning/ROADMAP.md phases 1–10 and 07.1 and the transcribed phases 11–26 | medium | mitigate | The splice script copies block bodies programmatically between the SECTIONS delimiters and refuses ambiguous or already-applied anchors. The roadmap gate checks each of the 11 segments against 63ca176 and SECTIONS, pins the CR-stripped SHA-256 1af9525e…5373, and cross-checks gsd-tools roadmap.analyze |
| T-quick-260930-bvi-04 | Information disclosure | git staging of .planning/state.json and .gsd/ | low | mitigate | Every task stages explicit paths and checks git diff --cached --name-only before committing. The final git gate rejects any 260930-bvi commit touching .planning/state.json, .gsd/, docs/, src/, tests/, params/ or REQUIREMENTS.md |
| T-quick-260930-bvi-05 | Denial of service | gsd-tools phase resolution for phases 11–26 | low | mitigate | The dirs gate requires exactly one directory per number 11–26 and runs find-phase for each, so a leftover old directory with a duplicate number cannot silently misroute a later /gsd-plan-phase |
| T-quick-260930-bvi-06 | Repudiation | Provenance of the re-plan | low | mitigate | README records audit identity (63ca176, read-only, 2026-09-29) and the re-plan date. Commit subjects carry the task id 260930-bvi, and the git gate requires the Co-Authored-By trailer on every task commit |
| T-quick-260930-bvi-SC | Tampering | npm/pip/cargo installs | high | accept | No package installs in this plan. The helper scripts use only Node built-ins (fs, path, os, crypto, child_process), so there is no supply-chain surface |
</threat_model>

<verification>
Overall checks after all three tasks (cwd = repo root):
- node .planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-verify.cjs all prints ALL_PASS all.
- git log -3 --format=%s shows the three docs(quick-260930-bvi) commits: import, re-plan and map, newest first.
- git status --porcelain -- .planning/state.json still prints " M .planning/state.json". The file was never committed.
- Optional spot check: node ~/.claude/gsd-core/bin/gsd-tools.cjs query find-phase 14 returns .planning/phases/14-backtest-causality-rewrite.

Multi-source coverage audit:

| Source item | Covered by |
|---|---|
| GOAL: import deep-audit report and re-plan roadmap phases 11+ (stay in milestone v0.3) | Tasks 1–3 |
| INPUT Task A: copy the 12 named top-level files | Task 1 step 2, audit gate (content equality) |
| INPUT Task A: copy lanes/, verification/, tool-output/ recursively | Task 1 step 3, audit gate (51-file list) |
| INPUT Task A: do not copy snapshot/, tmp/, baseline/ | Task 1 step 3, audit gate (absence + no extras) |
| INPUT Task A: README identity (63ca176, read-only, 2026-09-29) | Task 1 step 4a, readme gates |
| INPUT Task A: README reading order with §19/§20 | Task 1 step 4b, readme order gate |
| INPUT Task A: README D031–D039 in docs/DECISIONS.md note | Task 1 step 4c, readme gates |
| INPUT Task A: README phases 11–26 re-planned 2026-09-30 note | Task 1 step 4c, readme gates |
| INPUT Task A: README OUTPUT_HASHES.txt / line-ending note | Task 1 step 4c, readme gates |
| INPUT Task A: README snapshot/ and tmp/ not imported, original path | Task 1 step 4c, readme gates |
| INPUT Task B: BLOCK 1 overview paragraph | Task 2, segment gate "BLOCK 1" |
| INPUT Task B: BLOCK 2 phase list lines | Task 2, segment gate "BLOCK 2" + analyze names |
| INPUT Task B: BLOCK 3 details 11–26 replacing old 11–17 | Task 2, segment gate "BLOCK 3" + stale-text gate + 27 headings |
| INPUT Task B: BLOCK 4a execution order, BLOCK 4b progress rows | Task 2, segment gates "BLOCK 4a"/"BLOCK 4b" |
| INPUT Task B: phases 1–10 and 07.1 byte-identical | Task 2, five preserved-segment gates + pinned digest |
| INPUT Task B: git mv renames, git rm 14-available-margin-check, new dirs with .gitkeep | Task 3 steps 1–3, dirs gate |
| INPUT Task B: roadmap.analyze reports 11–26 with goals; find-phase 11…26 resolve | Task 2 analyze gates, Task 3 find-phase gates |
| INPUT constraints: explicit git add only; never stage state.json or .gsd/ | Every task's commit step, git gate |
| INPUT constraints: no edits to docs/, src/, tests/, params/, REQUIREMENTS.md | Scope of all tasks, git gate forbidden-path check |
| INPUT constraints: Co-Authored-By trailer on every commit | Every task's commit step, git gate trailer check |
| REQ / RESEARCH / CONTEXT | None exist for this quick task |
| Excluded (deferred or out of scope per INPUT) | New REQ-IDs (Phase 11), doc amendments for D031–D039 (Phase 11), STATE.md progress update (orchestrator), renaming the 40-character-truncated quick directory (orchestrator decision) |
</verification>

<success_criteria>
- .planning/audits/2026-09-29-deep-audit/ holds 52 tracked files: the 51 audit files identical to the source (CR-insensitive) plus README.md.
- .planning/ROADMAP.md CR-stripped SHA-256 = 1af9525ed5a72dc0bbe8fa92fcaa21cba40398354bb6c2be0a682b3345d85373. Phases 1–10 and 07.1 are byte-identical to 63ca176.
- gsd-tools roadmap.analyze reports 27 phases with goals for 11–26. find-phase 11 … 26 each resolve to the SECTIONS-mapped directory, and the seven old directories are gone.
- Three docs(quick-260930-bvi) commits carry the trailer and touch only DEST, ROADMAP.md, .planning/phases/ and the two helper scripts.
</success_criteria>

<output>
Create `.planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-SUMMARY.md` when done (frontmatter `status: complete`).
</output>
