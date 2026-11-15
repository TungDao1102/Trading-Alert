# Phase 23 deferred items

Out-of-scope discoveries logged by executors (not fixed by the plan that found them).

## Found by plan 23-11 (2026-10-26): resolved

Both guard failures (`tests/test_no_unratified_defaults.py` on the retry-wait constant and
`tests/test_modeled_costs_none_guard.py` on the `money_at_stake` reads) were fixed by commit 1d62e1cb
and pass; the entries are removed. See `23-OWNER-CHECKS.md`.
