# Phase 16 audit: CONTEXT coverage by plans 16-01..16-49 (read-only, 2026-10-09)

Scope: 16-CONTEXT.md (all 322 lines), 16-DISCUSSION-LOG.md, 16-CONTEXT-CONSISTENCY.md, ROADMAP `### Phase 16` (SC1-9 plus 31 inherited items) mapped to plan frontmatter, objectives, must_haves, tasks and acceptance text. Method: id-reference grep across all 49 plans plus targeted reads of the plans that implement each item. No plan or context file was edited.

Bottom line: the plan set is NOT incomplete against the upstream documents. Every L-, D-, REV-, O- item and every SC and inherited item has at least one plan that carries it. The real weaknesses are a handful of weakly enforced details (section b), several planner-introduced decisions and options that touch locked items (c, d), and one deferred idea offered as a checkpoint option (e).

## Counts

| Class | Items | Covered with task or acceptance | Weak | No coverage |
|---|---|---|---|---|
| L-01..L-17 | 17 | 16 | 0 | 1 (L-17, vacuous; see a) |
| D-01..D-35 | 35 | 33 | 2 (D-10, D-35) | 0 |
| REV-01..REV-18 | 18 | 17 | 1 (REV-02 evidence-retention sentence) | 0 (REV-13 is a scope rule, nothing to build) |
| O-01..O-13 | 13 | 12 | 0 | 1 (O-05, correctly a no-op) |
| SC1-SC9 | 9 | 9 | 0 | 0 |
| Inherited ROADMAP items | 31 | 31 | 0 | 0 (D057, D061-D, D061-J and G3-029 have no literal id but are covered by substance) |

Contradictions with a locked decision: 0 outright, 4 options inside user checkpoints that deviate from a locked line and are properly gated (c). Context-changed-but-plan-follows-old: 0; plans deviate from stale context in 4 places on purpose and record it (d). Deferred-idea leaks: 1 (plan 33 option) plus 3 minor additions (e).

## (a) Items with NO plan coverage

1. **L-17** ("no health or enablement change here; D055 stays OPEN; Phase 16 touches no order path"): no plan cites it. It is a negative constraint. It is enforced indirectly by the D-13 isolation plans (38, 39) and by the absence of any D055 text in all 49 plans. No gap in behavior. Optional: add one grep or AST assertion that no Phase 16 file mentions the D055 candidates. Severity: none.
2. **O-05** (D055 execution model): no plan cites it, correctly. Same reasoning.
3. No uncovered locked decision, deferred-idea guard or open question was found. The two research facts CONTEXT says the repository lacks (GitHub Actions schedule behaviour, S3 Object Lock) are covered by plans 09/15/17 (G15) and 07/30/49 (G9/G10).

## (b) Weakly covered (mentioned, but no task, acceptance or verify enforcing the exact sentence)

1. **D-10 / SC7 "soak_smoke.log no longer reads BLOCKED".** CONTEXT D-10: "`soak_smoke.log` no longer reads `BLOCKED`, measurable acceptance recorded in a smoke evidence file." Plan 21 Task 3 and its automated check verify the new JSON evidence file (`proof_class == REAL_SMOKE`, `ws_subscribe == OK`, closed events per 1m/1h/4h). Nothing refreshes or checks the legacy `soak_smoke.log` that SC7 quotes (it is referenced only in Phase 7 files). Suggest one line in 16-21 Task 3 stating that the JSON supersedes the log, or regenerating the log. Severity: low.
2. **D-35 "logs a clock-skew check at start against a public time source".** Plan 26 Task 2 Test 3 measures skew against Binance server time only and sets no threshold. Binance serverTime is a public endpoint, but it is the same party as the data feed, so it is not an independent time source. Plan 07 covers chrony on the host. Severity: low; confirm that Binance serverTime is acceptable.
3. **D-35 / D-12 "printed in every Telegram message" and "Telegram messages show UTC and Asia/Ho_Chi_Minh".** Plan 04 tests the label and both time zones on the alert only. Plan 11 Test 1 asserts SHADOW_LABEL and mode on the confirmation card, but no test asserts the label on the CANCEL result, confirm-expiry, APPROVAL_EXPIRED or send-failure messages, and no plan 11 test checks the Ho_Chi_Minh rendering of "remaining validity". Suggest a parametrized test over every outgoing SHADOW message template in plans 04/11. Severity: medium (SC5 labelling).
4. **REV-02 "A missing tick does not delete evidence already collected" and REV-18 "earlier runtime evidence stays as auxiliary".** Only plan 44 mentions "auxiliary". Plans 15 and 25 do not state or test that a restart after an EVIDENCE_GAP keeps the pre-gap runtime records readable and excluded from the new trial's freeze criterion. Severity: low to medium.
5. **O-07 "freeze_tick_grace_seconds".** Plans 15 (Tasks 1 and 3), 22 and 27 add a user-owned `freeze_tick_grace_seconds` that separates a late tick from a missing one. REV-02 and REV-18 say "no tolerance because GitHub Actions may delay or drop a tick". Plan 27 states the grace "only separates a late tick from a missing one", which fits REV-02's "delayed so far that no valid evidence exists", but a number the user chooses is a de facto tolerance. Not a contradiction, but the plan should say the grace can never turn a gap into CLEAN and only bounds how late a valid run may be. Severity: medium (L-04 / REV-18 wording).
6. **L-14 / D059-4 (OI collector running by 2026-10-08).** Plans 07 and 20 only record the gap and the "never call it full history" rule. CONTEXT itself says this is a user commitment the repository cannot enforce. Fine.
7. **D-30 / G3-012 "max_cost_to_risk 0.15 is not touched".** Plan 18 Task 3 carries a statement only; no guard test asserts the value is unchanged. Acceptable (statement-level item); a one-line parameter-hash witness would harden it.
8. **L-16 (D058).** Only plan 11 mentions it (mark price unavailable on the card, no new gate). Adequate for SHADOW.
9. **D-26 vs plan 12.** D-26 says the gate reports G5 "30 in the holdout". Plan 12 correctly notices that counting holdout trades means simulating the single-use holdout (protocol v2.1.0 G5) and defaults to a user checkpoint Q-O. The default text "G5 floor not assessed (holdout untouched)" departs from D-26's literal wording until the user decides. This is the right behavior but the user should know D-26 is not met as written unless he chooses the extrapolation or a protocol statement.

## (c) Plans or plan options that touch or contradict a locked decision

All four are inside blocking-human checkpoints, so nothing is silently decided. They are listed because a locked line says "changing needs the user".

1. **Plan 16 Task 2 options "Alembic migration 0005" and "widen system_state_events CHECK" vs D-04** ("No second persistence mechanism is invented"). Plan 16 states the conflict itself and treats it as Q-J. Compliant; note that two of three options violate D-04's literal text.
2. **Plan 22 Task 2 Q-A option "Runtime gate mirrors pin_stream_epoch: entry required only for sets without rationale tables"** vs L-05 / D-01 (only a user-authorized exact-hash entry starts paper). Plan 22 flags it ("reads against L-05"). Option "change-pin-gate" also changes D054 item (i), which O-13 / G4-021 reserve for the user; plan 22 Task 3 stops and defers to plan 42. Compliant.
3. **Plan 24 Task 2 Q-D options "REST_BACKFILL bar may be evaluated within an age bound" and "every REST_BACKFILL bar is evaluated"** vs D-06 / L-11 ("backfill ... never evaluates a missed bar as a fresh signal"; "bars that closed while the process was down never produce signals"). Plan 24 narrows Q-D to the process-up reconnect case, which is a plausible reading, but the option also introduces a new user-owned number `backfill_eval_max_age_seconds` not listed in O-07. Compliant but the restart path (plan 29) must keep the no-late-signal rule regardless of the Q-D answer; confirm plan 29 Task 1 asserts that independently.
4. **Plan 33 Task 2 option "registry"** touches D050 (registry push deferred). Plan 33 says it needs a new DECISIONS entry before implementation. See (e).

No plan was found that contradicts D-02 (`run_paper_tick` digest unchanged: plan 10 pins "every pinned paper digest is unchanged"), L-02 (plans 10, 19 call the public lifecycle functions and never import `_Engine`), L-03, L-06/REV-15 (plan 05 uses exactly the four `blocks_report` items plus WR-10 scoped `blocks_live_enable`), L-13/REV-12 (plan 11 keeps TTL 60 s and uses the TradePlan expiry), L-15 (plan 28 Task 3 delegates the v2.2.0 amendment to a separate task) or REV-07 (plan 34 forbids a default equity).

## (d) Context decisions that changed or were corrected, and where plans follow

| CONTEXT text | What the plans do | Verdict |
|---|---|---|
| D-05 "the WS callback runs on the SDK thread; hand closed events to the loop through a thread-safe queue" | Plan 08 and plan 01 record research D6: callbacks run on the event loop thread; the callback only enqueues, the lock is kept only for the backfill race (plan 26 uses a queue) | Intentional correction by research; CONTEXT is stale. Suggest a one-line CONTEXT note. |
| D-02 "The runtime pins the epoch once at start (`pin_stream_epoch` then `write_pinned_state`)" | Plan 22 Task 3: pin only on the operator's `--pin-epoch` command with no existing state; restarts reuse the stored epoch (needed for SC8 one `epoch_id` and REV-18) | Correct refinement of D-02 under L-10; recorded as "planner audit 2026-10-08". |
| Prerequisites: CR-01 = `--checksum` at `backup_remote.py` line 334 | Plans 07, 14, 20 track D064 (SHA-256 manifests plus `cryptcheck`, commit e9a030c) and D066, as ROADMAP D062 now says | Plans follow the newer text; CONTEXT Prerequisites paragraph is stale. |
| D-07 / L-04 old wording "processed or explained-gap bars" | Already withdrawn in CONTEXT; plans 15, 25 follow REV-01 (whole-window denominator, only HEALTHY covered) | OK. |
| D-19 (test signal inside the soak) | Replaced by REV-03; plans 38, 39, 40 follow REV-03 (separate rehearsal before the trial, clean state at 43) | OK. No plan follows the withdrawn D-19. |
| D-25 grid-hash-only authorization | Plan 06 binds grid hash plus dataset manifest hash (REV-04/05) | OK. |
| D-31 four-item guard | Plan 05 builds the five-item registry with scopes (REV-15) | OK. |
| O-08 approval-expiry question | Plans 04, 11, 31 use the TradePlan expiry (REV-12) | OK. |
| ROADMAP "Depends on" | Already updated to 12, 13.1, 15, 17 | Consistency row 20 is resolved. |
| ROADMAP SC8 wording (derived 319.2 h, EVIDENCE_GAP restart) | Already updated in ROADMAP; plans 15, 25, 27, 44 follow it | Consistency rows 4 and 6 resolved. |

Planner-introduced user checkpoints that CONTEXT's "Open user decisions" list does NOT contain (new open items the user will meet during execution): Q-A (22), Q-B (19), Q-C (23), Q-D (24), Q-F (30), Q-I (33), Q-J (16), Q-L (14, Telegram token per environment), Q-O (12), O-03a/O-03b split (06/37). These are consistent with L-08/L-09 (stop at a checkpoint rather than fill a default) and are not scope creep, but the user should know the O-list in CONTEXT is no longer exhaustive. Recommend adding them to CONTEXT or a decision index.

Still-open consistency rows 1, 3, 13, 18, 22, 23 of 16-CONTEXT-CONSISTENCY.md (DECISIONS text for REV-03 placement, ROADMAP Phase 23 criterion 4 "extends the Phase 16 module", Phase 26 flip-the-registry and exclude-test-events lines, optional Phase 20 paper-only note, [OQ-1] timing wording) are file-owner edits outside Phase 16; no plan owns them, by design. Plan 28 and plan 37 carry the J.7 protocol/SC8-SC9/PAPER/WR-registry consistency check.

## (e) Deferred ideas or scope that leaked into plans

CONTEXT deferred list: D055/Demo probe, full Telegram hardening, user-data stream, reconcile, equity/daily-loss, leverage/margin, live runtime, WR-06 env split, incremental feature series, TP1 far-half rule, maker/post-only, container registry push and deploy-on-tag, BKTS-03 requirements re-map.

1. **Container registry push** (deferred by D050): offered as option "registry" in plan 33 Task 2 (Q-I), and the "ci-save-transfer" option implies a CI workflow change. Plan 33 says a registry needs a new DECISIONS entry. Not implemented unless the user chooses it. Minor leak as an option; the chosen default of the plan (none pre-selected) is correct. Note the tension with D-32 ("digest-pinned image tag produced by CI"): the "host-build-recorded" option would not be CI-produced.
2. **Plan 03 (new `src/adapters/binance_public.py`)**: not named in CONTEXT, which only says "the market-data adapter ... is the public-data one with no credentials" (D-13). Justified by SC6, but it is a refactor of `binance_usdm.py` that Phase 18/24 order code will also touch. Low risk.
3. **Plan 14 Task 3 (Telegram bot token per environment, Q-L)**: operational hardening not in CONTEXT; no deferred item covers it. Reasonable (a second poller on one token breaks getUpdates).
4. **Plans 27/34 `config/paper/paper-runtime-v1.toml`**: new user-owned configuration file. CONTEXT leaves evidence layouts to discretion and forbids defaults (L-09); consistent.
5. Telegram hardening: plan 11 builds the minimal CONFIRM module with chat gate and token bound to the approving `from_user` id, and states that full user-id auth, money amounts and keyboard removal are Phase 23. No leak.
6. G4-009, TP1 far-half, maker/post-only, D055: only mentioned as deferred or not at all. No leak.

## Item-to-plan map (primary implementers)

L-01: 09, 15, 30, 47. L-02: 10, 19. L-03: 06, 12, 13. L-04: 15, 25, 29, 44. L-05: 02, 22, 42. L-06: 05. L-07: 17, 21, 40, 07. L-08/L-09: 14, 27, 34. L-10: 42-48. L-11: 07, 14, 20, 29, 32. L-12: 03, 04, 38. L-13: 11. L-14: 07, 20, 37. L-15: 28. L-16: 11. L-17: none (vacuous).
D-01: 22, 26, 32. D-02: 10, 22, 24. D-03: 02. D-04: 16. D-05: 08, 24, 26. D-06: 08, 16, 29. D-07: 15, 16, 24. D-08/D-09: 01. D-10: 17, 21. D-11: 17. D-12: 04. D-13: 03, 22, 38. D-14: 19. D-15: 35. D-16: 04, 11, 31. D-17: 23, 34. D-18: 36. D-19: 39, 40. D-20: 10. D-21: 09. D-22: 15, 30, 47. D-23: 25. D-24/D-25: 06. D-26: 12. D-27: 18. D-28: 13, 48. D-29/D-30: 18, 41. D-31: 05. D-32: 32, 33. D-33: 07, 20. D-34: 07, 14, 20. D-35: 04, 07, 26.
REV-01: 15, 25, 27. REV-02: 09, 15, 25, 30. REV-03: 38, 39, 40, 43. REV-04/05: 06, 37, 46. REV-06: 06, 12, 46. REV-07: 22, 23, 34. REV-08: 07, 30, 49. REV-09: 18, 41. REV-10: 18, 41. REV-11: 05. REV-12: 04, 11. REV-15: 05. REV-16: 28, 37. REV-17: 15, 25, 27. REV-18: 09, 15, 25, 44.
O-01: 30, 47, 49. O-02: 45. O-03: 06, 37, 46. O-04: 42. O-06: 41. O-07: 27. O-08: 04, 11, 45. O-09: 34. O-10: 41. O-11: 20, 40, 43, 44. O-12: 14. O-13: 02, 22, 42.
SC1: 22, 26. SC2: 01. SC3: 04, 19, 31, 35. SC4: 25. SC5: 04, 11, 31, 35, 36. SC6: 03, 22, 38. SC7: 17, 21. SC8: 09, 15, 25, 30, 43, 44. SC9: 25, 44.
Closure-chain order in plan waves matches CONTEXT J.8: smoke (21), EC2 (14, 20), rehearsal (40), durable location (30), grid (45), run authorization (46), hash (42), pin/start (43), evaluation (44).

## Top gaps to fix (ordered)

1. SHADOW label and UTC plus Asia/Ho_Chi_Minh on every outgoing SHADOW message, not only the alert and the card (plans 04/11; D-12, D-35, SC5).
2. Make `freeze_tick_grace_seconds` explicit as non-tolerance (plans 15, 27; REV-02, REV-18).
3. State and test that REV-18 restarts keep pre-gap evidence as auxiliary and out of the new freeze criterion (plans 15/25).
4. Plan 29: assert the no-late-signal rule independently of the Q-D answer (D-06, L-11).
5. Reconcile `soak_smoke.log` wording in SC7/D-10 with the new JSON evidence file (plan 21).
6. Update CONTEXT for the three stale statements (event-loop thread, CR-01 text, epoch pin rule) and index the planner-added checkpoints Q-A..Q-O so the O-list is exhaustive.
7. Tell the user D-26's G5 reporting is deferred to checkpoint Q-O (plan 12) and does not meet D-26 literally until he picks.
