# Phase 16 revision notes (2026-10-09)

Revision of plans 16-01..16-49 against the eight gaps found by `16-AUDIT-CONTEXT.md` and `16-AUDIT-RESEARCH.md` (checked with `16-PLAN-CHECK.md`, `16-CONTEXT.md` and the RESEARCH files). Plans were edited in place; no plan was renumbered, no plan was added (the reserved id 16-50 was not needed), nothing was committed. Plan numbers below are written as `NN`, task numbers as `Tn`.

## User decisions surfaced (nothing was decided for the user)

| Id | Where | What the user will be asked | Recommendation shown (not a selection) |
|----|-------|-----------------------------|----------------------------------------|
| Q-Q (new) | 30 T4, blocking-human | Cron minute of the hourly freeze check: `keep-top-of-hour` (`0 * * * *`) or `off-hour-minute` (`M * * * *`, M from 1 to 59, the user's number). Record: `decisions/16-DEC-Q-Q.md` with a `cron:` line. | off-hour-minute, because D065 item 4 and REV-18 name moving the cron off the top of the hour as the example mitigation; its effect is unproven (G15) and it creates no tolerance. Extra schedules (two runs per hour) are deliberately not offered: a second run could cover a slot for its neighbour, which REV-02 and REV-18 forbid. |
| O-01 (extended) | 30 T2 | Besides option a-e and the S3 lock mode and retention: who must read the evidence off-host, whether it goes through the backup `crypt` remote, and when it is written (daily snapshot, exporter schedule, event time). New record lines `reader_access:`, `through_crypt_remote:`, `write_timing:`. | CONTEXT's own recommendation (e) stays the only labelled one. |
| Q-F (context extended) | 30 T3 | Same question as before; the context now states that `read-from-durable-store` is incompatible with evidence stored through the crypt remote unless the passphrases (or a plaintext remote) go to GitHub. | none |

Why the cron line was not a locked requirement: L-01 fixes the cadence (hourly), not the minute; D065 item 4 explicitly allows the mitigation. Plans 09 and 47 had kept `0 * * * *` as a planner convenience. That text was reworded accordingly (09 objective).

## Gap 1: cron of the hourly freeze check (G15, REV-18)

- 30 T4 (new checkpoint, plan stays at 4 tasks): the Q-Q decision above, with an automated check that the recorded `cron:` line agrees with the option.
- 09 objective and T2 Test 5: the cron is asserted, not assumed: exactly one `- cron:` list entry equal to `EXPECTED_FREEZE_CRON` (defined once in `tests/test_paper_freeze_allowlist_mode.py`, today `0 * * * *`), hourly `M * * * *` form, negative control. Plan 09 still does not change the line.
- 47 T2 (Test 2, 3, 4, action) and frontmatter: sets the cron exactly as recorded at Q-Q (the only edit of that line in the phase), updates `EXPECTED_FREEZE_CRON`, asserts workflow cron equals the record, checks the slot grid, and requires RUNBOOK 20.7 to state the recorded cron and that a different minute is an unproven mitigation under which a missing tick is still an EVIDENCE_GAP. Added `tests/test_paper_freeze_allowlist_mode.py` to its files and `decisions/16-DEC-Q-Q.md` to its context.
- 15 T3 (Tests 7 and 8): `expected_slots(pin, end, cron)` follows the cron minute; a CLEAN line whose recorded schedule string differs from the evaluated cron is `SCHEDULE_MISMATCH`, so a cron edit during the trial is a gap, never tolerated.
- 43 T1 and T2: preflight asserts the cron on `origin/master` equals the Q-Q record (automated) and that the scheduled workflow is enabled (`gh workflow list --all`, research A7/G15, F10); instruction not to edit the cron between pin and trial end.

## Gap 2: unsolicited close in the smoke, and the 23 h SDK reconnect path

- 01 T3 (Tests 4, 6, 7, fakes, adapter): `FakeSdkWsClient.simulate_unsolicited_close()` mirrors the SDK discard path (streams stay in the global map) while the fake `close_connection()` mirrors the user-initiated path (streams forgotten); `rebuild()` records a `RebuildReport` (`adapter.last_rebuild.stale_stream_names_found`); read-only `diagnostics()` (connection count, stale stream names). This makes the two paths distinguishable in CI and in the live file.
- 17 T2 (Tests 3, 6-9): the forced disconnect drops the transport beneath the SDK (`_drop_transport`: closes the aiohttp response behind the SDK's websocket; `--disconnect-method transport-drop|ws-close`); it never uses `close_connection`/`_close_one`/`close_initiated`. Evidence `forced_disconnect` carries `method`, `path_exercised`, `stale_stream_entries_before_rebuild`; pure `check_forced_disconnect()` fails the wrong path (negative control); contract test pins the aiohttp attribute path. 23 h path: faked-clock test fires the SDK-style `reconnect` at exactly 82800 s (read from the installed SDK constant) and the supervisor reacts as in plan 08; live smoke can shorten `binance_common.websocket.AUTO_RECONNECT_INTERVAL_SECONDS` for the smoke process only (floor 300 s tool guard, restored in `finally`, never in `src/`, contract test pins the attribute). 17 T3: SOURCES rows state the SDK internals are source readings, not verified live.
- 21 truths, T1, T2 (command and manual fallback), T3 (checks and verify): live command now passes `--disconnect-method transport-drop --force-disconnect-after-seconds 900 --sdk-reconnect-interval-seconds 3600`; a file whose path is not unsolicited fails; `sdk_reconnect` is PASS or recorded UNPROVEN with the documented manual fallback (not a FAIL).
- 43 T3: the first in-trial export check must list `sdk rotation observed: <count>` (natural 23 h rotation, anomaly if 0 after 23 h; observation, not a criterion).

## Gap 3: Telegram failure handling

- 04 T2 (Tests 7-10, action) and truths: errors are classified once in the adapter (`TelegramFailureKind`, `TelegramSendError`, `classify_telegram_error`, `send_text`, `edit_text`); a 429 (`RetryAfter`, int or timedelta) is honoured inside the existing retry budget (never earlier, never past the budget, injectable sleep); budget exhaustion journals a failure and approves nothing.
- 11 new T4 (plan now 4 tasks, 7 files): edit failure after APPROVE gets one fallback `send_message` of the same card; if that fails too the confirm is journaled `SHADOW_CONFIRM_EXPIRED` with reason `CARD_DELIVERY_FAILED`, the token is invalidated and the approval is never left stranded (invariant `assert_no_stranded_approvals`, repair sweep in `expire_due` for a crash between APPROVED and card delivery); "message is not modified" on a replayed callback is success (no second token, no second event); 429 on the edit within the remaining confirm TTL; `answerCallbackQuery` is guarded (`answer_callback_safely`: called once without text, failure logged by class, never aborts the gates); PG replay test of the failure row.
- 31 T2 (Test 4): PTB application error handler logs by class only and can never approve, confirm, cancel or stop the runtime.
- 35 T1: `CARD_DELIVERY_FAILED` and `RUNTIME_RESTART` confirm expiries are attributed `opportunity` with that reason.
- 17 T3: SOURCES rows for 429 `retry_after`, the "not modified" text and answerCallbackQuery, with the UNVERIFIED sub-points (G7, G8).
- 14, 19 and 32 were read and own no Telegram send/edit/answer path (14 is the token-per-environment decision, 19 is the fill driver, 32 is compose), so they are unchanged for this gap.

## Gap 4: O-01 evidence-location options (S2 points 1 and 7)

- 30 T2: decision, context and the cons of options a, d and e now state that evidence written through the backup `crypt` remote is ciphertext and unreadable off-host (GitHub runner, auditor) without `BACKUP_CRYPT_PASSWORD(2)` (S2 #1) and that the daily snapshot leaves up to a 24 h loss window unless evidence is written at event time (S2 #7). The purge-versus-COMPLIANCE statement is labelled an inference (G10 vs G18). Plan 30 T3 states the Q-F interaction. Resume signal and record lines extended (see decisions table).
- 47 (executor rules, Task 2 Test 3 and 4): stops if the O-01 record says `through_crypt_remote: no` (a separate remote needs names and an access policy nobody decided) or `write_timing: event-time` (no runtime-side writer exists in Phase 16); RUNBOOK 20.7 states reader, crypt layer and loss window; compatibility test between the O-01 and Q-F records (negative control).
- 07 T3 Test 2 and 49 (context, T3 new "Reader read test" heading, instruction 3): RUNBOOK 19.6 lists both S2 points and labels the purge statement an inference; the destination record must now include a read-back test by the named reader.

## Gap 5: smoke and runtime measurements (A2, A10, A11, P20)

- 17 T1 (schema) and new T4: smoke evidence gains `connection_count` (A2/D5/G5, observation, private socket noted), `arrival_latency_ms_by_interval`, `clock_skew_ms` (start and end), `future_close_events`, and `rest_minute_lag` (A11/Q-M: first-seen delay after the minute close for 1m trade and mark klines, poll and max-wait settings are required CLI measurement settings with no default in code, weight header only if the SDK exposes it). All are observations; no limit is compared. 21 passes explicit measurement settings and writes OBSERVED lines; 27 T1 maps these fields into the observation column of the O-07 table.
- 08 T1 (Test 4): vocabulary adds `PAPER_TICK_STATS` and `DropReason.FUTURE_CLOSE`. 16 T1 (Test 5): deterministic id `paper:{epoch}:tick:{at_ms}:{batch_seq}`.
- 24 T1 (Test 5): a closed bar with close after the tick time is still not evaluated (rule unchanged) but is reported in `PipelineResult.dropped` with `FUTURE_CLOSE` and the delta, and is not recorded as processed.
- 26 T1 (Test 5, injected monotonic clock) and T3 (Test 4): one `PAPER_TICK_STATS` record per consumer batch (tick time, counts, dropped by reason, `duration_ms`, queue depth); duration feeds no decision. T3: the healthcheck also exits 1 where the start gate would refuse.
- 15 T4 (Test 4) and 25 T2 (Test 7): report-only `tick_timing_summary`, shown in an observations block of the evaluation that cannot change a PASS or FAIL. 43 T3 records it at the first export.

## Gap 6: SHADOW label and time zones (D-12, D-35, SC5)

- 04 T1 (Test 4), T2 (Test 7), truths, artifacts: one composer `render_shadow_message` (kinds ALERT, DECISION_RESULT with APPROVED/SKIPPED/REPLAYED/REJECTED_APPROVAL_EXPIRED/REJECTED_OTHER, SEND_FAILURE_NOTICE) adds the exact label, the mode and UTC plus Asia/Ho_Chi_Minh stamps (`format_time_pair`); `make_shadow_reply_fn` wraps even the adapter's own "Rejected" text; the fake bot asserts all of it on every call; a test enumerates the enum so a new kind needs a row.
- 11 T1 and T2 (Test 7), T4: confirm kinds (CONFIRM_CARD, CONFIRM_RESULT outcomes CONFIRMED/CANCELLED/EXPIRED_TTL/REJECTED_*, CARD_DELIVERY_FAILED); the card shows the plan expiry in UTC and Asia/Ho_Chi_Minh next to the remaining seconds. `src/paper/shadow.py` added to its files.
- 31 T1 (Test 4): whole-session check over every variant, plus an AST check that every `send_text`/`edit_text` argument comes from the composer.

## Gap 7: freeze_tick_grace_seconds and auxiliary evidence

- 15 truths, T2 (Test 5, `epoch_id` filter), T4 (new, plan now 4 tasks): one run is assigned to one slot; the grace only separates a late valid run from a missing one; a grace at or above the slot interval raises (one run could cover two slots); property-style test over several grace values proves a slot without a CLEAN schedule-run line is never satisfied; earlier-epoch lines, runs and records are returned untouched as `auxiliary`, reproducible with the old pin.
- 25 truths, T2 (Tests 6 and 7), action: judge one epoch; earlier-epoch evidence listed as "auxiliary evidence (not qualifying)", never counted, never edited; grace passes only to `freeze_evidence_report`.
- 22 T3 (Test 5, README text): `freeze_tick_grace_seconds` entry says it bounds only how late a valid run may start, never turns a missing tick into CLEAN and must be smaller than the slot interval. 27 (truths, T1 action and a grep check): the table row says the same. 34 T3 (Test 4): the user's grace must be smaller than the slot interval or the plan stops and reports (the executor never edits the number).
- 30 T1 (Test 5): per-epoch export keeps the earlier epoch's bundle complete next to the new one.

## Gap 8: restart loop on configuration refusals

- 22 truths, T1 (Tests 5 and 6, action), T3 (exit codes), threat T-16-110: named `ExitCode` table (0 OK, 2 usage, 3 trade-capable variable, 4 configuration not ratified, 5 no pinned epoch, 6 admission or epoch mismatch, 7 `FAIL_CLOSED_RUNTIME`); refusal codes {3, 4, 5, 6} are disjoint from the interpreter crash status 1 and from 7. The mismatch cases that used exit 1 (22 T3, 29 T2) now use 6. New opt-in `--hold-on-refusal`: a refused process logs, stays up (healthcheck unhealthy) and exits with the refusal code only when stopped; SKIPPED still exits 0 at once (D-01). `build_parser()` exposed.
- 32 truths, planner-choice paragraph, T1 (command with the flag, Test 4 static restart-loop guard with negative control): Compose has no per-exit-code exclusion, so the runtime holds; no restart cap was set because a cap would stop the runtime for good after a few quick crashes during a short database outage, which costs coverage. 26 T1 (Test 4): queue overflow exits with 7 (restartable, recorded as a CRASH gap). 33 T1 (Test 4): RUNBOOK 20.1 lists every `ExitCode` member and the hold behaviour.

## Also done

- 29 truths, T1 (Test 4, action): no late signal independent of the Q-D answer (D-06, L-11): the supervisor is seeded from the warm-up snapshot and `apply_restart_fence` demotes any non-live bar at or before the snapshot to history; test over all three evaluation rules with a negative control. This also closes a latent hole: the "open" connection event after a restart triggers a verification backfill that would otherwise return downtime bars tagged REST_BACKFILL.
- 21 T3: states that the JSON evidence supersedes the legacy `soak_smoke.log` (SC7, D-10).
- `16-PATTERNS.md`: three stale table rows and one stale paragraph corrected (EVIDENCE_GAP lives in `coverage.py`, evaluator in `exit_criteria.py`, `notify.py` is reused read-only).
- `16-VALIDATION.md`: ten new behaviour rows and the updated live-smoke manual row (flags `draft`/`nyquist_compliant: false` unchanged on purpose).
- New threat ids: T-16-110 (22), T-16-111 (04), T-16-112 (11), T-16-113 (17), T-16-114 (15).

## Mechanical re-verification (run after the edits)

- `frontmatter.validate` (schema `plan`) and `verify.plan-structure`: valid for all 25 edited plans (01, 04, 07, 08, 09, 11, 15, 16, 17, 21, 22, 24, 25, 26, 27, 29, 30, 31, 32, 33, 34, 35, 43, 47, 49); the only warnings are the pre-existing "bare git diff" notes in 09, 24 and 35 (unchanged by this revision).
- Dependency graph: 49 plans, no cycle, every `depends_on` exists, wave = max(dependency waves)+1 for all plans, no `files_modified` overlap between plans of the same wave; `estimate.tasks` equals the task count of every plan. Tasks per plan are at most 4 (plans 11, 15, 17, 30 now have 4). Plan 05 still lists 11 files (known warning, not touched). XML tags balance in every edited plan.
- No new plan, no changed `wave` or `depends_on` value; new data dependencies all point to earlier waves (22 to 26/32/33, 08 to 16/24/15, 04 to 11/31, 17 to 21, 30 to 47/43, 15 to 25/47).

## Residual items (deliberately not changed here)

- Research F8 (module-global SDK stream map across tests) is addressed only through the restoring fixture that plan 01 now requires for the patched map; the contract test keeps pinning its existence.
- Research F11 (new-connection rate limit, G3(c) UNVERIFIED): only a 300 s tool floor on the smoke's SDK timer override and the SOURCES label; the supervisor's retry constants stay in the O-07 table.
- CONTEXT stale statements (event-loop thread, CR-01 text, epoch pin rule), the CONTEXT O-list (it does not list Q-A..Q-Q), D-26 G5 reporting via Q-O and the still-open consistency rows 1, 3, 13, 18, 22, 23 are file-owner edits outside the plans and were not touched.
- The measurement settings in the plan 21 live command (`--force-disconnect-after-seconds 900`, `--sdk-reconnect-interval-seconds 3600`, `--rest-lag-*`) are tool settings of a user-run smoke, labelled "not thresholds" and never reused as runtime values; the user may change them when running the command.
