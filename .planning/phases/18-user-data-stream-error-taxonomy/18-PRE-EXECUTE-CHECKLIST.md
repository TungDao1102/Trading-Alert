# Phase 18: Pre-execute verification checklist

**Written:** 2026-10-15, on the planning machine (no Binance or Telegram access).
**Purpose:** everything that was unverified, unclear, risky or left open while discussing, researching and planning Phase 18. Work through this on a connected machine BEFORE `/gsd-execute-phase 18`. Tick each box and write the result next to it; do not skip an item because it looks minor.
**Rule for any fetch or connection error:** retry once, then record the exact error here and stop that item. Never guess an exchange fact.
**Sources:** `18-RESEARCH.md` (UNVERIFIED register, Open Questions, Pitfalls), the plan-checker report, the planner hand-back, and `18-CONTEXT.md` open items.

Status key: `[ ]` not checked, `[x]` checked and matches the plans, `[!]` checked and differs (write what differs and which plan must change).

---

## A. Environment and branch checks (do first)

- [ ] A1. `git fetch` shows branch `phase-18` (commits e8c0c9a, afb6a3b, f4967ec and any later). The worktree starts from `develop` at 6939c90; run `git log --oneline develop..phase-18` and `git log --oneline phase-18..develop` and note how far Phase 16 moved `develop`.
- [ ] A2. `.planning/config.json`: `workflow._auto_chain_active` must be `false` on the executing machine, or execute-phase may chain into later phases. (The committed value on `develop` is `true`; the planning worktree had it set to `false` locally and uncommitted.)
- [ ] A3. `uv sync --frozen --extra dev` works; SDK in `uv.lock` is still `binance-sdk-derivatives-trading-usds-futures` 17.4.0 and `binance-common` 4.4.0 (research reads and contract tests assume these exact versions). If `uv.lock` changed on `develop`, re-read the SDK facts in section C.
- [ ] A4. Baseline is green before any change: `uv run pytest -m "not docker"`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check`, `uv run python scripts/verify_decision_alignment.py all`. Record failures that exist before Phase 18 starts.
- [ ] A5. `TEST_DATABASE_URL` is available for plan 18-08 (store method tests skip without it). Note: not probed on the planning machine.
- [ ] A6. Next free D-number: check `docs/DECISIONS.md` on `develop` and on `phase-18` (plans assume D072, but Phase 16 runs in parallel and may have taken it). Plan 18-09 computes it at write time; confirm the rule still works.
- [ ] A7. No other process is using the Demo account's listenKey (the listenKey is an account-level singleton, inferred). Do not run the Phase 16 paper smoke or any other user-data client at the same time as the Phase 18 smoke or probe.

## B. Binance documentation facts to re-read (plan 18-01 does this; do it yourself first)

Official pages returned the Developer Docs landing shell or an empty WAF response from the planning machine. Everything below rests on SDK source, a 2026-01-13 Wayback transcription, and WebSearch/WebFetch summaries, all labelled "not verified live".

- [ ] B1. **Payload pages unreadable:** `ORDER_TRADE_UPDATE`, `ALGO_UPDATE`, `ACCOUNT_UPDATE`, `listenKeyExpired` (URLs `.../user-data-streams/Event-Order-Update`, `Event-Algo-Order-Update`, `Event-Balance-and-Position-Update`, `Event-Listen-Key-Expired`, and the catalog `ws-streams/user-data-streams` page). Read each in a browser. Compare every field name and type with the SDK models the parsers are built from (`order_trade_update_o.py`, `algo_update_o.py`, `account_update*.py`).
- [ ] B2. **ALGO_UPDATE status list** (NEW, TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED): is the list complete and are the meanings as assumed? Does `CANCELED` appear (it is missing from `docs/trading/EXECUTION_SPEC.md` 6.1 today)? (G3-001, G2-028.)
- [ ] B3. **REST `algoStatus` value list** (`GET /fapi/v1/algoOrder`, open algo orders): unverified; the plans assume it equals the stream `X` vocabulary. Confirm or correct.
- [ ] B4. **Subscription format on `/private`:** docs show only `wss://fstream.binance.com/private/ws?listenKey=<k>&events=...`. The JSON `SUBSCRIBE` parameter format with a bare listenKey, the message envelope, and whether `events=` is required are undocumented. See risk R1.
- [ ] B5. **listenKey facts:** 60-minute validity, keepalive `PUT`, `DELETE`, one key per account (inferred), error code of `PUT` on a closed or expired key (assumed -1125, documented only generally), exact event string for expiry (assumed `listenKeyExpired`).
- [ ] B6. **24-hour connection limit** and any limit on new connections per IP/time window (a targeted read returned "Not present"). Ping/pong interval (3 minutes, 10-minute disconnect) from the Phase 16 SOURCES row: re-confirm.
- [ ] B7. **Error-code page:** confirm -2011, -2013, -2019, -4164, -1021, -2021, -4116, -4509, -1022, -1003, -1015, -4067, -4068 and any others used in the taxonomy. -4509 is Demo-observed only and absent from the error-code page summary. Check whether -1003 appears for both 429 and 418 (research says yes).
- [ ] B8. **Does Binance send a `Retry-After` header** on 418/429? Unverified. The SDK exposes `retry_after`; see what it is filled from.
- [ ] B9. **recvWindow maximum:** documented as 60000 on only two endpoints (algoOrder, positionSide/dual). Check the others. Also confirm the "host clock ahead by more than 1000 ms is rejected regardless of recvWindow" rule.
- [ ] B10. **Change-Position-Mode wording** (-4067 open orders, -4068 open position) from G3-001: still not fetched.
- [ ] B11. **Child-order identity of a triggered algo order:** which `c`/`i` values appear in `ORDER_TRADE_UPDATE` when a protective algo order triggers and fills? Needed so a triggered protective leg is matched to its algo order.
- [ ] B12. **Order of delivery:** is `ACCOUNT_UPDATE` before or after the matching `ORDER_TRADE_UPDATE`? Unverified.
- [ ] B13. **Money fields:** can a bare JSON number (not a string) ever arrive in a money field? The parsers treat a non-string as an anomaly; confirm this will not reject valid frames.
- [ ] B14. **Binance docs changed several times in 2026** (2026-03-05, 07-21, 08-07, 08-21). Check the futures change log for anything after 2026-10-15 that touches user data, algo orders, listenKey or `/private`. The research validity window for doc facts is 2026-10-22.

## C. Environment, endpoints and credentials (open owner question O-18-04)

- [ ] C1. **What the SDK `TESTNET` constant denotes.** Docs call `demo-fapi.binance.com` "Testnet REST" and `wss://demo-fstream.binance.com` "Testnet WebSocket", while the SDK `TESTNET` constants point at `testnet.binancefuture.com`. The plans make the TESTNET row raise "not configured" until you answer. Decide: Demo only, or Demo plus testnet.
- [ ] C2. **Demo WebSocket URL** `wss://demo-fstream.binance.com` rests on a single-source summary. The SDK has no Demo WebSocket constant, so a REST-only config leaves the WebSocket on the production URL (risk R3).
- [ ] C3. **Does Demo serve** `POST /fapi/v1/listenKey` and a user-data socket? Only the Options Demo statement was read; futures Demo key provisioning is unverified.
- [ ] C4. **Credential variable names** for Demo (reuse `BINANCE_TESTNET_*` or add `BINANCE_DEMO_*`): small decision recorded at plan 18-02.
- [ ] C5. Demo keys exist, have no withdrawal permission, and the account holds no leftover orders or positions from Phase 9 rehearsals.

## D. Risks the plans handle but you should consciously accept or change

- [ ] R1. **SDK `/private` event delivery may not work.** The SDK subscribes with the bare listenKey; if Binance expects the URL-parameter form or another envelope, the SDK silently drops every event to an INFO log line. Plan 18-18 makes end-to-end event delivery the first smoke criterion; plan 18-19 is a conditional fallback (direct `aiohttp` transport, needs `aiohttp` as a direct dependency via `uv add`, lock updated in the same change; `aiohttp` 3.14.3 is already locked transitively). Decide beforehand: is a direct-aiohttp fallback acceptable, and what is the stop rule if both routes fail?
- [ ] R2. **Error surface is narrower than CONTEXT D-09/D-10 assumed.** `status_code` is the Binance body code only for HTTP 400/401/403/404/418/429; for 5xx it is the HTTP status (body discarded, so 503 variants are indistinguishable); other 4xx such as 408 become `ClientError` with `status_code=None`. 418/429 are identified by exception class only. So the taxonomy key is (SDK class, int code, call kind), not an int alone. Confirm you accept this deviation from the CONTEXT wording.
- [ ] R3. **Mixed-environment trap:** a client built with only a REST config leaves the WebSocket on the production URL. Plans add a guard over REST, streams and WS-API URLs and a single SDK construction site. Verify with a transport-level check that no request goes to a production host during the smoke.
- [ ] R4. **SDK retries by itself** (GET and DELETE on network errors, `retries=3`, `backoff=1000` ms, blocking `time.sleep`; default `timeout` 1000 ms). This stacks with the project's tenacity cancel retry and blocks the event loop. Plan 18-13 sets `retries=0` and a timeout through the config layer; confirm on the connected machine that the SDK honors it.
- [ ] R5. **Secret leaks:** the SDK logs the listenKey at INFO through the root logger; `Redactor` has no rule for it; a key loaded from a file is invisible to `Redactor.from_environ`; `NetworkError` text embeds the signed URL (`signature=`). After the smoke, grep all captured logs and the evidence JSON for key, secret, signature and listenKey.
- [ ] R6. **Stale-stream age must use liveness, not event silence.** A quiet account produces no events. The numeric limit overlaps Phase 20 T-06 / G2-026. You must either ratify a number in plan 18-02 or defer it to Phase 20 explicitly.
- [ ] R7. **Gap handling:** on reconnect, rotation or a missed keepalive the stream is UNKNOWN until a REST snapshot; events after a gap are not trusted before it. Verify with the forced transport drop in the smoke (acceptance e) and record the measured gap.
- [ ] R8. **Fill key space:** `fold_fills` keys on `(order_id, exchange_trade_id)`. Confirm on Demo that `account_trade_list` `id` equals the stream field `t`; otherwise REST-fallback fills and stream fills double count (the replay test has a negative control for this).
- [ ] R9. **Dual position mode:** `ps` (position side) must be handled; test the events in both one-way and hedge mode if the Demo account allows switching (it cannot switch with open orders or positions: -4067/-4068).
- [ ] R10. **`BinanceSemanticsFakeAdapter` stays unchanged until the probe runs** (duplicate `clientAlgoId` code and id reuse after FILLED/CANCELED are unverified). Phase 19 depends on these facts. Do not start Phase 19 planning on the fake's assumptions.
- [ ] R11. **Doc-gate hazard:** `scripts/decision_alignment/exchange.py` and its tests pin phrases in `docs/trading/EXECUTION_SPEC.md` and `docs/integration/BINANCE.md`; every Binance URL cited in EXECUTION_SPEC must be a row of the Phase 11 SOURCES section dated 2026-09-30. New reads go in a NEW SOURCES section. Run `verify_decision_alignment.py all` after every docs task.
- [ ] R12. **Probe safety:** the probe places real Demo orders. Confirm the host assertion runs before the first signed call, the confirmation phrase is typed by you, quantities are within your limits, cleanup leaves zero open orders, zero open algo orders and a flat position, and the account state is recorded before and after. Never run `--execute` unattended.

## E. Open owner decisions (nothing in the plans fills these; you must supply them)

- [ ] E1. **O-18-01 safety numbers** (26 canonical keys in plan 18-02's table, including REST timeouts, recvWindow, drift limit, maximum stale-stream age, keepalive cadence and rotation margin, reconnect backoff caps, `stream.sdk_reconnect_delay_ms`, `stream.sdk_reconnect_attempts`, `stream.project_rotation_interval_seconds`). Plan 18-02 produces the table with an empty value column; plan 18-09 transcribes your answers into `config/binance/binance-limits-v1.toml`. Plans 06, 09, 13, 16, 17, 18, 20 cannot run before this.
- [ ] E2. **Algo status class rows flagged as judgment calls:** TRIGGERING and TRIGGERED, FINISHED, CANCELED (plus REJECTED and EXPIRED are checked by plan 18-06, which stops if any of the six is classed ACTIVE). Unseen statuses are UNKNOWN (fail closed).
- [ ] E3. **O-18-03:** smoke limits (plan 18-18) and probe limits (plan 18-20): symbol, quantity, which optional probe cases. Written verbatim from your own reply.
- [ ] E4. **O-18-04:** environment choice, re-confirmed at plan 18-20 (see C1).
- [ ] E5. **D055 execution model** (protection after fill vs pre-placed) stays OPEN. Plan 18-21 writes a "NOT A DECISION" draft from the probe evidence; you record the decision as a new DECISIONS row later. No LIVE execution before it is closed (D055 item 2).
- [ ] E6. **Plan 18-03 design gate (D-01):** you review the frozen event dataclasses before Phases 19/20/24 import them (costly to reverse). This gate was added by the planner; CONTEXT did not require a mid-plan human stop. Keep it or drop it.
- [ ] E7. **Plan 18-19 rotation rule:** if the SDK route fails and `stream.project_rotation_interval_seconds` is `none`, the plan stops because you would have to ratify a rotation value.

## F. Plan-quality items from the plan-checker (0 blockers, 2 warnings, 4 info)

- [ ] F1. WARNING: plan 18-17 (probe script) estimates 130k tokens, over the 100k budget (about 19 probe cases, cleanup framework, live rig, CLI gates in 3 tasks). Options: split into a tracer plan (skeleton, read-only cases, cleanup, dry run) and an expansion plan (write cases, G2-029 additions, live rig, CLI gates), or let the executor split at a task boundary.
- [ ] F2. WARNING: plan 18-03 lists 16 files (6 small JSON fixtures and a README are non-code). Consider moving fixtures and `tests/fixtures/phase18/README.md` to a follow-on task.
- [ ] F3. INFO: plan 18-17 says it will extend `load_demo_order_limits` in `src/ops/operator_evidence.py` and `tests/test_operator_evidence.py` if plan 18-16 left only the smoke kind; neither file is in its `files_modified`. Plan 18-16 already states smoke and probe kinds, so delete the conditional or declare the files.
- [ ] F4. INFO: plan 18-13 makes signed calls fail closed without a policy (`SignedCallPolicyMissing`); more than 20 test and source files reference `BinanceUsdmAdapter` but only 9 test files are declared. Its Task 3 runs the full suite and fixes what fails; add a note in `files_modified`.
- [ ] F5. INFO: plan 18-12 (wave 3) imports private row converters from `src/adapters/binance_usdm.py`, which plan 18-10 (same wave) edits, with no `depends_on` 10. Plan 18-07 reads `decisions/18-O-18-01-table.md` from plan 18-02 without declaring `depends_on` 02. Low risk; declare the dependencies (this may move plan 18-12 to wave 4).
- [ ] F6. INFO: shared-file merge hazards with Phase 16 on `develop`: `docs/SOURCES.md`, `docs/DECISIONS.md`, `docs/DOC_STATUS.md`, `docs/integration/BINANCE.md`, `docs/trading/EXECUTION_SPEC.md`, and `pyproject.toml`/`uv.lock` (conditional plan 18-19). Only the D-number has a stated strategy. Before merging: rebase on `develop` and re-run `verify_decision_alignment.py all`.
- [ ] F7. Plans 18-11, 18-14 and 18-16 sit at exactly 100k estimated tokens; 18-15, 18-21 and 18-22 are near it. Estimates have confidence "low" (no calibration samples). Watch these during execution.
- [ ] F8. The ordering cost: plan 18-02's human checkpoint (wave 1) and plan 18-03's mid-plan design gate hold wave 2 and everything after, including pure-code plans 18-05, 18-07, 18-08 that need no owner value. Consider running 18-05 and 18-08 before the checkpoint is answered.
- [ ] F9. The label "F-504" (REST timeout audit ref) appears in no plan text; the work it names is in plan 18-04 (`ClientLimits`, `rest_timeout_ms`). Traceability only; add the label to plan 18-04 if you want the audit ref traceable.
- [ ] F10. `18-VALIDATION.md` per-task map is not filled in (requirement-level mapping only) because task IDs came from the planner. Planner's requirement-to-test mapping: EXEC-05 `test_userdata_events`, `test_userdata_parsers`, `test_userdata_adapter`, `test_userdata_contract`, `test_userdata_supervisor`, `test_userdata_router`, `test_userdata_replay`, `test_userdata_rig`; EXEC-01 `test_algo_status`, `test_execution_attach`, `test_binance_usdm_error_routing`, `test_binance_usdm_signed_calls`; EXEC-02 `test_exchange_errors`, `test_sdk_error_mapping_contract`, `test_adapter_not_found_mapping`, `test_persistence_exit_evidence_pg`; OPS-02 `test_binance_client_config`, `test_binance_secret_redaction`, `test_binance_limits`, `test_clock_drift`, `test_no_unratified_defaults`. Update the VALIDATION map before `nyquist_compliant` is set to true.
- [ ] F11. Planning-time estimates and the ROADMAP: the ROADMAP Phase 18 plan list, its criteria text and the REQUIREMENTS statuses were NOT edited. Plans 18-01, 18-21 and 18-22 write proposed corrections into their SUMMARYs; apply them at merge time together with `STATE.md`.

## G. Items that stay out of Phase 18 (do not let them leak in)

- Composing the stream into a running process and the soak: Phases 24 and 25.
- Using `ACCOUNT_UPDATE` for equity, margin or position truth: Phases 20 to 22 (Phase 18 only parses and emits events; `commission` and `commissionAsset` are carried for Phase 21).
- Symbol/side/qty binding and the live-price check: Phase 19.
- Closing D055 and any change to `execute_approved_plan` ordering: separate user decision and new task after the probe.
- `binance-sdk-algo` TWAP/VP: not V1.
- Phase 17 review items folded in by the planner: `src/persistence/__init__.py` module-map docstring fix (ROADMAP Phase 999.3, in plan 18-08) and 08-REVIEW IN-10 (the `-2011` substring risk, closed by plan 18-10).

## H. Suggested order on the connected machine

1. Section A (environment) and A4 (baseline green).
2. Section B reads (B1 to B14) in a browser; paste results into the Phase 18 SOURCES section later via plan 18-01, or note differences here now.
3. Section C answers; section E1 to E4 and E6 (fill the plan 18-02 table, design gate preference).
4. Decide F1/F2 (split or accept), apply F3 to F5 if you want clean plans, then re-run the plan-checker (`/gsd-plan-phase 18` with existing plans, or `gsd-plan-checker`).
5. Only then `/gsd-execute-phase 18`, starting with wave 1.

---

*Phase: 18-user-data-stream-error-taxonomy*
*Checklist written: 2026-10-15*
