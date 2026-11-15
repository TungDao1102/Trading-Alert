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


async def test_the_placement_records_the_verified_snapshot_and_the_restart_rehydrates_f3(
    tmp_path: Path,
) -> None:
    """Finding F3 (fixed by plan 24-37, D095): the write-ahead path records the VERIFIED plan
    constraint snapshot, so the restart rebuilds the plan with no test-side gap fill."""
    from src.execution.constraint_snapshot import LiveInputsStatus

    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    await dr.run_composed_smoke(env, recorder)
    stored = list(env.rig.stores.snapshots._rows.values())
    assert len(stored) == 1, "one write-once snapshot, for the one plan that was placed"
    (snapshot,) = stored
    assert snapshot.live_inputs_status is LiveInputsStatus.COMPLETE
    assert snapshot.margin_type is not None and snapshot.leverage and snapshot.equity_used
    restart = recorder.details["start_sequences"][-1]
    assert restart["label"] == "restart"
    assert restart["recovery_failed_steps"] == [] and restart["plans_restored"] == 1
    assert _statuses(recorder)["restart_rehydrate"] == dr.STEP_PASSED


async def test_a_restart_that_finds_no_snapshot_row_fails_closed(tmp_path: Path) -> None:
    """The fail-closed side of F3: a database that lost the row cannot rebuild the plan; the
    recovery enters SAFE_MODE RESTORE_INCONSISTENT (the faulty entry is isolated, D110) and
    the smoke stops at the restart step."""
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path, drop_snapshots_before_restart=True)
    with pytest.raises(dr.SmokeHalt, match="restart_rehydrate"):
        await dr.run_composed_smoke(env, recorder)
    restart = recorder.details["start_sequences"][-1]
    assert restart["label"] == "restart"
    assert restart["recovery_failed_steps"] == ["COORDINATOR_RESTORED"]
    assert restart["recovery_safe_mode_reasons"] == ["RESTORE_INCONSISTENT"]
    assert _statuses(recorder)["restart_rehydrate"] == dr.STEP_FAILED
    assert len(env.fake.calls_to("place_entry")) == 1


async def test_the_snapshot_is_recorded_after_the_consume_and_before_the_entry_is_sent_f3(
    tmp_path: Path,
) -> None:
    """The one added write sits between the consume and `mark_sent`: nothing is sent for a plan
    whose snapshot is not durable, and the Phase 17 to 21 order around it is unchanged."""
    env = build_fake_smoke_env(tmp_path)
    rig = env.rig
    order: list[str] = []
    intents = rig.stores.execution_state
    for name in ("consume_and_record_entry_intent", "mark_sent"):
        original = getattr(intents, name)

        def wrap(*args: Any, _name: str = name, _orig: Any = original, **kwargs: Any) -> Any:
            order.append(_name)
            return _orig(*args, **kwargs)

        setattr(intents, name, wrap)
    original_place = env.fake.place_entry

    async def place(**kwargs: Any) -> Any:
        order.append("place_entry")
        return await original_place(**kwargs)

    env.fake.place_entry = place
    snapshots = rig.stores.snapshots
    record = snapshots.record

    def spy(snapshot: Any, **kwargs: Any) -> Any:
        order.append("snapshot.record")
        return record(snapshot, **kwargs)

    snapshots.record = spy  # type: ignore[method-assign]
    await dr.run_composed_smoke(env, _recorder())
    first = {name: order.index(name) for name in set(order)}
    assert first["consume_and_record_entry_intent"] < first["snapshot.record"]
    assert first["snapshot.record"] < first["mark_sent"] < first["place_entry"]


async def test_a_snapshot_that_cannot_be_recorded_sends_nothing_f3(tmp_path: Path) -> None:
    """A store failure of the new write ends the placement as RECONCILIATION_REQUIRED, with the
    INTENDED row unresolved and no order sent (like a failing `mark_sent`)."""
    from src.persistence.errors import StoreUnavailable

    class _Down(dict[str, Any]):
        def __setitem__(self, key: str, value: Any) -> None:
            raise StoreUnavailable("down")

    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    env.rig.stores.snapshots._rows = _Down()  # the wiring gate still sees the real recorder
    with pytest.raises(dr.SmokeHalt, match="confirm_entry"):
        await dr.run_composed_smoke(env, recorder)
    assert env.fake.calls_to("place_entry") == []
    outcomes = [
        json.loads(event.payload_json)["reason_code"]
        for event in env.rig.memory.journal.by_type("LIVE_PLACEMENT_OUTCOME")
    ]
    assert outcomes == ["RECONCILIATION_REQUIRED"]


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


async def test_a_clean_start_and_a_restart_enable_entries_without_an_operator_exit_f1(
    tmp_path: Path,
) -> None:
    """Finding F1 (fixed by plan 24-37, D094): the stream starts before the first reconcile tick,
    so a clean start is not parked in SAFE_MODE STALE_FEED. HEALTH and ENABLE run as the last
    steps of BOTH starts, and the only /safemode_exit of the whole run is the drill's."""
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    actions: list[str] = []
    original_act = env.owner.act

    async def spy(action: str, **context: Any) -> None:
        actions.append(action)
        await original_act(action, **context)

    env.owner.act = spy  # type: ignore[method-assign]
    await dr.run_composed_smoke(env, recorder)
    first, second = recorder.details["start_sequences"]
    for sequence in (first, second):
        steps = sequence["steps"]
        assert steps.index("STREAM=OK") < steps.index("RECONCILE=OK")
        assert "HEALTH=OK" in steps and "ENABLE=OK" in steps
        assert sequence["safe_mode_reasons"] == []
    statuses = _statuses(recorder)
    assert "startup_safe_mode_exit" not in statuses
    assert statuses["demo_enable"] == dr.STEP_PASSED
    assert statuses["restart_enable"] == dr.STEP_PASSED
    assert actions.count("safemode_exit") == 1, "only the drill needs the operator exit"


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


async def test_the_console_owner_also_sends_each_instruction_to_the_owner_and_survives_a_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nobody should have to watch the terminal: the instruction reaches the owner's phone, and a
    failed message changes nothing (first Demo rehearsals: the drill prompt was missed)."""
    sent: list[str] = []

    async def notify(text: str) -> None:
        sent.append(text)

    owner = dr.ConsoleOwner(_recorder(), notify=notify)
    await owner.act("safemode_exit", short_id="abc123", note="")
    assert len(sent) == 1 and "/safemode_exit" in sent[0] and sent[0].startswith("REHEARSAL: ")

    async def failing(text: str) -> None:
        raise RuntimeError("telegram is down")

    await dr.ConsoleOwner(_recorder(), notify=failing).act("approve", short_id="x", note="")
    assert "OPERATOR: " in capsys.readouterr().out


async def test_the_refused_drill_reservation_is_released_by_the_sweep_at_its_expiry_f4(
    tmp_path: Path,
) -> None:
    """Finding F4 (fixed by plan 24-37, D095): the SAFE_MODE refusal is not final, so the drill's
    reservation stays counted until its plan expires; the scheduler's sweep then releases it
    (PLAN_EXPIRED) and the smoke shows it. The executed plan's reservation is released when its
    position is closed (POSITION_CLOSED, finding F5): no reservation is left counted."""
    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    await dr.run_composed_smoke(env, recorder)
    statuses = _statuses(recorder)
    assert statuses["drill_reservation_released"] == dr.STEP_PASSED
    assert statuses["reservation_released_on_close"] == dr.STEP_PASSED
    rows = env.rig.memory.reservations._rows
    released = sorted(
        (row.status.value, row.release_reason.value) for row in rows.values() if row.release_reason
    )
    assert released == [("RELEASED", "PLAN_EXPIRED"), ("RELEASED", "POSITION_CLOSED")], released
    assert env.rig.memory.reservations.list_counted() == ()
    outcomes = [
        json.loads(event.payload_json)["reason_code"]
        for event in env.rig.memory.journal.by_type("LIVE_PLACEMENT_OUTCOME")
    ]
    assert outcomes[0] == "OK" and outcomes[-1] != "OK", outcomes


async def test_a_start_whose_clock_drift_guard_blocks_entries_stops_before_any_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First Demo run, 2026-11-06: the host clock was 540 ms ahead, the start sequence passed, and
    the run lost 5 minutes and left an approved plan blocking the symbol for 26 minutes."""
    from src.adapters.binance_clock import ClockDriftGuard, DriftBlockReason

    recorder = _recorder()
    env = build_fake_smoke_env(tmp_path)
    monkeypatch.setattr(env, "synthetic", False)  # the check is for the real (Demo) process only
    monkeypatch.setattr(
        ClockDriftGuard, "blocked_reason", lambda self, now_utc: DriftBlockReason.OUT_OF_LIMITS
    )

    with pytest.raises(dr.SmokeHalt):
        await dr.run_composed_smoke(env, recorder)

    statuses = _statuses(recorder)
    assert statuses["demo_enable"] == dr.STEP_FAILED
    assert "signal" not in statuses
    failed = next(s for s in recorder.steps if s["name"] == "demo_enable")
    assert "OUT_OF_LIMITS" in failed["detail"]
    assert env.fake.calls_to("place_entry") == []
