# Phase 11: Decision Alignment (docs + params) - Context

**Gathered:** 2026-09-30
**Status:** Ready for planning
**Mode:** `--auto --all` (Claude chose the recommended option for every gray area; each choice is logged in 11-DISCUSSION-LOG.md and can be overridden before planning)

<domain>
## Phase Boundary

Make the canonical docs and the versioned parameter sets say what the user decided in D031–D039 (plus D040–D042 where they touch docs). Under D031, DECISIONS.md outranks the docs, so conflicting doc text is amended here and no later phase (12+) is planned against stale rules.

Deliverables are documentation, parameter/TOML files, one universe manifest, and CI/verification gates. **No runtime behavior change in `src/`** beyond what a param-set loader needs to accept the new files. Code that implements the decisions (costs, SAFE_MODE re-placement, margin guard, mark-price triggers) belongs to Phases 12–24.

Requirements in scope: RSCH-01, RSCH-02, RISK-02, EXEC-02, OPS-01, plus new REQ-IDs for the lost MUST-level doc requirements (F-116).
</domain>

<decisions>
## Implementation Decisions

### Protocol amendment v1.1.0 (D032)
- **D-01:** Bump `docs/research/RESEARCH_PROTOCOL.md` from v1.0.1 to **v1.1.0** as a semantic change. Add a `Supersedes: v1.0.1` line and a migration paragraph, as protocol §0 requires. Do not edit v1.0.1 in place: keep the v1.0.1 text reachable in git history and note the supersession. — **Reversibility:** one-way — a frozen version cited by hashes and the research-gate CI cannot be un-published.
- **D-02:** Freeze v1.1.0 only when all three witnesses agree in the same change: the header line, a new DECISIONS row, and the DOC_STATUS entry. Update `.github/workflows/research-gate.yml` (and any script it calls) to expect v1.1.0. Run the gate's negative test (one witness missing must fail).
- **D-03:** The numeric pre-registration replaces the "TBD until exercised on real data" reservation in §0/§1–§5. It must contain concrete numbers for:
  - min trade count per candidate on validation (default **100 trades**, and at least 30 in each walk-forward fold);
  - min expectancy after costs (default **> 0 R after full costs, lower 95% bootstrap bound > 0**);
  - max drawdown (default **≤ 20% of research equity**, using the same equity base as the risk engine);
  - the variant budget (default **N = 25**, counting every parameter combination tried, per family);
  - the multiple-testing correction (default **Holm–Bonferroni at family-wise α = 0.05** over the N variants);
  - a single-use holdout (default **the last 20% of the dataset by time**, locked, touched once per candidate lineage).

  Values are Claude's recommended defaults. The planner must check feasibility against expected trade frequency on 4H/1H (a 100-trade floor may be unreachable for a low-frequency family) and adjust the number *before* freezing, never after seeing results. — **Reversibility:** one-way — after freeze, a change forces v1.2.0 and a new lineage.
- **D-04:** Remove any wording that lets a human pass a failing candidate. A human may only reject a candidate that passes (D032). Record the holdout as single-use with an auditable "consumed" marker (a hash of the candidate spec + params, stored beside the protocol), so a second look is detectable.
- **D-05:** Keep D030 (kill-gate firing rule) untouched. The amendment must not reintroduce the inverted disjunction.

### Parameter sets (D036–D039)
- **D-06:** Never edit an existing `params/**/*.toml` in place (F-810). Create new versioned sets next to the old ones, e.g. `params/trend-pullback/baseline-v4.toml`, `params/breakout-retest/baseline-v4.toml`, and matching `baseline-no-trade-v2` / `baseline-simple-trend-v2` for trend-pullback. Old files stay for reproducing past hashes. — **Reversibility:** costly — new set names get baked into experiment hashes and registry rows.
- **D-07:** New sets carry: `partial_fill_fraction = 1.0` (D038), entry fee modeled at the taker rate (D036), and `working_type = "MARK_PRICE"` (D037). Partial-fill behavior is a separate sensitivity run, not a canonical parameter. If the loader cannot express `working_type` or the taker-entry flag today, extend the registry schema minimally and add a loader test. Any hash-normalization problem is fixed in code, never by picking trading parameters (D038).
- **D-08:** Old sets get a `superseded by v4 (D036-D038)` marker. This is metadata only, not a content edit, and must not change the set's hash. If any metadata field participates in the hash, put the note in the DECISIONS row and the phase summary instead.
- **D-09:** The point-in-time research universe (D039) is a committed manifest file (default `params/universe/research-universe-v1.toml`, planner's choice) listing 10–15 symbols, the selection date, the selection rule, delisted symbols included, and a content hash. It is frozen and hashed before any evaluation. If the volume data needed to rank symbols at the dataset start date is not yet available (Phase 13 backfills it), this phase records the *rule and slots* and ships the manifest as `DRAFT`, with the freeze step owned by Phase 13. The live-5 list stays a separate config and is untouched.

### Doc amendments (D033, D034, D035, exchange facts)
- **D-10:** One consolidated amendment pass per doc, ordered by authority (DECISIONS first, then GLOSSARY / DATA_MODEL / CONFIGURATION, then the rest). Each edited paragraph cites its decision ID (e.g. "per D034") so the audit trail survives. Do not rewrite unrelated text.
- **D-11:** SAFE_MODE: in `SECURITY_AND_OPERATIONS`, `RUNBOOK` and `EXECUTION_SPEC`, replace "no new live order placement" with entries-only blocking. Protective and reduce-only orders are always allowed. Document the ladder: missing or canceled SL → automatic re-place; SL rejected or unacknowledged → reduce-only close → alert (D034). Also update the cancel-only reconciler wording it supersedes.
- **D-12:** RISK_MANAGEMENT: daily loss = realized PnL + commissions + funding, against equity at the UTC day start (00:00 UTC = 07:00 Asia/Ho_Chi_Minh), thresholds 0.5% warning / 1% stop, DAILY_STOP cancels pending entries and keeps SLs (D033). Margin rules: ISOLATED, 5x cap, marginType/leverage set explicitly, liquidation beyond SL with buffer, available-margin check includes resting entries (D035). Also put the quantization check order that D031 says conflicts between docs, AGENTS.md and .planning into one canonical statement.
- **D-13:** Exchange facts are corrected in the docs, each with a "verify against current Binance docs before implementation" marker instead of new hard-coded numbers from memory:
  - the 200 conditional-order limit is account-wide, not per symbol (F-051);
  - algo trigger-time semantics: `FINISHED` ≠ filled, and `REJECTED`/`EXPIRED` can occur at trigger (F-054);
  - the WS URL split (F-053);
  - `MARKET_LOT_SIZE` and `PERCENT_PRICE` filters (F-056);
  - remove "HMAC-checked" for TradingView webhooks, since TradingView cannot sign; describe the actual shared-secret/allow-list control (F-052).
- **D-14:** Every exchange-fact edit is grounded in the current official docs. The researcher fetches them (Context7 / WebFetch on developers.binance.com) and records the source URL and fetch date in `docs/SOURCES.md`. No fact is edited from memory or from the audit report alone.

### GLOSSARY and new requirements (F-110, F-116)
- **D-15:** GLOSSARY §9: collapse synonym reason-code pairs to one canonical code each and list every `ApprovalResult` value and reason code the code actually emits (derive the list from `src/` with CodeGraph or grep, not from memory). Where a code and a glossary term disagree, the glossary is the enum source of truth (D016), so record any needed *code* rename as a follow-up for the phase that owns that module. Do not rename code in Phase 11. Also fix the stale cross-references the audit lists (DECISIONS.md:22, alert example, SOURCES link; audit item P2-3).
- **D-16:** F-116: add new REQ-IDs to `.planning/REQUIREMENTS.md` for the MUST-level doc rules that fell out of the plan (SL may never be loosened, no averaging down, constraint snapshot stored per plan, restart sequence, version in health, secrets encrypted at rest, emergency controls). Each gets a traceability row to the phase that will implement it (12–26). Where a rule is deliberately dropped, record that in DECISIONS as an explicit exclusion rather than leaving it silent. Prefix and numbering follow the existing REQ-ID style.

### Verification and gates
- **D-17:** Verification is script-based, in the style of the earlier `.planning/quick/*-verify.cjs` checks. A script asserts the greppable facts: protocol header + DECISIONS row + DOC_STATUS agree at v1.1.0; no "no new live order placement" left; no "HMAC-checked" for TradingView; new params contain the three required keys; universe manifest hash matches; GLOSSARY has no duplicate reason codes. It runs locally and, where cheap, is wired into an existing workflow.
- **D-18:** Run the existing suites that touch params/registry/hash (registry, experiment hash, golden fixtures) after adding param sets. New sets must not change any old hash. Any hash that must change is recorded as a deliberate change, per D038, and is not silently regenerated.
- **D-19:** DOC_STATUS.md is bumped for every doc whose status or version changes, and DECISIONS.md gets one summary row for this phase's alignment work (no new decision content, only the record that D031–D039 are now reflected in the docs).

### Claude's Discretion
- File/folder naming for the universe manifest and param-set suffixes, as long as D-06 (no in-place edits) and D-09 (frozen and hashed) hold.
- Exact wording of amended paragraphs, provided each cites its decision ID.
- Exact REQ-ID prefixes and numbering for the F-116 additions.
- Whether the verify script is one file or one per plan.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authority and decisions
- `docs/DECISIONS.md` — D031–D042; D029 freeze, D030 kill-gate rule, D016 (GLOSSARY as enum source), D013
- `docs/DOC_STATUS.md` — status/version index; the third freeze witness
- `AGENTS.md` — project constraints (determinism, no-AI core, fail-closed, quantization order); must not conflict with amended docs
- `.planning/ROADMAP.md` §"Phase 11" — goal and 5 success criteria
- `.planning/REQUIREMENTS.md` — RSCH-01, RSCH-02, RISK-02, EXEC-02, OPS-01; target for new F-116 REQ-IDs

### Audit
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` — findings F-022, F-903, F-960, F-009, F-952, F-013, F-011, F-051, F-052, F-053, F-054, F-056, F-005, F-006, F-024, F-110, F-116, F-810; AMB-001…AMB-039 (§20); item P2-3
- `.planning/audits/2026-09-29-deep-audit/findings.json` — machine-readable findings
- `.planning/audits/2026-09-29-deep-audit/INVARIANTS.md` — authority ranking used by the audit

### Research protocol and gate
- `docs/research/RESEARCH_PROTOCOL.md` — v1.0.1 FROZEN; §0 freeze/bump rules, numeric-gate reservation, kill-gate paragraph
- `docs/research/families/trend-pullback.md`, `docs/research/families/breakout-retest.md`, `docs/research/families/range-mr.md` — family sheets (variant counts feed D-03)
- `docs/research/kill_gate_decisions.json`
- `docs/backtest/BACKTEST_SPEC.md` — dataset splits, walk-forward, research vs live universe
- `.github/workflows/research-gate.yml`, `.github/workflows/registry-gate.yml`, `.github/workflows/paper_freeze_check.yml` — gates to update or keep green

### Docs to amend
- `docs/configuration/CONFIGURATION.md` — parameter registry; `working_type`, taker entry, `partial_fill_fraction`
- `docs/GLOSSARY.md` §8–§9 — enums, reason codes, `ApprovalResult`
- SECURITY_AND_OPERATIONS, RUNBOOK, EXECUTION_SPEC, RISK_MANAGEMENT — planner locates exact paths under `docs/operations/`, `docs/trading/`, `docs/integration/`
- `docs/data/DATA_MODEL.md` — constraint snapshot / entities lost per F-111, F-112, F-116
- `docs/SOURCES.md` — record Binance doc URLs and fetch dates for D-14
- `docs/TECHNOLOGY_STACK.md`

### Parameter sets
- `params/trend-pullback/baseline-v3.toml`, `params/trend-pullback/baseline-no-trade-v1.toml`, `params/trend-pullback/baseline-simple-trend-v1.toml`
- `params/breakout-retest/baseline-v3.toml`
- `src/domain/registry.py` — param loader and hash normalization
- `src/backtest/costs.py`, `src/backtest/simulator.py` — read-only context for `partial_fill_fraction` and entry-fee handling (not modified here)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/domain/registry.py`: parameter-set loader and hashing; the new v4 sets must load through it and must not perturb old hashes.
- `.planning/quick/*/*-verify.cjs`: prior script-style verification; follow the same pattern for D-17.
- `.github/workflows/research-gate.yml`: the three-witness freeze check to update for v1.1.0.

### Established Patterns
- Frozen artifacts are never edited in place; a new version is created with a `Supersedes` line (protocol §0, and F-810 for params).
- Every doc change cites a DECISIONS row; DECISIONS > docs > AGENTS.md > .planning (D031).
- Exchange-sensitive facts are verified against current official docs, not memory.

### Integration Points
- `partial_fill_fraction` appears in `src/backtest/costs.py`, `src/backtest/simulator.py`, `src/domain/registry.py` and four param files. Phase 12 changes cost math and Phase 14 the simulator, so Phase 11 only covers the data and schema side.
- The universe manifest is consumed later by Phase 13 (backfill) and the research runs.
- New REQ-IDs feed phases 12–26 traceability.
</code_context>

<specifics>
## Specific Ideas

- The multiple-testing motivation from D032: ~25 variants with no correction gives P(at least one false pass) ≈ 72%; the pre-registered correction must bring the family-wise rate back to ≤ 5%.
- The operator works full-time, so nothing in the docs should imply a human must react within minutes (D034 rationale).
</specifics>

<deferred>
## Deferred Ideas

- Implementing the decisions in code: cost model (Phase 12), mark-price klines and universe backfill (Phase 13), simulator (Phase 14), SAFE_MODE re-placement and reconciler (Phase 20), daily-loss state (Phase 21), margin and liquidation guard (Phase 22), two-step confirm (Phase 23).
- Renaming any code enum or reason code that disagrees with the cleaned GLOSSARY: the owning phase does it (D-15).
- Freezing the research universe with real volume data: Phase 13 (D-09).

None of the pending todos matched this phase.
</deferred>

---

*Phase: 11-Decision Alignment (docs + params)*
*Context gathered: 2026-09-30*
