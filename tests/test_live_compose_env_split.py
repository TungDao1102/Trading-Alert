"""Plans 24-30 and 24-36 (D-29, WR-06, T-02, OPS-02): which container may hold which secret.

The shared env file (`.env`, `TRADING_ENV_FILE`) no longer carries every credential. The `live`
service reads its own file (`TRADING_LIVE_ENV_FILE`, default `.env.live`) and nothing else, so the
Binance names and the live bot names reach the live container only (plan 24-30). Plan 24-36 split
the rest the same way: the SHADOW Telegram names are in the paper services' file
(`TRADING_PAPER_ENV_FILE`, default `.env.paper`) and the BACKUP_ names in the backup and ops
services' file (`TRADING_BACKUP_ENV_FILE`, default `.env.backup`), each read on top of the shared
file. The shared file carries only the names listed in `SHARED_FILE_NAMES`, and this module keeps
that list closed, so the always-on collector holds no Telegram token, no backup secret and no
Binance key.

The per-service allow-lists below are derived from the readers, not only from greps:

- collector: the `os.environ` reads of `src/data/collector.py` (AST scan, so a new read fails here);
- db-upgrade: the `os.environ` read of `src/db/alembic/env.py` (AST scan);
- paper, paper-pin: `src.paper.runtime_config.ALLOWED_ENV_NAMES`, the one set the runtime reads;
- live: the `*_VARIABLE` constants of `src/live/*.py` (AST scan) and the credential names of
  `src.adapters.binance_client.CREDENTIAL_SPECS` with their `_FILE` variants.

Everything here uses FAKE values built in a temporary directory from the tracked example files.
`.env` is never read. Assertion messages carry variable names only, never a value.
"""

from __future__ import annotations

import ast
import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from src.adapters.binance_client import CREDENTIAL_SPECS
from src.live import config as live_config
from src.paper.runtime_config import ALLOWED_ENV_NAMES, TRADE_KEY_PREFIX

from tests.infra_helpers import compose_cli_available, infra_skip

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_LIVE_EXAMPLE = REPO_ROOT / ".env.live.example"
ENV_PAPER_EXAMPLE = REPO_ROOT / ".env.paper.example"
ENV_BACKUP_EXAMPLE = REPO_ROOT / ".env.backup.example"

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_COMMENTED_ASSIGNMENT = re.compile(r"^#\s*([A-Z][A-Z0-9_]*)=(.*)$")
_SCRUBBED_ENV_PREFIXES = (
    "POSTGRES_",
    "COMPOSE_",
    "TRADING_ENV_FILE",
    "TRADING_LIVE_ENV_FILE",
    "TRADING_PAPER_ENV_FILE",
    "TRADING_BACKUP_ENV_FILE",
    "TRADING_APP_REVISION",
    "IMAGE_TAG",
    "DATABASE_URL",
)

# Set by compose itself in `environment` (x-database-env), not read from any file.
DATABASE_VALUES: frozenset[str] = frozenset({"DATABASE_URL", "POSTGRES_HOST"})

# What the shared base file (`.env.example`) delivers to every service that reads it. Since plan
# 24-36 it holds the database values, the collector cadence and the image tag only. A name added
# to `.env.example` without being added here fails
# `test_the_shared_file_example_carries_only_the_closed_list`.
SHARED_FILE_NAMES: frozenset[str] = frozenset(
    {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "DATABASE_URL",
        "OI_POLL_INTERVAL_SECONDS",
        "IMAGE_TAG",
    }
)

# The SHADOW Telegram names: the paper services' own file (`.env.paper`), nowhere else. The live
# bot has other names (`TELEGRAM_LIVE_*`), and the live process refuses the shadow token.
PAPER_FILE_NAMES: frozenset[str] = frozenset(
    {"TELEGRAM_BOT_TOKEN", "TELEGRAM_AUTHORIZED_CHAT_ID", "TELEGRAM_AUTHORIZED_USER_IDS"}
)
# The shadow names the live service must never receive (TELEGRAM_AUTHORIZED_USER_IDS is shared
# with the live file on purpose: the same owner users, set again in `.env.live`).
SHADOW_ONLY_NAMES: frozenset[str] = frozenset({"TELEGRAM_BOT_TOKEN", "TELEGRAM_AUTHORIZED_CHAT_ID"})

# The backup services' own file (`.env.backup`): every BACKUP_ name and the bundle target.
BACKUP_FILE_NAMES: frozenset[str] = frozenset(
    {
        "OFF_HOST_BACKUP_TARGET",
        "BACKUP_REMOTE",
        "BACKUP_S3_PROVIDER",
        "BACKUP_S3_ENDPOINT",
        "BACKUP_S3_REGION",
        "BACKUP_S3_BUCKET",
        "BACKUP_S3_ACCESS_KEY_ID",
        "BACKUP_S3_SECRET_ACCESS_KEY",
        "BACKUP_CRYPT_PASSWORD",
        "BACKUP_CRYPT_PASSWORD2",
    }
)

# The names the live process reads. Built from the code, then compared with the AST scan.
LIVE_READER_NAMES: frozenset[str] = frozenset(
    {
        live_config.MODE_VARIABLE,
        live_config.TELEGRAM_TOKEN_VARIABLE,
        live_config.TELEGRAM_CHAT_VARIABLE,
        live_config.TELEGRAM_USER_IDS_VARIABLE,
    }
    | {
        name
        for spec in CREDENTIAL_SPECS.values()
        for name in (
            spec.key_variable,
            spec.secret_variable,
            spec.key_variable + "_FILE",
            spec.secret_variable + "_FILE",
        )
    }
)

# Variables the collector and Alembic read, recorded from the AST scans below.
COLLECTOR_READER_NAMES: frozenset[str] = frozenset({"DATABASE_URL", "DATABASE_URL_SYNC"})
DB_UPGRADE_READER_NAMES: frozenset[str] = frozenset({"DATABASE_URL"})

ALLOWED_BY_SERVICE: dict[str, frozenset[str]] = {
    "collector": COLLECTOR_READER_NAMES | SHARED_FILE_NAMES | DATABASE_VALUES,
    "db-upgrade": DB_UPGRADE_READER_NAMES | SHARED_FILE_NAMES | DATABASE_VALUES,
    "paper": frozenset(ALLOWED_ENV_NAMES) | SHARED_FILE_NAMES | DATABASE_VALUES,
    "paper-pin": frozenset(ALLOWED_ENV_NAMES) | SHARED_FILE_NAMES | DATABASE_VALUES,
    "backup": BACKUP_FILE_NAMES | SHARED_FILE_NAMES | DATABASE_VALUES,
    "ops": BACKUP_FILE_NAMES | SHARED_FILE_NAMES | DATABASE_VALUES,
    "live": LIVE_READER_NAMES | DATABASE_VALUES,
}

# Names that may reach the live container only.
LIVE_ONLY_NAMES: frozenset[str] = LIVE_READER_NAMES - frozenset(ALLOWED_ENV_NAMES)
# The live Telegram bot names and the mode; TELEGRAM_AUTHORIZED_USER_IDS is shared with the
# paper runtime (the same owner users), so it is not live-only.
LIVE_BOT_NAMES: frozenset[str] = frozenset(
    {
        live_config.TELEGRAM_TOKEN_VARIABLE,
        live_config.TELEGRAM_CHAT_VARIABLE,
        live_config.MODE_VARIABLE,
    }
)

SERVICES_WITHOUT_TRADING_NAMES = (
    "collector",
    "db-upgrade",
    "paper",
    "paper-pin",
    "backup",
    "ops",
)


# ----------------------------------------------------------------------------- helpers


# Non-secret values compose must be able to parse (a port, an image tag); the mode is a word.
_PARSEABLE_VALUES: dict[str, str] = {
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "tradingtest",
    "IMAGE_TAG": "dev",
    "LIVE_RUNTIME_MODE": "DEMO",
}


def _fake(name: str) -> str:
    """A FAKE value that is recognisable as one and never a real credential shape."""
    if name in _PARSEABLE_VALUES:
        return _PARSEABLE_VALUES[name]
    return f"fake-{name.lower().replace('_', '-')}-{secrets.token_hex(4)}"


def _example_names(path: Path) -> tuple[list[str], list[str]]:
    """(active assignment names, commented assignment names) of an example file, in order."""
    active: list[str] = []
    commented: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := _ASSIGNMENT.match(line):
            active.append(match.group(1))
        elif match := _COMMENTED_ASSIGNMENT.match(line):
            commented.append(match.group(1))
    return active, commented


def _fake_env_file(example: Path, destination: Path) -> dict[str, str]:
    """Write `destination` with every active name of `example` set to a FAKE value."""
    values = {name: _fake(name) for name in _example_names(example)[0]}
    body = "".join(f"{name}={value}\n" for name, value in values.items())
    destination.write_text(body, encoding="utf-8", newline="\n")
    return values


def _require_compose() -> None:
    available, detail = compose_cli_available()
    if not available:
        infra_skip(f"docker compose CLI unavailable: {detail}")


def _hermetic_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_SCRUBBED_ENV_PREFIXES)
        and not k.startswith(("BACKUP_", "BINANCE_", "TELEGRAM_", "LIVE_RUNTIME_MODE"))
    }
    env["MSYS_NO_PATHCONV"] = "1"
    return env


def _render(
    tmp_path: Path, *, with_live_file: bool = True, with_split_files: bool = True
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str]]:
    """`docker compose config` of the real compose file over FAKE copies of every example.

    The returned dictionaries are the FAKE values written to the shared file and to the live file.
    The paper and backup files are written too, unless `with_split_files` is false.
    """
    _require_compose()
    project = tmp_path / f"project-{secrets.token_hex(3)}"
    project.mkdir()
    shutil.copyfile(COMPOSE_FILE, project / "docker-compose.yml")
    (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8", newline="\n")
    base_values = _fake_env_file(ENV_EXAMPLE, project / ".env")
    live_values: dict[str, str] = {}
    if with_live_file:
        live_values = _fake_env_file(ENV_LIVE_EXAMPLE, project / ".env.live")
    if with_split_files:
        _fake_env_file(ENV_PAPER_EXAMPLE, project / ".env.paper")
        _fake_env_file(ENV_BACKUP_EXAMPLE, project / ".env.backup")
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(project),
        "-f",
        str(project / "docker-compose.yml"),
    ]
    for profile in ("paper", "paper-pin", "live", "ops"):
        cmd += ["--profile", profile]
    cmd += ["config", "--format", "json"]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, check=False, env=_hermetic_env()
    )
    # stderr can echo interpolation errors but never the resolved config.
    assert proc.returncode == 0, f"compose config failed: {proc.stderr.strip()[:400]}"
    services = json.loads(proc.stdout)["services"]
    assert isinstance(services, dict)
    return services, base_values, live_values


def _environment(services: dict[str, dict[str, Any]], name: str) -> set[str]:
    environment = services[name].get("environment") or {}
    assert isinstance(environment, dict)
    return set(environment)


def _environ_reads(path: Path) -> set[str]:
    """Constant names read through `os.environ.get(...)`, `os.environ[...]` or `os.getenv(...)`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            func = ast.unparse(node.func)
            first = node.args[0]
            if (
                func in {"os.environ.get", "os.getenv", "environ.get", "env.get"}
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
            ):
                names.add(first.value)
        elif (
            isinstance(node, ast.Subscript)
            and ast.unparse(node.value) in {"os.environ", "environ", "env"}
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            names.add(node.slice.value)
    return names


def _variable_constants(path: Path) -> set[str]:
    """Module-level `SOMETHING_VARIABLE = "NAME"` string constants (the live reader names)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.endswith("_VARIABLE")
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found.add(node.value.value)
    return found


# ------------------------------------------------------------------- Task 1: the tracer


def test_compose_gives_the_binance_names_to_the_live_service_only(tmp_path: Path) -> None:
    services, base_values, live_values = _render(tmp_path)

    live = _environment(services, "live")
    assert "BINANCE_DEMO_API_KEY" in live
    assert "BINANCE_DEMO_API_SECRET" in live
    assert live_config.TELEGRAM_TOKEN_VARIABLE in live
    assert live_config.TELEGRAM_CHAT_VARIABLE in live
    assert live_config.MODE_VARIABLE in live

    for service in SERVICES_WITHOUT_TRADING_NAMES:
        names = _environment(services, service)
        binance = sorted(n for n in names if n.startswith(TRADE_KEY_PREFIX))
        assert not binance, f"{service} received BINANCE_ names: {binance}"
        bot = sorted(names & LIVE_BOT_NAMES)
        assert not bot, f"{service} received live bot names: {bot}"

    # the fake values stay recognisable as fake, so a leak into any log is obvious
    written = {**base_values, **live_values}
    assert all(v.startswith("fake-") for k, v in written.items() if k not in _PARSEABLE_VALUES)


def test_the_live_service_reads_its_own_file_and_not_the_shared_one(tmp_path: Path) -> None:
    services, _base, _live = _render(tmp_path)
    live = _environment(services, "live")
    leaked = sorted(live & (SHARED_FILE_NAMES - DATABASE_VALUES))
    assert not leaked, f"the live service received shared-file names: {leaked}"


def test_the_live_file_is_optional_so_every_compose_command_still_runs(tmp_path: Path) -> None:
    services, _base, _live = _render(tmp_path, with_live_file=False)
    assert "live" in services
    live = _environment(services, "live")
    assert not {n for n in live if n.startswith(TRADE_KEY_PREFIX)}
    assert live <= DATABASE_VALUES


def test_the_compose_file_names_the_live_env_file_variable() -> None:
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    assert text.count("TRADING_LIVE_ENV_FILE") >= 1
    assert "${TRADING_LIVE_ENV_FILE:-.env.live}" in text
    assert "required: false" in text


# ----------------------------------------------------- Task 2: the closed allow-lists


def test_allow_lists_name_each_of_the_four_services() -> None:
    assert {"collector", "db-upgrade", "paper", "live"} <= set(ALLOWED_BY_SERVICE)


@pytest.mark.parametrize("service", sorted(ALLOWED_BY_SERVICE))
def test_each_services_environment_is_inside_its_allow_list(tmp_path: Path, service: str) -> None:
    services, _base, _live = _render(tmp_path)
    extra = sorted(_environment(services, service) - ALLOWED_BY_SERVICE[service])
    assert not extra, f"{service} receives names outside its allow-list: {extra}"


def test_paper_pin_follows_the_paper_allow_list(tmp_path: Path) -> None:
    services, _base, _live = _render(tmp_path)
    assert _environment(services, "paper-pin") == _environment(services, "paper")


def test_collector_reads_exactly_the_recorded_names() -> None:
    assert _environ_reads(REPO_ROOT / "src" / "data" / "collector.py") == COLLECTOR_READER_NAMES


def test_db_upgrade_reads_exactly_the_recorded_names() -> None:
    reads = _environ_reads(REPO_ROOT / "src" / "db" / "alembic" / "env.py")
    assert reads == DB_UPGRADE_READER_NAMES


def test_paper_reads_only_its_allowed_names() -> None:
    reads = _environ_reads(REPO_ROOT / "src" / "paper" / "runtime.py")
    reads |= _environ_reads(REPO_ROOT / "src" / "paper" / "runtime_config.py")
    assert reads <= set(ALLOWED_ENV_NAMES) | {"TRADING_APP_REVISION"}, sorted(
        reads - set(ALLOWED_ENV_NAMES)
    )


def test_the_live_reader_constants_are_all_in_the_live_allow_list() -> None:
    constants: set[str] = set()
    for path in sorted((REPO_ROOT / "src" / "live").glob("*.py")):
        constants |= _variable_constants(path)
    # the shadow bot names are refused in the live environment, never read
    constants -= set(live_config.SHADOW_TELEGRAM_VARIABLES)
    constants.discard("TRADING_APP_REVISION")  # stamped into the image, not an env file name
    missing = sorted(constants - LIVE_READER_NAMES)
    assert not missing, f"a live reader was added without updating the allow-list: {missing}"


def test_the_live_runtime_reads_no_name_outside_the_allow_list() -> None:
    reads: set[str] = set()
    for path in sorted((REPO_ROOT / "src" / "live").glob("*.py")):
        reads |= _environ_reads(path)
    outside = sorted(reads - LIVE_READER_NAMES)
    assert not outside, f"the live package reads names outside its allow-list: {outside}"


def test_the_shared_file_example_carries_only_the_closed_list() -> None:
    active, commented = _example_names(ENV_EXAMPLE)
    extra = sorted(set(active) - SHARED_FILE_NAMES)
    assert not extra, f".env.example has active names outside SHARED_FILE_NAMES: {extra}"
    # no live-only name, active or commented, in the shared file
    trading = sorted(
        n for n in {*active, *commented} if n.startswith(TRADE_KEY_PREFIX) or n in LIVE_ONLY_NAMES
    )
    assert not trading, f".env.example still names live-only variables: {trading}"


def test_the_live_file_example_carries_only_the_live_allow_list() -> None:
    active, commented = _example_names(ENV_LIVE_EXAMPLE)
    outside = sorted({*active, *commented} - LIVE_READER_NAMES)
    assert not outside, f".env.live.example names variables the live process never reads: {outside}"
    assert live_config.MODE_VARIABLE in active


# --------------------------------------------- Task 3: the live example and ignore rules


def test_the_live_example_has_names_only() -> None:
    for number, line in enumerate(ENV_LIVE_EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
        match = _ASSIGNMENT.match(line) or _COMMENTED_ASSIGNMENT.match(line)
        if not match:
            continue
        name, value = match.groups()
        if name == live_config.MODE_VARIABLE:
            assert value in {"DEMO", "LIVE", ""}, f"line {number}: {name} has an odd value"
            continue
        assert value == "", f"line {number}: {name} must be an empty assignment (names only)"


def test_the_live_example_activates_one_mode_only() -> None:
    """The live process refuses to start when the OTHER mode's key name is present (even empty)."""
    active, commented = _example_names(ENV_LIVE_EXAMPLE)
    live_names = {n for n in {*active, *commented} if n.startswith("BINANCE_LIVE_")}
    demo_names = {n for n in {*active, *commented} if n.startswith("BINANCE_DEMO_")}
    assert live_names and demo_names
    assert not (set(active) & live_names), "BINANCE_LIVE_ names must be commented in the template"
    assert demo_names <= set(active)


def test_the_live_example_is_lf_and_ends_with_a_newline() -> None:
    raw = ENV_LIVE_EXAMPLE.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")


def _check_ignore(name: str) -> int:
    return subprocess.run(
        ["git", "check-ignore", "-q", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def test_the_real_live_file_is_ignored_and_its_example_is_tracked() -> None:
    assert _check_ignore(".env.live") == 0
    assert _check_ignore(".env.live.example") == 1


@pytest.mark.parametrize("name", [".env.prod", ".env.backup", ".env.paper", ".env.local"])
def test_every_other_real_env_variant_stays_ignored(name: str) -> None:
    assert _check_ignore(name) == 0


@pytest.mark.parametrize(
    "name", [".env.example", ".env.live.example", ".env.paper.example", ".env.backup.example"]
)
def test_every_env_example_is_tracked_not_ignored(name: str) -> None:
    assert _check_ignore(name) == 1


# ------------------------------------------- Plan 24-36: the paper file and the backup file


PAPER_SERVICES = ("paper", "paper-pin")
BACKUP_SERVICES = ("backup", "ops")


def test_compose_gives_the_shadow_telegram_names_to_the_paper_services_only(
    tmp_path: Path,
) -> None:
    services, _base, _live = _render(tmp_path)

    for service in PAPER_SERVICES:
        names = _environment(services, service)
        missing = sorted(PAPER_FILE_NAMES - names)
        assert not missing, f"{service} did not receive its paper-file names: {missing}"

    for service in ("collector", "db-upgrade", *BACKUP_SERVICES):
        names = _environment(services, service)
        shadow = sorted(names & PAPER_FILE_NAMES)
        assert not shadow, f"{service} received shadow Telegram names: {shadow}"
    live = _environment(services, "live")
    shadow_in_live = sorted(live & SHADOW_ONLY_NAMES)
    assert not shadow_in_live, f"live received shadow Telegram names: {shadow_in_live}"


def test_compose_gives_the_backup_names_to_the_backup_services_only(tmp_path: Path) -> None:
    services, _base, _live = _render(tmp_path)

    for service in BACKUP_SERVICES:
        names = _environment(services, service)
        missing = sorted(BACKUP_FILE_NAMES - names)
        assert not missing, f"{service} did not receive its backup-file names: {missing}"

    for service in ("collector", "db-upgrade", *PAPER_SERVICES, "live"):
        names = _environment(services, service)
        leaked = sorted(n for n in names if n.startswith("BACKUP_") or n in BACKUP_FILE_NAMES)
        assert not leaked, f"{service} received backup names: {leaked}"


def test_the_collector_holds_no_telegram_token_no_backup_secret_and_no_binance_key(
    tmp_path: Path,
) -> None:
    """WR-06 in one assertion: the internet-facing collector gets the shared names only."""
    services, _base, _live = _render(tmp_path)
    names = _environment(services, "collector")
    assert names <= COLLECTOR_READER_NAMES | SHARED_FILE_NAMES | DATABASE_VALUES, sorted(names)
    forbidden = sorted(
        n
        for n in names
        if n.startswith(("BACKUP_", "BINANCE_", "TELEGRAM_")) or n in BACKUP_FILE_NAMES
    )
    assert not forbidden, f"collector received: {forbidden}"


def test_paper_and_backup_files_are_optional_so_every_compose_command_still_runs(
    tmp_path: Path,
) -> None:
    services, _base, _live = _render(tmp_path, with_split_files=False)
    for service in PAPER_SERVICES:
        assert not (_environment(services, service) & PAPER_FILE_NAMES)
    for service in BACKUP_SERVICES:
        assert not (_environment(services, service) & BACKUP_FILE_NAMES)


def test_the_compose_file_names_the_paper_and_backup_env_file_variables() -> None:
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    assert "${TRADING_PAPER_ENV_FILE:-.env.paper}" in text
    assert "${TRADING_BACKUP_ENV_FILE:-.env.backup}" in text
    assert text.count("required: false") >= 3


def test_the_selected_paper_and_backup_files_are_the_ones_compose_reads(tmp_path: Path) -> None:
    """TRADING_PAPER_ENV_FILE and TRADING_BACKUP_ENV_FILE move the file, as the soak needs."""
    _require_compose()
    project = tmp_path / "project"
    project.mkdir()
    shutil.copyfile(COMPOSE_FILE, project / "docker-compose.yml")
    (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8", newline="\n")
    _fake_env_file(ENV_EXAMPLE, project / ".env")
    # the default-named files exist but hold no names of the example, only a marker name
    (project / ".env.paper").write_text("DEFAULT_PAPER_MARKER=x\n", encoding="utf-8", newline="\n")
    (project / ".env.backup").write_text(
        "DEFAULT_BACKUP_MARKER=x\n", encoding="utf-8", newline="\n"
    )
    other = tmp_path / "other"
    other.mkdir()
    _fake_env_file(ENV_PAPER_EXAMPLE, other / "soak-paper.env")
    _fake_env_file(ENV_BACKUP_EXAMPLE, other / "soak-backup.env")
    env = _hermetic_env()
    env["TRADING_PAPER_ENV_FILE"] = (other / "soak-paper.env").as_posix()
    env["TRADING_BACKUP_ENV_FILE"] = (other / "soak-backup.env").as_posix()
    cmd = ["docker", "compose", "--project-directory", str(project)]
    cmd += ["-f", str(project / "docker-compose.yml")]
    for profile in ("paper", "paper-pin", "ops"):
        cmd += ["--profile", profile]
    cmd += ["config", "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False, env=env)
    assert proc.returncode == 0, f"compose config failed: {proc.stderr.strip()[:400]}"
    services = json.loads(proc.stdout)["services"]
    for service in PAPER_SERVICES:
        names = _environment(services, service)
        assert PAPER_FILE_NAMES <= names and "DEFAULT_PAPER_MARKER" not in names, service
    for service in BACKUP_SERVICES:
        names = _environment(services, service)
        assert BACKUP_FILE_NAMES <= names and "DEFAULT_BACKUP_MARKER" not in names, service


def test_the_paper_file_example_carries_only_the_shadow_names() -> None:
    active, commented = _example_names(ENV_PAPER_EXAMPLE)
    assert set(active) == PAPER_FILE_NAMES
    outside = sorted({*active, *commented} - frozenset(ALLOWED_ENV_NAMES))
    assert not outside, (
        f".env.paper.example names variables the paper runtime never reads: {outside}"
    )
    assert not [n for n in {*active, *commented} if n.startswith(TRADE_KEY_PREFIX)]


def test_the_backup_file_example_carries_only_the_backup_names() -> None:
    active, commented = _example_names(ENV_BACKUP_EXAMPLE)
    assert set(active) == BACKUP_FILE_NAMES
    # a prose line such as "OFFSITE_COPY=skipped" in a comment is not a variable; the check is
    # that no moved or trading name hides in the comments either
    foreign = sorted(n for n in commented if n.startswith(("BINANCE_", "TELEGRAM_", "PAPER_")))
    assert not foreign, f".env.backup.example comments name foreign variables: {foreign}"


def test_the_shared_example_has_no_telegram_or_backup_name_at_all() -> None:
    active, commented = _example_names(ENV_EXAMPLE)
    moved = sorted(
        n
        for n in {*active, *commented}
        if n.startswith(("BACKUP_", "TELEGRAM_", "PAPER_")) or n in BACKUP_FILE_NAMES
    )
    assert not moved, f".env.example still names moved variables: {moved}"


@pytest.mark.parametrize("example", [ENV_PAPER_EXAMPLE, ENV_BACKUP_EXAMPLE], ids=lambda p: p.name)
def test_the_split_examples_have_names_only_and_are_lf(example: Path) -> None:
    for number, line in enumerate(example.read_text(encoding="utf-8").splitlines(), 1):
        match = _ASSIGNMENT.match(line) or _COMMENTED_ASSIGNMENT.match(line)
        if not match:
            continue
        name, value = match.groups()
        if name == "OFF_HOST_BACKUP_TARGET":
            assert value == "data/backup", f"line {number}: {name} keeps its default path"
            continue
        assert value == "", f"line {number}: {name} must be an empty assignment (names only)"
    raw = example.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")


def test_every_moved_name_is_in_exactly_one_example() -> None:
    examples = {
        "shared": ENV_EXAMPLE,
        "live": ENV_LIVE_EXAMPLE,
        "paper": ENV_PAPER_EXAMPLE,
        "backup": ENV_BACKUP_EXAMPLE,
    }
    active = {label: set(_example_names(path)[0]) for label, path in examples.items()}
    for name in sorted(BACKUP_FILE_NAMES | SHADOW_ONLY_NAMES):
        homes = sorted(label for label, names in active.items() if name in names)
        assert len(homes) == 1, f"{name} is active in {homes}"
