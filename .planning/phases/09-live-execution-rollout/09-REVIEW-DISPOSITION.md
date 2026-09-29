---
phase: 09
review: 09-REVIEW.md
titles: json
findings:
  - id: CR-01
    severity: critical
    disposition: fixed
    title: "Protective attach crashes against the real adapter (`reduce_only` kwarg), and TP1 would never be sent reduce-only"
  - id: CR-02
    severity: critical
    disposition: fixed
    title: "Adapter exceptions during attach leave the position unprotected with no SAFE_MODE; the default `safe_mode_controller=None` silently drops the signal"
  - id: CR-03
    severity: critical
    disposition: fixed
    title: "A TP1 sizing rejection aborts before the SL is placed, leaving a filled position with no stop at all"
  - id: CR-04
    severity: critical
    disposition: fixed
    title: "Deterministic algo IDs collide between `execute_approved_plan` and `attach_protectives_to_fill`, and across successive partial fills"
  - id: CR-05
    severity: critical
    disposition: fixed
    title: "`execute_approved_plan` ignores the SL placement result and returns OK with the entry live and unprotected"
  - id: CR-06
    severity: critical
    disposition: fixed
    title: "`execute_approved_plan` calls `asyncio.run` in a sync function, which cannot work in the production asyncio stack"
  - id: CR-07
    severity: critical
    disposition: fixed
    title: "Live placement gates are fail-open by default: enablement, placement gates, SAFE_MODE, and reconciliation are all skippable or absent"
  - id: CR-08
    severity: critical
    disposition: fixed
    title: "The approval binding does not check the approval's action or status, or that the executed plan is the approved plan"
  - id: CR-09
    severity: critical
    disposition: fixed
    title: "The adapter blindly retries entry and algo placement with the same client ID on ambiguous failures, and the manager's no-blind-recovery probe is unreachable or broken"
  - id: CR-10
    severity: critical
    disposition: fixed
    title: "The expiry and emergency-close paths call a non-existent adapter method, and the emergency sequence disables live orders and enters SAFE_MODE last"
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "Limit and trigger prices are never quantized to `price_tick_size`"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "Position mode is hard-coded to `BOTH` and never detected; the Protocol and adapter types disagree"
  - id: WR-03
    severity: warning
    disposition: fixed
    title: "`_is_leg_confirmed` is fail-open for any non-dict response, which is what the real adapter returns"
  - id: WR-04
    severity: warning
    disposition: fixed
    title: "`fold_fills` sums unrelated fills, silently drops malformed ones, and gets the SHORT sign wrong"
  - id: WR-05
    severity: warning
    disposition: fixed
    title: "Placement gates judge a different sizing, snapshot and clock than the order actually placed"
  - id: WR-06
    severity: warning
    disposition: fixed
    title: "The headroom limit is hard-coded, counts are unvalidated, and early rejects misreport `daily_state`"
  - id: WR-07
    severity: warning
    disposition: skipped
    title: "Entry expiry orphans the entry-time close-all SL, and the emergency close opens an unprotected window"
  - id: WR-08
    severity: warning
    disposition: fixed
    title: "The health aggregate passes on incomplete probe sets and never gates enablement"
  - id: WR-09
    severity: warning
    disposition: fixed
    title: "`journal_event_id` values collide on the same injected timestamp (the DB primary key)"
  - id: WR-10
    severity: warning
    disposition: fixed
    title: "The enablement journal payload records the pre-transition state"
  - id: WR-11
    severity: warning
    disposition: fixed
    title: "Quality gates are red: `mypy --strict` and `ruff check` fail"
  - id: WR-12
    severity: warning
    disposition: fixed
    title: "The tests validate fakes, not the adapter contract, and leave the risky paths untested"
  - id: IN-01
    severity: info
    disposition: open
    title: "A file-wide E501 ignore covers the most safety-critical adapter"
  - id: IN-02
    severity: info
    disposition: open
    title: "Decimals reach the SDK raw, not as strings as documented"
  - id: IN-03
    severity: info
    disposition: open
    title: "Dead or redundant code"
  - id: IN-04
    severity: info
    disposition: open
    title: "`assert` is used for runtime invariants on the placement path"
  - id: IN-05
    severity: info
    disposition: open
    title: "Fixture and test precision gaps"
  - id: IN-06
    severity: info
    disposition: open
    title: "`EnablementVerdict` validation is lopsided, and the guard receives a mislabelled argument"
  - id: IN-07
    severity: info
    disposition: open
    title: "Health probe edge cases"
open: 7
total: 29
recorded: 2026-09-29T03:50:20.705Z
---

# Phase 09: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| CR-01 | critical | fixed | 09-REVIEW-FIX.md |
| CR-02 | critical | fixed | 09-REVIEW-FIX.md |
| CR-03 | critical | fixed | 09-REVIEW-FIX.md |
| CR-04 | critical | fixed | 09-REVIEW-FIX.md |
| CR-05 | critical | fixed | 09-REVIEW-FIX.md |
| CR-06 | critical | fixed | 09-REVIEW-FIX.md |
| CR-07 | critical | fixed | 09-REVIEW-FIX.md |
| CR-08 | critical | fixed | 09-REVIEW-FIX.md |
| CR-09 | critical | fixed | 09-REVIEW-FIX.md |
| CR-10 | critical | fixed | 09-REVIEW-FIX.md |
| WR-01 | warning | fixed | 09-REVIEW-FIX.md |
| WR-02 | warning | fixed | 09-REVIEW-FIX.md |
| WR-03 | warning | fixed | 09-REVIEW-FIX.md |
| WR-04 | warning | fixed | 09-REVIEW-FIX.md |
| WR-05 | warning | fixed | 09-REVIEW-FIX.md |
| WR-06 | warning | fixed | 09-REVIEW-FIX.md |
| WR-07 | warning | skipped | 09-REVIEW-FIX.md |
| WR-08 | warning | fixed | 09-REVIEW-FIX.md |
| WR-09 | warning | fixed | 09-REVIEW-FIX.md |
| WR-10 | warning | fixed | 09-REVIEW-FIX.md |
| WR-11 | warning | fixed | 09-REVIEW-FIX.md |
| WR-12 | warning | fixed | 09-REVIEW-FIX.md |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |
| IN-07 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
