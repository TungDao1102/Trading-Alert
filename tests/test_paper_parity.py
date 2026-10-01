"""Backtest-to-paper parity gate (Phase 7, plan 07-02 task 3).

Per D-02: paper evaluation on an overlapping history window must
produce byte-identical trade outcomes to backtest simulator.run on
the same inputs, verified by sha256_hex equality. Any divergence
is an engine incident — the fix lives in the shared engine
(evaluate / plan / evaluate_risk), never at the paper call site.

The replay helper builds the paper loop's warmed_up_1h /
warmed_up_4h / feed_events from the fixture's strategy_bars bar
by bar, so the paper loop and simulator see the same snapshots.
The projection reduces both outputs to a list of
(signal_id, reason_code) tuples — the verdict chain is the
common surface (the paper loop does not simulate fills yet).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.simulator import run as simulator_run
from src.domain.canonical import sha256_hex
from src.paper.loop import run_paper_tick

PHASE7_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "phase7"
PARITY_FIXTURE_DIR = PHASE7_FIXTURES_DIR / "parity_overlapping_history"


# --------------------------------------------------------------------------- #
# Replay helper — builds paper loop inputs from strategy_bars.
# --------------------------------------------------------------------------- #


def _bar_to_ws_event(bar: dict[str, Any]) -> dict[str, Any]:
    """Project a 1H strategy bar to a Binance WS kline event payload.

    The paper loop consumes Binance wire-format fields (t/T/o/h/l/c/v/n/x/q).
    The bar's close_time_utc is the event's T (close ms); open_time_utc is t.
    x=True marks the event as closed (the double closed-candle gate).
    """
    open_ms = int(datetime.fromisoformat(bar["open_time_utc"]).timestamp() * 1000)
    close_ms = int(datetime.fromisoformat(bar["close_time_utc"]).timestamp() * 1000)
    return {
        "t": open_ms,
        "T": close_ms,
        "o": str(bar["open"]),
        "h": str(bar["high"]),
        "l": str(bar["low"]),
        "c": str(bar["close"]),
        "v": str(bar["volume"]),
        "n": 100,
        "x": True,
        "q": str(bar["volume"]),
    }


def _replay_paper_through_bars(
    fixture_input: dict[str, Any],
) -> list[dict[str, Any]]:
    """Replay strategy_bars through the paper loop, one bar at a time.

    For each strategy_bar at index i:
      - warmed_up_1h = strategy_bars[:i]
      - warmed_up_4h = context_bars filtered to <= bar close
      - feed_events = [WS event from current bar]
      - now_utc = bar close_time_utc

    Returns the list of run_paper_tick outcomes (one per bar).
    """
    strategy_bars = fixture_input["strategy_bars"]
    context_bars = fixture_input["context_bars"]
    symbol = fixture_input["constraint_snapshot"]["symbol"]

    outcomes: list[dict[str, Any]] = []
    for i, bar in enumerate(strategy_bars):
        warmed_up_1h = strategy_bars[:i]
        bar_close = bar["close_time_utc"]
        warmed_up_4h = [c for c in context_bars if c["close_time_utc"] <= bar_close]
        feed_event = _bar_to_ws_event(bar)

        paper_input = {
            **fixture_input,
            "symbol": symbol,
            "warmed_up_1h": warmed_up_1h,
            "warmed_up_4h": warmed_up_4h,
            "feed_events": [feed_event],
            "now_utc": bar_close,
        }
        outcome = run_paper_tick(paper_input)
        outcomes.append(outcome)
    return outcomes


# --------------------------------------------------------------------------- #
# Projection — reduce both outputs to canonical verdict tuples.
# --------------------------------------------------------------------------- #


def _project_paper_verdicts(
    paper_outcomes: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Project paper loop outcomes to (signal_id, reason_code) tuples.

    Only includes records where a signal was produced (signal_id is
    not None). This matches the simulator's behavior of skipping
    strategy NO_TRADE bars (no trade record emitted).

    Known limitation (WR-10): strategy-stage NO_TRADEs (no signal
    emitted — the common case) are excluded here, so this projection
    alone is vacuous for the strategy decision itself. Use
    `_project_paper_verdicts_full` for the per-bar audit trail; full
    cross-side strategy parity needs per-bar simulator outcomes (the
    simulator emits trades only — engine work, not a paper-call-site
    fix).
    """
    verdicts: list[tuple[str, str]] = []
    for outcome in paper_outcomes:
        for record in outcome["no_trade_records"]:
            signal_id = record.get("signal_id")
            if signal_id is not None:
                verdicts.append((signal_id, record["reason_code"]))
    return sorted(verdicts)


def _project_paper_verdicts_full(
    paper_outcomes: list[dict[str, Any]],
) -> list[tuple[str, str | None, str, str]]:
    """Project ALL paper records to per-bar verdict tuples (WR-10).

    Returns one `(bar_close_utc, signal_id_or_None, reason_code,
    stage)` tuple per record, in replay order (sequence matters — no
    sorting). Strategy-stage NO_TRADEs and feed-gate rejections
    (WARMUP_INSUFFICIENT/DATA_STALE, which carry no signal_id) are
    included: paper and backtest can no longer "agree" by both
    emitting nothing-projected while disagreeing on every setup
    signal.
    """
    verdicts: list[tuple[str, str | None, str, str]] = []
    for outcome in paper_outcomes:
        for record in outcome["no_trade_records"]:
            verdicts.append(
                (
                    record["bar_close_utc"],
                    record.get("signal_id"),
                    record["reason_code"],
                    record["stage"],
                )
            )
    return verdicts


def _project_simulator_verdicts(
    trades: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Project simulator trades to (signal_id, reason_code) tuples."""
    verdicts: list[tuple[str, str]] = [(t["signal_id"], t["reason_code"]) for t in trades]
    return sorted(verdicts)


def _verdict_digest(verdicts: list[tuple[str, str]]) -> str:
    """Compute sha256_hex digest over canonical verdict tuples."""
    return sha256_hex({"verdicts": verdicts})


# --------------------------------------------------------------------------- #
# Test 1 — paper replay digest equals simulator digest (D-02).
# --------------------------------------------------------------------------- #


def test_paper_replay_digest_equals_simulator_digest() -> None:
    """Beh. 1: paper evaluation on overlapping history produces
    byte-identical trade outcomes to backtest simulator.run.

    Per D-02: same snapshot + same spec + same config = same decision.
    The paper loop and simulator must agree on every verdict
    (signal_id, reason_code) for every bar in the overlapping window.
    Any divergence is an engine incident — the fix lives in the
    shared engine, never at the paper call site.
    """
    case_input = json.loads((PARITY_FIXTURE_DIR / "input.json").read_text())
    expected = json.loads((PARITY_FIXTURE_DIR / "expected.json").read_text())

    # Simulator run.
    sim_result = simulator_run(case_input)
    sim_verdicts = _project_simulator_verdicts(sim_result["trades"])
    sim_digest = _verdict_digest(sim_verdicts)

    # Paper replay.
    paper_outcomes = _replay_paper_through_bars(case_input)
    paper_verdicts = _project_paper_verdicts(paper_outcomes)
    paper_digest = _verdict_digest(paper_verdicts)

    # Both must match the pinned expected digest.
    assert sim_digest == expected["digest"], (
        f"simulator digest {sim_digest} != expected {expected['digest']}"
    )
    assert paper_digest == expected["digest"], (
        f"paper digest {paper_digest} != expected {expected['digest']}"
    )
    # And they must match each other (the parity contract).
    assert paper_digest == sim_digest, (
        f"paper digest {paper_digest} != simulator digest {sim_digest} — "
        f"engine incident: paper and simulator diverged on the same inputs"
    )


# --------------------------------------------------------------------------- #
# Test 2 — prefix invariance: appending a post-horizon bar does not
# change earlier outcome digests (D-02 determinism).
# --------------------------------------------------------------------------- #


def test_paper_replay_is_prefix_invariant() -> None:
    """Beh. 2: appending one post-horizon bar does not change the
    earlier outcome digest.

    Per D-02 determinism: the verdict for bar N must depend only on
    bars [0..N], not on bars [N+1..]. The paper replay must produce
    the same digest for the first N bars regardless of whether
    bar N+1 is appended.
    """
    case_input = json.loads((PARITY_FIXTURE_DIR / "input.json").read_text())
    expected = json.loads((PARITY_FIXTURE_DIR / "expected.json").read_text())

    # Baseline replay: all N bars, digest of verdicts from bars [0..N-1].
    full_outcomes = _replay_paper_through_bars(case_input)
    full_verdicts = _project_paper_verdicts(full_outcomes)
    full_digest = _verdict_digest(full_verdicts)

    # Extended replay: append one post-horizon bar (advance timestamps
    # by 1H to avoid the duplicate-bar guard in compute_features).
    # The new bar's verdict is excluded — we compare the earlier
    # bars' digests only.
    last_bar = case_input["strategy_bars"][-1]
    from datetime import timedelta as _td

    last_open = datetime.fromisoformat(last_bar["open_time_utc"])
    last_close = datetime.fromisoformat(last_bar["close_time_utc"])
    extra_bar = {
        **last_bar,
        "open_time_utc": (last_open + _td(hours=1)).isoformat(),
        "close_time_utc": (last_close + _td(hours=1)).isoformat(),
    }
    extended_bars = [*case_input["strategy_bars"], extra_bar]
    extended_input = {**case_input, "strategy_bars": extended_bars}
    extended_outcomes = _replay_paper_through_bars(extended_input)
    # Drop the last outcome (the appended bar's verdict) — we only
    # care about the first N bars' verdicts.
    extended_verdicts = _project_paper_verdicts(extended_outcomes[:-1])
    extended_digest = _verdict_digest(extended_verdicts)

    # The extended digest (first N bars) must equal the full digest
    # (also first N bars). Appending a bar must not change earlier
    # verdicts (prefix invariance).
    assert extended_digest == full_digest, (
        f"extended digest {extended_digest} != full digest {full_digest} — "
        f"engine incident: paper replay is not prefix-invariant"
    )
    # And the full digest must match the pinned expected digest.
    assert full_digest == expected["digest"], (
        f"full digest {full_digest} != expected {expected['digest']}"
    )


# --------------------------------------------------------------------------- #
# Test 3 — full per-bar projection covers every replayed bar (WR-10).
# --------------------------------------------------------------------------- #


def test_paper_full_projection_covers_every_bar() -> None:
    """Beh. 3: the full projection includes signal-less records.

    Per WR-10: the signal-only projection is vacuous for the strategy
    decision (both sides can "match" by projecting nothing). The full
    per-bar projection must carry exactly one entry per replayed bar —
    including feed-gate rejections and strategy-stage NO_TRADEs that
    carry no signal_id — so a strategy-stage divergence can never
    again hide behind an empty projection.
    """
    case_input = json.loads((PARITY_FIXTURE_DIR / "input.json").read_text())

    paper_outcomes = _replay_paper_through_bars(case_input)
    full = _project_paper_verdicts_full(paper_outcomes)

    strategy_bars = case_input["strategy_bars"]
    assert len(full) == len(strategy_bars), (
        f"full projection must cover every bar: {len(full)} != {len(strategy_bars)}"
    )
    for (bar_close_utc, _signal_id, _reason_code, stage), bar in zip(
        full, strategy_bars, strict=True
    ):
        assert bar_close_utc == bar["close_time_utc"], (
            f"projection order must follow replay order: {bar_close_utc} != {bar['close_time_utc']}"
        )
        assert stage in ("feed_gate", "strategy", "planner", "risk", "risk_passed"), (
            f"unknown stage {stage!r}"
        )
    # The signal-less records must actually be present (the property
    # the old projection dropped): at least one entry without a
    # signal_id, otherwise this test is vacuous too.
    assert any(signal_id is None for (_, signal_id, _, _) in full), (
        "full projection must include signal-less records"
    )


# --------------------------------------------------------------------------- #
# Test 4 - documentary fields of expected.json cannot drift (12-09).
# --------------------------------------------------------------------------- #


def test_parity_expected_documentary_fields_match_registry_and_simulator() -> None:
    """expected.json's identity fields equal the registry-derived values.

    strategy_version and parameter_set_hash come from the pinned
    tests/fixtures/phase4/parameters.json entry for the fixture's set;
    cost_model_hash is the hash of the cost slice of that registry set. All
    three must also equal what the simulator reports on the fixture, and the
    fixture must sit on the v5 identity (8-key cost dict).
    """
    from src.backtest.costs import build_cost_model, cost_slice
    from src.domain.registry import load_parameter_set

    case_input = json.loads((PARITY_FIXTURE_DIR / "input.json").read_text())
    expected = json.loads((PARITY_FIXTURE_DIR / "expected.json").read_text())

    assert case_input["parameter_set_id"] == "baseline-v5"
    assert "exit_slippage_rate" in case_input["cost_model"]

    pins = json.loads((PHASE7_FIXTURES_DIR.parent / "phase4" / "parameters.json").read_text())[
        "parameter_sets"
    ]
    pin = next(
        e
        for e in pins
        if e["strategy_id"] == case_input["strategy_id"]
        and e["parameter_set_id"] == case_input["parameter_set_id"]
    )
    registry_set = load_parameter_set(case_input["strategy_id"], case_input["parameter_set_id"])
    registry_cost_hash = build_cost_model(cost_slice(registry_set.params)).cost_model_hash
    sim_result = simulator_run(case_input)

    assert expected["strategy_version"] == pin["strategy_version"] == "v4.0.0"
    assert expected["parameter_set_hash"] == pin["parameter_set_hash"]
    assert expected["parameter_set_hash"] == sim_result["parameter_set_hash"]
    assert expected["cost_model_hash"] == registry_cost_hash
    assert expected["cost_model_hash"] == sim_result["cost_model_hash"]
    assert expected["trade_count"] == len(sim_result["trades"]) == 1


# --------------------------------------------------------------------------- #
# Test 5 - both modes pass identical cost inputs to evaluate_risk (D-19).
# --------------------------------------------------------------------------- #


def test_simulator_and_paper_pass_identical_cost_inputs_to_evaluate_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cost_rates and both guard rates the simulator and the paper loop
    hand to evaluate_risk are equal, for every risk call either makes."""
    import src.backtest.simulator as simulator_module
    import src.paper.loop as paper_module

    def _spy(module: Any, sink: list[tuple[Any, Any, Any]]) -> None:
        real = module.evaluate_risk

        def wrapper(**kwargs: Any) -> Any:
            sink.append(
                (
                    kwargs["cost_rates"],
                    kwargs["min_stop_distance_rate"],
                    kwargs["max_cost_to_risk"],
                )
            )
            return real(**kwargs)

        monkeypatch.setattr(module, "evaluate_risk", wrapper)

    sim_calls: list[tuple[Any, Any, Any]] = []
    paper_calls: list[tuple[Any, Any, Any]] = []
    _spy(simulator_module, sim_calls)
    _spy(paper_module, paper_calls)

    case_input = json.loads((PARITY_FIXTURE_DIR / "input.json").read_text())
    simulator_run(case_input)
    _replay_paper_through_bars(case_input)

    assert sim_calls, "the simulator never reached the risk stage"
    assert paper_calls, "the paper loop never reached the risk stage"
    assert set(sim_calls) == set(paper_calls)
    (cost_rates, min_stop, max_cost), *_ = sim_calls
    assert cost_rates.fee_rate_entry == Decimal("0.0005")
    assert cost_rates.entry_slippage_rate == Decimal("0.0001")
    assert cost_rates.fee_rate_exit == Decimal("0.0005")
    assert cost_rates.exit_slippage_rate == Decimal("0.0003")
    assert (min_stop, max_cost) == (Decimal("0.003"), Decimal("0.15"))
