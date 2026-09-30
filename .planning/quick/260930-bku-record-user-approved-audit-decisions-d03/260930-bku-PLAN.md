---
phase: quick-260930-bku
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/DECISIONS.md
autonomous: true
requirements:
  - QUICK-260930-bku

estimate:
  tokens: 20000
  raw_tokens: 20000
  tasks: 2
  confidence: low

must_haves:
  truths:
    - "docs/DECISIONS.md contains rows D031, D032, D033, D034, D035, D036, D037, D038, D039, each exactly once, directly after the D030 row, in ascending order, as the last nine lines of the file"
    - "Every new row is one physical line with exactly four cells (ID, Decision, Status, Rationale), no literal pipe character inside any cell, Status cell exactly 'Accepted (2026-09-30, user)', and a Rationale cell citing audit finding IDs (AMB-NNN and/or F-NNN)"
    - "Decision and Rationale cell text is verbatim from 260930-bku-INPUT.md; the only transformations are removal of the bold markers and of the 'Rationale: ' label (the rows are pre-computed in the exact_rows block of this plan)"
    - "No pre-existing line changed: header, separator, D001-D030 and the blank line before D018 are byte-identical; git diff against base 63ca176 for docs/DECISIONS.md is exactly 9 additions and 0 deletions"
    - "Executor commits touch only docs/DECISIONS.md; .planning/state.json (pre-existing unrelated modification) is never staged or committed"
  artifacts:
    - path: "docs/DECISIONS.md"
      provides: "Architecture / strategy decision log with user-approved audit decisions D031-D039 appended after D030"
      contains: "| D039 | Research universe is point-in-time."
  key_links:
    - from: "docs/DECISIONS.md D032 row"
      to: "docs/DECISIONS.md D029 row (frozen research protocol v1.0.0)"
      via: "D032 supersedes the TBD-until-Validation threshold wording of the frozen protocol and names D029"
      pattern: "frozen protocol v1.0.0 \\(D029\\)"
    - from: "docs/DECISIONS.md D034 row"
      to: "Phase 08 D-03 / Phase 09 D-02 cancel-only reconciler decisions and SECURITY_AND_OPERATIONS SAFE_MODE wording"
      via: "D034 explicitly supersedes both"
      pattern: "Phase 08 D-03 / Phase 09 D-02"
    - from: "docs/DECISIONS.md D031 row"
      to: "all canonical docs, AGENTS.md and .planning/"
      via: "source-of-authority precedence rule"
      pattern: "DECISIONS.md > canonical docs/ > AGENTS.md > .planning/"
---

<objective>
Record the nine user-approved deep-audit decisions D031-D039 (approved 2026-09-30; question 7 answered with option (b) MARK_PRICE) as new rows in the canonical decision log docs/DECISIONS.md, appended directly after D030, in the existing four-column format.

Purpose: D031 makes DECISIONS.md the highest-authority source, so these rows must land verbatim and without disturbing any existing accepted decision. Follow-up amendments to other docs are separate work.
Output: docs/DECISIONS.md with nine added lines and zero changed lines, committed with only that file staged.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@docs/DECISIONS.md
@.planning/quick/260930-bku-record-user-approved-audit-decisions-d03/260930-bku-INPUT.md

Facts observed at planning time (2026-09-30, HEAD 63ca176):
- docs/DECISIONS.md is 35 lines, UTF-8, stored LF in the index and checked out CRLF (core.autocrlf=true). The last line is the D030 row, followed by a single trailing newline.
- The D030 row ends with the text "and the D029 row are untouched |" and that text occurs exactly once in the file, so it is a unique Edit anchor.
- A blank line sits between D017 and D018 (line 22). It is OUT OF SCOPE and must stay as-is.
- docs/DECISIONS.md is unmodified relative to 63ca176 (last touched in 6210d5a). All diff gates below use 63ca176 as the base so they work before and after the task commits.
- .planning/state.json carries a pre-existing unrelated modification. It must never be staged.
- Windows console note: Python print() in this environment defaults to cp1252 and fails on characters such as the approximately-equal sign. Prefer the Edit tool. If a script is used anyway, read and write with encoding utf-8 and set PYTHONIOENCODING=utf-8.

Row construction rule (already applied below; do not re-derive): for each INPUT bullet "**D0NN — Title.** Body. Rationale: text", Decision cell = "Title. Body." with the bold markers removed, Status cell = "Accepted (2026-09-30, user)", Rationale cell = the text after "Rationale: " verbatim (lowercase first letter kept). No cell contains a pipe character.
</context>

<exact_rows>
The nine rows below are the exact bytes to insert (one physical line each, in this order). Copy them verbatim, character for character, including the approximately-equal sign in D032, the en dash in "10–15" and the circled S in "USDⓈ-M" in D039.

| D031 | Source-of-authority precedence. When sources conflict, DECISIONS.md > canonical docs/ > AGENTS.md > .planning/. When .planning decides something new, the canonical doc must be updated in the same change. | Accepted (2026-09-30, user) | resolves audit AMB-001; conflicts found between docs, AGENTS.md and .planning (e.g. quantization check order, 200-order limit source). |
| D032 | Research acceptance thresholds are pre-registered numerically BEFORE any Validation run. The pre-registration covers min trade count, min expectancy after costs, max drawdown, the number of variants to be tried with a multiple-testing correction, and a single-use holdout. A human may reject a candidate that passes but may never pass one that fails. This supersedes the "TBD until Validation" wording of the frozen protocol v1.0.0 (D029); the protocol amendment to v1.1.0 is pending as a separate phase. | Accepted (2026-09-30, user) | audit F-022, F-903, F-960; with ~25 variants and no correction, P(at least one false pass) ≈ 72%. |
| D033 | Daily loss definition. The day is the UTC day (00:00 UTC = 07:00 Asia/Ho_Chi_Minh). The loss counted is realized PnL + commissions + funding, against a base of account equity at the UTC day start. Thresholds stay as in the params (warning 0.5%, stop 1%). On DAILY_STOP: cancel pending entries, keep the protective SL of open positions, alert. | Accepted (2026-09-30, user) | resolves AMB-012/AMB-017; audit F-013, F-963. |
| D034 | SAFE_MODE blocks new ENTRIES only. Protective and reduce-only orders are always allowed. On a missing or canceled SL, the system automatically re-places the SL; if the SL is rejected or unacknowledged, it closes the position with a reduce-only order, then alerts. This supersedes the "no new live order placement" wording in SECURITY_AND_OPERATIONS and the cancel-only reconciler decision (Phase 08 D-03 / Phase 09 D-02). | Accepted (2026-09-30, user) | resolves AMB-015/AMB-024; audit F-009, F-952, F-401; the operator works full-time and cannot react quickly. |
| D035 | Margin mode ISOLATED, leverage cap 5x. The system sets marginType and leverage explicitly before entry and never inherits account defaults. It rejects the plan unless the liquidation price lies beyond SL with a buffer. The available-margin check includes other resting entries. | Accepted (2026-09-30, user) | audit F-011, F-964, F-966; roadmap phases 13/14. |
| D036 | Entry fee modeled as taker. Entries may fill immediately (no GTX/post-only in V1). Sizing, backtest and paper always model the entry fee at the taker rate (conservative). | Accepted (2026-09-30, user) | audit F-005, F-055; a GTC LIMIT placed hours after the signal can be marketable. |
| D037 | Protective SL/TP trigger on MARK_PRICE (user chose option b). Backtest and paper must evaluate SL/TP triggers on mark-price klines (Binance markPriceKlines), so live and backtest use the same trigger price series. The workingType is recorded on the plan. | Accepted (2026-09-30, user) | audit F-507, F-958, F-010; live currently uses MARK_PRICE while the backtest uses last-price candles. |
| D038 | partial_fill_fraction = 1.0 for all canonical cost sets (candidates and baselines identical). Partial or missed fills are studied as a separate sensitivity test. Hash-normalization issues are fixed in code, never by choosing trading parameters. | Accepted (2026-09-30, user) | audit F-006, F-957, F-812; 0.5 was chosen for hash convenience. |
| D039 | Research universe is point-in-time. It is the top 10–15 USDⓈ-M perpetuals by volume at the dataset start date, including later-delisted symbols, and is frozen and hashed before evaluation. Live trading may still restrict itself to the liquid live-5 list. | Accepted (2026-09-30, user) | audit F-024, F-907; survivorship bias of the current live-5-only research universe. |

Pinned SHA-256 digests (content with all carriage returns stripped, computed at planning time from the 63ca176 blob plus these rows):
- After Task 1 (base + D031 only): 3bb5d564b70ba27dfb79a80afc309d3cdc49f0c1257beda79b2002dcc70f986a
- After Task 2 (base + D031..D039): 1042661278a410e508de763ee277dea7915e52c963517e290afa3d7bd58bc73e
</exact_rows>

<tasks>

<task type="tracer">
  <name>Task 1: Tracer - append the D031 row end-to-end (edit, gates, scoped commit)</name>
  <files>docs/DECISIONS.md</files>
  <read_first>docs/DECISIONS.md (the D030 row at the end of the file), the exact_rows block of this plan</read_first>
  <action>Prove the whole append path on one row before doing the other eight: the Edit anchor, UTF-8 and CRLF handling, the digest gate, the diff-only-additions gate and the scoped commit.

Use the Edit tool on docs/DECISIONS.md. old_string is the unique end of the D030 row, "and the D029 row are untouched |". new_string is that same text, then a line break, then the D031 line copied verbatim from the exact_rows block. The new row therefore sits on its own physical line directly after D030 and before the file's existing final newline. Do not add a blank line before or after it. Do not touch any other line, including the blank line before D018, which is out of scope. The working tree is CRLF. If the tool writes a bare LF for the inserted break, that is acceptable because git normalizes on commit and the gates strip carriage returns.

Run the automated gate. If the digest check fails, compare the file against the D031 line in exact_rows with git diff 63ca176 -- docs/DECISIONS.md and fix the character drift (quotes, dashes, spacing). Do not edit the pinned digest.

Commit with explicit staging only: git add docs/DECISIONS.md, then commit with message "docs(quick-260930-bku): record D031 source-of-authority precedence decision". Never use git add -A, git add ., or git commit -a, because .planning/state.json carries an unrelated local modification that must stay unstaged.</action>
  <verify>
    <automated>NS=$(git diff 63ca176 --numstat -- docs/DECISIONS.md) && test "$(printf '%s' "$NS" | cut -f1,2 | tr '\t' ' ')" = "1 0" && test "$(tr -d '\r' < docs/DECISIONS.md | sha256sum | cut -d' ' -f1)" = "3bb5d564b70ba27dfb79a80afc309d3cdc49f0c1257beda79b2002dcc70f986a" && tr -d '\r' < docs/DECISIONS.md | awk -F'|' '/^\| D031 \|/{n++; if (NF!=6 || $4!=" Accepted (2026-09-30, user) " || $5 !~ /AMB-001/) bad++} END{exit !(n==1 && bad==0)}' && echo TRACER_PASS</automated>
  </verify>
  <done>docs/DECISIONS.md is 36 lines. Line 36 is the verbatim D031 row with 4 cells, and the CR-stripped file digest equals 3bb5d564...f986a. git diff against 63ca176 reports 1 addition and 0 deletions. The task commit contains only docs/DECISIONS.md (git show --name-only --format= HEAD prints exactly docs/DECISIONS.md), and .planning/state.json is still unstaged and uncommitted.</done>
</task>

<task type="auto">
  <name>Task 2: Expand - append rows D032 through D039 after D031 and run the full gate</name>
  <files>docs/DECISIONS.md</files>
  <read_first>docs/DECISIONS.md (the D031 row now at the end of the file), the exact_rows block of this plan</read_first>
  <action>Use the Edit tool on docs/DECISIONS.md. old_string is the unique end of the D031 row, "(e.g. quantization check order, 200-order limit source). |". new_string is that same text followed by the eight lines D032, D033, D034, D035, D036, D037, D038, D039, in that order, copied verbatim from the exact_rows block. Put one line break before each row. Add no blank lines, and add nothing after D039 other than the file's existing final newline.

Keep every character exactly as written in exact_rows. Watch these in particular: the approximately-equal sign and "~25" in D032; "AMB-012/AMB-017" in D033; "Phase 08 D-03 / Phase 09 D-02" in D034; "13/14" in D035; "GTX/post-only" in D036; "SL/TP" in D037; "partial_fill_fraction" with no backticks in D038; and the en dash in "10–15" and "USDⓈ-M" in D039. These rows record the user's locked audit decisions (question 7 = option b, MARK_PRICE), so do not reword, summarize, re-capitalize or add markdown emphasis. Do not change any existing row, the header, the separator, or the blank line before D018. The follow-up amendments to RESEARCH_PROTOCOL, SECURITY_AND_OPERATIONS, RISK_MANAGEMENT and EXECUTION_SPEC are out of scope, so modify no other file.

Run the automated gate. It checks that the diff has only additions (9 added, 0 deleted, counted against base 63ca176 across both tasks). It checks the full-file digest. It checks that each D031-D039 row has exactly 6 pipe-separated fields (4 cells, so no stray pipe), the exact Status cell, and an AMB- or F- finding ID in the Rationale cell. It checks that exactly nine rows carry the IDs D031-D039, so no ID is duplicated. It checks that the last ten lines run D030 through D039 in order. On a digest mismatch, locate the drift with git diff 63ca176 -- docs/DECISIONS.md and fix the row text. Never edit the pinned digest.

Commit with explicit staging only: git add docs/DECISIONS.md, then commit with message "docs(quick-260930-bku): record user-approved audit decisions D032-D039". Never use git add -A, git add ., or git commit -a (.planning/state.json must stay unstaged).</action>
  <verify>
    <automated>NS=$(git diff 63ca176 --numstat -- docs/DECISIONS.md) && test "$(printf '%s' "$NS" | cut -f1,2 | tr '\t' ' ')" = "9 0" && test "$(tr -d '\r' < docs/DECISIONS.md | sha256sum | cut -d' ' -f1)" = "1042661278a410e508de763ee277dea7915e52c963517e290afa3d7bd58bc73e" && tr -d '\r' < docs/DECISIONS.md | awk -F'|' '/^\| D03[1-9] \|/{n++; if (NF!=6 || $4!=" Accepted (2026-09-30, user) " || $5 !~ /(AMB|F)-[0-9][0-9][0-9]/) bad++} END{exit !(n==9 && bad==0)}' && test "$(tr -d '\r' < docs/DECISIONS.md | tail -n 10 | cut -d'|' -f2 | tr -d ' ' | tr '\n' ',')" = "D030,D031,D032,D033,D034,D035,D036,D037,D038,D039," && test "$(tr -d '\r' < docs/DECISIONS.md | grep -c '^| D[0-9][0-9][0-9] |')" = "39" && echo FULL_PASS</automated>
  </verify>
  <done>docs/DECISIONS.md is 44 lines. D031-D039 each appear exactly once as the last nine lines, in ascending order, directly after D030. Each row is verbatim from exact_rows, has 4 cells, Status "Accepted (2026-09-30, user)" and an AMB-/F- finding ID in its rationale. The CR-stripped digest equals 10426612...8bc73e. git diff against 63ca176 reports 9 additions and 0 deletions, so no D001-D030 line, header line or the blank line before D018 changed. The task commit contains only docs/DECISIONS.md, and .planning/state.json is still unstaged and uncommitted.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| user-approved decision text (260930-bku-INPUT.md) to canonical decision log (docs/DECISIONS.md) | Under D031 the log becomes the highest-authority source, so any drift in transcription changes what the system is later built to do |
| local working tree to git history | Staging crosses here. An unrelated local modification (.planning/state.json) must not cross |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-quick-260930-bku-01 | Tampering | docs/DECISIONS.md new rows D031-D039 | medium | mitigate | Rows are pre-computed programmatically from INPUT.md into the exact_rows block. The Task 2 gate pins a full-file SHA-256 digest and checks per-row field count, the Status cell and the finding-ID citation, so any paraphrase or character drift fails the gate |
| T-quick-260930-bku-02 | Tampering | docs/DECISIONS.md existing rows D001-D030, header, blank line before D018 | medium | mitigate | git diff numstat against base 63ca176 must be exactly "9 0" (zero deletions means zero modified lines). The full-file digest also covers every pre-existing byte after CR normalization |
| T-quick-260930-bku-03 | Information disclosure | git staging of .planning/state.json | low | mitigate | Both tasks stage with git add docs/DECISIONS.md only and forbid the -A, dot and commit -a forms. The done criteria check that git show --name-only --format= HEAD prints exactly docs/DECISIONS.md |
| T-quick-260930-bku-04 | Repudiation | provenance of D031-D039 | low | mitigate | The Status cell carries the approval date and approver ("Accepted (2026-09-30, user)"), the rationale cites audit finding IDs, and the commit messages name the quick task id |
| T-quick-260930-bku-SC | Tampering | npm/pip/cargo installs | high | accept | No package installs in this plan. Docs-only edit, so there is no supply-chain surface |
</threat_model>

<verification>
Overall checks after both tasks (cwd = repo root):
- The Task 2 automated gate prints FULL_PASS.
- git log -2 --format=%s shows the two docs(quick-260930-bku) commits. For each, git show --name-only --format= on that commit prints only docs/DECISIONS.md.
- git status --porcelain -- .planning/state.json still shows it as a local, unstaged modification in the main checkout (" M"). It was never part of an executor commit.

Source coverage audit:

| Source item | Covered by |
|---|---|
| GOAL: record user-approved audit decisions D031-D039 in docs/DECISIONS.md | Task 1 (D031), Task 2 (D032-D039) |
| INPUT D031 precedence | Task 1 |
| INPUT D032 through D039 (incl. D037 option b MARK_PRICE) | Task 2 |
| INPUT constraint: after D030, existing format, Status text, finding-ID rationale, single physical line, no pipe | exact_rows block plus Task 1/2 gates (position, NF==6, Status, AMB/F regex, digest) |
| INPUT constraint: change only docs/DECISIONS.md; do not stage .planning/state.json | files_modified, explicit git add, commit-content check |
| REQ / RESEARCH / CONTEXT | None exist for this quick task |
| Excluded (out of scope per INPUT/orchestrator) | RESEARCH_PROTOCOL v1.1.0, SECURITY_AND_OPERATIONS SAFE_MODE text, RISK_MANAGEMENT daily-loss text and EXECUTION_SPEC amendments, plus the blank line before D018 |
</verification>

<success_criteria>
- docs/DECISIONS.md has 39 decision rows (was 30), and the last nine are D031-D039 verbatim from exact_rows.
- Diff against 63ca176: 9 insertions, 0 deletions, one file.
- The CR-stripped file digest equals 1042661278a410e508de763ee277dea7915e52c963517e290afa3d7bd58bc73e.
- Only docs/DECISIONS.md appears in executor commits, and .planning/state.json is untouched by git.
</success_criteria>

<output>
Create `.planning/quick/260930-bku-record-user-approved-audit-decisions-d03/260930-bku-SUMMARY.md` when done (frontmatter `status: complete`).
</output>
