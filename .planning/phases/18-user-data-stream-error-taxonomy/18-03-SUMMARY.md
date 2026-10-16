---
phase: 18-user-data-stream-error-taxonomy
plan: 03
subsystem: adapters/userdata-events, domain/algo-status, execution/fill-monitor
status: complete
tags: [binance, user-data-stream, ORDER_TRADE_UPDATE, ALGO_UPDATE, ACCOUNT_UPDATE, listenKey, StreamAnomaly, EXEC-05, EXEC-02, D-01, D-05, D-06, D-08]
requires: []
provides:
  - src/adapters/binance_userdata_events.py (StreamAnomalyKind, StreamAnomaly, make_stream_anomaly, canonical_payload_sha256, OrderUpdateEvent, AlgoUpdateEvent, BalanceDelta, PositionDelta, AccountUpdateEvent, ListenKeyExpiredEvent, AccountConfigUpdateEvent, IgnoredEvent, StreamOutcome, unwrap_message, normalize_event_name, parse_stream_message, parse_order_trade_update, parse_algo_update, parse_account_update, parse_listen_key_expired, parse_account_config_update, to_fill_event, ORDER_EXECUTION_TYPE_VOCABULARY, ORDER_STATUS_VOCABULARY, FORCED_CLOSE_CLIENT_ID_PREFIXES, ORDER_UPDATE_WIRE_FIELDS, ALGO_UPDATE_WIRE_FIELDS, ACCOUNT_UPDATE_WIRE_FIELDS, ACCOUNT_BALANCE_WIRE_FIELDS, ACCOUNT_POSITION_WIRE_FIELDS)
  - src/domain/algo_status.py (ALGO_STATUS_VOCABULARY, is_known_algo_status)
  - src/execution/fill_monitor.py FillEvent optional commission, commission_asset, realized_pnl, is_maker (carried through fold_fills)
  - tests/support/ast_guards.py (module_imports, forbidden_imports, float_constructor_calls, wall_clock_calls)
  - tests/support/userdata_frames.py (FRAME_LABEL and a synthetic builder for every event kind)
affects:
  - plan 18-06 (classification table over ALGO_STATUS_VOCABULARY)
  - plan 18-11 (pins the wire-field frozensets against the SDK aliases)
  - plan 18-15 (router: journals StreamAnomaly, counts IgnoredEvent, de-duplicates the twice-arriving trailing-stop ALGO_UPDATE, adds FILL_TOTAL_MISMATCH / UNKNOWN_ORDER / QUEUE_OVERFLOW)
  - plan 18-24 (JSON file form of the synthetic frames and the provenance README)
  - Phases 19, 20, 21, 24 (import these event types)
tech-stack:
  added: []
  patterns:
    - frozen kw_only dataclasses with __post_init__ validation; Decimal money through a strict ASCII decimal grammar; exact ms-to-UTC via timedelta
    - every parse failure is a StreamAnomaly (detail from field and type names only, canonical-JSON sha256), never a coercion or a default
    - order-level anomaly classification (x, c, X) before the remaining fields are read
    - routing tables keyed by the normalized event name (wire name and SDK model class name meet)
    - wire-field frozensets proven equal to the keys the parsers read (recording dict) and a subset of the SDK aliases
key-files:
  created:
    - src/adapters/binance_userdata_events.py
    - src/domain/algo_status.py
    - tests/support/userdata_frames.py
    - tests/support/ast_guards.py
    - tests/test_userdata_events.py
    - tests/test_userdata_parsers.py
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DESIGN-REVIEW-event-types.md
  modified:
    - src/execution/fill_monitor.py
decisions:
  - "Task 2 design gate: option amend, decided by the user on 2026-10-16 (decisions/18-DEC-D01-event-types.md). OrderUpdateEvent gains close_position (o.cp), price_protect (o.pP), activation_price (o.AP), callback_rate (o.cr) and good_till_date_ms (o.gtd, raw int); AlgoUpdateEvent also carries stp_mode (o.V), price_match (o.pm), good_till_date_ms (o.gtd); everything else approved as listed"
  - "Order-level anomaly precedence: unseen x, then AMENDMENT, then CALCULATED, then a forced-close client id, then unseen X; these run before the other fields are read, so a liquidation frame is reported as LIQUIDATION_EVENT even if another field is malformed"
  - "Any string outside the x, X or algo X vocabulary (also the empty string) is the UNKNOWN_* anomaly; a non-string is FIELD_VALIDATION; absence is MALFORMED_PAYLOAD"
  - "OrderUpdateEvent and AlgoUpdateEvent re-check the vocabularies at construction (execution_type only NEW, CANCELED, EXPIRED, TRADE; order_status in the six documented values; algo_status in ALGO_STATUS_VOCABULARY), so the invariant also holds for directly built events"
  - "The settlement_autoclose- prefix is kept although the 2026-10-16 page read does not list it (SOURCES row: contradicts baseline B5b); an extra forced-close prefix can only add an anomaly"
metrics:
  duration: "Task 1 committed 2026-10-16T03:11Z; Task 2 decided by the user the same day; amendment and Task 3 from about 04:20Z to 04:50Z"
  completed: 2026-10-16
  tasks: 3
  files: 8
actuals:
  tokens: 34500
  tasks: 3
  commits: 7
plan_head_before: 45c986cbd87578919d7b5ed6a31c345f75000eb2
plan_head_after: 175f6eb364a60e5f11b573e40ed541cd3b1cb7d6
---

# Phase 18 Plan 03: User-data event types and strict parsers Summary

Every user-data stream message now becomes either a frozen, SDK-free, Decimal-typed event (ORDER_TRADE_UPDATE, ALGO_UPDATE, ACCOUNT_UPDATE deltas, listenKeyExpired, ACCOUNT_CONFIG_UPDATE), an `IgnoredEvent` (TRADE_LITE, STRATEGY_UPDATE, GRID_UPDATE) or a `StreamAnomaly` with a deterministic payload hash. A TRADE frame reaches `fold_fills` as a `FillEvent` with commission, commission asset, realized PnL and the maker flag carried. The shapes were reviewed by the user at the Task 2 design gate and amended as recorded in `decisions/18-DEC-D01-event-types.md`.

All test frames are SYNTHETIC (`FRAME_LABEL = "SYNTHETIC_FROM_SDK_MODEL"`), built from the installed SDK 17.4.0 models. The event field tables of the Binance pages could not be read (docs/SOURCES.md, "Facts read for Phase 18"). Field names and types therefore come from the SDK models. The value lists (order `x`/`X`, algo `X`) and the event names come from WebFetch summaries, which are not verified live. Passing these tests is not evidence of how live Binance frames behave.

## Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Tracer: ORDER_TRADE_UPDATE TRADE frame to OrderUpdateEvent, FillEvent and folded view | bed16f6 | src/adapters/binance_userdata_events.py, src/execution/fill_monitor.py, tests/support/userdata_frames.py, tests/test_userdata_events.py |
| 2 | Design review gate (blocking-human) | 9b733df (review aid), ec8a94b (decision record, user option amend) | decisions/18-DESIGN-REVIEW-event-types.md, decisions/18-DEC-D01-event-types.md |
| 2a | D01 amendment applied to the Task 1 code and tests | a7c5b85 | src/adapters/binance_userdata_events.py, tests/support/userdata_frames.py, tests/test_userdata_events.py |
| 3 | Strict parsers for ALGO_UPDATE, ACCOUNT_UPDATE, listenKeyExpired, ACCOUNT_CONFIG_UPDATE, the anomaly paths, the status vocabulary and the AST guards | 175f6eb | src/adapters/binance_userdata_events.py, src/domain/algo_status.py, tests/support/ast_guards.py, tests/support/userdata_frames.py, tests/test_userdata_parsers.py |

The measured `commits: 7` (`git rev-list --count 45c986c..HEAD`, before this SUMMARY commit) includes two commits of other plans that landed on the branch in the same window: 142a476 (18-01) and 2c848ae (18-02). Five of the seven belong to this plan, and ec8a94b also records O-18-01.

## Task 2 decision (design gate)

`option: amend`, `decided by: user`, `date: 2026-10-16`, record `decisions/18-DEC-D01-event-types.md`. The user adopted the reviewer's answers to Q1 to Q13. The amendments that were applied:

- **Q1/Q4 (OrderUpdateEvent):** these fields are added, all optional:
  - `close_position: bool | None` from `o.cp`
  - `price_protect: bool | None` from `o.pP`
  - `activation_price: Decimal | None` from `o.AP`, through the strict decimal grammar, non-negative
  - `callback_rate: Decimal | None` from `o.cr`, through the same grammar, non-negative
  - `good_till_date_ms: int | None` from `o.gtd`, a raw integer >= 0 with no timestamp meaning inferred

  A present value of the wrong type is a FIELD_VALIDATION anomaly. The dataclass rejects wrong types itself (TypeError or ValueError).
- **Q6 (AlgoUpdateEvent):** `stp_mode` (`o.V`), `price_match` (`o.pm`) and `good_till_date_ms` (`o.gtd`) are added. The rest of the listing in section 3.1 of the review aid is unchanged.
- **Q2, Q3, Q5, Q7 to Q13: approved as written.** These cover:
  - `modify_id` stays `str`, and `o.ps` stays required
  - an empty optional text is FIELD_VALIDATION
  - `rm` is kept verbatim, capped at 200 characters, and used as a diagnostic only
  - ACCOUNT_UPDATE yields deltas only
  - ListenKeyExpiredEvent carries the event time only
  - leverage is an int and multi_assets a bool
  - the ignored, unhandled and deprecated routes stay as listed
  - every event is kw_only and frozen
  - a TRADE with `l == 0` parses and yields no fill

## Results

- `tests/test_userdata_events.py`: 123 passed (Task 1, plus 33 parametrized cases for the amendment)
- `tests/test_userdata_parsers.py`: 232 passed (59 test functions, one or more per behaviour bullet of Task 3)
- `tests/test_execution_partials.py`: 9 passed; `tests/test_execution_attach.py`: 20 passed (no assertion removed or changed)
- All four together: 384 passed
- `uv run mypy src`: no issues in 188 source files
- `uv run ruff check`: all checks passed
- `uv run ruff format --check`: 554 files already formatted
- The AST guards report no forbidden import, no `float()` call and no wall-clock read in `src/adapters/binance_userdata_events.py` and `src/domain/algo_status.py`. Beyond the stdlib, the events module imports only `src.execution.fill_monitor` and `src.domain.algo_status`.
- Every builder's frame is accepted by the strict SDK model (`model.to_dict() == frame`) and by its parser. The SDK callback shape (`UserDataStreamEventsResponse`) parses to the same event as the plain dict.
- The parsers read exactly the keys in the wire-field frozensets (checked with a recording dict), and each set is a subset of the installed SDK aliases. `ALGO_UPDATE_WIRE_FIELDS` equals all 26 keys of the SDK model.
- The synthetic dummy listenKey never appears in the `repr`, the `str` or any attribute of the event or of any anomaly. The checks cover the dict shape, the SDK-model shape, a missing `E`, a mistyped `E`, a wrong `e` and a frame with no `e`.

## Deviations from Plan

### Auto-fixed Issues

None. No bug was found in the code being changed.

### Judgment calls (documented, open to review)

1. **Required versus optional wire fields of ALGO_UPDATE.** Required: `E`, `T`, and `o.caid aid at o s S ps f q X tp`. Every other key is optional. The plan's listing marks only `ai`, `ap`, `aq`, `act` as optional. The SDK types every field `Optional`, and the field table could not be read, so this split is the executor's.
2. **ACCOUNT_UPDATE rows.**
   - Balance rows require `a wb cw bc`.
   - Position rows require `s pa ep up mt ps`. `bep`, `cr` and `iw` are optional, because `iw` is documented "if isolated position".
   - An absent `B` or `P` is an empty tuple.
   - Balances, `pa`, `cr`, `up` and `iw` are signed. `ep` and `bep` are non-negative.
3. **`rm` empty string.** Q5 (empty optional text is FIELD_VALIDATION) applies to `rm` as well, so `rm: ""` is an anomaly. The default ALGO_UPDATE frame therefore omits `rm`. `ai: ""` is read as None, because the plan says so explicitly.
4. **`tt` = 0** converts exactly to the epoch (`1970-01-01T00:00Z`) and is not mapped to None. The parser infers nothing from it.
5. **ACCOUNT_CONFIG_UPDATE.**
   - At least one of `ac` or `ai` must be present; otherwise the frame is MALFORMED_PAYLOAD with field `ac`.
   - Within `ac`, both `s` and `l` are required. Within `ai`, `j` is required.
   - The leverage must be an int >= 1.
6. **Algo `S`** must be BUY or SELL, the same rule as J4 for orders.
7. **`IgnoredEvent`** carries `event_name` (as received, at most 64 characters) and a fixed `reason` text. It carries no event time.
8. **The plan's `files_modified` list includes `tests/test_execution_partials.py`.** It needed no edit, because no assertion compares a whole folded fill dict. Nothing in it changed.

## Known Stubs

None. The phrase "placeholder" in `tests/support/userdata_frames.py` describes the intentional synthetic dummy listenKey (`SYNTHETIC_LISTEN_KEY`). It is not a stub.

## Open Issues

- **Synthetic frames only.** Real RECORDED_DEMO frames from plan 18-21 must confirm or contradict several things:
  - the required sets above
  - whether Binance sends `rm: ""` or `ai: ""` on normal updates; `rm: ""` would currently make every such ALGO_UPDATE an anomaly
  - `tt` before the trigger
  - how `ap`, `aq` and `act` look before the trigger
  - the empty-string behaviour of `er` and the other optional texts

  A contradiction calls for a user decision. The guards must not be weakened silently.
- **The forced-close prefix `settlement_autoclose-`** is kept although the page read on 2026-10-16 does not list it (SOURCES row: contradicts baseline B5b).
- **The trailing-stop ALGO_UPDATE that arrives twice** (`ia` false, then true) parses both times. De-duplicating it is plan 18-15.

## Threat Flags

None. The module adds no network endpoint, file access or credential path. The listenKey is never read into any type (T-18-08 mitigated and tested).

## Self-Check: PASSED

- FOUND: src/adapters/binance_userdata_events.py, src/domain/algo_status.py, tests/support/ast_guards.py, tests/support/userdata_frames.py, tests/test_userdata_events.py, tests/test_userdata_parsers.py, decisions/18-DEC-D01-event-types.md
- FOUND commits: bed16f6, 9b733df, ec8a94b, a7c5b85, 175f6eb
