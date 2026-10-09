# Phase 16: research-versus-plans audit

Audited: 2026-10-09. Read-only; no plan was edited. Scope: do the 49 plans (16-01..16-49) carry everything in `16-RESEARCH.md`, `16-RESEARCH-GAPS.md`, `16-RESEARCH-GAPS-RESULT.md`, `16-PATTERNS.md` and `16-VALIDATION.md`?

## Verdict

The plans are NOT materially incomplete relative to the research. Nearly every finding, pitfall, gap resolution, pattern analog and validation row has a plan and a test. What is left is 13 narrow findings (3 medium-high, 6 medium, 4 low) plus a list of research items that stay open and that the plans acknowledge or silently assume. No finding blocks execution; findings F1-F3 are worth a plan revision or a recorded user decision before the trial soak.

Method and limits: the five research artifacts were read in full. Plans were parsed mechanically (frontmatter `files_modified`, task names, `<files>`, `<automated>`), cross-checked by keyword/identifier search across all 49 plans, and read in part (01, 08, 17, 19, 24, 26, 30 and targeted excerpts of 04, 07, 09, 11, 14, 15, 21, 22, 27, 31, 32, 33, 47). I did NOT read every task action line by line, so "no plan mentions X" means a full-text search of all 49 plans found nothing.

## What was extracted

- RESEARCH: 17 locked decisions L-01..L-17; D-01..D-35; REV-01..REV-18 (via CONTEXT); 23 pitfalls P1-P23; 9 SDK defects D1-D9 (+3 CONTEXT defects a-c); 7 patterns; 12 assumptions A1-A12; 16 questions Q-A..Q-P; 13 open decisions O-01..O-13; supplements S1 (GitHub schedule), S2 (S3/Object Lock/rclone, 7 interactions), S3 (`modeled_costs_per_unit` readers); an O-07 constants table; 23-row validation table; real-vs-fake table; 9-row security table.
- GAPS-RESULT: 19 items. CITED 5 (G1, G7, G9, G14, G16), CITED (partial) 10 (G2, G3, G6, G8, G10, G11, G12, G15, G17, G18), UNVERIFIED 3 (G4, G5, G13), NOT ATTEMPTED 1 (G19).
- PATTERNS: 31 file rows (28 with an analog, 4 listed as no-analog), 12 shared patterns.
- VALIDATION: 37 behaviour rows, 5 manual-only rows, 6 Wave 0 items; frontmatter `status: draft`, `nyquist_compliant: false`, `wave_0_complete: false`, sign-off unchecked (expected before execution).

## (a) Research findings that no plan applies, or applies only partly

| # | Sev | Finding | Evidence |
|---|-----|---------|----------|
| F1 | MED-HIGH | G15 / Pitfall P18 / S1: scheduled runs "can be delayed ... start of every hour ... some queued jobs may be dropped". The workflow cron is `0 * * * *`, exactly that minute. REV-18 turns any missing scheduled tick into an `EVIDENCE_GAP` that restarts the trial with a new epoch pin, so the documented drop behaviour directly threatens the 14-day trial. PATTERNS lists moving the cron off the hour as a candidate mitigation. Plans 09 and 47 do the opposite: acceptance criteria require the cron line to stay byte-unchanged. No plan or checkpoint weighs the choice or asks the user. | `grep` of 16-09 (Test 4, acceptance "cron line unchanged"), 16-47 (executor rules "keep the workflow's cron line"); 16-PATTERNS lines 168 |
| F2 | MED-HIGH | Pitfall P4 / D3 / D2 proof gap in the live smoke. Plan 17 T2 implements the forced disconnect "by closing the adapter's SDK connection object (the unsolicited-close path of research D3)". Research D3 says the dead-subscription defect exists only on an UNSOLICITED close (`_discard_connection`); a user-initiated close (`_close_one`, `close_connection`) calls `_forget_connection_streams`, the clean path. If the smoke closes via the SDK's own close API it exercises the wrong branch and PAPER-01 criterion 7 would not be shown for the failure path. Also never exercised before the trial: the SDK 23 h rotation / `serverShutdown` `reconnect` event (D2). Plan 21 runs about 4.2 h (`--duration-seconds 15000`). | 16-17 T2 action; 16-21 line 77; RESEARCH D2, D3, P4 |
| F3 | MEDIUM | G7/G8 Telegram failure modes have no behaviour or test in the SHADOW chain: no handling of 429 / `retry_after`; no handling of `editMessageText` failure or "message is not modified" when APPROVE edits the alert into the CONFIRM card (plan 11 T1) or on a replayed callback; `answerCallbackQuery` not mentioned outside the SOURCES row. A failed edit after APPROVE leaves an approved plan with no confirm card and no journaled outcome. The tenacity retry in `src/paper/notify.py` (reused by plan 04) does not read `retry_after`. Only `docs/SOURCES.md` rows (plan 17 T3) record these facts. | grep `retry_after\|429\|not modified\|answerCallbackQuery` finds only 16-17 T3 |
| F4 | MEDIUM | S2 interactions 1 and 7 are missing from the O-01 decision text. Plan 30 T2 options a/e do not say that evidence written through the backup `crypt` remote is ciphertext and unreadable by the GitHub runner or an auditor without `BACKUP_CRYPT_PASSWORD(2)` (S2 #1), nor that the daily snapshot leaves a up-to-24 h loss window unless evidence is written at event time (S2 #7). Plan 07 RUNBOOK 19.6 covers crypt-has-no-hashes and the purge/Object Lock clash but not the reader-passphrase point. grep `crypt` in 16-30/47/49: no hit. |
| F5 | MEDIUM | P20 mitigation is half applied. Plan 26 T2 records clock skew at start only. Research also asks to journal the tick `now_utc` and the dropped-event counts (events with close `T` later than `now_utc`, `feed_events_dropped`) so a lagging clock cannot silently discard valid bars. Plans journal tick time (plan 24) but no plan records or tests dropped-event counts (`grep feed_events_dropped` finds nothing). | RESEARCH P20; 16-24, 16-26 |
| F6 | MEDIUM | A10 (the tick over up to 1000 bars x 5 symbols finishes well inside a bar interval) is never measured. No runtime record carries tick duration; the only timing hook (plan 18 T3) is for the research runner. The healthcheck uses processed-bar age, which would only reveal a backlog after the fact. | grep `tick duration\|elapsed\|backlog`: none outside decision-surface text |
| F7 | MEDIUM | A11 / Q-M: research says the smoke should measure REST 1m kline lag and weight budget. Plan 19 makes `poll_interval`/`close_lag` required user-ratified inputs (O-07 table via `[timing]` keys, fine) but the smoke evidence schema (plan 17 T1) has no REST-minute lag or weight field, so the user ratifies those numbers with no measurement. |
| F8 | LOW | D7 (module-global `global_stream_connections` leaks across tests). Plan 01 T3 test 4 seeds a foreign stream name into that map and the contract test pins its existence, but no plan adds a reset/autouse fixture. | 16-01 T2/T3 |
| F9 | LOW | D5 / A2 / G5: the SDK opens three sockets (`market`, `public`, `private`); acceptance of an unauthenticated `/private` connection is UNVERIFIED. Plan 01 only checks `ws.connections` is non-empty, and the smoke evidence records no connection count, so a refused `/private` socket would go unnoticed. |
| F10 | LOW | A7 / G15: private-repository auto-disable of scheduled workflows is UNVERIFIED. Nothing in plans 09, 15 or 43 checks that the scheduled workflow is still enabled (for example a `gh workflow list` check in the plan 43 preflight). The reconciler (plan 15) detects the consequence, not the cause. |
| F11 | LOW | G3(c) new-connection rate limit is UNVERIFIED and no plan bounds the rebuild loop with a documented limit. Plan 08 reuses the unratified `SUPERVISOR_MAX_ATTEMPTS`; plan 27 lists it for ratification, so the exposure is covered by the O-07 checkpoint but not called out as having no documented ceiling. |

Applied well (spot-verified): P1 (1 ms fix, plan 08 T2), P2/P6/P7 (source tags, sibling wait, windows 1000/300; plans 08/10/24), P3 (one rotation owner), P5 (connections check, bar-age healthcheck), P8/P9/P11/P12 (restore, sinks, deterministic ids, Q-J checkpoint; plans 08/16/29), P10 (`put_nowait`, `to_thread`, blocking-store test; plan 26), P13/P14 (restart expiry, functional buttons; plans 04/31), P15 (plan 35/36), P16 (public adapter split, plan 03), P17 (Q-L, plan 14), P19 (Q-I, plans 32/33), P21 (Q-O, plan 12), P22 (pin entry, plans 13/45), P23 (glob scan, plan 10), D1-D4/D6/D8, Q-A..Q-P (every question has a checkpoint or a recorded planner choice), O-01..O-13, REV-01..REV-18, S3 consumer audit (plan 18), IN-01..IN-05 (plan 02), glossary (plan 09).

## (b) Files: PATTERNS versus plans

PATTERNS rows with no `files_modified` entry in any plan:
1. Protocol v2.2.0 amendment files: `docs/research/RESEARCH_PROTOCOL.md`, `docs/research/holdout_consumed.json`, `scripts/decision_alignment/protocol.py`, `tests/test_decision_alignment_protocol.py`, `.github/workflows/research-gate.yml`, `docs/DECISIONS.md` row, `docs/DOC_STATUS.md`. Deliberate per VALIDATION ("separate prerequisite task, not a Phase 16 code plan"); plan 28 T3 only gates on it. Risk: nothing in the phase owns or tracks that task (it can be orphaned).
2. `src/paper/notify.py` (PATTERNS row "modify: functional APR/SKP buttons, SHADOW label"): no plan modifies it; plan 04 reuses it read-only from the new `src/paper/shadow.py` and edits `src/adapters/telegram_notify.py`. Acceptable, but PATTERNS is stale on this row.
3. PATTERNS puts the `EVIDENCE_GAP` line shape in `src/paper/freeze.py`; plans keep it in `src/paper/coverage.py` (plan 15) as a separate artifact, which matches RESEARCH S1 ("never edits the append-only registry_diff.jsonl"). PATTERNS is stale, plans are right.

Plan files with no PATTERNS entry (no analog excerpt for the executor): `src/adapters/binance_public.py`, `src/paper/{vocabulary,pipeline,restart,runtime_config,market_inputs,live_minutes,shadow_confirm,shadow_ledger,shadow_runtime,evidence_bundle,exit_criteria,evidence_export}.py`, `src/persistence/paper_runtime_state.py`, `src/persistence/system_state.py` + `src/db/models.py` + `src/db/alembic/versions/0005_paper_runtime_state.py` (conditional on Q-J), `src/research/{__init__,authorization}.py`, `src/analytics/render_killgate.py`, `docs/research/kill_gate_review_registry.json`, `scripts/{paper_ws_smoke,export_soak_evidence,evaluate_trial_soak,soak_host_acceptance}.py`, `deploy/{soak-image.sh,soak.env.example}`, `config/paper/*`, `docs/SOURCES.md`, the preregistration documents and `params/*/research-run-1-*.toml`. These are plan-level decomposition of PATTERNS rows (all trace to a PATTERNS section or a research item); none looks unjustified. The plans name analogs in their own `read_first`.

Plan 05 lists 11 files (known warning in `16-PLAN-CHECK.md`); not repeated here. No file is modified by two plans without a dependency chain (checked mechanically).

## (c) Validation rows versus plans and tests

- All 37 VALIDATION behaviour rows and all 70 test files cited in VALIDATION/RESEARCH resolve to a plan that creates or runs them. No orphan test, no row without a plan.
- Task references in the Plan/Task column were checked against each plan's task `<files>`. Three rows cite a task whose `<files>` do not contain the row's test files: REV-03 rehearsal (16-36 T2, 16-25 T2), D-20 parity (16-25 T2), D-27/29/30 runner report (16-18 T3). Likely labelling drift (the test runs in a neighbouring task); worth correcting so the traceability grep holds.
- Wave 0 list is covered: SDK-shaped fakes (01), real-shaped fixtures (08), rewrites (01, 08), PG preconditions (11, 16, 29), no-float scan (05, 10, plus plan 15 and 36 verifies).
- Frontmatter still `nyquist_compliant: false`, `wave_0_complete: false`, "Max feedback latency" unset, sign-off unchecked. Expected pre-execution, but keep as an open item.
- Plans run tests with `.venv/Scripts/python` (Windows); VALIDATION quick command is `uv run`. Documented as equivalent; fine on the execution machine, but any plan step that must run on the Linux soak host cannot reuse those verify lines.

## (d) Plans that ignore or contradict the research

- SDK signatures, WS awaiting, plain-string interval, `stream_url`, `handle.on("message")`, no `on_message`/`reconnect`, `on_connection` events, `connections` check, D6 loop-thread callbacks, D8 SDK model fixtures: plans 01, 08, 26 match the introspected signatures. No contradiction found.
- Gap results: plans use G1-G18 correctly (plan 17 T3 records the SOURCES rows; plans 07/09/30/33/49 carry G9-G16). No plan contradicts a CITED fact.
- F1 (cron) is the only real conflict with research intent.
- Plan 32 sets the `paper` service `restart: "on-failure"` while plan 22 defines refusal exits 3, 4 and 5 (non-zero) for configuration or admission failures. A refusal then restarts in a loop. Not a research item, but it interacts with D-01 (SKIPPED exits 0, so that path is fine) and with P8 (each restart writes RUNTIME_START/gap rows). Consider a refusal exit code Docker does not retry, or a bounded restart policy.
- Plan 17 states the REST client/archive fetch uses `make_archive_client`; fine. Plan 19 uses `poll_interval_seconds`/`close_lag_seconds` as poller arguments while plan 22's config keys are `minute_poll_interval_seconds`/`minute_close_lag_seconds`; cosmetic, plan 31 must map them.
- Plan 07 RUNBOOK 19.6 asserts as fact that `apply_retention`'s `rclone purge` "would fail under a COMPLIANCE default on the backup bucket". G18 says the behaviour of `rclone purge` on a path inside a versioned or locked bucket is UNVERIFIED (only G10's permanent-delete 403 is cited). The text should be labelled an inference.

## (e) Gaps still open in research that plans assume or only partly acknowledge

| Gap | Research status | Plan handling |
|-----|-----------------|---------------|
| G3(c) new-connection rate limit | UNVERIFIED | not mentioned (F11) |
| G4 / A8 mark-price kline WS stream | UNVERIFIED | explicit: plan 19 chooses REST and labels G4 UNVERIFIED (good) |
| G5 / A2 `/private` without listen key | UNVERIFIED | silent (F9) |
| G6 two-poller 409 text | UNVERIFIED | explicit via Q-L (plan 14) and runtime log (plan 31) (good) |
| G8 callback wait/validity, "not modified", edit time limit | UNVERIFIED | silent (F3) |
| G2 last kline row may be unfinished | UNVERIFIED | plan 08 drops forming rows by close time vs the injected clock; sound, but depends on clock skew (F5) |
| G10 Object Lock separate charge, G11 SSE-KMS policy, G13 prices | UNVERIFIED | O-12 checkpoint (plan 14) keeps prices with the user; acceptable |
| G12 EBS default state of a new account | UNVERIFIED | explicit: plan 07 requires `get-ebs-encryption-by-default` in ap-southeast-1 (good) |
| G14 stock Ubuntu chrony default | UNVERIFIED | plan 07 requires `chronyc` evidence (good) |
| G15 retry/detect of dropped runs, numeric delay, private-repo auto-disable | UNVERIFIED | detection handled by plan 15 reconciler; auto-disable silent (F10); delay handled as user-owned `freeze_tick_grace_seconds` (good) |
| G17/G18 cryptcheck on multipart objects, `purge` on locked/versioned path | UNVERIFIED | plan 07 states a purge failure as fact (see (d)) |
| G19 real-S3 crypt repeat | NOT ATTEMPTED | superseded by D064 for the backup chain (RESEARCH A6); nothing assumed |
| A10 tick duration, A11 REST minute lag, A12 closed kline once per stream | unproven | A12: dedup kept (plan 24); A10, A11: F6, F7 |

## Counts

- Findings: 11 research-application gaps (F1-F11) + 2 extra plan observations (restart policy; stale PATTERNS rows) + 1 labelling issue (3 validation rows) + 1 unlabelled inference (purge). Severity: 2 medium-high (F1, F2), 5 medium (F3-F7), 4 low (F8-F11).
- PATTERNS rows with no plan: 1 group (protocol amendment, deliberate) + 2 stale rows (notify.py, EVIDENCE_GAP location).
- Plan files with no PATTERNS entry: about 38 (all justified by decomposition).
- Validation rows without plan: 0. Test files without plan: 0. Rows citing a task that lacks the row's test file: 3.
- Missing files referenced by plans: 0 (561 distinct repo paths named in plans; every one exists or is created by a plan). Existing symbols spot-checked via `codegraph explore` and an identifier index (208 backticked names; the 93 not found in the repo are all names introduced by the plans themselves).

## Top gaps to fix first

1. F1: decide the hourly cron minute with the user (or record why `0 * * * *` stays) before plan 09 and 47 lock it.
2. F2: make plan 17 T2 force the disconnect through the unsolicited path (kill the socket / drop the transport, not `close_connection`), add an acceptance line that the SDK global stream map still held the stale entries before `rebuild`, and decide how the 23 h `reconnect` path is first observed (the trial soak itself, with a gap-row check).
3. F3: add Telegram failure handling to plans 04/11/31: 429 with `retry_after`, edit failure after APPROVE (journal and expire, never leave a decided-but-cardless plan), "message is not modified" on replay.
4. F4: add the crypt-reader and event-time-write points to the O-01/Q-F option text in plan 30.
5. F5-F7: journal dropped-event counts, add tick duration to the heartbeat record, add REST 1m lag and connection count to the smoke evidence.
