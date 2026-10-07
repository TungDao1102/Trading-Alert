---
phase: quick-261007-mkw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/bootstrap.sh
  - tests/test_bootstrap.py
  - tests/test_deploy_docs.py
  - docs/operations/RUNBOOK.md
  - docs/DOC_STATUS.md
  - .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md
autonomous: true
requirements:
  - QUICK-261007-mkw

estimate:
  tokens: 90000
  raw_tokens: 90000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "A real (non dry-run) bootstrap run installs the sudo package only when dpkg reports it missing, and only afterwards runs usermod -aG sudo for the trading user (stub log shows the package install before the usermod, and usermod -aG sudo is skipped when id -nG already lists sudo)"
    - "The SSH drop-in is never written, and sshd -t and the ssh reload are never reached, unless the trading user is in the sudo group AND passwd -S for that user reports status P; status L, status NP, unreadable output and a missing group each end in a non-zero exit whose stderr starts the guard message with 'lock-out guard'"
    - "The guard runs on every real run, including a re-run on an already configured host, and never prints, reads or sets a password: the only passwd call in any run is 'passwd -S USER' (a test asserts this)"
    - "deploy/bootstrap.sh --dry-run prints '+ usermod -aG sudo trading' in the ordered plan and a 'lock-out guard' line that only states what would be checked, makes no passwd call, changes nothing, and adds no '+ ' line to a second dry run on a configured host"
    - "The SSH drop-in still has exactly the four directives PasswordAuthentication no, KbdInteractiveAuthentication no, PermitRootLogin no, PubkeyAuthentication yes; the sshd_effective_gaps expectations and the OS matrix are unchanged"
    - "The sudo-with-password decision is implemented without any passwordless sudo rule: the all-caps sudoers tag named in the SPEC and D062 appears nowhere under deploy/ and nowhere in docs/operations/RUNBOOK.md (a test scans both)"
    - "The final operator checklist (item 6) and RUNBOOK 13.1, 13.4 and 13.5 describe the new flow: passwd trading in the root session, sudo -v in a SECOND SSH session before the root session is closed, then sudo for the backup timer and later apt, ufw or systemctl changes; the sentences 'trading has no sudo' and 'install the timer as root from the provider console' are gone from the script output and the RUNBOOK"
    - "13.1-OPEN-DECISIONS.md marks WR-05 implemented in the status column and in the WR-05 section; docs/DOC_STATUS.md gains one dated line; CRLF files stay CRLF; ROADMAP.md, DECISIONS.md, .planning/config.json, .planning/state.json and .gsd/ are not modified or staged"
  artifacts:
    - path: "deploy/bootstrap.sh"
      provides: "sudo package install, trading user in the sudo group, sudo lock-out guard (group + passwd -S status P), new checklist item 6"
      contains: "usermod -aG sudo"
    - path: "tests/test_bootstrap.py"
      provides: "stateful user stubs, passwd stub, guard fail-closed tests, dry-run tests, checklist tests, PermitRootLogin pin"
      contains: "STUB_PASSWD_STATUS"
    - path: "tests/test_deploy_docs.py"
      provides: "RUNBOOK sudo-flow tests and the no-passwordless-sudo scan over deploy/ and the RUNBOOK"
      contains: "passwd trading"
    - path: "docs/operations/RUNBOOK.md"
      provides: "13.1, 13.4, 13.5 and section 17 notes for sudo with a password"
      contains: "sudo -v"
    - path: ".planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md"
      provides: "WR-05 marked implemented (status column and section)"
      contains: "implemented"
    - path: "docs/DOC_STATUS.md"
      provides: "one dated line recording the WR-05 documents and script change"
      contains: "D062"
  key_links:
    - from: "deploy/bootstrap.sh step_user"
      to: "deploy/bootstrap.sh step_base_packages"
      via: "sudo package is installed (apt_install_missing) before usermod -aG sudo needs the sudo group"
      pattern: "usermod -aG sudo"
    - from: "deploy/bootstrap.sh step_sshd"
      to: "deploy/bootstrap.sh sudo_lockout_guard"
      via: "guard call sits after the authorized_keys guard and before write_if_changed of the drop-in"
      pattern: "sudo_lockout_guard"
    - from: "tests/test_bootstrap.py STUBS"
      to: "deploy/bootstrap.sh preflight and sudo_lockout_guard"
      via: "passwd stub answers 'passwd -S USER' from STUB_PASSWD_STATUS; useradd and usermod stubs record state read by getent and id -nG"
      pattern: "STUB_STATE"
    - from: "deploy/bootstrap.sh print_checklist item 6"
      to: "docs/operations/RUNBOOK.md 13.5 item 6"
      via: "same flow and same key phrases (passwd trading, sudo -v, sudo /opt/trading/deploy/backup.sh --install-timer)"
      pattern: "sudo -v"
---

<!-- planner-discipline-allow: NOPASSWD -->

<objective>
Implement WR-05 as decided in D062 (docs/DECISIONS.md, user decision of 2026-10-07): after SSH hardening
(`PermitRootLogin no`) the `trading` user joins the `sudo` group and uses a password; there is NO passwordless
sudo rule (a rule that skips the password for a script the trading user can edit would be unrestricted root).

Purpose: `deploy/bootstrap.sh` currently leaves nobody able to run root commands over SSH once root login is off;
the EC2 host of D061 is created only after this is implemented and tested (ROADMAP Phase 16 item D062).
Output: `deploy/bootstrap.sh` (sudo package, group membership, fail-closed lock-out guard, new checklist item 6),
updated and new tests in `tests/test_bootstrap.py` and `tests/test_deploy_docs.py`, RUNBOOK 13.1/13.4/13.5/17,
WR-05 marked implemented in `13.1-OPEN-DECISIONS.md`, one dated line in `docs/DOC_STATUS.md`, one commit.

Execution rules (from the user, binding):
- No push. Never read `.env`. Do not touch or stage `.planning/config.json`, `.planning/state.json`, `.gsd/`,
  `.planning/ROADMAP.md` or `docs/DECISIONS.md`. Do not stage anything under `.planning/quick/` (the quick workflow
  commits its own artifacts).
- Run pytest file by file with `PYTHONPATH=.` (Windows crashes otherwise), for example
  `PYTHONPATH=. uv run pytest tests/test_bootstrap.py -q`. Bootstrap tests run real bash (Git Bash) with stub
  binaries, so they can run here; a test that needs Docker or a real Linux host cannot, and the report must name each
  one that was skipped or could not run.
- Network is flaky: for any Binance, Telegram or internet call retry at most once, then report instead of retrying.
- Before Grep or Read of Python code, prefer `codegraph explore "<symbol or question>"` via Bash (the repo has
  `.codegraph/`); the shell scripts and markdown are small enough to read directly.
- The guard stays fail-closed and no non-interactive way to set a password may be invented: the operator runs
  `passwd trading` in the root session; the script never sets, reads or prints a password.
- CRLF files in the working copy (`tests/test_bootstrap.py`, `tests/test_deploy_docs.py`,
  `docs/operations/RUNBOOK.md`, `docs/DOC_STATUS.md`, `13.1-OPEN-DECISIONS.md`) must stay pure CRLF. The Edit tool
  can leave mixed endings on multi-line replacements, so edit them with a short Python script kept in the scratchpad
  directory: open with `newline=""`, normalise to LF in memory, apply `str.replace` edits asserting each old string
  occurs exactly once, and write back with `newline="\r\n"`. `deploy/bootstrap.sh` is LF (gitattributes) and may be
  edited with Edit.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/STATE.md
@.planning/quick/261007-mkw-wr-05-d062-trading-user-joins-sudo-with-/261007-mkw-SPEC.md
@deploy/bootstrap.sh
@deploy/lib.sh
@tests/test_bootstrap.py

Source audit (every item of the SPEC, D062, D061 HOSTS and the research facts is covered):

| Source | ID | Item | Task | Status |
|--------|----|------|------|--------|
| GOAL | - | trading user joins sudo with a password, no passwordless rule, guard fail-closed | 1, 2, 3 | COVERED |
| REQ (SPEC) | 1 | usermod -aG sudo in step_user, sudo package verified and installed if missing, SSH settings unchanged | 1 | COVERED |
| REQ (SPEC) | 2 | lock-out guard: sudo group AND passwd -S status P, die with clear message, dry-run only prints | 1 (code), 2 (tests) | COVERED |
| REQ (SPEC) | 3 | checklist item 6 rewritten, RUNBOOK 13.5 and every other "no sudo" or "console" sentence | 2 (script), 3 (RUNBOOK) | COVERED |
| REQ (SPEC) | 4 | OPEN-DECISIONS WR-05 implemented (CRLF), one DOC_STATUS line (CRLF), no ROADMAP edit | 3 | COVERED |
| REQ (SPEC) | 5 | test updates and new tests (membership step, guard refusals, no passwordless tag, PermitRootLogin unchanged) | 1, 2, 3 | COVERED |
| REQ (SPEC) | Acceptance | dry-run output, fail-closed tests, ruff/format/mypy, shellcheck status, one commit with trailer | 2, 3 | COVERED |
| CONTEXT | D062(1) | WR-05 option 1, sudo with a password, no passwordless rule, key is effectively a root key (RUNBOOK says so) | 1, 3 | COVERED |
| CONTEXT | D061 HOSTS | EC2 host created only after WR-05 implemented and tested | n/a (this plan is the prerequisite) | COVERED |
| RESEARCH | sudo package | sudo is in main on Debian 12 (1.9.13p3-1+deb12u4), Ubuntu 22.04 (1.9.9-1ubuntu2.6), Ubuntu 24.04 (1.9.15p5-3ubuntu5.24.04.3); sources https://packages.debian.org/bookworm/sudo, https://packages.ubuntu.com/jammy/sudo, https://packages.ubuntu.com/noble/sudo, read 2026-10-07, not verified live on a host; Debian minimal images may lack it, so it is installed when dpkg reports it missing and it must precede the group step | 1 | COVERED |
| Deferred | CR-01 (`--checksum`), WR-06 (env_file split) | not part of this task | none | EXCLUDED (D062 owner is Phase 16 for CR-01; WR-06 stays open) |
</context>

<tasks>

<task type="tracer">
  <name>Task 1: Tracer - trading user joins sudo; SSH drop-in blocked until group and usable password exist (script plus stubbed real-bash test)</name>
  <files>deploy/bootstrap.sh, tests/test_bootstrap.py</files>
  <read_first>
    - .planning/quick/261007-mkw-wr-05-d062-trading-user-joins-sudo-with-/261007-mkw-SPEC.md (authoritative)
    - docs/DECISIONS.md row D062 (single physical line starting with "| D062 |")
    - deploy/bootstrap.sh (step_base_packages, step_user, step_sshd, preflight command list, sshd_dropin_content)
    - deploy/lib.sh (run, die, pkg_installed, write_if_changed)
    - tests/test_bootstrap.py (STUBS, Host.run, golden fixture, CONFIGURED_ENV, is_mutation, test_user_step_*)
  </read_first>
  <action>
    One path end to end per D062: fresh host, real run, user created, sudo installed, user in sudo group, guard passes, drop-in written. Write the harness change and the new golden test first and watch the new test fail, then change the script.

    PART A - harness in tests/test_bootstrap.py (CRLF file, scripted edit):
    1. Pass a new env var STUB_STATE from Host.run, a directory under the host base (base / "state"), next to STUB_LOG. It lives outside the `root` tree so tree() comparisons and the "dry run changes nothing" test are unaffected. Create that directory in build_host (next to `bin` and `root`) AND have every stub that writes under it run `mkdir -p "$STUB_STATE"` first, because the stubs have no `set -e` and a missing directory would silently lose the marker and make the user look absent (a refusal test could then pass for the wrong reason).
    2. Make the user stubs stateful, because a fresh-host run calls useradd and usermod and the guard then asks id -nG about the same user. The useradd stub creates a marker file `user_created` in STUB_STATE. The usermod stub, when called as `-aG GROUP USER`, appends GROUP to a `groups` file in STUB_STATE unless env STUB_USERMOD_NOOP is 1 (that switch simulates a membership change that did not take effect). The getent stub and the `id -nG` branch of the id stub treat the user as existing when STUB_USER_EXISTS is 1 OR the marker exists; `id -nG` prints STUB_GROUPS (default "trading") followed by every group recorded in the groups file, space separated. Keep the existing `_LOG` prefix so every call is still logged first, and read STUB_STATE with a default so a stub called without it never errors.
    3. Add a `passwd` stub: for `-S USER` print one line in the real format (user name, then the status taken from STUB_PASSWD_STATUS with default P, then a date and the numeric aging fields); when STUB_PASSWD_STATUS is UNREADABLE print nothing and exit 1. Any other invocation of the passwd stub must exit 2, so a script that ever tried to SET a password fails the test.
    4. Add the prefix "passwd -S" to the probe prefixes used by is_mutation (it only reads state).
    5. CONFIGURED_ENV: STUB_GROUPS becomes "trading docker sudo" so a configured host already has the membership.
    6. Add test_user_step_adds_the_trading_user_to_the_sudo_group on the shared `golden` fixture: the first-run log contains `usermod -aG sudo trading`; the line `apt-get install -y ca-certificates curl git ufw sudo` appears BEFORE it (package before group); it appears before the `sshd -t` call; and the drop-in file exists (the guard passed with the default status P).
    Run the new test now: it must fail because the script does not yet add the group.

    PART B - deploy/bootstrap.sh (LF; keep it shellcheck-clean because CI runs `shellcheck -x -P SCRIPTDIR deploy/*.sh` and shellcheck is not installed locally: quote every expansion, declare locals on their own line before a command substitution assigns them, no unused variables, no backticks or command substitution inside the unquoted checklist heredoc):
    1. step_base_packages: add `sudo` to the apt_install_missing list so it is installed only when dpkg reports it missing. This is the "verify and install if missing" requirement: do not assume the image ships sudo (research, read 2026-10-07: sudo is in main on Debian 12, Ubuntu 22.04 and 24.04; Debian minimal images may lack it and the package creates the sudo group). base packages already run before step_user, so the group exists when usermod needs it.
    2. Add helper user_in_group GROUP: reads `id -nG` for the trading user with errors tolerated, pads the result with spaces and tests membership with a bash pattern match. No pipe, so pipefail and SIGPIPE cannot turn a match into a miss. Refactor the existing docker membership check in step_user to use it.
    3. step_user, right after the docker membership block: when the user is not in the sudo group run `usermod -aG sudo "$TRADING_USER"` through run (it prints "+ usermod -aG sudo trading" and is skipped in dry-run). Comment cites D062 and says why: after root SSH login is disabled this account is the administrator and sudo asks for its password.
    4. Add helper passwd_status: runs `passwd -S` for the trading user with errors tolerated and prints the second field of the first line (empty when unreadable).
    5. Add sudo_lockout_guard. In dry-run it only prints one stdout line, not starting with "+ ", that contains EXACTLY the phrase "lock-out guard would require" (Task 2 pins that same string as the dry-run marker), then the user name, the words "sudo group" and "passwd -S", and tells the operator the password is set with passwd USER; it calls nothing. All of these phrases must sit on one physical line of the output. In a real run it dies unless the user is in the sudo group (message contains "lock-out guard", the user and "not in the sudo group") and dies unless passwd_status is exactly P (message contains "lock-out guard", the user, the status found or "unreadable", "passwd USER" as the command to run in this root session, and an instruction to run the same bootstrap command again afterwards). The message prints the one-letter status only, never anything else from passwd.
    6. step_sshd: call sudo_lockout_guard immediately after the existing authorized_keys guard block and before write_if_changed of the drop-in, so it runs on every real run (a re-run on a host whose account was later locked fails closed). Do not touch sshd_dropin_content, SSHD_DROPIN_REL, sshd_effective_gaps, the usage text (lines 2-12 feed `usage`), the flags or the OS list.
    7. preflight: add `passwd` to the required command list.
    8. Comment text in deploy/ must describe a passwordless sudo rule in words only; never write the all-caps sudoers keyword (a test in Task 3 scans deploy/ for it and the keyword is spelled in the SPEC and D062).
  </action>
  <behavior>
    - Fresh host, real run: `apt-get install -y ca-certificates curl git ufw sudo` precedes `usermod -aG sudo trading`, which precedes `sshd -t`; the drop-in is written.
    - Configured host (CONFIGURED_ENV): no useradd, no usermod, no apt install of sudo, guard passes, run exits 0.
    - bash -n deploy/bootstrap.sh passes.
  </behavior>
  <verify>
    <automated>bash -n deploy/bootstrap.sh && PYTHONPATH=. uv run pytest tests/test_bootstrap.py -x -q -k "sudo or user_step or ufw_runs or ssh_drop_in or second_run or lockout"</automated>
  </verify>
  <done>A real fresh-host run through real bash with stubs installs sudo when missing, adds trading to the sudo group, passes the new guard and writes the unchanged drop-in; the existing user, ufw, drop-in, second-run and lock-out tests still pass with the stateful stubs.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Guard fails closed (group, status L, NP, unreadable), dry-run output, never sets a password, checklist item 6</name>
  <files>deploy/bootstrap.sh, tests/test_bootstrap.py</files>
  <read_first>
    - deploy/bootstrap.sh (print_checklist, sudo_lockout_guard from Task 1)
    - tests/test_bootstrap.py (CHECKLIST_NEEDLES, assert_checklist_last, test_dry_run_prints_the_ordered_plan_and_ends_with_the_checklist, real_run, has_call, first_index)
  </read_first>
  <behavior>
    - Guard refusal on password: with STUB_PASSWD_STATUS in L, NP and UNREADABLE (parametrized), a real run on a fresh host exits non-zero, stderr contains "lock-out guard" and "passwd trading", the drop-in does not exist, and the log has no `sshd -t` and no `systemctl try-reload-or-restart`.
    - Guard refusal on group: with STUB_USERMOD_NOOP=1 and status P, exit non-zero, stderr contains "lock-out guard" and "sudo group", no drop-in.
    - Re-run fail-closed: CONFIGURED_ENV plus STUB_PASSWD_STATUS=L exits non-zero and writes no drop-in.
    - Documented flow: a first run with status NP stops at the guard after the user step (log has `usermod -aG sudo trading`, no drop-in); a second run on the same host with status P exits 0, writes the drop-in and does not call useradd again.
    - Dry run with STUB_PASSWD_STATUS=L exits 0, stdout contains "+ usermod -aG sudo trading" and "lock-out guard", the log has no passwd call, and the host tree is unchanged.
    - Password never set: in every run of the golden and flow tests, every logged line that starts with "passwd" starts with "passwd -S".
    - Drop-in directives: the non-comment lines of the written drop-in equal exactly PasswordAuthentication no, KbdInteractiveAuthentication no, PermitRootLogin no, PubkeyAuthentication yes, in that order.
    - Checklist (real and dry run): contains "Root SSH login is now disabled", "passwd trading", "sudo -v", "sudo /opt/trading/deploy/backup.sh --install-timer", "no passwordless sudo rule"; does not contain "has no sudo" or "from the provider console".
  </behavior>
  <action>
    Write the tests above in tests/test_bootstrap.py (CRLF file, scripted edit) and watch them fail where they depend on the new checklist, then finish deploy/bootstrap.sh.

    Test edits:
    1. Update test_dry_run_prints_the_ordered_plan_and_ends_with_the_checklist: add the marker "+ usermod -aG sudo" after "+ usermod -aG docker", and the marker "lock-out guard would require" between "+ ufw --force enable" and "00-trading-hardening.conf".
    2. Update CHECKLIST_NEEDLES: keep every existing needle except "provider console" (item 5 still says provider console for disk encryption but that needle was the WR-05 pin; drop it); keep "Root SSH login is now disabled" and fix its comment to say it pins the new item 6 sentence; add the needles listed in the behavior block. In assert_checklist_last add the two negative assertions (no "has no sudo", no "from the provider console").
    3. Add the guard, flow, dry-run, password-never-set and drop-in tests from the behavior block, reusing real_run, host.run, has_call, first_index and the DROPIN_REL constant. Do not duplicate the golden run; use the `host` fixture for refusals. NEEDLES: every checklist needle is a single contiguous phrase; when writing the heredoc, wrap the lines so that none of the needles ("Root SSH login is now disabled", "passwd trading", "sudo -v", "sudo /opt/trading/deploy/backup.sh --install-timer", "no passwordless sudo rule") is split across a line break (check the actual output, not the source). PROVE THE REFUSAL TESTS ARE NOT VACUOUS: after they pass, temporarily comment out the single `sudo_lockout_guard` call in step_sshd, run the refusal tests (status L, NP, UNREADABLE, missing group, configured-host re-run, NP-then-P flow) and confirm each of them FAILS, then restore the call and confirm they pass again; state this in the SUMMARY. Name the tests so the `-k` expression in verify selects them: put "sudo_guard" in the refusal and flow test names, "dry_run" in the dry-run test, "password" in the never-set test and "permit_root_login" in the drop-in directive test.

    Script edit (print_checklist only): rewrite item 6 of the unquoted heredoc. Keep it a numbered item 6 of 8 and keep items 1-5, 7 and 8 untouched. The new text, in the same wrapped style: first the backups sentence as before (set the BACKUP_* variables in $INSTALL_DIR/.env as $TRADING_USER and run $INSTALL_DIR/deploy/backup.sh --init-remote as $TRADING_USER); then "Root SSH login is now disabled. $TRADING_USER is in the sudo group and sudo asks for its password; there is no passwordless sudo rule." then that the lock-out guard only let bootstrap continue because the password is usable and that it is set with `passwd $TRADING_USER` in the root session (write it without backticks: the heredoc is unquoted, so a backtick would execute); then "In a SECOND SSH session as $TRADING_USER with your key run sudo -v and see it succeed BEFORE you close this root session"; then "Afterwards use sudo for the backup timer (the install does not read .env):" followed by the indented command `sudo $INSTALL_DIR/deploy/backup.sh --install-timer`; then "Use sudo the same way for every later apt, ufw or systemctl change." Do not mention the provider console as the way to reach root. The comment above print_checklist, if any, must not contain the all-caps sudoers keyword either.
  </action>
  <verify>
    <automated>PYTHONPATH=. uv run pytest tests/test_bootstrap.py -x -q -k "sudo or guard or lockout or checklist or permit or drop_in or dry_run or password"</automated>
  </verify>
  <done>The guard is proven fail-closed for a missing group and for status L, NP and unreadable, on fresh and configured hosts; the dry run shows `usermod -aG sudo` and the guard and calls no passwd; the script never sets a password; the drop-in directives are pinned; the checklist carries the new flow and not the old wording.</done>
</task>

<task type="auto">
  <name>Task 3: RUNBOOK, WR-05 status, DOC_STATUS line, docs tests, full gates, single commit</name>
  <files>docs/operations/RUNBOOK.md, tests/test_deploy_docs.py, .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md, docs/DOC_STATUS.md</files>
  <read_first>
    - docs/operations/RUNBOOK.md sections 13.1 (item 3), 13.4 (order sentence, SSH bullets, "Keep your current root session open"), 13.5 (items 4 and 6) and the section 17 rows for 13.1, 13.4, 13.5
    - .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md (status table row WR-05, section "WR-05: who administers the host after hardening")
    - docs/DOC_STATUS.md (last bullet, D061)
    - tests/test_deploy_docs.py (helpers _read, _runbook, _section, test_section_13_states_bootstrap_prerequisites_and_firewall_facts, test_doc_status_logs_d050_and_sources_has_the_phase_facts)
    - deploy/bootstrap.sh print_checklist (the RUNBOOK 13.5 item 6 must use the same flow and phrases)
  </read_first>
  <action>
    All four files are CRLF: edit through a scratchpad Python script as described in the objective.

    RUNBOOK (per D062; never write the all-caps sudoers keyword, say "passwordless sudo rule"):
    1. 13.1 item 3: after the authorized-key lock-out guard sentence add that bootstrap also refuses to write the SSH drop-in unless the `trading` user is in the `sudo` group and `passwd -S trading` reports status `P` (a usable password), see 13.4.
    2. 13.4 order sentence: base packages become `ca-certificates`, `curl`, `git`, `ufw`, `sudo`; the user step becomes the `trading` user in the `docker` and `sudo` groups with its authorized keys; the SSH hardening step mentions the sudo guard.
    3. 13.4 add a bullet after the SSH hardening bullet: sudo with a password (D062). Content: root cannot log in over SSH after hardening, so `trading` is the administrator; bootstrap installs the `sudo` package when missing and runs `usermod -aG sudo trading`; there is no passwordless sudo rule anywhere, because a rule that skips the password for a script `trading` can edit would be unrestricted root; `useradd` creates the account without a password, so bootstrap refuses to write the drop-in (lock-out guard) until the account is in the `sudo` group and `passwd -S trading` reports `P`; on a fresh host the first run therefore stops at the SSH step, after the user and ufw steps, with a message naming the fix: set the password yourself in the root session with `passwd trading` (bootstrap never sets, reads or prints it) and run the same command again, which is idempotent; the SSH key of `trading` is now effectively a root key, so keep it key-only, protected and rotated like one (D042 condition 3).
    4. 13.4 "Keep your current root session open" bullet: the second SSH session as `trading` must also run `sudo -v` and see it succeed before the first session is closed.
    5. 13.5 item 4: add "and run `sudo -v` there". 13.5 item 6: replace the sentence that says root login is disabled and `trading` has no sudo, and the timer is installed as root from the provider console, and the sentence that later apt, ufw or systemctl changes need the provider console. New text: root SSH login is disabled; `trading` is in the `sudo` group and sudo asks for its password (no passwordless sudo rule); set the password with `passwd trading` in the root session (the lock-out guard requires it); run `sudo -v` in a SECOND SSH session as `trading` BEFORE closing the root session; then install the timer with `sudo /opt/trading/deploy/backup.sh --install-timer` (it does not read `.env`) and use `sudo` for every later apt, ufw or systemctl change. Keep the first half of the item (BACKUP_* variables and `--init-remote` run as `trading`, section 11).
    6. Section 17 table: append to the Notes of rows 13.1 and 13.4 that the sudo group, the password guard and the checklist text are tested with stub binaries, and to row 13.5 that the sudo password prompt and `sudo -v` in a second session are real-host checks. Keep every existing phrase (test_section_17_names_what_only_a_real_host_can_show pins several) and keep the labels inside the allowed set.
    7. Search the whole RUNBOOK once more for "no sudo", "provider console", "console" and "reach root" and fix any remaining sentence that says `trading` has no sudo or that root is reached through the console (the 13.5 item 6 hit is the only one found while planning; confirm).

    13.1-OPEN-DECISIONS.md: change the WR-05 status cell of the table to "implemented 2026-10-07 (D062): `trading` joins sudo with a password and no passwordless rule; bootstrap.sh step and guard, checklist, RUNBOOK 13.1, 13.4, 13.5; real-host check with UAT 8-10", keeping the "Decide before" cell. In the WR-05 section append one paragraph "Implemented 2026-10-07 (quick task 261007-mkw)" listing the script, tests and RUNBOOK changes, that the first run on a fresh host stops at the guard until `passwd trading` is run, and that a real-host check is still owed. Leave the older paragraphs (including "Done so far" and the options list) as written. CR-01, WR-06 and UAT rows stay as they are.

    docs/DOC_STATUS.md: append one dated bullet at the end of the list, in the style of the D061 bullet: "- 2026-10-07 — WR-05 implemented per D062: `deploy/bootstrap.sh` (sudo package, `trading` in the sudo group, lock-out guard requiring a usable password, checklist item 6), `operations/RUNBOOK.md` (13.1, 13.4, 13.5, 17) and `13.1-OPEN-DECISIONS.md` updated; no passwordless sudo rule exists; no parameter, protocol or strategy file changed." Do not mention the decision id D050 anywhere in the new line (a test takes the first line that mentions it).

    tests/test_deploy_docs.py (add near the section 13 tests, reuse _read, _runbook, _section; add a small helper that returns the text of one `### 13.x` subsection):
    - test that section 13 contains "passwd trading", "sudo -v", "sudo group" (write the plain words "sudo group" in the RUNBOOK at least once, not only the backticked form `sudo` group, which does not contain that string), "passwd -S", "passwordless sudo rule" and the sudo package name in the base packages sentence, and that the subsection 13.5 contains "sudo /opt/trading/deploy/backup.sh --install-timer";
    - test that the RUNBOOK no longer contains "has no sudo" or "from the provider console";
    - test that `PermitRootLogin no` is still in section 13 (the RUNBOOK still documents the four-line drop-in);
    - test that scans every file under deploy/ and the RUNBOOK and fails if the all-caps sudoers keyword (spelled in the SPEC and in D062) occurs in any of them, listing the offending paths. The literal may appear in the test file itself because tests/ is not scanned.
    Existing tests there must keep passing unchanged.

    GATES (run each command as its own call; use a 600000 ms timeout for the pytest calls; do not stash anything and do not touch config.json, state.json or .gsd):
    1. `PYTHONPATH=. uv run pytest tests/test_bootstrap.py -q` then `PYTHONPATH=. uv run pytest tests/test_deploy_docs.py -q` then `PYTHONPATH=. uv run pytest tests/test_deploy_scripts.py -q` (bash -n, LF-only and header checks run locally; its shellcheck test skips here unless TRADING_CI_STRICT is set). A failure in code this change did not touch (for example the refresh-pins tests) is reported with its name, not fixed.
    2. `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`. If ruff format wants changes in the two test files run `uv run ruff format tests/test_bootstrap.py tests/test_deploy_docs.py` and re-check that they are still pure CRLF.
    3. shellcheck: `command -v shellcheck` (CI runs `shellcheck -x -P SCRIPTDIR deploy/*.sh` in ci.yml). If absent, say so in the report; do not install it.
    4. Line endings: the CRLF checks in the verify block.

    COMMIT: stage exactly deploy/bootstrap.sh, tests/test_bootstrap.py, tests/test_deploy_docs.py, docs/operations/RUNBOOK.md, docs/DOC_STATUS.md and .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md with explicit paths (never `git add -A`). Check `git diff --cached --name-only` lists only those six files. Commit with subject `fix(deploy): trading user joins sudo with a password (D062 WR-05)`, a short body (sudo package and group, lock-out guard, checklist and RUNBOOK flow, no passwordless rule, tests), and the trailer line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do not push.
  </action>
  <verify>
    <automated>PYTHONPATH=. uv run pytest tests/test_deploy_docs.py -q && ! grep -q 'NOPASSWD' docs/operations/RUNBOOK.md deploy/bootstrap.sh deploy/lib.sh && ! grep -q $'\r' deploy/bootstrap.sh && ! grep -qv $'\r$' docs/operations/RUNBOOK.md && ! grep -qv $'\r$' docs/DOC_STATUS.md && ! grep -qv $'\r$' .planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md && ! grep -qv $'\r$' tests/test_bootstrap.py && ! grep -qv $'\r$' tests/test_deploy_docs.py && test "$(grep -c 'D062' docs/DOC_STATUS.md)" = 1 && uv run ruff check && uv run ruff format --check && uv run mypy src && git show --stat --name-only --format=%s HEAD</automated>
  </verify>
  <done>RUNBOOK 13.1/13.4/13.5/17 and the script checklist describe the same sudo-with-password flow; the old "no sudo" and "provider console" sentences are gone; WR-05 is marked implemented; one DOC_STATUS line exists; the docs tests pin the flow and the absence of any passwordless rule; all five CRLF files are still pure CRLF; test_bootstrap.py, test_deploy_docs.py and test_deploy_scripts.py pass file by file; ruff check, ruff format --check and mypy src are clean; shellcheck status is stated; one commit with the required subject and trailer contains only the six files and nothing was pushed.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| operator root session to bootstrap.sh | runs as root on a fresh internet-facing host; decides who can administer it afterwards |
| trading SSH key and password to root | after this change the trading account can become root through sudo (key plus password) |
| bootstrap.sh to passwd, useradd, usermod | privileged account and group changes; the password itself never crosses this boundary |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-261007-01 | Elevation of Privilege | trading user in the sudo group (its SSH key is effectively a root key) | high | accept | User decision D062 and D042 condition 3. Compensating controls: sudo needs the account password, SSH stays key-only (existing drop-in), RUNBOOK 13.4 states the key is a root key to be protected and rotated. |
| T-261007-02 | Elevation of Privilege | a passwordless sudo rule on a script the trading user can edit | critical | mitigate | No sudoers rule is written anywhere; membership of the stock sudo group is the only mechanism; a test scans deploy/ and the RUNBOOK for the all-caps sudoers keyword and fails on any hit. |
| T-261007-03 | Denial of Service (self lock-out) | SSH drop-in written while the account cannot use sudo or has no password | high | mitigate | sudo_lockout_guard in step_sshd, fail-closed: not in the sudo group, status L, NP or unreadable all die before write_if_changed; runs on every real run; tested for each case on fresh and configured hosts; dry run only prints. |
| T-261007-04 | Information Disclosure | password handling by the script | high | mitigate | The script never sets, reads or prints a password; it reads only the one-letter status from `passwd -S`; no non-interactive password mechanism exists; the passwd stub exits non-zero for anything but `-S` and a test asserts every logged passwd call is `-S`. |
| T-261007-05 | Tampering | group membership attempted before the sudo package (and group) exists | low | mitigate | sudo is added to step_base_packages, which runs before step_user; a test asserts the package install precedes `usermod -aG sudo`. |
| T-261007-06 | Elevation of Privilege | SSH hardening weakened by the edit (for example PermitRootLogin) | high | mitigate | sshd_dropin_content and sshd_effective_gaps are not touched; a test pins the four non-comment drop-in directives. |
| T-261007-SC | Tampering | apt install of the `sudo` package | low | accept | Distro package from the already trusted main archive of every supported release (Debian 12, Ubuntu 22.04, 24.04; sources in the audit table, read 2026-10-07); no npm, pip or cargo install, so the package-legitimacy checkpoint does not apply. |
</threat_model>

<verification>
- `bash -n deploy/bootstrap.sh`; `PYTHONPATH=. uv run pytest tests/test_bootstrap.py -q`, `tests/test_deploy_docs.py -q` and `tests/test_deploy_scripts.py -q`, each as its own run.
- `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` clean.
- shellcheck: only CI runs it (`shellcheck -x -P SCRIPTDIR deploy/*.sh`); report whether it was available locally.
- Dry-run acceptance is covered by tests: stdout shows `+ usermod -aG sudo trading` and the `lock-out guard` line.
- `git show --stat --name-only HEAD` lists exactly the six files; `git status --short` still shows `.planning/config.json` and `.planning/state.json` as unstaged modifications and `.gsd/` untracked, as before.
- Report back: files changed, test commands and results, anything surprising, anything not verifiable locally (real sudo prompt, real `passwd -S` output on Debian and Ubuntu, real ufw and sshd effects, shellcheck). Also tell the caller that docs/DECISIONS.md D062 still says the implementation is not done (it covers CR-01 as well, and DECISIONS.md was not in scope), and that on AWS Ubuntu images cloud-init may add its own passwordless rule for the default image user, which this change neither adds nor removes.
</verification>

<success_criteria>
- `trading` is in the `sudo` group after bootstrap, the `sudo` package is installed when missing, and no passwordless sudo rule exists in deploy/ or the RUNBOOK.
- The SSH drop-in is refused (fail-closed, tested) unless the account is in the sudo group and `passwd -S` reports P; the script never handles the password.
- Checklist and RUNBOOK 13.1/13.4/13.5 carry the flow passwd trading, sudo -v in a second SSH session before closing root, then sudo for the timer and later changes.
- WR-05 is marked implemented, one DOC_STATUS line exists, CRLF preserved, ROADMAP/DECISIONS/config/state/.gsd untouched.
- One commit `fix(deploy): trading user joins sudo with a password (D062 WR-05)` with the Claude trailer, not pushed.
</success_criteria>

<output>
Create `.planning/quick/261007-mkw-wr-05-d062-trading-user-joins-sudo-with-/261007-mkw-SUMMARY.md` when done
</output>
