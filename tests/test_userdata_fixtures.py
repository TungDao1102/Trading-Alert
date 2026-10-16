"""Synthetic user-data fixture files (Phase 18, plan 18-24, D-21).

Every file under `tests/fixtures/phase18/synthetic/` is SYNTHETIC (label
SYNTHETIC_FROM_SDK_MODEL): it is the output of a frame builder of
`tests/support/userdata_frames.py` (plan 18-03), written as sorted-key,
2-space-indented JSON with LF newlines. Nothing here was recorded from
Binance. The tests pin each file equal to its builder, so a fixture cannot
drift from the frames the parser tests use; they parse every file to its typed
event, fold the TRADE file through the unchanged idempotent `fold_fills`, and
check that `tests/fixtures/phase18/README.md` lists exactly the files present.

No network: the frames come from the builders and the files on disk.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_userdata_events import (
    AccountUpdateEvent,
    AlgoUpdateEvent,
    ListenKeyExpiredEvent,
    OrderUpdateEvent,
    parse_stream_message,
    to_fill_event,
)
from src.execution.fill_monitor import CurrentPositionView, FillEvent, fold_fills
from src.ops.redaction import REDACTED, scrub

from tests.support.userdata_frames import (
    FRAME_LABEL,
    SYNTHETIC_LISTEN_KEY,
    account_update_frame,
    algo_update_frame,
    listen_key_expired_frame,
    order_trade_update_frame,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "phase18"
SYNTHETIC_DIR = FIXTURE_ROOT / "synthetic"
README = FIXTURE_ROOT / "README.md"
SYNTHETIC_SECTION = "Synthetic frames"

OBSERVED_AT = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)

# The `rm` text of the REJECTED algo fixture: the same synthetic reason the plan 18-03
# parser tests use, not a reason captured from Binance.
SYNTHETIC_REJECT_REASON = "Reduce Only reject"

# Each fixture file name -> a zero-argument callable returning the wire dict of the
# plan 18-03 builder it was written from (with the overrides the plan 18-03 tests use).
FIXTURE_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "order_trade_update_trade.json": order_trade_update_frame,
    "order_trade_update_new.json": lambda: order_trade_update_frame(
        x="NEW", X="NEW", l="0", z="0", L="0"
    ),
    "algo_update_new.json": algo_update_frame,
    "algo_update_rejected.json": lambda: algo_update_frame(
        X="REJECTED", rm=SYNTHETIC_REJECT_REASON
    ),
    "account_update_order.json": account_update_frame,
    "listen_key_expired.json": listen_key_expired_frame,
}


def _canonical_text(frame: dict[str, Any]) -> str:
    """The exact file text of a fixture: sorted keys, 2-space indent, one trailing LF."""
    return json.dumps(frame, sort_keys=True, indent=2) + "\n"


def _load(name: str) -> dict[str, Any]:
    loaded = json.loads((SYNTHETIC_DIR / name).read_bytes().decode("ascii"))
    assert isinstance(loaded, dict)
    return loaded


def _parse(name: str) -> object:
    return parse_stream_message(_load(name), observed_at_utc=OBSERVED_AT)


# --------------------------------------------------------------------------- #
# The file form equals the builder output (D-21).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(FIXTURE_BUILDERS))
def test_fixture_file_equals_its_builder(name: str) -> None:
    data = (SYNTHETIC_DIR / name).read_bytes()
    assert b"\r" not in data, "fixture must be LF-only"
    assert data.endswith(b"\n")
    assert not data.endswith(b"\n\n"), "fixture must end with a single newline"
    frame = FIXTURE_BUILDERS[name]()
    assert json.loads(data.decode("ascii")) == frame
    assert data.decode("ascii") == _canonical_text(frame)


# --------------------------------------------------------------------------- #
# The tracer: TRADE file -> OrderUpdateEvent -> FillEvent -> folded view.
# --------------------------------------------------------------------------- #


def _flat_view() -> CurrentPositionView:
    return CurrentPositionView(symbol="BTCUSDT", position_side="BOTH", position_amt=Decimal("0"))


def test_trade_fixture_parses_converts_and_folds_to_one_unique_fill() -> None:
    event = _parse("order_trade_update_trade.json")
    assert isinstance(event, OrderUpdateEvent)
    assert event.execution_type == "TRADE"

    fill = to_fill_event(event)
    assert isinstance(fill, FillEvent)

    once = fold_fills(fill_events=[fill], current_position_view=_flat_view())
    twice = fold_fills(fill_events=[fill, fill], current_position_view=_flat_view())
    for view in (once, twice):
        assert view.fill_count == 1
        assert view.filled_quantity == Decimal("0.004")
        folded = view.fills[0]
        assert folded["order_id"] == "8000000001"
        assert folded["exchange_trade_id"] == "900000001"
        assert folded["commission"] == Decimal("0.09600000")
        assert folded["commission_asset"] == "USDT"
        assert folded["realized_pnl"] == Decimal("0")
        assert folded["is_maker"] is False
    assert once.fills == twice.fills


# --------------------------------------------------------------------------- #
# README provenance: the "Synthetic frames" rows equal the files present.
# --------------------------------------------------------------------------- #


def _section(readme_text: str, heading: str) -> list[str]:
    """The lines of the `## <heading>` section, up to the next `## ` heading."""
    lines = readme_text.splitlines()
    start = lines.index(f"## {heading}") + 1
    out: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def _synthetic_rows(readme_text: str) -> dict[str, str]:
    """File name -> label for each table row of the "Synthetic frames" section."""
    rows: dict[str, str] = {}
    for line in _section(readme_text, SYNTHETIC_SECTION):
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if cells[0] in ("File", "") or set(cells[0]) <= {"-", ":", " "}:
            continue
        assert cells[0] not in rows, f"duplicate README row {cells[0]}"
        rows[cells[0]] = cells[-1]
    return rows


def _readme_mismatch(readme: Path, synthetic_dir: Path) -> tuple[set[str], set[str]]:
    """(files without a row, rows without a file)."""
    rows = set(_synthetic_rows(readme.read_text(encoding="ascii")))
    files = {path.name for path in synthetic_dir.glob("*.json")}
    return files - rows, rows - files


def test_readme_synthetic_rows_equal_the_files_present() -> None:
    assert _readme_mismatch(README, SYNTHETIC_DIR) == (set(), set())
    rows = _synthetic_rows(README.read_text(encoding="ascii"))
    assert rows
    assert set(rows.values()) == {FRAME_LABEL}
    assert set(FIXTURE_BUILDERS) == set(rows)


def test_readme_states_the_provenance_of_the_synthetic_frames() -> None:
    text = README.read_text(encoding="ascii")
    section = " ".join(_section(text, SYNTHETIC_SECTION))
    assert "SDK model" in section
    assert "not recorded from Binance" in section
    assert "RECORDED_DEMO" in section
    assert "18-21" in section


def test_readme_check_fails_for_a_file_without_a_row_and_a_row_without_a_file(
    tmp_path: Path,
) -> None:
    readme = tmp_path / "README.md"
    synthetic = tmp_path / "synthetic"
    shutil.copy(README, readme)
    shutil.copytree(SYNTHETIC_DIR, synthetic)
    assert _readme_mismatch(readme, synthetic) == (set(), set())

    (synthetic / "unlisted_extra.json").write_bytes(b"{}\n")
    assert _readme_mismatch(readme, synthetic) == ({"unlisted_extra.json"}, set())

    (synthetic / "unlisted_extra.json").unlink()
    (synthetic / "order_trade_update_trade.json").unlink()
    assert _readme_mismatch(readme, synthetic) == (set(), {"order_trade_update_trade.json"})


def test_rows_of_other_sections_are_not_compared(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    text = README.read_text(encoding="ascii")
    other = "\n## Recorded demo frames\n\n| File | Event | Label |\n|---|---|---|\n"
    other += "| recorded_only.json | ORDER_TRADE_UPDATE | RECORDED_DEMO |\n"
    readme.write_text(text + other, encoding="ascii")
    assert _readme_mismatch(readme, SYNTHETIC_DIR) == (set(), set())


# --------------------------------------------------------------------------- #
# Per-kind parse expectations.
# --------------------------------------------------------------------------- #


def test_new_order_fixture_parses_and_has_no_fill() -> None:
    event = _parse("order_trade_update_new.json")
    assert isinstance(event, OrderUpdateEvent)
    assert event.execution_type == "NEW"
    assert event.order_status == "NEW"
    assert event.trade_id is None
    assert to_fill_event(event) is None


def test_new_algo_fixture_parses_to_an_algo_update_event() -> None:
    event = _parse("algo_update_new.json")
    assert isinstance(event, AlgoUpdateEvent)
    assert event.algo_status == "NEW"
    assert event.reject_reason is None


def test_rejected_algo_fixture_keeps_rm_as_a_diagnostic() -> None:
    event = _parse("algo_update_rejected.json")
    assert isinstance(event, AlgoUpdateEvent)
    assert event.algo_status == "REJECTED"
    assert event.reject_reason == SYNTHETIC_REJECT_REASON
    assert _load("algo_update_rejected.json")["o"]["rm"] == SYNTHETIC_REJECT_REASON


def test_account_update_fixture_parses_with_balance_and_position_rows() -> None:
    event = _parse("account_update_order.json")
    assert isinstance(event, AccountUpdateEvent)
    assert event.reason == "ORDER"
    assert len(event.balances) >= 1
    assert len(event.positions) >= 1


def test_listen_key_expired_fixture_parses_and_its_key_stays_out_of_the_event() -> None:
    key = _load("listen_key_expired.json")["listenKey"]
    event = _parse("listen_key_expired.json")
    assert isinstance(event, ListenKeyExpiredEvent)
    assert key not in repr(event)
    assert key not in str(event)


# --------------------------------------------------------------------------- #
# Secret shapes (D-22, research P3, T-18-73).
# --------------------------------------------------------------------------- #

_LISTEN_KEY_NAME = re.compile(r"(?i)^listen_?key$")


def _mask_listen_key_values(value: Any) -> Any:
    """`value` with the value under every listenKey-named key replaced by REDACTED.

    This mirrors the redactor's key-name rule: in JSON text it masks the value of a
    `"listenKey"` key whatever that value is (plan 18-04). Every other value of a fixture
    must come out of the redactor unchanged.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED if _LISTEN_KEY_NAME.match(key) else _mask_listen_key_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_listen_key_values(item) for item in value]
    return value


@pytest.mark.parametrize("name", sorted(FIXTURE_BUILDERS))
def test_redactor_changes_no_fixture_value_other_than_the_listen_key_field(name: str) -> None:
    text = (SYNTHETIC_DIR / name).read_bytes().decode("ascii")
    expected = _canonical_text(_mask_listen_key_values(json.loads(text)))
    assert scrub(text) == expected
    if "listenKey" not in text:
        assert scrub(text) == text


def test_the_dummy_listen_key_is_not_listen_key_shaped() -> None:
    key = listen_key_expired_frame()["listenKey"]
    assert key == SYNTHETIC_LISTEN_KEY
    assert "SYNTHETIC" in key
    assert "DUMMY" in key
    # Outside the JSON key-name rule the value itself is not secret-shaped.
    for text in (key, f"listenKey={key}", f"listen_key={key}", f"?listenKey={key}&x=1"):
        assert scrub(text) == text


def test_a_realistic_listen_key_is_changed_by_the_redactor() -> None:
    # Negative control: a made-up key of the realistic shape (64 alphanumerics).
    realistic = ("Ab3" * 22)[:64]
    assert len(realistic) >= 24
    for text in (f"listenKey={realistic}", json.dumps({"listenKey": realistic})):
        scrubbed = scrub(text)
        assert scrubbed != text
        assert realistic not in scrubbed
