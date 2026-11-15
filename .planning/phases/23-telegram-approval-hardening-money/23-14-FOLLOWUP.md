# 23-14 Follow-up: presentation time in the approval messages (owner O-3) and SHADOW exemption (owner R-1)

Quick follow-up to Phase 23, done on branch `develop` on 2026-10-30. It closes the two owner items
that 23-VERIFICATION.md left open (`human_needed`).

## Owner decisions (2026-10-30)

- **O-3.** The DEMO, LIVE, SIMULATE and confirmation-card messages show the local Vietnam time as the
  main time and UTC in brackets: `2026-10-30 21:15:00 +07 (2026-10-30 14:15:00 UTC)`.
- **R-1.** The SHADOW approval alert stays without the money block. The owner accepted the
  exemption. SHADOW text is not changed. Composing a money block for SHADOW, if wanted, is a
  Phase 24 composition question.

## Why

- `docs/DECISIONS.md` D025 and `docs/01_ENGINEERING_PRINCIPLES.md` section 8: persist UTC, convert
  to Asia/Ho_Chi_Minh only in presentation. Phase 23 (D-14) showed UTC only, which conflicted with
  D025 (owner item O-3). The new text satisfies D025 and keeps UTC visible, which matters because the
  daily-loss rule (D033) counts in the UTC day.
- D025 is NOT edited. Nothing stored changes: only the text of the messages.
- Vietnam has no daylight saving, so a fixed offset `timezone(timedelta(hours=7))` is exact. No
  `zoneinfo` / tzdata dependency is added. The suffix is `+07` (not the zone name).

## What changes

1. `src/adapters/telegram_notify.py`: `format_utc` is replaced by `format_presentation_time(instant)`
   returning `YYYY-MM-DD HH:MM:SS +07 (YYYY-MM-DD HH:MM:SS UTC)`. A naive datetime still raises
   `ValueError`, a non-datetime `TypeError`, an aware instant in any zone is converted. The function
   takes the instant as an argument (no wall clock). All callers are updated
   (`src/paper/notify.py`, `src/execution/approval_desk.py`, `src/execution/confirm_flow.py`, tests).
2. The Phase 23 message goldens are regenerated only through `scripts/gen_phase23_fixtures.py`;
   `--check` must exit 0. The gate invariant in `tests/test_phase23_gate.py` flips: the
   DEMO/LIVE/SIMULATE/card goldens carry ` +07 (` and ` UTC)` and still no `Display:` note. The
   SHADOW pins (`format_time_pair`, UTC plus Asia/Ho_Chi_Minh) are unchanged.
3. `docs/integration/TELEGRAM.md` states the new rule and drops the "conflict / O-3 open" text.
4. `23-OWNER-CHECKS.md`: O-3 and R-1 ANSWERED; stale "two guards still fail on HEAD" statements fixed
   in it and in `23-VALIDATION.md`; Phase 24 note: compose only through `on_callback`.
5. Stale comments: `0014_decided_excl_expired.py` (O-2 was answered (a) on 2026-10-26, D088) and the
   two comments the 23-13 summary lists in `src/paper/shadow.py` and `src/paper/shadow_runtime.py`
   (comment/docstring edits only).

## Out of scope

`docs/DECISIONS.md`, `AGENTS.md`, `docs/trading/RISK_MANAGEMENT.md`, SHADOW text, any behavior of
placement, the full test suite (the orchestrator runs it once per phase).
