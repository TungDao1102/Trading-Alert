# Decision audit D001 to D083 (proposals only)

Date: 2026-10-23. Requested by the owner. Three read-only reviewers (opus) covered D001-D028, D029-D056 and D057-D083; their full reports are kept outside the repo (`p20-decrev/part-1..3.md`). The three highest-severity claims were checked in the code by the orchestrator (see "Verified"). Everything else is a reviewer lead.

**This file changes no decision.** `docs/DECISIONS.md` belongs to the owner. Each row below is a proposal; the owner accepts, rejects or edits it, and a new DECISIONS row is written only after that.

Totals: about 45 OK, 23 OK with a note, 12 QUESTIONABLE, 3 WRONG-OR-OUTDATED. The research rows (D057-D076) hold up; the problems are in order placement and rate limits.

## Verified in code

| Claim | Result |
|-------|--------|
| `expire_pending_entry` has no scheduled caller | Confirmed: called only on hand-off failure (`manager.py` ~1165, ~1232) and operator close (~2501) |
| `transition_signal` / `transition_trade_plan` are never called | Confirmed: defined in `src/persistence/entities.py` only |
| Live path has no same-symbol refusal | Confirmed: no `CONFLICT_WITH_OPEN_POSITION` equivalent in `src/execution` or `src/risk` |

## A. Safety gaps (decision or code needed; carried to Phase 24 in `20-DEFERRED.md`)

| Decision | Proposal |
|----------|----------|
| D079 / D042 | Make a scheduled cancel of an unfilled entry at plan expiry a Phase 24 blocker. Record the resting-entry-while-down risk as an explicit, alerted, owner-accepted risk, or evaluate `countdownCancelAll` (unverified for algo orders) |
| D082 | Refuse a second plan on a symbol with an active plan or position before placement, as backtest and paper do; keep the reconcile check as a backstop |
| D028 | Owner chooses: name the component that writes Signal/TradePlan APPROVED, or state that V1 does not maintain those statuses (Approval row is the authority) |

## B. Wording that is wrong or stale against the code (text edits, no behavior change)

| Decision | Problem | Proposed wording change |
|----------|---------|-------------------------|
| D080 | Says stops are never re-sent; code re-places a stop proven absent under the same client id (B2/B3, owner 2026-10-22) | State: placements of entries are never re-sent; a never-confirmed stop proven absent by this step's REST query is re-placed once per step under the same id |
| D034 | Still carries "re-place the SL"; D077 and D080 superseded it; "protective orders always allowed" conflicts with D072/D081 pauses | Add: partly superseded by D077 and B2/B3; protective actions are subject to the REST gate pause (D072, D081) |
| D077 | Item 5 says P6/A3 unobserved; they were observed 2026-10-22 | Update the evidence line |
| D055 | Says model (b) (pre-placed reduce-only stop) is unverified on Demo; Demo accepted it on 2026-10-16. D079 never compared (a) and (b) on outage risk | Record the comparison and keep or revisit (a) explicitly |
| D051 | Write-ahead order and "not found and younger than 3 days => REJECTED" are outdated by D079/D080 | Mark those parts superseded |
| D083 | Title uses "D-10", an ID with three meanings across Phases 18, 19, 20 | Rename |
| D022 | Mode list lacks SHADOW / DEMO / CANARY; SAFE_MODE is a gate, not a peer mode | Separate activity, release stage and the SAFE_MODE gate |
| D011, D013, D062, D075, D043, D046, D050 | Still "Provisional" or lacking pointers to D036/D079, D030, D064, D069; D075 says R7 open (answered 2026-10-19); D046 "basis points" wording; D050 item (d) says `BINANCE_TESTNET_*` | Add pointers or correct the wording |
| D081 | The maximum lot-filter age has no config key, so the NOT_CONFIGURED guard cannot catch it | Name an owner key |
| D079 | Item 3 names the wrong config file; item 6 overstates Demo coverage (A4 and P5 could be run) | Correct |

## C. Owner decisions with trade-offs

| Decision | Question |
|----------|----------|
| D009 / D017 / D059 | Historical open interest is available from the public archive `data.binance.vision` (reviewer: daily `metrics` files from 2020-09-01, HTTP 200 on 2026-10-23); not verified by the orchestrator. If true, amend D009 and relax the D059 deadline. Is any machine collecting OI now? |
| D052 | The TP1-below-min-notional refusal is not an exchange rule (Demo R-P10). Changing it needs a protocol bump and regeneration. Belongs to O-03 (Phase 21 / 22) |
| D040 | A USD 50-100 canary at 0.5% risk with a stop of at least 0.79% cannot reach the 50 USDT minimum notional seen on Demo; sub-account eligibility unverified; "zero unprotected positions" undefined under stop-after-fill |
| D072 | On Futures the 3-day wait is the normal 418 path (no documented Retry-After); the gate is per process while bans are per IP and the collector bypasses it. D083 defers the -1003 parse to Phase 24; no change now |
| D005 | Signals are valid 4 or 8 hours; many 4H closes fall outside the owner's available hours. Measure the answered fraction during SHADOW before trusting backtest numbers |
| D001 | State that an agent may draft parameter values before any result, the owner freezes them, and an LLM never chooses among results |
| D035 | Not built; Demo runs x20 CROSSED. Revisit when built |
| D014 / D024 | D014 keeps the TradeStatus list although D045 removed the trades table; D024 relies on the plan status D028 shows is never set |

## Not verified by anyone

Mainnet min notional and step values; `countdownCancelAll` effect on algo orders; sub-account availability; VPS region rules (D042); whether a reduce-only MARKET order can flip a position (A4); how Phase 24 will route live signals (shadow ledger or an expiry scheduler).
