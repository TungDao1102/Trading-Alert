# Phase 15 deferred items

Out-of-scope discoveries logged by executors. Not fixed in the plan that found them.

## Found in 15-04

- **`tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` fails on this Windows checkout.** The generator writes LF files and the working copy of the committed fixtures is CRLF (`core.autocrlf=true`), so the byte comparison differs at the first line ending. Verified independently: generating the fixtures and comparing after `\r\n` -> `\n` shows zero differences, so the planner change in 15-04 did not alter any fixture content. Pre-existing and unrelated to Phase 15 (fix would be a test that normalizes line endings or a `.gitattributes` entry; not done here).

## Resolved in 15-10

- The CRLF failure logged under "Found in 15-04" is fixed (F12): `tests/test_phase6_fixture_geometry.py::test_generator_is_deterministic_and_matches_committed_fixtures` now normalizes `\r\n` to `\n` on both sides before comparing, and passes on this Windows checkout. The comparison still binds the generator output to the committed files by content.
