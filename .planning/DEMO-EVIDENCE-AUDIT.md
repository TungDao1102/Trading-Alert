# Demo evidence audit, Phases 16 to 26

Written 2026-10-22 for the owner. Reference only: it lists what is unclear or unobserved and what
Binance Demo (or another connected machine) would have to show. It decides nothing. Every Demo result
is labelled "demo-observed, not mainnet" (D-17); no result here may choose a trading parameter.

Sources read: `18-VERIFICATION.md`, `18-UAT.md`, `17-VERIFICATION.md`, `19-UAT.md`, `19-OWNER-GAPS.md`,
`20-DEFERRED.md`, `16-50-operator-verification.md`, the Phase 16/18 `deferred-items.md`, ROADMAP
Phases 21 to 26. Per-plan PLAN and SUMMARY files were not read one by one.

## What the 2026-10-21 probe run already gave

Evidence: `.planning/phases/19-execution-plan-binding-price-check/evidence/demo-probe-EVIDENCE-20261021T132718Z.json`
(`REAL_DEMO`, `COMPLETE`, acceptance `PASS`, no ban, account flat before and after).
15 of 16 cases OBSERVED. Not observed: `triggered_market_exit_lifecycle` (the trigger was not reached
within `case_timeout_seconds`).

Limits of that run:

- A6 / P1 is still unproven. `closeposition_stop_flat` ran with no position and got `-4509`. The
  full-fill cases placed the stop with `close_position=false` and an explicit quantity.
- `partial_fill` is derived from other cases (`derived_from`); every LIMIT entry filled completely.
- Unexplained: `query_algo_order` returned `-2013 ORDER_ABSENT` right after a `NEW` algo placement in
  `below_min_notional_reduce_only_leg` and `triggered_market_exit_lifecycle`, but returned `NEW` in
  `full_fill_protective_quantity`.

## Phase 16 (paper runtime)

Almost nothing needs Demo. Items for a connected machine:

| Item | Source | What to record |
|---|---|---|
| Heartbeat monitor | `16-50-operator-verification.md` | UTC times of collector stop, alert received, start, recovery notice; systemd version. The user's statement is not an independent observation. |
| Telegram tap from an unknown chat or user (G2-014) | ROADMAP Phase 24 | Rejected with no state change and a journaled `chat_gate_rejected`. Needs a second Telegram account or a group. |
| Alert of a signal evaluated during a planned stop (B1-WR-04) | Phase 16 `deferred-items.md` | Whether the alert is delivered. |

## Phase 17 (persistence)

The Binance leftovers were `-4116` for algo client ids and id reuse after the first order closed.
Phase 18 probe cases `duplicate_client_algo_id` and `id_reuse_*` are OBSERVED (2026-10-16 and again
2026-10-21). The `docs/SOURCES.md` line that says "still NOT verified live" should be updated from that
evidence (docs task, no Demo needed).

## Phase 18 (user-data stream, error taxonomy)

| Gap | Source | How to get evidence |
|---|---|---|
| Stream smoke not rerun after the 26 review-fix commits | 18-UAT item 11 | `uv run python scripts/user_data_smoke.py --environment DEMO --execute` |
| ALGO_UPDATE: only `NEW` and `CANCELED` seen; `ia` double delivery and child `ai`/`aq` not observed | 18-VERIFICATION | A really triggered stop (new probe case) |
| `partial_fill`, `triggered_market_exit_lifecycle` | 18-VERIFICATION, 2026-10-21 run | Same triggered-stop case; a partial fill may be impossible on Demo (A5) |
| Codes seen only in documentation: `-2019`, `-4164`, `-1021`, `-4024` | 18-VERIFICATION | `-1021` needs a deliberate clock offset; low priority, owner decides |
| `/private` URL form: the SDK builds it, the form was not captured | 18-VERIFICATION | Log of the connection in the smoke run |
| `MARKET_LOT_SIZE` out of range | optional case | Enable `market_lot_size_out_of_range` in a new owner limits file |
| Keys have no withdrawal right and are IP-restricted (OPS-02) | 18-UAT | Owner attestation, not code |

## Phase 19 (execution plan binding)

P1 to P11 are listed in `19-OWNER-GAPS.md` section 2. After the 2026-10-21 run:

- Not covered: P1, P2, P3, P6, P7, P8, P10; P4 and P5 only in part.
- P9 (emergency MARKET close) and P11 (account flat) were touched by the probe cleanup, but not as a
  recorded close of a protected position.
- The `-2013` observation above.
- `max_last_price_age_ms` and the `get_last_price` ticker shape were never observed on Demo.

## Phase 20 (reconcile, SAFE_MODE)

From `20-DEFERRED.md`, "Needs a connected machine (Demo)":

| Item | Label |
|---|---|
| A2: GTD expiry reports a terminal status | NOT_TESTED |
| A3: Binance cancels `closePosition` legs when the position closes | DESIGN, not observed |
| Real HTTP 418 ban outlives 259200 s | NOT_TESTED. Do not provoke it. |
| 429/418 queue order against the real exchange | DOC |
| Stop re-place with the same id (B2/B3) | NOT_TESTED |
| Manual close outside the system (G4-035) | NOT_TESTED |
| Stream states for SAFE_MODE exit row 7 (`LIVE` when healthy) | NOT_TESTED |

## Phases 21 to 26 (what will be needed)

| Phase | Needs |
|---|---|
| 21 | Equity field of `/fapi/v3/account` and `/fapi/v3/balance`; whether `realizedPnl` excludes commission (G2-042) |
| 22 | `symbolConfig`, margin type and leverage changes, leverage brackets, `availableBalance`, position mode |
| 23 | Telegram only: replayed callbacks, CONFIRM after TTL, other user |
| 24 | End-to-end rehearsal on the VPS; `entry_price` float noise at the SDK boundary; live commission rates; IP whitelist |
| 25 | `pytest -m demo` scenario suite and a 3-week soak, unattended; "Demo cross-check" lines of `09-EXCHANGE-FACTS.md` |
| 26 | Mainnet read-only key check of exchangeInfo, commission and balances; canary sub-account |

## Documentation re-read, 2026-10-22

One fetch per page, one retry at most (AGENTS.md).

| Page | Result |
|---|---|
| Change Position Mode | Read. `dualSidePosition` "true" Hedge, "false" One-way; applies to every symbol; UM and CM share the setting; rejected with `-4067` (open orders) or `-4068` (open positions); IP weight 1; response `{"code": 200, "msg": "success"}`. This answers G3-001 for the wording on the page; `docs/SOURCES.md` still needs the edit. |
| Error codes | Read. `-1003` has two texts: "Too many requests; current limit is %s requests per minute. Please use the websocket for live updates to avoid polling the API." and "Way too many requests; IP banned until %s. Please use the websocket for live updates to avoid bans." The format of `%s` is still not on the page (P20-ERR1003). `-2021` "Order would immediately trigger." `-2013` "Order does not exist." `-4116` "clientOrderId is duplicated". `-4509` is not on the page; it stays Demo-observed only. |
| ORDER_TRADE_UPDATE, ALGO_UPDATE | Not obtained. Both URLs tried (the `docs/...` form and the catalog form) returned the landing page. Still UNVERIFIED: `t` on every partial fill, the `ALGO_UPDATE.o.rm` list, whether `CONDITIONAL_ORDER_TRIGGER_REJECT` still exists. Next try: the `llms-full.txt` or the `.md` page named in `19-GAP-RESEARCH-CHECKLIST.md`, or read the pages by hand. |

## Suggested order for the owner

1. Session 1: triggered stop with a position (P1, P2, A3, P6, P8, P10, B2/B3, the `-2013` question),
   plus `user_data_smoke --execute`.
2. Session 2: Phase 21/22 reads and one small open and close for commission versus `realizedPnl`.
3. Session 3: A2 (GTD expiry), which needs more than 10 minutes of waiting.
4. Any time: heartbeat and Telegram checks.

The probe cases for sessions 1 to 3 are planned in quick task `261021-sj0`; the runbook with
commands will be `.planning/DEMO-EVIDENCE-PLAN.md`.
