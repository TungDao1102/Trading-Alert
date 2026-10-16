# range-mr regime_filter_lookback 50 vs 100: probe (2026-10-16)

Question: why do range-mr points c01..c08 and c09..c16 (differing only in regime_filter_lookback 50 vs 100) report identical feasibility counts?

Finding: the parameter is read (src/core/strategy.py _resolve_regime_pivots, geometry_version 1 path) and is live, not dead. The regime verdict depends on the newest two confirmed 4H pivot highs and lows inside the lookback; with pivot width 3 they almost always lie within 50 bars (200 h), so 100 bars gives the same verdict. They differ only when the 50-bar window holds fewer than two pivots of a kind (NO_TRADE at 50, NEUTRAL or BULLISH at 100).

Probe: the function itself on real 4H trade klines, windows of 300 bars as the engine uses, only files dated before 2026-05-10 (no Holdout day read), 4 symbols (not all 12), pivot widths 3/3, 3,394 bars per symbol, no trades simulated.

```
BTCUSDT regime differs 0 of 3394
ETHUSDT regime differs 15 of 3394 (NO_TRADE->NEUTRAL 12, NO_TRADE->BULLISH 3)
BNBUSDT regime differs 2 of 3394 (NO_TRADE->NEUTRAL 2)
SOLUSDT regime differs 14 of 3394 (NO_TRADE->NEUTRAL 14)
```

Consequence: on this data the lookback axis is practically flat, so the 16 range-mr points behave as 8; the plateau section's neighbours along that axis are identical by construction of the data, not evidence of robustness. Script: scratchpad regime_probe.py (copied below).

```python
import glob, re
from datetime import date
import polars as pl
from src.core.types import Candle
from src.core.strategy import _resolve_regime_pivots

class PS:  # minimal stand-in: only .params is read
    def __init__(self, lb): self.params = {"regime_filter_lookback": lb, "pivot_left_bars": 3, "pivot_right_bars": 3}

CUT = date(2026, 5, 10)  # nothing on or after the Holdout start is read
SYMS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
for sym in SYMS:
    files = [f for f in sorted(glob.glob(f"data/raw/interval=4h/symbol={sym}/date=*/part.parquet"))
             if date.fromisoformat(re.search(r"date=([\d-]+)", f).group(1)) < CUT]
    if not files: print(sym, "no files"); continue
    df = pl.concat([pl.read_parquet(f) for f in files]).sort("open_time_utc")
    cs = [Candle(r["symbol"], r["interval"], r["open_time_utc"], r["close_time_utc"], r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in df.iter_rows(named=True)]
    diff = 0; tally = {}
    n = 0
    for i in range(110, len(cs)):
        win = cs[max(0, i - 299): i + 1]
        a = _resolve_regime_pivots(win, PS(50)); b = _resolve_regime_pivots(win, PS(100))
        n += 1
        tally[(a, b)] = tally.get((a, b), 0) + 1
        diff += a != b
    print(sym, "bars", len(cs), "checked", n, "regime differs", diff, tally if diff else "")
```
