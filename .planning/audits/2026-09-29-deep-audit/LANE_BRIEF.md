# LANE BRIEF — common instructions for every audit lane agent

You are ONE lane of a READ-ONLY forensic audit. Fresh context. Other lanes cover other angles — stay in your lane, but record cross-lane observations in Open Questions.

## Paths
- AUDIT = `C:\Users\admin\Music\project-audit\2026-09-29_63ca176`
- SNAPSHOT (audit input, commit 63ca176) = `AUDIT\snapshot` — read code/docs/planning from here; cite paths repo-relative (`src/risk/sizing.py:60`).
- ORIGINAL REPO = `C:\Users\admin\Music\Trading` — **never write, never run anything that writes there.** Only allowed use: running `codegraph explore` with that cwd (read-only index, its source == snapshot).
- Read before starting: `AUDIT\AUDIT_CHARTER.md` (rules), `AUDIT\INVARIANTS.md` (INV-/AMB- IDs to reference), `AUDIT\MANIFEST.md` (file list).
- Prior known results (cross-reference, mark `KNOWN:<source>`, don't blindly re-report as new): `.planning/v0.3-MILESTONE-AUDIT.md`, `.planning/phases/*/??-REVIEW.md`, `*-REVIEW-FIX.md`, `*-VERIFICATION.md`, `10-REVIEW-DISPOSITION.md`, ROADMAP phases 11–17 (already-planned fixes: fee-unit bug in `modeled_costs_per_unit`, equity from Binance, leverage/margin/liquidation guard, available-margin check, pre-placement price check, notification $ amounts, configurable quote asset).
- Pre-computed tool output (do not re-run unless needed): `AUDIT\tool-output\` (ruff-check.txt, ruff-format.txt, mypy-src.txt, pytest.txt).

## Code navigation
Run `codegraph explore "<symbol names or question>"` via Bash (cwd `C:\Users\admin\Music\Trading`) BEFORE grep/Read loops for code questions — it returns verbatim line-numbered source + call paths. Use Grep/Read on the SNAPSHOT for docs/planning/non-code and to confirm exact lines. Git history: `git -C <SNAPSHOT> log/show/blame/log -S` (read-only).

## Allowed writes
ONLY `AUDIT\lanes\<lane>.md` and `AUDIT\lanes\<lane>.findings.json` (and scratch files under `AUDIT\tmp\<lane>\`). Nothing else. No tests created, no fixes, no /gsd commands, no package installs, no network to Binance/Telegram/DB. If you execute Python, use `C:\Users\admin\Music\Trading\.venv\Scripts\python.exe -B` with cwd = SNAPSHOT (or AUDIT\tmp), `TEST_DATABASE_URL`/`DATABASE_URL` unset, `-p no:cacheprovider` for pytest. Small throwaway probe scripts go in `AUDIT\tmp\<lane>\` and may import snapshot code (set `PYTHONPATH` to SNAPSHOT) to demonstrate a finding — that is strong evidence; prefer it for money/sizing claims.

## Evidence standard
- Every finding cites exact file:line and quotes the relevant code/doc text.
- CONFIRMED requires you traced the code path (and ideally a probe/test output). Otherwise PROBABLE / SUSPICIOUS / UNVERIFIED. Never inflate.
- Severity = consequence if real (money loss / unsafe order = CRITICAL/HIGH; wrong report = MEDIUM; hygiene = LOW/INFO).
- Classification: DEFECT (code wrong vs rule) | GAP (required thing missing) | DRIFT (doc/plan ≠ code, neither necessarily wrong) | AMBIGUITY (rule unclear; reference AMB-) | IMPROVEMENT (recommendation, not a bug). Architecture taste is IMPROVEMENT at most.
- No quota. An empty findings list with a solid Verified Safe Areas section is a good result.
- For an invariant enforced in one entry point: find ALTERNATE entry points (CLI, scripts, paper vs live vs backtest, direct function calls) and check each.

## Output: `AUDIT\lanes\<lane>.md`
```
# Lane <n>: <name>
## Scope            (modules/files/docs inspected)
## Coverage         (table: file | DEEP_READ/NORMAL_READ/METADATA_ONLY/EXCLUDED | note)  — list every file you touched; directories may be summarized only for METADATA_ONLY
## Verified Safe Areas   (INV-xxx or behavior → what you checked → where → why it's correct)
## Findings         (one ### F-nnn block each, fields below)
## Open Questions
```
Finding block fields: ID · Severity · Confidence · Classification · Category · Component · File · Lines · Invariant · Phase/commit · Known-prior · Evidence · Expected · Actual · Reproduction · Impact · Why tests miss it · Remediation.

## Output: `AUDIT\lanes\<lane>.findings.json`
JSON array; each object: `{id, severity, confidence, classification, category, lane, component, file, line_start, line_end, invariant_id, phase, commit, summary, expected, actual, impact, evidence, reproduction, why_tests_miss, recommendation, known_prior}` (use null when unknown). Must be valid JSON — verify with `python -c "import json;json.load(open(...))"`.

## Final reply
≤15 lines: counts by severity, the IDs of CRITICAL/HIGH findings with one-line summaries, and anything you could not inspect.
