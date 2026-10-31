"""Admission of the live process (plan 24-11, D-02, D-03, D-12, OPS-02, T-24-27 to T-24-30).

Every refusal is driven through `main` with injected environment, repo root, limits file, stop
waiter and clock; nothing reads `.env`, the network or a database. Seeded secret values prove that
a refusal names variables and never prints a value.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from src.adapters.binance_client import Environment
from src.live import config as live_config
from src.live import runtime
from src.live.config import LiveConfig, LiveExitCode, LiveRefusal, parse_live_environment
from src.ops import redaction
from src.paper import held_marker

from tests.support.execution_limits import (
    TEST_ONLY_EXECUTION_LIMIT_VALUES,
    write_execution_limits_toml,
)

DEMO_KEY = "demo-key-SEEDED-0123456789"
DEMO_SECRET = "demo-secret-SEEDED-9876543210"
LIVE_KEY = "live-key-SEEDED-0123456789"
LIVE_SECRET = "live-secret-SEEDED-9876543210"
BOT_TOKEN = "123456:LIVE-BOT-TOKEN-SEEDED-abcdefgh"
SHADOW_TOKEN = "654321:SHADOW-BOT-TOKEN-SEEDED-zyxwvuts"
SEEDED = (DEMO_KEY, DEMO_SECRET, LIVE_KEY, LIVE_SECRET, BOT_TOKEN, SHADOW_TOKEN)
NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


def demo_env(**extra: str) -> dict[str, str]:
    env = {
        "LIVE_RUNTIME_MODE": "DEMO",
        "BINANCE_DEMO_API_KEY": DEMO_KEY,
        "BINANCE_DEMO_API_SECRET": DEMO_SECRET,
        "TELEGRAM_LIVE_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID": "424242",
        "TELEGRAM_AUTHORIZED_USER_IDS": "424242,515151",
    }
    env.update(extra)
    return env


@pytest.fixture(autouse=True)
def _clean_runtime_secrets() -> None:
    redaction.clear_runtime_secrets()


@pytest.fixture
def limits_file(tmp_path: Path) -> Path:
    return write_execution_limits_toml(
        tmp_path / "limits.toml", values=dict(TEST_ONLY_EXECUTION_LIMIT_VALUES)
    )


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


class Stopper:
    """A `wait_for_stop` that records what the world looked like while it was awaited."""

    def __init__(self, marker_dir: Path) -> None:
        self.marker_dir = marker_dir
        self.calls = 0
        self.marker_during: held_marker.HeldMarker | None = None

    def __call__(self) -> None:
        self.calls += 1
        self.marker_during = held_marker.read_own_marker(self.marker_dir)


def run_main(
    tmp_path: Path,
    repo_root: Path,
    limits_file: Path,
    environ: Mapping[str, str],
    *extra: str,
    run_live: runtime.LiveRunner | None = None,
    stopper: Stopper | None = None,
) -> tuple[int, Stopper]:
    state_dir = tmp_path / "state"
    waiter = stopper if stopper is not None else Stopper(state_dir)
    code = runtime.main(
        ["--state-dir", str(state_dir), *extra],
        environ=environ,
        wait_for_stop=waiter,
        clock=lambda: NOW,
        run_live=run_live,
        repo_root=repo_root,
        limits_path=limits_file,
    )
    return code, waiter


def assert_no_seeded_value(*texts: str) -> None:
    for text in texts:
        for value in SEEDED:
            assert value not in text


def test_demo_with_live_credentials_present_is_refused_by_name(
    tmp_path: Path,
    repo_root: Path,
    limits_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = demo_env(BINANCE_LIVE_API_KEY=LIVE_KEY)
    code, _ = run_main(tmp_path, repo_root, limits_file, env)
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.CREDENTIAL_REFUSED)
    assert "BINANCE_LIVE_API_KEY" in captured.err
    assert "DEMO" in captured.err
    assert_no_seeded_value(captured.out, captured.err)


def test_the_live_file_form_of_the_other_mode_is_also_refused(
    tmp_path: Path, repo_root: Path, limits_file: Path
) -> None:
    env = demo_env(BINANCE_LIVE_API_SECRET_FILE="/nowhere/at/all")
    with pytest.raises(LiveRefusal) as caught:
        parse_live_environment(env, repo_root=repo_root, limits_path=limits_file)
    assert caught.value.code is LiveExitCode.CREDENTIAL_REFUSED
    assert "BINANCE_LIVE_API_SECRET_FILE" in caught.value.reason


@pytest.mark.parametrize("mode", [None, "TESTNET", "demo ", "demo", "Demo", "", " DEMO", "LIVE "])
def test_a_mode_that_is_not_exactly_demo_or_live_is_refused(
    tmp_path: Path,
    repo_root: Path,
    limits_file: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str | None,
) -> None:
    env = demo_env()
    if mode is None:
        del env["LIVE_RUNTIME_MODE"]
    else:
        env["LIVE_RUNTIME_MODE"] = mode
    code, _ = run_main(tmp_path, repo_root, limits_file, env)
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.MODE_REFUSED)
    assert "LIVE_RUNTIME_MODE" in captured.err
    assert_no_seeded_value(captured.out, captured.err)


def test_live_mode_is_refused_while_live_orders_are_disabled(
    tmp_path: Path,
    repo_root: Path,
    limits_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = {
        "LIVE_RUNTIME_MODE": "LIVE",
        "BINANCE_LIVE_API_KEY": LIVE_KEY,
        "BINANCE_LIVE_API_SECRET": LIVE_SECRET,
        "TELEGRAM_LIVE_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID": "424242",
        "TELEGRAM_AUTHORIZED_USER_IDS": "424242",
    }
    code, _ = run_main(tmp_path, repo_root, limits_file, env)
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.MODE_REFUSED)
    assert "LIVE_ORDERS_DISABLED" in captured.err
    assert "LIVE" in captured.err
    assert_no_seeded_value(captured.out, captured.err)


def test_the_default_of_the_orders_flag_is_the_enablement_controllers(
    repo_root: Path, limits_file: Path
) -> None:
    assert live_config.live_orders_disabled_by_default() is True


def test_live_mode_loads_only_live_credentials_once_orders_are_enabled(
    repo_root: Path, limits_file: Path
) -> None:
    env = {
        "LIVE_RUNTIME_MODE": "LIVE",
        "BINANCE_LIVE_API_KEY": LIVE_KEY,
        "BINANCE_LIVE_API_SECRET": LIVE_SECRET,
        "TELEGRAM_LIVE_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID": "424242",
        "TELEGRAM_AUTHORIZED_USER_IDS": "424242",
    }
    config = parse_live_environment(
        env, repo_root=repo_root, limits_path=limits_file, live_orders_disabled=False
    )
    assert config.mode is Environment.LIVE
    with pytest.raises(LiveRefusal) as caught:
        parse_live_environment(
            {**env, "BINANCE_DEMO_API_KEY": DEMO_KEY},
            repo_root=repo_root,
            limits_path=limits_file,
            live_orders_disabled=False,
        )
    assert caught.value.code is LiveExitCode.CREDENTIAL_REFUSED
    assert "BINANCE_DEMO_API_KEY" in caught.value.reason


@pytest.mark.parametrize("name", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_FILE"])
def test_the_shadow_bot_variable_is_refused(
    tmp_path: Path,
    repo_root: Path,
    limits_file: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    env = demo_env(**{name: SHADOW_TOKEN})
    code, _ = run_main(tmp_path, repo_root, limits_file, env)
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.CREDENTIAL_REFUSED)
    assert name in captured.err
    assert_no_seeded_value(captured.out, captured.err)


@pytest.mark.parametrize(
    "missing",
    ["TELEGRAM_LIVE_BOT_TOKEN", "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID", "TELEGRAM_AUTHORIZED_USER_IDS"],
)
def test_a_missing_telegram_variable_is_refused_by_name(
    tmp_path: Path,
    repo_root: Path,
    limits_file: Path,
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    env = demo_env()
    del env[missing]
    code, _ = run_main(tmp_path, repo_root, limits_file, env)
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.CREDENTIAL_REFUSED)
    assert missing in captured.err
    assert_no_seeded_value(captured.out, captured.err)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TELEGRAM_LIVE_AUTHORIZED_CHAT_ID", "not-a-number"),
        ("TELEGRAM_LIVE_AUTHORIZED_CHAT_ID", "0"),
        ("TELEGRAM_AUTHORIZED_USER_IDS", "1,,2"),
        ("TELEGRAM_AUTHORIZED_USER_IDS", "007"),
    ],
)
def test_a_malformed_telegram_value_is_refused_without_echoing_it(
    repo_root: Path, limits_file: Path, name: str, value: str
) -> None:
    with pytest.raises(LiveRefusal) as caught:
        parse_live_environment(
            demo_env(**{name: value}), repo_root=repo_root, limits_path=limits_file
        )
    assert caught.value.code is LiveExitCode.CREDENTIAL_REFUSED
    assert name in caught.value.reason
    assert value not in caught.value.reason


def test_an_unset_limit_key_is_refused_naming_keys_only(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values: dict[str, int | None] = dict(TEST_ONLY_EXECUTION_LIMIT_VALUES)
    values["stale_feed.max_user_data_silence_ms"] = None
    values["protection.max_unprotected_ms"] = None
    limits = write_execution_limits_toml(tmp_path / "unset.toml", values=values)
    code, _ = run_main(tmp_path, repo_root, limits, demo_env())
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.LIMITS_NOT_CONFIGURED)
    assert "stale_feed.max_user_data_silence_ms" in captured.err
    assert "protection.max_unprotected_ms" in captured.err
    assert "7777" not in captured.err
    assert_no_seeded_value(captured.out, captured.err)


def test_the_shipped_limits_file_keeps_the_live_path_refused_until_the_owner_fills_it(
    tmp_path: Path, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shipped = Path(__file__).resolve().parents[1] / "config" / "execution"
    shipped_file = shipped / "execution-limits-v1.toml"
    if "NOT_CONFIGURED" not in shipped_file.read_text(encoding="utf-8"):
        pytest.skip("the owner has filled the shipped limits file (plan 24-06)")
    code, _ = run_main(tmp_path, repo_root, shipped_file, demo_env())
    assert code == int(LiveExitCode.LIMITS_NOT_CONFIGURED)
    capsys.readouterr()


def test_a_missing_limits_file_is_refused(tmp_path: Path, repo_root: Path) -> None:
    with pytest.raises(LiveRefusal) as caught:
        parse_live_environment(
            demo_env(), repo_root=repo_root, limits_path=tmp_path / "does-not-exist.toml"
        )
    assert caught.value.code is LiveExitCode.LIMITS_NOT_CONFIGURED


def test_the_refusal_order_is_mode_then_credentials_then_telegram_then_limits(
    tmp_path: Path, repo_root: Path
) -> None:
    values: dict[str, int | None] = dict(TEST_ONLY_EXECUTION_LIMIT_VALUES)
    values["protection.max_unprotected_ms"] = None
    unset = write_execution_limits_toml(tmp_path / "unset.toml", values=values)
    everything_wrong = demo_env(BINANCE_LIVE_API_KEY=LIVE_KEY, TELEGRAM_BOT_TOKEN=SHADOW_TOKEN)
    del everything_wrong["TELEGRAM_LIVE_BOT_TOKEN"]
    everything_wrong["LIVE_RUNTIME_MODE"] = "TESTNET"
    codes = []
    for fix in (None, "mode", "credentials", "telegram"):
        if fix == "mode":
            everything_wrong["LIVE_RUNTIME_MODE"] = "DEMO"
        elif fix == "credentials":
            del everything_wrong["BINANCE_LIVE_API_KEY"]
        elif fix == "telegram":
            del everything_wrong["TELEGRAM_BOT_TOKEN"]
            everything_wrong["TELEGRAM_LIVE_BOT_TOKEN"] = BOT_TOKEN
        with pytest.raises(LiveRefusal) as caught:
            parse_live_environment(everything_wrong, repo_root=repo_root, limits_path=unset)
        codes.append(caught.value.code)
    assert codes == [
        LiveExitCode.MODE_REFUSED,
        LiveExitCode.CREDENTIAL_REFUSED,
        LiveExitCode.CREDENTIAL_REFUSED,
        LiveExitCode.LIMITS_NOT_CONFIGURED,
    ]


def test_a_valid_demo_environment_is_admitted_and_the_config_hides_its_secrets(
    repo_root: Path, limits_file: Path
) -> None:
    config = parse_live_environment(demo_env(), repo_root=repo_root, limits_path=limits_file)
    assert isinstance(config, LiveConfig)
    assert config.mode is Environment.DEMO
    assert config.authorized_chat_id == 424242
    assert config.authorized_user_ids == frozenset({424242, 515151})
    assert config.telegram_token_variable == "TELEGRAM_LIVE_BOT_TOKEN"
    assert config.telegram_chat_variable == "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID"
    assert config.telegram_user_ids_variable == "TELEGRAM_AUTHORIZED_USER_IDS"
    assert config.limits.stale_feed_max_mark_price_age_ms == 3579
    assert_no_seeded_value(repr(config), str(config))


def test_the_state_paths_derive_from_one_directory(repo_root: Path, limits_file: Path) -> None:
    state = repo_root / "elsewhere"
    config = parse_live_environment(
        demo_env(), repo_root=repo_root, limits_path=limits_file, state_dir=state
    )
    assert config.state_dir == state
    assert config.held_marker_dir == state
    assert config.liveness_dir == state
    assert config.gate_state_path.parent == state
    assert config.spill_dir.parent == state


def test_the_file_credential_form_is_accepted_and_the_secrets_are_redacted(
    tmp_path: Path, repo_root: Path, limits_file: Path
) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    key_file = secrets / "key"
    secret_file = secrets / "secret"
    key_file.write_text("file-key-SEEDED-abcdef0123\n", encoding="utf-8")
    secret_file.write_text("file-secret-SEEDED-fedcba9876\n", encoding="utf-8")
    env = demo_env()
    del env["BINANCE_DEMO_API_KEY"]
    del env["BINANCE_DEMO_API_SECRET"]
    env["BINANCE_DEMO_API_KEY_FILE"] = str(key_file)
    env["BINANCE_DEMO_API_SECRET_FILE"] = str(secret_file)
    config = parse_live_environment(env, repo_root=repo_root, limits_path=limits_file)
    assert config.credentials.api_key == "file-key-SEEDED-abcdef0123"
    redacted = redaction.scrub("x file-secret-SEEDED-fedcba9876 y " + BOT_TOKEN)
    assert "file-secret-SEEDED-fedcba9876" not in redacted
    assert BOT_TOKEN not in redacted


def test_loaded_secrets_are_registered_with_the_redactor(
    repo_root: Path, limits_file: Path
) -> None:
    parse_live_environment(demo_env(), repo_root=repo_root, limits_path=limits_file)
    redacted = redaction.scrub(f"{DEMO_KEY} {DEMO_SECRET} {BOT_TOKEN}")
    assert_no_seeded_value(redacted)


def test_an_admitted_start_without_a_composed_runner_fails_closed(
    tmp_path: Path, repo_root: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run_main(tmp_path, repo_root, limits_file, demo_env())
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert "runner not composed" in captured.err
    assert_no_seeded_value(captured.out, captured.err)


def test_an_admitted_start_hands_the_context_to_the_runner(
    tmp_path: Path, repo_root: Path, limits_file: Path
) -> None:
    seen: list[runtime.LiveContext] = []

    def runner(context: runtime.LiveContext) -> int:
        seen.append(context)
        return 0

    code, stopper = run_main(
        tmp_path,
        repo_root,
        limits_file,
        demo_env(),
        "--initialize-gate-state",
        "--operator-id",
        "owner-1",
        run_live=runner,
    )
    assert code == 0
    assert stopper.calls == 0
    assert len(seen) == 1
    context = seen[0]
    assert context.config.mode is Environment.DEMO
    assert context.initialize_gate_state is True
    assert context.operator_id == "owner-1"
    assert context.started_at_utc == NOW


def test_a_runner_that_raises_fails_closed_naming_the_class_only(
    tmp_path: Path, repo_root: Path, limits_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def runner(context: runtime.LiveContext) -> int:
        raise RuntimeError(f"boom {DEMO_SECRET}")

    code, _ = run_main(tmp_path, repo_root, limits_file, demo_env(), run_live=runner)
    captured = capsys.readouterr()
    assert code == int(LiveExitCode.STARTUP_FAILED)
    assert "RuntimeError" in captured.err
    assert_no_seeded_value(captured.out, captured.err)


def test_hold_on_refusal_holds_with_the_marker_and_returns_the_code_only_after_the_stop(
    tmp_path: Path, repo_root: Path, limits_file: Path
) -> None:
    state = tmp_path / "state"
    env = demo_env(BINANCE_LIVE_API_KEY=LIVE_KEY)
    code, stopper = run_main(tmp_path, repo_root, limits_file, env, "--hold-on-refusal")
    assert stopper.calls == 1
    assert stopper.marker_during is not None
    assert stopper.marker_during.code == int(LiveExitCode.CREDENTIAL_REFUSED)
    assert stopper.marker_during.refusal == "CREDENTIAL_REFUSED"
    assert held_marker.read_own_marker(state) is None
    assert code == int(LiveExitCode.CREDENTIAL_REFUSED)


def test_without_hold_on_refusal_the_refusal_exits_at_once(
    tmp_path: Path, repo_root: Path, limits_file: Path
) -> None:
    env = demo_env(BINANCE_LIVE_API_KEY=LIVE_KEY)
    code, stopper = run_main(tmp_path, repo_root, limits_file, env)
    assert code == int(LiveExitCode.CREDENTIAL_REFUSED)
    assert stopper.calls == 0
    assert held_marker.read_own_marker(tmp_path / "state") is None


def test_a_hold_whose_marker_cannot_be_written_exits_instead_of_holding(
    tmp_path: Path,
    repo_root: Path,
    limits_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: object, **_kwargs: object) -> Path:
        raise OSError("read-only")

    monkeypatch.setattr(held_marker, "write_marker", broken)
    env = demo_env(BINANCE_LIVE_API_KEY=LIVE_KEY)
    code, stopper = run_main(tmp_path, repo_root, limits_file, env, "--hold-on-refusal")
    assert code == int(LiveExitCode.CREDENTIAL_REFUSED)
    assert stopper.calls == 0


def test_the_exit_code_table_is_stable() -> None:
    assert {code.name: int(code) for code in LiveExitCode} == {
        "OK": 0,
        "USAGE": 2,
        "CREDENTIAL_REFUSED": 3,
        "LIMITS_NOT_CONFIGURED": 4,
        "MODE_REFUSED": 5,
        "STARTUP_FAILED": 7,
    }


def test_the_runtime_never_imports_the_paper_runtime() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "live"
    for path in (root / "runtime.py", root / "config.py"):
        text = path.read_text(encoding="utf-8")
        assert "src.paper.runtime" not in text
