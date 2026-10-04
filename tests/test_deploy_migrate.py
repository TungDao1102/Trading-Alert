"""Behavioural tests for ``deploy/migrate.sh`` through real bash with stub binaries (13.1-09).

The real script runs under Git Bash (Windows) or bash (Linux CI). ``docker``, ``ssh``,
``rsync`` and ``sha256sum`` are stubs first on PATH that append their argv to a log, so the
tests assert the decided order of the cutover (D-14) and the safety rules (no deletion, nothing
stopped or torn down on the old host except the collector) without any container. The report
stub's exit code, the tick probe and the stale-artifact probe come from environment variables.

The two-environment proof with real containers is ``tests/test_docker_cutover.py``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATE = REPO_ROOT / "deploy" / "migrate.sh"

DUMP_SHA = "a" * 63 + "b"
OLD = "old.example"

_LOG = r"""
printf '%s\n' "${0##*/} $*" >> "${STUB_LOG:?}"
"""

# One behaviour shared by docker (new side, local) and ssh (old side, remote docker).
_COMMON = r"""
case "$*" in
  *"cat /app/data/backup/cutover/pg.dump.sha256"*)
    echo "${STUB_DUMP_SHA:-}  pg.dump"; exit 0 ;;
  *"cutover advanced"*)
    n=0; [ -f "$STUB_LOG.polls" ] && n="$(cat "$STUB_LOG.polls")"
    n=$((n + 1)); echo "$n" > "$STUB_LOG.polls"
    if [ "$n" -gt "${STUB_ADVANCE_AFTER:-0}" ]; then exit 0; fi
    exit 1 ;;
  *"cutover report"*)
    echo "stub cutover report"; exit "${STUB_REPORT_RC:-0}" ;;
  *"restore-db"*)
    exit "${STUB_RESTORE_RC:-0}" ;;
esac
"""

STUBS: dict[str, str] = {
    "docker": _COMMON
    + r"""
case "$*" in
  *"test -e"*) exit "${STUB_STALE_NEW_RC:-1}" ;;
esac
exit 0
""",
    "ssh": _COMMON
    + r"""
case "$*" in
  *"test -e"*) exit "${STUB_STALE_OLD_RC:-1}" ;;
esac
exit 0
""",
    "rsync": "exit 0\n",
    "sha256sum": "exit 0\n",
}

DRIVER = """\
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
export PATH="$here/bin:$PATH"
exec bash "${MIGRATE_SCRIPT:?}" "$@"
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
    env_extra: dict[str, str] = field(default_factory=dict)

    @property
    def log(self) -> Path:
        return self.base / "stub.log"

    def lines(self) -> list[str]:
        if not self.log.exists():
            return []
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def run(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        full_env = dict(os.environ)
        full_env.update(
            {
                "MSYS_NO_PATHCONV": "1",
                "MIGRATE_SCRIPT": MIGRATE.as_posix(),
                "STUB_LOG": (self.base / "stub.log").as_posix(),
                "STUB_DUMP_SHA": DUMP_SHA,
                "MIGRATE_POLL_SECONDS": "0",
            }
        )
        full_env.update(self.env_extra)
        full_env.update(env or {})
        return subprocess.run(
            [self.bash, (self.base / "driver.sh").as_posix(), *args],
            capture_output=True,
            text=True,
            env=full_env,
            check=False,
            timeout=120,
        )

    def go(
        self, *extra: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """A normal run: default key source is a named volume (no file checks)."""
        return self.run("--key-source", "t131keys", *extra, OLD, "local", env=env)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; migrate tests need Git Bash or Linux bash")
    base = tmp_path / "rig"
    for name, body in STUBS.items():
        _write(base / "bin" / name, "#!/usr/bin/env bash\n" + _LOG + body)
    _write(base / "driver.sh", DRIVER)
    return Rig(base=base, bash=bash)


def _index(lines: list[str], *needles: str, start: int = 0) -> int:
    """Index of the first log line at or after ``start`` containing every needle."""
    for i in range(start, len(lines)):
        if all(n in lines[i] for n in needles):
            return i
    raise AssertionError(f"no log line from {start} containing {needles}:\n" + "\n".join(lines))


def _rsync_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if " ops rsync " in ln]


def test_a_remote_new_target_is_refused_before_anything_runs(rig: Rig) -> None:
    """WR-03: a second ssh hop would split the rsync arguments after the old side was stopped."""
    proc = rig.run("--key-source", "t131keys", OLD, "trading@new.example")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "must be 'local'" in proc.stderr
    assert rig.lines() == [], "nothing may run before the refusal"


# --- dry run ---------------------------------------------------------------------------------


def test_dry_run_prints_the_ordered_plan_and_executes_nothing(rig: Rig) -> None:
    proc = rig.run("--dry-run", "--key-source", "t131keys", OLD, "local")
    assert proc.returncode == 0, proc.stderr
    assert rig.lines() == [], "a dry run must not call any stub"
    out = proc.stdout
    names = [
        "preflight",
        "pre-sync",
        "stop the old collector",
        "final Parquet sync",
        "pg_dump, fingerprint",
        "pull the dump",
        "restore the database",
        "start the new collector",
        "first new tick",
        "cutover report",
    ]
    pos = 0
    for number, name in enumerate(names, start=1):
        marker = f"== step {number}/10"
        idx = out.find(marker, pos)
        assert idx >= 0 and name in out[idx : idx + 120], f"step {number} ({name}) out of order"
        pos = idx + len(marker)
    assert "+ " in out
    assert "stop collector" in out
    assert "src.ops.cutover report" in out
    assert "NOT been shut down" in out


# --- the real order --------------------------------------------------------------------------


def test_real_run_follows_the_cutover_order(rig: Rig) -> None:
    proc = rig.go(env={"STUB_ADVANCE_AFTER": "2"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = rig.lines()

    stops = [ln for ln in lines if ln.startswith("ssh") and " stop " in ln]
    assert len(stops) == 1 and stops[0].endswith(" stop collector"), stops
    i_stop = lines.index(stops[0])

    rsyncs = [i for i, ln in enumerate(lines) if " ops rsync " in ln]
    assert len(rsyncs) == 3
    presync, final, pull = rsyncs
    assert presync < i_stop < final, "pre-sync while running, final sync after the stop"
    assert "/data/raw/" in lines[presync] and "/data/raw/" in lines[final]
    assert "/data/backup/cutover/" in lines[pull]

    i_dump = _index(lines, "ssh", "src.ops.backup dump", start=final)
    i_fp = _index(lines, "ssh", "src.ops.cutover fingerprint", start=final)
    i_wm = _index(lines, "ssh", "src.ops.cutover watermarks", start=final)
    assert final < i_dump < pull and final < i_fp < pull and final < i_wm < pull
    assert "--out /app/data/backup/cutover/pg.dump" in lines[i_dump]

    i_pg = _index(lines, "docker", " up -d --wait", "postgres", start=pull)
    i_hash = _index(lines, "pg.dump.sha256", start=pull)
    i_restore = _index(lines, "docker", "src.ops.backup restore-db", start=pull)
    assert pull < i_pg < i_hash < i_restore
    assert f"--expect-sha256 {DUMP_SHA}" in lines[i_restore]
    assert "--pg-dump /app/data/backup/cutover/pg.dump" in lines[i_restore]

    i_up = _index(lines, "docker", " up -d collector", start=i_restore)
    i_poll = _index(lines, "cutover advanced", start=i_up)
    i_report = _index(lines, "cutover report", start=i_poll)
    assert i_up < i_poll < i_report
    assert sum("cutover advanced" in ln for ln in lines) == 3, "polled until the tick advanced"
    assert "--max-gap-minutes 60" in lines[i_report]
    assert "--window-end" not in lines[i_report]

    # Every old-side call goes through ssh to the old target; the new side never does.
    for ln in lines:
        if ln.startswith("ssh"):
            assert OLD in ln and "docker compose" in ln
        else:
            assert OLD not in ln.replace(f"{OLD}:", "SRC:")


def test_max_gap_and_window_end_reach_the_report(rig: Rig) -> None:
    proc = rig.go(
        "--max-gap-minutes", "30", env={"MIGRATE_REPORT_WINDOW_END": "2026-09-01T11:46:00Z"}
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = rig.lines()[_index(rig.lines(), "cutover report")]
    assert "--max-gap-minutes 30" in report
    assert "--window-end 2026-09-01T11:46:00Z" in report
    assert "--raw-root /app/data/raw" in report


@pytest.mark.parametrize("report_rc", [0, 1, 2, 3])
def test_exit_code_is_the_reports_and_the_notice_always_prints(rig: Rig, report_rc: int) -> None:
    proc = rig.go(env={"STUB_REPORT_RC": str(report_rc)})
    assert proc.returncode == report_rc, proc.stdout + proc.stderr
    assert "NOT been shut down" in proc.stdout
    assert "by hand only after the report above is clean" in proc.stdout


def test_a_tick_timeout_still_runs_the_report(rig: Rig) -> None:
    proc = rig.go("--wait-seconds", "0", env={"STUB_ADVANCE_AFTER": "999", "STUB_REPORT_RC": "3"})
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "no new tick within 0s" in proc.stderr
    lines = rig.lines()
    assert sum("cutover advanced" in ln for ln in lines) == 1
    assert any("cutover report" in ln for ln in lines)


# --- safety rules ----------------------------------------------------------------------------

_DELETING = (
    "--delete",
    "--remove-source-files",
    "--delete-before",
    "--delete-after",
    "--delete-during",
    "--delete-excluded",
    "--del ",
    "--force",
)
_BANNED_OLD_WORDS = {"down", "rm", "kill", "poweroff", "shutdown", "halt", "reboot", "prune"}


def test_every_rsync_call_is_append_only_strict_and_deletes_nothing(rig: Rig) -> None:
    proc = rig.go()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = _rsync_lines(rig.lines())
    assert len(calls) == 3
    for call in calls:
        assert "--ignore-existing" in call
        assert "--exclude .*.tmp" in call
        assert "StrictHostKeyChecking=yes" in call
        assert "UserKnownHostsFile=/keys/known_hosts" in call
        assert "-v t131keys:/keys:ro" in call
        assert "--user 0:0" in call
        for flag in _DELETING:
            assert flag not in call + " "
        assert f"{OLD}:/data/" in call


def test_default_rsync_path_reads_the_old_volumes_read_only(rig: Rig) -> None:
    proc = rig.go(env={"MIGRATE_OLD_PROJECT": "prod", "IMAGE_TAG": "v9"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    call = _rsync_lines(rig.lines())[0]
    assert "--rsync-path=docker run --rm -i" in call
    assert "-v prod_rawdata:/data/raw:ro" in call
    assert "-v prod_backupdata:/data/backup:ro" in call
    assert "--entrypoint rsync trading-alert-ops:v9" in call


def test_the_old_host_only_ever_loses_its_collector(rig: Rig) -> None:
    proc = rig.go()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    old_calls = [ln for ln in rig.lines() if ln.startswith("ssh")]
    assert old_calls
    for call in old_calls:
        words = set(call.split())
        assert not (words & _BANNED_OLD_WORDS), call
        if " stop " in call:
            assert call.endswith(" stop collector"), call
        assert "StrictHostKeyChecking=yes" in call
    # No docker call on the new side may stop or remove anything either.
    for call in rig.lines():
        assert " down" not in call and " stop " not in call or call.startswith("ssh")


def test_script_text_has_no_deletion_or_shutdown_commands() -> None:
    text = MIGRATE.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    for banned in ("--delete", "--remove-source-files", "poweroff", "shutdown -", "compose down"):
        assert banned not in code, banned
    assert "--ignore-existing" in code
    assert "StrictHostKeyChecking=yes" in code
    assert "src.ops.cutover" in code and "restore-db" in code
    assert "shut the old host down" in text.lower()


def test_stale_artifacts_on_either_side_stop_everything_before_any_change(rig: Rig) -> None:
    for var in ("STUB_STALE_OLD_RC", "STUB_STALE_NEW_RC"):
        proc = rig.go(env={var: "0"})
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "earlier run" in proc.stderr
        lines = rig.lines()
        assert not any(" ops rsync " in ln or " stop " in ln for ln in lines)
        rig.log.unlink()


def test_a_failed_restore_after_the_stop_says_how_to_resume_the_old_collector(rig: Rig) -> None:
    proc = rig.go(env={"STUB_RESTORE_RC": "1"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "old collector is STOPPED" in proc.stderr
    assert f"{OLD} docker compose" in proc.stderr and "start collector" in proc.stderr
    assert not any("up -d collector" in ln for ln in rig.lines())


def test_a_malformed_dump_hash_is_refused_before_the_restore(rig: Rig) -> None:
    proc = rig.go(env={"STUB_DUMP_SHA": "not-a-digest"})
    assert proc.returncode == 1
    assert "sha256" in proc.stderr
    assert not any("restore-db" in ln for ln in rig.lines())


# --- overrides, report-only, usage -----------------------------------------------------------


def test_overrides_replace_the_compose_prefixes_and_the_rsync_source(rig: Rig) -> None:
    proc = rig.go(
        env={
            "MIGRATE_OLD_COMPOSE": "docker compose -p t131-old --profile ops",
            "MIGRATE_NEW_COMPOSE": "docker compose -p t131-new --profile ops",
            "MIGRATE_RSYNC_SOURCE": "rsync@t131-sidecar",
            "MIGRATE_RSYNC_PATH": "rsync",
        }
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = rig.lines()
    assert not any(ln.startswith("ssh") for ln in lines)
    stop = lines[_index(lines, " stop collector")]
    assert stop == "docker compose -p t131-old --profile ops stop collector"
    for call in _rsync_lines(lines):
        assert "docker compose -p t131-new" in call
        assert "--rsync-path=rsync " in call
        assert "rsync@t131-sidecar:/data/" in call


def test_report_only_runs_just_the_report_steps(rig: Rig) -> None:
    args = ["--report-only", "--max-gap-minutes", "30", "--key-source", "k", OLD, "local"]
    proc = rig.run(*args, env={"STUB_REPORT_RC": "3"})
    assert proc.returncode == 3, proc.stdout + proc.stderr
    lines = rig.lines()
    assert not any(" stop " in ln or " ops rsync " in ln or "restore-db" in ln for ln in lines)
    assert "--max-gap-minutes 30" in lines[_index(lines, "cutover report")]


def test_a_key_directory_path_must_hold_the_key_and_known_hosts(rig: Rig, tmp_path: Path) -> None:
    keys = tmp_path / "keys"
    keys.mkdir()
    proc = rig.run("--key-source", keys.as_posix(), OLD, "local")
    assert proc.returncode == 1
    assert "id_ed25519 and known_hosts" in proc.stderr
    assert rig.lines() == []


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["only-one-target"],
        ["a", "b", "c"],
        ["--bogus", "a", "b"],
        ["--max-gap-minutes", "soon", "a", "b"],
        ["--wait-seconds", "a", "b"],
        ["--max-gap-minutes"],
    ],
)
def test_bad_usage_exits_two_with_usage_text(rig: Rig, args: list[str]) -> None:
    proc = rig.run(*args)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Usage" in proc.stderr
    assert rig.lines() == []
