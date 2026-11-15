# Phase 22 deferred register

Written by plan 22-16 on 2026-10-24. It lists what Phase 22 deliberately did NOT build, decide or prove, and what only the owner can decide or run, each with its owner phase or owner decision. It is the Phase 22 counterpart of `21-DEFERRED.md`; the owner items are in `22-OWNER-DECISIONS.md` and the Demo facts in `22-DEMO-RESULTS.md`, which this file cites and does not reinterpret.

Evidence in Phase 22 is executed tests with fakes (stateful fake SDKs, scripted ports), the real Binance adapter over recorded Demo payloads, a local PostgreSQL for the `*_pg.py` files, and one owner-run Demo session of 2026-10-24 (six cases, single samples, demo-observed, not mainnet). Nothing built in Phase 22 is wired in a running process: no entry point constructs the margin guard, the configuration guard, the bracket cache or the liquidation watch before Phase 24. No requirement is marked complete by this phase. The owner answered O-1 to O-4 on 2026-10-24 and `docs/DECISIONS.md` D085 records the answer (applied after the phase was executed). Labels: [DOC], [DESIGN], [NOT_TESTED].

Two facts the reader must not lose:

- Nothing in Phase 22 writes `required_margin`. The column and the claims reader (`PgRiskReservationStore.list_margin_claims`) exist; the Phase 24 issuer calls `register_request` with `required_margin` from `required_initial_margin`. Until then every RESERVED or PLACED row reads as an unknown margin, and a plan placed while another claim exists is refused `UNCERTAIN_ACCOUNT_STATE`. The "approved-but-unplaced plans" part of criterion 3 is therefore proven on fakes and on the PostgreSQL claims reader only; criterion 3 is NOT complete and NOT Demo-proven. `tests/test_phase22_gate.py` pins that no module in `src/` calls `register_request` or passes `required_margin`.
- `liquidation_watch` is built and tested but is NOT active. `ProtectionCoordinator` defaults it to None; Phase 24 composes the watch and its `LiquidationFailurePolicy`. EXEC-02 and D-12 are not active until then. The gate pins that nothing in `src/` or `scripts/` passes it.

## Owner items

Each row cites `22-OWNER-DECISIONS.md`. All four are DECIDED and APPLIED by the owner's answer of 2026-10-24 (DECISIONS D085); the assistant recorded and applied them. Deciding them opens nothing: fourteen required limit keys stay `NOT_CONFIGURED` and `LIVE_ORDERS_DISABLED` stays.

| Item | Status | What is built | Who decides |
|------|--------|--------------------------|-------------|
| O-1 Target leverage, and a symbol the owner also trades by hand (D-02, D-04) | DECIDED and APPLIED 2026-10-24 (D085): leverage 5, ISOLATED; the system may change the margin type and leverage of a FLAT symbol. The Telegram control the owner asked for is a NEW REQUIREMENT, NOT built (see Deferred items) | `TARGET_LEVERAGE` = 5 (the D035 cap) in `src/execution/symbol_config_guard.py`, passed as a required argument; the 5x cap check stays; the guard changes only a flat symbol with no orders and journals the previous configuration without restoring it. The Demo account's BTCUSDT is ISOLATED x5 after the 2026-10-24 run (demo-observed, not mainnet) | owner (decided) |
| O-2 Liquidation buffer: number, definition, home (D-10) | DECIDED and APPLIED 2026-10-24 (D085): 300 bps, provenance `DECISION`; stays an execution-limits key, the deviation from RISK_MANAGEMENT section 9 is accepted | Basis points of the entry price in the REQUIRED key `margin.liquidation_buffer_bps`; not a registry parameter | owner (decided) |
| O-3 Bracket maximum age, margin headroom, free-margin basis (D-11, D-13) | DECIDED and APPLIED 2026-10-24 (D085): `margin.max_bracket_age_ms` = 60000, `margin.headroom_bps` = 1000 (both `DECISION`), and the netting constant flipped to True | The two keys REQUIRED; `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` = True (two Demo samples saw the netting; demo-observed, not mainnet): a PLACED claim placed at or before the reading is not counted twice, one placed after it still counts. A mainnet sample at the Phase 26 canary re-checks it; a wrong True can only let the exchange reject with -2019 | owner (decided) |
| O-4 A failed post-fill liquidation check: close or only alert (D-12) | DECIDED 2026-10-24 (D085): `CLOSE_POSITION`, recorded only | Both `LiquidationFailurePolicy` members exist behind a required argument; the watch is NOT active before Phase 24, and the Phase 24 composition must pass `CLOSE_POSITION` | owner (decided) |

## Owner-run Demo cases

The owner ran the six SJ3 cases on 2026-10-24 (evidence in `evidence/`, results in `22-DEMO-RESULTS.md`; every figure is demo-observed, not mainnet). The cases record facts; they set no number and flip no flag. "NOT RUN" below names the part no run has covered.

| Case | Settles (RESEARCH Assumptions Log) | Observed on 2026-10-24 | Still NOT RUN or unobserved |
|------|------------------------------------|------------------------|-----------------------------|
| `symbol_config_change_to_isolated` | A5 (casing of an ISOLATED marginType) | Margin type and leverage 5 accepted; the read-back shows `ISOLATED` in upper case and leverage 5 (R-1) | A symbol that is not flat; a short; any host other than the Demo |
| `margin_type_change_with_resting_order` | A6 (code and class of a margin-type change with a resting order) | Refused, code -4047, BAD_REQUEST, REJECTED_DEFINITIVE; configuration unchanged (R-2) | -4048 (open position) and -4046 (no-op change) are NOT RUN |
| `leverage_above_bracket_maximum` | A6 (code of a leverage above the maximum) | Bracket 1 maximum 125 read from the exchange; 126 refused with -4028 (R-3) | The code for a leverage above a lower bracket's maximum is NOT RUN |
| `margin_insufficient_at_target_leverage` | the -2019 shape of criterion 3 | 1 BTC at ISOLATED x5 refused with -2019, REJECTED_DEFINITIVE (R-6) | Nothing further for this case |
| `available_balance_with_resting_order` | A1 (what `availableBalance` deducts) | Two samples (CROSSED x20, ISOLATED x5): `availableBalance` fell by exactly the order's initial margin (R-4, R-5) | More samples and other hosts are NOT RUN; the owner flipped the constant to True on these two samples (D085), and a mainnet sample at the Phase 26 canary re-checks it |
| `isolated_position_liquidation_price` | A3 (isolated `liquidationPrice` against the formula) | One long sample, tier 1: matched only with the entry fee netted from the isolated wallet; `entry_fee_rate` became a required argument (R-7) | A short, a higher tier, a mainnet figure and a funding or fee other than the Demo taker rate are NOT RUN |

Status of the criteria after the run, no more than `22-DEMO-RESULTS.md` says:

- Criterion 1 (margin type and leverage set and verified by `symbolConfig`): observed on the Demo for BTCUSDT, one-way, set and read back with refusals. It is NOT Demo-proven for the guard end to end: the guard (plan 22-11) is proven on a stateful fake SDK and recorded payloads.
- Criterion 2 (liquidation beyond the SL from exchange brackets): one long sample on tier 1 agrees with the formula once the entry fee is included. It is NOT Demo-proven: no short and no higher tier.
- Criterion 3 (available margin): the netting fact is observed on two samples (the constant is True since D085). It is NOT Demo-proven and not complete: the claims of other approved plans are not written by any Phase 22 code (see the first fact above).
- Criterion 4 (one-way, single-asset only): decided by the guard on fakes and recorded payloads; read by `account_read_only_capture`.
- Nothing here is mainnet.

## Deferred items

| Item | Why deferred | Owner phase or decision | Source |
|------|--------------|-------------------------|--------|
| Phase 24 composition of the margin guard: `MarginGuard` over `LiveEquitySource`, `SymbolConfigGuard` (with the target leverage), `BracketCache` and a claims port over `PgRiskReservationStore.list_margin_claims`, passed into `LivePlacementContext` [DESIGN] | Phase 22 builds the pieces and tests them with fakes; no entry point constructs them | Phase 24 | 22-11, 22-12, 22-14, 22-15 SUMMARYs |
| Passing `liquidation_watch` and its `LiquidationFailurePolicy` to `ProtectionCoordinator`; the fee-rate port of the watch (`EntryFeeRateSource`) [DESIGN] | The hook is built and tested with `None` as default; EXEC-02 and D-12 are not active until composed. The policy is decided: the Phase 24 composition must pass `CLOSE_POSITION` (O-4, D085) | Phase 24 | 22-13 SUMMARY; D085 |
| NEW OWNER REQUIREMENT (2026-10-24, O-1): set the leverage and the margin type from Telegram. NOT designed and NOT built [DESIGN] | The owner asked for it with the answer to O-1; no design exists. A design must keep: owner chat only, a two-step confirm, a flat symbol only, never above the D035 cap of 5 (raising the cap needs its own DECISIONS row), and the mutation only through `SymbolConfigGuard` | future phase (Phase 24 composition or a new phase) | `22-OWNER-DECISIONS.md` O-1; D085 |
| Mainnet re-check of the `availableBalance` netting [NOT_TESTED] | The constant `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` is True on two Demo samples only (D085) | Phase 26 canary | `22-DEMO-RESULTS.md` R-4, R-5; D085 |
| `register_request` at plan issue with `required_margin`, `margin_entry_price` and `margin_leverage` from `required_initial_margin` [DESIGN] | Phase 22 adds the nullable columns (migration 0012) and the reader; the issuer does not exist. Rows read as unknown margin and fail closed | Phase 24 | 22-08 SUMMARY |
| The rehearsal margin guard: `scripts/demo_rehearsal.py` refuses with `MARGIN_GUARD_NOT_COMPOSED` without an injected guard [DESIGN] | The rehearsal runs only with a composed guard | Phase 24 | 22-15 SUMMARY |
| A spill for the best-effort `MARGIN_CONFIG_CHANGED` journal row: a failing journal never changes the outcome, and the row is then lost [NOT_TESTED] | A durable spill is composition work | Phase 24 | 22-15 SUMMARY |
| Approval-time margin pre-check (amendment A2) [DESIGN] | The authoritative sum is at placement with a fresh async reading; the approval transaction is synchronous | not built | `22-CONTEXT.md` A2 |
| The weight budget of the guard's reads (symbolConfig 5, leverageBracket 1, accountConfig 5, account 5, balance 5 per run; the shared gate has no weight accounting); no number set [NOT_TESTED] | A cadence is an owner-visible number and no process is started | Phase 24 | 22-10, 22-14 SUMMARYs |
| Monitoring the liquidation distance of an open position over time [DESIGN] | Not in this phase's criteria; only the one post-fill check exists | not built (backlog) | `22-CONTEXT.md` Deferred Ideas |
| Dynamic or volatility-scaled leverage [DESIGN] | Out of scope; the target is a constant | not built | `22-CONTEXT.md` |
| Automatic margin top-up [DESIGN] | `isAutoAddMargin` true is refused (`AUTO_ADD_MARGIN_ENABLED`); no top-up is built | not built | `22-CONTEXT.md` D-06 |
| A registry-parameter liquidation buffer with a backtest liquidation model [DESIGN] | Not chosen: the owner kept the execution-limits key (O-2, D085). Only a later owner decision could change that; it needs a new parameter set, a new `strategy_version` and regenerated research records (D075, D076) | owner, O-2 | `22-CONTEXT.md` Deferred Ideas |
| Portfolio Margin accounts [DESIGN] | A multi-asset account is refused (`MARGIN_MODE_UNSUPPORTED`); the `/fapi` calls assume a classic account (RESEARCH A10) | not built | 22-14 SUMMARY |
| The `notionalCoef` meaning [NOT_TESTED] | A coefficient other than 1 makes the bracket set unusable (fail closed); its semantics are not established (RESEARCH A8) | owner if it ever appears | 22-12 SUMMARY |
| The isolated-wallet, fee and funding assumptions of the formula [NOT_TESTED] | One long sample, tier 1, Demo taker rate 0.0004, no funding; a short and a higher tier are unobserved (RESEARCH A2, A3) | Phases 24 to 26 (Demo), owner | `22-DEMO-RESULTS.md` R-7 |
| Codes still unobserved on the Demo: -4048, -4046 and the code for a leverage above a lower bracket's maximum [NOT_TESTED] | Classified by the error table from the documentation; the Demo answered only -4047, -4028 and -2019 | Phases 24 to 26 | 22-03 SUMMARY; `22-DEMO-RESULTS.md` |
| Mainnet attestation of brackets, formulas and the configuration calls [NOT_TESTED] | No mainnet use; the Demo bracket table (first bracket 125x) differs from the mainnet figure the change-log quotes | Phases 25 and 26 | `22-RESEARCH.md` 2.2 |
| Documentation reads of Phase 22 were cited from the research, not re-fetched during execution [DOC] | The API pages are the research's reading of the official OpenAPI document of 2026-10-23 | next documentation pass | 22-03 SUMMARY |

## Requirement status after Phase 22

- RISK-01 and RISK-02: the status recorded in `.planning/REQUIREMENTS.md` is unchanged (no change made by Phase 22).
- EXEC-01: stays Pending. Demo and mainnet proof of the guard in a running process belong to Phases 24 to 26.
- EXEC-02: stays Pending. The post-fill liquidation watch is built and tested but NOT active before Phase 24.
- `requirements.mark-complete` was skipped by plan rule; `.planning/REQUIREMENTS.md` is not edited by this phase.
- Inherited G3-001 (the Change-Position-Mode wording) is closed by the `docs/SOURCES.md` section "Facts read for Phase 22" (cited from the research, not re-fetched). Inherited G4-039 is delivered for the in-memory snapshot only: the guard's verified margin type, leverage and equity complete the snapshot handed to protection; the persisted write-once row is untouched and Phase 24 builds it later.

The assistant recorded the owner's answers and applied them; it decided none of these items itself.
