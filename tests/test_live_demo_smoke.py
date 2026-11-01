"""The Demo smoke over the composed live process, on the fakes (plan 24-29, D-33).

TEST_ONLY: the exchange is the Binance-semantics fake and the presses are fake, so every step of
these runs is labelled SYNTHETIC; nothing here is, or is reported as, Demo-observed. The process is
the real `build_wiring` composition driven by `run_start_sequence`; the smoke script only
observes it (no `_drive_protection`, no hand-stepped coordinator).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_rehearsal as dr

from tests.support.live_rig import forbid_real_sleep
from tests.support.live_smoke_env import build_fake_smoke_env

FAKE_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
SENTINELS = {
    "BINANCE_DEMO_API_KEY": "FAKE-API-KEY-SENTINEL-0001",
    "BINANCE_DEMO_API_SECRET": "FAKE-API-SECRET-SENTINEL-0002",
    "TELEGRAM_LIVE_BOT_TOKEN": "999999:FAKE-BOT-TOKEN-SENTINEL-0003",
}


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


def _recorder(environ: Mapping[str, str] | None = None) -> dr.EvidenceRecorder:
    return dr.EvidenceRecorder(
        mode=dr.RunMode.DRY_RUN,
        scenario=dr.SCENARIO_SMOKE,
        symbol=dr.SYMBOL,
        base_url=dr.DEMO_BASE_URL,
        environ=environ or {},
        clock=lambda: FAKE_NOW,
    )


async def _run(tmp_path: Path, recorder: dr.EvidenceRecorder) -> tuple[str, dr.SmokeEnv]:
    env = build_fake_smoke_env(tmp_path)
    outcome = await dr.run_composed_smoke(env, recorder)
    return outcome, env


def _statuses(recorder: dr.EvidenceRecorder) -> dict[str, str]:
    return {step["name"]: step["status"] for step in recorder.steps}


async def test_the_whole_sequence_runs_on_the_composed_process_and_is_synthetic(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    outcome, _ = await _run(tmp_path, recorder)
    assert outcome == dr.OUTCOME_COMPLETE
    statuses = _statuses(recorder)
    for name in dr._SMOKE_STEPS:
        assert statuses.get(name) == dr.STEP_PASSED, (name, recorder.steps)
    assert all(step["detail"].startswith("SYNTHETIC") for step in recorder.steps)
    assert recorder.details["evidence_kind"] == "SYNTHETIC"
    attestation = dr.build_smoke_attestation(recorder)["composed_smoke"]
    assert set(attestation.values()) == {"SYNTHETIC_NOT_OBSERVED"}


async def test_one_entry_is_placed_gtd_limit_with_no_entry_time_stop_and_no_replay_places(
    tmp_path: Path,
) -> None:
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    await dr.run_composed_smoke(env, recorder)
    fake = env.fake
    entries = fake.calls_to("place_entry")
    assert len(entries) == 1, "a placement is never re-sent"
    kwargs = entries[0]["kwargs"]
    assert (kwargs["symbol"], kwargs["side"], kwargs["time_in_force"]) == ("BTCUSDT", "BUY", "GTD")
    assert recorder.details["entry_acked"]["open_algo_orders_at_ack"] == 0
    stops = [
        c
        for c in fake.calls_to("place_algo_protective")
        if c["kwargs"]["client_algo_id"].endswith("SL")
    ]
    assert len(stops) == 1 and stops[0]["kwargs"]["close_position"] is True


async def test_the_evidence_records_every_field_phase_24_needs_from_demo(tmp_path: Path) -> None:
    recorder = _recorder()
    await _run(tmp_path, recorder)
    details = recorder.details
    steps = {entry["step"]: entry for entry in details["order_ids"]}
    assert {"confirm_entry", "stop_confirmed", "tp_legs"} <= set(steps)
    assert steps["confirm_entry"]["demo_order_ids"], "the entry's exchange order id"
    assert len(steps["confirm_entry"]["client_order_ids"]) == 1
    assert len(steps["tp_legs"]["algo_client_ids"]) == 3
    form = details["user_data_url_form"]
    assert form["listen_key"] == dr.LISTEN_KEY_MARKER
    assert form["path_form"].endswith(dr.LISTEN_KEY_MARKER)
    assert details["commission_rates"]["BTCUSDT"].keys() == {"maker_rate", "taker_rate"}
    sample = details["fill_pnl_sample"]
    assert set(sample) >= {"realized_pnl", "commission"}
    assert "evidence only, D086" in sample["note"]
    assert details["entry_price_raw"]["type"] == "Decimal"
    lag = {row["role"] for row in details["cancel_query_lag_observations"]}
    assert lag == {"STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"}
    assert len(details["user_data_liveness"]) >= 3
    assert {"last_ping_at_utc", "last_pong_at_utc"} <= set(details["user_data_liveness"][0])


async def test_no_secret_reaches_the_evidence_file_or_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = _recorder(SENTINELS)
    await _run(tmp_path, recorder)
    for secret in SENTINELS.values():
        recorder.record_failure_name("probe", "ValueError", f"leaked {secret}")
    recorder.attestation_map = dr.build_smoke_attestation(recorder)
    recorder.outcome = dr.OUTCOME_COMPLETE
    path = recorder.write(tmp_path / "evidence")
    text = path.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    for secret in SENTINELS.values():
        assert secret not in text
        assert secret not in captured.out
        assert secret not in captured.err
    assert "listenKey=" not in text
    assert json.loads(text)["details"]["evidence_kind"] == "SYNTHETIC"


async def test_without_the_snapshot_gap_fill_the_restart_fails_closed_f3(tmp_path: Path) -> None:
    """Finding F3: nothing in `src` records the plan constraint snapshot, so a restart cannot
    rebuild a live plan; the recovery fails closed (SAFE_MODE DB_FAILURE) and the smoke says so.
    This pins the gap: it flips when a production writer for the snapshot is added.
    """
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path, persist_snapshots=False)
    with pytest.raises(dr.SmokeHalt, match="restart_rehydrate"):
        await dr.run_composed_smoke(env, recorder)
    restart = recorder.details["start_sequences"][-1]
    assert restart["label"] == "restart"
    assert restart["recovery_failed_steps"] == ["COORDINATOR_RESTORED"]
    assert restart["recovery_safe_mode_reasons"] == ["DB_FAILURE"]
    assert _statuses(recorder)["restart_rehydrate"] == dr.STEP_FAILED
    assert len(env.fake.calls_to("place_entry")) == 1


async def test_a_confirm_in_safe_mode_places_nothing(tmp_path: Path) -> None:
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    await dr.run_composed_smoke(env, recorder)
    drill = _statuses(recorder)
    assert drill["safe_mode_drill"] == dr.STEP_PASSED
    assert len(env.fake.calls_to("place_entry")) == 1, "the SAFE_MODE CONFIRM placed nothing"


def test_the_default_run_without_execute_is_synthetic_and_writes_a_dry_run_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = dr.main(
        ["--scenario", "smoke"],
        environ={},
        clock=lambda: FAKE_NOW,
        evidence_dir=tmp_path,
    )
    assert code == dr.EXIT_OK
    (path,) = tmp_path.glob("*.json")
    assert "DRYRUN-smoke" in path.name
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mode"] == "DRY_RUN"
    assert data["outcome"] == dr.OUTCOME_COMPLETE
    assert set(data["attestation_map"]["composed_smoke"].values()) == {"SYNTHETIC_NOT_OBSERVED"}
    assert data["exchange_orders"] == [], "a dry run holds no exchange order record"
    assert "evidence:" in capsys.readouterr().out


async def test_the_demo_start_enables_only_through_the_explicit_degraded_flag_f2(
    tmp_path: Path,
) -> None:
    """Finding F2: the live health is DEGRADED by design (no candle feed), so a DEMO producer
    without the D056 flag could never enable entries. The composition sets it in DEMO only."""
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    await dr.run_composed_smoke(env, recorder)
    health = env.rig.wiring.health
    assert health.demo_degraded_allowed is True
    assert _statuses(recorder)["demo_enable"] == dr.STEP_PASSED


async def test_a_fresh_start_enters_safe_mode_stale_feed_before_the_stream_starts_f1(
    tmp_path: Path,
) -> None:
    """Finding F1: step 8 (reconcile) runs before step 9 (stream), so every start enters SAFE_MODE
    STALE_FEED and skips HEALTH and ENABLE; the smoke performs the operator exit and the enable.
    This pins the observed order; it flips if the D-08 order is changed."""
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    await dr.run_composed_smoke(env, recorder)
    first = recorder.details["start_sequences"][0]
    assert first["label"] == "start"
    assert "RECONCILE=OK" in first["steps"] and "STREAM=OK" in first["steps"]
    assert "HEALTH=SKIPPED" in first["steps"] and "ENABLE=SKIPPED" in first["steps"]
    assert "startup_safe_mode_exit" in _statuses(recorder)


def test_the_executed_run_uses_the_admitted_environment_and_writes_an_evidence_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--execute` with the typed phrase and an admitted environment; the env itself is the fake."""
    from src.ops import redaction

    redaction.clear_runtime_secrets()

    async def factory(recorder: dr.EvidenceRecorder) -> dr.SmokeEnv:
        del recorder
        env = build_fake_smoke_env(tmp_path / "fake")
        assert isinstance(env, dr.SmokeEnv)
        return env

    code = dr.main(
        ["--scenario", "smoke", "--execute"],
        environ={
            "LIVE_RUNTIME_MODE": "DEMO",
            "BINANCE_DEMO_API_KEY": SENTINELS["BINANCE_DEMO_API_KEY"],
            "BINANCE_DEMO_API_SECRET": SENTINELS["BINANCE_DEMO_API_SECRET"],
            "TELEGRAM_LIVE_BOT_TOKEN": SENTINELS["TELEGRAM_LIVE_BOT_TOKEN"],
            "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID": "424242",
            "TELEGRAM_AUTHORIZED_USER_IDS": "424242",
        },
        clock=lambda: FAKE_NOW,
        is_tty=lambda: True,
        read_confirmation=lambda _p: "DEMO SMOKE BTCUSDT",
        evidence_dir=tmp_path / "evidence",
        smoke_env_factory=factory,
    )
    assert code == dr.EXIT_OK
    (path,) = (tmp_path / "evidence").glob("*.json")
    assert "EVIDENCE-smoke" in path.name
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["mode"] == "EXECUTE"
    for secret in SENTINELS.values():
        assert secret not in text
    out = capsys.readouterr()
    for secret in SENTINELS.values():
        assert secret not in out.out and secret not in out.err


def test_the_real_environment_assembles_the_process_with_the_demo_guarded_sdk_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No network: `default_assemble` is replaced; what the smoke hands it is what is asserted."""
    import asyncio
    from types import SimpleNamespace

    from src.live import runtime

    seen: list[dict[str, Any]] = []

    def fake_assemble(context: Any, **kwargs: Any) -> Any:
        seen.append({"context": context, **kwargs})
        return SimpleNamespace()

    monkeypatch.setattr(runtime, "default_assemble", fake_assemble)
    config = SimpleNamespace(authorized_chat_id=1)
    factory = dr._real_smoke_env_factory(
        config=config,
        environ={},
        clock=lambda: FAKE_NOW,
        initialize_gate_state=True,
        approval_timeout_seconds=300,
        sleep=dr._default_sleep,
    )
    recorder = _recorder()
    env = asyncio.run(factory(recorder))
    assert seen[0]["sdk_factory"] is dr.demo_guarded_sdk_factory
    assert seen[0]["context"].initialize_gate_state is True
    assert seen[0]["context"].operator_id == dr.OPERATOR_ID
    assert env.synthetic is False and env.label == "DEMO_OBSERVED"
    assert env.wait_ticks == 150
    restarted = asyncio.run(env.restart())  # type: ignore[misc]
    assert seen[1]["context"].initialize_gate_state is False, "a restart never re-initializes"
    assert restarted.synthetic is False


def test_the_console_owner_prints_one_instruction_per_action_and_records_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import asyncio

    recorder = _recorder()
    owner = dr.ConsoleOwner(recorder)
    for action in ("approve", "confirm", "safemode_exit", "replay_approve", "replay_confirm"):
        asyncio.run(owner.act(action, short_id="abc123", note=""))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("OPERATOR: ")]
    assert len(lines) == 5
    assert len(recorder.details["operator_instructions"]) == 5
    assert any("/safemode_exit" in line for line in lines)
