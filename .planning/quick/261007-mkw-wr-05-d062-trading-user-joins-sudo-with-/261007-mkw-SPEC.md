# Quick task 261007-mkw: WR-05 (D062), trading user joins sudo with a password

Source: the user's instruction of 2026-10-07 (decision recorded in docs/DECISIONS.md D062, host context in D061 HOSTS). Read docs/DECISIONS.md D062, D061 and .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md first.

Rules: no push. Do not touch .planning/config.json, .planning/state.json or .gsd/. Do not stage them. Commit trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Pytest runs file by file with `PYTHONPATH=.` (Windows crashes otherwise). Docker, bootstrap and deploy tests that need Docker or a Linux host are CI-only on this Windows machine: run only the non-docker ones locally and say which could not run. Never read `.env`.

## Why

`deploy/bootstrap.sh` sets `PermitRootLogin no` and its final operator message says "$TRADING_USER has no sudo". The user decided that the `trading` user joins the sudo group with a password and NO NOPASSWD rule (a NOPASSWD rule on a script the trading user can edit would be unrestricted root).

## Change (only these)

1. `deploy/bootstrap.sh`: when creating or updating the trading user (near lines 221-227, where `useradd` and `usermod -aG docker` run) also add the user to the `sudo` group. Verify the `sudo` package exists on the target image (Ubuntu or Debian, check which images the script supports) and install it if missing. Do not assume. Keep `PermitRootLogin no` and every other SSH setting unchanged.
2. Lock-out guard: sudo with a password needs the account to HAVE a password, and `useradd` creates none while SSH password login stays disabled. Do NOT invent a non-interactive way to set the password. The operator sets it with `passwd trading` in the root session. Add a guard like the existing authorized_keys guard (around line 320, "lock-out guard"): refuse to write the SSH drop-in unless the trading user is in the sudo group AND `passwd -S trading` shows a usable password (status P). Die with a clear message. In `--dry-run` the guard only prints what it would check.
3. Final operator checklist (around lines 524-540): replace item 6's "Root SSH login is now disabled and $TRADING_USER has no sudo ... install the timer as root from the provider console" text with the new flow: set the password with `passwd trading`, test `sudo -v` in a SECOND SSH session as trading BEFORE closing the root session, then use `sudo` for the timer install and later apt, ufw or systemctl changes. Update `docs/operations/RUNBOOK.md` section 13.5 (operator checklist) and any other RUNBOOK sentence that says trading has no sudo or that root is reached through the console.
4. Docs: mark WR-05 as implemented in `.planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md` (status column and the WR-05 section; this file is CRLF, preserve it). Add one dated line to `docs/DOC_STATUS.md` (CRLF, preserve). Do not rewrite history in closed phases and do not edit ROADMAP.md.
5. Tests: update `tests/test_bootstrap.py` and `tests/test_deploy_docs.py` (they pin the old wording). Add tests: the sudo-membership step is present, the guard refuses without a password and without the group, no `NOPASSWD` string appears anywhere in deploy/ or the RUNBOOK, `PermitRootLogin no` is unchanged. Docker/bootstrap tests are CI-only on Windows: run the non-docker ones file by file and say which could not run locally.

## Acceptance

- `deploy/bootstrap.sh --dry-run` output shows `usermod -aG sudo` and the new guard.
- The guard fails closed in tests (no group, no password).
- `uv run ruff check`, `uv run ruff format --check` and `uv run mypy src` are clean; `shellcheck` if the repo CI runs it (check .github/workflows/ci.yml) and it is available locally, otherwise say so.
- One commit `fix(deploy): trading user joins sudo with a password (D062 WR-05)` with the trailer.

## Report back

Files changed, test commands and results, anything that surprised you, and anything you could not verify locally.
