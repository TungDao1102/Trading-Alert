# Quick task input: import deep-audit report + re-plan roadmap phases 11+

On 2026-09-30 the user asked to (1) copy the audit report into the repo and (2) rebuild the roadmap from it. The coordinator was allowed to choose the milestone and chose to **stay in milestone v0.3**, for three reasons:
- the roadmap has a single milestone;
- v0.3 is `gaps_found`, so it cannot be closed cleanly;
- the current phases 11–17 have 0 plans, so replacing them loses nothing.

## Task A: import the audit artifacts (copy, do not modify content)

Source directory: `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\` (outside the repo).
Destination: `.planning/audits/2026-09-29-deep-audit/` in the repo.

Copy exactly these items:
- Top-level files:
  - `BAO_CAO_TONG_HOP.md`
  - `DEEP_AUDIT_REPORT.md`
  - `findings.json`
  - `INVARIANTS.md`
  - `FILE_COVERAGE.md`
  - `MANIFEST.md`
  - `AUDIT_CHARTER.md`
  - `LANE_BRIEF.md`
  - `LANES.md`
  - `VERIFIER_BRIEF.md`
  - `TODO.md`
  - `OUTPUT_HASHES.txt`
- Directories, recursively:
  - `lanes/`
  - `verification/`
  - `tool-output/`

Do NOT copy `snapshot/` (a full repo clone), `tmp/` (about 106 MB of probes and scratch) or `baseline/` (it contains a local diff of an uncommitted file).

Then create `.planning/audits/2026-09-29-deep-audit/README.md`, a short English index containing:
- the audit identity: snapshot `63ca176`, read-only, 2026-09-29;
- a reading order: `BAO_CAO_TONG_HOP.md` (Vietnamese summary) → `DEEP_AUDIT_REPORT.md` (§19 remediation, §20 decisions) → `findings.json`;
- a note that the user decisions resulting from §20 are D031–D039 in `docs/DECISIONS.md`;
- a note that phases 11–26 in ROADMAP.md were re-planned from this audit on 2026-09-30;
- a note that `OUTPUT_HASHES.txt` hashes refer to the original out-of-repo copy, and that git line-ending normalization may change them;
- a note that `snapshot/` and `tmp/` probe scripts were intentionally not imported and remain at the original out-of-repo path.

## Task B: re-plan ROADMAP.md phases 11+

Apply the four blocks in `.planning/quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/260930-bvi-ROADMAP-SECTIONS.md` exactly as that file instructs:
- BLOCK 1: Overview paragraph.
- BLOCK 2: phase list lines.
- BLOCK 3: Phase Details for 11–26, replacing the old 11–17 details.
- BLOCK 4a / 4b: execution order and progress rows.

Phases 1–10 and 07.1 (list lines, details, progress rows) must stay byte-identical.

Then apply the phase directory mapping table at the end of that file under `.planning/phases/`:
- use `git mv` for renames;
- remove `14-available-margin-check` with `git rm`;
- create new directories, each containing an empty `.gitkeep`.

Afterwards, `node ~/.claude/gsd-core/bin/gsd-tools.cjs query roadmap.analyze` must report phases 11–26 with goals, and `find-phase 11` … `find-phase 26` must each resolve to the new directory.

## Constraints

- NEVER stage or commit `.planning/state.json` (it has a pre-existing, unrelated local modification) or `.gsd/`. Use explicit `git add <paths>` only; never `-A`, `.` or `commit -a`.
- Do not edit `docs/`, `src/`, `tests/`, `params/`, or `REQUIREMENTS.md` in this task. New REQ-IDs are deferred to Phase 11.
- End every commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
