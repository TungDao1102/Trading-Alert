---
phase: 13-research-data-foundation-fixes
plan: 12
subsystem: research-universe-freeze
tags: [universe, freeze, survivorship-bias, one-way-door, operator-action]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-10 freeze tool (propose/freeze, FreezeReport, two-witness writer)"
provides:
  - "docs/research/universe/research-universe-v1.freeze-report.json (ranking evidence, proposal_sha256)"
  - "research-universe-v1.toml FROZEN with 12 symbols and content_sha256"
  - "FROZEN_CONTENT_SHA256 second witness in scripts/decision_alignment/universe.py"
affects: [13-13, backtest, experiment universe_hash]

key-files:
  created:
    - docs/research/universe/research-universe-v1.freeze-report.json
  modified:
    - docs/research/universe/research-universe-v1.toml
    - scripts/decision_alignment/universe.py
    - tests/test_decision_alignment_universe.py

key-decisions:
  - "Operator decision 2026-10-03: freeze-as-proposed, approved proposal_sha256 5b5dc9516511099f4ed980a1d775b198e3308c9903298107e9d50abad552f92c. No proposed symbol was UNAVAILABLE, so freeze-noting-unavailable would have produced the same 12 symbols."
  - "The operator ran the dry run and the --freeze write themselves in their own terminal; the executor then updated the test and committed."

requirements-completed: [DATA-01, BKTS-02]

duration: operator-gated
completed: 2026-10-03
---

# Phase 13 Plan 12: Research universe freeze

The point-in-time research universe v1 is FROZEN. Manifest, second witness and updated real-manifest test landed in one commit.

## Commits

| Task | Commit | What |
|------|--------|------|
| 1 | `e9b2735` | Freeze report (only that file) |
| 3 | `f1d63e0` | Manifest FROZEN, FROZEN_CONTENT_SHA256 witness, test rewrite (one commit) |

## Task 1 review block (verbatim from `propose`)

```
universe_freeze propose: run_date=2026-10-03 dataset_start=2024-10-03 window=[2024-09-03, 2024-10-03) top_n=12
candidates=685 eligible=274
proposed (rank order):
   1 BTCUSDT 2 ETHUSDT 3 SOLUSDT 4 1000PEPEUSDT 5 SUIUSDT 6 WIFUSDT
   7 XRPUSDT 8 REEFUSDT (SETTLING, delivery 2025-01-22) 9 DOGSUSDT 10 DOGEUSDT 11 BNBUSDT 12 WLDUSDT
   all: source=REST trade=REST mark=REST
unrankable (no source, 25, all UNAVAILABLE): 1000BTTCUSDT AKROUSDT ANCUSDT ANTUSDT AUDIOUSDT BDXNUSDT
  BLUEBIRDUSDT BTSUSDT BTTUSDT BZRXUSDT COCOSUSDT DODOUSDT DOTECOUSDT FOOTBALLUSDT GALUSDT HNTUSDT
  KEEPUSDT LENDUSDT LUNAUSDT MBLUSDT NUUSDT RNDRUSDT SRMUSDT TOMOUSDT YFIIUSDT
UNAVAILABLE proposed data: none
proposal_sha256: 5b5dc9516511099f4ed980a1d775b198e3308c9903298107e9d50abad552f92c
```

## Decision record (Task 2)

- Option: `freeze-as-proposed`
- Approved proposal_sha256: `5b5dc9516511099f4ed980a1d775b198e3308c9903298107e9d50abad552f92c`
- Date: 2026-10-03
- Resulting manifest content_sha256: `d6223620ade78290ca6b0a2eeeadd3430eb35316a42c78894afa2d62a82a1682`
- Known recorded gaps: the 25 unrankable symbols above (no trade or mark source for the ranking window).

## Verification

- `verify_decision_alignment.py universe` ends `ALL_PASS universe`.
- `pytest tests/test_decision_alignment_universe.py tests/test_universe_freeze.py` passes.
- Witnesses match: CLI hash equals `FROZEN_CONTENT_SHA256`.
- `_draft()` now reads the DRAFT fixture from plan 13-10, so the DRAFT rejection tests are unchanged; the old draft-state test became `test_real_manifest_is_frozen_with_matching_witnesses`.

## Deviations

- Task 3 was run by the orchestrator instead of the executor subagent, because the executor correctly refused to treat a relayed approval as the user's own. The operator typed the freeze command directly.

## Next

Plan 13-13: re-issue the collect list with the still-TRADING frozen symbols, then the operator runs the real backfill.
