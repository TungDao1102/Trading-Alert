# DEEP PROJECT AUDIT — CHARTER (requirements for this audit)

> Recovery anchor: if context is lost, re-read THIS file, then `TODO.md`, then continue from the first unchecked item.
> Requested by user 2026-09-29 (Vietnamese). Final chat answer to user must be in Vietnamese.
> DEEP_AUDIT_REPORT.md is written in Vietnamese (technical terms/identifiers stay English). Lane files may be English.

## 0. Identity

| Item | Value |
|---|---|
| Repository | `C:\Users\admin\Music\Trading` (branch `master`) |
| Snapshot commit | `63ca17686137d037ec7d8d9283f99259c3a4d27e` (`63ca176`, no tag) |
| Dirty state at snapshot | `M .planning/state.json` (pre-existing, not ours), `?? Trading.7z` (untracked archive). Audit is of the COMMITTED tree only. |
| Snapshot clone (read-only audit input) | `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\snapshot` (git clone --no-hardlinks, detached at SHA) |
| Output dir | `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\` |
| Baseline of original repo | `baseline/` (status, diff, hashes of dirty files, stash, worktrees) |
| Audit start | 2026-09-29T11:02:07Z |
| OS | Windows 10 Enterprise 10.0.19045, Git Bash + PowerShell 7 |
| Tools | Python 3.13.15 (repo `.venv`), uv 0.12.20, git 2.49.0, node 24.18.0, ruff 0.16.8, mypy 2.3.1, pytest 9.1.1, codegraph CLI (Volta). No semgrep/CodeQL installed. |

## 1. Objective

A read-only forensic audit of the whole project, driven by evidence. It covers code, tests, schema and migrations, config and params, integrations (Binance/Telegram/TradingView), docs, requirements, GSD planning (phases 01–17, research, context, plans, summaries, reviews, verifications), git history, CI and dependencies. The audit looks for:
business-logic bugs, violated invariants, cross-phase regressions, doc/plan/code drift, gaps/gray areas, missing requirements, undocumented behavior, data/concurrency, integration, security/reliability, and testing gaps.
Do not optimize for number of findings. "No verified finding" is a valid result.

## 2. Hard rules (non-negotiable)

1. **Read-only on the original repo.** Nothing inside `C:\Users\admin\Music\Trading` is edited, created, formatted, or committed. `.planning/` and GSD state are not touched. No `/gsd-*` commands. No `git worktree add` (it writes `.git` metadata), so a clone is used instead.
2. All audit artifacts live under the output dir only.
3. Lanes read code from the **snapshot clone** (paths are cited repo-relative, e.g. `src/risk/sizing.py:60`).
4. **CodeGraph is allowed** as a read-only index. `.codegraph/` lives in the original repo, and its source equals the snapshot because only `.planning/state.json` differs. Use `codegraph explore "<symbols/question>"` via Bash (cwd = original repo) or the MCP tool. It must be run before grep/read loops for code questions.
5. **Safe execution:**
   - Tests and static analysis run ONLY inside the snapshot clone, using `C:\Users\admin\Music\Trading\.venv\Scripts\python.exe`.
   - Required settings: `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `TEST_DATABASE_URL` **unset**, `DATABASE_URL` unset.
   - No network credentials: `.env` is never read or copied.
   - mypy uses `--cache-dir` pointed at the output dir's `tmp/`. ruff uses `--no-cache` and never `--fix` or `format` (only `format --check`).
   - Nothing connects to Binance, Telegram, or any real DB. If isolation is unclear, the test is not run and this is recorded.
6. No fixes, no new tests, no doc edits. Distinguish **Confirmed defect** from **Recommended improvement**. Architecture preferences ≠ bugs.
7. Ambiguous business rules are recorded as `AMB-xxx`, never resolved by guessing.

## 3. Pre-audit artifacts (in order)

1. `MANIFEST.md`: generated from git/filesystem; categories: source, tests, fixtures, docs, planning, migrations, config/params, CI, scripts, infra, untracked, ignored-relevant.
2. `FILE_COVERAGE.md`: each relevant file gets exactly one of DEEP_READ / NORMAL_READ / METADATA_ONLY / EXCLUDED, filled from lane coverage tables at synthesis. It starts as all `UNASSIGNED`.
3. `INVARIANTS.md`: `INV-xxx` (ID, Source, Exact rule, Scope, Modules, Transitions, Verification targets, Ambiguity) + `AMB-xxx`. Taken from authoritative sources (docs/, AGENTS.md, .planning/PROJECT.md, REQUIREMENTS.md, DECISIONS.md). **The coordinator reviews it before the lanes start.**

## 4. Lanes (fresh-context subagents; each writes `lanes/<lane>.md` + `lanes/<lane>.findings.json`)

| # | Lane | Finding ID range |
|---|---|---|
| 1 | requirements_docs_plan | F-101…F-199 |
| 2 | architecture_code | F-201…F-299 |
| 3 | business_invariants | F-301…F-399 |
| 4 | data_database_concurrency | F-401…F-499 |
| 5 | integrations_external_apis | F-501…F-599 |
| 6 | testing_verification (runs static analysis + unit tests safely) | F-601…F-699 |
| 7 | security_reliability | F-701…F-799 |
| 8 | historical_regression (git history, plan→commit tracing) | F-801…F-899 |

ID ranges guarantee global uniqueness without coordination. Duplicates across lanes are merged at synthesis (the lower ID is kept and the others are listed as `duplicates`).

Lane output contract:
- **Scope**
- **Coverage table**: file → level
- **Verified Safe Areas**
- **Findings**: every field below
- **Open Questions**

Finding fields:
- ID, Severity (CRITICAL/HIGH/MEDIUM/LOW/INFO), Confidence (CONFIRMED/PROBABLE/SUSPICIOUS/UNVERIFIED)
- Category, Component, File, Lines
- Evidence, Expected, Actual, Reproduction, Impact
- Why tests miss it, Remediation
- Invariant ID, Phase/commit
- Classification: `DEFECT` | `IMPROVEMENT` | `GAP` (missing requirement/impl) | `DRIFT` (doc/plan≠code) | `AMBIGUITY`
- Known-prior: if the finding was already in the phase-10 REVIEW, the v0.3 MILESTONE-AUDIT, or ROADMAP phases 11–17, the source is cited. A known finding is still reported when it matters, but marked `KNOWN:<source>`.

findings.json schema (per finding):
`{id, severity, confidence, classification, category, lane, component, file, line_start, line_end, invariant_id, phase, commit, summary, expected, actual, impact, evidence, reproduction, why_tests_miss, recommendation, known_prior}`

## 5. Priority order for depth

1. core business workflows (signal → plan → approve → order → protect → reconcile → journal)
2. state transitions
3. money effects (sizing, fees, PnL, leverage/margin, quantization, daily loss stop)
4. auth/signatures (webhook HMAC, Telegram callback authority)
5. concurrency/data integrity
6. external integrations
7. retry/idempotency
8. reliability/recovery (SAFE_MODE, fail-closed)
9. testing gaps
10. maintainability
11. generated/vendor content

## 6. Independent verification

- Every CRITICAL and HIGH finding goes to a **fresh verifier agent**. The verifier gets only the snapshot path, the finding statement, and the evidence locations, never the lane's reasoning. It retraces the code independently.
- CRITICAL findings get a second independent verifier.
- Outcomes: CONFIRMED / DOWNGRADED / REJECTED / INSUFFICIENT_EVIDENCE. Results are written to `verification/`.

## 7. Synthesis → `DEEP_AUDIT_REPORT.md` (Vietnamese) + `findings.json` (merged)

Sections:
1. Audit Identity
2. Executive Summary
3. Coverage
4. Methodology
5. Critical Findings
6. High Findings
7. Medium Findings
8. Low/Info Findings
9. Business Invariant Results
10. Documentation/Plan Drift
11. Cross-Phase Regressions
12. Architecture Risks
13. Data/Concurrency Risks
14. Integration Risks
15. Security/Reliability Risks
16. Testing Gaps
17. Verified Safe Areas
18. Unverified/Suspicious Areas
19. Remediation Recommendations
20. Items Requiring Human Business Decision
21. Audit Limitations

## 8. Final integrity check

1. All CRIT/HIGH findings are verified.
2. Every finding has evidence and a unique ID.
3. Coverage is derived from the lane tables.
4. On the original repo, `git status` and `git diff` match `baseline/`, and the dirty-file hashes are unchanged.
5. `OUTPUT_HASHES.txt` is written.
6. No findings were created to fill a quota.

If the repo changed unexpectedly: STOP and report.

## 9. Final chat message (Vietnamese, short)

It contains only:
- completed / not completed
- snapshot SHA
- output dir
- coverage counts by level
- finding counts by severity
- number of unverified findings
- whether the repo is unchanged
- major limitations

No speculative findings in chat.

## 10. Deviations from the user's suggested prompt (and why)

- Clone instead of `git worktree` (worktree mutates `.git` of the audited repo).
- ID ranges per lane instead of a sequential F-001… (parallel lanes can't coordinate numbering).
- Known prior findings are cross-referenced, not rediscovered blindly. Phase-10 review, v0.3 milestone audit, and backlog phases 11–17 already exist.
- Additional classification field (DEFECT/IMPROVEMENT/GAP/DRIFT/AMBIGUITY) to satisfy the "distinguish defect vs improvement" rule mechanically.
- Agent tool (subagents) used for lanes/verifiers; no Workflow tool.

## 11. SCOPE UPDATE (user, 2026-09-29, after charter v1). Where it conflicts with §4, this section wins.

User clarifications:
- `docs/` is the core design, but it was **generated by AI and may be wrong**. Audit it for correctness in trading and Binance terms, not only for internal consistency. Treat docs as "documented intent", not ground truth.
- `.planning/` is managed by gsd-core. Its discuss/research/plan decisions were mostly **"recommended" options that the AI picked on its own**, because the user has little trading expertise. Review every such decision for soundness.
- The audit flows **docs → plan → code**, in that order. Code lanes judge the code against the *corrected* rules (the stage A/B verdicts), not blindly against the docs.

User answers:

| Question | Answer |
|---|---|
| (a) Web access | Allowed to read public official docs: Binance developer docs, fee pages, Telegram Bot API. Read-only, no login, no account API. |
| (b) Lane order | Stages run **sequentially**. |
| (c) Strategy review | **Methodology only**: lookahead, overfit, cost realism, statistics, kill-gate. No judgment on whether it is profitable. |
| (d) Depth | **Deep**, about 14–20 agents. Every CRIT/HIGH finding is verified, and CRIT findings get a 2nd verifier. |

Stages and lanes (ID ranges):

**Stage A: soundness of the docs**
- A1 `docs_trading_soundness` F-001..F-049
- A2 `docs_exchange_facts` F-051..F-099

**Stage B: planning decisions.** Inputs are the stage A outputs.
- B1 `planning_decisions_01_06` F-901..F-949
- B2 `planning_decisions_07_17` F-951..F-999
- L1 `requirements_docs_plan` F-101..F-199

**Stage C: code.** Inputs are the stage A and B outputs.
- L2..L8 as listed in §4 (F-201..F-899)

**Verification:** blind verifiers per topic batch of CRIT/HIGH findings, plus a 2nd verifier for each CRITICAL finding.
