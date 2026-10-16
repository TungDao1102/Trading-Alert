"""Plan 16-57 Task 3: the effective configuration is bound to the pinned epoch (B1-WR-08).

Owner decision 16-DEC-CONFIG-PIN (16-57 Q1 = B, option `refuse-on-value-change`): the pin and
every start record the SHA-256 of the canonical, schema-validated effective configuration values;
every start recomputes it and a mismatch is refused with exit 6 in the held state of plan 16-55; a
comment or whitespace edit does not change the identity; the raw file SHA-256 is recorded for
provenance only and is never the comparison.

No network, no database: the admission rig of `tests/test_paper_runtime_admission.py` with the
in-memory state port and a no-op loop.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import src.domain.registry as domain_registry
from src.domain.canonical import canonical_bytes
from src.paper import held_marker, runtime
from src.paper.restart import EpochMismatch, check_epoch_consistency
from src.paper.runtime_config import (
    CONFIG_IDENTITY_FIELD,
    CONFIG_PROVENANCE_FIELD,
    REQUIRED_KEYS,
    ConfigNotRatified,
    ExitCode,
    config_identity,
    config_identity_payload,
    load_runtime_config,
    load_runtime_config_with_provenance,
    parse_runtime_config,
)
from src.paper.runtime_state import InMemoryRuntimeState, RuntimeRecord
from src.paper.vocabulary import RuntimeEventType

from tests.test_paper_runtime_admission import CONFIG_TEXT, _Rig
from tests.test_rationale import write_rationalized_set

REPO = Path(__file__).resolve().parent.parent
CONFIG_V2 = REPO / "config" / "paper" / "paper-runtime-v2.toml"


def identity_of(text: str) -> str:
    return config_identity(parse_runtime_config(tomllib.loads(text)))


# ---------------------------------------------------------------------------------------------- #
# Test 1: the identity.
# ---------------------------------------------------------------------------------------------- #

COSMETIC = """\
# A comment line that the identity must not see.

[scope]
symbols = [ "BTCUSDT",   "ETHUSDT" ]   # same order, other spacing

[account]
risk_rate = "0.010"
initial_equity      =   "1000"

[timing]
rest_backfill_depth_bars = 21
healthcheck_max_bar_age_seconds = 20
minute_close_lag_seconds = 19
minute_poll_interval_seconds = 18
exchange_info_refresh_seconds = 17
constraint_snapshot_ttl_seconds = 16
sibling_4h_wait_seconds = 15


[health]
feed_silence_timeout_seconds = 300
freeze_tick_grace_seconds = 14
continuous_uncovered_ceiling_seconds = 13
max_closed_bar_lateness_seconds = 12
max_ws_message_silence_seconds = 11
"""


def test_comments_whitespace_blank_lines_and_key_order_do_not_change_the_identity() -> None:
    assert identity_of(COSMETIC) == identity_of(CONFIG_TEXT)
    assert CONFIG_TEXT.encode() != COSMETIC.encode()


def _changed(section: str, key: str, value: Any) -> Any:
    if key == "symbols":
        return [*reversed(value)]  # the configured order is part of the identity
    if isinstance(value, int):
        return value + 1
    return str(Decimal(value) + Decimal("0.001"))


@pytest.mark.parametrize(
    ("section", "key"),
    [(section, key) for section, keys in REQUIRED_KEYS.items() for key in keys],
)
def test_every_changed_value_changes_the_identity(section: str, key: str) -> None:
    raw = tomllib.loads(CONFIG_TEXT)
    raw[section][key] = _changed(section, key, raw[section][key])
    assert config_identity(parse_runtime_config(raw)) != identity_of(CONFIG_TEXT)


def test_the_identity_is_sha256_of_the_canonical_validated_values() -> None:
    config = parse_runtime_config(tomllib.loads(CONFIG_TEXT))
    payload = config_identity_payload(config)
    assert payload == {
        "schema": "paper-runtime-config-identity/1",
        "health": {
            "max_ws_message_silence_seconds": 11,
            "max_closed_bar_lateness_seconds": 12,
            "continuous_uncovered_ceiling_seconds": 13,
            "freeze_tick_grace_seconds": 14,
            "feed_silence_timeout_seconds": 300,
        },
        "timing": {
            "sibling_4h_wait_seconds": 15,
            "constraint_snapshot_ttl_seconds": 16,
            "exchange_info_refresh_seconds": 17,
            "minute_poll_interval_seconds": 18,
            "minute_close_lag_seconds": 19,
            "healthcheck_max_bar_age_seconds": 20,
            "rest_backfill_depth_bars": 21,
        },
        "account": {"initial_equity": "1000", "risk_rate": "0.01"},
        "scope": {"symbols": ["BTCUSDT", "ETHUSDT"]},
    }
    assert config_identity(config) == hashlib.sha256(canonical_bytes(payload)).hexdigest()
    # Every key of the schema is in the form: nothing is dropped, nothing is defaulted.
    for section, keys in REQUIRED_KEYS.items():
        if section == "scope":
            assert set(payload["scope"]) == set(keys)
        else:
            assert tuple(payload[section]) == keys


@pytest.mark.parametrize(
    "edit",
    [
        lambda raw: raw["timing"].pop("rest_backfill_depth_bars"),
        lambda raw: raw["account"].update(extra="1"),
        lambda raw: raw.update(extras={"anything": 1}),
        lambda raw: raw.update(version=3),
        lambda raw: raw.pop("scope"),
    ],
    ids=["missing-key", "unknown-key", "unknown-section", "unknown-top-level-key", "no-section"],
)
def test_a_missing_or_unknown_key_is_refused_before_any_hash(edit: Any) -> None:
    raw = tomllib.loads(CONFIG_TEXT)
    edit(raw)
    with pytest.raises(ConfigNotRatified):
        parse_runtime_config(raw)


def test_the_loader_gives_the_identity_and_the_raw_file_hash_apart(tmp_path: Path) -> None:
    plain = tmp_path / "plain.toml"
    commented = tmp_path / "commented.toml"
    plain.write_text(CONFIG_TEXT, encoding="utf-8")
    commented.write_text(COSMETIC, encoding="utf-8")
    config_a, prov_a = load_runtime_config_with_provenance(str(plain))
    config_b, prov_b = load_runtime_config_with_provenance(str(commented))
    assert config_a == config_b == load_runtime_config(str(plain))
    assert prov_a.identity == prov_b.identity == config_identity(config_a)
    assert prov_a.file_sha256 == hashlib.sha256(plain.read_bytes()).hexdigest()
    assert prov_a.file_sha256 != prov_b.file_sha256
    assert prov_a.path == str(plain)
    assert prov_a.record_fields() == {
        CONFIG_IDENTITY_FIELD: prov_a.identity,
        CONFIG_PROVENANCE_FIELD: {"file_sha256": prov_a.file_sha256, "path": str(plain)},
    }


def test_the_configuration_in_force_loads_and_has_an_identity() -> None:
    config, provenance = load_runtime_config_with_provenance(str(CONFIG_V2))
    assert provenance.identity == config_identity(config)
    assert len(provenance.identity) == 64


# ---------------------------------------------------------------------------------------------- #
# Test 2: the pin and every start.
# ---------------------------------------------------------------------------------------------- #


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Rig]:
    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    yield rig


def _records(rig: _Rig, event: RuntimeEventType) -> list[RuntimeRecord]:
    return list(rig.state.records(rig.pinned().epoch_id, {event}))


def _provenance_of(record: RuntimeRecord) -> tuple[str, dict[str, Any]]:
    payload = json.loads(record.payload_json)
    return payload[CONFIG_IDENTITY_FIELD], payload[CONFIG_PROVENANCE_FIELD]


def _set_risk_rate(rig: _Rig, value: str) -> None:
    text = rig.config_path.read_text(encoding="utf-8")
    assert 'risk_rate = "0.01"' in text
    rig.config_path.write_text(text.replace('risk_rate = "0.01"', f'risk_rate = "{value}"'))


def test_the_pin_and_every_start_record_the_identity_and_the_provenance(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    expected = identity_of(CONFIG_TEXT)
    file_hash = hashlib.sha256(rig.config_path.read_bytes()).hexdigest()

    [pin] = _records(rig, RuntimeEventType.EPOCH_PINNED)
    identity, provenance = _provenance_of(pin)
    assert identity == expected
    assert provenance == {"file_sha256": file_hash, "path": str(rig.config_path)}

    assert rig.run() == 0
    [start] = _records(rig, RuntimeEventType.RUNTIME_START)
    assert _provenance_of(start) == (expected, provenance)


def test_a_comment_edit_runs_and_records_the_new_file_hash_as_provenance(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    rig.config_path.write_text(
        "# an operator note, nothing else changed\n" + CONFIG_TEXT, encoding="utf-8"
    )
    seen: list[str] = []
    assert rig.run(run_loop=lambda ctx: seen.append(str(ctx.config.account.risk_rate))) == 0
    assert seen == ["0.01"]
    [pin] = _records(rig, RuntimeEventType.EPOCH_PINNED)
    [start] = _records(rig, RuntimeEventType.RUNTIME_START)
    pin_identity, pin_provenance = _provenance_of(pin)
    start_identity, start_provenance = _provenance_of(start)
    assert start_identity == pin_identity
    assert start_provenance["file_sha256"] != pin_provenance["file_sha256"]
    assert (
        start_provenance["file_sha256"] == hashlib.sha256(rig.config_path.read_bytes()).hexdigest()
    )


def test_a_changed_value_is_refused_with_exit_6_before_runtime_start(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    """The B1-WR-08 re-check: on the parent this start exited 0 and ran with risk_rate 0.02."""
    assert rig.run("--pin-epoch") == 0
    _set_risk_rate(rig, "0.02")
    capsys.readouterr()

    code = rig.run(run_loop=lambda _ctx: pytest.fail("a refused start must not run the loop"))

    assert code == int(ExitCode.ADMISSION_OR_EPOCH_MISMATCH) == 6
    assert _records(rig, RuntimeEventType.RUNTIME_START) == []
    err = capsys.readouterr().err
    assert "effective runtime configuration differs" in err
    assert "16-DEC-CONFIG-PIN" in err
    assert "0.02" not in err, "the refusal names the identity, never a configuration value"


def test_a_changed_value_holds_with_the_marker_and_the_probe_reports_unhealthy(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rig.run("--pin-epoch") == 0
    _set_risk_rate(rig, "0.02")
    marker_dir = rig.pinned_path.parent
    probes: list[tuple[held_marker.HeldMarker | None, int, str]] = []

    def wait_for_stop() -> None:
        capsys.readouterr()
        code = runtime.main(
            ["--healthcheck", "--pinned-state", str(rig.pinned_path)],
            environ=rig.environ(),
            state=rig.state,
            registry_root=rig.root,
            clock=rig.clock,
        )
        probes.append((held_marker.read_own_marker(marker_dir), code, capsys.readouterr().out))

    code = runtime.main(
        ["--hold-on-refusal", "--pinned-state", str(rig.pinned_path)],
        environ=rig.environ(),
        wait_for_stop=wait_for_stop,
        state=rig.state,
        registry_root=rig.root,
        clock=rig.clock,
        run_loop=lambda _c: pytest.fail("a held start must not run the loop"),
    )

    assert code == 6
    [(marker, probe_code, out)] = probes
    assert marker is not None and marker.refusal == "ADMISSION_OR_EPOCH_MISMATCH"
    assert probe_code == 1 and out.startswith("unhealthy:")
    assert _records(rig, RuntimeEventType.RUNTIME_START) == []


def test_a_pin_record_without_an_identity_is_refused_never_accepted_silently(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    epoch = rig.pinned()
    [pin] = _records(rig, RuntimeEventType.EPOCH_PINNED)
    stripped = {
        k: v
        for k, v in json.loads(pin.payload_json).items()
        if k not in (CONFIG_IDENTITY_FIELD, CONFIG_PROVENANCE_FIELD)
    }
    legacy = InMemoryRuntimeState()
    legacy.record(
        RuntimeRecord(
            event_type=RuntimeEventType.EPOCH_PINNED,
            epoch_id=epoch.epoch_id,
            occurred_at_utc=pin.occurred_at_utc,
            payload=stripped,
        )
    )
    with pytest.raises(EpochMismatch, match="no configuration identity"):
        check_epoch_consistency(epoch, legacy, config_identity=identity_of(CONFIG_TEXT))

    rig.state = legacy
    assert rig.run(run_loop=lambda _c: pytest.fail("refused")) == 6
    assert list(legacy.records(epoch.epoch_id, {RuntimeEventType.RUNTIME_START})) == []


def test_check_epoch_consistency_compares_the_identity_only(rig: _Rig) -> None:
    assert rig.run("--pin-epoch") == 0
    epoch = rig.pinned()
    check_epoch_consistency(epoch, rig.state, config_identity=identity_of(CONFIG_TEXT))
    with pytest.raises(EpochMismatch, match="differs from the configuration the epoch was pinned"):
        check_epoch_consistency(epoch, rig.state, config_identity="0" * 64)
