"""Behavioural tests for ``deploy/bootstrap.sh`` through real bash with stub binaries (13.1-05).

The real script runs under Git Bash (Windows) or bash (Linux CI). Every system binary it
touches (apt-get, ufw, sshd, systemctl, useradd, ...) is a tiny stub first on PATH, and every
absolute system path is redirected under ``TRADING_ROOT_PREFIX`` (a temp tree). Stubs append
their argv to a log and print canned output selected by environment variables, so the tests
assert both what the script decided and in which order it called things. A driver script
prepends the stub directory to PATH from inside bash, so Windows path conversion never
matters.

Real-host effects (an actual ufw enable, sshd reload, chrony sync, Docker apt repository) are
not reachable from here; they are listed as host-only checks in the runbook.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = REPO_ROOT / "deploy" / "bootstrap.sh"

VALID_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForTestsOnlyNotARealKeyXXXXXXXX op@laptop"
SECRET_PASSWORD = "Zq8vN2pLr7XwK4mTb9HcYd3Fe6"  # unique marker; must never be echoed


def _os_release(os_id: str, version: str, codename: str, *, ubuntu: bool = False) -> str:
    text = f'ID={os_id}\nVERSION_ID="{version}"\nVERSION_CODENAME={codename}\n'
    if ubuntu:
        text += f"UBUNTU_CODENAME={codename}\n"
    return text


OS_RELEASES = {
    "ubuntu-22.04": _os_release("ubuntu", "22.04", "jammy", ubuntu=True),
    "ubuntu-24.04": _os_release("ubuntu", "24.04", "noble", ubuntu=True),
    "debian-12": _os_release("debian", "12", "bookworm"),
    "ubuntu-20.04": _os_release("ubuntu", "20.04", "focal", ubuntu=True),
    "debian-11": _os_release("debian", "11", "bullseye"),
    "fedora-40": 'ID=fedora\nVERSION_ID="40"\n',
}

TRACKING_GOOD = """\
Reference ID    : A9FEA97B (169.254.169.123)
Stratum         : 4
Ref time (UTC)  : Thu Oct 01 08:00:00 2026
System time     : 0.000045000 seconds fast of NTP time
Last offset     : +0.000012000 seconds
RMS offset      : 0.000030000 seconds
Frequency       : 1.234 ppm slow
Leap status     : Normal
"""

# --- stub binaries -------------------------------------------------------------------------

_LOG = r"""
printf '%s\n' "${0##*/} $*" >> "${STUB_LOG:?}"
"""

STUBS: dict[str, str] = {
    "apt-get": "",
    "usermod": r"""
if [ "${1:-}" = "-aG" ] && [ "${STUB_USERMOD_NOOP:-0}" != "1" ] && [ -n "${STUB_STATE:-}" ]; then
  mkdir -p "$STUB_STATE"
  printf '%s\n' "${2:-}" >> "$STUB_STATE/groups"
fi
""",
    "useradd": r"""
if [ -n "${STUB_STATE:-}" ]; then
  mkdir -p "$STUB_STATE"
  : > "$STUB_STATE/user_created"
fi
""",
    "passwd": r"""
if [ "${1:-}" = "-S" ] && [ -n "${2:-}" ]; then
  st="${STUB_PASSWD_STATUS:-P}"
  if [ "$st" = "UNREADABLE" ]; then exit 1; fi
  echo "$2 $st 2026-10-07 0 99999 7 -1"
  exit 0
fi
exit 2
""",
    "chown": "",
    "dpkg": r"""
if [ "${1:-}" = "--print-architecture" ]; then echo "${STUB_ARCH:-amd64}"; fi
""",
    "dpkg-query": r"""
pkg="${*: -1}"
if [ "${STUB_INSTALLED:-}" = "ALL" ] || [[ " ${STUB_INSTALLED:-} " == *" $pkg "* ]]; then
  printf 'install ok installed'
  exit 0
fi
echo "dpkg-query: no packages found matching $pkg" >&2
exit 1
""",
    "getent": r"""
if [ "${STUB_USER_EXISTS:-0}" = "1" ] || [ -f "${STUB_STATE:-/nonexistent}/user_created" ]; then
  echo "${2:-trading}:x:1000:1000::/home/${2:-trading}:/bin/bash"
  exit 0
fi
exit 2
""",
    "id": r"""
case "${1:-}" in
  -u) echo "${STUB_UID:-0}" ;;
  -nG)
    if [ "${STUB_USER_EXISTS:-0}" = "1" ] || [ -f "${STUB_STATE:-/nonexistent}/user_created" ]; then
      extra=""
      if [ -f "${STUB_STATE:-/nonexistent}/groups" ]; then
        extra=" $(tr '\n' ' ' < "$STUB_STATE/groups")"
      fi
      echo "${STUB_GROUPS:-trading}$extra"
    else
      exit 1
    fi
    ;;
esac
""",
    "ssh-keygen": r"""
file="${*: -1}"
if grep -Eq '^ssh-(ed25519|rsa) AAAA[A-Za-z0-9+/=]+' "$file"; then
  echo "256 SHA256:stub op (ED25519)"
  exit 0
fi
echo "$file is not a public key file." >&2
exit 255
""",
    "curl": r"""
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; shift; fi
  shift
done
if [ -n "$out" ]; then printf 'FAKE-DOCKER-GPG-KEY\n' > "$out"; fi
""",
    "install": r"""
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -o | -g) shift 2 ;;
    -m)
      case "$(uname -s)" in
        MINGW* | MSYS*) shift 2 ;;
        *) args+=("$1" "$2"); shift 2 ;;
      esac
      ;;
    *) args+=("$1"); shift ;;
  esac
done
exec /usr/bin/install "${args[@]}"
""",
    "ufw": r"""
if [ "${1:-}" = "status" ]; then
  if [ "${STUB_UFW_ACTIVE:-0}" = "1" ]; then
    printf 'Status: active\nDefault: deny (incoming), allow (outgoing), disabled (routed)\n\n'
    printf 'To                         Action      From\n'
    printf '%s/tcp                     ALLOW IN    Anywhere\n' "${STUB_SSH_PORT:-22}"
  else
    printf 'Status: inactive\n'
  fi
fi
""",
    "sshd": r"""
if [ "${1:-}" = "-t" ]; then exit "${STUB_SSHD_T_RC:-0}"; fi
if [ "${1:-}" = "-T" ]; then
  dropin="${TRADING_ROOT_PREFIX:-}/etc/ssh/sshd_config.d/00-trading-hardening.conf"
  echo "port ${STUB_SSH_PORT:-22}"
  echo "pubkeyauthentication yes"
  if [ -f "$dropin" ] && [ "${STUB_SSHD_IGNORE_DROPIN:-0}" != "1" ]; then
    printf 'passwordauthentication no\nkbdinteractiveauthentication no\n'
    printf 'permitrootlogin no\n'
  else
    printf 'passwordauthentication yes\nkbdinteractiveauthentication yes\n'
    printf 'permitrootlogin yes\n'
  fi
fi
""",
    "systemctl": r"""
if [ "${1:-}" = "is-enabled" ]; then
  if [[ " ${STUB_ENABLED:-} " == *" ${2:-} "* ]]; then echo enabled; exit 0; fi
  echo disabled
  exit 1
fi
""",
    "chronyc": r"""
if [ "${1:-}" = "tracking" ]; then
  if [ -n "${STUB_TRACKING_FILE:-}" ] && [ -f "$STUB_TRACKING_FILE" ]; then
    cat "$STUB_TRACKING_FILE"
    exit 0
  fi
  exit 1
fi
if [ "${1:-}" = "waitsync" ]; then exit "${STUB_WAITSYNC_RC:-0}"; fi
""",
    "git": r"""
args=("$@")
if [ "${args[0]:-}" = "-C" ]; then args=("${args[@]:2}"); fi
case "${args[0]:-}" in
  rev-parse)
    if [ "${args[1]:-}" = "HEAD" ]; then
      echo "${STUB_GIT_HEAD:-}"
    else
      echo "${STUB_GIT_REF_COMMIT:-}"
    fi
    ;;
  clone) mkdir -p "${*: -1}/.git" ;;
esac
""",
    "runuser": r"""
while [ $# -gt 0 ] && [ "$1" != "--" ]; do shift; done
shift
exec "$@"
""",
}

DRIVER = """\
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
export PATH="$here/bin:$PATH"
exec bash "${BOOTSTRAP_SCRIPT:?}" "$@"
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    if text.startswith("#!"):
        path.chmod(0o755)  # stubs must be executable on Linux; Git Bash ignores the bit
    return path


def _posix(path: Path) -> str:
    return path.as_posix()


# Argv prefixes that only read state. Everything else a stub logs counts as a mutation.
_PROBE_FIRST_WORDS = {"dpkg-query", "dpkg", "getent", "id", "ssh-keygen"}
_PROBE_PREFIXES = (
    "ufw status",
    "systemctl is-enabled",
    "sshd -T",
    "chronyc tracking",
    "passwd -S",
)


def is_mutation(line: str) -> bool:
    if line.split(" ", 1)[0] in _PROBE_FIRST_WORDS:
        return False
    if line.startswith(_PROBE_PREFIXES):
        return False
    return " rev-parse " not in line


@dataclass
class Host:
    """A temp tree plus stubs, and a way to run the real bootstrap script against it."""

    base: Path
    bash: str
    env_extra: dict[str, str] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return self.base / "root"

    @property
    def log(self) -> Path:
        return self.base / "stub.log"

    @property
    def state(self) -> Path:
        """Stub state (user created, groups added); outside ``root`` so tree() ignores it."""
        return self.base / "state"

    @property
    def secrets(self) -> Path:
        return self.base / "secrets.conf"

    @property
    def keys(self) -> Path:
        return self.base / "keys.pub"

    @property
    def tracking(self) -> Path:
        return self.base / "tracking.txt"

    def log_lines(self) -> list[str]:
        if not self.log.exists():
            return []
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def mutations(self) -> list[str]:
        return [ln for ln in self.log_lines() if is_mutation(ln)]

    def set_os(self, name: str) -> None:
        _write(self.base / "os-release", OS_RELEASES[name])

    def tree(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def args(self, *extra: str, **overrides: str | None) -> list[str]:
        """Default argument vector; ``overrides`` replace a flag value or drop it (None)."""
        flags = {
            "--secrets-file": _posix(self.secrets),
            "--repo": "https://example.invalid/trading.git",
            "--ref": "v1.0.0",
            "--authorized-keys": _posix(self.keys),
            "--max-drift-ms": "100",
        }
        for name, value in overrides.items():
            flag = "--" + name.replace("_", "-")
            if value is None:
                flags.pop(flag, None)
            else:
                flags[flag] = value
        out: list[str] = []
        for flag, value in flags.items():
            out += [flag, value]
        return out + list(extra)

    def run(
        self, args: list[str], env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        full_env = dict(os.environ)
        full_env.update(
            {
                "MSYS_NO_PATHCONV": "1",
                "BOOTSTRAP_SCRIPT": _posix(BOOTSTRAP),
                "STUB_LOG": _posix(self.log),
                "STUB_STATE": _posix(self.state),
                "TRADING_ROOT_PREFIX": _posix(self.root),
                "OS_RELEASE_FILE": _posix(self.base / "os-release"),
                "STUB_TRACKING_FILE": _posix(self.tracking),
                "STUB_UID": "0",
            }
        )
        full_env.update(self.env_extra)
        if env:
            full_env.update(env)
        return subprocess.run(
            [self.bash, _posix(self.base / "driver.sh"), *args],
            capture_output=True,
            text=True,
            env=full_env,
            check=False,
            timeout=120,
        )


def build_host(base: Path, bash: str) -> Host:
    h = Host(base=base, bash=bash)
    for name, body in STUBS.items():
        _write(base / "bin" / name, "#!/usr/bin/env bash\n" + _LOG + body)
    _write(base / "driver.sh", DRIVER)
    (base / "state").mkdir(parents=True, exist_ok=True)
    h.set_os("ubuntu-24.04")
    _write(
        h.secrets,
        "POSTGRES_USER=trading\n"
        f"POSTGRES_PASSWORD={SECRET_PASSWORD}\n"
        "POSTGRES_DB=trading\n"
        "# a comment\n",
    )
    _write(h.keys, f"# operator key\n{VALID_KEY}\n")
    _write(h.tracking, TRACKING_GOOD)
    _write(
        h.root / "etc" / "ssh" / "sshd_config",
        "Include /etc/ssh/sshd_config.d/*.conf\nPort 22\nUsePAM yes\n",
    )
    (h.root / "etc" / "ssh" / "sshd_config.d").mkdir(parents=True, exist_ok=True)
    return h


def _need_bash() -> str:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; bootstrap tests need Git Bash or Linux bash")
    return bash


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return build_host(tmp_path / "host", _need_bash())


@dataclass
class Golden:
    """One shared successful first run on a fresh host, plus cheap idempotent re-runs.

    Most per-step assertions only inspect what that first run did, so they share it instead
    of paying for a dozen identical bash runs (each costs seconds under Git Bash on Windows).
    """

    host: Host
    proc: subprocess.CompletedProcess[str]
    first_run_lines: list[str]

    def rerun(self, *, dry_run: bool = False) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Run again against the configured state; return the output and only the new log."""
        before = len(self.host.log_lines())
        args = self.host.args(*(["--dry-run"] if dry_run else []))
        proc = self.host.run(args, env=dict(CONFIGURED_ENV))
        return proc, self.host.log_lines()[before:]


@pytest.fixture(scope="module")
def golden(tmp_path_factory: pytest.TempPathFactory) -> Golden:
    h = build_host(tmp_path_factory.mktemp("golden") / "host", _need_bash())
    proc = h.run(h.args(), env={"STUB_ENABLED": "systemd-timesyncd"})
    assert proc.returncode == 0, proc.stderr
    return Golden(host=h, proc=proc, first_run_lines=h.log_lines())


def assert_in_order(text: str, markers: list[str]) -> None:
    pos = 0
    for marker in markers:
        idx = text.find(marker, pos)
        assert idx >= 0, f"marker {marker!r} not found (in order) after offset {pos} in:\n{text}"
        pos = idx + len(marker)


# --- Task 1: preflight, OS matrix, anti lock-out guard, dry-run plan -------------------------


@pytest.mark.parametrize("release", ["ubuntu-22.04", "ubuntu-24.04", "debian-12"])
def test_supported_os_accepts_dry_run(host: Host, release: str) -> None:
    host.set_os(release)
    proc = host.run(host.args("--dry-run"))
    assert proc.returncode == 0, proc.stderr
    assert "+ " in proc.stdout


@pytest.mark.parametrize("release", ["ubuntu-20.04", "debian-11", "fedora-40"])
def test_unsupported_os_is_refused_before_anything_runs(host: Host, release: str) -> None:
    host.set_os(release)
    proc = host.run(host.args("--dry-run"))
    assert proc.returncode != 0
    assert "unsupported" in proc.stderr.lower()
    assert host.log_lines() == []


def test_unsupported_os_is_refused_in_real_mode_too(host: Host) -> None:
    host.set_os("fedora-40")
    proc = host.run(host.args())
    assert proc.returncode != 0
    assert "unsupported" in proc.stderr.lower()
    assert host.mutations() == []


@pytest.mark.parametrize("state", ["missing", "empty", "garbage"])
def test_lockout_guard_blocks_before_any_step(host: Host, state: str) -> None:
    keys = host.base / "bad_keys.pub"
    if state == "empty":
        _write(keys, "")
    elif state == "garbage":
        _write(keys, "this is not a public key\nssh-rsa nonsense\n")
    proc = host.run(host.args(authorized_keys=_posix(keys)))
    assert proc.returncode != 0
    assert "lock-out" in proc.stderr.lower()
    assert host.mutations() == []
    assert not (host.root / "etc" / "ssh" / "sshd_config.d" / "00-trading-hardening.conf").exists()


def test_lockout_guard_without_flag_and_without_existing_target_keys(host: Host) -> None:
    proc = host.run(host.args(authorized_keys=None))
    assert proc.returncode != 0
    assert "lock-out" in proc.stderr.lower()
    assert host.mutations() == []


def test_existing_target_user_keys_satisfy_the_guard(host: Host) -> None:
    _write(host.root / "home" / "trading" / ".ssh" / "authorized_keys", VALID_KEY + "\n")
    proc = host.run(host.args("--dry-run", authorized_keys=None))
    assert proc.returncode == 0, proc.stderr


def test_dry_run_prints_the_ordered_plan_and_ends_with_the_checklist(host: Host) -> None:
    proc = host.run(host.args("--dry-run"))
    assert proc.returncode == 0, proc.stderr
    assert_in_order(
        proc.stdout,
        [
            "+ apt-get update",
            "+ apt-get install -y ca-certificates",
            "docker.sources",
            "install -y docker-ce",
            "+ useradd",
            "+ usermod -aG docker",
            "+ usermod -aG sudo",
            "+ ufw allow",
            "+ ufw --force enable",
            "lock-out guard would require",
            "00-trading-hardening.conf",
            "+ sshd -t",
            "+ systemctl try-reload-or-restart ssh",
            "+ apt-get install -y chrony",
            "git clone",
            "install -m 0600",
            "Operator checklist",
        ],
    )


def test_dry_run_changes_nothing(host: Host) -> None:
    before = host.tree()
    proc = host.run(host.args("--dry-run"))
    assert proc.returncode == 0, proc.stderr
    assert host.tree() == before
    assert host.mutations() == []


def test_unknown_flag_dies(host: Host) -> None:
    proc = host.run(host.args("--no-such-flag"))
    assert proc.returncode != 0
    assert "unknown" in proc.stderr.lower()
    assert host.log_lines() == []


def test_missing_ref_dies(host: Host) -> None:
    proc = host.run(host.args("--dry-run", ref=None))
    assert proc.returncode != 0
    assert "--ref" in proc.stderr
    assert host.mutations() == []


def test_real_mode_requires_root(host: Host) -> None:
    proc = host.run(host.args(), env={"STUB_UID": "1000"})
    assert proc.returncode != 0
    assert "root" in proc.stderr.lower()
    assert host.mutations() == []


# --- Task 2: Docker repository, trading user, ufw, SSH hardening -------------------------------

DOCKER_PACKAGES = "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
DROPIN_REL = Path("etc/ssh/sshd_config.d/00-trading-hardening.conf")
CONFIGURED_ENV = {
    "STUB_INSTALLED": "ALL",
    "STUB_USER_EXISTS": "1",
    "STUB_GROUPS": "trading docker sudo",
    "STUB_UFW_ACTIVE": "1",
    "STUB_ENABLED": "chrony docker",
    "STUB_GIT_HEAD": "0123abc",
    "STUB_GIT_REF_COMMIT": "0123abc",
}


def first_index(lines: list[str], prefix: str) -> int:
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            return idx
    raise AssertionError(f"no logged call starting with {prefix!r} in:\n" + "\n".join(lines))


def has_call(lines: list[str], prefix: str) -> bool:
    return any(line.startswith(prefix) for line in lines)


def real_run(host: Host, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
    return host.run(host.args(*extra), env=dict(env))


def assert_docker_repo(host: Host, distro: str, codename: str, lines: list[str]) -> None:
    sources = host.root / "etc" / "apt" / "sources.list.d" / "docker.sources"
    assert sources.read_text(encoding="utf-8") == (
        "Types: deb\n"
        f"URIs: https://download.docker.com/linux/{distro}\n"
        f"Suites: {codename}\n"
        "Components: stable\n"
        "Architectures: amd64\n"
        "Signed-By: /etc/apt/keyrings/docker.asc\n"
    )
    gpg_url = f"download.docker.com/linux/{distro}/gpg"
    assert any(gpg_url in ln for ln in lines if ln.startswith("curl"))
    assert (host.root / "etc" / "apt" / "keyrings" / "docker.asc").is_file()
    assert has_call(lines, f"apt-get install -y {DOCKER_PACKAGES}")


def test_docker_repository_is_written_in_deb822_form_for_ubuntu(golden: Golden) -> None:
    assert_docker_repo(golden.host, "ubuntu", "noble", golden.first_run_lines)


def test_docker_repository_is_written_in_deb822_form_for_debian(host: Host) -> None:
    host.set_os("debian-12")
    proc = real_run(host)
    assert proc.returncode == 0, proc.stderr
    assert_docker_repo(host, "debian", "bookworm", host.log_lines())


def test_docker_step_is_a_noop_when_repo_and_packages_are_present(golden: Golden) -> None:
    proc, new_lines = golden.rerun()
    assert proc.returncode == 0, proc.stderr
    assert not has_call(new_lines, "curl")
    assert not any("docker" in ln for ln in new_lines if ln.startswith("apt-get"))
    assert "docker.sources" not in proc.stdout


def test_user_step_creates_user_group_and_keys(golden: Golden) -> None:
    lines = golden.first_run_lines
    assert has_call(lines, "useradd --create-home --shell /bin/bash trading")
    assert has_call(lines, "usermod -aG docker trading")
    assert any(ln.startswith("install -d -m 0700 -o trading -g trading") for ln in lines)
    keys = golden.host.root / "home" / "trading" / ".ssh" / "authorized_keys"
    assert VALID_KEY in keys.read_text(encoding="utf-8")
    assert any(ln.startswith("chown trading:trading") and "authorized_keys" in ln for ln in lines)


def test_user_step_skips_existing_user_and_docker_membership(host: Host) -> None:
    proc = real_run(host, **CONFIGURED_ENV)
    assert proc.returncode == 0, proc.stderr
    lines = host.log_lines()
    assert not has_call(lines, "useradd")
    assert not has_call(lines, "usermod")


def test_user_step_adds_group_only_when_user_exists_without_it(host: Host) -> None:
    proc = real_run(host, STUB_USER_EXISTS="1", STUB_GROUPS="trading")
    assert proc.returncode == 0, proc.stderr
    lines = host.log_lines()
    assert not has_call(lines, "useradd")
    assert has_call(lines, "usermod -aG docker trading")


def test_existing_authorized_keys_are_kept_when_new_keys_are_merged(host: Host) -> None:
    existing = host.root / "home" / "trading" / ".ssh" / "authorized_keys"
    _write(existing, "ssh-rsa AAAAB3NzaC1yc2EOLDKEYxxxxxxxxxxxxxxxxxxxxxxxxxxxx old@box\n")
    proc = real_run(host)
    assert proc.returncode == 0, proc.stderr
    text = existing.read_text(encoding="utf-8")
    assert "old@box" in text
    assert VALID_KEY in text


def test_ufw_allows_the_effective_ssh_port_before_enabling(host: Host) -> None:
    proc = real_run(host, STUB_SSH_PORT="2222")
    assert proc.returncode == 0, proc.stderr
    lines = host.log_lines()
    allow = first_index(lines, "ufw allow 2222/tcp")
    enable = first_index(lines, "ufw --force enable")
    deny = first_index(lines, "ufw default deny incoming")
    assert deny < enable
    assert first_index(lines, "ufw default allow outgoing") < enable
    # WR-13: the SSH allow rule exists before the default flips to deny, so a re-run on an
    # already active firewall never drops new SSH connections between the two commands.
    assert allow < deny < enable
    assert not has_call(lines, "ufw allow 22/tcp")


def test_ufw_runs_after_the_user_step_and_before_the_ssh_drop_in(golden: Golden) -> None:
    lines = golden.first_run_lines
    assert first_index(lines, "usermod") < first_index(lines, "ufw --force enable")
    assert first_index(lines, "ufw --force enable") < first_index(lines, "sshd -t")


def test_ufw_is_a_noop_when_already_active_with_the_rule(host: Host) -> None:
    proc = real_run(host, **CONFIGURED_ENV)
    assert proc.returncode == 0, proc.stderr
    lines = host.log_lines()
    assert not any(ln.startswith("ufw") and not ln.startswith("ufw status") for ln in lines)


def test_ssh_drop_in_is_written_validated_asserted_and_reloaded(golden: Golden) -> None:
    content = (golden.host.root / DROPIN_REL).read_text(encoding="utf-8")
    for line in (
        "PasswordAuthentication no",
        "KbdInteractiveAuthentication no",
        "PermitRootLogin no",
        "PubkeyAuthentication yes",
    ):
        assert line in content.splitlines()
    lines = golden.first_run_lines
    validate = first_index(lines, "sshd -t")
    reload_ = first_index(lines, "systemctl try-reload-or-restart ssh")
    effective = max(i for i, ln in enumerate(lines) if ln.startswith("sshd -T"))
    assert validate < effective < reload_
    assert "second ssh session" in (golden.proc.stdout + golden.proc.stderr).lower()


def test_ssh_step_refuses_without_the_include_line(host: Host) -> None:
    _write(host.root / "etc" / "ssh" / "sshd_config", "Port 22\nUsePAM yes\n")
    proc = real_run(host)
    assert proc.returncode != 0
    assert "include" in proc.stderr.lower()
    assert not (host.root / DROPIN_REL).exists()
    assert not has_call(host.log_lines(), "systemctl try-reload-or-restart")


def test_ssh_drop_in_is_removed_when_the_effective_config_is_not_hardened(host: Host) -> None:
    proc = real_run(host, STUB_SSHD_IGNORE_DROPIN="1")
    assert proc.returncode != 0
    assert "passwordauthentication" in proc.stderr.lower()
    assert not (host.root / DROPIN_REL).exists()
    assert not has_call(host.log_lines(), "systemctl try-reload-or-restart")


def test_ssh_drop_in_is_removed_when_sshd_t_fails(host: Host) -> None:
    proc = real_run(host, STUB_SSHD_T_RC="1")
    assert proc.returncode != 0
    assert not (host.root / DROPIN_REL).exists()
    assert not has_call(host.log_lines(), "systemctl try-reload-or-restart")


# --- WR-05 (D062): trading user joins sudo with a password; the lock-out guard fails closed ---


def test_user_step_adds_the_trading_user_to_the_sudo_group(golden: Golden) -> None:
    lines = golden.first_run_lines
    install = first_index(lines, "apt-get install -y ca-certificates curl git ufw sudo")
    add = first_index(lines, "usermod -aG sudo trading")
    assert install < add < first_index(lines, "sshd -t")
    assert (golden.host.root / DROPIN_REL).is_file()


def test_sudo_group_is_not_re_added_on_a_configured_host(host: Host) -> None:
    proc = real_run(host, **CONFIGURED_ENV)
    assert proc.returncode == 0, proc.stderr
    lines = host.log_lines()
    assert not has_call(lines, "usermod -aG sudo")
    assert not any(ln.startswith("apt-get install") and "sudo" in ln for ln in lines)


def assert_sudo_guard_refused(host: Host, proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode != 0
    assert "lock-out guard" in proc.stderr
    assert not (host.root / DROPIN_REL).exists()
    lines = host.log_lines()
    assert not has_call(lines, "sshd -t")
    assert not has_call(lines, "systemctl try-reload-or-restart")


@pytest.mark.parametrize("status", ["L", "NP", "UNREADABLE"])
def test_sudo_guard_refuses_an_account_without_a_usable_password(host: Host, status: str) -> None:
    proc = real_run(host, STUB_PASSWD_STATUS=status)
    assert_sudo_guard_refused(host, proc)
    assert "passwd trading" in proc.stderr
    assert "again" in proc.stderr
    assert has_call(host.log_lines(), "usermod -aG sudo trading")


def test_sudo_guard_refuses_an_account_that_is_not_in_the_sudo_group(host: Host) -> None:
    proc = real_run(host, STUB_USERMOD_NOOP="1", STUB_PASSWD_STATUS="P")
    assert_sudo_guard_refused(host, proc)
    assert "sudo group" in proc.stderr


def test_sudo_guard_fails_closed_on_a_rerun_of_a_configured_host(host: Host) -> None:
    proc = real_run(host, **{**CONFIGURED_ENV, "STUB_PASSWD_STATUS": "L"})
    assert_sudo_guard_refused(host, proc)
    assert not has_call(host.log_lines(), "useradd")


def test_sudo_guard_flow_first_run_stops_then_second_run_after_passwd_succeeds(host: Host) -> None:
    first = real_run(host, STUB_PASSWD_STATUS="NP")
    assert_sudo_guard_refused(host, first)
    assert has_call(host.log_lines(), "useradd")
    second = real_run(host, STUB_PASSWD_STATUS="P")
    assert second.returncode == 0, second.stderr
    assert (host.root / DROPIN_REL).is_file()
    assert sum(1 for ln in host.log_lines() if ln.startswith("useradd")) == 1


def test_dry_run_shows_the_sudo_step_and_the_guard_without_calling_passwd(host: Host) -> None:
    before = host.tree()
    proc = host.run(host.args("--dry-run"), env={"STUB_PASSWD_STATUS": "L"})
    assert proc.returncode == 0, proc.stderr
    assert "+ usermod -aG sudo trading" in proc.stdout
    guard = [ln for ln in proc.stdout.splitlines() if "lock-out guard would require" in ln]
    assert len(guard) == 1
    assert not guard[0].startswith("+ ")
    assert "trading" in guard[0]
    assert "sudo group" in guard[0]
    assert "passwd -S" in guard[0]
    assert "passwd trading" in guard[0]
    assert not has_call(host.log_lines(), "passwd")
    assert host.tree() == before
    assert host.mutations() == []


def test_the_script_never_sets_or_reads_a_password(golden: Golden, host: Host) -> None:
    proc = real_run(host, STUB_PASSWD_STATUS="NP")
    assert proc.returncode != 0
    for lines in (golden.first_run_lines, host.log_lines()):
        calls = [ln for ln in lines if ln.startswith("passwd")]
        assert calls, "the guard must read the account status"
        assert all(ln.startswith("passwd -S trading") for ln in calls), calls
    assert SECRET_PASSWORD not in combined(proc)


def test_ssh_drop_in_keeps_permit_root_login_no_and_exactly_four_directives(
    golden: Golden,
) -> None:
    content = (golden.host.root / DROPIN_REL).read_text(encoding="utf-8")
    directives = [ln for ln in content.splitlines() if ln.strip() and not ln.startswith("#")]
    assert directives == [
        "PasswordAuthentication no",
        "KbdInteractiveAuthentication no",
        "PermitRootLogin no",
        "PubkeyAuthentication yes",
    ]


# --- Task 3: chrony, checkout, .env and the operator checklist ---------------------------------


def tracking_text(
    system_time: str = "0.000045000 seconds fast of NTP time", leap: str = "Normal"
) -> str:
    return (
        "Reference ID    : A9FEA97B (169.254.169.123)\n"
        "Stratum         : 4\n"
        f"System time     : {system_time}\n"
        "Last offset     : +0.000012000 seconds\n"
        f"Leap status     : {leap}\n"
    )


def combined(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def test_chrony_is_installed_enabled_synced_and_drift_is_reported(golden: Golden) -> None:
    lines = golden.first_run_lines
    assert has_call(lines, "apt-get install -y chrony")
    assert has_call(lines, "systemctl disable --now systemd-timesyncd")
    assert has_call(lines, "systemctl enable --now chrony")
    enable = first_index(lines, "systemctl enable --now chrony")
    assert enable < first_index(lines, "chronyc waitsync")
    assert "0.045 ms" in combined(golden.proc)


@pytest.mark.parametrize("direction", ["fast", "slow"])
def test_chrony_drift_within_bound_passes_in_either_direction(host: Host, direction: str) -> None:
    _write(host.tracking, tracking_text(f"0.000900000 seconds {direction} of NTP time"))
    proc = real_run(host)
    assert proc.returncode == 0, proc.stderr
    assert "0.900 ms" in combined(proc)


def test_chrony_drift_above_the_bound_fails_and_names_the_drift(host: Host) -> None:
    _write(host.tracking, tracking_text("0.250000000 seconds fast of NTP time"))
    proc = real_run(host)
    assert proc.returncode != 0
    assert "250.000 ms" in proc.stderr
    assert "100 ms" in proc.stderr


def test_chrony_drift_bound_is_configurable(host: Host) -> None:
    _write(host.tracking, tracking_text("0.250000000 seconds fast of NTP time"))
    proc = host.run(host.args(max_drift_ms="1000"))
    assert proc.returncode == 0, proc.stderr


def test_chrony_not_synchronised_fails(host: Host) -> None:
    _write(host.tracking, tracking_text(leap="Not synchronised"))
    proc = real_run(host)
    assert proc.returncode != 0
    assert "not synchronised" in proc.stderr.lower()


def test_chrony_waitsync_failure_fails(host: Host) -> None:
    proc = real_run(host, STUB_WAITSYNC_RC="1")
    assert proc.returncode != 0
    assert "waitsync" in proc.stderr.lower()


def test_chrony_step_is_a_noop_when_installed_enabled_and_synced(golden: Golden) -> None:
    proc, new_lines = golden.rerun()
    assert proc.returncode == 0, proc.stderr
    assert not has_call(new_lines, "chronyc waitsync")
    assert not has_call(new_lines, "systemctl enable")
    assert not has_call(new_lines, "systemctl disable")


def test_checkout_clones_as_the_trading_user_and_detaches_at_the_ref(golden: Golden) -> None:
    lines = golden.first_run_lines
    repo = (golden.host.root / "opt" / "trading").as_posix()
    clone = next(ln for ln in lines if ln.startswith("runuser -u trading -- git clone"))
    assert "https://example.invalid/trading.git" in clone
    assert clone.endswith(repo)
    checkout = next(ln for ln in lines if "checkout --detach v1.0.0" in ln)
    assert checkout.startswith("runuser -u trading -- git -C")
    assert lines.index(clone) < lines.index(checkout)
    assert any(ln.startswith("install -d -o trading -g trading") for ln in lines)


def test_checkout_uses_the_deploy_key_through_git_ssh_command(host: Host) -> None:
    deploy_key = _write(host.base / "deploy_key", "-----BEGIN FAKE KEY-----\n")
    proc = real_run(host, "--deploy-key", deploy_key.as_posix())
    assert proc.returncode == 0, proc.stderr
    clone = next(ln for ln in host.log_lines() if " git clone " in ln)
    assert "GIT_SSH_COMMAND=ssh -i /home/trading/.ssh/id_deploy" in clone
    assert (host.root / "home" / "trading" / ".ssh" / "id_deploy").is_file()


def test_checkout_fetches_when_the_repo_exists_at_another_commit(host: Host) -> None:
    (host.root / "opt" / "trading" / ".git").mkdir(parents=True)
    proc = real_run(host, STUB_GIT_HEAD="aaa111", STUB_GIT_REF_COMMIT="bbb222")
    assert proc.returncode == 0, proc.stderr
    lines = host.log_lines()
    assert any(" fetch " in ln for ln in lines)
    assert not any(" git clone " in ln for ln in lines)
    assert any("checkout --detach v1.0.0" in ln for ln in lines)


def test_checkout_is_a_noop_when_already_at_the_ref(host: Host) -> None:
    (host.root / "opt" / "trading" / ".git").mkdir(parents=True)
    proc = real_run(host, STUB_GIT_HEAD="same123", STUB_GIT_REF_COMMIT="same123")
    assert proc.returncode == 0, proc.stderr
    lines = host.log_lines()
    assert not any(" fetch " in ln or " checkout " in ln or " clone " in ln for ln in lines)


def test_checkout_without_repo_flag_and_without_a_checkout_dies(host: Host) -> None:
    proc = host.run(host.args("--dry-run", repo=None))
    assert proc.returncode != 0
    assert "--repo" in proc.stderr
    assert host.mutations() == []


def test_env_file_is_installed_from_the_secrets_file_without_echoing_values(
    golden: Golden,
) -> None:
    host = golden.host
    env_file = host.root / "opt" / "trading" / ".env"
    assert env_file.read_bytes() == host.secrets.read_bytes()
    assert SECRET_PASSWORD not in combined(golden.proc)
    assert any(
        ln.startswith("install -m 0600 -o trading -g trading") and ".env" in ln
        for ln in golden.first_run_lines
    )
    assert SECRET_PASSWORD not in "\n".join(host.log_lines())


@pytest.mark.skipif(sys.platform == "win32", reason="NTFS cannot represent POSIX modes")
def test_env_file_mode_is_0600(golden: Golden) -> None:
    env_file = golden.host.root / "opt" / "trading" / ".env"
    assert (env_file.stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize(
    ("content", "named_key"),
    [
        (f"POSTGRES_USER=trading\nPOSTGRES_PASSWORD={SECRET_PASSWORD}\n", "POSTGRES_DB"),
        ("POSTGRES_USER=trading\nPOSTGRES_PASSWORD=\nPOSTGRES_DB=trading\n", "POSTGRES_PASSWORD"),
        ("POSTGRES_USER=trading\nPOSTGRES_PASSWORD=''\nPOSTGRES_DB=trading\n", "POSTGRES_PASSWORD"),
        (
            f"POSTGRES_USER=trading\nPOSTGRES_PASSWORD=change_me_please\nPOSTGRES_DB=trading\n"
            f"BINANCE_DEMO_API_SECRET={SECRET_PASSWORD}\n",
            "POSTGRES_PASSWORD",
        ),
        (
            f"POSTGRES_USER=trading\nPOSTGRES_PASSWORD={SECRET_PASSWORD}\nPOSTGRES_DB=trading\n"
            "BACKUP_S3_SECRET_ACCESS_KEY=CHANGE_ME\n",
            "BACKUP_S3_SECRET_ACCESS_KEY",
        ),
    ],
    ids=["missing-key", "empty-value", "quoted-empty", "placeholder", "placeholder-other-key"],
)
def test_env_validation_refuses_before_any_step_and_never_prints_values(
    host: Host, content: str, named_key: str
) -> None:
    _write(host.secrets, content)
    proc = real_run(host)
    assert proc.returncode != 0
    assert named_key in proc.stderr
    assert SECRET_PASSWORD not in combined(proc)
    assert host.mutations() == []
    assert SECRET_PASSWORD not in "\n".join(host.log_lines())


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("Ab1@cdEfGhIjKlMn2", "URL-safe"),
        ("Ab1/cdEfGhIjKlMn2", "URL-safe"),
        ("Ab1:cdEfGhIjKlMn2", "URL-safe"),
        ("Ab1#cdEfGhIjKlMn2", "URL-safe"),
        ("Ab1$cdEfGhIjKlMn2", "URL-safe"),
        ("Short1pw", "too short"),
        ("Fifteen-chars-15", "OK"),
    ],
    ids=["at", "slash", "colon", "hash", "dollar", "short", "sixteen-ok"],
)
def test_env_validation_enforces_a_url_safe_long_postgres_password(
    host: Host, password: str, reason: str
) -> None:
    """WR-11: compose builds DATABASE_URL from the password, so the shape is checked up front."""
    _write(
        host.secrets, f"POSTGRES_USER=trading\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=trading\n"
    )
    proc = real_run(host)
    if reason == "OK":
        assert proc.returncode == 0, proc.stderr
        return
    assert proc.returncode != 0
    assert "POSTGRES_PASSWORD" in proc.stderr
    assert reason in proc.stderr
    assert password not in combined(proc)
    assert host.mutations() == []


def test_env_validation_rejects_carriage_returns(host: Host) -> None:
    with host.secrets.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            "POSTGRES_USER=trading\r\nPOSTGRES_PASSWORD=x1y2z3w4\r\nPOSTGRES_DB=trading\r\n"
        )
    proc = real_run(host)
    assert proc.returncode != 0
    assert "line endings" in proc.stderr
    assert host.mutations() == []


def test_missing_secrets_file_is_refused(host: Host) -> None:
    proc = host.run(host.args(secrets_file=(host.base / "nope.conf").as_posix()))
    assert proc.returncode != 0
    assert "secrets file" in proc.stderr.lower()
    assert host.mutations() == []


CHECKLIST_NEEDLES = (
    "IP whitelist",
    "withdraw",
    "heartbeat",
    "passphrase",
    "second SSH session",
    "disk encryption",
    "backup.sh --install-timer",
    "Root SSH login is now disabled",  # WR-05 (D062): pins the new item 6 sentence
    "passwd trading",
    "sudo -v",
    "sudo /opt/trading/deploy/backup.sh --install-timer",
    "no passwordless sudo rule",
    "docker group",
)


def assert_checklist_last(out: str) -> None:
    assert "Operator checklist" in out
    for needle in CHECKLIST_NEEDLES:
        assert needle in out, f"checklist lacks {needle!r}"
    assert "has no sudo" not in out
    assert "from the provider console" not in out
    assert out.index("Operator checklist") > out.index("install -m 0600")


def test_operator_checklist_ends_a_real_run(golden: Golden) -> None:
    assert_checklist_last(golden.proc.stdout)


def test_operator_checklist_ends_a_dry_run(host: Host) -> None:
    proc = host.run(host.args("--dry-run"))
    assert proc.returncode == 0, proc.stderr
    assert_checklist_last(proc.stdout)


def test_second_run_announces_no_mutation_at_all(golden: Golden) -> None:
    proc, new_lines = golden.rerun()
    assert proc.returncode == 0, proc.stderr
    assert [ln for ln in proc.stdout.splitlines() if ln.startswith("+ ")] == []
    assert [ln for ln in new_lines if is_mutation(ln)] == []


def test_second_dry_run_announces_no_mutation_either(golden: Golden) -> None:
    proc, new_lines = golden.rerun(dry_run=True)
    assert proc.returncode == 0, proc.stderr
    assert [ln for ln in proc.stdout.splitlines() if ln.startswith("+ ")] == []
    assert [ln for ln in new_lines if is_mutation(ln)] == []
