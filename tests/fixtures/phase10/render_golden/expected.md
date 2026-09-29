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

---

## 3. Full Report (unsliced)

All figures are descriptive and carry uncertainty. Nothing here changes parameters or ranks strategy families.

### 3.1 BACKTEST

*Evidence: BACKTEST*

| Metric | Value | n | Low-n | Note |
| :--- | :--- | ---: | :--- | :--- |
| Trades (n) | 2 | 2 |  |  |
| R-valued trades | 2 | 2 |  |  |
| Zero-risk excluded | 0 | 2 |  |  |
| INCOMPLETE | 0 | 2 |  |  |
| Mean R | 0.8000 [0.8000, 0.8000] n=2 | 2 | LOW_N |  |
| Median R | 0.8000 | 2 | LOW_N |  |
| Win rate | 1.0000 | 2 | LOW_N |  |
| Expectancy (R) | 0.8000 | 2 | LOW_N |  |
| Max drawdown (R) | 0.0000 | 2 | LOW_N |  |
| Loss streak (max) | 0 | 2 | LOW_N |  |

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

### 3.2 PAPER

*Evidence: PAPER*

| Metric | Value | n | Low-n | Note |
| :--- | :--- | ---: | :--- | :--- |
| Trades (n) | 0 | 0 |  |  |
| R-valued trades | 0 | 0 |  |  |
| Zero-risk excluded | 0 | 0 |  |  |
| INCOMPLETE | 0 | 0 |  |  |
| Mean R | no data | 0 | LOW_N | interval absent (fewer than 2 R-valued trades) |
| Median R | no data | 0 | LOW_N |  |
| Win rate | no data | 0 | LOW_N |  |
| Expectancy (R) | no data | 0 | LOW_N |  |
| Max drawdown (R) | no data | 0 | LOW_N |  |
| Loss streak (max) | no data | 0 | LOW_N |  |

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

### 3.3 LIVE

*Evidence: LIVE*

| Metric | Value | n | Low-n | Note |
| :--- | :--- | ---: | :--- | :--- |
| Trades (n) | 0 | 0 |  |  |
| R-valued trades | 0 | 0 |  |  |
| Zero-risk excluded | 0 | 0 |  |  |
| INCOMPLETE | 0 | 0 |  |  |
| Mean R | no data | 0 | LOW_N | interval absent (fewer than 2 R-valued trades) |
| Median R | no data | 0 | LOW_N |  |
| Win rate | no data | 0 | LOW_N |  |
| Expectancy (R) | no data | 0 | LOW_N |  |
| Max drawdown (R) | no data | 0 | LOW_N |  |
| Loss streak (max) | no data | 0 | LOW_N |  |

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

No LIVE rows exist for this evidence kind. Nothing is imputed, hidden, or pooled.

---

## 4. Dual Universe: Live-5 vs Research

Live-5: BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Research universe: ADAUSDT, BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT (universe hash 760c0431a63a; VERIFIED)

### 4.1 BACKTEST

*Evidence: BACKTEST*

| Metric | Live-5 value | Live-5 n | Research value | Research n | Low-n (Live-5 / Research) |
| :--- | :--- | ---: | :--- | ---: | :--- |
| Trades (n) | 2 | 2 | 2 | 2 | - / - |
| R-valued trades | 2 | 2 | 2 | 2 | - / - |
| Zero-risk excluded | 0 | 2 | 0 | 2 | - / - |
| INCOMPLETE | 0 | 2 | 0 | 2 | - / - |
| Mean R | 0.8000 [0.8000, 0.8000] n=2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 2 | LOW_N / LOW_N |
| Median R | 0.8000 | 2 | 0.8000 | 2 | LOW_N / LOW_N |
| Win rate | 1.0000 | 2 | 1.0000 | 2 | LOW_N / LOW_N |
| Expectancy (R) | 0.8000 | 2 | 0.8000 | 2 | LOW_N / LOW_N |
| Max drawdown (R) | 0.0000 | 2 | 0.0000 | 2 | LOW_N / LOW_N |
| Loss streak (max) | 0 | 2 | 0 | 2 | LOW_N / LOW_N |

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

### 4.2 PAPER

*Evidence: PAPER*

| Metric | Live-5 value | Live-5 n | Research value | Research n | Low-n (Live-5 / Research) |
| :--- | :--- | ---: | :--- | ---: | :--- |
| Trades (n) | no data | 0 | no data | 0 | - / - |
| R-valued trades | no data | 0 | no data | 0 | - / - |
| Zero-risk excluded | no data | 0 | no data | 0 | - / - |
| INCOMPLETE | no data | 0 | no data | 0 | - / - |
| Mean R | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Median R | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Win rate | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Expectancy (R) | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Max drawdown (R) | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Loss streak (max) | no data | 0 | no data | 0 | LOW_N / LOW_N |

Live-5 slice has no rows for this evidence kind. Nothing is imputed or hidden.

Research slice has no rows for this evidence kind. Nothing is imputed or hidden.

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

### 4.3 LIVE

*Evidence: LIVE*

| Metric | Live-5 value | Live-5 n | Research value | Research n | Low-n (Live-5 / Research) |
| :--- | :--- | ---: | :--- | ---: | :--- |
| Trades (n) | no data | 0 | no data | 0 | - / - |
| R-valued trades | no data | 0 | no data | 0 | - / - |
| Zero-risk excluded | no data | 0 | no data | 0 | - / - |
| INCOMPLETE | no data | 0 | no data | 0 | - / - |
| Mean R | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Median R | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Win rate | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Expectancy (R) | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Max drawdown (R) | no data | 0 | no data | 0 | LOW_N / LOW_N |
| Loss streak (max) | no data | 0 | no data | 0 | LOW_N / LOW_N |

Live-5 slice has no rows for this evidence kind. Nothing is imputed or hidden.

Research slice has no rows for this evidence kind. Nothing is imputed or hidden.

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

---

## 5. Approval-Delay Impact

### 5.1 BACKTEST

*Evidence: BACKTEST*

| Metric | System (all valid signals) | User execution (approved only) | Opportunity (skipped/expired) |
| :--- | :--- | :--- | :--- |
| Signals (n) | 2 | 0 | 0 |
| Mean R | 0.8000 [0.8000, 0.8000] n=2 | no data | no data |
| Expectancy (R) | 0.8000 | no data | no data |
| Win rate | 1.0000 | no data | no data |
| INCOMPLETE | 0 | 0 | 0 |

### 5.2 PAPER

*Evidence: PAPER*

SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS=30)

| Metric | System (all valid signals) | User execution (approved only) | Opportunity (skipped/expired) |
| :--- | :--- | :--- | :--- |
| Signals (n) | 2 | 1 | 1 |
| Mean R | INCOMPLETE (no hypothetical outcome) | INCOMPLETE (NO_PAPER_OUTCOME) | INCOMPLETE (no hypothetical outcome) |
| Expectancy (R) | INCOMPLETE (no hypothetical outcome) | INCOMPLETE (NO_PAPER_OUTCOME) | INCOMPLETE (no hypothetical outcome) |
| Win rate | INCOMPLETE (no hypothetical outcome) | INCOMPLETE (NO_PAPER_OUTCOME) | INCOMPLETE (no hypothetical outcome) |
| INCOMPLETE | 2 (NO_HYPOTHETICAL_OUTCOME: 1; NO_PAPER_OUTCOME: 1) | 1 (NO_PAPER_OUTCOME: 1) | 1 (NO_HYPOTHETICAL_OUTCOME: 1) |

### 5.3 LIVE

*Evidence: LIVE*

| Metric | System (all valid signals) | User execution (approved only) | Opportunity (skipped/expired) |
| :--- | :--- | :--- | :--- |
| Signals (n) | 0 | 0 | 0 |
| Mean R | no data | no data | no data |
| Expectancy (R) | no data | no data | no data |
| Win rate | no data | no data | no data |
| INCOMPLETE | 0 | 0 | 0 |

| Signal-to-approve bucket | n | Mean R | Low-n |
| :--- | ---: | :--- | :--- |
| <1m | 0 | no data | LOW_N |
| 1-5m | 0 | no data | LOW_N |
| 5-30m | 0 | no data | LOW_N |
| >=30m | 0 | no data | LOW_N |

Measured signal-to-approve distribution: no data

Differences between columns describe selection and timing effects only.

---

## 6. Execution Quality

### 6.1 BACKTEST

*Evidence: BACKTEST*

| Leg / metric | n measured | n INCOMPLETE | Mean | Median | p90 | Unit |
| :--- | ---: | ---: | :--- | :--- | :--- | :--- |
| Signal created -> seen | 0 | 2 | INCOMPLETE (NO_SEEN_TIMESTAMP) | INCOMPLETE | INCOMPLETE | s |
| Signal created -> delivery requested (proxy) | 0 | 2 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | s |
| Delivery requested -> approved | 0 | 2 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | s |
| Signal created -> approved | 0 | 2 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | s |
| Approved -> order placed | 0 | 2 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | s |
| Order placed -> filled (wait-to-fill) | 0 | 2 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | s |
| Fill % | 2 | - | 100.00% | - | - | % |
| Expiry without fill rate | 2 | - | 0.00% | - | - | % |
| Entry deviation (price, signed; positive = worse) | 0 | 2 | INCOMPLETE (NO_INTENDED_PRICE) | INCOMPLETE | INCOMPLETE | price |
| Entry deviation (bps of intended) | 0 | 2 | INCOMPLETE (NO_INTENDED_PRICE) | INCOMPLETE | INCOMPLETE | bps |

INCOMPLETE (NO_SEEN_TIMESTAMP): no read-receipt is journaled. Only delivery-request time is available as a proxy.

### 6.2 PAPER

*Evidence: PAPER*

SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS=30)

| Leg / metric | n measured | n INCOMPLETE | Mean | Median | p90 | Unit |
| :--- | ---: | ---: | :--- | :--- | :--- | :--- |
| Signal created -> seen | 0 | 2 | INCOMPLETE (NO_SEEN_TIMESTAMP) | INCOMPLETE | INCOMPLETE | s |
| Signal created -> delivery requested (proxy) | 0 | 2 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | s |
| Delivery requested -> approved | 0 | 1 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | s |
| Signal created -> approved | 1 | 0 | 30.0 [interval absent] n=1 | 30.0 | 30.0 | s |
| Approved -> order placed | 1 | 0 | 1.0 [interval absent] n=1 | 1.0 | 1.0 | s |
| Order placed -> filled (wait-to-fill) | 1 | 0 | 420.0 [interval absent] n=1 | 420.0 | 420.0 | s |
| Fill % | 1 | - | 100.00% | - | - | % |
| Expiry without fill rate | 1 | - | 0.00% | - | - | % |
| Entry deviation (price, signed; positive = worse) | 0 | 1 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | price |
| Entry deviation (bps of intended) | 0 | 1 | INCOMPLETE (NOT_MEASURED_FOR_EVIDENCE) | INCOMPLETE | INCOMPLETE | bps |

### 6.3 LIVE

*Evidence: LIVE*

| Leg / metric | n measured | n INCOMPLETE | Mean | Median | p90 | Unit |
| :--- | ---: | ---: | :--- | :--- | :--- | :--- |
| Signal created -> seen | 0 | 0 | INCOMPLETE (NO_SEEN_TIMESTAMP) | INCOMPLETE | INCOMPLETE | s |
| Signal created -> delivery requested (proxy) | 0 | 0 | no data | no data | no data | s |
| Delivery requested -> approved | 0 | 0 | no data | no data | no data | s |
| Signal created -> approved | 0 | 0 | no data | no data | no data | s |
| Approved -> order placed | 0 | 0 | no data | no data | no data | s |
| Order placed -> filled (wait-to-fill) | 0 | 0 | no data | no data | no data | s |
| Fill % | 0 | - | no data | - | - | % |
| Expiry without fill rate | 0 | - | no data | - | - | % |
| Entry deviation (price, signed; positive = worse) | 0 | 0 | no data | no data | no data | price |
| Entry deviation (bps of intended) | 0 | 0 | no data | no data | no data | bps |

---

## 7. MFE / MAE

### 7.1 BACKTEST

*Evidence: BACKTEST*

| Measure | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| MFE (price) | 2 | 2.90 [1.79750, 4.00250] n=2 | 2.90 | 4.580 | price | LOW_N |
| MAE (price) | 2 | 2.90 [2.90000, 5.00000] n=2 | 2.90 | 4.580 | price | LOW_N |
| MFE (R) | 2 | 0.5800 [0.1600, 0.8005] n=2 | 0.5800 | 0.9160 | R | LOW_N |
| MAE (R) | 2 | 0.5800 [0.3595, 1.0000] n=2 | 0.5800 | 0.9160 | R | LOW_N |
| Time to MFE | 2 | 45.0 [0.0, 45.0] n=2 | 45.0 | 81.0 | s | LOW_N |
| Time to MAE | 2 | 45.0 [21.4, 45.0] n=2 | 45.0 | 81.0 | s | LOW_N |
| Holding duration | 2 | 160.0 [160.0, 160.0] n=2 | 160.0 | 160.0 | s | LOW_N |

| MFE (R) of stop-loss exits | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | R | LOW_N |

| MAE (R) of take-profit exits | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 2 | 0.5800 [0.5800, 0.8005] n=2 | 0.5800 | 0.9160 | R | LOW_N |

| MFE (R) vs realized R (give-back) | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 2 | -0.2200 [-0.6400, 0.2000] n=2 | -0.2200 | 0.1160 | R | LOW_N |

| Holding duration distribution | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 2 | 160.0 [160.0, 160.0] n=2 | 160.0 | 160.0 | s | LOW_N |

### 7.2 PAPER

*Evidence: PAPER*

| Measure | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| MFE (price) | 0 | no data | no data | no data | price | LOW_N |
| MAE (price) | 0 | no data | no data | no data | price | LOW_N |
| MFE (R) | 0 | no data | no data | no data | R | LOW_N |
| MAE (R) | 0 | no data | no data | no data | R | LOW_N |
| Time to MFE | 0 | no data | no data | no data | s | LOW_N |
| Time to MAE | 0 | no data | no data | no data | s | LOW_N |
| Holding duration | 0 | no data | no data | no data | s | LOW_N |

| MFE (R) of stop-loss exits | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | R | LOW_N |

| MAE (R) of take-profit exits | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | R | LOW_N |

| MFE (R) vs realized R (give-back) | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | R | LOW_N |

| Holding duration distribution | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | s | LOW_N |

### 7.3 LIVE

*Evidence: LIVE*

| Measure | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| MFE (price) | 0 | no data | no data | no data | price | LOW_N |
| MAE (price) | 0 | no data | no data | no data | price | LOW_N |
| MFE (R) | 0 | no data | no data | no data | R | LOW_N |
| MAE (R) | 0 | no data | no data | no data | R | LOW_N |
| Time to MFE | 0 | no data | no data | no data | s | LOW_N |
| Time to MAE | 0 | no data | no data | no data | s | LOW_N |
| Holding duration | 0 | no data | no data | no data | s | LOW_N |

| MFE (R) of stop-loss exits | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | R | LOW_N |

| MAE (R) of take-profit exits | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | R | LOW_N |

| MFE (R) vs realized R (give-back) | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | R | LOW_N |

| Holding duration distribution | n | Mean | Median | p90 | Unit | Low-n |
| :--- | ---: | :--- | :--- | :--- | :--- | :--- |
| Distribution | 0 | no data | no data | no data | s | LOW_N |

Window: entry minute through exit minute, inclusive, 1m high/low. Trades without 1m coverage are counted as INCOMPLETE.

These distributions are descriptive. They imply no change to take-profit, stop-loss, entry, or holding rules.

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

---

## 8. Robustness Slices

Every slice table starts with the unsliced ALL row. Slices are ordered by key, never by result.

### 8.1 Symbol

(BACKTEST 2 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| BTCUSDT | 1 | 1 | 0.8000 [interval absent] n=1 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ETHUSDT | 1 | 1 | 0.8000 [interval absent] n=1 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

### 8.2 Month

(BACKTEST 1 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| 2026-01 | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

### 8.3 Quarter

(BACKTEST 1 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| 2026-Q1 | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

### 8.4 Session

(BACKTEST 1 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

Session bands (UTC hour of entry time): ASIA 00-08, EUROPE 08-16, US 16-24

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| EUROPE | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

### 8.5 Direction (long/short)

(BACKTEST 2 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| LONG | 1 | 1 | 0.8000 [interval absent] n=1 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| SHORT | 1 | 1 | 0.8000 [interval absent] n=1 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

### 8.6 Volatility regime

(BACKTEST 1 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

Volatility regime is UNKNOWN until a derivation lands.

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| UNKNOWN | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

### 8.7 Trend/range regime

(BACKTEST 1 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| UNKNOWN | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

### 8.8 Strategy version

(BACKTEST 1 slices, n=2; PAPER 0 slices, n=0; LIVE 0 slices, n=0)

*Evidence: BACKTEST | PAPER | LIVE (separate rows, not pooled)*

| Slice key | n | R-valued n | Mean R [interval] | Win rate | Expectancy (R) | Low-n | Evidence |
| :--- | ---: | ---: | :--- | ---: | ---: | :--- | :--- |
| ALL (unsliced) | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| v2.0.0 | 2 | 2 | 0.8000 [0.8000, 0.8000] n=2 | 1.0000 | 0.8000 | LOW_N | BACKTEST |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | PAPER |
| ALL (unsliced) | 0 | 0 | no data | no data | no data | LOW_N | LIVE |

LOW_N: n < 30. Flag only; not an acceptance threshold. The row is not hidden.

---

## 9. Incomplete and Excluded Inputs

| Evidence | Input | Reason | Count |
| :--- | :--- | :--- | ---: |
| BACKTEST | adapter.rejected_rows | MALFORMED_ROW | 1 |
| BACKTEST | execution_quality.APPROVED_TO_ORDER | NOT_MEASURED_FOR_EVIDENCE | 2 |
| BACKTEST | execution_quality.DELIVERY_TO_APPROVED | NOT_MEASURED_FOR_EVIDENCE | 2 |
| BACKTEST | execution_quality.ORDER_TO_FILL | NOT_MEASURED_FOR_EVIDENCE | 2 |
| BACKTEST | execution_quality.SIGNAL_TO_APPROVED | NOT_MEASURED_FOR_EVIDENCE | 2 |
| BACKTEST | execution_quality.SIGNAL_TO_DELIVERY | NOT_MEASURED_FOR_EVIDENCE | 2 |
| BACKTEST | execution_quality.SIGNAL_TO_SEEN | NOT_MEASURED_FOR_EVIDENCE | 2 |
| BACKTEST | execution_quality.deviation | NO_INTENDED_PRICE | 2 |
| PAPER | approval_delay.OPPORTUNITY | NO_HYPOTHETICAL_OUTCOME | 1 |
| PAPER | approval_delay.SYSTEM | NO_HYPOTHETICAL_OUTCOME | 1 |
| PAPER | approval_delay.SYSTEM | NO_PAPER_OUTCOME | 1 |
| PAPER | approval_delay.USER_EXECUTION | NO_PAPER_OUTCOME | 1 |
| PAPER | execution_quality.DELIVERY_TO_APPROVED | NOT_MEASURED_FOR_EVIDENCE | 1 |
| PAPER | execution_quality.SIGNAL_TO_DELIVERY | NOT_MEASURED_FOR_EVIDENCE | 2 |
| PAPER | execution_quality.SIGNAL_TO_SEEN | NO_SEEN_TIMESTAMP | 2 |
| PAPER | execution_quality.deviation | NOT_MEASURED_FOR_EVIDENCE | 1 |

adapter.rejected_rows: 1 rows rejected (MALFORMED_ROW). The report was produced without them. Fix the input and regenerate.

---

## 10. Provenance

| Field | Value |
| :--- | :--- |
| strategyVersion | v2.0.0 |
| parameterSetId | PS-1 |
| parameterSetHash | aaaaaaaaaaaa |
| experiment identity (BACKTEST) | experiment_id=e1e1e1e1e1e1; strategy_version=v2.0.0; parameter_set_id=PS-1; parameter_set_hash=aaaaaaaaaaaa; data_snapshot_id=d1d1d1d1d1d1; code_version=code-abc123; cost_model_hash=c1c1c1c1c1c1 |
| universe hash | 760c0431a63a (VERIFIED) |
| dataset/version identifiers | snapshots: d1d1d1d1d1d1; schema: analytics-schema/1 |
| epoch_id (paper) | EPOCH-1 |
| APPROVAL_DELAY_LAG_SECONDS | 30 |
| LOW_N_THRESHOLD | 30 |
| resamples | 100 |
| base_seed | 20260929 |
| slice vocabulary version | slices/1 |
| session bands | ASIA 00-08, EUROPE 08-16, US 16-24 |
| evidence kinds present | BACKTEST, PAPER |
