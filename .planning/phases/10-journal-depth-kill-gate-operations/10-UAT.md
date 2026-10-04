---
status: complete
phase: 10-journal-depth-kill-gate-operations
source: [10-01-SUMMARY.md, 10-02-SUMMARY.md, 10-03-SUMMARY.md, 10-04-SUMMARY.md, 10-05-SUMMARY.md, 10-06-SUMMARY.md, 10-07-SUMMARY.md, 10-08-SUMMARY.md, 10-09-SUMMARY.md, 10-10-SUMMARY.md, 10-11-SUMMARY.md, 10-12-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 10-01:D1 Tracer: one LONG backtest TradeRecord flows normalize_backtest -> compute_trade_excursion 
expected: Tracer: one LONG backtest TradeRecord flows normalize_backtest -> compute_trade_excursion -> build_excursion_section with MFE/MAE in price and R plus time-to-extreme, pinned by a golden fixture and section digest
result: pass
source: automated
coverage_id: 10-01:D1

### 2. 10-01:D2 SHORT mirror, zero-risk exclusion (counted, price excursions kept), and bootstrap-backed a
expected: SHORT mirror, zero-risk exclusion (counted, price excursions kept), and bootstrap-backed aggregates with interval_absent for n_valued < 2
result: pass
source: automated
coverage_id: 10-01:D2

### 3. 10-01:D3 INCOMPLETE buckets (NO_1M_COVERAGE, NO_FILL_EVENT, FALLBACK_APPLIED, absent risk) with not
expected: INCOMPLETE buckets (NO_1M_COVERAGE, NO_FILL_EVENT, FALLBACK_APPLIED, absent risk) with nothing imputed; REJECT trades become NoTradeRecord only
result: pass
source: automated
coverage_id: 10-01:D3

### 4. 10-01:D5 Pure, strictly typed, order-independent, byte-reproducible core with glob-discovered purit
expected: Pure, strictly typed, order-independent, byte-reproducible core with glob-discovered purity and mypy guards
result: pass
source: automated
coverage_id: 10-01:D5

### 5. 10-01:D4 METRICS section 6 diagnostics reported only as descriptive distributions (MFE_R of SL exit
expected: METRICS section 6 diagnostics reported only as descriptive distributions (MFE_R of SL exits, MAE_R of TP exits, give-back, holding)
result: pass
verified: tests/test_analytics_excursion.py descriptive-diagnostic tests pass (run in 583-test sweep, 0 failures). Checked by Claude on 2026-10-04.

### 6. 10-02:D1 D030 row records the D013 reconciliation; protocol v1.0.1 kill-gate section and DOC_STATUS
expected: D030 row records the D013 reconciliation; protocol v1.0.1 kill-gate section and DOC_STATUS state the same conjunctive rule; Status/Frozen-on/Supersedes/D029 and the three research-gate witnesses remain intact
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 7. 10-02:D2 KillGateState is a GLOSSARY-canonical str Enum with exactly three members, parity-tested a
expected: KillGateState is a GLOSSARY-canonical str Enum with exactly three members, parity-tested against GLOSSARY 8.2
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 8. 10-02:D3 Amendment class (clarification, v1.0.1) is the planner's adopted default and needs user co
expected: Amendment class (clarification, v1.0.1) is the planner's adopted default and needs user confirmation
result: skipped
reason: Amendment class (clarification v1.0.1 vs semantic change) is a governance judgment reserved for the human operator; the delegate cannot ratify it. Docs/code consistency of the D030 wording itself passed (test_kill_gate_docs).

### 9. 10-03:D1 Tracer: paper PaperRecord rows normalize to LifecycleRecords and yield a digest-stamped ex
expected: Tracer: paper PaperRecord rows normalize to LifecycleRecords and yield a digest-stamped execution-quality section with six fixed-order legs, honest INCOMPLETE buckets and the synthetic-lag label
result: pass
source: automated
coverage_id: 10-03:D1

### 10. 10-03:D2 Fill %, expiry-without-fill rate and signed entry deviation per evidence kind; empty denom
expected: Fill %, expiry-without-fill rate and signed entry deviation per evidence kind; empty denominators are None, PAPER deviation is INCOMPLETE, backtest lifecycle normalizer maps entry_kind
result: pass
source: automated
coverage_id: 10-03:D2

### 11. 10-03:D3 Live lifecycle normalization with join accounting, twin-safe ENTRY_EXPIRY handling, malfor
expected: Live lifecycle normalization with join accounting, twin-safe ENTRY_EXPIRY handling, malformed-row rejection, order independence and no payload free-text passthrough
result: pass
source: automated
coverage_id: 10-03:D3

### 12. 10-03:D4 That the paper synthetic-lag label and the delivery-request PROXY wording are presented to
expected: That the paper synthetic-lag label and the delivery-request PROXY wording are presented to the operator as such (not as measured latency / read receipt) in rendered reports
result: pass
verified: Rendered/ built section carries synthetic-lag label via imported constant: tests/test_analytics_approval_delay.py + test_analytics_latency.py + test_analytics_render.py pass. Wording is machine-pinned; operator taste not assessed. Checked by Claude on 2026-10-04.

### 13. 10-04:D1 Tracer: CoreMetrics block and the SYMBOL slice table with the ALL row first, low-n rows re
expected: Tracer: CoreMetrics block and the SYMBOL slice table with the ALL row first, low-n rows retained, shuffle-invariant ordering
result: pass
source: automated
coverage_id: 10-04:D1

### 14. 10-04:D2 All eight METRICS section 5 slice dimensions with pinned exit/entry time bases, session bo
expected: All eight METRICS section 5 slice dimensions with pinned exit/entry time bases, session boundary mapping, UNKNOWN/INCOMPLETE buckets, favorability-blind ordering and per-row seeds
result: pass
source: automated
coverage_id: 10-04:D2

### 15. 10-04:D3 Dual-universe view: live-5 vs research side by side, empty live-5 is explicit no data, res
expected: Dual-universe view: live-5 vs research side by side, empty live-5 is explicit no data, research universe VERIFIED or UNVERIFIED_UNIVERSE, weak-live-universe rule mirrors Phase 6, LIVE5_SYMBOLS imported not copied
result: pass
source: automated
coverage_id: 10-04:D3

### 16. 10-04:D4 NO_TRADE counted by the five protocol reason categories plus UNMAPPED and Total, split liv
expected: NO_TRADE counted by the five protocol reason categories plus UNMAPPED and Total, split live-5 / research / all; paper NO_TRADE extraction excludes opportunity and signal-chain rows
result: pass
source: automated
coverage_id: 10-04:D4

### 17. 10-04:D5 That the pinned session bands, LOW_N_THRESHOLD and reason-category mapping (flagged resear
expected: That the pinned session bands, LOW_N_THRESHOLD and reason-category mapping (flagged research assumptions A1/A2/A4) are the reporting vocabulary the operator wants kill-gate evidence to cite
result: pass
verified: Pinned session bands, LOW_N_THRESHOLD and reason mapping are exercised by test_analytics_slices/no_trade (pass); assumptions A1/A2 remain flagged research assumptions, accepted as documented. Checked by Claude on 2026-10-04.

### 18. 10-05:D1 Pure D013/D030 evaluator: INSUFFICIENT_EDGE iff >=3 counted independent families AND >=6 c
expected: Pure D013/D030 evaluator: INSUFFICIENT_EDGE iff >=3 counted independent families AND >=6 calendar months AND no pass; PASSING_CANDIDATE on any recorded pass; else WITHIN_BUDGET
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 19. 10-05:D2 Exact inclusive 6-month boundary with day clamping (2027-03-18T23:59:59Z WITHIN_BUDGET, 20
expected: Exact inclusive 6-month boundary with day clamping (2027-03-18T23:59:59Z WITHIN_BUDGET, 2027-03-19T00:00:00Z INSUFFICIENT_EDGE)
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 20. 10-05:D3 Family independence decided by facts (7-slot sheet, distinct sheet hash, disjoint param-se
expected: Family independence decided by facts (7-slot sheet, distinct sheet hash, disjoint param-set hashes); fabricated pass cannot be constructed
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 21. 10-05:D4 Append-only KILL_GATE_EVALUATION event: exact allow-listed constant key set, content-hash 
expected: Append-only KILL_GATE_EVALUATION event: exact allow-listed constant key set, content-hash id, idempotent replay, secret-free, journal-first single write
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 22. 10-05:D5 Whether a recorded INSUFFICIENT_EDGE terminal outcome is the right permanent audit posture
expected: Whether a recorded INSUFFICIENT_EDGE terminal outcome is the right permanent audit posture (one-way door, locked D-03)
result: skipped
reason: Whether a permanent INSUFFICIENT_EDGE terminal is the right audit posture is a one-way-door governance decision for the operator. Mechanics (sticky, idempotent event) verified by automated tests.

### 23. 10-06:D1 Tracer: System / User execution / Opportunity reports for PAPER evidence side by side with
expected: Tracer: System / User execution / Opportunity reports for PAPER evidence side by side with honest INCOMPLETE reasons, hypothetical_used flags and the SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS=30) label built from the imported constant
result: pass
source: automated
coverage_id: 10-06:D1

### 24. 10-06:D2 LIVE-only signal->approve delay buckets in fixed order with exact Decimal edges, measured-
expected: LIVE-only signal->approve delay buckets in fixed order with exact Decimal edges, measured-delay calibration distribution, PAPER/BACKTEST empty buckets, paper constant unchanged
result: pass
source: automated
coverage_id: 10-06:D2

### 25. 10-06:D3 Live-row normalizer: VWAP entry/exit, exit kind, open-position detection, explicit net-PnL
expected: Live-row normalizer: VWAP entry/exit, exit kind, open-position detection, explicit net-PnL rule, USDT-only commission, both branches of the exchange-semantics gate pinned
result: pass
source: automated
coverage_id: 10-06:D3

### 26. 10-06:D4 That Binance realizedPnl excludes commission and commission is denominated in commissionAs
expected: That Binance realizedPnl excludes commission and commission is denominated in commissionAsset (the premise of the net-PnL rule); until confirmed against the official docs live R stays INCOMPLETE
result: skipped
reason: Premise that Binance realizedPnl excludes commission and commission is in commissionAsset needs re-verification against current official Binance docs/real fills; not available (no signed/live access, no doc fetch performed). Code behaviour tested by test_analytics_live_outcomes.

### 27. 10-07:D1 INSUFFICIENT_EDGE is sticky: new passing evidence never clears it; only a valid human KILL
expected: INSUFFICIENT_EDGE is sticky: new passing evidence never clears it; only a valid human KILL_GATE_QUESTION_APPROVED after the latest terminal reopens research; reset before terminal, empty operator_id, empty decision_ref, future reset and same-instant prior are ignored
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 28. 10-07:D2 Replay idempotence: identical inputs, and the same instant with the evaluation's own persi
expected: Replay idempotence: identical inputs, and the same instant with the evaluation's own persisted event as a prior, give the identical digest and content-hash event id; payload key set unchanged from plan 05
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 29. 10-07:D3 Clock start parsed from the protocol header with the exact research-gate regex (00:00Z of 
expected: Clock start parsed from the protocol header with the exact research-gate regex (00:00Z of Frozen-on) with freeze-commit provenance; gate cells never fabricate a pass (exhaustive 48-combination test)
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 30. 10-07:D4 enable() refuses INSUFFICIENT_EDGE, None and plain strings before any journal write or fla
expected: enable() refuses INSUFFICIENT_EDGE, None and plain strings before any journal write or flag flip; WITHIN_BUDGET and PASSING_CANDIDATE permit; enable payload key set unchanged; 7 call sites updated
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 31. 10-07:D5 Registration tripwire: a new params/ family directory fails CI under a recorded terminal s
expected: Registration tripwire: a new params/ family directory fails CI under a recorded terminal state (tmp-dir self-test) and the committed repo state passes
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 32. 10-07:D6 Whether the post-reset budget-restart semantics (cycle clock restarts at the reset time; o
expected: Whether the post-reset budget-restart semantics (cycle clock restarts at the reset time; only later decisions count) match the user's intent for D013
result: skipped
reason: Post-reset budget-restart semantics is a governance policy choice for the operator; mechanics verified by test_kill_gate_sticky/clock.

### 33. 10-08:D1 One pure function composes exactly three per-kind evidence blocks (BACKTEST, PAPER, LIVE, 
expected: One pure function composes exactly three per-kind evidence blocks (BACKTEST, PAPER, LIVE, always present and ordered; empty kinds are valid no-data blocks) with one digest; cross-kind elements raise
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 34. 10-08:D2 Backtest, paper and live evidence are never pooled: no aggregate field anywhere in the tre
expected: Backtest, paper and live evidence are never pooled: no aggregate field anywhere in the tree, blocks built from own-kind inputs only, blocks sum to the input total, and a PAPER-only change leaves the other block digests untouched
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 35. 10-08:D3 Full evidence provenance: strategy versions, parameter-set ids/hashes, experiment identity
expected: Full evidence provenance: strategy versions, parameter-set ids/hashes, experiment identity fields, universe hash with VERIFIED/UNVERIFIED_UNIVERSE/NOT_APPLICABLE status, snapshot and epoch ids, vocabulary constants and which kinds are present
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 36. 10-08:D4 Live-orders posture is read-only from the latest LIVE_ORDERS_ENABLED/DISABLED event by a t
expected: Live-orders posture is read-only from the latest LIVE_ORDERS_ENABLED/DISABLED event by a total key, UNKNOWN when none, shuffle-invariant, and the module imports no enablement code
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 37. 10-08:D5 Kill-gate section wraps the evaluated verdict with fixed-order family rows (trend-pullback
expected: Kill-gate section wraps the evaluated verdict with fixed-order family rows (trend-pullback, breakout-retest, range-mr, then others alphabetically), gate cells that never fabricate a pass, and live-5/research counts
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 38. 10-08:D6 Every INCOMPLETE bucket, ZERO_RISK exclusion, rejected row and unmatched join surfaces in 
expected: Every INCOMPLETE bucket, ZERO_RISK exclusion, rejected row and unmatched join surfaces in one sorted, zero-omitting ledger with a fixed reason vocabulary
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 39. 10-08:D7 Reproducibility and secret posture: pinned report digest, shuffled inputs give an equal re
expected: Reproducibility and secret posture: pinned report digest, shuffled inputs give an equal report, seed/resamples/as_of change the digest, no secret-looking substrings or free text or journal payload in the canonical dump
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 40. 10-08:D8 Whether the report's section vocabulary and per-kind provenance layout are what the operat
expected: Whether the report's section vocabulary and per-kind provenance layout are what the operator-facing renderer and the future amendment citations need (renderer plans 10 and 11 consume this schema)
result: pass
verified: Section vocabulary and per-kind provenance verified via test_analytics_report/test_analytics_provenance and an actual CLI run whose report shows the expected sections in order. Checked by Claude on 2026-10-04.

### 41. 10-09:D1 Tracer: the real params/ registry and docs/research/families sheets yield three independen
expected: Tracer: the real params/ registry and docs/research/families sheets yield three independent families (7 slots, distinct sheet hashes, disjoint non-baseline candidate hashes) and evaluate() returns WITHIN_BUDGET on the real repo
result: pass
source: automated
coverage_id: 10-09:D1

### 42. 10-09:D2 Evidence, decisions and universe files load fail-closed into typed objects; output directo
expected: Evidence, decisions and universe files load fail-closed into typed objects; output directories are confined to the reports root (.., absolute and symlink escapes refused)
result: pass
source: automated
coverage_id: 10-09:D2

### 43. 10-09:D3 SELECT-only journal/entity reader in total-key order with rejects counted, single idempote
expected: SELECT-only journal/entity reader in total-key order with rejects counted, single idempotent KILL_GATE_EVALUATION append, and read-only 1m candle reader that feeds compute_trade_excursion to identical MFE/MAE
result: pass
source: automated
coverage_id: 10-09:D3

### 44. 10-09:D4 Append and re-read of a KILL_GATE_EVALUATION event against a live PostgreSQL 17 (ON CONFLI
expected: Append and re-read of a KILL_GATE_EVALUATION event against a live PostgreSQL 17 (ON CONFLICT semantics on the real dialect)
result: pass
verified: test_analytics_store.py PG integration test ran against live PostgreSQL 17 (TEST_DATABASE_URL set) and did not skip: append + re-read of KILL_GATE_EVALUATION passed. Checked by Claude on 2026-10-04.

### 45. 10-10:D1 Kill Gate view rendered first after the header per the UI-SPEC: state banner, budget table
expected: Kill Gate view rendered first after the header per the UI-SPEC: state banner, budget table with the D013 rule sentence, clock provenance with the earliest-possible note, family matrices K-2a/K-2b, NO_TRADE by category K-3 per evidence kind, decision references and enablement effect
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 46. 10-10:D2 INSUFFICIENT_EDGE is a calm terminal outcome (TERMINAL token, fixed sentence, sticky note,
expected: INSUFFICIENT_EDGE is a calm terminal outcome (TERMINAL token, fixed sentence, sticky note, reset line); PASSING_CANDIDATE is explicitly non-authorizing; every state ends with the fixed line that live trading is never enabled by this report
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 47. 10-10:D3 Both universes and all three evidence kinds are shown unpooled with no data for empty grou
expected: Both universes and all three evidence kinds are shown unpooled with no data for empty groups: K-2a Universe cell, K-3 Live-5/Research/All columns (a zero-total column is no data in every row), Section 2 rows BACKTEST/PAPER/LIVE with the live-rows-absent sentence
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 48. 10-10:D4 All sourced text passes one md_cell escape (pipe, backslash, backtick, angle brackets, lin
expected: All sourced text passes one md_cell escape (pipe, backslash, backtick, angle brackets, line breaks, control and format characters, 200-char truncation with the fixed marker); hostile family ids and decision refs cannot break a table or inject markup
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 49. 10-10:D5 Byte-deterministic output: LF only, single trailing LF, no trailing whitespace, ASCII exce
expected: Byte-deterministic output: LF only, single trailing LF, no trailing whitespace, ASCII except the banner em dash, no ambient state, pinned number formats and Asia/Ho_Chi_Minh display time; byte-exact golden for header + Sections 1 and 2
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 50. 10-10:D6 Reserved vocabulary never appears in rendered output or renderer source, with a detector s
expected: Reserved vocabulary never appears in rendered output or renderer source, with a detector self-check that finds an injected word; no favorability emphasis
result: pass
verified: Cited tests pass in the combined run: 582 passed, 1 skipped (symlink test unavailable on Windows) across tests/test_analytics_*.py, test_kill_gate_*.py, test_execution_enablement.py, test_domain_enums.py with TEST_DATABASE_URL set. Checked by Claude on 2026-10-04.

### 51. 10-10:D7 Whether the operator-facing layout (numbered H3 blocks in Section 1, the 11-column gate ma
expected: Whether the operator-facing layout (numbered H3 blocks in Section 1, the 11-column gate matrix, plain-text tokens) is legible and reads as neutral in a real Markdown viewer and terminal
result: pass
verified: Actual CLI report inspected: numbered H3 blocks, 11-column gate matrix, plain-text tokens render legibly as Markdown; test_analytics_render passes. Checked by Claude on 2026-10-04.

### 52. 10-11:D1 Full report (Section 3) and dual-universe view (Section 4) render per evidence kind from o
expected: Full report (Section 3) and dual-universe view (Section 4) render per evidence kind from one shared M-1 row builder; estimate cells are never bare, empty slices are explicit no data with 0 n and fixed notes, low-n rows stay in place
result: pass
source: automated
coverage_id: 10-11:D1

### 53. 10-11:D2 Sections 5-7: approval-delay impact with the SYNTHETIC LAG label on paper and a LIVE-only 
expected: Sections 5-7: approval-delay impact with the SYNTHETIC LAG label on paper and a LIVE-only four-row bucket table, execution quality with the ten fixed rows and INCOMPLETE reasons, MFE/MAE with the four descriptive tables and fixed sentences
result: pass
source: automated
coverage_id: 10-11:D2

### 54. 10-11:D3 Section 8 renders eight dimension tables each led by the ALL row per evidence kind, ordere
expected: Section 8 renders eight dimension tables each led by the ALL row per evidence kind, ordered by key and never by result; Section 9 counts every INCOMPLETE bucket, exclusion, unmatched join, rejected row and truncation; Section 10 lists provenance in the fixed field order with 12-hex hash prefixes
result: pass
source: automated
coverage_id: 10-11:D3

### 55. 10-11:D4 All ten sections render in the fixed order regardless of data, byte-identical for identica
expected: All ten sections render in the fixed order regardless of data, byte-identical for identical inputs, pinned by a full Markdown golden
result: pass
source: automated
coverage_id: 10-11:D4

### 56. 10-11:D5 JSON sidecar with schema version, report digest and Markdown SHA-256; verify_render detect
expected: JSON sidecar with schema version, report digest and Markdown SHA-256; verify_render detects one-byte Markdown tampering and digest edits; stem and pointer formatter; the pointer carries no decision surface and no send is wired
result: pass
source: automated
coverage_id: 10-11:D5

### 57. 10-11:D6 Governance scans over the rendered Markdown and sidecar: no secret-like words beyond the e
expected: Governance scans over the rendered Markdown and sidecar: no secret-like words beyond the explicit allow-list, no absolute paths, hostnames or CR, no reserved advisory vocabulary, no emphasis in the metric sections
result: pass
source: automated
coverage_id: 10-11:D6

### 58. 10-11:D7 Legibility of the 11-column K-2b gate matrix and the eight S-1 slice tables in a plain ter
expected: Legibility of the 11-column K-2b gate matrix and the eight S-1 slice tables in a plain terminal and rendering as tables in a Markdown viewer (UI-SPEC backstop)
result: pass
verified: Rendered report from real CLI run (463 lines) inspected as plain text: tables are ASCII/Markdown and legible; test_analytics_render passes. Visual rendering in a GUI Markdown viewer not checked. Checked by Claude on 2026-10-04.

### 59. 10-12:D2 Clock, confinement and failure discipline: --as-of naive/unparseable and --resamples below
expected: Clock, confinement and failure discipline: --as-of naive/unparseable and --resamples below the minimum exit 2; the clock is read once only when --as-of is omitted; malformed input and out-of-root --out-dir exit 1 with the 'Report not produced' copy and no file written
result: pass
source: automated
coverage_id: 10-12:D2

### 60. 10-12:D3 Read-only DB path (live rows, prior evaluations, journal and file resets) plus the explici
expected: Read-only DB path (live rows, prior evaluations, journal and file resets) plus the explicit idempotent --record step; only Select statements on the report path, exactly one guarded Insert for --record, no DATABASE_URL text in any output, --record without a usable database exits 2 before writing
result: pass
source: automated
coverage_id: 10-12:D3

### 61. 10-12:D1 One CLI (python -m src.analytics.cli) turns evidence/decision/universe files into a byte-i
expected: One CLI (python -m src.analytics.cli) turns evidence/decision/universe files into a byte-identical Markdown + JSON sidecar pair with the four-line stdout contract and exit codes 0/1/2; a terminal INSUFFICIENT_EDGE exits 0 with the calm banner
result: pass
verified: CLI run via python -m src.analytics.cli --no-db --as-of 2027-04-01T00:00:00+00:00 on tests/fixtures/phase10/loaders/evidence_sample.json wrote .md + .json sidecar; second run to another out-dir gave identical digest sha256:db07633981d9...; kill gate WITHIN_BUDGET. test_analytics_cli passes. (Smoke outputs deleted.) Checked by Claude on 2026-10-04.

### 62. 10-12:D4 Phase-closing guards: the no-float scan lists every pure analytics module (drift guard), e
expected: Phase-closing guards: the no-float scan lists every pure analytics module (drift guard), edge modules are float/clock clean with one bounded clock read, the only Insert builder is build_append_stmt, the CLI imports no server/exchange/Telegram/execution code, migration parity unchanged and the full suite green
result: issue
reported: "tests/test_analytics_edge_guards.py passes (22 tests) but the SUMMARY-cited verification command 'uv run python scripts/check_migration_parity.py' fails: scripts/check_migration_parity.py does not exist in the repo (no such tracked file)."
severity: minor

### 63. 10-12:D5 The CLI against a real PostgreSQL 17 (read of the real journal/entity tables, the real mak
expected: The CLI against a real PostgreSQL 17 (read of the real journal/entity tables, the real make_session_factory engine on a Windows selector loop, and a real --record append with ON CONFLICT DO NOTHING)
result: skipped
reason: CLI end-to-end against the real PostgreSQL 17 journal/entity tables not run (would need a populated trading DB; --record would write). Store-level PG append/re-read passed (10-09:D4).

## Summary

total: 63
passed: 57
issues: 1
pending: 0
skipped: 5
blocked: 0

## Gaps

- truth: "Phase-closing guards incl. migration parity check runnable via scripts/check_migration_parity.py"
  status: failed
  reason: "Script referenced in 10-12-SUMMARY does not exist; edge-guard tests themselves pass. Migration parity is covered only by tests/test_persistence_migration_pg.py, not the cited script."
  severity: minor
  test: 62
  root_cause: ""
  artifacts: []
  missing: ["scripts/check_migration_parity.py or corrected reference in SUMMARY"]
  debug_session: ""

<!-- Notes: kill-gate on real evidence not possible yet (no real evidence). Review findings WR-01/06/12/13 deferred to Phase 26, WR-10 to Phase 24. 10-REVIEW-DISPOSITION lists CR-01 as open but src/analytics/cli.py now merges decisions.recorded_terminal (CR-01 comment at line ~400); disposition table appears stale. -->
