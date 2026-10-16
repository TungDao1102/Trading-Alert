"""The ratified runtime configuration file equals the user's decision records (plan 16-34).

Plan 16-56: the configuration in force is `paper-runtime-v2.toml`, every v1 value unchanged plus
the owner's `[health] feed_silence_timeout_seconds` (16-DEC-WS-WATCHDOG). The v1 file stays
byte-unchanged as the historical version, and the loader now refuses it for the missing key.
"""

from __future__ import annotations

import re
import tomllib
from decimal import Decimal
from pathlib import Path

from src.paper.runtime_config import load_runtime_config

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "paper" / "paper-runtime-v2.toml"
CONFIG_V1 = ROOT / "config" / "paper" / "paper-runtime-v1.toml"
DECISIONS = ROOT / ".planning" / "phases" / "16-paper-runtime-composition" / "decisions"
O07 = DECISIONS / "16-DEC-O-07.md"
O09 = DECISIONS / "16-DEC-O-09.md"
WATCHDOG = DECISIONS / "16-DEC-WS-WATCHDOG.md"
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
    watchdog = _record_values(WATCHDOG, ("health",))
    assert watchdog == {("health", "feed_silence_timeout_seconds"): "120"}, watchdog
    assert not set(watchdog) & set(values), "the new key is not an O-07 key"
    values.update(watchdog)
    return values


def _file_values(path: Path = CONFIG) -> dict[tuple[str, str], str]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
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
    for record in ("16-DEC-O-07", "16-DEC-O-09", "16-DEC-WS-WATCHDOG", "16-DEC-FIXPLANS"):
        assert record in text, record
    readme = README.read_text(encoding="utf-8")
    for _section, key in _file_values():
        assert f"`{key}`" in readme, key


def test_the_freeze_grace_is_strictly_smaller_than_the_workflow_slot_interval() -> None:
    cron = re.search(r'cron:\s*"(\S+) \* \* \* \*"', FREEZE_WORKFLOW.read_text(encoding="utf-8"))
    assert cron is not None, "the freeze workflow must be an hourly M * * * * cron"
    grace = int(_decisions()[("health", "freeze_tick_grace_seconds")])
    assert grace < 3600


def test_v2_is_v1_plus_exactly_the_watchdog_key() -> None:
    v1, v2 = _file_values(CONFIG_V1), _file_values(CONFIG)
    assert {key: v2[key] for key in v1} == v1, "every v1 value is copied unchanged"
    assert set(v2) - set(v1) == {("health", "feed_silence_timeout_seconds")}
    assert v2[("timing", "rest_backfill_depth_bars")] == "1500"  # correction 5: same file


def test_the_historical_v1_file_is_refused_for_the_missing_key() -> None:
    import pytest
    from src.paper.runtime_config import ConfigNotRatified

    with pytest.raises(ConfigNotRatified, match="health.feed_silence_timeout_seconds"):
        load_runtime_config(str(CONFIG_V1))


def test_the_new_key_is_required_strictly_positive_and_has_no_default() -> None:
    import dataclasses

    import pytest
    from src.paper.runtime_config import (
        HEALTH_KEYS,
        ConfigNotRatified,
        RuntimeHealthConfig,
        parse_runtime_config,
    )

    assert "feed_silence_timeout_seconds" in HEALTH_KEYS
    field = next(
        f
        for f in dataclasses.fields(RuntimeHealthConfig)
        if f.name == "feed_silence_timeout_seconds"
    )
    assert field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    raw = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    for bad in (0, -1, True, "120"):
        raw["health"]["feed_silence_timeout_seconds"] = bad
        with pytest.raises(ConfigNotRatified, match="health.feed_silence_timeout_seconds"):
            parse_runtime_config(raw)
    del raw["health"]["feed_silence_timeout_seconds"]
    with pytest.raises(ConfigNotRatified, match="health.feed_silence_timeout_seconds"):
        parse_runtime_config(raw)


def test_the_readme_names_v2_as_the_values_file_and_keeps_v1_as_history() -> None:
    text = README.read_text(encoding="utf-8")
    assert "`paper-runtime-v2.toml`" in text
    assert "`paper-runtime-v1.toml`" in text and "history" in text
    assert "may be zero" not in text
