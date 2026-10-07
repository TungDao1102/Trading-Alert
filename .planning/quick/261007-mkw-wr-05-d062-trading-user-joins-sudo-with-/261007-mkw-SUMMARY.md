---
phase: quick-261007-mkw
plan: 01
status: complete
commits: 1
plan_head_before: 157ffc7
plan_head_after: 7148528
completed: 2026-10-07
actuals:
  tasks: 3
  commits: 1
---

# Quick 261007-mkw: WR-05 (D062), trading user joins sudo with a password

Code commit: `7148528` `fix(deploy): trading user joins sudo with a password (D062 WR-05)` (not pushed).

## Files changed (six, all staged by explicit path)

- `deploy/bootstrap.sh`: `sudo` added to `step_base_packages`; helpers `user_in_group` and `passwd_status`; `usermod -aG sudo` in `step_user`; `sudo_lockout_guard` called in `step_sshd` after the authorized_keys guard and before the drop-in write; `passwd` added to the preflight command list; checklist item 6 rewritten.
- `tests/test_bootstrap.py`: stateful `useradd`/`usermod`/`getent`/`id` stubs (state dir outside the `root` tree), `passwd` stub (only `-S` accepted, anything else exits 2), `passwd -S` a probe prefix, `CONFIGURED_ENV` groups include sudo, dry-run markers, checklist needles, 9 new test functions (13 cases).
- `tests/test_deploy_docs.py`: three new tests (RUNBOOK sudo flow, old sentences gone, scan of `deploy/` and the RUNBOOK for the all-caps sudoers keyword).
- `docs/operations/RUNBOOK.md`: 13.1 item 3, 13.4 order sentence, new sudo bullet, "keep root session open" bullet, 13.5 items 4 and 6, section 17 notes for 13.1, 13.4, 13.5.
- `docs/DOC_STATUS.md`: one dated line.
- `.planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md`: WR-05 status cell and an "Implemented 2026-10-07" paragraph.

All five CRLF files edited through scratchpad Python scripts and verified pure CRLF afterwards (CRLF count equals LF count; `ruff format` on the two test files kept CRLF). `deploy/bootstrap.sh` is pure LF.

## Commands and results

- `bash -n deploy/bootstrap.sh`: ok
- `PYTHONPATH=. uv run --frozen --offline pytest tests/test_bootstrap.py -q`: all pass, 1 skipped (`test_env_file_mode_is_0600`, NTFS cannot represent POSIX modes, pre-existing)
- `... tests/test_deploy_docs.py -q`: all pass
- `... tests/test_deploy_scripts.py -q`: pass, 8 skipped (shellcheck not installed)
- Also run, all pass: `test_decision_alignment_bookkeeping`, `test_decision_alignment_protocol`, `test_env_example`, `test_kill_gate_docs`, `test_research_gate_negative`
- `uv run ruff check`: clean; `uv run ruff format --check`: clean (after formatting `tests/test_deploy_docs.py`); `uv run mypy src`: no issues in 149 files
- `git diff --cached --name-only` listed exactly the six files; `git status` afterwards still shows config.json/state.json modified and `.gsd/` and the two quick dirs untracked, as before.

## Non-vacuity proof

With the single `sudo_lockout_guard` call in `step_sshd` commented out, running `-k "sudo_guard or dry_run_shows or never_sets"` made 8 tests FAIL: guard refusal for status L, NP and UNREADABLE, missing sudo group (`STUB_USERMOD_NOOP`), configured-host re-run with status L, the NP-then-P flow, the dry-run guard line test and the password-never-set test (which needs a refusal). Call restored (file identical to the committed one), all pass again.

## Deviations

- Order: I implemented the bootstrap.sh change before the new tests (plan Task 1 asked for the failing golden test first). The non-vacuity proof above stands in for the red phase on the guard; the golden sudo-membership test was not watched failing against the old script.

## Surprises

- None blocking. `git status` initially listed the same untracked/modified paths the orchestrator named. No `NOPASSWD` text existed in `deploy/` or the RUNBOOK beforehand. The only "console" sentence in the RUNBOOK was 13.5 item 6, as the plan predicted.

## Not verifiable locally

- shellcheck (not installed; CI runs `shellcheck -x -P SCRIPTDIR deploy/*.sh`); the new shell code was written to be clean (quoted expansions, declared locals, no unused variables) but was not linted.
- Real sudo prompt, real `passwd -S` output format on Debian 12 / Ubuntu 22.04 / 24.04 (stub imitates `user STATUS date min max warn inact`), real `usermod`, that the `sudo` package creates the `sudo` group on a minimal Debian image, real ufw/sshd effects: real-host only (UAT 8-10).
- Docker-only tests were not run (none were touched; `test_deploy_scripts.py` ran without its shellcheck cases).
- Package facts for `sudo` (Debian 12, Ubuntu 22.04/24.04) come from the plan's research table, not re-fetched.

## For the caller

- `docs/DECISIONS.md` D062 still says the implementation is not done (it also covers CR-01, and DECISIONS.md was out of scope); ROADMAP.md and STATE.md were not touched.
- On AWS Ubuntu images cloud-init may add its own passwordless sudo rule for the default image user; this change neither adds nor removes it.
- Behavior to know: a fresh host's first real bootstrap run now stops at the SSH step (after user and ufw) until the operator runs `passwd trading` in the root session and re-runs the same command.
