---
phase: 22-leverage-margin-liquidation-guard
plan: 04
subsystem: risk
tags: [margin, available-balance, fail-closed, pure-module, F-966, criterion-3]
requires:
  - phase: 21
    provides: "ReservationStatus (RESERVED, PLACED) in src/risk/reservations.py; live_equity.py style"
provides:
  - "src/risk/margin_check.py: required_initial_margin, estimated_fees, estimated_open_loss, MarginVerdict, margin_verdict, MarginClaim, free_margin_basis, other_claims_margin, AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED"
affects: [22-09, 22-10, 22-14, 22-16]
tech-stack:
  added: []
  patterns: ["pure money predicate: every number is a keyword-only input, one function per open fact, one constant per unverified exchange rule"]
key-files:
  created:
    - src/risk/margin_check.py
    - tests/test_margin_check.py
  modified:
    - tests/test_domain_no_float.py
key-decisions:
  - "free_margin_basis is the single seam for the free-margin basis; it returns availableBalance today."
  - "AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED is False (amendment A1): every PLACED claim is counted in addition to availableBalance until the owner-run Demo case settles the netting."
  - "MarginVerdict.required is Decimal | None: None only for UNCERTAIN_ACCOUNT_STATE (an unknown claim makes the need unknown)."
status: complete
requirements-addressed: [RISK-01, RISK-02]
duration: ~30 min
completed: 2026-10-24
commits: 2
plan_head_before: b2d9ec8347c12976816ec689d451eec94a3785c3
plan_head_after: 6e4c7562cddd04eea69e172d68de660b5556b583
actuals:
  tokens: 14000
  tasks: 2
  commits: 2
---

# Phase 22 Plan 04: Pure available-margin predicate Summary

**Clock-free Decimal module that decides criterion 3 (F-966): the free margin must cover the new order's initial margin, round-trip fees, the open loss of an already-marketable limit, the margin of every other RESERVED/PLACED claim and an owner-supplied headroom; the recorded Demo -2019 shape is refused INSUFFICIENT_MARGIN.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | c04c2aa2 | `required_initial_margin`, `estimated_fees`, `estimated_open_loss`, `MarginVerdict`, `margin_verdict`; the module in `SCANNED_FILES` |
| 2 | 6e4c7562 | `MarginClaim`, `free_margin_basis`, `other_claims_margin`, the netting constant |

`commits: 2` counts the commits whose subject starts with `(22-04)`. The shared working tree means `git rev-list plan_head_before..plan_head_after` also contains sibling plans' commits (22-01, 22-02); the SUMMARY commit follows.

## What was built

- `required_initial_margin(*, quantity, price, leverage)` = quantity x price / leverage; leverage is a plain int of at least 1 (bool, Decimal, float, str, 0 refused).
- `estimated_fees(...)` = notional x (entry rate + exit rate); negative rates refused. `estimated_open_loss(...)` = the marketable-limit gap x quantity, 0 for a resting limit.
- `margin_verdict(...)`: required = need + need x headroom_bps / 10000; pass when `available >= required` (equality passes). Shortfall gives `INSUFFICIENT_MARGIN`; `others_margin=None` gives `UNCERTAIN_ACCOUNT_STATE`. Leverage, both fee rates and `headroom_bps` are keyword-only with no default (signature test).
- `MarginClaim` accepts only RESERVED or PLACED; PLACED requires an aware-UTC `placed_at_utc`; margin is a positive Decimal or None.
- `other_claims_margin`: RESERVED always counts; PLACED counts unless `resting_orders_netted` is True and the claim was placed at or before the reading; the candidate's own row is excluded; an unknown margin on a counted claim returns None.
- Literal oracles: recorded shape 10 x 78570.9 at x20 needs 39285.45 against 4998.39137539 (required with 1 bps headroom 39918.00860172); small plan needs 160.64, passes at exactly 168.672 and fails at 168.671999; with 50 of other claims 221.172.
- Purity tests: no wall clock, no float, forbidden-import scan, no quote-asset literal, and the only int literals are 0, 1 and 10000.

## Verification

| Command | Result |
|---------|--------|
| `uv run pytest -m "not docker" tests/test_margin_check.py tests/test_domain_no_float.py tests/test_phase21_gate.py` | passed (110 tests; 87 in `test_margin_check.py`) |
| `uv run mypy src/risk/margin_check.py` | no issues |
| `uv run ruff check` / `ruff format --check` on the three files | clean |
| `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config` | clean |
| `git log --grep="^[a-z]*(22-04):" -- config params src/adapters src/execution src/persistence src/domain` | prints nothing |

Evidence label: executed unit tests [DESIGN]; the -2019 figures are demo-observed, not mainnet (D-19). The free-margin basis and the netting rule are NOT Demo-proven (amendment A1): criterion 3 is not Demo-proven until the owner runs `available_balance_with_resting_order`.

## Deviations from Plan

None - plan executed as written. Two small choices inside the plan's latitude:

- `MarginVerdict.required` is `Decimal | None` (None for the UNCERTAIN verdict) because the need is unknown there; the plan's field list was `(ok, reason_code, required, available)`.
- `margin_verdict` takes the already-based `available_balance`; `free_margin_basis` is called by the reading-based `check_available_margin` of plan 22-10, not inside the verdict.

## Known Stubs

None. `free_margin_basis` ignoring `total_open_order_initial_margin` is the documented seam, not a stub.

## Threat Flags

None. No new endpoint, auth path, file access or schema.

## Self-Check: PASSED

- `src/risk/margin_check.py`, `tests/test_margin_check.py` exist; `tests/test_domain_no_float.py` lists the module.
- Commits c04c2aa2 and 6e4c7562 are ancestors of HEAD.
