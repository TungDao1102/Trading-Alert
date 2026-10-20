---
quick_id: 261020-g1a
slug: gate-1008-not-a-429
status: complete
date: 2026-10-20
base: eb471c0
commits:
  - cef22ea test(261020-g1a) RED
  - cb9bd71 fix(261020-g1a) GREEN
  - f5b790e docs(261020-g1a)
---

# 261020-g1a: a -1008 is not a 429

## Defect

`src/domain/exchange_errors.py` classified -1008 ("Request Throttled") as RATE_LIMITED for every
call kind. `BinanceUsdmAdapter._sdk_call` (and `SdkListenKeyPort`, `BinancePublicMarketData`, the
probe) record every RATE_LIMITED in the one process-wide `RestRateLimitGate`. So one -1008, which
is usually the answer to a new entry, paused every REST call of the process for the 429 fallback.
During that pause the protective stop, the entry-remainder cancel and the emergency reduce-only
close were refused with a `PreSendRefusal`.

## Binance facts (WebFetch summaries, read 2026-10-20, not character-exact)

- Error-code page, -1008: "Server is currently overloaded with other requests. Please try again
  in a few minutes." and "Request throttled by system-level protection. Reduce-only/close-position
  orders are exempt. Please try again." The page names only reduce-only/close-position as exempt.
- General-info page: the node has exceeded its maximum concurrency; "Close-position, reduce-only,
  and cancel orders are exempt"; covered endpoints POST /fapi/v1/order, /batchOrders (the summary
  also named /order/test); "Rate-limit counting: Not counted (overload protection)".
- HTTP 429 must be backed off from, and repeated 429s lead to a 418 IP ban (2 minutes to 3 days).
- -1003 is the request-weight limit (429 text and the IP-ban text): unchanged, still RATE_LIMITED.
  -1015 (too many new orders) is unchanged, still RATE_LIMITED.

## Change

- New `ExchangeErrorCategory.SYSTEM_THROTTLED`. The -1008 table entry maps every call kind to it.
  Its note records the 2026-10-20 reading. `read_date` stays at the baseline (see Gaps).
- No consumer changes meaning:
  - It is not in the gate's recorded sets (`_RATE_LIMIT_CATEGORIES` in binance_usdm.py and
    binance_public.py, `_GATE_CATEGORIES` in binance_userdata.py, `_RATE_LIMIT_REASONS` in
    binance_probe.py). `RestRateLimitGate.record` and `rate_limit_decision` give no wait for it.
  - `retry_eligible` is False and `safe_mode_eligible` is False.
  - In the manager, protection coordinator and emergency closer, a placement -1008 takes the same
    path RATE_LIMITED took (it is neither REJECTED_DEFINITIVE nor PRECONDITION_NO_POSITION). The
    manager still sends one POST and probes once by client id. Not found means UNKNOWN + SAFE_MODE,
    and nothing is re-sent. What changed: that probe now reaches the exchange. Before, the gate
    pause refused it.
  - The listenKey port adds SYSTEM_THROTTLED to `_TRANSIENT_CATEGORIES`, so it is still reported
    as `ListenKeyTransient`, as before, but nothing is paused.
- The HTTP-class rules are byte-identical. A 429 class is RATE_LIMITED and a 418 class is IP_BANNED
  whatever the body code, -1008 included. Nothing bypasses a 429 pause or a 418 ban.
- No backoff hint was added. The codebase has a pattern for a wait only in `RateLimitDecision` for
  418/429, and reusing it would re-create the pause. The call is re-raised unchanged.

## Tests (test-first: RED at cef22ea, GREEN at cb9bd71)

- tests/test_exchange_errors.py: -1008 expected SYSTEM_THROTTLED on all kinds. New tests check
  that SYSTEM_THROTTLED gives no rate-limit wait, no retry and no SAFE_MODE. A -1008 under a
  429/418 class still pauses or bans. -1003 and -1015 stay RATE_LIMITED. The note records the
  exemption and the read.
- tests/test_binance_usdm_signed_calls.py: a -1008 on the entry is one POST, re-raised as the same
  object, and leaves the gate open. All eleven signed methods (stop, both cancels, queries,
  snapshots) then reach the SDK. A -1008 on any signed method is neither recorded nor retried. A
  real 429 after a -1008 still pauses every method.
- tests/test_binance_market_close_adapter.py: after a -1008 entry, the reduce-only MARKET close is
  sent.
- tests/test_userdata_adapter.py: a -1008 on start/keepalive/close is ListenKeyTransient with
  category SYSTEM_THROTTLED. The gate is not paused and the next call is sent.
- tests/test_system_throttle_protection.py (new): the real adapter meets the -1008, and the
  coordinator and the closer run over the fake exchange behind the SAME real gate. The coordinator
  places the stop and the cancel and reaches PROTECTED. The closer goes FLAT. Two controls show a
  real 429 in that gate still refuses the stop and the close.

## Verification (run on this worktree)

- Targeted and related suites with `-n 4` (24 files: taxonomy, gate, signed calls, error routing,
  market close, user data, probe, SDK mapping contract, protection, emergency close, manager,
  phase 18/19 gates, public, adapter contracts, limits): 1921 passed, 1 skipped (symlinks are not
  available on Windows).
- tests/test_phase18_gate.py, test_phase19_gate.py, test_agents_md.py, test_exchange_errors.py:
  355 passed. test_sources_phase18_section.py, test_decision_alignment_exchange.py: 104 passed.
- `ruff check src tests scripts` passed; `ruff format --check` passed (623 files); `mypy src`
  found no issues (214 files); `uv lock --check` passed;
  `verify_decision_alignment.py all` printed ALL_PASS.
- Not run: the full suite, `-m docker`, the `*_pg.py` files (no PG code was touched), any Demo,
  `--execute` or Binance call. The only network calls were two WebFetch reads of the docs pages.

## Docs

- docs/integration/BINANCE.md 6.2: the category list now includes SYSTEM_THROTTLED, and the
  retry-rules bullet has a sentence on -1008.
- 19-OWNER-GAPS.md, Q4 row: the -1008 defect is fixed, and the owner's 429/418 policy is recorded
  (durable pending protective actions, no bypass of the pause, reconcile before resend,
  CLOSE_REQUIRED when max_unprotected_ms expires). The row stays OPEN until that policy is built.
- 19-REVIEW-FIX.md: a short follow-up section.
- No DECISIONS id was added. Historical Phase 18 research, plan and summary files that call -1008
  RATE_LIMITED were left as records.

## Gaps and surprises

- The worktree started at 344d1c0, which does not descend from eb471c0. It was reset to eb471c0
  as instructed.
- `read_date` of the -1008 entry was not moved to 2026-10-20. The read-date machinery is pinned by
  tests (the latest read must be 2026-10-17, with a fixed re-read code set and a matching
  docs/SOURCES.md row). The 2026-10-20 reading is recorded in the entry note only, and
  docs/SOURCES.md has no 2026-10-20 row. If the owner wants a third read recorded formally, that
  is a separate change.
- A -1008 on an entry still ends in UNKNOWN + SAFE_MODE when the probe does not find the order.
  That is the existing fail-closed Q5 path. Treating -1008 as a definitive "not placed" answer
  would avoid the SAFE_MODE, but the docs do not say "not executed" in so many words, so that is
  left for the owner.
- `-1015` (too many new orders) still pauses the whole process, including the protective calls.
  It is an order-count limit, but whether it should pause risk-reducing calls belongs to Q4. Not
  changed.
