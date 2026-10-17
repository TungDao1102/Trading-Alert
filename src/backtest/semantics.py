"""Phase 14 simulator semantics constants (plan 14-01).

Constants only, no logic. Everything the causal simulator treats as a fixed
convention lives here so one version string covers it (D-02): changing any
value below is a semantics change and must bump `SIMULATOR_SEMANTICS_VERSION`.

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

# D-02: experiment-identity version of the simulator semantics. A record produced by
# the v1 simulator can never be compared with a v2 record.
# Documented exception (plan 14-17, review WR-05): the annotate-only mark-hole coverage note is
# NOT a semantics change. For input without a mark hole inside a position's life nothing changes;
# for input with such a hole only the `coverage_note` text moves, and with it the trade payload
# bytes and the hashes derived from them, while the version stayed 2.0.0 at the time because no
# price, time, cost, count or event moved (2.0.0 at the time; the version moved to 2.1.0 with the
# terminal settlement, D070). 2.2.0 (plan 16-60, D073) adds the research warm-up span below: for a
# case without warm-up input nothing but the version string and the ids hashed from it moves.
# 2.3.0 (plan 16-63, D075) adds the planner rule that a plan whose TP2 is not a positive price
# is NO_TRADE RR_TOO_LOW; for input where no plan has such a TP2 nothing but the version string
# and the ids hashed from it moves. A new NO_TRADE outcome moves counts and events, so the
# annotate-only exception above does not apply and the version moved.
SIMULATOR_SEMANTICS_VERSION = "2.3.0"

# D-27 (resolved by the user 2026-10-04): TP1 closes half the position. A code constant
# covered by SIMULATOR_SEMANTICS_VERSION, NOT a registry tunable; no params/ file changes.
TP1_QUANTITY_FRACTION = Decimal("0.5")

# D-25: the live leg matrix is exercised in one-way position mode only.
POSITION_MODE = "ONE_WAY"

# D-12: SL and a TP touched inside one 1m mark bar resolves to the stop. The name goes
# into the experiment record (BKTS-04).
TIE_BREAK = "STOP_FIRST"

# D-14/D-36: funding PnL = -sign(position) x open quantity x markPrice(fundingTime) x rate.
FUNDING_CONVENTION = "MARK_NOTIONAL_SIGNED_V1"

# D-36: a holding window is covered when consecutive funding rows are at most the max
# cadence plus jitter apart. These mirror DEFAULT_FUNDING_INTERVAL_MS and
# FUNDING_JITTER_MS in src/data/coverage.py; src/backtest must not import src/data, so
# plan 14-10 adds an equality test between the two sets of values.
FUNDING_MAX_CADENCE = timedelta(hours=8)
FUNDING_JITTER = timedelta(seconds=60)

# D-31: the strategy front-end is windowed (1h bars about 1,000, 4h bars about 300).
STRATEGY_WINDOW_BARS = 1000
CONTEXT_WINDOW_BARS = 300

# Plan 16-60 (review finding B3-CR-01, 16-DEC-V250 item 1, 16-DEC-FIXPLANS.md 16-60 Q0): the candle
# history a research window is built with BEFORE its start, for the indicators only (no signal is
# evaluated before the window start, no Holdout day is ever part of it, and it never starts before
# the dataset start). STRUCTURAL: it is not a tuned number; it is the whole-day ceiling of the span
# that fills the engine's two windows above, max(1000 x 1 h, 300 x 4 h) = 1200 h = 50 days, the same
# depth the paper REST warm-up loads (`src/paper/restart.py`). A code constant covered by
# SIMULATOR_SEMANTICS_VERSION (it moved to 2.2.0 with it), NOT a registry tunable.
RESEARCH_WARMUP_SPAN = timedelta(
    days=-(-max(STRATEGY_WINDOW_BARS * 1, CONTEXT_WINDOW_BARS * 4) // 24)
)

# D-01/D-34: terminal outcomes of a resting entry. `TOUCH_NO_FILL` is a per-plan counter
# on the record, never a terminal kind.
ENTRY_FILLED = "ENTRY_FILLED"
PARTIAL_FILL = "PARTIAL_FILL"
EXPIRED = "EXPIRED"
INVALIDATION_CANCEL = "INVALIDATION_CANCEL"
DAILY_STOP_CANCEL = "DAILY_STOP_CANCEL"
PENDING_AT_DATA_END = "PENDING_AT_DATA_END"
REJECT = "REJECT"
# Quick 261014-nnl: a resting entry cancelled at the declared terminal instant of its symbol.
SETTLEMENT_CANCEL = "SETTLEMENT_CANCEL"
ENTRY_KINDS = frozenset(
    {
        ENTRY_FILLED,
        PARTIAL_FILL,
        EXPIRED,
        INVALIDATION_CANCEL,
        DAILY_STOP_CANCEL,
        PENDING_AT_DATA_END,
        REJECT,
        SETTLEMENT_CANCEL,
    }
)

# D-06/D-11: how a filled position leaves. TP1 is a partial leg, not a terminal kind.
EXIT_SL = "SL"
EXIT_TP2 = "TP2"
EXIT_END_OF_DATA = "END_OF_DATA"
# Quick 261014-nnl: an OPEN position of a declared symbol closes at the terminal instant at the
# adverse bound of the recorded settlement interval (LONG at price_lower, SHORT at price_upper).
EXIT_SETTLEMENT = "SETTLEMENT"
EXIT_KINDS = frozenset({EXIT_SL, EXIT_TP2, EXIT_END_OF_DATA, EXIT_SETTLEMENT})

# D-32: one active plan or position per symbol; a re-signal meanwhile is skipped and
# counted under this summary-counter label (never a new RejectionReason member).
NO_TRADE_CONFLICT = "CONFLICT_WITH_OPEN_POSITION"

# Quick 261014-nnl (S-B-interval): summary-counter label of a setup that cannot activate before
# the terminal instant of its symbol (not a RejectionReason; counted by plan 04), the two
# strings a `terminal_settlements` case row must carry, and the prefix of the fixed-format
# `coverage_note` piece of a settled trade. Vocabulary only when added; SIMULATOR_SEMANTICS_VERSION
# moved to 2.1.0 in plan 07 (D070) after the regeneration inventory was approved.
NO_TRADE_TERMINAL = "TERMINAL_BEFORE_ACTIVATION"
TERMINAL_KIND_BOUNDED_BY_INDEX_KLINES = "BOUNDED_BY_INDEX_KLINES"
TERMINAL_EVALUATION_UNION_ADVERSE_BOUND = "UNION_ADVERSE_BOUND"
SETTLEMENT_NOTE_PREFIX = "terminal_settlement"

# Where a plan came from (strategy-driven run versus a hand-built scripted fixture).
PLAN_SOURCE_STRATEGY = "STRATEGY"
PLAN_SOURCE_SCRIPTED = "SCRIPTED"
