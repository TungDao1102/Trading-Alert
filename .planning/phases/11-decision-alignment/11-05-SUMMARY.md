---
phase: 11-decision-alignment
plan: 05
subsystem: exchange-facts-docs
tags: [f-051, f-053, f-054, f-056, f-057, d031, d034, d037, d-13, d-14, source-register, gate-module]
status: complete

requires:
  - phase: 11-decision-alignment
    provides: plan 11-04 D034 SAFE_MODE ladder wording and gate-module pattern (scripts/decision_alignment); orchestrator-fetched Binance facts in 11-05-WEBFACTS.md
provides:
  - EXECUTION_SPEC section 12 with the account-wide 200 conditional-order limit, new section 6.1 with algo trigger-time status semantics, corrected position-mode citation, D034 orphan/reconciler and emergency-control wording
  - BINANCE.md WebSocket URL split (/public, /market, /private), explicit MARK_PRICE workingType, MARKET_LOT_SIZE and PERCENT_PRICE filters, audit claims labelled unverified
  - docs/SOURCES.md dated register "Facts verified for Phase 11 (2026-09-30)" with URL, use, date and honest retrieval method for every exchange fact
  - No coin-futures citation left anywhere under docs/
  - scripts/decision_alignment/exchange.py gates EX-01..EX-08 (9 results: EX-06a included) plus 73 tests
affects: [11-08, phase-18, phase-19, phase-20]

requirements-completed: []

actuals:
  tokens: 11500
  tasks: 3
  commits: 3
plan_head_before: 130618f522d63829e4a885a706fc8235358c9153
plan_head_after: a2eceb8cb1cd0513e6cf9c4885b3494cf6723498

tech-stack:
  added: []
  patterns:
    - "Gate module of pure text functions (normalise, numbered-section extract, required phrases, per-line forbidden regexes) plus run(); negative tests use git show 679825c"
    - "Source-register gate: every developers.binance.com / tradingview.com URL cited in a document must appear in the dated SOURCES.md table with fetch date and method"

key-files:
  created:
    - scripts/decision_alignment/exchange.py
    - tests/test_decision_alignment_exchange.py
  modified:
    - docs/trading/EXECUTION_SPEC.md
    - docs/SOURCES.md
    - docs/integration/BINANCE.md
    - docs/architecture/ARCHITECTURE.md
    - docs/research/TRADING_STRATEGY_RESEARCH.md

key-decisions:
  - "The 200 conditional-order limit is documented from the dated change-log entry (2025-12-29), not from the common-definition page, which is recorded in SOURCES.md as stale"
  - "Pages that could not be retrieved keep a verify marker and are registered as 'not fetched' with the exact curl behaviour, never as fetched"
  - "The 2025-12-15 deprecation date of CONDITIONAL_ORDER_TRIGGER_REJECT is stated only as a search-summary report, not as a confirmed fact"

requirements-completed-note: "EXEC-02, OPS-01, RISK-02 are also claimed by 11-08 and were deliberately not marked complete here; the 13 new REQ-IDs were not touched."

coverage:
  - id: D1
    description: "EXECUTION_SPEC states the 200 conditional-order limit is account-wide with the dated change-log citation and verify marker"
    requirement: "RISK-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_exchange.py (EX-01 positive, pre-change, per-phrase and reintroduction tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Algo trigger-time semantics (FINISHED is not filled, REJECTED/EXPIRED at trigger, reason in o.rm), D034 orphan/reconciler and emergency-control wording, Change-Position-Mode citation"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_exchange.py (EX-02..EX-05)"
        status: pass
    human_judgment: false
  - id: D3
    description: "BINANCE.md WebSocket split, workingType default, MARKET_LOT_SIZE / PERCENT_PRICE, unverified audit claims; dated source register; no coin-futures citation"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_exchange.py (EX-06, EX-06a, EX-07, EX-08)"
        status: pass
    human_judgment: true
---

# Phase 11 Plan 05: Exchange Facts Alignment Summary

**The docs now state the Binance 200 conditional-order limit as account-wide, document algo-order trigger-time failure modes and the /public /market /private WebSocket split, send MARK_PRICE explicitly, and every one of those facts is registered in a dated SOURCES.md table with its true retrieval method; a 9-result gate module (EX-01..EX-08) fails if the stale wording returns.**

## Performance

- **Completed:** 2026-09-30
- **Tasks:** 3 (1 tracer, 2 auto/tdd)
- **Files:** 2 created, 5 modified; no `src/` file touched (`git diff 130618f -- src` empty)

## Accomplishments

- EXECUTION_SPEC section 12: the `MAX_NUM_ALGO_ORDERS` filter was removed on 2025-12-29 and the limit is 200 open conditional orders across all symbols (account-wide, not per symbol); the risk/execution layer counts algo orders account-wide; the stale common-definition page is called out; verify marker and F-051.
- New EXECUTION_SPEC 6.1: NEW / TRIGGERING / FINISHED / REJECTED / EXPIRED, "FINISHED does not mean filled", REJECTED and EXPIRED can occur at trigger after the SL was accepted, no margin check before a conditional order triggers, reason in `o.rm` of `ALGO_UPDATE`, trailing-stop double NEW event; grounding and confidence stated in the section itself (F-054).
- Section 8 cites Change-Position-Mode instead of New-Order and gives -4067 / -4068 (from the installed SDK docstring). Section 9: a stop paired with a working ENTRY order is not an orphan (F-401); a missing stop is re-placed at the original plan SL, superseding the cancel-only decision (D034). Section 11: "disable new entry orders", an explicit protect action, protective and reduce-only orders never blocked.
- BINANCE.md: WebSocket URL paths with the 2026-04-23 legacy retirement; user data on `/private`; `workingType` must be `MARK_PRICE` explicitly because the API default is `CONTRACT_PRICE` (D037); `MARKET_LOT_SIZE` and `PERCENT_PRICE` definitions; the two audit claims (triggered `*_MARKET` exits fall under `MARKET_LOT_SIZE`; reduce-only legs skip `MIN_NOTIONAL`) explicitly "unverified, confirm on the demo before Phase 19"; cross-references to EXECUTION_SPEC 6.1 and 12.
- Coin-futures citations replaced in SOURCES.md, ARCHITECTURE.md and TRADING_STRATEGY_RESEARCH.md (URL only, one line changed); EX-08 scans every markdown file under `docs/`.
- `exchange.py`: EX-01, EX-02, EX-03, EX-04, EX-05, EX-06, EX-06a, EX-07, EX-08 all green on the real repo.

## Task Commits

1. Task 1 (tracer): `2714f28` - account-wide 200 limit, source register, gates EX-01 and EX-06a
2. Task 2: `32b5696` - algo status semantics, position-mode citation, D034 wording, gates EX-02..EX-06
3. Task 3: `a2eceb8` - BINANCE.md, remaining citations, gates EX-07 and EX-08

## Verification

- `pytest tests/test_decision_alignment_exchange.py -q -p no:cacheprovider` and `tests/test_kill_gate_docs.py`: all green (73 tests in the exchange file).
- `exchange.run()` one-liner: 9 gate results, 0 failed.
- `ruff check`, `ruff format --check` and `mypy` on the module: clean.
- Sibling gate suites (`ops_risk`, `authority`) green alongside; full-repository `pytest -x -q` ran to 100% with no failure line.
- Each task commit touched only files in `files_modified`; the TRADING_STRATEGY_RESEARCH diff is one line (one URL).

## Deviations from Plan

**1. [Rule 3 - Blocking] No WebFetch for the executor**
- **Found during:** Tasks 1-3 preconditions
- **Issue:** The plan requires WebFetch of the Binance pages; the executor has none and `curl` gets HTTP 202 with an empty body (with a browser user-agent it gets a 302 first, then the same empty 202).
- **Fix:** Used the orchestrator's WebFetch results in `11-05-WEBFACTS.md` (recorded in SOURCES.md as "WebFetch (orchestrator, summarised by the tool's small model)", MEDIUM confidence, verify markers kept). TradingView about-webhooks was fetched directly with curl (HTTP 200, text searched).
- **Commit:** 2714f28, 32b5696

**2. [Rule 3 - Blocking] Event-Algo-Order-Update page unavailable**
- **Issue:** The orchestrator's WebFetch again returned only the documentation shell; curl got the same 302 + empty 202.
- **Fix:** Field names taken from the installed SDK model `algo_update_o.py` (`X` "Algo Status", `rm` "Algo order failed reason", `ia`); status meanings from the search summary in 11-RESEARCH.md. SOURCES.md and EXECUTION_SPEC 6.1 both say so and require re-confirmation on the official page before Phase 18. The SDK model does not list status words, so the status table is MEDIUM confidence. The 2025-12-15 deprecation date of `CONDITIONAL_ORDER_TRIGGER_REJECT` appears only in the search summary and is worded that way in 6.1.
- **Commit:** 32b5696

**3. [Rule 3 - Blocking] Change-Position-Mode, websocket Connect and user-data-streams pages not retrievable**
- **Fix:** Registered as "Not fetched" with the observed redirect behaviour (the Change-Position-Mode path redirected to the catalog anchor `#change-position-mode`, so it exists). Position-mode wording rests on the installed SDK docstring (-4067 / -4068); the citations carry verify markers.
- **Commit:** 32b5696, a2eceb8

**4. WebSocket 24-hour lifetime re-check (requested by the orchestrator)**
- Neither WEBFACTS nor the SDK states a 24-hour lifetime, so it stays unconfirmed. The "believed to" marker was kept in SECURITY_AND_OPERATIONS (plan 11-04's file, not edited here) and applied in the same form to ARCHITECTURE.md and BINANCE.md section 3. SOURCES.md registers the Connect page as not fetched.

**5. [Ordering] Common-definition row registered in Task 1, and RED shown by baseline negatives**
- The common-definition row (needed for the stale-page note) was added in Task 1 rather than Task 2. Each task is one commit (as in 11-04), not separate RED and GREEN commits: RED was confirmed by running the new tests before the document edits in Task 1; in Tasks 2 and 3 the document edits were made just before the gate functions, so RED there is evidenced by the pre-change (`git show 679825c`) negative tests rather than a failing run.

**Total deviations:** 3 blocking-retrieval workarounds, 1 unresolved marker, 1 ordering note. **Impact:** documents are correct to the evidence available and every soft fact is labelled; Phase 18 must re-confirm the algo status list and the 24-hour lifetime, Phase 19 the two unverified filter claims.

## Issues Encountered

- Working tree is CRLF; docs were edited through a CRLF-preserving helper. Git prints LF/CRLF warnings for the new `.py` files; commits are unaffected.
- `EX-02` initially failed because a sentence began with a capital "Verify"; the gates are case-sensitive on the marker, so the wording was lowercased mid-sentence.

## Known Stubs

None. No placeholders were introduced.

## Threat Flags

None. T-11-13 (stale exchange facts) is mitigated by the dated register, verify markers and EX-01..EX-08; T-11-14 (unsourced fact) by EX-06, which requires every cited Binance/TradingView URL in EXECUTION_SPEC to be registered with date and method. T-11-SC: no packages installed.

## Next Phase Readiness

Ready for 11-07 and 11-08 (11-06 is already done). Open items: 11-08 still owes EXEC-02, OPS-01 and RISK-02 completion; the 24-hour WebSocket lifetime, the algo status list (Event-Algo-Order-Update) and Change-Position-Mode text need a real page fetch before Phase 18; the two `MARKET_LOT_SIZE` / `MIN_NOTIONAL` audit claims need the Phase 19 demo.

## Self-Check: PASSED

Files exist (`exchange.py`, its test file, the five amended documents); commits 2714f28, 32b5696, a2eceb8 found in git log; verify commands re-run green.
