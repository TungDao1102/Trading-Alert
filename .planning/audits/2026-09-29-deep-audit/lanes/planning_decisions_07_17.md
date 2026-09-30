# Lane B2: planning_decisions_07_17

## Scope

Stage B review of the planning decisions for phases 07, 07.1, 08, 09 and 10, plus the ROADMAP goal definitions of phases 11–17 (no plans yet) and `.planning/v0.3-MILESTONE-AUDIT.md`. The decisions are judged against the Stage A corrected rules (`lanes/docs_trading_soundness.md` "Corrected Rules for Code Audit", numbered "Rule n" below) and exchange facts (`lanes/docs_exchange_facts.md` "Exchange Facts for Code Audit"). The code is cited only to show what a decision caused. It was not audited deeply; Stage C does that.

Context (AUDIT_CHARTER §11): every CONTEXT.md in this range says the user ran `--auto --chain`. All 25 gray areas (5 per phase) were auto-resolved to the "(recommended default)" option, with no human input.

Web check performed: Binance USDⓈ-M New Order docs (`developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api`) state `newClientOrderId`: "A unique id among open orders". GTD `goodTillDate` must be > now + 600 s. This settles A1 open question / INV-087 "re-verify".

## Coverage

| File | Level | Note |
|---|---|---|
| lanes/docs_trading_soundness.md | NORMAL_READ | Findings index + Corrected Rules + Open Questions read in full |
| lanes/docs_exchange_facts.md | NORMAL_READ | Exchange Facts for Code Audit + Open Questions read in full |
| lanes/*.findings.json (A1, A2) | NORMAL_READ | IDs/summaries |
| INVARIANTS.md | NORMAL_READ (targeted) | INV-047, -074, -078 area, -087, -120, domain-soundness summary |
| AUDIT_CHARTER.md §11, LANES.md B2, LANE_BRIEF.md | DEEP_READ | |
| .planning/v0.3-MILESTONE-AUDIT.md | DEEP_READ | |
| .planning/ROADMAP.md | DEEP_READ | phases 7–17 + progress table |
| phases/07-*/07-CONTEXT.md, 07-DISCUSSION-LOG.md | DEEP_READ | |
| phases/07-*/07-RESEARCH.md | NORMAL_READ | summary, patterns, pitfalls, assumptions, open questions |
| phases/07-*/07-REVIEW.md, 07-REVIEW-FIX.md | NORMAL_READ | headings, fix header (25/25 fixed) |
| phases/07-*/07-0x-SUMMARY.md, COVERAGE.md | NORMAL_READ | deferrals, soak smoke (WS leg BLOCKED) |
| phases/07-*/07-0x-PLAN.md, 07-PATTERNS.md, 07-VALIDATION.md, 07-USER-SETUP.md | METADATA_ONLY | |
| phases/07.1-*/07.1-CONTEXT.md | DEEP_READ | |
| phases/07.1-*/07.1-01-PLAN.md, 07.1-0x-SUMMARY.md, 07.1-PATTERNS.md | NORMAL_READ (grep) | partial_fill_fraction choice |
| phases/07.1-* others (RESEARCH, REVIEW, VERIFICATION, VALIDATION, DISCUSSION-LOG) | METADATA_ONLY | |
| phases/08-*/08-CONTEXT.md | DEEP_READ | |
| phases/08-*/08-RESEARCH.md | NORMAL_READ | patterns 3–4, don't-hand-roll table |
| phases/08-*/08-REVIEW.md, 08-REVIEW-FIX.md | NORMAL_READ | headings, 34/34 fixed |
| phases/08-* PLANs, SUMMARYs, PATTERNS, VALIDATION, COVERAGE, DISCUSSION-LOG | METADATA_ONLY | |
| phases/09-*/09-CONTEXT.md, deferred-items.md, 09-REVIEW-DISPOSITION.md | DEEP_READ | |
| phases/09-*/09-REVIEW.md, 09-REVIEW-FIX.md | NORMAL_READ | WR-07 (skipped), IN-02, open exchange facts list |
| phases/09-*/09-RESEARCH.md, 09-01-PLAN.md, 09-04-SUMMARY.md, COVERAGE.md | NORMAL_READ (grep) | TIF/GTD, working_type, LIVE-TAP blocked |
| phases/09-* other PLANs/SUMMARYs, PATTERNS, VALIDATION, DISCUSSION-LOG | METADATA_ONLY | |
| phases/10-*/10-CONTEXT.md, 10-REVIEW-DISPOSITION.md | DEEP_READ | |
| phases/10-*/10-REVIEW.md, 10-REVIEW-FIX.md | NORMAL_READ | CR/WR list, skipped WR-01/06/10/12/13 |
| phases/10-*/10-06-PLAN.md, 10-06-SUMMARY.md | NORMAL_READ (grep) | lag calibration |
| phases/10-* other PLANs/SUMMARYs, RESEARCH, UI-SPEC, PATTERNS, VALIDATION, DISCUSSION-LOG | METADATA_ONLY | |
| phases/11-* … 17-* | METADATA_ONLY | directories exist; goals read from ROADMAP |
| docs/DECISIONS.md (D030 row) | NORMAL_READ | |
| src/execution/manager.py L150–265, L500–560 | NORMAL_READ | effect of D-04 / D-02 decisions |
| src/execution/enablement.py L140–215 | NORMAL_READ | enable() kill-gate contract |
| src/execution/placement.py L125–145 | NORMAL_READ | zone-mid limit |
| src/backtest/simulator.py L445–515 | NORMAL_READ | zone-touch fill, partial_fill_fraction use |
| src/approval/binding.py L1–10, L149–195 | NORMAL_READ | expiry boundary, no min remaining validity |
| src/analytics/gates.py L1–80 | NORMAL_READ | TBD thresholds |
| src/paper/attribution.py L15–55 | NORMAL_READ | APPROVAL_DELAY_LAG_SECONDS = 30 |
| src/ops/health.py, src/adapters/binance_usdm.py, src/adapters/paper_ws.py | METADATA_ONLY (grep) | no listenKey/user-data stream; WS connect path |
| params/*/baseline-*.toml | METADATA_ONLY (grep) | partial_fill_fraction, signal_expiry_hours |

## Verified Safe Areas

- **Phase 7 D-01/D-02 (closed-candle double gate, identical engine calls, flag-never-fabricate gaps, fail-closed feed).** Consistent with Rule 35 (INV-003..006) and the identical-logic constraint. 07-RESEARCH Pitfall 1 requires `x is True AND close_time <= now`, which matches the A2 "kline closed only when k.x == true" fact. SOUND.
- **Phase 7 D-04 (pinned registry epoch + diff monitor, per-epoch evidence).** This is the right mechanism against tuning on the forward stream (Rule 31 spirit). SOUND. The acceptance artifact problem (07-REVIEW CR-06) was fixed.
- **Phase 7 Pitfall 5 / Phase 8 D-01 "notification failure never auto-approves".** Matches the approval-safety constraint. SOUND.
- **Phase 8 D-01 (full identity binding, token hash only, replay resolves to the existing Approval).** The binding itself is sound, and 08-REVIEW CR-01/WR-10 (button ignored, no compare-and-set) were fixed. The gaps are downstream: execution consumption (F-951) and minimum remaining validity (F-955).
- **Phase 8 D-02 (PTB polling, authorized-chat gate first, 64-byte short id).** Matches the Telegram fact that `callback_data` is 1–64 bytes. SOUND.
- **Phase 8 D-05 (all 8 drills with injected faults, journaled).** Rehearsal never creates real exposure. SOUND as far as it goes; see F-952 for what the drills cannot remediate.
- **Phase 9 D-01 (LIMIT entry on /fapi/v1/order, protectives on POST /fapi/v1/algoOrder algoType=CONDITIONAL, no blind retry, query by client id first).** Matches A2 endpoints: -4120 for conditional types on the order endpoint, and 503 "Unknown error" means execution status UNKNOWN. The manager's `_place_entry_no_blind_retry` (src/execution/manager.py:160-204) fails closed to SAFE_MODE on an indeterminate probe. SOUND.
- **Phase 9 pre-placed close-all SL at entry time.** The SL is placed as a `closePosition=true` STOP_MARKET immediately after the entry acknowledgment (manager.py:538-555), before any fill. This mitigates F-008 (a fill while the process is down stays protected), which is better than the doc. Direction SOUND. It creates the WR-07 orphan issue (F-952).
- **Phase 9 D-04 (no-withdrawal key, IP allowlist, secrets off-source, LIVE_ORDERS_DISABLED default).** Matches Rule 29 and INV-078. SOUND.
- **Phase 9 D-03 placement-time exchangeInfo revalidation with TTL, fail closed.** SOUND, except that the "200 per symbol" wording is wrong (KNOWN F-051, not re-reported).
- **Phase 10 D-01/D-02/D-05 (pure read-only analytics, METRICS-verbatim, INCOMPLETE bucket, unpooled evidence, uncertainty-first).** SOUND. WR-06 (pooled BACKTEST headline) violates D-05 and was skipped (see F-960).
- **Phase 10 D-03 / DECISIONS D030 kill-gate firing rule.** "≥3 independent families tested AND ≥6 months AND none passing", with the clock starting at the protocol freeze (2026-09-19). This matches Rule 34 and resolves F-025 correctly. The firing rule is SOUND; the definition of "pass" is not (F-960).
- **Phase 10 D-04 (offline static report, no web UI, no exchange access).** SOUND.
- **Phase 07.1 D-01..D-04 (binding enforced in assemble(), fail-closed dedicated exception, six-field identity untouched).** SOUND. The W2 bypass via direct `simulator.run` is KNOWN (milestone audit).
- **Phase 10-06 honest labelling.** Paper approval delay is labelled "SYNTHETIC LAG" and live buckets are measured only. This is honest, but see F-961.

## Findings

### F-951 — Phase 8 D-04 assumes the exchange dedups deterministic client IDs; Binance enforces uniqueness only among OPEN orders, and local "already-sent" state was explicitly rejected

- **Severity:** HIGH · **Confidence:** HIGH (decision premise CONFIRMED against official docs; code effect PROBABLE because there is no runtime composer yet, M2)
- **Classification:** DEFECT · **Category:** execution-idempotency
- **Component:** Phase 8 D-04 / 08-RESEARCH Pattern 4 + Don't-Hand-Roll; inherited by Phase 9 D-05
- **File / Lines:** `.planning/phases/08-approval-reconciliation-hardening/08-CONTEXT.md` D-04; `08-RESEARCH.md:268`, `08-RESEARCH.md:305`; effect `src/execution/manager.py:241-243`
- **Invariant:** INV-087, INV-047; Rule 28 · **Phase/commit:** 08 / 63ca176
- **Known-prior:** INVARIANTS domain-soundness note on INV-087 says "re-verify". A1 Rule 28 says "A2 to verify". A2 did not verify the scope. Not in ROADMAP 11–17.
- **Evidence:**
  - 08-CONTEXT D-04: "retries, restarts, and replayed events reuse the same identifier and the exchange dedups them — duplicate entry orders are structurally impossible, not just unlikely."
  - 08-RESEARCH:305 (Don't Hand-Roll): "Exchange ID dedup bookkeeping | Local "already-sent" boolean flags | Deterministic client/algo IDs (exchange is the dedup authority) | Flags die on restart; the exchange remembers".
  - Binance New Order doc (read 2026-09-29): `newClientOrderId` — "A unique id among open orders."
  - manager.py:241-243 docstring: "NOTE: consuming the approval (so an at-least-once Telegram replay re-plays the persisted outcome instead of re-running the pipeline) needs persisted execution state and is NOT handled here."
- **Expected:** A durable local record keyed on approval token/plan hash + role blocks re-submission once an entry was ever sent. This is Rule 28.
- **Actual:** The only dedup is the deterministic ID. After the first entry FILLS or is CANCELED/EXPIRED, it is no longer open, so the same `newClientOrderId` is accepted again. A replayed APPROVE callback (Telegram delivery is at least once), a restart that re-runs `execute_approved_plan`, or an operator re-tap reaches the placement pipeline again. The approval row still reads APPROVED, and the manager does not consume it.
- **Reproduction:** Planning-level: read 08-RESEARCH:305 against the Binance doc. Code-level (Stage C to confirm): call `execute_approved_plan` twice with the same approved inputs, the first time with a fake adapter whose order ends FILLED. The second call reaches `place_entry` with the same client id.
- **Impact:** A duplicate live entry doubles the position and the risk (for example 2 × 0.5% of equity) on one approval. The "structurally impossible" claim also stopped anyone from planning a durable guard.
- **Why tests miss it:** The 08-03 retry/restart/replay tests use fakes whose dedup model is "same ID ⇒ same order", which bakes in the wrong premise.
- **Remediation:** Add a new phase or extend Phase 15: a persisted execution-intent row (unique on approval_id/plan_hash + role), written before `place_entry`, that makes `execute_approved_plan` idempotent across replays and restarts. Correct 08-CONTEXT D-04 and EXECUTION_SPEC §7 wording.

### F-952 — Planning chose a cancel-only reconciler that never re-places a stop, and skipped 09 WR-07 (emergency close cancels the SL before the position is flat; the expired entry leaves a close-all SL). No later phase picks either up.

- **Severity:** HIGH · **Confidence:** HIGH · **Classification:** GAP · **Category:** protection / SAFE_MODE
- **Component:** Phase 8 D-03, Phase 9 D-02, 09-REVIEW WR-07 disposition
- **File / Lines:** `08-CONTEXT.md` D-03 ("the reconciler never places orders"); `09-CONTEXT.md` D-02 ("Entry-without-protective is a divergence that forces SAFE_MODE via the Phase-8 reconciler (sweeper never places rescue protection)"); `09-REVIEW-DISPOSITION.md` WR-07 `skipped`; `09-REVIEW-FIX.md:268-283`
- **Invariant:** INV-074, INV-084, INV-085, AMB-024; Rules 14 and 24 · **Phase/commit:** 08/09 / 63ca176
- **Known-prior:** Root cause KNOWN as A1 F-009 (doc) and F-007/F-008. The planning-level choice and the skipped WR-07 are new. Not in ROADMAP 11–17.
- **Evidence:**
  - 09-REVIEW WR-07: "`emergency_manual_close` cancels the SL/TP legs before the operator has closed the position … which leaves a live position with no stop for an unbounded time", and "`expire_pending_entry` cancels only the entry, so the close-all SL … will later close whatever position exists on that symbol".
  - 09-REVIEW-FIX skip reason: "a new order type and adapter method outside the V1 approval model".
- **Expected:** Per Rule 24, reduce-only/closePosition protectives are always allowed. A missing stop is re-placed automatically at the plan SL (never wider), or the position is closed reduce-only at market when price is beyond the SL. Per Rule 14, an SL rejected after a fill (for example -2021) triggers a reduce-only MARKET close and SAFE_MODE. The emergency path keeps the SL until the position is confirmed flat.
- **Actual:** The only automatic response to an unprotected position is SAFE_MODE plus an alert. SAFE_MODE blocks new entries but does nothing for existing exposure. The emergency-close path creates the unprotected window itself. Phases 11–17 contain nothing on this.
- **Reproduction:** Planning review. Code check for Stage C: `src/execution/manager.py` emergency_manual_close order of operations (lines cited in 09-REVIEW WR-07: 627-688, 761-832).
- **Impact:** A leveraged futures position can sit without a stop until a part-time operator (office hours, sleep) reacts to Telegram. The loss is unbounded by the plan SL. This is the failure mode the whole approval/protection design exists to prevent.
- **Why tests miss it:** The drills assert that SAFE_MODE is entered and the journal written. No test asserts "position protected or flat within N seconds".
- **Remediation:** Add a phase (before any live enable): protective re-placement and reduce-only close path exempt from SAFE_MODE (Rule 24); post-fill SL-reject fallback (Rule 14); WR-07 fix (cancel the plan's protectives only after flat confirmation; cancel the close-all SL when an entry expires with zero fills). Verify first how Binance treats a `closePosition=true` STOP_MARKET with no position (09-REVIEW-FIX item 6).

### F-953 — The live enablement gate is negative-only: enable() accepts WITHIN_BUDGET, requires no paper exit gate and no recorded passing family, and the paper soak never started

- **Severity:** HIGH · **Confidence:** HIGH · **Classification:** GAP · **Category:** research-governance / live gating
- **Component:** Phase 7 D-05, Phase 9 D-04, Phase 10 D-03
- **File / Lines:** `src/execution/enablement.py:147-208`; `10-CONTEXT.md` D-03 ("PASSING_CANDIDATE … does NOT authorize live … a separate decision record is required"); `07-CONTEXT.md` D-05 ("the evidence gate thresholds are set by the researcher"); `07-RESEARCH.md` Assumptions A5; `07-04-SUMMARY.md:64-65,221`
- **Invariant:** INV-120, INV-098; Rules 31, 32 · **Phase/commit:** 07/09/10 / 63ca176
- **Known-prior:** Partially KNOWN: milestone audit M1 (kill-gate state never fed to enable), 10-REVIEW WR-10 (enable trusts the caller, skipped). A1 F-023 (paper exit gate undefined) is the doc root. The new element: even when correctly wired, the gate only refuses INSUFFICIENT_EDGE.
- **Evidence:**
  - enablement.py docstring: "`PASSING_CANDIDATE` only records that evidence exists and NEVER authorizes live trading by itself: a separate human decision record is a process requirement". The code only raises on `INSUFFICIENT_EDGE` or a non-`KillGateState` value, so `WITHIN_BUDGET` (no family has passed; the default state until 2027-03-19 at the earliest) enables live.
  - 07-04-SUMMARY: "ws_subscribe=BLOCKED … soak must NOT start until live WS smoke passes." The milestone audit (M3) confirms that no paper journal is written.
  - ROADMAP Phase 8: "enablement gates on paper evidence". Nothing in enable() or the plans implements that.
- **Expected:** Rule 32: live enable requires a positive gate. That means a recorded PASSING_CANDIDATE (Rule 31 thresholds frozen beforehand) AND a paper exit gate (replay parity, fill/slippage within model, expectancy ≥ backtest bootstrap lower bound, ≥30 closed trades, ≥3 months), checked by code.
- **Actual:** The only barriers are health = green, an operator id, and not-INSUFFICIENT_EDGE. Phases 8–10 were planned and executed in 3 days (2026-09-27..29) while the 3–6-month "long pole" soak had not started. The paper minimum-evidence thresholds were never defined (assumed "research input").
- **Reproduction:** `LiveEnablementController(...).enable(operator_id="op", now_utc=..., health_verdict=<passing>, kill_gate_state=KillGateState.WITHIN_BUDGET)` succeeds by the code path read above.
- **Impact:** A user without trading expertise can enable live orders on a strategy with no validated edge and no forward evidence. The safety net against the most likely project outcome (no edge, NO_TRADE) becomes a manual discipline.
- **Why tests miss it:** Tests pin "INSUFFICIENT_EDGE refuses" and "PASSING_CANDIDATE does not authorize", but never "WITHIN_BUDGET must refuse".
- **Remediation:** Add a phase: enable() takes the latest recorded KILL_GATE_EVALUATION event id (WR-10), requires PASSING_CANDIDATE plus a recorded paper-exit-gate verdict with frozen numeric thresholds (Rule 32), and journals both. Define the paper exit thresholds now, before the soak starts.

### F-954 — ROADMAP puts the money-safety fixes (P11–P15) after the live-rollout phase and never ties live enablement to them; P11 is not ordered before the paper soak

- **Severity:** HIGH · **Confidence:** HIGH · **Classification:** GAP · **Category:** roadmap dependency order
- **Component:** ROADMAP Progress / Phases 9, 11–15
- **File / Lines:** `.planning/ROADMAP.md:22-30` (phase list), `:286-312` (Phase 9 "First cautious live orders"), `:355-408` (P11–P15 "Depends on: Phase 10/12…"), `:435` "Phases execute in numeric order"
- **Invariant:** INV-053/054 (P11), INV-067 (P12), INV-068..070 (P13/14), INV-071 (P15), INV-120 · **Phase/commit:** ROADMAP / 63ca176
- **Known-prior:** The contents of P11–P17 are KNOWN (backlog 999.x). The ordering/gating defect is new.
- **Evidence:**
  - Phase 9 is "In Progress" with only 09-04 task 3 left (testnet + credential + LIVE-TAP human checkpoint, `09-04-SUMMARY.md:122`). Once the operator clears it, nothing in ROADMAP or code prevents enabling live before P11 (sizing loses 16–40% more than budget on tight stops, A1 F-001), P13 (liquidation can precede the SL), or P15 (instant fill + immediately-triggered SL).
  - P11 says "golden fixtures and experiment hashes will change and must be regenerated deliberately". A paper soak pinned to baseline-v3 before P11 would have to restart its epoch (Phase 7 D-04) or would accumulate evidence under wrong sizing.
- **Expected:** An explicit rule "LIVE enable is blocked until P11–P15 are verified", enforced by a check in enable() or a milestone gate. P11 (and any other sizing/cost change) is sequenced before the paper soak epoch starts.
- **Actual:** Numeric order 9 → 10 → 11…17. Phase 9's success criteria claim first live orders. P11 depends on Phase 10 (analytics), which has no technical dependency on it.
- **Reproduction:** Read ROADMAP phases 9 and 11–15 and the Progress note.
- **Impact:** First live orders could run with known money bugs. Forward evidence could be invalidated after months of soak.
- **Why tests miss it:** Ordering is not testable. No enable-time prerequisite check exists.
- **Remediation:** Re-sequence: P11 (and F-957's partial-fill fix) → start soak; P12–P15 plus F-951/F-952/F-953 fixes → live enable. Make "Phase 9 live readiness" depend on them explicitly, and record this in ROADMAP and STATE.

### F-955 — Phases 11–17 omit several corrected-rule safety items that no phase or plan covers

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** roadmap completeness
- **Component:** ROADMAP 11–17
- **File / Lines:** `.planning/ROADMAP.md:355-430`; evidence of absence: `src/approval/binding.py:8-9,189-190`; `09-*/COVERAGE.md:27`; grep of `src/` for listenKey/user-data (no hits except the health-probe name `src/ops/health.py:51`)
- **Invariant:** INV-047, INV-063..065, INV-076, INV-081, INV-093; Rules 3, 9, 12, 14, 21, 26 · **Phase/commit:** ROADMAP / 63ca176
- **Known-prior:** Doc roots KNOWN (A1 F-002, F-014, F-016; A2 F-051, OQ3). Here the planning consequence is reported: no phase owns them. F-951/F-952/F-953 are reported separately and are not repeated.
- **Evidence (items with no owning phase):**
  1. **Minimum remaining validity at approval.** Binding: "One second before expiry is still approvable" (binding.py:9). Rule 21 requires ≥ max(600 s, param).
  2. **GTD exchange-side expiry.** COVERAGE row 16 marks it "OPT-OUT … not wired in V1" (Rule 12). See F-959.
  3. **Portfolio caps counting working entries + APPROVED-unplaced plans under one lock.** Phase 9 D-03 says "evaluated against the live/reconciled position set" (Rule 9).
  4. **Cost-to-risk ceiling** (Rule 3).
  5. **Account-wide 200 algo cap** (KNOWN F-051). Phase 9 D-03 wording "per-symbol" was carried into gates.
  6. **User-data stream.** Phase 8 D-03 and Phase 9 D-01 declare "user-data WS preferred realtime", and P12 builds on it ("account endpoint + user-data stream"). No listenKey / ORDER_TRADE_UPDATE / ALGO_UPDATE consumer exists in `src/`, and no plan in 08/09 created one. It is an orphaned decision.
  7. **Reconciliation cadence values** (Rule 26). Phase 8 D-03 leaves "check cadence at the planner's discretion", and no value is fixed or scheduled (milestone audit: "reconciler not scheduled").
- **Expected:** Each Rule-level minimum safe rule has an owning phase before live enable.
- **Actual:** None of these items appear in P11–P17 goals.
- **Reproduction:** Read the P11–P17 goals against Rules 3/9/12/14/21/26.
- **Impact:** Live trading can proceed with approvals seconds before expiry, racing caps, entries resting after the process dies, and fills detected only by an unscheduled REST path.
- **Why tests miss it:** These are absent features.
- **Remediation:** Add phases (or extend P14/P15) for items 1–7, placed before live enable.

### F-956 — No phase exists for runtime composition (M1–M4) or for verifying phases 06–10, although the milestone audit asks for that decision to be recorded

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** roadmap completeness
- **Component:** ROADMAP vs v0.3-MILESTONE-AUDIT
- **File / Lines:** `.planning/v0.3-MILESTONE-AUDIT.md` "Recommended closure order" 1–3, integration M1–M4; `.planning/ROADMAP.md:22-30, 437-455`
- **Invariant:** INV-120 · **Phase/commit:** ROADMAP / 63ca176
- **Known-prior:** KNOWN (the milestone audit lists M1–M4 and the missing VERIFICATION files). New: the audit's step 2 ("insert a closure phase, or record it in ROADMAP as explicit deferred debt") was not done, and backlog promotion (commit 63ca176) added 11–17 without it.
- **Evidence:**
  - Audit: "ROADMAP does not state that this layer is deferred."
  - ROADMAP marks Phase 8 "Complete 2026-09-27" while APRV-01/02, EXEC-02/03 and OPS-01 are "orphaned" (no 08-VERIFICATION.md), and plan 08-05 is still unchecked at ROADMAP:273.
  - Every P11–P17 goal fixes a library function (`size_position`, `format_approve`, `execute_approved_plan`) that has zero production callers.
- **Expected:** A runtime-composition phase (paper process: supervisor → tick → journal; live process: PTB callback → execute_approved_plan → attach/reconcile scheduler; kill-gate → enable; Parquet → case_input), plus verification of 06–10, ordered before or with P11–P15.
- **Actual:** Neither exists. The paper soak (the schedule long pole) cannot start without M3.
- **Reproduction:** Compare the ROADMAP phase list with the milestone audit's gaps block.
- **Impact:** The schedule: the long pole does not start. Safety: the fixes in F-951/F-952 must be designed into the composer, and without a phase they will be improvised.
- **Why tests miss it:** Library tests pass in isolation (the audit confirms by grep that there are no callers).
- **Remediation:** Insert a phase such as "10.1 runtime composition + verification", which the P11–P17 goals then target.

### F-957 — Phase 07.1 fixed `partial_fill_fraction = 0.5` in the candidate registry sets for hash-spelling convenience; candidate and paper runs model half-filled trades while the baselines use 1.0

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** DEFECT · **Category:** backtest methodology
- **Component:** Phase 07.1 plan 01
- **File / Lines:** `.planning/phases/07.1-*/07.1-01-PLAN.md:93`; `07.1-01-SUMMARY.md:68`; `07.1-PATTERNS.md:341,371`; `params/trend-pullback/baseline-v3.toml:57`; `params/breakout-retest/baseline-v3.toml:61`; `params/trend-pullback/baseline-simple-trend-v1.toml:56` (1.0); effect `src/backtest/simulator.py:483-484,512`
- **Invariant:** INV-104, AMB-036; Rule 18 · **Phase/commit:** 07.1 / 63ca176
- **Known-prior:** Doc-level KNOWN as A1 F-006. This answers A1's open question "Who chose partial_fill_fraction = 0.5": the 07.1-01 planner, independently, for a hash-spelling reason.
- **Evidence:**
  - 07.1-01-PLAN:93: "partial_fill_fraction 0.5 fractional (never 1.0, which normalizes to int per Pitfall 1)".
  - The same phase's PATTERNS doc shows that JSON int `1` binds correctly: "partial_fill_fraction MUST be JSON int 1, NOT string "1.0"".
  - simulator.py:484 `filled_quantity = _mul(quantity, cost_model.partial_fill_fraction)`; :512 labels every candidate fill `PARTIAL_FILL`.
  - Baseline sets keep `1.0`. Paper pins baseline-v3, so paper inherits 0.5.
- **Expected:** Rule 18: `partial_fill_fraction = 1.0` at V1 sizes, identical across the candidate and its baselines. Parameter values are never chosen for hash convenience.
- **Actual:** Every candidate trade in backtest and paper realizes half the sized quantity. The baselines realize the full quantity.
- **Reproduction:** Assemble any trend-pullback baseline-v3 case; the trade record shows `PARTIAL_FILL` with qty × 0.5.
- **Impact:** Candidate-vs-baseline comparison (acceptance gate G10), realized-R distributions, $ outcomes and the paper-vs-live execution-quality comparison are all distorted. Live fills are full fills at these sizes.
- **Why tests miss it:** The 07.1 match fixture was written with 0.5 on both sides, so the binding "passes".
- **Remediation:** Include in P11 (which regenerates hashes anyway): new set version with `partial_fill_fraction = 1` (int spelling), and baselines on the same value.

### F-958 — Phase 9 chose `workingType = MARK_PRICE` for live SL/TP with no matching backtest/paper trigger series

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** DRIFT · **Category:** backtest/live parity
- **Component:** Phase 9 research/plan 09-01 (discretion item)
- **File / Lines:** `09-RESEARCH.md:253`; `09-01-PLAN.md:107`; `09-01-SUMMARY.md:100`; effect `src/execution/manager.py:554` (`"working_type": "MARK_PRICE"`)
- **Invariant:** INV-058, INV-103; Rule 15 · **Phase/commit:** 09 / 63ca176
- **Known-prior:** A2 Open Question 4 raised the code fact. A1 F-010 covers the doc silence. The planning choice is not recorded as a decision anywhere (no D-xx, no DECISIONS entry).
- **Evidence:** The 09-01 action text hard-codes `working_type MARK_PRICE`. The backtest resolves SL/TP on 1m contract/last-price candles (BACKTEST_SPEC intrabar), and paper reuses that. Binance's default is CONTRACT_PRICE (A2).
- **Expected:** Rule 15: CONTRACT_PRICE with priceProtect=false, recorded on the plan. MARK_PRICE only together with a mark-price-kline backtest.
- **Actual:** Live stops trigger on a different price series than the one the evidence was produced on, and the choice is undocumented.
- **Reproduction:** Planning review. Stage C to verify the TP legs (A2 cites placement.py L325/L437/L450).
- **Impact:** Stop-out rates, slippage and R in live systematically differ from backtest/paper. In fast moves, last price can blow through the SL level while the mark-price trigger lags, giving a larger loss than the risk budget. The paper-vs-live divergence gate becomes uninterpretable.
- **Why tests miss it:** Fakes do not simulate trigger series.
- **Remediation:** Record a decision. Either switch to CONTRACT_PRICE, or add mark-price klines to the data foundation and the simulator before live.

### F-959 — Phase 9 opted out of GTD; entry expiry relies only on a local cancel with no runtime caller

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** execution / expiry
- **Component:** Phase 9 research open question 2 / COVERAGE row 16
- **File / Lines:** `09-RESEARCH.md:87,285,295-298`; `.planning/phases/09-live-execution-rollout/COVERAGE.md:27`; effect `src/execution/manager.py` entry kwargs `"time_in_force": "GTC"` (≈L512)
- **Invariant:** INV-081, INV-089; Rules 12, 21 · **Phase/commit:** 09 / 63ca176
- **Known-prior:** A1 F-008/F-016 are the doc roots. Milestone audit M2 says the expiry paths have no production caller.
- **Evidence:** COVERAGE:27: "`goodTillDate` (GTD) entry expiry | OPT-OUT | Manual expiry-cancel is the EXECUTION_SPEC §4-explicit path … not wired in V1".
- **Expected:** An exchange backstop: GTD = plan expiry (Binance requires > now + 600 s), plus the local cancel. Refuse placement when less than 600 s of validity remains.
- **Actual:** GTC LIMIT at zone mid. If the process, host or scheduler is down at expiry, the entry rests indefinitely and can fill days later on a dead setup. The pre-placed close-all SL then protects a trade nobody approved at that time.
- **Reproduction:** Planning review.
- **Impact:** Unapproved-in-time exposure. It also combines with WR-07: an expired entry's close-all SL stays live (F-952).
- **Why tests miss it:** Tests inject `now_utc` and call `expire_pending_entry` directly.
- **Remediation:** Wire `goodTillDate` (second precision) with plan expiry, and add the ≥600 s rule to the approval/placement gates.

### F-960 — Kill-gate "pass" is a human-recorded decision with TBD thresholds, and the five review findings that can flip it were left for the non-expert user to decide

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** research governance
- **Component:** Phase 10 D-03 / DECISIONS D030 / 10-REVIEW dispositions
- **File / Lines:** `docs/DECISIONS.md` D030 row ("Acceptance thresholds remain TBD, so a family passing/failing status is a recorded human decision"); `src/analytics/gates.py:1-8`; `10-REVIEW.md` WR-01, WR-06, WR-12, WR-13; `10-REVIEW-FIX.md` skipped block; milestone audit tech_debt
- **Invariant:** INV-098, INV-100, INV-101; Rules 31, 34 · **Phase/commit:** 10 / 63ca176
- **Known-prior:** Root KNOWN as A1 F-022 (HIGH). Skipped WRs KNOWN (milestone audit). The planning consequence is new: Phase 10 formalised F-022 into the governance machinery instead of forcing a threshold freeze, and the open WRs make the recorded "pass" forgeable or accidental.
- **Evidence:**
  - WR-12: `--record` accepts an arbitrary decisions file (an extra TESTED_PASS or reset).
  - WR-13: gates G07/G08/G10 turn MET on self-reported booleans.
  - WR-01: independence is vacuous; adding a directory can stop the kill gate firing.
  - WR-06: the BACKTEST headline pools baselines with candidates.
- **Expected:** Rule 31: numeric gates and a trial-count penalty frozen before any Validation run. A human may veto a pass but never pass a failing candidate. Gate cells derive from artifacts, not flags.
- **Actual:** "Pass" = a human writes TESTED_PASS in a decisions file, and the evidence cells can be self-attested.
- **Reproduction:** See the 10-REVIEW WR-12/WR-13 reproductions.
- **Impact:** V1 family selection, and (once F-953 is fixed) live enablement, rests on a subjective decision by a user who told the audit they lack trading expertise. Research validity is compromised.
- **Why tests miss it:** The fixtures supply well-formed decision files.
- **Remediation:** Before any Validation run, add a protocol amendment (v1.1.0) freezing the numeric thresholds and multiple-testing adjustment. Fix WR-01/06/12/13 (artifact references, decisions_sha256, independence among TESTED families only).

### F-961 — Paper "user-executed" attribution uses a fixed 30 s approval lag, and paper SIMULATE buttons are inert, so the approval-delay effect is first measured with real money

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** research validity / attribution
- **Component:** Phase 7 D-03/D-05, 07-RESEARCH Open Question 3, Phase 10-06
- **File / Lines:** `src/paper/attribution.py:47-51` (`APPROVAL_DELAY_LAG_SECONDS: int = 30`); `07-RESEARCH.md` OQ3 ("calibrated against measured Telegram latency in Phase 10"); `10-06-PLAN.md:27` ("PAPER … never appears in buckets … the paper constant stays unchanged"); `07-RESEARCH.md` code example ("callbacks are inert labels")
- **Invariant:** PAPER-02; F-016 (A1) · **Phase/commit:** 07/10 / 63ca176
- **Known-prior:** A1 F-016 (office-hours/sleep bias undefined) is the root. The deferral "Phase 10 calibrates" was only half honoured: labelled, not calibrated.
- **Evidence:** See the files above. The planned calibration source is "Telegram latency", which is a transport delay, not the operator's response time.
- **Expected:** Paper forward observation captures real operator APPROVE/SKIP taps (as "would take" decisions) with timestamps, so the System/User/Opportunity split in METRICS §3 is measured before live.
- **Actual:** User-executed ≈ system with a 30 s lag. The availability bias of a full-time worker (signals at night or in meetings, 4 h validity) is unmeasured until LIVE rows exist.
- **Reproduction:** Planning review.
- **Impact:** Paper evidence overstates what this operator can actually capture. The paper exit gate (F-953) would judge the wrong population.
- **Why tests miss it:** The constant is the specified behaviour.
- **Remediation:** In the runtime-composition phase (F-956), route paper SIMULATE callbacks through the Phase 8 approval intake as non-order-authorizing "paper approvals", and replace the constant with the recorded taps.

### F-962 — P11 goal is incomplete against Rules 2, 3 and 8: exit slippage, adverse-edge distance, fee fallback direction and taker entries are missing

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** risk sizing (roadmap goal)
- **Component:** ROADMAP Phase 11
- **File / Lines:** `.planning/ROADMAP.md:355-364`
- **Invariant:** INV-053, INV-054, AMB-002, AMB-004, AMB-005; Rules 2, 3, 8 · **Phase/commit:** ROADMAP / 63ca176
- **Known-prior:** The bug itself is KNOWN (P11). The goal gaps are new.
- **Evidence:** The goal says "multiply by entry reference price (entry fee on entry, exit fee on SL price)" and "if unavailable, fall back to the versioned parameter-set fees … Keep backtest on versioned fees".
- **Expected:**
  - Rule 2: `|entry_worst − SL| + entry_ref×fee_entry + SL×(fee_exit + slip_exit)` (+ entry slippage if taker), with entry_worst = the adverse zone edge.
  - Rule 8: live uses max(parameter fee, account commissionRate) per side, recorded on the plan; loader rejects rates > 0.01; a marketable entry pays taker or is sent GTX.
  - Rule 3: cost-to-risk ceiling.
  - Acceptance test: simulated SL loss incl. costs ≤ allowed_risk.
- **Actual:** Slippage is not mentioned. The distance keeps the zone-mid reference (Phase 5 D-02, `placement.py:131-143`). If the account rate is available, it is used even when lower than the backtested fee, so live sizes larger than the evidence. Maker/taker selection for a GTC entry at zone mid (which is marketable when price is already inside the zone; A2 F-055) is not addressed.
- **Reproduction:** Read the goal against the rules.
- **Impact:** After P11, SL losses can still exceed the budget (slippage, taker entry, adverse edge), and live/backtest cost parity diverges.
- **Why tests miss it:** Not planned yet.
- **Remediation:** Amend the P11 goal with the Rule 2/3/8 formulas and the acceptance test.

### F-963 — P12 goal leaves the equity field, the daily-loss definition, and the data source (a user-data stream that does not exist) undefined

- **Severity:** MEDIUM · **Confidence:** HIGH · **Classification:** GAP · **Category:** risk inputs (roadmap goal)
- **Component:** ROADMAP Phase 12
- **File / Lines:** `.planning/ROADMAP.md:366-375`
- **Invariant:** INV-066, INV-067, AMB-003, AMB-012; Rules 7, 10 · **Phase/commit:** ROADMAP / 63ca176
- **Known-prior:** Topic KNOWN (P12). Gaps new.
- **Evidence:** The goal says "Read equity from the USD-M account endpoint + user-data stream … daily realized loss". It names no field and no day boundary.
- **Expected:**
  - Rule 7: equity = min(totalWalletBalance, totalMarginBalance), snapshotted at plan creation, re-checked at placement (≤ 1.05× rule, never upsize).
  - Rule 10: UTC day, loss = −(realized PnL + commission + funding) (FUNDING_FEE/COMMISSION/REALIZED_PNL income types, plus the new SPECIAL_FUNDING_FEE), base at 00:00 UTC, `≥`, persisted across restart.
- **Actual:** "Realized loss" alone ignores commission and funding. It also ignores unrealized loss on open positions, which is covered only if equity uses the margin balance. The user-data stream has no implementation (F-955 item 6).
- **Reproduction:** Read the goal against the rules.
- **Impact:** DAILY_STOP could trip late, and sizing could use an optimistic wallet balance while positions are under water.
- **Why tests miss it:** Not planned yet.
- **Remediation:** Amend the P12 goal. Make the user-data stream (or a REST polling cadence) an explicit deliverable.

### F-964 — P13 goal: "liquidation strictly beyond the SL" has no buffer, the margin type is left open, and there is no leverage cap

- **Severity:** MEDIUM · **Confidence:** MEDIUM · **Classification:** GAP · **Category:** margin/liquidation (roadmap goal)
- **Component:** ROADMAP Phase 13
- **File / Lines:** `.planning/ROADMAP.md:377-386`
- **Invariant:** INV-068, INV-069, INV-070, AMB-019; Rule 11 · **Phase/commit:** ROADMAP / 63ca176
- **Known-prior:** Topic KNOWN (P13). Gaps new.
- **Evidence:** The goal says "margin type (isolated/cross) are set explicitly per symbol from a versioned parameter … refused … unless the projected liquidation price lies strictly beyond the SL".
- **Expected:** Rule 11: isolated margin; smallest leverage fitting availableBalance with ≥20% headroom, capped at 5×; liquidation beyond the SL by ≥1× the SL distance using bracket MMR. Also detect Multi-Assets mode (Rule 17; the -4425 error is new as of 2026-09-28).
- **Actual:** One tick beyond the SL would pass. A STOP_MARKET fills with slippage, and the SL (mark price, F-958) and liquidation (mark price) can be close together in gaps. The choice of cross margin is left open; cross exposes the whole wallet.
- **Reproduction:** Read the goal against the rule.
- **Impact:** A liquidation fee plus a loss larger than planned in fast markets.
- **Why tests miss it:** Not planned yet.
- **Remediation:** Amend the P13 goal with the Rule 11 numbers. Decide isolated (record it in DECISIONS). Include change_margin_type preconditions (it cannot change with open orders or positions).

### F-965 — Phase 9 committed to supporting both position modes, where the corrected rule is one-way only

- **Severity:** LOW · **Confidence:** HIGH · **Classification:** IMPROVEMENT · **Category:** scope / execution surface
- **Component:** ROADMAP Phase 9 SC1, 09-CONTEXT D-02
- **File / Lines:** `.planning/ROADMAP.md:296` ("supports both position modes"); `09-CONTEXT.md` D-02
- **Invariant:** INV-083, AMB-030; Rule 17 · **Phase/commit:** 09 / 63ca176
- **Known-prior:** A1 F-020 (doc ambiguity).
- **Evidence:** D-02 builds a hedge branch with `positionSide` legs. 09-REVIEW WR-02 found the mode hard-coded, and it was fixed with detection plus both branches.
- **Expected:** Support One-way + Single-Asset only. Any other mode → no new entries.
- **Actual:** A second, never-exercised order-parameter branch (hedge closePosition/reduceOnly constraints differ; A2) on the live path.
- **Reproduction:** Planning review.
- **Impact:** More surface for a wrong protective on a mode the operator never uses. Low probability.
- **Why tests miss it:** The hedge branch is tested only against fakes and contract signatures.
- **Remediation:** Make hedge mode (and Multi-Assets) a fail-closed NO_TRADE and delete or park the branch.

### F-966 — P14 and P16 goal details fall short of Rules 11 and 23

- **Severity:** LOW · **Confidence:** HIGH · **Classification:** GAP · **Category:** roadmap goal detail
- **Component:** ROADMAP Phases 14, 16
- **File / Lines:** `.planning/ROADMAP.md:388-397, 410-419`
- **Invariant:** INV-050, INV-051, INV-069; Rules 11, 23 · **Phase/commit:** ROADMAP / 63ca176
- **Known-prior:** Topics KNOWN (P14, P16).
- **Evidence:**
  - P14 checks `availableBalance` against "the initial margin of the new order". It does not account for other resting entries or APPROVED-unplaced plans, which reserve margin at trigger/fill (A2: algo orders have no margin check before trigger).
  - P16's field list omits the liquidation price, current price and time left to expiry.
- **Expected:** Per Rule 11 / Rule 9, margin is checked against all pending exposure with ≥20% headroom. Per Rule 23, the message shows the liquidation price, current price and time left.
- **Actual:** As described above.
- **Reproduction:** Read the goals.
- **Impact:** A second fill or a TP/SL trigger can be rejected (-2019) at a bad moment. The operator approves without seeing liquidation distance or staleness.
- **Why tests miss it:** Not planned yet.
- **Remediation:** Amend both goals.

### F-967 — Planning bookkeeping drift: stale review disposition, Phase 8 marked Complete, TBD requirements, and user confirmations never collected

- **Severity:** LOW · **Confidence:** HIGH · **Classification:** DRIFT · **Category:** planning hygiene
- **Component:** .planning state files
- **File / Lines:**
  - `10-REVIEW-DISPOSITION.md` rows CR-01, WR-04, WR-05, WR-07, WR-08, WR-09, WR-11, WR-14, WR-15 = `open`, while `10-REVIEW-FIX.md:33-150` marks them fixed (seven with "requires human verification").
  - `.planning/ROADMAP.md:273` (08-05 unchecked) vs `:24` "[x] Phase 8 … completed".
  - ROADMAP P11–P17 "Requirements: TBD".
  - DECISIONS D030 "flagged for user confirmation"; 08/09/10-CONTEXT "ApprovalResult value set … user confirmation pending".
- **Invariant:** AMB-001 · **Phase/commit:** 08/10/ROADMAP / 63ca176
- **Known-prior:** Partly KNOWN (milestone audit tech_debt).
- **Evidence:** See above.
- **Expected:** The disposition mirrors the fix report. A phase is marked complete only after verification. Promoted phases map to requirement IDs. Pending user confirmations are tracked to closure.
- **Actual:** The state files disagree, and the "user confirmation" items have been carried for 4 phases while the user runs `--auto`.
- **Reproduction:** Compare the files cited.
- **Impact:** A future `--auto` run may treat open fixes as undone or done fixes as open. The requirement traceability for money fixes is lost.
- **Why tests miss it:** Not code.
- **Remediation:** Re-run the disposition gate. Un-mark Phase 8 until 08-VERIFICATION exists. Assign REQ IDs to P11–P17. Put the pending confirmations in front of the user in one list.

## Open Questions

- **For Stage C (L3/L5, execution):**
  - Confirm F-951 in code: does anything between the future composer and `place_entry` consult persisted state? Also, the manager maps a query probe that raises to UNKNOWN; is `-2013` mapped (09-REVIEW-FIX item 1)?
  - Confirm the order of operations in the emergency-close path (F-952).
  - Confirm which `working_type` the TP legs send (F-958).
- **For Stage C (backtest lane):** `src/backtest/simulator.py:448-481` fills at zone mid when the bar merely touches the zone (`bar.high >= entry_min and bar.low <= entry_max`). A bar that reaches only the far edge is filled at the mid price. That is a touch-as-fill and a better-than-reached price, against Rule 18. It is a Phase 6 decision (B1 scope), so it is not reported here.
- **For B1:** Phase 5 D-02 set `entry_ref` = zone mid for sizing, where Rule 2 requires the adverse edge. This feeds F-962.
- **For Stage C / A2:** No code in `src/` hard-codes a WS base URL. `PaperWsAdapter.connect` delegates to the SDK (`src/adapters/paper_ws.py:214-235`). Check that the SDK 17.4.0 default market-stream URL uses the post-2026-04-23 `/market` path (A2 F-053) before the soak starts. The 07-RESEARCH diagram cites the legacy `wss://fstream.binance.com`.
- **For the user (decisions that should not be auto-picked):** Isolated vs cross margin (F-964). MARK vs CONTRACT trigger (F-958). Numeric acceptance thresholds and the paper-exit thresholds (F-953/F-960). Whether hedge mode is supported at all (F-965).
- **Not inspected:** The VALIDATION.md files for 07/08/09 beyond metadata (the milestone audit already records Nyquist as partial); 10-UI-SPEC.md; 10-RESEARCH.md (81 KB) beyond the decisions carried into CONTEXT/D030.

## Appendix: Decision Register (phases 07–17)

Verdicts: SOUND / QUESTIONABLE / WRONG / RISKY-DEFERRAL. The "auto" column: every D-xx below was auto-selected as "(recommended default)" under `--auto --chain`.

| Phase | Decision | What was chosen | Alternatives | Verdict | Reasoning (trading reality / corrected rules) |
|---|---|---|---|---|---|
| 07 | D-01 ingestion | SDK WS behind adapters, REST resync, journaled gaps, fail-closed | direct WS with synthesized candles | SOUND | Flag-never-fabricate plus closed-candle gate matches Rules 26/35. WS connect path was not wired at phase end (07-04 smoke BLOCKED); see F-956. |
| 07 | D-02 engine reuse | identical core/risk/backtest calls + divergence gate | paper-local engine | SOUND | Parity is the right acceptance. It also propagates backtest defects into paper (F-957, zone-touch fill). |
| 07 | D-03 attribution/storage | three-way attribution, PG rows + Parquet mirror | log-only | SOUND (design) / QUESTIONABLE (user leg) | Attribution design is fine. The user-executed leg is synthetic (F-961). |
| 07 | D-04 freeze proof | pinned registry epoch + diff monitor | convention | SOUND | Correct anti-tuning control. P11 will force a new epoch (F-954). |
| 07 | D-05 scope | live-5, 4H/1H, SIMULATE-only, 3–6 mo, "evidence thresholds set by the researcher" | full approval loop in Phase 7 | QUESTIONABLE | Paper exit thresholds left undefined (Rule 32 / F-023). Inert buttons prevent measuring operator behaviour (F-961). |
| 07 | RESEARCH OQ1 | hourly CI cron freeze check | soak-host process | SOUND | Either works. CR-06 fixed the artifact loss. |
| 07 | RESEARCH OQ2 | Parquet extracts deferred to Phase 10 | build now | SOUND | Lossless (epoch_id carried). |
| 07 | RESEARCH OQ3 | APPROVAL_DELAY_LAG_SECONDS = 30 constant, "calibrate in Phase 10" | record real taps | RISKY-DEFERRAL | Calibration never done. The concept (Telegram latency) is wrong for human delay. F-961. |
| 07 | 07-04 soak checkpoint | soak must not start until WS smoke passes | — | SOUND (gate) / orphaned | Correct stop. No phase owns the fix + soak start (F-956). |
| 07 | Discretion: TP/SIM button labels, module layout | planner | — | SOUND | Hygiene. |
| 07.1 | D-01 | enforce binding in assemble() | verifier module / simulator derives | SOUND | Single choke point. The direct simulator.run bypass is KNOWN W2. |
| 07.1 | D-02 | keep cost dict + binding check | derive from registry everywhere | SOUND | Keeps fixtures self-contained. |
| 07.1 | D-03 | dedicated exception, fail closed | warning / reason code | SOUND | Programming error, not a market outcome. |
| 07.1 | D-04 | six-field identity untouched | re-derive hashes | SOUND | Protects published IDs. |
| 07.1 | D-05 | new fixture dir + audit phase6 (grandfather 10 fixtures) | regenerate all | SOUND | Honest logging. |
| 07.1 | Plan choice | partial_fill_fraction = 0.5 in baseline-v3 | int 1 (shown to work in PATTERNS) | WRONG | Chosen for hash convenience. Candidate ≠ baseline fill model (F-957, Rule 18). |
| 08 | D-01 approval binding | full identity + token hash + replay-to-existing + no auto-approve | chat-only | SOUND (binding) / QUESTIONABLE (expiry) | Binding is right. No minimum remaining validity ("one second before expiry is still approvable"), Rule 21 (F-955). |
| 08 | D-02 intake | PTB polling behind adapters, chat gate first, short-id map | FastAPI webhook | SOUND | No inbound surface. Respects the 64-byte limit. |
| 08 | D-03 reconciler | three-source compare, cancel-only sweep, SAFE_MODE on divergence, cadence at discretion | local-only check | QUESTIONABLE | Three-source compare is right. "Never places orders" conflicts with Rule 24 (F-952). Cadence never fixed (Rule 26, F-955). "User-data WS preferred" never built (F-955). |
| 08 | D-04 order IDs | deterministic plan-hash+role IDs, "exchange dedups" | random UUID per attempt | WRONG (premise) | Deterministic IDs are good. The claim that the exchange dedups is false (unique only among open orders), and local sent-state was rejected (F-951). |
| 08 | D-05 drills | all 8 drills, injected faults, journaled; SAFE_MODE exit only via restore | walkthrough | SOUND | Matches Rule 25 (manual exit). Drills cannot fix what the design lacks (F-952). |
| 08 | Discretion: cadence, mapping storage | planner | — | RISKY-DEFERRAL | The reconciler cadence was never set or scheduled (milestone audit). |
| 08 | Carried: ApprovalResult set PENDING/APPROVED/SKIPPED/EXPIRED "user confirmation pending" | locked without confirmation | — | QUESTIONABLE | Low impact. It has been pending for 4 phases (F-967). |
| 09 | D-01 entry/protective wiring | LIMIT entry + CONDITIONAL algo exits, SDK re-verified, no blind retry | MARKET entry / legacy conditional | SOUND | Matches A2 endpoints and 503 semantics. |
| 09 | D-02 modes + partial fills | dynamic mode detection, both modes, protectives sized to filled qty, "sweeper never places rescue protection" | one-way template, planned qty | QUESTIONABLE | Filled-qty sizing is right (INV-084). Supporting hedge contradicts Rule 17 (F-965). No rescue protection contradicts Rule 24 (F-952). |
| 09 | D-03 placement gates | exchangeInfo revalidation, TTL, "200-per-symbol" headroom, caps on reconciled positions | plan-time snapshot | QUESTIONABLE | Revalidation is right. Per-symbol is wrong (KNOWN F-051). Caps ignore working and approved-unplaced plans (Rule 9, F-955). |
| 09 | D-04 security + rollout | no-withdrawal key, IP allowlist, off-source secrets, LIVE_ORDERS_DISABLED, smallest capital live-5 | permissive keys | SOUND | Matches Rule 29 / INV-078. The enable gate is too weak (F-953). |
| 09 | D-05 manager shape | pure manager reusing canonical contracts, journaled | local sizing | SOUND | Identical-logic constraint. |
| 09 | Discretion: limit price | GTC at zone mid | zone edge, GTD | QUESTIONABLE | Mid matches the backtest. GTC without a GTD backstop (F-959). A marketable-at-placement entry pays taker (F-962 / A2 F-055). |
| 09 | Discretion: trigger series | working_type MARK_PRICE | CONTRACT_PRICE (default) | QUESTIONABLE | No backtest parity, undocumented (F-958). |
| 09 | Discretion: expiry | manual cancel, GTD OPT-OUT | GTD | RISKY-DEFERRAL | F-959. |
| 09 | 09-REVIEW WR-07 | skipped (design decision needed) | fix | RISKY-DEFERRAL (orphaned) | Unprotected window in emergency close; close-all SL orphan on expiry. No later phase (F-952). |
| 09 | 09-REVIEW IN-02 | open | fix | QUESTIONABLE | `str(Decimal)` exponent → -1100. Overlaps KNOWN A2 F-058. Code lane. |
| 09 | 09-REVIEW-FIX exchange facts 1–6 | "fails closed" pending doc check | verify now | RISKY-DEFERRAL | Item 5 (MAX_NUM_ALGO_ORDERS per symbol) is based on a removed filter (A2: removed 2025-12-29; cap is account-wide). Item 6 feeds F-952. |
| 09 | 09-04 task 3 | testnet/credential/LIVE-TAP blocked on human | — | SOUND (gate) | Correct to block. The only barrier before live is this human step (F-954). |
| 09 | deferred-items (ruff F401 in drills.py) | deferred | fix | SOUND | Hygiene. |
| 10 | D-01 analytics shape | pure deterministic read-only package, digest | ad hoc notebooks | SOUND | |
| 10 | D-02 metrics | METRICS verbatim, full report visible, INCOMPLETE bucket | favourable slices | SOUND | WR-08 fix kept LIVE delay buckets approvals-only. That hides OPPORTUNITY selection bias in the delay view (minor). |
| 10 | D-03 kill gate | D013/D030 evaluator, journaled terminal, fail-closed; PASS = human decision (thresholds TBD) | advisory dashboard | SOUND (firing rule) / WRONG (pass definition) | Firing rule matches Rule 34. A human-decided pass with TBD thresholds contradicts Rule 31 (F-960). enable() is not positively gated (F-953). |
| 10 | D-04 dashboard | offline static report + JSON sidecar, dual universe | FastAPI UI | SOUND | Research-universe hash check was unwired (WR-07, fixed with human verification pending). |
| 10 | D-05 persistence | derived views, append-only KILL_GATE_EVALUATION, unpooled | metrics tables | SOUND | WR-06 pooled headline skipped (F-960). |
| 10 | D030 clock start | protocol "Frozen on" 2026-09-19 | first Validation run | SOUND | Deterministic, documented. |
| 10 | Skipped WR-01/06/10/12/13 | awaiting human decision | fix | RISKY-DEFERRAL | They can flip or forge the kill gate. The user lacks the expertise to decide (F-960, F-953). |
| 10 | 7 fixes "requires human verification" | fixed, pending review | — | QUESTIONABLE | Disposition file still shows them open (F-967). |
| 11 | Goal | fix fee units ×price; read commissionRate; fall back to param fees; backtest keeps versioned fees | Rule 2/8 formula | QUESTIONABLE | Missing slippage, adverse edge, max(param, account), taker/GTX, cost-to-risk (F-962). Ordering: must precede soak (F-954). |
| 12 | Goal | equity + daily PnL from account endpoint + user-data stream, fail closed | caller-supplied | QUESTIONABLE | Equity field and day/loss definition undefined. The user-data stream does not exist (F-963). |
| 13 | Goal | explicit leverage + margin type from param; liquidation "strictly beyond" SL | Rule 11 | QUESTIONABLE | No buffer, cross allowed, no cap (F-964). |
| 14 | Goal | availableBalance ≥ new order IM + fees | Rule 11/9 | QUESTIONABLE (minor) | Ignores other pending exposure (F-966). |
| 15 | Goal | verify, then add a mark/last price gate vs SL and zone | Rule 13 | SOUND | Matches Rule 13. Should also own the post-fill -2021 fallback (Rule 14) and the min remaining validity (F-955). |
| 16 | Goal | $ amounts, qty, notional, margin, equity + source in messages | Rule 23 | SOUND (mostly) | Missing liquidation price, current price, time left (F-966). |
| 17 | Goal | configurable quote asset / USDC readiness | defer beyond V1 | QUESTIONABLE (priority) | Not a safety item. It changes the research universe (a protocol amendment). Placing it ahead of the missing safety phases (F-955/F-956) is misprioritised. No finding, IMPROVEMENT only. |
| ROADMAP | Ordering 9 → 10 → 11…17, "numeric order" | — | safety-first before live | WRONG | F-954. |
| ROADMAP | Missing phases | none for M1–M4, verification, F-951/F-952/F-953 items | insert closure phase | RISKY-DEFERRAL | F-955, F-956. |
