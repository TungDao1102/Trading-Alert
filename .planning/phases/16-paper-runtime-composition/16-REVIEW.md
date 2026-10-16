---
phase: 16-paper-runtime-composition
reviewed: 2026-10-16
depth: deep
reviewers: 3 (Opus, read-only), one per batch
status: issues_found
counts: {critical: 9, warning: 25, info: 23}
---
# Phase 16 code review (consolidated)

Full findings: `16-REVIEW-batch1.md` (runtime, start, pin, restart: 2 critical, 12 warning, 8 info), `16-REVIEW-batch2.md` (SHADOW approval, ledger, evidence, deploy: 5 critical, 8 warning, 8 info), `16-REVIEW-batch3.md` (research, backtest, core, analytics: 2 critical, 5 warning, 7 info). Scope: 155 files named by the phase SUMMARY files, 68 of them non-test source (about 35,000 lines). Findings are the reviewers' claims unless marked VERIFIED here. Nothing was fixed (no --fix).

## Critical

| Id | Finding | Status |
|---|---|---|
| B1-CR-01 | After a long WebSocket outage the supervisor stops retrying, the process stays up, nothing fails closed, `on-failure` never restarts it | claim |
| B1-CR-02 | Heartbeats committed before their `PAPER_HISTORY_BARS` log entry; a crash in that window leaves heartbeats the parity replay can never match | claim |
| B2-CR-01 | Two threads take the ledger and coordinator locks in opposite order (CONFIRM vs poll worker): possible deadlock | claim |
| B2-CR-02 | Reservations released at wall-clock expiry while the fill driver lags; false `SHADOW_PLAN_EXPIRED_UNFILLED`, then `ValueError` at TP1/exit | claim |
| B2-CR-03 | A confirmed plan the fill driver cannot size raises at start and on every restore: crash-loop until the plan expires | claim |
| B2-CR-04 | RUNBOOK 20.7 hourly publish exits 4 from the second run (epoch prefix already holds a manifest); the final bundle cannot be published | claim |
| B2-CR-05 | `Dockerfile` copies no `params/` and no `config/paper/`, compose mounts only `logs`: the paper service cannot load its parameter set or config | VERIFIED (Dockerfile COPY lines read) |
| B3-CR-01 | Research windows start cold: no warm-up history before `window.start_utc`; `WARMUP_INSUFFICIENT` is exactly 8756 in every one of the 192 Validation records and 9552 in every one of the 48 Development records (796 hourly bars, about 33 days, per symbol per window; about 45% of a 73-day fold) | VERIFIED (counts read from the committed records) |
| B3-CR-02 | The kill-gate JSON sidecar keeps `any_pass`, `pass_count`, budget flags and gate matrices when the conclusion is withheld | claim |

## Warning (25) and Info (23)

Listed in the batch files. Highlights to read first: B1-WR-01 (bars lost between warm-up snapshot and first subscription), B1-WR-06 (one Binance 5xx while a position is open crashes the runtime), B1-WR-07 (no single-instance guard per epoch; `--pin-epoch` also starts the loop), B1-WR-08 (runtime config not pinned to the epoch), B1-WR-11 (a clean SIGTERM exits 0, so `on-failure` does not restart after a reboot; medium confidence), B2-WR-05 (no `concurrency` group on the freeze workflow), B2-WR-07 (nothing restarts or reports a hung runtime; heartbeat and backup target the `trading` project, not the soak database), B3-WR-02 (research records carry no trades digest), B3-WR-03/04 (constraint path relative to cwd; `--repo-root` identity gap).

## Not found (reviewers' positive statements)

Start gate, exact-hash admission, pin/restore rules, Decimal, UTC and secret handling held on every traced path (batch 1). Coverage, exit-criteria and evidence-bundle judges show no path from a gap to a PASS (batch 2). The `compute_features` last-bar optimisation is equivalent to the old path, Holm-Bonferroni over 48 hypotheses is correct, plateau/feasibility/settlement-evidence logic is correct, the holdout is never read (batch 3).

## Untested

B1-CR-01, B1-CR-02, B2-CR-01 to CR-04, B2-WR-01 to WR-05, B3-CR-01, B3-CR-02, B3-WR-01 have no test of the failing scenario (reviewers' grep of tests/).
