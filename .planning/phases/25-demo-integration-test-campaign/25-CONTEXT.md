# Phase 25: Binance Demo Integration Test Campaign - Context

**Gathered:** 2026-11-07
**Status:** Ready for planning (decisions chosen by `--auto`; items marked OWNER are NOT decided)

<domain>
## Phase Boundary

Prove the whole system correct and robust on Binance Demo Trading (D040 DEMO stage), failure paths included,
before any real money. Correctness is the only goal; profitability is out of scope. Deliverables, from the
ROADMAP: (1) an automated Demo scenario suite separate from unit tests (`pytest -m demo`, credentials from the
environment, never in CI by default); (2) APPROVE -> CONFIRM on the Demo account through the same code path as
live; (3) a pre-registered continuous soak of at least 3 weeks; (4) a written list of known Demo-vs-mainnet
differences so Phase 26 CANARY targets only what Demo cannot prove.

Out of scope: any mainnet or LIVE order (live placement stays disabled, `LIVE_ORDERS_DISABLED`), parameter
tuning, new strategy work. Phase 24's owner steps (plan 24-33: VPS, second Telegram account, heartbeat) are a
prerequisite the owner closes; this phase does not close them.

</domain>

<decisions>
## Implementation Decisions

`[auto]` marks a choice made without asking, using the recommended option. Each is grounded in AGENTS.md, the
ROADMAP entry or Phase 24 artifacts. The owner may overrule any of them in review.

### Who runs what (hard rule)
- **D-01 [auto]:** Any step that sends an order or any signed request to Binance Demo (`--execute`, `pytest -m demo`, soak start) is run **by the owner only**. Agents write, review and dry-run the suite against fakes; they never run it. Source: AGENTS.md "Demo smoke/probe scripts (--execute) are run by the owner only". — **Reversibility:** reversible — a process rule.
- **D-02 [auto]:** Every agent-run test in this phase uses fakes or the project's own stores (`tests/support/`, fake exchange), as in Phase 24.

### Suite shape (criterion 1)
- **D-03 [auto]:** Register a `demo` pytest marker; the default and CI selection (`-m "not docker"`) excludes it, and a guard test fails if a `demo`-marked test is collected without the marker. Credentials come from `BINANCE_DEMO_*` env names only; the suite refuses to start if any `BINANCE_LIVE_*` variable is present or the base URL is not `demo-fapi.binance.com`. — **Reversibility:** costly — marker and env names become the owner's run procedure.
- **D-04 [auto]:** Reuse the Phase 24 harness (`scripts/demo_rehearsal.py`, `tests/support/live_rig.py`, the fake exchange) instead of a second framework. Scenario results are recorded as evidence JSON under the phase `evidence/` directory with the `DEMO_OBSERVED` label, the same shape as the Phase 24 smoke files.
- **D-05 [auto]:** One scenario per ROADMAP bullet (happy path, partial fill, -2021 before placement, SL rejected after fill, cancel racing a fill, replayed APPROVE/CONFIRM, restart at three points, WS disconnect and listenKey expiry, clock skew, 418/429, DB outage during a risk-reducing action, DAILY_STOP, liquidation-guard and margin rejections, SAFE_MODE entry and exit, foreign order and doubled position). Each scenario first gets a fake-exchange twin that runs in CI, so the logic is tested before the owner spends Demo time.
- **D-06 [auto]:** Add the three RUNBOOK drills the ROADMAP list omits (G2-016): manual close outside the system, stale feed, unprotected-position drill; and the P20-DEMO operator-command scenarios (`rest_gate_cli status/clear` after a false restriction).
- **D-07 [auto]:** Questions only Demo can answer are scenarios with an explicit evidence label and a NOT_OBSERVED default until the owner runs them: A2 (GTD expiry terminal status), A3 (does Binance cancel `closePosition` legs when the position closes), whether a real 418 ban outlives 259200 s, 429/418 queue order, B2/B3 same-id stop re-place, user-data stream states used by SAFE_MODE exit row 7.

### Same code path as live (criterion 2)
- **D-08 [auto]:** No Demo-only branch in `src/execution`, `src/live` or `src/risk`. Only the endpoint and keys differ, enforced by an AST or wiring test. Demo runs in a DEGRADED health state are never evidence of live readiness (D056): scenarios and soak also run healthy.

### Soak (criterion 3)
- **D-09 [auto]:** Pre-register the soak before it starts: duration (minimum 21 days), symbols (live-5 universe), pass criteria (zero unexplained local-vs-exchange divergence, zero position without an exchange-side SL, zero duplicate entry, every alert explained) and the restart rule (any defect restarts the clock after the fix). The registration is a committed file with a hash, written before the first soak order. The soak is started and stopped by the owner.
- **D-10 [auto]:** The soak reuses the Phase 16/24 soak tooling (`scripts/export_soak_evidence.py`, `soak_host_acceptance.py`, `deploy/` soak scripts) rather than new tooling.
- **D-11 [auto]:** Before the soak, reduce the health-tick journal volume (R-25, about 63,000 rows a day): write on change only or lengthen the cadence, with a test.

### Demo-vs-mainnet differences (criterion 4)
- **D-12 [auto]:** A single document `docs/operations/DEMO_VS_MAINNET.md` lists each difference (liquidity, fills, filters, fees, resets) with an evidence label (DEMO_OBSERVED, DOCS, NOT_OBSERVED), and Phase 26 reads it. Fill the "Demo cross-check" lines of `09-EXCHANGE-FACTS.md` from recorded Demo order ids (G2-030).

### Inherited code items that gate the campaign
- **D-13 [auto]:** R-25 (health tick volume) and R-24 (wrap a pool-exhaustion TimeoutError as `StoreUnavailable`) are small and are done in this phase before the soak.
- **D-14 [auto]:** R-23, R-28 and the other Info-level review items stay deferred unless a scenario exposes them.

### OWNER decisions (NOT decided here)
- **OWNER-1 (R-21 / WR-03):** margin reservations never advance (`mark_placed`, `mark_open` have no caller). The recommendation agreed 2026-11-07 is to stamp `mark_placed` at the acknowledgement and `mark_open` at the first fill through `StoreExecutor.write`, but it needs a DECISIONS row first. Planning may prepare the plan; execution waits for the row.
- **OWNER-2 (R-22 / WR-04):** cancel-on-stop for the live process touches D079 and the never-resend rule; needs an owner decision. The interim stop procedure (RUNBOOK 22.5) applies; restarting the process during the campaign follows it.
- **OWNER-3 (P20-ERR1003):** parsing the text of Binance error -1003 needs an owner exception to D-10 and a DECISIONS row. Until then the assumed 259200 s wait stays, and the scenario only observes and records the text.
- **OWNER-4:** which owner session slots and dates run the scenarios, and the soak start date. No plan sets a date.

### Claude's Discretion
- Scenario file layout, evidence JSON field names (within the Phase 24 shape), wave split and plan count.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Rules and decisions
- `AGENTS.md` - owner-only Demo runs, secrets, no mainnet, execution model since Phase 19
- `docs/DECISIONS.md` - D040 (stages), D041 (approval), D055/D079/D080 (fill-driven protection), D056, D058
- `docs/operations/RUNBOOK.md` - section 22 (live process), drills, stop procedure 22.5
- `docs/testing/TESTING_STRATEGY.md` - marker and gate conventions
- `.planning/ROADMAP.md` - Phase 25 entry and its inherited items

### Phase inputs
- `.planning/phases/24-live-runtime-composition-demo/24-CONTEXT.md`, `24-DEFERRED.md`, `24-REVIEW.md`, `24-REVIEW-FIX.md`, `24-OWNER-RUNBOOK.md`
- `.planning/phases/24-live-runtime-composition-demo/evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json` - the COMPLETE smoke file, the evidence shape to follow
- `.planning/phases/20-reconcile-safe-mode-hardening/20-DEFERRED.md` - section "Needs a connected machine (Demo)"
- `.planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md` and `09-DEMO-REHEARSAL-FINDINGS.md`
- `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md`

### Coverage
- `.planning/phases/24-live-runtime-composition-demo/COVERAGE.md` - API surface decisions (DRAFT, owner review pending); this phase adds no new API capability

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/demo_rehearsal.py`, `scripts/demo_probe.py`, `scripts/demo_clear.py`: the owner-run Demo harness and cleanup.
- `tests/support/live_rig.py`, `tests/support/fake_binance_exchange.py`: fakes for the CI twin of each scenario.
- `src/ops/drills.py`: the eight RUNBOOK drills.
- `src/live/` (composition, start sequence, operator commands), `src/reconcile/`, `src/execution/protection.py`, `emergency_close.py`.
- `scripts/export_soak_evidence.py`, `scripts/soak_host_acceptance.py`, `deploy/*.sh`: soak tooling.

### Established Patterns
- Evidence files with an evidence-kind label; NOT_OBSERVED until the owner records a result.
- Owner-run steps live in an OWNER-RUNBOOK; agents only write and dry-run.
- Hash-locked parameters: nothing in `params/` is edited in place.

### Integration Points
- `pyproject.toml` pytest markers (new `demo` marker, default selection excludes it).
- Phase 24 plan 24-33 results (owner) are an input to scenario 1.

</code_context>

<specifics>
## Specific Ideas

- Each scenario has a fake twin (CI, agents) and a Demo run (owner) sharing the same assertions.
- A single evidence index file per owner session listing scenario, evidence label, order ids and result.

</specifics>

<deferred>
## Deferred Ideas

- Mainnet CANARY runs and anything with real money: Phase 26.
- Full async rewrite of `OperatorCommands` database work (R-23): later phase.
- Strategy or parameter changes based on Demo results: out of scope by the research rule.

</deferred>

---

*Phase: 25-demo-integration-test-campaign*
*Context gathered: 2026-11-07*
