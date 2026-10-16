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
