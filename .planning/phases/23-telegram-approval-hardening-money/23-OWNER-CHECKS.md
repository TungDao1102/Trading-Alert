# Phase 23 owner checks and owner questions (plan 23-13)

Written on 2026-10-27 from the twelve SUMMARY files of plans 23-01 to 23-12 and the code at HEAD. Every default named below was read from the code or from a SUMMARY before it was written. Nothing in this file claims a live behavior verified: Phase 23 is a library phase (D-17), executed with fakes and local PostgreSQL, and nothing it built is composed into a running process until Phase 24.

Evidence label: [DESIGN] (executed tests). The owner-run checks below are NOT_REHEARSED.

## Owner-run checks (not run by an agent, NOT_REHEARSED, for Phase 24 or 25)

| ID | Check | Why only the owner can do it | What the code assumes until then | Where it is registered |
|----|-------|------------------------------|----------------------------------|------------------------|
| A1 | An `editMessageText` with an empty inline keyboard removes the keyboard on the live Bot API. If it does not, the fallback `edit_message_reply_markup` call (already in the code) must be tried and the result written down. | needs a real Telegram bot and a real chat | an empty `reply_markup` removes the keyboard; the stored state, not the keyboard, is the guarantee: a stale tap is answered from the stored row (`ALREADY_DECIDED`) | `docs/integration/TELEGRAM.md` section 6; 23-07, 23-10, 23-11 and 23-12 SUMMARY files |
| G2-014 | A tap on an APPROVE button from a second Telegram account, and from a group chat, is refused on the live Bot API (`USER_NOT_AUTHORIZED`, `CHAT_NOT_PRIVATE`), the stored approval is unchanged and the journal row holds only the presser's id. | needs a second account and a group | the refusal is proven with fakes (`tests/test_telegram_authorization.py`) | `docs/integration/TELEGRAM.md` section 3; `docs/operations/DEPLOY_GUIDE.vi.md` section 8.1 |
| A2 | The exact live text of the Bot API error for an expired callback query ("Query is too old ..."). | needs a callback query older than the Telegram limit | the adapter matches the phrase "Query is too old" and logs it at debug level; any other answer error keeps the warning | `docs/integration/TELEGRAM.md` section 6; 23-07 SUMMARY |

## Owner questions

"Default built" is what the code does today. "Answered" means the owner gave an answer; everything else stays OPEN until the owner answers.

| ID | Question | Default built | Implemented in | Status |
|----|----------|---------------|----------------|--------|
| O-1 | Who is on the allow-list `TELEGRAM_AUTHORIZED_USER_IDS`? | one Telegram user id, set by the owner in `.env` (never in the repository); required, no default, empty is refused | `src/adapters/telegram_callbacks.py` (`authorized_user_gate`), `src/paper/runtime_config.py` (`parse_authorized_user_ids`, startup refusal) | OPEN: the owner sets the value on each host |
| O-2 | Which expiry rule for sibling approval rows (G4-042)? | exclude EXPIRED from `uq_approvals_one_decided_per_plan`; the store refuses EXPIRED on a plan that already has an APPROVED or SKIPPED row | `src/db/alembic/versions/0014_decided_excl_expired.py`, `src/persistence/approvals.py` | ANSWERED 2026-10-26, option (a), owner reply "theo cách bạn recommend" (23-08 SUMMARY); recorded as `docs/DECISIONS.md` D088 and `docs/data/DATA_MODEL.md` section 2.5 |
| O-3 | Show times in local time (Asia/Ho_Chi_Minh) or in UTC? `docs/DECISIONS.md` D025 names Asia/Ho_Chi_Minh the canonical presentation timezone. | UTC with an explicit suffix in DEMO, LIVE, SIMULATE and the confirm card (D-14); SHADOW alerts keep the UTC and Asia/Ho_Chi_Minh pair; D025 is not edited | `src/adapters/telegram_notify.py` (`format_utc`), `src/paper/shadow.py` (`format_time_pair`) | OPEN: either D025 is amended or the messages gain the local time |
| O-4 | May a group chat ever be allowed? | never: the chat type must be exactly `private` | `src/adapters/telegram_callbacks.py` (`authorized_user_gate`) | the rule is built as stated; the owner confirms by the G2-014 check |
| R-1 | Should the SHADOW alert carry the money block? (orchestrator resolution 1) | not built: SHADOW texts are byte-identical to before Phase 23 | `src/paper/shadow.py` (unchanged) | OPEN |
| R-5 | The Demo rehearsal places a Demo order after ONE tap on APPROVE (D041 says only CONFIRM may do that). | only the keyboard changed (one message, APPROVE and SKIP); the APPROVE-to-placement path of `scripts/demo_rehearsal.py` is unchanged (resolution 5) | `scripts/demo_rehearsal.py` | ANSWERED 2026-10-26 (relayed by the orchestrator), option (c): retire the `far` and `fill` scenarios once Phase 24 provides a composed Demo path, keep `taps`; no code change now. Until then `far` and `fill` are not evidence of the two-step flow |
| R-7 | D-15 proposed new `RejectionReason` members for the Phase 23 refusals. | plain-string codes instead; the enum keeps 21 members and GLOSSARY 9.1 is unchanged (orchestrator resolution 7) | `src/approval/reason_codes.py`, `docs/GLOSSARY.md` section 9.3 (19 rows) | recorded; the owner may promote the codes to the enum in Phase 24 |
| Q-TP | What is "profit at a take-profit"? | per leg, gross and net of modeled costs, labelled an estimate (the live leg is floored to the step size, so a real leg can be smaller) | `src/risk/money_at_stake.py` (plan 23-02) | OPEN: confirm the wording |
| Q-SRC | Which equity and leverage sources are shown? | labels `ACCOUNT_LIVE:min(totalWalletBalance,totalMarginBalance)` or `PAPER_CONFIG:initial_equity`, and `PLAN_CONSTRAINT_SNAPSHOT:verified_leverage` or `PAPER_CONFIG:target_leverage`; the time of the equity reading is shown | `src/risk/money_at_stake.py` (`EQUITY_SOURCES`, `LEVERAGE_SOURCES`) | OPEN: Phase 24 chooses the producer of each reading |
| Q-REC | `RECONCILIATION_REQUIRED` | wording only: the text exists, nothing raises the alert (it is not in `ALERT_EVENTS`) | `src/ops/alert_wording.py` (`reconciliation_required_text`) | OPEN: a later phase decides whether it becomes an event |
| Q-ATT | Do the DEMO and LIVE confirm journal events count in attribution? | not read: `src/paper/attribution.py` knows only the SHADOW names | `src/approval/confirm_core.py` profiles; rows `DEMO_` and `LIVE_` `CONFIRM_ISSUED`, `CONFIRMED`, `CONFIRM_CANCELLED`, `CONFIRM_EXPIRED`, `CONFIRM_REJECTED`, `CONFIRM_NOTICE_FAILED`, `CONFIRM_MESSAGE_EDIT_FAILED` | OPEN: the later consumer (Phase 24 or after) decides |
| P20-OPS-REMOTE | A remote operator control through Telegram. | deferred to Phase 24 (D-16); the allow-list (plan 23-01) and the confirm core (plan 23-06) are built in a form a Telegram command can reuse | `src/approval/confirm_core.py`, `src/adapters/telegram_callbacks.py` | DEFERRED to Phase 24 |

## Wording left behind on purpose (O-2 answer (a))

`src/paper/shadow.py` (the `RestartReport` docstring still says one decided approval per plan, and `left_pending` is now only the decided-plan case) and `src/paper/shadow_runtime.py` near line 1121 (a comment that assumes one decided row per plan) were not edited: plan 23-08 prohibited it. A later cleanup should adjust both wordings.

## Failing guard tests found during the phase (not caused by plan 23-13; need a decision on a pinned list)

Logged in `deferred-items.md` by plan 23-11 and re-run on 2026-10-27, both still fail on HEAD:

1. `tests/test_no_unratified_defaults.py::test_no_canonical_key_gets_a_numeric_constant_in_src_or_scripts` fails on `RETRY_AFTER_CAP_SECONDS: int = 30` in `src/adapters/telegram_notify.py` (plan 23-07): the guard must learn that the constant restates a ratified value, or the constant must be imported instead of restated.
2. `tests/test_modeled_costs_none_guard.py::test_consumer_audit_is_pinned_and_fails_when_a_new_reader_appears` fails because `build_money_at_stake` in `src/risk/money_at_stake.py` (plan 23-02) reads `sized.modeled_costs_per_unit` and raises `MoneyAtStakeUnavailable`; the pinned consumer list needs the two entries after an audit (the read refuses on None, it never treats None as zero).

The orchestrator's full-suite run will report both until the pinned lists are updated.

## Requirement status (recorded, not changed)

- APRV-01: stays Complete (Phase 8). Phase 23 hardens it at library level (money block, plain-word alerts); the senders are composed in Phase 24.
- APRV-02: stays Complete (Phase 8). Phase 23 hardens it at library level (user and private-chat gate, final decided message, two-step confirm core and flow); nothing is composed into a running process.
- PAPER-02: stays Pending. Phase 16 closes it; Phase 23 contributes G4-042 (D088) and P16R-02 (every adopted CONFIRM reaches the hook).
- Live placement stays disabled (`LIVE_ORDERS_DISABLED`); `on_confirmed` is connected to nothing before Phase 24.
