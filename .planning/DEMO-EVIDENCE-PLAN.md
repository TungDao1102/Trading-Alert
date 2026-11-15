# Demo evidence plan: the owner runs the capture cases

Written for the owner by quick task 261021-sj0 and extended by quick task 261022-sj1 (five more cases and the section "One session: all cases") and by quick task 261023-sj2 (eight more cases, sections 16 to 23), and by Phase 22 (six more cases, sections 24 to 29, `SJ3_CASES`). It tells you which commands to run on Binance Demo, which files each run leaves behind and which later phase or open item reads them. It decides nothing. Every result is labelled "demo-observed, not mainnet" (D-17); no result may choose a trading parameter, a model or a limit number; D055 stays OPEN (the closure is yours, see `19-DEC-D055-DRAFT.md`).

The tool is `scripts/demo_probe.py` (ten opt-in cases of 261021-sj0, `CAPTURE_CASES`, five more of 261022-sj1, `SJ1_CASES`, eight more of 261023-sj2, `SJ2_CASES`, and six of Phase 22, `SJ3_CASES`) plus the existing `scripts/user_data_smoke.py` (one re-run, Step 2). The code and its offline tests were written without any network call: no agent ran `--execute` of anything.

## Safety

- You run every `--execute`. Agents never do. Each `--execute` needs an interactive terminal and a typed phrase (`DEMO PROBE <SYMBOL>` for the probe, `DEMO SMOKE <SYMBOL>` for the smoke; for the Phase 18 symbol: `DEMO PROBE BTCUSDT` and `DEMO SMOKE BTCUSDT`).
- Demo only: there is no host, URL, key or LIVE option in either tool, and a LIVE credential variable in the environment refuses the run. Credentials come only from the Demo variables your environment already uses; never paste them into a file or into chat.
- One process per Demo account: the listenKey is a singleton. Stop every other process on the Demo account (the paper runtime, the rehearsal) before a run.
- The tool never retries. On a flaky network re-run one case at most once and then stop. Never provoke a 418 or 429 on purpose; if one happens the run stops by itself (`ABORTED_BAN`), and you wait out the `retry_after_seconds` the evidence records.
- Each order case opens at most the approved quantity (an order above your approved quantity or above your notional cap is refused before it is sent). The only exceptions are `insufficient_margin_order` (section 19) and `margin_insufficient_at_target_leverage` (section 27): each sends your own `insufficient_margin_quantity`, which is deliberately larger than the margin allows, so the `max_notional_quote` check and the approved-quantity check are NOT applied to that one order (it keeps the symbol, the flat precheck, the far-price band, the step grid and the cleanup). No other case may send more than the approved quantity or notional, and the tests pin that. After every case the cleanup cancels all orders and all algo orders and closes any residual position with one reduce-only MARKET order, then checks the symbol is flat. If the run ends `CLEANUP_FAILED` or `ABORTED_BAN`, open the Demo account and clean it by hand (open orders, open algo orders, position).
- Phase 22 cases (sections 24 to 29): `symbol_config_change_to_isolated` changes the margin type and leverage of your Demo symbol, and `margin_type_change_with_resting_order` and `leverage_above_bracket_maximum` do so only if the exchange accepts a request it is expected to refuse (the case then asks once for the previous value back). The previous configuration is always in the evidence; restoring it after `symbol_config_change_to_isolated` is your choice. Each case has its own flag in your file, and no agent runs any of them.
- One-way mode only. In hedge mode every order case ends NOT_OBSERVED (`hedge mode: reduceOnly cannot be sent`) and sends nothing.
- Results are facts: a case ends OBSERVED (with the exchange answers) or NOT_OBSERVED (with the reason). Nothing here says a behaviour is good or safe.

## Step 0: your limits file

You create and approve `.planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml` and record the approval in a decision note of your own. The agent did not create or approve it, and the Phase 18 files (`18-probe-limits.toml`, `18-smoke-limits.toml`) are unchanged.

Layout: the Phase 18 keys, the twenty-nine new `[optional_cases]` keys (ten of 261021-sj0, five of 261022-sj1, eight of 261023-sj2 and six of Phase 22 plans 22-05 and 22-09), and six new keys that are required exactly when their case is on. Every number is yours: nothing is proposed here, and every placeholder below is written `<OWNER: ...>`, so the loader refuses the file until you replace each one.

```toml
[order]
symbol = "<OWNER: the Demo symbol>"
quantity = "<OWNER: approved quantity>"
max_notional_quote = "<OWNER: notional cap in quote currency>"
far_price_fraction = "<OWNER: strictly between 0 and 1>"
# only with triggered_bracket, tp1_from_fill, stop_reject_after_accept or trigger_cancel_race:
near_trigger_fraction = "<OWNER: strictly between 0 and 1>"
# only with gtd_expiry:
gtd_lifetime_seconds = <OWNER: whole seconds>
# only with cancel_fill_race or trigger_cancel_race:
race_repeats = <OWNER: a whole number, at most 5>
# only with insufficient_margin or margin_insufficient_target (its own quantity; the notional cap does not apply to it):
insufficient_margin_quantity = "<OWNER: whole quantity on the step grid, large enough to exceed available margin at the account's leverage>"
# only with symbol_config_change, margin_insufficient_target or isolated_liquidation (Phase 22; the leverage the probe asks the exchange for, or expects the symbol to read):
config_target_leverage = <OWNER: a whole number, the leverage you want requested>

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
exchange_info_read = <OWNER: true or false>
gtd_min_lifetime = <OWNER: true or false>
partial_fill_attempt = <OWNER: true or false>
cancel_fill_race = <OWNER: true or false>
stream_loss = <OWNER: true or false>
reduce_only_flat = <OWNER: true or false>
reduce_only_oversize = <OWNER: true or false>
min_notional_entry = <OWNER: true or false>
insufficient_margin = <OWNER: true or false>
stop_reject_after_accept = <OWNER: true or false>
trigger_cancel_race = <OWNER: true or false>
recv_window_error = <OWNER: true or false>
income_history = <OWNER: true or false>
symbol_config_change = <OWNER: true or false>
margin_type_resting_order = <OWNER: true or false>
leverage_above_max = <OWNER: true or false>
margin_insufficient_target = <OWNER: true or false>
available_balance_resting = <OWNER: true or false>
isolated_liquidation = <OWNER: true or false>
gtd_expiry = <OWNER: true or false>
```

What the loader enforces (it names keys, never values, when it refuses):

- `near_trigger_fraction` is a plain decimal strictly between 0 and 1, required exactly when `triggered_bracket`, `tp1_from_fill`, `stop_reject_after_accept` or `trigger_cancel_race` is true and refused otherwise. The closer to 1, the closer the trigger sits to the live mark price; a trigger case ends NOT_OBSERVED when the price does not reach it within `case_timeout_seconds`.
- `gtd_lifetime_seconds` and `gtd_expiry_wait_seconds` are positive integers, required exactly when `gtd_expiry` is true and refused otherwise; the wait must be greater than the lifetime. Binance requires `goodTillDate` greater than now plus 600 seconds; the loader does not check that floor, so a lifetime below it is allowed and the exchange answer to it is evidence (A1).
- `race_repeats` is a positive integer of at most 5 (`RACE_REPEATS_MAX`, a cap on the number of probe orders, not a trading number), required exactly when `cancel_fill_race` or `trigger_cancel_race` is true and refused otherwise.
- `insufficient_margin_quantity` is a positive plain decimal (a string like the other quantities), required exactly when `insufficient_margin` or `margin_insufficient_target` is true and refused otherwise. There is no default and no proposed number: the text `<OWNER: ...>` is not a decimal, so the loader refuses the file until you replace it. Choose a whole quantity on the step grid that is large enough to exceed the available margin at your account's leverage; the case records the available balance, the leverage and the implied margin it read just before, so you can see whether it was large enough. It must also be inside the LOT_SIZE range (a quantity above the exchange maximum would answer a lot-size error, not -2019, so the case does not send it).
- `config_target_leverage` (Phase 22 plans 22-05 and 22-09) is a positive integer, required exactly when `symbol_config_change`, `margin_insufficient_target` or `isolated_liquidation` is true and refused otherwise; there is no default. It is the leverage `symbol_config_change_to_isolated` asks the exchange for after switching the symbol to ISOLATED, and the leverage `margin_insufficient_at_target_leverage` and `isolated_position_liquidation_price` require the symbol to read before they act (they change nothing themselves). The six Phase 22 flags are `symbol_config_change`, `margin_type_resting_order`, `leverage_above_max`, `margin_insufficient_target`, `available_balance_resting` and `isolated_liquidation`; each case has its own flag and a flag that is absent or false leaves the case off.
- A larger `case_timeout_seconds` (your choice) gives the trigger cases and the stream-loss case more time. A key that is absent means the case is off, and a file with none of the twenty-nine keys behaves exactly like the Phase 18 file.

## Step 1: dry run first (offline)

```
uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file .planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml --evidence-dir <a temporary directory>
```

Nothing is sent: the dry run uses fakes and virtual time and writes `demo-probe-DRYRUN-<stamp>.json` with every case NOT_REHEARSED. Expect `acceptance: FAIL` (FAKE evidence never passes). Expect the dry run to end `FAILED` with exit 1 when your quantity is not on the step grid of the FAKE market (step 0.001; the Phase 18 quantity 0.0008 is not): the order cases then show an "order bound" error. That is an artifact of the FAKE step (the real Demo step is 0.0001), not a defect; read only that the case ids you enabled are listed and that no case says "script error".

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
- In the `--fixtures-dir`: the raw user-data payloads `<case_id>-<NNN>-<event>.json` (scrubbed), and for the twenty-nine opt-in cases (the ten of 261021-sj0, the five of 261022-sj1, the eight of 261023-sj2 and the six of Phase 22) the REST answers `<case_id>-rest-<NNN>-<operation>.json` (scrubbed), and `provenance.md` listing every file of the run with its label. A dry run writes none of these.

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

### 11. exchange_info_read_for_close (key `exchange_info_read`; added by 261022-sj1)

- Sends no order and runs in hedge mode too. One read of the exchangeInfo filters of the symbol, through the same public reader the paper path uses, timed with the tool clock.
- Read in `details`: `filter_LOT_SIZE_min_qty`, `filter_LOT_SIZE_max_qty`, `filter_LOT_SIZE_step_size`, `filter_MARKET_LOT_SIZE_min_qty`, `filter_MARKET_LOT_SIZE_max_qty`, `filter_MARKET_LOT_SIZE_step_size`, `filter_PRICE_FILTER_tick_size`, `filter_MIN_NOTIONAL_notional`, `symbol_status`, `read_elapsed_ms` and `read_endpoint`. `matches_run_start_snapshot` and `snapshot_differences` compare the read with the filters the run itself read at its start; the plan-time snapshot is the planner's, compare it yourself. `price_filter_min_price_max_price` is NOT_OBSERVED: the project port reads the tick size of PRICE_FILTER only.
- Files: `exchange_info_read_for_close-rest-001-symbol_filters.json`.
- Consumers: A10 and Q3 (the emergency close may read the filters afresh and may fall back to the plan-time snapshot); `src/execution/emergency_close.py`. The read time is one sample on your connection; it says nothing about how long a failing read takes.

### 12. gtd_min_lifetime_boundary (key `gtd_min_lifetime`; added by 261022-sj1)

- Sends two far BUY LIMIT GTD entries of the approved quantity, each once: `goodTillDate` = the public server time (GET /fapi/v1/time, read right before each send) plus 599 seconds, then plus 601 seconds. Every accepted order is cancelled at once. It never waits for expiry (that is `gtd_entry_expiry_status`).
- Read, for the points `plus_599s` and `plus_601s`: `_margin_seconds`, `_server_time_ms`, `_local_clock_before_utc` and `_local_clock_after_utc` (the tool clock around the server time read), `_local_minus_server_ms`, `_good_till_date_ms`, `_good_till_date_minus_server_ms`, `_good_till_date_minus_local_ms`, `_accepted`; on a rejection `_error_code` (the exact code), `_error_class`, `_error_category`, `_error_message`; on an acceptance `_good_till_date_echoed` and `_cancel_accepted`.
- How to read it: the tool gives no verdict. If only the plus 601 point is accepted, a floor of 600 seconds is consistent with it; which clock the floor uses can only be inferred when `_local_minus_server_ms` is large compared with the 2 second gap between the points. A point whose server time could not be read is skipped and says so in `_skipped`.
- Consumers: A1; `src/execution/pre_placement.py` (`good_till_date_ms`, the clock margin).

### 13. partial_fill_attempt (key `partial_fill_attempt`; added by 261022-sj1; best effort, may stay NOT_OBSERVED)

- Reads the depth (top 20 levels), then sends ONE BUY LIMIT of the approved quantity, never more, priced as high as your notional cap allows but never above the marketable price the entry cases already use. If that price does not reach the best ask nothing is sent. Afterwards: one status query, a cancel of the remainder if the order is still open, a final query, and a reduce-only MARKET close of the held quantity.
- OBSERVED only when a partial fill was seen (status PARTIALLY_FILLED, an executed quantity strictly between zero and the original, or a PARTIALLY_FILLED user-data frame). A complete fill, no fill and a rejection are valid answers: the case ends NOT_OBSERVED with the reason `no partial fill produced` and the raw numbers.
- Read: `approved_quantity`, `notional_cap`, `cap_price`, `band_price`, `limit_price`, `best_bid`, `best_ask`, `ask_levels_read`, `ask_quantity_within_limit_price`, `depth_expects_partial` (true, false or unknown), `placement_accepted`, `placement_status`, `orig_qty`, `executed_qty`, `avg_price`, `query_status`, `query_executed_qty`, `final_status`, `final_executed_qty`, `partial_fill_seen`, `partial_seen_in` (rest, frames), `flatten_quantity`, `not_sent`.
- Honest limit: a small order against a book with ample depth fills completely, and the tool never raises the quantity to force a partial fill, so Demo may never give you one.
- Consumers: P3, A5 and A2 (is `t` present on a partial fill).

### 14. entry_cancel_fill_race (key `cancel_fill_race`; needs `race_repeats`; added by 261022-sj1; best effort)

- Repeats `race_repeats` times: reads the depth, sends one BUY LIMIT of the approved quantity at the best ask (the touch: the price a BUY executes against; it must lie within your `far_price_fraction` band around the mark, else the case stops), cancels it as soon as the placement answer arrives, queries the final status once and, if any fill happened, closes it at once with one reduce-only MARKET order. A rejected placement stops the repeats; nothing is re-sent.
- Plainly: this does not reproduce a deterministic race. It records what the cancel and the final status say for orders placed at the touch (for example -2011, FILLED, CANCELED). Whether a cancel ever crosses a fill in flight depends on exchange timing and may never happen on Demo.
- Read: `race_repeats`, `repeats_completed`, `note`, `touch_price_side`, `stopped`; per repeat `r<n>_touch_price`, `r<n>_place_status`, `r<n>_place_executed_qty`, `r<n>_cancel` and `r<n>_cancel_code` (accepted or the exact code), `r<n>_final_status`, `r<n>_filled`, `r<n>_outcome`; the tallies `outcome_canceled_in_time`, `outcome_cancel_rejected` and `outcome_filled`.
- Consumers: P7, the branch B4 order, A5.

### 15. stream_loss_during_case (key `stream_loss`; added by 261022-sj1; needs the user-data stream)

- Reuses the stream-gap mechanism of `stream_gap_during_case` (it closes the private connection once; there is no new fault injection). Order: drop first (nothing is sent when no stream runs or the drop is not possible); then, while the stream is down or reconnecting, a marketable BUY LIMIT entry (its fill is read over REST) and a closePosition STOP_MARKET far below, with REST reads of both; one wait of `case_timeout_seconds` for the stream to return to LIVE; then what the stream delivered after the drop is compared with what REST said. The stop is cancelled and the cleanup flattens the position.
- Ends NOT_OBSERVED when no stream runs, when the drop is not possible, when the entry does not fill, or when the stream does not return to LIVE (the later deliveries cannot be compared).
- Binance is not assumed to replay what a dropped stream missed: the case records whether it did.
- Read: `transport_dropped`, `stream_states_at_entry_send`, `stream_states_when_stop_answered`, `stream_states_after_drop`, `stream_recovered_live`, `rest_entry_status_during_gap`, `rest_stop_status_during_gap`, `frames_before_drop_count`, `frames_after_drop_entry`, `frames_after_drop_stop`, `entry_fill_frame_delivered`, `stop_frame_delivered`, `comparison_entry`, `comparison_stop`, and `end_open_orders`, `end_open_algo_orders`, `end_position`.
- Consumers: P5 (the branch timing of B2 and B3, reconciliation when the stream is lost or late).

Sections 16 to 23 were added by quick task 261023-sj2. Each ends with a line "If it stops" that says what a NOT_OBSERVED or ERROR means and what, if anything, to do. Every case below records the exact answer of every exchange call (HTTP class, code, category, message) in `observations` and in the `*_error_*` details, and never retries.

### 16. reduce_only_market_on_flat (key `reduce_only_flat`; added by 261023-sj2)

- Reads open orders, open algo orders and the position first and stops (NOT_OBSERVED) unless the symbol is flat. Then sends ONE reduce-only MARKET SELL of the approved quantity with no position, and reads the position again. If the exchange accepted it and any position appeared (a flip) the tool flattens it at once with one reduce-only MARKET order and records `flipped` = true.
- Read: `precheck_state`, `client_order_id`, `order_accepted`; on a rejection `order_error_code` (the exact code), `order_error_class`, `order_error_category`, `order_error_message`; on an acceptance `order_status`, `order_executed_qty`; `position_after`, `flipped`. A rejection code is the answer (OBSERVED).
- Consumers: 19-OWNER-GAPS A4 (reduce-only with no position: rejected, or accepted).
- If it stops: "not flat" means the symbol had an open order, algo order or position when the case began; clean the Demo account and run the case alone with `--only reduce_only_market_on_flat`. An "order bound" ERROR means the approved quantity at the marketable price is above your notional cap; nothing was sent.

### 17. reduce_only_market_larger_than_position (key `reduce_only_oversize`; added by 261023-sj2)

- Opens a position of about half the approved quantity (floored to the step; it must be at least the exchange minimum quantity, else NOT_OBSERVED with the reason), then sends ONE reduce-only MARKET SELL of the full approved quantity, which is larger than the position. After an acceptance it waits once (`case_timeout_seconds`) for the position to change, reads the order and the position again, and flattens any remainder (a flip is closed with the opposite reduce-only order).
- Read: `half_quantity`, `held_before`, `oversize_quantity`, `order_accepted`, and the exact error fields on a rejection, `order_status` and `order_executed_qty`, `final_status`, `final_executed_qty`, `position_after`, and `outcome` (`rejected`, `clipped_to_position`, `partly_reduced`, `unchanged` or `flipped`).
- Consumers: 19-OWNER-GAPS A8 (is a larger reduce-only MARKET clipped, rejected or flipped), A4.
- If it stops: "half of the approved quantity ... below the exchange minimum quantity" means your approved quantity is too small to open half of it; raise the approved quantity in your file (your number), or leave the case off. "entry rejected" (for example -4164) means the half entry is below the minimum notional at the marketable price; the entry code is recorded.

### 18. non_reduce_only_below_min_notional (key `min_notional_entry`; added by 261023-sj2)

- Reads the filters, takes the exchange MIN_NOTIONAL, and computes the largest quantity on the step grid whose notional at the far price is strictly below it (never above the approved quantity). Sends ONE far BUY LIMIT (not reduce-only) of that quantity, records the answer, and cancels it at once if it was accepted.
- Read: `min_notional_used`, `far_price`, `sent_quantity`, `computed_notional`, `client_order_id`, `order_accepted`, the exact error fields (the expected answer is -4164), `cancel_accepted`.
- Consumers: -4164 for the O-03 TP1 minimum-notional evidence (what the exchange says for a non-reduce-only order below the minimum notional; reduce-only is exempt by the exchange text).
- If it stops: NOT_OBSERVED with "MIN_NOTIONAL filter is not listed" means the exchange did not list it for the symbol. "below the exchange minimum quantity" means no quantity below the minimum notional is also a valid order; nothing can be sent. A reason naming the cap means the computed order is above your notional cap; nothing was sent (the tool never exceeds your cap).

### 19. insufficient_margin_order (key `insufficient_margin`; needs `insufficient_margin_quantity`; added by 261023-sj2)

- This is the one case that does NOT use `max_notional_quote` or the approved quantity. It sends exactly your own `insufficient_margin_quantity` as ONE far BUY LIMIT (not reduce-only) at the far price inside your `far_price_fraction` band (always below the mark, so it can only rest, never fill). It keeps the symbol, the flat precheck (stops NOT_OBSERVED unless the symbol is flat), the price band, the step grid, the LOT_SIZE range, and the cleanup. Just before the order it reads the account (availableBalance and the margin totals), the symbol configuration (the leverage) and computes the implied notional and margin.
- If the order is rejected, the code is the answer (OBSERVED; the expected answer is -2019). If it is accepted (it rests), it is cancelled at once, the margin figures before and after are recorded, `order_accepted` = true, and the case ends NOT_OBSERVED (the quantity did not exceed your available margin). If anything filled (it should not), the runner cleanup flattens it, because no cap applies to this quantity.
- Read: `far_price`, `insufficient_margin_quantity`, `available_balance_before`, `total_wallet_balance_before`, `total_initial_margin_before`, `total_open_order_initial_margin_before`, `leverage`, `implied_notional`, `implied_initial_margin`, `implied_margin_exceeds_available`, `order_accepted`, the exact error fields, `cancel_accepted`, `final_status`, the same four figures with `_after`, `position_after`.
- Consumers: 19 error-taxonomy coverage for -2019 (`src/domain/exchange_errors.py` lists it as documented; this is the Demo answer).
- If it stops: "not flat" - clean the account. A reason about the exchange minimum or maximum quantity or the step grid means your `insufficient_margin_quantity` would draw a lot-size error instead of -2019, so nothing was sent; change your number. Accepted and NOT_OBSERVED means the quantity was not large enough to exceed the margin; raise it (your number) and run the case alone.

### 20. stop_rejected_after_acceptance (key `stop_reject_after_accept`; needs `near_trigger_fraction`; added by 261023-sj2; best effort)

- Opens a position of about half the approved quantity, reads the live mark price, then places a reduce-only STOP_MARKET SELL (not closePosition) for the full approved quantity, which is larger than the position, with its trigger just below the mark (your fraction). If the placement is rejected the code is the answer (OBSERVED). If it is accepted, the tool watches the REST status and the ALGO_UPDATE frames for one `case_timeout_seconds` until the leg ends, records every status and the raw `rm` text, and cancels the leg if it is still open. The runner cleanup flattens the position.
- Read: `half_quantity`, `held_before`, `stop_trigger_price`, `stop_quantity`, `placement_accepted`, on a rejection `stop_leg_error_code`, `stop_leg_error_class`, `stop_leg_error_category`, `stop_leg_error_message`; if accepted `stop_statuses_rest`, `stop_statuses_frames`, `stop_ai`, `stop_aq`, `stop_rm` (the raw reject text), `stop_algo_update_sequence` (`X|ia|ai|aq|rm|E|T` per delivery), `after_*`.
- Honest limit: if the mark does not move to the trigger the leg stays NEW and nothing informative happens: NOT_OBSERVED (the acceptance and the NEW status are still recorded). It needs the user-data stream for the frames; without a stream only the REST statuses are seen.
- Consumers: P5 remainder (a stop accepted and then rejected) and the `ALGO_UPDATE.o.rm` text.
- If it stops: NOT_OBSERVED "accepted but no ALGO_UPDATE status beyond NEW" - run again with a `near_trigger_fraction` closer to 1 or when the price is moving, or accept that Demo did not show it.

### 21. trigger_cancel_race (key `trigger_cancel_race`; needs `near_trigger_fraction` and `race_repeats`; added by 261023-sj2; best effort)

- Plainly: this is not a deterministic race. Per repeat, with a position open (the tool opens one marketable entry of the approved quantity when none is open): reads the live mark, places a closePosition STOP_MARKET SELL just below it, cancels it at once, then queries the algo order and the position. Whether the exchange triggers the stop before the cancel lands depends on timing and the price; a repeat may show nothing happening at all.
- Read: `note`, `race_repeats`, `repeats_completed`, `stopped`; per repeat `r<n>_stop_trigger_price`, `r<n>_placement_accepted` (and `r<n>_placement_error_code` and the other error fields), `r<n>_cancel_code` (`accepted` or the exact code, for example -2011), `r<n>_final_algo_status` (`CANCELED`, `FINISHED`, `ABSENT`, ...), `r<n>_triggered`, `r<n>_position_closed`, `r<n>_outcome`; the tallies `outcome_triggered`, `outcome_not_triggered`, `outcome_cancel_rejected`, `outcome_placement_rejected`.
- Consumers: P7 trigger part (a stop triggering while its cancel is in flight), P3/P5 timing.
- If it stops: NOT_OBSERVED "no stop was placed and cancelled" means every placement was rejected or the entry did not fill; the first rejection code is in `r1_placement_error_code`. A run where nothing triggered is still OBSERVED: it says the cancel won in every sample.

### 22. timestamp_outside_recv_window (key `recv_window_error`; added by 261023-sj2)

- Sends no order and runs in hedge mode too. Reads the public server time, then sends ONE read-only signed GET (open orders) whose timestamp is 2 x the recvWindow behind the exchange time. The recvWindow used is your ratified `signed_calls.recv_window_ms` (the project does not document a smaller allowed minimum, so none is invented). The SDK stamps the real clock itself, so the tool replaces that one clock read for the duration of this one call (thread-local, restored afterwards) and adds the clock offset between the tool and the exchange to what it takes away.
- Read: `recv_window_ms`, `server_time_ms`, `local_clock_before_utc`, `local_clock_after_utc`, `local_minus_server_ms`, `timestamp_behind_server_ms_target`, `timestamp_behind_local_ms`, `clock_calls`, `real_clock_ms`, `timestamp_sent_ms`, `timestamp_sent_minus_server_read_ms`, `accepted`, `error_code` (the expected answer is -1021), `error_class`, `error_category`, `error_message`.
- Consumers: -1021 for the GTD clock margin (`pre_placement.py`) and the drift guard.
- If it stops: NOT_OBSERVED "did not ask the stale clock" means the SDK did not use the replaced clock (an SDK change): no conclusion may be drawn, report it. "offset swallows" means the tool and the exchange clocks differ by more than twice the window; fix the machine clock first.

### 23. income_history_read (key `income_history`; added by 261023-sj2)

- Sends no order and runs in hedge mode too. After the other cases it reads the income history from the run start (converted to the exchange clock with one server-time read; the local start is used and the `window_note` says so when the server time cannot be read), without a type filter and with the exchange default limit.
- Read: `window_start_ms`, `window_note`, `local_minus_server_ms`, `row_count`, `row_fields` (the field names seen), `row_types` (for example COMMISSION, REALIZED_PNL, FUNDING_FEE), `row_count_<TYPE>`, `derived_sum_<TYPE>_<ASSET>` (exact sums, arithmetic only), `first_row_time_ms`, `last_row_time_ms`. The rows themselves are in `observations` and in the fixture file (values are account values; the free-text `info` goes through the redactor and a 200 character cap; read the fixture before it enters git).
- Consumers: Phase 21 (daily loss and the income types), G2-042/A9 (commission and realized PnL).
- If it stops: NOT_OBSERVED "no income row in the run window" means nothing was charged or paid in the window (for example when the other cases were off); run it after the order cases in the same session. A read failure shows the exact code.

### 24. symbol_config_change_to_isolated (key `symbol_config_change`; needs `config_target_leverage`; added by Phase 22 plan 22-05)

- This case CHANGES your Demo account: it is the first Phase 22 case that does. On a symbol that is flat (no open order, no algo order, no position) it reads the symbol configuration, asks the exchange for ISOLATED margin, asks for your `config_target_leverage`, then reads the configuration back. Each request is sent once and never repeated. It sends no order. It does not restore the previous configuration: it records it (`previous_margin_type`, `previous_leverage`) and you decide whether to change it back. A hedge-mode account is NOT_OBSERVED. If the symbol is not flat, or the previous configuration cannot be read, nothing is changed and the case is NOT_OBSERVED.
- Read: `requested_margin_type`, `requested_leverage`, `config_before_margin_type`, `config_before_leverage`, `config_before_max_notional_value`, `previous_margin_type`, `previous_leverage`, `already_at_target`, the answer to each change (`margin_type_answer_accepted`, `margin_type_answer_code`, `margin_type_answer_msg`, or the `_error_code`, `_error_class`, `_error_category`, `_error_message` fields; `leverage_answer_accepted`, `leverage_answer_symbol`, `leverage_answer_leverage`, `leverage_answer_maxNotionalValue` or the error fields), then `config_after_margin_type` (the exchange's own casing), `config_after_leverage`, `config_after_max_notional_value` and `config_after_margin_type_equals_ISOLATED`. An exchange error is evidence, not a failure: the case stays OBSERVED.
- Consumers: Phase 22 criterion 1 (the leverage and margin guard), the casing of an ISOLATED `marginType` on the Demo host, the code the exchange answers to a no-op change. Anything seen is demo-observed, not mainnet.
- If it stops: NOT_OBSERVED with the reason text. Run it again when the symbol is flat.

Sections 25 to 29 were added by Phase 22 plan 22-09. They change nothing unless the exchange accepts a request it is expected to refuse, and then only that case undoes its own change, once, and records it. Every case records the exact answer of every exchange call and never retries; none sets a number or draws a conclusion for you. Run sections 25 and 26 and 28 on a flat symbol at any configuration; run sections 27 and 29 only after section 24 has left the symbol ISOLATED at your `config_target_leverage`.

### 25. margin_type_change_with_resting_order (key `margin_type_resting_order`; added by Phase 22 plan 22-09)

- Needs no extra owner number. Reads open orders, open algo orders and the position first and stops (NOT_OBSERVED) unless the symbol is flat. It reads the symbol configuration; if `marginType` does not read ISOLATED or CROSSED (any casing) it sends nothing. Then it sends ONE far resting BUY LIMIT of the approved quantity (your notional cap and far-price band apply; if the order is not accepted, or it filled, no change is sent), ONE margin-type change request to the OPPOSITE type (CROSSED when the symbol reads ISOLATED, otherwise ISOLATED), cancels the order, and reads the configuration again. If the exchange ACCEPTED the change (a surprise, with an order resting) the case asks once for the original type back and records that; it never changes the leverage and restores nothing else.
- This case CHANGES your Demo account only if the exchange accepts the request. The expected answer is a refusal (the guard of plan 22-11 relies on -4047 and -4048 for orders and positions); the case does not assume it, the answer is the evidence.
- Read: `far_price`, `previous_margin_type`, `requested_margin_type`, `config_before_margin_type`, `config_before_leverage`, `config_before_max_notional_value`, `client_order_id`, `order_accepted` (and `order_status`, or the `order_error_*` fields), then `change_accepted` with `change_code` and `change_msg`, or `change_error_code`, `change_error_class`, `change_error_category`, `change_error_message`, `cancel_accepted`, `config_after_margin_type`, `config_after_leverage`; only after an accepted change: `restore_accepted`, the `restore_*` answer fields and `config_restored_margin_type`.
- Consumers: Phase 22 criterion 1 and plan 22-11 (the flat-symbol precondition of D-04 and the codes it reads); the exact code, HTTP class and text of the answer. Demo-observed, not mainnet.
- If it stops: "not flat" - clean the account. "the resting order was not accepted" - the order code is in `order_error_code`; no change was sent. "could not be read as ISOLATED or CROSSED" - the configuration answer is recorded; nothing was sent. An "order bound" ERROR means the approved quantity at the far price is above your notional cap.

### 26. leverage_above_bracket_maximum (key `leverage_above_max`; added by Phase 22 plan 22-09)

- Needs no extra owner number. On a flat symbol it reads the leverage bracket table, takes `initialLeverage` of bracket 1 from the exchange's own answer (never assumed; the recorded Demo value 125 is demo-observed, not mainnet), reads the configuration, and sends ONE leverage request of that maximum plus one. If the maximum or the current leverage cannot be read, nothing is sent. If the exchange ACCEPTED the request (a surprise) the case asks once for the previous leverage back and records that. It sends no order and does not touch the margin type.
- Read: `bracket_one_initial_leverage`, `previous_leverage`, `requested_leverage`, `config_before_margin_type`, `config_before_leverage`, `change_accepted` with `change_code`, `change_symbol`, `change_leverage`, `change_maxNotionalValue`, or `change_error_code` (the expected code is -4028 or -4209, assumption A6, unobserved), `change_error_class`, `change_error_category`, `change_error_message`; only after an accepted change: `config_after_change_leverage`, `restore_accepted` and the `restore_*` fields; then `config_after_margin_type`, `config_after_leverage`.
- Consumers: Phase 22 criterion 2 (the leverage-above-bracket refusal; plans 22-11 and 22-14); assumption A6.
- If it stops: "not flat" - clean the account. "maximum leverage ... could not be read" - the bracket answer is recorded under `leverage_brackets_read`; nothing was sent.

### 27. margin_insufficient_at_target_leverage (key `margin_insufficient_target`; needs `insufficient_margin_quantity` and `config_target_leverage`; added by Phase 22 plan 22-09)

- Run it AFTER section 24: it requires the symbol to read ISOLATED (any casing) at exactly your `config_target_leverage`; otherwise it ends NOT_OBSERVED ("run symbol_config_change_to_isolated first") and changes nothing and sends nothing. It is the section 19 flow under its own key: ONE far BUY LIMIT (not reduce-only) of exactly your own `insufficient_margin_quantity` at the far price inside your band (it can only rest), with the margin figures read just before and after. Like section 19 it is NOT held to `max_notional_quote` or the approved quantity; it keeps the symbol, the flat precheck, the price band, the step grid, the LOT_SIZE range and the cleanup.
- The `insufficient_margin_quantity` rule is now: required exactly when `insufficient_margin` OR `margin_insufficient_target` is true. Choose a quantity large enough to exceed the available margin at your target leverage; the case records the figures so you can see whether it was.
- If the order is rejected the code is the answer (OBSERVED; the expected answer is -2019). If it is accepted it is cancelled at once and the case ends NOT_OBSERVED (the quantity did not exceed your margin).
- Read (every name starts with `target_`): `target_config_target_leverage`, `target_far_price`, `target_insufficient_margin_quantity`, `target_available_balance_before`, `target_total_wallet_balance_before`, `target_total_initial_margin_before`, `target_total_open_order_initial_margin_before`, `target_leverage`, `target_implied_notional`, `target_implied_initial_margin`, `target_implied_margin_exceeds_available`, `target_client_order_id`, `target_order_accepted` and the exact `target_order_error_*` fields, `target_cancel_accepted`, `target_final_status`, the same four figures with `_after`, `target_position_after`. When the configuration is not at the target: `target_config_margin_type` and `target_config_leverage`.
- Consumers: Phase 22 criterion 3 (the margin-insufficient refusal shape; the margin predicate of plan 22-14, reason INSUFFICIENT_MARGIN).
- If it stops: as section 19, plus the not-at-target reason above.

### 28. available_balance_with_resting_order (key `available_balance_resting`; added by Phase 22 plan 22-09)

- Needs no extra owner number. On a flat symbol it reads the symbol configuration and the account (before), sends ONE far resting BUY LIMIT of the approved quantity (your caps apply), reads the account again WHILE the order rests, and cancels the order. A rejected order is recorded and the account is still read after it. It sends nothing else and changes nothing.
- It draws NO conclusion and invents no threshold. It records what the exchange said so that you can decide whether `availableBalance` already nets the initial margin of resting orders (assumption A1; the API reference does not say, the support-center text says it is deducted). Run it twice: once at the account's current configuration and once after section 24 (ISOLATED), because the open-order term can differ with the margin type (22-RESEARCH 2.6).
- Read: `far_price`, `approved_quantity`, `config_margin_type`, `config_leverage`, `config_max_notional_value`, `implied_notional`, `implied_initial_margin` (notional divided by the leverage read), `available_balance_before`, `total_wallet_balance_before`, `total_initial_margin_before`, `total_open_order_initial_margin_before`, `quote_asset_before`, `quote_row_open_order_initial_margin_before`, `client_order_id`, `order_accepted` (and `order_status`, or the `order_error_*` fields), the same figures with `_after`, `cancel_accepted`, then the exact differences (after minus before) `available_balance_delta`, `open_order_margin_delta`, `quote_row_open_order_margin_delta`, and the text `available_decreased` and `open_order_margin_increased`; `position_after`. A figure the exchange did not return is `NOT_OBSERVED` text, never zero, and then no delta is written.
- Consumers: Phase 22 criterion 3 and assumption A1; plan 22-14 (does the margin predicate subtract resting entries a second time); your own DECISIONS row if you want `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` (the constant of plan 22-04, False until you decide) to change. This case changes nothing by itself.
- If it stops: "not flat" - clean the account. An "order bound" ERROR means the approved quantity at the far price is above your notional cap.

### 29. isolated_position_liquidation_price (key `isolated_liquidation`; needs `config_target_leverage`; added by Phase 22 plan 22-09)

- Run it AFTER section 24: the symbol must be flat and read ISOLATED at exactly your `config_target_leverage`, otherwise it ends NOT_OBSERVED and sends nothing. It opens ONE marketable entry of the approved quantity (your caps apply), then reads, in this order: the positions, the leverage brackets, the symbol configuration and the account. The runner cleanup closes the position with one reduce-only MARKET order and checks that the symbol is flat. The tool computes nothing and imports no risk module: you (or a later plan) compare the exchange's figure with `src/risk/liquidation.py` offline from the recorded inputs (assumption A3, the only way to obtain an isolated golden value).
- Read: `entry_client_id`, `entry_statuses`, `position_position_side`, `position_position_amt`, `position_entry_price`, `position_mark_price`, `position_liquidation_price`, `position_break_even_price`, `position_unrealized_profit`, `position_notional`, `position_margin_asset`; every bracket field as `bracket_<path>` (for example `bracket_0.brackets.3.cum`, `bracket_0.brackets.3.maintMarginRatio`); `config_at_position_margin_type`, `config_at_position_leverage`, `config_at_position_max_notional_value`; `account_total_maint_margin`, `account_total_initial_margin`, `account_total_position_initial_margin`, `account_total_open_order_initial_margin`, `account_total_margin_balance`, `account_available_balance`; `account_position_isolatedMargin`, `account_position_isolatedWallet`, `account_position_maintMargin`, `account_position_initialMargin`, `account_position_positionInitialMargin`, `account_position_openOrderInitialMargin`, `account_position_notional`, `account_position_positionAmt`, `account_position_unrealizedProfit`, `account_position_leverage`; `quote_asset` and `quote_row_walletBalance`, `quote_row_marginBalance`, `quote_row_maintMargin`, `quote_row_positionInitialMargin`, `quote_row_openOrderInitialMargin`, `quote_row_availableBalance`. A field the exchange did not return is `NOT_OBSERVED: absent`. The fixture files hold the raw answers.
- Honest limit: the positions summary of the tool carries entry price, mark price, liquidation price and notional; the isolated margin, isolated wallet and maintenance margin come from the account answer and may be absent on the Demo host. If `liquidationPrice` itself is absent the case ends NOT_OBSERVED with every other figure kept. A cross-margin sentinel (for example `0`) is recorded as read and is not interpreted.
- Consumers: Phase 22 criterion 2, assumption A3, the isolated golden of the pure liquidation module (plan 22-07) and the post-fill watch (plan 22-13, which compares the exchange `liquidationPrice` with the local one). Demo-observed, not mainnet; no buffer or threshold is chosen from it (your O-2 stays yours).
- If it stops: "not flat" or "does not read ISOLATED" - run section 24 first, or clean the account. "entry rejected" - the entry code is recorded; no position was opened. An "order bound" ERROR means the marketable entry is above your notional cap.

## One session: all cases

The order of the case ids in one run without `--only` is the `CASE_ORDER` of the tool. The sixteen required Phase 18 cases run first; the cases below run only when their key is true in your file; the one case that waits more than ten minutes is last.

1. `account_read_only_capture` (key `account_capture`)
2. `algo_query_timing_after_new` (key `algo_query_timing`)
3. `close_position_stop_with_position` (key `close_position_with_position`)
4. `stop_would_trigger_after_fill` (key `stop_trigger_after_fill`)
5. `stop_query_absent_then_same_id` (key `stop_absent_same_id`)
6. `manual_close_with_open_legs` (key `manual_close_open_legs`)
7. `commission_vs_realized_pnl` (key `commission_realized_pnl`)
8. `triggered_close_position_bracket` (key `triggered_bracket`)
9. `tp1_quantity_from_fill` (key `tp1_from_fill`)
10. `exchange_info_read_for_close` (key `exchange_info_read`)
11. `gtd_min_lifetime_boundary` (key `gtd_min_lifetime`)
12. `partial_fill_attempt` (key `partial_fill_attempt`)
13. `entry_cancel_fill_race` (key `cancel_fill_race`)
14. `stream_loss_during_case` (key `stream_loss`)
15. `reduce_only_market_on_flat` (key `reduce_only_flat`)
16. `reduce_only_market_larger_than_position` (key `reduce_only_oversize`)
17. `non_reduce_only_below_min_notional` (key `min_notional_entry`)
18. `insufficient_margin_order` (key `insufficient_margin`): the one case with its own quantity key, not held to the notional cap
19. `stop_rejected_after_acceptance` (key `stop_reject_after_accept`)
20. `trigger_cancel_race` (key `trigger_cancel_race`)
21. `timestamp_outside_recv_window` (key `recv_window_error`)
22. `income_history_read` (key `income_history`): reads the income of the whole run window, so it runs after the order cases
23. `symbol_config_change_to_isolated` (key `symbol_config_change`): changes the symbol to ISOLATED and your `config_target_leverage`; does not restore the old configuration
24. `margin_type_change_with_resting_order` (key `margin_type_resting_order`): ONE far resting BUY, then ONE margin-type change request to the opposite type; undoes its own change only if the exchange accepted it
25. `leverage_above_bracket_maximum` (key `leverage_above_max`): ONE leverage request of the bracket-1 maximum plus one; undoes its own change only if the exchange accepted it
26. `margin_insufficient_at_target_leverage` (key `margin_insufficient_target`): needs `insufficient_margin_quantity` and `config_target_leverage`; the section 19 flow on a symbol that already reads ISOLATED at your leverage; changes nothing
27. `available_balance_with_resting_order` (key `available_balance_resting`): the account figures before and after ONE far resting order; draws no conclusion
28. `isolated_position_liquidation_price` (key `isolated_liquidation`): needs `config_target_leverage`; ONE entry of the approved quantity on a symbol that reads ISOLATED at your leverage, then the exchange's liquidation price with every input of the local formula; the runner cleanup closes the position
29. `gtd_entry_expiry_status` (key `gtd_expiry`): waits more than 10 minutes, always last

A complete probe-limits file with every one of these keys on. Every number is yours: nothing is proposed, every placeholder is written `<OWNER: ...>`, and the loader refuses the file until you replace each one. The three Phase 18 optional cases stay off here (they are your earlier decisions; enabling `market_lot_size_out_of_range` also needs `market_lot_probe_quantity`).

```toml
[order]
symbol = "<OWNER: the Demo symbol>"
quantity = "<OWNER: approved quantity>"
max_notional_quote = "<OWNER: notional cap in quote currency>"
far_price_fraction = "<OWNER: strictly between 0 and 1>"
near_trigger_fraction = "<OWNER: strictly between 0 and 1>"
gtd_lifetime_seconds = <OWNER: whole seconds>
race_repeats = <OWNER: a whole number, at most 5>
insufficient_margin_quantity = "<OWNER: whole quantity on the step grid, large enough to exceed available margin at the account's leverage>"
config_target_leverage = <OWNER: a whole number, the leverage you want requested>

[waits]
case_timeout_seconds = <OWNER: whole seconds>
cleanup_timeout_seconds = <OWNER: whole seconds>
gtd_expiry_wait_seconds = <OWNER: whole seconds, greater than gtd_lifetime_seconds>

[optional_cases]
explicit_time_in_force = false
stream_gap = false
market_lot_size_out_of_range = false
account_capture = true
algo_query_timing = true
close_position_with_position = true
stop_trigger_after_fill = true
stop_absent_same_id = true
manual_close_open_legs = true
commission_realized_pnl = true
triggered_bracket = true
tp1_from_fill = true
exchange_info_read = true
gtd_min_lifetime = true
partial_fill_attempt = true
cancel_fill_race = true
stream_loss = true
reduce_only_flat = true
reduce_only_oversize = true
min_notional_entry = true
insufficient_margin = true
stop_reject_after_accept = true
trigger_cancel_race = true
recv_window_error = true
income_history = true
symbol_config_change = true
margin_type_resting_order = true
leverage_above_max = true
margin_insufficient_target = true
available_balance_resting = true
isolated_liquidation = true
gtd_expiry = true
```

The single command for one session (no `--only`), typed phrase `DEMO PROBE BTCUSDT` (the symbol of your file):

```
uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file .planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml --evidence-dir .planning/phases/19-execution-plan-binding-price-check/evidence --fixtures-dir .planning/phases/19-execution-plan-binding-price-check/evidence/fixtures --execute
```

Before it: the dry run of Step 1 and the smoke re-run of Step 2. The session takes more than ten minutes (the last case alone waits `gtd_expiry_wait_seconds`). If a ban or a rate limit stops the run (`ABORTED_BAN`), wait out the `retry_after_seconds` the evidence records and re-run only the cases that did not run, once, with `--only`.

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
| exchange_info_read_for_close | A10, Q3: the live filters and the read time, for the emergency close fallback | `emergency_close.py`; your comparison with the plan-time snapshot |
| gtd_min_lifetime_boundary | A1: accepted or rejected at server time + 599 s and + 601 s, with the exact codes and both clocks | 19 A1; `pre_placement.py` clock margin |
| partial_fill_attempt | P3, A5: can Demo produce a partial fill (best effort; NOT_OBSERVED is a valid answer) | 19 P3, A5, A2 |
| entry_cancel_fill_race | P7: the cancel answer, the final status and the fill of orders placed at the touch (not a deterministic race) | 19 P7, B4 order, A5 |
| stream_loss_during_case | P5: REST during a user-data gap against what the stream delivers after it | 19 P5, B2 and B3 timing |
| reduce_only_market_on_flat | A4: a reduce-only MARKET order with no position is rejected (the exact code) or accepted (and whether a position appeared) | 19-OWNER-GAPS A4 |
| reduce_only_market_larger_than_position | A8: a reduce-only MARKET larger than the position is clipped, rejected or flipped | 19-OWNER-GAPS A8 (and A4) |
| non_reduce_only_below_min_notional | The -4164 answer of a non-reduce-only order below the minimum notional, with the minimum used | 19 O-03 TP1 minimum-notional evidence; the exchange error table (-4164) |
| insufficient_margin_order | The -2019 answer of a resting order larger than the margin allows, with the available balance, leverage and implied margin | 19 error-taxonomy coverage for -2019 (`exchange_errors.py`) |
| stop_rejected_after_acceptance | P5 remainder: a stop accepted and then rejected, and the raw `ALGO_UPDATE.o.rm` text (best effort) | 19 P5; the algo-status classes (`algo_status.py`) |
| trigger_cancel_race | P7 trigger part: place and cancel a near stop; the cancel answer, the final algo status, whether it triggered (not a deterministic race) | 19 P7 (trigger part), P3/P5 timing |
| timestamp_outside_recv_window | The -1021 answer with both clocks, for a timestamp 2 x the recvWindow behind | the GTD clock margin in `pre_placement.py`; the drift guard |
| income_history_read | The income row types and fields seen in the run window (commission, realized PnL, funding) | Phase 21 (daily loss, income types); G2-042/A9 |
| symbol_config_change_to_isolated | The casing of an ISOLATED `marginType`, the answers to the margin-type and leverage changes, the configuration read back | Phase 22 criterion 1; plan 22-11 (configuration guard); your O-1 |
| margin_type_change_with_resting_order | The exchange's answer (code, class, text) to a margin-type change while an order rests | Phase 22 criterion 1; plan 22-11 (D-04 precondition codes -4047 and -4048) |
| leverage_above_bracket_maximum | The bracket-1 maximum from the exchange and the code for the maximum plus one | Phase 22 criterion 2; assumption A6; plans 22-11 and 22-14 |
| margin_insufficient_at_target_leverage | The -2019 shape of a resting order larger than the margin allows, at ISOLATED and your target leverage | Phase 22 criterion 3; plan 22-14 (margin predicate, INSUFFICIENT_MARGIN) |
| available_balance_with_resting_order | `availableBalance` and the open-order initial margin before and after one resting order, as exact deltas | Phase 22 criterion 3; assumption A1; plan 22-14; your DECISIONS row for `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` |
| isolated_position_liquidation_price | The exchange `liquidationPrice` of an isolated position with entry, mark, margin, brackets and configuration | Phase 22 criterion 2; assumption A3; plans 22-07 (offline comparison) and 22-13 (post-fill watch); your O-2 |

## Phase 22 evidence map

What each Phase 22 case would support, and what stays open until you have run it. Nothing here is automatic: no result sets a number, flips a flag, chooses a parameter or changes a decision (RESEARCH_PROTOCOL, D-19). Every result is demo-observed, not mainnet.

| Case | Criterion | Assumption it settles | What you do with the result |
|------|-----------|-----------------------|-----------------------------|
| symbol_config_change_to_isolated | 1 (set and verify ISOLATED and the leverage) | the casing of an ISOLATED `marginType` on the Demo host, the answer to a no-op change | read the casing and the codes; plan 22-11 compares what the exchange wrote |
| margin_type_change_with_resting_order | 1 (the D-04 flat-symbol precondition) | the codes the exchange answers to a margin-type change with an order resting (expected -4047 or -4048, unobserved) | confirm or correct the codes the guard relies on, in a later plan or a DECISIONS row of your own |
| leverage_above_bracket_maximum | 2 (brackets from the exchange, never hard-coded) | A6: the code of a leverage above the bracket-1 maximum (-4028 or -4209, unobserved) | confirm or correct the refusal code the guard reads |
| margin_insufficient_at_target_leverage | 3 (the available-margin check) | the shape of the margin refusal at the target leverage on an ISOLATED symbol | compare with the predicate of plan 22-04 and the guard of plan 22-14 |
| available_balance_with_resting_order | 3 (resting entries count once) | A1: does `availableBalance` already net the margin of resting orders | decide, in your own DECISIONS row, whether `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` changes; until then it stays False |
| isolated_position_liquidation_price | 2 (liquidation beyond the stop) | A3: the exchange's own isolated liquidation price with every input of the local formula | compare it offline with `src/risk/liquidation.py`; a difference is a finding, not a parameter |

Criteria 1, 2 and 3 of Phase 22 are NOT Demo-proven until you have run the matching cases and read the results: criterion 1 is proven only against fakes and recorded CROSSED payloads, and criteria 2 and 3 only against fakes and the recorded Demo bracket table. Until then they are not Demo-proven, and no Phase 22 document may say otherwise. Criterion 4 (one-way, single-asset margin) is read by section 1 (`account_read_only_capture`) and decided by the guard, not by these cases. The owner numbers O-1 to O-4 (target leverage, liquidation buffer, bracket age and margin headroom, close or alert after a failed post-fill check) are yours and are not set by any case: the cases record facts, they propose no number.

## Not covered here

Listed so nobody assumes otherwise:

- P3 partial fill: best effort only. The existing derived `partial_fill` case reads the entries of the run; `partial_fill_attempt` (261022-sj1) sends one crossing limit order at the approved quantity. Demo may never produce a partial fill, so P3 can stay NOT_OBSERVED for ever (the tool never raises the quantity to force one).
- P5 stream loss: `stream_loss_during_case` (261022-sj1) runs one entry and stop cycle across a dropped user-data stream, next to the existing optional `stream_gap_during_case`. It ends NOT_OBSERVED when the stream does not return; a stream lost for longer than one `case_timeout_seconds` is not covered. "Stop rejected after acceptance" is best effort in `stop_rejected_after_acceptance` (261023-sj2) and may stay NOT_OBSERVED when the price does not reach the trigger; "stop timed out" under a lost stream has no case.
- P7 fill, cancel and trigger race: best effort only. `entry_cancel_fill_race` (261022-sj1) captures the -2011, FILLED and CANCELED answers of cancels sent right after placements at the touch price, and `trigger_cancel_race` (261023-sj2) samples the cancel of a near stop; neither reproduces a deterministic race, and P7 can stay NOT_OBSERVED on Demo.
- The real 418 duration and the 429 queue order of plan 20-21: never provoked, by your instruction and your decision not to provoke a ban (a case would have to cause the ban or the queue on purpose, and the tool never does); there is no case for either.
- The stream states of SAFE_MODE exit row 7: the smoke and stream evidence only.
- Hedge Mode: every order case refuses hedge mode and sends nothing (the reduce-only parameter cannot be sent there); the project runs one-way mode only, so there is no case for it.

## After a run

Commit nothing automatically. You decide which fixtures move into `tests/fixtures/phaseNN/recorded_demo/` with their provenance; later phases cite the evidence file name and its stamp. Check each fixture file before it enters git (the tool scrubs known secrets, but the account captures hold account values).
