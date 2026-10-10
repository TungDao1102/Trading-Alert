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
        self,
        *args: str,
        env: dict[str, str] | None = None,
        script: str = "heartbeat.sh",
        stdin: str | None = None,
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
        raw = subprocess.run(
            [self.bash, (self.base / "driver.sh").as_posix(), (DEPLOY / script).as_posix(), *args],
            capture_output=True,
            env=full_env,
            check=False,
            timeout=120,
            # bytes in, bytes out: text mode would turn the newline of the piped URL into CRLF
            input=(stdin or "").encode("utf-8"),
        )
        return subprocess.CompletedProcess(
            raw.args,
            raw.returncode,
            raw.stdout.decode("utf-8", errors="replace"),
            raw.stderr.decode("utf-8", errors="replace"),
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


# === Task 2: secret storage, timer installation and the unit templates ============================

SERVICE = "trading-heartbeat.service"
TIMER = "trading-heartbeat.timer"
INTERVAL = "123"  # an arbitrary test value, not a recommendation


def _unit_dir(made: Rig) -> Path:
    return made.prefix / "etc" / "systemd" / "system"


def _systemctl(made: Rig) -> list[str]:
    return [ln for ln in made.lines() if ln.startswith("systemctl ")]


def _checkout_as_bash_sees_it(made: Rig) -> str:
    out = subprocess.run(
        [made.bash, "-c", 'cd "$1" && pwd', "_", REPO_ROOT.as_posix()],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _directive_lines(text: str) -> list[str]:
    return [ln.strip() for ln in _strip_comments(text).splitlines() if ln.strip()]


# --- --set-url -----------------------------------------------------------------------------------


def test_set_url_stores_the_line_from_stdin_with_mode_0600_and_never_shows_it(rig: Rig) -> None:
    rig.url_path.unlink()
    proc = rig.run("--set-url", stdin=SENTINEL_URL + "\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rig.url_path.read_text(encoding="utf-8").strip() == SENTINEL_URL
    assert f"+ write {rig.url_path.as_posix()}" in proc.stdout
    assert "stored" in proc.stderr and "not shown" in proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)
    if _posix_modes():
        assert rig.url_path.stat().st_mode & 0o777 == 0o600


def test_set_url_twice_with_the_same_value_writes_nothing_the_second_time(rig: Rig) -> None:
    rig.url_path.unlink()
    assert rig.run("--set-url", stdin=SENTINEL_URL + "\n").returncode == 0
    again = rig.run("--set-url", stdin=SENTINEL_URL + "\n")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "+ write " not in again.stdout
    assert_no_secret(again, rig)


def test_set_url_honours_the_url_file_flag(rig: Rig) -> None:
    proc = rig.run("--set-url", "--url-file", "/etc/trading/custom.url", stdin=OTHER_URL + "\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    custom = rig.prefix / "etc" / "trading" / "custom.url"
    assert custom.read_text(encoding="utf-8").strip() == OTHER_URL
    assert rig.url_path.read_text(encoding="utf-8").strip() == SENTINEL_URL  # untouched


@pytest.mark.parametrize("name", ["http-scheme", "query", "empty", "crlf"])
def test_set_url_refuses_invalid_input_and_writes_nothing(rig: Rig, name: str) -> None:
    rig.url_path.unlink()
    proc = rig.run("--set-url", stdin=INVALID_CONTENT[name])
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert not rig.url_path.exists()
    assert_no_secret(proc, rig)


def test_set_url_dry_run_writes_nothing(rig: Rig) -> None:
    rig.url_path.unlink()
    proc = rig.run("--set-url", "--dry-run", stdin=SENTINEL_URL + "\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not rig.url_path.exists()
    assert "+ write " in proc.stdout
    assert_no_secret(proc, rig)


# --- no default interval -------------------------------------------------------------------------


def _install(*extra: str) -> list[str]:
    return ["--install-timer", "--interval-seconds", INTERVAL, *extra]


@pytest.mark.parametrize(
    "args",
    [
        ["--install-timer"],
        ["--install-timer", "--interval-seconds", "0"],
        ["--install-timer", "--interval-seconds", "-1"],
        ["--install-timer", "--interval-seconds", "1.5"],
        ["--install-timer", "--interval-seconds", "abc"],
        ["--install-timer", "--interval-seconds", ""],
        ["--install-timer", "--interval-seconds"],
        ["--interval-seconds", INTERVAL],
        ["--set-url", "--install-timer", "--interval-seconds", INTERVAL],
        _install("--url-file", "relative/heartbeat.url"),
        _install("--url-file", "/etc/tr ading/x.url"),
        _install("--url-file", "/etc/tr%ading/x.url"),
        _install("--url-file", "/etc/tr@ding/x.url"),
    ],
)
def test_install_timer_without_a_valid_operator_interval_is_a_usage_error(
    rig: Rig, args: list[str]
) -> None:
    proc = rig.run(*args, stdin=SENTINEL_URL + "\n")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert not (rig.prefix / "etc" / "systemd").exists()


# --- --install-timer -----------------------------------------------------------------------------


def test_install_timer_writes_both_units_and_enables_the_timer(rig: Rig) -> None:
    proc = rig.run(*_install())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    service = (_unit_dir(rig) / SERVICE).read_text(encoding="utf-8")
    timer = (_unit_dir(rig) / TIMER).read_text(encoding="utf-8")
    checkout = _checkout_as_bash_sees_it(rig)
    for text in (service, timer):
        assert "@" not in text.replace("@@", ""), "a substitution token was left behind"
    lines = service.splitlines()
    assert f"WorkingDirectory={checkout}" in lines
    assert f"ExecStart=/usr/bin/env bash {checkout}/deploy/heartbeat.sh" in lines
    assert "LoadCredential=heartbeat-url:/etc/trading/heartbeat.url" in lines
    assert "Environment=HEARTBEAT_FAIL_PING=0" in lines
    assert f"OnBootSec={INTERVAL}s" in timer.splitlines()
    assert f"OnUnitActiveSec={INTERVAL}s" in timer.splitlines()
    assert _systemctl(rig) == [
        "systemctl daemon-reload",
        f"systemctl enable --now {TIMER}",
        f"systemctl restart {TIMER}",
    ]
    assert rig.docker_lines() == [] and rig.curl_lines() == []


def test_install_timer_with_fail_ping_and_a_custom_url_file_bakes_both_into_the_service(
    rig: Rig,
) -> None:
    custom = _write(rig.prefix / "opt" / "secrets" / "hb.url", SENTINEL_URL + "\n")
    if _posix_modes():
        custom.chmod(0o600)
    proc = rig.run(*_install("--fail-ping", "--url-file", "/opt/secrets/hb.url"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    service = (_unit_dir(rig) / SERVICE).read_text(encoding="utf-8").splitlines()
    assert "Environment=HEARTBEAT_FAIL_PING=1" in service
    assert "LoadCredential=heartbeat-url:/opt/secrets/hb.url" in service


def test_a_second_identical_install_writes_nothing_but_still_enables_the_timer(rig: Rig) -> None:
    assert rig.run(*_install()).returncode == 0
    before = len(rig.lines())
    second = rig.run(*_install())
    assert second.returncode == 0, second.stdout + second.stderr
    assert "+ write " not in second.stdout
    assert rig.lines()[before:] == [f"systemctl enable --now {TIMER}"]


def test_a_different_interval_rewrites_the_timer_and_restarts_it(rig: Rig) -> None:
    assert rig.run(*_install()).returncode == 0
    before = len(rig.lines())
    proc = rig.run("--install-timer", "--interval-seconds", "456")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("+ write ") == 1
    assert "OnBootSec=456s" in (_unit_dir(rig) / TIMER).read_text(encoding="utf-8")
    assert rig.lines()[before:] == [
        "systemctl daemon-reload",
        f"systemctl enable --now {TIMER}",
        f"systemctl restart {TIMER}",
    ]


def test_install_timer_dry_run_changes_nothing_and_announces_the_writes(rig: Rig) -> None:
    proc = rig.run(*_install("--dry-run"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (rig.prefix / "etc" / "systemd").exists()
    assert rig.lines() == []
    assert proc.stdout.count("+ write ") == 2


def test_install_timer_needs_the_url_file_first_but_a_dry_run_only_warns(rig: Rig) -> None:
    rig.url_path.unlink()
    real = rig.run(*_install())
    assert real.returncode != 0, real.stdout + real.stderr
    assert "--set-url" in real.stderr
    assert not (rig.prefix / "etc" / "systemd").exists()
    assert rig.lines() == []
    dry = rig.run(*_install("--dry-run"))
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "--set-url" in dry.stderr


# --- the unit templates --------------------------------------------------------------------------

LINK_DIRECTIVE = re.compile(
    r"^(Requires|Requisite|BindsTo|PartOf|Conflicts|Restart|OnFailure|OnSuccess|Upholds)\w*\s*=",
    re.IGNORECASE,
)


def test_the_service_is_a_oneshot_with_no_link_to_the_collector() -> None:
    lines = _directive_lines((UNITS / SERVICE).read_text(encoding="utf-8"))
    assert "Type=oneshot" in lines and "User=trading" in lines
    assert "Wants=network-online.target" in lines
    after = [ln for ln in lines if ln.startswith("After=")]
    assert after and "network-online.target" in after[0] and "docker.service" in after[0]
    assert [ln for ln in lines if LINK_DIRECTIVE.match(ln)] == []
    assert "WorkingDirectory=@TRADING_DIR@" in lines
    assert "LoadCredential=heartbeat-url:@URL_FILE@" in lines
    assert "ExecStart=/usr/bin/env bash @TRADING_DIR@/deploy/heartbeat.sh" in lines


def test_the_timer_has_no_catch_up_no_random_delay_and_a_tokenised_interval() -> None:
    text = (UNITS / TIMER).read_text(encoding="utf-8")
    lines = _directive_lines(text)
    assert [
        ln for ln in lines if re.match(r"^(Persistent|RandomizedDelaySec|OnCalendar)", ln)
    ] == []
    assert "OnBootSec=@INTERVAL_SECONDS@s" in lines
    assert "OnUnitActiveSec=@INTERVAL_SECONDS@s" in lines
    assert f"Unit={SERVICE}" in lines and "WantedBy=timers.target" in lines
    raw = text.splitlines()
    idx = next(i for i, ln in enumerate(raw) if ln.startswith("AccuracySec="))
    assert "STRUCTURAL" in raw[idx - 1] or "STRUCTURAL" in raw[idx]


def test_neither_the_units_nor_the_script_hold_a_url_or_a_monitor_host_name() -> None:
    script = _strip_comments((DEPLOY / "heartbeat.sh").read_text(encoding="utf-8"))
    literal = [ln for ln in script.splitlines() if "https://" in ln or "http://" in ln]
    assert len(literal) == 1 and literal[0].startswith("URL_PATTERN="), literal
    for path in (DEPLOY / "heartbeat.sh", UNITS / SERVICE, UNITS / TIMER):
        text = path.read_text(encoding="utf-8").lower()
        for banned in ("hc-ping", "healthchecks.io", "uuid"):
            assert banned not in text, f"{path.name} names {banned!r}"
    for path in (UNITS / SERVICE, UNITS / TIMER):
        assert "://" not in path.read_text(encoding="utf-8")


def test_the_heartbeat_units_do_not_collide_with_the_backup_units() -> None:
    assert (UNITS / "trading-backup.service").exists() and (UNITS / "trading-backup.timer").exists()
    for name in (SERVICE, TIMER):
        assert (UNITS / name).exists()
        assert "trading-backup" not in (UNITS / name).read_text(encoding="utf-8")


# --- the secret survives the whole path ----------------------------------------------------------


def test_the_url_is_in_no_unit_file_and_no_output_across_set_url_install_and_run(
    rig: Rig,
) -> None:
    rig.url_path.unlink()
    steps = [
        rig.run("--set-url", stdin=SENTINEL_URL + "\n"),
        rig.run(*_install()),
        rig.run(),
    ]
    for proc in steps:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert_no_secret(proc, rig)
    for unit in (SERVICE, TIMER):
        text = (_unit_dir(rig) / unit).read_text(encoding="utf-8")
        assert not any(marker in text for marker in SECRET_MARKERS)
