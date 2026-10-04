# Task completion checklist

Run the CI gate locally before calling a code task done:
1. `uv run ruff check` and `uv run ruff format --check`
2. `uv run mypy src`
3. `uv run pytest -m "not docker" -rs -p no:cacheprovider` (or the relevant subset plus anything touching pinned hashes/fixtures)
4. If params/protocol/fixtures changed: `python scripts/verify_decision_alignment.py` and a DECISIONS entry listing moved pins.
5. New `src/` modules touching money: add to the explicit file list in `tests/test_domain_no_float.py`.
Report failures with output; never claim green without running.
