# Lane X08: operator_golive_gap

## Scope
Operator view (part-time owner, no trading expertise, 3 a.m.): `docs/operations/*` (RUNBOOK,
DEPLOY_GUIDE.vi.md, DEMO_VS_MAINNET.md, SECURITY_AND_OPERATIONS.md), the phase `*-OWNER-RUNBOOK.md`
files (24, 25), alert wording, the `/status` reply. Walkthroughs: first start, a normal trade, SAFE_MODE at
3 a.m., an UNKNOWN placement, a position without a stop, a ban, a restore from backup, an update with a
migration, key rotation. Demo -> mainnet delta. Single point of failure. Defects found by other lanes
(G-0300, G-0301, G-0403, G-0500/0501, G-0602/0603, G-0700, G-0801, G-0804, G-1800, G-1801, G-2100) are
cross-referenced, not re-reported; this lane checks whether the documents tell the owner what to do then.

## Coverage

| file | depth | note |
|---|---|---|
| docs/operations/RUNBOOK.md | DEEP_READ | sections 1-14, 21, 22 deep; 15-20 headings and grep only (soak / cutover / pins are the ops lane) |
| docs/operations/DEPLOY_GUIDE.vi.md | NORMAL_READ | headings, sections 0, 12, 10.6, 15 read; rest grep for live-process terms |
| docs/operations/DEMO_VS_MAINNET.md | DEEP_READ | all 36 rows |
| docs/operations/SECURITY_AND_OPERATIONS.md | DEEP_READ | whole file |
| .planning/phases/24-live-runtime-composition-demo/24-OWNER-RUNBOOK.md | DEEP_READ | every command checked against Dockerfile / compose / bootstrap |
| .planning/phases/25-demo-integration-test-campaign/25-OWNER-RUNBOOK.md | NORMAL_READ | structure, S19, section 11 |
| src/ops/alert_wording.py | NORMAL_READ | operator_must texts of EMERGENCY_CLOSE_*, ENTRY_STATE_UNKNOWN, REST_GATE_* (lines 278-420) |
| src/live/operator.py | NORMAL_READ | `/status` lines 395-416, `_FINISHED_STATES` line 106 |
| src/live/config.py | NORMAL_READ | liveness stamp and `live_liveness_problem` 296-426, `GATE_STATE_FILE` 67 |
| src/live/wiring.py | METADATA_ONLY | `_write_liveness` 1160-1168, signal source wiring |
| src/live/startup.py | METADATA_ONLY | `_enable` 1078-1081 (DEMO only) |
| src/execution/enablement.py | NORMAL_READ | lines 1-120 |
| src/risk/margin_check.py | METADATA_ONLY | flag at 273-282 |
| Dockerfile | NORMAL_READ | ENV (no PATH to venv), comment 73-74 |
| deploy/update.sh | NORMAL_READ | live guard 101-126 |
| deploy/restore.sh | NORMAL_READ | main 72-97 (no live guard) |
| deploy/heartbeat.sh | METADATA_ONLY | probe commands 82, 351-357 |
| deploy/bootstrap.sh | METADATA_ONLY | packages installed (no uv / project python) |
| docker-compose.yml (live service) | METADATA_ONLY | command, healthcheck, restart |
| .planning/ROADMAP.md (Phase 26) | NORMAL_READ | goal, criteria, 0 plans |
| Telegram approval / confirm cards | NOT_READ | covered by telegram_alerts lane (G-0802..G-0806) |

## Verified Safe Areas

- **Alert wording for the ban, gate-recovery, emergency-close and unknown-entry alerts tells the owner the
  first action** -> `src/ops/alert_wording.py:278-420` -> each has an `operator_must` text ("Check the
  exchange position now and close it yourself if it is still open", "Check the exchange position and its
  stop yourself now..."). Holds for these worded events; the unworded CRITICAL ones are G-0804.
- **Update refuses while the live service runs** -> `deploy/update.sh:105-126` -> `--ref` and `--rollback`
  both call `require_live_stopped`, fail closed when the probe cannot tell. Holds (but see G-2004 on the
  rule it tells the owner to follow).
- **Heartbeat sender uses the venv interpreter** -> `deploy/heartbeat.sh:82` (`PY=/app/.venv/bin/python`),
  `:357` -> the external probe itself is runnable; only the owner-runbook commands are not (G-2000).
- **Secrets never go into argv/history in the heartbeat path** -> RUNBOOK 11.9 and `deploy/heartbeat.sh
  --set-url` read stdin -> holds as documented.
- **A restart never places or enables an entry by itself** -> RUNBOOK 22.2, `src/live/startup.py:1078-1081`
  (`_enable` acts only in DEMO after a passing health verdict; entries start disabled) -> a restart can only
  protect, which is the basis of G-2007.
- **SAFE_MODE exit readiness rows double as a checklist** -> RUNBOOK 21.1 rows 1-7 and 21.1a step 1 -> the
  refusal codes are returned to the owner on Telegram; sound for an inexpert operator.
- **DEMO_VS_MAINNET.md label discipline** -> every NOT_OBSERVED row states a reason; no row claims a
  mainnet observation; injected faults are kept apart (DVM-25). Sound document (one drift: G-2009).
- **UNKNOWN placement walk-through** -> RUNBOOK 5 (read-only SELECTs, query Binance by client id, never
  approve again) plus the ENTRY_STATE_UNKNOWN wording (alert_wording.py:315-331) -> the owner is told not to
  re-approve and the system keeps the entry under lookup; an UNKNOWN resolver exists
  (`list_unresolved_intents` step, "Closes an UNKNOWN ENTRY intent only on repeated, fresh, journaled
  Binance evidence"). Not traced further (reconcile lane).

## Decision review

| decision/doc rule | verdict | yardstick | reason |
|---|---|---|---|
| D034 / SECURITY_AND_OPERATIONS 7: "nothing depends on the operator reacting within minutes" (automatic ladder) | SOUND | owner goals (part-time) | right premise; but the same docs then tell the owner "do not wait for an automatic action, place the stop yourself" (RUNBOOK 3 line 49, DEPLOY_GUIDE 12.1), and G-0300/G-0301 leave cases only a human can fix |
| D104: operator surface = Telegram commands; gate clear = ssh command | DOUBTFUL | owner goals, single channel | Telegram is the only alert and command channel; the ssh path is not runnable as written (G-2003, G-2005) |
| D106 Q11: one healthchecks.io check per process, probe = loop-alive stamp | DOUBTFUL | operator need (learn of danger when Telegram is down) | the probe is green in SAFE_MODE, with a naked position, and with Telegram down (G-2003) |
| D106 Q15: live `restart: "no"` "is the safe default" | DOUBTFUL | logic (D079 fill-driven protection; restarts never place entries) | with a resting entry the down process is the unsafe state; the stated switch condition (first clean Demo run) is met (G-2007) |
| RUNBOOK 22.5 stop rule "wait until protections: 0 open" | WRONG | code (`operator.py:106,411-413`) | counts filled-and-protected trades as open (G-2004) |
| RUNBOOK 21.3 / O-C a1: unknown gate state blocks every REST call until a human clears it | CANNOT_JUDGE (here) | - | trade-off judged by binance_adapters (G-0700); here only its operability (G-2005) |
| D040 / Phase 26 criterion 5: canary "with the operator watching", zero divergences | DOUBTFUL | owner goals, G-0500 | a part-time owner cannot watch a 4H/1H trade end to end; "zero divergences" may be unattainable while a healthy trade produces divergences (G-0500); Phase 26 has 0 plans (G-2010) |
| D085 flag `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED=True` | SOUND (direction) | code comment: a wrong True only yields -2019 at placement | the go-live document misstates it (G-2009) |
| DEMO_VS_MAINNET.md as the Phase 26 input | SOUND | evidence discipline | complete list of Demo-only items; lacks the flag / config delta (inventory below) |

## Findings

### G-2000
- ID: G-2000
- Severity: LOW now / LOW mainnet
- Confidence: PROBABLE (static trace; no container was run)
- Classification: DEFECT
- Category: operator commands / first install
- Component: Phase 24 owner runbook, RUNBOOK 21.3
- File: .planning/phases/24-live-runtime-composition-demo/24-OWNER-RUNBOOK.md
- Lines: 61-62, 89 (also docs/operations/RUNBOOK.md:1097-1101)
- Rule: RUNBOOK 21.1c (commands use `/app/.venv/bin/python`); Dockerfile:73-74
- Known-prior: none found
- Evidence: D2 `docker compose --profile live run --rm live python -m src.live.runtime --initialize-gate-state --operator-id owner`; D3 `docker compose --profile live exec live python -m src.live.runtime --healthcheck`. Dockerfile:73-74: "bare `python` on PATH is the base interpreter, which has none of the venv packages (F-705)"; the image sets no PATH to `/app/.venv/bin` (Dockerfile:21-25). G1 runs `uv run python scripts/demo_clear.py` and `uv run python -m scripts.demo_rehearsal --execute` "from the VPS", but `deploy/bootstrap.sh` installs only ca-certificates, curl, git, ufw, sudo and Docker (RUNBOOK 13.4, bootstrap.sh:176). RUNBOOK 21.3 gives `python -m src.ops.rest_gate_cli ...` "run on the host, over ssh" with no container form.
- Expected: every owner command runs as written on the host the runbook names.
- Actual: the first-install step D2 and the probe D3 fail with an import error inside the container; G1 and the gate CLI have no interpreter with the project on the host.
- Reproduction: read Dockerfile ENV block and the D2/D3 commands; compare with RUNBOOK 21.1c:1082 and the compose `command` (`/app/.venv/bin/python`).
- Impact: the first install on the VPS stops at its first command; a confused owner may start `up -d live` without the gate initialisation and meet GATE_STATE_UNKNOWN (every REST call blocked, RUNBOOK 22.3). Fails closed, no money effect.
- Why tests miss it: no test executes owner-runbook text.
- Remediation: use `/app/.venv/bin/python` in every container command; give the container form (`docker compose --profile live run --rm --no-deps live /app/.venv/bin/python -m src.ops.rest_gate_cli status --path /app/logs/live/rest_gate_state.json`) for host-side tools.

### G-2001
- ID: G-2001
- Severity: LOW now / MEDIUM mainnet
- Confidence: CONFIRMED
- Classification: DRIFT
- Category: operator documentation (owner's language)
- Component: DEPLOY_GUIDE.vi.md
- File: docs/operations/DEPLOY_GUIDE.vi.md
- Lines: 3, 106, 2155, 2482-2495, 2761, 2763-2771
- Rule: D031 (docs order); the guide's own promise to label what the repository does not have (line 5)
- Known-prior: none found
- Evidence: line 3 "Đọc repository ngày 2026-10-09, commit `97a92a6`". Line 106: "Live runtime | `[CHƯA XÂY]` | Service `live` trong compose chỉ là khung báo lỗi, đến Phase 24". Section 12.1 (emergency table) is labelled `[CHƯA XÂY]` and says the ladder is "Phase 20 và CHƯA XÂY: ... BẠN phải tự đặt SL hoặc đóng vị thế thủ công trên sàn". Line 2761 "SL vẫn nằm trên sàn" (the stop stays on the exchange), false since D079 (G-2100). Appendix: "Mô hình thực thi D055 (đặt SL trước hay sau khi vào lệnh): còn là quyết định mở" although D079 decided it. Grep counts in the guide: `safemode_exit` 0, `/close` 0, `disable_entries` 0, `initialize-gate-state` 0, `rest_gate` 0, `UNPROTECTED_POSITION` 0.
- Expected: the guide written "for a person who is not DevOps" in the owner's language covers the live process the owner is now asked to run (Phase 24/25 owner runbooks), or says plainly that it stops at Phase 16 and points to RUNBOOK 21-22.
- Actual: it describes a system without a live process; its emergency table gives pre-Phase-20 advice and a false "the stop is on the exchange" assurance.
- Reproduction: `grep -c "safemode_exit\|disable_entries\|initialize-gate-state" docs/operations/DEPLOY_GUIDE.vi.md` -> 0.
- Impact: at 3 a.m. the owner reading his own-language guide does not learn the Telegram commands, the stop procedure, the gate recovery, or that a resting entry can fill without a stop while the process is down.
- Why tests miss it: no freshness check on this guide; DOC_STATUS amendments touched it only for single variables (DOC_STATUS lines 86, 91).
- Remediation: mark the guide as covering up to Phase 16 at its top, and add a Vietnamese section for the live process (commands, the alert table of G-2002, the stop procedure, gate recovery).

### G-2002
- ID: G-2002
- Severity: LOW now / MEDIUM mainnet
- Confidence: CONFIRMED
- Classification: GAP
- Category: incident response / alert-to-action mapping
- Component: RUNBOOK
- File: docs/operations/RUNBOOK.md
- Lines: 9-63, 1024-1066 (absence)
- Rule: SECURITY_AND_OPERATIONS 5 / 5.1 (OPS-05 alert set); RUNBOOK 1 ("operational response guide for incidents")
- Known-prior: failure_scenarios Open Question (X08); G-1801 remediation "Add the runbook step for CLOSE_FAILED"; G-0804 (wording)
- Evidence: grep counts in RUNBOOK.md: `UNPROTECTED_POSITION` 0, `EMERGENCY_CLOSE_FAILED` 0, `EMERGENCY_CLOSE_NOT_SENT` 0, `PROTECTIVE_REJECTED` 0, `ENTRY_STATE_UNKNOWN` 0, `AUTH_FAILURE` 0, `STALE_DATA` 0, `DAILY_STOP` 0, `API_DEGRADATION` 0, `PENDING_UNKNOWN` 0; only TP_UNAVAILABLE (section 3), PROTECTION_HANDOFF_FAILED (21.6), TASK_STALLED (22.8) and the gate alerts (21.3, by name only) have an entry. Section 2 step 1 "Set SAFE_MODE" has no command (the bot has `/disable_entries`, not a SAFE_MODE entry). No text separates "act now" (naked position) from "can wait until morning" (SAFE_MODE with every position protected, e.g. G-0501's one failed GET). CLOSE_FAILED after a manual flatten has no way out (G-1801), and the runbook does not say so.
- Expected: one table: alert code / SAFE_MODE reason -> is a position at risk -> what to check -> what to do -> how to leave the state.
- Actual: the owner receives `[CRITICAL] UNPROTECTED_POSITION / subject: ETHUSDT / reason: POSITION_WITHOUT_STOP` (G-0804 probe) and must find section 3 by reading; for EMERGENCY_CLOSE_FAILED / CLOSE_FAILED nothing says that the manual close leaves the system blocked until a database edit.
- Reproduction: `grep -c <code> docs/operations/RUNBOOK.md` for each code above.
- Impact: slower or wrong reaction exactly in the cases where only the human can act (G-0300: naked position the system no longer tracks; G-0301: unbounded PENDING_UNKNOWN close); needless 3 a.m. interventions for benign SAFE_MODE reasons.
- Why tests miss it: documentation; the alert contract test checks templates, not runbook coverage.
- Remediation: add an alert/reason index to RUNBOOK (and the Vietnamese guide) with an urgency column; document the CLOSE_FAILED dead end until G-1801 is fixed.

### G-2003
- ID: G-2003
- Severity: LOW now / HIGH mainnet
- Confidence: CONFIRMED
- Classification: DESIGN
- Category: notification channel / single point of failure
- Component: live heartbeat, alert sink
- File: src/live/config.py
- Lines: 395-426 (also src/live/wiring.py:1160-1168; deploy/heartbeat.sh:357)
- Rule: D106 Q11; D042 condition 1 (off-host monitor); SECURITY_AND_OPERATIONS 4 (monitor "Telegram delivery", "unprotected positions")
- Known-prior: G-0801 (CRITICAL alert dropped after a failed send), G-0602 (failing task, green heartbeat), G-0603 (bot never retried). Not recorded: that no channel other than Telegram exists for any CRITICAL state.
- Evidence: `live_liveness_problem` docstring: "Live means: no held marker of this container and a readable stamp of this container whose ..." age is below the bound (config.py:404-426); the stamp is written every loop with the task results, which the probe does not judge (wiring.py:1160-1168). SAFE_MODE, an UNPROTECTED plan, a failed Telegram send and a stopped bot do not enter the probe. RUNBOOK 11.9 line 281: the signal "does not show that positions are protected (the stop-loss stays on the exchange, D042 condition 1)"; the parenthesis is false since D079 (G-2100).
- Expected (yardstick: owner goals, fail closed): a state in which a position may be naked reaches the owner even when Telegram is down, e.g. the liveness probe fails (or a fail ping is sent) while an UNPROTECTED / CLOSE_REQUIRED / CLOSE_FAILED plan or an undelivered CRITICAL alert exists.
- Actual: with Telegram unreachable (or the bot token revoked), a naked position produces journal rows only; healthchecks.io stays green.
- Reproduction: read `live_liveness_problem`; combine with G-0801's probe (alert dropped after 3 attempts).
- Impact: mainnet with placement enabled: an unprotected position can stay unknown to the owner for as long as Telegram is down; the system's own close ladder covers most cases, not G-0300/G-0301.
- Why tests miss it: liveness tests assert stamp age and the held marker only.
- Remediation: owner choice (Owner decisions 1): make `--liveness` fail while a CRITICAL alert is undelivered or a plan is in UNPROTECTED/CLOSE_REQUIRED/CLOSE_FAILED, so the existing off-host check carries it.

### G-2004
- ID: G-2004
- Severity: LOW now / MEDIUM mainnet
- Confidence: CONFIRMED
- Classification: DEFECT
- Category: operator procedure (stop / update)
- Component: RUNBOOK 22.5, deploy/update.sh, 25-OWNER-RUNBOOK 11
- File: docs/operations/RUNBOOK.md
- Lines: 1182 (also deploy/update.sh:125-126; .planning/phases/25-demo-integration-test-campaign/25-OWNER-RUNBOOK.md:532-538; src/live/operator.py:106, 411-413)
- Rule: KNOWN:24-DEFERRED R-22 (cancel-on-stop missing; 22.5 is the interim)
- Known-prior: R-22 is known; the wrong criterion is not recorded
- Evidence: RUNBOOK 22.5: "send `/status` and wait until the line `protections: 0 open of N tracked` shows, that is until every resting entry has filled and been protected or has expired". Code: `_FINISHED_STATES = frozenset({ProtectionState.FLAT, ProtectionState.ENTRY_ENDED_NO_FILL})` and `open_plans = [p for p in plans if p.state not in _FINISHED_STATES]` (operator.py:106, 411-412). A filled trade in PROTECTED, COMPLETE or TP_UNAVAILABLE counts as open. update.sh:125-126 repeats the rule ("wait for 'protections: 0 open' in /status").
- Expected: the stop is safe when no plan is in AWAITING_FILL (no resting entry) and none is UNPROTECTED / CLOSE_REQUIRED; a protected open position does not need to close first.
- Actual: the rule is met only when every trade has fully ended (SL or TP hit), which for a 4H/1H trade can take days.
- Reproduction: one plan in COMPLETE -> `/status` prints `protections: 1 open of 1 tracked`.
- Impact: plausible wrong actions: the owner closes a healthy position by hand to be allowed to update (cost plus a divergence and SAFE_MODE), or learns to use `--force-live` routinely, which also skips the check when an entry really rests. During a ban (G-2005) the gate clear needs a stop that this rule forbids.
- Why tests miss it: no test ties the runbook rule to the `/status` count.
- Remediation: print the count of AWAITING_FILL (resting entries) and of non-protected plans separately in `/status`, and state the rule on those.

### G-2005
- ID: G-2005
- Severity: LOW now / MEDIUM mainnet
- Confidence: PROBABLE
- Classification: GAP
- Category: ban / REST gate recovery procedure
- Component: RUNBOOK 10, 21.3; alert wording REST_GATE_BAN_ENTERED
- File: docs/operations/RUNBOOK.md
- Lines: 173-177, 1093-1104 (also src/ops/alert_wording.py:390-394; src/live/config.py:67)
- Rule: O-C a1, D083; KNOWN:25-14-F2 (`rest_gate_cli` has no running-process check)
- Known-prior: G-0700 (the 3-day fallback blocks protective calls) covers the code; this is the procedure.
- Evidence: Section 10 "Binance API degradation" is two lines and does not mention a ban. 21.3: `python -m src.ops.rest_gate_cli status --path STATE_FILE` "run on the host, over ssh"; no container form, no path (the file is `/app/logs/live/rest_gate_state.json` in the `livestate` volume, config.py:67 and RUNBOOK 21.1c); "Stop the trading process first" (but 22.5 forbids the stop while a trade is open, G-2004); "A recorded deadline cannot tell a real Binance ban from the assumed wait: check once by hand before clearing" vs the alert "Start no other traffic to the exchange from this address until the until time has passed" (alert_wording.py:392-393). Nothing says that an IP ban of the host does not block the owner's Binance app / web UI, which is the only place to protect a position while the gate refuses every REST call.
- Expected: a ban procedure: (1) protect or close positions from the Binance app now; (2) how to tell a real ban end (header / message time) from the 3-day fallback; (3) the exact container command to read and clear the gate; (4) when a forced clear is acceptable.
- Actual: the owner must derive these; the two texts contradict each other on probing the exchange.
- Reproduction: read the cited lines; try the 21.3 command on a host built by bootstrap (no project interpreter).
- Impact: with the fallback (no Retry-After) the system is blind and unable to act for up to 3 days; the owner's correct action (UI) is not written down.
- Why tests miss it: S19 runs the CLI in process (`25-14-SUMMARY.md`), never the host command.
- Remediation: a "Ban" section with the four steps; container command forms.

### G-2006
- ID: G-2006
- Severity: LOW now / MEDIUM mainnet
- Confidence: PROBABLE
- Classification: GAP
- Category: restore / rollback with live trading state
- Component: RUNBOOK 11.5, 14.4; deploy/restore.sh
- File: deploy/restore.sh
- Lines: 72-97 (also docs/operations/RUNBOOK.md:239-243, 383-384)
- Rule: RUNBOOK 22.5 / update.sh live guard (WR-04)
- Known-prior: none found
- Evidence: restore.sh runs `up -d postgres`, `pull`, `restore [--force]`, `up -d`; it has no `require_live_stopped` (update.sh:105 has). RUNBOOK 14.4 sends the owner to `deploy/restore.sh` to undo a migration (same host, non-empty database, so `--force`). Neither 11.5 nor 14.4 mentions the live process: a snapshot is up to 24 h old (03:15 UTC timer) or the pre-update dump, while the exchange holds orders, positions and algo legs created later; the `livestate` volume (gate state, spill sentinel) is not part of the backup, so a restore onto a new host is a first install (22.3) that needs `--initialize-gate-state`.
- Expected: a restore section for the live process: stop it (22.5), restore, compare the exchange with the restored intents before the first start, expect SAFE_MODE (UNTRACKED_SYSTEM_ORDER / FOREIGN_ORDER / unknown positions) and protect such positions by hand; restore.sh refuses while `live` runs.
- Actual: none of this is written; a forced restore can run under a live process.
- Reproduction: read restore.sh main(); grep RUNBOOK 11.5 for "live" (no hit).
- Impact: after a restore the system does not know positions opened after the snapshot (no stop supervision by the system, only what the exchange holds); the owner is not warned.
- Why tests miss it: restore tests cover the bundle and empty-target checks, not a live state.
- Remediation: add the live guard to restore.sh and a "Restore with live trading" subsection.

### G-2007
- ID: G-2007
- Severity: LOW now / MEDIUM mainnet
- Confidence: CONFIRMED (logic and code; not observed on a host)
- Classification: DESIGN
- Category: restart policy / unattended hours
- Component: docker-compose `live` service, RUNBOOK 21.1c
- File: docs/operations/RUNBOOK.md
- Lines: 1087 (also docker-compose.yml live service `restart: "no"`; docs/DECISIONS.md D106 Q15)
- Rule: D106 Q15; D079 (fill-driven protection)
- Known-prior: G-2100 (D042 condition 1 premise false since D079), G-1800 (restart refused when a HOLD step fails); KNOWN:RUNBOOK 22.7 (switch is the owner's)
- Evidence: RUNBOOK 21.1c: "With `no`, a host reboot or a daemon restart leaves the live process down, which is the safe default while nothing has been observed." But a start never enables or places an entry by itself (22.2: "entries start disabled at every start"; ENABLE in DEMO only, startup.py:1078-1081), and protection is placed only by a running process after it sees a fill (D079, RUNBOOK 22.5). The stated condition for switching ("after the first clean Demo run") was met on 2026-11-06 (RUNBOOK 22.4).
- Expected (yardstick: logic): the only thing a restart can do is protect; so "down" is the unsafe state whenever an entry rests, and the docs say so when they ask the owner to choose.
- Actual: the trade-off is presented the other way round; after a provider reboot at night a resting GTD entry can fill and stay naked until the owner wakes, reads the heartbeat mail and starts the service.
- Reproduction: reason from the cited lines; failure_scenarios row 1 shows the naked time equals the downtime.
- Impact: unprotected exposure for the whole time the owner is unavailable (sleep, travel) after an unplanned host restart.
- Why tests miss it: compose tests pin `restart: "no"` as the decided value.
- Remediation: owner decision (Owner decisions 2), presented with the correct trade-off.

### G-2008
- ID: G-2008
- Severity: LOW now / MEDIUM mainnet
- Confidence: CONFIRMED
- Classification: GAP
- Category: key rotation / credential compromise
- Component: RUNBOOK, SECURITY_AND_OPERATIONS, DEPLOY_GUIDE 10.6
- File: docs/operations/DEPLOY_GUIDE.vi.md
- Lines: 2243-2262 (absence in docs/operations/RUNBOOK.md and SECURITY_AND_OPERATIONS.md)
- Rule: D042 condition 3 (keys rotated); SECURITY_AND_OPERATIONS 1
- Known-prior: none found
- Evidence: RUNBOOK has no "rotat" outside the ssh key sentence (line 343). DEPLOY_GUIDE 10.6 table: Binance key "quy trình xoay `[CHƯA XÁC MINH]`", Telegram token "quy trình thu hồi và tạo lại `[CHƯA XÁC MINH]`", POSTGRES_PASSWORD "Đổi giá trị trong `.env` không tự đổi mật khẩu đã nằm sẵn trong volume `pgdata`".
- Expected: a procedure for a suspected leak of the live Binance key or the live bot token at any hour: revoke in the Binance UI / BotFather, what the live process does then (AUTH_FAILURE, every REST call fails, the bot is gone), how positions stay protected, how to install the new key (`.env.live`, stop rule 22.5, restart), and the PostgreSQL password trap.
- Actual: none.
- Reproduction: `grep -in rotat docs/operations/RUNBOOK.md`.
- Impact: a plausible wrong action is editing `POSTGRES_PASSWORD` in `.env` (every service then fails to connect; the live start is held at ALEMBIC); a leaked trading key is handled ad hoc.
- Why tests miss it: documentation.
- Remediation: add a key-rotation / compromise section.

### G-2009
- ID: G-2009
- Severity: INFO now / LOW mainnet
- Confidence: CONFIRMED
- Classification: DRIFT
- Category: Demo -> mainnet document
- Component: DEMO_VS_MAINNET.md
- File: docs/operations/DEMO_VS_MAINNET.md
- Lines: 53, 89
- Rule: D085 (owner flipped the flag 2026-10-24)
- Known-prior: none; exchange_facts lane row F48 repeats the same wrong state
- Evidence: DVM-14: "`AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` stays False until the owner records a DECISIONS row." Code: `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED: Final[bool] = True` with the comment "the owner flipped this to True on 2026-10-24 (DECISIONS D085, O-3)" (src/risk/margin_check.py:273-282).
- Expected: the Phase 26 input states that the flag is already True on Demo evidence and must be re-checked on the canary.
- Actual: it says False; a canary planner reading it would think the conservative basis is in force.
- Reproduction: grep the flag in src and the doc.
- Impact: small: a wrong True only lets the exchange reject with -2019 (code comment); the document is wrong about the state it hands to Phase 26.
- Why tests miss it: the doc is not gated.
- Remediation: correct DVM-14.

### G-2010
- ID: G-2010
- Severity: INFO now / LOW mainnet
- Confidence: CONFIRMED
- Classification: GAP
- Category: go-live readiness (Demo -> mainnet delta)
- Component: Phase 26 plan, live process LIVE mode
- File: .planning/ROADMAP.md
- Lines: Phase 26 section ("**Plans:** 0 plans")
- Rule: D040, D101, SECURITY_AND_OPERATIONS 2 ("The operator must explicitly enable live execution")
- Known-prior: KNOWN:RUNBOOK 22.7 ("Which later phase owns strategy-driven DEMO signals (D101) is not named"); G-0901 (no research candidate can pass)
- Evidence: `_enable` returns unless `ports.mode is Environment.DEMO` (src/live/startup.py:1078-1081), and no other path enables entries in LIVE mode, so a LIVE process can never place; the only `SignalSource` is `DemoSmokeSignalSource`, registered in DEMO only (src/live/smoke_injection.py:298, D101). Phase 26 criterion 5 asks for "a pre-registered number of trades with the operator watching", with zero divergences.
- Expected: the go-live gate names what must exist before the first real-money order: a LIVE enable path, a signal source for LIVE, the owner's watch window, and how "zero divergences" is reachable given G-0500.
- Actual: none of these is planned; the delta list below is the inventory.
- Reproduction: read the cited code and the Phase 26 section.
- Impact: planning only; safe today (fail closed).
- Why tests miss it: not a code defect.
- Remediation: carry the inventory below into the Phase 26 plan.

## Demo -> mainnet delta (inventory, not findings)

Flags / config that must change or be decided before a real-money order:
- `LIVE_ORDERS_DISABLED` / enablement: LIVE mode has no enable path at all (`startup.py:1078-1081`); the Phase 26 `enable()` conditions (passing candidate, paper exit gate, Demo campaign, minimum capital, WR registry) are unbuilt.
- `LIVE_NET_PNL_SEMANTICS_VERIFIED=False` (src/analytics/live_outcomes.py:80), `FUNDING_SOURCE_VERIFIED=False` (src/risk/daily_loss.py:72), `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED=True` on Demo evidence only (G-2009).
- `NOT_CONFIGURED`: `rest_gate.ban_end_clock_margin_ms`, `scheduler.duration_summary_interval_ms` (config/execution/execution-limits-v1.toml:80-84, 121-125).
- `restart: "no"` on the live service (G-2007); separate DB owner / application roles (G4-033); `.env.live` with `BINANCE_LIVE_*` and `LIVE_RUNTIME_MODE=LIVE`, an IP-restricted key without withdrawal.
- Signal source for LIVE: none (D101).
- Daily stop: `enforce_daily_state` has no caller (G-0403): the DAILY_STOP alert the docs list (SECURITY_AND_OPERATIONS 5) never fires.

First exercised with real money (no Demo observation, per DEMO_VS_MAINNET.md): partial fills (DVM-03, P3), slippage / depth (DVM-02), GTD terminal status (DVM-22, A2), funding fees (DVM-12), a real 418/429 and the queue order after it (DVM-28..31, never provoked), the emergency close and the ladder timeouts (RUNBOOK 3 line 49), a stop rejected after acceptance (DVM-33), a stale-feed SAFE_MODE, the user-data 24 h cut-off (DVM-27), short / higher-tier liquidation price (DVM-15), mainnet `-2013` lag after placement (DVM-19), the heartbeat and the compose service on a host (24-OWNER-RUNBOOK B-E all NOT_OBSERVED), `/status`, `/disable_entries`, `/close` as typed commands (RUNBOOK 22.6).

What the system cannot do without the owner: approve and confirm any entry; leave SAFE_MODE (any reason, including benign one-tick ones, G-0500/G-0501); clear the REST gate (ssh); end CLOSE_FAILED after a manual close (needs a database edit, G-1801); close a position the system lost (G-0300) or whose close is PENDING_UNKNOWN (G-0301); restart the live process after a host reboot (G-2007); fix an unrestorable plan row (RUNBOOK 21.6 step 3, manual database correction). With the owner asleep or travelling, positions rely on the exchange-side stop when one was placed; a resting entry that fills while the process is down has none.

## Owner decisions

1. Second alert channel (G-2003). Example: Telegram down 02:00-07:00, an ETHUSDT position of 0.5 ETH at 3000 USDT goes naked at 02:10 (G-0300 case). Option A: keep Telegram only (owner learns at 07:00; a 5 % adverse move = 75 USDT on a 500-1000 USDT account). Option B: make the live liveness probe fail while a plan is UNPROTECTED / CLOSE_REQUIRED / CLOSE_FAILED or a CRITICAL alert is undelivered, so healthchecks.io (e-mail / SMS) carries it within period + grace (about 3 min with 60 s / 120 s).
2. Live restart policy (G-2007). Option A `restart: "no"`: after a 03:00 provider reboot, a resting entry that fills at 03:20 has no stop until the owner restarts (e.g. 07:30). Option B `unless-stopped`: the process restarts within seconds and protects the fill; a refused start still holds (21.1c). Decide knowing that a start never places an entry.
3. Stop rule for updates (G-2004): whether a protected open position may stay open across a planned stop (the exchange holds its stop) or whether the owner wants every trade closed first.

## Open Questions

- (M12) What exactly `restore --force` does on a non-empty database (`src/ops/backup.py:746-770`): fail or overwrite? Decides how dangerous G-2006 is.
- (M06) Is the `livestate` volume included in any backup? Not found; if not, a host loss always ends in a first install.
- (X10 / exchange_facts) Row F48 of `lanes/exchange_facts.md` states the flag stays False; the code says True since D085 (G-2009).
- (M08) An explicit operator "enter SAFE_MODE" command does not exist (RUNBOOK 2 step 1 "Set SAFE_MODE"); `/disable_entries` is the nearest.
- Telegram approval / confirm cards were not re-read here (telegram_alerts lane).
- Healthchecks.io notification channels and the owner's period/grace for the live check are owner-side and NOT_OBSERVED (24-OWNER-RUNBOOK E1-E3).

## DONE
