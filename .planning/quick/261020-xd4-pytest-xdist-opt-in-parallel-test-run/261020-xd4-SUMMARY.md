---
status: complete
---
# 261020-xd4 summary

pytest-xdist 3.8.0 is in the dev extra (uv.lock adds only pytest-xdist and execnet 2.1.2). Parallel is opt-in: `uv run pytest -m "not docker" -n 4`. `addopts` stays `-q`, so the default run, CI and every recorded gate command (IMAGE_COMMIT evidence etc.) stay sequential. Whether a parallel run counts as equivalent evidence is the owner's decision.

Nothing broke in parallel. Four full runs (-n 4 twice, -n 6 twice), each 10424 passed + 19 skipped of the same 10443 selected, 0 failed, with the same skip reasons as the 16-64 baseline. The static scan found no shared state (no fixed temp dirs, no repo writes, no os.environ mutation outside monkeypatch, only port 0, git used read-only). PostgreSQL tests clone uniquely named databases, and each worker builds its own template.

Wall time: sequential ~24 min; -n 4 566-606 s; -n 6 487-529 s. Python peak memory: about 1.7 GB at -n 4 and 2.3 GB at -n 6. Recommended: -n 4 on this machine. Numbers and where the time goes are in xdist-measurements.txt: the slowest tests are research-engine replays in module fixtures (up to 62 s setup), Parquet dataset building (test_case_input_builder 101 s across 6 tests), backfill_cli (29.6 s) and bash-subprocess deploy tests (about 10 s each). Database clones are not among the slowest 30.

Docs: one line in the AGENTS.md Conventions commands and the test.ps1 row in scripts/dev/README.md. Gates: verify_decision_alignment ALL_PASS, ruff check, ruff format --check, mypy src, uv lock --check green. Not pushed.
