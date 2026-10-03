"""Symbol validation rejects a trailing newline everywhere it matters (WR-03).

`re.match(r"^[A-Z0-9]+USDT$", "BTCUSDT\\n")` succeeds because `$` also matches
before a trailing newline. A symbol that reaches a `symbol=...` directory, a
cursor file name or an archive URL must be exactly the validated text.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.decision_alignment.universe import SYMBOL_RE as UNIVERSE_SYMBOL_RE
from src.data.archive import SYMBOL_RE as ARCHIVE_SYMBOL_RE
from src.data.archive import archive_zip_url
from src.data.collect_list import SYMBOL_RE as COLLECT_SYMBOL_RE
from src.data.collect_list import CollectListError, _validate_symbols

BAD = ["BTCUSDT\n", "BTCUSDT\r\n", "\nBTCUSDT", "btcusdt", "BTC USDT", ""]


@pytest.mark.parametrize("symbol", BAD)
@pytest.mark.parametrize(
    "pattern",
    [ARCHIVE_SYMBOL_RE, COLLECT_SYMBOL_RE, UNIVERSE_SYMBOL_RE],
    ids=["archive", "list", "universe"],
)
def test_symbol_pattern_users_reject_malformed_text(pattern: object, symbol: str) -> None:
    import re

    assert isinstance(pattern, re.Pattern)
    assert pattern.fullmatch(symbol) is None


def test_archive_url_builder_rejects_a_trailing_newline() -> None:
    with pytest.raises(ValueError, match="invalid archive symbol"):
        archive_zip_url("BTCUSDT\n", "1h", "monthly", "2024-01")
    assert archive_zip_url("BTCUSDT", "1h", "monthly", "2024-01").startswith("https://")


def test_collect_list_validation_rejects_a_trailing_newline(tmp_path: Path) -> None:
    with pytest.raises(CollectListError, match="invalid symbol"):
        _validate_symbols(["BTCUSDT\n"], tmp_path / "list.toml")
    live5 = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    assert _validate_symbols(live5, tmp_path / "list.toml") == tuple(sorted(live5))
