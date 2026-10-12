"""The ratified runtime configuration file equals the user's decision records (plan 16-34)."""

from __future__ import annotations

import re
import tomllib
from decimal import Decimal
from pathlib import Path

from src.paper.runtime_config import load_runtime_config

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "paper" / "paper-runtime-v1.toml"
DECISIONS = ROOT / ".planning" / "phases" / "16-paper-runtime-composition" / "decisions"
O07 = DECISIONS / "16-DEC-O-07.md"
O09 = DECISIONS / "16-DEC-O-09.md"
README = ROOT / "config" / "paper" / "README.md"
FREEZE_WORKFLOW = ROOT / ".github" / "workflows" / "paper_freeze_check.yml"


def _record_values(path: Path, sections: tuple[str, ...]) -> dict[tuple[str, str], str]:
    """`[section]` then `key: value` lines of a decision record, as strings (never floats)."""
    out: dict[tuple[str, str], str] = {}
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        head = re.fullmatch(r"\[([a-z ]+)\]", line.strip())
        if head:
            section = head.group(1) if head.group(1) in sections else None
            continue
        pair = re.fullmatch(r"([a-z0-9_]+): (\S.*)", line)
        if section is not None and pair:
            key = (section, pair.group(1))
            assert key not in out, f"duplicate decision line {key}"
            out[key] = pair.group(2).strip()
    return out


def _decisions() -> dict[tuple[str, str], str]:
    values = _record_values(O07, ("health", "timing"))
    values.update(_record_values(O09, ("account", "scope")))
    return values


def _file_values() -> dict[tuple[str, str], str]:
    raw = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], str] = {}
    for section, body in raw.items():
        for key, value in body.items():
            out[(section, key)] = ",".join(value) if isinstance(value, list) else str(value)
    return out


def test_the_file_exists_and_the_loader_accepts_it() -> None:
    config = load_runtime_config(str(CONFIG))
    assert config.account.initial_equity == Decimal("600")
    assert config.account.risk_rate == Decimal("0.005")
    assert config.symbols == ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


def test_every_value_equals_its_decision_line_and_nothing_else_is_in_the_file() -> None:
    assert _file_values() == _decisions()


def test_the_file_names_its_decision_records_and_holds_no_key_outside_the_readme() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert "16-DEC-O-07" in text and "16-DEC-O-09" in text
    readme = README.read_text(encoding="utf-8")
    for _section, key in _file_values():
        assert f"`{key}`" in readme, key


def test_the_freeze_grace_is_strictly_smaller_than_the_workflow_slot_interval() -> None:
    cron = re.search(r'cron:\s*"(\S+) \* \* \* \*"', FREEZE_WORKFLOW.read_text(encoding="utf-8"))
    assert cron is not None, "the freeze workflow must be an hourly M * * * * cron"
    grace = int(_decisions()[("health", "freeze_tick_grace_seconds")])
    assert grace < 3600
