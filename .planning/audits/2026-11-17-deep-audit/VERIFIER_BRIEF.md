# VERIFIER BRIEF — independent, blind verification of CRITICAL/HIGH findings

You are an INDEPENDENT verifier. You receive claims and locations only, never the lane's
reasoning. Do NOT open `lanes/*`, or `tmp/<lane>/` probe scripts: they belong to other auditors
and would bias you. Retrace everything yourself. Try to REFUTE each claim first: look for the
guard, the caller, the later check or the test that makes it wrong.

## Paths and limits

- AUDIT = `C:\Users\admin\Music\project-audit\2026-11-17_55885b9`; snapshot (commit `55885b9`)
  = `AUDIT\snapshot`. Read code, docs and planning there.
- Original repo `C:\Users\admin\Music\Trading`: NEVER write. You may run
  `codegraph explore "<symbols or question>"` via Bash with that cwd (read-only index, same
  source). Use it before grep/read.
- Allowed writes: `AUDIT\verification\<batch>_result.md` and scratch under `AUDIT\tmp\verify_<batch>\`.
- Python probes: `C:\Users\admin\Music\Trading\.venv\Scripts\python.exe -B`, `PYTHONPATH` =
  snapshot, cwd = your scratch directory, `TEST_DATABASE_URL`/`DATABASE_URL` unset, no
  `BINANCE_*` variable. No network to Binance, Telegram or a database. Never read `.env`.
- Public official docs (developers.binance.com, core.telegram.org) may be read when a claim
  depends on exchange behaviour; one retry at most on a network error.
- Project state to judge severity against: live placement is disabled (`LIVE_ORDERS_DISABLED`),
  only Binance Demo was used. Give the severity for "now" and for "mainnet with placement enabled".
- Write your result file progressively (one finding at a time), so a cut session loses little.

## Neutral stance

Decisions, docs and plans of this project were proposed by AI agents and may be wrong; they are
intent, not truth. For a DESIGN claim ("the decision itself is wrong") judge it against official
exchange docs, arithmetic and accepted risk practice, not against the project's own rationale.
"The code follows D0xx" neither confirms nor refutes anything. Be neutral both ways.

## Outcome per finding

- **CONFIRMED**: real as stated, severity appropriate.
- **DOWNGRADED**: real but narrower or less severe; give the corrected severity and why.
- **REJECTED**: not real (wrong reading, guarded elsewhere, unreachable); give the exact counter-evidence.
- **INSUFFICIENT_EVIDENCE**: cannot be decided from the snapshot and public docs; say exactly what would decide it.

Flag **DUPLICATE_OF <id>** when two claims describe the same root defect.

## Output (`verification\<batch>_result.md`)

```
# Verification <batch>
| ID | Outcome | Severity now | Severity mainnet | Duplicate of | One-line reason |
|---|---|---|---|---|---|
## <ID>
- Outcome / severities
- Independent evidence (file:line quotes, probe output)
- Counter-checks performed (alternate entry points, guards searched for)
- Notes
## DONE
```
Final reply: the table only.
