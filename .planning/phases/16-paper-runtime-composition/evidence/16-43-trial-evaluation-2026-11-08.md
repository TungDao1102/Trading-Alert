# 16-43 — trial evaluation of epoch ce6c0bbf, window ended 2026-11-08

Result of `scripts/evaluate_trial_soak.py` on the final bundle of the first 14-day soak trial.
**RESULT: FAIL** on two criteria. The full evaluator report is kept next to this file as
`16-43-trial-evaluation-2026-11-08-report.txt` (the `risk.*` log lines are filtered out; no other
line is removed).

## Inputs

| Item | Value |
|---|---|
| Epoch | `ce6c0bbf27f080a6843c62dcedfd336e6d90b918ca08203912035235e9f83eda` |
| Strategy / set | trend-pullback / research-run-1-a01, parameter_set_hash `6f42f70e7e7a107b1be02fc4079fbb70f1408b4307099aa253bd93ebdbce6d87` |
| Window | 2026-10-25T12:37:43.833841Z to 2026-11-08T12:37:43.833841Z (the pin instant, plus 14 days) |
| As-of | window end plus `freeze_tick_grace_seconds` (1800 s), the default of the exporter |
| Source | `--source pg`, proof class REAL_SOAK, 6974 runtime records |
| Freeze input | 335 `registry-diff-<run_id>` artifacts and the GitHub run list (996 successful runs overall) |
| Config / Q-D | `config/paper/paper-runtime-v2.toml`, `decisions/16-DEC-Q-D.md` (rule in force: history-only) |

The bundle, the run list and the artifacts are working files and are not committed.

## Criteria

| Criterion | Result | Detail |
|---|---|---|
| trial window | PASS | 14 days from the pin |
| freeze continuity | **FAIL** | 336 expected slots, 327 satisfied, 9 EVIDENCE_GAP, 0 non-CLEAN lines |
| single epoch | PASS | 333 freeze lines after the pin |
| pinned hash unchanged | PASS | 333 CLEAN lines, hash unchanged |
| runtime coverage | PASS | 334.779 h of 336 h (0.9964); 0.95 required |
| continuous uncovered time | **FAIL** | longest block 3034.95 s against a ceiling of 900 s |
| gaps explained, no fabricated bar | PASS | 2115 bar records, all LIVE_WS, 0 PAPER_GAP |
| restart warm-up | PASS | 8 runs, 1695 evaluated bars |
| no duplicate signal | PASS | 2115 records, 380 distinct signal ids |
| no missing journal row | PASS | 2100 expected closed bars, 0 without a record |
| no test signal | PASS | |
| parity (tolerance zero) | PASS | 2115 records compared with the replay of 54115 bars, 0 differences |

## The two failures

### Freeze continuity: nine EVIDENCE_GAP slots

No freeze line after the pin differs from CLEAN and the parameter hash never changed. The failure is
about missing evidence of the ticks, not about the registry.

| Reason | Slots (UTC) | Count |
|---|---|---|
| RUN_WITHOUT_LINE | 2026-10-25 13:34, 14:34 (runs `40198757199`, `40203425195`, before the `__main__` fix) | 2 |
| RUN_LATE_BEYOND_GRACE | 2026-10-26 00:34, 06:34, 13:34, 14:34; 2026-10-27 00:34 | 5 |
| NO_RUN_FOUND | 2026-10-26 12:34; 2026-11-01 08:34 | 2 |

The two RUN_WITHOUT_LINE slots come from the defect recorded in `16-43-freeze-first-clean.md`.
The seven other slots are scheduled runs that GitHub started later than the grace or did not
start; the cron already ran at minute 34 (decision Q-Q), so the move off the top of the hour did not
prevent them. D065 item 4: a missing tick is an EVIDENCE_GAP, never tolerated because GitHub may
delay or drop it, and the qualifying 14-day trial starts again with a new epoch pin.

### Continuous uncovered time: 3034.95 s

One block from 2026-10-27 00:09:25 to 01:00:00 UTC (WS_DISCONNECTED, CRASH, WS_RECONNECT_WINDOW).
It is the market-stream silence recorded in `16-43-ws-silence-2026-10-27.md`: seven fail-closed
cycles, then a reconnect window that lasts until the next closed bar. The evaluator counts the
runtime as covered again only from that bar, so the block is longer than the 33 minutes between the
first warning and the last restart. The ceiling is the user's O-07 number, 900 s, and the block is
about 3.4 times larger.

## What the trial shows beyond the criteria

- The registry was frozen for the whole window (333 CLEAN lines, one epoch, one hash).
- The runtime covered 99.64 % of the window and the replay parity held to zero differences.
- Time of day and tick timing are observations and do not change any criterion
  (tick duration median 185 ms, max 1864 ms, queue depth max 10, 0 dropped events).
- The criteria do not judge PnL. From 2026-10-31 no simulated position opened because of the cluster
  cap (`16-43-cap-reject-2026-11-03.md`), so the PnL sample is small and no conclusion on the
  strategy follows from this trial.

## Notes on earlier statements

- `16-DEC-PARITY.md` (2026-10-10) says parity stays NOT EVALUATED until the gap-closure plan lands.
  The evaluator now evaluates parity on a real bundle with zero differences, so that plan has
  landed. The decision file is not edited here; this note records the change of state.
- The first export used `--window-start 2026-10-25T12:37:43Z`, which is 0.83 s before the pin, and the
  evaluator marked the trial window FAIL. The bundle was exported again with the exact pin instant
  and that line passed. Both reports show the same other results (the second has 5 more processed
  bars and 19 more runtime records because the first bundle ended earlier).
- A mid-trial reading of this window in the session assumed the evaluator would refuse an
  as-of before the window end plus the grace; the exporter accepts an explicit `--as-of` only in
  whole seconds, so the final bundle of a window whose pin has a fractional second is made without
  `--as-of` (the default is the window end plus the grace).

## Owner decisions and work before a new trial

A new qualifying trial needs a new epoch pin. Open items, none of them changed here:

1. Equity base of the cluster cap and of sizing, and the quantity and risk on the confirm card
   (`16-43-cap-reject-2026-11-03.md`). A fix is a new parameter set and a new `strategy_version`.
2. Root cause of the market-stream silence and the repeated fail-closed cycles
   (`16-43-ws-silence-2026-10-27.md`).
3. A way to lower the chance of a missing or late freeze tick that does not create a tolerance
   (D065 item 4 allows researching mitigations, not tolerating gaps).
4. The running soak (container `trading-soak-paper-1`) is untouched and still on this epoch.

No code or configuration was changed for this record.
