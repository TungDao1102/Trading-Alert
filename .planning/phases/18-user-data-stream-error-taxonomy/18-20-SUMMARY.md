---
phase: 18-user-data-stream-error-taxonomy
plan: 20
subsystem: live evidence
status: complete
tags: [demo-probe, D055, D-16, D-17, G2-029, EXEC-01, EXEC-02, evidence, blocking-human, REAL_DEMO]
requires: [18-17, 18-18, 18-19, 18-23]
provides:
  - "evidence/demo-probe-EVIDENCE-20261016T142134Z.json and demo-probe-EVIDENCE-20261016T173612Z.json (proof_class REAL_DEMO)"
  - "evidence/18-probe-check.txt (dry-run line, both runs, the fact list for plan 18-21, the three fake assumptions)"
  - "decisions/18-probe-limits.toml and decisions/18-DEC-O-18-03.md (the user's authorization and the rerun addendum)"
  - "tests/fixtures/phase18/recorded_demo/probe/ (57 RECORDED_DEMO frames of the second run: ORDER_TRADE_UPDATE, ALGO_UPDATE, TRADE_LITE, ACCOUNT_UPDATE)"
  - "scripts/demo_probe.py: the marketable entry price sits halfway into the PERCENT_PRICE band"
affects: [18-21, 18-22, 18-25]
key-files:
  created:
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-probe-limits.toml
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-03.md
    - .planning/phases/18-user-data-stream-error-taxonomy/evidence/18-probe-check.txt
    - .planning/phases/18-user-data-stream-error-taxonomy/evidence/demo-probe-EVIDENCE-20261016T142134Z.json
    - .planning/phases/18-user-data-stream-error-taxonomy/evidence/demo-probe-EVIDENCE-20261016T173612Z.json
    - tests/fixtures/phase18/recorded_demo/probe/
  modified:
    - scripts/demo_probe.py
    - tests/test_demo_probe_cases.py
decisions:
  - "Authorized by the user on 2026-10-16: DEMO, BTCUSDT, quantity 0.0008, max_notional_quote 100, far_price_fraction 0.96, case_timeout 30 s, cleanup_timeout 60 s, all three optional cases off."
  - "D055 stays OPEN. The check records facts only and changes no decision file (D-17)."
  - "The probe script was changed once, test first (a live finding): marketable_buy() returns mark times (1 + multiplier_up) / 2 instead of the band edge."
metrics:
  completed: 2026-10-16
  tasks: 4
  commits: 8
---

# Phase 18 Plan 20: Demo probe of the D055 / D-16 cases Summary

The user ran the probe twice on Binance Demo (BTCUSDT, 0.0008). Both evidence files are REAL_DEMO, pass `check_probe_evidence`, ended COMPLETE with no failure and no ban, and left the account FLAT (zero open orders, zero open algo orders, no position). 14 of the 16 required cases are OBSERVED in the second run; two stay NOT_OBSERVED. The results are demo-observed, not mainnet. D055 stays OPEN.

## Commits

All on branch `phase-18-smoke` (worktree `Trading-Alert-p18`), not merged into `develop` and not pushed.

| Step | Commit | Content |
| --- | --- | --- |
| Dry run (Task 1) | 43dcaa4 | 16 cases NOT_REHEARSED in order, zero live port calls, 108 tests |
| Authorization (Task 2) | b216cc1 | `18-probe-limits.toml`, `18-DEC-O-18-03.md` (option: authorize) |
| First live run (Tasks 3 and 4) | 2a27afb | evidence, 47 frames, check file with the fact list |
| Price fix | 90574c8 | `marketable_buy()` halfway into the band, test first; three tests updated to the new price |
| Rerun record | c9d027e | addendum in the decision record, with the user's words |
| Second live run | 19d41d9 | second evidence, 57 frames, check file update |

Plan 18-19 (the transport gate) was recorded before this plan: `transport: sdk` (commit 68cf2bd). Both live runs were typed by the user (`DEMO PROBE BTCUSDT`); no agent ran `--execute`.

## Case results

Both runs record all 16 required cases. The first run had 13 OBSERVED and 3 NOT_OBSERVED. The second run differs in one case.

| Case | First run | Second run |
| --- | --- | --- |
| id_reuse_after_filled | NOT_OBSERVED (entry refused with -4016) | OBSERVED |
| partial_fill | NOT_OBSERVED (every entry filled completely) | NOT_OBSERVED |
| triggered_market_exit_lifecycle | NOT_OBSERVED (trigger not reached in case_timeout_seconds) | NOT_OBSERVED |
| the other 13 cases | OBSERVED | OBSERVED |

## Facts recorded for plan 18-21 (copied from the evidence)

- Not found: GET order and GET algoOrder `(BAD_REQUEST, -2013, ORDER_ABSENT, "Order does not exist.")`; cancel order and cancel algo order `(BAD_REQUEST, -2011, ORDER_ABSENT, "Unknown order sent.")`.
- Duplicate `clientAlgoId` while the first is open: `(BAD_REQUEST, -4116, DUPLICATE_CLIENT_ID, "ClientOrderId is duplicated.")`.
- Id reuse is accepted after CANCELED (normal and algo) and after FILLED (normal order, a new order id).
- A pre-placed reduce-only STOP_MARKET while flat is accepted (status NEW) and stays listed as one open algo order. The close-position variant while flat is rejected with -4509 (PRECONDITION_NO_POSITION). Reduce-only together with close-position gives -1106. A wrong-side trigger gives -2021.
- The protective leg placed while the entry rests stays NEW after the entry is cancelled (orphan) and cancels cleanly.
- After a full fill the protective quantity equals the position amount.
- A reduce-only STOP_MARKET below the minimum notional (7.89 against 50) is accepted.
- REST `algoStatus` seen: NEW only. GET order on an algo id: -2013.

## Assumptions of `BinanceSemanticsFakeAdapter`

| Assumption | Result |
| --- | --- |
| a client id is unique among open orders | agrees for `clientAlgoId` (-4116); not observed for a normal order |
| a CANCELED order frees its id | agrees (normal and algo) |
| a FILLED order frees its id | agrees (normal order) |

The 3-day retention rule of the fake is a documentation rule the probe does not test.

## Deviations and defects found by the live run

- The first run's `id_reuse_after_filled` entry was refused with -4016. The probe priced its marketable entry at the PERCENT_PRICE band edge (`mark * 1.05`) of a mark taken from the last one-minute close, which was above the exchange's own mark. The plan says a probe defect goes through `/gsd-plan-phase 18 --gaps`; the user asked for the fix and a rerun directly, so it was made test first inside this plan (commit 90574c8) and is recorded here. The new price follows from the filter itself, with no new constant.
- The second run was typed with a truncated `--fixtures-dir` (`.../recorded_demo/prob`), so its frames were written to `prob/`. They were copied over `probe/` and the stray directory was removed. The second run's frames replace the first run's files of the same name; the first run's versions stay in git history (2a27afb).
- `mypy scripts/demo_probe.py` reports two errors in `tests/support/limits.py`, a file this plan did not touch. They were not checked against the parent commit; CI runs `mypy src`.

## Open items

- `partial_fill` and `triggered_market_exit_lifecycle` are NOT_OBSERVED. The triggered lifecycle matters most for D055: the child order identity (`ai`, `aq`, child `c` and `i`) was never observed, and the trigger was not reached within `case_timeout_seconds`. A fix needs a probe change (a trigger closer to the mark, or a longer wait) and a new run, so it belongs to a gap plan.
- The optional cases (explicit time in force, stream gap, MARKET_LOT_SIZE out of range) were off.
- Whether REST trade ids equal stream trade ids was not compared (the verdict has no such field).
- Secrets: none in either evidence file or in the 57 fixtures (scanned for the key and secret values and for listenKey and signature shapes).

## Next

- 18-21 corrects the semantics fake from this evidence; 18-22 and 18-25 use the recorded frames.
- Branch `phase-18-smoke` still has to be merged into `develop`.
