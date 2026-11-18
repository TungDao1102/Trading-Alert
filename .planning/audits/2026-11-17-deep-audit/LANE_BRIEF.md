# LANE BRIEF — common instructions for every audit lane

You are ONE lane of a READ-ONLY forensic audit of a Binance USDⓈ-M Futures research and
semi-automated execution system (Python 3.13, Decimal, asyncio, PostgreSQL). You have a fresh
context. Other lanes cover other areas: stay in your lane and put cross-lane observations in
"Open Questions". Your own section is in `LANES.md`.

## Paths

- AUDIT = `C:\Users\admin\Music\project-audit\2026-11-17_55885b9`
- SNAPSHOT = `AUDIT\snapshot` (commit `55885b9`). Read code, docs and planning here. Cite paths
  repo-relative with lines (`src/risk/sizing.py:60`).
- ORIGINAL REPO = `C:\Users\admin\Music\Trading`. **Never write there, never run anything that
  writes there.** Only allowed use: `codegraph explore "<symbols or question>"` via Bash with
  that directory as cwd (read-only index, same source as the snapshot). Run it BEFORE grep/Read
  loops for code questions: it returns verbatim line-numbered source and call paths.
- Read first: `AUDIT\AUDIT_CHARTER.md` (rules §2, severity §5), then `AUDIT\snapshot\AGENTS.md`
  (project rules), then your section of `AUDIT\LANES.md`. File sizes: `AUDIT\MANIFEST_src_files.txt`.
- Documented intent: `docs/DECISIONS.md` (D001–D114), canonical `docs/`, `AGENTS.md`,
  `.planning/`. `.planning/codebase/*` and `.planning/research/*` are NOT evidence of the code.

## Neutral stance (owner instruction, read twice)

Every decision, doc and plan in this project was proposed by an AI agent; the owner only picked
among the options offered, has little trading expertise, and is worried the planning is wrong.
So the documents are **intent, not truth** (charter §2.7). You do two jobs:
1. Does the code do what the documented intent says? (DEFECT / GAP / DRIFT when not.)
2. **Is the intent itself right?** Judge each decision that governs your area against: what the
   exchange really does (official docs, installed SDK), arithmetic (a probe with numbers),
   accepted futures risk-management / research practice, and the owner's goals (small capital,
   part-time, fail closed). Code that faithfully implements a wrong or doubtful decision is a
   finding with classification **DESIGN**, never "correct per D0xx".
Stay neutral in both directions: a D-number and a confident rationale prove nothing; "an AI
wrote it" proves nothing either. Do not copy a plan's or summary's reasoning as your evidence:
SUMMARY/VERIFICATION/REVIEW files are claims by the same kind of agent that wrote the code.
Watch for the typical faults of AI-made plans: a rationale that sounds right but rests on an
unverified exchange "fact"; a number picked without derivation; a test and its code written
from the same misunderstanding; a problem "closed" by redefining it, deferring it, or marking
it an owner item; a decision labelled owner-approved where the owner only accepted the default.
Record sound decisions too: the lane file has a "Decision review" table.
- Previous audit (2026-09-29): `.planning/audits/2026-09-29-deep-audit/` in the snapshot
  (`findings.json`, IDs F-xxx). Cite an old ID when your finding is its continuation.
- Tool output, when present: `AUDIT\tool-output\` (ruff, mypy, decision alignment, pytest).
  Do not run the full test suite. You may run single test files or small probes.

## Allowed writes

ONLY `AUDIT\lanes\<lane>.md`, `AUDIT\lanes\<lane>.findings.json` and scratch files under
`AUDIT\tmp\<lane>\`. No fixes, no tests added to the project, no `/gsd` commands, no package
installs, no git writes. Python: `C:\Users\admin\Music\Trading\.venv\Scripts\python.exe -B` with
`PYTHONPATH` = SNAPSHOT, cwd = `AUDIT\tmp\<lane>`, `PYTHONDONTWRITEBYTECODE=1`,
`TEST_DATABASE_URL`/`DATABASE_URL` unset, no `BINANCE_*` variable, `-p no:cacheprovider` for
pytest. Never read `.env`. No network to Binance (signed or Demo), Telegram or a database.
Never `--execute`, never `pytest -m demo`. Public official web docs (developers.binance.com,
core.telegram.org) may be read; on a network error retry once at most, then record it and go on.
A small probe script that imports snapshot code and shows concrete numbers is the strongest
evidence: prefer it for money, sizing and state-machine claims.

## Save your progress as you go (important)

The session may be cut at any time. So:
1. Create `lanes/<lane>.md` with the skeleton below within your first few minutes.
2. After each file group you finish, append the coverage rows, the safe areas and the findings
   to the file immediately. Do not hold findings in memory until the end.
3. If your lane file already exists when you start, it is a partial run: read it, keep what is
   there, and continue with what is missing.
4. When everything is written, write `lanes/<lane>.findings.json`, validate it, and only then
   append the last line `## DONE` to the `.md`.

## Evidence standard

- Every finding cites exact file:line and quotes the code or doc text it rests on.
- CONFIRMED needs a traced code path (ideally a probe output). Otherwise PROBABLE / SUSPICIOUS /
  UNVERIFIED. Never inflate. Before reporting, search for the guard that would make you wrong
  (callers, alternate entry points, a later check, a test that pins the behaviour).
- Severity = consequence if real (charter §5). State it for "now" (placement disabled, Demo
  only) and for "mainnet with placement enabled".
- Classification: DEFECT | DESIGN | GAP | DRIFT | AMBIGUITY | IMPROVEMENT.
- Known items (charter §2.8) are marked `KNOWN:<source>` and reported only when wrongly
  described, wrongly closed, or more severe than recorded. `LIVE_ORDERS_DISABLED` and
  `NOT_CONFIGURED` keys are intended state, not findings.
- For an invariant enforced at one entry point, find the ALTERNATE entry points (CLI, scripts,
  paper vs live vs backtest, restart/recovery path, direct calls) and check each.
- No quota. A short finding list with a solid "Verified Safe Areas" section is a good result.
- Money/safety choices that need the owner are listed under "Owner decisions", with a concrete
  example in numbers. Do not pick for the owner.

## Output 1: `AUDIT\lanes\<lane>.md`

```
# Lane <id>: <name>
## Scope
## Coverage            (table: file | DEEP_READ / NORMAL_READ / METADATA_ONLY / NOT_READ | note) — every file of your scope appears
## Verified Safe Areas (rule or behaviour → what you checked → where → why it holds)
## Decision review     (table: decision/doc rule governing your area | SOUND / DOUBTFUL / WRONG / CANNOT_JUDGE | yardstick used | reason in one line)
## Findings            (one "### G-nnnn" block each)
## Owner decisions
## Open Questions
## DONE
```
Finding block fields: ID · Severity (now / mainnet) · Confidence · Classification · Category ·
Component · File · Lines · Rule (D-number, doc section, or old F-id) · Known-prior · Evidence ·
Expected · Actual · Reproduction · Impact · Why tests miss it · Remediation.

## Output 2: `AUDIT\lanes\<lane>.findings.json`

JSON array; each object:
`{id, severity, severity_mainnet, confidence, classification, category, lane, component, file, line_start, line_end, rule, summary, expected, actual, impact, evidence, reproduction, why_tests_miss, recommendation, known_prior}`
(`null` when unknown; `severity` is the "now" value). Validate it:
`python -B -c "import json,sys;json.load(open(sys.argv[1],encoding='utf-8'))" <file>`.

## Final reply (to the coordinator)

At most 15 lines: counts by severity, the IDs of CRITICAL/HIGH findings with one line each, what
you could not inspect, and whether `## DONE` was written.
