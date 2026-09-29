# scripts/dev

Quick dev helpers (PowerShell). Run from anywhere:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/<name>.ps1

| Script | Purpose |
|--------|---------|
| `clean.ps1` | Remove `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`, `htmlcov`, `logs/` (`-WhatIf` to preview; never touches `.venv`, `data/`, `.env`) |
| `test.ps1` | Run all tests (`uv run pytest`); extra args go to pytest |
| `migrate.ps1` | `alembic upgrade head` using `DATABASE_URL` from `.env` (`-Revision`, `-Current`) |
| `_common.ps1` | Shared helpers (dot-sourced; not a command) |

Add new helpers here and dot-source `_common.ps1`.
