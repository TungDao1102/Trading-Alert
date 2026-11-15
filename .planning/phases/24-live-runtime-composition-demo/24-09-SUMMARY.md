---
phase: 24-live-runtime-composition-demo
plan: 09
subsystem: paper-shadow
tags: [shadow, money-at-stake, telegram, text-version, D-19, P23-R1]
requires: [24-01, 24-05, 24-08]
provides:
  - "SHADOW_TEXT_V2: SHADOW alert with the money rows; money_json on both approval rows"
  - "build_shadow_money: money block from the SizedResult that sized the plan"
affects: [src/paper/shadow_runtime.py (wiring still to do), 24-06, 24-10 to 24-17 (no file overlap)]
tech-stack:
  added: []
  patterns: ["versioned alert text selected at ShadowApprovalBook construction"]
key-files:
  created: [tests/test_paper_shadow_money.py]
  modified: [src/paper/shadow.py, tests/shadow_fakes.py, tests/test_paper_shadow_messages.py]
key-decisions:
  - "Q10 (owner, 24-01): a Phase 16 soak is running, so the money block is a NEW text version (shadow-text/2); shadow-text/1 is the old text byte for byte and stays the default"
  - "Money rows reuse render_money_block (DEMO wording); only the equity observation time is rewritten to the SHADOW UTC + Asia/Ho_Chi_Minh pair, because every SHADOW text must show each time in both zones"
status: complete
actuals:
  tokens: 20000
  tasks: 2
  commits: 2
plan_head_before: 18b04991c750901f9ff1fcde643df585653bc267
plan_head_after: 19da625ab90658be7cf770a7589790551e6633c3
commits: 2
completed: 2026-10-31
---

# Phase 24 Plan 09: SHADOW money block as a new text version Summary

SHADOW alerts can now show the money at stake (notional, margin at the configured leverage, loss at SL, profit per TP gross and net, equity used with source and time) and store the same canonical `money_json` on both approval rows, as `shadow-text/2`; `shadow-text/1` keeps the old text and pins untouched (owner Q10).

## What was built

- `src/paper/shadow.py`
  - `SHADOW_TEXT_V1` / `SHADOW_TEXT_V2` / `DEFAULT_SHADOW_TEXT_VERSION` (= V1). The version is chosen at `ShadowApprovalBook(..., text_version=)`; unknown value refused.
  - `build_shadow_money(signal, plan, sized, cost_rates, leverage, leverage_source, equity, equity_source, equity_observed_at_utc)`: wraps `build_money_at_stake` with the side from the signal and the stop and take-profits from the plan, so the block comes from the same `SizedResult` that sized the plan (F-015, T-24-22).
  - `format_shadow_alert(..., money=None, text_version=V1)`: V2 requires a block that agrees with the plan (`require_money_consistent`, same checks as the DEMO request) and inserts the rows directly after `Quantity:`. V1 refuses a block instead of dropping it silently.
  - `ShadowApprovalBook.issue(..., money=None)`: V2 stores `money_canonical_json` on both rows; a missing or disagreeing block is refused before any token is issued. `send_shadow_alert(..., money=None)` passes it through, refused before any store write or send.
- `tests/shadow_fakes.py`: `make_shadow_sized`, `make_shadow_money` (the in-memory stores already keep the whole `Approval`, so `money_json` is mirrored with no change).
- `tests/test_paper_shadow_money.py` (new, 9 tests): both rows identical and parse back to the built block; rows shown in DEMO wording; refusal with no trace entry; build failures name the field; mismatching block refused; V1 byte-identical and stores no money; V2 differs from V1 only by the money rows; default is V1.
- `tests/test_paper_shadow_messages.py`: a V1 pin (no money rows) and a V2 pin naming D-19 / P23-R1.

No pin had to change: V1 is the default, so every existing assertion still holds. `src/adapters/telegram_notify.py` was not touched (`render_money_block` and `require_money_consistent` are public).

## Verification

- 368 passed: money, messages, runtime, isolation, buttons, confirm, approval_message, money_at_stake, approval_desk, agents_md.
- ruff check and format clean on the four files; `uv run mypy src` clean (done before the last docstring edit; mypy on shadow.py and telegram_notify.py re-run clean after it).
- `git diff --exit-code -- tests/fixtures/phase23 pyproject.toml uv.lock` clean; `uv lock --check` resolves.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git grep -n -e src.execution -e src.live -- src/paper/shadow.py` prints nothing (see deviations).

## Deviations from Plan

1. **[Rule 1 - Bug] Time format in the money rows.** The DEMO `Equity used:` row writes the observation time as `+07 (... UTC)`. SHADOW texts must show each time as a UTC + Asia/Ho_Chi_Minh pair (`assert_shadow_text`, FakeBot), so the first send failed. `_shadow_money_lines` rewrites only that time with `format_time_pair`; every amount and word is the DEMO renderer's.
2. **[Rule 3] Acceptance grep.** The module docstring contained the text `src.execution` ("imports nothing from `src.execution`"), so the plan's own `git grep` would never print nothing. Reworded to "the execution package". No import change.
3. The plan said `issue` builds the block itself. `issue` does not hold the `SizedResult`, cost rates, leverage or equity, so the caller builds it with `build_shadow_money` and passes `money=`; `issue` validates, canonicalises and stores it.

## Open item for the orchestrator (wiring, not in this plan's files)

`src/paper/shadow_runtime.py:425` still builds `ShadowApprovalBook(stores, clock=clock)` (V1) and `on_outcome` calls `send_shadow_alert` without `money`, so the running SHADOW path is unchanged, which is what keeps the Phase 16 soak evidence valid. To switch SHADOW to V2: construct the book with `text_version=SHADOW_TEXT_V2` and pass `money=build_shadow_money(signal=..., plan=..., sized=verdict.sized, cost_rates=..., leverage=..., leverage_source=..., equity=..., equity_source=..., equity_observed_at_utc=...)` from `on_outcome`. The cost rates, leverage and equity reading for SHADOW (paper config values, owner item O-1 for leverage) are not available in this plan's files; the switch is the owner's call after the soak. `tests/test_paper_shadow_runtime.py` has no V2 session yet for the same reason (its Rig builds the book).

## Known Stubs

None.

## Threat Flags

None.

## Gaps

No PostgreSQL tests were run (`*_pg.py`, by instruction); `approvals.money_json` already exists (migration 0013) and the PG store persists the whole `Approval`.

## Self-Check: PASSED

- tests/test_paper_shadow_money.py, src/paper/shadow.py, tests/shadow_fakes.py, tests/test_paper_shadow_messages.py exist.
- Commits 601abc8a and 19da625a are ancestors of HEAD.
