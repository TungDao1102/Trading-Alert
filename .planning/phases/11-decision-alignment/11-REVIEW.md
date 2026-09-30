---
phase: 11-decision-alignment
reviewed: 2026-09-30T00:00:00Z
depth: deep
files_reviewed: 49
files_reviewed_list:
  - .github/workflows/registry-gate.yml
  - .github/workflows/research-gate.yml
  - AGENTS.md
  - docs/DECISIONS.md
  - docs/DOC_STATUS.md
  - docs/GLOSSARY.md
  - docs/SOURCES.md
  - docs/architecture/ARCHITECTURE.md
  - docs/backtest/BACKTEST_SPEC.md
  - docs/configuration/CONFIGURATION.md
  - docs/data/DATA_MODEL.md
  - docs/integration/BINANCE.md
  - docs/integration/TRADINGVIEW.md
  - docs/operations/RUNBOOK.md
  - docs/operations/SECURITY_AND_OPERATIONS.md
  - docs/research/RESEARCH_PROTOCOL.md
  - docs/research/TRADING_STRATEGY_RESEARCH.md
  - docs/research/holdout_consumed.json
  - docs/research/universe/research-universe-v1.toml
  - docs/trading/EXECUTION_SPEC.md
  - docs/trading/RISK_MANAGEMENT.md
  - docs/trading/SIGNAL_AND_ALERTS.md
  - params/breakout-retest/baseline-v4.toml
  - params/range-mr/baseline-v4.toml
  - params/trend-pullback/baseline-no-trade-v2.toml
  - params/trend-pullback/baseline-simple-trend-v2.toml
  - params/trend-pullback/baseline-v4.toml
  - scripts/decision_alignment/authority.py
  - scripts/decision_alignment/bookkeeping.py
  - scripts/decision_alignment/exchange.py
  - scripts/decision_alignment/ops_risk.py
  - scripts/decision_alignment/params.py
  - scripts/decision_alignment/protocol.py
  - scripts/decision_alignment/universe.py
  - scripts/verify_decision_alignment.py
  - src/domain/registry.py
  - tests/fixtures/phase4/parameters.json
  - tests/test_analytics_files.py
  - tests/test_decision_alignment.py
  - tests/test_decision_alignment_authority.py
  - tests/test_decision_alignment_bookkeeping.py
  - tests/test_decision_alignment_exchange.py
  - tests/test_decision_alignment_ops_risk.py
  - tests/test_decision_alignment_params.py
  - tests/test_decision_alignment_protocol.py
  - tests/test_decision_alignment_universe.py
  - tests/test_kill_gate_docs.py
  - tests/test_registry.py
  - tests/test_research_gate_negative.py
findings:
  critical: 0
  warning: 12
  info: 8
  total: 20
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-09-30
**Depth:** deep
**Files Reviewed:** 49
**Status:** issues_found

## Summary

Phase 11 is a docs, parameter and gate-script phase. I ran `scripts/verify_decision_alignment.py all` on the working tree: all 64 gates print PASS. I also probed the gate functions with adversarial input. The parameter and registry side is sound:

- The ten old files are byte-locked and their hashes are locked.
- `working_type` is not a cost key, so `cost_model_hash` is unaffected.
- The five new sets share one cost hash.
- CRLF handling is correct in every gate module.
- The `add_months` freeze clock is unchanged: 2026-09-19 plus 6 months is 2027-03-19, as D043 states.

I found no BLOCKER. The defects fall into four groups.

1. **Time-bomb gates.** Several gates and tests pin the 2026-09-30 snapshot. They will turn CI red on the next legitimate change, including changes the phase itself schedules as follow-ups.
2. **Vacuous or over-lenient phrase gates.** I demonstrated this by probing: AU-01, AU-06, EX-06 and OR-09 accept text they are meant to reject. As a result, the old quantization order still sits in `AGENTS.md`.
3. **CI shallow clone.** Most negative tests silently skip in CI because they need a git commit that a shallow clone does not have.
4. **Docs versus src.** Some documents describe not-yet-built behaviour in the present tense. Some registry values are accepted but not honoured by any code.

## Warnings

### WR-01: CI shallow clone silently skips the phase's negative tests

**File:** `.github/workflows/registry-gate.yml:17`, `tests/test_decision_alignment_authority.py:17-42` (same pattern in `_bookkeeping.py:18`, `_exchange.py:17`, `_ops_risk.py:17`)
**Issue:** The negative tests in four modules (27 call sites of `_old(...)`) run `git show 679825c:<file>` and call `pytest.skip(...)` when the commit is missing. The workflow uses `actions/checkout@v4` with default `fetch-depth: 1`, so commit `679825c` does not exist in CI. Those tests skip, and the pytest run stays green. The "Registry negative tests (fail-closed gates must hold)" step therefore does not exercise the pre-change-text negatives that prove the gates can fail. The tests also use a 7-character abbreviated SHA, which can become ambiguous.
**Fix:** Either add `with: { fetch-depth: 0 }` to the checkout step, or vendor the pre-change snippets as fixtures under `tests/fixtures/phase11/` so the tests need no git history. Also make CI fail on skips, for example `-p no:cacheprovider -W error` plus a check that the skipped count is 0 for `tests/test_decision_alignment*.py`. Use the full 40-character SHA.

### WR-02: Gates pin the 2026-09-30 snapshot and will fail on legitimate follow-up work

**File:** `scripts/decision_alignment/bookkeeping.py:266-275, 287, 334, 351, 417-428`; `scripts/decision_alignment/protocol.py:159`; `tests/test_decision_alignment_protocol.py:109-113`; `tests/test_kill_gate_docs.py`
**Issue:** `registry-gate` runs `verify_decision_alignment.py all` on every push and PR to master. The following checks are hard-wired to today's state:
- RQ-01 requires all 13 new requirements to be `Pending`. OPS-06 belongs to Phase 13, so completing Phase 13 turns RQ-01 red.
- RQ-02 requires the totals `(43, 43, 0)`.
- RQ-05 requires the footer line `*Last updated: 2026-09-30`. Any later REQUIREMENTS.md update breaks it.
- DC-02 requires exactly D001..D045 (`LAST_DECISION = 45`). D044 follow-up (2) says the cost-hash fix "needs its own DECISIONS entry", so D046 is already planned.
- GL-03 requires the five aliases to stay in the enum. The Phase 12 enum cleanup, which D044 schedules, will fail it.
- PR-02 requires `Supersedes == "v1.0.1"`. A v1.2.0 amendment, the process the protocol prescribes, would fail it.
- `test_holdout_real_marker_is_valid_and_empty` asserts `entries == []`. The first legitimately consumed holdout entry breaks it.

`RQ-*` and `AU-*` also read `.planning/REQUIREMENTS.md`, `ROADMAP.md`, `PROJECT.md` and `research/STACK.md`. `/gsd-complete-milestone` archives and rewrites these files, and `/gsd-pr-branch` filters `.planning/` out of PR branches. Either action raises `FileNotFoundError` and makes CI red.
**Fix:** Test invariants, not snapshots:
- RQ-01: a requirement ID appears once as a list item and once as a trace row. Do not test status or date.
- RQ-02: the coverage counts equal the counts derived from the list.
- DC-02: IDs are contiguous from D001, with no duplicates and none missing. Do not pin the last ID.
- PR-02: `Supersedes` matches `v\d+\.\d+\.\d+`.
- Drop the emptiness assertion on `holdout_consumed.json`.
- Gate the `.planning`-dependent gates on file existence with an explicit SKIP, or move them out of the CI-blocking `all` mode.

### WR-03: EX-06 counts "Not fetched" rows as grounded sources

**File:** `scripts/decision_alignment/exchange.py:205-238`, `docs/SOURCES.md:39-47`
**Issue:** `registered_urls` accepts a row when `FETCH_DATE in cells[2]` and `cells[3]` is non-empty. The Change-Position-Mode, Connect and user-data-streams rows are dated 2026-09-30 in the "Fetched" column, yet their Method cell says "Not fetched: curl ... 302 ... HTTP 202 empty body". Probe: a spec citing `https://developers.binance.com/docs/x/y`, with a register row whose method is "Not fetched: 404", returns `('EX-06', True, 'ok')`. D-14 and the SOURCES intro say each fact must be grounded in a page listed there, so EX-06 passes without confirming that any page was read. The "Fetched" column also carries a date for pages that were not fetched, which misleads readers.
**Fix:** Keep an explicit `Status` (`fetched` | `not-fetched`) and require `fetched` for URLs that back facts. Make `not-fetched` URLs pass only when the citing sentence carries the verify marker. Leave the "Fetched" cell empty or write "n/a" for pages that were not fetched.

### WR-04: The old quantization order is still in AGENTS.md and STACK.md, and AU-06 cannot see it

**File:** `AGENTS.md:153`, `.planning/research/STACK.md:141`, `scripts/decision_alignment/authority.py:63`
**Issue:** D031 fixes one order: stepSize, min quantity, min notional, then utilization. `AGENTS.md:153` (and its source `STACK.md:141`) still says "quantization floor → realized-risk check → min-qty/notional gates". This is the pre-decision order, and it sits in the file every agent reads. AU-06 matches only the exact string `realized-risk check (60% baseline) → min-qty/notional reject`. Probe: `check_no_old_order({"AGENTS.md": "quantization floor → realized-risk check → min-qty/notional gates"})` returns `('AU-06', True, 'ok')`. Gate AU-03 compares only the FastAPI row, so it never sees this line drift either. `.planning/research/PITFALLS.md:157` and `FEATURES.md` carry `QUANTIZATION_REJECT` and the old order too, but these are outside the gate's scope.
**Fix:** Change the sentence in STACK.md, regenerate the AGENTS.md row, and widen AU-06. For example, flag any single line where `realized-risk` precedes `min-qty|min quantity|notional`: `r"realized[- ]risk[^\n]{0,40}(→|->)[^\n]{0,20}min[- ](qty|quantity|notional)"`. Or scan `AGENTS.md` and `STACK.md` line by line for the sequence "realized-risk check" followed by "min-qty".

### WR-05: Several "phrase present anywhere in the section" gates cannot fail on the defects they are named for

**File:** `scripts/decision_alignment/ops_risk.py:337-347`; `scripts/decision_alignment/exchange.py:119-136`; `scripts/decision_alignment/authority.py:33,97`
**Issue:** Probes show that the following pass on wrong or stale text:
- **OR-09** `check_data_model_plan_fields` collects the first token of every line as a "field". A prose line such as `constraint_snapshot_json is not persisted` satisfies it, so the gate does not check that the fields are in the `trade_plans` field list.
- **AU-01** `HMAC_CLAIM = "HMAC-checked"` matches only that exact spelling. "HMAC-verified", "HMAC checked" and "HMAC signature check" are not detected.
- **EX-02** requires `NEW`, `FINISHED`, `EXPIRED` and `REJECTED` as bare case-sensitive substrings. The test suite itself excludes `NEW` and `FINISHED` from the "each phrase is required" test because they appear elsewhere. The status table rows are therefore not checked.
- **OR-10a** looks for `taker`, `MARK_PRICE` and similar tokens anywhere in the whole CONFIGURATION.md, not in section 10.
**Fix:** Parse the structure the gate is about. For OR-09, restrict to lines inside the fenced `text` block of section 2.4. For EX-02, parse the status table rows with a `| \`STATUS\` |` regex. For AU-01, use `re.compile(r"HMAC[- ]?(checked|verif\w*|signature|signed)", re.I)` over lines that also mention webhook or TradingView. For OR-10a, scope to section 10.

### WR-06: The frozen universe manifest is self-hashed only, so a post-freeze edit is not tamper-evident

**File:** `scripts/decision_alignment/universe.py:72-87, 120-129, 195-199`
**Issue:** The point of D039 is that the symbol list is fixed and hashed before evaluation. UN-02 recomputes the hash from the same file's content, so editing `symbols` and re-running the CLI to refresh `content_sha256` produces a passing gate. `params/` differs: the pin file `tests/fixtures/phase4/parameters.json` holds hashes separately from the TOMLs, and PA-03 hardcodes the old hashes. No equivalent second witness exists for the universe. Protocol section 1 says the experiment record carries the hash, but no gate compares the two.
**Fix:** When Phase 13 freezes, also record `content_sha256` in a second place (the protocol, or a DECISIONS row) and add a gate that requires the manifest hash to equal that value. Alternatively store a `FROZEN_HASHES` constant, like `PRE_PHASE_HASHES`, in the gate module, checked in a separate commit.

### WR-07: The RUNBOOK and SECURITY_AND_OPERATIONS describe the D034 ladder in the present tense, but the code does the opposite

**File:** `docs/operations/RUNBOOK.md:40-42`, `docs/operations/SECURITY_AND_OPERATIONS.md:84-85`; contradicted by `src/execution/fill_monitor.py:24` and `src/execution/manager.py:566-568`
**Issue:** The RUNBOOK says a missing stop-loss is "automatically re-place[d]" and "manual intervention is optional, not required". SECURITY_AND_OPERATIONS section 7 says the same. `fill_monitor.py:24` says "The monitor never places rescue stops". `manager.py` responds to an entry without a stop by entering SAFE_MODE and waiting. ROADMAP places the auto re-place in Phase 20 (line 56, 642). An operator following the RUNBOOK today would wait for an automation that does not exist, with a position unprotected. The OR-01 gate makes it worse: it enforces the present-tense wording and would fail if someone added a "planned" caveat. The phrase list needs `automatically re-placed`, and the forbidden list still demands `not an orphan`.
**Fix:** Add a "Target behaviour (D034), implemented in Phase 20; until then the operator must place the stop manually" line in both documents. Relax the OR-01 phrase set so the caveat can coexist.

### WR-08: `working_type` is accepted and hashed into parameter-set identity, but no code honours it

**File:** `src/domain/registry.py:115-121, 311-315`, `src/execution/placement.py:325,437,450`, `src/execution/manager.py:558`
**Issue:** The registry now accepts `working_type` = `MARK_PRICE` or `CONTRACT_PRICE` and includes it in `parameter_set_hash`. Live placement hardcodes `"working_type": "MARK_PRICE"`, and no `src/backtest` or `src/paper` code reads it. A set that declares `CONTRACT_PRICE` loads, hashes and pins successfully, yet live still uses MARK_PRICE. The identity claims something the engine ignores, which is the same class of defect D038 warns about. D037 also says the `CONTRACT_PRICE` alternative "is not adopted", but the whitelist permits it. The protocol (section 3, frozen) states backtest, paper and live "share one trigger price series"; the current backtest simulator uses last-price candles. D044 follow-ups do not list this item; the Phase 14 roadmap line does.
**Fix:** Until the consumers exist, restrict `WORKING_TYPE_VALUES` to `{"MARK_PRICE"}`. Or make the placement and simulator code read the plan's `working_type` and fail closed on any mismatch. Add a D044 follow-up naming the owner phases (14 and 19).

### WR-09: EXECUTION_SPEC section 11 lists "cancel pending strategy orders" without excluding protective stops

**File:** `docs/trading/EXECUTION_SPEC.md:171-180`
**Issue:** The control list starts with "cancel pending strategy orders", which can be read to include the SL/TP orders. The D034 sentence added below it says "the controls above only stop the system from opening or adding to risk". That is false for "close strategy-generated positions" and for cancelling a protective stop. EX-05 checks only that some phrases exist and that "disable new live orders" is absent. It cannot catch this ambiguity, and an operator reading the spec might cancel protection.
**Fix:** Reword: "cancel pending entry orders (protective stops and take-profits are never cancelled by this control)". Change the sentence below it to "a disable never blocks protective or reduce-only orders; close and protect actions are separate, explicit actions".

### WR-10: Protocol G5 has no trade-count floor, so a lucky handful of trades can pass the single-use holdout

**File:** `docs/research/RESEARCH_PROTOCOL.md:225`
**Issue:** G5 passes when mean net R is above 0 and drawdown is at most 20% on the holdout "(trade count reported, no floor)". One or two winning trades pass. The holdout is the one unbiased test, so this weakens the whole G1-G5 chain. The section also says "A pre-registered value changes only by a new protocol version (v1.2.0)", so once results exist the floor cannot be added. G1 caps false passes on Validation, but nothing constrains holdout size. D043 acknowledges only that the G1 floor "may be unreachable". Separately, D043 says the user may override any number before the first Validation run, while the protocol requires v1.2.0 plus a new lineage for any change. The two texts disagree on the override procedure.
**Fix:** Before the first Validation run, decide the G5 rule. For example, require the holdout trade count to be at least the expected count from the Validation trade rate at a stated fraction (say 50%). Or require the bootstrap lower bound above 0 on the holdout as well. Amend to v1.1.1 or v1.2.0 now and align the D043 override sentence with the protocol.

### WR-11: The alert example depends on an unstated reference price

**File:** `docs/trading/SIGNAL_AND_ALERTS.md:91-96, 111`
**Issue:** The example shows a zone entry of 103800-104050, SL 103250, TP1 105275 and TP2 106625, with "Expected R:R: 2.0 / 4.0", and the note says it satisfies `minimum_rr = 2.0`. It does so only at the zone midpoint 103925: risk 675, reward 1350 and 2700. If filled at the upper edge, 104050, R:R is 1225/800 = 1.53, below `minimum_rr`. At the lower edge, 103800, it is 2.68. The zone-mid convention appears only in `src/risk/quantization.py` (zone-mid `entry_ref`). A reader cannot tell whether the R:R gate uses mid, worst-case or best-case entry. OR-10b only matches the literal strings, so it cannot catch this.
**Fix:** State the reference in the doc ("R:R computed at the zone midpoint 103925"). Or state whether the gate must hold at the worst-case fill of the zone, and change the numbers if it must.

### WR-12: `params.run()` mislabels and aborts on non-`ValueError` load errors

**File:** `scripts/decision_alignment/params.py:121-139, 247-252`
**Issue:** `check_pins` catches only `ParameterSetMutated`, `RegistrySchemaMismatch` and `StrategyKeyOutsideRegistry`. Other exceptions from `verify_parameter_set` propagate: `UnregisteredParameterSet` (raised for unsafe path segments) is not caught at all, and `tomllib.TOMLDecodeError` and `UnicodeDecodeError` are `ValueError` subclasses that `run()` catches and reports as "pin file unreadable" (wrong attribution). A syntax error in a single TOML therefore reports as a pin-file problem and skips the remaining sets. `UnregisteredParameterSet` aborts `run()` entirely, so PA-02..PA-06 never run. The failure is loud (`params-error`), but the diagnostic is wrong and everything after it is lost.
**Fix:** In the `verify_parameter_set` loop, catch `Exception` and record `f"{key}: {type(exc).__name__}: {exc}"` per file, as `check_old_hashes` already does. Keep the "pin file unreadable" branch for `load_pins()` only.

## Info

### IN-01: UN-03, UN-04 and UN-05 are largely tautological or duplicates

**File:** `scripts/decision_alignment/universe.py:204-217`
**Issue:** `MANIFEST_PATH.is_relative_to(UNIVERSE_DIR)` compares two constants derived from each other and is always true (I confirmed it returns True). UN-04 repeats a DRAFT check already in `_check_draft`, and UN-05 repeats the note check in `validate_manifest`. The five gates count as five but give about two independent checks. `EXPECTED_MIN["universe"] = 5` therefore does not guard what it looks like it guards.
**Fix:** Drop the tautology. Give UN-04 and UN-05 independent inputs, or fold them into UN-01 and lower the minimum.

### IN-02: `SYMBOL_RE` rejects legitimate Binance perpetual symbols

**File:** `scripts/decision_alignment/universe.py:43`
**Issue:** `^[A-Z0-9]+USDT$` rejects contracts with non-ASCII base names. The universe is meant to include later-delisted contracts, and such symbols have existed. A freeze that must contain one would fail UN-01 with a confusing message.
**Fix:** Relax to `^\S+USDT$` and validate against `exchangeInfo` at freeze time, or document the limitation in the Phase 13 handoff.

### IN-03: `candidate_sha256` is defined only in a verification script

**File:** `scripts/decision_alignment/protocol.py:107-115`
**Issue:** The protocol says `candidate_sha256` is "the hash of `strategy_id`, `strategy_version` and the candidate `parameter_set_hash`". The only formula is this helper in a script that is never imported by `src/`. Nothing in the document defines the serialization: canonical JSON of a three-key dict, key order, or spelling. Phase 26 will write the holdout marker from `src/`, and a re-implementation could hash differently. The helper is also unused by any gate.
**Fix:** Move it to `src/domain/` next to `sha256_hex`, or spell out the formula in protocol section 4.

### IN-04: The hash tables are triplicated

**File:** `scripts/decision_alignment/params.py:31-62`, `tests/test_registry.py:~790-810`, `tests/fixtures/phase4/parameters.json`
**Issue:** The ten pre-phase hashes live in three files. That is redundant, but a mismatch would fail loudly. The private `registry._parse_and_validate` is also called from a script (`params.py:177`).
**Fix:** Keep one source, or add a test asserting the tables are equal. Expose a public `parse_parameter_text` in `registry.py`.

### IN-05: A stale comment above `STRING_KEYS`

**File:** `src/domain/registry.py:277-288`
**Issue:** The comment says "string-valued cost-model keys", but `working_type` is a non-cost string key. The comment two lines above it (lines 110-114) says the opposite.
**Fix:** Reword to "string-valued keys (three cost keys plus working_type)".

### IN-06: Citations do not always support the claim beside them

**File:** `docs/operations/SECURITY_AND_OPERATIONS.md:32`, `docs/integration/TRADINGVIEW.md:44`, `docs/architecture/ARCHITECTURE.md:187`
**Issue:**
- The 24-hour WebSocket lifetime claim cites the `Important-WebSocket-Change-Notice` page. SOURCES records that page as backing the URL split, not the lifetime, and the `Connect` page as unfetched.
- TRADINGVIEW.md item 4 says TradingView "may occasionally deliver a webhook more than once". I fetched the cited "about webhooks" page and it says only that webhooks "may occasionally fail to reach the specified URL". It says nothing about duplicate delivery. (The 3-second timeout, ports 80 and 443, no IPv6, the four IPs and 2-factor authentication all check out.)
- ARCHITECTURE.md now points to a `Connect` URL that SOURCES says returned an empty body.
**Fix:** Cite the page that supports each claim, or drop the claim. Keep idempotent de-duplication as a design safeguard, and describe the duplicate-delivery risk as a design assumption, not as something TradingView documents.

### IN-07: The bash freeze witnesses in `research-gate.yml` are weaker than the Python versions

**File:** `.github/workflows/research-gate.yml:56, 62`
**Issue:** Witness 3 is `grep -E "protocol v${VER_RE} frozen" docs/DECISIONS.md`. It is not anchored to a table row, so any prose mention satisfies it. The Python version (`protocol.check_witnesses`) anchors to `^\| D\d+ \|`. `VER` uses `head -1` (first match) while Python's `_header` dictionary keeps the last match; the two disagree if the header ever repeats. The bash grep on line 30 has no anchor at the end of the line either.
**Fix:** Use `grep -E "^\| D[0-9]+ \| .*protocol v${VER_RE} frozen"` and make Python take the first match.

### IN-08: The power note is approximate

**File:** `docs/research/RESEARCH_PROTOCOL.md:233`
**Issue:** "With sigma about 1.2 R and Holm over 25 variants the trade floor detects only a large edge, about 0.35 R." With n = 100, SE = 0.12 and the smallest Holm threshold alpha/25 = 0.002 (z = 2.88), 0.35 R is the effect that reaches the threshold about half the time. 80% power needs roughly 0.45 R. The sentence understates the minimum detectable effect.
**Fix:** Say "about 0.35 R at 50% power, about 0.45 R at 80% power".

---

_Reviewed: 2026-09-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
