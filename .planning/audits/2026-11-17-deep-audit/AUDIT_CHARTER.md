# DEEP PROJECT AUDIT #2 — CHARTER

> **Recovery anchor.** If the session or context is lost: read THIS file, then `TODO.md`
> (status table + log), then continue from the first lane/step that is not `DONE`.
> A lane whose file exists but has no `## DONE` line at the end is PARTIAL: re-launch it with
> "continue from your partial file, do not redo what is already written".
> Requested by the owner 2026-11-17 (Vietnamese). Chat answers and the final report are in
> Vietnamese (identifiers stay English). Lane files are English.

## 0. Identity

| Item | Value |
|---|---|
| Repository | `C:\Users\admin\Music\Trading` (branch `develop`) |
| Snapshot commit | `55885b932ec38048385677d150f92fa7369e196d` (`55885b9`) |
| Dirty state at snapshot | `M .planning/config.json`, `M .planning/state.json`, `?? .gsd/`, `?? .planning/milestone.lock` (not ours). The audit is of the COMMITTED tree. |
| AUDIT dir (all outputs) | `C:\Users\admin\Music\project-audit\2026-11-17_55885b9\` |
| Snapshot clone | `AUDIT\snapshot` (detached at the SHA, clean) |
| Baseline of the original repo | `AUDIT\baseline\` |
| Previous audit | `.planning/audits/2026-09-29-deep-audit/` (snapshot `63ca176`, 152 primary findings, 12 HIGH) |
| Size now | 3,890 tracked files; `src` ≈ 135k lines in 16 packages; 946 test files ≈ 306k lines; 2,500 commits since the previous audit |
| Start | 2026-11-17 |

## 1. Objective

A second read-only forensic audit of the whole project, evidence-driven. Since the first audit
the project grew about tenfold and now contains the real money path (execution, protection,
reconcile, live composition, Demo smoke 21/21). The audit answers:

1. Are the findings of 2026-09-29 really closed in code (not only in plans)?
2. Does the code that was written since then hold the money/safety invariants
   (AGENTS.md "not negotiable" + `docs/DECISIONS.md` D031–D114)?
3. What is still wrong, missing, drifting or unproven before Phases 25/26 (Demo campaign, go-live gate)?

"No verified finding" is a valid result for a lane. No quota.

## 2. Hard rules

1. **Read-only on the original repo.** Nothing in `C:\Users\admin\Music\Trading` is edited,
   created, formatted or committed. No `/gsd-*` commands. Only allowed use of that directory:
   `codegraph explore` (read-only index; source == snapshot).
2. All artifacts live under AUDIT. Lanes read code from `AUDIT\snapshot`, cite repo-relative paths.
3. Safe execution: Python only via `C:\Users\admin\Music\Trading\.venv\Scripts\python.exe -B`,
   `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `TEST_DATABASE_URL`/`DATABASE_URL`
   unset, no `BINANCE_*` variable. `.env` is never read. Nothing connects to Binance (signed or
   Demo), Telegram or a database. No `--execute`, no `pytest -m demo`.
4. Web: public official docs only (developers.binance.com, core.telegram.org), read-only, at
   most one retry on a network error, then record it and go on.
5. No fixes, no new tests, no doc edits. DEFECT vs IMPROVEMENT is kept apart. Taste is not a bug.
6. Ambiguous rules are recorded (classification AMBIGUITY), never resolved by guessing.
   Money/safety choices are surfaced to the owner, never auto-picked.
7. **Neutral stance on decisions, docs and plans (owner, 2026-11-17).** `docs/DECISIONS.md`,
   canonical `docs/`, `AGENTS.md` and everything in `.planning/` were proposed by AI agents;
   the owner only chose among the options offered and is worried they may be wrong. They are
   **documented intent, not ground truth**. The project's own order (DECISIONS > docs > AGENTS >
   .planning) only tells which text the project meant; it does not make the text right.
   The yardsticks for "right" are, in order: (a) what the exchange really does (official
   Binance/Telegram docs, the installed SDK, recorded Demo observations marked as such);
   (b) arithmetic and logic (a probe with numbers); (c) accepted futures risk-management and
   research-methodology practice; (d) the owner's stated goals (small capital, part-time,
   no trading expertise, fail closed, never auto-trade).
   So every lane does two things: checks the code against the documented intent, AND judges
   the intent itself. When code faithfully implements a wrong or doubtful decision, that is a
   finding (classification DESIGN). Neutral means both ways: do not assume a decision is right
   because it has a D-number and a rationale, and do not assume it is wrong because an AI wrote
   it. A decision that holds up is recorded as such, with the reason.
   `.planning/codebase/*` and `.planning/research/*` are not evidence of what the code does.
8. Already-known items are cross-referenced (`KNOWN:<source>`), not re-reported as new:
   phase `*-REVIEW.md`, `*-VERIFICATION.md`, `*-DEFERRED.md` / `deferred-items.md`,
   `*-OWNER-DECISIONS.md`, `19-OWNER-GAPS.md`, `.planning/WINDOWS.md`, STATE.md open items,
   placement disabled (`LIVE_ORDERS_DISABLED`) and `NOT_CONFIGURED` keys are known design state.
   A known item is still reported when it is wrongly described, wrongly closed, or more severe
   than recorded.

## 3. Method

Stage 0 (coordinator): baseline, snapshot, manifest (`MANIFEST_*.txt`), static tools and the
test suite in the snapshot → `tool-output/`.

Stage 1: 23 lanes in four waves (fresh-context subagents, 5–7 at a time). Each lane writes
`lanes/<lane>.md` and `lanes/<lane>.findings.json` **incrementally** (so a session limit loses
little). Common rules: `LANE_BRIEF.md`. Per-lane scope: `LANES.md`.

Stage 2: every CRITICAL/HIGH finding goes to a blind verifier (`VERIFIER_BRIEF.md`), which gets
the claim and the location only. CRITICAL gets a second verifier. Results in `verification/`.

Stage 3: merge and dedupe → `findings.json`; coverage from the lane tables → `FILE_COVERAGE.md`;
`DEEP_AUDIT_REPORT.md` (Vietnamese) and `BAO_CAO_TONG_HOP.md` (short Vietnamese summary).

Stage 4: integrity check (original repo == baseline; unique IDs; every finding has evidence;
every CRIT/HIGH verified; `OUTPUT_HASHES.txt`).

## 4. Depth priority

1. The order path: signal → plan → approve/confirm → place → fill → protect → reconcile → journal
2. Money effects: sizing, quantization, fees, daily loss, equity, margin, liquidation, reservations
3. Fail-closed and SAFE_MODE; crash/restart windows; "never re-send a placement"
4. Exchange facts (SDK and official docs) and error taxonomy
5. Concurrency and persistence integrity
6. Research validity (causality, multiplicity, kill-gate)
7. Ops, deploy, secrets, backups
8. Tests that would not fail if the behaviour broke
9. Doc/plan/code drift, maintainability

## 5. Severity and confidence

Severity = consequence if real, **in the state the project is in** (placement disabled, Demo
only): say both "now" and "when placement is enabled on mainnet". CRITICAL/HIGH = money loss,
unprotected position, unsafe or duplicate order, a safety gate that can be bypassed, or evidence
that is void. MEDIUM = wrong report/decision input, a latent defect behind a guard. LOW/INFO = hygiene.
Confidence: CONFIRMED (traced, ideally with a probe) / PROBABLE / SUSPICIOUS / UNVERIFIED.
Classification: DEFECT (code differs from intent) | DESIGN (the decision/doc/plan itself is
wrong or doubtful; code may follow it faithfully) | GAP | DRIFT | AMBIGUITY | IMPROVEMENT.

## 6. Answers carried over from the owner (2026-09-29 charter §11)

Web access to public official docs: allowed. Strategy review: methodology only (no judgment of
profitability). Depth: deep, every CRIT/HIGH verified. Docs and plans were largely AI-written:
judge them, do not trust them.

## 7. Limits known at the start

- PostgreSQL tests (`*_pg.py`) are skipped in the audit run (`TEST_DATABASE_URL` unset on purpose).
- Docker suite, Demo scripts and anything on a host are not run. Demo evidence is read, not reproduced.
- 135k source lines cannot all be DEEP_READ; coverage levels are recorded per file.
