---
phase: 11-decision-alignment
plan: 06
subsystem: authority-documents
tags: [d031, d-12, d-13, f-052, tradingview, quantization, generated-blocks, gate-module]
status: complete

requires:
  - phase: 11-decision-alignment
    provides: 11-01 protocol quantization block, 11-04 RISK_MANAGEMENT "Canonical order (D031)" line and SECURITY_AND_OPERATIONS webhook pointer, gate-module pattern (scripts/decision_alignment)
provides:
  - TRADINGVIEW.md section 5 stating that TradingView cannot sign requests, with the real control set and an F-052 verify marker
  - STACK.md and AGENTS.md FastAPI row without the false "HMAC-checked" claim
  - One canonical quantization order restated by pointer in PROJECT.md and AGENTS.md
  - scripts/decision_alignment/authority.py gates AU-01..AU-06 plus 41 tests
affects: [11-07, 11-08, phase-15, phase-17]

requirements-completed: []

actuals:
  tokens: 9000
  tasks: 2
  commits: 2
plan_head_before: e892833ba11c093739138bbd99a3cd93be3fd3a0
plan_head_after: 5861890a5e35364a00547689c89996fc28be6917

tech-stack:
  added: []
  patterns:
    - "Generated-block drift gate: compare the source line (STACK.md / PROJECT.md) with the generated AGENTS.md line by prefix; source is edited first"

key-files:
  created:
    - scripts/decision_alignment/authority.py
    - tests/test_decision_alignment_authority.py
  modified:
    - .planning/research/STACK.md
    - .planning/PROJECT.md
    - AGENTS.md
    - docs/integration/TRADINGVIEW.md

key-decisions:
  - "Task 1 wording states TradingView has no request-signing facility and no custom-header mechanism; the page is silent on signing, so this is recorded as an audit design recommendation (F-052) with a verify-before-implementation marker"
  - "Quantization tokens are matched with min(imum)? so the protocol wording (minimum quantity / minimum notional) and the instruction-file wording (min quantity / min notional) are both accepted while the order stays fixed"

requirements-completed-note: "RISK-02 and EXEC-02 are also claimed by 11-05 and 11-08, so they were deliberately not marked complete here."

coverage:
  - id: D1
    description: "No file claims TradingView webhooks are HMAC-checked; TRADINGVIEW section 5 documents the real scheme with the F-052 verify marker"
    requirement: "RISK-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_authority.py (AU-01, AU-02 positive, pre-change and per-phrase negative tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Generated AGENTS.md FastAPI row and Quantization bullet equal their STACK.md / PROJECT.md sources"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_authority.py (AU-03, AU-05 drift and pre-change tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "RISK_MANAGEMENT section 11, protocol section 2, PROJECT.md and AGENTS.md agree on one quantization order and the old ordering is gone"
    requirement: "EXEC-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_authority.py (AU-04 four-location agreement, swap and pre-change tests; AU-06)"
        status: pass
    human_judgment: false
---

# Phase 11 Plan 06: Authority Documents Alignment Summary

**The false "HMAC-checked" TradingView claim is removed everywhere and replaced by the real control set (secret URL path, source-IP allow-list, 3-second acknowledgement, de-duplication, normalisation, 2FA), and PROJECT.md and AGENTS.md now restate the single canonical quantization order by pointer, with a six-gate module that fails if either drifts.**

## Performance

- **Completed:** 2026-09-30
- **Tasks:** 2 (1 tracer, 1 auto/tdd)
- **Files:** 2 created, 4 modified; nothing under `src/` touched

## Accomplishments

- `STACK.md` line 57 was edited first, then the identical FastAPI row applied to `AGENTS.md` line 77: "TradingView webhooks (secret URL path + source-IP allow-list; TradingView cannot sign requests)". The rest of the row is unchanged. All `<!-- GSD:... -->` markers are untouched.
- `TRADINGVIEW.md` section 5 rewritten: no signing facility, so HMAC verification is unavailable; V1 has no webhook endpoint (INTG-02 is v2); six controls (secret path segment kept out of the body, source-IP allow-list with the four addresses recorded on 2026-09-30, acknowledge within 3 seconds, idempotent de-duplication, payload normalisation, 2FA); F-052 and a "verify against current TradingView docs" marker. Section 7 gains one pointer sentence. Sections 1-4 and 6 are unchanged (git diff hunks touch only lines 36+ and the file's last line).
- `PROJECT.md` line 53 was edited first, then `AGENTS.md` line 16: floor to stepSize, reject below min quantity, reject below min notional, reject below minimum_risk_utilization_after_rounding (60% baseline), NO_TRADE preferred over round-up, identical in backtest/paper/live, canonical statement in `docs/trading/RISK_MANAGEMENT.md` section 11 (D031). This matches `src/risk/quantization.py`.
- `authority.py`: AU-01 (no "HMAC-checked" in docs/, AGENTS.md, STACK.md, PROJECT.md), AU-02 (TRADINGVIEW section 5 phrases), AU-03 (FastAPI row drift), AU-04 (token order across RISK_MANAGEMENT canonical line, protocol quantization block, PROJECT bullet and AGENTS bullet), AU-05 (Quantization bullet drift), AU-06 (old ordering phrase absent). All green on the real repo.

## Task Commits

1. Task 1 (tracer): `74bcc57` - STACK.md and AGENTS.md FastAPI row, TRADINGVIEW.md sections 5 and 7, gates AU-01..AU-03
2. Task 2: `5861890` - PROJECT.md and AGENTS.md Quantization bullet, gates AU-04..AU-06

## Verification

- `pytest tests/test_decision_alignment_authority.py -q -p no:cacheprovider`: 41 passed (Task 1 checkpoint: 23 passed).
- `authority.run()` one-liner: 6 gates, 0 failed.
- `ruff check` clean; `ruff format` applied; `mypy` on the module clean.
- Regression run alongside: `test_decision_alignment_ops_risk`, `test_risk_quantization`, `test_drills` all pass.
- RED was observed before each GREEN (13 failures before the Task 1 edits; 4 failures before the Task 2 edits).
- `git diff 679825c -U0 -- AGENTS.md` shows exactly two changed lines (16 and 77); `.planning/PROJECT.md` line 53 only; `.planning/research/STACK.md` line 57 only; zero `GSD:` marker lines in the AGENTS.md diff.
- `git diff 679825c --stat -- src/` is not empty, but the only file is `src/domain/registry.py` from plan 11-02; `src/risk/` is unchanged.
- Precondition (SOURCES.md): the TradingView webhooks page is not listed by URL in `docs/SOURCES.md` (only a generic "Webhook Alerts documentation" bullet), so the page was re-fetched with `curl` and cited directly without editing SOURCES.md. Confirmed on the fetched page: source IPs 52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7; ports 80/443 only; 3-second cancellation; no IPv6; webhook alerts require 2-factor authentication; no mention of request signing or custom headers.

## Deviations from Plan

**1. [Ordering] Tracer RED/GREEN committed together per task.** As in plans 11-01..11-04, each task is one commit containing the tests and the implementation; RED was run and observed but not committed separately.

**2. [Scope note] Acceptance line "git diff 679825c --stat -- src/ is empty"** cannot hold at this point because plan 11-02 legitimately changed `src/domain/registry.py`. This plan changed nothing under `src/`.

**Total deviations:** 0 fixes, 2 notes. **Impact:** none.

## Issues Encountered

- The FastAPI row still says "Pydantic-v2-native request validation gives signature/body checks almost free". The plan requires the rest of the row to stay unchanged, and this is generic Pydantic wording rather than a TradingView claim, so it was left as is. It could be reworded in a later pass if it is felt to be misleading.
- Git prints LF/CRLF warnings for the new files (working tree is CRLF via autocrlf); commits are unaffected.

## Known Stubs

None.

## Threat Flags

None. T-11-15 (webhook built on the false HMAC belief) is mitigated by AU-01 and AU-02; T-11-16 (generated block drift) by AU-03 and AU-05.

## Next Phase Readiness

Ready for the remaining Phase 11 plans (11-05 exchange facts, 11-07, 11-08). If 11-05 adds the TradingView webhooks page URL to `docs/SOURCES.md`, the TRADINGVIEW.md link is already the same URL.

## Self-Check: PASSED

Files exist (authority.py, test file, TRADINGVIEW.md, STACK.md, PROJECT.md, AGENTS.md); commits 74bcc57 and 5861890 found in git log; verify commands re-run green.
