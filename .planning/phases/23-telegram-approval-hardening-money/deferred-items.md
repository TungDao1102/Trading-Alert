# Phase 23 deferred items

Out-of-scope discoveries logged by executors (not fixed by the plan that found them).

## Found by plan 23-11 (2026-10-26), both pre-existing guard failures from earlier plans

Both fail on HEAD without any 23-11 change (`git diff d0ecc2c2 HEAD -- src/adapters src/risk` is empty).
The orchestrator's full-suite run will report them; they need an owner/orchestrator decision on the
pinned lists, not a code fix inside plan 23-11.

1. `tests/test_no_unratified_defaults.py::test_no_canonical_key_gets_a_numeric_constant_in_src_or_scripts`
   fails with `src/adapters/telegram_notify.py:464 annotated assignment gives RETRY_AFTER_CAP_SECONDS a
   numeric constant`. Source: plan 23-07 (`RETRY_AFTER_CAP_SECONDS: int = 30`, restating
   `NOTIFY_MAX_DELAY_SECONDS`). The 23-07 SUMMARY did not run this test. Either the guard learns that
   this constant restates a ratified value (a pinned allow-list entry), or the constant is imported
   rather than restated.
2. `tests/test_modeled_costs_none_guard.py::test_consumer_audit_is_pinned_and_fails_when_a_new_reader_appears`
   fails because `src/risk/money_at_stake.py::build_money_at_stake` now reads `sized.modeled_costs_per_unit`
   (an attribute read and a `MoneyAtStakeUnavailable` call label that the pinned list lacks). Source: plan
   23-02. The read is a refusal on None (not a None-as-zero read); the pinned list needs the two entries
   after an audit.
