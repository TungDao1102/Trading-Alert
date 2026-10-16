---
phase: 18-user-data-stream-error-taxonomy
plan: 01
subsystem: docs / exchange facts
status: complete
tags: [binance, sources, user-data-stream, algo-status, error-taxonomy, docs-gate]
requires: []
provides:
  - "docs/SOURCES.md section 'Facts read for Phase 18 (research 2026-10-15; executor re-read dated per row)' (15 page rows, 9 register status lines)"
  - "tests/test_sources_phase18_section.py (structure, Phase 11 hash, status rows, marker count, URL register)"
  - "EXECUTION_SPEC.md 6.1 rows TRIGGERED and CANCELED; BINANCE.md section 5 stream lifecycle"
affects: [18-03, 18-05, 18-06, 18-11, 18-14, 18-18, 18-25]
tech-stack:
  added: []
  patterns: ["Phase-scoped SOURCES section kept apart from the gate-read Phase 11 register, pinned by a sha256 test"]
key-files:
  created:
    - tests/test_sources_phase18_section.py
  modified:
    - docs/SOURCES.md
    - docs/integration/BINANCE.md
    - docs/trading/EXECUTION_SPEC.md
decisions:
  - "Every executor re-read failed (no WebFetch tool; curl answered by the AWS WAF challenge), so all 15 rows are UNVERIFIED with the exact failure text; the research baseline facts (B1 to B13) are kept in the Used-for cells, labelled as baseline and not re-confirmed"
  - "Installed SDK 17.4.0 docstrings and models (listenKey endpoints, Change Position Mode, Query Algo Order, ALGO_UPDATE and ListenKeyExpired models) are used only as a labelled cross-check, never as a page read"
  - "EXECUTION_SPEC 6.1 TRIGGERED and CANCELED meanings come from the research search summary and 09-EXCHANGE-FACTS Fact 2, as the plan directs when the page stays UNVERIFIED; the grounding paragraph says so"
metrics:
  duration: "about 15 minutes (2026-10-16 02:40Z to 02:55Z)"
  completed: 2026-10-16
actuals:
  tokens: 9600
  tasks: 3
  commits: 3
plan_head_before: b195db9037c57e0f92d9a1299cfb47d144e8d02b
plan_head_after: 5854085
---

# Phase 18 Plan 01: Binance documentation re-read and the Phase 18 SOURCES section Summary

The new `docs/SOURCES.md` section "Facts read for Phase 18" lists 15 Binance pages. Each has a dated row with its method and the label "not verified live". The executor could not read any page: the WebFetch tool was missing and every curl request got the AWS WAF challenge. So every row is UNVERIFIED and records the exact failure text, and the research baseline facts in each row are labelled as not re-confirmed. EXECUTION_SPEC 6.1 and 8 and BINANCE.md section 5 now state the facts inside the pinned gate wording. The docs gate prints ALL_PASS.

## Commits

`commits: 3` counts only this plan's commits (`git log --grep "(18-01)" b195db9..HEAD`). `git rev-list --count b195db9..HEAD` gives 4 because it also counts `3b6a3a3 feat(18-04)`, which the parallel plan 18-04 committed into the same worktree. This SUMMARY's own docs commit is not in that count.

| Task | Commit | Files |
| --- | --- | --- |
| 1 Tracer: listenKey, /private, 24-hour rows plus the structure test | fe12f45 | docs/SOURCES.md, tests/test_sources_phase18_section.py |
| 2 Event, position-mode, error-code and remaining rows plus the nine register lines | a75343e | docs/SOURCES.md, tests/test_sources_phase18_section.py |
| 3 Facts carried into BINANCE.md 5 and EXECUTION_SPEC 6.1 and 8 | 5854085 | docs/integration/BINANCE.md, docs/trading/EXECUTION_SPEC.md, tests/test_sources_phase18_section.py |

## Page status (executor re-read 2026-10-16)

No page was READ. The WebFetch tool was not available in the executor session, because the deferred-tool loader that provides it was missing. So each page was requested with curl (browser user-agent): one attempt, then one retry. Every request ended in HTTP 202 with `x-amzn-waf-action: challenge` and a 2110-byte AWS WAF JavaScript challenge page with no documentation text. A documentation path was first redirected with HTTP 302 to a `/en/docs/products/...` or `/en/docs/catalog/...` path.

| Page | Status | Exact failure |
| --- | --- | --- |
| user-data-streams/Start-User-Data-Stream | UNVERIFIED | 02:47:32Z and 02:47:33Z: 302 to catalog `rest-api/user-data-streams#start-user-data-stream`, then 202 WAF challenge |
| user-data-streams/Keepalive-User-Data-Stream | UNVERIFIED | 02:47:34Z and 02:47:35Z: 302 to catalog `#keepalive-user-data-stream`, then 202 WAF challenge |
| websocket-market-streams/Important-WebSocket-Change-Notice | UNVERIFIED | 02:47:36Z and 02:47:38Z: 302 to `/en/docs/products/.../Important-WebSocket-Change-Notice`, then 202 WAF challenge |
| websocket-market-streams/Connect | UNVERIFIED | 02:47:39Z (twice): 302 to `/en/docs/products/.../Connect`, then 202 WAF challenge |
| user-data-streams/Event-Algo-Order-Update | UNVERIFIED | 02:47:40Z and 02:47:41Z: 302, then 202 WAF challenge; the catalog alternative `ws-streams/user-data-streams` (02:47:59Z and 02:48:00Z) got the same challenge directly, so no path answered |
| user-data-streams/Event-Order-Update | UNVERIFIED | 02:47:41Z and 02:47:42Z: 302, then 202 WAF challenge; catalog alternative as above |
| user-data-streams/Event-Balance-and-Position-Update | UNVERIFIED | 02:47:43Z (twice): 302, then 202 WAF challenge; catalog alternative as above |
| user-data-streams/Event-Listen-Key-Expired | UNVERIFIED | 02:47:44Z and 02:47:46Z: 302, then 202 WAF challenge; catalog alternative as above |
| trade/rest-api/Change-Position-Mode | UNVERIFIED | 02:47:46Z and 02:47:48Z: 302 to catalog `trade#change-position-mode`, then 202 WAF challenge |
| error-code | UNVERIFIED | 02:47:49Z and 02:47:51Z: 302, then 202 WAF challenge |
| general-info | UNVERIFIED | 02:47:51Z and 02:47:52Z: 302, then 202 WAF challenge |
| trade/rest-api/Query-Algo-Order | UNVERIFIED | 02:47:53Z and 02:47:54Z: 302 to catalog `trade#query-algo-order`, then 202 WAF challenge |
| change-log | UNVERIFIED | 02:47:55Z (twice): 302, then 202 WAF challenge |
| websocket-market-streams/Live-Subscribing-Unsubscribing-to-streams | UNVERIFIED | 02:47:56Z and 02:47:57Z: 302, then 202 WAF challenge |
| catalog `api/rest-api/trade` (New Algo Order section, the URL research B9 used) | UNVERIFIED | 02:48:00Z (twice): 202 WAF challenge directly; the direct `trade/rest-api/New-Algo-Order` path (02:47:58Z and 02:47:59Z) was redirected with 302 to `#new-algo-order` on the same page and got the same challenge |

All nine items of the research UNVERIFIED register are still UNVERIFIED. Each has a one-line reason in the SOURCES section.

## Gate and test results

- `uv run pytest -m "not docker" tests/test_sources_phase18_section.py -x`: 9 passed (red first: 4 failures before the section existed; `test_execution_spec_status_rows` failed before the Task 3 rows were added).
- `uv run pytest -m "not docker" tests/test_decision_alignment_exchange.py tests/test_sources_phase18_section.py -x`: 90 passed.
- `uv run python scripts/verify_decision_alignment.py docs`: no FAIL line, final line `ALL_PASS docs` (after each task).
- `uv run ruff check` and `uv run ruff format --check` on the new test file: clean.
- Phase 11 register: its sha256 (`248baa07...3dbbd5`, LF body) still matches. The register is byte-identical.
- BINANCE.md now has 6 `verify against current Binance docs` markers (at least 3 are required). EXECUTION_SPEC.md has no new developers.binance.com URL.

## Deviations from Plan

1. **[Rule 3 - Blocking] WebFetch unavailable.** The plan prescribes WebFetch, but the tool could not be loaded in this session. curl to the official host was the only way to fetch, and it was answered by the WAF challenge. Following the plan's failure rule, every page is recorded as UNVERIFIED with the exact failure. No Wayback copy, mirror, search summary or memory was used.
2. **Extra retry on the event-page alternative path.** For the four event pages, the direct path got one attempt and one retry. The plan's one allowed alternative, the catalog `ws-streams/user-data-streams` page, also got an attempt and a retry, so that alternative was requested twice, not once. Both were answered by the same WAF challenge.
3. **Installed SDK source used as a labelled cross-check.** The plan allows the label "installed SDK source". Rows say where an SDK 17.4.0 docstring or model was read on 2026-10-16. The Method cell still starts with UNVERIFIED, because an SDK docstring is not a page read.
4. **`uv sync --frozen --extra dev`** was run once because the worktree's fresh `.venv` lacked the dev and runtime packages. It installs exactly what `uv.lock` pins, and no dependency changed.
5. **STATE.md, ROADMAP.md, REQUIREMENTS.md and WINDOWS.md were not updated.** The orchestrator instructed this executor not to edit ROADMAP.md, STATE.md or DECISIONS.md. The state and requirement updates are left to the phase orchestrator.

## Proposed ROADMAP correction

None. No page was re-read, so no ROADMAP success criterion can be shown to be wrong.

## Open issues

- Every Phase 18 Binance fact still rests on the research baseline (WebFetch summaries of 2026-10-15, plus search summaries for the event pages), not on an executor re-read. Plan 18-18, a blocking-human step on the connected machine, has to repeat every read with a working fetch path, such as a browser or a WebFetch-capable session.
- The ALGO_UPDATE status vocabulary, including the new TRIGGERED and CANCELED rows, the event-type string `listenKeyExpired`, the SUBSCRIBE parameter format on `/private` and Demo user-data support remain UNVERIFIED.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: tests/test_sources_phase18_section.py, docs/SOURCES.md (section present), docs/integration/BINANCE.md, docs/trading/EXECUTION_SPEC.md
- FOUND commits: fe12f45, a75343e, 5854085

## Addendum 2026-10-16

After this plan ran, the phase orchestrator re-read the Binance pages with WebFetch on the same day. The old `/docs/derivatives/usds-margined-futures/...` paths answer a landing shell or the WAF challenge. The pages that answered use `https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/<page>` for general pages and `https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/<group>` for REST endpoints. The user-data events are sections of one user-data-streams page, and `api/ws-streams/~schemas` shows only the top-level keys. The results are in a fixed fact sheet. This addendum carries that sheet into the documents. WebFetch passes each page through a small summarising model, so every fact below is not character-exact and not verified live. No fact was added beyond the sheet.

### What changed

- `docs/SOURCES.md`, section "Facts read for Phase 18" only. Rows the sheet covers now have a Method cell that starts with "WebFetch summary" and says "not character-exact" and "not verified live". The facts read go in "Used for". The old URL stays first in each row, and the working URL is added beside it. Two rows are new: the general part of the user-data-streams page (`#connect`) and the WebSocket API general-info page, so the table has 17 rows. A new addendum paragraph explains the URL pattern. The nine register status lines now give the 2026-10-16 reason. The Phase 11 section is untouched, and its sha256 test still passes.
- `tests/test_sources_phase18_section.py`, written test-first: three new tests. They failed (2 failures) before the SOURCES edit. They check the following. (1) A "WebFetch summary" row cites a working-pattern URL and the date 2026-10-16, and says "not character-exact". (2) The eight pages the sheet covers are recorded as READ. (3) `/private/ws/<listenKey>` and `settlement_autoclose` are each named in a row that says "CONTRADICTS the research baseline", and `Retry-After` and `-4509` are each named as "absent from the page". No existing assertion was weakened, and the required suffixes are unchanged.
- `docs/trading/EXECUTION_SPEC.md` 6.1. The TRIGGERED, CANCELED and FINISHED rows use the page wording. FINISHED is "filled OR canceled" and does not prove that the protective exit executed. The "FINISHED does not mean filled" bullet now says the same. The trailing-stop bullet cites the change-log entry of 2026-08-21 (two ALGO_UPDATE events, `ia:false` then `ia:true`). The grounding paragraph now records the WebFetch read. Section 8 now records the read Change-Position-Mode facts: weight 1, `dualSidePosition` required, `recvWindow` at most 60000, UM and CM share the setting, -4067 and -4068. No developers.binance.com URL was added, and all pinned phrases of EX-02, EX-03 and EX-06 are kept.
- `docs/integration/BINANCE.md` section 5. The baseline statements are replaced by the read ones:
  - listenKey validity is 60 minutes, PUT extends it by 60 minutes, and DELETE answers 200 with no data;
  - a connection lasts 24 hours;
  - ping every 3 minutes with a 10-minute pong deadline. This comes from the WebSocket API general-info page, and the doc labels it as such;
  - the URL is `wss://fstream.binance.com/private/ws/<listenKey>`;
  - events of the same type are ordered by `T` and `E`;
  - the ORDER_TRADE_UPDATE `x` and `X` lists, the ALGO_UPDATE statuses, the ACCOUNT_UPDATE `m` list and the `listenKeyExpired` wording;
  - the change-log entry on the duplicate trailing-stop ALGO_UPDATE.

  The remaining UNVERIFIED items are listed in the section. The file has 6 "verify against current Binance docs" markers.

### Page status after the addendum

| Page | Status |
| --- | --- |
| Start-User-Data-Stream (REST `user-data-streams`) | READ, WebFetch summary (error list not on the page) |
| Keepalive-User-Data-Stream (PUT and DELETE) | READ, WebFetch summary (error lists not on the page) |
| user-data-streams page, general part and `#connect` (new row) | READ, WebFetch summary |
| websocket-api-general-info (new row) | READ, WebFetch summary |
| Event-Listen-Key-Expired | READ, WebFetch summary (section and schema keys) |
| Change-Position-Mode | READ, WebFetch summary |
| error-code | READ, WebFetch summary |
| general-info | READ, WebFetch summary (Demo hosts, 503 variants and base endpoints not in the summary) |
| Query-Algo-Order (with DELETE algoOrder and GET order) | READ, WebFetch summary (`algoStatus` not enumerated; not-found code not on the page) |
| change-log | READ, WebFetch summary (first 100000 of 155376 characters) |
| New Algo Order (catalog `trade`) | READ, WebFetch summary (`recvWindow` maximum not in the summary) |
| Event-Algo-Order-Update | UNVERIFIED: the `o.*` field table did not render (the status values were read) |
| Event-Order-Update | UNVERIFIED: the `o.*` field table and the meaning of `t` did not render (the `x` and `X` lists were read) |
| Event-Balance-and-Position-Update | UNVERIFIED: the `a.*`, `B` and `P` tables did not render (the `m` list was read) |
| Important-WebSocket-Change-Notice | UNVERIFIED: not covered (SUBSCRIBE format, whether `events=` is accepted) |
| websocket-market-streams/Connect | UNVERIFIED: not covered (the streams' own ping rule, message and stream limits, new-connection limit) |
| Live-Subscribing-Unsubscribing-to-streams | UNVERIFIED: not covered (SUBSCRIBE parameter format for a listenKey) |

Not read at all: `GET /fapi/v1/openAlgoOrders` and `DELETE /fapi/v1/order`. Also unread: Demo user-data support and the Demo host, the not-found error codes, and the duplicate `clientAlgoId` code. All nine register items stay "still UNVERIFIED", each with an updated reason.

### Contradictions and differences against the research baseline

1. **URL form (CONTRADICTS).** The user-data-streams page gives `wss://fstream.binance.com/private/ws/<listenKey>`. It has no `?listenKey=` query form and no `events=` parameter. Baseline B3 had `/private/ws?listenKey=<k>&events=...`, taken from the Change Notice page, which was not re-read. Plan 18-11 must not assume the query form, and plan 18-18 settles it live.
2. **`settlement_autoclose` (CONTRADICTS).** The prefix is absent from the Order Update section. Baseline B5b, a search summary, listed `settlement_autoclose-`.
3. **FUNDING_FEE `B` and `P` (differs, as far as the summary goes).** The summary says the event carries `B`, and also `P` only for an isolated position. B5b said a cross position carries both `B` and `P`. The tables did not render, so this stays open.
4. **Retry-After (absent from the page).** It is not on general-info, error-code or the WebSocket API general-info page. This agrees with the B7 and B8 summaries, but no page supports the research assumption A9 that Binance sends the header. The fallback wait for a missing `retry_after` stays required.
5. **-4509 (absent from the page).** It is not on error-code, which agrees with B7. It stays Demo-observed only, although D-09 lists it as a required code.
6. **Smaller points.** The ACCOUNT_UPDATE `m` list has 17 values, against 7 in B5b. The change-log is now 155376 characters, against 154346, and its newest entry is 2026-10-15. The New Algo Order summary does not list the `recvWindow` maximum that B9 recorded (60000). The user-data-streams page still lists a "Conditional Order Trigger Reject" section, and whether it is marked deprecated is not in the summary.

### Observation outside this addendum's scope

`src/ops/redaction.py` catches a listenKey by shape only in the forms `listenKey=<value>` and `"listenKey": "<value>"`. Under the path form `/private/ws/<listenKey>`, a logged URL is caught only through the runtime-secret registration (D-13). The plan that builds the connection (18-11) should make sure the key is registered before any URL is logged. No code was changed here.

### Verification (addendum)

- `UV_OFFLINE=1 uv run --frozen --extra dev pytest -m "not docker" tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py -q`: all passed (12 in the Phase 18 file, which had 2 failing first).
- `UV_OFFLINE=1 uv run --frozen --extra dev python scripts/verify_decision_alignment.py docs`: final line `ALL_PASS docs`.
- `ruff check` and `ruff format --check` on the test file: clean.
