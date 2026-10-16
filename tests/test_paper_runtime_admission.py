"""Plan 16-22 Task 3: admission per the user's Q-A decision (runtime-exact-hash-all), one epoch
pin per trial, RUNTIME_START/STOP records and the required runtime configuration.

Q-A (decisions/16-DEC-Q-A.md): the runtime process gate requires an exact-hash allowlist entry
for EVERY parameter set, a fully rationalized one included. `pin_stream_epoch` and its Phase 15
tests are unchanged; a hash match only lets its full validation continue.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import src.domain.registry as domain_registry
import src.paper.freeze as freeze
from src.paper import runtime
from src.paper.runtime_config import ExitCode, load_runtime_config
from src.paper.runtime_state import InMemoryRuntimeState
from src.paper.vocabulary import RuntimeEventType

from tests.test_rationale import (
    BASE_SET,
    SET_ID,
    STRATEGY_ID,
    parsed_params,
    write_rationalized_set,
    write_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "config" / "paper" / "README.md"
DEC_Q_A = (
    REPO_ROOT / ".planning" / "phases" / "16-paper-runtime-composition" / "decisions"
) / "16-DEC-Q-A.md"
SKIPPED_TEXT = "SKIPPED (allowlist empty)"

CONFIG_TEXT = """\
[health]
max_ws_message_silence_seconds = 11
max_closed_bar_lateness_seconds = 12
continuous_uncovered_ceiling_seconds = 13
freeze_tick_grace_seconds = 14

[timing]
sibling_4h_wait_seconds = 15
constraint_snapshot_ttl_seconds = 16
exchange_info_refresh_seconds = 17
minute_poll_interval_seconds = 18
minute_close_lag_seconds = 19
healthcheck_max_bar_age_seconds = 20
rest_backfill_depth_bars = 21

[account]
initial_equity = "1000"
risk_rate = "0.01"

[scope]
symbols = ["BTCUSDT", "ETHUSDT"]
"""
REQUIRED_KEYS = {
    "health": (
        "max_ws_message_silence_seconds",
        "max_closed_bar_lateness_seconds",
        "continuous_uncovered_ceiling_seconds",
        "freeze_tick_grace_seconds",
    ),
    "timing": (
        "sibling_4h_wait_seconds",
        "constraint_snapshot_ttl_seconds",
        "exchange_info_refresh_seconds",
        "minute_poll_interval_seconds",
        "minute_close_lag_seconds",
        "healthcheck_max_bar_age_seconds",
        "rest_backfill_depth_bars",
    ),
    "account": ("initial_equity", "risk_rate"),
    "scope": ("symbols",),
}


class _Clock:
    """A strictly increasing injected clock (one second per call)."""

    def __init__(self) -> None:
        self._now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


class _Rig:
    """One tmp registry, one tmp config, one state port: everything a runtime start needs."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.root = tmp_path / "registry"
        self.config_path = tmp_path / "paper-runtime-test.toml"
        self.config_path.write_text(CONFIG_TEXT, encoding="utf-8")
        self.pinned_path = tmp_path / "logs" / "pinned_epoch.json"
        self.state = InMemoryRuntimeState()
        self.clock = _Clock()
        self.order: list[str] = []
        self.stops = 0

    def environ(self) -> dict[str, str]:
        return {
            "PAPER_STRATEGY_ID": STRATEGY_ID,
            "PAPER_PARAMETER_SET_ID": SET_ID,
            "PAPER_RUNTIME_CONFIG": str(self.config_path),
        }

    def set_hash(self) -> str:
        return freeze.load_parameter_set_at_root(STRATEGY_ID, SET_ID, self.root).parameter_set_hash

    def _allow(self, parameter_set_id: str, parameter_set_hash: str) -> None:
        entry = freeze.PaperAllowlistEntry(
            strategy_id=STRATEGY_ID,
            parameter_set_id=parameter_set_id,
            parameter_set_hash=parameter_set_hash,
            purpose="runtime test entry",
            approved_at="2026-10-10",
            basis="test only",
        )
        self.monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", (entry,))

    def authorize(self, parameter_set_hash: str | None = None) -> None:
        self._allow(SET_ID, parameter_set_hash or self.set_hash())

    def authorize_other_set(self) -> None:
        self._allow("some-other-set", "a" * 64)

    def spy(self) -> None:
        """Record the order of the gate lookup and the per-call pin."""
        find = runtime.find_allowlist_entry
        pin = runtime.pin_stream_epoch

        def spy_find(*args: Any, **kwargs: Any) -> Any:
            self.order.append("gate")
            return find(*args, **kwargs)

        def spy_pin(*args: Any, **kwargs: Any) -> Any:
            self.order.append("pin")
            return pin(*args, **kwargs)

        self.monkeypatch.setattr(runtime, "find_allowlist_entry", spy_find)
        self.monkeypatch.setattr(runtime, "pin_stream_epoch", spy_pin)

    def run(
        self,
        *flags: str,
        environ: dict[str, str] | None = None,
        run_loop: Callable[[Any], None] | None = None,
    ) -> int:
        def wait_for_stop() -> None:
            self.stops += 1

        return runtime.main(
            [*flags, "--pinned-state", str(self.pinned_path)],
            environ=self.environ() if environ is None else environ,
            wait_for_stop=wait_for_stop,
            state=self.state,
            registry_root=self.root,
            clock=self.clock,
            run_loop=run_loop if run_loop is not None else (lambda _context: None),
        )

    def pinned(self) -> freeze.StreamEpoch:
        return freeze.load_pinned_state(self.pinned_path)

    def types(self) -> list[RuntimeEventType]:
        if not self.pinned_path.is_file():
            return []
        return [r.event_type for r in self.state.records(self.pinned().epoch_id)]


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Rig]:
    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    yield rig


@pytest.fixture
def admitted(rig: _Rig) -> _Rig:
    """A rationalized set with an exact-hash entry: everything but the config can go wrong."""
    write_rationalized_set(rig.root)
    rig.authorize()
    return rig


# ---- admission: the user's Q-A decision, exactly -------------------------------------------- #


def test_decision_record_is_runtime_exact_hash_all() -> None:
    text = DEC_Q_A.read_text(encoding="utf-8")
    assert re.search(r"^option: runtime-exact-hash-all$", text, re.MULTILINE)
    assert re.search(r"^decided by: user$", text, re.MULTILINE)


@pytest.fixture(autouse=True)
def _start_from_an_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the runtime on an empty allowlist unless a test injects entries.

    The production allowlist holds the user's single entry since checkpoint G4-021 (pinned in
    tests/test_paper_start_gate.py), so each test here starts from an injected empty one.
    """
    import src.paper.freeze as freeze

    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", ())


def test_empty_allowlist_skips_without_a_fallback_set(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    write_rationalized_set(rig.root)
    rig.spy()

    code = rig.run("--pin-epoch")

    assert code == 0
    assert SKIPPED_TEXT in capsys.readouterr().out
    assert rig.order == [], "an empty allowlist must not reach the gate lookup or the pin"
    assert not rig.pinned_path.exists()


def test_rationalized_but_unauthorized_set_is_refused_before_the_pin(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    write_rationalized_set(rig.root)
    rig.authorize_other_set()
    rig.spy()

    code = rig.run("--pin-epoch")

    assert code == ExitCode.ADMISSION_OR_EPOCH_MISMATCH == 6
    assert "no allowlist entry" in capsys.readouterr().err
    assert rig.order == ["gate"], "the strict gate refuses before pin_stream_epoch is called"
    assert not rig.pinned_path.exists()


def test_exact_hash_match_proceeds_to_the_pin(admitted: _Rig) -> None:
    admitted.spy()

    code = admitted.run("--pin-epoch")

    assert code == 0
    assert admitted.order == ["gate", "pin"]
    assert admitted.pinned_path.is_file()


def test_hash_mismatch_is_refused_before_the_pin(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    write_rationalized_set(rig.root)
    rig.authorize("b" * 64)
    rig.spy()

    code = rig.run("--pin-epoch")

    assert code == 6
    assert "hash" in capsys.readouterr().err
    assert rig.order == ["gate"]
    assert not rig.pinned_path.exists()


def test_authorization_does_not_replace_the_full_validation(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hash match only lets the existing validation continue (PLACEHOLDER keys still refuse)."""
    write_rationalized_set(rig.root, placeholder_key=next(iter(parsed_params(BASE_SET))))
    rig.authorize()
    rig.spy()

    code = rig.run("--pin-epoch")

    assert code == 6
    assert rig.order == ["gate", "pin"], "the gate passed and pin_stream_epoch still judged"
    assert "PLACEHOLDER" in capsys.readouterr().err
    assert not rig.pinned_path.exists()


def test_unrationalized_set_with_an_exact_entry_is_admitted_by_both_layers(rig: _Rig) -> None:
    write_set(rig.root, spec=None)
    rig.authorize()
    rig.spy()

    assert rig.run("--pin-epoch") == 0
    assert rig.order == ["gate", "pin"]


def test_gate_runs_first_on_every_entry_path(admitted: _Rig) -> None:
    admitted.spy()

    assert admitted.run() == 5, "no state and no flag"
    assert admitted.run("--pin-epoch") == 0, "the pin command"
    assert admitted.run() == 0, "a restart"
    assert admitted.order == ["gate", "gate", "pin", "gate"]


def test_ambiguous_allowlist_is_refused(rig: _Rig) -> None:
    write_rationalized_set(rig.root)
    entry = freeze.PaperAllowlistEntry(
        strategy_id=STRATEGY_ID,
        parameter_set_id=SET_ID,
        parameter_set_hash=rig.set_hash(),
        purpose="p",
        approved_at="2026-10-10",
        basis="b",
    )
    rig.monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", (entry, entry))

    assert rig.run("--pin-epoch") == 6


def test_unregistered_set_is_refused(rig: _Rig) -> None:
    rig.root.mkdir(parents=True)
    rig._allow(SET_ID, "d" * 64)

    assert rig.run("--pin-epoch") == 6


def test_missing_ids_in_the_environment_are_a_configuration_refusal(admitted: _Rig) -> None:
    env = admitted.environ()
    del env["PAPER_STRATEGY_ID"]

    assert admitted.run("--pin-epoch", environ=env) == ExitCode.CONFIG_NOT_RATIFIED


def test_admission_refusal_holds_when_asked(rig: _Rig) -> None:
    write_rationalized_set(rig.root)
    rig.authorize_other_set()

    assert rig.run("--hold-on-refusal") == 6
    assert rig.stops == 1


# ---- epoch pin: operator command only, reused by every restart ------------------------------- #


def test_no_pinned_state_and_no_flag_exits_5(
    admitted: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    assert admitted.run() == ExitCode.NO_PINNED_EPOCH == 5
    err = capsys.readouterr().err
    assert "no pinned epoch: pinning is an operator command (O-11 iii)" in err
    assert not admitted.pinned_path.exists()


def test_pin_epoch_pins_once_writes_the_file_and_records_only_the_pin(admitted: _Rig) -> None:
    """Pin-and-exit (16-55 Q3 = A, decisions/16-DEC-PIN-COMMAND.md): no RUNTIME_START."""
    pins: list[int] = []
    writes: list[int] = []
    real_pin, real_write = runtime.pin_stream_epoch, runtime.write_pinned_state

    def counting_pin(**kwargs: Any) -> freeze.StreamEpoch:
        pins.append(1)
        return real_pin(**kwargs)

    def counting_write(epoch: freeze.StreamEpoch, path: Path) -> None:
        writes.append(1)
        real_write(epoch, path)

    admitted.monkeypatch.setattr(runtime, "pin_stream_epoch", counting_pin)
    admitted.monkeypatch.setattr(runtime, "write_pinned_state", counting_write)

    assert admitted.run("--pin-epoch") == 0

    assert pins == [1]
    assert writes == [1]
    epoch = admitted.pinned()
    types = admitted.types()
    assert types == [RuntimeEventType.EPOCH_PINNED]
    assert (epoch.strategy_id, epoch.parameter_set_id) == (STRATEGY_ID, SET_ID)
    assert epoch.parameter_set_hash == admitted.set_hash()


def test_restart_reuses_the_pinned_epoch_and_never_pins_again(admitted: _Rig) -> None:
    seen_epochs: list[str] = []

    def remember(context: Any) -> None:
        seen_epochs.append(context.epoch.epoch_id)

    assert admitted.run("--pin-epoch", run_loop=remember) == 0
    first = admitted.pinned()
    pinned_bytes = admitted.pinned_path.read_bytes()
    pins: list[int] = []

    def must_not_pin(**_kwargs: Any) -> None:
        pins.append(1)

    admitted.monkeypatch.setattr(runtime, "pin_stream_epoch", must_not_pin)

    assert admitted.run(run_loop=remember) == 0

    assert pins == []
    assert seen_epochs == [first.epoch_id], "the pin exits; only the restart runs the loop"
    assert admitted.pinned_path.read_bytes() == pinned_bytes
    types = admitted.types()
    assert types.count(RuntimeEventType.RUNTIME_START) == 1
    assert types.count(RuntimeEventType.EPOCH_PINNED) == 1, "a restart never re-records the pin"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strategy_id", "other-strategy"),
        ("parameter_set_id", "other-set"),
        ("parameter_set_hash", "c" * 64),
    ],
)
def test_pinned_state_that_differs_from_the_admitted_entry_exits_6(
    admitted: _Rig, field: str, value: str
) -> None:
    assert admitted.run("--pin-epoch") == 0
    pinned = admitted.pinned()
    freeze.write_pinned_state(
        freeze.StreamEpoch(**{**pinned.__dict__, field: value}), admitted.pinned_path
    )

    assert admitted.run() == ExitCode.ADMISSION_OR_EPOCH_MISMATCH


def test_pin_epoch_with_an_existing_pinned_state_exits_6(admitted: _Rig) -> None:
    assert admitted.run("--pin-epoch") == 0
    before = admitted.pinned_path.read_bytes()

    assert admitted.run("--pin-epoch") == 6
    assert admitted.pinned_path.read_bytes() == before


# ---- RUNTIME_STOP ---------------------------------------------------------------------------- #


def test_clean_shutdown_records_runtime_stop_and_leaves_the_pinned_state_alone(
    admitted: _Rig,
) -> None:
    assert admitted.run("--pin-epoch") == 0
    before = admitted.pinned_path.read_bytes()

    assert admitted.run() == 0

    assert admitted.pinned_path.read_bytes() == before
    assert admitted.types().count(RuntimeEventType.RUNTIME_STOP) == 1


def test_a_crashing_loop_leaves_a_start_without_a_stop(admitted: _Rig) -> None:
    assert admitted.run("--pin-epoch") == 0

    def boom(_context: object) -> None:
        raise RuntimeError("loop crashed")

    with pytest.raises(RuntimeError):
        admitted.run(run_loop=boom)

    types = admitted.types()
    assert types.count(RuntimeEventType.RUNTIME_START) == 1
    assert types.count(RuntimeEventType.RUNTIME_STOP) == 0


# ---- runtime configuration: every value required -------------------------------------------- #


def test_unset_config_variable_exits_4(admitted: _Rig, capsys: pytest.CaptureFixture[str]) -> None:
    env = admitted.environ()
    del env["PAPER_RUNTIME_CONFIG"]

    assert admitted.run("--pin-epoch", environ=env) == ExitCode.CONFIG_NOT_RATIFIED == 4
    err = capsys.readouterr().err
    assert "runtime configuration not ratified:" in err
    assert "PAPER_RUNTIME_CONFIG" in err


def test_missing_config_file_exits_4(admitted: _Rig) -> None:
    admitted.config_path.unlink()

    assert admitted.run("--pin-epoch") == 4


@pytest.mark.parametrize(
    ("section", "key"),
    [(section, key) for section, keys in REQUIRED_KEYS.items() for key in keys],
)
def test_every_missing_key_exits_4_and_names_the_key(
    admitted: _Rig, capsys: pytest.CaptureFixture[str], section: str, key: str
) -> None:
    lines = [ln for ln in CONFIG_TEXT.splitlines() if not ln.startswith(f"{key} ")]
    assert len(lines) == len(CONFIG_TEXT.splitlines()) - 1
    admitted.config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert admitted.run("--pin-epoch") == 4
    assert f"{section}.{key}" in capsys.readouterr().err


def test_missing_section_exits_4(admitted: _Rig, capsys: pytest.CaptureFixture[str]) -> None:
    admitted.config_path.write_text(CONFIG_TEXT.split("[scope]")[0], encoding="utf-8")

    assert admitted.run("--pin-epoch") == 4
    assert "scope.symbols" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("initial_equity", "initial_equity = 1000.5"),
        ("rest_backfill_depth_bars", 'rest_backfill_depth_bars = "21"'),
        ("rest_backfill_depth_bars", "rest_backfill_depth_bars = true"),
        ("symbols", "symbols = []"),
        ("risk_rate", 'risk_rate = "not-a-number"'),
        ("freeze_tick_grace_seconds", "freeze_tick_grace_seconds = 0"),
    ],
)
def test_a_value_of_the_wrong_kind_exits_4(admitted: _Rig, key: str, replacement: str) -> None:
    lines = [replacement if ln.startswith(f"{key} ") else ln for ln in CONFIG_TEXT.splitlines()]
    admitted.config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert admitted.run("--pin-epoch") == 4


def test_unparseable_config_exits_4(admitted: _Rig) -> None:
    admitted.config_path.write_text("this is = = not toml [", encoding="utf-8")

    assert admitted.run("--pin-epoch") == 4


def test_unratified_configuration_never_pins(admitted: _Rig) -> None:
    admitted.config_path.write_text("[health]\n", encoding="utf-8")
    admitted.spy()

    assert admitted.run("--pin-epoch") == 4
    assert "pin" not in admitted.order
    assert not admitted.pinned_path.exists()


def test_load_runtime_config_returns_typed_values(rig: _Rig) -> None:
    config = load_runtime_config(str(rig.config_path))

    assert config.health.freeze_tick_grace_seconds == 14
    assert config.timing.rest_backfill_depth_bars == 21
    assert config.account.initial_equity == Decimal("1000")
    assert config.account.risk_rate == Decimal("0.01")
    assert config.symbols == ("BTCUSDT", "ETHUSDT")


def _numeric(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    )


def test_no_numeric_default_for_any_configuration_key() -> None:
    """AST check: no literal number is bound to a configuration key name in the runtime modules."""
    keys = {key for names in REQUIRED_KEYS.values() for key in names}
    offenders: list[str] = []
    for module in ("runtime_config.py", "runtime.py"):
        tree = ast.parse((REPO_ROOT / "src" / "paper" / module).read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _numeric(node.value):
                offenders += [
                    t.id for t in node.targets if isinstance(t, ast.Name) and t.id in keys
                ]
            if isinstance(node, ast.AnnAssign) and _numeric(node.value):
                if isinstance(node.target, ast.Name) and node.target.id in keys:
                    offenders.append(node.target.id)
            if isinstance(node, ast.arguments):
                positional = [*node.posonlyargs, *node.args]
                defaults = [None] * (len(positional) - len(node.defaults)) + list(node.defaults)
                for arg, default in zip(positional, defaults, strict=True):
                    if arg.arg in keys and _numeric(default):
                        offenders.append(arg.arg)
                for arg, kw_default in zip(node.kwonlyargs, node.kw_defaults, strict=True):
                    if arg.arg in keys and _numeric(kw_default):
                        offenders.append(arg.arg)
            if isinstance(node, ast.keyword) and node.arg in keys and _numeric(node.value):
                offenders.append(node.arg)
    assert offenders == []


# ---- README: key list, grace wording, the two layers ----------------------------------------- #


def test_readme_lists_every_key_one_per_line_without_values() -> None:
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    for names in REQUIRED_KEYS.values():
        for key in names:
            assert any(ln.lstrip("-* ").startswith(f"`{key}`") for ln in lines), key
    standalone_number = re.compile(r"(?<![\w.\-])\d+(?:\.\d+)?(?![\w\-])")
    assert standalone_number.findall(text) == []


def test_readme_grace_documentation() -> None:
    text = README.read_text(encoding="utf-8")
    assert "bounds only how late a valid scheduled run may start" in text
    assert "never turns a missing tick into CLEAN" in text
    assert "must be strictly smaller than the slot interval of the workflow cron" in text


def test_readme_distinguishes_the_two_gate_layers_and_the_restartable_codes() -> None:
    text = README.read_text(encoding="utf-8")
    assert "runtime process gate" in text
    assert "exact-hash" in text
    assert "pin_stream_epoch" in text
    assert "per-call" in text
    assert "rationale tables never replace runtime authorization" in text
    assert "restartable" in text
    assert "--hold-on-refusal" in text
