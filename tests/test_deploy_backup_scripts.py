"""Behavioural tests for the Linux backup, restore, drill and update wrappers (13.1-10).

The real scripts run under Git Bash (Windows) or bash (Linux CI). ``docker``, ``systemctl`` and
``git`` are stubs first on PATH that append their argv to a log (the docker stub also models
image tags in a state directory), so the tests assert ordering, flag forwarding, exit-code
propagation and the rollback identity check (D-12, D-13, D-16) without any container.

The wrappers hold no backup logic: every decision lives in ``python -m src.ops.backup``. The
proof with real containers is ``tests/test_docker_backup_drill.py``.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = REPO_ROOT / "deploy"
UNITS = DEPLOY / "systemd"

PY = "/app/.venv/bin/python"
OPS = "--profile ops run --rm -T"

OLD_APP = "sha256:" + "a" * 64
OLD_OPS = "sha256:" + "b" * 64
NEW_APP = "sha256:" + "c" * 64
NEW_OPS = "sha256:" + "d" * 64
OLD_SHA = "1" * 40
REF_SHA = "2" * 40

_LOG = r"""
printf '%s\n' "${0##*/} $*" >> "${STUB_LOG:?}"
state="${STUB_STATE:?}"
mkdir -p "$state/img"
"""

STUBS: dict[str, str] = {
    "docker": r"""
img() { printf '%s' "$state/img/${1//[:\/]/_}"; }
if [ "$1" = image ] && [ "$2" = inspect ]; then
  f="$(img "${@: -1}")"
  if [ -f "$f" ]; then cat "$f"; exit 0; fi
  exit 1
fi
if [ "$1" = tag ]; then
  cp "$(img "$2")" "$(img "$3")"
  exit 0
fi
case "$*" in
  *"src.ops.backup scheduled"*) exit "${STUB_BACKUP_RC:-0}" ;;
  *"src.ops.backup backup"*) exit "${STUB_BUNDLE_RC:-0}" ;;
  *"src.ops.backup pull"*) exit "${STUB_PULL_RC:-0}" ;;
  *"src.ops.backup restore"*) exit "${STUB_RESTORE_RC:-0}" ;;
  *"src.ops.backup drill-remote"*) exit "${STUB_DRILL_RC:-0}" ;;
  *" up -d"*) exit "${STUB_UP_RC:-0}" ;;
  *" build") # a build moves the active tags to new images
    printf '%s' "${STUB_NEW_APP:?}" > "$(img trading-alert:dev)"
    printf '%s' "${STUB_NEW_OPS:?}" > "$(img trading-alert-ops:dev)"
    exit "${STUB_BUILD_RC:-0}" ;;
esac
exit 0
""",
    "systemctl": "exit 0\n",
    "git": r"""
head="$state/head"
case "$1" in
  status) printf '%s' "${STUB_GIT_DIRTY:-}"; exit 0 ;;
  rev-parse)
    if [ "$2" = --verify ]; then
      [ -z "${STUB_REF_UNRESOLVED:-}" ] || exit 1
      ref="${@: -1}"
      ref="${ref%'^{commit}'}"
      if [[ $ref =~ ^[0-9a-f]{40}$ ]]; then printf '%s\n' "$ref"
      else printf '%s\n' "${STUB_REF_SHA:?}"; fi
      exit 0
    fi
    cat "$head"; exit 0 ;;
  checkout)
    target="${@: -1}"
    if [[ $target =~ ^[0-9a-f]{40}$ ]]; then printf '%s\n' "$target" > "$head"
    else printf '%s\n' "${STUB_REF_SHA:?}" > "$head"; fi
    exit 0 ;;
esac
exit 0
""",
}

DRIVER = """\
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
export PATH="$here/bin:$PATH"
script="$1"
shift
exec bash "$script" "$@"
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    if text.startswith("#!"):
        path.chmod(0o755)  # stubs must be executable on Linux; Git Bash ignores the bit
    return path


@dataclass
class Rig:
    base: Path
    bash: str

    @property
    def log(self) -> Path:
        return self.base / "stub.log"

    @property
    def state(self) -> Path:
        return self.base / "state"

    @property
    def prefix(self) -> Path:
        return self.base / "root"

    @property
    def deploy_state(self) -> Path:
        return self.base / "deploy-state"

    def lines(self) -> list[str]:
        if not self.log.exists():
            return []
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def docker_lines(self) -> list[str]:
        return [ln for ln in self.lines() if ln.startswith("docker ")]

    def set_image(self, tag: str, image_id: str) -> None:
        _write(self.state / "img" / tag.replace(":", "_").replace("/", "_"), image_id)

    def image(self, tag: str) -> str:
        path = self.state / "img" / tag.replace(":", "_").replace("/", "_")
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def head(self) -> str:
        return (self.state / "head").read_text(encoding="utf-8").strip()

    def run(
        self, script: str, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        full_env = dict(os.environ)
        full_env.update(
            {
                "MSYS_NO_PATHCONV": "1",
                "STUB_LOG": (self.base / "stub.log").as_posix(),
                "STUB_STATE": self.state.as_posix(),
                "STUB_NEW_APP": NEW_APP,
                "STUB_NEW_OPS": NEW_OPS,
                "STUB_REF_SHA": REF_SHA,
                "TRADING_ROOT_PREFIX": self.prefix.as_posix(),
                "TRADING_DEPLOY_STATE_DIR": self.deploy_state.as_posix(),
            }
        )
        full_env.pop("TRADING_ENV_FILE", None)
        full_env.pop("COMPOSE_PROJECT_NAME", None)
        full_env.update(env or {})
        return subprocess.run(
            [self.bash, (self.base / "driver.sh").as_posix(), (DEPLOY / script).as_posix(), *args],
            capture_output=True,
            text=True,
            env=full_env,
            check=False,
            timeout=120,
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; the wrapper tests need Git Bash or Linux bash")
    base = tmp_path / "rig"
    for name, body in STUBS.items():
        _write(base / "bin" / name, "#!/usr/bin/env bash\n" + _LOG + body)
    _write(base / "driver.sh", DRIVER)
    made = Rig(base=base, bash=bash)
    _write(made.state / "head", OLD_SHA + "\n")
    made.set_image("trading-alert:dev", OLD_APP)
    made.set_image("trading-alert-ops:dev", OLD_OPS)
    return made


def _strip_comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _index(lines: list[str], *needles: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if all(n in lines[i] for n in needles):
            return i
    raise AssertionError(f"no log line from {start} containing {needles}:\n" + "\n".join(lines))


# --- backup.sh -------------------------------------------------------------------------------


def test_backup_runs_the_scheduled_subcommand_in_the_backup_service(rig: Rig) -> None:
    proc = rig.run("backup.sh")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = rig.docker_lines()
    assert len(calls) == 1, calls
    assert f"{OPS} backup {PY} -m src.ops.backup scheduled" in calls[0]


def test_backup_propagates_the_python_exit_code(rig: Rig) -> None:
    proc = rig.run("backup.sh", env={"STUB_BACKUP_RC": "7"})
    assert proc.returncode == 7, proc.stdout + proc.stderr


def test_backup_uses_the_env_file_and_project_from_the_environment(
    rig: Rig, tmp_path: Path
) -> None:
    env_file = tmp_path / "x.env"
    proc = rig.run(
        "backup.sh",
        env={"TRADING_ENV_FILE": env_file.as_posix(), "COMPOSE_PROJECT_NAME": "t131-proj"},
    )
    assert proc.returncode == 0, proc.stderr
    (call,) = rig.docker_lines()
    assert f"--env-file {env_file.as_posix()}" in call
    assert call.index("--env-file") < call.index("--profile")


def _remote_env(rig: Rig, text: str = "BACKUP_S3_BUCKET=b\n") -> dict[str, str]:
    """TRADING_ENV_FILE pointing at a test env file (never the checkout's own .env)."""
    path = _write(rig.base / "backup.env", text)
    return {"TRADING_ENV_FILE": path.as_posix()}


def test_init_remote_makes_a_bundle_then_creates_the_sentinel(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--init-remote", env=_remote_env(rig))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = rig.docker_lines()
    assert len(calls) == 2, calls
    assert f"{PY} -m src.ops.backup backup --bundle-root data/backup/bundle" in calls[0]
    assert f"{PY} -m src.ops.backup push --init-remote" in calls[1]
    assert "scheduled" not in " ".join(calls)


def test_init_remote_does_not_push_when_the_bundle_backup_fails(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--init-remote", env={**_remote_env(rig), "STUB_BUNDLE_RC": "5"})
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert len(rig.docker_lines()) == 1


def test_dry_run_prints_the_command_and_executes_nothing(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert rig.lines() == []
    assert "src.ops.backup scheduled" in proc.stdout


@pytest.mark.parametrize("script", ["backup.sh", "restore.sh", "backup-drill.sh", "update.sh"])
def test_unknown_flag_exits_two(rig: Rig, script: str) -> None:
    proc = rig.run(script, "--definitely-not-a-flag")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert rig.lines() == []


def test_init_remote_and_install_timer_are_mutually_exclusive(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--init-remote", "--install-timer")
    assert proc.returncode == 2, proc.stderr
    assert rig.lines() == []


def _checkout_as_bash_sees_it(rig: Rig) -> str:
    out = subprocess.run(
        [rig.bash, "-c", 'cd "$1" && pwd', "_", REPO_ROOT.as_posix()],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_install_timer_writes_both_units_and_enables_the_timer(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--install-timer")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    unit_dir = rig.prefix / "etc" / "systemd" / "system"
    service = (unit_dir / "trading-backup.service").read_text(encoding="utf-8")
    timer = (unit_dir / "trading-backup.timer").read_text(encoding="utf-8")
    checkout = _checkout_as_bash_sees_it(rig)
    for text in (service, timer):
        assert "@" not in text.replace("@@", ""), "a substitution token was left behind"
    assert f"WorkingDirectory={checkout}" in service
    assert f"ExecStart=/usr/bin/env bash {checkout}/deploy/backup.sh" in service
    assert "Persistent=true" in timer
    calls = [ln for ln in rig.lines() if ln.startswith("systemctl ")]
    assert calls == [
        "systemctl daemon-reload",
        "systemctl enable --now trading-backup.timer",
    ]
    assert rig.docker_lines() == []


def test_install_timer_twice_writes_nothing_the_second_time(rig: Rig) -> None:
    first = rig.run("backup.sh", "--install-timer")
    assert first.returncode == 0, first.stderr
    assert first.stdout.count("+ write ") == 2
    second = rig.run("backup.sh", "--install-timer")
    assert second.returncode == 0, second.stderr
    assert "+ write " not in second.stdout
    assert "daemon-reload" not in second.stdout


def test_install_timer_dry_run_changes_nothing(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--install-timer", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert not (rig.prefix / "etc").exists()
    assert rig.lines() == []
    assert "+ write " in proc.stdout


# --- the unit files ----------------------------------------------------------------------------


def test_timer_is_daily_at_0315_utc_persistent_and_randomised() -> None:
    timer = (UNITS / "trading-backup.timer").read_text(encoding="utf-8")
    assert re.search(r"^OnCalendar=\*-\*-\* 03:15:00 UTC$", timer, re.MULTILINE)
    assert re.search(r"^Persistent=true$", timer, re.MULTILINE)
    assert re.search(r"^RandomizedDelaySec=5m$", timer, re.MULTILINE)
    assert re.search(r"^WantedBy=timers.target$", timer, re.MULTILINE)


def test_service_is_a_oneshot_that_runs_the_wrapper_as_the_trading_user() -> None:
    service = (UNITS / "trading-backup.service").read_text(encoding="utf-8")
    assert re.search(r"^Type=oneshot$", service, re.MULTILINE)
    assert re.search(r"^User=trading$", service, re.MULTILINE)
    assert re.search(r"^WorkingDirectory=@TRADING_DIR@$", service, re.MULTILINE)
    assert re.search(
        r"^ExecStart=/usr/bin/env bash @TRADING_DIR@/deploy/backup\.sh$", service, re.M
    )
    assert "docker.service" in service


# --- thin wrappers -----------------------------------------------------------------------------

FORBIDDEN = ("pg_dump", "pg_restore", "psql", "rclone", "restic", "gpg", "openssl", "age ")


@pytest.mark.parametrize("name", ["backup.sh", "restore.sh", "backup-drill.sh"])
def test_wrappers_never_call_dump_restore_or_remote_tools_directly(name: str) -> None:
    path = DEPLOY / name
    assert path.exists(), f"{name} is missing"
    code = _strip_comments(path.read_text(encoding="utf-8"))
    for word in FORBIDDEN:
        assert word not in code, f"{name} mentions {word!r} outside a comment"
    assert "src.ops.backup" in code


# --- restore.sh --------------------------------------------------------------------------------

STAMP = r"[0-9]{8}T[0-9]{6}Z"


def test_restore_runs_postgres_pull_restore_and_then_the_stack_in_order(rig: Rig) -> None:
    proc = rig.run("restore.sh")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = rig.docker_lines()
    assert len(calls) == 4, calls
    assert "up -d --wait" in calls[0] and calls[0].endswith(" postgres")
    pull = re.search(rf"src\.ops\.backup pull --dest (data/backup/restore-{STAMP})$", calls[1])
    assert pull, calls[1]
    assert f"{OPS} --no-deps ops {PY} -m src.ops.backup pull" in calls[1]
    restore = re.search(
        rf"src\.ops\.backup restore --bundle-root (data/backup/restore-{STAMP}) "
        r"--parquet-target data/raw$",
        calls[2],
    )
    assert restore, calls[2]
    assert restore.group(1) == pull.group(1), "restore must read the directory pull wrote"
    assert calls[3].endswith(" up -d") and "postgres" not in calls[3]


def test_restore_no_start_omits_the_final_up(rig: Rig) -> None:
    proc = rig.run("restore.sh", "--no-start")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = rig.docker_lines()
    assert len(calls) == 3
    assert not any(c.endswith(" up -d") for c in calls)


def test_restore_forwards_force_to_restore_and_snapshot_to_pull(rig: Rig) -> None:
    proc = rig.run("restore.sh", "--force", "--snapshot", "20260930T031500Z", "--no-start")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = rig.docker_lines()
    assert calls[1].endswith(" --snapshot 20260930T031500Z")
    assert "--force" not in calls[1]
    assert calls[2].endswith(" --force") and "--snapshot" not in calls[2]


def test_restore_rejects_a_malformed_snapshot_id(rig: Rig) -> None:
    proc = rig.run("restore.sh", "--snapshot", "../../etc")
    assert proc.returncode == 2, proc.stderr
    assert rig.lines() == []


def test_a_failing_pull_stops_before_the_restore(rig: Rig) -> None:
    proc = rig.run("restore.sh", env={"STUB_PULL_RC": "4"})
    assert proc.returncode == 4, proc.stdout + proc.stderr
    calls = rig.docker_lines()
    assert len(calls) == 2, calls
    assert "src.ops.backup restore" not in " ".join(calls)


def test_a_refusing_restore_reaches_the_operator_and_the_stack_is_not_started(rig: Rig) -> None:
    proc = rig.run("restore.sh", env={"STUB_RESTORE_RC": "1"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not any(c.endswith(" up -d") for c in rig.docker_lines())


def test_restore_dry_run_executes_nothing(rig: Rig) -> None:
    proc = rig.run("restore.sh", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert rig.lines() == []
    assert proc.stdout.count("+ ") == 4


# --- backup-drill.sh ---------------------------------------------------------------------------


def test_drill_makes_exactly_one_ops_call_and_propagates_its_exit_code(rig: Rig) -> None:
    proc = rig.run("backup-drill.sh", env={"STUB_DRILL_RC": "3"})
    assert proc.returncode == 3, proc.stdout + proc.stderr
    (call,) = rig.docker_lines()
    assert re.search(
        rf"{re.escape(OPS)} --no-deps ops {re.escape(PY)} -m src\.ops\.backup drill-remote "
        rf"--scratch-root data/backup/drill-{STAMP}$",
        call,
    ), call


def test_drill_succeeds_with_a_zero_exit_code(rig: Rig) -> None:
    assert rig.run("backup-drill.sh").returncode == 0


# --- update.sh ---------------------------------------------------------------------------------


def _update(
    rig: Rig, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return rig.run("update.sh", *args, env=env)


def test_update_requires_a_ref_or_rollback_and_not_both(rig: Rig) -> None:
    assert _update(rig).returncode == 2
    assert _update(rig, "--ref", "v1", "--rollback").returncode == 2
    assert _update(rig, "--ref", "--evil").returncode == 2
    assert _update(rig, "--rollback", "--skip-backup").returncode == 2
    assert rig.lines() == []


def test_a_dirty_tree_stops_the_update_before_anything_else(rig: Rig) -> None:
    proc = _update(rig, "--ref", "v0.3.1", env={"STUB_GIT_DIRTY": " M src/x.py\n"})
    assert proc.returncode != 0
    assert "uncommitted" in proc.stderr
    assert rig.docker_lines() == []
    assert not any(ln.startswith(("git checkout", "git fetch")) for ln in rig.lines())
    assert not (rig.deploy_state / "last-good.env").exists()


def test_update_records_state_backs_up_retags_checks_out_builds_and_starts(rig: Rig) -> None:
    proc = _update(rig, "--ref", "v0.3.1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    state = (rig.deploy_state / "last-good.env").read_text(encoding="utf-8")
    assert state == f"GIT_SHA={OLD_SHA}\nAPP_IMAGE_ID={OLD_APP}\nOPS_IMAGE_ID={OLD_OPS}\n"

    lines = rig.lines()
    i_backup = _index(lines, "docker compose", "src.ops.backup scheduled")
    i_tag_app = _index(lines, "docker tag trading-alert:dev trading-alert:rollback")
    i_tag_ops = _index(lines, "docker tag trading-alert-ops:dev trading-alert-ops:rollback")
    i_fetch = _index(lines, "git fetch")
    i_checkout = _index(lines, "git checkout --detach v0.3.1")
    i_build = _index(lines, "--profile ops build")
    i_up = _index(lines, " up -d")
    assert i_backup < i_tag_app < i_tag_ops < i_fetch < i_checkout < i_build < i_up
    assert "--no-build" not in lines[i_up]
    # the rollback tags hold the old images, the active tags the new ones
    assert rig.image("trading-alert:rollback") == OLD_APP
    assert rig.image("trading-alert-ops:rollback") == OLD_OPS
    assert rig.image("trading-alert:dev") == NEW_APP
    assert rig.head() == REF_SHA


def test_a_retried_update_keeps_the_rollback_state_of_the_last_good_release(rig: Rig) -> None:
    """WR-02: run 1 builds the new images but fails to start; run 2 must not record them."""
    failed = _update(rig, "--ref", "v0.3.1", env={"STUB_UP_RC": "1"})
    assert failed.returncode != 0
    assert rig.head() == REF_SHA
    assert rig.image("trading-alert:dev") == NEW_APP

    retry = _update(rig, "--ref", "v0.3.1")
    assert retry.returncode == 0, retry.stdout + retry.stderr

    state = (rig.deploy_state / "last-good.env").read_text(encoding="utf-8")
    assert state == f"GIT_SHA={OLD_SHA}\nAPP_IMAGE_ID={OLD_APP}\nOPS_IMAGE_ID={OLD_OPS}\n"
    assert rig.image("trading-alert:rollback") == OLD_APP
    assert rig.image("trading-alert-ops:rollback") == OLD_OPS
    assert "keeping the rollback state" in retry.stderr

    assert _update(rig, "--rollback").returncode == 0
    assert rig.head() == OLD_SHA
    assert rig.image("trading-alert:dev") == OLD_APP


def test_an_unresolvable_ref_is_never_mistaken_for_a_retry(rig: Rig) -> None:
    assert _update(rig, "--ref", "v0.3.1").returncode == 0  # state records OLD, head is now NEW
    proc = _update(rig, "--ref", "v0.4.0", env={"STUB_REF_UNRESOLVED": "1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    state = (rig.deploy_state / "last-good.env").read_text(encoding="utf-8")
    assert f"GIT_SHA={REF_SHA}" in state  # recorded the release that was running
    previous = (rig.deploy_state / "last-good.env.prev").read_text(encoding="utf-8")
    assert previous == f"GIT_SHA={OLD_SHA}\nAPP_IMAGE_ID={OLD_APP}\nOPS_IMAGE_ID={OLD_OPS}\n"


def test_skip_backup_omits_the_backup_run(rig: Rig) -> None:
    proc = _update(rig, "--ref", "v0.3.1", "--skip-backup")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not any("src.ops.backup" in ln for ln in rig.lines())


def test_a_failing_backup_stops_the_update(rig: Rig) -> None:
    proc = _update(rig, "--ref", "v0.3.1", env={"STUB_BACKUP_RC": "9"})
    assert proc.returncode == 9, proc.stdout + proc.stderr
    lines = rig.lines()
    assert not any(ln.startswith(("git checkout", "git fetch")) for ln in lines)
    assert not any(" build" in ln for ln in lines)
    assert rig.head() == OLD_SHA
    assert rig.image("trading-alert:dev") == OLD_APP


def test_an_update_without_local_images_is_refused(rig: Rig) -> None:
    (rig.state / "img" / "trading-alert_dev").unlink()
    proc = _update(rig, "--ref", "v0.3.1")
    assert proc.returncode != 0
    assert "must exist locally" in proc.stderr
    assert not any(ln.startswith("git checkout") for ln in rig.lines())


def test_update_dry_run_executes_nothing(rig: Rig) -> None:
    proc = _update(rig, "--ref", "v0.3.1", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not any(ln.startswith(("git checkout", "git fetch", "docker tag")) for ln in rig.lines())
    assert not (rig.deploy_state / "last-good.env").exists()
    assert "git checkout --detach v0.3.1" in proc.stdout


def test_rollback_without_a_state_file_fails(rig: Rig) -> None:
    proc = _update(rig, "--rollback")
    assert proc.returncode != 0
    assert "nothing to roll back" in proc.stderr
    assert rig.docker_lines() == []


def test_rollback_restores_the_recorded_commit_and_image_ids(rig: Rig) -> None:
    assert _update(rig, "--ref", "v0.3.1").returncode == 0
    assert rig.image("trading-alert:dev") == NEW_APP
    before = len(rig.lines())

    proc = _update(rig, "--rollback")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rig.head() == OLD_SHA
    assert rig.image("trading-alert:dev") == OLD_APP
    assert rig.image("trading-alert-ops:dev") == OLD_OPS
    lines = rig.lines()[before:]
    i_checkout = _index(lines, f"git checkout --detach {OLD_SHA}")
    i_tag = _index(lines, "docker tag trading-alert:rollback trading-alert:dev")
    i_up = _index(lines, "up -d --no-build")
    assert i_checkout < i_tag < i_up
    assert not any(" build" in ln and "--no-build" not in ln for ln in lines)
    assert "NOT undone" in proc.stderr


def test_rollback_aborts_when_the_rollback_image_is_not_the_recorded_one(rig: Rig) -> None:
    assert _update(rig, "--ref", "v0.3.1").returncode == 0
    rig.set_image("trading-alert:rollback", "sha256:" + "e" * 64)
    before = len(rig.lines())
    proc = _update(rig, "--rollback")
    assert proc.returncode != 0
    assert "recorded was" in proc.stderr
    after = rig.lines()[before:]
    assert not any(ln.startswith(("git checkout", "docker compose")) for ln in after)
    assert rig.image("trading-alert:dev") == NEW_APP


def test_rollback_aborts_when_the_record_disagrees_with_the_image_ids(rig: Rig) -> None:
    assert _update(rig, "--ref", "v0.3.1").returncode == 0
    state = rig.deploy_state / "last-good.env"
    text = state.read_text(encoding="utf-8").replace(OLD_APP, "sha256:" + "f" * 64)
    _write(state, text)
    proc = _update(rig, "--rollback")
    assert proc.returncode != 0
    assert not any(ln.endswith("up -d --no-build") for ln in rig.lines())


def test_rollback_refuses_a_corrupt_state_file(rig: Rig) -> None:
    _write(rig.deploy_state / "last-good.env", "GIT_SHA=not-a-sha\n")
    proc = _update(rig, "--rollback")
    assert proc.returncode != 0
    assert "GIT_SHA" in proc.stderr
    assert rig.lines() == []


def test_deploy_state_directory_is_ignored_by_git() -> None:
    proc = subprocess.run(
        ["git", "check-ignore", ".deploy/last-good.env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# --- 16-55 Task 4: the soak project's own backup unit (review B2-WR-07) ----------------------
#
# The remote layout of src/ops/backup_remote.py has no project component, so the soak project
# (trading-soak) must back up into its OWN bucket with its own crypt passwords and sentinel; on a
# shared remote the two projects' snapshots would form one series and retention would delete
# one project's daily dump (evidence/16-55-recheck.md). Decision for plan 16-55: a separate
# BACKUP_S3_BUCKET in the soak env file (orchestrator, 2026-10-16; no change to the layout).

BASELINE = "5f8269b"
SOAK_UNITS = ("trading-soak-backup.service", "trading-soak-backup.timer")


def _timer_keys(text: str) -> dict[str, str]:
    keys = ("OnCalendar", "Persistent", "RandomizedDelaySec")
    out: dict[str, str] = {}
    for line in text.splitlines():
        name, _, value = line.partition("=")
        if name in keys:
            out[name] = value
    assert set(out) == set(keys), out
    return out


def test_the_soak_backup_units_select_the_soak_project_and_env_file() -> None:
    service = (UNITS / "trading-soak-backup.service").read_text(encoding="utf-8")
    assert re.search(r"^Type=oneshot$", service, re.MULTILINE)
    assert re.search(r"^User=trading$", service, re.MULTILINE)
    assert re.search(r"^WorkingDirectory=@TRADING_DIR@$", service, re.MULTILINE)
    assert re.search(r"^Environment=COMPOSE_PROJECT_NAME=trading-soak$", service, re.MULTILINE)
    assert re.search(r"^Environment=TRADING_ENV_FILE=@SOAK_ENV_FILE@$", service, re.MULTILINE)
    assert re.search(
        r"^ExecStart=/usr/bin/env bash @TRADING_DIR@/deploy/backup\.sh$", service, re.M
    )
    assert "docker.service" in service
    timer = (UNITS / "trading-soak-backup.timer").read_text(encoding="utf-8")
    existing = (UNITS / "trading-backup.timer").read_text(encoding="utf-8")
    assert _timer_keys(timer) == _timer_keys(existing)
    assert re.search(r"^Unit=trading-soak-backup\.service$", timer, re.MULTILINE)
    assert re.search(r"^WantedBy=timers.target$", timer, re.MULTILINE)


@pytest.mark.parametrize("name", ["trading-backup.service", "trading-backup.timer"])
def test_the_existing_backup_units_are_byte_unchanged(name: str) -> None:
    proc = subprocess.run(
        ["git", "show", f"{BASELINE}:deploy/systemd/{name}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    assert (UNITS / name).read_bytes().replace(b"\r\n", b"\n") == proc.stdout.replace(
        b"\r\n", b"\n"
    )


def _env_files(rig: Rig, soak_bucket: str, trading_bucket: str) -> tuple[Path, Path]:
    soak = _write(rig.base / "soak.env", f"POSTGRES_USER=x\nBACKUP_S3_BUCKET={soak_bucket}\n")
    trading = _write(rig.base / "trading.env", f"BACKUP_S3_BUCKET={trading_bucket}\n")
    return soak, trading


def _install_soak(rig: Rig, soak: Path, trading: Path) -> subprocess.CompletedProcess[str]:
    return rig.run(
        "backup.sh",
        "--install-soak-timer",
        "--soak-env-file",
        soak.as_posix(),
        env={"TRADING_BACKUP_ENV_FILE": trading.as_posix()},
    )


def test_install_soak_timer_writes_the_soak_units_and_enables_their_timer(rig: Rig) -> None:
    soak, trading = _env_files(rig, "soak-evidence-bucket", "trading-bucket")
    proc = _install_soak(rig, soak, trading)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    unit_dir = rig.prefix / "etc" / "systemd" / "system"
    service = (unit_dir / "trading-soak-backup.service").read_text(encoding="utf-8")
    timer = (unit_dir / "trading-soak-backup.timer").read_text(encoding="utf-8")
    checkout = _checkout_as_bash_sees_it(rig)
    for text in (service, timer):
        assert "@TRADING_DIR@" not in text and "@SOAK_ENV_FILE@" not in text
    assert f"WorkingDirectory={checkout}" in service
    assert f"Environment=TRADING_ENV_FILE={soak.as_posix()}" in service
    assert "Environment=COMPOSE_PROJECT_NAME=trading-soak" in service
    assert not (unit_dir / "trading-backup.service").exists(), "the trading pair is untouched"
    calls = [ln for ln in rig.lines() if ln.startswith("systemctl ")]
    assert calls == [
        "systemctl daemon-reload",
        "systemctl enable --now trading-soak-backup.timer",
    ]
    out = proc.stdout + proc.stderr
    assert "soak-evidence-bucket" not in out and "trading-bucket" not in out


def test_install_soak_timer_refuses_the_trading_backup_bucket(rig: Rig) -> None:
    soak, trading = _env_files(rig, "shared-bucket", "shared-bucket")
    proc = _install_soak(rig, soak, trading)
    assert proc.returncode != 0
    assert "BACKUP_S3_BUCKET" in proc.stderr
    assert "shared-bucket" not in proc.stdout + proc.stderr, "a value is never printed"
    assert not (rig.prefix / "etc").exists()
    assert rig.lines() == []


def test_install_soak_timer_refuses_an_empty_soak_bucket(rig: Rig) -> None:
    soak, trading = _env_files(rig, "", "trading-bucket")
    proc = _install_soak(rig, soak, trading)
    assert proc.returncode != 0
    assert "BACKUP_S3_BUCKET" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_install_soak_timer_needs_a_readable_soak_env_file(rig: Rig) -> None:
    _soak, trading = _env_files(rig, "a", "b")
    proc = _install_soak(rig, rig.base / "missing.env", trading)
    assert proc.returncode != 0
    assert not (rig.prefix / "etc").exists()
    proc = rig.run("backup.sh", "--install-soak-timer")
    assert proc.returncode == 2, "the soak env file is a required argument"


def test_soak_env_template_keeps_the_bucket_empty_and_says_it_is_its_own() -> None:
    lines = (DEPLOY / "soak.env.example").read_text(encoding="utf-8").splitlines()
    assert "BACKUP_S3_BUCKET=" in lines
    comments = "\n".join(ln for ln in lines if ln.startswith("#"))
    assert "trading-backup" in comments
    assert "own bucket" in comments


# --- 16-65: the bucket guard reads the env files as Compose does; safe unit substitution ------
# Review of c654524..6f73e5b (MINOR 1): the awk reader took the FIRST `BACKUP_S3_BUCKET=` line
# and kept `export `, inline comments and half-stripped quotes, while Compose accepts `export `,
# strips quotes and an unquoted ` # comment`, and lets the LAST assignment win. The guard now
# reads the value the Compose way and refuses the install when it cannot determine it.


def _install_soak_texts(
    rig: Rig, soak_text: str, trading_text: str
) -> subprocess.CompletedProcess[str]:
    soak = _write(rig.base / "soak.env", soak_text)
    trading = _write(rig.base / "trading.env", trading_text)
    return _install_soak(rig, soak, trading)


SHARED = "shared-bucket"


@pytest.mark.parametrize(
    "soak_text",
    [
        f"export BACKUP_S3_BUCKET={SHARED}\n",
        f"BACKUP_S3_BUCKET=soak-bucket\nBACKUP_S3_BUCKET={SHARED}\n",
        f'BACKUP_S3_BUCKET="{SHARED}"\n',
        f"BACKUP_S3_BUCKET='{SHARED}'\n",
        f"BACKUP_S3_BUCKET={SHARED} # the soak bucket\n",
        f'BACKUP_S3_BUCKET="{SHARED}" # the soak bucket\n',
        f"  export   BACKUP_S3_BUCKET={SHARED}\r\n",
    ],
    ids=[
        "export",
        "last-wins",
        "double-quoted",
        "single-quoted",
        "inline-comment",
        "quoted-comment",
        "indented-crlf",
    ],
)
def test_install_soak_timer_refuses_the_trading_bucket_in_every_compose_form(
    rig: Rig, soak_text: str
) -> None:
    proc = _install_soak_texts(rig, soak_text, f"BACKUP_S3_BUCKET={SHARED}\n")
    assert proc.returncode != 0, "Compose would read the trading bucket here"
    assert "BACKUP_S3_BUCKET" in proc.stderr
    assert SHARED not in proc.stdout + proc.stderr, "a value is never printed"
    assert not (rig.prefix / "etc").exists()


@pytest.mark.parametrize(
    "trading_text",
    [
        f"export BACKUP_S3_BUCKET={SHARED}\n",
        f"BACKUP_S3_BUCKET=other-bucket\nBACKUP_S3_BUCKET={SHARED}\n",
        f'BACKUP_S3_BUCKET="{SHARED}" # comment\n',
    ],
    ids=["export", "last-wins", "quoted-comment"],
)
def test_the_trading_env_file_is_read_the_same_way(rig: Rig, trading_text: str) -> None:
    proc = _install_soak_texts(rig, f"BACKUP_S3_BUCKET={SHARED}\n", trading_text)
    assert proc.returncode != 0
    assert not (rig.prefix / "etc").exists()


def test_the_last_assignment_of_the_soak_file_wins_as_in_compose(rig: Rig) -> None:
    proc = _install_soak_texts(
        rig,
        f"BACKUP_S3_BUCKET={SHARED}\n# BACKUP_S3_BUCKET={SHARED}\n"
        "BACKUP_S3_BUCKET=soak-bucket # own\n",
        f"BACKUP_S3_BUCKET={SHARED}\n",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (rig.prefix / "etc" / "systemd" / "system" / "trading-soak-backup.service").exists()


@pytest.mark.parametrize(
    "soak_text",
    [
        "BACKUP_S3_BUCKET=${OTHER_BUCKET}\n",
        'BACKUP_S3_BUCKET="unterminated\n',
        'BACKUP_S3_BUCKET="a" trailing\n',
        "BACKUP_S3_BUCKET=a\\b\n",
        "BACKUP_S3_BUCKET=soak-bucket\nBACKUP_S3_BUCKET='half\n",
    ],
    ids=["interpolation", "unterminated", "text-after-quote", "backslash", "bad-later-line"],
)
def test_an_undeterminable_soak_bucket_is_refused(rig: Rig, soak_text: str) -> None:
    proc = _install_soak_texts(rig, soak_text, "BACKUP_S3_BUCKET=trading-bucket\n")
    assert proc.returncode != 0
    assert "BACKUP_S3_BUCKET" in proc.stderr and "cannot be determined" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_an_undeterminable_trading_bucket_is_refused(rig: Rig) -> None:
    proc = _install_soak_texts(
        rig, "BACKUP_S3_BUCKET=soak-bucket\n", "BACKUP_S3_BUCKET=${SOMETHING}\n"
    )
    assert proc.returncode != 0
    assert "cannot be determined" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_a_comment_only_value_is_an_empty_bucket(rig: Rig) -> None:
    proc = _install_soak_texts(
        rig, "BACKUP_S3_BUCKET= # fill in\n", "BACKUP_S3_BUCKET=trading-bucket\n"
    )
    assert proc.returncode != 0
    assert "empty" in proc.stderr
    assert not (rig.prefix / "etc").exists()


# MINOR 2: a `&` in a replacement is the matched text under bash 5.2 patsub_replacement, and a
# `%` in a unit file is a systemd specifier. heartbeat.sh turns patsub_replacement off and
# accepts only letters, digits and . _ / + = , ~ - in a unit path; backup.sh now does the same.


@pytest.mark.parametrize("name", ["soak%i.env", "soak&x.env"], ids=["percent", "ampersand"])
def test_install_soak_timer_refuses_a_unit_unsafe_env_file_path(rig: Rig, name: str) -> None:
    soak = _write(rig.base / name, "BACKUP_S3_BUCKET=soak-bucket\n")
    trading = _write(rig.base / "trading.env", "BACKUP_S3_BUCKET=trading-bucket\n")
    proc = _install_soak(rig, soak, trading)
    assert proc.returncode != 0
    assert "--soak-env-file" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_the_unit_substitution_turns_patsub_replacement_off() -> None:
    text = (DEPLOY / "backup.sh").read_text(encoding="utf-8")
    body = text[text.index("write_units() {") :]
    body = body[: body.index("\n}\n")]
    assert "shopt -u patsub_replacement" in body
    assert body.index("shopt -u patsub_replacement") < body.index('content="${content//')


# --- 261020-bkp A: review of 2026-10-20, two MINOR findings ------------------------------------
# A1: the checkout path is substituted into every unit (@TRADING_DIR@), so it gets the character
# rule of --soak-env-file (no systemd specifier %, no bash replacement &, no whitespace).
# A2: Compose takes the value of a bare `KEY` line (no `=`) from the process environment, so the
# guard cannot determine it and refuses.


def _copied_checkout(tmp_path: Path, name: str) -> Path:
    """A copy of backup.sh, lib.sh and the unit templates under a checkout named ``name``."""
    deploy = tmp_path / name / "deploy"
    (deploy / "systemd").mkdir(parents=True)
    for rel in ("backup.sh", "lib.sh"):
        _write(deploy / rel, (DEPLOY / rel).read_text(encoding="utf-8"))
    for unit in UNITS.iterdir():
        _write(deploy / "systemd" / unit.name, unit.read_text(encoding="utf-8"))
    return deploy / "backup.sh"


@pytest.mark.parametrize(
    "name",
    ["re%ipo", "re&po", "re po", "re;po"],
    ids=["percent", "ampersand", "space", "semicolon"],
)
@pytest.mark.parametrize("mode", ["--install-timer", "--install-soak-timer"])
def test_a_checkout_path_the_units_cannot_carry_is_refused(
    rig: Rig, tmp_path: Path, name: str, mode: str
) -> None:
    script = _copied_checkout(tmp_path, name)
    soak, trading = _env_files(rig, "soak-bucket", "trading-bucket")
    args = [mode] if mode == "--install-timer" else [mode, "--soak-env-file", soak.as_posix()]
    proc = rig.run(script.as_posix(), *args, env={"TRADING_BACKUP_ENV_FILE": trading.as_posix()})
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "checkout path" in proc.stderr
    assert not (rig.prefix / "etc").exists()
    assert rig.lines() == []


def test_a_plain_copied_checkout_still_installs(rig: Rig, tmp_path: Path) -> None:
    script = _copied_checkout(tmp_path, "plain-checkout_1.2+x")
    proc = rig.run(script.as_posix(), "--install-timer")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    service = (rig.prefix / "etc" / "systemd" / "system" / "trading-backup.service").read_text(
        encoding="utf-8"
    )
    assert "plain-checkout_1.2+x/deploy/backup.sh" in service


@pytest.mark.parametrize(
    "soak_text",
    [
        "BACKUP_S3_BUCKET\n",
        "BACKUP_S3_BUCKET=soak-bucket\nBACKUP_S3_BUCKET\n",
        "BACKUP_S3_BUCKET\nBACKUP_S3_BUCKET=soak-bucket\n",
        "export BACKUP_S3_BUCKET\n",
        "  BACKUP_S3_BUCKET  \r\n",
        "BACKUP_S3_BUCKET # from the shell\n",
    ],
    ids=["bare", "bare-last", "bare-first", "export-bare", "indented-crlf", "bare-comment"],
)
def test_a_bare_key_soak_bucket_cannot_be_determined(rig: Rig, soak_text: str) -> None:
    proc = _install_soak_texts(rig, soak_text, "BACKUP_S3_BUCKET=trading-bucket\n")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "BACKUP_S3_BUCKET" in proc.stderr and "cannot be determined" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_a_bare_key_trading_bucket_cannot_be_determined(rig: Rig) -> None:
    proc = _install_soak_texts(rig, "BACKUP_S3_BUCKET=soak-bucket\n", "BACKUP_S3_BUCKET\n")
    assert proc.returncode != 0
    assert "cannot be determined" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_a_bare_line_of_another_name_does_not_matter(rig: Rig) -> None:
    proc = _install_soak_texts(
        rig,
        "OTHER_NAME\nBACKUP_S3_BUCKET_X\nBACKUP_S3_BUCKET=soak-bucket\n",
        "BACKUP_S3_BUCKET=trading-bucket\n",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- 261020-bkp B: explicit local-only mode (BACKUP_REMOTE=none in the env file) -------------
# The decision lives in python (scheduled and drill-remote run locally, print the warning and
# OFFSITE_COPY=skipped; tests/test_backup_remote.py). The wrapper only refuses --init-remote and
# lets --install-soak-timer accept a soak env file without a bucket.

OFFSITE_WARNING = "OFF-HOST COPY SKIPPED: this backup does not survive the loss of this host"


def test_init_remote_in_local_only_mode_refuses_before_any_docker_call(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--init-remote", env=_remote_env(rig, "BACKUP_REMOTE=none\n"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "BACKUP_REMOTE=none" in proc.stderr and "nothing to initialise" in proc.stderr
    assert rig.lines() == []


@pytest.mark.parametrize(
    "text",
    ["BACKUP_REMOTE=${X}\n", "BACKUP_REMOTE\n", "BACKUP_REMOTE=azure\n", "BACKUP_REMOTE=NONE\n"],
    ids=["interpolation", "bare", "unknown", "upper-case"],
)
def test_init_remote_refuses_an_undeterminable_or_unknown_mode(rig: Rig, text: str) -> None:
    proc = rig.run("backup.sh", "--init-remote", env=_remote_env(rig, text))
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "BACKUP_REMOTE" in proc.stderr
    assert "azure" not in proc.stderr, "a value is never printed"
    assert rig.lines() == []


def test_init_remote_with_the_explicit_s3_mode_runs(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--init-remote", env=_remote_env(rig, "BACKUP_REMOTE=s3\n"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(rig.docker_lines()) == 2


def test_a_scheduled_run_in_local_only_mode_is_the_same_single_python_call(rig: Rig) -> None:
    proc = rig.run("backup.sh", env=_remote_env(rig, "BACKUP_REMOTE=none\n"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (call,) = rig.docker_lines()
    assert f"{PY} -m src.ops.backup scheduled" in call


def test_install_soak_timer_in_local_only_mode_needs_no_bucket_and_warns(rig: Rig) -> None:
    soak = _write(rig.base / "soak.env", "BACKUP_REMOTE=none\nBACKUP_S3_BUCKET=\n")
    proc = _install_soak(rig, soak, rig.base / "no-trading.env")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert OFFSITE_WARNING in proc.stderr
    unit_dir = rig.prefix / "etc" / "systemd" / "system"
    service = (unit_dir / "trading-soak-backup.service").read_text(encoding="utf-8")
    assert f"Environment=TRADING_ENV_FILE={soak.as_posix()}" in service


def test_install_soak_timer_in_local_only_mode_still_refuses_the_trading_bucket(rig: Rig) -> None:
    proc = _install_soak_texts(
        rig, f"BACKUP_REMOTE=none\nBACKUP_S3_BUCKET={SHARED}\n", f"BACKUP_S3_BUCKET={SHARED}\n"
    )
    assert proc.returncode != 0
    assert "BACKUP_S3_BUCKET" in proc.stderr
    assert SHARED not in proc.stdout + proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_install_soak_timer_in_local_only_mode_accepts_an_own_bucket(rig: Rig) -> None:
    proc = _install_soak_texts(
        rig, "BACKUP_REMOTE=none\nBACKUP_S3_BUCKET=soak-bucket\n", "BACKUP_S3_BUCKET=trading\n"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert OFFSITE_WARNING in proc.stderr


@pytest.mark.parametrize("text", ["BACKUP_REMOTE=azure\n", "BACKUP_REMOTE=$X\n", "BACKUP_REMOTE\n"])
def test_install_soak_timer_refuses_an_unknown_or_undeterminable_mode(rig: Rig, text: str) -> None:
    proc = _install_soak_texts(rig, text + "BACKUP_S3_BUCKET=soak\n", "BACKUP_S3_BUCKET=t\n")
    assert proc.returncode != 0
    assert "BACKUP_REMOTE" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_the_default_mode_still_refuses_an_empty_soak_bucket(rig: Rig) -> None:
    proc = _install_soak_texts(rig, "BACKUP_REMOTE=s3\nBACKUP_S3_BUCKET=\n", "BACKUP_S3_BUCKET=t\n")
    assert proc.returncode != 0
    assert "empty" in proc.stderr
    assert not (rig.prefix / "etc").exists()


def test_the_help_and_the_docs_describe_the_local_only_mode(rig: Rig) -> None:
    proc = rig.run("backup.sh", "--help")
    assert proc.returncode == 0
    assert "BACKUP_REMOTE=none" in proc.stderr and "OFFSITE_COPY=skipped" in proc.stderr
    runbook = (REPO_ROOT / "docs" / "operations" / "RUNBOOK.md").read_text(encoding="utf-8")
    section_11 = runbook[runbook.index("## 11. ") : runbook.index("## 12. ")]
    for phrase in ("BACKUP_REMOTE=none", "OFFSITE_COPY=skipped", "OFF-HOST COPY SKIPPED"):
        assert phrase in section_11, phrase
    section_20_5 = runbook[runbook.index("### 20.5 ") : runbook.index("### 20.6 ")]
    assert "OFFSITE_COPY=skipped" in section_20_5 and "pin" in section_20_5
    for name in ("soak.env.example",):
        lines = (DEPLOY / name).read_text(encoding="utf-8").splitlines()
        assert "BACKUP_REMOTE=" in lines, name
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "BACKUP_REMOTE=" in env_example
