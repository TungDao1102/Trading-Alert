---
phase: 25-demo-integration-test-campaign
plan: 06
subsystem: demo-vs-mainnet-record
tags: [D-07, D-12, criterion-4, G2-030, EXEC-01, OPS-01, docs]
requires: []
provides:
  - "docs/operations/DEMO_VS_MAINNET.md: 36 rows (DVM-01 to DVM-36), each with exactly one label (DEMO_OBSERVED, DEMO_FAULT_INJECTED, DOCS, NOT_OBSERVED), a source and the Phase 26 implication; empty 'Scenario evidence (campaign)' section for plan 25-20"
  - "docs/DOC_STATUS.md: Operations index line and a 2026-11-07 change-log line"
  - "09-EXCHANGE-FACTS.md: Demo cross-check lines of Facts 2, 3, 4, 5 and Addenda A, B filled from recorded Demo ids"
affects: [25-20, phase-26]
tech-stack:
  added: []
  patterns:
    - "one evidence label per row with a path, case id and order or client id; an injected trigger is DEMO_FAULT_INJECTED, never DEMO_OBSERVED"
key-files:
  created:
    - docs/operations/DEMO_VS_MAINNET.md
  modified:
    - docs/DOC_STATUS.md
    - .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md
key-decisions:
  - "Rows are split where one topic mixes an observed fact and a gap (for example DVM-01 Demo depth is DEMO_OBSERVED, DVM-02 mainnet slippage is NOT_OBSERVED), so no row claims more than its evidence."
  - "Stream gap: the missing replay of frames (DVM-24) is DEMO_OBSERVED, the supervisor state names for SAFE_MODE exit row 7 (DVM-25) are DEMO_FAULT_INJECTED because the probe forced the drop."
  - "listenKey 60-minute validity, the 24-hour cut-off and the 200 conditional-order limit are DOCS rows citing the SOURCES.md record; their read method (summarising tool, Wayback) is stated and a re-check is advised."
requirements-completed: [EXEC-01, OPS-01]
status: complete
actuals:
  tokens: 7400
  tasks: 2
  commits: 2
plan_head_before: bca8e60f1b371cb75de785e1851d71e71188e14d
plan_head_after: 86eb6be1e4c1f4640c8d3f78807b0178b81829be
---

# Phase 25 Plan 06: Demo-versus-mainnet record Summary

Phase 26 now has one table that says what Binance Demo proved, what was injected and what only mainnet can show, and every exchange fact of Phase 9 says whether a recorded Demo order confirmed it. Documentation only: no file under `src`, `tests`, `params` or the dependency set changed, and no decision, flag or parameter changed.

## Commits

| Task | Commit | Files |
|------|--------|-------|
| 1 (tracer) | 5995f8cb | docs/operations/DEMO_VS_MAINNET.md, docs/DOC_STATUS.md |
| 2 | 86eb6be1 | .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md (six Demo cross-check lines), docs/operations/DEMO_VS_MAINNET.md (DVM-08 wording: multiplierUp not recorded) |

## Label counts (36 rows)

DEMO_OBSERVED 22, DEMO_FAULT_INJECTED 1 (DVM-25), DOCS 3 (DVM-26, DVM-27, DVM-35), NOT_OBSERVED 10 (DVM-02, 03, 07, 12, 13, 22, 28, 29, 30, 31). Nothing is labelled mainnet-observed.

D-07 observation-only items: A2 GTD expiry (DVM-22, NOT_OBSERVED: no terminal status seen), A3 legs after close (DVM-21, DEMO_OBSERVED), B2/B3 (DVM-19 -2013 right after NEW, DVM-20 -4116), stream states for SAFE_MODE exit row 7 (DVM-24, DVM-25), the -1003 ban text (DVM-30, NOT_OBSERVED). The real 418 beyond 259200 s (DVM-28) and the 429/418 queue order (DVM-29) are permanent NOT_OBSERVED rows with the reason "owner decision 2026-10-22: never provoked".

## Cross-check lines changed in 09-EXCHANGE-FACTS.md (G2-030)

| Entry | New status | Source (date, evidence, Demo id) |
|-------|------------|----------------------------------|
| Fact 2 active algo statuses | OBSERVED in part | 2026-10-22 `demo-probe-EVIDENCE-20261022T120704Z.json` (stop client algo id dprobe-tbs-20261022T120704Z-12, child order 28645789207; TP1 dprobe-tp1-20261022T120704Z-15); 2026-11-06 smoke (order 28668586471, xa-cda74315b3b878e4e2f54f5ce37281d SL/T1/T2). The active-versus-terminal classification stays undecided. |
| Fact 3 reduceOnly on algo orders | OBSERVED | 2026-10-22 same file, TP1 child order 28645790346; 2026-10-16 `demo-probe-EVIDENCE-20261016T142134Z.json` case `rejected_protective_variants` (-1106 for reduceOnly with closePosition) |
| Fact 4 MIN_NOTIONAL on reduce-only legs | OBSERVED | 2026-10-16 case `below_min_notional_reduce_only_leg` (dprobe-bml-20261016T142134Z-20); 2026-10-22 TP1 32.7 USDT filled; 2026-10-23 -4164 for a non-reduce-only entry (dprobe-mnl-20261023T140731Z-3) |
| Fact 5 limit of 200 | NOT YET OBSERVED, now names Phase 25 | No scenario or probe case places 200 conditional orders; recorded as DVM-35 (DOCS) |
| Addendum A algo endpoints on Demo | OBSERVED | 2026-11-06 smoke (`base_url`, order 28668586471, three algo client ids); 2026-10-22 open-algo list (algo id 1000000251915712) |
| Addendum B PERCENT_PRICE | OBSERVED in part | 2026-10-16 -4016 above 86305.10 (dprobe-rfl-20261016T142134Z-8); rerun accepted and filled BUY LIMIT at 83366.80 (order 28636771570); multiplierUp not recorded, formula not confirmed numerically |

Facts 1 and 6 (already OBSERVED), the fact text, the code-impact paragraphs and the header paragraph were not touched: every removed line in the diff starts with `**Demo cross-check:**`.

## Verification

- Task 1 automated check: 36 rows, none without a known label or a source; `uv run python scripts/verify_decision_alignment.py all` ALL_PASS (re-run after Task 2: ALL_PASS).
- Task 2 automated check: 8 cross-check lines, none lost its status word, no NOT YET OBSERVED line without "Phase 25".
- Acceptance: `git grep "operations/DEMO_VS_MAINNET.md" -- docs/DOC_STATUS.md` 2 lines; "never provoked" appears in 4 lines of the new document.
- `uv run pytest tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_protocol.py tests/test_deploy_docs.py tests/test_phase23_gate.py`: all passed. `uv run mypy src`: no issues in 291 files. `uv lock --check`: resolved; `git diff --exit-code -- pyproject.toml uv.lock` exits 0.
- Line endings kept: both edited tracked files are CRLF in the working tree and LF in the index (edited bytes-aware); the new document was written CRLF to match.

## Deviations from Plan

- **[Rule 1 - Accuracy] Plan wording "partial fills (A10)".** In 19-OWNER-GAPS the partial-fill assumption is A5 (A10 is the exchangeInfo read during an emergency close); DVM-03 cites A5. The 25-RESEARCH list also calls it A10 for scenario S02; no content impact.
- **Fact 5 keeps NOT YET OBSERVED without a scenario id.** The plan asks for the scenario or probe case that can observe it; none exists (200 conditional orders is not planned), so the line says that and points to DVM-35 instead of inventing an id.
- No other deviations. No auth gate, no checkpoint, no package install.

## Not covered by an agent-run test

- Each DEMO_OBSERVED figure was read from the recorded evidence JSON or the owner-gap summaries and copied by hand; the only machine check is the row format (label, five columns, non-empty source). A wrong figure would not fail a test.
- DVM-26, DVM-27 and DVM-35 depend on documentation pages that SOURCES.md records as read through a summarising tool or a Wayback snapshot, not live; the live pages answer bots with a challenge. They should be re-read before Phase 26 relies on the numbers.
- DVM-13 (virtual-fund resets) rests on the absence of evidence: the Binance FAQ was never read.
- The `tests/test_phase25_gate.py` row check named in 25-RESEARCH Pattern 5 does not exist yet; this plan wrote the table it will parse (row ids DVM-NN, label in column 3).

## Known Stubs

None. The empty "Scenario evidence (campaign)" table is intentional: plan 25-20 fills it from the owner's Demo sessions.

## Threat Flags

None. Only order ids, client ids, error codes and dates were copied from evidence; no key, token, listenKey value or URL with a secret (T-25-14). Every row has a source (T-25-13). No dependency added (T-25-SC).

## Self-Check: PASSED

- docs/operations/DEMO_VS_MAINNET.md: FOUND
- Commits 5995f8cb and 86eb6be1: FOUND in HEAD history
