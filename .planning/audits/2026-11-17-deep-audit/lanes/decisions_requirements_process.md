# Lane X05: decisions_requirements_process

## Scope

Process and bookkeeping view of the documented intent, snapshot `55885b9`: `docs/**` (except
`docs/research/experiments/**`), `AGENTS.md`, `.planning/{PROJECT,REQUIREMENTS,ROADMAP,STATE}.md`,
phase `*-OWNER-*`, `*-DEFERRED*`, `*-VERIFICATION.md`, `19-OWNER-GAPS.md`, and the discussion logs
of Phases 11-15, 17, 18, 23, 25 (not read by X09). Soundness of decisions = X09, exchange facts =
X10: not repeated here. (Sections below are appended as each file group is finished.)

## Working notes (partial run; replaced by the final sections when the lane is finished)

- [done] REQUIREMENTS.md read in full; ROADMAP progress table and phase checkboxes read; all `*-VERIFICATION.md` front-matter statuses listed; `config/execution/execution-limits-v1.toml` + README + loader key classes read.
- Candidate finding A (DRIFT, LOW): ROADMAP progress table rows 21 ("5/16 In progress (wave 1 done)") and 22 ("0/TBD Not started") while both have 16/16 summaries and a VERIFICATION (human_needed); STATE.md `last_updated` 2026-11-07, no mention of D110-D114 / the 2026-11-15 smokes; phases 16, 19, 24 have no VERIFICATION.md; phases 13.1 and 18 are ticked `[x]` with status human_needed.
- Candidate finding B (DRIFT, LOW): `config/execution/README.md` lines 3, 9, 16, 36, 155 ("nineteen keys", "four are filled", "`stale_feed.max_user_data_silence_ms` is REQUIRED and not answered ... live path keeps refusing") vs the values file (23 keys, 21 set, silence = 420000 by D091).
- Candidate finding C (DRIFT, LOW): REQUIREMENTS BKTS-03 ticked Complete while its own note and `src/backtest/report.py:58` say "not computed (BKTS-03 pending)"; EXEC-02 note "not composed into a running process" stale since Phase 24; footer "Last updated" stops 2026-10-18.
- Remaining: discussion logs 11-15, 17, 18, 23, 25; DECISIONS D040-D114 implementation spot checks; canonical docs vs code; Phases 16-24 success criteria; consolidated owner register.

- [done] Discussion logs of Phases 11, 12, 13, 13.1, 14, 15, 17, 18, 23, 25 read in full; `18-DEC-O-18-01.md`, `25-OWNER-DECISIONS.md` (head + answer lines) read. All ten logs say `--auto`, "no questions asked / recommended option chosen". D072's 27 numbers (418 wait 259200 s, 429 wait 120 s ...) = "the reviewer's two texts" accepted by the owner line "dùng đúng câu trên, làm đi", the sentence itself drafted by the orchestrator. Phase 25 Q-AB..Q-L: all answered by one line "theo bạn recommend cho tất cả đi".
- [done] STATE.md "Open user decisions (2026-10-07)" still lists D055 OPEN, G4-042, G4-040, T-06 as open (decided by D079, D088, D099, D089); "Pending Todos" still says the WS-connect gap blocks the soak.
- [done] Success-criteria probes (own greps in the snapshot): P18 c1 "feeds fold_fills": `fold_fills` has no caller in src outside `fill_monitor.py`; P21 c2 "At DAILY_STOP pending entries are cancelled": `enforce_daily_state` has no caller; P21 c3: no `.mark_placed(`/`.mark_open(` call in src/scripts; P24 c4: `docker-compose.yml:232` live `restart: "no"`, host not observed. Hold: P16 c2 (`paper_ws.py:377,474` await), P16 c6 (`runtime_config.py:68`), P17 c3 (`manager.py:1230,1280,1323` consume -> snapshot -> mark_sent -> place), P19 c1 (`manager.py:958-960`), P19 c2 (`pre_placement.py:39-56`), P20 c1 (`classify.py:108,133`), P20 c3 (`safe_mode.py:592-601` operator_id), P22 c1 (`symbol_config_guard.py:168,201`), P22 c4 (`manager.py:1064-1071`), P23 c1 (`telegram_callbacks.py:294-298`).
- [done] EXECUTION_SPEC stale lines: 145 ("Both keys are NOT_CONFIGURED ... live path refuses"), 251 (D-11 numbers NOT_CONFIGURED, owner-open), 275 ("Nothing calls them from a running process yet: that composition is Phase 24 ... until Phase 24 wires it the operator uses RUNBOOK section 3").
- D092 checked: `src/live/enablement.py:234-237` raises `LiveEnableForbidden` for a non-DEMO mode.


(Run 2 continues below. The working notes above are the partial run and are kept as written.)

## Coverage

| File | Level | Note |
|---|---|---|
| `docs/DECISIONS.md` | DEEP_READ (Status column D040-D114; full text of D055, D056, D058, D072, D079-D083, D089, D091, D092, D096, D113, D114) | soundness of the rows is X09; here: draft/OPEN status, contradictions, implementation spot checks |
| `docs/trading/EXECUTION_SPEC.md` | NORMAL_READ (sections 6, 10; stale lines 145, 251, 275) | |
| `docs/trading/RISK_MANAGEMENT.md` | NORMAL_READ (daily stop section, lines 110-130) | quantization and sizing are X09/core lanes |
| `docs/operations/RUNBOOK.md` | NORMAL_READ (restart policy 688-723, 1087; section 22.6-22.8) ; rest METADATA_ONLY | operator walk-through is X08 |
| `docs/integration/BINANCE.md` | METADATA_ONLY | exchange facts = X10 (G-2200, G-2202) |
| other `docs/**` (GLOSSARY, CONFIGURATION, DATA_MODEL, TESTING_STRATEGY, DOC_STATUS, SOURCES, research/* except experiments) | METADATA_ONLY | not read line by line in this lane |
| `AGENTS.md` | NORMAL_READ | AGENTS.md:112 premise is X10 G-2201 |
| `.planning/PROJECT.md` | METADATA_ONLY | |
| `.planning/REQUIREMENTS.md` | DEEP_READ | |
| `.planning/ROADMAP.md` | NORMAL_READ (phase list, progress table 1585-1594, success criteria of Phases 16-25) | |
| `.planning/STATE.md` | NORMAL_READ (front matter, cross-phase status, Pending Todos, Open user decisions 665-680) | |
| `*-VERIFICATION.md` (all phases) | NORMAL_READ front matter; 18 and 21 body read | 16, 19, 24 have none |
| `19-OWNER-GAPS.md` | NORMAL_READ | |
| `25-OWNER-DECISIONS.md` | NORMAL_READ (all questions and answer lines) | |
| `21/22/24-OWNER-DECISIONS.md`, `24-LIMITS-CHECKPOINT.md` | METADATA_ONLY | read by X09 (G-2103) |
| `*-DEFERRED*` / `deferred-items.md` | METADATA_ONLY | used through the KNOWN tags of other lanes |
| Discussion logs 11, 12, 13, 13.1, 14, 15, 17, 18, 23, 25 | DEEP_READ | the phases X09 did not read |
| `18-.../decisions/18-DEC-O-18-01.md` | NORMAL_READ | source of D072 |
| `config/execution/execution-limits-v1.toml`, `config/execution/README.md` | NORMAL_READ | |
| `.planning/phases/24-.../evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T{083259,104211}Z.json` | NORMAL_READ (outcome, step lines, search for durations) | |
| `src/live/enablement.py:219-280`, `src/execution/manager.py:1758-2030`, `.github/workflows/ci.yml:30-75`, `docker-compose.yml:232` | NORMAL_READ | spot checks of D092, D113, P17 c5, D106 |

## Verified Safe Areas

| Rule / behaviour | What I checked | Where | Why it holds |
|---|---|---|---|
| D092: LIVE cannot be enabled through the Demo kill-gate shortcut | `enable_demo` refuses a non-DEMO mode | `src/live/enablement.py:234-237` | raises `LiveEnableForbidden` before any state write |
| D113 reread is implemented as recorded | loop `for attempt in range(1 + _CONFIRM_REREADS)`, sleep `_CONFIRM_REREAD_DELAY_SECONDS` | `src/execution/manager.py:1758-1759, 1997-2030` | 3 rereads, 0.5 s apart, reads only (no place/cancel in the loop) |
| D089 / D091 / D114 values are the ones recorded | values lines 61, 65, 83 and provenance lines 102, 106, 124 | `config/execution/execution-limits-v1.toml` | 23 keys, 21 set, 2 `NOT_CONFIGURED` (`rest_gate.ban_end_clock_margin_ms`, `scheduler.duration_summary_interval_ms`), both documented as optional refinements that never refuse the start |
| P17 c5: PG tests run against a throwaway `_test` database in CI | service container and env | `.github/workflows/ci.yml:32-34, 72` | `TEST_DATABASE_URL=...trading_test` |
| Success criteria that held when checked in code (SUMMARY/VERIFICATION ignored) | P16 c2, P16 c6, P17 c3, P17 c5, P19 c1, P19 c2, P20 c1, P20 c3, P22 c1, P22 c4, P23 c1 | citations in the working notes above | each has a production caller in the composed path |
| No DECISIONS row D040-D114 is a draft while code depends on it | Status column of every row | `docs/DECISIONS.md:44-118` | every row reads Accepted/DECIDED; D055 is closed by D079; D058 keeps OQ-1 open, but OQ-1 concerns backtest evidence only and no live code depends on it |
| No later row silently contradicts an earlier one in D040-D114 | supersessions read: D055→D079, D062→D064, D089 (5000)→D096 (30000), D091 sets key 14 | `docs/DECISIONS.md` | each later row names the row it changes (the soundness of D096 is X09 G-2106) |

## Decision review

(Process view only; the trading soundness of these rows is in X09, the exchange facts in X10.)

| Decision / doc rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D072 "DECIDED by the user ... the executor chose no value" | DOUBTFUL (label) | record vs its source | `18-DEC-O-18-01.md:12-14`: the 27 values are "the reviewer's two texts", accepted by "dùng đúng câu trên, làm đi"; no value was shown with its consequence (418 → 259200 s, X10 owner item 3) |
| Verification convention "VERIFIED (library level)" as closure of a ROADMAP criterion | WRONG as closure | outcome in the composed process | 4 of 18 checked criteria do not hold in the running process (G-1604) |
| D056 "implementation NOT done now ... belongs to Phase 24 and 26" | DOUBTFUL | later rows | D102 made the post-enable health reading journal-only for DEMO; policy (1) for LIVE ("no new entry while DEGRADED") has no implementation yet (live_composition G-0600) |
| D058 mark-price fail closed, OQ-1 kept open | SOUND as split | scope | OQ-1 is a backtest-evidence question; listed in the register (R-29) |
| D106 / RUNBOOK:1087 `restart: "no"` "until the owner has seen the first clean Demo run" | DOUBTFUL | condition vs facts | clean runs exist (2026-11-06; 2026-11-15 21/21); 25 Q-E re-tied the switch to the end of the Phase 16 soak; the condition text was not updated (consequence: X09 G-2100) |
| 19-OWNER-GAPS status convention ("OPEN means no decision exists and the code does not pretend one does") | SOUND convention, stale content | register vs DECISIONS | O-04 still OPEN although D089/D091/D114 set the numbers (G-1600) |
| Phase 25 owner packet (options + "Assistant recommendation (not a decision)" + answer line) | SOUND format / DOUBTFUL use | owner process | alternatives were shown, but all ten questions were answered by one blanket line, including N = 3 trips/week picked by the assistant (G-1603) |
| D113 / D114 evidence statements | DOUBTFUL (record) | repo state | the evidence files are committed now; the 886 ms basis of D114 is not in them (G-1605) |
| D092 Demo-only kill-gate source | SOUND | code | LIVE refused (`enablement.py:234-237`); the LIVE kill-gate producer remains to be built (register R-27) |

## Findings

### G-1600 — Planning status records disagree with each other and with DECISIONS: open items that are decided, phases ticked complete without a passed verification, a stale progress table
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED (text)
- Classification: DRIFT
- Category: bookkeeping
- Component: `.planning/ROADMAP.md`, `.planning/STATE.md`, `19-OWNER-GAPS.md`
- File / Lines: `.planning/ROADMAP.md:50,55,1585-1594`; `.planning/STATE.md:9,606,614,665-680`; `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md:18`
- Rule: AGENTS.md "Source of truth" (STATE/ROADMAP are "live, hand-kept")
- Known-prior: none
- Evidence: ROADMAP:1590 `| 21. Account Equity + Daily Loss from Binance | 5/16 | In progress (wave 1 done) |` and :1591 `| 22. ... | 0/TBD | Not started |` while both phases have 16/16 summaries and a VERIFICATION (human_needed). ROADMAP:50 and :55 tick 13.1 and 18 `[x]` while their VERIFICATION status is `human_needed`; Phases 16, 19 and 24 have no VERIFICATION file. STATE.md:9 `last_updated: "2026-11-07..."` (no D110-D114, no 2026-11-15 smokes); STATE.md:665-677 "Open user decisions (2026-10-07)": "D055 execution model ... OPEN" (closed by D079), T-06 thresholds (set by D089/D091), G4-040 (decided by D099), G4-042 (D088); STATE.md:606,614 "WS-connect gap ... blocks soak start" although the soak ran. 19-OWNER-GAPS.md:18 O-04 "OPEN | Keys, all `NOT_CONFIGURED`" although D089 set them.
- Expected: one current list of what is open.
- Actual: three registers, each partly stale, none matching DECISIONS.
- Reproduction: grep the cited lines.
- Impact: the owner and the next agent cannot tell from the planning files what still needs a decision; the consolidated register below had to be rebuilt from the lane files.
- Why tests miss it: `verify_decision_alignment.py` gates AGENTS.md/PROJECT/STACK bytes, not the content of STATE/ROADMAP/OWNER-GAPS.
- Remediation: retire STATE "Open user decisions" and 19-OWNER-GAPS section 1 in favour of one register (the one below can seed it); refresh the ROADMAP progress table from the phase directories.

### G-1601 — Canonical docs state live behaviour that the code does not have (daily stop cancels resting entries "exactly as in live") and keep "NOT_CONFIGURED / not composed" statements that are no longer true
- Severity: now LOW / mainnet MEDIUM (the RISK_MANAGEMENT statement over-states a safety behaviour the operator relies on)
- Confidence: CONFIRMED (text; the missing wiring is CONFIRMED by live_risk_state G-0403)
- Classification: DRIFT
- Category: canonical docs vs code
- Component: `docs/trading/RISK_MANAGEMENT.md`, `docs/trading/EXECUTION_SPEC.md`, `config/execution/README.md`
- File / Lines: `docs/trading/RISK_MANAGEMENT.md:115,125`; `docs/trading/EXECUTION_SPEC.md:145,251,275`; `config/execution/README.md:3,9,16,36,155`
- Rule: D031 (canonical docs outrank planning)
- Known-prior: the missing wiring is KNOWN (25 Q-J, plan 25-28 not executed; live_risk_state G-0403). That the canonical doc states the opposite is recorded nowhere.
- Evidence: RISK_MANAGEMENT:115 "cancel pending entry orders, so no working entry opens a new position (... resting entries are cancelled on DAILY_STOP in backtest exactly as in live)"; :125 "Daily stop: the resting entries are cancelled with the expiry trigger `daily_stop`". `enforce_daily_state` has no caller in `src` (G-0403; `21-VERIFICATION.md:158` "no scheduler calls it yet"). EXECUTION_SPEC:145 "Both keys are `NOT_CONFIGURED` ... and the live path refuses" (set by D089); :251 the D-11 numbers "are `NOT_CONFIGURED`" (set by D089); :275 "Nothing calls them from a running process yet: that composition is Phase 24" (composed in `src/live/`). config/execution/README.md:3 "the nineteen safety limits", :9 "(four are filled)", :155 "`stale_feed.max_user_data_silence_ms` is REQUIRED and not answered ... The live path keeps refusing", against the values file (23 keys, 21 set, silence 420000 by D091).
- Expected: canonical docs describe the code at the snapshot; a safety behaviour that is not wired is marked as such.
- Actual: one over-statement in the direction that matters (daily stop) and several under-statements.
- Reproduction: grep the cited lines; `grep -rn enforce_daily_state src`.
- Impact: an owner who reads RISK_MANAGEMENT believes a resting entry is cancelled when the day's loss limit is reached; on mainnet with placement enabled it can still fill after the stop (G-0403). The stale README/SPEC lines make the owner believe the live path still refuses on unset keys.
- Why tests miss it: doc gates compare docs with planning files, not with call graphs.
- Remediation: mark RISK_MANAGEMENT daily-stop text "live: not wired until plan 25-28"; refresh EXECUTION_SPEC 145/251/275 and the README key count and status.

### G-1602 — REQUIREMENTS: BKTS-03 is "Complete" while its bootstrap intervals are not computed; EXEC-02 and the footer describe a pre-Phase 24 state
- Severity: now LOW / mainnet LOW
- Confidence: CONFIRMED
- Classification: DRIFT
- Category: requirements traceability
- Component: `.planning/REQUIREMENTS.md`, `src/backtest/report.py`
- File / Lines: `.planning/REQUIREMENTS.md:47,64,142,149,181-183`; `src/backtest/report.py:58`
- Rule: REQUIREMENTS traceability note (`:171`, evidence-level review)
- Known-prior: the note on line 47 mentions the pending part itself
- Evidence: `:47` `- [x] **BKTS-03**: Reports show ... bootstrap intervals ...` and `:142 | BKTS-03 | Phase 16 | Complete |`, while `src/backtest/report.py:58` says "not computed (BKTS-03 pending)". `:183` "EXEC-01, EXEC-02, EXEC-05 and OPS-02 stay Pending (... not composed into a running process)"; Phase 24 composed them. Footer `:181` "Last updated: 2026-09-30".
- Expected: a requirement is Complete only when every clause holds.
- Actual: Complete with a clause the code itself calls pending.
- Impact: low; it inflates the completed count. (The research run's G2/G3 verdicts use their own bootstrap code, X09 G-2101; the gap is the report requirement.)
- Why tests miss it: no test reads REQUIREMENTS.
- Remediation: set BKTS-03 to Partial; refresh the EXEC-02 note and the footer.

### G-1603 — Phases 11-15, 13.1, 17, 18, 23 and 25 were discussed in `--auto` mode: no question reached the owner; money-relevant choices made there were never shown with their consequence in numbers, and one of them is labelled "DECIDED by the user"
- Severity: now LOW / mainnet MEDIUM
- Confidence: CONFIRMED (each log says so in its header)
- Classification: DESIGN (decision process)
- Category: governance
- Component: discussion logs; DECISIONS D043-D054, D072; `25-OWNER-DECISIONS.md`
- File / Lines: `11-DISCUSSION-LOG.md:10`; `12-DISCUSSION-LOG.md:9,21,30`; `13-DISCUSSION-LOG.md:8`; `13.1-DISCUSSION-LOG.md:5`; `14-DISCUSSION-LOG.md:8`; `15-DISCUSSION-LOG.md:8`; `17-DISCUSSION-LOG.md:10`; `18-DISCUSSION-LOG.md:3`; `23-DISCUSSION-LOG.md:8,13`; `25-DISCUSSION-LOG.md:8,13`; `18-.../decisions/18-DEC-O-18-01.md:8,12,14`; `docs/DECISIONS.md:76` (D072); `25-OWNER-DECISIONS.md:82,111,136,169,198,215,244,273,303,331`
- Rule: charter section 2.7; X09 G-2103 (this finding extends it to the phase discussions X09 did not read)
- Known-prior: self-declared in each log; the consequence is recorded nowhere.
- Evidence:
  - `11-DISCUSSION-LOG.md:10` "Mode: `--auto --all`; no AskUserQuestion was used. The recommended option was chosen for each question." The other nine logs say the same ("no questions asked", "recommended option auto-selected for every question"). Money/safety choices made there: Phase 11 research thresholds ("100 trades, lower-95% ..."); Phase 12 cost formula "adverse edge, both legs with slippage" (`12-DISCUSSION-LOG.md:21`) and the slippage rates (`:30`) — the adverse-edge sizing is why a stopped-out trade loses about 0.30 % instead of the nominal 0.5 % (core_strategy_risk G-0102), a consequence shown nowhere; Phase 14 fill rule and DAILY_STOP cancel in the simulator; Phase 15 geometry; Phase 18 thresholds; Phase 23 money block and its SHADOW exemption.
  - D072 Status: "DECIDED by the user (... the executor chose no value)". Its source, `18-DEC-O-18-01.md:14`: "The values below are the reviewer's two texts as accepted by that line", the line being `:8` "dùng đúng câu trên, làm đi" ("use exactly the text above, do it"); `:12` adds the 418/429/cap split (259200 s / 120 s / 259200 s), from the reviewer's second text. Nothing shows what 259200 s costs (binance_adapters G-0700: next REST call on day 4).
  - Phase 25: ten questions Q-AB to Q-L with options and an "Assistant recommendation (not a decision)", all answered by one line "theo bạn recommend cho tất cả đi, recommend cho tôi luôn cả N nữa" ("go with your recommendation for all of them, and recommend N for me too"); so N = 3 owner round trips per week (`:82`) was picked by the assistant.
  - Positive cases (alternatives with consequences shown): 25-OWNER-DECISIONS option lists; 19-OWNER-GAPS probe outcomes; D068, D078, D085 O-1, D096 (X09 list).
- Expected: a value that moves money is put to the owner with at least one worked example per option before it is called the owner's.
- Actual: in these ten phases no question reached the owner; for D072 the label says the opposite of its own source.
- Reproduction: read the header line of each log.
- Impact: the owner cannot see which numbers he really chose. Together with G-2103: almost no money/safety parameter was chosen by the owner after seeing its consequence.
- Why tests miss it: not testable.
- Remediation: register item R-30 (re-present the money numbers); reword D072 to "accepted by the user from the reviewer's text".

### G-1604 — ROADMAP success criteria were closed as "VERIFIED (library level)"; in the composed process 4 of 18 checked criteria do not hold, and Phase 18 is ticked Complete on one of them
- Severity: now LOW / mainnet MEDIUM (process; the money consequences are in G-0403 HIGH-mainnet, G-0401, G-0306)
- Confidence: CONFIRMED (call-site searches; each gap is confirmed by the lane cited)
- Classification: GAP (process: a criterion closed by redefining it)
- Category: plans vs outcome
- Component: `.planning/ROADMAP.md` Phases 16-24, `*-VERIFICATION.md`
- File / Lines: `.planning/ROADMAP.md:880` (P18 c1 "It feeds `fold_fills` and reconciliation"), `:1106` (P21 c2 "At DAILY_STOP, pending entries are canceled"), `:1107` (P21 c3 "Portfolio caps count resting entries and approved-but-unplaced plans"), `:1283` (P24 c1 "kill-gate event → `enable()`"), `:1292` (P24 c4 "under Docker Compose with restart policies"); `18-VERIFICATION.md:50,58,65`; `21-VERIFICATION.md:4,101,158`
- Rule: ROADMAP success criteria; AGENTS.md "A claim from a subagent ... is a lead, not a fact"
- Known-prior: each gap is known somewhere (P21 c2 = 25 Q-J / plan 25-28; P21 c3 = R-21 / plan 25-23; P24 c1 = D092; P18 c1 = exec_protection G-0306). Not recorded: that the ticks and scores over-count.
- Evidence: 18-VERIFICATION:50 "Criterion 1 ... feeds `fold_fills` ... **VERIFIED** (library level ...)" and :65 "'Feeds `fold_fills` and reconciliation' is proven through rig and replay tests, not in a running process (Phases 24 and 25)"; Phase 24 then used `FillEvent` only (`fold_fills` has no caller in `src`, G-0306). 21-VERIFICATION:4 "score: 3/3 roadmap success criteria verified at library level (0 behavior-unverified, 0 gaps)" and :158 "entry cancels are retried on each later call (`enforce_daily_state`); no scheduler calls it yet". P21 c3: `mark_placed` has one caller (the sweep) and `mark_open` none (G-0401), so a placed plan stays RESERVED. P24 c1: nothing writes the KILL_GATE state (D092; DEMO uses an explicit value, LIVE has none). P24 c4: `docker-compose.yml:232` live `restart: "no"`; no host observed.
- Tally (own checks, SUMMARY/VERIFICATION ignored): 18 criteria across Phases 16-24. Held 11; did not hold in the composed process 4 (P18 c1, P21 c2, P21 c3, P24 c1 for LIVE); not observable here 1 (P24 c4); partly 2 (P24 c2 restart/rehydrate, passed on Demo only on the second 2026-11-15 run; P23 c2 money block, SHADOW exempted by owner decision R-1). Claims that did not hold: 4/18 = 22 %, all four scored VERIFIED.
- Expected: a criterion that names runtime behaviour is closed when the running process shows it; "library level" is reported as PARTIAL.
- Actual: library-level proofs are scored VERIFIED, and the composition phase did not re-open them.
- Reproduction: `grep -rn "fold_fills\|enforce_daily_state\|\.mark_open(" src` in the snapshot.
- Impact: the gaps that matter most for money (daily stop, reservations) were found only by the Phase 25 strict-xfail twins and by this audit; more library-level closures may exist among criteria not sampled.
- Why tests miss it: unit and rig tests call the library directly (`tests/test_live_alerts_wiring.py:320` calls `enforce_daily_state` itself).
- Remediation: re-score every "VERIFIED (library level)" criterion of Phases 17-24 as PARTIAL until a composed-process test or Demo evidence exists; add a gate "every safety function named in a criterion has a production caller".

### G-1605 — D113, D114 and RUNBOOK 22.6 still call the 2026-11-15 evidence "untracked"; D114's measured basis (886 ms) is not in the committed evidence
- Severity: now INFO / mainnet INFO
- Confidence: CONFIRMED
- Classification: DRIFT
- Category: evidence trail
- Component: `docs/DECISIONS.md` D113, D114; `docs/operations/RUNBOOK.md`
- File / Lines: `docs/DECISIONS.md:117,118`; `docs/operations/RUNBOOK.md:1197,1222`; `.planning/phases/24-live-runtime-composition-demo/evidence/09-DEMO-REHEARSAL-EVIDENCE-smoke-20261115T104211Z.json`
- Rule: AGENTS.md (evidence under the phase `evidence/` directory)
- Known-prior: none
- Evidence: D113 "the evidence file ... is untracked"; D114 "(..., untracked, outcome COMPLETE ...)"; RUNBOOK:1197 "not committed". Commit 55885b9 added both files. `grep -c "886\|LIVE_TASK_DURATION\|duration"` on the 104211Z file returns 0; D114 itself says the figure "comes from a read-only query of those journal rows made on 2026-11-15 by the agent that prepared this change".
- Expected / Actual: a DECISIONS number rests on evidence that is in the repo; here its only measured input is an agent's query of a database that is not.
- Impact: small (D114 is an alert-only bound), but it is G-2103 in miniature.
- Why tests miss it: no test reads evidence references.
- Remediation: correct "untracked" in three places; attach the duration rows or state the number is not reproducible.
<!-- FINDINGS-END -->

## Owner decisions

### Consolidated register of open owner items (all finished lanes, de-duplicated)

Built from the "Owner decisions" sections of the 14 lane files that end with `## DONE` at the time
of writing (backtest_research_analytics, binance_adapters, core_strategy_risk,
decisions_trading_soundness, exchange_facts, exec_gapfill, exec_placement, exec_protection,
failure_scenarios, live_composition, live_risk_state, paper_runtime, reconcile_safemode,
telegram_alerts), plus the still-open items of `19-OWNER-GAPS.md`, `25-OWNER-DECISIONS.md` and the
`NOT_CONFIGURED` keys. Lanes not finished (data_persistence_db, evidence_reproducibility,
ops_deploy_security, scripts_tooling, mutation_probe, prior_findings_closure_a, operator_golive_gap)
are not included. The options are the lanes' own; nothing is picked here. Numbers are the lanes'
examples (equity 1000 USDT unless said otherwise; 1R = 5 USDT at 0.5 % risk).

**A. Protection of an open position (largest money effect on mainnet)**

| ID | Decision | Source | Options, with a numeric example | If left as is |
|---|---|---|---|---|
| R-01 | Exchange-side protection while the process is not running (stop placed only after the fill; live `restart: "no"`) | X09 O-1 (G-2100); X10 1 (G-2201); failure_scenarios O-1 (G-1800); D106, RUNBOOK:1087, 25 Q-E | Example: long 0.004 BTC at 80,000, stop 1.5 % (risk 4.8 USDT); host offline 20 min, entry fills, price -6 %: loss about 19.2 USDT, bounded only by isolated margin (about 88 USDT at 5x on a 440 USDT position). (a) pre-place a reduce-only STOP_MARKET with the entry (Demo-accepted, mainnet unobserved); (b) probe and use `countdownCancelAll` for resting entries; (c) `restart: unless-stopped` plus a short entry lifetime, risk accepted in writing; (d) entries only while the owner is reachable; for a DB not reachable at start: retry N minutes / exit and let a delayed restart retry / keep the hold | a filled entry has no stop for as long as the process is down; the restart policy is "no" although its stated condition (one clean Demo run) has been met |
| R-02 | One negative by-id read of a confirmed stop → market close + SAFE_MODE | X09 O-5 (G-2104); exec_gapfill 1 (G-0250); exec_protection 5 | Example: long 0.010 BTC from 60,000, stop 59,000, price 59,600; one false "not found" (seen on Demo 2026-10-22, 2026-11-01, 2026-11-15) → sells at market, about -4 USDT plus fees, SAFE_MODE. (a) keep one read; (b) 2-3 consecutive negatives plus the open-algo listing (a really lost stop is acted on 15-45 s later); on restart with an unknown stop history: close (today) or read the stop first | each false negative closes a healthy trade and stops trading until a manual exit |
| R-03 | Emergency close after a lost or refused answer: may a second reduce-only close be sent? | X10 2 (G-2203); exec_protection 1 (G-0301); failure_scenarios O-2, O-3 (G-1801) | Example: 0.02 BTC at 60,000, 5x isolated (240 USDT margin), no stop; close answered -4131 in a fast market or lost. A: one close, wait for a human (worst case the 240 USDT margin); B: new close under a new id after a documented definitive refusal; C: B plus after N (say 3 in 30 s) "not found" polls. Also: may the system mark the plan FLAT after the owner closed by hand (two zero position reads), and how long between first alert and the owner's action is acceptable | the position stays open without a stop until the owner acts; a manual close still needs a database edit |
| R-04 | `protection.max_unprotected_ms` = 180000 and the other D089 limits (entry timeout 15 min, UNKNOWN grace 30 min, reconcile tick 15 s) | X09 O-4 (G-2103); exec_protection 2 | Example: 1.5 % adverse move in 3 min on a 1,200 USDT position = 18 USDT against a 5-10 USDT planned risk. Shorter closes sooner but also closes healthy positions during a 120 s 429 pause | numbers derived from the rate-limit pause, not from price risk, stay labelled the owner's |
| R-05 | Take profit below the minimum notional; TP step retry; single-TP fallback (19-OWNER-GAPS O-03); partial-fill remainder (N1) | exec_gapfill 2, 3 (G-0251/0252/0254); exec_protection 3, 4 (G-0302, G-0305); 19-OWNER-GAPS O-03, N1 | Example: min notional 100, TP1 0.003 BTC at 62,000 refused, 0.004 the smallest that passes. (a) keep the stricter rule (small plans never traded, partial fills end in SAFE_MODE); (b) send the reduce-only TP1 anyway (exchange text says reduce-only is exempt) and treat -4164 as the hold; (c) one closePosition TP when TP1 cannot be sized (needs the same backtest rule). Retry a failed read in the TP step (no duplicate risk). Partial fill: cancel the remainder (today) or let it work to GTD. B1: market-close a stopped position whose entry cannot be cancelled for 15 min, or not | a filled position too small for TP1 ends without a take profit and parks the system |
| R-06 | TP1 split fraction is a code constant, not a parameter (EXEC-07 vs D052 item (c)) | 19-OWNER-GAPS O-02 | keep `TP1_QUANTITY_FRACTION` in code, or move it to the hash-locked parameter set (new set + strategy_version) | the split cannot be changed by the registry process |

**B. Exchange limits and connectivity**

| ID | Decision | Source | Options, with a numeric example | If left as is |
|---|---|---|---|---|
| R-07 | 418 ban without Retry-After = 259200 s (3 days) of no REST; `rest_gate.ban_end_clock_margin_ms` is `NOT_CONFIGURED` | binance_adapters 1 (G-0700); X10 3; D072 | Example: ban at 12:00 whose body says it ends 12:02; today the next stop/close can be sent on day 4 at 12:00; with the margin set to 60000 at 12:03. Options: set the margin; lower the fallback with an escalating re-check; an audited "clear" after the owner checked Binance (the CLI `rest_gate_cli clear` exists) | a 2-minute ban can block reconcile and closes for 3 days unless the owner intervenes |
| R-08 | Risk-reducing call during a 429 pause | binance_adapters 2 (G-0701); D081 | Example: 0.01 BTC fills 5 s after a 429; the stop waits up to 115 s; a 1 % move is about 8.4 USDT unprotected. Option: allow one stop / reduce-only close attempt during a 429 (never during a 418), at the risk of turning the 429 into a ban | stops and closes wait up to 120 s after any 429 |
| R-09 | User-data stream halted for good after 7 reconnects / 120 s | binance_adapters 3 (G-0702); 25 Q-K (operator `/resync_stream` chosen) | automatic bounded resync every N minutes vs the manual command | each halt costs the time until the owner sees the alert |
| R-10 | Last-price age 30 s shared by Demo and LIVE | X09 O-7 (G-2106); D096 | 30 s for both, or 5 s for LIVE after a mainnet read-only measurement | a 30 s old last price can pass the marketability check on mainnet |
| R-11 | Re-read the exchange facts from character-exact sources before Phase 25/26 | X10 4 (G-2202) | require `llms-full.txt` + OpenAPI re-read as a gate, or not | seven register entries stay "unknown" though documented; DVM-23 misdescribes -5040 |
| R-12 | Fees paid in BNB on mainnet | live_risk_state 4 (G-0404) | switch BNB fee burn off on the account, or have the system check it at start | the system stops trading after the first fill of each day |

**C. Sizing, caps and the daily stop**

| ID | Decision | Source | Options, with a numeric example | If left as is |
|---|---|---|---|---|
| R-13 | Cluster cap after a same-day gain | core_strategy_risk 1 (G-0101); live_risk_state 2 (G-0400) | Example: day starts 1000, +10 win; next XRP plan sized on 1010 has risk 5.045 > cap 5.000 → refused with nothing open (at 600: 3.03 > 3.00). (a) keep; (b) cap and size on one equity base; (c) cap slightly above one risk unit. (b)/(c) change trade sets and research records | fewer trades after winning days, in live and backtest |
| R-14 | Real risk per trade (position sized for a fill at the far edge of the zone) | core_strategy_risk 2 (G-0102); cause in Phase 12 auto choice (G-1603) | Example at 1000 USDT, "risk 0.5 %": a stop-out loses about 3.05 (Family A), 4.65 (B), 4.47 (C) instead of 5. (a) keep and show real figures on the card and in reports; (b) size at the placed limit price | the stated risk is not the risk taken |
| R-15 | Daily stop semantics and wiring | live_risk_state 1 (G-0403); 25 Q-J (wire-daily-stop, plan 25-28 not executed); G-1601 | Example: two closed trades -9.90 (not stopped), then two open trades of 5 risk each: the day can end about -19.90 (2 %), not -10; a stop at 23:55 UTC is lifted at 00:00 UTC. Options: closed trades only (today); count open risk; rolling 24 h. Wiring: until plan 25-28 runs, a resting entry is not cancelled at DAILY_STOP in the live process | the 1 % daily limit is about 2 % in practice and resting entries survive it |
| R-16 | Reservations that never advance or never end (R-21) | live_risk_state 3 (G-0401); 25 Q-F (ack-then-first-fill, plan 25-23 not executed) | Example: with one position open the second plan is refused (margin counted twice: 882.2 required vs 600 available). An UNKNOWN entry's row blocks its direction until a database edit; option: an audited operator release command | the system is single-position in fact; an UNKNOWN entry blocks a direction indefinitely |
| R-17 | Approved quantity vs a recomputed larger quantity at CONFIRM | exec_placement 1 (G-0202) | Example: card shows 181.9 XRP at equity 1000.00; at CONFIRM equity is 1000.55 → 182.0 → refused QUANTITY_ABOVE_APPROVED and the card is dead. Option: place 181.9 (the approved quantity, risk slightly below budget) | small equity moves kill approvals |
| R-18 | Re-check disable / SAFE_MODE at the last moment of a CONFIRM | exec_placement 2 (G-0201) | Example: CONFIRM for ETHUSDT, 1 s later the kill gate disables or SAFE_MODE starts; today the entry is still sent | an in-flight CONFIRM bypasses a fresh disable |
| R-19 | Small-account viability: BTC at 500-600 USDT, canary 50-100 USDT | X09 O-6 (G-2105); core_strategy_risk 3 (G-0108); D040 | At 500 USDT BTC is tradeable only with stops of about 0.8-2.35 %; the canary cannot trade BTC (min notional); 1R = 2.5-5 USDT; +0.10R edge x 250 trades = 62-125 USDT a year before hosting. Options: accept as a research instrument; drop BTC from the small-account universe; revisit the 60 % utilisation floor (re-read mainnet BTCUSDT min notional first) | expectations not recorded; BTC live trade set differs from backtest |

**D. Runtime supervision and alerts**

| ID | Decision | Source | Options, with a numeric example | If left as is |
|---|---|---|---|---|
| R-20 | Health turning RED after enable (D056 policy (1) not implemented) | live_composition 1 (G-0600) | A: N consecutive NO_TRADE ticks disable entries (N = 2 = 30 s); B: journal only and correct D102. Example: 4 of last 10 REST calls fail at 10:00:15; with A a CONFIRM at 10:00:50 is refused | a degraded process keeps placing if the manager's own checks pass |
| R-21 | Telegram unreachable at start; silent task failures; reconcile pause during placement | live_composition 2, 3, 4 (G-0603, G-0602, G-0604) | hold vs continue in SAFE_MODE retrying the bot; alert after 3 failed runs (45 s) or 20 (5 min); cap the reconcile skip at 2 ticks (30 s) or not (a 70 s placement skips 5 ticks) | a restored position may be left to its exchange stop only; silent failures unseen |
| R-22 | Reconcile: one sighting parks the system; one failed read → SAFE_MODE; auto-clear of API_DEGRADATION/STALE_FEED; `scripts/demo_clear.py` | reconcile_safemode 1-4 (G-0500, G-0501, G-0503) | Example: entry fills 14:00:07.0, stop ACTIVE 14:00:09.0, tick at 14:00:08 → SAFE_MODE POSITION_WITHOUT_STOP until `/safemode_exit`. Options: two consecutive ticks, transition-aware compare, latch only non-transient kinds; N = 4 failed ticks (60 s) before SAFE_MODE; demo_clear bound to Demo or removed before mainnet | frequent false SAFE_MODE episodes that need the owner |
| R-23 | Telegram: redelivery of failed safety alerts, outcome messages after CONFIRM, buttons after a curable refusal, missed card notice | telegram_alerts 1-4 (G-0801, G-0802, G-0803, G-0806) | Example: Telegram down 40 s at 03:00 while an emergency close fails → 3 tries in 30 s, dropped, phone silent. Options: retry on every drain until delivered; for N minutes; as today. Outcome message per state (placed, refused + reason, filled, stop set, closed + PnL) | the owner can miss the one alert that matters |
| R-24 | Kill-gate producer for LIVE | D092; G-1604 (P24 c1) | build the producer before any LIVE enable, or keep LIVE refused | LIVE stays refused `KILL_GATE_UNEVALUATED` (safe) |

**E. Research and evidence**

| ID | Decision | Source | Options, with a numeric example | If left as is |
|---|---|---|---|---|
| R-25 | Record the result of research run 1 | X09 O-2 (G-2101); backtest_research_analytics O-1 (G-0901, G-0903) | 48 candidates: 45 negative Validation mean (-0.23R to -0.011R), one below the trade floor, two positive by 0.003R and 0.0007R with uncertainty 0.055R and 0.14R. (a) record "no passing candidate" (kill gate can fire 2027-03-19); (b) leave unrecorded (state stays WITHIN_BUDGET); (c) continue Demo as engineering only, no go-live date | execution work continues toward live with no strategy that passed |
| R-26 | Rules for a second research run; cap-free per-signal R; slippage per exit type; trade lists | X09 O-3 (G-2102), G-2107; backtest_research_analytics O-2, O-3 (G-0902, G-0904); X09 O-4 (slippage) | alpha across runs, fresh Validation period, real holdout test; report cap-free R beside gated R (trend-pullback Development: 47,117 aggregate-cap rejects vs 171-570 trades per point); one 3 bps rate for all market exits vs 1 bp on TPs (new simulator version); keep trade lists (disk, about 25 h re-run) | a second run on the same data is uncontrolled |
| R-27 | EXPERIMENT-labelled values with no basis in SHADOW/go-live; cluster membership (8 of 12 research symbols outside the hard-coded cluster) | core_strategy_risk 4, 5 (G-0105; KNOWN F-908) | allow in SHADOW only and refuse at the go-live gate, or not; define cluster membership | an unsupported value can reach live |
| R-28 | Paper soak rules: uncovered-time ceiling, new pin on the same DB, 21-day limit, build identity, clock-skew bound | paper_runtime 1-5 (G-1001, G-1002, G-1003, G-1005, G-1008) | Example: a 60 s restart at 12:20 counts 2400 s uncovered and fails the 900 s ceiling; at 12:50 it passes. Options: keep 900 s; record feed proof at start; ceiling = one bar + start time. Skew bound e.g. 500 ms | trials fail on harmless restarts; long soak cannot restart after about day 21 |
| R-29 | OQ-1: backtest trades held through mark-price holes | D058 | annotate only / count against coverage / exclude from pooled R / void | open since 2026-10-07 |

**F. Process**

| ID | Decision | Source | Options | If left as is |
|---|---|---|---|---|
| R-30 | Re-present the money numbers the owner never chose with a consequence shown | G-1603; X09 G-2103 (O-4) | one worked USDT example per number for: `max_unprotected_ms`, `entry_terminal_timeout_ms`, slippage 1/3 bps, `cluster_cap`, the 60 % utilisation floor, 418 = 3 days, 429 = 120 s, N = 3 trips/week, the adverse-edge sizing; add a provenance value such as `ASSISTANT_DEFAULT_ACCEPTED` | assistant defaults keep the `DECISION` label and are not questioned |
| R-31 | Close-out rule for success criteria | G-1604 | "library level" = PARTIAL until a composed-process test or Demo evidence; or keep | criteria keep being closed on library proofs |
| R-32 | One register of open items | G-1600 | adopt this table as the register and retire STATE "Open user decisions" and 19-OWNER-GAPS section 1 | three stale registers |
| R-33 | Optional `NOT_CONFIGURED` keys | `config/execution/execution-limits-v1.toml:80,84` | `rest_gate.ban_end_clock_margin_ms` (unset: the 418 fallback of R-07 applies, start not refused); `scheduler.duration_summary_interval_ms` (unset: only new-maximum duration rows are written) | as described; neither refuses the start |
| R-34 | Demo checks not yet done and what Demo cannot show | 19-OWNER-GAPS 2a (R-P3, R-P7, R-A2, R-A5); AGENTS.md (P3, P7, A2 wait for Phases 25/26); 25 Q-G (no campaign date until P6 holds and the Phase 16 soak is confirmed finished); gap plans 25-19 to 25-32 not executed | Partial fill (P3/A5) and fill/cancel race (P7) cannot be produced on Demo; GTD expiry (A2) stayed `NEW` 840 s after `goodTillDate`. Options: accept them as first-seen at the canary with a written fallback, or design a mainnet read-only / minimum-size observation | these paths are first exercised with real money |

Count: 34 register rows covering the 56 owner items of the 14 finished lanes plus open items of 19-OWNER-GAPS, 25-OWNER-DECISIONS, D058, D092 and the config file (duplicates merged: R-01 4 sources, R-02 3, R-03 3, R-13 2, R-25 2, R-19 2).
<!-- OWNER-END -->

## Open Questions

- Lanes not finished when this register was built (data_persistence_db, evidence_reproducibility, ops_deploy_security, scripts_tooling, mutation_probe, prior_findings_closure_a; X08 operator_golive_gap has no file): their owner items are not in the register. The coordinator should merge them.
- For X08: RUNBOOK:1087 ties the live restart policy to "the first clean Demo run"; clean runs exist; who decides now (25 Q-E says after the Phase 16 soak)?
- Success criteria sampled: 18 of about 30 in Phases 16-24. The "library level" pattern (G-1604) should be checked for the rest, especially Phase 20 criteria (reconcile) and Phase 22 (margin), which other lanes cover in code.
- `docs/**` other than DECISIONS, EXECUTION_SPEC, RISK_MANAGEMENT and RUNBOOK sections 20/22 was not read line by line here (GLOSSARY, CONFIGURATION, DATA_MODEL, TESTING_STRATEGY); stale statements there are possible.
- The "reviewer" whose two texts became D072 is not identified in the record (another AI review or a person); the provenance chain of the 27 values ends there.

## DONE
