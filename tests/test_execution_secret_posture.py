"""Source-level secret posture at the exchange-facing boundary (Phase 9, OPS-02).

Plan 09-04 states the prohibition explicitly: the live execution path
"MUST NOT log API keys, signatures, raw approval tokens, or whole SDK
responses at any log site", and credentials must live off-source (env /
secret store) — never in project code.

`tests/test_execution_enablement.py::test_secret_free_log_scan_across_enablement_and_health_events`
covers the *runtime* side (emitted records carry no secret substrings).
This suite covers the *source* side over the modules that actually touch
exchange credentials and SDK payloads:

  1. No credential-shaped string literal is assigned in any target module
     (mirrors `tests/test_backup.py::test_backup_module_has_no_secret_literal`).
  2. Every log site in the target modules passes only a literal event name
     plus scalar, non-credential keyword fields — no SDK response object,
     no credential-bearing field name.
  3. The Binance SDK client is constructed with no project-held key
     material, and no target module reads credentials out of the
     environment itself, so keys can only arrive via the SDK's own
     env-based configuration (off-source storage).

Per review finding WR-12, every target path is resolved against the
repository root and a missing target FAILS the test — never skips.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The exchange-facing / ops surface where credential risk actually lives.
TARGET_RELPATHS: tuple[str, ...] = (
    "src/adapters/binance_usdm.py",
    "src/ops/health.py",
    "src/execution/__init__.py",
    "src/execution/binding.py",
    "src/execution/emergency_close.py",
    "src/execution/enablement.py",
    "src/execution/execution_limits.py",
    "src/execution/fill_monitor.py",
    "src/execution/gates.py",
    "src/execution/live_context.py",
    "src/execution/lot_split.py",
    "src/execution/manager.py",
    "src/execution/order_ids.py",
    "src/execution/placement.py",
    "src/execution/pre_placement.py",
    "src/execution/protection.py",
    "src/execution/tp_sizing.py",
)

# Names that, if bound to a string literal in project code, mean a
# credential was checked into the repo.
CREDENTIAL_NAME_FRAGMENTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "api_secret",
    "secret_key",
    "secretkey",
    "private_key",
    "access_token",
    "bot_token",
    "auth_token",
    "bearer",
    "password",
    "passwd",
    "signature",
    "hmac_key",
)

# Backup-test precedent: raw literal shapes that betray a pasted secret.
SECRET_LITERAL_PATTERNS: tuple[str, ...] = (
    "api_key =",
    "API_KEY=",
    "api_secret =",
    "API_SECRET=",
    "AKIA",
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN OPENSSH PRIVATE KEY",
)

# Keyword field names forbidden at any log site: credential-bearing, or a
# whole SDK payload dumped into the record.
FORBIDDEN_LOG_FIELDS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "signature",
    "token",
    "password",
    "credentials",
    "authorization",
    "response",
    "raw_response",
    "raw",
    "payload",
    "body",
    "sdk_response",
    "data",
)

LOGGER_ROOTS = frozenset({"log", "logger", "logging", "structlog", "_log", "_logger"})
LOG_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "msg", "log"}
)


def _resolve(relpath: str) -> Path:
    """Resolve a target against the repo root; a missing target FAILS."""
    path = REPO_ROOT / relpath
    assert path.is_file(), f"secret-posture target missing from repo: {path}"
    return path


def _targets() -> list[tuple[str, Path, str]]:
    """Every target as (relpath, path, source); fails if any is absent."""
    assert TARGET_RELPATHS, "no secret-posture targets configured"
    out: list[tuple[str, Path, str]] = []
    for relpath in TARGET_RELPATHS:
        path = _resolve(relpath)
        out.append((relpath, path, path.read_text(encoding="utf-8")))
    return out


# --------------------------------------------------------------------------- #
# 1 — no credential literal anywhere in the exchange-facing modules.
# --------------------------------------------------------------------------- #


def test_exchange_facing_modules_hold_no_secret_literal() -> None:
    """OPS-02: no credential-shaped literal is present in project code."""
    for relpath, path, source in _targets():
        for pat in SECRET_LITERAL_PATTERNS:
            assert pat not in source, f"{relpath} contains secret-like literal: {pat!r}"

        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(
                node.value.value, (str, bytes)
            ):
                continue
            for target in targets:
                name = ast.unparse(target).lower()
                for fragment in CREDENTIAL_NAME_FRAGMENTS:
                    assert fragment not in name, (
                        f"{relpath}:{node.lineno} binds credential-shaped name "
                        f"{ast.unparse(target)!r} to a string literal"
                    )


# --------------------------------------------------------------------------- #
# 2 — no log site emits a credential field or a whole SDK response.
# --------------------------------------------------------------------------- #


def _log_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in LOG_METHODS:
            continue
        root = node.func.value
        if isinstance(root, ast.Name) and root.id in LOGGER_ROOTS:
            calls.append(node)
        elif isinstance(root, ast.Attribute) and root.attr in LOGGER_ROOTS:
            calls.append(node)
    return calls


def test_no_log_site_emits_credentials_or_whole_sdk_responses() -> None:
    """Plan 09-04: every log site carries a literal event name plus
    scalar non-credential fields only."""
    scanned = 0
    for relpath, path, source in _targets():
        tree = ast.parse(source, filename=str(path))
        for call in _log_calls(tree):
            scanned += 1
            # Positional arguments: only the literal event name is allowed,
            # so no object (SDK response included) can be rendered into the
            # record by repr.
            for index, arg in enumerate(call.args):
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                    f"{relpath}:{call.lineno} log site passes non-literal positional "
                    f"arg #{index}: {ast.unparse(arg)!r}"
                )
            for keyword in call.keywords:
                assert keyword.arg is not None, (
                    f"{relpath}:{call.lineno} log site splats **kwargs, so its "
                    f"field set is unverifiable: {ast.unparse(keyword)!r}"
                )
                field = keyword.arg.lower()
                for forbidden in FORBIDDEN_LOG_FIELDS:
                    assert forbidden not in field, (
                        f"{relpath}:{call.lineno} log site emits forbidden field "
                        f"{keyword.arg!r} (matched {forbidden!r})"
                    )
    # Guard the guard: if the scan finds nothing, the AST shape drifted and
    # this test would pass vacuously.
    assert scanned > 0, "no log sites found in target modules; scan shape has drifted"


# --------------------------------------------------------------------------- #
# 3 — credentials are never sourced from project code.
# --------------------------------------------------------------------------- #


def test_sdk_client_is_constructed_without_project_held_key_material() -> None:
    """OPS-02: `DerivativesTradingUsdsFutures()` takes no project-supplied
    credentials, so keys can only come from the SDK's own environment
    configuration (off-source storage)."""
    relpath = "src/adapters/binance_usdm.py"
    path = _resolve(relpath)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    constructions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DerivativesTradingUsdsFutures"
    ]
    assert constructions, f"{relpath} no longer constructs DerivativesTradingUsdsFutures"
    for call in constructions:
        assert not call.args and not call.keywords, (
            f"{relpath}:{call.lineno} passes arguments to the SDK client "
            f"({ast.unparse(call)!r}); credentials must come from the environment"
        )


def test_no_target_module_reads_credentials_from_the_environment_itself() -> None:
    """OPS-02: no target module reads key material out of os.environ /
    os.getenv — credential handling stays outside project code."""
    for relpath, path, source in _targets():
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            rendered = ast.unparse(node.func)
            if rendered not in {"os.getenv", "getenv", "os.environ.get"}:
                continue
            literal = " ".join(
                arg.value.lower()
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
            for fragment in CREDENTIAL_NAME_FRAGMENTS:
                assert fragment not in literal, (
                    f"{relpath}:{node.lineno} reads credential-shaped env var "
                    f"{literal!r} inside project code"
                )
        for subscript in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ"
        ):
            key = ast.unparse(subscript.slice).lower()
            for fragment in CREDENTIAL_NAME_FRAGMENTS:
                assert fragment not in key, (
                    f"{relpath}:{subscript.lineno} reads credential-shaped env var "
                    f"{key!r} inside project code"
                )
