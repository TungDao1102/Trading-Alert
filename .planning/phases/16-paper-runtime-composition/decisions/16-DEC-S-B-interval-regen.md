# 16-DEC-S-B-interval-regen: approval of the regeneration inventory and of simulator semantics 2.1.0 (user decision)

option: approve
decided by: user
date: 2026-10-15
words:
approve S1

inventory: evidence/16-S-B-interval-regen-inventory.md at commit 4789c6a
inventory_sha256: dba5e32b6cd131a027dce64cd8cd5b2dfe5c9de59c3658b724107f6b97b102a4

context (recorded for audit): the words above are the user's whole reply. They answer the assistant's request to approve, approve-except or refuse the inventory, with the choice S1/S2/S3 for the stale experiment_id in tests/fixtures/phase10/loaders/evidence_sample.json. The user chose S1.

## Scope (the assistant's reading; the user did not state a narrower or wider one)
- Authorized: plan 07 Task 3 of quick 261014-nnl: SIMULATOR_SEMANTICS_VERSION 2.0.0 -> 2.1.0 and regeneration/re-pinning of every item of the inventory by the command the inventory names (6 VERSION_PIN tests / 7 literal lines, 9 DERIVED_DIGEST tests in tests/test_backtest_simulator.py and the 9 digests in tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md, 88 STORED_RECORD tests from tests/fixtures/phase10/loaders/evidence_sample.json), the comment rewording the inventory proposes (semantics.py WR-05 note and the comment at lines 88-92, lifecycle.py docstring), design test 10, and the two files the plan's files_modified omitted: tests/test_backtest_simulator.py and tests/test_backtest_terminal_settlement.py (pin at line 200).
- S1: in evidence_sample.json change only backtest[0].experiment.simulator_semantics_version to the code constant, by the verified command in the inventory; the stale experiment_id is left untouched (option S2/S3 not chosen).
- The skipped PostgreSQL test (test_soak_evidence_export.py::test_the_pg_source_exports_every_record_stored_on_postgresql) is unverified on this host; the executor reports it, it does not edit it unless the inventory's classification applies and a verifying run is possible.
- Any failure outside the three inventory classes is a STOP.

## NOT covered (each needs its own words from the user)
Plan 09 (landing, holdout_consumed.json marker), plan 10, manifest freeze, O-03/16-46, any Holdout read, ExperimentRecord, git push.
