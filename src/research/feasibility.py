"""Feasibility and sample-size report (Phase 16, plan 16-12, D-26; inherited G3-027, D043).

Reporting only (L-03). It counts closed trades the way acceptance gate G1 counts them, sets
the pooled and per-fold counts beside the protocol floors and names every shortfall. It never
lowers a floor, never ranks or orders anything by a count, and never reads or runs the
holdout (REV-06: counting holdout trades would consume the single-use holdout).

User decision Q-O (decisions/16-DEC-Q-O.md, option not-assessed): only Development and
Validation counts are reported; the G5 floor is printed as not assessed. There is no holdout
count, no extrapolation and no protocol change.

The closed-trade rule is the one `src/backtest/report.py` applies: a filled entry
(ENTRY_FILLED or PARTIAL_FILL with outcome OK) that left by SL or TP2 is closed; a filled
entry that left at the end of the data is counted apart and is not closed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from src.backtest.semantics import (
    ENTRY_FILLED,
    EXIT_END_OF_DATA,
    EXIT_SL,
    EXIT_TP2,
    PARTIAL_FILL,
)

# RESEARCH_PROTOCOL.md v2.1.0 G1 (trade floor), D043: at least 100 closed trades pooled across
# the four Validation folds. Never lowered after the freeze.
G1_POOLED_FLOOR: Final = 100
# RESEARCH_PROTOCOL.md v2.1.0 G1, D043: at least 30 closed trades in each Validation fold.
# Never lowered after the freeze.
G1_PER_FOLD_FLOOR: Final = 30
# RESEARCH_PROTOCOL.md v2.1.0 G5, D060: at least 30 closed trades in the holdout, counted as G1
# counts. Never lowered after the freeze. A constant only: this module never counts the holdout.
G5_HOLDOUT_FLOOR: Final = 30

# The G1 closed-exit rule, built from the backtest semantics constants. A test pins these two
# sets to the private ones in src/backtest/report.py so the rule cannot drift apart.
FILLED_ENTRY_KINDS: Final = frozenset({ENTRY_FILLED, PARTIAL_FILL})
CLOSED_EXIT_KINDS: Final = frozenset({EXIT_SL, EXIT_TP2})


# The only statement about the G5 floor (Q-O, option not-assessed). The holdout stays unused
# until the real G5 evaluation.
G5_NOT_ASSESSED_LINE: Final = "G5 floor not assessed (holdout untouched)"


class FeasibilityError(Exception):
    """A trade record cannot be classified under the G1 rule."""


@dataclass(frozen=True)
class TradeCounts:
    """Closed trades (G1 rule) and END_OF_DATA trades counted apart."""

    closed: int
    end_of_data: int


@dataclass(frozen=True)
class FeasibilityReport:
    """Counts against the protocol floors for one grid point; holds no verdict or ordering."""

    parameter_set_id: str
    development_closed: int | None
    development_end_of_data: int | None
    pooled_closed: int
    pooled_end_of_data: int
    fold_closed: tuple[int, ...]
    fold_end_of_data: tuple[int, ...]
    pooled_floor: int
    per_fold_floor: int
    shortfalls: tuple[str, ...]


def count_closed_trades(trades: Sequence[Mapping[str, object]]) -> TradeCounts:
    """Count closed trades the way G1 does; END_OF_DATA exits are reported apart.

    Records that did not fill are plan outcomes and are not trades. A filled record with any
    other exit is refused rather than counted as a trade of unknown meaning.
    """
    closed = 0
    end_of_data = 0
    for trade in trades:
        filled = trade.get("outcome_kind") == "OK" and trade.get("entry_kind") in FILLED_ENTRY_KINDS
        if not filled:
            continue
        exit_kind = trade.get("exit_kind")
        if exit_kind in CLOSED_EXIT_KINDS:
            closed += 1
        elif exit_kind == EXIT_END_OF_DATA:
            end_of_data += 1
        else:
            raise FeasibilityError(
                f"filled trade {trade.get('trade_id')!r} has exit_kind {exit_kind!r}: "
                f"expected one of {sorted(CLOSED_EXIT_KINDS | {EXIT_END_OF_DATA})}"
            )
    return TradeCounts(closed=closed, end_of_data=end_of_data)


def feasibility_report(
    validation_folds: Sequence[Sequence[Mapping[str, object]]],
    *,
    parameter_set_id: str,
    development_trades: Sequence[Mapping[str, object]] | None = None,
) -> FeasibilityReport:
    """Closed-trade counts pooled over the Validation folds and per fold, with the shortfalls.

    Folds keep the order they were given (fold 1 is the first); nothing is sorted by a count.
    The Development window is counted when given and carries no floor.
    """
    development = None if development_trades is None else count_closed_trades(development_trades)
    counts = [count_closed_trades(fold) for fold in validation_folds]
    fold_closed = tuple(c.closed for c in counts)
    pooled = sum(fold_closed)
    shortfalls: list[str] = []
    if pooled < G1_POOLED_FLOOR:
        shortfalls.append(f"pooled: {pooled} closed trades, floor {G1_POOLED_FLOOR}")
    for index, closed in enumerate(fold_closed, start=1):
        if closed < G1_PER_FOLD_FLOOR:
            shortfalls.append(f"fold {index}: {closed} closed trades, floor {G1_PER_FOLD_FLOOR}")
    return FeasibilityReport(
        parameter_set_id=parameter_set_id,
        development_closed=None if development is None else development.closed,
        development_end_of_data=None if development is None else development.end_of_data,
        pooled_closed=pooled,
        pooled_end_of_data=sum(c.end_of_data for c in counts),
        fold_closed=fold_closed,
        fold_end_of_data=tuple(c.end_of_data for c in counts),
        pooled_floor=G1_POOLED_FLOOR,
        per_fold_floor=G1_PER_FOLD_FLOOR,
        shortfalls=tuple(shortfalls),
    )


def render_feasibility(report: FeasibilityReport) -> list[str]:
    """Neutral output lines: counts, floors and each shortfall; no verdict wording."""
    folds = ",".join(str(n) for n in report.fold_closed)
    eod = ",".join(str(n) for n in report.fold_end_of_data)
    development = (
        ""
        if report.development_closed is None
        else f"development_closed={report.development_closed} "
        f"development_end_of_data={report.development_end_of_data} "
    )
    lines = [
        f"feasibility parameter_set_id={report.parameter_set_id} "
        f"{development}pooled_closed={report.pooled_closed} pooled_floor={report.pooled_floor} "
        f"fold_closed={folds} fold_floor={report.per_fold_floor} "
        f"end_of_data_pooled={report.pooled_end_of_data} end_of_data_by_fold={eod}"
    ]
    lines.extend(
        f"feasibility parameter_set_id={report.parameter_set_id} shortfall {text}"
        for text in report.shortfalls
    )
    return lines
