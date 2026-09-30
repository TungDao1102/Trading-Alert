# VERIFIER BRIEF — independent, blind verification of CRITICAL/HIGH findings

You are an INDEPENDENT verifier. You receive only claims and locations, never the original lane's reasoning. Do NOT open `lanes/*.md`, `lanes/*.json`, or `tmp/<lane>/` probe scripts; they belong to other auditors and would bias you. Retrace everything yourself from the snapshot.

## Paths
- Snapshot (commit 63ca176): `C:\Users\admin\Music\project-audit\2026-09-29_63ca176\snapshot`. Read code, docs and planning here.
- Original repo `C:\Users\admin\Music\Trading`: NEVER write to it. You may run `codegraph explore "<symbols/question>"` via Bash with that cwd (read-only index; source identical to the snapshot). Use it before grep/read.
- Allowed writes: only your output file `verification\<batch>_result.md` and scratch files under `tmp\verify_<batch>\`.
- Python probes: use `C:\Users\admin\Music\Trading\.venv\Scripts\python.exe -B` with PYTHONPATH=snapshot and cwd outside the original repo. Keep TEST_DATABASE_URL/DATABASE_URL unset. No network calls to Binance/Telegram/DB.
  - Public official web docs (developers.binance.com, core.telegram.org) may be read when a claim depends on exchange behavior.
- Claims about docs/plans: check the cited text. Then judge whether the consequence claimed is real in trading terms.

## Outcome per finding
- **CONFIRMED**: the defect/gap is real as stated, and the severity is appropriate.
- **DOWNGRADED**: real, but narrower or less severe. Give the corrected severity and the reason.
- **REJECTED**: not real (wrong reading, guarded elsewhere, unreachable). Give the exact counter-evidence.
- **INSUFFICIENT_EVIDENCE**: cannot be decided from snapshot + public docs (e.g. needs a testnet call). Say exactly what would decide it.

Also flag **DUPLICATE_OF <id>** when two claims in your batch describe the same root defect.

## Output format (`verification\<batch>_result.md`)
```
# Verification <batch>
| ID | Outcome | Final severity | Duplicate of | One-line reason |
|---|---|---|---|---|
...
## <ID>
- Outcome / final severity
- Independent evidence (file:line quotes, probe output)
- Counter-checks performed (alternate entry points, guards searched for)
- Notes
```
Final reply: the table only.
