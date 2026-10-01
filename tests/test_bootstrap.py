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
from collections.abc import Callable
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
printf '%s\n' "$(basename "$0") $*" >> "${STUB_LOG:?}"
"""

STUBS: dict[str, str] = {
    "apt-get": "",
    "usermod": "",
    "useradd": "",
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
if [ "${STUB_USER_EXISTS:-0}" = "1" ]; then
  echo "${2:-trading}:x:1000:1000::/home/${2:-trading}:/bin/bash"
  exit 0
fi
exit 2
""",
    "id": r"""
case "${1:-}" in
  -u) echo "${STUB_UID:-0}" ;;
  -nG)
    if [ "${STUB_USER_EXISTS:-0}" = "1" ]; then echo "${STUB_GROUPS:-trading}"; else exit 1; fi
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
    return path


def _posix(path: Path) -> str:
    return path.as_posix()


# Argv prefixes that only read state. Everything else a stub logs counts as a mutation.
_PROBE_FIRST_WORDS = {"dpkg-query", "dpkg", "getent", "id", "ssh-keygen"}
_PROBE_PREFIXES = ("ufw status", "systemctl is-enabled", "sshd -T", "chronyc tracking")


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


@pytest.fixture
def host(tmp_path: Path) -> Host:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; bootstrap tests need Git Bash or Linux bash")
    base = tmp_path / "host"
    h = Host(base=base, bash=bash)
    for name, body in STUBS.items():
        _write(base / "bin" / name, "#!/usr/bin/env bash\n" + body)
    _write(base / "driver.sh", DRIVER)
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


def assert_in_order(text: str, markers: list[str]) -> None:
    pos = 0
    for marker in markers:
        idx = text.find(marker, pos)
        assert idx >= 0, f"marker {marker!r} not found (in order) after offset {pos} in:\n{text}"
        pos = idx + len(marker)


GetHost = Callable[[], Host]

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
            "+ ufw allow",
            "+ ufw --force enable",
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
