---
phase: 10
review: 10-REVIEW.md
titles: json
findings:
  - id: CR-01
    severity: critical
    disposition: open
    title: "The sticky INSUFFICIENT_EDGE terminal is lost whenever the database is not read; the committed `recorded_terminal` is never used"
  - id: CR-02
    severity: critical
    disposition: fixed
    title: "Human family decisions whose `family_id` is not a registry directory are silently discarded"
  - id: WR-01
    severity: warning
    disposition: skipped
    title: "The family-independence test is partly vacuous and depends on order"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "Unmapped CANDIDATE experiments are silently dropped"
  - id: WR-03
    severity: warning
    disposition: fixed
    title: "The CLI failure contract is broken by exceptions outside `_EXPECTED_FAILURES`"
  - id: WR-04
    severity: warning
    disposition: open
    title: "`--record` accepts any `--as-of`, including future instants, and writes it into the append-only journal"
  - id: WR-05
    severity: warning
    disposition: open
    title: "A failed record returns exit 1 after the report files are written and the success lines are printed"
  - id: WR-06
    severity: warning
    disposition: skipped
    title: "The BACKTEST block pools every experiment's trades into a single headline metric set"
  - id: WR-07
    severity: warning
    disposition: open
    title: "Research-universe hash verification is never wired, so it always reports NOT_APPLICABLE"
  - id: WR-08
    severity: warning
    disposition: open
    title: "The LIVE approval-delay buckets never contain skipped or expired (OPPORTUNITY) signals"
  - id: WR-09
    severity: warning
    disposition: open
    title: "The kill-gate verdict cannot be computed or recorded without a complete evidence file; the documented `-Record` usage fails"
  - id: WR-10
    severity: warning
    disposition: skipped
    title: "`LiveEnablementController.enable` trusts a caller-supplied kill-gate state and does not journal it"
  - id: WR-11
    severity: warning
    disposition: fixed
    title: "Malformed KILL_GATE_EVALUATION and QUESTION_APPROVED rows are dropped silently"
  - id: WR-12
    severity: warning
    disposition: skipped
    title: "`--record` accepts an arbitrary decisions file, and file-only resets bypass the journal reset event"
  - id: WR-13
    severity: warning
    disposition: skipped
    title: "Gate cells G07, G08 and G10 turn MET based on self-reported booleans in the evidence file"
  - id: WR-14
    severity: warning
    disposition: open
    title: "The PostgreSQL integration test drops every table on whatever `TEST_DATABASE_URL` points to, and uses the Proactor loop on Windows"
  - id: WR-15
    severity: warning
    disposition: open
    title: "A negative `realized_risk` flips the sign of R in the core metrics, while the excursion engine calls it MALFORMED_ROW"
  - id: IN-01
    severity: info
    disposition: open
    title: "The live-posture tie-break favours ENABLED"
  - id: IN-02
    severity: info
    disposition: open
    title: "The Evidence Overview INCOMPLETE column adds up overlapping buckets"
  - id: IN-03
    severity: info
    disposition: open
    title: "TP2 exits are excluded from the \"MAE (R) of take-profit exits\" diagnostic"
  - id: IN-04
    severity: info
    disposition: open
    title: "Static report copy asserts facts the code does not check, and some provenance fields are missing from the Markdown"
  - id: IN-05
    severity: info
    disposition: open
    title: "`md_cell` leaves Markdown link and emphasis syntax active, and the truncation count can be spoofed"
  - id: IN-06
    severity: info
    disposition: open
    title: "The registration tripwire checks only directory names, and it disagrees with `_family_ids`"
  - id: IN-07
    severity: info
    disposition: open
    title: "A new sticky terminal after a reset still reports the old reset as \"Reopened by\""
  - id: IN-08
    severity: info
    disposition: open
    title: "The wrapper exports every `.env` secret to the analytics process"
  - id: IN-09
    severity: info
    disposition: open
    title: "The message \"Replaying the same inputs is a no-op\" is misleading without `--as-of`"
  - id: IN-10
    severity: info
    disposition: open
    title: "`_realized_r_by_signal` silently keeps the last value on duplicate signal ids"
open: 18
total: 27
recorded: 2026-09-29T09:45:04.493Z
---

# Phase 10: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| CR-01 | critical | open | - |
| CR-02 | critical | fixed | 10-REVIEW-FIX.md |
| WR-01 | warning | skipped | 10-REVIEW-FIX.md |
| WR-02 | warning | fixed | 10-REVIEW-FIX.md |
| WR-03 | warning | fixed | 10-REVIEW-FIX.md |
| WR-04 | warning | open | - |
| WR-05 | warning | open | - |
| WR-06 | warning | skipped | 10-REVIEW-FIX.md |
| WR-07 | warning | open | - |
| WR-08 | warning | open | - |
| WR-09 | warning | open | - |
| WR-10 | warning | skipped | 10-REVIEW-FIX.md |
| WR-11 | warning | fixed | 10-REVIEW-FIX.md |
| WR-12 | warning | skipped | 10-REVIEW-FIX.md |
| WR-13 | warning | skipped | 10-REVIEW-FIX.md |
| WR-14 | warning | open | - |
| WR-15 | warning | open | - |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |
| IN-07 | info | open | - |
| IN-08 | info | open | - |
| IN-09 | info | open | - |
| IN-10 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
