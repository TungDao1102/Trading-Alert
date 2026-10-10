---
phase: 16-paper-runtime-composition
plan: 50
subsystem: deploy / external heartbeat sender (D042 condition 1)
tags: [heartbeat, healthchecks-io, systemd, curl, deploy, secret-handling, fail-open, paper-01]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-14 (RUNBOOK 19.3 acceptance conditions, O-12 record); plan 16-20 (EC2 host acceptance, user waivers incl. HEARTBEAT_MONITOR_ALERT_RECEIVED)"
provides:
  - "deploy/heartbeat.sh: run mode (read-only collector probe, then one success ping only while it passes), --fail-ping, --set-url, --install-timer --interval-seconds N, --url-file, --dry-run; exit codes 0..4"
  - "deploy/systemd/trading-heartbeat.service and .timer: oneshot unit with LoadCredential, monotonic timer, no catch-up, no link to the collector"
  - "tests/test_deploy_heartbeat.py (offline: stub docker/curl/systemctl, one real-curl loopback run)"
  - "scripts/soak_host_acceptance.py: exit 2 on a ping-URL-shaped value (UUID-path URL or hosted ping domain)"
  - "RUNBOOK 11.9 and corrected 11.4, 13.5, 17, 19.3, 19.4; SOURCES rows; O-12 record line heartbeat_service: healthchecks.io"
  - "DEPLOY_GUIDE.vi.md cards and quick-reference rows for the three new deploy files"
affects: [16-43 (waits for the operator verification of HEARTBEAT_MONITOR_ALERT_RECEIVED), Phase 24 (paper and live process probes)]

requirements-completed: [PAPER-01]

status: complete
actuals:
  tokens: 20800
  tasks: 4
  commits: 9
plan_head_before: b97fd93e89714ce53460c55c0d893322c1291433
plan_head_after: 1b7f7e336aadd0bb06721331e7822458e07e5237
commits: 9

tech-stack:
  added: []
  patterns:
    - "Secret ping URL reaches curl only as a configuration read from standard input (printf builtin, no argv), from a root-only file or a systemd credential; curl stderr discarded, only 'curl exit N' logged"
    - "Fail-open sender: the only docker subcommand is exec of the read-only probe, proven by a static check with a negative control"
    - "No default monitor values: --install-timer refuses without --interval-seconds; the single code default is a transport bound labelled PLACEHOLDER"

key-files:
  created:
    - deploy/heartbeat.sh
    - deploy/systemd/trading-heartbeat.service
    - deploy/systemd/trading-heartbeat.timer
    - tests/test_deploy_heartbeat.py
  modified:
    - scripts/soak_host_acceptance.py
    - tests/test_deploy_docs.py
    - tests/test_soak_runbook.py
    - docs/operations/RUNBOOK.md
    - docs/operations/DEPLOY_GUIDE.vi.md
    - docs/SOURCES.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-O-12.md

key-decisions:
  - "Ping URL source order: systemd credential heartbeat-url, then --url-file, then HEARTBEAT_URL_FILE, then /etc/trading/heartbeat.url; a non-credential file readable by group or others is refused (exit 4)"
  - "Success ping by default; a fail ping is opt-in (--fail-ping / HEARTBEAT_FAIL_PING=1) because it bypasses the monitor's grace, which is the user's value"
  - "Timer pairs OnBootSec and OnUnitActiveSec with the operator interval and sets no Persistent and no randomized delay, so no catch-up ping masks an outage; AccuracySec=1s is labelled STRUCTURAL"
  - "The validator's second ping-URL pattern names the hosted ping domain from the plan author's knowledge (not read from the docs page); recorded as such in SOURCES and in the code comment"

patterns-established:
  - "Per-step transport bound HEARTBEAT_STEP_TIMEOUT_SECONDS (code default copied from the collector probe timeout in docker-compose.yml, provenance PLACEHOLDER, never tuned)"

coverage:
  - deliverable: "heartbeat.sh run mode: probe then one ping only while the probe passes; fail ping opt-in; exit codes 0..4"
    verification:
      - {kind: pytest, ref: "tests/test_deploy_heartbeat.py", status: pass}
    human_judgment: false
  - deliverable: "ping URL never in argv, environment, logs, units, docs or acceptance.json"
    verification:
      - {kind: pytest, ref: "tests/test_deploy_heartbeat.py (assert_no_secret in every scenario)", status: pass}
      - {kind: pytest, ref: "tests/test_soak_runbook.py::test_a_ping_url_shaped_value_exits_2_naming_the_condition_and_field_only", status: pass}
    human_judgment: false
  - deliverable: "fail-open: only docker exec of the read-only probe; units with no link to the collector"
    verification:
      - {kind: pytest, ref: "tests/test_deploy_heartbeat.py::test_every_compose_expansion_in_the_script_is_an_exec", status: pass}
      - {kind: pytest, ref: "tests/test_deploy_heartbeat.py::test_the_service_is_a_oneshot_with_no_link_to_the_collector", status: pass}
    human_judgment: false
  - deliverable: "--set-url, --install-timer with operator interval and no default, no catch-up"
    verification:
      - {kind: pytest, ref: "tests/test_deploy_heartbeat.py", status: pass}
    human_judgment: false
  - deliverable: "RUNBOOK 11.9 and corrected sections, SOURCES rows, O-12 record, operator guide cards"
    verification:
      - {kind: pytest, ref: "tests/test_deploy_docs.py tests/test_soak_runbook.py tests/test_deploy_guide_vi.py", status: pass}
    human_judgment: false
  - deliverable: "real delivery to healthchecks.io, systemd credential delivery to the trading user, timer firing, monitor alert and recovery notice"
    verification: []
    human_judgment: true
    rationale: "Real-host and real-monitor behaviour; the operator verification of plan 16-50 (not an executor step) and the waived acceptance row HEARTBEAT_MONITOR_ALERT_RECEIVED"

duration: ~25 min
completed: 2026-10-10
---

# Phase 16 Plan 50: Off-host heartbeat sender Summary

**`deploy/heartbeat.sh` probes the collector (read-only `exec`) and sends one healthchecks.io success ping only while the probe passes, with the ping URL kept in a root-only file and handed to curl on standard input, plus a oneshot unit and a no-catch-up timer whose interval is the operator's `--interval-seconds` (no default).**

## Performance

- **Duration:** about 25 min (2026-10-10T09:12Z to 09:37Z)
- **Tasks:** 4 of 4 (Task 1 tracer, Tasks 2 to 4 auto, all `tdd="true"`, RED commit then GREEN commit each)
- **Files:** 4 created, 7 modified
- **Commits:** 9 measured (`plan_head_before..plan_head_after`); this SUMMARY commit is the tenth and also carries the guide label flip

## Accomplishments

- **Sender (Task 1, tracer).** One run executes `docker compose exec -T collector /app/.venv/bin/python -m src.data.collector --healthcheck` inside `timeout`, then one success ping through `curl --config -` (URL on standard input, `--proto =https`, `--proto-redir =https`, `--fail`, `--max-time`). Probe failure sends nothing (or one `/fail` ping with `--fail-ping`); exit codes 0 ok, 1 probe failed, 2 usage, 3 ping not delivered, 4 URL source missing or invalid. The real curl option set was exercised against a closed loopback port and reports `curl exit 7`. The tracer gate was the same `<verify>` re-run end to end (auto mode): passed, expansion continued.
- **Secret and timer (Task 2).** `--set-url` stores one silent stdin line at mode 0600 through `write_if_changed`; `--install-timer --interval-seconds N` writes `trading-heartbeat.service` (oneshot, `User=trading`, `LoadCredential`, `HEARTBEAT_FAIL_PING`) and `trading-heartbeat.timer` (`OnBootSec` and `OnUnitActiveSec` = N, no `Persistent`, no randomized delay), reloads only on change, enables, and restarts the timer on change.
- **Docs (Task 3).** RUNBOOK 11.9 (new) and corrected 11.4, 13.5, 17 (row 11.9), 19.3 (row `HEARTBEAT_MONITOR_ALERT_RECEIVED` and the "Heartbeat monitor." paragraph) and 19.4 item 5; SOURCES section "Facts read for plan 16-50 (2026-10-09)" with the not-verified-live label and the UNVERIFIED sub-points; the O-12 record gains `heartbeat_service: healthchecks.io` (user decision 2026-10-09) with interval and grace left open. No interval, grace or period number is written anywhere.
- **Consumers (Task 4).** The acceptance validator exits 2, naming only condition and field, on a UUID-path URL or a URL on the hosted ping domain; an AWS ARN with `key/<uuid>` and the Binance ping URL still pass. The Vietnamese guide has cards for the script and both units and a section 14 table; in this commit its not-built labels for the sender are flipped (see Deviations).

## Task Commits

| Task | Commit | What |
| --- | --- | --- |
| 1 RED | 00445dd | test(16-50): RED for the heartbeat sender tracer |
| 1 GREEN | caeb436 | feat(16-50): heartbeat.sh probes the collector and pings the monitor while it passes |
| 2 RED | fa4ed27 | test(16-50): RED for --set-url, --install-timer and the unit templates |
| 2 GREEN | 41e093c | feat(16-50): --set-url, --install-timer and the heartbeat unit templates |
| 3 RED | 885367d | test(16-50): RED for RUNBOOK 11.9 and the other docs |
| 3 GREEN | ba5bb7e | docs(16-50): RUNBOOK 11.9, corrected sections, SOURCES rows, O-12 service record |
| 4 RED | 8190447 | test(16-50): RED for the acceptance validator ping-URL guard |
| 4 GREEN (validator) | a403b7e | feat(16-50): acceptance validator exits 2 on a ping-URL-shaped value |
| 4 GREEN (guide) | 1b7f7e3 | docs(16-50): Vietnamese guide cards and quick-reference rows |

## Verification (plan level, re-run at SUMMARY time)

- `TRADING_CI_STRICT=1 .venv/Scripts/python -m pytest tests/test_deploy_heartbeat.py -q -p no:cacheprovider`: pass. Four POSIX-mode cases (group/other-readable URL file) are skipped on this Windows machine, which the plan allows; the tracer test and the real-curl test ran.
- `tests/test_deploy_scripts.py tests/test_deploy_docs.py tests/test_soak_runbook.py tests/test_deploy_guide_vi.py`: pass.
- `ruff check` and `ruff format --check` on the new test file, the validator and the two edited test files: pass; `mypy scripts/soak_host_acceptance.py`: pass.
- `shellcheck -x -P SCRIPTDIR deploy/heartbeat.sh` is installed on this machine and exited 0; `tests/test_deploy_scripts.py` runs it as a test and it passed here as well (not only in CI).
- Index mode of `deploy/heartbeat.sh` is 100755; the three new deploy files have no carriage returns.
- O-12 record greps: `^option: postpone$` and `^heartbeat_service: healthchecks.io$` both match.

## Deviations from Plan

**1. [Rule 1 - Bug] Guide sentences that became false when the sender was built**
- **Found during:** Task 4 (label flip in the SUMMARY commit)
- **Issue:** the plan allows only a label flip, but sentences such as "chưa có code, chưa có lệnh, chưa có SUMMARY" (step 8.3), "Chưa làm được hôm nay vì bộ gửi tín hiệu chưa xây", the "Chưa xây" quick-reference row and the "Cách tạm thời" paragraph would have stayed false once the SUMMARY exists.
- **Fix:** rewrote only those sentences (25 scoped replacements: sections 1, 2, 3.8, 4, 6, 7.3, 8.3, 11, 13, 14, 15), keeping every item the guide test pins for step 8.3. Statements stay truthful: the sender is built and tested against stubs, not installed, not run on a host (`[CHƯA XÁC MINH]`).
- **Files:** `docs/operations/DEPLOY_GUIDE.vi.md`. **Commit:** the SUMMARY commit.

**2. [Rule 2 - Missing critical] Hosted ping domain in the validator comes from the author's knowledge**
- **Found during:** Task 4
- **Issue:** the plan names "the monitor's ping domain" but the fetched page facts do not state it.
- **Fix:** the pattern is kept (defensive only) and the origin is stated in the code comment and in the SOURCES row; the UUID-path pattern is the primary guard and catches self-hosted UUID URLs.
- **Files:** `scripts/soak_host_acceptance.py`, `docs/SOURCES.md`. **Commit:** a403b7e.

**3. [Rule 3 - Blocking] Test rig sends stdin as bytes**
- **Found during:** Task 2
- **Issue:** `subprocess` text mode on Windows turns the newline of the piped URL into CRLF, which the URL validation (correctly) refuses.
- **Fix:** the rig passes bytes in and decodes bytes out.
- **Files:** `tests/test_deploy_heartbeat.py`. **Commit:** fa4ed27.

**Total deviations:** 3 auto-fixed (1 bug, 1 missing critical, 1 blocking). **Impact:** none on scope; no architectural change.

## Authentication Gates

None. No step needed the real ping URL; the executor never saw, wrote or printed one (every test uses a fake sentinel).

## Known Stubs

None. No hardcoded empty values, placeholders or TODOs in the new code. (`<N>` in the docs is a documented stand-in for the operator's interval, not a stub.)

## Threat Flags

None beyond the plan's threat model. The new network egress (one https request to the monitor) is the planned T-16-115 to T-16-119 surface and is mitigated as listed there.

## Operator verification still open (not an executor step)

Plan 16-50 ends here; these need the user, the real URL and the EC2 host, and were not performed:

1. Create the healthchecks.io check, record the interval and the grace in `decisions/16-DEC-O-12.md` (the executor wrote no number).
2. On the host: `sudo deploy/heartbeat.sh --set-url`, `sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>` (dry run first), `sudo systemctl start trading-heartbeat.service`, confirm exit 0 and one ping, and that `journalctl -u trading-heartbeat` has no URL. This settles the UNVERIFIED systemd credential sub-points in `docs/SOURCES.md`.
3. Repeat RUNBOOK 19.3 `HEARTBEAT_MONITOR_ALERT_RECEIVED` with this sender (stop the collector, wait longer than period plus grace, confirm alert and recovery notice, record both UTC times without the URL) and record it in `evidence/16-50-operator-verification.md`.

**`HEARTBEAT_MONITOR_ALERT_RECEIVED` was waived in plan 16-20 (decisions/16-DEC-O-12.md, evidence/16-20-*) and must be verified after this plan and before 16-43.** That waiver is still open.

## Self-Check: PASSED

- Created files exist: `deploy/heartbeat.sh`, `deploy/systemd/trading-heartbeat.service`, `deploy/systemd/trading-heartbeat.timer`, `tests/test_deploy_heartbeat.py` (checked with `[ -f ]`).
- Commits exist: 00445dd, caeb436, fa4ed27, 41e093c, 885367d, ba5bb7e, 8190447, a403b7e, 1b7f7e3.
- Acceptance criteria of all four tasks re-run green (see Verification). STATE.md and ROADMAP.md were not touched.
