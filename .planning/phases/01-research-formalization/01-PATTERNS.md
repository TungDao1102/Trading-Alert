# Phase 1: Research Formalization — Pattern Map

**Mapped:** 2026-09-19
**Files analyzed:** 18 (5 new + 13 modified)
**Analogs found:** 13 with format analogs / 18 (5 new files reuse existing-doc structures; the YAML gate has no in-repo analog and references GitHub Actions schema conventions)

## Phase Context (docs-only, greenfield)

This is a **documents-and-gates-only** phase (CONTEXT D-01..D-08). There is no `src/`, no database, no product code in this repo — the working material is the `docs/` corpus (27 markdown files, Core Docs v0.3) plus one new CI YAML. There are NO codebase analogs for source code. Format analogs below cite the closest existing doc whose role / structure the new file should mirror. For in-place edits, the analog is the file's own existing structure (the edit preserves that structure).

Doc-role / doc-data-flow vocabulary used in the table:

| Doc role | Doc data flow |
|----------|---------------|
| `frozen-protocol` | canonical methodology contract; versioned + freezable |
| `family-spec-sheet` | per-family hypothesis + variants + backtest path |
| `ci-gate-yaml` | fail-closed GitHub Actions check (the gate, not product code) |
| `decision-log` | append-only architectural/strategy decision rows |
| `status-index` | additive bump of a doc into a stable/living/blocked bucket |
| `in-place-correction` | targeted edit preserving the doc's existing purpose (resolves a contradiction) |
| `section-renumber` | mechanical numeric renumber; zero semantic change |
| `mirror-note` | adds a clarifying paragraph; no enum-value change |

## File Classification

| # | New/Modified File | Doc Role | Doc Data Flow | Closest Format Analog | Match Quality |
|---|-------------------|----------|---------------|-----------------------|---------------|
| 1 | `docs/research/RESEARCH_PROTOCOL.md` *(new)* | frozen-protocol | protocol-spec (canonical, freezable) | `docs/backtest/BACKTEST_SPEC.md` (§1-§13 methodology spec, gates at end, "TBD until exercised" footer pattern) | exact (same doc role: methodology contract with acceptance gates) |
| 2 | `docs/research/families/trend-pullback.md` *(new)* | family-spec-sheet | hypothesis-spec (TBD-footered) | `docs/strategy/TRADING_STRATEGY_SPEC.md` (TBD slot template + status banner + §13 acceptance status footer) | exact (same TBD-slot structure) |
| 3 | `docs/research/families/breakout-retest.md` *(new)* | family-spec-sheet | hypothesis-spec (TBD-footered) | `docs/strategy/TRADING_STRATEGY_SPEC.md` | exact |
| 4 | `docs/research/families/range-mr.md` *(new)* | family-spec-sheet | hypothesis-spec (TBD-footered) | `docs/strategy/TRADING_STRATEGY_SPEC.md` | exact |
| 5 | `.github/workflows/research-gate.yml` *(new — no in-repo analog)* | ci-gate-yaml | gate-config (fail-closed check) | none — greenfield (`.github/` directory does not exist in repo; format reference: GitHub Actions YAML schema for `on:` + `jobs:` shape — no in-repo prior art) | analog: none — greenfield |
| 6 | `docs/DECISIONS.md` *(modified)* | decision-log | append-row | self — preserve existing 4-column row format | self |
| 7 | `docs/DOC_STATUS.md` *(modified)* | status-index | additive-bump | self — preserve existing section headers (Stable / Living / Blocked / Baseline / Integrations / Operations / Implementation) | self |
| 8 | `docs/00_PRODUCT_SCOPE.md` *(modified, C1)* | scope-doc | in-place-correction | self — preserve §7 "Operating modes" list, replace list with GLOSSARY §8 verbatim | self |
| 9 | `docs/trading/SIGNAL_AND_ALERTS.md` *(modified, C2 + C7)* | signal-doc | in-place-correction + mirror-note | self — preserve §1 signal-not-order framing (C7 mirror); trim §4 enum list to GLOSSARY §2 8 values (C2) | self |
| 10 | `docs/trading/EXECUTION_SPEC.md` *(modified, C3)* | execution-doc | in-place-correction | self — preserve §3 lifecycle diagram, remove `APPROVED` node, add cross-ref to GLOSSARY §5 + approval ownership note | self |
| 11 | `docs/testing/TESTING_STRATEGY.md` *(modified, C3)* | testing-doc | in-place-correction | self — preserve §8 invalid-transition example, re-name owning machine so the example no longer implies OrderStatus.APPROVED | self |
| 12 | `docs/research/TRADING_STRATEGY_RESEARCH.md` *(modified, C4 + C5 + C6)* | research-draft | in-place-correction + section-renumber | self — preserve Vietnamese/English voice, fix §9.3 timezone (C4), rewrite §12 state names to canonical (C5), renumber trailing duplicate `# 13.` and `## 14.` to next-free numbers (C6) | self |
| 13 | `docs/GLOSSARY.md` *(modified, C7)* | glossary-doc | mirror-note | self — preserve canonical enums (§2 SignalStatus / §3 TradePlanStatus), add ownership clarification paragraph between/within those sections | self |
| 14 | `docs/data/DATA_MODEL.md` *(modified, C7)* | data-model-doc | mirror-note | self — preserve §3 state-machine separation rule, append one sentence mirroring the ownership clarification | self |
| 15 | `docs/backtest/BACKTEST_SPEC.md` *(modified, C6)* | backtest-spec-doc | section-renumber | self — preserve all titles + content; renumber duplicate `## 11. Acceptance gates` → `## 12` and verify the "Acceptance gates" title (referenced by title elsewhere) is kept | self |
| 16 | `docs/architecture/DATA_PIPELINE.md` *(modified, C6)* | data-pipeline-doc | section-renumber | self — preserve all content; renumber trailing `## 8. Storage architecture` → `## 13`, `## 9. Python implementation rule` → `## 14` | self |
| 17 | `docs/integration/TRADINGVIEW.md` *(modified, C6)* | integration-doc | section-renumber | self — preserve all content; renumber `## 8. Python webhook adapter` → `## 7` | self |
| 18 | `docs/operations/SECURITY_AND_OPERATIONS.md` *(modified, C6)* | security-ops-doc | section-renumber | self — preserve all content; renumber `## 11. Python runtime operations` → `## 10` | self |

## Pattern Assignments

### 1. `docs/research/RESEARCH_PROTOCOL.md` *(new)* — frozen-protocol / protocol-spec

**Analog:** `docs/backtest/BACKTEST_SPEC.md` (closest in-repo methodology contract: numbered sections §1-§13, acceptance criteria at end, explicit "TBD until exercised" reservation on numerical thresholds).

**Status-banner pattern** (BACKTEST_SPEC implicit; TRADING_STRATEGY_SPEC.md lines 3-5 explicit):
```
# <Title>

> **Protocol version:** v1.0.0
> **Status:** FROZEN | DRAFT
> **Frozen on:** YYYY-MM-DD (DECISIONS row, e.g. D029)
> **Supersedes:** (none | v0.x.y + migration note)

> Status vocabulary is binary: `DRAFT` or `FROZEN`. No "provisional"/"baseline" qualifiers.
```
Source: `docs/strategy/TRADING_STRATEGY_SPEC.md:3-5`
```
> Status: TEMPLATE — **NOT FROZEN**
>
> This file becomes implementation-authoritative only after the research gates pass.
```

**Numbered-section methodology pattern** (BACKTEST_SPEC §1-§13 layout, copy verbatim-equivalent for §1-§6 of RESEARCH_PROTOCOL):
- §1 = Purpose
- §2 = Source/Inputs
- §3 = Decision rules
- §4 = Edge cases / ambiguous inputs
- §5 = Costs / fees / funding
- §6 = Configuration identity
- ...
- (final) = Acceptance methodology + "Exact numerical acceptance thresholds remain `TBD` until the research methodology is exercised on real data."

Source: `docs/backtest/BACKTEST_SPEC.md:1-156` (full file, especially §7 Dataset splits lines 52-64, §8 Walk-forward lines 66-74, §10 Statistical power lines 87-109, §10.1 Research universe lines 111-119, §11 Acceptance gates lines 136-151, §13 Research implementation lines 154-156).

**Cross-reference convention** — point back to source docs that own the section (do NOT duplicate methodology):
> See `backtest/BACKTEST_SPEC.md` §7 for the full split discipline; this protocol only restates the operative rule.

**Living-doc firewall paragraph (§0)** — required by D-02 (protocol docs explicit "draft → frozen → amendment via version bump" rule). Pattern language:
> New learnings go to `research/TRADING_STRATEGY_RESEARCH.md` first. They enter this protocol only via a versioned amendment (`v1.1.0` clarification, `v2.0.0` semantic change). The header `Status: FROZEN` + a matching DECISIONS.md row + git history are three independent witnesses; all three must agree for the freeze to be effective.

**Frozen = three-witness rule** (RESEARCH.md `## Freeze Mechanics`):
1. Header block `Status: FROZEN` + `Frozen on` date filled.
2. New DECISIONS.md row recording the freeze (e.g. D029 "Research protocol v1.0.0 frozen").
3. DOC_STATUS.md adds the file under **Stable / canonical**.

CI gate (file 5) requires all three to be present; any one missing fails closed.

---

### 2-4. `docs/research/families/{trend-pullback,breakout-retest,range-mr}.md` *(new)* — family-spec-sheet / hypothesis-spec

**Analog:** `docs/strategy/TRADING_STRATEGY_SPEC.md` (TBD-slot template; same `TBD` discipline; same acceptance-status footer pattern).

**Status banner** (copy format from TRADING_STRATEGY_SPEC.md lines 3-5):
```
# <Family name>

> Status: HYPOTHESIS — **NOT FROZEN**
>
> Values remain `TBD` until the research methodology is exercised on real data.
```

**Fixed 7-slot template per concept** (D-03, D-04 — every family uses the same slots, so sheets are mutually comparable):
1. Informal definition (prose hypothesis)
2. Machine-detectable definition (composable rules on closed bars only)
3. Alternative definitions (competing variants to test, never blended)
4. Advantages / disadvantages (incl. entry-quality metrics: fill rate, missed-trade rate, slippage, MFE/MAE)
5. Look-ahead-bias analysis (swing lookback L/R, confirmation timing, no unclosed pivots, no repaint)
6. Testable parameters (link to CONFIGURATION §3 list)
7. Backtest path (research backlog pointers)

**Per-family sheet sections** (one page, same cosmetics across families):
- Hypothesis (one sentence)
- Timeframe mapping (`4H → regime / 1H → setup`; 15M optional; 1m execution-sim only)
- Variants table (A1-A4 / B-alternatives / C-filter states)
- Entry / SL / TP method codes (E1-E4, S1-S3, T1-T3) — cross-reference the source definitions in `research/TRADING_STRATEGY_RESEARCH.md:415-522`
- Open questions pointing at Q1-Q12 — source: `research/TRADING_STRATEGY_RESEARCH.md:880-964`
- **Mandatory footer (D-08, blocks D012 violation):** `> V1 family selection: TBD (D012)`

**D012 / Pitfall-1 guards** — sheets must NOT contain "preferred", "optimal", "chosen", "best" unless qualified with "pending backtest + OOS". Comparative adjectives are de-facto winner declarations.

**TBD discipline** — copy from TRADING_STRATEGY_SPEC.md lines 9-13:
```
- Strategy ID: `TBD`
- Strategy version: `TBD`
- Direction: `LONG`, `SHORT`, or both — `TBD`
- Primary timeframes: `TBD`
- Supported symbols: `TBD`
```

**Source material citations** (each slot must cite its source by section/line, not invent content):
- Family A — `docs/research/TRADING_STRATEGY_RESEARCH.md:320-345` (idea + variants A1-A4) + `:880-886` (Q1) + `:1123-1133` (P0 backlog)
- Family B — `docs/research/TRADING_STRATEGY_RESEARCH.md:349-382` + `:239-312` (B1-B4 + retest seq) + `:899-933` (Q3-Q8)
- Family C — `docs/research/TRADING_STRATEGY_RESEARCH.md:386-405` + `:219-227` (range definition) + `:489-522` (T1-T3 + NO_TRADE rule) + `:858-870` (regime filter + dataset gate)

---

### 5. `.github/workflows/research-gate.yml` *(new)* — ci-gate-yaml / gate-config

**Analog:** none — greenfield (`.github/` directory does not exist in repo; `git ls-files -- .github/` returns empty).

**Format reference:** Standard GitHub Actions YAML schema for `on:` triggers + `jobs.<id>.steps[]` shape. No in-repo prior art; pattern is dictated by GitHub Actions documentation, not by project files.

**Fail-closed shape** (verbatim from RESEARCH.md `## Gate Design`):
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

**Required-status-check setting** (RESEARCH.md Pitfall-4 guard): the workflow must be marked as a required status check at repo-settings level so a failure blocks merge. The repo-settings step is *plan content*, not workflow content — planner must include it explicitly.

**Empty-repo semantics** (must be stated in plan to prevent "gate is broken" misread):
- Check 1 carries the gate on an empty repo (status + DECISIONS row + DOC_STATUS bump = the three-witness freeze).
- Checks 2-3 pass vacuously (no experiment records yet, no parameter files outside the tripwire path).
- Phase 3 plan must reference this workflow as its acceptance criterion (so the loader is built against an already-green gate, not added later).

**No-code-yet justification** (RESEARCH.md A4 assumption): "CI YAML as gate, not product code" is the explicit exception to the phase's docs-only boundary. If a reviewer rejects this interpretation, the gate becomes pure spec and D-07 executable evidence slips to Phase 3.

---

### 6. `docs/DECISIONS.md` *(modified, D022-D028)* — decision-log / append-row

**Analog:** self — preserve existing 4-column table format (ID | Decision | Status | Rationale).

**Current format source** (`docs/DECISIONS.md:3-26`):
```
| ID    | Decision                          | Status | Rationale |
|-------|-----------------------------------|--------|-----------|
| D001  | No AI/LLM in trading decision core| Accepted | Deterministic, reproducible, ... |
...
| D021  | `pyproject.toml` + `uv` ...       | Accepted | Reproducible environments, ...   |
```

**Append pattern** — add D022-D028 as new rows below D021, preserving pipe-table alignment. Use `Accepted` for contradictions now resolved by this phase (D022-D028); C1-C7 are already-accepted decisions at the time of writing this row, not provisional.

**Per-row content** (verbatim from RESEARCH.md `## C1–C7 Resolution Approaches`):
- **D022** — SystemMode canonical list = GLOSSARY §8; scope §7 aligned. (C1)
- **D023** — `SIGNAL_AND_ALERTS.md` §4 trimmed to canonical 8 SignalStatus values; ORDER_PLACED/FILLED/CLOSED moved to lifecycle cross-reference. (C2)
- **D024** — `EXECUTION_SPEC.md` §3 OrderStatus chain drops `APPROVED`; approval ownership moved to SignalStatus.APPROVED / TradePlanStatus.APPROVED. (C3)
- **D025** — Canonical timezone = `Asia/Ho_Chi_Minh`; research §9.3 / DATA_PIPELINE / ENGINEERING_PRINCIPLES §8 agree; Windows-`tzdata` wheel required. (C4)
- **D026** — research §12 status names rewritten to canonical SignalStatus / OrderStatus / TradeStatus / PositionStatus / ApprovalAction enums (no-synonyms rule per GLOSSARY:141). (C5)
- **D027** — Section-numbering normalization batch (C6): BACKTEST_SPEC §11-gates → §12; DATA_PIPELINE trailing §8/§9 → §13/§14; TRADINGVIEW §8 → §7; SECURITY §11 → §10; research `# 13. Research stop conditions` → `# 25`, `## 14. Statistical uncertainty questions` → `## 26`.
- **D028** — SignalStatus.APPROVED vs TradePlanStatus.APPROVED ownership clarification (both kept, ownership paragraph added to GLOSSARY §2/§3 + mirrors in SIGNAL_AND_ALERTS §1 and DATA_MODEL §3). (C7)

**Pre-existing D-rows unchanged** — D001-D021 must remain untouched (D-05: pure additive append for the contradiction set).

---

### 7. `docs/DOC_STATUS.md` *(modified)* — status-index / additive-bump

**Analog:** self — preserve existing section headers (Stable / Living / Blocked / Baseline / Integrations / Operations / Implementation).

**Current sections** (`docs/DOC_STATUS.md:3-46`):
- `## Stable / canonical` (lines 3-12)
- `## Living research` (lines 14-16)
- `## Blocked until strategy freeze` (lines 18-20)
- `## Baseline architecture/specification` (lines 22-30)
- `## Integrations` (lines 32-36)
- `## Operations` (lines 38-41)
- `## Implementation` (lines 43-46)

**Additions** (verbatim from RESEARCH.md `## DOC_STATUS.md bump`):
- Add `research/RESEARCH_PROTOCOL.md` under **Stable / canonical** *once frozen*; otherwise `Baseline — pending freeze` is acceptable as a transitional state (planner choice — D-08 prefers listing it under Stable immediately with a footnote line).
- Nothing else moves.
- The C1-C7 edits are recorded in a one-line changelog annotation under the affected docs (e.g. `/* C1–C7 resolved per D022–D028 */` inline note), or skipped entirely if the project conventions don't carry doc-level changelogs — current DOC_STATUS.md has no changelog convention, so default is **no changelog line**, only the DECISIONS rows audit.

**Verification grep** (RESEARCH.md `## Common Pitfalls` Pitfall 6): after edit, planner must verify every doc still appears under its expected section.

---

### 8. `docs/00_PRODUCT_SCOPE.md` *(modified, C1)* — scope-doc / in-place-correction

**Analog:** self — preserve §7 "Operating modes" purpose (defines the runnable SystemModes a V1 product may be in).

**Current §7** (`docs/00_PRODUCT_SCOPE.md:92-98`):
```
## 7. Operating modes

1. `RESEARCH`
2. `BACKTEST`
3. `PAPER`
4. `LIVE_APPROVAL`
5. `LIVE_AUTONOMOUS` — future only, disabled by default and requiring explicit evidence/gates.
```

**Target replacement** (verbatim from GLOSSARY §8, `docs/GLOSSARY.md:109-120`):
```
## 7. Operating modes

Canonical list is in `GLOSSARY.md` §8. As of D022 the operative set is:

1. `RESEARCH`
2. `BACKTEST`
3. `PAPER`
4. `LIVE_APPROVAL`
5. `SAFE_MODE`
6. `LIVE_AUTONOMOUS_DISABLED` — future architecture mode; disabled by default; requires explicit evidence/gates.
```

**Authority citation** (RESEARCH.md C1): D016 (GLOSSARY is sole terminology truth, `docs/DECISIONS.md:20`) outranks product scope.

**No-synonyms check** — the new list contains zero synonyms; every name is one of the canonical six. `LIVE_AUTONOMOUS` (the unqualified name) is removed from §7 entirely.

---

### 9. `docs/trading/SIGNAL_AND_ALERTS.md` *(modified, C2 + C7)* — signal-doc / in-place-correction + mirror-note

**Analog:** self — preserve §1 "Signal is not an order" framing + the signal/plan/order three-way separation rule.

**Current §4 enum (C2)** (`docs/trading/SIGNAL_AND_ALERTS.md:61-75`):
```
## 4. Alert states

```text
DETECTED
NOTIFIED
VIEWED
APPROVED
SKIPPED_USER
SKIPPED_BUSY
EXPIRED
INVALIDATED
ORDER_PLACED
FILLED
CLOSED
```
```

**Target replacement** (verbatim from GLOSSARY §2, `docs/GLOSSARY.md:37-50`, plus a cross-reference):
```
## 4. Signal states (canonical)

Canonical enum is in `GLOSSARY.md` §2. As of D023:

```text
DETECTED
NOTIFIED
VIEWED
APPROVED
SKIPPED_USER
SKIPPED_BUSY
EXPIRED
INVALIDATED
```

Execution-lifecycle states (`ORDER_PLACED`, `FILLED`, `CLOSED`) belong in `OrderStatus` / `TradeStatus` (§5 / §6 of `GLOSSARY.md`), not here. See `data/DATA_MODEL.md` §3 for the state-machine separation rule.
```

**Section rename guard**: `Alert states` → `Signal states (canonical)` (kills the alert/signal conflation; RESEARCH.md C2 resolution).

**C7 mirror in §1** (RESEARCH.md C7 resolution: mirror one paragraph):
Append to `## 1. Signal is not an order`:
```
A signal reaching `APPROVED` means the user approved the signal instance, not a trade plan and not an order. Plan-level approval is `TradePlanStatus.APPROVED` (see `GLOSSARY.md` §3). Order placement reads TradePlan status; the transition is `Signal.APPROVED → TradePlan.APPROVED → Order.PLANNED`.
```

---

### 10. `docs/trading/EXECUTION_SPEC.md` *(modified, C3)* — execution-doc / in-place-correction

**Analog:** self — preserve §3 lifecycle diagram purpose (entry order lifecycle, PLANNED → SUBMITTING → NEW → ...).

**Current §3** (`docs/trading/EXECUTION_SPEC.md:39-53`):
```
## 3. Entry order lifecycle

```text
PLANNED
  ↓
APPROVED
  ↓
SUBMITTING
  ↓
NEW
  ├→ PARTIALLY_FILLED
  ├→ FILLED
  ├→ CANCELED
  └→ EXPIRED
```
```

**Target replacement** (C3 resolution: delete `APPROVED` node, add ownership note):
```
## 3. Entry order lifecycle

```text
PLANNED
  ↓
SUBMITTING
  ↓
NEW
  ├→ PARTIALLY_FILLED
  ├→ FILLED
  ├→ CANCELED
  └→ EXPIRED
```

An order enters `PLANNED` only after plan approval (`TradePlanStatus.APPROVED`). The order chain itself has no `APPROVED` state; approval lives upstream at the signal/plan level (`GLOSSARY.md` §2 / §3, `data/DATA_MODEL.md` §3). See D024.
```

**Cross-reference required** to GLOSSARY §5 (canonical OrderStatus, `docs/GLOSSARY.md:75-87`) — the chain shown above must match the canonical enum exactly (note: §5 also includes `REJECTED` and `UNKNOWN`; those are reachable states via reconciliation, not shown in the happy-path diagram — preserve the current diagram's level of detail, do not bloat it).

---

### 11. `docs/testing/TESTING_STRATEGY.md` *(modified, C3)* — testing-doc / in-place-correction

**Analog:** self — preserve §8 "State-machine tests" purpose (invalid-transition examples that exercise the state machine without implying the wrong owner).

**Current §8** (`docs/testing/TESTING_STRATEGY.md:107-117`):
```
## 8. State-machine tests

At minimum validate invalid transitions such as:

```text
EXPIRED → APPROVED
CANCELED → FILLED
CLOSED → NEW PROTECTIVE ORDER
```

unless an explicit reconciliation workflow authorizes the transition.
```

**Target replacement** (C3 resolution: re-name the owning machine so the example no longer implies `OrderStatus.APPROVED`):
```
## 8. State-machine tests

At minimum validate invalid transitions such as:

```text
SignalStatus.EXPIRED     → SignalStatus.APPROVED
OrderStatus.CANCELED     → OrderStatus.FILLED
TradeStatus.CLOSED       → OrderStatus.NEW (protective order)
```

unless an explicit reconciliation workflow authorizes the transition. Approval lives in the SignalStatus / TradePlanStatus machines (per `GLOSSARY.md` §2 / §3 and `data/DATA_MODEL.md` §3); the OrderStatus machine has no `APPROVED` state (see D024).
```

**Why three examples need re-naming** — the original `EXPIRED → APPROVED` example could be read as an OrderStatus transition; renaming it to `SignalStatus.EXPIRED → SignalStatus.APPROVED` makes the invalid transition concrete (Signal cannot become Approved after Expiry) and prevents the same misread recurring.

---

### 12. `docs/research/TRADING_STRATEGY_RESEARCH.md` *(modified, C4 + C5 + C6)* — research-draft / in-place-correction + section-renumber

**Analog:** self — preserve the Vietnamese/English voice (this is the living research draft).

**C4 edit (§9.3 Time standard)** — `docs/research/TRADING_STRATEGY_RESEARCH.md:647-651`:
```
## 9.3. Time standard

- DB: UTC.
- UI/Telegram: convert sang Asia/Bangkok (UTC+7) khi cần.
```
Replace `Asia/Bangkok (UTC+7)` with `Asia/Ho_Chi_Minh` (per `docs/01_ENGINEERING_PRINCIPLES.md:81` — "Convert to Asia/Ho_Chi_Minh only in presentation"). Add Windows-`tzdata` note (one sentence) if absent — Windows lacks OS zoneinfo so the wheel is load-bearing per STACK.md and RESEARCH.md C4.

**C5 edit (§12 System Performance vs User Performance)** — `docs/research/TRADING_STRATEGY_RESEARCH.md:746-771`:
```
Mỗi signal cần có trạng thái:

```text
Generated
Approved
SKIPPED_USER
Skipped-Busy
Expired
Invalidated
```

Nếu được approve:

```text
OrderPlaced
PartiallyFilled
Filled
Canceled
TP
SL
ManualExit
```
```
Replace the first block (signal states) with canonical `SignalStatus` (`docs/GLOSSARY.md:37-48`): `DETECTED, NOTIFIED, VIEWED, APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED`. Replace the second block (order/exit states) with canonical `OrderStatus` + `TradeStatus` (`docs/GLOSSARY.md:75-97`): `PLANNED, SUBMITTING, NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, UNKNOWN` + `PENDING, OPEN, CLOSED, ABORTED, UNKNOWN`. The `Generated` / `OrderPlaced` / `TP` / `SL` / `ManualExit` / `Skipped-Busy` synonyms are banned by GLOSSARY:141. Preserve the section's two performance tables + four timestamps (SignalTime / ApproveTime / OrderTime / FillTime) — that content is canonical, only the join vocabulary changes.

**C6 renumber** — `docs/research/TRADING_STRATEGY_RESEARCH.md:1249-1262` and `:1264-1273`:
- `# 13. Research stop conditions` (line 1249) → `# 25. Research stop conditions` (next-free after the appended-block rule: last numbered top section is `# 24. References` at line 1203, so next free is `# 25`).
- `## 14. Statistical uncertainty questions` (line 1264) → `## 26. Statistical uncertainty questions` (sibling of `# 25`, same numbering).
- Original owners keep their numbers: `# 13. Signal validity` (line 796) and `# 14. Candidate Research Plan` (line 829) are unchanged.

**Cross-reference risk (Pitfall 6)** — RESEARCH.md flagged: any other doc referencing "section 13" or "section 14" of the research doc may break. Verification grep before/after:
```
grep -rn "research.*§\?1[34]\|research.*section 1[34]" docs/
```
If matches found, switch references to titles ("Signal validity" / "Research stop conditions") not numbers. Planner must include this verification step explicitly.

---

### 13. `docs/GLOSSARY.md` *(modified, C7)* — glossary-doc / mirror-note

**Analog:** self — preserve canonical enums (§2 SignalStatus, §3 TradePlanStatus) byte-equivalent; add an ownership paragraph.

**Edit insertion point** — between §3 (`## 3. Canonical TradePlanStatus`) and §4 (`## 4. Canonical ApprovalAction`), or appended to §2/§3 as a closing paragraph. Preferred location: append one paragraph to §2 (SignalStatus), one to §3 (TradePlanStatus), with identical wording:

```
**Ownership note (D028):** `APPROVED` appears in both `SignalStatus` and `TradePlanStatus`. They are distinct values, not synonyms:
- `SignalStatus.APPROVED` = user approval observed on the signal instance.
- `TradePlanStatus.APPROVED` = trade plan authorized for execution handoff.

Order placement reads `TradePlanStatus`; the transition order is `Signal.APPROVED → TradePlan.APPROVED → Order.PLANNED`. Do not collapse these into a single approval state.
```

**No enum-value change** — D-06 / D028 specifically: "this is a clarification, not a value change". The 8 SignalStatus values and 6 TradePlanStatus values stay byte-equivalent.

**Authority citation** (RESEARCH.md C7): D007 (separation) + D016 (terminology authority). Reference both rows by ID in the paragraph so the audit trail is in-line.

---

### 14. `docs/data/DATA_MODEL.md` *(modified, C7)* — data-model-doc / mirror-note

**Analog:** self — preserve §3 state-machine separation rule byte-equivalent; add a sentence mirroring the GLOSSARY §2/§3 ownership clarification.

**Edit insertion point** — after `docs/data/DATA_MODEL.md:338-340`:
```
Domain separation is mandatory:

```text
SignalStatus       ≠ OrderStatus ≠ PositionStatus ≠ ApprovalAction
```

A signal reaching `APPROVED` must never imply that an order was accepted by Binance.
```

Append one sentence:
```
A signal reaching `SignalStatus.APPROVED` represents user approval on the signal instance; plan-level approval is `TradePlanStatus.APPROVED` and is the value order placement reads. See `GLOSSARY.md` §2 / §3 (D028) for the ownership distinction.
```

**No entity / no field change** — pure documentation mirror; DATA_MODEL.md §2 (entities) and §4 (relationships) untouched.

---

### 15. `docs/backtest/BACKTEST_SPEC.md` *(modified, C6)* — backtest-spec-doc / section-renumber

**Analog:** self — preserve all section titles + content; renumber only the duplicate `## 11.` and the missing `## 12.`.

**Current duplicate numbering** (`docs/backtest/BACKTEST_SPEC.md:121, 136`):
- Line 121: `## 11. Experiment record`
- Line 136: `## 11. Acceptance gates`
- Line 154: `## 13. Research implementation` (missing `## 12.`)

**Target renumber** (RESEARCH.md C6):
- `## 11. Experiment record` → stays `## 11. Experiment record` (owner of the §11 slot).
- `## 11. Acceptance gates` → `## 12. Acceptance gates` (keeps the title — referenced by title elsewhere per scope §9 + ROADMAP, RESEARCH.md Pitfall 6).
- `## 13. Research implementation` → stays `## 13. Research implementation` (no change to title; the gap between §12 and §13 is now correctly filled).

**Verification step (Pitfall 6)** — grep before/after for numeric citations:
```
grep -rn "BACKTEST_SPEC.*§\?1[123]\|backtest.*section 1[123]" docs/
```
External references may have used "BACKTEST_SPEC §11" meaning the gates section; if any are found, update to "BACKTEST_SPEC §12 Acceptance gates" (title-based) and never "§11" alone. Source: BACKTEST_SPEC.md is referenced from `00_PRODUCT_SCOPE.md:115` ("validation gates in `backtest/BACKTEST_SPEC.md`") — by title, safe.

---

### 16. `docs/architecture/DATA_PIPELINE.md` *(modified, C6)* — data-pipeline-doc / section-renumber

**Analog:** self — preserve all content; renumber the two trailing duplicate-numbered sections only.

**Current trailing duplicates** (`docs/architecture/DATA_PIPELINE.md:144, 162`):
- After `## 12. Phase-0 data acquisition` (line 138), the file jumps to:
- Line 144: `## 8. Storage architecture`
- Line 162: `## 9. Python implementation rule`

**Target renumber** (RESEARCH.md C6):
- `## 8. Storage architecture` → `## 13. Storage architecture` (next-free after §12).
- `## 9. Python implementation rule` → `## 14. Python implementation rule` (sibling of §13).

**No content change** — both sections stay byte-equivalent. The body of each section (including the storage-architecture diagram and the SDK-leakage rule) is preserved verbatim.

---

### 17. `docs/integration/TRADINGVIEW.md` *(modified, C6)* — integration-doc / section-renumber

**Analog:** self — preserve all content; renumber only the trailing `## 8.`.

**Current** (`docs/integration/TRADINGVIEW.md:46`):
- After `## 6. Alert-copy caveat` (line 41), file jumps to:
- Line 46: `## 8. Python webhook adapter` (missing §7).

**Target renumber** (RESEARCH.md C6):
- `## 8. Python webhook adapter` → `## 7. Python webhook adapter`.

**No content change** — title + body preserved verbatim.

---

### 18. `docs/operations/SECURITY_AND_OPERATIONS.md` *(modified, C6)* — security-ops-doc / section-renumber

**Analog:** self — preserve all content; renumber only the trailing `## 11.`.

**Current** (`docs/operations/SECURITY_AND_OPERATIONS.md:112`):
- After `## 9. Backup and restore` (line 98), file jumps to:
- Line 112: `## 11. Python runtime operations` (missing §10).

**Target renumber** (RESEARCH.md C6):
- `## 11. Python runtime operations` → `## 10. Python runtime operations`.

**No content change** — title + body preserved verbatim.

---

## Shared Patterns

### Authority chain (cross-cutting, applies to every C1-C7 edit)

Per D-06 (`docs/01-CONTEXT.md:24`):

```
DECISIONS.md
  > product scope (00_PRODUCT_SCOPE.md)
  > engineering principles (01_ENGINEERING_PRINCIPLES.md)
  > GLOSSARY
  > frozen SPEC (strategy/TRADING_STRATEGY_SPEC.md once frozen)
  > supporting specs (backtest, trading, configuration, data, integration, operations)
  > research notes (research/TRADING_STRATEGY_RESEARCH.md)
```

**Apply to:** all C1-C7 edits. C1 (SystemMode), C2 (SignalStatus), C3 (OrderStatus), C5 (status names), C7 (SignalStatus vs TradePlanStatus ownership) — GLOSSARY is the operative source of truth, downstream docs align to it. C4 (timezone) — ENGINEERING_PRINCIPLES §8 + DATA_PIPELINE §7 outrank research notes. C6 (renumber) — pure mechanical, no authority dispute.

### Three-witness freeze (cross-cutting, applies to RESEARCH_PROTOCOL.md + DOC_STATUS.md + DECISIONS.md)

```
1. Header block "Status: FROZEN" + Frozen-on date           (file #1, the protocol doc itself)
2. DECISIONS.md row (e.g. D029 "Research protocol v1.0.0 frozen")  (file #6)
3. DOC_STATUS.md lists the file under "Stable / canonical"  (file #7)
```

**Apply to:** the freeze beat at end of phase. All three must be present before the CI gate (file 5) turns green on check 1. Any one missing → check 1 fails closed.

### TBD discipline (cross-cutting, applies to family sheets + frozen-protocol)

```
- TBD means TBD, not "we'll figure it out later"
- "TBD" is always uppercase in these docs
- TBD never becomes a chosen value without a DECISIONS row + OOS evidence
- A backtest run against a TBD slot is invalid by construction
```

**Source pattern:** `docs/strategy/TRADING_STRATEGY_SPEC.md:9-13` (TBD slot pattern) + `docs/backtest/BACKTEST_SPEC.md:151` ("Exact numerical acceptance thresholds remain `TBD` until the research methodology is exercised on real data.").

**Apply to:** all 3 family sheets + every "TBD until exercised on real data" reservation in RESEARCH_PROTOCOL.md (numerical acceptance thresholds; cost-model numbers; cost calibration from live data).

### No-synonyms (cross-cutting, applies to every C1-C7 status rename)

```
Do not create synonyms such as `Skipped-User`, `USER_SKIPPED`, and `SKIPPED_USER` in different modules. Use the canonical enum names above.
```

**Source:** `docs/GLOSSARY.md:141` (last paragraph of §9 rejection reasons).

**Apply to:** C2 trim (§4 SIGNAL_AND_ALERTS), C5 rewrite (§12 research doc), C1 alignment (§7 scope). The audit grep after each edit must find zero non-canonical status tokens:
```
grep -rn "Bangkok\|LIVE_AUTONOMOUS[^_]\|ORDER_PLACED\|OrderPlaced\|Skipped-Busy\|Generated\b\|Filled\b" docs/ | head -50
```

### Verification grep suite (cross-cutting, applies to the entire phase)

Per RESEARCH.md `## Code Examples` — three greps must pass at phase gate:

```bash
# C6: find all numeric section cross-references before renumbering
grep -rn "§ *1[123]\|section 1[123]\|Section [789]\|§ *[789]" docs/ | head -50

# C4/C1: confirm no remaining stale tokens after edits
grep -rn "Bangkok\|LIVE_AUTONOMOUS[^_]\|ORDER_PLACED\|OrderPlaced" docs/ | head -50

# Gate: protocol frozen AND freeze recorded (both must print)
grep -n "Status.*FROZEN" docs/research/RESEARCH_PROTOCOL.md
grep -n "RESEARCH_PROTOCOL\|protocol.*frozen\|frozen.*protocol" docs/DECISIONS.md
```

**Apply to:** every plan in the phase. The first grep is run *before* any C6 renumber (to find cross-refs that need to be title-based); the second and third are run *after* every C1/C2/C4/C5 edit and after the freeze beat respectively.

---

## No Analog Found

| File | Doc Role | Doc Data Flow | Reason |
|------|----------|---------------|--------|
| `.github/workflows/research-gate.yml` | ci-gate-yaml | gate-config (fail-closed) | Greenfield — `.github/` directory does not exist in repo; `git ls-files -- .github/` returns empty. Format reference is GitHub Actions YAML schema (external), not any in-repo prior art. |

All other 17 files (5 new + 13 modified) have a clear format analog — either an existing doc with the same role (for the 4 new docs that mirror methodology/slot conventions) or the file's own existing structure (for the 13 in-place edits).

---

## Metadata

**Analog search scope:** `docs/**/*.md` (27 files in Core Docs v0.3) + `.planning/**/*.md` (planning context) + `.github/` (returned empty — greenfield).

**Files scanned:** 27 docs + 2 planning inputs (CONTEXT.md, RESEARCH.md).

**Tracked-source verification:** All cited format analogs (`docs/backtest/BACKTEST_SPEC.md`, `docs/strategy/TRADING_STRATEGY_SPEC.md`, `docs/DECISIONS.md`, `docs/DOC_STATUS.md`, `docs/GLOSSARY.md`, `docs/data/DATA_MODEL.md`, `docs/configuration/CONFIGURATION.md`, `docs/research/TRADING_STRATEGY_RESEARCH.md`, `docs/00_PRODUCT_SCOPE.md`, `docs/trading/SIGNAL_AND_ALERTS.md`, `docs/trading/EXECUTION_SPEC.md`, `docs/testing/TESTING_STRATEGY.md`, `docs/architecture/DATA_PIPELINE.md`, `docs/integration/TRADINGVIEW.md`, `docs/operations/SECURITY_AND_OPERATIONS.md`, `docs/01_ENGINEERING_PRINCIPLES.md`) are git-tracked under `git ls-files -- docs/`. The two new files (`docs/research/RESEARCH_PROTOCOL.md`, `docs/research/families/*.md`) and one new file outside docs (`.github/workflows/research-gate.yml`) do not exist yet — they will be created by Phase-1 plans.

**Pattern extraction date:** 2026-09-19

## PATTERN MAPPING COMPLETE

**Phase:** 01 — Research Formalization
**Files classified:** 18 (5 new + 13 modified)
**Analogs found:** 17 with format analogs / 18 (one greenfield — `.github/workflows/research-gate.yml`)

### Coverage
- Files with exact format analog: 4 (RESEARCH_PROTOCOL.md + 3 family sheets)
- Files with self-as-analog (in-place edits): 13
- Files with no analog: 1 (research-gate.yml — greenfield CI YAML)

### Key Patterns Identified
- **Frozen-protocol structure** mirrors `BACKTEST_SPEC.md` (numbered sections §1-§13, TBD-on-numbers footer, gates at end, cross-reference-by-title not by-number).
- **Family-spec-sheet structure** mirrors `TRADING_STRATEGY_SPEC.md` (TBD-slot template + status banner + `V1 family selection: TBD (D012)` footer).
- **In-place edits preserve the file's own existing structure** (purpose + section order + voice) — only the contradiction-relevant slice changes.
- **Three-witness freeze** (header + DECISIONS row + DOC_STATUS bump) is the operative audit pattern; the CI gate enforces all three simultaneously.
- **Authority chain** (DECISIONS > product scope > engineering principles > GLOSSARY > frozen SPEC > supporting specs > research notes) resolves every C1-C7 edit; GLOSSARY is the operative source for C1/C2/C3/C5/C7.
- **TBD discipline + no-synonyms rule + status vocabulary** are cross-cutting and must be enforced by verification greps before the phase gate.

### File Created
`C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/01-research-formalization/01-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns and concrete line ranges in PLAN.md files. The 5 new files should be split across 4-5 fine-grained plans (frozen protocol → 3 family sheets → C1-C7 edits + DECISIONS rows + DOC_STATUS bump → CI gate YAML + required-status-check step), with the freeze beat locked as the final plan after a re-read of the protocol against BACKTEST_SPEC / CONFIGURATION checklists.

## PATTERN MAPPING COMPLETE
