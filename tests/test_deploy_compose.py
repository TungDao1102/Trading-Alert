"""Compose stack checks via ``docker compose config --format json`` (13.1-03).

Needs the Docker CLI with the compose plugin but never a daemon. The compose file is copied into
a temporary project directory together with a ``.env`` holding only the four POSTGRES_*
variables (random hex values), so the checks are hermetic and prove that no backup or live
variable is needed at interpolation time (research findings 6 and 7). The resolved config
contains secrets, so assertion messages never print it.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.infra_helpers import compose_cli_available, infra_skip

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

HEALTH_PROBE = ["/app/.venv/bin/python", "-m", "src.data.collector", "--healthcheck"]
PAPER_PROBE = ["CMD", "/app/.venv/bin/python", "-m", "src.paper.runtime", "--healthcheck"]
BASE_VARS = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT")
_SCRUBBED_ENV_PREFIXES = (
    "POSTGRES_",
    "COMPOSE_",
    "TRADING_ENV_FILE",
    "TRADING_APP_REVISION",
    "IMAGE_TAG",
    "DATABASE_URL",
)


def _require_compose() -> None:
    available, detail = compose_cli_available()
    if not available:
        infra_skip(f"docker compose CLI unavailable: {detail}")


def _write_project(tmp_path: Path, overrides: dict[str, str] | None = None) -> Path:
    # Unique per call: one test may render several projects (different profiles or env).
    project = tmp_path / f"project-{secrets.token_hex(3)}"
    project.mkdir()
    shutil.copyfile(COMPOSE_FILE, project / "docker-compose.yml")
    # The build context only has to exist for `config`; its content is irrelevant here.
    (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8", newline="\n")
    values = {
        "POSTGRES_USER": "u" + secrets.token_hex(4),
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "POSTGRES_DB": "tradingtest",
        "POSTGRES_PORT": "5432",
    }
    values.update(overrides or {})
    body = "".join(f"{k}={v}\n" for k, v in values.items() if v != "")
    (project / ".env").write_text(body, encoding="utf-8", newline="\n")
    return project


def _hermetic_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_SCRUBBED_ENV_PREFIXES) and not k.startswith("BACKUP_")
    }
    env["MSYS_NO_PATHCONV"] = "1"
    return env


def _run_config(project: Path, profiles: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(project),
        "-f",
        str(project / "docker-compose.yml"),
    ]
    for profile in profiles:
        cmd += ["--profile", profile]
    cmd += ["config", "--format", "json"]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=_hermetic_env(),
    )


def compose_config(
    tmp_path: Path,
    profiles: tuple[str, ...] = (),
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    _require_compose()
    project = _write_project(tmp_path, overrides)
    proc = _run_config(project, profiles)
    # stderr can echo interpolation errors but never the resolved config.
    assert proc.returncode == 0, f"compose config failed: {proc.stderr.strip()[:400]}"
    parsed = json.loads(proc.stdout)
    assert isinstance(parsed, dict)
    return parsed


def _services(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    services = config["services"]
    assert isinstance(services, dict)
    return services


def test_project_is_named_trading(tmp_path: Path) -> None:
    config = compose_config(tmp_path)
    assert config["name"] == "trading"


def test_default_services_are_exactly_postgres_db_upgrade_collector(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path))
    assert set(services) == {"postgres", "db-upgrade", "collector"}


def test_postgres_publishes_loopback_only(tmp_path: Path) -> None:
    postgres = _services(compose_config(tmp_path))["postgres"]
    ports = postgres["ports"]
    assert len(ports) == 1
    assert ports[0]["host_ip"] == "127.0.0.1"
    assert int(ports[0]["target"]) == 5432
    assert int(ports[0]["published"]) == 5432


def test_only_postgres_publishes_ports(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("paper", "live", "ops")))
    published = {name for name, svc in services.items() if svc.get("ports")}
    assert published == {"postgres"}


def test_non_default_postgres_port_changes_only_the_host_side(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, overrides={"POSTGRES_PORT": "5433"}))
    port = services["postgres"]["ports"][0]
    assert port["host_ip"] == "127.0.0.1"
    assert int(port["published"]) == 5433
    assert int(port["target"]) == 5432
    for name in ("db-upgrade", "collector"):
        url = services[name]["environment"]["DATABASE_URL"]
        assert "@postgres:5432/" in url, f"{name} must dial the in-network port"
        assert "@postgres:5433" not in url
        assert url.startswith("postgresql+psycopg://")
        assert services[name]["environment"]["POSTGRES_HOST"] == "postgres"


def test_database_url_uses_the_database_name_from_env(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, overrides={"POSTGRES_DB": "alt_db"}))
    assert services["collector"]["environment"]["DATABASE_URL"].endswith("@postgres:5432/alt_db")


def test_no_container_name_anywhere(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("paper", "live", "ops")))
    offenders = [name for name, svc in services.items() if "container_name" in svc]
    assert offenders == []


def test_all_volume_mounts_are_named_volumes_never_binds(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("paper", "live", "ops")))
    seen: set[str] = set()
    for svc in services.values():
        for mount in svc.get("volumes", []):
            assert mount["type"] == "volume", mount.get("target")
            seen.add(mount["source"])
    assert seen <= {"pgdata", "rawdata", "backupdata", "logs"}
    assert {"pgdata", "rawdata", "logs"} <= seen


def test_declared_volumes_are_only_the_four_named_volumes(tmp_path: Path) -> None:
    # `config` drops volumes no enabled service uses, so the default stack shows three and
    # the ops profile (backup, ops) brings in backupdata.
    declared = set(compose_config(tmp_path)["volumes"])
    assert declared == {"pgdata", "rawdata", "logs"}
    all_declared = set(compose_config(tmp_path, profiles=("paper", "live", "ops"))["volumes"])
    assert all_declared == {"pgdata", "rawdata", "backupdata", "logs"}


def test_collector_healthcheck_is_the_exec_form_venv_probe(tmp_path: Path) -> None:
    collector = _services(compose_config(tmp_path))["collector"]
    health = collector["healthcheck"]
    assert health["test"] == ["CMD", *HEALTH_PROBE]
    assert collector["command"] == ["/app/.venv/bin/python", "-m", "src.data.collector"]


def test_postgres_healthcheck_is_pg_isready(tmp_path: Path) -> None:
    health = _services(compose_config(tmp_path))["postgres"]["healthcheck"]
    assert "pg_isready" in " ".join(health["test"])


def test_db_upgrade_is_a_one_shot_migration_without_a_probe(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path))
    upgrade = services["db-upgrade"]
    assert upgrade["command"] == ["/app/.venv/bin/alembic", "upgrade", "head"]
    assert upgrade["restart"] == "no"
    assert upgrade["healthcheck"] == {"disable": True}
    assert upgrade["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["collector"]["depends_on"]["db-upgrade"]["condition"] == (
        "service_completed_successfully"
    )


def test_collector_mounts_raw_data_and_logs_but_not_backups(tmp_path: Path) -> None:
    collector = _services(compose_config(tmp_path))["collector"]
    targets = {m["target"]: m["source"] for m in collector["volumes"]}
    assert targets == {"/app/data/raw": "rawdata", "/app/logs": "logs"}


def test_images_are_pinned_by_digest_or_local_tag(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path))
    assert services["postgres"]["image"].startswith("postgres:17.11-bookworm@sha256:")
    assert services["collector"]["image"] == "trading-alert:dev"
    assert services["db-upgrade"]["image"] == "trading-alert:dev"
    # Exactly one of the two app services owns the build (no N parallel builds).
    builders = [n for n in ("db-upgrade", "collector") if "build" in services[n]]
    assert builders == ["db-upgrade"]
    assert services["db-upgrade"]["build"]["target"] == "runtime"


REVISION_STAMP = "0123456789abcdef0123456789abcdef01234567"


def test_building_services_pass_the_revision_as_a_build_argument(tmp_path: Path) -> None:
    """OPS-04, D-31, Q13: the stamp reaches the Dockerfile ARG from the environment."""
    config = compose_config(
        tmp_path, profiles=("ops",), overrides={"TRADING_APP_REVISION": REVISION_STAMP}
    )
    services = _services(config)
    builders = [name for name, svc in services.items() if "build" in svc]
    assert sorted(builders) == ["backup", "db-upgrade"]
    for name in builders:
        assert services[name]["build"]["args"] == {"TRADING_APP_REVISION": REVISION_STAMP}


def test_the_revision_build_argument_is_empty_when_unset(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("ops",)))
    for name in ("db-upgrade", "backup"):
        value = services[name]["build"]["args"]["TRADING_APP_REVISION"]
        assert value in ("", None), name


def test_missing_postgres_credentials_fail_config(tmp_path: Path) -> None:
    _require_compose()
    project = _write_project(tmp_path, overrides={"POSTGRES_PASSWORD": ""})
    proc = _run_config(project)
    assert proc.returncode != 0
    assert "POSTGRES_PASSWORD" in proc.stderr


DEFAULT = {"postgres", "db-upgrade", "collector"}


@pytest.mark.parametrize(
    ("profiles", "extra"),
    [
        ((), set()),
        (("paper",), {"paper"}),
        (("live",), {"live"}),
        (("ops",), {"backup", "ops"}),
        (("paper", "live", "ops"), {"paper", "live", "backup", "ops"}),
    ],
)
def test_profiles_add_exactly_their_services(
    tmp_path: Path, profiles: tuple[str, ...], extra: set[str]
) -> None:
    services = _services(compose_config(tmp_path, profiles=profiles))
    assert set(services) == DEFAULT | extra


@pytest.mark.parametrize(("service", "phase"), [("live", "Phase 24")])
def test_placeholders_fail_fast_naming_the_owning_phase(
    tmp_path: Path, service: str, phase: str
) -> None:
    svc = _services(compose_config(tmp_path, profiles=(service,)))[service]
    assert svc["restart"] == "no"
    assert svc["healthcheck"] == {"disable": True}
    command = svc["command"]
    assert command[0] == "/app/.venv/bin/python"
    assert any("SystemExit" in part and phase in part for part in command)
    assert "src.data.collector" not in " ".join(command)


def test_backup_service_runs_the_scheduled_cli_from_the_ops_image(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("ops",)))
    backup = services["backup"]
    assert backup["command"] == ["/app/.venv/bin/python", "-m", "src.ops.backup", "scheduled"]
    assert backup["image"] == "trading-alert-ops:dev"
    assert backup["build"]["target"] == "ops"
    assert backup["restart"] == "no"
    assert backup["healthcheck"] == {"disable": True}
    assert backup["depends_on"]["postgres"]["condition"] == "service_healthy"
    mounts = {m["target"]: m for m in backup["volumes"]}
    assert set(mounts) == {"/app/data/raw", "/app/data/backup"}
    assert mounts["/app/data/raw"]["source"] == "rawdata"
    assert mounts["/app/data/raw"].get("read_only") is True
    assert mounts["/app/data/backup"]["source"] == "backupdata"
    assert not mounts["/app/data/backup"].get("read_only")
    env = backup["environment"]
    assert "@postgres:5432/" in env["DATABASE_URL"]


def test_ops_service_is_a_toolbox_on_the_ops_image(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("ops",)))
    ops = services["ops"]
    assert ops["image"] == "trading-alert-ops:dev"
    # Exactly one service owns the ops build.
    assert "build" not in ops
    assert ops["restart"] == "no"
    assert ops["healthcheck"] == {"disable": True}
    mounts = {m["target"]: m["source"] for m in ops["volumes"]}
    assert mounts == {
        "/app/data/raw": "rawdata",
        "/app/data/backup": "backupdata",
        "/app/logs": "logs",
    }
    assert ops["command"][:3] == ["/app/.venv/bin/python", "-m", "src.ops.backup"]
    assert "@postgres:5432/" in ops["environment"]["DATABASE_URL"]


def test_every_service_rotates_json_logs(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("paper", "live", "ops")))
    for name, svc in services.items():
        logging = svc["logging"]
        assert logging["driver"] == "json-file", name
        assert logging["options"]["max-size"], name
        assert logging["options"]["max-file"], name


def test_every_app_service_has_init_and_a_stop_grace_period(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("paper", "live", "ops")))
    for name, svc in services.items():
        if name == "postgres":
            continue
        assert svc["init"] is True, name
        assert svc["stop_grace_period"] == "30s", name


def test_every_service_has_its_own_healthcheck_decision(tmp_path: Path) -> None:
    services = _services(compose_config(tmp_path, profiles=("paper", "live", "ops")))
    for name, svc in services.items():
        assert "healthcheck" in svc, f"{name} must state a healthcheck decision explicitly"
    # The paper service is no longer a placeholder: it carries the runtime's own probe (16-32).
    assert services["paper"]["healthcheck"]["test"] == PAPER_PROBE


def test_profile_services_need_no_backup_or_live_variables(tmp_path: Path) -> None:
    # Only the four POSTGRES_* variables are present in the temp .env; interpolation of
    # profile-gated services must not require anything else (research finding 6).
    config = compose_config(tmp_path, profiles=("paper", "live", "ops"))
    assert set(config["services"]) == DEFAULT | {"paper", "live", "backup", "ops"}
