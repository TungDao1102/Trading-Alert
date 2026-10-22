# Demo evidence plan: the owner runs the capture cases

Written for the owner by quick task 261021-sj0. It tells you which commands to run on Binance Demo, which files each run leaves behind and which later phase or open item reads them. It decides nothing. Every result is labelled "demo-observed, not mainnet" (D-17); no result may choose a trading parameter, a model or a limit number; D055 stays OPEN (the closure is yours, see `19-DEC-D055-DRAFT.md`).

The tool is `scripts/demo_probe.py` (ten new opt-in cases, `CAPTURE_CASES`) plus the existing `scripts/user_data_smoke.py` (one re-run, Step 2). The code and its offline tests were written without any network call: no agent ran `--execute` of anything.

## Safety

- You run every `--execute`. Agents never do. Each `--execute` needs an interactive terminal and a typed phrase (`DEMO PROBE <SYMBOL>` for the probe, `DEMO SMOKE <SYMBOL>` for the smoke; for the Phase 18 symbol: `DEMO PROBE BTCUSDT` and `DEMO SMOKE BTCUSDT`).
- Demo only: there is no host, URL, key or LIVE option in either tool, and a LIVE credential variable in the environment refuses the run. Credentials come only from the Demo variables your environment already uses; never paste them into a file or into chat.
- One process per Demo account: the listenKey is a singleton. Stop every other process on the Demo account (the paper runtime, the rehearsal) before a run.
- The tool never retries. On a flaky network re-run one case at most once and then stop. Never provoke a 418 or 429 on purpose; if one happens the run stops by itself (`ABORTED_BAN`), and you wait out the `retry_after_seconds` the evidence records.
- Each order case opens at most the approved quantity (an order above your approved quantity or above your notional cap is refused before it is sent). After every case the cleanup cancels all orders and all algo orders and closes any residual position with one reduce-only MARKET order, then checks the symbol is flat. If the run ends `CLEANUP_FAILED` or `ABORTED_BAN`, open the Demo account and clean it by hand (open orders, open algo orders, position).
- One-way mode only. In hedge mode every order case ends NOT_OBSERVED (`hedge mode: reduceOnly cannot be sent`) and sends nothing.
- Results are facts: a case ends OBSERVED (with the exchange answers) or NOT_OBSERVED (with the reason). Nothing here says a behaviour is good or safe.

## Step 0: your limits file

You create and approve `.planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml` and record the approval in a decision note of your own. The agent did not create or approve it, and the Phase 18 files (`18-probe-limits.toml`, `18-smoke-limits.toml`) are unchanged.

Layout: the Phase 18 keys, the ten new `[optional_cases]` keys, and three new keys that are required exactly when their case is on. Every number is yours: nothing is proposed here, and every placeholder below is written `<OWNER: ...>`, so the loader refuses the file until you replace each one.

```toml
[order]
symbol = "<OWNER: the Demo symbol>"
quantity = "<OWNER: approved quantity>"
max_notional_quote = "<OWNER: notional cap in quote currency>"
far_price_fraction = "<OWNER: strictly between 0 and 1>"
# only with triggered_bracket or tp1_from_fill:
near_trigger_fraction = "<OWNER: strictly between 0 and 1>"
# only with gtd_expiry:
gtd_lifetime_seconds = <OWNER: whole seconds>

[waits]
case_timeout_seconds = <OWNER: whole seconds>
cleanup_timeout_seconds = <OWNER: whole seconds>
# only with gtd_expiry:
gtd_expiry_wait_seconds = <OWNER: whole seconds, greater than gtd_lifetime_seconds>

[optional_cases]
explicit_time_in_force = false
stream_gap = false
market_lot_size_out_of_range = false
account_capture = <OWNER: true or false>
algo_query_timing = <OWNER: true or false>
close_position_with_position = <OWNER: true or false>
stop_trigger_after_fill = <OWNER: true or false>
stop_absent_same_id = <OWNER: true or false>
manual_close_open_legs = <OWNER: true or false>
commission_realized_pnl = <OWNER: true or false>
triggered_bracket = <OWNER: true or false>
tp1_from_fill = <OWNER: true or false>
gtd_expiry = <OWNER: true or false>
```

What the loader enforces (it names keys, never values, when it refuses):

- `near_trigger_fraction` is a plain decimal strictly between 0 and 1, required exactly when `triggered_bracket` or `tp1_from_fill` is true and refused otherwise. The closer to 1, the closer the trigger sits to the live mark price; a trigger case ends NOT_OBSERVED when the price does not reach it within `case_timeout_seconds`.
- `gtd_lifetime_seconds` and `gtd_expiry_wait_seconds` are positive integers, required exactly when `gtd_expiry` is true and refused otherwise; the wait must be greater than the lifetime. Binance requires `goodTillDate` greater than now plus 600 seconds; the loader does not check that floor, so a lifetime below it is allowed and the exchange answer to it is evidence (A1).
- A larger `case_timeout_seconds` (your choice) gives the trigger cases more time. A key that is absent means the case is off, and a file with none of the ten keys behaves exactly like the Phase 18 file.

## Step 1: dry run first (offline)

```
uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file .planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml --evidence-dir <a temporary directory>
```

Nothing is sent: the dry run uses fakes and virtual time and writes `demo-probe-DRYRUN-<stamp>.json` with every case NOT_REHEARSED. Expect `acceptance: FAIL` (FAKE evidence never passes). Expect the dry run to end `FAILED` with exit 1 when your quantity is not on the step grid of the FAKE market (step 0.001; the Phase 18 quantity 0.0008 is not): the order cases then show an "order bound" error. That is an artifact of the FAKE step (the real Demo step is 0.0001), not a defect; read only that the ten case ids are listed and that no case says "script error".

## Step 2: re-run the user-data smoke (18-UAT item 11)

```
uv run python -m scripts.user_data_smoke --environment DEMO --smoke-limits-file .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-smoke-limits.toml --evidence-dir .planning/phases/18-user-data-stream-error-taxonomy/evidence --fixtures-dir .planning/phases/18-user-data-stream-error-taxonomy/evidence/smoke-rerun-fixtures --execute
```

Typed phrase: `DEMO SMOKE BTCUSDT`.

- Why: 18-UAT item 11 (live Demo smoke with real user-data events) is blocked until you re-run it. The last Demo smoke (`user-data-smoke-EVIDENCE-20261016T140446Z.json`) predates the 26 review-fix commits, and CR-01 and CR-02 touched that path.
- Expected: one `user-data-smoke-EVIDENCE-<stamp>.json` with `sdk_route_delivery` PASS, the ORDER_TRADE_UPDATE events NEW and CANCELED, and the account flat at the end; the raw frames go to the `--fixtures-dir` you named.
- Consumers: 18-UAT item 11, then Phase 24 and Phase 25 (the stream path).
- Run it before the probe runs.

## Step 3: the probe runs, one section per case

Common command (replace `<case id>`; the `--only` list may name several ids, comma separated, and must name only cases whose key is true in your file):

```
uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file .planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml --evidence-dir .planning/phases/19-execution-plan-binding-price-check/evidence --fixtures-dir .planning/phases/19-execution-plan-binding-price-check/evidence/fixtures --only <case id> --execute
```

Typed phrase: `DEMO PROBE BTCUSDT` (the symbol of your file). Running all enabled cases in one session without `--only` is also valid; run the GTD case last, it waits more than 10 minutes. An `--only` run reports `acceptance.overall` FAIL because the required Phase 18 set did not run: that is by design, read the per-case verdicts.

Files every run leaves (in the evidence directory unless noted):

- `demo-probe-EVIDENCE-<stamp>.json`: the evidence document, schema `demo-probe-evidence/schema-1`. Each case has `details` (the facts named below), `observations` (every exchange answer: HTTP class, code, category, message), `frames` and `cleanup`.
- In the `--fixtures-dir`: the raw user-data payloads `<case_id>-<NNN>-<event>.json` (scrubbed), and for the ten new cases the REST answers `<case_id>-rest-<NNN>-<operation>.json` (scrubbed), and `provenance.md` listing every file of the run with its label. A dry run writes none of these.

### 1. account_read_only_capture (key `account_capture`)

- Sends no order. Six read-only calls, in order: account information (/fapi/v3/account), all balances (/fapi/v3/balance), account configuration, symbol configuration, leverage brackets, position mode.
- Files: `account_read_only_capture-rest-001-account_information.json` to `-006-position_mode.json`.
- Read in `details`: `<label>_fields` (every field name the exchange returned, list positions shown as `*`) and `<label>_field_count` for `account_information`, `account_balance_all`, `account_config`, `symbol_config`, `leverage_brackets`, `position_mode`; `<label>_truncated` appears only if an answer was cut at 2000 keys. The fixture files hold the values (including the account alias if the exchange returns one; check them before you commit any fixture).
- Consumers: Phase 21 SC1 (the equity field of /fapi/v3/account or /fapi/v3/balance) and G4-039; Phase 22 SC1 (symbolConfig), SC2 (leverage brackets), SC3 (availableBalance), SC4 (one-way, single-asset margin: `dualSidePosition`, `multiAssetsMargin`; G3-001).

### 2. algo_query_timing_after_new (key `algo_query_timing`)

- Sends two far legs, no fill: a reduce-only STOP_MARKET leg (the shape that met -2013 in the 20261021T132718Z run) and a non-reduce-only far STOP BUY carrier. For each leg: the leg is queried by client id and by algo id at once, then (if either answer is not OK) once more after one `case_timeout_seconds` wait; then it is listed, cancelled and queried again. At most the approved quantity per leg.
- Read in `details` (prefix `ro` or `carrier`): `<prefix>_algo_id`, `<prefix>_query1_by_client_id`, `<prefix>_query1_by_client_id_elapsed_ms`, `<prefix>_query1_by_algo_id` (and `query2` when the wait happened), `<prefix>_queries_before_all_ok`, `<prefix>_listed_in_open_algo_orders`, `<prefix>_cancel`, `<prefix>_after_cancel_by_client_id`, `<prefix>_after_cancel_by_algo_id`.
- Consumers: the -2013-right-after-NEW question of the 20261021T132718Z run; 19 O-05 P5 and P11; the 20-DEFERRED stop re-place row; the `protection.py` stop-confirmation reading of ABSENT (WR-04).

### 3. close_position_stop_with_position (key `close_position_with_position`)

- Sends a marketable BUY LIMIT of the approved quantity (the entry), then a closePosition STOP_MARKET SELL at the far-below trigger and a closePosition TAKE_PROFIT_MARKET SELL at the far-above trigger; lists and cancels the accepted legs.
- Read: `close_position_stop_accepted`, `close_position_tp_accepted`, `close_position_stop`, `close_position_tp` (the exact error if refused), `with_legs_open_algo_orders`, `with_legs_position`, `stop_listed_*` and `tp_listed_*` (the row fields the exchange lists).
- Consumers: 19 P1 and A6 (the model rests on it), the O-01 D055 closure draft.

### 4. stop_would_trigger_after_fill (key `stop_trigger_after_fill`)

- Sends the entry, then a closePosition STOP_MARKET SELL with its trigger on the wrong side (far above the mark). If it is accepted the leg may trigger at once and the cleanup flattens.
- Read: `would_trigger_accepted`, `would_trigger_stop` (for example -2021), and if accepted `would_trigger_status` and `after_*`.
- Consumers: 19 P8 (the B5 classification of -2021); Phase 25 SC1 "price crossed SL" and "SL rejected after fill".

### 5. stop_query_absent_then_same_id (key `stop_absent_same_id`)

- This is your requested probe: a deliberate same-id re-placement on Demo, not a retry of a failed answer. After the entry it queries a never-used client algo id, places a closePosition stop with that id, queries it at once, then places the same id again (same shape, then the reduce-only explicit-quantity shape), lists the algo orders, cancels once and queries again.
- Read: `query_before_place`, `first_place`, `query_right_after_place` and `query_right_after_place_elapsed_ms`, `same_id_replace_close_position`, `same_id_replace_reduce_only`, `legs_listed_with_id`, `legs_listed_total`, `cancel_once`, `query_after_cancel`.
- Consumers: 20-DEFERRED "Stop re-place of B2 / B3" (your answer at plan 20-26), Q5.

### 6. manual_close_with_open_legs (key `manual_close_open_legs`)

- Sends the entry, a closePosition stop and a closePosition take profit, then one reduce-only MARKET SELL for exactly the held quantity (a manual close). It waits one `case_timeout_seconds` for the legs to end, records both legs, and cancels by hand only a leg that is still open.
- Read: `manual_close`, `manual_close_status`, `manual_close_executed_qty` (the answer to the close, P9), `held_quantity`, `stop_auto_cancelled` and `tp_auto_cancelled` (true / false / unknown), `stop_statuses_rest`, `stop_statuses_frames`, `stop_ai`, `stop_aq`, `stop_rm`, `stop_algo_update_sequence` (and the same for `tp`), `after_close_*`.
- Consumers: 19 P6, P9, A3, A4 and A8 (the reduce-only MARKET answer); the 20-DEFERRED A3 and Manual-close (G4-035) rows; Phase 25 G2-016 manual-close drill.

### 7. commission_vs_realized_pnl (key `commission_realized_pnl`)

- Sends the entry and a reduce-only MARKET close of the held quantity, then reads the trades of the close order and of the entry order (waiting one `case_timeout_seconds` for the close trades) and the income rows from the earliest trade time (one more wait for the rows of these trades).
- Read: `entry_order_id`, `close_order_id`, `entry_trade_<n>` and `close_trade_<n>` (`trade_id|side|price|qty|quote_qty|commission|commission_asset|realized_pnl|maker|time_ms`), `income_<n>` (`income_type|income|asset|trade_id|tran_id|time_ms`), and the arithmetic named `derived_`: `derived_sell_quote_minus_buy_quote`, `derived_sum_realized_pnl_trades`, `derived_sum_commission_trades` (written only when every commission asset is the same), `derived_income_realized_pnl_sum`, `derived_income_commission_sum`. The tool gives no verdict on whether realizedPnl includes the commission; `LIVE_NET_PNL_SEMANTICS_VERIFIED` is your decision.
- Consumers: G2-042 and A9 (Phase 24 owns the verification; Phase 21 D033 daily loss depends on it).

### 8. triggered_close_position_bracket (key `triggered_bracket`; needs `near_trigger_fraction`)

- Sends the entry, reads the live mark price (premiumIndex, not the one-minute kline), then a closePosition STOP_MARKET SELL just below the mark and a closePosition TAKE_PROFIT_MARKET SELL just above it (the owner fraction decides how close). It waits one `case_timeout_seconds` for a leg to progress, then one more for the position to be flat and the other leg to end. A -2013 answer never counts as an ended or triggered leg. If nothing triggers the case ends NOT_OBSERVED with every fact recorded.
- Read: `live_mark_price`, `stop_trigger_price`, `tp_trigger_price`, `triggered_leg` (stop / tp / both / unknown), and for each leg the full raw ALGO_UPDATE sequence: `<leg>_algo_update_count`, `<leg>_algo_update_sequence` (`X|ia|ai|aq|rm|E|T` per delivery, in delivery order), `<leg>_repeated_statuses` (for example `NEW x2`: the `ia` double delivery), `<leg>_statuses_beyond_new_canceled`, `<leg>_ia_values`, `<leg>_ai_values`, `<leg>_aq_values`, `<leg>_child_<n>` (the raw child ORDER_TRADE_UPDATE `c|X|x|ot|z|ap|n|N|rp|T`, so the commission `n` and `rp` are there), `<other>_auto_cancelled`, `after_trigger_*`, `child_trades_query`.
- Consumers: 19 P2, P11 and A3; the 20-DEFERRED A3 row; `18-VERIFICATION.md` (line 66: ALGO_UPDATE statuses beyond NEW and CANCELED, the `ia` double delivery, `ai` and `aq` were not observed), `src/domain/algo_status.py` classes; Phase 24 G2-030 (`09-EXCHANGE-FACTS.md` Demo cross-check).

### 9. tp1_quantity_from_fill (key `tp1_from_fill`; needs `near_trigger_fraction`)

- Sends the entry, sizes TP1 from the held quantity with the production quantizer (`quantize_to_lot` on the intersection of LOT_SIZE and MARKET_LOT_SIZE, and the constant `TP1_QUANTITY_FRACTION`), then sends one reduce-only TAKE_PROFIT_MARKET SELL of that quantity just above the live mark, and waits one `case_timeout_seconds` for it to trigger.
- Read: `held_quantity`, `tp1_quantity`, `tp1_quantity_lot_size_only`, `tp1_fraction_source`, `tp_trigger_price`, `tp1_notional_at_trigger`, `min_notional` (facts, no production gate verdict), `tp1_statuses_rest`, `tp1_statuses_frames`, `tp1_aq` (executed quantity at trigger), `tp1_algo_update_sequence`, `tp1_child_<n>`, `after_tp1_position` (the observed remainder).
- Consumers: 19 P10, A7 and O-03.

### 10. gtd_entry_expiry_status (key `gtd_expiry`; needs `gtd_lifetime_seconds` and `gtd_expiry_wait_seconds`)

- Sends one far BUY LIMIT with timeInForce GTD of the approved quantity and a `goodTillDate` of the current time (whole seconds, from the tool clock) plus your lifetime, then waits `gtd_expiry_wait_seconds` (more than 10 minutes) for the order to end. If it is still open it is cancelled once and the case is NOT_OBSERVED. A rejected placement is OBSERVED: the code is the answer.
- Read: `good_till_date_ms`, `good_till_date_echoed`, `placed_at_utc`, `rest_statuses`, `frame_statuses` (`order_status/execution_type/expire_reason` per frame), `terminal_status`, `seconds_to_terminal`, `raw_order_updates` (`X|x|T` of the raw frames).
- Consumers: 19 P4, A2 and part of A1; the 20-DEFERRED A2 row (`UnknownEntryResolver`, restart recovery).

## Consumers table

| Case | What it answers | Who reads it |
|------|-----------------|--------------|
| account_read_only_capture | The equity field, symbolConfig, leverage brackets, availableBalance, one-way and single-asset margin flags | Phase 21 SC1, G4-039; Phase 22 SC1 to SC4, G3-001 |
| algo_query_timing_after_new | Whether -2013 right after a NEW algo placement is a timing window, by client id and by algo id | 19 O-05 P5 and P11; 20-DEFERRED stop re-place row; `protection.py` (WR-04) |
| close_position_stop_with_position | A6: is a closePosition stop accepted with a position open | 19 P1 and A6; the O-01 D055 closure draft |
| stop_would_trigger_after_fill | The answer to a stop on the wrong side after a fill | 19 P8 (B5 classification of -2021); Phase 25 SC1 |
| stop_query_absent_then_same_id | What the exchange does with a second placement of one client algo id | 20-DEFERRED "Stop re-place of B2 / B3" (plan 20-26), Q5 |
| manual_close_with_open_legs | A3: are the legs cancelled by the exchange after a manual close; the reduce-only MARKET answer | 19 P6, P9, A3, A4, A8; 20-DEFERRED A3 and Manual-close (G4-035); Phase 25 G2-016 |
| commission_vs_realized_pnl | G2-042 and A9: the commission and realized PnL facts of a round trip | Phase 24 (verification), Phase 21 D033; your decision `LIVE_NET_PNL_SEMANTICS_VERIFIED` |
| triggered_close_position_bracket | The ALGO_UPDATE lifecycle after a real trigger, the child order, the other leg | 19 P2, P11, A3; 20-DEFERRED A3; `18-VERIFICATION.md` line 66; Phase 24 G2-030 |
| tp1_quantity_from_fill | A7: MARKET_LOT_SIZE at trigger, the TP1 quantity from the real fill | 19 P10, A7, O-03 |
| gtd_entry_expiry_status | A2: a GTD entry that expires is `EXPIRED` and terminal; part of A1 | 19 P4, A2, A1; 20-DEFERRED A2 row |

## Not covered here

Listed so nobody assumes otherwise:

- P3 partial fill: only the existing derived `partial_fill` case.
- P5 stream loss: only the existing optional `stream_gap_during_case`.
- P7 fill, cancel and trigger race.
- The real 418 duration and the 429 queue order of plan 20-21: never provoked, by your instruction.
- The stream states of SAFE_MODE exit row 7: the smoke and stream evidence only.
- Hedge Mode.

## After a run

Commit nothing automatically. You decide which fixtures move into `tests/fixtures/phaseNN/recorded_demo/` with their provenance; later phases cite the evidence file name and its stamp. Check each fixture file before it enters git (the tool scrubs known secrets, but the account captures hold account values).
