"""Safety tests for the Binance Demo Trading rehearsal runner (quick task 261005-tx9).

Every test is offline. The transport-level tests patch `requests.Session.request`, so no
socket is ever opened, and every credential below is an obviously fake value. Nothing here
runs the runner against Binance, Telegram or a real account.
"""

from __future__ import annotations

import ast
import builtins
import inspect
import json
import pathlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import requests
from binance_common.constants import (
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
)
from scripts import demo_rehearsal as dr
from src.adapters.binance_usdm import (
    AlgoOrderProbe,
    AlgoPlacementResult,
    BinanceUsdmAdapter,
    EntryPlacementResult,
    MarketCloseResult,
    OrderProbe,
    PositionModeResult,
    SymbolFilters,
)
from src.execution.enablement import LiveEnablementController

SCRIPT_PATH = Path(dr.__file__)

FAKE_KEY = "FAKEKEY0123456789ABCDEF"
FAKE_SECRET = "FAKESECRET0123456789GHIJKL"
FAKE_TOKEN = "123456789:FAKETELEGRAMTOKENFAKETELEGRAMTOKEN12"
FAKE_CHAT = "424242"
FAKE_USERS = "777001, 777002"

FIXED_NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)

MUTATING_METHODS = (
    "place_entry",
    "place_algo_protective",
    "cancel_normal_order",
    "cancel_algo_order",
    "place_market_close",
)


def fake_environ() -> dict[str, str]:
    return {
        "BINANCE_DEMO_API_KEY": FAKE_KEY,
        "BINANCE_DEMO_API_SECRET": FAKE_SECRET,
        "TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
        "TELEGRAM_AUTHORIZED_CHAT_ID": FAKE_CHAT,
        "TELEGRAM_AUTHORIZED_USER_IDS": FAKE_USERS,
    }


def fixed_clock() -> datetime:
    return FIXED_NOW


def btc_filters(**overrides: Any) -> SymbolFilters:
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "contract_type": "PERPETUAL",
        "status": "TRADING",
        "onboard_time_utc": None,
        "price_tick_size": Decimal("0.10"),
        "quantity_step_size": Decimal("0.001"),
        "min_quantity": Decimal("0.001"),
        "max_quantity": Decimal("1000"),
        "min_notional": Decimal("100"),
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "margin_asset": "USDT",
        "notional_constraints_json": "{}",
        "order_capabilities_json": "{}",
        "position_mode_snapshot_json": "{}",
        "percent_price_multiplier_up": Decimal("1.05"),
        "percent_price_multiplier_down": Decimal("0.95"),
        "percent_price_multiplier_decimals": 4,
    }
    fields.update(overrides)
    return SymbolFilters(**fields)


class RecordingInner:
    """Recording stand-in for BinanceUsdmAdapter: logs every call, touches no network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def exchange_info(self) -> list[SymbolFilters]:
        self.calls.append("exchange_info")
        return [btc_filters()]

    async def server_time(self) -> datetime:
        self.calls.append("server_time")
        return FIXED_NOW

    async def klines(self, **kwargs: Any) -> list[Any]:
        self.calls.append("klines")
        return []

    async def mark_klines(self, **kwargs: Any) -> list[Any]:
        self.calls.append("mark_klines")
        return []

    async def user_commission_rate(self, symbol: str) -> Any:
        self.calls.append("user_commission_rate")
        return None

    async def get_position_mode(self) -> PositionModeResult:
        self.calls.append("get_position_mode")
        return PositionModeResult(dual_side_position=False)

    async def snapshot_open_normal_orders(self, **kwargs: Any) -> list[Any]:
        self.calls.append("snapshot_open_normal_orders")
        return []

    async def snapshot_open_algo_orders(self, **kwargs: Any) -> list[Any]:
        self.calls.append("snapshot_open_algo_orders")
        return []

    async def snapshot_positions(self, **kwargs: Any) -> list[Any]:
        self.calls.append("snapshot_positions")
        return []

    async def query_order_by_client(self, **kwargs: Any) -> OrderProbe:
        self.calls.append("query_order_by_client")
        return OrderProbe(
            client_order_id=kwargs["orig_client_order_id"],
            found=False,
            order_id=None,
            status=None,
            update_time_utc=None,
        )

    async def query_algo_order_by_client(self, **kwargs: Any) -> AlgoOrderProbe:
        self.calls.append("query_algo_order_by_client")
        return AlgoOrderProbe(
            client_algo_id=kwargs["client_algo_id"],
            found=False,
            algo_status=None,
            update_time_utc=None,
        )

    async def place_entry(self, **kwargs: Any) -> Any:
        self.calls.append("place_entry")
        raise AssertionError("a mutating method reached the inner adapter")

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        self.calls.append("place_algo_protective")
        raise AssertionError("a mutating method reached the inner adapter")

    async def cancel_normal_order(self, **kwargs: Any) -> None:
        self.calls.append("cancel_normal_order")
        raise AssertionError("a mutating method reached the inner adapter")

    async def cancel_algo_order(self, **kwargs: Any) -> None:
        self.calls.append("cancel_algo_order")
        raise AssertionError("a mutating method reached the inner adapter")

    async def place_market_close(self, **kwargs: Any) -> Any:
        self.calls.append("place_market_close")
        raise AssertionError("a mutating method reached the inner adapter")

    async def symbol_lot_filters(self, **kwargs: Any) -> Any:
        self.calls.append("symbol_lot_filters")
        return "LOT-FILTERS-SENTINEL"

    async def get_last_price(self, **kwargs: Any) -> Any:
        self.calls.append("get_last_price")
        return "LAST-PRICE-SENTINEL"


class CountingFactory:
    """adapter_factory seam that counts builds and hands back one RecordingInner."""

    def __init__(self) -> None:
        self.builds = 0
        self.inner = RecordingInner()

    def __call__(self, credentials: dr.RehearsalCredentials) -> dr.AdapterBundle:
        self.builds += 1
        return dr.AdapterBundle(inner=self.inner, guard=lambda: None)  # type: ignore[arg-type]


def make_recorder(
    mode: dr.RunMode = dr.RunMode.DRY_RUN, environ: dict[str, str] | None = None
) -> dr.EvidenceRecorder:
    return dr.EvidenceRecorder(
        mode=mode,
        scenario="far",
        symbol="BTCUSDT",
        base_url=dr.DEMO_BASE_URL,
        environ=environ if environ is not None else fake_environ(),
        clock=fixed_clock,
    )


def run_main(
    argv: list[str],
    tmp_path: Path,
    factory: CountingFactory | None = None,
    *,
    is_tty: bool = False,
    confirmation: Callable[[str], str] | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[int, CountingFactory]:
    used = factory if factory is not None else CountingFactory()
    code = dr.main(
        argv,
        environ=environ if environ is not None else fake_environ(),
        adapter_factory=used,
        clock=fixed_clock,
        is_tty=lambda: is_tty,
        read_confirmation=confirmation,
        evidence_dir=tmp_path,
        # The spine tests exercise the tracer path only (reads, evidence, gates); the full
        # scenarios and their Telegram dependencies are covered in test_demo_rehearsal_flow.py.
        scenario_runner=dr.run_tracer,
    )
    return code, used


# --------------------------------------------------------------------------- #
# SR-1 credentials.
# --------------------------------------------------------------------------- #


def test_load_credentials_reads_only_the_five_named_env_vars() -> None:
    env = fake_environ()
    env["UNRELATED_SECRET"] = "must-never-be-read-1234"
    creds = dr.load_credentials(env)
    assert creds.binance_api_key == FAKE_KEY
    assert creds.binance_api_secret == FAKE_SECRET
    assert creds.telegram_bot_token == FAKE_TOKEN
    assert creds.telegram_chat_id == 424242
    assert creds.telegram_user_ids == frozenset({777001, 777002})
    for rendered in (repr(creds), str(creds)):
        for secret in (FAKE_KEY, FAKE_SECRET, FAKE_TOKEN):
            assert secret not in rendered

    for name in (
        "BINANCE_DEMO_API_KEY",
        "BINANCE_DEMO_API_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_AUTHORIZED_CHAT_ID",
        "TELEGRAM_AUTHORIZED_USER_IDS",
    ):
        missing = fake_environ()
        del missing[name]
        with pytest.raises(dr.CredentialError) as info:
            dr.load_credentials(missing)
        assert name in str(info.value)
        blank = fake_environ()
        blank[name] = "   "
        with pytest.raises(dr.CredentialError):
            dr.load_credentials(blank)

    bad_chat = fake_environ()
    bad_chat["TELEGRAM_AUTHORIZED_CHAT_ID"] = "not-an-int"
    with pytest.raises(dr.CredentialError) as info:
        dr.load_credentials(bad_chat)
    assert "not-an-int" not in str(info.value)

    for bad_users in ("abc", "777001,", "0", "-5", "777001,777001"):
        bad = fake_environ()
        bad["TELEGRAM_AUTHORIZED_USER_IDS"] = bad_users
        with pytest.raises(dr.CredentialError) as info:
            dr.load_credentials(bad)
        assert "TELEGRAM_AUTHORIZED_USER_IDS" in str(info.value)
        assert bad_users not in str(info.value)


_FORBIDDEN_ENV_FILE_TOKENS = ("dotenv", "env_file", "pydantic_settings")


def test_runner_never_opens_an_environment_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(t in alias.name for t in _FORBIDDEN_ENV_FILE_TOKENS)
        elif isinstance(node, ast.ImportFrom):
            assert not any(t in (node.module or "") for t in _FORBIDDEN_ENV_FILE_TOKENS)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.rstrip().endswith(".env")
            assert not any(t in node.value for t in _FORBIDDEN_ENV_FILE_TOKENS)

    real_open = builtins.open
    real_path_open = pathlib.Path.open
    real_read_text = pathlib.Path.read_text

    def guard(name: Any) -> None:
        if str(name).lower().endswith(".env"):
            raise AssertionError(f"environment file touched: {name}")

    def spy_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        guard(file)
        return real_open(file, *args, **kwargs)

    def spy_path_open(self: pathlib.Path, *args: Any, **kwargs: Any) -> Any:
        guard(self)
        return real_path_open(self, *args, **kwargs)

    def spy_read_text(self: pathlib.Path, *args: Any, **kwargs: Any) -> Any:
        guard(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(pathlib.Path, "open", spy_path_open)
    monkeypatch.setattr(pathlib.Path, "read_text", spy_read_text)
    code, _ = run_main(["--scenario", "taps"], tmp_path)
    assert code == 0


# --------------------------------------------------------------------------- #
# SR-2 Demo host only.
# --------------------------------------------------------------------------- #


def test_demo_base_url_is_the_sdk_demo_constant() -> None:
    assert dr.DEMO_BASE_URL == DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
    assert dr.DEMO_HOST == "demo-fapi.binance.com"
    assert dr.DEMO_BASE_URL == f"https://{dr.DEMO_HOST}"


@pytest.mark.parametrize(
    "url",
    [
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
        "https://fapi.binance.com/",
        "http://demo-fapi.binance.com",
        "https://demo-fapi.binance.com.evil.example",
        "https://demo-fapi.binance.com@evil.example",
        "https://demo-fapi.binance.com:8443",
        "https://demo-fapi.binance.com/extra",
        "",
        None,
    ],
)
def test_assert_demo_base_url_rejects_everything_else(url: Any) -> None:
    with pytest.raises(dr.DemoHostViolation):
        dr.assert_demo_base_url(url)


def test_assert_demo_base_url_accepts_the_exact_demo_url() -> None:
    dr.assert_demo_base_url(DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL)


def test_demo_client_factory_has_no_host_parameter() -> None:
    params = inspect.signature(dr.build_demo_sdk_client).parameters
    assert list(params) == ["api_key", "api_secret"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())


class _Sentinel(Exception):  # noqa: N818 - a test marker, not an error taxonomy
    """Raised by the patched transport so no network error can masquerade as success."""


def _patch_transport(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake_request(self: requests.Session, *args: Any, **kwargs: Any) -> Any:
        seen.append(str(kwargs.get("url")))
        raise _Sentinel

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return seen


def _real_guarded(mode: dr.RunMode = dr.RunMode.EXECUTE) -> tuple[Any, dr.GuardedAdapter]:
    client = dr.build_demo_sdk_client(api_key=FAKE_KEY, api_secret=FAKE_SECRET)
    inner = BinanceUsdmAdapter(sdk_client=client)
    guarded = dr.GuardedAdapter(
        inner,
        guard=lambda: dr.assert_demo_sdk_client(client),
        mode=mode,
        clock=fixed_clock,
        recorder=make_recorder(mode),
    )
    return client, guarded


async def test_every_request_targets_the_demo_host_at_transport_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_transport(monkeypatch)
    _, guarded = _real_guarded()
    with pytest.raises(_Sentinel):
        await guarded.server_time()
    with pytest.raises(_Sentinel):
        await guarded.exchange_info()
    assert len(seen) == 2
    assert all(url.startswith("https://demo-fapi.binance.com/") for url in seen)


async def test_mutated_base_path_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_transport(monkeypatch)
    client, guarded = _real_guarded()
    client.rest_api.configuration.base_path = DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    with pytest.raises(dr.DemoHostViolation):
        await guarded.server_time()
    with pytest.raises(dr.DemoHostViolation):
        await guarded.snapshot_open_normal_orders(symbol="BTCUSDT")
    assert seen == []


def test_runner_source_has_no_prod_host_or_default_client_construction() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert not re.search(r"(?<!demo-)fapi\.binance\.com", source)
    tree = ast.parse(source)

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []
            self.sdk_constructions: list[str] = []
            self.bare_adapters = 0

        def _visit_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit_def
        visit_AsyncFunctionDef = _visit_def

        def visit_Call(self, node: ast.Call) -> None:
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name == "DerivativesTradingUsdsFutures":
                self.sdk_constructions.append(self.stack[-1] if self.stack else "<module>")
            if name == "BinanceUsdmAdapter" and not node.args and not node.keywords:
                self.bare_adapters += 1
            self.generic_visit(node)

    visitor = _Visitor()
    visitor.visit(tree)
    assert visitor.sdk_constructions == ["build_demo_sdk_client"]
    assert visitor.bare_adapters == 0


# --------------------------------------------------------------------------- #
# SR-9 dry-run default and the --execute gate.
# --------------------------------------------------------------------------- #


async def test_dry_run_never_reaches_mutating_methods() -> None:
    inner = RecordingInner()
    recorder = make_recorder()
    guarded = dr.GuardedAdapter(
        inner,  # type: ignore[arg-type]
        guard=lambda: None,
        mode=dr.RunMode.DRY_RUN,
        clock=fixed_clock,
        recorder=recorder,
    )
    entry = await guarded.place_entry(
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=Decimal("0.002"),
        price=Decimal("50000.0"),
        new_client_order_id="e" * 36,
    )
    algo = await guarded.place_algo_protective(
        symbol="BTCUSDT",
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=Decimal("49000.0"),
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id="a" * 36,
    )
    await guarded.cancel_normal_order(symbol="BTCUSDT", orig_client_order_id="e" * 36)
    await guarded.cancel_algo_order(symbol="BTCUSDT", client_algo_id="a" * 36)
    # Plan 19-16: the emergency close is a mutating method too; in a dry run it is only planned.
    close = await guarded.place_market_close(
        symbol="BTCUSDT",
        side="SELL",
        position_side="BOTH",
        quantity=Decimal("0.002"),
        new_client_order_id="c" * 36,
    )
    assert inner.calls == []
    assert guarded.mutating_attempts == len(MUTATING_METHODS)
    assert isinstance(close, MarketCloseResult) and close.status == "NEW"
    assert close.executed_quantity is None and close.average_price is None
    assert isinstance(entry, EntryPlacementResult) and entry.status == "NEW"
    assert isinstance(algo, AlgoPlacementResult) and algo.algo_status == "NEW"
    assert [p["method"] for p in recorder.planned_requests] == list(MUTATING_METHODS)
    assert recorder.exchange_orders == []

    await guarded.server_time()
    await guarded.snapshot_positions(symbol="BTCUSDT")
    assert inner.calls == ["server_time", "snapshot_positions"]
    # symbol_lot_filters is a read passthrough: allowed in a dry run, never counted as mutating.
    assert await guarded.symbol_lot_filters(symbol="BTCUSDT") == "LOT-FILTERS-SENTINEL"
    assert inner.calls[-1] == "symbol_lot_filters"
    # Quick task 261020-l4p: the last-price read (gate 5e) is a read passthrough too.
    assert await guarded.get_last_price(symbol="BTCUSDT") == "LAST-PRICE-SENTINEL"
    assert inner.calls[-1] == "get_last_price"
    assert guarded.mutating_attempts == len(MUTATING_METHODS)

    with pytest.raises(AttributeError):
        guarded.open_interest  # noqa: B018 - there is no passthrough to the inner adapter
    with pytest.raises(AttributeError):
        guarded.new_order  # noqa: B018


def test_execute_requires_tty_and_exact_phrase(tmp_path: Path) -> None:
    def raises_eof(_prompt: str) -> str:
        raise EOFError

    cases: list[tuple[bool, Callable[[str], str] | None]] = [
        (False, lambda _p: "DEMO SMOKE BTCUSDT"),
        (True, raises_eof),
        (True, lambda _p: "demo smoke btcusdt"),
        (True, lambda _p: "DEMO SMOKE BTCUSDT please"),
        (True, lambda _p: ""),
    ]
    for is_tty, confirmation in cases:
        factory = CountingFactory()
        code, _ = run_main(
            ["--scenario", "smoke", "--execute"],
            tmp_path,
            factory,
            is_tty=is_tty,
            confirmation=confirmation,
        )
        assert code == dr.EXIT_REFUSED == 2
        assert factory.builds == 0
        assert factory.inner.calls == []
    assert list(tmp_path.iterdir()) == []

    # The exact phrase on a terminal passes the gate; the composed smoke then admits the live
    # process's own environment (LIVE_RUNTIME_MODE=DEMO and the live names). This one has none,
    # so the run is refused before any adapter, SDK object or network call (plan 24-29).
    factory = CountingFactory()
    code, _ = run_main(
        ["--scenario", "smoke", "--execute"],
        tmp_path,
        factory,
        is_tty=True,
        confirmation=lambda _p: "DEMO SMOKE BTCUSDT",
    )
    assert code == dr.EXIT_REFUSED
    assert factory.builds == 0
    assert list(tmp_path.iterdir()) == []


def test_execute_with_the_taps_scenario_is_a_usage_error(tmp_path: Path) -> None:
    factory = CountingFactory()
    code, _ = run_main(
        ["--scenario", "taps", "--execute"],
        tmp_path,
        factory,
        is_tty=True,
        confirmation=lambda _p: "DEMO TAPS BTCUSDT",
    )
    assert code == dr.EXIT_REFUSED
    assert factory.builds == 0


def test_no_host_symbol_or_base_url_option_exists(tmp_path: Path) -> None:
    for flag in ("--symbol", "--host", "--base-url"):
        code, factory = run_main([flag, "x"], tmp_path)
        assert code == dr.EXIT_REFUSED
        assert factory.builds == 0


def test_missing_credentials_refuse_before_any_adapter_is_built(tmp_path: Path) -> None:
    env = fake_environ()
    del env["BINANCE_DEMO_API_SECRET"]
    code, factory = run_main(["--scenario", "taps"], tmp_path, environ=env)
    assert code == dr.EXIT_REFUSED
    assert factory.builds == 0


def test_missing_user_allow_list_refuses_before_any_adapter_is_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Phase 23 (D-02): no allow-list, no rehearsal; the refusal names the variable only."""
    env = fake_environ()
    del env["TELEGRAM_AUTHORIZED_USER_IDS"]
    code, factory = run_main(["--scenario", "taps"], tmp_path, environ=env)
    assert code == dr.EXIT_REFUSED
    assert factory.builds == 0
    assert "TELEGRAM_AUTHORIZED_USER_IDS" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Plan 18-13: the ratified signed-call policy and the one REST gate.
# --------------------------------------------------------------------------- #


def test_missing_limits_file_refuses_before_any_adapter_is_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "absent-limits.toml"
    code, factory = run_main(["--scenario", "taps", "--limits-file", str(missing)], tmp_path)
    assert code == dr.EXIT_REFUSED
    assert factory.builds == 0
    err = capsys.readouterr().err
    assert "LimitsFileRefused" in err
    assert str(missing) in err
    assert not list(tmp_path.glob("09-DEMO-REHEARSAL-*.json"))


def test_invalid_limits_file_refuses_and_names_the_path_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken-limits.toml"
    broken.write_text("[signed_calls]\nrecv_window_ms = \n", encoding="utf-8")
    code, factory = run_main(["--scenario", "taps", "--limits-file", str(broken)], tmp_path)
    assert code == dr.EXIT_REFUSED
    assert factory.builds == 0
    err = capsys.readouterr().err
    assert str(broken) in err
    assert "TOML" not in err  # the loader's problem list is not echoed, only the path


def test_limits_file_option_defaults_to_the_ratified_repository_file() -> None:
    args = dr._build_parser().parse_args([])
    assert args.limits_file == dr.REPO_ROOT / "config" / "binance" / "binance-limits-v1.toml"
    assert args.limits_file == dr.DEFAULT_LIMITS_FILE
    assert dr.load_signed_call_policy(args.limits_file).recv_window_ms > 0


def test_default_adapter_factory_carries_the_policy_and_one_shared_gate() -> None:
    policy = dr.load_signed_call_policy(dr.DEFAULT_LIMITS_FILE)
    credentials = dr.load_credentials(fake_environ())
    bundle = dr.default_adapter_factory(credentials, signed_call_policy=policy, clock=fixed_clock)
    inner = bundle.inner
    assert inner._signed_call_policy is policy  # noqa: SLF001
    gate = inner._rest_gate  # noqa: SLF001
    assert gate is not None
    assert gate.policy == policy.rate_limit
    assert inner._public._rest_gate is gate  # noqa: SLF001 - the one gate, shared
    assert inner._drift_guard is None  # noqa: SLF001 - an operator tool, not the runtime


def test_runner_source_builds_exactly_one_rest_gate() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    owners: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def _visit_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit_def
        visit_AsyncFunctionDef = _visit_def

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id == "RestRateLimitGate":
                owners.append(self.stack[-1] if self.stack else "<module>")
            self.generic_visit(node)

    _Visitor().visit(tree)
    assert owners == ["default_adapter_factory"]
    assert "ClockDriftGuard" not in SCRIPT_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# SR-8 evidence hygiene.
# --------------------------------------------------------------------------- #


def test_evidence_is_scrubbed_atomic_and_lf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorder = make_recorder()
    recorder.add_step("probe", "FAILED", "detail")
    recorder.record_failure("probe", ValueError("boom"), message=f"leaked {FAKE_SECRET} here")

    replaced: list[tuple[str, str]] = []
    real_replace = dr.os.replace

    def spy_replace(src: Any, dst: Any) -> None:
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(dr.os, "replace", spy_replace)
    path = recorder.write(tmp_path)

    assert len(replaced) == 1
    assert replaced[0][1] == str(path)
    assert replaced[0][0] != str(path)
    raw = path.read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    text = raw.decode("utf-8")
    assert FAKE_SECRET not in text
    assert FAKE_KEY not in text
    assert "[REDACTED]" in text
    loaded = json.loads(text)
    assert text == json.dumps(loaded, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    from src.ops.redaction import Redactor

    assert Redactor.from_environ(fake_environ()).scrub(text) == text
    assert loaded["failures"][0]["exception_type"] == "ValueError"
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_evidence_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    first = make_recorder().write(tmp_path)
    second = make_recorder().write(tmp_path)
    assert first != second
    assert first.exists() and second.exists()


def test_evidence_cannot_record_a_hand_written_exchange_record() -> None:
    recorder = make_recorder(dr.RunMode.EXECUTE)
    for bogus in ({"order_id": "1"}, "order", 7, None, object()):
        with pytest.raises(TypeError):
            recorder.record_exchange_record(bogus)
    assert recorder.exchange_orders == [] and recorder.observations == []

    entry = EntryPlacementResult(
        symbol="BTCUSDT",
        client_order_id="e" * 36,
        exchange_order_id="9001",
        side="BUY",
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTC",
        status="NEW",
        quantity=Decimal("0.002"),
        price=Decimal("50000.0"),
        update_time_utc=FIXED_NOW,
    )
    recorder.record_exchange_record(entry)
    recorder.record_exchange_record(
        OrderProbe(
            client_order_id="e" * 36,
            found=True,
            order_id="9001",
            status="NEW",
            update_time_utc=FIXED_NOW,
        )
    )
    assert len(recorder.exchange_orders) == 1
    assert recorder.exchange_orders[0]["exchange_order_id"] == "9001"
    assert recorder.exchange_orders[0]["price"] == "50000.0"
    assert recorder.exchange_orders[0]["source"] == "exchange_response"
    assert len(recorder.observations) == 1


def test_dry_run_evidence_carries_no_exchange_order_and_a_dryrun_name(tmp_path: Path) -> None:
    dry = make_recorder(dr.RunMode.DRY_RUN)
    with pytest.raises(TypeError):
        # a dry run never talks to the order endpoints, so it cannot hold an order record
        dry.record_exchange_record(
            EntryPlacementResult(
                symbol="BTCUSDT",
                client_order_id="e" * 36,
                exchange_order_id="1",
                side="BUY",
                position_side="BOTH",
                order_type="LIMIT",
                time_in_force="GTC",
                status="NEW",
                quantity=Decimal("1"),
                price=Decimal("1"),
                update_time_utc=FIXED_NOW,
            )
        )
    path = dry.write(tmp_path)
    assert "DRYRUN" in path.name
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["exchange_orders"] == []
    assert data["mode"] == "DRY_RUN"
    live = make_recorder(dr.RunMode.EXECUTE).write(tmp_path)
    assert "DRYRUN" not in live.name and "EVIDENCE" in live.name


# --------------------------------------------------------------------------- #
# SR-3 enablement default and the tracer path.
# --------------------------------------------------------------------------- #


class _Journal:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def test_live_orders_stay_disabled_by_default(tmp_path: Path) -> None:
    journal = _Journal()
    assert LiveEnablementController(journal=journal).is_disabled
    assert journal.events == []
    # The rehearsal runner (tracer path) never enables live orders: nothing mutating is sent
    # and its evidence carries no enablement record (review WR-11).
    code, factory = run_main(["--scenario", "taps"], tmp_path)
    assert code == 0
    assert not set(factory.inner.calls) & set(MUTATING_METHODS)
    (written,) = tmp_path.glob("09-DEMO-REHEARSAL-DRYRUN-taps-*.json")
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "enablement" not in data.get("details", {})
    assert data["exchange_orders"] == []


def test_tracer_dry_run_main_end_to_end(tmp_path: Path) -> None:
    code, factory = run_main(["--scenario", "taps"], tmp_path)
    assert code == 0
    assert factory.builds == 1
    assert not set(factory.inner.calls) & set(MUTATING_METHODS)
    written = list(tmp_path.glob("09-DEMO-REHEARSAL-DRYRUN-taps-*.json"))
    assert len(written) == 1
    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["schema"] == "demo-rehearsal-evidence/schema-1"
    assert data["mode"] == "DRY_RUN"
    assert data["symbol"] == "BTCUSDT"
    assert data["base_url"] == "https://demo-fapi.binance.com"
    assert data["exchange_orders"] == []
    assert data["constraints"]["price_tick_size"] == "0.10"
    assert data["constraints"]["quantity_step_size"] == "0.001"
    assert data["constraints"]["min_quantity"] == "0.001"
    assert data["constraints"]["min_notional"] == "100"
    assert data["outcome"] == "COMPLETE"
    text = written[0].read_text(encoding="utf-8")
    for secret in (FAKE_KEY, FAKE_SECRET, FAKE_TOKEN):
        assert secret not in text


def test_tracer_fails_closed_when_btcusdt_is_not_a_trading_perpetual(tmp_path: Path) -> None:
    class Halted(RecordingInner):
        async def exchange_info(self) -> list[SymbolFilters]:
            self.calls.append("exchange_info")
            return [btc_filters(status="BREAK")]

    factory = CountingFactory()
    factory.inner = Halted()
    code, _ = run_main(["--scenario", "taps"], tmp_path, factory)
    assert code == dr.EXIT_ABORTED == 3
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert data["outcome"] == "ABORTED_NO_ORDER"
    assert data["exchange_orders"] == []


# --------------------------------------------------------------------------- #
# Plan 24-29: the guards of the composed smoke (T-24-91, T-24-92, T-24-93).
# --------------------------------------------------------------------------- #

SMOKE_ENV = {
    "LIVE_RUNTIME_MODE": "DEMO",
    "BINANCE_DEMO_API_KEY": "FAKE-DEMO-KEY-SEEDED-0001",
    "BINANCE_DEMO_API_SECRET": "FAKE-DEMO-SECRET-SEEDED-0002",
    "TELEGRAM_LIVE_BOT_TOKEN": "123456:FAKE-LIVE-BOT-TOKEN-SEEDED",
    "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID": "424242",
    "TELEGRAM_AUTHORIZED_USER_IDS": "424242,515151",
}


@pytest.fixture
def _clean_runtime_secrets() -> None:
    from src.ops import redaction

    redaction.clear_runtime_secrets()


def test_the_smoke_admits_a_complete_demo_environment(_clean_runtime_secrets: None) -> None:
    config = dr.admit_smoke_environment(dict(SMOKE_ENV))
    assert config.mode.value == "DEMO"
    assert config.limits.unset_keys() == ()


@pytest.mark.parametrize(
    "change",
    [
        {"LIVE_RUNTIME_MODE": "LIVE"},
        {"LIVE_RUNTIME_MODE": "TESTNET"},
        {"BINANCE_LIVE_API_KEY": "FAKE-LIVE-KEY-SEEDED-0003"},
        {"BINANCE_LIVE_API_SECRET": "FAKE-LIVE-SECRET-SEEDED-0004"},
        {"TELEGRAM_BOT_TOKEN": "654321:FAKE-SHADOW-BOT-TOKEN-SEEDED"},
    ],
)
def test_live_credentials_a_live_mode_or_the_shadow_bot_refuse_the_smoke(
    change: dict[str, str], _clean_runtime_secrets: None
) -> None:
    with pytest.raises(dr.SmokeRefused) as caught:
        dr.admit_smoke_environment({**SMOKE_ENV, **change})
    for value in change.values():
        if "SEEDED" in value:
            assert value not in str(caught.value)


def test_a_missing_variable_is_named_by_the_refusal_and_never_its_value(
    _clean_runtime_secrets: None,
) -> None:
    env = dict(SMOKE_ENV)
    del env["TELEGRAM_LIVE_BOT_TOKEN"]
    with pytest.raises(dr.SmokeRefused, match="TELEGRAM_LIVE_BOT_TOKEN"):
        dr.admit_smoke_environment(env)


def test_the_demo_sdk_factory_wraps_the_one_place_a_client_is_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from src.adapters import binance_client
    from src.adapters.binance_client import Environment

    def bundle_for(base_path: str) -> Any:
        rest = SimpleNamespace(configuration=SimpleNamespace(base_path=base_path))
        return SimpleNamespace(client=SimpleNamespace(rest_api=rest))

    built: list[dict[str, Any]] = []

    def fake_build(**kwargs: Any) -> Any:
        built.append(kwargs)
        return bundle_for(dr.DEMO_BASE_URL)

    monkeypatch.setattr(binance_client, "build_sdk_client", fake_build)
    assert dr.demo_guarded_sdk_factory(environment=Environment.DEMO, surfaces=frozenset())
    assert len(built) == 1

    # LIVE (or any other environment) never reaches the SDK builder.
    for environment in (Environment.LIVE, Environment.TESTNET):
        with pytest.raises(dr.DemoHostViolation):
            dr.demo_guarded_sdk_factory(environment=environment, surfaces=frozenset())
    assert len(built) == 1

    # A client whose host is not the Demo host is refused after the build.
    monkeypatch.setattr(
        binance_client, "build_sdk_client", lambda **_k: bundle_for("https://fapi.binance.com")
    )
    with pytest.raises(dr.DemoHostViolation):
        dr.demo_guarded_sdk_factory(environment=Environment.DEMO, surfaces=frozenset())


def test_the_smoke_path_has_no_rehearsal_sink_and_no_hand_stepped_protection() -> None:
    text = Path(dr.__file__).read_text(encoding="utf-8")
    assert "RehearsalAlertSink(" not in text
    assert "_drive_protection" not in text
    assert "build_wiring" not in text or "default_assemble" in text
    assert "ProtectionCoordinator(" not in text and "MarketEmergencyCloser(" not in text


def test_a_refused_smoke_environment_writes_no_evidence_and_builds_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], _clean_runtime_secrets: None
) -> None:
    built: list[object] = []
    env = {**SMOKE_ENV, "LIVE_RUNTIME_MODE": "LIVE"}
    code = dr.main(
        ["--scenario", "smoke", "--execute"],
        environ=env,
        is_tty=lambda: True,
        read_confirmation=lambda _p: "DEMO SMOKE BTCUSDT",
        evidence_dir=tmp_path,
        adapter_factory=lambda creds: built.append(creds),  # type: ignore[arg-type,return-value]
    )
    assert code == dr.EXIT_REFUSED
    assert built == []
    assert list(tmp_path.iterdir()) == []
    assert "LIVE" in capsys.readouterr().err


def test_execute_without_a_terminal_or_the_exact_phrase_refuses_before_admission(
    tmp_path: Path,
) -> None:
    for is_tty, typed in ((False, "DEMO SMOKE BTCUSDT"), (True, "yes"), (True, "")):
        code = dr.main(
            ["--scenario", "smoke", "--execute"],
            environ=dict(SMOKE_ENV),
            is_tty=lambda tty=is_tty: tty,
            read_confirmation=lambda _p, text=typed: text,
            evidence_dir=tmp_path,
        )
        assert code == dr.EXIT_REFUSED
    assert list(tmp_path.iterdir()) == []
