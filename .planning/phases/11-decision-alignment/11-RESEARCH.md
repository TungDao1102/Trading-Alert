# Phase 11: Decision Alignment (docs + params) - Research

**Researched:** 2026-09-30
**Domain:** Documentation authority alignment, frozen research-protocol amendment, versioned parameter registry, CI freeze gates (no `src/` runtime change)
**Confidence:** HIGH for repo facts (all files read this session), MEDIUM for Binance facts (official pages, one via search snippet), LOW for D-03 trade-frequency feasibility (no real data yet)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Protocol amendment v1.1.0 (D032)**
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

**Parameter sets (D036–D039)**
- **D-06:** Never edit an existing `params/**/*.toml` in place (F-810). Create new versioned sets next to the old ones, e.g. `params/trend-pullback/baseline-v4.toml`, `params/breakout-retest/baseline-v4.toml`, and matching `baseline-no-trade-v2` / `baseline-simple-trend-v2` for trend-pullback. Old files stay for reproducing past hashes. — **Reversibility:** costly — new set names get baked into experiment hashes and registry rows.
- **D-07:** New sets carry: `partial_fill_fraction = 1.0` (D038), entry fee modeled at the taker rate (D036), and `working_type = "MARK_PRICE"` (D037). Partial-fill behavior is a separate sensitivity run, not a canonical parameter. If the loader cannot express `working_type` or the taker-entry flag today, extend the registry schema minimally and add a loader test. Any hash-normalization problem is fixed in code, never by picking trading parameters (D038).
- **D-08:** Old sets get a `superseded by v4 (D036-D038)` marker. This is metadata only, not a content edit, and must not change the set's hash. If any metadata field participates in the hash, put the note in the DECISIONS row and the phase summary instead.
- **D-09:** The point-in-time research universe (D039) is a committed manifest file (default `params/universe/research-universe-v1.toml`, planner's choice) listing 10–15 symbols, the selection date, the selection rule, delisted symbols included, and a content hash. It is frozen and hashed before any evaluation. If the volume data needed to rank symbols at the dataset start date is not yet available (Phase 13 backfills it), this phase records the *rule and slots* and ships the manifest as `DRAFT`, with the freeze step owned by Phase 13. The live-5 list stays a separate config and is untouched.

**Doc amendments (D033, D034, D035, exchange facts)**
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

**GLOSSARY and new requirements (F-110, F-116)**
- **D-15:** GLOSSARY §9: collapse synonym reason-code pairs to one canonical code each and list every `ApprovalResult` value and reason code the code actually emits (derive the list from `src/` with CodeGraph or grep, not from memory). Where a code and a glossary term disagree, the glossary is the enum source of truth (D016), so record any needed *code* rename as a follow-up for the phase that owns that module. Do not rename code in Phase 11. Also fix the stale cross-references the audit lists (DECISIONS.md:22, alert example, SOURCES link; audit item P2-3).
- **D-16:** F-116: add new REQ-IDs to `.planning/REQUIREMENTS.md` for the MUST-level doc rules that fell out of the plan (SL may never be loosened, no averaging down, constraint snapshot stored per plan, restart sequence, version in health, secrets encrypted at rest, emergency controls). Each gets a traceability row to the phase that will implement it (12–26). Where a rule is deliberately dropped, record that in DECISIONS as an explicit exclusion rather than leaving it silent. Prefix and numbering follow the existing REQ-ID style.

**Verification and gates**
- **D-17:** Verification is script-based, in the style of the earlier `.planning/quick/*-verify.cjs` checks. A script asserts the greppable facts: protocol header + DECISIONS row + DOC_STATUS agree at v1.1.0; no "no new live order placement" left; no "HMAC-checked" for TradingView; new params contain the three required keys; universe manifest hash matches; GLOSSARY has no duplicate reason codes. It runs locally and, where cheap, is wired into an existing workflow.
- **D-18:** Run the existing suites that touch params/registry/hash (registry, experiment hash, golden fixtures) after adding param sets. New sets must not change any old hash. Any hash that must change is recorded as a deliberate change, per D038, and is not silently regenerated.
- **D-19:** DOC_STATUS.md is bumped for every doc whose status or version changes, and DECISIONS.md gets one summary row for this phase's alignment work (no new decision content, only the record that D031–D039 are now reflected in the docs).

### Claude's Discretion
- File/folder naming for the universe manifest and param-set suffixes, as long as D-06 (no in-place edits) and D-09 (frozen and hashed) hold.
- Exact wording of amended paragraphs, provided each cites its decision ID.
- Exact REQ-ID prefixes and numbering for the F-116 additions.
- Whether the verify script is one file or one per plan.

### Deferred Ideas (OUT OF SCOPE)
- Implementing the decisions in code: cost model (Phase 12), mark-price klines and universe backfill (Phase 13), simulator (Phase 14), SAFE_MODE re-placement and reconciler (Phase 20), daily-loss state (Phase 21), margin and liquidation guard (Phase 22), two-step confirm (Phase 23).
- Renaming any code enum or reason code that disagrees with the cleaned GLOSSARY: the owning phase does it (D-15).
- Freezing the research universe with real volume data: Phase 13 (D-09).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (REQUIREMENTS.md) | Research Support |
|----|-------------------------------|------------------|
| RSCH-01 | Research protocol is frozen (dataset splits, cost model, execution assumptions, acceptance methodology) before any parameter work begins | §"Protocol v1.1.0 + freeze gate": header/DECISIONS/DOC_STATUS witnesses, version-blind gate defect, pinned tests to update, D-03 feasibility |
| RSCH-02 | Three candidate families specified independently | §"Protocol v1.1.0": variant counts feed N; new v4 sets must not perturb family independence (dry-run shows only `_EXPECTED_CANDIDATE_IDS` changes) |
| RISK-02 | Portfolio limits, DAILY_STOP states, fail closed | §"Doc amendment inventory": RISK_MANAGEMENT §4/§8/§9/§11/§12 exact lines (D033, D035, quantization order, MARKET_LOT_SIZE/PERCENT_PRICE) |
| EXEC-02 | Reconciliation compares normal, algo, positions; sweeps orphans; forces SAFE_MODE | §"Doc amendment inventory": EXECUTION_SPEC §6/§9/§11/§12, RUNBOOK §2/§3/§4/§9, algo status semantics (D034, F-054, F-051) |
| OPS-01 | SAFE_MODE blocks new entries while monitoring continues; RUNBOOK rehearsed | SECURITY_AND_OPERATIONS §7:80 and RUNBOOK wording rewrite (D034) |
| NEW (F-116, ROADMAP-flagged F-104/F-106) | Lost MUST-level doc requirements | §"New REQ-IDs": proposed IDs, text, and phase traceability |
</phase_requirements>

## Summary

Phase 11 is a docs/params/CI phase. The work splits into six independent-ish streams: (1) protocol v1.1.0 pre-registration plus a strengthened three-witness freeze gate; (2) new versioned parameter sets plus a minimal registry key addition; (3) a DRAFT point-in-time universe manifest; (4) doc amendments (SAFE_MODE, daily loss, margin, quantization order, exchange facts, TradingView auth); (5) GLOSSARY/REQUIREMENTS/DECISIONS/DOC_STATUS bookkeeping; (6) a verify script wired into pytest/CI.

Several repo facts, discovered by reading and by a scratch-copy full-suite dry run, change how the phase must be planned. (a) The `registry-gate` CI job already fails on 7 of 10 existing param sets because `tests/fixtures/phase4/parameters.json` pins only the three `baseline-v1` sets; any new set also needs a pin. (b) `params/universe/` (the CONTEXT default path) would be read as a strategy family by three places (registry-gate, `analytics_files._family_ids`, kill-gate registration tripwire), so the manifest belongs elsewhere. (c) `working_type` is not in the closed `STRATEGY_KEYS` whitelist and needs a `STRING_KEYS` entry too, or the loader raises. (d) `partial_fill_fraction = 1.0` and a taker entry fee need no schema change (taker = `fee_rate_entry = 0.0005`; no flag). (e) The research-gate's third witness is version-blind (the D029 row satisfies it forever), so a v1.1.0 freeze can pass CI with no v1.1.0 row unless the gate is strengthened. (f) Tests pin the current protocol header (`v1.0.1`, `Supersedes: none`, DOC_STATUS `v1.0.1`) and must be updated in the same change.

**Primary recommendation:** Plan six plans in three waves (A protocol+gate, B params+registry, C universe manifest in wave 1; D ops/risk/exchange docs in wave 2; E GLOSSARY/REQUIREMENTS/DECISIONS-summary/DOC_STATUS + F verify script in wave 3). Keep every `DECISIONS.md` and `DOC_STATUS.md` edit inside one plan per wave to avoid merge conflicts. Keep D-03's numbers (100 trades / 30 per fold / N=25 / Holm α=0.05 / 20% holdout) but define the trade floor on the pooled out-of-sample blocks (not the validation slice alone) and make Phase 13 responsible for a dataset deep enough to reach it, because 100 trades is already a low-power floor.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Decision authority (D031-D042 wording) | Docs: `docs/DECISIONS.md` | `docs/DOC_STATUS.md` | D031: DECISIONS outranks docs, AGENTS.md, .planning |
| Protocol freeze witnesses | Docs (protocol header, DECISIONS row, DOC_STATUS) | CI `research-gate.yml` | Executable gate reads all three |
| Parameter identity and hash | Registry code `src/domain/registry.py` + `params/*.toml` | CI `registry-gate.yml` + pin file | Loader hashes normalized params; gate compares to pins |
| Universe manifest | Docs/research asset (`docs/research/universe/`) | verify script | Must stay out of `params/` (family-directory semantics) |
| Exchange facts | Docs `EXECUTION_SPEC`, `BINANCE`, `RISK_MANAGEMENT` | `docs/SOURCES.md` | D-14 requires URL + fetch date |
| Enum vocabulary | Docs `GLOSSARY.md` (source of truth, D016) | `src/domain/enums.py` (follow-up rename in owning phase) | Code rename is out of scope |
| Requirements traceability | `.planning/REQUIREMENTS.md` | `.planning/ROADMAP.md` | New REQ-IDs map to phases 13-26 |
| Verification | `scripts/verify_decision_alignment.py` + pytest wrapper | `registry-gate.yml` pytest step | Hash checks need `src.domain.canonical` (Python) |

## Standard Stack

No new libraries. Everything uses what is already installed.

| Tool | Version (verified this session) | Purpose |
|------|--------------------------------|---------|
| Python (repo `.venv`) | 3.13.15 | run pytest and the verify script |
| pytest | 9 (per `pyproject.toml` `pytest>=9`) | existing suites + new alignment tests |
| `src.domain.registry` / `src.domain.canonical.sha256_hex` | in-repo | param and manifest hashing |
| uv | 0.12.20 | CI (`uv sync --frozen --extra dev`) |
| bash (Git Bash) | present at `/usr/bin/bash` | run the workflow freeze step in negative tests |
| node | v24.18.0 | only needed if the planner chooses the `.cjs` verify style |

Not available: PyYAML (not in `pyproject.toml` dependencies; grep found no `yaml` entry), `gh` CLI. Extract the workflow `run:` block with a regex, not a YAML parser.

## Package Legitimacy Audit

This phase installs no external packages. Nothing to audit. **Packages removed due to [SLOP] verdict:** none. **Packages flagged [SUS]:** none.

## Architecture Patterns

### System flow (what changes and what checks it)

```
User decisions D031-D042 (DECISIONS.md, authoritative)
   |
   +--> RESEARCH_PROTOCOL v1.1.0 --witness 1--> [research-gate.yml]
   |        + DECISIONS row D043  --witness 3-->     |  (version-bound, negative-tested)
   |        + DOC_STATUS line     --witness 2-->     v
   |                                            pass / fail
   +--> params/<family>/baseline-v4.toml ----> registry.load_parameter_set()
   |        (+ working_type key)                   |-- hash --> pin file --> [registry-gate.yml]
   |                                               '-- tests: registry, analytics_files, full suite
   +--> docs/research/universe/research-universe-v1.toml (DRAFT; hash when FROZEN in Phase 13)
   +--> ops/risk/exec/binance/tradingview docs (each edit cites Dnnn, exchange facts cite SOURCES.md)
   +--> GLOSSARY §9 (+ApprovalResult) / REQUIREMENTS new IDs / DOC_STATUS bump
   |
   '--> scripts/verify_decision_alignment.py (PASS/FAIL lines) <-- pytest wrapper <-- registry-gate pytest step
```

### Recommended file layout for new artifacts

```
docs/research/universe/research-universe-v1.toml      # DRAFT manifest (NOT under params/)
docs/research/holdout_consumed.json                   # append-only consumed marker (no forbidden keys)
scripts/verify_decision_alignment.py                  # PASS/FAIL style, modes: protocol|docs|params|universe|glossary|reqs|all
tests/test_decision_alignment.py                      # runs the verify script; mirrors quick/*-verify.cjs PASS/FAIL output
tests/test_research_gate_negative.py                  # runs the workflow freeze step against tmp copies
params/{trend-pullback,breakout-retest,range-mr}/baseline-v4.toml
params/trend-pullback/baseline-no-trade-v2.toml
params/trend-pullback/baseline-simple-trend-v2.toml
```

### Suggested plan decomposition

| Plan | Wave | Scope | Owns (edit conflicts) |
|------|------|-------|----------------------|
| 11-A protocol v1.1.0 + gate | 1 | protocol text, BACKTEST_SPEC:153, D043 row, DOC_STATUS line, workflow freeze step, pinned-test updates, holdout marker, negative test | DECISIONS (D043), DOC_STATUS, protocol, research-gate.yml, test_kill_gate_docs |
| 11-B params + registry | 1 | `working_type` key, 5 new TOMLs, pins, `_EXPECTED_CANDIDATE_IDS`, CONFIGURATION.md | registry.py, params/, parameters.json pins, CONFIGURATION |
| 11-C universe manifest | 1 | DRAFT manifest + rule + verify hooks | new files only |
| 11-D ops/risk/exchange docs | 2 | SAFE_MODE, daily loss, margin, quantization order, exchange facts, TradingView, SOURCES, stale refs | SEC_OPS, RUNBOOK, EXEC_SPEC, RISK, BINANCE, TRADINGVIEW, TECH_STACK, SOURCES, SIGNAL_AND_ALERTS, DATA_MODEL, AGENTS.md, .planning/PROJECT.md, .planning/research/STACK.md |
| 11-E GLOSSARY + REQUIREMENTS + summary | 3 | GLOSSARY §9 + ApprovalResult, F-116 REQ-IDs, D044 summary row, DECISIONS blank-line fix, DOC_STATUS bumps | GLOSSARY, REQUIREMENTS, DECISIONS (D044), DOC_STATUS |
| 11-F verify script + CI wiring | 3 | script, pytest wrapper, registry-gate pytest line | scripts/, tests/, registry-gate.yml |

### Anti-patterns to avoid
- Editing an old `params/**/*.toml`, even comment-only. Comments do not change the hash, but any later byte-level hash lock (audit P2-8) would trip. Put the "superseded" note in the v4 file header and the DECISIONS row instead (deviation from D-08's "marker on old sets", which D-06 also forbids by its own terms; flagged as Open Question 4).
- Putting `working_type` into `COST_KEYS` (`src/backtest/costs.py:27-35`). That tuple feeds `cost_model_hash`; adding a key changes every existing cost hash and breaks D-18.
- Regenerating any pinned hash to make a test pass (F-810 anti-pattern).
- Adding a blank line inside the DECISIONS table (audit F-119 already documents this defect; remove the existing one).

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Param/manifest hashing | new hash routine | `src.domain.canonical.sha256_hex` (`canonical.py`: sorted keys, compact separators, Decimal as `str`) | one canonicalizer already owns identity |
| Param file validation | new TOML checker | `load_parameter_set` / `verify_parameter_set` | already fail-closed on unknown key, type, schema |
| Freeze gate negative test | new CI harness | run the workflow step's `run:` block under `bash` in `tmp_path` copies of the 3 files | proves the real gate fails, not a mirror |
| Reason-code inventory | memory | grep of `src/` + `RejectionReason` (see GLOSSARY table below) | D-15 requires derivation from code |

## Runtime State Inventory

Not a rename/refactor phase. Closest analogue is version-string pins that must move together; they are listed under Pitfalls 1, 2 and 4.

## Findings

### F1. Doc amendment inventory (file, line, offending text, change)

All line numbers read this session. Quoted text is verbatim.

| # | File:lines | Current text (verbatim) | Change | Decision |
|---|-----------|-------------------------|--------|----------|
| 1 | `docs/operations/SECURITY_AND_OPERATIONS.md:76-82` | `- no new live order placement;` | "SAFE_MODE blocks entries only (orders that can open or increase a position). Protective and reduce-only orders always allowed after an authoritative position query." Add ladder: missing/canceled SL -> auto re-place at original plan SL (never wider); SL rejected/unacknowledged -> reduce-only MARKET close -> alert HIGH. | D034 |
| 2 | `docs/operations/RUNBOOK.md:23-24` | `1. Set SAFE_MODE.` / `2. Block new live orders.` | "Block new ENTRY orders (protective/reduce-only remain allowed)" | D034 |
| 3 | `docs/operations/RUNBOOK.md:33-42` | `if stop is absent, submit protection only after risk validation` / `otherwise require explicit manual intervention` | Automatic re-place, then reduce-only close fallback; manual intervention optional, not required (operator works full-time) | D034 |
| 4 | `docs/operations/RUNBOOK.md:93, 117` | `NO NEW ORDERS` (feed stale) / `→ block new orders` (DB failure) | "NO NEW ENTRY ORDERS"; DB failure must not block risk-reducing actions | D034 |
| 5 | `docs/trading/EXECUTION_SPEC.md:142-149` | `- disable new live orders,` | "disable new entry orders"; add close/protect controls as explicit operator actions | D034 |
| 6 | `docs/trading/EXECUTION_SPEC.md:114-132` | `Orphan orders must be canceled after authoritative position verification.` | Add: a protective stop paired with a still-working ENTRY is not an orphan (F-401); the reconciler may re-place a missing SL (supersedes "cancel-only"). The words "cancel-only" do not appear in `docs/`; the decision lives in `.planning/phases/08-*/09-*` CONTEXT, so update via D034 citation, not by grep. | D034 |
| 7 | `docs/trading/EXECUTION_SPEC.md:87-98` (§6) | `After entry fill, the system must verify that the expected protective stop exists and is active.` | Add algo status semantics subsection (F2 table below) | F-054 |
| 8 | `docs/trading/EXECUTION_SPEC.md:151-155` (§12) | `documented a 200-open-conditional-order limit per symbol instead` | "200 open conditional orders across all symbols (account-wide)"; count open algo orders without a symbol filter; keep "verify against current Binance docs" marker | F-051 |
| 9 | `docs/trading/EXECUTION_SPEC.md:112` | link labelled `Binance Futures Trade API` -> `.../trade/rest-api/New-Order` for position-mode rules | fix citation (F-057) | P2-3 |
| 10 | `docs/trading/RISK_MANAGEMENT.md:51` | ``- daily loss stop: `TBD` `` | Replace with D033 numbers: 0.5% warning / 1% stop | D033 |
| 11 | `docs/trading/RISK_MANAGEMENT.md:71-85` (§8) | `- no new live positions;` (DAILY_STOP) | Define day = UTC day (00:00 UTC = 07:00 Asia/Ho_Chi_Minh); loss = -(realized PnL + commissions + funding); base = account equity at UTC day start; DAILY_STOP cancels pending entries, keeps protective SL, alerts | D033 |
| 12 | `docs/trading/RISK_MANAGEMENT.md:87-91` (§9) | `Leverage must be treated as an exchange/account constraint, not as the reason for choosing position size.` | ISOLATED; leverage cap 5x; marginType and leverage set explicitly before entry, never inherited; reject plan unless liquidation price is beyond SL with a buffer; available-margin check includes other resting entries. Do NOT hard-code the buffer number unless the planner records it as a registry parameter (D035 gives no number; audit suggests >= 1x SL distance, unratified) | D035 |
| 13 | `docs/trading/RISK_MANAGEMENT.md:102-127` (§11) | rules 1-4 in order: never round up; min qty/notional reject; utilization reject; same logic all modes | Single canonical statement (see F4) | D031 |
| 14 | `docs/trading/RISK_MANAGEMENT.md:129-143` (§12) | snapshot list ends `metadata_observed_at_utc` | Add `market_lot_size` (min/max/step), `percent_price` (multiplierUp/Down), `working_type`, `margin_type`, `leverage`, `equity_used` + source/time. State it is persisted per plan | F-056, D035, D037 |
| 15 | `docs/backtest/BACKTEST_SPEC.md:153` | `Exact numerical acceptance thresholds remain `TBD` until the research methodology is exercised on real data.` | Point to protocol v1.1.0 §4 pre-registration | D032 |
| 16 | `docs/backtest/BACKTEST_SPEC.md:87-119` | statistical power text and research universe "10-15 sufficiently liquid symbols" | Point universe to manifest and D039 point-in-time rule | D039 |
| 17 | `docs/integration/BINANCE.md:23-30` (§3), `:38-42` (§5) | market/user stream text with no URL paths | Add WS URL split (F2) and note user data on `/private` | F-053 |
| 18 | `docs/integration/TRADINGVIEW.md:37-40` (§5) | `Webhook endpoint must be authenticated and must not accept secrets in the message body.` | Remove any HMAC implication; V1 has no webhook (INTG-02 is v2); if built: shared secret in URL path + source-IP allowlist + <=3 s ack + dedupe; 2FA is a TradingView account requirement | F-052 |
| 19 | `docs/operations/SECURITY_AND_OPERATIONS.md:10` | `- Webhook endpoints must be authenticated.` | cross-reference TRADINGVIEW §5 scheme | F-052 |
| 20 | `docs/TECHNOLOGY_STACK.md:29-31` | `FastAPI is the default choice for optional HTTP endpoints such as TradingView webhooks` | no HMAC wording present; add pointer only if scheme is referenced | F-052 |
| 21 | `AGENTS.md:77` (generated block) and `.planning/research/STACK.md:57` | `TradingView webhooks (HMAC-checked)` | Replace with "TradingView webhooks (URL-path secret + IP allow-list; TradingView cannot sign)". The only "HMAC-checked" text is in these two files, not in `docs/`. AGENTS.md sits inside `<!-- GSD:stack-start source:research/STACK.md -->` so edit the source first or a regeneration reverts it | F-052 |
| 22 | `AGENTS.md:18`, `.planning/PROJECT.md:53`, `docs/research/RESEARCH_PROTOCOL.md:119-125` | quantization order `floor to stepSize → realized-risk check (60% baseline) → min-qty/notional reject` | conform to canonical order (F4) | D031 |
| 23 | `docs/trading/SIGNAL_AND_ALERTS.md:95,97` | `Expected R:R: 1.8 / 3.9` and `Valid until: 16:00 UTC` | R:R >= `minimum_rr` 2.0 (`params/trend-pullback/baseline-v3.toml`: `minimum_rr = 2.0`); show time in Asia/Ho_Chi_Minh (D025) | P2-3 / F-119 |
| 24 | `docs/DECISIONS.md` (blank line between D017 and D018 rows) | blank line splits the table | remove the blank line | P2-3 / F-119 |
| 25 | `docs/SOURCES.md:11`, `docs/operations/SECURITY_AND_OPERATIONS.md:32`, `docs/architecture/ARCHITECTURE.md:187` | link path `derivatives-trading-coin-futures/websocket-market-streams/Connect` cited for USD-M | replace with `usds-margined-futures/websocket-market-streams` | F-057 |
| 26 | `docs/testing/TESTING_STRATEGY.md:107-115` (§8) | `TradePlanStatus: CANCELED → APPROVED`, `TradeStatus: CLOSED → NEW PROTECTIVE ORDER` | optional in this phase: use canonical values (`CANCELED` is not a `TradePlanStatus`, GLOSSARY §3) | F-111 |
| 27 | `docs/data/DATA_MODEL.md` §2.4 `trade_plans` (lines 110-138) | field list has no constraint snapshot, working type, margin, leverage | add `constraint_snapshot_json`, `constraint_snapshot_hash`, `working_type`, `margin_type`, `leverage`, `equity_used`; record state-transition validation as target (F-111). For dropped entities (`trades`, `feature_snapshots`, `experiment_runs`) see Open Question 6 | RISK §12, D035, D037, F-112 |

### F2. Binance facts, verified against current official pages (2026-09-30)

| Fact | Source and how obtained | Confidence |
|------|-------------------------|-----------|
| 200 conditional orders across all symbols; `MAX_NUM_ALGO_ORDERS` filter removed from `GET /fapi/v1/exchangeInfo` (2025-12-29) | WebFetch `developers.binance.com/docs/derivatives/usds-margined-futures/change-log` 2026-09-30. Quote: `The parameter 'filterType': 'MAX_NUM_ALGO_ORDERS' has been removed from the endpoint GET /fapi/v1/exchangeInfo. The condtional order limits is 200 across all symbols.` | [CITED] HIGH |
| Pitfall: `.../usds-margined-futures/common-definition` still documents `MAX_NUM_ALGO_ORDERS` as "maximum number of all kinds of algo orders an account is allowed to have open on a symbol" (stale page, contradicts changelog) | WebFetch of common-definition 2026-09-30 | [CITED] HIGH that the page says it; changelog is later and governs |
| `No margin check before the conditional order gets triggered.` (2025-11-06) | change-log WebFetch | [CITED] HIGH |
| Algo statuses (ALGO_UPDATE): NEW = placed in Algo Service not yet triggered; TRIGGERING = condition met, forwarded to matching engine; FINISHED = "the triggered conditional order has been filled or canceled in the matching engine"; REJECTED = denied by matching engine, e.g. margin check failure; EXPIRED = canceled by the system | WebSearch result summarizing `.../user-data-streams/Event-Algo-Order-Update`; **WebFetch of that page returned only the docs home shell twice**. Treat as MEDIUM; executor must re-open the page (or SDK `algo_update_o.py`) before finalizing wording | [CITED via search snippet] MEDIUM |
| `CONDITIONAL_ORDER_TRIGGER_REJECT` deprecated 2025-12-15; rejection reasons now in `ALGO_UPDATE`; conditional orders migrated to Algo Service 2025-12-09 | same WebSearch summary of the change-log | MEDIUM |
| WS split: `wss://fstream.binance.com/public` (bookTicker, depth), `/market` (aggTrade, markPrice, kline, ticker), `/private` (user data via listenKey); legacy `/ws` "will remain available until 2026-04-23, after which they will be permanently decommissioned"; unmigrated connections "ONLY be able to receive data from wss://fstream.binance.com/public" | WebFetch `.../usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice` 2026-09-30 | [CITED] HIGH |
| Change-log entry 2026-03-05 adds `URL PATH` sections (`/public`, `/market`; `/private` for user data) | change-log WebFetch | [CITED] HIGH |
| `workingType` enum `MARK_PRICE, CONTRACT_PRICE`, "Default: CONTRACT_PRICE"; `algoType=CONDITIONAL`; `closePosition` cannot be sent with `quantity` or `reduceOnly` | WebFetch `.../trade/rest-api/New-Algo-Order` | [CITED] HIGH. Implication: D037 MARK_PRICE must be sent explicitly; the default differs |
| `MARKET_LOT_SIZE` "defines the quantity rules for MARKET orders on a symbol"; `PERCENT_PRICE` "defines valid range for a price based on the mark price", BUY: price <= markPrice * multiplierUp, SELL: price >= markPrice * multiplierDown | WebFetch `.../usds-margined-futures/common-definition` | [CITED] HIGH. That triggered `*_MARKET` exits with an explicit quantity fall under `MARKET_LOT_SIZE`, and that reduce-only legs skip `MIN_NOTIONAL`, come from audit F-056 and ROADMAP:609 and are NOT confirmed by these pages: keep the "verify" marker |
| TradingView webhooks: only ports 80 and 443; 3-second timeout; source IPs 52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7; 2FA required; no mention of custom headers or request signing | WebFetch `https://www.tradingview.com/support/solutions/43000529348-about-webhooks/` 2026-09-30 | [CITED] HIGH (absence of signing is silence, so "cannot sign" is [ASSUMED] beyond the page; the docs just must not promise HMAC) |

Record each URL and the fetch date 2026-09-30 in `docs/SOURCES.md` (currently 31 lines; sections Binance / TradingView / Python). Add a "Fetched" column or a dated bullet list.

### F3. Protocol v1.1.0 and the freeze gate

**Current header** (`docs/research/RESEARCH_PROTOCOL.md:3-6`):
```
> **Protocol version:** v1.0.1
> **Status:** FROZEN
> **Frozen on:** 2026-09-19
> **Supersedes:** none
```
**Sections to rewrite:** §0 line 24 numeric-gate reservation; §1 "Specific value reservations" (lines 75-77, split ratios "ranges to explore"); §2 "Quantization" (lines 117-130, order per F4); §4 "Thresholds remain TBD" (lines 205-213) and gate 6 wording (line 199, "TBD"); Appendix A (add v1.1.0 to Amendment log at 377+). Keep §4 "Kill gate D013" (lines 226-240) byte-identical (D-05; `tests/test_kill_gate_docs.py::test_protocol_kill_gate_matches_d013` asserts its content).

**Recommended header** (see Open Question 1 on `Frozen on`):
```
> **Protocol version:** v1.1.0
> **Status:** FROZEN
> **Frozen on:** 2026-09-19
> **Amended on:** 2026-09-30
> **Supersedes:** v1.0.1
```
`Frozen on` is the kill-gate clock start: `src/analytics/clock.py:26` `FROZEN_ON_PATTERN = r"^>\s*\*\*Frozen on:\*\*\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"`, docstring "Research-clock provenance (D030: the protocol's Frozen-on date is the clock start)". Changing it silently restarts the 6-month D013 budget, which the audit lists as an undecided human question (report §20.6, "L1 open question 3"). `Amended on` does not match that regex.

**Pre-registration content** (all defaults from D-03; additions are marked):

| Item | Value | Note |
|------|-------|------|
| Holdout | last 20% of dataset by time, locked; single use per candidate lineage | D-03 |
| Development / Validation | first 80% split: Development first 40%, Validation last 40% run as 4 sequential walk-forward test folds (Claude recommendation, [ASSUMED]) | fixes what §1 leaves as "ranges to explore" |
| Min trades | >= 100 pooled out-of-sample (Validation folds), >= 30 per fold | see F5 for feasibility |
| Expectancy | mean net R after full costs > 0 with block-bootstrap lower 95% bound > 0, AND Holm-adjusted one-sided p < 0.05 | define ONE primary test to avoid two competing rules |
| Max drawdown | <= 20% of research equity, same equity base as risk engine | equals 40R at `risk_rate = 0.005`; makes a separate loss-streak ceiling redundant (protocol gate 6 mentions loss streak: report only) |
| Variant budget | N = 25 per family, counting every parameter combination tried, logged | current named variants: trend-pullback 7 rows, breakout-retest 9 rows, range-mr 8 rows (family sheets, tables at `trend-pullback.md:70-78`, `breakout-retest.md:79-89`, `range-mr.md:84-93`) |
| Correction | Holm-Bonferroni, family-wise alpha 0.05 | scope question: Open Question 2 |
| Human override | "A human may reject a passing candidate; may never pass a failing one" | remove/replace `protocol:236` wording "a family's passing status is a recorded human decision ... never computed" only in so far as it lets a human pass; keep D030 text otherwise |
| Consumed marker | `docs/research/holdout_consumed.json`, schema `holdout-consumed/1`, append-only `entries[]` each with `lineage_id`, `candidate_sha256` (= `sha256_hex` of `{strategy_id, strategy_version, parameter_set_hash of the candidate}`), `consumed_at_utc`, `decision_ref` | file must avoid the keys `parameterSetId|parameter_set_id|parameterSetHash|parameter_set_hash` and a `parameters` key (research-gate tripwire scans JSON; `tests/test_kill_gate_registration.py:FORBIDDEN_KEYS` shows the same rule) |

`src/analytics/gates.py` computes gate cells from self-reported booleans today (F-960). The numbers above are documentation only in Phase 11. Record a follow-up: analytics gate code implementing them is not scheduled in ROADMAP phases 12-27 except implicitly at Phase 26 ("a family has passed under protocol v1.1.0"). Add an explicit note to the DECISIONS row or ROADMAP so the follow-up has an owner.

**Gate defect and required change** (`.github/workflows/research-gate.yml`, freeze step lines 19-55):
- Witness 1 checks `Status: FROZEN` and a `Frozen on` date only (lines 30-37). No version check.
- Witness 2 checks DOC_STATUS lists the protocol and lacks pending markers (lines 40-47). No version check.
- Witness 3 regex (line 50): `protocol v1\.0\.0 frozen|RESEARCH_PROTOCOL.*frozen|frozen.*RESEARCH_PROTOCOL`. The D029 row (`| D029 | Research protocol v1.0.0 frozen | Accepted |`) satisfies this forever, so a v1.1.0 header with no v1.1.0 row passes CI today.
- Required change: read `V` from `^>\s*\*\*Protocol version:\*\*\s*v([0-9.]+)`; require DECISIONS to contain `protocol v${V} frozen` (escape dots) and the DOC_STATUS protocol index line to contain `v${V}`. Keep the existing `Frozen on` `grep -E` line **verbatim**, because `tests/test_kill_gate_clock.py::_ci_frozen_on_regex` extracts it from the workflow by looking for a line containing both `Frozen on` and `grep -E`.
- New DECISIONS row must contain the literal `protocol v1.1.0 frozen` (D029 wording is `Research protocol v1.0.0 frozen`; mirror it: `Research protocol v1.1.0 frozen`). Next free ID is D043 (highest existing is D042).
- DOC_STATUS line 13 currently: `` `research/RESEARCH_PROTOCOL.md` — Frozen on 2026-09-19 (v1.0.1; D029, D030); executable gate at `.github/workflows/research-gate.yml` `` -> change to v1.1.0 and cite D043; add a change-log line (lines 51-53 are the prior entries). It must not match `research/RESEARCH_PROTOCOL\.md.*(pending-freeze|DRAFT|Living research)`.
- Negative test: `tests/test_research_gate_negative.py` extracts the `Freeze check` step `run:` text with a regex, writes `docs/research/RESEARCH_PROTOCOL.md`, `docs/DOC_STATUS.md`, `docs/DECISIONS.md` copies into `tmp_path`, runs `bash -c` there. Cases: intact -> exit 0; missing/`DRAFT` header -> non-zero; DOC_STATUS without v1.1.0 -> non-zero; DECISIONS without `protocol v1.1.0 frozen` -> non-zero. Skip if `bash` missing. (The existing `tests/test_kill_gate_docs.py` mirrors the regexes in Python; it does not run the workflow.)
- The `Identity-tuple` and `Registry-path tripwire` steps (workflow lines 57-135) scan the whole repo for `experiment*.json|backtest*.json` and for JSON/YAML files containing `parameterSetId|parameter_set_id|parameterSetHash|parameter_set_hash` plus a `parameters` block. The universe manifest (TOML) and the consumed marker (avoid those keys) stay clear.

**Tests that must change in the same commit as the header bump** (verified by reading):
- `tests/test_kill_gate_docs.py:39-41` `PINNED_PROTOCOL_LINES` includes `"> **Supersedes:** none"` -> `"> **Supersedes:** v1.0.1"`; keep `Status` and `Frozen on` pins if Open Question 1 keeps the date.
- `tests/test_kill_gate_docs.py:84` `assert "> **Protocol version:** v1.0.1" in protocol_lines` -> v1.1.0.
- `tests/test_kill_gate_docs.py:115-121` `test_doc_status_line_not_pending` asserts `"v1.0.1" in index_lines[0]` and `"D030" in index_lines[0]` -> require `v1.1.0` (keep D030 mention on the line).
- `tests/test_kill_gate_docs.py:45` `D029_ROW_PREFIX` stays valid (do not edit the D029 row).
- Module docstring at line 6 mentions v1.0.1; cosmetic.

### F4. Quantization check order: one canonical statement

Conflict, all read this session:
- Code `src/risk/quantization.py:43-47`: `Gate order (first failure wins): 1. rounded < min_quantity → MIN_QTY_REJECT  2. rounded × reference_price < min_notional → NOTIONAL_REJECT  3. realized_risk / allowed_risk < minimum_risk_utilization_after_rounding → UTILIZATION_REJECT`.
- `docs/trading/RISK_MANAGEMENT.md:113-117`: never round up; below min qty/notional -> reject; utilization below threshold -> reject `QUANTIZATION_REJECT`. Matches the code order but names a synonym code.
- `AGENTS.md:18` and `.planning/PROJECT.md:53`: `floor to stepSize → realized-risk check (60% baseline) → min-qty/notional reject → NO_TRADE preferred over round-up`. Utilization before minimums: conflicts.
- `docs/research/RESEARCH_PROTOCOL.md:119-125`: floor, realized-risk check, then min reject: conflicts.

Recommended canonical (matches code, audit AMB-006/007 "keep the current order"): floor to stepSize -> min quantity reject -> min notional reject -> realized-risk utilization reject (baseline `minimum_risk_utilization_after_rounding = 0.6`) -> NO_TRADE; never round up; identical in backtest, paper and live. Put it in `RISK_MANAGEMENT.md` §11, and make the protocol (v1.1.0, §2), AGENTS.md line 18 and PROJECT.md line 53 point to it. [ASSUMED: the user has not ratified this order; D031 only says a single statement is needed. Code order is the safest pick because nothing needs to change in `src/`.]

### F5. D-03 feasibility against trade frequency

Inputs read: Phase 2 CONTEXT D-02 "1H/4H ~2 years back, 1m ~6-12 months back" (history bound for the first run; Phase 13 extends). `docs/backtest/BACKTEST_SPEC.md:87-109` example uses `σ ≈ 1.2R`. Family sheets carry no trade-frequency estimate (grep for frequency/trades-per found none).

Computation (Python run this session; σ = 1.2R, independent trades, one-sided z): required mean net R for the raw lower bound to clear zero at n trades, and n needed for 80% power.

| Correction | alpha per test | z | mean R needed at n=100 | at n=200 | at n=300 | n for 80% power at true mean 0.15R |
|-----------|----------------|---|------------------------|----------|----------|-----------------------------------|
| none (m=1) | 0.05 | 1.645 | 0.197R | 0.140R | 0.114R | 396 |
| Holm, m=25 (smallest p) | 0.002 | 2.878 | 0.345R | 0.244R | 0.199R | 886 |
| Holm, m=75 (3 families x 25) | 0.00067 | 3.209 | 0.385R | 0.272R | 0.222R | 1050 |

Uncorrected false-pass probability: 1-0.95^25 = 72.3% (matches CONTEXT), 1-0.95^75 = 97.9%. Block-bootstrap dependence makes the real SE larger than σ/√n.

Trade count estimate (all [ASSUMED], no real data): trades ≈ symbols x months x fills per symbol-month. With 12 symbols and 24 months and 0.5-2 fills/symbol-month, total 144-576; excluding the 20% holdout leaves 115-460; a Validation block that is only 40% of the dataset holds 58-230 of these. A floor of 100 on a single Validation slice is therefore unreachable for a low-frequency family at 2-year depth.

**Recommendation (pre-freeze adjustment, per D-03):** do not lower 100/30. Instead (1) define the floor on the pooled out-of-sample Validation folds (4 folds x >= 30 each = 120 >= 100 is self-consistent), never on the live-5 slice (disclosed but no floor; 5 symbols cannot reach it); (2) state that a family below the floor cannot pass (no new enum; it counts toward the D013 budget) and the floor is never lowered after freeze; (3) set as a Phase 13 acceptance criterion a research dataset deep enough to reach the floor (rough target >= 4 years of 4H/1H for the universe, [ASSUMED]; Binance USDⓈ-M history and delisted-symbol klines must be confirmed then); (4) note honestly that 100 trades detects only a large edge under Holm (0.35R at m=25), which is the point of D032, not a bug. The real trade rate can only be measured after Phase 14 (causal simulator) exists, so the freeze cannot use a measured rate; the DECISIONS row should say so.

### F6. Params, loader, hashes

Verified in `src/domain/registry.py` (read in full):
- `STRATEGY_KEYS` (line 60-111) is a closed `frozenset`; unknown keys raise `StrategyKeyOutsideRegistry` (lines 360-364). `working_type` is absent.
- Types: `INT_KEYS`, `STRING_KEYS = frozenset({"funding_treatment","slippage_model","spread_fill_assumptions"})` (lines 271-277), `DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS - STRING_KEYS` (line 278). A new key added only to `STRATEGY_KEYS` becomes a DECIMAL key and a string value raises "must be Decimal or int". **Add it to `STRING_KEYS` as well.**
- `_normalize_value` (line 195-215): whole-number float -> `int` (so `partial_fill_fraction = 1.0` hashes as `1`); fractional float -> `Decimal(raw)`.
- Hash payload (lines 395-401 and 434-439): `{strategy_id, strategy_version, parameter_set_id, parameters}` only. Comments, `schema_version` do not participate.
- `check_strategy_key_outside_registry` (line 471) flags any ambient key equal to or ending in `_<strategy key>`. Adding `working_type` to `STRATEGY_KEYS` means ambient env/config named `WORKING_TYPE`/`X_WORKING_TYPE` now raises. No `src/` caller passes ambient config today (grep: only `tests/test_registry_gate.py` calls it), but record the constraint for Phases 18-20 adapter config.

Dry run (scratch copy of the repo at `<scratchpad>/repo`, not the real tree): I created `baseline-v4` for trend-pullback and breakout-retest (v3 + `fee_rate_entry = 0.0005`, `partial_fill_fraction = 1.0`, `working_type = "MARK_PRICE"`), `baseline-no-trade-v2`, `baseline-simple-trend-v2`, and added `working_type` to both `STRATEGY_KEYS` and `STRING_KEYS`. Results:
- All four load; `partial_fill_fraction` loads as int `1`; `working_type` = `MARK_PRICE`; `build_cost_model` over `COST_KEYS` succeeds for all four (cost_model_hash prefix `e18ce0093131`, identical across the four because the 7 cost keys are identical).
- `baseline-v3` hash unchanged: `5205ec6a87f4...`.
- Hashes for new sets in that run: trend-pullback/baseline-v4 `a61707fe0f79`, breakout-retest/baseline-v4 `b61cd35d00e3`, no-trade-v2 `250a6ef64c83`, simple-trend-v2 `8f9d310d9b74` (differ if the final files differ; compute from the real files).
- Full `pytest tests` in the scratch copy: **one failure**, `tests/test_analytics_files.py::test_tracer_real_repo_scan_feeds_evaluator` (line 138), because `_EXPECTED_CANDIDATE_IDS` lists the candidate ids per family and `baseline-v4` is a candidate id (`src/analytics/family.py:95-101` `is_baseline_parameter_set_id` only treats `baseline-no-trade*`/`baseline-simple-trend*` prefixes as baselines). The two `-v2` baseline sets do not disturb it. Update `_EXPECTED_CANDIDATE_IDS` (trend-pullback, breakout-retest, and range-mr if added) in the same change.

Design conclusions:
1. **Taker entry needs no flag.** D036 is satisfied by `fee_rate_entry = 0.0005` (the same value as `fee_rate_exit = 0.0005`, labelled taker in `baseline-v3.toml:43-44`). Adding a string key would only add hashed surface. The verify script asserts `fee_rate_entry == fee_rate_exit` in every v4 set. The 0.0005 rate itself: [ASSUMED], from the existing `fee_rate_exit` and audit F-005 secondary sources; Phase 12 replaces it with the account `commissionRate`.
2. **`partial_fill_fraction = 1.0` needs no loader fix in Phase 11.** `baseline-no-trade-v1.toml:54` and `baseline-simple-trend-v1.toml:56` already use it. The remaining "whole-number trap" is that `CostModel.cost_model_hash` hashes `Decimal(1)` as `"1"` while fixture dicts spelled `"1.0"` hash as `"1.0"` (`canonical.py`: Decimal -> `str(value)`), so `assert_cost_model_binds_registry` (`src/backtest/binding.py`) mismatches on spelling. Fix belongs to Phase 12/14 (cost model) and would change cost hashes; D-18 forbids doing it now. Record it as a follow-up in the DECISIONS/phase summary.
3. **`working_type` is optional in the loader** (absent in v1-v3), validated as one of `MARK_PRICE`, `CONTRACT_PRICE` (the two documented enum values, F2). Add loader tests: accepts `MARK_PRICE`; rejects `LAST` and empty; old sets still load with unchanged hashes (assert the v1-v3 hashes against the pins).
4. **Strategy version.** New sets change cost/execution assumptions: protocol §5 Immutability says "any behavior change requires a new parameter set and a strategy-version bump" and AMB-021 recommends bumping. Recommend `strategy_version = "v3.0.0"` for all v4/`-v2` sets. [ASSUMED]
5. **range-mr.** CONTEXT lists only trend-pullback and breakout-retest. `params/range-mr/baseline-v2.toml:47-49` has maker `fee_rate_entry = 0.0002`, no extended cost keys. D036/D038 say "all canonical cost sets", so add `params/range-mr/baseline-v4.toml` (uniform "v4 = D036-D038 aligned" naming; range-mr has no v3) built from `baseline-v2` plus the four extended cost keys. It needs the pin and the `_EXPECTED_CANDIDATE_IDS` update as well. [ASSUMED, Open Question 5]
6. **Old sets stay byte-identical.** See anti-pattern above; supersession note goes in the v4 file header (`# Supersedes baseline-v3 (D036-D038)`) and the DECISIONS row.

**Pin file and registry-gate (existing defect):** `registry-gate.yml` lines 30-83 iterate `params/**/*.toml`, key = `(parts[1], stem)`, and fail with `no pinned hash — register it` for anything absent from `tests/fixtures/phase4/parameters.json`. That file lists only `baseline-v1` for the three families (verified by reading it). Run locally this session: 3 PINNED, 7 NO-PIN (`breakout-retest` v2, v3; `range-mr` v2; `trend-pullback` no-trade-v1, simple-trend-v1, v2, v3). The gate is already red at HEAD (audit F-101). Consumers of that JSON: only the workflow (`tests/conftest.py:138` loads it as a `phase4_parameters` fixture; no test asserts its length). Recommended: append pins (schema `{"strategy_id","parameter_set_id","strategy_version","parameter_set_hash"}`) for the 5 new sets AND the 7 existing unpinned sets so the gate goes green, computing hashes from files with the loader. State it in the plan as a deliberate pin registration, not regeneration of an existing pin (the three `baseline-v1` pins must stay untouched). `paper_freeze_check.yml` pins `--parameter-set-id baseline-v3`; unaffected because the v3 hash is unchanged, and the pinned epoch is operator state. Leave it; Phase 16 re-pins.

### F7. Point-in-time universe manifest (D039, D-09)

- **Location.** Do not use `params/universe/`. `registry-gate.yml` would compute key `("universe", "research-universe-v1")`, find no pin and call `verify_parameter_set`, which requires `[strategy].strategy_id`; `src/adapters/analytics_files.py:172-176` `_family_ids()` treats every non-dot/underscore directory under `params/` as a strategy family; `tests/test_kill_gate_registration.py` (`registration_violations`) fails when `recorded_terminal` is non-null and `params/` gains a directory. Recommended: `docs/research/universe/research-universe-v1.toml`.
- **Content (DRAFT):**
```toml
schema = "research-universe/1"
status = "DRAFT"                       # FROZEN in Phase 13
top_n = 12                             # planner picks 10..15
rank_metric = "quote_volume_30d_usdt_trailing"   # D039: "by volume"
rank_date_source = "dataset_start_date"
include_delisted = true
selection_date = ""                    # filled at freeze
symbols = []                           # 10..15 unique USDT-margined perpetual symbols at freeze
live_universe_note = "live-5 list is a separate config; unchanged"
content_sha256 = ""                    # sha256_hex of {schema,rank_metric,top_n,selection_date,include_delisted,symbols}
```
- D039 fixes the list at the dataset start date, single list. The audit (F-024) suggested re-ranking at each walk-forward window start; D039 is the user decision and governs.
- Verify script: DRAFT -> required rule keys present, `symbols` empty or 10-15; FROZEN -> 10 <= len <= 15, unique, `selection_date` set, recomputed hash equals `content_sha256`. Hash with `src.domain.canonical.sha256_hex` (Node cannot reproduce it without reimplementing the canonicalizer).
- Protocol §1 line 60 (`Research universe: 10–15 sufficiently liquid Binance USDⓈ-M symbols`) and BACKTEST_SPEC §10.1 should reference the manifest and the point-in-time rule.

### F8. GLOSSARY §9 and `ApprovalResult` (F-110)

Emitted or defined in `src/` (grep + reads this session):

| Category | Values | Where |
|----------|--------|-------|
| `RejectionReason` enum, 23 members | NO_TRADE_REGIME, RR_TOO_LOW, STALE_SETUP, INVALIDATED, RISK_LIMIT, CORRELATED_RISK_LIMIT, DAILY_STOP, QUANTIZATION_REJECT, MIN_NOTIONAL_REJECT, INSUFFICIENT_MARGIN, EXCHANGE_CONSTRAINT, DATA_STALE, RECONCILIATION_REQUIRED, APPROVAL_EXPIRED, MIN_QTY_REJECT, NOTIONAL_REJECT, UTILIZATION_REJECT, CLUSTER_CAP_REJECT, AGGREGATE_CAP_REJECT, MAX_POSITIONS_REJECT, DAILY_STOP_BLOCK, STALE_CONSTRAINTS, UNCERTAIN_ACCOUNT_STATE | `src/domain/enums.py:122-156`; test `tests/test_domain_enums.py:189-227` hard-codes this set |
| Referenced as `RejectionReason.X` in non-enum code | INVALIDATED (25), DATA_STALE (14), NO_TRADE_REGIME (7), UNCERTAIN_ACCOUNT_STATE (6), EXCHANGE_CONSTRAINT (6), STALE_SETUP (4), RECONCILIATION_REQUIRED (4), STALE_CONSTRAINTS (3), RR_TOO_LOW (2), APPROVAL_EXPIRED (2), UTILIZATION_REJECT, NOTIONAL_REJECT, MIN_QTY_REJECT, MAX_POSITIONS_REJECT, DAILY_STOP_BLOCK, CLUSTER_CAP_REJECT, AGGREGATE_CAP_REJECT (1 each) | grep counts |
| Never referenced outside the enum | QUANTIZATION_REJECT, MIN_NOTIONAL_REJECT, RISK_LIMIT, CORRELATED_RISK_LIMIT, INSUFFICIENT_MARGIN; `DAILY_STOP` exists as `DailyState` value | grep returned no hits |
| String reason codes emitted but not in GLOSSARY | `"DISABLED"` (`src/execution/enablement.py:27`), `"ENTRY_WITHOUT_PROTECTIVE"` (`src/execution/manager.py:599`), `"NO_FILL"` (`manager.py:917`), `"HEALTH_CHECK_FAILED"` (`src/ops/health.py:611`), `"EXPIRED"` (`src/paper/journal.py:357`, `src/analytics/lifecycle.py:44`), `"OK"` (`src/backtest/simulator.py:387...`, `src/core/types.py:122`), `WARMUP_INSUFFICIENT`, `GAP_IN_SOURCE`, `INVALID_INPUT` (`src/core/types.py:123-125`) | reads |
| SAFE_MODE entry reasons (a separate vocabulary) | ENTRY_WITHOUT_PROTECTIVE, ORPHAN_PROTECTIVE, API_DEGRADATION, STALE_FEED, DB_FAILURE, MANUAL_CLOSE | `src/ops/drills.py:491-826`, `manager.py:1301`; also `REGISTRY_DIFF` (`src/paper/freeze.py:511`) |
| `ApprovalResult` | PENDING, APPROVED, SKIPPED, EXPIRED. Mapping `action_to_result` (`src/approval/binding.py:128-146`): APPROVE -> APPROVED; SKIP_USER, SKIP_BUSY, CANCEL -> SKIPPED; else -> PENDING (SIMULATE) | `enums.py:56-70`; SKIPPED merges SKIP_USER and SKIP_BUSY |

Proposed canonical collapse (Claude recommendation, [ASSUMED] pending Open Question 3; glossary is the source of truth, code rename is a follow-up in the owning phase):

| Synonym pair | Keep (emitted) | Deprecate (alias in GLOSSARY, not emitted) |
|--------------|---------------|-------------------------------------------|
| QUANTIZATION_REJECT vs MIN_QTY_REJECT/UTILIZATION_REJECT | MIN_QTY_REJECT, UTILIZATION_REJECT | QUANTIZATION_REJECT (RISK_MANAGEMENT §11 rule 3 must say UTILIZATION_REJECT) |
| MIN_NOTIONAL_REJECT vs NOTIONAL_REJECT | NOTIONAL_REJECT | MIN_NOTIONAL_REJECT |
| RISK_LIMIT vs AGGREGATE_CAP_REJECT / MAX_POSITIONS_REJECT | those two | RISK_LIMIT |
| CORRELATED_RISK_LIMIT vs CLUSTER_CAP_REJECT | CLUSTER_CAP_REJECT | CORRELATED_RISK_LIMIT |
| DAILY_STOP vs DAILY_STOP_BLOCK (as a reason) | DAILY_STOP_BLOCK; `DAILY_STOP` stays a `DailyState` value (GLOSSARY §8.1) | DAILY_STOP as a reason |

Add to GLOSSARY: a new `ApprovalResult` section (4 values, SKIPPED maps SKIP_USER/SKIP_BUSY/CANCEL, D-11 mapping); register `DISABLED`, `ENTRY_WITHOUT_PROTECTIVE`, `NO_FILL`, `HEALTH_CHECK_FAILED`, `EXPIRED` (paper/journal) as proposed canonical codes marked "in code, not yet in `RejectionReason`". Do not change `tests/test_domain_enums.py` in Phase 11 because the code enum is not renamed here. The follow-up rename (remove unused members, add emitted ones, update that test) needs an owner: record it in the DECISIONS summary row and ROADMAP; Phase 12 (risk/sizing) is the natural owner for the sizing codes, Phase 20 for `ENTRY_WITHOUT_PROTECTIVE`, Phase 26 or 24 for `DISABLED`/`HEALTH_CHECK_FAILED`. `tests/test_kill_gate_docs.py::test_glossary_tokens_match_enum` parses GLOSSARY §8.2 (heading `### 8.2 Canonical KillGateState (Phase 10, D-03)` and a `text` fence of 3 tokens): do not disturb that block.

### F9. New REQ-IDs (D-16, F-116, plus two ROADMAP-mandated)

Existing style (`REQUIREMENTS.md`): `- [ ] **AREA-NN**: sentence`, sections by area, traceability rows `| ID | Phase N | Pending |`, then a `**Coverage:**` block (`v1 requirements: 30 total`, `Mapped to phases: 30`, `Unmapped: 0`) and a `*Last updated:*` footer that must be updated. Existing prefixes: RSCH, DATA, DOMN, STRAT, RISK, BKTS, PAPER, APRV, EXEC, JRN, OPS, GOV. Highest current numbers: RISK-02, EXEC-03, OPS-02.

ROADMAP already says a new ID is to be added for the user-data stream (`ROADMAP.md:570`, Phase 18) and for operational alerts (`ROADMAP.md:624`, Phase 20). CONTEXT D-16 names only the F-116 items; include those two as well, otherwise the ROADMAP promise is left dangling.

| Proposed ID | Requirement text | Source | Phase (proposed) |
|-------------|------------------|--------|------------------|
| RISK-03 | A live protective stop is never loosened or removed while the position is open; any stop change is explicit, logged and permitted by the strategy/execution contract; automatic SL re-placement uses the original plan SL (never wider) | RISK_MANAGEMENT §6, D034 | 20 |
| RISK-04 | The system never increases risk because of prior losses or a missed target, and never adds to a losing position (no averaging down); at most one open position or resting entry per symbol | RISK_MANAGEMENT §7 (the "averaging down" wording is not in `docs/`; it comes from CONTEXT D-16; one-per-symbol is audit F-303, unratified) | 22 |
| EXEC-04 | The exact exchange constraint snapshot used for sizing (incl. MARKET_LOT_SIZE, PERCENT_PRICE, workingType, margin type, leverage, equity) is persisted per plan and revalidated when stale | RISK_MANAGEMENT §12, F-056, D035, D037 | 17 |
| EXEC-05 | Binance user-data stream (order, algo, account, position events) is consumed for fills and state, with REST as fallback | ROADMAP:570, F-104 | 18 |
| EXEC-06 | Manual emergency controls exist as an operator surface: cancel pending strategy orders, disable new entries, close strategy positions on explicit action, enter SAFE_MODE | EXECUTION_SPEC §11 | 20 |
| OPS-03 | Restart sequence: load config -> validate time -> reconcile Binance orders/positions -> reconnect streams -> verify no duplicate action -> resume only when consistent | SECURITY_AND_OPERATIONS §8 | 24 |
| OPS-04 | Health/diagnostic output includes runtime Python version and application git revision | SECURITY_AND_OPERATIONS §10 | 24 |
| OPS-05 | Operational alerts: the SECURITY_AND_OPERATIONS §5 catalogue (unprotected position, divergence, unknown order, duplicate attempt, stale data, rejected protective action, auth failure) plus DAILY_STOP/WARNING | ROADMAP:624, F-106 | 20 |
| OPS-06 | Secrets: outside source control, paper/test credentials separate from live, encrypted at rest or protected by the D042 control (see Open Question 7) | SECURITY_AND_OPERATIONS §1, D042 | 13 (storage) and 24 (credential separation) |

Other lost requirements the audit lists (§10.3: state-transition validation F-111, dropped entities F-112, live-enablement prerequisites F-105, experiment-record fields F-118, TP1/TP2/TIF params F-103, credential and key-permission check F-128) are outside CONTEXT D-16's list. Recommend the plan either add REQ-IDs for them (phases 17, 17, 26, 14, 19, 24) or record explicit DECISIONS exclusions; flag to the user as Open Question 6 rather than deciding silently.

### F10. Verification script

Model the output on `.planning/quick/260930-cgi-*/260930-cgi-verify.cjs` (PASS/FAIL line per gate, ends `ALL_PASS <mode>` or `FAILED n gate(s)`, exit 0/1, read-only). Recommend Python (`scripts/verify_decision_alignment.py`) rather than `.cjs`: hashing must reuse `sha256_hex`. D-17 says "in the style of", so this is compliant. Assertions:
1. Protocol header version equals the version named in a DECISIONS row `protocol v<V> frozen` and in the DOC_STATUS index line; `Supersedes: v1.0.1`; D030 kill-gate section unchanged (compare to a pinned sha256 of the section text captured at plan time).
2. Protocol §4 contains the six D-03 numbers and no remaining `remain \`TBD\`` for acceptance thresholds; contains "may reject" and no phrase letting a human pass a failing candidate.
3. `grep -r "no new live order placement" docs` -> 0 hits; `grep -rn "HMAC-checked" docs AGENTS.md .planning/research/STACK.md` -> 0 hits.
4. `200 ... per symbol` absent in `docs/trading/EXECUTION_SPEC.md`; algo status subsection and WS split present; `MARKET_LOT_SIZE` and `PERCENT_PRICE` present in RISK_MANAGEMENT §12.
5. Each v4 set: `partial_fill_fraction == 1`, `working_type == "MARK_PRICE"`, `fee_rate_entry == fee_rate_exit`; old v1-v3 hashes equal the pin file.
6. Universe manifest per F7; `holdout_consumed.json` schema valid, no forbidden keys.
7. GLOSSARY §9: no duplicate/synonym pairs from the table in F8; `ApprovalResult` section present; every string-emitted code registered.
8. REQUIREMENTS: each new ID present in the list and the traceability table; coverage counts updated.
9. DECISIONS: no blank line inside the table; rows D043/D044 exist; DOC_STATUS bumped.
Wire via `tests/test_decision_alignment.py` (calls the script's functions) and append the file to the `registry-gate.yml` pytest line (`uv run pytest tests/test_registry_gate.py tests/test_registry.py -q`, lines 85-89) so it runs on CI. Also add `tests/test_kill_gate_docs.py` and `tests/test_kill_gate_clock.py` to that line, since they guard the freeze witnesses.

## Common Pitfalls

### Pitfall 1: Version-blind freeze gate passes a half-frozen v1.1.0
**What goes wrong:** header says v1.1.0, no v1.1.0 DECISIONS row, CI still green.
**Why:** witness 3 regex is satisfied by the D029 row (F3).
**Avoid:** version-bound checks plus the negative test (F3).
**Warning sign:** the negative test "missing v1.1.0 DECISIONS row" exits 0.

### Pitfall 2: Pinned tests break on header bump
**What goes wrong:** `test_kill_gate_docs.py` lines 39-41, 84, 115-121 fail.
**Avoid:** update in the same commit; do not regenerate any pin to get green.

### Pitfall 3: Manifest under `params/` breaks three consumers
See F7. **Avoid:** `docs/research/universe/`.

### Pitfall 4: `working_type` added only to `STRATEGY_KEYS`
Loads as DECIMAL key and rejects the string. **Avoid:** add to `STRING_KEYS` (plus allowed-value check) and never to `COST_KEYS`.

### Pitfall 5: New candidate set id disturbs family independence tests
`baseline-v4` counts as a candidate. **Avoid:** update `_EXPECTED_CANDIDATE_IDS` (F6). Dry-run confirms it is the only breakage.

### Pitfall 6: registry-gate red before you start
Seven unpinned sets fail the re-hash step today. **Avoid:** register pins for all sets in one explicit plan task and say so.

### Pitfall 7: Editing generated AGENTS.md text
`AGENTS.md:24-184` is generated from `.planning/research/STACK.md`. **Avoid:** edit the source, then AGENTS.md, and keep `<!-- GSD:... -->` markers intact.

### Pitfall 8: Binance's own docs disagree
`common-definition` still lists `MAX_NUM_ALGO_ORDERS` "on a symbol". **Avoid:** cite the dated changelog entry, note the stale page in SOURCES.md, keep the verify marker.

### Pitfall 9: D042 vs "encrypt secrets at rest"
D042 says secrets "live only in a permission-restricted .env"; SECURITY_AND_OPERATIONS.md:8 says `- Encrypt secrets at rest.` See Open Question 7.

### Pitfall 10: Audit disagrees with the user on workingType
Audit recommended CONTRACT_PRICE (report §20.5 Corrected Rule 15); user chose MARK_PRICE (D037). Docs and params follow D037. The API default is CONTRACT_PRICE (F2), so state "send `MARK_PRICE` explicitly".

### Pitfall 11: Clock restart by accident
Changing `Frozen on` resets the D013 6-month clock. **Avoid:** keep it and add `Amended on` unless the user says otherwise.

## Code Examples

### v4 parameter set (trend-pullback), differences from `baseline-v3.toml` only
```toml
# params/trend-pullback/baseline-v4.toml
# Supersedes baseline-v3 (D036-D038). Do not mutate; new behavior = new set + version bump.
schema_version = 1

[strategy]
strategy_id = "trend-pullback"
strategy_version = "v3.0.0"          # [ASSUMED] bump per protocol §5 Immutability

[parameters]
# ... all non-cost keys copied from baseline-v3 unchanged ...
fee_rate_entry = 0.0005               # D036 taker entry (== fee_rate_exit)
fee_rate_exit = 0.0005
partial_fill_fraction = 1.0           # D038; loads as int 1
working_type = "MARK_PRICE"           # D037; string key
```

### Minimal registry change (verified in scratch copy)
```python
# src/domain/registry.py: add to STRATEGY_KEYS and STRING_KEYS (NOT to COST_KEYS in src/backtest/costs.py)
        "partial_fill_fraction",
        "working_type",
        # Constraint-snapshot freshness (RISK_MANAGEMENT §12).
...
STRING_KEYS = frozenset({"funding_treatment","slippage_model","spread_fill_assumptions","working_type"})
# plus, in _check_param_types: reject values outside {"MARK_PRICE","CONTRACT_PRICE"} for working_type
```

### Version-bound witness additions (research-gate freeze step)
```bash
# after the existing witnesses; keep the existing `grep -E "...Frozen on..."` line verbatim
VER=$(sed -nE 's/^>\s*\*\*Protocol version:\*\*\s*v([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' "$PROTOCOL" | head -1)
[ -n "$VER" ] || { echo "::error::no Protocol version header"; exit 1; }
VER_RE=$(printf '%s' "$VER" | sed 's/\./\\./g')
grep -E "protocol v${VER_RE} frozen" docs/DECISIONS.md >/dev/null || { echo "::error::no DECISIONS row 'protocol v${VER} frozen'"; exit 1; }
grep -E "^- \`research/RESEARCH_PROTOCOL\.md\`.*v${VER_RE}" docs/DOC_STATUS.md >/dev/null || { echo "::error::DOC_STATUS not at v${VER}"; exit 1; }
```

## State of the Art

| Old | Current | When | Impact |
|-----|---------|------|--------|
| conditional orders via `/fapi/v1/order` | Algo Service `POST /fapi/v1/algoOrder` (`algoType=CONDITIONAL`) | 2025-12-09 | ALGO_UPDATE carries rejection reason |
| `MAX_NUM_ALGO_ORDERS` filter (per symbol) | 200 across all symbols, filter removed | 2025-12-29 | count account-wide |
| single `wss://fstream.binance.com/ws` | `/public`, `/market`, `/private` | legacy retired 2026-04-23 | silent sockets on legacy URL |
| `CONDITIONAL_ORDER_TRIGGER_REJECT` | reasons inside `ALGO_UPDATE` | 2025-12-15 | reconciler parses ALGO_UPDATE |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Taker rate 0.0005 is a fair research entry fee | F6 | cost bias; Phase 12 replaces with account commissionRate |
| A2 | v4 sets use `strategy_version = "v3.0.0"` | F6 | naming only; hashes bake the string |
| A3 | Trade frequency 0.5-2 fills per symbol-month, 12 symbols, 24-month depth | F5 | floor may still be unreachable or overly easy; only Phase 14+ data can tell |
| A4 | σ = 1.2R for power figures (from BACKTEST_SPEC example) | F5 | power table shifts |
| A5 | Keep `Frozen on: 2026-09-19`, add `Amended on` | F3 | wrong if user wants the 6-month clock restarted |
| A6 | Canonical quantization order = code order | F4 | user may prefer utilization-first; would need code change |
| A7 | GLOSSARY keeps fine-grained codes, deprecates the five synonyms | F8 | different canonical pick changes follow-up rename scope |
| A8 | Holm scope (per family vs union of families) | F3 | residual family-wise error 14% vs 5% across three families |
| A9 | Phase assignment for new REQ-IDs | F9 | traceability misroute |
| A10 | D042 permission-restricted `.env` replaces "encrypt at rest" | F9 / Pitfall 9 | security posture gap if unratified |
| A11 | Include `range-mr/baseline-v4.toml` | F6 | scope creep vs incomplete D036/D038 coverage |
| A12 | Manifest at `docs/research/universe/` | F7 | none functionally; CONTEXT default path is unsafe |
| A13 | Algo status wording from a search snippet of an official page | F2 | re-open page before writing final text |
| A14 | 4 walk-forward folds, Dev 40% / Validation 40% / Holdout 20% | F3 | ratios were "ranges to explore" in v1.0.1 |
| A15 | >= 4 years dataset depth target for Phase 13 | F5 | Binance history/delisted klines availability unverified |
| A16 | TradingView scheme URL-path secret + IP allow-list is an audit design recommendation; V1 has no webhook | F1 #18 | user may want a different scheme (AMB-039) |

## Open Questions

1. **Does the kill-gate 6-month clock restart at v1.1.0?**
   - Known: `Frozen on` is the clock start (`src/analytics/clock.py`); audit report §20.6 lists it as an unanswered human question.
   - Recommendation: keep `Frozen on: 2026-09-19`, add `Amended on`; ask the user before changing.
2. **Holm scope: per family (D-03 default) or across all families' variants?**
   - Known: one family is selected as V1, so selection across three families is a further multiple-testing layer; per-family alpha 0.05 x 3 gives up to ~14% residual false-pass (1-0.95^3); union m<=75 is much stricter (F5 table).
   - Recommendation: state the scope explicitly in the freeze; default to per-family as D-03 says, record the residual, or pool if the user prefers. Decide before freeze (one-way).
3. **GLOSSARY canonical code per synonym pair.** Recommendation in F8; confirm.
4. **D-08 vs D-06 on marking old sets.** Marking old TOML files is an in-place edit. Recommendation: header note in v4 file + DECISIONS row; leave old files byte-identical.
5. **Include range-mr `baseline-v4`?** Recommendation yes (D036/D038 "all canonical cost sets").
6. **Lost requirements beyond D-16's list (F-105, F-111, F-112, F-118, F-103, F-128) and dropped entities.** Add REQ-IDs or write DECISIONS exclusions; the user should choose (esp. F-112 `trades`, `feature_snapshots`, `experiment_runs`).
7. **"Encrypt secrets at rest" vs D042's permission-restricted `.env`.** Recommendation: amend SECURITY_AND_OPERATIONS §1 to the D042 control (0600 `.env`, provider disk encryption), record the exclusion of application-level encryption for V1 in DECISIONS; needs user confirmation.
8. **Liquidation buffer number (D035).** D035 gives none; docs should say "with a buffer (a registry parameter)" and leave the value to Phase 22.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | tests, verify script | yes | 3.13.15 (`.venv`); system Python is 3.14.3 (do not use) | — |
| uv | CI parity | yes | 0.12.20 | run via `.venv/Scripts/python -m pytest` |
| bash | negative gate test | yes | Git Bash | skip test if absent |
| node | optional `.cjs` verify | yes | v24.18.0 | Python script |
| PyYAML | YAML parsing | no | — | regex extraction |
| gh CLI | CI status | no | — | inspect workflows by reading |
| Network (WebFetch) | Binance/TradingView facts | yes | pages returned; `Event-Algo-Order-Update` returns only the docs shell | WebSearch snippet, SDK source |

Note: `pytest` under Windows warns it cannot write `.pytest_cache` (permission); use `-p no:cacheprovider`. Tests were run from the venv with `PYTHONPATH=.` in a scratch copy; the repo suite passed there except the single expected `_EXPECTED_CANDIDATE_IDS` failure.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9 (`pyproject.toml` `testpaths = ["tests"]`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `.venv/Scripts/python -m pytest tests/test_kill_gate_docs.py tests/test_kill_gate_clock.py tests/test_kill_gate_registration.py tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py tests/test_decision_alignment.py tests/test_research_gate_negative.py -q -p no:cacheprovider` |
| Full suite command | `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider` (takes a few minutes; CI uses `uv run pytest`) |
| Script | `.venv/Scripts/python scripts/verify_decision_alignment.py all` |

### Phase Requirements -> Test Map
| Req | Behavior | Test type | Automated command | File exists? |
|-----|----------|-----------|-------------------|-------------|
| RSCH-01 | header, DECISIONS row, DOC_STATUS agree at v1.1.0; D030 section unchanged; numbers present | unit | `pytest tests/test_kill_gate_docs.py tests/test_decision_alignment.py -q` | updated / Wave 0 |
| RSCH-01 | gate fails when any witness is missing | integration (bash) | `pytest tests/test_research_gate_negative.py -q` | Wave 0 |
| RSCH-02 | family independence unaffected by v4 sets | unit | `pytest tests/test_analytics_files.py -q` | update expected ids |
| RSCH-01/DOMN-02 | v4 sets load, pinned, old hashes unchanged | unit | `pytest tests/test_registry.py tests/test_registry_gate.py -q` plus new loader tests | add tests |
| RISK-02 | daily loss, margin, quantization order text present; no stale wording | script | `verify_decision_alignment.py docs` | Wave 0 |
| EXEC-02 / OPS-01 | SAFE_MODE entries-only; 200 account-wide; algo semantics; WS split | script | `verify_decision_alignment.py docs` | Wave 0 |
| F-110 | GLOSSARY has no synonym pairs; ApprovalResult listed | script | `verify_decision_alignment.py glossary` | Wave 0 |
| F-116 | new IDs in list and traceability | script | `verify_decision_alignment.py reqs` | Wave 0 |
| D039 | manifest schema and hash | script | `verify_decision_alignment.py universe` | Wave 0 |

### Sampling Rate
- **Per task commit:** the quick run command above (under 30 s except imports).
- **Per wave merge:** full suite.
- **Phase gate:** full suite green plus `verify_decision_alignment.py all` prints `ALL_PASS all`, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_decision_alignment.py` and `scripts/verify_decision_alignment.py`
- [ ] `tests/test_research_gate_negative.py`
- [ ] loader tests for `working_type` (accept `MARK_PRICE`, reject `LAST`/empty, old sets unchanged) in `tests/test_registry.py`
- [ ] new pins in `tests/fixtures/phase4/parameters.json` (5 new + 7 existing unpinned)
- [ ] `_EXPECTED_CANDIDATE_IDS` update in `tests/test_analytics_files.py`

## Security Domain

`security_enforcement` is enabled in `.planning/config.json` (`security_asvs_level: 1`). This phase changes documentation and parameter files only; no runtime code beyond a whitelist key in the loader.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | docs only | TradingView webhook auth described (URL-path secret + IP allow-list); not implemented |
| V5 Input Validation | yes (small) | loader rejects unknown keys and bad `working_type` values (fail closed) |
| V6 Cryptography | docs only | secrets-at-rest wording reconciled with D042; use `sha256_hex`, never a new hash |
| V14 Configuration | yes | pins for every param set; no secrets in committed TOML/JSON |

| Threat | STRIDE | Mitigation |
|--------|--------|-----------|
| Silent parameter mutation | Tampering | pin file + registry-gate; old sets untouched |
| Forged/half-frozen protocol | Tampering / Repudiation | version-bound three-witness gate + negative test |
| Holdout re-use | Tampering | append-only consumed marker; verify script schema check |
| Unauthenticated webhook | Spoofing | doc-level scheme; no implementation in V1 |
| Stale exchange facts driving code | Tampering | dated URLs in SOURCES.md, "verify before implementation" markers |

## Sources

### Primary (HIGH)
- Repo files read this session: `.planning/phases/11-decision-alignment/11-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` (Phase 11-27), `.planning/STATE.md`, `.planning/config.json`, `docs/DECISIONS.md`, `docs/DOC_STATUS.md`, `docs/GLOSSARY.md`, `docs/research/RESEARCH_PROTOCOL.md`, `docs/trading/{RISK_MANAGEMENT,EXECUTION_SPEC}.md`, `docs/operations/{SECURITY_AND_OPERATIONS,RUNBOOK}.md`, `docs/integration/{BINANCE,TRADINGVIEW}.md`, `docs/backtest/BACKTEST_SPEC.md`, `docs/data/DATA_MODEL.md`, `docs/configuration/CONFIGURATION.md`, `.github/workflows/{research-gate,registry-gate,paper_freeze_check}.yml`, `src/domain/{registry,canonical,enums}.py`, `src/backtest/{costs,binding}.py`, `src/risk/quantization.py`, `src/approval/binding.py`, `src/analytics/{clock,family}.py`, `params/**/*.toml`, `tests/test_kill_gate_{docs,clock,registration}.py`, `tests/test_domain_enums.py`, `tests/fixtures/phase4/parameters.json`, audit `findings.json` and `DEEP_AUDIT_REPORT.md` (§10, §19, §20)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/change-log (fetched 2026-09-30)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice (2026-09-30)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition (2026-09-30)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order (2026-09-30)
- https://www.tradingview.com/support/solutions/43000529348-about-webhooks/ (2026-09-30)

### Secondary (MEDIUM)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update (statuses via WebSearch summary of the official page; direct fetch returned only the shell)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Algo-Order (fetch showed only NEW/CANCELED/EXPIRED in examples; no FINISHED text)

### Tertiary (LOW)
- Trade-frequency and dataset-depth estimates (F5): assumption only.
- Fee tier 0.02%/0.05% (audit F-005, secondary sources).

## Project Constraints (from CLAUDE.md / AGENTS.md)

`CLAUDE.md` does not exist in the repo; global `~/.claude/CLAUDE.md` only adds CodeGraph guidance (`.codegraph/` exists; I read files directly and used grep because the answers needed exact line text). `AGENTS.md` directives that bind this phase:
- No AI/LLM in the decision path; determinism (same inputs -> same decision); byte-equivalent outputs.
- Exchange facts must be re-verified against current official docs, never hard-coded from memory (this is why F2 records URLs and dates).
- Quantization: floor to stepSize, then the checks, NO_TRADE over round-up, identical logic in backtest/paper/live (order text in AGENTS.md:18 needs alignment with F4).
- Fail closed; SAFE_MODE blocks entries while monitoring/reconciliation continue (AGENTS.md:18 already says this; the docs must catch up).
- Use `Decimal` for exchange-sensitive values; pinned stable dependencies (no new dependencies here).
- GSD workflow enforcement: make repo edits through a GSD command (`/gsd-execute-phase`).
- Do not take AGENTS.md text as authoritative over `docs/` or DECISIONS (D031); edit its generated block via `.planning/research/STACK.md`.

## Metadata

**Confidence breakdown:**
- Standard stack / repo mechanics: HIGH. Every file read; loader and full-suite behavior reproduced in a scratch copy.
- Binance facts: MEDIUM-HIGH. Four official pages fetched; algo status text via search snippet only.
- Doc amendment inventory: HIGH for line references; wording choices are recommendations.
- D-03 feasibility: LOW-MEDIUM. Arithmetic is exact; trade frequency inputs are assumptions.

**Research date:** 2026-09-30
**Valid until:** 2026-10-30 for repo facts (files change with each plan); Binance facts 30 days (fast-moving: changelog entries in Nov 2025, Dec 2025, Mar 2026).
