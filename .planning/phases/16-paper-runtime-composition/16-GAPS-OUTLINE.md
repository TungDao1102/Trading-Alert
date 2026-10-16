# Phase 16 review gaps: fix plan outline (2026-10-16)

Source: `16-REVIEW.md` and the three batch reports. All nine Critical findings were checked against the code on 2026-10-16: eight confirmed as described, one (B2-CR-02) confirmed with a narrow window and downgraded. This outline is the plan to turn the findings into numbered plans (proposed 16-55 to 16-61) after the user fixes the scope. Nothing here is implemented.

## Rules for every fix plan

- Test first: each finding gets a test that fails on today's code (the reviewers found none for B1-CR-01/02, B2-CR-01..04, B3-CR-01/02). Unverified Warnings are re-checked in the code before a fix is written; a claim that does not hold is closed with a note, not "fixed".
- Offline only: no Binance, Telegram or network; fakes and fixtures as in the existing paper tests.
- One commit per finding group; the frozen image is built from the final commit, so no change after the plans are done and the full suite is green.
- After the last fix plan, one targeted re-review of the changed files (same three-batch method, only the diff since c654524) before anything is pushed or merged.
- No change to a registered parameter set, the frozen manifest or an authorization file.

## Proposed plans, in order

| Plan | Group | Findings | Why this order |
|---|---|---|---|
| 16-55 | Image and deploy | B2-CR-05 (params/ and config/paper/ missing from the image), B2-WR-07 (hung runtime undetected; heartbeat and backup target project `trading`, not `trading-soak`), B1-WR-11 (clean SIGTERM exit 0 vs `restart: on-failure`; confirm on the host), B1-WR-07 (single-instance guard per epoch) | Smallest change, and the image cannot run without it |
| 16-56 | Feed fail-closed | B1-CR-01 (exhausted rebuild must fail closed; silence watchdog), B1-WR-06 (retry wiring never matches SDK errors), B1-WR-02 (state-port engine without timeouts), B1-WR-12 (one bad symbol stops the constraint refresh), B1-WR-10 | Coverage criterion depends on it |
| 16-57 | Acceptance log and crash consistency | B1-CR-02 (flush the acceptance log before any heartbeat or gap write), B1-WR-03, B1-WR-05, B1-WR-01 (startup seam), B1-WR-08 (pin the runtime config hash to the epoch) | Parity criterion depends on it |
| 16-58 | SHADOW locking and reservations | B2-CR-01 (lock order), B2-CR-03 (unsizable confirmed plan must not crash-loop), B2-CR-02 (expiry vs fill horizon), B2-WR-01..04, B2-WR-08 | Deadlock and crash-loop are the worst failures during a 14-day soak |
| 16-59 | Evidence export and workflow | B2-CR-04 (hourly publish vs "never replaced"), B2-WR-05 (`concurrency` group), B2-WR-06 (future EVIDENCE_GAP records) | Needed before the first hourly export; RUNBOOK 20.7 changes with it |
| 16-60 | Research warm-up and runner hardening | B3-CR-01 (cold windows; needs the user decision below), B3-WR-02 (trades digest), B3-WR-03 (constraint path), B3-WR-04 (`--repo-root` identity), B3-WR-05 (duplicate grid points) | Independent of the soak image; a warm-up fix means a new run of 240 records |
| 16-61 | Kill-gate sidecar | B3-CR-02, B3-WR-01 | No kill-gate report exists before Phase 26; can wait |

Plans 16-55 to 16-59 change what the soak runs and block 16-43. 16-60 and 16-61 do not.

## Decisions the user owns

1. **Cold research windows (B3-CR-01).** Option A: fix by loading warm-up history before each window (a simulator semantics change, a new run of all three families, about 4 to 5 hours, a decision on `SIMULATOR_SEMANTICS_VERSION`, a new set of 240 records next to the old ones). Option B: keep the current design, state in the protocol and the report that every fold starts cold (the first about 796 hourly bars per symbol are WARMUP_INSUFFICIENT), and treat the 240 records as measured under that design. Either way the feasibility table of 2026-10-16 must carry the note.
2. **Scope of the blocking set.** Recommended: 16-55 to 16-59 before the soak, 16-60 and 16-61 afterwards. Alternative: add some Warnings of 16-60 now.
3. **Warnings not named above** (the Info items and the Warnings of the batch files not listed here): fix with the group they belong to when cheap, otherwise record in `deferred-items.md`.
