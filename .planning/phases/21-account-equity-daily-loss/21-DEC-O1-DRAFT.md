# Draft DECISIONS row for Phase 21 owner item O-1 (NOT WRITTEN)

PROPOSED BY THE ASSISTANT, NOT ACCEPTED. `docs/DECISIONS.md` is the owner's file: nothing here was added to it. The id is provisional (the next free id after D083 at the time of writing; the owner assigns the real one).

Owner answer of 2026-10-23, verbatim: "1 để 15000, 2 giữ toàn bộ".

| ID | Decision | Status | Basis and consequence |
|----|----------|--------|-----------------------|
| D0xx | O-1 of Phase 21: the maximum age of the account equity reading is 15000 milliseconds; the persisted day state is kept in full | Proposed | Basis: the owner's answer of 2026-10-23 adopting the assistant's recommendation. Part 1: `account.max_equity_age_ms` = 15000 in `config/execution/execution-limits-v1.toml` with provenance `DECISION`; age greater than the key or negative is stale (NO_TRADE `UNCERTAIN_ACCOUNT_STATE`), exactly the key passes (D-03); the equity is always a REST read and any ACCOUNT_UPDATE or stream gap invalidates the cached reading (D-01), so the key is only the bound for a silent stream. The number comes from the 1 to 2 seconds the three sequential REST reads took on Demo (demo-observed, not mainnet), not from mainnet latency data. Part 2: no retention rule; `daily_risk_days`, `daily_loss_components` and `risk_reservations` rows are not deleted; a purge, if ever wanted, is a separate decision with its own migration. Setting the key does not open the live path: the other keys of the file stay `NOT_CONFIGURED` and `LIVE_ORDERS_DISABLED` stays. |

## What applying it changes (when the owner accepts the row)

1. `config/execution/execution-limits-v1.toml`: `[account] max_equity_age_ms = 15000` and `[provenance.account] max_equity_age_ms = "DECISION"` (check the README of that directory for the exact provenance spelling).
2. `tests/test_phase21_gate.py` `test_invariant_2_the_equity_age_limit_is_not_configured_and_required` asserts the value and the provenance are `NOT_CONFIGURED`: it must change in the same commit (assert the key is present, required, and 15000 with provenance `DECISION`).
3. Other tests that read the file as all-`NOT_CONFIGURED` (a count of unset keys, the README count of keys still unset, the `LIMITS_NOT_CONFIGURED` GLOSSARY row "fifteen required of sixteen keys") move from fifteen to fourteen unset required keys; the full suite shows exactly which.
