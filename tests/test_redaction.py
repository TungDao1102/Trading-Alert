"""Redaction layer tests (13.1-04, D-09, F-708, OPS-02).

Secrets are generated at run time and never appear in assertion messages: leaks are
reported through ``pytest.fail`` with lengths only (a bare ``assert secret not in out``
would print the secret in the failure explanation).
"""

from __future__ import annotations

import ast
import io
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import pytest
import structlog
from src.data import collector
from src.ops import redaction
from src.ops.redaction import Redactor, configure_logging, scrub

REPO_ROOT = Path(__file__).resolve().parents[1]


def _libpq_text(secret: str) -> str:
    """The verified libpq conninfo error shape that echoes the whole URL (F-708)."""
    return (
        f'missing "=" after "postgresql+psycopg://trading:{secret}@postgres:5432/trading" '
        "in connection info string"
    )


def _no_leak(secret: str, text: str) -> None:
    if secret in text:
        pytest.fail(f"secret of length {len(secret)} leaked into {len(text)} chars of output")


def _telegram_token() -> str:
    return "123456789:" + secrets.token_urlsafe(27)[:35]


# --------------------------------------------------------------------------- #
# Task 1 - tracer: libpq-shaped exception through structlog and the collector print.
# --------------------------------------------------------------------------- #


def test_planted_secret_in_logged_exception_is_redacted() -> None:
    secret = secrets.token_hex(16)
    buffer = io.StringIO()
    configure_logging(environ={"POSTGRES_PASSWORD": secret}, stream=buffer)
    log = structlog.get_logger()
    try:
        raise RuntimeError(_libpq_text(secret))
    except RuntimeError:
        log.exception("db_connect_failed")
    output = buffer.getvalue()
    _no_leak(secret, output)
    assert "[REDACTED]" in output
    record = json.loads(output.strip().splitlines()[-1])
    assert record["event"] == "db_connect_failed"
    assert record["level"] == "error"


def test_url_userinfo_shape_masks_without_a_matching_env_var() -> None:
    secret = secrets.token_hex(16)
    buffer = io.StringIO()
    configure_logging(environ={}, stream=buffer)
    log = structlog.get_logger()
    try:
        raise RuntimeError(_libpq_text(secret))
    except RuntimeError:
        log.exception("db_connect_failed")
    output = buffer.getvalue()
    _no_leak(secret, output)
    assert "[REDACTED]" in output


def test_scrub_returns_text_without_secrets_unchanged() -> None:
    configure_logging(environ={}, stream=io.StringIO())
    text = "collector: loop start universe=5 cadence=300.0s raw_root=data/raw 2026-09-19T00:00:00Z"
    assert scrub(text) == text


def test_module_scrub_builds_from_environment_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = secrets.token_hex(16)
    monkeypatch.setenv("SOME_API_TOKEN", secret)
    redaction.uninstall_global_hooks()  # clears any configured redactor
    cleaned = scrub(f"boom {secret} boom")
    _no_leak(secret, cleaned)
    assert "[REDACTED]" in cleaned


def test_redactor_collects_env_values_url_passwords_and_variants() -> None:
    plain = secrets.token_hex(12)
    urlpw = secrets.token_hex(12) + "%40x"
    env = {
        "BACKUP_CRYPT_PASSWORD": plain,
        "DATABASE_URL": f"postgresql+psycopg://trading:{urlpw}@db:5432/trading",
        "SHORT_SECRET": "tiny",
        "OI_POLL_INTERVAL_SECONDS": "300",
        "PATH": "/usr/bin:/bin",
    }
    redactor = Redactor.from_environ(env)
    for secret in (plain, urlpw, urlpw.replace("%40", "@")):
        _no_leak(secret, redactor.scrub(f"x {secret} y"))
    # percent-encoded and JSON-escaped variants of a value with special characters
    special = 'p@ss/w"rd' + secrets.token_hex(4)
    variant_env = Redactor.from_environ({"X_PASSWORD": special})
    for form in (special, quote(special, safe=""), json.dumps(special)[1:-1]):
        _no_leak(form, variant_env.scrub(f"a {form} b"))
    # below the length floor and unrelated names are left alone
    assert redactor.scrub("tiny 300 /usr/bin:/bin") == "tiny 300 /usr/bin:/bin"


def test_collector_health_unknown_line_is_scrubbed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = secrets.token_hex(16)
    monkeypatch.setenv("POSTGRES_PASSWORD", secret)

    def boom(_url: str | None) -> object:
        raise RuntimeError(_libpq_text(secret))

    monkeypatch.setattr(collector, "_make_sync_engine", boom)
    code = collector.main(["--healthcheck"])
    err = capsys.readouterr().err
    _no_leak(secret, err)
    assert code == 1
    assert err.startswith("collector-health: UNKNOWN")
    assert "[REDACTED]" in err


def test_collector_startup_error_line_is_scrubbed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = secrets.token_hex(16)
    monkeypatch.setenv("POSTGRES_PASSWORD", secret)

    def boom(_url: str | None) -> object:
        raise RuntimeError(_libpq_text(secret))

    monkeypatch.setattr(collector, "_make_sync_engine", boom)
    code = collector.main(["--once"])
    err = capsys.readouterr().err
    _no_leak(secret, err)
    assert code == 2
    assert err.startswith("collector: ")
    assert "[REDACTED]" in err


def _main_first_statement_is_configure_logging(relpath: str) -> bool:
    tree = ast.parse((REPO_ROOT / relpath).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]  # skip the docstring
            first = body[0]
            return (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Name)
                and first.value.func.id == "configure_logging"
                and not first.value.args
                and not first.value.keywords
            )
    return False


def test_collector_main_calls_configure_logging_first() -> None:
    assert _main_first_statement_is_configure_logging("src/data/collector.py")


# --------------------------------------------------------------------------- #
# Task 2 - stdlib logging, uncaught exceptions, httpx, shape and key rules, backfill.
# --------------------------------------------------------------------------- #


def test_stdlib_logging_error_is_scrubbed() -> None:
    secret = secrets.token_hex(16)
    buffer = io.StringIO()
    configure_logging(environ={"X_API_KEY": secret}, stream=buffer)
    logging.getLogger("x").error("connect failed for %s", secret)
    try:
        raise RuntimeError(_libpq_text(secret))
    except RuntimeError:
        logging.getLogger("x").exception("with traceback")
    output = buffer.getvalue()
    _no_leak(secret, output)
    assert "[REDACTED]" in output
    assert "RuntimeError" in output  # the traceback itself is still printed


def test_stdlib_filter_attached_to_every_root_handler() -> None:
    other = logging.StreamHandler(io.StringIO())
    logging.getLogger().addHandler(other)
    configure_logging(environ={}, stream=io.StringIO())
    for handler in logging.getLogger().handlers:
        assert any(isinstance(f, redaction.RedactingFilter) for f in handler.filters)
    configure_logging(environ={}, stream=io.StringIO())  # idempotent: no duplicate filters
    assert sum(isinstance(f, redaction.RedactingFilter) for f in other.filters) == 1


def _run_child(code: str, secret: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PLANTED_SECRET": secret}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


_CHILD_MAIN = (
    "import os\n"
    "from src.ops.redaction import configure_logging\n"
    "configure_logging()\n"
    "raise RuntimeError('db url postgresql+psycopg://u:' + os.environ['PLANTED_SECRET'] + '@h/d')\n"
)

_CHILD_THREAD = (
    "import os, threading\n"
    "from src.ops.redaction import configure_logging\n"
    "configure_logging()\n"
    "def boom():\n"
    "    raise RuntimeError('token ' + os.environ['PLANTED_SECRET'])\n"
    "t = threading.Thread(target=boom, name='worker-1')\n"
    "t.start()\n"
    "t.join()\n"
)


def test_uncaught_exception_in_main_thread_is_scrubbed() -> None:
    secret = secrets.token_hex(16)
    proc = _run_child(_CHILD_MAIN, secret)
    _no_leak(secret, proc.stderr)
    _no_leak(secret, proc.stdout)
    assert proc.returncode != 0
    assert "RuntimeError" in proc.stderr
    assert "[REDACTED]" in proc.stderr


def test_uncaught_exception_in_worker_thread_is_scrubbed() -> None:
    secret = secrets.token_hex(16)
    proc = _run_child(_CHILD_THREAD, secret)
    _no_leak(secret, proc.stderr)
    assert "worker-1" in proc.stderr
    assert "RuntimeError" in proc.stderr
    assert "[REDACTED]" in proc.stderr


def test_install_global_hooks_wraps_once_and_uninstall_restores() -> None:
    original_sys = sys.excepthook
    original_thread = threading.excepthook
    redaction.install_global_hooks(Redactor.from_environ({}))
    wrapped_sys = sys.excepthook
    wrapped_thread = threading.excepthook
    assert wrapped_sys is not original_sys
    redaction.install_global_hooks(Redactor.from_environ({}))
    assert sys.excepthook is wrapped_sys
    assert threading.excepthook is wrapped_thread
    redaction.uninstall_global_hooks()
    assert sys.excepthook is original_sys
    assert threading.excepthook is original_thread


def test_httpx_and_httpcore_loggers_are_warning_or_higher() -> None:
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.NOTSET)
    configure_logging(environ={}, stream=io.StringIO())
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


def test_key_name_rule_masks_short_values_whatever_the_content() -> None:
    buffer = io.StringIO()
    configure_logging(environ={}, stream=buffer)
    log = structlog.get_logger()
    log.info(
        "login",
        api_key="short",
        password=12345,
        Authorization="Bearer x",
        client_secret="s",
        nested={"auth_token": "t", "ok": "fine"},
        symbol="BTCUSDT",
    )
    record = json.loads(buffer.getvalue().strip().splitlines()[-1])
    assert record["api_key"] == "[REDACTED]"
    assert record["password"] == "[REDACTED]"
    assert record["Authorization"] == "[REDACTED]"
    assert record["client_secret"] == "[REDACTED]"
    assert record["nested"] == {"auth_token": "[REDACTED]", "ok": "fine"}
    assert record["symbol"] == "BTCUSDT"


def test_shape_rules_mask_secrets_in_free_text() -> None:
    configure_logging(environ={}, stream=io.StringIO())
    telegram = _telegram_token()
    signature = secrets.token_hex(32)
    apikey = secrets.token_hex(32)
    aws = "AK" + "IA" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ234567") for _ in range(16))
    pem_body = secrets.token_urlsafe(48)
    pem = "-----BEGIN " + "PRIVATE KEY-----\n" + pem_body + "\n-----END " + "PRIVATE KEY-----"
    text = (
        f"GET https://api.telegram.org/bot{telegram}/getMe\n"
        f"query symbol=BTCUSDT&timestamp=1&signature={signature}\n"
        f"headers {{'X-MBX-APIKEY': '{apikey}'}}\n"
        f"aws id {aws} end\n"
        f"{pem}\ntail"
    )
    cleaned = scrub(text)
    for planted in (telegram, signature, apikey, aws, pem_body):
        _no_leak(planted, cleaned)
    assert cleaned.count("[REDACTED]") >= 5
    assert "symbol=BTCUSDT&timestamp=1" in cleaned
    assert cleaned.endswith("\ntail")


def test_ordinary_words_and_numbers_are_untouched() -> None:
    configure_logging(environ={}, stream=io.StringIO())
    text = "tick 12345678 at 10:30:45 ratio 3.14159265 http://host:8080/path BTCUSDT 1h"
    assert scrub(text) == text


def test_telegram_token_in_a_structlog_value_is_masked() -> None:
    buffer = io.StringIO()
    configure_logging(environ={}, stream=buffer)
    telegram = _telegram_token()
    structlog.get_logger().info("request", url=f"https://api.telegram.org/bot{telegram}/send")
    _no_leak(telegram, buffer.getvalue())


def test_backfill_main_calls_configure_logging_first() -> None:
    assert _main_first_statement_is_configure_logging("src/data/backfill_cli.py")


def test_redaction_module_imports_only_stdlib_and_structlog() -> None:
    tree = ast.parse((REPO_ROOT / "src/ops/redaction.py").read_text(encoding="utf-8"))
    banned = {"polars", "pandas", "numpy", "sqlalchemy", "pydantic", "httpx"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots = {node.module.split(".")[0]}
        else:
            continue
        assert not roots & banned
