# Phase 1: Research Formalization - Research

**Researched:** 2026-09-19
**Domain:** Research-protocol freeze + strategy-family formalization + canonical-doc contradiction resolution (docs-only phase)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** The frozen research protocol lives in a new canonical doc `docs/research/RESEARCH_PROTOCOL.md` — versioned and freezable, stating dataset splits, cost model, execution assumptions, and acceptance gates.
- **D-02:** It is NOT a section inside `TRADING_STRATEGY_RESEARCH.md` (a living document cannot be frozen) and NOT a `.planning`-only artifact (the contract must outlive planning).
- **D-03:** Each of the three families (Trend Pullback, Breakout+Retest, Range Mean-Reversion) is specified with a fixed 7-slot template per concept: informal definition → machine-detectable definition → alternative definitions → advantages/disadvantages → look-ahead-bias analysis → testable parameters → backtest path — plus one per-family sheet (hypothesis, timeframe mapping, variants).
- **D-04:** Freeform prose specs are rejected: family specs must be mutually comparable under the same framework.
- **D-05:** C1–C7 are resolved by direct canonical-doc edits (preserving each doc's purpose) plus one `DECISIONS.md` row per contradiction plus a `DOC_STATUS.md` bump, batched in a single Phase-1 plan — not by leaving docs untouched.
- **D-06:** Per documentation authority (DECISIONS.md > product scope > engineering principles > GLOSSARY > frozen SPEC > supporting specs > research notes); `TRADING_STRATEGY_SPEC.md` stays TBD wherever research has not produced a validated rule.
- **D-07:** "Rejected by gate, not by convention" means a registry loader plus CI check: any run without a registered `parameterSetId` + `parameterSetHash` fails closed. Convention/documentation-only enforcement is explicitly rejected.
- **D-08:** Strategy V1 family selection stays TBD (D012) — no phase output may declare a winner without backtest plus out-of-sample evidence.

### the agent's Discretion
- Exact section layout inside `RESEARCH_PROTOCOL.md` and the per-family sheet cosmetics are at the planner/researcher discretion, provided the D-01/D-03 content requirements are met.
- Plan slicing within the phase (fine granularity) is at the planner's discretion.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RSCH-01 | Research protocol frozen (dataset splits, cost model, execution assumptions, acceptance methodology) before any parameter work | `## Frozen-Protocol Document` gives section-by-section source mapping into BACKTEST_SPEC, CONFIGURATION, research doc, RISK; `## Freeze Mechanics` gives the version/freeze/amend procedure |
| RSCH-02 | Three candidate families specified independently (informal → machine-detectable → alternatives → bias → parameters → backtest) | `## 7-Slot Instantiation Guidance` maps each slot to exact source sections per family (A/B/C) plus per-family sheet contents |
| RSCH-03 | Core Doc contradictions resolved with decisions in DECISIONS.md | `## C1–C7 Resolution Approaches` gives per-contradiction edit target, replacement text direction, authority citation, and DECISIONS row (D022–D028) |
</phase_requirements>

## Summary

Phase 1 is a documents-and-gates phase: no strategy code, no backtest runs, no parameter values. Its three outputs are (1) a new freezable canonical doc `docs/research/RESEARCH_PROTOCOL.md` that consolidates — not duplicates — the methodology already scattered across BACKTEST_SPEC, CONFIGURATION, the research draft, RISK, and METRICS; (2) three family sheets in the fixed 7-slot template, transcribed from the living research draft's candidate definitions (B1–B4, E1–E4, S1–S3, T1–T3, Q1–Q12) with every unvalidated rule left TBD; (3) direct edits resolving contradictions C1–C7 plus DECISIONS rows D022–D028 and a DOC_STATUS bump, in one batched plan.

**Primary recommendation:** Structure the phase as 4–5 fine-grained plans in this order — frozen protocol doc → three family sheets (one plan, three sheets, same template) → C1–C7 edit batch + DECISIONS/DOC_STATUS → gate spec + minimal CI check — with the gate's executable limited to a single CI YAML (a gate, not product code) and the registry loader itself specified as a contract for Phase 3 to implement.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Frozen protocol document | Docs (canonical) | CI (gate check) | The contract is prose + version header; CI only verifies presence/frozen status, never strategy semantics |
| Family specification sheets | Docs (research/) | — | Hypotheses, not code; Phase 4 consumes them as detector requirements |
| Contradiction resolutions | Docs (canonical edits) | — | Authority-ordered text edits; no runtime behavior changes |
| Parameter registry gate | CI + contract doc | Backend (Phase 3) | Phase 1 delivers the loader contract + failing-closed check shape; Phase 3 builds the loader/DB |

## Project Constraints (from AGENTS.md)

- **Determinism** — protocol must mandate closed-candle, no-repaint, prefix-invariant rules; family sheets must state confirmation timing per concept.
- **No-AI core** — no family sheet may contain an LLM-gated condition; all 7 slots must be machine-checkable rules.
- **Exchange authority** — cost/execution assumptions reference Binance semantics but hard-code no endpoint details; re-verification-before-implementation policy carries into the protocol doc.
- **Quantization** — cost model section must include floor-only quantization + realized-risk gate as an execution assumption (identical backtest/paper/live).
- **Fail closed** — gate CI check fails closed (non-zero exit, required status) on missing protocol freeze or unregistered parameter identity.
- **Tech stack** — Python 3.13 hư; irrelevant to this docs-only phase except CI runner label (`ubuntu-latest`, no toolchain needed beyond YAML + doc lint).
- No `src/`, `pyproject.toml`, or product code may be created in this phase (PROJECT.md greenfield rule; research/spec/code separation in `docs/implementation/AGENT_INSTRUCTIONS.md`).

## Frozen-Protocol Document: `docs/research/RESEARCH_PROTOCOL.md`

New canonical file. Recommended section layout (cosmetics at planner discretion, content mandatory per D-01):

### §0 Protocol identity & status header (mandatory block)
```markdown
> **Protocol version:** v1.0.0
> **Status:** FROZEN | DRAFT
> **Frozen on:** YYYY-MM-DD (date + DECISIONS row ID, e.g. D029)
> **Supersedes:** (none | v0.x.y + migration note)
```
- Status vocabulary is binary: `DRAFT` or `FROZEN`. No "provisional"/"baseline" qualifiers — they are how anecdotes leak in.
- Source pattern: mirrors `TRADING_STRATEGY_SPEC.md` lines 3–5 (`TEMPLATE — NOT FROZEN`) but inverted: this doc is authoritative only when `FROZEN`.

### §1 Dataset splits — source: BACKTEST_SPEC §7 + research §2.4 + BACKTEST_SPEC §10.1
Must state verbatim-equivalent:
- Mandatory three-way split `Development → Validation → Final holdout / forward test` [VERIFIED: docs/backtest/BACKTEST_SPEC.md:52-64]; final holdout must not be used to choose parameters.
- Walk-forward `train → validate → roll forward` where practical, especially for parameterized structure/ATR rules [VERIFIED: docs/backtest/BACKTEST_SPEC.md:66-74].
- Research universe (10–15 liquid symbols) vs live universe (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT); report both slices; broader universe must not rescue a weak live universe [VERIFIED: docs/backtest/BACKTEST_SPEC.md:111-119].
- Anti-overfitting rules R1–R6 transcribed (parameter changes need reasons; plateau over point optimum; mandatory out-of-sample; costs from run #1; no daily-PnL targeting; no optimization on skipped trades) [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:968-1006].

### §2 Cost model — source: BACKTEST_SPEC §5 + RISK §3 + research §10.3–10.5
Minimum declared fields: entry fee, exit fee, funding treatment, slippage, spread/fill assumptions [VERIFIED: docs/backtest/BACKTEST_SPEC.md:30-40]. Must add:
- Funding applied to positions held through funding events (research §10.4).
- Slippage as explicit formula `effective entry = intended entry + slippage` (research §10.5), calibrated later from paper/live data — never zero by default.
- Quantization assumption: floor-only + realized-risk gate, identical in all modes (AGENTS.md constraint; full semantics owned by RISK §11 in Phase 5, referenced not duplicated).

### §3 Execution assumptions — source: BACKTEST_SPEC §3/§4/§6 + research §9–§10
- Candle-close rule: decisions use only information available by source candle close; no future swing confirmation or intrabar outcome leaks [VERIFIED: docs/backtest/BACKTEST_SPEC.md:18-22]; core signals on closed candles [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:633-639]; warm-up gates (e.g. EMA200-4H invalid until history suffices) [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:641-645].
- Strategy decision 1H/4H; execution simulation 1m; 1H OHLC both-touched bars resolved with 1m data [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:656-669].
- Intrabar tie-break: fixed before main evaluation; candidates are conservative adverse-first, next-finer-timeframe, or mark-ambiguous-and-segregate [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:671-683]; if finer data unavailable, conservative deterministic assumption + report it [VERIFIED: docs/backtest/BACKTEST_SPEC.md:24-28].
- Limit-order simulation checklist: touch-vs-fill, partials, TIF/expiry, cancel-after-invalidation, no retroactive fill after expiry [VERIFIED: docs/backtest/BACKTEST_SPEC.md:42-50].
- Baselines: every candidate compared against no-trade + at least one simple baseline (buy/hold reference or simple trend filter) [VERIFIED: docs/backtest/BACKTEST_SPEC.md:76-84].

### §4 Acceptance methodology — source: BACKTEST_SPEC §11 Acceptance gates + research §17 + D013
- The 10 acceptance gates transcribed (deterministic rules; no material look-ahead; costs modeled; not single-symbol/session; OOS consistent; tolerable drawdown; reproducible; interval/distributional uncertainty; no single-point dependence; baseline-compared) [VERIFIED: docs/backtest/BACKTEST_SPEC.md:136-151], with the explicit note that exact numerical thresholds remain TBD until exercised on real data [VERIFIED: docs/backtest/BACKTEST_SPEC.md:151].
- Research acceptance draft categories: Statistical / Robustness / Operational / User-fit [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:1008-1041].
- Uncertainty reporting: trade counts by symbol/quarter/regime, R mean/median/σ, bootstrap expectancy interval, resampled drawdown, block-bootstrap under dependence, `SE ≈ σ / sqrt(n)` diagnostic [VERIFIED: docs/backtest/BACKTEST_SPEC.md:87-109]; per-candidate uncertainty questions (independent-ish opportunities, bootstrap sensitivity, slice consistency, universe-broadening honesty, plateau existence) [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:1264-1273].
- Kill gate D013: ≥3 independently specified families AND ≥6 months research; else stop adding complexity, keep live disabled, classify as research/journal platform; NO_TRADE valid [VERIFIED: docs/DECISIONS.md:17 + research §13-stop-conditions lines 1249-1262].

### §5 Parameter-registry linkage — source: CONFIGURATION §2/§4/§5/§7
- Identity tuple `strategyVersion + parameterSetId + parameterSetHash` required on every backtest/paper/alert/order plan [VERIFIED: docs/configuration/CONFIGURATION.md:64-74]; hash over canonical serialized parameter JSON with normalized numerics/key order [VERIFIED: docs/configuration/CONFIGURATION.md:24-25,126-132].
- Immutability: published/live-used sets never mutated; behavior change → new set + strategy version bump [VERIFIED: docs/configuration/CONFIGURATION.md:76-82].
- Experiment linkage tuple: experimentId, strategyVersion, parameterSetHash, dataSnapshotId, codeVersion, costModelHash [VERIFIED: docs/configuration/CONFIGURATION.md:100-112].
- Search discipline: sweeps only inside research-declared ranges; report by region, not best point; narrow isolated optimum = robustness warning [VERIFIED: docs/configuration/CONFIGURATION.md:115-123].

### §6 Regime, invalidation, expiry, and journal separation (brief, by reference)
- Every setup carries `valid_until` + price/structure invalidation (+ optional volatility invalidation; no `high ATR = news` inference without event data) [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:796-826].
- System vs user-executed vs opportunity reporting with Signal/Approve/Order/Fill timestamps [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:746-793 + docs/data/DATA_MODEL.md:364-370].

## Freeze Mechanics

1. **Draft → Frozen:** author sets header `Status: FROZEN`, fills `Frozen on` date, and the same plan adds a DECISIONS.md row recording the freeze (e.g. D029 "Research protocol v1.0.0 frozen") + DOC_STATUS.md lists the new file under Stable/canonical. Frozen = header says FROZEN *and* the DECISIONS row exists; either alone is DRAFT in effect, and the CI check enforces both (see Gate Design).
2. **Amendment:** never edit a frozen version in place. Create `v1.1.0` (clarification, same semantics) or `v2.0.0` (semantic change: splits, cost, execution, gates), with a `Supersedes` line and a one-paragraph migration note; old version retained in-file (appendix) or in git history with the DECISIONS row citing the commit. Semantic change → new strategy-version lineage downstream (SPEC §12 rule: detection/entry/SL/TP/invalidation/expiry/feature change = new version [VERIFIED: docs/strategy/TRADING_STRATEGY_SPEC.md:99-111]).
3. **Living-doc firewall (D-02):** `TRADING_STRATEGY_RESEARCH.md` remains the living draft; the protocol doc copies methodology *out* of it once. After freezing, new learnings go to the research draft first and enter the protocol only via a versioned amendment — the planner must include this one-way flow as a protocol §0 paragraph to prevent silent drift.

## 7-Slot Instantiation Guidance

Fixed template per concept; every family uses the same 7 slots so sheets are mutually comparable (D-04). Source material per family:

### Family A — Trend Pullback (research §5.1, Stage A, Q1/Q5–Q9)
- **Informal:** trade with the larger trend after price pulls back to structure/MA/zone [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:320-328].
- **Machine-detectable:** must compose 4H-regime + 1H-pullback/setup rows; regime candidates from Q1 (structure? EMA? both?) [VERIFIED: research lines 330-335, 880-886]; sheet must pick from variants A1–A4 (structure-only; +EMA; +ATR; +volume) as separate testable rows, not prose [VERIFIED: research lines 337-345].
- **Alternatives:** Stage A baseline benchmark `4H trend + 1H pullback + structure entry + structure SL + 2R TP` [VERIFIED: research lines 831-847] is the mandatory reference alternative every A-variant is compared against.
- **Adv/disadv:** pullback gives defined stops (hypothesis [VERIFIED: research lines 326-328]); disadvantage to record: trend-filter dependence + in-range under-signal risk (cf. §5.3 rationale for a separate range family, lines 399-401).
- **Look-ahead-bias:** must answer research §4.1 questions 1–5 verbatim (swing lookback L/R bars, confirmation timing, no unclosed pivots, no repaint, 4H trend source) [VERIFIED: research lines 189-195]; baseline answer: pivot-based structure, closed-bar only.
- **Testable params:** swing lookback, zone tolerance ATR, EMA length, ATR buffer k, confirmation bars, minimum RR, signal expiry hours, risk rate — the CONFIGURATION §3 example list [VERIFIED: docs/configuration/CONFIGURATION.md:31-45].
- **Backtest path:** P0 backlog items (swing, pivot rule, zone, entry, stop, target, execution simulation [VERIFIED: research lines 1123-1133]) → P1 (implement A, same cost model, OOS compare, MFE/MAE [VERIFIED: research lines 1135-1141]).

### Family B — Breakout + Retest (research §4.3/§4.4/§5.2, Stage B)
- **Informal:** consolidation/S-R zone → breakout → retest → continuation [VERIFIED: research lines 349-361]; hypothesis: retest entry filters part of false breakouts vs entering the break [VERIFIED: research lines 363-365].
- **Machine-detectable:** breakout alternatives B1 close / B2 wick+close / B3 volume-confirmed / B4 two-bar [VERIFIED: research lines 239-267] and retest sequence (break → return → no confirmatory breakdown close → reclaim/rejection) [VERIFIED: research lines 275-303] must be instantiated as competing rows, never blended; baseline frame `4H direction/regime + 1H zone+breakout+retest` [VERIFIED: research lines 367-372].
- **Alternatives:** must-test list (wick-vs-close, volume, retest depth/timeframe, zone-vs-confirmation entry, beyond-zone-vs-beyond-swing SL, fixed-R-vs-structure TP) [VERIFIED: research lines 374-382] maps 1:1 onto Q3–Q8 [VERIFIED: research lines 899-933].
- **Adv/disadv:** advantage (fewer false breakouts); disadvantage: missed-trade/fill-rate cost — sheet must pre-commit to entry-quality metrics (fill rate, missed-trade rate, entry slippage, post-touch MFE/MAE) [VERIFIED: research lines 443-451].
- **Look-ahead-bias:** retest-waiting repaint risk must be addressed with explicit closed-bar confirmation rule (research warns some implementations repaint while awaiting retest [VERIFIED: research lines 303]); retest parameters (max bars, max distance, touch-vs-close, rejection candle, volume, 15M confirm) [VERIFIED: research lines 305-312] are bias controls, not free knobs.
- **Testable params:** same CONFIGURATION list as A, plus breakout confirmation bars and retest window/depth.
- **Backtest path:** Stage B comparisons (close vs volume vs zone vs confirmation [VERIFIED: research lines 849-856]).

### Family C — Range Mean-Reversion (research §5.3, Stage C)
- **Informal:** range high → SHORT, range low → LONG, stop outside range, TP to mid/opposite boundary [VERIFIED: research lines 386-397].
- **Machine-detectable:** range definition reuses §4.2 zone machinery (lookback, min touches, tolerance, ATR width, aging, invalidation [VERIFIED: research lines 219-227]) + explicit regime filter; sheet must state the filter as a NO_TRADE rule answering Q9 [VERIFIED: research lines 935-937].
- **Alternatives:** filter-on (trade only filtered ranges) vs filter-off diagnostic; TP-mid vs TP-opposite-boundary (T1/T2/T3 framework [VERIFIED: research lines 489-513]).
- **Adv/disadv:** covers non-trending periods the trend families miss [VERIFIED: research lines 399-401]; special risk: trend-break destruction, needs regime filter [VERIFIED: research lines 403-405].
- **Look-ahead-bias:** range boundaries confirmed on closed bars only; boundary-repaint (expanding range after entry) must be classified as invalidation, not hindsight redraw.
- **Testable params:** range lookback/touches/tolerance, regime-filter thresholds, SL buffer k, TP mode, minimum RR with NO_TRADE fallback (never beautify RR by shrinking SL [VERIFIED: research lines 514-522]).
- **Backtest path:** Stage C gated on regime-filter + dataset evidence of range periods [VERIFIED: research lines 858-860]; context features (funding/OI/session) only after core baseline, as incremental-value tests [VERIFIED: research lines 862-870]; OI experimental-only until self-collected history exists [VERIFIED: research lines 623-627].

### Per-family sheet (one page each, same cosmetics)
Hypothesis (one sentence) → timeframe mapping (`4H → regime / 1H → setup`; 15M optional only; 1m execution-simulation only) → variants table (A1–A4 / B-alternatives / C-filter states) → entry/SL/TP method codes (E1–E4 [VERIFIED: research lines 415-440]; S1–S3 [VERIFIED: research lines 463-483]; T1–T3) → open questions pointing at Q1–Q12 → explicit `V1 family selection: TBD (D012)` footer on every sheet (D-08).

## C1–C7 Resolution Approaches

Authority chain per D-06: DECISIONS > product scope > engineering principles > GLOSSARY > frozen SPEC > supporting specs > research notes. Each contradiction gets its own DECISIONS row (D022–D028); mechanical renumbers ride in the same batch (D-05).

### C1 — SystemMode naming (`LIVE_AUTONOMOUS` vs `LIVE_AUTONOMOUS_DISABLED`, missing `SAFE_MODE`)
- **Evidence:** GLOSSARY §8 canonical list is ``RESEARCH, BACKTEST, PAPER, LIVE_APPROVAL, SAFE_MODE, LIVE_AUTONOMOUS_DISABLED`` with note "`LIVE_AUTONOMOUS` is a future architecture mode and is disabled by default" [VERIFIED: docs/GLOSSARY.md:109-120]. `00_PRODUCT_SCOPE.md` §7 lists ``RESEARCH, BACKTEST, PAPER, LIVE_APPROVAL, LIVE_AUTONOMOUS`` (no `_DISABLED`, no `SAFE_MODE`) [VERIFIED: docs/00_PRODUCT_SCOPE.md:92-98].
- **Resolution:** edit scope §7 to the GLOSSARY list verbatim; keep the "future only, disabled by default, requires evidence/gates" qualifier attached to `LIVE_AUTONOMOUS_DISABLED`. Authority: D016 (GLOSSARY is sole terminology truth [VERIFIED: docs/DECISIONS.md:20]) outranks product scope.
- **Row:** D022 — SystemMode canonical list = GLOSSARY §8; scope §7 aligned.

### C2 — `SIGNAL_AND_ALERTS.md` §4 mixes execution states into signal states
- **Evidence:** §4 "Alert states" lists `DETECTED, NOTIFIED, VIEWED, APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED, ORDER_PLACED, FILLED, CLOSED` [VERIFIED: docs/trading/SIGNAL_AND_ALERTS.md:61-75]. GLOSSARY §2 lists the first 8 only and states "Execution lifecycle states do not belong in `SignalStatus`" [VERIFIED: docs/GLOSSARY.md:37-50].
- **Resolution:** trim §4 to the 8 canonical SignalStatus values; move `ORDER_PLACED/FILLED/CLOSED` to a short "lifecycle cross-reference" pointing at OrderStatus/TradeStatus (§5/§6). Section rename `Alert states` → `Signal states (canonical)` to kill the alert/signal conflation. Authority: GLOSSARY + D016.
- **Row:** D023.

### C3 — `EXECUTION_SPEC.md` §3 `APPROVED` vs GLOSSARY OrderStatus
- **Evidence:** §3 lifecycle runs `PLANNED → APPROVED → SUBMITTING → NEW …` [VERIFIED: docs/trading/EXECUTION_SPEC.md:39-53]. GLOSSARY §5 OrderStatus is `PLANNED, SUBMITTING, NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, UNKNOWN` — no `APPROVED` [VERIFIED: docs/GLOSSARY.md:75-87]. DATA_MODEL §3 mandates `SignalStatus ≠ OrderStatus ≠ PositionStatus ≠ ApprovalAction` [VERIFIED: docs/data/DATA_MODEL.md:330-338].
- **Resolution:** delete `APPROVED` from the §3 chain (`PLANNED → SUBMITTING → NEW …`); add one sentence: approval lives upstream (SignalStatus.APPROVED / TradePlanStatus.APPROVED); an order enters `PLANNED` only after plan approval. Also fix TESTING_STRATEGY §8's `EXPIRED → APPROVED` invalid-transition example [VERIFIED: docs/testing/TESTING_STRATEGY.md:107-117] to name the owning machine (approval/plan), so the example no longer implies an OrderStatus.APPROVED. Authority: GLOSSARY + D007 + D016.
- **Row:** D024.

### C4 — `Asia/Bangkok` vs `Asia/Ho_Chi_Minh`
- **Evidence:** research §9.3: "convert sang Asia/Bangkok (UTC+7)" [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:647-651]. ENGINEERING_PRINCIPLES §8: UTC internally, `Asia/Ho_Chi_Minh` presentation [VERIFIED: docs/01_ENGINEERING_PRINCIPLES.md:79-81 per grep]; DATA_PIPELINE §7: "UI may display `Asia/Ho_Chi_Minh`" (grep-verified).
- **Resolution:** one-word edit in research §9.3 → `Asia/Ho_Chi_Minh`; add Windows-`tzdata` note (stack requirement) if absent. Authority: engineering principles outrank research notes. [ASSUMED: exact ENGINEERING_PRINCIPLES §8 line number — verified by grep, not by Read this session.]
- **Row:** D025.

### C5 — research §12 non-canonical status names
- **Evidence:** §12 uses `Generated, Approved, SKIPPED_USER, Skipped-Busy, Expired, Invalidated` + execution names `OrderPlaced, PartiallyFilled, Filled, Canceled, TP, SL, ManualExit` [VERIFIED: docs/research/TRADING_STRATEGY_RESEARCH.md:746-771] — casing variants (`Skipped-Busy`), non-canonical `Generated/OrderPlaced/TP/SL/ManualExit` all violate the no-synonyms rule [VERIFIED: docs/GLOSSARY.md:139-141].
- **Resolution:** rewrite §12 states using canonical SignalStatus / OrderStatus / TradeStatus / PositionStatus / ApprovalAction; keep the section's real content (two performance tables + four timestamps SignalTime/ApproveTime/OrderTime/FillTime) and re-point the joins at DATA_MODEL §6 reporting joins [VERIFIED: docs/data/DATA_MODEL.md:364-370]. Authority: GLOSSARY + DATA_MODEL.
- **Row:** D026.

### C6 — duplicate/gapped section numbers
- **Evidence (all grep-verified on `^## ` headers):** BACKTEST_SPEC has `## 11. Experiment record` + `## 11. Acceptance gates`, then jumps to `## 13` (missing 12). DATA_PIPELINE ends `… §12` then repeats `## 8. Storage architecture` + `## 9. Python implementation rule`. TRADINGVIEW jumps `## 6 → ## 8` (missing 7). SECURITY_AND_OPERATIONS jumps `## 9 → ## 11` (missing 10). Research doc has `# 13. Signal validity` + `# 13. Research stop conditions`, `# 14. Candidate Research Plan` + `## 14. Statistical uncertainty questions`.
- **Resolution (pure renumber, zero semantic change):** BACKTEST_SPEC: Experiment record stays §11, Acceptance gates → §12, Research implementation → §13 (number only; keep the "Acceptance gates" title — it is referenced by scope §9 and ROADMAP). DATA_PIPELINE trailing 8/9 → §13/§14. TRADINGVIEW §8 → §7. SECURITY §11 → §10. Research: stop-conditions `# 13` → `# 25`, statistical-uncertainty `## 14` → `# 26` (appended sections take next-free numbers; original §13/§14 owners keep theirs). Cross-references mentioning old numbers (§9 scope→BACKTEST gates is by title, safe) checked in the same plan.
- **Row:** D027 (single row for the mechanical batch).
- **Risk:** any external reference to old numbers breaks silently — planner must add a "grep all `§1[13]`/`Section 8` references" verification step. [ASSUMED: no outside-repo links to these numbers exist.]

### C7 — `SignalStatus.APPROVED` vs `TradePlanStatus.APPROVED` ownership
- **Evidence:** GLOSSARY lists `APPROVED` in both SignalStatus [VERIFIED: docs/GLOSSARY.md:37-48] and TradePlanStatus (`READY, APPROVAL_PENDING, APPROVED, EXPIRED, INVALIDATED, SUPERSEDED` [VERIFIED: docs/GLOSSARY.md:52-61]). DATA_MODEL only constrains that signal-APPROVED must never imply exchange acceptance [VERIFIED: docs/data/DATA_MODEL.md:340].
- **Resolution:** keep both values (deleting either breaks SIGNAL_AND_ALERTS approval flow and Telegram APPROVE semantics); add an ownership note to GLOSSARY §2/§3: Signal.APPROVED = user approval observed on the signal instance; TradePlan.APPROVED = plan authorized for execution handoff; order placement reads TradePlan status; transition order Signal APPROVED → Plan APPROVED → Order PLANNED. Mirror one paragraph into SIGNAL_AND_ALERTS §1 (Signal≠plan≠order) and DATA_MODEL §3. Authority: D007 separation + D016; this is a clarification, not a value change.
- **Row:** D028.

### DOC_STATUS.md bump
Add `research/RESEARCH_PROTOCOL.md` (Stable/canonical once frozen, else "Baseline — pending freeze"), move nothing else; record the C1–C7 edit set + D022–D028 in the file's changelog line if present. CONTRACT: planner must verify DOC_STATUS lists every touched doc.

## Gate Design (registry loader + CI check, docs-only phase)

Phase boundary says no code; D-07 demands a loader + CI check that fails closed. Reconciliation (no product-code exception beyond the gate itself):

| Element | Phase 1 delivers | Deferred to Phase 3 |
|---------|-----------------|---------------------|
| Loader contract | Spec in RESEARCH_PROTOCOL §5: input (source-controlled JSON/YAML) → validated loader → canonical normalized JSON → DB registry, per CONFIGURATION §6 [VERIFIED: docs/configuration/CONFIGURATION.md:84-98]; normalization rule (numeric types + key order before hash) [VERIFIED: docs/configuration/CONFIGURATION.md:126-132] | Actual loader implementation + DB table + hash verification code |
| Parameter seed | Zero registered sets (correct: no parameter work exists yet) | First sets in Phase 4+ |
| CI check | One file `.github/workflows/research-gate.yml` — the gate, not product code | Full fixture/parity suites |

**CI check shape (fail-closed):**
```yaml
# research-gate: fails closed if the research contract is not frozen + linked
# 1. docs/research/RESEARCH_PROTOCOL.md header Status == FROZEN
#    AND a DECISIONS.md row cites the freeze version (grep D0xx + version)
# 2. every experiment/backtest record present in repo carries the identity
#    tuple (strategyVersion, parameterSetId, parameterSetHash, dataSnapshotId,
#    codeVersion, costModelHash) — missing field = non-zero exit
# 3. no strategy-parameter-looking file outside docs/research/registry/
#    (convention tripwire until the Phase-3 loader owns the path)
```
- Enforcement: workflow marked as a required status check (repo settings step in the plan); any failure blocks merge. "Rejected by gate, not by convention" = `exit 1`, not a review comment.
- **No-code-yet semantics:** with zero registered sets and zero experiment records, checks 2–3 pass vacuously and check 1 carries the gate: any parameter work attempted before the freeze flips to FROZEN is visibly unprotected, and the Phase-3 loader spec already requires `parameterSetId + parameterSetHash` on every run identity. Planner must state this explicitly so "gate passes on empty repo" is not misread as "gate is broken."

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Freeze/audit trail | Custom version footer | Header block (§0) + DECISIONS row + git history | Three independent witnesses; a footer alone is editable without trace |
| Status vocabulary | New lifecycle words | GLOSSARY enums only (C2/C5/C7) | Synonyms (`Skipped-Busy`, `OrderPlaced`) already caused C5; the no-synonyms rule exists for this |
| Acceptance numbers | Invented thresholds (e.g. "expectancy > 0.2R") | BACKTEST_SPEC "thresholds TBD" + interval reporting | Numeric gates before data are overfitting commitments; the spec deliberately defers them |
| Backtest engine | Any Python/prototype runs in this phase | Nothing — Phase 6 owns the engine; VectorBT exploratory-only later | A run now is an anecdote by definition (no frozen protocol, no registry) |
| Timezone handling | UTC+7 offsets or `Bangkok` alias | `Asia/Ho_Chi_Minh` via `zoneinfo` + `tzdata` | C4; Windows has no OS zoneinfo so the wheel is load-bearing |

**Key insight:** every hand-rolled shortcut in this phase (a threshold, a status synonym, an early backtest) destroys the exact property the phase exists to create: comparability of future evidence.

## Common Pitfalls

### Pitfall 1: Declaring a family winner (D012 violation)
**What goes wrong:** sheet language like "preferred variant" or "baseline winner" becomes a de-facto selection. **Why:** comparative adjectives read as decisions. **Avoid:** every sheet ends with a `TBD (D012)` footer; comparative statements allowed only with "pending backtest + OOS" qualifier. **Warning signs:** "best", "optimal", "chosen" anywhere in family sheets.

### Pitfall 2: Freezing numbers instead of methodology
**What goes wrong:** protocol pins ATR multipliers, RR minima,Expiry hours as frozen facts. **Why:** those are research parameters, not methodology. **Avoid:** freeze splits/cost/execution/gates + parameter *ranges-to-explore*; values live in registry sets (Phase 3+), never in the protocol.

### Pitfall 3: Silent renames during C1–C7 edits
**What goes wrong:** editor "fixes" extra terminology beyond the contradiction. **Why:** scope creep invalidates the one-row-per-contradiction audit. **Avoid:** diff review restricted to contradiction scope; anything else becomes a new DECISIONS row or is reverted.

### Pitfall 4: Gate that passes vacuously forever
**What goes wrong:** CI check written so empty-repo pass becomes permanent pass after parameter files appear. **Why:** check 3 (registry-path tripwire) omitted. **Avoid:** include the path tripwire + required-status-check setting step; Phase 3 plan must reference this gate as its acceptance criterion.

### Pitfall 5: Research-doc → protocol drift after freeze
**What goes wrong:** living draft evolves; protocol silently stale. **Why:** no one owns the sync direction. **Avoid:** protocol §0 one-way-flow paragraph (draft → versioned amendment only); DOC_STATUS bump records which research version the freeze was taken against.

### Pitfall 6: Section renumber breaking cross-references (C6)
**What goes wrong:** BACKTEST §11-gates referenced by title elsewhere; renumber orphans numeric citations. **Why:** numeric refs are brittle. **Avoid:** verification grep for `§ ?1[123]` + `section 1[123]` + `Section [89]` across `docs/` before/after; prefer titles in all new prose.

## Code Examples

Docs-only phase: no product code. Executable surface is the CI gate sketch in `## Gate Design` plus these verification commands the plans must run:

```bash
# C6: find all numeric section cross-references before renumbering
grep -rn "§ *1[123]\|section 1[123]\|Section [789]\|§ *[789]" docs/ | head -50
# C4/C1: confirm no remaining stale tokens after edits
grep -rn "Bangkok\|LIVE_AUTONOMOUS[^_]\|ORDER_PLACED\|OrderPlaced" docs/ | head -50
# Gate: protocol frozen AND freeze recorded (both must print)
grep -n "Status.*FROZEN" docs/research/RESEARCH_PROTOCOL.md
grep -n "RESEARCH_PROTOCOL\|protocol.*frozen\|frozen.*protocol" docs/DECISIONS.md
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Living research draft as contract | Frozen versioned protocol + living draft firewall | This phase (D-01/D-02) | Parameter work has an auditable baseline |
| Freeform family prose | Fixed 7-slot template + per-family sheet | This phase (D-03/D-04) | Families mutually comparable; bias analysis mandatory |
| Silent doc fixes | One DECISIONS row per contradiction + DOC_STATUS bump | This phase (D-05) | Audit trail; no rename without a decision ID |
| Convention enforcement | Registry loader + required CI check, fail-closed | This phase (D-07) → Phase 3 | Unregistered runs rejected mechanically |

**Deprecated/outdated:** nothing in this phase deprecates libraries; the only deprecation is procedural (convention-only enforcement, rejected per D-07).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ENGINEERING_PRINCIPLES §8 canonical timezone line content (grep-seen, not Read this session) | C4 | Low — DATA_PIPELINE §7 independently confirms `Asia/Ho_Chi_Minh`; plan verification grep settles it |
| A2 | CONTEXT C1–C7 backlog matches current doc contents (verified C1–C5/C7 by Read, C6 by header grep) | C1–C7 | Low — all seven confirmed against files this session |
| A3 | No outside-repo links to renumbered sections | C6 | Low — repo is greenfield, no src/ yet; verification grep covers `docs/` |
| A4 | `.github/workflows/` CI is acceptable as "gate, not product code" under the no-code boundary | Gate Design | Medium — if rejected, gate becomes pure spec doc and D-07 executable evidence slips to Phase 3; planner should confirm interpretation at plan review |

**If this table is empty:** n/a — four assumptions above need plan-time confirmation.

## Open Questions

1. **Who flips FROZEN, and when?**
   - What we know: freeze needs header + DECISIONS row + DOC_STATUS bump.
   - What's unclear: whether freeze happens inside the Phase-1 batch or as a separate review beat after family sheets land.
   - Recommendation: freeze as the last plan in the phase after a full re-read of the protocol against BACKTEST_SPEC/CONFIGURATION checklists.

2. **Registry seed directory shape**
   - What we know: CONFIGURATION §6 hybrid (JSON/YAML → loader → canonical JSON → DB).
   - What's unclear: exact Phase-1 tripwire path (`docs/research/registry/` proposed here).
   - Recommendation: planner picks the path; Phase 3 must honor it or amend via DECISIONS row.

## Environment Availability

SKIPPED — docs-only phase. No runtimes, services, or CLIs required beyond the existing markdown + git + GitHub Actions environment. No external dependencies to audit.

## Validation Architecture

Nyquist validation is enabled (config `workflow.nyquist_validation: true`), but this phase produces documents + one CI YAML, not product behavior. Adapted mapping:

### Test Framework
| Property | Value |
|----------|-------|
| Framework | GitHub Actions YAML check (research-gate) + human doc review |
| Config file | `.github/workflows/research-gate.yml` (created this phase — Wave 0 gap) |
| Quick run command | `grep -n "Status.*FROZEN" docs/research/RESEARCH_PROTOCOL.md` |
| Full suite command | Full research-gate workflow (freeze check + identity-tuple check + path tripwire) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RSCH-01 | Protocol frozen with splits/cost/execution/gates | doc-review + CI | `grep -n "Status.*FROZEN" docs/research/RESEARCH_PROTOCOL.md` | ❌ Wave 0 (protocol doc + workflow) |
| RSCH-02 | Three 7-slot family sheets, comparable, TBD-footered | doc-review | `grep -c "TBD (D012)" docs/research/families/*.md` (= 3) | ❌ Wave 0 |
| RSCH-03 | C1–C7 edits + D022–D028 rows + DOC_STATUS bump | doc-review + grep | contradiction-token greps in Code Examples | ❌ Wave 0 (rows + bump) |

### Sampling Rate
- **Per plan commit:** relevant `grep` verification from Code Examples.
- **Phase gate:** research-gate workflow green + reviewer confirms no winner declared + SPEC still TBD.

### Wave 0 Gaps
- [ ] `docs/research/RESEARCH_PROTOCOL.md` — covers RSCH-01 (Plan 1 output)
- [ ] `docs/research/families/{trend-pullback,breakout-retest,range-mr}.md` — covers RSCH-02
- [ ] `.github/workflows/research-gate.yml` — executable gate for D-07
- [ ] DECISIONS rows D022–D028 + DOC_STATUS bump — covers RSCH-03

## Security Domain

Docs-only phase; no auth, session, crypto, or input-validation surface. ASVS assessment:

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (this phase) | Deferred — approval-token binding is Phase 8; protocol must not pre-specify token formats |
| V3 Session Management | No | — |
| V4 Access Control | Partial | Required-status-check setting on research-gate workflow (who can bypass) — plan must include the repo-settings step |
| V5 Input Validation | No | — |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent protocol amendment (frozen doc edited in place) | Tampering | Header + DECISIONS row + git history triple-witness; CI checks both |
| Unregistered parameter run presented as evidence | Spoofing (of provenance) | Identity-tuple CI check, fail-closed; Phase-3 loader |

## Sources

### Primary (HIGH confidence)
- `docs/` canonical corpus read this session: TRADING_STRATEGY_RESEARCH.md (families, Q1–Q12, backlog, anti-overfitting, acceptance draft, stop conditions), TRADING_STRATEGY_SPEC.md (slot structure, TBD discipline, versioning §12), DECISIONS.md (D001–D021), GLOSSARY.md (canonical enums + no-synonyms rule), BACKTEST_SPEC.md (splits, costs, gates, uncertainty), CONFIGURATION.md (identity, hash, linkage, search rules), 00_PRODUCT_SCOPE.md (§7 modes), SIGNAL_AND_ALERTS.md (§4), EXECUTION_SPEC.md (§3), DATA_MODEL.md (§3/§6), DATA_PIPELINE.md (timezone §7, dup §8/§9), TESTING_STRATEGY.md (§8), 01_ENGINEERING_PRINCIPLES.md (timezone, via grep), SECURITY/TRADINGVIEW/BACKTEST headers (C6, via header grep)
- `.planning/` context: 01-CONTEXT.md (locked D-01–D-08), REQUIREMENTS.md (RSCH-01..03), ROADMAP.md (Phase 1 goal + success criteria), PROJECT.md, research/SUMMARY.md (Open Question 3 contradiction list — all seven confirmed)

### Secondary (MEDIUM confidence)
- None load-bearing; all structural claims verified against files above.

### Tertiary (LOW confidence)
- A1/A4 assumptions flagged in Assumptions Log for plan-time confirmation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — n/a (docs-only; no libraries). Toolchain is markdown + git + GitHub Actions.
- Architecture: HIGH — responsibility map + gate decomposition follow locked CONTEXT + Phase 2/3 downstream contracts.
- Pitfalls: HIGH — grounded in AGENTS.md constraints + SPEC TBD-discipline + D012/D013.

**Research date:** 2026-09-19
**Valid until:** 30 days (stable docs domain; re-verify only if Core Docs v0.3 changes)
