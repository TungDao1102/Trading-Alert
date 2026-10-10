"""Offline tests for the external heartbeat sender (plan 16-50, D042 condition 1).

``deploy/heartbeat.sh`` probes the collector inside its compose service and sends one ping to an
external monitor only while the probe passes. The real script runs under Git Bash (Windows) or bash
(Linux CI); ``docker``, ``curl`` and ``systemctl`` are stubs first on PATH that append their argv to
a log (the curl stub also saves the configuration it reads on standard input). One test runs the
real ``curl`` against a closed loopback port. No test reaches a network.

The ping URL is a secret. Every test uses a FAKE sentinel URL and asserts the sentinel is absent
from stdout, stderr and the whole stub log. Real delivery to the monitor, systemd credential
delivery and timer firing are operator verification on the host (plan 16-50), not claimed here.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = REPO_ROOT / "deploy"
UNITS = DEPLOY / "systemd"

PY = "/app/.venv/bin/python"
PROBE_LINE = f"docker compose exec -T collector {PY} -m src.data.collector --healthcheck"

# A FAKE secret. The token is what the tests grep for; the host is a reserved invalid name.
TOKEN = "SECRETPINGTOKEN7731"
SENTINEL_HOST = "sentinel.invalid"
SENTINEL_URL = f"https://{SENTINEL_HOST}/{TOKEN}"
OTHER_TOKEN = "OTHERPINGTOKEN5520"
OTHER_URL = f"https://{SENTINEL_HOST}/{OTHER_TOKEN}"
SECRET_MARKERS = (TOKEN, OTHER_TOKEN, SENTINEL_HOST)

_LOG = r"""
printf '%s\n' "${0##*/} $*" >> "${STUB_LOG:?}"
state="${STUB_STATE:?}"
mkdir -p "$state"
"""

STUBS: dict[str, str] = {
    "docker": r"""
exit "${STUB_PROBE_RC:-0}"
""",
    "curl": r"""
n="$(grep -c '^curl ' "$STUB_LOG")"
cat > "$state/curl-stdin.$n"
exit "${STUB_CURL_RC:-0}"
""",
    "systemctl": "exit 0\n",
}

DRIVER = """\
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
export PATH="$here/bin:$PATH"
script="$1"
shift
exec bash "$script" "$@"
"""

PROXY_VARS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "no_proxy",
)
SCRUBBED_VARS = (
    "TRADING_ENV_FILE",
    "COMPOSE_PROJECT_NAME",
    "CREDENTIALS_DIRECTORY",
    "HEARTBEAT_URL_FILE",
    "HEARTBEAT_FAIL_PING",
    "HEARTBEAT_STEP_TIMEOUT_SECONDS",
    "SHELLOPTS",
    "DRY_RUN",
    "STUB_PROBE_RC",
    "STUB_CURL_RC",
)


def _write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8") if isinstance(text, str) else text
    path.write_bytes(data)
    if data.startswith(b"#!"):
        path.chmod(0o755)  # stubs must be executable on Linux; Git Bash ignores the bit
    return path


def _posix_modes() -> bool:
    return sys.platform != "win32"


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
    def url_path(self) -> Path:
        return self.prefix / "etc" / "trading" / "heartbeat.url"

    def lines(self) -> list[str]:
        if not self.log.exists():
            return []
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def docker_lines(self) -> list[str]:
        return [ln for ln in self.lines() if ln.startswith("docker ")]

    def curl_lines(self) -> list[str]:
        return [ln for ln in self.lines() if ln.startswith("curl ")]

    def curl_stdin(self, n: int = 1) -> str:
        return (self.state / f"curl-stdin.{n}").read_text(encoding="utf-8")

    def write_url(self, content: str | bytes = SENTINEL_URL + "\n", mode: int = 0o600) -> Path:
        path = _write(self.url_path, content)
        if _posix_modes():
            path.chmod(mode)
        return path

    def run(
        self, *args: str, env: dict[str, str] | None = None, script: str = "heartbeat.sh"
    ) -> subprocess.CompletedProcess[str]:
        full_env = dict(os.environ)
        for name in SCRUBBED_VARS:
            full_env.pop(name, None)
        full_env.update(
            {
                "MSYS_NO_PATHCONV": "1",
                "STUB_LOG": self.log.as_posix(),
                "STUB_STATE": self.state.as_posix(),
                "TRADING_ROOT_PREFIX": self.prefix.as_posix(),
            }
        )
        full_env.update(env or {})
        return subprocess.run(
            [self.bash, (self.base / "driver.sh").as_posix(), (DEPLOY / script).as_posix(), *args],
            capture_output=True,
            text=True,
            env=full_env,
            check=False,
            timeout=120,
        )


def _make_rig(tmp_path: Path, stubs: tuple[str, ...]) -> Rig:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; the heartbeat tests need Git Bash or Linux bash")
    probe = subprocess.run(
        [bash, "-c", "timeout --version"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0 or "GNU coreutils" not in probe.stdout:
        infra_skip("GNU coreutils timeout not found; the heartbeat script needs it")
    base = tmp_path / "rig"
    for name in stubs:
        _write(base / "bin" / name, "#!/usr/bin/env bash\n" + _LOG + STUBS[name])
    _write(base / "driver.sh", DRIVER)
    return Rig(base=base, bash=bash)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    made = _make_rig(tmp_path, ("docker", "curl", "systemctl"))
    made.write_url()
    return made


def assert_no_secret(proc: subprocess.CompletedProcess[str], made: Rig) -> None:
    """The ping URL must be absent from stdout, stderr and the whole stub log (T-16-115)."""
    blobs = {"stdout": proc.stdout, "stderr": proc.stderr, "stub log": "\n".join(made.lines())}
    for where, blob in blobs.items():
        for marker in SECRET_MARKERS:
            assert marker not in blob, f"{marker!r} leaked into the {where}:\n{blob}"


def _strip_comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def compose_lines_without_exec(text: str) -> list[str]:
    """Non-comment lines that expand the compose array without the ``exec`` subcommand."""
    return [
        ln
        for ln in _strip_comments(text).splitlines()
        if "${COMPOSE[@]}" in ln and not re.search(r"\bexec\b", ln)
    ]


# --- the tracer: one run, end to end -------------------------------------------------------------


def test_one_run_probes_the_collector_and_sends_one_ping_without_exposing_the_url(
    rig: Rig,
) -> None:
    proc = rig.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rig.docker_lines() == [PROBE_LINE]
    curl = rig.curl_lines()
    assert len(curl) == 1, curl
    assert "https://" not in curl[0] and TOKEN not in curl[0]
    config = rig.curl_stdin(1)
    assert config.count(SENTINEL_URL) == 1, config
    assert not re.search(r"/fail\b", config)
    assert_no_secret(proc, rig)


def test_a_failed_probe_without_the_flag_sends_nothing(rig: Rig) -> None:
    proc = rig.run(env={"STUB_PROBE_RC": "1"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert rig.curl_lines() == []
    message = proc.stderr.lower()
    assert "probe failed" in message and "no ping" in message
    assert_no_secret(proc, rig)


@pytest.mark.parametrize(
    ("args", "env"),
    [(["--fail-ping"], {}), ([], {"HEARTBEAT_FAIL_PING": "1"})],
    ids=["flag", "environment"],
)
def test_a_failed_probe_sends_one_fail_ping_only_when_asked(
    rig: Rig, args: list[str], env: dict[str, str]
) -> None:
    proc = rig.run(*args, env={"STUB_PROBE_RC": "1", **env})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert len(rig.curl_lines()) == 1
    config = rig.curl_stdin(1)
    assert re.search(re.escape(SENTINEL_URL) + r"/fail\"", config), config
    assert_no_secret(proc, rig)


@pytest.mark.parametrize("curl_rc", [6, 22, 28])
def test_an_undeliverable_ping_after_a_passing_probe_exits_three(rig: Rig, curl_rc: int) -> None:
    proc = rig.run(env={"STUB_CURL_RC": str(curl_rc)})
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert f"curl exit {curl_rc}" in proc.stderr
    assert_no_secret(proc, rig)


def test_a_failed_fail_ping_still_exits_with_the_probe_verdict(rig: Rig) -> None:
    proc = rig.run("--fail-ping", env={"STUB_PROBE_RC": "1", "STUB_CURL_RC": "22"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "curl exit 22" in proc.stderr
    assert_no_secret(proc, rig)


# --- fail-open for the collector (T-16-117) ------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "env"),
    [
        ([], {}),
        ([], {"STUB_PROBE_RC": "1"}),
        (["--fail-ping"], {"STUB_PROBE_RC": "1"}),
        ([], {"STUB_CURL_RC": "28"}),
        (["--dry-run"], {}),
    ],
    ids=["pass", "probe-fails", "fail-ping", "ping-fails", "dry-run"],
)
def test_the_only_docker_call_is_the_read_only_exec_probe(
    rig: Rig, args: list[str], env: dict[str, str]
) -> None:
    proc = rig.run(*args, env=env)
    assert proc.returncode in {0, 1, 3}, proc.stdout + proc.stderr
    assert all(ln.startswith("docker compose exec ") for ln in rig.docker_lines())
    assert len(rig.docker_lines()) <= 1
    assert not any(w in " ".join(rig.docker_lines()) for w in ("restart", "stop", "up", "down"))


def test_every_compose_expansion_in_the_script_is_an_exec() -> None:
    text = (DEPLOY / "heartbeat.sh").read_text(encoding="utf-8")
    assert "${COMPOSE[@]}" in text
    assert compose_lines_without_exec(text) == []


def test_the_static_check_reports_a_line_that_restarts_a_service() -> None:
    seeded = (DEPLOY / "heartbeat.sh").read_text(encoding="utf-8")
    seeded += '\nrun "${COMPOSE[@]}" restart collector\n'
    assert compose_lines_without_exec(seeded) == ['run "${COMPOSE[@]}" restart collector']


# --- where the URL comes from, and what is refused -----------------------------------------------


def test_the_systemd_credential_wins_over_every_file_source(rig: Rig, tmp_path: Path) -> None:
    cred_dir = tmp_path / "cred"
    _write(cred_dir / "heartbeat-url", OTHER_URL + "\n")
    rig.write_url(SENTINEL_URL + "\n")
    other = _write(rig.prefix / "etc" / "trading" / "other.url", SENTINEL_URL + "\n")
    if _posix_modes():
        other.chmod(0o600)
    env = {
        "CREDENTIALS_DIRECTORY": cred_dir.as_posix(),
        "HEARTBEAT_URL_FILE": "/etc/trading/other.url",
    }
    proc = rig.run("--url-file", "/etc/trading/other.url", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    config = rig.curl_stdin(1)
    assert OTHER_URL in config and TOKEN not in config


def test_the_url_file_flag_wins_over_the_environment_and_the_default(rig: Rig) -> None:
    flag = _write(rig.prefix / "etc" / "trading" / "flag.url", OTHER_URL + "\n")
    env_file = _write(rig.prefix / "etc" / "trading" / "env.url", SENTINEL_URL + "\n")
    if _posix_modes():
        flag.chmod(0o600)
        env_file.chmod(0o600)
    proc = rig.run(
        "--url-file", "/etc/trading/flag.url", env={"HEARTBEAT_URL_FILE": "/etc/trading/env.url"}
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert OTHER_URL in rig.curl_stdin(1)
    # without the flag the environment variable wins over the default path
    proc = rig.run(env={"HEARTBEAT_URL_FILE": "/etc/trading/env.url"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert SENTINEL_URL in rig.curl_stdin(2)


def test_no_url_source_exits_four_and_runs_nothing(rig: Rig) -> None:
    rig.url_path.unlink()
    proc = rig.run()
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert rig.lines() == []


def test_an_unreadable_url_source_exits_four_and_runs_nothing(rig: Rig) -> None:
    rig.url_path.unlink()
    rig.url_path.mkdir(parents=True)  # a directory is never a readable URL file
    proc = rig.run()
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert rig.lines() == []


INVALID_CONTENT = {
    "http-scheme": f"http://{SENTINEL_HOST}/{TOKEN}\n",
    "inner-whitespace": f"https://{SENTINEL_HOST}/{TOKEN} x\n",
    "double-quote": f'https://{SENTINEL_HOST}/{TOKEN}"x\n',
    "single-quote": f"https://{SENTINEL_HOST}/{TOKEN}'x\n",
    "backslash": f"https://{SENTINEL_HOST}/{TOKEN}\\x\n",
    "query": f"https://{SENTINEL_HOST}/{TOKEN}?a=b\n",
    "fragment": f"https://{SENTINEL_HOST}/{TOKEN}#f\n",
    "userinfo": f"https://user@{SENTINEL_HOST}/{TOKEN}\n",
    "two-lines": f"https://{SENTINEL_HOST}/{TOKEN}\nhttps://{SENTINEL_HOST}/{OTHER_TOKEN}\n",
    "trailing-blank-line": f"https://{SENTINEL_HOST}/{TOKEN}\n\n",
    "empty": "",
    "newline-only": "\n",
    "crlf": f"https://{SENTINEL_HOST}/{TOKEN}\r\n",
}


@pytest.mark.parametrize("name", sorted(INVALID_CONTENT))
def test_content_that_is_not_one_https_url_is_refused_and_never_echoed(rig: Rig, name: str) -> None:
    rig.write_url(INVALID_CONTENT[name].encode("utf-8"))
    proc = rig.run()
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)


@pytest.mark.skipif(not _posix_modes(), reason="file modes do not exist on Windows")
@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
def test_a_url_file_readable_by_group_or_others_is_refused(rig: Rig, mode: int) -> None:
    rig.write_url(mode=mode)
    proc = rig.run()
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)


# --- --dry-run -----------------------------------------------------------------------------------


def test_dry_run_announces_the_probe_and_the_ping_and_runs_neither(rig: Rig) -> None:
    proc = rig.run("--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert "+ timeout" in proc.stdout and "src.data.collector --healthcheck" in proc.stdout
    assert "not shown" in proc.stdout
    assert_no_secret(proc, rig)


def test_dry_run_still_refuses_an_invalid_url_source(rig: Rig) -> None:
    rig.write_url(INVALID_CONTENT["http-scheme"].encode("utf-8"))
    proc = rig.run("--dry-run")
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)


# --- xtrace would print the URL ------------------------------------------------------------------


def test_the_script_refuses_to_run_under_xtrace_before_reading_the_url(rig: Rig) -> None:
    proc = rig.run(env={"SHELLOPTS": "xtrace"})
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)


# --- usage ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--definitely-not-a-flag"], {}),
        (["--url-file"], {}),
        ([], {"HEARTBEAT_FAIL_PING": "2"}),
        ([], {"HEARTBEAT_FAIL_PING": "yes"}),
        ([], {"HEARTBEAT_STEP_TIMEOUT_SECONDS": "0"}),
        ([], {"HEARTBEAT_STEP_TIMEOUT_SECONDS": "-1"}),
        ([], {"HEARTBEAT_STEP_TIMEOUT_SECONDS": "1.5"}),
        ([], {"HEARTBEAT_STEP_TIMEOUT_SECONDS": "abc"}),
    ],
)
def test_a_usage_error_exits_two_and_runs_nothing(
    rig: Rig, args: list[str], env: dict[str, str]
) -> None:
    proc = rig.run(*args, env=env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)


# --- the real curl, loopback only ----------------------------------------------------------------


def _closed_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_the_real_curl_accepts_the_option_set_and_reports_a_refused_connection(
    tmp_path: Path,
) -> None:
    if shutil.which("curl") is None:
        infra_skip("curl not found; the loopback test runs the real option set")
    made = _make_rig(tmp_path, ("docker", "systemctl"))  # no curl stub: the real one runs
    url = f"https://127.0.0.1:{_closed_loopback_port()}/{TOKEN}"
    made.write_url(url + "\n")
    env = {name: "" for name in PROXY_VARS}
    for name in PROXY_VARS:
        env[name] = ""
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    proc = made.run(env=env)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "curl exit 7" in proc.stderr, proc.stderr
    for blob in (proc.stdout, proc.stderr, "\n".join(made.lines())):
        assert TOKEN not in blob and "127.0.0.1" not in blob
