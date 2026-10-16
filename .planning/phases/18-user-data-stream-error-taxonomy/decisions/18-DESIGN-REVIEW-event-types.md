# Phase 18 design review aid: user-data event types (plan 18-03, Task 2 gate)

**Status:** review aid only. This is NOT the decision record. The decision record
`decisions/18-DEC-D01-event-types.md` is written after the user answers the Task 2 gate
(blocking-human, never auto-selected).

**Where the code is:** plan 18-03 Task 1 (the tracer) is done and committed as `bed16f6` on
branch `phase-18`:

- `src/adapters/binance_userdata_events.py` (new): the event types, the strict parser for
  `ORDER_TRADE_UPDATE`, the envelope unwrapping, `to_fill_event`
- `src/execution/fill_monitor.py`: `FillEvent` gains four optional fields; `fold_fills` carries them
- `tests/support/userdata_frames.py`: `FRAME_LABEL = "SYNTHETIC_FROM_SDK_MODEL"` and the
  `ORDER_TRADE_UPDATE` frame builder
- `tests/test_userdata_events.py`: 119 tests in the verify set pass, including the new tests

Task 3 (the remaining parsers) has NOT started. It waits for this gate.

**Why this matters (CONTEXT D-01, reversibility costly):** Phases 19 (binding), 20 (reconcile),
21 (daily loss reads commission and asset) and 24 (composition) import these types. If a field
name or type changes after them, every consumer needs an edit in the same change. No data
migration is involved, because nothing stores these types yet.

**Sources:** wire field names and Python types were checked against the installed SDK models
(`binance_sdk_derivatives_trading_usds_futures` 17.4.0, `websocket_streams/models/*.py`, read as
files). The Binance event pages are UNVERIFIED for Phase 18 (`docs/SOURCES.md`, "Facts read for
Phase 18"). Every test frame is synthetic and was built from the SDK model. None is captured
Binance data.

---

## 1. Types written in Task 1

All types are `@dataclass(frozen=True)`. They hold no float, no SDK type and no wall-clock read.
Money, quantities and prices are `Decimal`. Times are UTC-aware `datetime`. Required text is a
non-empty `str`.

### 1.1 `StreamAnomalyKind` (str Enum, 15 values, exactly as the plan lists them)

`UNRECOGNIZED_ENVELOPE`, `MALFORMED_PAYLOAD`, `FIELD_VALIDATION`, `UNKNOWN_EVENT_TYPE`,
`UNKNOWN_EXECUTION_TYPE`, `UNKNOWN_ORDER_STATUS`, `UNKNOWN_ALGO_STATUS`, `FORCED_CLOSE_ORDER`,
`AMENDMENT_EVENT`, `LIQUIDATION_EVENT`, `DEPRECATED_EVENT`, `UNHANDLED_EVENT`,
`FILL_TOTAL_MISMATCH`, `UNKNOWN_ORDER`, `QUEUE_OVERFLOW`.

Task 1 emits only `UNRECOGNIZED_ENVELOPE`, `MALFORMED_PAYLOAD`, `FIELD_VALIDATION` and
`UNKNOWN_EVENT_TYPE`. Task 3 adds the order and algo kinds. Plan 18-15 (the router) adds
`FILL_TOTAL_MISMATCH`, `UNKNOWN_ORDER` and `QUEUE_OVERFLOW`.

### 1.2 `StreamAnomaly`

| Field | Type | Rule |
|---|---|---|
| `kind` | `StreamAnomalyKind` | |
| `event_name` | `str \| None` | event name as received (wire `e`, or the SDK model class name); at most 64 characters |
| `field` | `str \| None` | dotted wire path, e.g. `o.q`, `E`, `T`; at most 64 characters |
| `detail` | `str` | built only from field names and type names, never a payload value; non-empty; at most 200 characters |
| `payload_sha256` | `str` | 64 lowercase hex characters: sha256 of the canonical JSON of the whole message payload (sorted keys, separators `,` and `:`, ASCII) |
| `observed_at_utc` | `datetime` (UTC) | an argument from the caller; the module never reads a clock |

Factory: `make_stream_anomaly(kind, *, event_name, field, detail, payload, observed_at_utc)`
caps the lengths and computes the hash. Plan 18-15 will need it for the router's own kinds.

### 1.3 `OrderUpdateEvent` (one `ORDER_TRADE_UPDATE` frame)

Declared `@dataclass(frozen=True, kw_only=True)`, so it is built with keywords only. This keeps
the plan's field order and gives every optional field a `None` default.

| Attribute | Python type | Wire key (SDK type) | Required on the wire | Rule |
|---|---|---|---|---|
| `event_time_utc` | `datetime` | `E` (StrictInt) | yes | exact ms to UTC (`epoch + timedelta(milliseconds=E)`), int >= 0, never bool |
| `transaction_time_utc` | `datetime` | `T` (StrictInt) | yes | same |
| `symbol` | `str` | `o.s` (StrictStr) | yes | non-empty |
| `client_order_id` | `str` | `o.c` (StrictStr) | yes | non-empty |
| `side` | `str` | `o.S` (StrictStr) | yes | must be `BUY` or `SELL` |
| `order_type` | `str` | `o.o` (StrictStr) | yes | non-empty |
| `original_order_type` | `str \| None` | `o.ot` (StrictStr) | no | non-empty when present |
| `time_in_force` | `str` | `o.f` (StrictStr) | yes | non-empty |
| `position_side` | `str` | `o.ps` (StrictStr) | yes (judgment J1) | non-empty (`BOTH` in one-way mode, `LONG`/`SHORT` in hedge mode) |
| `original_quantity` | `Decimal` | `o.q` (StrictStr) | yes | decimal text, >= 0 |
| `original_price` | `Decimal \| None` | `o.p` (StrictStr) | no | decimal text, >= 0 |
| `average_price` | `Decimal \| None` | `o.ap` (StrictStr) | no | decimal text, >= 0 |
| `stop_price` | `Decimal \| None` | `o.sp` (StrictStr) | no | decimal text, >= 0 |
| `execution_type` | `str` | `o.x` (StrictStr) | yes | raw string (Task 3 adds the vocabulary check) |
| `order_status` | `str` | `o.X` (StrictStr) | yes | raw string (Task 3 adds the vocabulary check) |
| `exchange_order_id` | `str` | `o.i` (StrictInt) | yes | the int as text, int >= 0, never bool |
| `last_filled_quantity` | `Decimal \| None` | `o.l` (StrictStr) | yes for `x` TRADE | decimal text, >= 0 |
| `accumulated_filled_quantity` | `Decimal \| None` | `o.z` (StrictStr) | yes for `x` TRADE | decimal text, >= 0 |
| `last_filled_price` | `Decimal \| None` | `o.L` (StrictStr) | yes for `x` TRADE | decimal text, >= 0 |
| `commission` | `Decimal \| None` | `o.n` (StrictStr) | no | decimal text, may be signed |
| `commission_asset` | `str \| None` | `o.N` (StrictStr) | no | non-empty when present |
| `trade_time_utc` | `datetime` | `o.T` (StrictInt) | yes | exact ms to UTC |
| `trade_id` | `str \| None` | `o.t` (StrictInt) | yes for `x` TRADE | the int as text, set ONLY for TRADE; `None` for every other `x`, whatever the wire carries; never synthesized |
| `is_maker` | `bool \| None` | `o.m` (StrictBool) | no | a real bool |
| `reduce_only` | `bool \| None` | `o.R` (StrictBool) | no | a real bool |
| `working_type` | `str \| None` | `o.wt` (StrictStr) | no | non-empty when present |
| `realized_profit` | `Decimal \| None` | `o.rp` (StrictStr) | no | decimal text, may be signed |
| `modify_id` | `str \| None` | `o.M` (StrictStr) | no | **typed `str` per the SDK; the plan said int (judgment J2)** |
| `expire_reason` | `str \| None` | `o.er` (StrictStr) | no | non-empty when present |
| `stp_mode` | `str \| None` | `o.V` (StrictStr) | no | non-empty when present |
| `price_match` | `str \| None` | `o.pm` (StrictStr) | no | non-empty when present |

Wire keys the SDK model has but the event does NOT carry: `o.b`, `o.a` (bid/ask notional),
`o.cp` (close-all), `o.pP` (price protect), `o.AP`, `o.cr` (trailing only), `o.si`, `o.ss`
("ignore"), `o.gtd`. The top-level `e` is used only for routing.

### 1.4 `FillEvent` extension (G3-009, additive)

`FillEvent` keeps its eight fields and gains four, each defaulting to `None`:

| Field | Type | Validation when given |
|---|---|---|
| `commission` | `Decimal \| None` | must be Decimal (TypeError otherwise) |
| `commission_asset` | `str \| None` | non-empty str (ValueError otherwise) |
| `realized_pnl` | `Decimal \| None` | must be Decimal |
| `is_maker` | `bool \| None` | must be a real bool (TypeError otherwise) |

Inside `fold_fills`, each unique fill dict gains the keys `commission`, `commission_asset`,
`realized_pnl` and `is_maker`, read with `_get_field`. For older callers and dict-style events,
these keys are `None`. The fold's signature, its key `(order_id, exchange_trade_id)` and its
ordering do not change. `tests/test_execution_partials.py` needed no edit: none of its
assertions compares a whole fill dict against a literal.

### 1.5 Functions

- `unwrap_message(message) -> (event_name | None, payload dict | None)`. It accepts two shapes and
  reads them by duck typing, with no SDK import:
  - an object whose `actual_instance` is a plain dict, or a model with `to_dict()`; the event name
    is then the model class name, e.g. `OrderTradeUpdate`
  - a plain dict whose `e` carries the wire name

  Anything else returns `(None, None)`.
- `normalize_event_name(name)`: lower-cases the name and removes underscores and hyphens.
- `parse_stream_message(message, *, observed_at_utc)`: unwraps, routes and parses. In Task 1 only
  the `ordertradeupdate` route exists; every other name returns `UNKNOWN_EVENT_TYPE`.
- `parse_order_trade_update(payload, *, observed_at_utc, event_name=...)`
- `to_fill_event(event) -> FillEvent | None`. It sets `order_id = exchange_order_id`,
  `exchange_trade_id = trade_id`, `fill_price = last_filled_price`,
  `fill_quantity = last_filled_quantity` and `fill_time_utc = trade_time_utc`, and carries
  `commission`, `commission_asset`, `realized_pnl = realized_profit` and `is_maker`. It returns
  `None` for every `x` other than TRADE, and for a TRADE whose `l` is not positive.
- `canonical_payload_sha256(payload)`

---

## 2. What the plan fixes and what was a judgment call

### 2.1 Fixed by the plan (implemented as written)

- The `OrderUpdateEvent` field names and order, and which fields are optional (one exception: J1)
- `exchange_order_id` and `trade_id` are text built from the wire ints. `trade_id` exists only for
  TRADE and is never synthesized.
- The required wire set: `s c S o f q x X i E` and both `T`; for TRADE also `l L z t`
- A money field that arrives as a number (int, float, Decimal) is a `FIELD_VALIDATION` anomaly
  and is never coerced. A missing required field is `MALFORMED_PAYLOAD`.
- Quantities and prices are non-negative. Commission and realized profit may be signed.
- The 15 anomaly kinds, the six `StreamAnomaly` fields, a detail made only of names and types
  (at most 200 characters), and the canonical-JSON sha256
- The `to_fill_event` mapping and its `None` rules
- The four optional `FillEvent` fields and their carry-through in `fold_fills`
- The two envelope shapes and the name normalization
- The module is SDK-free; `observed_at_utc` is an argument.

### 2.2 Judgment calls made in Task 1 (each one is open to amendment)

| Id | Choice | Why | Alternative |
|---|---|---|---|
| J1 | `o.ps` is required on the wire | `position_side` is not optional in the plan's field list, and `FillEvent` and `fold_fills` need it; the plan's required-wire list omits `ps` | make `position_side` optional, and have `to_fill_event` return `None` without it |
| J2 | `modify_id` is `str \| None` | the SDK model types `M` as `StrictStr`; the plan said "optional int" (a mismatch with the SDK, recorded here) | `int`, which would make every real `M` (a string per the SDK) a `FIELD_VALIDATION` anomaly |
| J3 | `kw_only=True` on `OrderUpdateEvent` | keeps the plan's field order with `None` defaults; positional construction of 31 fields is error-prone | plain `frozen=True`, which forces required fields first and changes the order |
| J4 | `side` must be `BUY`/`SELL`, otherwise `FIELD_VALIDATION` | `fold_fills` raises on any other side; failing at parse turns that into an anomaly instead of a crash | keep `side` as a raw string |
| J5 | an empty string in an optional text field (`ot`, `N`, `wt`, `M`, `er`, `V`, `pm`) is `FIELD_VALIDATION` | the rule is "non-empty strings, never coerce"; mapping `""` to `None` would be a coercion | treat `""` as absent; this matters if real frames send `er: ""` (UNVERIFIED) |
| J6 | decimal grammar: ASCII digits, optional sign, optional fraction, optional exponent; no whitespace, `_`, NaN, Infinity or non-ASCII digits | `Decimal()` accepts all of these silently | accept whatever `Decimal()` accepts, provided the result is finite |
| J7 | ids and millisecond times must be ints >= 0 | negative ids and times are never valid | accept any int |
| J8 | a JSON `null` counts as absent (required: `MALFORMED_PAYLOAD`; optional: `None`) | the SDK's `to_dict` drops `None` anyway, so both message shapes behave the same | treat `null` as `FIELD_VALIDATION` |
| J9 | on a non-TRADE event, a present `o.t` is still type-checked (int >= 0) and then discarded | strict everywhere (P4) | ignore `o.t` completely for non-TRADE |
| J10 | a wire `e` that disagrees with the envelope's model name is `UNRECOGNIZED_ENVELOPE` (field `e`) | inconsistent envelopes are not trusted | ignore `e` when the model name is known |
| J11 | a `to_dict()` that raises, or a payload with non-string keys, is `UNRECOGNIZED_ENVELOPE` | an exception inside an SDK callback is swallowed (P5); an anomaly is visible | let the exception propagate |
| J12 | the hash covers the whole message payload, not just the `o` object; a `Decimal` inside it hashes as `{"__decimal__": text}`, any other non-JSON value as `{"__type__": name}` | deterministic, with no memory addresses | hash only the offending sub-object |
| J13 | the event does not carry `cp` (close-all), `pP` (price protect), `b`, `a`, `AP`, `cr`, `si`, `ss` or `gtd` | they are not in the plan's field list | add `close_position` and `price_protect` (see Q4) |
| J14 | a TRADE with `l == 0` parses and `to_fill_event` returns `None`, with no anomaly | as the plan says | make it a `FIELD_VALIDATION` anomaly |
| J15 | extra public names: `make_stream_anomaly`, `canonical_payload_sha256`, `StreamOutcome` (a type alias, widened in Task 3), `ORDER_TRADE_UPDATE_EVENT`, `DETAIL_MAX_CHARS`, `EVENT_NAME_MAX_CHARS`, `FIELD_PATH_MAX_CHARS` | the router (18-15) and the tests need them | keep them private |

### 2.3 Plan deviations and checks against the SDK

- **Millisecond conversion.** The plan says to reuse the approach of `binance_public._ms_to_utc`,
  but that function uses float division (`datetime.fromtimestamp(ms / 1000, tz=UTC)`). The
  events module follows the plan's other wording, "exact timedelta from the epoch":
  `epoch + timedelta(milliseconds=ms)`. This matches `src/data/archive.py` and
  `src/data/coverage.py`. An out-of-range value is `FIELD_VALIDATION`.
- **`M` type mismatch:** see J2.
- **No `e` property on the SDK model.** `OrderTradeUpdate.__properties` is `["E", "T", "o"]`, so
  `e` survives only through `from_dict`'s `additional_properties`; `to_dict` then emits it at the
  top level. This is why the event name for the model shape comes from the class name. A test
  pins this: the synthetic frame passes `OrderTradeUpdate.from_dict`, and a
  `UserDataStreamEventsResponse` around the model parses to the same event as the plain dict.
- All the other field names and types in section 1.3 match `order_trade_update_o.py` exactly.

---

## 3. What Task 3 will add (after this gate, with any amendment applied)

These field lists are the plan's own Task 2 listing. SDK types are taken from the installed
models (read for this aid). "Optional" follows the plan wherever the plan says so; everywhere
else it is the executor's proposal and part of Q6.

### 3.1 `AlgoUpdateEvent` (`ALGO_UPDATE`; SDK `AlgoUpdate{T, E, o}`, with no `e` property)

| Attribute | Wire (SDK type) | Note |
|---|---|---|
| `event_time_utc`, `transaction_time_utc` | `E`, `T` (StrictInt) | |
| `client_algo_id` | `o.caid` (StrictStr) | |
| `algo_id` | `o.aid` (StrictInt) | stored as text |
| `algo_type` | `o.at` (StrictStr) | |
| `order_type` | `o.o` (StrictStr) | |
| `symbol`, `side`, `position_side`, `time_in_force` | `o.s`, `o.S`, `o.ps`, `o.f` (StrictStr) | |
| `quantity` | `o.q` (StrictStr) | Decimal |
| `algo_status` | `o.X` (StrictStr) | the raw string, which must be in `ALGO_STATUS_VOCABULARY`; otherwise `UNKNOWN_ALGO_STATUS`, with no event. Classification is plan 18-06 |
| `actual_order_id` | `o.ai` (**StrictStr**, "Order Id") | `None` when `""` (before trigger); text otherwise |
| `average_price`, `executed_quantity`, `actual_order_type` | `o.ap`, `o.aq`, `o.act` (StrictStr) | "only display when order is triggered": optional |
| `trigger_price`, `price` | `o.tp`, `o.p` (StrictStr) | Decimal |
| `working_type` | `o.wt` (StrictStr) | |
| `reduce_only`, `close_position`, `price_protect` | `o.R`, `o.cp`, `o.pP` (StrictBool) | |
| `trigger_time_utc` | `o.tt` (StrictInt) | |
| `reject_reason` | `o.rm` (StrictStr) | free text, verbatim, at most 200 characters; diagnostic only, never a decision input (P23) |
| `is_activated` | `o.ia` (StrictBool) | "only meaningful for trailing order" |

The SDK also has `o.V` (STP mode), `o.pm` (price match) and `o.gtd` (StrictInt); the listing
does not carry them.

### 3.2 `AccountUpdateEvent`, `BalanceDelta`, `PositionDelta` (`ACCOUNT_UPDATE`, D-08: deltas only)

- `AccountUpdateEvent`: `event_time_utc` (`E`), `transaction_time_utc` (`T`), `reason` (`a.m`,
  carried verbatim; an unknown reason is NOT an anomaly), `balances: tuple[BalanceDelta, ...]`
  (`a.B`), `positions: tuple[PositionDelta, ...]` (`a.P`), `funding_symbol` (`a.S`, accepted only
  when the reason is FUNDING_FEE; otherwise `FIELD_VALIDATION`).
- `BalanceDelta`: `asset` (`a`), `wallet_balance` (`wb`), `cross_wallet_balance` (`cw`),
  `balance_change` (`bc`). All are StrictStr; the three balances become Decimal.
- `PositionDelta`: `symbol` (`s`), `position_amount` (`pa`, signed Decimal), `entry_price` (`ep`),
  `breakeven_price` (`bep`), `accumulated_realized` (`cr`), `unrealized_pnl` (`up`), `margin_type`
  (`mt`), `isolated_wallet` (`iw`), `position_side` (`ps`). All are StrictStr in the SDK.
- Nothing computes equity, margin or a position view from these events.

### 3.3 Other events

- `ListenKeyExpiredEvent`: `event_time_utc` only. The SDK model carries `listenKey` (StrictStr).
  It is a credential and is never stored; a test checks that the `repr` of every outcome never
  contains the key.
- `AccountConfigUpdateEvent`: `symbol` (`ac.s`, StrictStr), `leverage` (`ac.l`, **StrictInt**),
  `multi_assets` (`ai.j`, StrictBool), plus `E`/`T`.
- `IgnoredEvent`: event name and reason, for TRADE_LITE, STRATEGY_UPDATE and GRID_UPDATE.
- MARGIN_CALL gives `UNHANDLED_EVENT`. CONDITIONAL_ORDER_TRIGGER_REJECT gives `DEPRECATED_EVENT`.
  Any other name gives `UNKNOWN_EVENT_TYPE`.

### 3.4 Order-update anomaly paths (P22)

| Condition | Result |
|---|---|
| `x == AMENDMENT` | `AMENDMENT_EVENT` (the project never amends orders) |
| `x == CALCULATED` | `LIQUIDATION_EVENT` |
| `c` starts with `autoclose-`, `adl_autoclose` or `settlement_autoclose-` | `FORCED_CLOSE_ORDER` |
| `X == EXPIRED_IN_MATCH` | parses as an `OrderUpdateEvent` (terminal, not filled) |
| an unseen `x` / an unseen `X` | `UNKNOWN_EXECUTION_TYPE` / `UNKNOWN_ORDER_STATUS` |

None of these is dropped or coerced.

### 3.5 Other Task 3 artifacts

- `src/domain/algo_status.py`: `ALGO_STATUS_VOCABULARY` = {NEW, TRIGGERING, TRIGGERED, FINISHED,
  CANCELED, REJECTED, EXPIRED} and `is_known_algo_status`. The classification table is plan 18-06.
- The wire-field frozensets `ORDER_UPDATE_WIRE_FIELDS`, `ALGO_UPDATE_WIRE_FIELDS`,
  `ACCOUNT_UPDATE_WIRE_FIELDS`, `ACCOUNT_BALANCE_WIRE_FIELDS` and `ACCOUNT_POSITION_WIRE_FIELDS`.
  Plan 18-11 pins them against the SDK aliases.
- `tests/support/ast_guards.py`: guards that report forbidden imports, `float(` calls and
  wall-clock calls.
- More frame builders: `algo_update_frame`, `account_update_frame`, `listen_key_expired_frame`,
  `account_config_update_frame`.

---

## 4. Questions for the Task 2 gate (yes/no)

Reply "approve" to accept everything as written, or "amend" followed by the changes. Each
question below can be answered yes or no. A "no" means an amendment.

1. **Q1 (overall shape).** Do you approve the `OrderUpdateEvent` field list, names and types in
   section 1.3 as the shared contract for Phases 19, 20, 21 and 24?
2. **Q2 (J2).** Should `modify_id` stay `str` (as the SDK model types `M`) rather than the
   plan's `int`?
3. **Q3 (J1).** Should `o.ps` stay required (a frame without it becomes an anomaly)?
4. **Q4 (J13).** Should `OrderUpdateEvent` stay without `close_position` (`cp`) and
   `price_protect` (`pP`)? Answering no adds them as optional bools.
5. **Q5 (J5).** Should an empty string in an optional text field stay a `FIELD_VALIDATION`
   anomaly, rather than being read as absent?
6. **Q6 (Task 3 listing).** Do you approve `AlgoUpdateEvent` as listed in section 3.1? This
   covers `actual_order_id` as text from the SDK's `StrictStr` `ai`; `algo_id` as text from the
   int `aid`; the trigger-only fields optional; and `V`, `pm`, `gtd` not carried.
7. **Q7.** Should `reject_reason` (`rm`) be stored verbatim, capped at 200 characters, and stay
   diagnostic only?
8. **Q8 (D-08).** Do you approve `AccountUpdateEvent` with `BalanceDelta` and `PositionDelta` as
   in section 3.2, as deltas only, with an unknown reason carried verbatim rather than raised as
   an anomaly?
9. **Q9.** Should `ListenKeyExpiredEvent` carry only the event time, with no key field at all?
10. **Q10.** Should `AccountConfigUpdateEvent` carry `leverage` as `int` (per the SDK's
    `StrictInt`) and `multi_assets` as `bool`?
11. **Q11.** Should TRADE_LITE, STRATEGY_UPDATE and GRID_UPDATE become `IgnoredEvent` (counted,
    not anomalies), with MARGIN_CALL as `UNHANDLED_EVENT` and CONDITIONAL_ORDER_TRIGGER_REJECT as
    `DEPRECATED_EVENT`?
12. **Q12 (J3).** Should `OrderUpdateEvent` (and the Task 3 events) stay keyword-only
    (`kw_only=True`)?
13. **Q13 (J14).** Should a TRADE with `l == 0` stay a parsed event that yields no fill, rather
    than becoming an anomaly?
