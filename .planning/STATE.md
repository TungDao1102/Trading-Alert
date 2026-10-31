---
gsd_state_version: "1.0"
milestone: v0.3
current_phase: 24
current_phase_name: Live Runtime Composition + Demo Rehearsal
current_plan: 5
status: executing
stopped_at: Completed 24-04-PLAN.md
last_updated: "2026-10-31T05:37:25.933Z"
last_activity: 2026-10-31
last_activity_desc: Phase 24 execution started
state_head: fc3812d7cab10a360eead033a0e1a838c5c33747
progress:
  total_phases: 29
  completed_phases: 19
  total_plans: 364
  completed_plans: 329
milestone_name: milestone
---

<!-- STATE-MD-SCHEMA:END:frontmatter -->

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-19)

**Core value:** Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.
**Current focus:** Phase 24 — Live Runtime Composition + Demo Rehearsal

## Current Position

Phase: 24 (Live Runtime Composition + Demo Rehearsal) — EXECUTING
Previous: Phase 20 (Reconcile + SAFE_MODE Hardening + Alerts) — EXECUTED, verification human_needed
Current Plan: 5
Total Plans in Phase: 36
Status: Ready to execute
Last activity: 2026-10-31 — Phase 24 execution started

Progress: [██████░░░░] 61%

### Cross-phase status (2026-10-16)

- Phase 22 (leverage, margin and liquidation guard): all 16 plans executed on develop (2026-10-24), verification human_needed, no blocking gap (`22-VERIFICATION.md`). Library level only: `MarginGuard`, `SymbolConfigGuard`, `BracketCache`, `LiquidationWatch` and gate 5f2 exist but no running process composes them (Phase 24); nothing writes `required_margin` yet and the post-fill watch is inactive until Phase 24. The owner ran six Demo cases on 2026-10-24 (`22-DEMO-RESULTS.md`, single samples, demo-observed, not mainnet): -4047, -4028, -2019 observed; `availableBalance` netted a resting order (flag `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` stays False until the owner's DECISIONS row); the isolated liquidation formula matches the exchange only with the entry fee netted from the isolated wallet (one long sample). BTCUSDT on Demo is now ISOLATED x5. Open owner items: O-1 target leverage, O-2 liquidation buffer, O-3 bracket age and margin headroom, O-4 close or alert after a failed post-fill check.
- Phase 21 (account equity and daily loss from Binance): all 16 plans executed on develop (2026-10-23), verification human_needed, no gap (`21-VERIFICATION.md`). Library level only: `LiveEquitySource`, `LiveDayRiskService`, `enforce_daily_state`, `build_live_risk_inputs` and `make_reserving_save_atomic` are composed into no running process until Phase 24. Migrations 0010 (daily risk state) and 0011 (risk reservations); signed adapter registry at sixteen methods. Owner decision O-2 (2026-10-23): option A, `FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING`; O-1, O-3, O-4, O-5 and O-6 stay OPEN (`21-OWNER-DECISIONS.md`); the assistant's pre-canary FUNDING_FEE check is an OPEN recommendation, not an owner decision. `account.max_equity_age_ms` is `NOT_CONFIGURED` and required. Demo income (2026-10-23, demo-observed, not mainnet): one COMMISSION row, no FUNDING_FEE row. The 2026-10-23 Demo runs of the eight sj2 cases are in `19-OWNER-GAPS.md` section 2b. No requirement was marked complete (EXEC-01 and OPS-02 stay Pending). Full non-docker suite (`-n 4`, strict, PostgreSQL) had one failure, `test_paper_shadow_isolation` (five new read-only adapter methods unclassified), fixed in 90d10ef7; the full suite was not re-run after that fix and no recorded sequential gate exists for Phase 21 yet.
- Phase 19 (execution plan binding and pre-placement checks): all 17 plans executed on branches phase-19 / p19-15 and merged into develop by the owner (2026-10-20, merges e5ba20a and 6d90d84). Model: fill-driven protection (D-10), GTD LIMIT entry with no entry-time stop, coordinator `src/execution/protection.py`, emergency close, live TP sizing, migration 0005 (sized realized risk); quick task 261020-jua made Q5 true in code (one `place_entry` POST per approval, ambiguous result probed once, otherwise UNKNOWN + SAFE_MODE). Status: complete-pending-owner-read. NOT closed: no requirement is marked complete (EXEC-01, EXEC-02, RISK-04, APRV-01, APRV-02, EXEC-07 stay Pending, no Demo run), D055 stays OPEN (decision rows D079 for D-10 and D080 for Q5 are drafts, not written; D077 and D078 are written rows: D077 the stop-lost row of 19-REVIEW WR-04, D078 the approved-quantity row of 19-REVIEW WR-01), live placement stays disabled, the four `NOT_CONFIGURED` limit keys and the 11 Demo probes belong to the owner (`.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md`). The whole suite was NOT run on the merged tree; the owner runs the fresh sequential gate and records `IMAGE_COMMIT=<40 hex>` under `.planning/phases/16-paper-runtime-composition/evidence/`, and plan 16-43 must then read that record instead of `16-65-gate.txt` (the 9b27da5 image predates Phase 19).
- AGENTS.md (2026-10-20): the generated blocks of commit 0884fea (1,222 lines) were removed; the file is now a ~190-line router (rules, commands, tests with `-n 4`, commit-trailer rule, secrets, execution model, source-of-truth order, a table of where to read). `tests/test_agents_md.py` caps it and checks its paths. `.planning/codebase/` and `.planning/research/` each have a README that states role and trust. `.planning/codebase/*.md` were mapped at commit 4e37e15 (before the Phase 16 fix plans and the Phase 19 merge): run `/gsd-map-codebase` to refresh them; do not run `generate-claude-md` on AGENTS.md.
- Phase 18 (user-data stream and error taxonomy): CLOSED 2026-10-18, status human_needed (no gap, no BLOCKER). All 26 plans are executed on develop (18-19 skipped by design: gate result `transport: sdk`). The user integrated `phase-18-smoke` with `git merge --no-ff` (merge commit dde100b); plan 18-26 recorded the owner's taxonomy decision of 2026-10-17 (-1106, -4016, -4024 REJECTED_DEFINITIVE on placement, -1125 Demo provenance); fix 1291caa made the Demo credential names `BINANCE_DEMO_API_KEY` and `BINANCE_DEMO_API_SECRET`; the verification report is c45bbfc (`18-VERIFICATION.md`, verified at fea8e2e). The gates are green at fea8e2e (`18-TRACEABILITY.md`). Nothing is pushed. All evidence is Demo-observed, not mainnet. Human items left: the user signs `18-VALIDATION.md` (still draft), the no-withdrawal key and IP-allowlist attestation (OPS-02, Phases 24 to 26), and the D055 decision. D055 stays OPEN (no DECISIONS row); the Demo evidence is `decisions/18-DRAFT-D055-evidence-for-user.md` and the adopted direction is noted, not decided, in `.planning/phases/19-execution-plan-binding-price-check/19-NOTES.md` for `/gsd-discuss-phase 19`. Requirements EXEC-01, EXEC-02, EXEC-05 and OPS-02 stay Pending in REQUIREMENTS.md (library-proven, Demo-observed, no running-process proof). Next for Phase 18's successors: Phase 19 discussion, in order after Phase 16 closes.
- Phase 16 fix plans: 16-55, 16-56, 16-57, 16-58 and 16-59 done on develop (owner decisions in 16-DEC-FIXPLANS.md; 16-57 adds 16-DEC-CONFIG-PIN; 16-58 fixed the SHADOW lock order, refusal of unsizable plans, data-horizon expiry, midnight roll, unknown-append reconcile, per-press replies and the dispatch error log; 16-59 added the as-of export with partial-bundle refusal, per-bundle create-only evidence keys, the merged freeze log with missing-tick records, the workflow concurrency group with queue max and the dispositions in deferred-items.md). The blocking set 16-55 to 16-59 is green on GATE_COMMIT a54f9da47ca8b7b7c6c2488b0d8cb67b506f4ba0 (evidence/16-59-gate.txt); the soak image is NOT built from it, plan 16-62 records the image commit. Plan 16-62 (B1-WR-09) is done: rest_backfill_depth_bars (1500, v2 file unchanged) now bounds every supervisor REST backfill, newest closes first, older missing closes are recorded gaps with the window reason; the soak image is built from IMAGE_COMMIT efae1f3efe3211f75f94e165e5d1c9956b20a6f1 (evidence/16-62-gate.txt, full suite 10118 ran, 10112 passed, 6 skipped, 0 failed; ruff, ruff format, mypy src and uv lock --check clean); the targeted re-review of c654524..efae1f3 is still to run before anything is pushed or merged. Next in order: 16-60 and 16-43, then 16-61 and 16-44. Phase 16's new DECISIONS rows are D073 (protocol v2.5.0 warm-up amendment) and D074 (regeneration inventory), because Phase 18 took D072.
- Plan 16-63 done on develop (2026-10-20): TP2 positivity guard (NO_TRADE RR_TOO_LOW), simulator semantics 2.3.0, protocol v2.6.0 with D075 and D076 (landing commit 6f599dd). The rerun of research run 1 at 2.3.0 is complete: 240 records in docs/research/experiments/research-run-1-v2-3-0/ (commit b17312a, RUN_COMMIT 58a5374), the three families ran in parallel by owner decision of 2026-10-19 (16-DEC-RERUN-PARALLEL.md), each exit 0 with 80 records; verification rerun all present. The 2.1.0 records are kept and superseded (16-DEC-RUN1-SUPERSEDED.md, f8453f9). Final gate 03e29ee: 10394 passed, 19 skipped (no PostgreSQL skip; native Windows PostgreSQL 17.11 service), ruff, format, mypy, uv lock clean. 16-61 stays partial; its Tasks 3 and 4 were done as 16-63 Tasks 6 and 7. BKTS-03 unchanged (already Complete). Next: plan 16-43 on the soak host, after the soak image is rebuilt from a commit that contains the TP2 guard and the 16-62 gate is repeated (R7, answered 2026-10-19).
- Plan 16-65 done on develop (2026-10-20): fixes of the review of c654524..6f73e5b. MAJOR: the liveness stamp is owned by the instance-lease holder, removed right after the lease and at every exit, and records no frame before the first message (5c866c4, follow-up 9b27da5; decisions/16-DEC-LIVENESS-FIRST-FRAME.md). MINOR: backup.sh reads BACKUP_S3_BUCKET as Compose does and substitutes unit tokens safely (86b4db7); P16R-01 export_soak_evidence refuses an --as-of later than now (56844f9). P16R-02 (Phase 23) and P16R-03 (Phase 24) stay deferred. Final gate on ce79193 (evidence/16-65-gate.txt): 10441 passed, 19 skipped, 0 failed, PostgreSQL tests run, sequential 20 min 25 s; ruff, format, mypy, uv lock, decision alignment clean. New soak IMAGE_COMMIT 9b27da55ff1675b66c8033792b68186da9b4a498 (contains 6f599dd and the quick tasks 261020-xd4 and 261020-spd); 16-43 reads it. Before push or merge: targeted re-review of 6f73e5b..9b27da5 (c654524..9b27da5 overall).
- Plan 16-64 done on develop (2026-10-20, R7 of 16-DEC-V260 executed): the 16-62 final gate was repeated on the current tree (evidence/16-64-gate.txt: 10393 passed, 19 skipped, 0 failed, PostgreSQL tests run; ruff, format, mypy, uv lock clean). The soak image is now built from IMAGE_COMMIT 6f73e5bb87167f386b22a64a00effa56ca4ef0bf (contains the TP2 guard 6f599dd; supersedes efae1f3 for the soak); 16-43 reads it from evidence/16-64-gate.txt. The targeted re-review range is c654524..6f73e5b (now including 16-60, 16-61, 16-63 and Phase 18). docs/DECISIONS.md D075 still calls R7 open (not edited). Next: 16-43 on the soak host.
- Plan 16-60 done on develop (2026-10-17, landing commit c96fa0d, gate commit 76b1da0): research windows get a 50-day price-only warm-up (`RESEARCH_WARMUP_SPAN`), simulator semantics 2.2.0, protocol v2.5.0 with DECISIONS D073 and D074 (the Phase 18 row D072 keeps its number); the Development window starts cold (data begins 2024-10-03); the 240 records of run 1 are unchanged and superseded by D074. Full suite at the landing: 10145 ran, 10139 passed, 6 skipped, 0 failed; ruff, ruff format, mypy src and `uv lock --check` clean. Next: 16-43 (host/owner), then 16-61 (sixth authorization key, three new authorization files, the rerun into `research-run-1-v2-2-0`) and 16-44. BKTS-03 stays open (requirements.ready-ids: blocked).
- Full suite after 16-59 (2026-10-16, GATE_COMMIT a54f9da): `pytest -m "not docker"` 10099 ran, 10093 passed, 6 skipped, 0 failed; ruff, ruff format, mypy src and `uv lock --check` clean. Earlier, after 16-58: 10071 collected, 10065 passed, 6 skipped, 0 failed. In that shell TEST_DATABASE_URL was set and the PostgreSQL tests ran (tests/test_paper_shadow_runtime_pg.py passed 3 of 3).
- Remaining for Phase 23 from 16-58: a distinct canonical rejection reason for store failures (INVALIDATED covers them now, with an error log line by class name).
- Owner actions pending: second soak backup bucket with its own crypt passwords; second heartbeat check (period 60 s, grace 120 s) and its secret URL (before 16-43); confirm the PostgreSQL tests run on the owner machine (see .planning/WINDOWS.md; they ran in the 16-58 session).
- From 16-59 for plan 16-43 and the operator: the freeze workflow change (concurrency group with `queue: max`) takes effect only on `master` (G15), so plan 16-43 checks `origin/master` for the block before the pin; GitHub's acceptance of the `queue` key is shown only by the first live run (WINDOWS.md entry 12). Hourly evidence exports use `--as-of` and one `--diff-log` per downloaded run artifact (RUNBOOK 20.7).

## Performance Metrics

**Velocity:**

- Total plans completed: 132 (Phase 03 + Phase 05 plans 1+2 + Phase 06 plan 1)
- Average duration: ~14 min
- Total execution time: ~100 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 3 | 5 | - | - |
| 5 | 2 | - | - |
| 06 | 1 | 3 | ~15 min |
| 07.1 | 2 | - | - |
| 12 | 11 | - | - |
| 13 | 13 | - | - |
| 4 | 4 | - | - |
| 7.1 | 2 | - | - |
| 1 | 4 | - | - |
| 2 | 5 | - | - |
| 8 | 5 | - | - |
| 9 | 4 | - | - |
| 10 | 12 | - | - |
| 11 | 8 | - | - |
| 7 | 4 | - | - |
| 15 | 18 | - | - |
| 14 | 17 | - | - |
| 17 | 15 | - | - |

**Recent Trend:**

- Last 7 plans: 03-01 (tracer slice) — ~15 min, 03-02 (six entities) — ~10 min, 03-03 (registry hardening) — ~10 min, 03-04 (ORM mirror + mappers + migration) — ~15 min, 05-01 (risk tracer slice) — ~25 min, 05-02 (portfolio gates) — ~25 min, 06-01 (backtest simulator tracer slice) — ~15 min
- Trend: stable

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 06 P02 | 45min | 3 tasks | 12 files |
| Phase 06 P03 | 45min | 3 tasks | 7 files |
| Phase 07.1 P01 | ~15 min | 2 tasks | 9 files |
| Phase 07.1 P02 | ~10 min | 2 tasks | 4 files |
| Phase 07 P01 | ~45 min | 3 tasks | 10 files |
| Phase 07 P02 | ~30 min | 3 tasks | 8 files |
| Phase 08 P01 | ~15 min | 3 tasks | 7 files |
| Phase 08 P03 | ~10 min | 2 tasks | 5 files |
| Phase 08 P04 | ~25 min | 3 tasks | 8 files |
| Phase 8 P2 | ~25 min | 3 tasks | 8 files |
| Phase 8 P05 | ~15 min | 2 tasks | 4 files |
| Phase 09 P04 | ~50min | 2 tasks | 11 files |
| Phase 10 P01 | 18min | 3 tasks | 23 files |
| Phase 10 P02 | 12 min | 2 tasks | 7 files |
| Phase 10 P03 | 12 min | 3 tasks | 8 files |
| Phase 10 P04 | 27min | 3 tasks | 14 files |
| Phase 10 P05 | 5 min | 3 tasks | 14 files |
| Phase 10 P06 | 11 min | 3 tasks | 8 files |
| Phase 10 P07 | 12 min | 3 tasks | 18 files |
| Phase 10 P08 | 12 min | 3 tasks | 6 files |
| Phase 10 P09 | 13 min | 3 tasks | 7 files |
| Phase 10 P10 | 14 min | 2 tasks | 6 files |
| Phase 10 P11 | 35 min | 3 tasks | 7 files |
| Phase 10 P12 | 13 min | 3 tasks | 6 files |
| Phase 11 P01 | 30 min | 3 tasks | 10 files |
| Phase 11 P02 | 25min | 3 tasks | 11 files |
| Phase 11 P03 | 20min | 2 tasks | 3 files |
| Phase 11 P04 | 25min | 3 tasks | 8 files |
| Phase 11 P06 | 30 min | 2 tasks | 6 files |
| Phase 11 P05 | 40min | 3 tasks | 7 files |
| Phase 11 P07 | 10 min | 3 tasks | 8 files |
| Phase 11 P08 | 35 min | 3 tasks | 4 files |
| Phase 12 P01 | 25 min | 2 tasks | 5 files |
| Phase 12 P02 | 35min | 3 tasks | 12 files |
| Phase 12 P03 | 35min | 2 tasks | 9 files |
| Phase 12 P04 | 25 min | 2 tasks | 15 files |
| Phase 12 P05 | 25 min | 3 tasks | 6 files |
| Phase 12 P06 | 25 min | 2 tasks | 6 files |
| Phase 12 P07 | 25min | 3 tasks | 19 files |
| Phase 12 P08 | 15min | 2 tasks | 3 files |
| Phase 12 P09 | 35min | 3 tasks | 9 files |
| Phase 12 P10 | 10min | 3 tasks | 2 files |
| Phase 12 P11 | 35min | 3 tasks | 6 files |
| Phase 13 P01 | 21 min | 3 tasks | 9 files |
| Phase 13 P02 | 15 min | 3 tasks | 8 files |
| Phase 13 P03 | 15 min | 2 tasks | 3 files |
| Phase 13 P04 | 20 min | 3 tasks | 8 files |
| Phase 13 P05 | 11 min | 3 tasks | 2 files |
| Phase 13 P06 | 12 min | 3 tasks | 2 files |
| Phase 13 P07 | 20 min | 3 tasks | 5 files |
| Phase 13 P09 | 30 min | 3 tasks | 4 files |
| Phase 13 P10 | 15min | 3 tasks | 3 files |
| Phase 13 P08 | 35 min | 3 tasks | 4 files |
| Phase 13 P11 | 11 min | 3 tasks | 9 files |
| Phase 13.1 P01 | 40 min | 2 tasks | 12 files |
| Phase 13.1 P02 | 20min | 2 tasks | 5 files |
| Phase 13.1 P03 | 45min | 3 tasks | 7 files |
| Phase 13.1 P04 | 70min | 3 tasks | 8 files |
| Phase 13.1 P05 | 95min | 3 tasks | 5 files |
| Phase 13.1 P06 | 60min | 2 tasks | 2 files |
| Phase 13.1 P07 | 45min | 2 tasks | 2 files |
| Phase 13.1 P08 | 45 min | 3 tasks | 5 files |
| Phase 13.1 P09 | 3h | 3 tasks | 9 files |
| Phase 13.1 P10 | ~2h | 3 tasks | 10 files |
| Phase 13.1 P11 | 25min | 3 tasks | 7 files |
| Phase 17 P01 | 22 min | 3 tasks | 19 files |
| Phase 17 P02 | 30min | 2 tasks | 8 files |
| Phase 17 P03 | 12 min | 2 tasks | 3 files |
| Phase 17 P04 | 35min | 2 tasks | 7 files |
| Phase 17 P05 | 40 min | 3 tasks | 6 files |
| Phase 17 P06 | 45 min | 2 tasks | 4 files |
| Phase 17 P07 | 45 min | 2 tasks | 6 files |
| Phase 17 P08 | 30 min | 2 tasks | 3 files |
| Phase 17 P09 | 45 min | 2 tasks | 7 files |
| Phase 17 P10 | 25 min | 2 tasks | 4 files |
| Phase 17 P11 | 35 min | 2 tasks | 8 files |
| Phase 17 P12 | 32 min | 2 tasks | 8 files |
| Phase 17 P13 | 25 min | 3 tasks | 7 files |
| Phase 17 P14 | 25 min | 2 tasks | 2 files |
| Phase 17 P15 | 36 min | 2 tasks | 11 files |
| Phase 14 P01 | 20 min | 3 tasks | 16 files |
| Phase 14 P02 | 15min | 3 tasks | 4 files |
| Phase 14 P03 | 7 min | 2 tasks | 2 files |
| Phase 14 P04 | 35min | 3 tasks | 18 files |
| Phase 14 P05 | 25 min | 3 tasks | 4 files |
| Phase 14 P06 | 15 min | 2 tasks | 3 files |
| Phase 14 P07 | 36 min | 3 tasks | 6 files |
| Phase 14 P08 | 3h | 3 tasks | 6 files |
| Phase 14 P09 | 35 min | 3 tasks | 9 files |
| Phase 14 P10 | 20 min | 3 tasks | 6 files |
| Phase 14 P11 | about 1 h | 3 tasks | 29 files |
| Phase 14 P12 | 70min | 3 tasks | 19 files |
| Phase 14 P13 | 90 min | 3 tasks | 36 files |
| Phase 14 P14 | 3h | 2 tasks | 2 files |
| Phase 14 P15 | 2.5h | 3 tasks | 22 files |
| Phase 14 P16 | 90min | 3 tasks | 19 files |
| Phase 15 P01 | 25min | 2 tasks | 2 files |
| Phase 15 P02 | 40min | 2 tasks | 6 files |
| Phase 15 P03 | 40min | 3 tasks | 11 files |
| Phase 15 P04 | 45min | 3 tasks | 6 files |
| Phase 15 P05 | 105min | 3 tasks | 7 files |
| Phase 15 P06 | 1h 20m | 3 tasks | 7 files |
| Phase 15 P07 | 1h30m | 3 tasks | 3 files |
| Phase 15 P08 | 1h | 3 tasks | 10 files |
| Phase 15 P09 | 25min | 2 tasks | 6 files |
| Phase 15 P10 | 60min | 2 tasks | 3 files |
| Phase 15 P11 | 40min | 2 tasks | 5 files |
| Phase 15 P14 | 25min | 2 tasks | 6 files |
| Phase 15 P12 | 2h | 3 tasks | 21 files |
| Phase 15 P13 | 55min | 2 tasks | 3 files |
| Phase 15 P15 | ~2h | 3 tasks | 7 files |
| Phase 15 P16 | 10 min | 1 tasks | 2 files |
| Phase 15 P17 | 6 min | 3 tasks | 8 files |
| Phase 15 P18 | 8 min | 2 tasks | 3 files |
| Phase 14 P17 | 12 min | 3 tasks | 5 files |
| Phase 16 P01 | 14 min | 3 tasks | 4 files |
| Phase 16 P02 | 21 min | 2 tasks | 4 files |
| Phase 16 P03 | 14 min | 2 tasks | 3 files |
| Phase 16 P04 | 15 min | 3 tasks | 5 files |
| Phase 16 P05 | 9 min | 3 tasks | 11 files |
| Phase 16 P06 | two sessions | 3 tasks | 6 files |
| Phase 16 P07 | 15 min | 3 tasks | 3 files |
| Phase 16 P08 | 27 min | 3 tasks | 12 files |
| Phase 16 P09 | 10 min | 3 tasks | 4 files |
| Phase 16 P10 | 10 min | 3 tasks | 6 files |
| Phase 16 P11 | 24 min | 4 tasks | 9 files |
| Phase 16 P12 | n/a | 3 tasks | 4 files |
| Phase 16 P13 | single session | 2 tasks | 2 files |
| Phase 16 P14 | n/a | 3 tasks | 3 files |
| Phase 16 P15 | 22 min | 4 tasks | 3 files |
| Phase 16 P17 | 35min | 4 tasks | 4 files |
| Phase 16 P18 | 35 min | 3 tasks | 6 files |
| Phase 16 P35 | 12 min | 2 tasks | 5 files |
| Phase 16 P16 | 12min | 3 tasks | 4 files |
| Phase 16 P19 | 55min | 3 tasks | 5 files |
| Phase 16 P55 | 120min | 4 tasks | 40 files |
| Phase 16 P56 | 50min | 4 tasks | 40 files |
| Phase 16 P57 | 30 min | 3 tasks | 22 files |
| Phase 16 P58 | 70 min | 4 tasks | 12 files |
| Phase 16 P59 | not measured (suite 15 min) | 4 tasks | 15 files |
| Phase 16 P62 | not measured (two full suites of 15 min) | 3 tasks | 11 files |
| Phase 16 P60 | 3h | 4 tasks | 33 files |
| Phase 19 P01 | 28 min | 3 tasks | 8 files |
| Phase 19 P16 | about 30 min (commit clock, 13:45 to 14:13) | 3 tasks | 13 files |
| Phase 20 P01 | 15 min | 3 tasks | 7 files |
| Phase 20 P02 | 18 min | 3 tasks | 6 files |
| Phase 23 P01 | approx 1h | 3 tasks | 25 files |
| Phase 23 P02 | 35min | 2 tasks | 3 files |
| Phase 23 P08 | 1 session | 3 tasks | 12 files |
| Phase 23 P10 | 40min | 2 tasks | 3 files |
| Phase 23 P11 | 70min | 3 tasks | 5 files |
| Phase 23 P12 | 25min | 3 tasks | 9 files |
| Phase 24 P02 | 35min | 3 tasks | 21 files |
| Phase 24 P03 | ~1h | 3 tasks | 17 files |
| Phase 24 P01 | 1 session | 3 tasks | 2 files |
| Phase 24 P04 | 1 session | 3 tasks | 8 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 10 fine-grained phases follow evidence order (protocol → data → domain → core → risk → backtest → paper → approval/reconciliation → live → journal/kill-gate); EXEC-02/EXEC-03/OPS-01 harden in Phase 8 before any live order
- [Roadmap]: Strategy V1 family stays TBD (D012); no phase may declare a winner without backtest + out-of-sample evidence
- [Roadmap]: Paper forward-observation (3–6 mo wall-clock) is the schedule long pole; Phase 8 construction may overlap the soak
- [03-01]: D-10 enum values copy GLOSSARY §§2-9 verbatim; str+Enum mixin (not StrEnum) per research canonical pattern
- [03-01]: D-04 parameterSetHash = SHA256 over canonical JSON of normalized TOML body (sorted keys, compact separators, ensure_ascii, allow_nan=False)
- [03-01]: D-03 SignalId input list = strategyVersion + parameterSetId + symbol + source_timeframe + source_candle_close_utc + setup_fingerprint
- [03-01]: D-06 closed whitelist of strategy-semantic keys (STRATEGY_KEYS); unknown keys raise StrategyKeyOutsideRegistry
- [03-01]: D-12 float rejected loudly in canonical hash; TOML floats coerced to Decimal via str() before hashing
- [03-02]: D-10 ApprovalResult enum with PENDING, APPROVED, SKIPPED, EXPIRED (planner assumption flagged for user confirmation)
- [03-02]: D-11 Approval carries both result and explicit status (both ApprovalResult); status alone answers state
- [03-02]: D-12 __post_init__ validates Decimal typing on all money/qty/price fields and UTC awareness on all timestamps
- [03-02]: T-03-04 JournalEvent event_type and entity_type are validated non-empty strings; empty values rejected at construction
- [03-02]: DATA_MODEL §2.8 Fill has no status attribute (fills are events, not state)
- [03-02]: DATA_MODEL §2.7 Order carries three independent identifier fields (client_order_id, exchange_order_id, algo_client_id)
- [03-02]: Phase 4 deferral — setup_type, regime, order_role, side, position_side, order_type, time_in_force, event_type, entity_type stay as validated non-empty strings; Enum promotion deferred to Phase 4
- [03-03]: D-04/D-12 trailing precision preserved by reading raw TOML text and building Decimal from string form (1.50 stays Decimal('1.50'), not Decimal('1.5'))
- [03-03]: D-06 parameter names restricted to 7-bit ASCII so code-point sorting matches the documented canonical profile
- [03-03]: D-04 volatile sidecar fields (author, timestamp) never enter the hashed body; editing them does not change the hash
- [03-03]: D-06 check_strategy_key_outside_registry raises StrategyKeyOutsideRegistry if any whitelisted strategy key appears in ambient configuration
- [03-04]: D-02 seven ORM tables on the existing single Base; no separate Base per entity
- [03-04]: D-03 all PKs are content-hash IDs (String(128)); no auto-increment anywhere
- [03-04]: D-11 nullable columns ONLY for 'transition never happened' timestamps
- [03-04]: D-10 Enum translation via .value for storage and Enum(value) for restore; unknown values raise ValueError
- [03-04]: FillRow has unique constraint on (order_id, exchange_trade_id) to protect against duplicate fill ingestion
- [03-04]: CapturingSession pattern snapshots ORM instances BEFORE SQLite roundtrip so NUMERIC lossiness cannot hide mapper errors
- [04-03]: TP2 rule (04-03 checkpoint:decision option A): TP2 = entry_ref + 2 * minimum_rr * risk, where entry_ref = zone mid for LIMIT_ZONE plans
- [04-03]: Setup fingerprint key list: family id, variant codes, regime verdict + confirming 4H bar closes, trigger 1H bar close, zone bounds, ATR value at decision time
- [04-03]: source_timeframe spelling: setup timeframe using exact spelling from tests/fixtures/phase3/candles.csv (lowercase "1h", "4h", "1m"); 4H context folded into fingerprint
- [04-03]: SetupType tokens: TREND_PULLBACK_LONG/SHORT, BREAKOUT_RETEST_LONG/SHORT, RANGE_MR_LONG/SHORT
- [04-03]: Invalidation JSON schema: basis=CANDLE_CLOSE, level=stop_loss_price, break_distance_atr=sl_buffer_atr*ATR
- [04-03]: RR gate is a hard gate returning PlanResult(is_no_trade=True, reason_code=RR_TOO_LOW) — never a downgraded TP1-only plan
- [04-03]: PlanResult envelope: is_no_trade=True requires trade_plan=None; is_no_trade=False requires a TradePlan
- [04-03]: Registry whitelist extended with 7 family B/C keys (D-05); 4 keys assigned to INT_KEYS, rest to DECIMAL_KEYS
- [05-01]: D-05 RejectionReason enum promotion + GLOSSARY §9 update (one-way, locked in plan 05-01 checkpoint:decision)
- [05-01]: D-02 utilization gate = realized_risk / allowed_risk >= 0.6 (Pitfall 2 distinguishing case pinned by parity fixture)
- [05-01]: D-03 notional-check reference price = zone-mid entry_ref (consistent with SL-distance basis)
- [05-01]: D-04 candidate-plan risk ADDED to cap sums in aggregate/cluster caps (Pitfall 6 — exact-cap equality PASSES)
- [05-01]: D-05 new versioned parameter sets named baseline-v2.toml per family at strategy_version v2.0.0 (never ambient v1 edits)
- [05-01]: D-06 src/risk/ is dependency-free (stdlib + Decimal + src/core/_decimal.py only); no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic
- [05-01]: D-07 ConstraintSnapshot type guard rejects zero/negative step_size at construction (fail-closed at type level, not runtime)
- [05-02]: D-01 Gate order fixed (cluster → aggregate → count → daily) with first-failure-wins reason code (D-03)
- [05-02]: D-02 V1 conservative cluster rule: directionally-aligned BTC/ETH/SOL/XRP counted as one cluster (D-03 + RESEARCH A3)
- [05-02]: D-03 Candidate risk ADDED to cluster/aggregate sums; candidate NOT counted in position count (Pitfall 6 lock)
- [05-02]: D-04 Open positions sorted by (symbol, position_side) before aggregation for deterministic iteration (Pitfall 4)
- [05-02]: D-05 TTL subtraction between UTC-aware datetimes only; boundary at exactly TTL is PASS, one second over is STALE_CONSTRAINTS (Pitfall 3)
- [05-02]: D-06 Daily state machine NORMAL → WARNING → DAILY_STOP with inclusive boundaries; DAILY_STOP blocks, WARNING passes with state reported
- [05-02]: D-07 Fail-closed on None daily_loss_quote, positions_reconciled=False, stale constraint snapshot (D-04)
- [05-02]: D-08 parameter_set values are ABSOLUTE quote amounts in check_portfolio; caller converts registry rates to absolute amounts
- [06-01]: D-05 src/backtest/ is dependency-free (stdlib + Decimal + src/core/_decimal.py only); no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic
- [06-01]: D-01 Invalidation gate uses bar direction (bearish bar for LONG, bullish bar for SHORT) since SL < bar.low ≤ bar.close makes bar.close < SL structurally impossible
- [06-01]: D-02 Expiry check uses fixture now_utc (backtest wall-clock), NOT bar.close_time_utc — a backtest running past expiry means the limit window closed without a fill
- [Phase 06]: [06-02] D-01 assemble() uses parameter_set.parameter_set_hash from registry (fail closed on UnregisteredParameterSet); experiment_id binds to registry's authoritative hash
- [Phase 06]: [06-02] D-02 universe_hash sorts symbols alphabetically before sha256_hex for input-order stability
- [Phase 06]: [06-02] D-03 Baselines are NEW TOML files (baseline-no-trade-v1.toml minimum_rr=100; baseline-simple-trend-v1.toml looser config); runners delegate to simulator.run with the new parameter_set_id
- [Phase 06]: [06-02] D-05 STRING_KEYS set added alongside INT_KEYS and DECIMAL_KEYS; three string-valued cost keys validated as non-empty strings; partial_fill_fraction classified as DECIMAL_KEYS
- [Phase 06]: [06-02] D-04 Baselines filter simulator output to filled trades only (entry_kind in {ENTRY_FILLED, PARTIAL_FILL}); REJECT records are risk-rejection outcomes, not filled trades
- [Phase 07.1]: [07.1-01] D-01 gate lives in assemble(); canonical-hash-to-hash compare against registry cost-key slice; CostModelBindingMismatch on inequality (distinct from ExperimentReproducibilityBroken)
- [Phase 07.1]: [07.1-01] D-02 keep both representations (registry TOML + cost dict); shared assertion helper reused by assemble() — comparison logic exists exactly once
- [Phase 07.1]: [07.1-01] D-04 six-field identity tuple byte-stable; gate only shrinks the set of assemblable inputs, never changes what a consistent input hashes to
- [Phase 07.1]: [07.1-01] D-03 fail closed with dedicated CostModelBindingMismatch exception; absent slice keys propagate as bare KeyError from build_cost_model
- [Phase 07.1]: [07.1-01] D-05 phase6 fixtures stay byte-identical (grandfathered); tests that call assemble() migrate to baseline-v3 (7-key set); new tests/fixtures/phase7.1/ binding fixtures
- [Phase 07.1]: [07.1-02] D-05 grandfather log in test module header documents phase6 audit verdict (8 missing-keys + 2 spelling); bare KeyError propagates from build_cost_model for missing slice keys (never translated, never skipped, never ExperimentReproducibilityBroken); comparison is hash-string only (never Decimal value equality)
- [Phase 07]: [07-01] D-01 paper loop is the realtime mirror of the backtest — identical evaluate→plan→evaluate_risk chain, no paper-local setup logic, no simplified sizing, no cost-free path
- [Phase 07]: [07-01] D-02 double closed-candle gate is structural (x=True AND close_time_utc <= now_utc), not a log warning; forming updates and future-close markers MUST NOT reach evaluate
- [Phase 07]: [07-01] D-03 feature-validity gate short-circuits the whole loop when either stream lacks EMA200 warmup; feed-freshness gate is per-event (not latched) so a fresh event after a stale one resumes evaluation without restart
- [Phase 07]: [07-01] D-04 SDK WS surface isolated to src/adapters/paper_ws.py; src/paper/loop.py imports nothing from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + Decimal + src/core/_decimal.py only
- [Phase 07]: [07-01] D-05 STALENESS_THRESHOLD_SECONDS=60 (1H cadence) and WARMUP_MIN_BARS=200 (EMA200) exported as module constants for tests and downstream consumers
- [Phase 07]: [07-02] D-01 resync drops forming candles (x=False or close_time_utc > now_utc) before the open_time_utc diff — never synthesizes; unrecoverable windows stay explicit gap records matching CollectorGap shape
- [Phase 07]: [07-02] D-02 24h server-initiated rotation triggers on_disconnect(scheduled=True) — NO reconnect attempt (WS still connected), only resubscribe + resync from last-seen close; only unsolicited drops get the bounded reconnect path
- [Phase 07]: [07-02] D-03 parity gate is a divergence tripwire — replay helper builds paper loop inputs from strategy_bars bar by bar; projection reduces both outputs to (signal_id, reason_code) tuples; any divergence is an engine incident fixed in the shared engine, never at the paper call site
- [Phase 07]: [07-02] D-04 prefix-invariance test guards D-02 determinism — verdict for bar N must depend only on bars [0..N]; appending a post-horizon bar must not change earlier verdicts
- [Phase 07]: [07-02] D-05 src/paper/resync.py and src/paper/supervisor.py import only stdlib + tenacity + structlog + sibling modules; no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic leaks
- [Phase 07]: [07-02] FLAGGED ASSUMPTION (PAPER-01 unclassified): bounded-retry ceilings (RESYNC_MAX_ATTEMPTS=7, RESYNC_MAX_DELAY_SECONDS=120, SUPERVISOR_MAX_ATTEMPTS=7, SUPERVISOR_MAX_DELAY_SECONDS=120) are module-level named constants; operator tunes them only before a soak epoch starts, never mid-epoch
- [Phase 07]: [07-04] D-04 frozen: pin_stream_epoch fails closed on CostModelBindingMismatch; check_registry_unchanged re-hashes without rewriting old pinned hashes; pinned hash string is append-only history (per epoch_id)
- [Phase 07]: [07-04] D-05 frozen: SIMULATE-notify is journal-first send-only with bounded tenacity retry (NOTIFY_MAX_ATTEMPTS=3, NOTIFY_MAX_DELAY_SECONDS=30); callbacks are inert labels (SIMULATE-recorded / SKIP (Phase 8)); never auto-approves on notification failure
- [Phase 07]: [07-04] Telegram isolation: only src/adapters/telegram_notify.py imports python-telegram-bot; src/paper/notify.py consumes a Protocol-typed TelegramBot with test-injected fake
- [Phase 07]: [07-04] FLAGGED ASSUMPTION (PAPER-03 unclassified): freeze-monitor tick cadence (hourly cron) and minimum-evidence signal-frequency gate are researcher-set values recorded in the soak log, not code defaults
- [Phase 07]: [07-04] BLOCKED-FOLLOW-UP: PaperWsAdapter + PaperSupervisor have no SDK connect path wired (0 live events in 30s); Wave 1/2 tests use injected fakes. Soak must NOT start until live WS smoke passes. Routed to executor as separate plan.
- [Phase 8]: [08-01] D-01 fixed gate order enforced: chat -> expiry -> plan-hash -> version/parameter-set -> token; chat gate runs BEFORE any state lookup (security-critical invariant)
- [Phase 8]: [08-01] D-02 token-hash is the idempotency key; raw token never persisted or logged; SHA-256 hex form stored on Approval.approval_token_hash
- [Phase 8]: [08-01] D-03 constant-time compare via hmac.compare_digest prevents timing attacks on token verification
- [Phase 8]: [08-01] D-04 expiry boundary inclusive: now_utc >= expiry_utc is expired; one second before expiry is still approvable
- [Phase 8]: [08-01] D-05 src/approval/ is dependency-free (stdlib + src/domain/* only); no telegram, binance_sdk, sqlalchemy, pydantic, polars imports; zero float( usage for money/qty/price fields
- [Phase 8]: [08-03] D-01 ROLE_CODES maps exactly the OrderRole vocabulary (ENTRY, STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2) to distinct 2-char codes (EN, SL, T1, T2); the table is the only place role-code literals appear
- [Phase 8]: [08-03] D-02 derive_client_order_id and derive_algo_client_id are pure functions of (plan_hash, role) using stdlib only — no float, no locale-dependent string conversion
- [Phase 8]: [08-03] D-03 Pinned ID shape: client_order_id = 'x-' (2) + plan_hash[:32] (32) + role_code (2) = 36 chars; algo_client_id = 'xa-' (3) + plan_hash[:31] (31) + role_code (2) = 36 chars
- [Phase 8]: [08-03] D-04 Charset is a strict subset of the Binance client-order-ID rule (<=36 chars, ASCII alnum + hyphen/underscore): [0-9a-f-] plus uppercase role codes
- [Phase 8]: [08-03] D-05 Unknown role raises ValueError with the canonical vocabulary listed in the message — no fallback code, no silent default
- [Phase 8]: [08-03] D-06 plan_hash slice is the first N hex chars of the canonical 64-char SHA-256 plan hash — deterministic across processes and Python versions
- [Phase 8]: [08-03] D-07 Retry/restart/replay determinism proven: same call twice, importlib.reload, and interleaving other plans all yield byte-identical IDs
- [Phase 8]: [08-04] D-01 Five divergence kinds: ORPHAN_PROTECTIVE (sweeper target), ENTRY_WITHOUT_PROTECTIVE (SAFE_MODE trigger, never swept), UNSYNCED_NORMAL, UNSYNCED_ALGO, UNSYNCED_POSITION (each drives SAFE_MODE without cancel)
- [Phase 8]: [08-04] D-02 ORPHAN_PROTECTIVE classification: local algo protective (SL/TP1/TP2) with no matching local position AND no exchange position — regardless of whether the algo still matches the exchange truth
- [Phase 8]: [08-04] D-03 Sweeper requires authoritative position-zero verification (T-8-30): two consecutive zero reads from the position_verifier callable; a single non-zero read blocks the cancel
- [Phase 8]: [08-04] D-04 Sweeper uses query-by-ID-first posture (T-8-32): query_algo_order_by_client probe before cancel; not-found probe is treated as a successful prior sweep
- [Phase 8]: [08-04] D-05 Sweeper journals pre-image BEFORE the cancel call and post-image AFTER (D-05 extended journal-first ordering); the audit trail is the safety net
- [Phase 8]: [08-04] D-06 SAFE_MODE enters on any divergence (idempotent re-entry); exits only on a fresh clean three-source compare PLUS a journaled SAFE_MODE_EXIT event (Pitfall 4)
- [Phase 8]: [08-04] D-07 SAFE_MODE_TICK_SECONDS=60 with operator-tunable-before-soak semantics (FLAGGED ASSUMPTION, RECON-01 unclassified); 60s per RESEARCH A2
- [Phase 8]: [08-04] D-08 Adapter extension is the only module importing the Binance SDK for reconciliation calls; src/reconcile/ consumes Protocol-typed surfaces
- [Phase 8]: [08-04] D-09 SDK 17.3.1 -> 17.4.0 delta (per RESEARCH Open Question 2 closed): no public REST method-signature change in any of the seven reconciler methods; ALGO_UPDATE.o.rm field semantics change is WS-side and out of scope
- [Phase 8]: [08-04] D-10 Bounded-tenacity cancel ceilings (RECONCILER_CANCEL_MAX_ATTEMPTS=3, RECONCILER_CANCEL_MAX_DELAY_SECONDS=30) mirror the notify/resync precedent; transient-only retry filter
- [Phase 8]: [08-04] D-11 Already-canceled-as-success posture: SDK error code -2011 (UNKNOWN_ORDER) on cancel is treated as success because the post-condition is satisfied
- [Phase 8]: [08-04] D-12 Zero-amount positions filtered out of snapshot_positions: Binance semantics is position_amt == 0 means no position
- [Phase 8]: [08-02] D-08-02-01 format_approve is PTB-free and mirrors format_simulate posture; lives in telegram_notify.py so paper-core can reuse it without adapter violation
- [Phase 8]: [08-02] D-08-02-06 receiver persists ShortIdMappingRow in the SAME transaction as the Approval row transition via injected save_atomic(approval, mapping); replay paths pass mapping=None
- [Phase 8]: [08-02] D-08-02-10 LIVE-TAP GATE PENDING: TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID not provisioned in this environment; operator must run real APPROVE + SKIP tap + unknown-chat rejection before plan 08-02 can be marked complete
- [Phase 8]: [08-05] D-01 Canonical 8-drill vocabulary pinned in DRILL_NAMES tuple (unprotected, orphan, duplicate, api_down, stale_feed, db_failure, manual_close, restore); tuple order is part of the acceptance contract
- [Phase 8]: [08-05] D-02 Drill harness drives 08-01 approval core, 08-02 receiver seam, and 08-04 reconciler/sweeper/SAFE_MODE through Protocol-typed surfaces; tests inject fakes; no Binance SDK or PTB leakage
- [Phase 8]: [08-05] D-03 Double-run determinism: caller-supplied now_utc sequence (never wall-clock); repeat runs produce byte-identical ordered outcome names and payloads
- [Phase 8]: [08-05] D-04 SAFE_MODE exit rehearsed only through the restore drill (Pitfall 4: a boolean flip without both a clean compare AND a journaled restore event is rejected)
- [Phase 09]: [09-04] health.py: ten fail-closed probes journal HEALTH_CHECK; any FAIL blocks enablement via run_health_checks aggregate
- [Phase 09]: [09-04] require_protective_confirmation is single source of truth for SL/TP1/TP2 confirmed check; composes with SafeModeController on any gap, never places rescue protection
- [Phase 09]: [09-04] attach_protectives_to_fill places SL then TP1 then TP2 in fixed order; unconfirmed leg halts immediately with zero rescue placement
- [Phase 09]: [09-04] LIVE5_SYMBOLS scope guard raises ValueError before any adapter call across execute_approved_plan, attach, expiry, cancel, and emergency-close paths
- [Phase 09]: [09-04] Task 3 (testnet plus credential plus LIVE-TAP GATE) is gate=blocking-human — plan BLOCKED pending operator attestation; no live order exists
- [Phase 10]: Evidence kinds are never pooled and every TradeOutcome carries strategy_version + parameter_set_hash (analytics core types)
- [Phase 10]: Estimate carries n and n_valued; interval_absent is an explicit marker when n_valued < 2, otherwise a seeded Phase-6 stationary-block-bootstrap interval
- [Phase 10]: ExcursionSection seed ordinals: measures 0-6 in EXCURSION_MEASURES order, diagnostics 7-9; per_trade sorted by trade_id, bootstrap input in (exit_time, trade_id) order
- [Phase 10]: Analytics reuses Phase-6 private report helpers intentionally (RESEARCH P7), guarded by fixture digests; time arithmetic uses integer microseconds, never total_seconds
- [Phase 10]: D030: D013 firing rule (>=3 independently specified families AND >=6 calendar months since freeze AND none passing) recorded as new decision + protocol v1.0.1 clarification; Status/Frozen-on/D029 untouched; amendment class flagged for user confirmation
- [Phase 10]: KillGateState (WITHIN_BUDGET, PASSING_CANDIDATE, INSUFFICIENT_EDGE) lives in src/domain/enums.py, GLOSSARY 8.2 canonical
- [Phase 10]: 10-03: approved_at_utc for live records is set only for APPROVED approvals; SKIPPED/EXPIRED acted_at is never an approval time — Prevents mislabelled skip times polluting DELIVERY_TO_APPROVED/SIGNAL_TO_APPROVED legs (T-10-07)
- [Phase 10]: 10-03: paper sections carry synthetic_lag_seconds (imported APPROVAL_DELAY_LAG_SECONDS); SIGNAL_TO_SEEN is always INCOMPLETE(NO_SEEN_TIMESTAMP); Approval.requested_at_utc is a delivery-request proxy — No seen timestamp is journaled and paper approval time is a constant; honesty over imputation (D-02, RESEARCH P1/P2)
- [Phase 10]: 10-04: slice time bases pinned - month/quarter from exit time, session from entry-time UTC bands ASIA 00-08/EUROPE 08-16/US 16-24; missing basis time -> INCOMPLETE, absent tag -> UNKNOWN (D-02, flagged A1/A4)
- [Phase 10]: 10-04: R-valued requires R and an exit time; low_n is a display flag on n_r_valued only, never an acceptance gate; NO_TRADE reason-to-category mapping is a documented assumption with UNMAPPED counted
- [Phase 10]: 10-05: kill-gate decision checkpoint auto-approved (pre-approved by locked CONTEXT D-03, option-deterministic-journaled); KILL_GATE_EVALUATION contract fixed one-way: 24-key constant payload, id prefix kill_gate, entity KILL_GATE_D013, reopen/sticky fields present from plan 05 — Only counted families (independent, TESTED_*, decided_at >= cycle start) drive the verdict; TESTED_* is constructible only from a recorded decision_ref plus Development/Validation experiment ids; evaluator never compares metrics to thresholds
- [Phase 10]: 10-06: LIVE_NET_PNL_SEMANTICS_VERIFIED stays False (Binance realizedPnl/commission semantics not verifiable from official docs on 2026-09-29); live R is INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS) until a human records a docs citation — Project rule: exchange semantics never taken from memory; fail closed
- [Phase 10]: 10-06: approval-delay reports are descriptive only; delay buckets and measured_delay are LIVE-only, PAPER keeps the SYNTHETIC LAG label and APPROVAL_DELAY_LAG_SECONDS is unchanged — D-02 / RESEARCH P2, Open Question 4
- [Phase 10]: 10-07: Post-reset kill-gate semantics (FLAGGED PLANNER DECISION, D013 silent): cycle clock restarts at the latest valid reset time, only decisions dated on/after it count, reopening decision_ref/operator recorded; INSUFFICIENT_EDGE sticky until an explicit human KILL_GATE_QUESTION_APPROVED after the latest terminal — D-03 never auto-clears; evaluator only reads resets, never writes or infers them
- [Phase 10]: 10-07: enable() requires an evaluated kill_gate_state and refuses INSUFFICIENT_EDGE/non-KillGateState before any journal write; registration blocked in CI via docs/research/kill_gate_decisions.json recorded_terminal tripwire; enable journal payload unchanged — Phase 9 D-04 + Phase 10 D-03 fail-closed; CI cannot read the journal
- [Phase 10]: 10-08: ReportInputs.clock is required; provenance keeps per-kind identity (by_evidence) and tags experiments by evidence slot; family gate facts for unknown families raise; posture tie ordering follows the plan total key (ENABLED after DISABLED at the same instant, display-only)
- [Phase 10]: 10-09: family sheet hash normalizes CRLF to LF so digests match the committed blob across checkouts; unknown CANDIDATE parameter_set_hashes are listed in unknown_experiment_ids, never guessed onto a family; the only analytics write is one ON CONFLICT DO NOTHING KILL_GATE_EVALUATION append — Determinism across Windows autocrlf and CI checkouts; fail-closed family mapping (D-03); SELECT-only reader (T-10-28)
- [Phase 10]: 10-10: Section 1 uses numbered H3 blocks (1.1 budget ... 1.9 enablement effect); md_cell also escapes backslash and drops Unicode format/control characters; golden pinned with a -text gitattribute
- [Phase 10]: 10-10: SECTION_TITLES lives in render_common and is re-exported from render; requirements JRN-01/GOV-01 left unmarked (ready-ids 0/2)
- [Phase 10]: 10-11: Live-5 line built from sorted LIVE5_SYMBOLS (single source) instead of a second hard-coded order
- [Phase 10]: 10-11: verify_render recomputes the report digest only when given the report; without it it checks the Markdown SHA-256 and header/sidecar digest agreement
- [Phase 10]: 10-11: Telegram pointer is a formatter only; no send wired (notify Protocol is inline-keyboard only, plain-text send deferred per D-04)
- [Phase 10]: 10-12: report CLI is read-only by construction; the only write is one guarded, idempotent KILL_GATE_EVALUATION append via --record after both files exist — D-03/D-05: journal append stays an explicit separate step; ON CONFLICT DO NOTHING on the content-hash id makes replays no-ops
- [Phase 10]: 10-12: database failures surface as exception type names only; DATABASE_URL is read once and passed only to the session factory — RESEARCH V7: no credential or request text in stdout, stderr, reports or sidecars
- [Phase 10]: 10-12: CLI runs asyncio on SelectorEventLoop on Windows and disposes the engine per run — psycopg async cannot use the Proactor loop; read and record use separate asyncio.run calls
- [Phase 11]: D043: research protocol v1.1.0 frozen with D032 pre-registration (100/30 trade floor, N=25 Holm-Bonferroni per family, last-20% single-use holdout); Frozen-on unchanged so the D013 clock is not restarted
- [Phase 11]: 11-02: working_type is a closed-set registry string key (MARK_PRICE/CONTRACT_PRICE), outside COST_KEYS; D036-D038 delivered as five new v3.0.0 sets, old params files byte-locked and all 15 sets pinned
- [Phase 11]: 11-03: research-universe manifest is DRAFT with no symbols under docs/research/universe; Phase 13 freezes it with a sha256_hex content hash over sorted symbols
- [Phase 11]: 11-04: liquidation buffer stays a registry parameter (value chosen in Phase 22); canonical quantization order lives on one labelled line in RISK_MANAGEMENT s11 (D031)
- [Phase 11]: 11-06: TradingView cannot sign requests; docs describe secret URL path + source-IP allow-list + 3s ack + dedupe + normalise + 2FA (F-052); V1 has no webhook endpoint
- [Phase 11]: 11-06: single canonical quantization order restated by pointer in PROJECT.md and AGENTS.md (D031); generated AGENTS.md rows guarded by drift gates AU-03/AU-05
- [Phase 11]: 11-05: 200 conditional-order limit documented account-wide from the dated change-log (2025-12-29); pages not retrievable are registered as not fetched and keep verify markers
- [Phase 11]: 11-07: GLOSSARY canonical reason codes are the 17 code-referenced plus reserved INSUFFICIENT_MARGIN; five synonyms are deprecated aliases kept in the enum until the Phase 12 cleanup — D-15: no rename in Phase 11; gates GL-01..GL-06 tie the glossary to src/ and the enum
- [Phase 11]: 11-07: 13 new requirement IDs registered (mapped to phases 13-26, Pending); D044 records the alignment and follow-ups, D045 records exclusions (trades, feature_snapshots, experiment_runs not built; no application-level secret encryption in V1) — D-16: silent drops not allowed; F-128 covered by OPS-02
- [Phase 12]: 12-01: RejectionReason reduced to 20 codes (STOP_TOO_TIGHT, COST_TO_RISK_EXCEEDED added; five aliases retired, GLOSSARY 9.2 is a removal record; GL-01/GL-03 keep them out)
- [Phase 12]: 12-02: Phase 12 cost-guard keys are optional registry keys; exit_slippage_rate stays outside the 7-key COST_KEYS so existing cost_model_hash values do not move; five v4.0.0 sets pinned and gated by PA-07
- [Phase 12]: 12-03: cost_model_hash canonicalizes numeric values to plain normalized text (D-15, D047); exit_slippage_rate joins the hash by presence, COST_KEYS stays 7 keys; legacy models refused for sizing
- [Phase 12]: 12-04: Phase 6 fixtures regenerated with BAR_HALF_RANGE 0.80 (stops about 1.1 percent) on baseline-v5 / v3 sets; guard clearance pre-flight uses independent literal arithmetic
- [Phase 12]: 12-05: adapter keeps its own 0.01 commission-rate ceiling (imports nothing from src); commissionRate SOURCES row stays MEDIUM (official page not read directly)
- [Phase 12]: 12-06: risk sizing entry is the adverse zone edge (LONG entry_max, SHORT entry_min); zone mid stays the quantizer notional reference (supersedes Phase 5 D-02 for sizing; DECISIONS D046 by 12-11)
- [Phase 12]: 12-07: Phase 5 portfolio test helper runs shared size_and_quantize; candidate risks hand-derived in DERIVATIONS.md
- [Phase 12]: 12-08: legacy modeled_costs_per_unit key rejected explicitly in the live cost-rate gate; PARAMETER fee source is NO_TRADE UNCERTAIN_ACCOUNT_STATE before evaluate_risk
- [Phase 12]: 12-09: EOD exits use exit_slippage_rate (market-style close, D046 assumption A2); TP1 uses expected_slippage; unknown exit_kind refused
- [Phase 12]: 12-09: guard rates read at the risk stage in both modes via guard_rates_from_params (legacy sets fail closed, paper fixtures that never reach risk keep legacy sets)
- [Phase 12]: 12-10: property test uses zero loss tolerance; vacuity proof kept as a permanent harness test
- [Phase 12]: D046-D048 recorded; max_cost_to_risk 0.15 implies ~0.79 percent min stop, ratification pending
- [Phase 13]: 13-01: collector universe comes from docs/research/universe/collect-list-v1.toml; any list defect exits 2 (healthcheck 1) with no live-5 fallback
- [Phase 13]: 13-01: collect list is an operational input (no FROZEN semantics, no hash, not under params/); proposer keeps only TRADING PERPETUAL USDT, ranks by Decimal quoteVolume with symbol tie-break
- [Phase 13]: 13-02: backfill publishes only whole closed UTC days (effective end = min(end_ms, current UTC day start)); partial days held and counted, terminal_end only for a closed past end
- [Phase 13]: 13-02: Parquet publish is atomic (same-dir tmp, fsync, exists check, bounded os.replace retry); zero-trade bars accepted as telemetry; more than 8 fractional digits or non-finite Decimal is a structural reject
- [Phase 13]: 13-03: supervisor verification backfill skips pairs whose first pass raised; last-close cursor is monotonic via lock-guarded _advance_last_close gating WS dispatch and backfill
- [Phase 13]: Mark-price klines are a separate immutable dataset under data/raw/dataset=mark_klines (invisible to candles_v1, inside the backup root); rows carry price_tick_count and no volume or trade_count (D-11, D-29)
- [Phase 13]: Paginator is dataset-generic via DatasetSpec (TRADE_DATASET default, MARK_DATASET); CursorStore.dataset namespaces cursor files and a mismatched cursor store is refused
- [Phase 13]: Only an empty markPrice string maps to None in historical funding rows; malformed values still raise; deliveryDate exposed as SymbolFilters.delivery_date_ms with no migration (D-26)
- [Phase 13]: 13-05: archive CSV header accepted only as exactly open_time; both open_time and close_time must be 13-digit ms (fail closed)
- [Phase 13]: 13-05: checksum 404 disambiguated by probing zip status only (zip 404 -> ArchiveNotFound, zip 200 -> ArchiveChecksumMissing); monthly-404 falls back to daily zips, missing days skipped never interpolated
- [Phase 13]: 13-06: funding-history walk treats end_ms as inclusive (cursor <= end_ms); a page with no forward progress stops the symbol with a warning
- [Phase 13]: 13-06: clock probe is warn-only (>1000 ms warns, failure logs and returns None); fail-closed clock checks stay Phase 18, chrony Phase 13.1
- [Phase 13]: 13-07: backfill windows are per (dataset, symbol, interval); CLI calls backfill_universe once per (dataset, interval) with the window start as symbol floor and window end as symbol cap; mark windows copy trade windows
- [Phase 13]: 13-07: symbol absent from exchangeInfo or non-TRADING without deliveryDate gets DELIVERY_UNKNOWN and no window (fail closed); only the 13-08 archive fallback can bound it
- [Phase 13]: 13-07: refresh_symbol_metadata raises MetadataWidthError (ValueError) for universe rows with contract_type/status over 16 chars; CLI prints exception type names only, plus width-error message (symbol and field)
- [Phase 13]: 13-09: dataset_id = sha256 over sorted posix-relative path + file-bytes sha256 of exactly the files read; re-written datasets are new datasets — Reproducible experiment identity (BKTS-02, D-18); byte changes after a Polars upgrade must be visible
- [Phase 13]: 13-09: unresolved gap defined once in coverage.gap_ranges_for_files; builder fails closed (CaseInputGapError), allow_gaps recorded on the output — D-19: never pad or interpolate; acknowledged holes stay visible with the dataset
- [Phase 13]: [13-10] Freeze report proposal_sha256 covers the full report body (candidates, ranking, unrankable, availability), not only the ranking
- [Phase 13]: [13-10] Only -1121 switches REST to the archive; rate limits retry then fail the run; other REST errors fail closed; archive symbols listed with another contract type in exchangeInfo (TRADIFI) are never readmitted
- [Phase 13]: [13-10] Archive-only proposed symbols have no mark source (REST only): they stay proposed and are flagged UNAVAILABLE in the review for the operator (13-12)
- [Phase 13]: 13-08: sufficiency report checks data depth only; TRADE_FLOOR_NOTE states the D043 floor is unmeasurable until the Phase 14 simulator; exit 3 only for NOT_BACKFILLED, GAP, UNAVAILABLE
- [Phase 13]: 13-08: archive fallback is lazy per symbol (REST -1121 or not in exchangeInfo), mark only from REST, provenance persisted in <cursor-root>/_sources.json; archive-capped windows trimmed to the last archived bar in the report
- [Phase 13]: 13-08: 1m coverage printed per protocol split block on the 1h/4h timeline; extending 1m beyond 12 months stays a user decision (D-21)
- [Phase 13]: D049 records Phase 13 data foundation; case-input builder lives in src/data/case_input.py (D-22 supersedes D-17); 1m depth stays 12 months pending the sufficiency report (D-21)
- [Phase 13]: Decision-alignment requirements gate maps OPS-06 to Phase 13.1 (string phases); Phase 13 exchange facts recorded MEDIUM where only SDK docstring or live probe was available
- [Phase 13.1]: 13.1-01: ruff format repo-wide in own commit; src/risk/portfolio.py F841 per-file ignore (risk code untouched); docker marker + TRADING_CI_STRICT-aware infra_skip
- [Phase 13.1]: 13.1-03: compose project name trading and runtime UID 10001 fixed; ops-image postgresql-client-17 floats within major 17 (sole exception to D-05)
- [Phase 13.1]: 13.1-04: structlog output becomes JSON after configure_logging(); redaction is value-based (env names containing PASSWORD/SECRET/TOKEN/API_KEY/ACCESS_KEY/CRYPT/PRIVATE, length >= 8) plus shape and key-name rules; alembic db-upgrade intentionally not wired
- [Phase 13.1]: [13.1-06] restore order verify -> checks -> pg_restore -> Parquet copy -> alembic upgrade head; all refusals precede the first destructive step; password only via PGPASSWORD
- [Phase 13.1]: 13.1-07: cutover report exit 2 covers all input/runtime failures; gap-measurement errors cannot hide proven data loss (exit 1)
- [Phase 13.1]: 13.1-08: upload order is parquet, pg.dump, manifest.json, cryptcheck so a snapshot is complete only after its dependencies exist; retention counts periods that have a snapshot; --init-remote also requires an empty raw bucket
- [Phase 13.1]: 13.1-09: migrate.sh refuses to start when cutover/pg.dump already exists on either side (append-only rsync would silently reuse stale artifacts); first-tick wait uses new src.ops.cutover advanced subcommand
- [Phase 13.1]: D050 records Phase 13.1; runbook step tables and pin tables are test-enforced against the repository files
- [Phase 17]: 17-01 Task 1 auto-resolved to locked: sync SQLAlchemy repositories (D-01) and execution_intents PK (approval_id, role) with OrderRole role values, explicit approvals.consumption_status, UNIQUE(trade_plan_id, role) (D-13, C2, C8, Open Q5); record in D051 — One-way door gated in auto mode per plan; Phases 18-24 and Phase 20 reconciliation bind to these signatures
- [Phase 17]: 17-01 Pre-placement NO_TRADE never consumes the approval; consumption only immediately before place_entry (research Open Q1); stored-outcome lookup moves ahead of expiry gate in plan 11 — Keeps a retried APPROVE able to re-run gates until placement; revisit in Phase 19
- [Phase 17]: 17-02: positions.quantity gets no sign CHECK (position_amt is signed; C4 refinement for D051) — src/adapters/binance_usdm.py documents position_amt as negative for SHORT in one-way mode; >= 0 would reject a legal short
- [Phase 17]: 17-02: terminal-status triggers use research draft terminal sets (signals, trade_plans, orders, positions, approvals, execution_intents); plan 10 cross-checks vs transitions.py — auto-mode default C3; DB rule mirrors Python transition tables
- [Phase 17]: 17-02: all new 0004 constraints/indexes are PostgreSQL-only on the ORM via ddl_if; 18 pre-existing indexes declared plainly — keeps SQLite create_all fixture suites unchanged; alembic compare_metadata shows zero diff
- [Phase 17]: 17-03: Transition tables authored from research draft as auto-mode default (C3); unchanged state is not a transition; APPROVED->SUPERSEDED for TradePlan illegal (open point, D051)
- [Phase 17]: 17-04: journal ids are pure functions (content hash or callback_query.id correlation); missing callback query id fails closed
- [Phase 17]: Plan 17-05: persisted plan Decimals quantized to NUMERIC(38,18) with ROUND_HALF_EVEN before hashing; _plan_hash hashes canonical decimal text (D-12, one-way); phase4 expected_plans.json regenerated (inventory in 17-05-SUMMARY for D051)
- [Phase 17]: 17-06: max_quantity counts as a filter value for snapshot completeness (None => INCOMPLETE, invalid for live); snapshot JSON carries snapshot_schema_version 1 — Fail closed (D-19); versionable evidence (D-18)
- [Phase 17]: 17-07: no ORM/migration drift found; parity enforced by compare_metadata (checkconstraint_byname) plus catalog assertions for predicates, CHECK literals and triggers; async make_engine pins timezone=UTC; alembic floor 1.19.2
- [Phase 17]: 17-08: PgJournalStore conflict rule compares identity fields and payload only (not occurred_at_utc/created_at_utc); JournalConflict names field names, never payload. Journal-outage behavior pinned, not fixed: disable stays enabled (F-702) and emergency_manual_close issues zero exchange cancels when the journal is down (unsafe, Phase 20)
- [Phase 17]: 17-09: insert_pending replay compares request identity fields only; pair-uniqueness violation on short_id_mapping maps to ShortIdRebindingRefused
- [Phase 17]: 17-10: idempotent entity inserts compare only non-evolving columns (replay after the entity advanced is a no-op, a different entity is RowConflict); DB terminal triggers proven equal to transitions.TERMINAL_STATES on PostgreSQL; transition of a missing row is RowConflict
- [Phase 17]: 17-11: SL write-ahead failure policy - on a store failure after the entry may exist enter SAFE_MODE DB_FAILURE once, skip later store writes, still place the SL by its deterministic algo id, return RECONCILIATION_REQUIRED (protection outranks the audit row, D034); for D051
- [Phase 17]: 17-11: gate order is identity, then stored-outcome replay, then expiry (Open Q2); pre-placement store failures return NO_TRADE without SAFE_MODE (IntentStateConflict at consume is INVALIDATED); for D051
- [Phase 17]: 17-12: restart recovery probes by deterministic id only (found -> ACKED, young absent -> REJECTED, error/indeterminate/at-or-past 3 days stays UNKNOWN) and enters SAFE_MODE UNRESOLVED_EXECUTION_INTENT once; consume/protective-insert race loser returns False when the same (approval_id, role) row exists (secondary unique arbiter); for D051
- [Phase 17]: 17-13: snapshot reads verify the denormalized columns as well as the sha256; system state values are str/bool/None only; state_snapshot normalizes entry/enable fields to None when off/disabled and rehydrate rejects inconsistent or malformed state (ValueError); for D051 — Fail closed on tampered evidence (D-18/D-19, T-17-35) and on restart state that could silently read SAFE_MODE as off (D-22, C14, T-17-34)
- [Phase 17]: 17-14: no defect found by the end-to-end replay and redelivery tests, so no production file changed; after plan expiry the callback layer answers APPROVAL_EXPIRED while execute_approved_plan handed the stored approval returns the stored outcome; for D051
- [Phase 17]: D051 recorded (Phase 17 persistence layer); the six transition tables stay an auto-mode default awaiting user confirmation (DOMN-04 manual check) — Research C3: tables were authored in Phase 17, GLOSSARY 11, user to confirm
- [Phase 14]: 14-01: TP1_QUANTITY_FRACTION is the code constant Decimal('0.5') in src/backtest/semantics.py covered by SIMULATOR_SEMANTICS_VERSION 2.0.0 (D-27), not a registry tunable — User-resolved 2026-10-04; keeps params/ untouched and ties the policy to simulator identity
- [Phase 14]: 14-01: validate_trade_record requires planned_quantity on filled records and ListMinuteSource raises on an unknown symbol (fail closed) — A missing planned quantity or series cannot be compared or read as no price moves
- [Phase 14]: 14-02: advance() raises when a bar does not close at end_inclusive; invalidation skipped when the window end is after expiry (EXPIRED wins); cancel_plan accepts only EXPIRED/INVALIDATION_CANCEL/DAILY_STOP_CANCEL on RESTING plans
- [Phase 14]: 14-03: funding coverage requires a funding instant at or before the window start and at or after its end with spacing at most 8h+60s; allow-gaps cover a hole only by full same-symbol containment and are recorded on the result
- [Phase 14]: 14-04: funding_convention is a presence-driven string cost key appended by cost_slice for sizeable sets; funding data identity rides in data_snapshot_id plus allowed_gaps (D-36)
- [Phase 14]: 14-05: exhausted equity (<= 0) at a UTC day roll resolves the rate thresholds to 0 (DAILY_STOP, all caps reject) instead of raising; equity_positive lets the engine stop before AccountState raises
- [Phase 14]: 14-05: point-in-time constraints clamp the snapshot metadata_observed_at_utc to the bar close (ttl timedelta(0)) and return the true observed_at and an extrapolated flag separately; src/risk untouched
- [Phase 14]: 14-06: live R denominator is realized_risk_for_fill over an explicit sized_risks input (D-29, not persisted); absent input stays INCOMPLETE(NO_RISK_VALUE), overfill is MALFORMED_ROW
- [Phase 14]: Plan 14-07: a hole in a strategy bar's mark minutes resolves the rest of the bar once at the bar close from the trade-price bar range, stop-first (minutes after the hole unused); a fill inside that bar defers take-profits to the next bar and only the stop resolves — D-12/D-33: fallback never resolves mid-bar and never optimistically; the bar range includes pre-fill minutes so the fill-bar fallback is stop-only
- [Phase 14]: Plan 14-07: new_plan_state takes sized levels from protective_levels_for_fill (TP1 half via size_protectives_to_filled_qty, D-27); finalize_at_data_end needs the minute source to close an OPEN position as END_OF_DATA at the last mark close with exit_slippage_rate; CANCEL and PENDING events book zero — D-06/D-11/D-34: live ladder mirrored exactly, no time stop exists (searched), END_OF_DATA flagged and never booked as SL or TP
- [Phase 14]: 14-08: case-input v2 is a closed key set; a passed minute_source wins over case minute rows; warm-up closes before data_window.start are not evaluated
- [Phase 14]: 14-08: DAILY_STOP cancels entries resting at the booking instant by re-advancing from the window-start state; END_OF_DATA bookings are dated no earlier than the last ledger booking
- [Phase 14]: 14-09: regime rides SetupResult only (never Signal), so no signal/plan hash moves (D-38)
- [Phase 14]: 14-09: planner, risk and TP1-sizing rejects also count in run_summary no_trade_counts; run_summary has 18 sorted JSON-native keys recomputed from records
- [Phase 14]: 14-10: builder dataset_id hashes every 1m trade/mark partition of the requested range (lazy source files_read() is a subset), so the id covers every file a run reads
- [Phase 14]: 14-10: funding cadence (8h/4h) inferred per symbol by spacing majority; tolerance fixed at FUNDING_MAX_CADENCE + FUNDING_JITTER, equal by test to coverage constants
- [Phase 14]: 14-10: to_case_input exports v2 allowed_gaps without interval, omits open_interest, strips price_tick_count from mark rows; minute rows only with with_minute_rows=True
- [Phase 14]: 14-11: report refuses a filled record whose exit_kind is not SL/TP2/END_OF_DATA instead of counting it as a plan outcome
- [Phase 14]: 14-11: PlateauSection is a fixed NOT_COMPUTED structure (note: not computed (BKTS-03 pending)); regions and isolated-optimum warnings removed
- [Phase 14]: 14-11: test_analytics_cli (31 tests) red until 14-15 migrates the evidence loader and evidence_sample.json; logged in deferred-items.md
- [Phase 14]: 14-12: simulator.run is a thin shell over engine.simulate with evaluate_risk resolved from module globals at call time; phase6 cases are regression snapshots with 1m data from bar N+1
- [Phase 14]: 14-12: paper parity fixture is a single-signal history where the ledger never binds (D052 input); asserted explicitly
- [Phase 14]: 14-13: Phase 14 goldens use scripted round-number plans; expected.json is hand-written from DERIVATIONS.md standalone Decimal arithmetic and the generator writes input.json only
- [Phase 14]: 14-13: daily_loss_blocks_next needs three sequential stop-outs (about 34 each, sizes shrink with realized equity) to reach the 100 DAILY_STOP threshold; two stop-outs cannot
- [Phase 14]: 14-14: smoke script requests series trade/intrabar_1m/mark_1m/funding only; open_interest is not consumed by the v2 engine and cannot be backfilled for 90 days
- [Phase 14]: 14-14: real smoke measured BTCUSDT 90d at ~380s/run (tracemalloc on), heap peak ~7.8MB, digest 806c885e... reproducible; constraints are today's values (assumption, smoke only); incremental feature series recommended as post-Phase-15 follow-up (D052 input)
- [Phase 14]: 14-15: ExperimentRecord carries 17 required typed fields validated in __post_init__; cost_values must hash to cost_model_hash and carry funding_convention; experiment_id binds simulator_semantics_version, split_role and split boundaries
- [Phase 14]: 14-15: assemble also binds run_summary data_window to the record range and dataset_id to data_snapshot_id; reproduce compares every typed field of the re-run summary; legacy 7-key sets can no longer assemble (gate and legacy hashes unchanged)
- [Phase 14]: 14-15: evidence schema analytics-evidence/2 (closed experiment key set, v1 refused); Phase 10 report_composite identity moved to a 40-hex commit and baseline-v5 cost hash, digest pins regenerated (report_digest ebd9e101...)
- [Phase 14]: D052: research protocol v2.0.0 frozen (Phase 14 backtest causality); all earlier backtest evidence void; Frozen on unchanged, D013 clock not restarted
- [Phase 14]: D053: Phase 14 regeneration inventory recorded (cost_model_hash 3063dc39 to 6d6c4e23, goldens, evidence schema analytics-evidence/2)
- [Phase 14]: Protocol version pins are read from the header in gate code and tests (PR-08, DC-03); research-gate negative tests header-driven
- [Phase 15]: 15-01: geometry audit verdicts follow D-22..D-27 over D-10/D-11 (B stop FIX per D-23, B breakout_confirmation_bars is PARAMETER pending 15-08)
- [Phase 15]: 15-02: rationale tables are hash-neutral metadata; pin_stream_epoch refuses missing/incomplete rationale and PLACEHOLDER keys by default (allow_unrationalized is test-only)
- [Phase 15]: 15-03: pivot tie rule is left non-strict/right strict, so of two equal lows the right one is the pivot; geometry_version gates the corrected Family A path, legacy sets unchanged
- [Phase 15]: 15-03: optional registry keys pivot_left_bars, pivot_right_bars, geometry_version, tp_mode, min_stop_atr with cross-key rules; no committed set changed hash
- [Phase 15]: 15-04: _geometry_rejection is the single structural validator (D-06/D-07/D-08/F6, fixed order, before the RR gate); RR and TP2 RR use the signed profit-side leg; TP1-beyond-entry-zone tightening deferred (check compares entry_ref per plan)
- [Phase 15]: Phase 15 plan 15-05: Family B geometry_version 1 anchors the retest to the evaluated bar, trades only with the 4H regime and puts the stop beyond the far edge of the narrow S/R zone (D-23, D-24); legacy output pinned unchanged
- [Phase 15]: Phase 15 plan 15-05: breakout_confirmation_bars is 1 only as a test-local proposed baseline (sheet B1), 3 only in the labelled legacy case; ratification stays at 15-08
- [Phase 15]: 15-06: Family C regime under geometry_version is the two newest confirmed 4H pivots per side (HH+HL bullish, LH+LL bearish, tied or mixed neutral, fewer than two NO_TRADE); S3 stop beyond the narrow S/R zone; tp_mode T_MID midpoint or T_OPPOSITE opposite boundary — D-22, D-23, D-10; one tied pair is NEUTRAL; values test-local, ratified at 15-08
- [Phase 15]: 15-07: census is counts-only and run once per draft set; draft geometry_version 1 sets show 0 invariant violations, legacy Family A 323 of 323 (F-301); values stay with the user for 15-08
- [Phase 15]: Phase 15 baseline-v6 sets written exactly as ratified by the user at checkpoint 15-08-01 (reply ratify); min_stop_atr 0.5 and most seed values are PLACEHOLDER so the sets are research-only
- [Phase 15]: risk_rate, breakout_volume_threshold (B) and breakout_confirmation_bars (A, C) omitted from the v6 sets: no src/ reader
- [Phase 15]: 15-09: -v4 baselines take baseline-v6 values with only the ratified overrides; override basis DECISION D054; PA-08 plus exact pin-set equality guard the five Phase 15 sets
- [Phase 15]: 15-10: v6 payloads use a V-dip 1H history (confirmed pivot low at bar 240, TP1 pivot high at bar 244) and mirror around 250.00 for SHORT; no ratified or registry value tuned, bars and minutes were designed to the ratified values
- [Phase 15]: 15-10: fixture facts consumed by 15-12 are hand-derived with standalone Decimal commands quoted in 15-10-SUMMARY; engine digests are regression pins only
- [Phase 15]: 15-11: planner tests and Phase 4 snapshots run on baseline-v6; the regeneration script no longer writes the pin file (parameters.json) or expected_features.json (T-15-19)
- [Phase 15]: 15-12: Phase 6/7 fixtures regenerated from build_v6_payloads(); every consumer migrated in the same plan; digests re-pinned only on cases proven by V6_SCENARIOS; no parameter tuned from results
- [Phase 15]: [15-13] Structural validator (D-06/D-07/D-08/F6) now runs for every parameter set; legacy Family A plans are STOP_TOO_TIGHT, legacy B/C signal bar through the stop is INVALIDATED; passing legacy B/C plan_hash unchanged
- [Phase 15]: D054: Phase 15 geometry correction recorded once with the compiled regeneration inventory; no amendment of RESEARCH_PROTOCOL v2.0.0 needed; re-run readiness verified on the Phase-14 engine for all three baseline-v6 sets (equal digests, census invariant_violations 0)
- [Phase 15]: D054 records the user's 2026-10-07 answer: the three -v4 override values are comparison reference points, not evidence-backed parameters; in-file DECISION/D054 label stays (hash-locked)
- [Phase 15]: 15-17: run_paper_tick runs the stream-start gate (pin_stream_epoch) at its top before any candle is parsed; sets without rationale tables need an exact-hash PAPER_START_ALLOWLIST entry; allowlist ships empty (checkpoint 15-17-01 Option B, D-27 unchanged)
- [Phase 14]: 14-17: mark holes outside a closing-bar fallback are annotated in coverage_note only (annotate-only); OQ-1 (count/exclude/void) left to the user; SIMULATOR_SEMANTICS_VERSION stays 2.0.0
- [Phase 16]: 16-01: SDK owns WS reconnection/rotation; PaperWsAdapter has no handle-level reconnect/close, uses on_connection events plus rebuild() (own stream names only) for unsolicited close
- [Phase 16]: 16-02: registry root resolved once per run_paper_tick call and passed to pin_stream_epoch; loop loads the set via freeze.load_parameter_set_at_root so gate and loop judge one file (IN-05)
- [Phase 16]: 16-02: strategy_version ValueError keeps running before the rationale gate; order documented as a contract, no exception type or digest moved (IN-03, D-02)
- [Phase 16]: Two PENDING approval rows per plan (APPROVE, SKIP_USER) with separate tokens; ShadowApprovalBook.dispatch picks the token per button because the replay layer rejects an action mismatch (CR-01)
- [Phase 16]: Restart sweep expires one approval per plan; the SKIP sibling stays PENDING with a lost token because PostgreSQL allows one decided approval per plan
- [Phase 16]: SHADOW decision actor_id is the callback chat id; user-id authorization stays Phase 23
- [Phase 16]: Telegram errors classified once in the adapter; retry_after honoured inside the existing NOTIFY_* budget, never slept past it
- [Phase 16]: 16-05: blocked --record on real evidence exits 1 before any write or journal append; blocked plain runs still write the journal-depth pair with the kill-gate section NOT CONCLUDED
- [Phase 16]: 16-05: review registry loader requires the five canonical ids and REV-15 scopes, so deleting an item or flipping a scope cannot unblock a report
- [Phase 16]: 16-06: O-03a decided by the user, option a (user-committed JSON authorization file); only --authorization <path> is accepted
- [Phase 16]: 16-06: experiment_already_recorded is checked after each window is assembled and before any write, since experiment_id exists only after assemble
- [Phase 16]: 16-07: pulled research data is copied into the development raw root only with src.ops.backup restore --skip-db --parquet-target --force after pull and verify; no option overwrites a raw file
- [Phase 16]: One rotation owner: the SDK owns the 23 h rotation and reconnection; the supervisor reacts to open/reconnect/close/error events with a REST verification backfill and adds no timer
- [Phase 16]: Gap reason names the window being verified (WS_RECONNECT_WINDOW or WS_DISCONNECTED on rebuild exhaustion); live bars are held during a pending recovery so the monotonic cursor never skips a recoverable bar
- [Phase 16]: Resync expected slots are anchored on the exchange grid (close = open + interval - 1 ms), fixing phantom gaps; tenacity loops no longer retry task cancellation
- [Phase 16]: Plan 16-09: freeze CLI --from-allowlist writes one SKIPPED line for an empty allowlist, checks the single approved entry with the pinned hash equal to the entry hash, and exits 1 on two entries (ambiguous allowlist); find_allowlist_entry raises on duplicate ids; every line may carry run_metadata from five named environment variables
- [Phase 16]: 16-10: evaluate_closed_bar takes the caller's setup/context candle lists (tick keeps whole-series behaviour, no digest moves); BarBuffers cut the engine windows 1000/300 with bisect_right and cap at window plus one bar — D-02 byte-identity of run_paper_tick; research P6/P7 window and 4h-before-1h parity with the engine
- [Phase 16]: 16-10: decision_surface is a non-semantic observer (no simulator import, tolerance-zero surface_digest); a conflicting duplicate bar raises; src/paper/shadow.py excluded from the float glob scan with a stated reason (tenacity seconds) — L-02/D061 B and G2-008; plan fallback of an explicit justified exclusion instead of weakening the scan
- [Phase 16]: [16-11] D041 SHADOW confirm: APPROVE edits the alert into a card; the confirm token is separate, in-memory, single use, bound to the approving from_user id and plan hash, 60 s TTL (inclusive boundary); CNF:/CXL: never enter dispatch_callback — D-16, L-13, REV-12: APPROVE alone confirms nothing; terminal outcomes are exactly one of CONFIRMED, CANCELLED, EXPIRED (reason in the payload); user-id allow-list authorization stays Phase 23
- [Phase 16]: [16-11] Card delivery fails closed: edit (429 honoured inside the remaining TTL only), one fallback send, else EXPIRED CARD_DELIVERY_FAILED; not-modified is success; answerCallbackQuery failure is logged by class and never aborts the gates — T-16-112: an approved plan must never sit with no card and no journaled outcome; expire_due / expire_on_restart and assert_no_stranded_approvals state and repair the invariant
- [Phase 16]: Q-O: user chose not-assessed; G5 floor printed as 'G5 floor not assessed (holdout untouched)'; holdout never counted, extrapolated or simulated
- [Phase 16]: 16-13: candidate validator prints the parameter_set_hash only for a VALID candidate; --list-grid shows structure verdicts only, in grid-file order (D-28, L-03)
- [Phase 16]: O-12 postponed by user (no connectivity); EC2 creation (16-20) blocked until O-12 values recorded
- [Phase 16]: Q-L: separate Telegram bot token for the soak host (user creates it, token never pasted)
- [Phase 16]: 16-15: a freeze slot is satisfied only by a CLEAN line linked to a schedule-event run of the exported run list with the evaluated cron string and run_attempt 1; a re-run line is INVALID_LINE and grace is refused at or above 3600 s — A re-run executes later than the slot and a grace at or above the slot interval lets one run stand for two slots; both would fill a missed tick (REV-02, REV-18, T-16-114)
- [Phase 16]: 16-15: after every RUNTIME_START the time to the first live feed message is uncovered (WS_RECONNECT_WINDOW) and only LIVE_WS bar records prove a live arrival — Matches plan 16-29 HEALTH_STATE_CHANGED rule and REV-01 (time the runtime did not observe the feed is not covered); fails closed if the payload contract is not matched
- [Phase 16]: 16-17: path_exercised is unsolicited only when the first rebuild after the drop found stale stream names and no close API was called; a fake rig is never labelled REAL_SMOKE, even in --live mode
- [Phase 16]: 16-17: --live checks BINANCE_* environment names before the operator flag (exit 3 before exit 2) and prints only the name; the SDK rotation override (floor 300 s) is process-local and restored in a finally block
- [Phase 16]: 16-18: plateau/mark-hole/cost-field reporting is reporting only; per-point figures are existing backtest report outputs over pooled Validation trades, axis values ordered numerically, no marker or ordering by a metric
- [Phase 16]: 16-35: SHADOW approval delay is the measured acted - requested of the approval row for a human action; APPROVAL_DELAY_LAG_SECONDS only for records with no human action (SIMULATE leg) — D-15, SC3; new PaperRecord fields are optional and omitted from the canonical output when absent so every pinned digest is unchanged (Q-K)
- [Phase 16]: Q-J (user): paper runtime state is journal rows only (PgRuntimeState via PgJournalStore, entity PaperRuntime); no migration, no table
- [Phase 16]: [16-19] Q-B (user): SHADOW fill eligibility = recorded CONFIRM instant floored to the minute plus one minute, passed as advance start_exclusive; no simulator change
- [Phase 16]: [16-19] Live 1m trade and mark minutes by REST polling; poll cadence and close lag are required inputs (O-07); driver advances only to the shared settled watermark
- [Phase 16]: 16-55: soak backups use a separate BACKUP_S3_BUCKET (own crypt passwords, own --init-remote); deploy/backup.sh --install-soak-timer refuses an empty or shared bucket; backup_remote.py layout unchanged (orchestrator option a; owner creates the bucket before 16-43)
- [Phase 16]: 16-55: instance lease is one fixed paper-runtime scope per database (session advisory lock), not per epoch id, because the pin mints the epoch id after the lease must be held
- [Phase 16]: 16-56: SDK-error mapping is opt-in per BinancePublicMarketData instance (project_transport_errors=True, set by the paper composition root); Phase 18 callers keep SDK types
- [Phase 16]: 16-56: the silence watchdog has its own injected sleep and monotonic seams (LoopWiring.watchdog_sleep, feed_clock); one guard makes _fail run once
- [Phase 16]: 16-56: [health] is RuntimeHealthConfig(HealthThresholds) with feed_silence_timeout_seconds; paper-runtime-v2.toml is in force, v1 is history and refused
- [Phase 16]: 16-56: deploy/heartbeat.sh --target paper install requires --soak-env-file (the unit runs deploy/compose-soak.sh)
- [Phase 16]: 16-57: configuration identity = SHA-256 of the canonical validated values (canonical decimal text, configured symbol order); EPOCH_PINNED and RUNTIME_START carry it plus raw-file provenance; a different or absent identity refuses with exit 6 held (16-DEC-CONFIG-PIN)
- [Phase 16]: 16-57: one PAPER_GAP per close across restart, supervisor and pipeline via a shared GapLedger (first writer wins); one post-start seam verification backfill (B1-WR-05, B1-WR-01)
- [Phase 16]: 16-57: a risk-passed heartbeat without a persisted SHADOW alert is journaled once at start as SHADOW_SIGNAL_LOST and never re-alerted (B1-WR-03, L-11)
- [Phase 16]: [16-58] A pending reservation the fill driver cannot open is released with SHADOW_RESERVATION_REFUSED (driver reject code, occurred_at = CONFIRM instant); an opened position that cannot be rebuilt stays a loud error
- [Phase 16]: [16-58] Reservation expiry follows the data horizon (now minus minute_close_lag_seconds); ShadowLedger.admit and risk_inputs judge on a rolled copy and never store a roll
- [Phase 16]: [16-58] Lock order: the coordinator lock is never held while the ledger lock is awaited; on_confirmed fires after the CONFIRM section; confirm reply records are keyed by the press correlation id
- [Phase 16]: [16-59] Evidence bundles are keyed <epoch>/<as_of>-<sha12 of manifest>/ and create-only; identical bytes succeed, different bytes exit 4 (16-DEC-EVIDENCE-KEYS, Q1 = A)
- [Phase 16]: [16-59] The freeze log is the union of every run artifact deduplicated by (run_id, run_attempt), originals kept, each tick without a usable line recorded as a missing tick; workflow concurrency with queue max (16-DEC-FREEZE-LOG-ASSEMBLY, Q2 = B)
- [Phase 16]: [16-59] An export is judged as of an instant and an hourly bundle is partial: the trial evaluator refuses to judge a bundle whose as_of_utc is before window end plus the ratified grace (B2-WR-06)
- [Phase 16]: 16-62: rest_backfill_depth_bars is a required keyword through build_supervisor into backfill_missed_closes; closes beyond the depth are gaps with the window reason (B1-WR-09)
- [Phase 16]: 16-60: research windows are built with RESEARCH_WARMUP_SPAN (50 days, STRUCTURAL) of price history before their start; simulator semantics 2.2.0; protocol v2.5.0 with D073 and D074 (B3-CR-01); the Development window starts cold (data begins 2024-10-03)
- [Phase 16]: 16-60: the original 240 research records stay unchanged and are superseded by the rerun under 2.2.0 (D074, owner's wording); rerun directory research-run-1-v2-2-0 and a sixth authorization key are implemented by 16-61
- [Phase 16]: 16-63: a plan whose stored TP2 is not above zero is NO_TRADE RR_TOO_LOW (owner Option A, strict reading); simulator semantics 2.3.0, protocol v2.6.0, D075 and D076
- [Phase 16]: 16-63: research run 1 regenerated under 2.3.0 (240 records, families in parallel by owner decision); the 2.1.0 records are superseded in the owner's wording with only the versions replaced (16-DEC-RUN1-SUPERSEDED.md)
- [Phase 16]: 16-63: R7: the soak image is rebuilt from a commit containing the TP2 guard and the 16-62 gate repeated before plan 16-43 pins the epoch
- [Phase 20]: 20-01: Phase 20 ExecutionLimits fields are <section>_<key> (EXECUTION_LIMIT_FIELDS); Phase 19 field names unchanged; the numeric-default guard covers key texts and field names
- [Phase 20]: 20-02: PROTECTION is a seventh TransitionKind (not persisted, no GLOSSARY block until O-01); ProtectionCoordinator._transition is the only place a protection state changes and refuses moves outside the table (journal PROTECTION_TRANSITION_REJECTED, SAFE_MODE PROTECTION_STATE_INVALID). — D-29, T-A, D077. Audit added the edges PROTECTED_ENTRY_OPEN -> FLAT and AWAITING_FILL -> ENTRY_UNRESOLVED (covered by the docstring intent). O-H exception not built (default NO). Phase 20 has no exchange event-time column: no general stale-event detection (deferred to Phase 24).
- [Phase 23]: 23-01: new Telegram edge refusal codes are plain strings in src/approval/reason_codes.py, not RejectionReason members (enum stays 21; DispatchResult.reason_code is RejectionReason | str | None)
- [Phase 23]: 23-01: authorized_user_ids is a required keyword-only frozenset[int] on on_callback, build_application, ShadowCoordinator, ShadowWiring and RehearsalSettings; a configured Telegram without TELEGRAM_AUTHORIZED_USER_IDS refuses the paper start
- [Phase 23]: [23-02] MoneyAtStake computed once in src/risk/money_at_stake.py from the SizedResult (net SL loss = realized_risk read, margin via required_initial_margin truncated at 18 digits, TP legs via per_unit_round_trip_cost); stored form money-at-stake/1 canonical JSON, strict parser
- [Phase 23]: O-2 (G4-042) decided (a) by owner 2026-10-26: EXPIRED excluded from uq_approvals_one_decided_per_plan (0014); store refuses EXPIRED on a plan with an APPROVED/SKIPPED approval
- [Phase 23]: TP fractions of the DEMO/LIVE request come from the stored money block, not a constant (no src.backtest import in src.execution; Phase 19 invariant 7)
- [Phase 23]: Desk answers an unreadable entry intent on an APPROVED expired redelivery as needs reconciliation (never expired/rejected, Q5)
- [Phase 23]: Desk final message text is derived from stored approval rows, edited once per request
- [Phase 23]: 23-12: validity_rule is called with keywords (expiry_utc, now_utc) so a partial over check_remaining_validity binds directly; a refused-before-recheck CONFIRM awaits no prefetch; a handler that raised is answered with the neutral text; the confirm core was not changed
- [Phase 24]: 24-02: NO_FILL and HEALTH_CHECK_FAILED are RejectionReason members (23), values unchanged (G3-005, D-35)
- [Phase 24]: 24-03: D083 clock margin is rest_gate.ban_end_clock_margin_ms, an OPTIONAL NOT_CONFIGURED key outside require_live_ready; ban-entry alert is REST_GATE_BAN_ENTERED until_utc=<ISO>
- [Phase 24]: Q1: one live process python -m src.live.runtime, one asyncio loop (24-01, owner 2026-10-31)
- [Phase 24]: Q2: sync stores kept; on-loop store calls go through src/ops/store_executor.py with one writer thread, no async pool (24-01, owner 2026-10-31)
- [Phase 24]: Q3: migration 0015_order_event_time with a monotonic event-time guard (24-01, owner 2026-10-31)
- [Phase 24]: Q9/Q14: CLOSE_POSITION after a failed post-fill liquidation check (D085); LIVE_NET_PNL_SEMANTICS_VERIFIED stays False until the Phase 26 canary (D086) (24-01, owner 2026-10-31)
- [Phase 24]: Q10: Phase 16 soak is running, so the SHADOW money block ships as a new text version with old pins kept (24-01, owner 2026-10-31)
- [Phase 24]: 24-04: ExecutionService is the single execute_approved_plan call site (src/live), sync on_confirmed schedules on the loop (call_soon_threadsafe from other threads); entry client id is registered in the in-memory ClientIdIndex before the manager is awaited (P-4)
- [Phase 24]: 24-04: build_execution_path in src/live/wiring.py is the only constructor of live objects (D-04); PlacementInputsSource is the port plan 24-16 implements

### Pending Todos

- WS-connect gap fix (PaperWsAdapter + PaperSupervisor SDK connect path proven live) — blocks soak start

### Blockers/Concerns

- Paper forward observation (Phase 7) is wall-clock bound (3–6 months) — dominates calendar regardless of code velocity
- OI history irrecoverable outside ~30-day window — OI collector must start in Phase 2 day one (the collector exists in `src/data`; the dated commitment of D059 item 4 is under Commitments with dates)
- Algo-Order field details MEDIUM confidence — Phase 9 wiring is done; the `ALGO_UPDATE` field wording and the 24-hour WebSocket lifetime are re-confirmed before Phase 18 wiring (ROADMAP Phase 18 inherited items); the clientOrderId facts were re-read live on 2026-10-07 (docs/SOURCES.md, Phase 17 section)
- evaluate_risk takes absolute amounts: the backtest ledger (`src/backtest/ledger.py`) and the paper loop (`src/paper/loop.py`) convert registry rates through `resolve_absolute_thresholds`; the live caller (live risk-input producer) is owned by Phase 24 success criterion 1
- WS-connect gap (07-04 follow-up) blocks soak start; Phase 8 construction can proceed in parallel
- 08-02 LIVE-TAP GATE: partly cleared. Real APPROVE and SKIP taps were observed (`09-DEMO-REHEARSAL-FINDINGS.md`, dry-run `taps`: SKIP and APPROVE passed); the unknown-chat tap is still NOT_REHEARSED and the live Telegram check is deferred to Phases 23/24 (08-VERIFICATION, accepted by the operator 2026-10-04; ROADMAP Phase 24 item G2-014)
- Phase 09 Plan 04 task 3 (Demo rehearsal plus credential provisioning plus LIVE-TAP clearance) is only partly done: the Demo runs of 2026-10-05 stopped at SL placement with -4509 (D055, execution model OPEN) and credential provisioning is not attested, so EXEC-01 and OPS-02 stay Pending until real Demo evidence exists (`09-DEMO-REHEARSAL-FINDINGS.md`); owners Phases 24/25

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260930-bku | Record user-approved audit decisions D031-D039 in docs/DECISIONS.md | 2026-09-30 | c63d507 | [260930-bku-record-user-approved-audit-decisions-d03](./quick/260930-bku-record-user-approved-audit-decisions-d03/) |
| 260930-bvi | Import deep-audit report into .planning/audits and re-plan roadmap phases 11-26 (stay in v0.3) | 2026-09-30 | d190855 | [260930-bvi-import-deep-audit-report-and-re-plan-roa](./quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/) |
| 260930-cgi | Add D040 safe release path (SHADOW-DEMO-CANARY-LIVE) and D041 two-step Telegram confirm; insert Phase 25 demo test campaign | 2026-09-30 | 7a05679 | [260930-cgi-add-safe-release-path-and-two-step-teleg](./quick/260930-cgi-add-safe-release-path-and-two-step-teleg/) |
| 260930-d0b | Record D042 single-VPS deployment; pull VPS hardening + collector deployment into Phase 13 | 2026-09-30 | 2660fb6 | [260930-d0b-record-single-vps-deployment-decision-d0](./quick/260930-d0b-record-single-vps-deployment-decision-d0/) |
| 261007-mkw | WR-05 (D062): trading user joins sudo with a password, lock-out guard, no passwordless rule | 2026-10-07 | 7148528 | [261007-mkw-wr-05-d062-trading-user-joins-sudo-with-](./quick/261007-mkw-wr-05-d062-trading-user-joins-sudo-with-/) |
| 261007-onb | CR-01 replacement (D064): Parquet push by manifest SHA-256 plus cryptcheck (double only; real-S3 gate pending) | 2026-10-07 | e9a030c | [261007-onb-cr-01-replacement-d064-parquet-push-mani](./quick/261007-onb-cr-01-replacement-d064-parquet-push-mani/) |
| 261009-jqi | Vietnamese operator deploy/operations guide docs/operations/DEPLOY_GUIDE.vi.md plus traceability checker | 2026-10-09 | 894d359 | [261009-jqi-vietnamese-operator-deployment-guide-dep](./quick/261009-jqi-vietnamese-operator-deployment-guide-dep/) |
| 261014-cvk | Research protocol v2.3.0: declared exchange-constraint assumption (D068) and one global Holm for G3 over 48 hypotheses (D069) | 2026-10-14 | f80e0a2 | [261014-cvk-protocol-v2-3-0-amendment-d068-d069-land](./quick/261014-cvk-protocol-v2-3-0-amendment-d068-d069-land/) |
| 261014-nnl | S-B-interval: REEFUSDT terminal settlement as a bounded interval (manifest terminal_settlements, engine SETTLEMENT/SETTLEMENT_CANCEL, simulator 2.1.0, protocol v2.4.0 D070/D071); 10 plans, gates green, REEF diagnostic 48/48 | 2026-10-15 | ded32f7 | [261014-nnl-plan-s-b-interval-implementation-plan-on](./quick/261014-nnl-plan-s-b-interval-implementation-plan-on/) |
| 261015-mvq | compute_features computes the last bar only, byte-identical (core performance; 14x on the function, 3-10x on engine runs; simulator stays 2.1.0) | 2026-10-15 | a64e6af | [261015-mvq-optimise-compute-features-last-bar-only-](./quick/261015-mvq-optimise-compute-features-last-bar-only-/) |
| 261015-o9l | Manifest build command (python -m src.research.manifest --build from the O-03b record); draft S0 manifest hash ec161733 outside the repo, not frozen | 2026-10-15 | f0f5366 | [261015-o9l-manifest-build-command-for-the-research-](./quick/261015-o9l-manifest-build-command-for-the-research-/) |
| 261015-pdb | Research runner: per-point records and window checkpoints (--checkpoint-dir, resume); default behaviour unchanged | 2026-10-15 | (this commit) | [261015-pdb-research-runner-per-point-records-and-sp](./quick/261015-pdb-research-runner-per-point-records-and-sp/) |
| 261016-pre | Close 16-41, ROADMAP/REQUIREMENTS bookkeeping (BKTS-03 complete), 16-42 Task 1 preflight | 2026-10-16 | (this commit) | [261016-pre-close-16-41-roadmap-state-and-16-42-pre](./quick/261016-pre-close-16-41-roadmap-state-and-16-42-pre/) |
| 261016-alw | 16-42 Tasks 2 and 3: G4-021 exact-entry-pin, allowlist entry research-run-1-a01, tests and D054 item (i) | 2026-10-16 | (this commit) | [261016-alw-allowlist-entry-research-run-1-a01-g4-021](./quick/261016-alw-allowlist-entry-research-run-1-a01-g4-021/) |
| 261020-xd4 | pytest-xdist opt-in parallel run (`-n 4`, about 9-10 min vs 24); default, CI and recorded gates stay sequential | 2026-10-20 | (this commit) | [261020-xd4-pytest-xdist-opt-in-parallel-test-run](./quick/261020-xd4-pytest-xdist-opt-in-parallel-test-run/) |
| 261020-bkp | backup.sh review fixes, explicit local-only mode (BACKUP_REMOTE=none), D064 real-S3 gate script (result pending until the owner runs it), 16-43 plan and checklist fixes | 2026-10-20 | (this commit) | [261020-bkp-backup-local-only-and-d064-gate](./quick/261020-bkp-backup-local-only-and-d064-gate/) |
| 261020-jua | Q5: one `place_entry` POST per approval, ambiguous result probed once, else UNKNOWN + SAFE_MODE | 2026-10-20 | 94ad09a | [261020-jua-q5-remove-entry-placement-retry-unknown-](./quick/261020-jua-q5-remove-entry-placement-retry-unknown-/) |

### Roadmap Evolution

- Phase 07.1 inserted after Phase 7: Close gap: B1 registry-cost to backtest identity binding (URGENT)
- Phase 07.1 edited: edited fields: depends_on (Phase 7 -> Phase 6)
- Phase 13.1 inserted after Phase 13: Deployment & CI: CI pipeline, image pinning, bootstrap/migrate scripts, provider-portable backups; VPS provisioning deferred

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| Pending decision | Maker/post-only entries instead of taker (operator idea 2026-10-04). D036 currently says no GTX in V1 and entry fee modeled as taker; changing it needs a new decision plus Phase 12 and Phase 14 changes. Details in `.planning/LIVE-TEST-2026-10-04.md` | Awaiting operator | 2026-10-04 | v0.3 |
| Live test findings | Telegram and Binance Demo probe: findings and owners (Phases 16, 22, 23, 24) recorded in `.planning/LIVE-TEST-2026-10-04.md` and ROADMAP | Recorded | 2026-10-04 | v0.3 |
| Phase 7 carry-over | Live WS ingestion (`PaperWsAdapter` missing `await`, `soak_smoke.log` ws_subscribe=BLOCKED), runnable paper process, SC3 soak evidence (`pinned_epoch.json`, `registry_diff.jsonl` all CLEAN). PAPER-01..03 stay Pending. Written into ROADMAP Phase 16 success criteria 7-9 | Deferred to Phase 16 | 2026-10-04 | v0.3 |
| Phase 8 carry-over | Live Telegram callback check, read-only Binance reconcile, real-stack RUNBOOK drill | Deferred to Phases 20/23/24/25 | 2026-10-04 | v0.3 |
| Phase 9 carry-over | Testnet rehearsal (needs signed-request adapter and a trading-permission demo key), 6 unconfirmed exchange facts in 09-REVIEW-FIX.md (confirm before Phase 24 wiring), hard-coded HEADROOM_LIMIT=200 | Deferred to Phases 24/25 | 2026-10-04 | v0.3 |
| Phase 10 carry-over | Kill-gate review findings WR-01, WR-06, WR-12, WR-13 (decide before the first report on real evidence), WR-10 (enable flow) | Deferred to Phase 26 / Phase 24 | 2026-10-04 | v0.3 |
| Phase 11 carry-over | Re-confirm ALGO_UPDATE wording and the 24h WebSocket lifetime against Binance pages | Deferred to before Phase 18 | 2026-10-04 | v0.3 |
| Phase 2 carry-over | Backup drill: PostgreSQL dump and restore proof (operator hand-copied data/raw on 2026-10-04) | Deferred to Phase 13.1 remote drill | 2026-10-04 | v0.3 |
| Enum promotion | Partly done: `SetupType`, `OrderRole` and `Direction` (side, position_side) exist in `src/domain/enums.py`. Still plain values: regime, order_type, time_in_force; event_type and entity_type are validated strings in `src/domain/journal.py`. Phase 4 is closed; no owner phase | Remaining part has no owner | 2026-09-22 | v0.3 |
| trades table | Logical user-executed trade entity (DATA_MODEL §2.6) | Not built in V1 (D045 item a) | 2026-09-22 | v0.3 |
| experiment_runs table | Backtest/research reproducibility (DATA_MODEL §2.12) | Not built in V1 (D045 item a, `docs/data/DATA_MODEL.md` §2.12) | 2026-09-22 | v0.3 |
| Registry DB mirror | DB table mirroring registry rows for experiment-join queryability | Not built; parameter-set files stay canonical (no registry table in `src/db/models.py`); Phase 6 is closed and no phase owns it | 2026-09-22 | v0.3 |

## Open user decisions (2026-10-07)

Recorded as open; none is decided here. Each line names where the item is owned.

- D055 execution model (protective stop before or after the entry fill, -4509): OPEN; the Phase 18 Demo probe ran (2026-10-16) and supplied evidence only (`18-DRAFT-D055-evidence-for-user.md`), the adopted direction is noted in `.planning/phases/19-execution-plan-binding-price-check/19-NOTES.md` and is not a decision; `docs/DECISIONS.md` D055, ROADMAP Phase 18 and the D055 items in Phases 24 and 25.
- OQ-1 (how a trade held through mark-price holes counts in the evidence): `.planning/phases/14-backtest-causality-rewrite/deferred-items.md`; ROADMAP Backlog 999.2 (Phase 16 inherited item D052-open covers the related `modeled_costs_per_unit` question).
- EC2 creation date: not set. The host is an AWS EC2 instance in ap-southeast-1 (Singapore), chosen 2026-10-07 (D061); until it exists the collector runs on a dev machine (`.planning/phases/13.1-deployment-ci/13.1-CONTEXT.md`, 13.1-OPEN-DECISIONS UAT 8-10, D042, D050, D061).
- Container registry push and deploy on tag: needs a registry and VPS decision; no owner phase (`13.1-CONTEXT.md` Deferred Ideas, D050).
- Legacy Parquet partitions with a different Decimal scale: repair is optional, operator decision, no deadline (`.planning/phases/13-research-data-foundation-fixes/deferred-items.md` item 3, `scripts/repair_parquet_scale.py`).
- Phase 13.1 WR-05 is implemented (commit 7148528, D062); CR-01 is replaced by D064 (manifest comparison plus post-upload `cryptcheck`; a real rclone run showed that `--checksum` falls back to `--size-only` on a crypt remote) and its implementation is a quick task with the proof first, before the first real backup; WR-06 (split `env_file` per service; ROADMAP Phase 24 G3-029) is still open and must precede any live key: `.planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md`.
- Values of the reconcile cadence, stale-feed and WS-silence thresholds (T-06) and the WR-07 ordering rules (G2-026): ROADMAP Phase 20.
- Sibling-approval expiry rule for `uq_approvals_one_decided_per_plan`: ROADMAP Phase 23 item G4-042.
- `asyncio.to_thread` or an async pool for the synchronous PostgreSQL store, or a recorded decision: ROADMAP Phase 24 item G4-040.
- Research-gate as a required status check on master, or a recorded waiver: ROADMAP Phase 26 item G1-001.
- Phase 16 open items (D061): the durable location for `pinned_epoch.json` and `registry_diff.jsonl` (the plan proposes, the user approves) and the closure-chain checkpoints (hypothesis and parameter grid approval, research run authorization, exact-hash allowlist entry) decided when Phase 16 executes; the paper exit values were ratified on 2026-10-07 (D061 item D).
- Decided 2026-10-07 and removed from this list: freeze-check host, per-bar parity and kill-gate WR timing (D061 items A, B, F), the plan that carries protocol v2.1.0 (done, D060) and WR-05 (implemented) and the CR-01 decision (replaced by D064).

## Commitments with dates

- OI collector must be running and writing OI data successfully no later than 2026-10-08 (user commitment, D059 item 4); a deployment that does not ingest does not count, and the repository cannot enforce the date.
- Decisions D055-D059 were recorded on 2026-10-07 in `docs/DECISIONS.md`.

## Session Continuity

Last session: 2026-10-31T05:37:18.748Z
Stopped at: Completed 24-04-PLAN.md
Resume file: None
