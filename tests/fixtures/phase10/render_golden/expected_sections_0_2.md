# Journal Depth + Kill-Gate Report

| Field | Value |
| :--- | :--- |
| Report digest | sha256:57bcaab6d328210b2484b20d98250c9b63e8d65628ffb68d8fb5e418744535ee |
| As of (UTC) | 2027-04-01T00:00:00+00:00 |
| As of (display) | 2027-04-01 07:00:00 +07:00 (Asia/Ho_Chi_Minh) |
| Timezone note | Stored and computed values are UTC. Display times are Asia/Ho_Chi_Minh (UTC+07:00, no DST). |
| Generator | src.analytics.cli + analytics-schema/1 |
| Read-only statement | This report is read-only. It never changes parameters, orders, or approvals, and it never enables live trading. |
| Kill gate state | INSUFFICIENT_EDGE |
| Live orders | LIVE_ORDERS_DISABLED |

---

## 1. Kill Gate

> **KILL GATE STATE: INSUFFICIENT_EDGE TERMINAL** — NO_TRADE / INSUFFICIENT EDGE. Three or more independently specified families were tested under the frozen methodology, at least six months have elapsed, and none passed. This is a valid terminal outcome, not an error. Live trading stays disabled and new strategy families are not registered until a new evidence-backed question is approved by an explicit human decision record.

### 1.1 Budget progress

| Budget | Required | Actual | Status |
| :--- | :--- | ---: | :--- |
| Independently specified families tested | 3 | 3 | MET |
| Research months elapsed | 6 calendar months | 6.4 (6 calendar months + 13 days) | MET |
| Any family passing acceptance | none required | 0 | informational |

INSUFFICIENT_EDGE requires BOTH budgets met AND no passing family (D013).

### 1.2 Clock provenance

| Field | Value |
| :--- | :--- |
| Research clock start (UTC) | 2026-09-19T00:00:00+00:00 |
| Source | docs/research/RESEARCH_PROTOCOL.md header: Frozen on |
| Freeze commit | 281ccd0894ea35717cc741788b6133cfb202af82 |
| Commit author date | 2026-09-19T14:08:12+07:00 |
| Earliest possible INSUFFICIENT_EDGE (UTC) | 2027-03-19T00:00:00+00:00 |
| Evaluated at (UTC) | 2027-04-01T00:00:00+00:00 |
| Evaluated at (display) | 2027-04-01 07:00:00 +07:00 |

### 1.3 Family acceptance

| Family | Independent | Sheet hash (12) | Param sets | Experiments | Status | Decision ref | Universe |
| :--- | :--- | :--- | ---: | ---: | :--- | :--- | :--- |
| trend-pullback | YES | a1a1a1a1a1a1 | 2 | 2 | TESTED_FAIL | DEC-2026-11-fail-trend-pullback | Live-5 n=2 / Research n=2 |
| breakout-retest | YES | a2a2a2a2a2a2 | 1 | 2 | TESTED_FAIL | DEC-2026-11-fail-breakout-retest | no data |
| range-mr | YES | a3a3a3a3a3a3 | 1 | 2 | TESTED_FAIL | DEC-2026-11-fail-range-mr | no data |

Families A and C share the regime detector; B reuses the 4H direction gate. Shown for transparency; independence is decided by the registry test, not this note.

### 1.4 Family gate matrix

| Family | G01 | G02 | G03 | G04 | G05 | G06 | G07 | G08 | G09 | G10 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| trend-pullback | NOT_EVALUATED | NOT_EVALUATED | MET | PENDING_THRESHOLD_TBD | PENDING_THRESHOLD_TBD | PENDING_THRESHOLD_TBD | MET | MET | PENDING_THRESHOLD_TBD | MET |
| breakout-retest | NOT_EVALUATED | NOT_EVALUATED | MET | PENDING_THRESHOLD_TBD | PENDING_THRESHOLD_TBD | PENDING_THRESHOLD_TBD | NOT_EVALUATED | NOT_MET | PENDING_THRESHOLD_TBD | NOT_MET |
| range-mr | NOT_EVALUATED | NOT_EVALUATED | NOT_MET | PENDING_THRESHOLD_TBD | PENDING_THRESHOLD_TBD | PENDING_THRESHOLD_TBD | NOT_EVALUATED | NOT_MET | PENDING_THRESHOLD_TBD | NOT_MET |

G01 Deterministic rules, G02 No material look-ahead, G03 Costs modeled, G04 Not single-symbol/session, G05 OOS consistent, G06 Tolerable drawdown, G07 Reproducible, G08 Interval uncertainty, G09 No single-point dependence, G10 Baseline-compared

### 1.5 NO_TRADE by reason category (BACKTEST)

*Evidence: BACKTEST*

| Reason category | Live-5 n | Research n | All n |
| :--- | ---: | ---: | ---: |
| regime filter | no data | no data | no data |
| RR floor | no data | no data | no data |
| open-position conflict | no data | no data | no data |
| data unavailability | no data | no data | no data |
| kill-gate trip | no data | no data | no data |
| UNMAPPED | no data | no data | no data |
| **Total** | no data | no data | no data |

### 1.6 NO_TRADE by reason category (PAPER)

*Evidence: PAPER*

| Reason category | Live-5 n | Research n | All n |
| :--- | ---: | ---: | ---: |
| regime filter | 1 | 1 | 1 |
| RR floor | 0 | 0 | 0 |
| open-position conflict | 0 | 0 | 0 |
| data unavailability | 0 | 0 | 0 |
| kill-gate trip | 0 | 0 | 0 |
| UNMAPPED | 1 | 1 | 1 |
| **Total** | 2 | 2 | 2 |

### 1.7 NO_TRADE by reason category (LIVE)

*Evidence: LIVE*

| Reason category | Live-5 n | Research n | All n |
| :--- | ---: | ---: | ---: |
| regime filter | no data | no data | no data |
| RR floor | no data | no data | no data |
| open-position conflict | no data | no data | no data |
| data unavailability | no data | no data | no data |
| kill-gate trip | no data | no data | no data |
| UNMAPPED | no data | no data | no data |
| **Total** | no data | no data | no data |

### 1.8 Decision references

- DEC-2026-11-fail-breakout-retest
- DEC-2026-11-fail-range-mr
- DEC-2026-11-fail-trend-pullback

### 1.9 Enablement effect

New strategy families are not registered and live enablement is refused until an explicit human decision record clears this state.

Live trading is never enabled by this report.

---

## 2. Evidence Overview

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

| Evidence | Has data | Outcomes (n) | Lifecycle records | NO_TRADE rows | INCOMPLETE |
| :--- | :--- | ---: | ---: | ---: | ---: |
| BACKTEST | YES | 2 | 2 | 0 | 15 |
| PAPER | YES | 0 | 2 | 2 | 10 |
| LIVE | NO | 0 | 0 | 0 | 0 |

No LIVE evidence rows exist yet. Backtest and paper sections are complete; live-5 sections populate when live journal rows appear.
