# Phase 18: Binance User-Data Stream + Exchange Error Taxonomy - Context

**Gathered:** 2026-10-15
**Status:** Ready for planning
**Mode:** --auto (recommended defaults chosen; the user may override any D-number before planning). Owner-only items are NOT decided here; they are listed under "Open, user-owned" and the planner must stop at a blocking-human checkpoint for each (D061 item H, D061 item I).
**Branch / worktree:** `phase-18` in `.claude/worktrees/phase-18`, created from `develop` at 6939c90 so Phase 16 can keep running on `develop`.
**Machine rule (user, 2026-10-15):** this machine has no Binance or Telegram connectivity. It runs discuss, research, plan and plan verification only; execute-phase, code, tests and every Binance/Telegram probe run on another machine. Plans must therefore be self-contained for an executor on a connected machine and cite only files inside the repository. On a connection error: one retry, then record the gap and stop; never guess or try other routes (memory: network-flaky-report-dont-retry).

<domain>
## Phase Boundary

The system learns fills, order and algo state, and account changes from Binance in real time, interprets exchange errors by numeric code (never by message text), and can target Binance Demo Trading safely. REST stays the fallback and the reconciliation authority.

Delivers (ROADMAP Phase 18, requirements EXEC-05, EXEC-01, EXEC-02, OPS-02):
1. A user-data stream: listenKey lifecycle (as the current docs require), `ORDER_TRADE_UPDATE`, `ALGO_UPDATE` (including `o.rm`), `ACCOUNT_UPDATE`, on the `/private` WS URL, feeding `fold_fills` and reconciliation (F-104, F-054).
2. An error taxonomy keyed on int `status_code` (-2011, -2013, -2019, -4164, -1021, -2021 and the rest of the list in D-09), replacing the regex-on-message fallbacks (F-501, F-205, F-503, F-502).
3. A client configuration layer: explicit REST timeouts, API key loading, Demo / testnet / live selection, recvWindow with a fail-closed server-time drift check, no retry on 418 and honoring `retry_after` (F-504, F-128, F-505, F-706, F-506).
4. A Demo probe (human-run on a connected machine) that records the actual not-found codes, the duplicate `clientAlgoId` code, id reuse after FILLED or CANCELED, and the D055 protective-stop cases. Phase 17's `BinanceSemanticsFakeAdapter` is corrected if the probe disagrees.

Out of scope (other phases): symbol/side/qty binding and the live-price check (19); reconcile loop logic, SAFE_MODE exit rules and the auto SL re-place (20); Binance-canonical equity and daily loss (21); leverage, margin and liquidation guard (22); composing the stream into a running process and the Demo/live evidence runs (24, 25); closing the D055 execution model (a user decision recorded as a new DECISIONS row).

</domain>

<decisions>
## Implementation Decisions

### Stream architecture
- **D-01:** The stream lives in a new adapter module `src/adapters/binance_userdata.py` behind a project-owned interface (Protocol) in the style of `src/adapters/paper_ws.py`. SDK response and event models never leave the adapter; it emits frozen, SDK-free dataclasses (Decimal for money and quantity, UTC-aware datetimes, non-empty strings) exactly like the Phase 8 snapshots in `binance_usdm.py`. — **Reversibility:** costly — every Phase 19, 20 and 24 consumer will import these event types.
  - *Note (2026-10-16):* Superseded in part on 2026-10-16 by the user's record `decisions/18-DEC-D01-event-types.md` (option amend): `OrderUpdateEvent` also carries the optional `close_position`, `price_protect`, `activation_price`, `callback_rate` and `good_till_date_ms`; `AlgoUpdateEvent` also carries `stp_mode`, `price_match` and `good_till_date_ms`; every event dataclass is keyword-only and frozen, and the listenKey is never stored in an event.
- **D-02:** Use the official SDK `binance-sdk-derivatives-trading-usds-futures` (17.4.0 in `uv.lock`) for the `/private` socket and for the listenKey REST calls; direct HTTP/WS only for a gap the SDK cannot cover, and the research must say which of the two the SDK offers today (listenKey REST vs WS API user-data subscription). The listenKey lifecycle (start, keepalive, close, expiry handling) is implemented as documented on the live page at plan time, not from memory. SDK internals the stream depends on are pinned by a contract test in the style of `tests/test_paper_ws_contract.py`.
- **D-03:** One supervisor coroutine owns connect, keepalive, the 24-hour rotation, reconnect with bounded backoff (tenacity, capped attempts, never infinite on an order-relevant path), and a clean stop. It follows the structure of the Phase 16 `PaperSupervisor` where that fits, without importing from `src/paper`. A reconnect, a rotation or a missed keepalive marks the stream UNKNOWN for the duration of the gap and triggers a REST snapshot before any event after the gap is trusted.
- **D-04:** Composition into a running process is NOT in this phase. Phase 18 ships the library, a fake-driven test rig, and a connected-machine smoke script (`scripts/`), as Phase 16 did with `paper_ws_smoke.py`. Process wiring belongs to the phases that compose the runtime (24, 25).

### Event handling and state authority
- **D-05:** The stream is a low-latency hint plus evidence; Binance REST snapshots remain the authority (AGENTS.md exchange authority). Events never fabricate state: an event for an unknown order, a malformed payload, an unknown `algoStatus`, or a field that fails Decimal/UTC validation is journaled as a stream anomaly and surfaced as a divergence for the reconciler; it is never silently dropped or coerced (09-REVIEW WR-04 precedent in `fold_fills`).
- **D-06:** `ORDER_TRADE_UPDATE` becomes `FillEvent`s consumed by the existing `fold_fills` (`src/execution/fill_monitor.py`) with the unique key `(order_id, exchange_trade_id)`, so replays and out-of-order delivery stay idempotent. `commission` and `commissionAsset` are parsed and carried through (G3-009) so Phase 21 can use them; Phase 18 does not compute daily loss.
- **D-07:** `ALGO_UPDATE` is parsed into an algo-order event carrying `X` (algo status), `rm` (reject reason, the replacement for the removed `CONDITIONAL_ORDER_TRIGGER_REJECT`) and `ia`. The algo status classification (G2-028) is a documented table covering NEW, TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED: each value is classified ACTIVE, TERMINAL_OK, TERMINAL_FAILED or UNKNOWN and used by attach, reconcile and the sweeper; today `_ACTIVE_ALGO_STATUSES` is `{"NEW"}` only. An unseen status value classifies UNKNOWN (fail closed), never ACTIVE.
  - *Note (2026-10-16):* Superseded in part on 2026-10-16 by the user's record `decisions/18-DEC-O-18-01.md`: TRIGGERING, TRIGGERED, FINISHED and CANCELED are classified UNKNOWN (none is ACTIVE); NEW stays ACTIVE and REJECTED and EXPIRED stay TERMINAL_FAILED, so only NEW confirms protection; the table does not decide D055.
- **D-08:** `ACCOUNT_UPDATE` is parsed into balance and position deltas as events only. Wiring them into equity, margin or the position view is Phases 20 to 22. Moving an Order or Position out of UNKNOWN requires Binance evidence and the journal records the evidence source, REST reconcile or user-data event (G4-034); Order `exchange_status` and `exchange_order_id` updates get their store methods together with this first caller (G4-043). Persisted stream events use the existing append-only journal; no new table unless the planner shows the journal cannot hold them.

### Error taxonomy
- **D-09:** A pure module (placed under `src/adapters/` or `src/domain/`, planner's choice, no SDK import in the pure part) maps an int Binance `status_code` to a project category. Required codes: -2011, -2013, -2019, -4164, -1021, -2021 (ROADMAP criterion 2), plus -4116 and -4509 (known from Phase 17 and D055), 418 and 429 (rate limit and ban, reusing `is_rate_limit_error`, `is_rate_limit_ban_error`, `rate_limit_retry_after_seconds`), and -1022 (signature) if the docs list it. Each code carries its documentation source and read date, and codes seen only on Demo are labelled demo-observed (09-DEMO-REHEARSAL-FINDINGS finding 1: -2013 for GET algoOrder not found).
- **D-10:** Classification is by `status_code` only. The message-text and regex fallbacks (`_NOT_FOUND_MESSAGE`, `_is_already_canceled_message`) are removed or reduced to a logged diagnostic that cannot change a decision. A code that is not in the table is category UNKNOWN_EXCHANGE_ERROR and is treated as ambiguous: no retry on a placement path, SAFE_MODE-eligible, never mapped to "absent".
- **D-11:** Placement is never retried inside the adapter (09-REVIEW CR-09 stays). Retry is allowed only for read and cancel paths on transient categories, bounded by the existing reconciler ceilings (`_RECONCILER_CANCEL_*`). 418 never retries and waits `retry_after`; 429 honors `retry_after` and backs off. Timeout or 5xx on placement stays "execution status unknown" and goes to the probe-by-deterministic-client-id path (EXECUTION_SPEC section 10).
  - *Note (2026-10-16):* Superseded in part on 2026-10-16 by the user's record `decisions/18-DEC-O-18-01.md` (including its section "Amendment 2026-10-16 (user): 429 semantics"): no call (placement, cancel or read) is retried because of a 418 or 429; a 418 bans and a 429 pauses every REST call of the process through one shared gate, for a valid Retry-After capped by `signed_calls.rate_limit_retry_after_cap_seconds`, otherwise for the `signed_calls.rate_limit_418_no_retry_after_wait_seconds` or `signed_calls.rate_limit_429_no_retry_after_wait_seconds` fallback; the bounded cancel retry under `_RECONCILER_CANCEL_*` covers transient status-unknown errors only; the end of a ban or pause proves nothing about an order, a cancel, a fill or a protective stop; a protective order that cannot be placed or confirmed because of a pause or ban is reported as an unprotected position for Phases 19 and 20.

### Client configuration and environment selection
- **D-12:** One configuration function builds the SDK client for an explicit environment value `DEMO | TESTNET | LIVE`, with hosts from a table verified against current docs (Demo is `demo-fapi.binance.com`, already used by `scripts/demo_rehearsal.py`). There is no default environment inferred from the host: a missing or unknown value raises. LIVE additionally requires the existing enablement state; this phase builds the selector, it does not enable live. The mainnet-host guard generalizes `assert_demo_sdk_client` from `scripts/demo_rehearsal.py` into a production module that the rehearsal and probe scripts reuse.
  - *Note (2026-10-16):* Superseded in part on 2026-10-16 by the user's record `decisions/18-DEC-O-18-01.md`: the probe and smoke environment is DEMO, with the Demo WebSocket Streams URL `wss://demo-fstream.binance.com` and the Demo WebSocket API URL NOT_CONFIGURED; TESTNET is NOT_CONFIGURED, so selecting it raises; LIVE is never used by this phase.
- **D-13:** API keys load from the environment or a file path, never from a CLI argument or the repository; key and secret are redacted in every log and exception path with a test that greps the structured output (OPS-02, SECURITY_AND_OPERATIONS). No-withdrawal permission and IP allowlisting are attested by the operator, not by code (stays a Phase 24 to 26 HUMAN item).
  - *Note (2026-10-16):* Supplemented on 2026-10-16 by the user's record `decisions/18-DEC-O-18-01.md` (nothing above is replaced): the credential variable names are `BINANCE_DEMO_API_KEY` and `BINANCE_DEMO_API_SECRET` for DEMO and `BINANCE_LIVE_API_KEY` and `BINANCE_LIVE_API_SECRET` for LIVE (the LIVE names serve only to refuse a LIVE key in a DEMO process).
- **D-14:** Server-time drift is measured against `GET /fapi/v1/time` with a fail-closed outcome: drift beyond the limit, or a failed measurement, blocks new entries and is reported; a -1021 response triggers a re-measure and never an automatic retry of the order. `recvWindow` is set explicitly on every signed call. The numeric limits (timeouts, recvWindow, drift limit, keepalive and rotation margins, reconnect backoff caps, maximum stale-stream age) are SAFETY thresholds: see "Open, user-owned" O-18-01. The plan lists each as a named module constant with a provenance label (STRUCTURAL, COST_GUARD, DECISION or PLACEHOLDER) and never fills a number the user has not ratified.
  - *Note (2026-10-16):* Supplemented on 2026-10-16 by the user's record `decisions/18-DEC-O-18-01.md` (nothing above is replaced): the safety numbers are the user's 27 recorded `limit` lines, in which the rate-limit wait is split into `signed_calls.rate_limit_418_no_retry_after_wait_seconds` and `signed_calls.rate_limit_429_no_retry_after_wait_seconds` beside `signed_calls.rate_limit_retry_after_cap_seconds`; the plans carry them as required arguments loaded from `config/binance/binance-limits-v1.toml` (written verbatim by plan 18-09, provenance DECISION) with no default in code.

### Demo probe (D055 and inherited verification tasks)
- **D-15:** The probe is a script in the style of `scripts/demo_rehearsal.py`: Demo host asserted before any signed call, a dry-run mode that sends nothing, an `--execute` mode that needs the user to type the confirmation phrase themselves, evidence written as JSON with the schema name and version, every artifact scrubbed of secrets. It cleans up every order it opened and records the account state before and after. Results are labelled demo-observed, not mainnet, and are never used to choose a trading parameter.
- **D-16:** Probe cases, in this order of risk: read-only first (GET order and GET algoOrder not-found codes; the duplicate `clientAlgoId` code; id reuse after FILLED and after CANCELED), then the D055 cases (pre-placed STOP_MARKET with explicit quantity and reduceOnly with no position; an entry that never fills then cancelled, is the protective order orphaned and does it cancel cleanly; a full fill; a partial fill; a rejected protective order; reconciliation after each state), then the G2-029 additions (a below-minimum-notional reduce-only conditional leg; the MARKET_LOT_SIZE question for a triggered `*_MARKET` exit). The probe also records which `ALGO_UPDATE` and `ORDER_TRADE_UPDATE` frames arrive for each case, captured as redacted fixtures for the parser tests.
- **D-17:** The probe records facts and stops. It does not close D055: whether protection is placed after the fill or pre-placed stays OPEN until the user records a new DECISIONS row (D055 item 4: alternative (b) is UNVERIFIED on Demo). If the probe disagrees with `BinanceSemanticsFakeAdapter`, the fake is corrected in the same plan that consumes the evidence; if the probe has not run, the fake keeps its documented assumptions and the plan states that.
- **D-18:** Because this machine cannot reach Binance, the work splits into plans that need no network (parsers, taxonomy, supervisor logic against fakes, configuration, contract tests, probe script with a dry-run) and blocking-human plans that need a connected machine (the live smoke, the `--execute` probe). The blocking-human steps carry stated prerequisites and measurable acceptance, and the fixtures they produce feed a follow-up plan or task rather than being assumed in advance.

### Documentation and fact re-verification (first task)
- **D-19:** First task of the first plan: re-read the official Binance pages for the ALGO_UPDATE status list, the 24-hour WS lifetime, the listenKey lifetime and keepalive rules, the `/private` path, and the Change-Position-Mode wording (G3-001), and update `docs/SOURCES.md` with URL, read date, method and a not-verified-live label. On this machine a failed fetch is retried once, then recorded as UNVERIFIED with the exact failure; the executor on a connected machine repeats it. No exchange fact is taken from memory.
- **D-20:** Doc updates that follow from the facts: the Binance integration doc and `docs/trading/EXECUTION_SPEC.md` where they describe the stream, the error codes and the environment selection; ROADMAP criterion text is corrected if a re-read shows it is wrong. A decision that changes behavior goes into `docs/DECISIONS.md` as a new row (D-number assigned by the planner, next free number), not into this file.

### Test strategy
- **D-21:** Pure-function tests for the taxonomy and the algo status table; parser tests from recorded or documented sample frames for each of the three event types, including the malformed, unknown-status and duplicate-trade cases; supervisor tests with an injected clock and a scripted fake socket covering keepalive, rotation, reconnect, gap-then-snapshot and bounded backoff; a replay test proving `fold_fills` yields the same position view for a stream replayed, reordered and duplicated; secret-redaction tests. No test touches Binance or Telegram; every network step is blocking-human.
- **D-22:** Determinism and fail-closed rules stay: no float in any exchange-sensitive value, no wall-clock reads in pure code (clock injected), UTC-aware datetimes, byte-stable serialization for anything journaled.

### Claude's Discretion
- Module and file names inside `src/adapters/`, the exact Protocol shapes, the tenacity wiring, and the split of work into plans.
- Whether the taxonomy lives in `src/adapters/` or `src/domain/`, provided the pure part imports no SDK.
- Fixture file layout under `tests/` and the exact evidence JSON schema of the probe, following the Phase 9 and Phase 16 precedents.

### Folded inherited items (tracked in ROADMAP "Inherited items", not new scope)
G3-001 (D-19), G2-028 (D-07), G2-029 (D-16), G3-009 (D-06), G4-034 and G4-043 (D-08), D055 probe cases (D-16, D-17).

</decisions>

<open_items>
## Open, user-owned (an agent must not decide these; D061 items H and I)

- **O-18-01 Safety thresholds.** REST timeouts, recvWindow, the server-time drift limit, the maximum stale-stream age before entries are blocked, keepalive cadence and rotation margin, reconnect backoff caps, and any "stream gap then SNAPSHOT" timing. The planner gathers the constants, the Binance documented limits and the project precedents (Phase 16 O-07 table) into one table with rationale and sources, and stops at a blocking-human checkpoint for the user to ratify before the code plan that needs them executes. No default is filled.
  - *Note (2026-10-16):* Recorded on 2026-10-16 by the user in `decisions/18-DEC-O-18-01.md` (option values: 27 `limit` lines and the four algo status classes, with the section "Amendment 2026-10-16 (user): 429 semantics"); the item text above is kept as written.
- **O-18-02 D055 execution model.** Protection after the fill versus pre-placed. Stays open; the probe supplies evidence only. The user records a new DECISIONS row after the probe.
- **O-18-03 Probe authorization.** Each `--execute` run is the user's explicit go-ahead on a connected machine; the user types the confirmation phrase. Account state and size limits for the probe (quantity, symbol) are the user's to approve at the checkpoint.
- **O-18-04 Environment choice for the probe.** Demo (`demo-fapi.binance.com`) versus testnet: ROADMAP says "demo or testnet". Recommended: Demo, because Phase 9 already used it and its not-found code is observed there; the user confirms at the probe checkpoint. LIVE is never used by this phase.
  - *Note (2026-10-16):* Recorded on 2026-10-16 by the user in `decisions/18-DEC-O-18-01.md`: `probe environment: DEMO`, TESTNET NOT_CONFIGURED (see the note under D-12); the user still re-confirms at the probe checkpoint of plan 18-20 and has not approved running the Demo smoke or the probe.
</open_items>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap, requirements, decisions
- `.planning/ROADMAP.md` Phase 18 section (goal, criteria 1 to 3, inherited items G3-001, G2-028, G2-029, G3-009, G4-034, G4-043, D055)
- `.planning/REQUIREMENTS.md` EXEC-01, EXEC-02, EXEC-05, OPS-02 (including the evidence-level notes)
- `docs/DECISIONS.md` D055 (protective stop before or after fill, the probe plan), D044 item 7 (docs not fetched), D051 item (i) (UNKNOWN needs evidence), D061 items G, H and I (machine split, who decides), D062, D031 (source order)
- `AGENTS.md` (constraints: exchange authority, fail closed, Decimal, no AI in the decision path, GSD workflow)

### Exchange facts and prior probes
- `docs/SOURCES.md` sections "Facts verified for Phase 11", "Phase 17" (including the 2026-10-07 live re-read) and "Phase 16" (WS Connect page rows G3 to G5, SDK internals row)
- `.planning/phases/09-live-execution-rollout/09-DEMO-REHEARSAL-FINDINGS.md` (finding 1: -2013; finding 2: -4509) and `09-EXCHANGE-FACTS.md`
- `.planning/phases/17-operational-persistence-layer/17-CONTEXT.md` D-25 and the `BinanceSemanticsFakeAdapter` / `tests/support/fake_binance_exchange.py`
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` finding sections for F-104, F-054, F-501, F-205, F-503, F-502, F-504, F-128, F-505, F-706, F-506
- `docs/trading/EXECUTION_SPEC.md` (sections 7 and 10: deduplication and restart recovery)

### Code to read before planning
- `src/adapters/binance_usdm.py` (error helpers around lines 145 to 195 and 436 to 490, snapshots, `place_entry`, `place_algo_protective`, `user_commission_rate`)
- `src/adapters/paper_ws.py` and `scripts/paper_ws_smoke.py` (supervisor, rotation, drop-transport precedent), `tests/test_paper_ws_contract.py`, `tests/test_paper_ws_smoke_evidence.py`
- `src/execution/fill_monitor.py` (`fold_fills`, `FillEvent`, divergence kinds), `src/execution/manager.py` (`execute_approved_plan`, `_ACTIVE_ALGO_STATUSES` near line 1036), `src/reconcile/` (compare, safe_mode, sweeper)
- `scripts/demo_rehearsal.py` (`DEMO_HOST`, `assert_demo_sdk_client`, `build_demo_sdk_client`, evidence schema)
- `src/domain/order.py`, `src/domain/fill.py`, `src/db/mappers.py`, `src/persistence/` (journal and order stores for G4-034 and G4-043)

No external spec files exist beyond the above; every Binance fact must be re-read from the official page at plan time and recorded in `docs/SOURCES.md`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `fold_fills` and `FillEvent` (`src/execution/fill_monitor.py`): idempotent fold keyed on `(order_id, exchange_trade_id)`; the stream's fill output plugs in unchanged.
- `is_rate_limit_error`, `is_rate_limit_ban_error`, `rate_limit_retry_after_seconds`, `is_invalid_symbol_error` and the `_NOT_FOUND_CODES` set in `binance_usdm.py`: starting point for the taxonomy; they already prefer the int `status_code`.
- Snapshot dataclasses (`OpenOrderSnapshot`, `OpenAlgoOrderSnapshot`, `PositionSnapshot`, `AlgoOrderProbe`) and `BinanceUsdmAdapter.server_time`: the REST fallback and the drift check use them.
- `scripts/demo_rehearsal.py`: Demo host assertion, SDK client builder, evidence recorder, confirmation-phrase flow.
- `src/adapters/paper_ws.py` supervisor and the SDK contract tests: the model for reconnect, rotation and "drop the transport" testing.
- Append-only journal and the Phase 17 stores: where stream anomalies and evidence-source records go.

### Established Patterns
- SDK models are converted to frozen, Decimal/UTC dataclasses at the adapter edge; strict parsing that raises on an unknown value, never defaults to zero.
- Placement is never retried in the adapter; ambiguity goes to a probe by deterministic client id.
- Named module-level constants for ceilings, audited before live enablement, with provenance labels in parameter files.
- Facts get a URL, read date, method and a not-verified-live label in `docs/SOURCES.md`.

### Integration Points
- `execute_approved_plan` / attach-protectives path and the Phase 8 reconciler consume the new event types in Phases 19 and 20.
- `_ACTIVE_ALGO_STATUSES` in `src/execution/manager.py` is replaced by the classification table of D-07.
- `BinanceSemanticsFakeAdapter` is corrected from probe evidence (D-17).
- Phase 21 reads `commission` and `commissionAsset` carried by D-06.

</code_context>

<specifics>
## Specific Ideas

- Demo is where `-2013` was already observed for GET algoOrder (2026-10-05); the probe extends that evidence, it does not restart it.
- The stream must never be the only source of truth: a plan that makes a decision depend only on an event without a REST confirmation path is a defect.
- Captured Demo frames become redacted test fixtures, so parser tests lock the real field set after the first connected run.

</specifics>

<deferred>
## Deferred Ideas

- Composing the stream supervisor into the running process and soak: Phases 24 and 25.
- Using `ACCOUNT_UPDATE` for equity, margin and position truth: Phases 20 to 22.
- Symbol/side/qty binding and live-price check: Phase 19.
- `binance-sdk-algo` TWAP/VP: Phase 3+ evaluation only, not V1.
- The D055 model choice and any change to `execute_approved_plan` ordering: a separate user decision and a new task after the probe.

</deferred>

---

*Phase: 18-user-data-stream-error-taxonomy*
*Context gathered: 2026-10-15*
