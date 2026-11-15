"""Offline tests for the host freeze tick and its S3 witness (quick 261114-12e, plan B).

``deploy/freeze-witness.sh`` (the ExecStart of ``trading-soak-freeze-witness.service``) runs one
hourly freeze tick on the soak host: it takes the image of the running paper container, copies the
pinned epoch out of it, runs ``python -m src.paper.freeze --check --from-allowlist`` on that copy in
an isolated ``docker run --rm`` and uploads the exact line bytes create-only to the S3 witness
prefix (owner decision ``16-DEC-HOST-TICK``).

The real script runs under Git Bash (Windows) or bash (Linux CI). ``docker``, ``curl``,
``systemctl`` and ``date`` are stubs first on PATH that append their argv to a log (the curl stub
also saves the configuration it reads on standard input and the file it was told to upload). No test
reaches a network, S3 or a real container. The credential is FAKE: its values are sentinels that
the tests grep for. The real upload, the bucket policy, systemd credential delivery, the timer
firing and the container permissions are owner-run verification (RUNBOOK 20.10), not claimed here.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.evaluate_trial_soak import DEFAULT_WORKFLOW, read_workflow_cron

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = REPO_ROOT / "deploy"
UNITS = DEPLOY / "systemd"
SCRIPT = "freeze-witness.sh"
SERVICE = "trading-soak-freeze-witness.service"
TIMER = "trading-soak-freeze-witness.timer"

CRON = read_workflow_cron(DEFAULT_WORKFLOW)
MINUTE = int(CRON.split()[0])
EPOCH = "e" * 64
CONTAINER = "0123456789ab"
IMAGE = "sha256:" + "a" * 64
CREDENTIAL_FILE = "/etc/trading/freeze-witness.conf"

# A FAKE credential. The values look like none of the redaction patterns; the host is reserved.
KEY_ID = "FAKEWITNESSKEYID0001"
SECRET = "FAKEwitnessSECRET+value/0000000000"
BUCKET_HOST = "witness-bucket.example.invalid"
BUCKET_URL = f"https://{BUCKET_HOST}"
REGION = "eu-west-1"
PREFIX = "witness-ticks"
SECRET_MARKERS = (KEY_ID, SECRET, BUCKET_HOST)
CREDENTIAL_KEYS = ("bucket_url", "region", "witness_prefix", "access_key_id", "secret_access_key")


def make_credential(**overrides: str | None) -> str:
    """The five credential lines; an override of None drops that key."""
    values = {
        "bucket_url": BUCKET_URL,
        "region": REGION,
        "witness_prefix": PREFIX,
        "access_key_id": KEY_ID,
        "secret_access_key": SECRET,
    }
    values.update(overrides)
    return "".join(f"{key}={values[key]}\n" for key in CREDENTIAL_KEYS if values[key] is not None)


def at(hour: int, minute: int, second: int = 0, day: int = 20) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=UTC)


def expected_slot(now: datetime, minute: int = MINUTE) -> str:
    """The latest slot minute at or before ``now`` (independent of the script's arithmetic)."""
    slot = now.replace(minute=minute, second=0)
    if slot > now:
        slot -= timedelta(hours=1)
    return slot.strftime("%Y%m%dT%H%MZ")


NOW = at(0, MINUTE, 4)

_LOG = r"""
printf '%s\n' "${0##*/} $*" >> "${STUB_LOG:?}"
state="${STUB_STATE:?}"
mkdir -p "$state"
"""

_LINE_HEAD = (
    '{"checked_at_utc":"2026-11-20T00:00:09+00:00","current_hash":"%s","epoch_id":"%s",'
    '"outcome":"clean","pinned_hash":"%s","run_metadata":'
)

STUBS: dict[str, str] = {
    "docker": r"""
case "$1" in
  compose)
    [[ -z "${STUB_NO_CONTAINER:-}" ]] || exit 0
    printf '%s\n' "${STUB_CID:?}"
    exit 0
    ;;
  inspect)
    printf '%s\n' "${STUB_IMAGE:?}"
    exit 0
    ;;
  cp)
    [[ -z "${STUB_NO_PIN:-}" ]] || exit 1
    printf '{\n  "epoch_id": "%s",\n  "parameter_set_hash": "x"\n}' "${STUB_EPOCH:?}" > "$3"
    exit 0
    ;;
  run)
    src="" tick="" sched=""
    for a in "$@"; do
      case "$a" in
        type=bind,src=*,dst=/scratch)
          v="${a#type=bind,src=}"
          src="${v%,dst=/scratch}"
          ;;
        PAPER_TICK_ID=*) tick="${a#PAPER_TICK_ID=}" ;;
        PAPER_EVENT_SCHEDULE=*) sched="${a#PAPER_EVENT_SCHEDULE=}" ;;
      esac
    done
    h="$(printf 'b%.0s' $(seq 1 64))"
    out="$src/registry_diff.jsonl"
    rc=0
    case "${STUB_LINE_MODE:-host}" in
      host)
        printf '__HEAD__{"schedule":"%s","source":"host","tick_id":"%s"}}\n' \
          "$h" "$STUB_EPOCH" "$h" "$sched" "$tick" > "$out"
        ;;
      old)
        printf '__HEAD__{"schedule":"%s"}}\n' "$h" "$STUB_EPOCH" "$h" "$sched" > "$out"
        ;;
      diff)
        printf '{"checked_at_utc":"2026-11-20T00:00:09+00:00","current_hash":"%s","epoch_id":"%s",'\
'"outcome":"REGISTRY_DIFF","pinned_hash":"%s","run_metadata":'\
'{"schedule":"%s","source":"host","tick_id":"%s"}}\n' \
          "$h" "$STUB_EPOCH" "$h" "$sched" "$tick" > "$out"
        rc=3
        ;;
      skipped)
        printf '{"checked_at_utc":"2026-11-20T00:00:09+00:00","outcome":"SKIPPED",'\
'"reason":"allowlist empty","run_metadata":{"schedule":"%s","source":"host","tick_id":"%s"}}\n' \
          "$sched" "$tick" > "$out"
        ;;
      twolines)
        printf '__HEAD__{"schedule":"%s","source":"host","tick_id":"%s"}}\n' \
          "$h" "$STUB_EPOCH" "$h" "$sched" "$tick" > "$out"
        cat "$out" "$out" > "$out.2"
        mv "$out.2" "$out"
        ;;
      big)
        printf '%5000s\n' x > "$out"
        ;;
      noline) ;;
      wrongtick)
        printf '__HEAD__{"schedule":"%s","source":"host","tick_id":"%s"}}\n' \
          "$h" "$STUB_EPOCH" "$h" "$sched" "ffffffffffffffffffffffffffffffff" > "$out"
        ;;
    esac
    [[ ! -f "$out" ]] || cp "$out" "$state/line-written"
    [[ -z "${STUB_RUN_RC:-}" ]] || rc="$STUB_RUN_RC"
    exit "$rc"
    ;;
esac
echo "unexpected docker verb: $1" >&2
exit 99
""".replace("__HEAD__", _LINE_HEAD),
    "curl": r"""
n="$(grep -c '^curl ' "$STUB_LOG")"
cat > "$state/curl-config.$n"
prev=""
for a in "$@"; do
  if [[ $prev == --upload-file ]]; then
    cp "$a" "$state/upload.$n"
  fi
  prev=$a
done
rc="${STUB_CURL_RC:-0}"
if [[ $rc == 0 ]]; then printf 200; elif [[ $rc == 22 ]]; then printf 412; else printf 000; fi
exit "$rc"
""",
    "systemctl": "exit 0\n",
}

DATE_STUB = r"""#!/usr/bin/env bash
if [[ "$*" == "-u +%s" && -n "${STUB_NOW:-}" ]]; then
  printf '%s\n' "$STUB_NOW"
  exit 0
fi
PATH="${PATH#*:}"
exec date "$@"
"""

DRIVER = """\
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
export PATH="$here/bin:$PATH"
script="$1"
shift
exec bash "$script" "$@"
"""

SCRUBBED_VARS = (
    "TRADING_ENV_FILE",
    "COMPOSE_PROJECT_NAME",
    "CREDENTIALS_DIRECTORY",
    "FREEZE_WITNESS_SCHEDULE",
    "FREEZE_WITNESS_STEP_TIMEOUT_SECONDS",
    "RUNTIME_DIRECTORY",
    "SHELLOPTS",
    "DRY_RUN",
    "STUB_NOW",
    "STUB_CID",
    "STUB_IMAGE",
    "STUB_EPOCH",
    "STUB_NO_CONTAINER",
    "STUB_NO_PIN",
    "STUB_LINE_MODE",
    "STUB_RUN_RC",
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
    def cred_dir(self) -> Path:
        return self.base / "cred"

    @property
    def runtime_dir(self) -> Path:
        return self.base / "runtime"

    @property
    def credential_path(self) -> Path:
        return self.prefix / "etc" / "trading" / "freeze-witness.conf"

    def lines(self) -> list[str]:
        if not self.log.exists():
            return []
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def docker_lines(self) -> list[str]:
        return [ln for ln in self.lines() if ln.startswith("docker ")]

    def curl_lines(self) -> list[str]:
        return [ln for ln in self.lines() if ln.startswith("curl ")]

    def curl_config(self, n: int = 1) -> str:
        return (self.state / f"curl-config.{n}").read_text(encoding="utf-8")

    def upload(self, n: int = 1) -> bytes:
        return (self.state / f"upload.{n}").read_bytes()

    def write_credential(self, text: str | None = None) -> Path:
        return _write(self.cred_dir / "freeze-witness", make_credential() if text is None else text)

    def run(
        self,
        *args: str,
        env: dict[str, str | None] | None = None,
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
                "CREDENTIALS_DIRECTORY": self.cred_dir.as_posix(),
                "FREEZE_WITNESS_SCHEDULE": CRON,
                "STUB_NOW": str(int(NOW.timestamp())),
                "STUB_CID": CONTAINER,
                "STUB_IMAGE": IMAGE,
                "STUB_EPOCH": EPOCH,
            }
        )
        for name, value in (env or {}).items():
            if value is None:
                full_env.pop(name, None)
            else:
                full_env[name] = value
        raw = subprocess.run(
            [self.bash, (self.base / "driver.sh").as_posix(), (DEPLOY / SCRIPT).as_posix(), *args],
            capture_output=True,
            env=full_env,
            check=False,
            timeout=120,
            input=(stdin or "").encode("utf-8"),
        )
        return subprocess.CompletedProcess(
            raw.args,
            raw.returncode,
            raw.stdout.decode("utf-8", errors="replace"),
            raw.stderr.decode("utf-8", errors="replace"),
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found; the freeze witness tests need Git Bash or Linux bash")
    probe = subprocess.run(
        [bash, "-c", "timeout --version && sha256sum --version && od --version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        infra_skip("GNU coreutils (timeout, sha256sum, od) not found; the script needs them")
    base = tmp_path / "rig"
    for name, body in STUBS.items():
        _write(base / "bin" / name, "#!/usr/bin/env bash\n" + _LOG + body)
    _write(base / "bin" / "date", DATE_STUB)
    _write(base / "driver.sh", DRIVER)
    (base / "runtime").mkdir(parents=True)
    made = Rig(base=base, bash=bash)
    made.write_credential()
    return made


def assert_no_secret(proc: subprocess.CompletedProcess[str], made: Rig) -> None:
    """The credential and the bucket URL are absent from stdout, stderr and the whole stub log."""
    blobs = {"stdout": proc.stdout, "stderr": proc.stderr, "stub log": "\n".join(made.lines())}
    for where, blob in blobs.items():
        for marker in SECRET_MARKERS:
            assert marker not in blob, f"{marker!r} leaked into the {where}:\n{blob}"


def _strip_comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _run_tick(made: Rig, **env: str | None) -> subprocess.CompletedProcess[str]:
    return made.run(env={"RUNTIME_DIRECTORY": made.runtime_dir.as_posix(), **env})


# --- Test 1 (tracer): one tick, end to end -------------------------------------------------------


def test_one_tick_uploads_the_exact_line_create_only_without_exposing_the_credential(
    rig: Rig,
) -> None:
    proc = _run_tick(rig)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    curl = rig.curl_lines()
    assert len(curl) == 1, curl
    written = (rig.state / "line-written").read_bytes()
    assert written.endswith(b"\n") and written.count(b"\n") == 1
    assert rig.upload() == written
    tick = re.search(r"PAPER_TICK_ID=([0-9a-f]{32})", "\n".join(rig.docker_lines()))
    assert tick, rig.docker_lines()
    slot = expected_slot(NOW)
    key = f"{PREFIX}/{EPOCH}/{slot}-{tick.group(1)}.jsonl"
    config = rig.curl_config()
    assert f'url = "{BUCKET_URL}/{key}"' in config.splitlines(), config
    assert f'user = "{KEY_ID}:{SECRET}"' in config.splitlines(), config
    sha = hashlib.sha256(written).hexdigest()
    for needle in (
        "--aws-sigv4",
        f"aws:amz:{REGION}:s3",
        "If-None-Match: *",
        f"x-amz-content-sha256: {sha}",
        "=https",
        "--upload-file",
    ):
        assert needle in curl[0], (needle, curl[0])
    assert f"witness: created {EPOCH}/{slot}-{tick.group(1)}.jsonl (clean)" in proc.stderr
    assert_no_secret(proc, rig)


# --- Test 2: the slot label -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "now",
    [
        at(0, 10, 0),
        at(0, MINUTE, 0),
        at(0, MINUTE, 59),
        at(0, 0, 0),
        at(23, 59, 59),
        at(0, MINUTE - 1 if MINUTE else 59, 59),
    ],
    ids=["10:00", "exactly the minute", "end of the minute", "00:00", "23:59:59", "just before"],
)
def test_the_slot_label_is_the_latest_slot_at_or_before_now(rig: Rig, now: datetime) -> None:
    proc = _run_tick(rig, STUB_NOW=str(int(now.timestamp())))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    key = re.search(r'url = "[^"]*/([^/"]+\.jsonl)"', rig.curl_config())
    assert key, rig.curl_config()
    assert key.group(1).startswith(expected_slot(now) + "-"), (key.group(1), now)


# --- Test 3: the docker verbs and the isolated container -----------------------------------------


def test_the_docker_calls_are_ps_inspect_cp_and_one_isolated_run(rig: Rig) -> None:
    proc = _run_tick(rig)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = rig.docker_lines()
    assert [ln.split()[1] for ln in calls] == ["compose", "inspect", "cp", "run"], calls
    assert calls[0] == "docker compose -p trading-soak ps -q paper"
    assert calls[1] == f"docker inspect --format {{{{.Image}}}} {CONTAINER}"
    assert calls[2].startswith(f"docker cp {CONTAINER}:/app/logs/paper/pinned_epoch.json ")
    run = calls[3]
    for needle in (
        "--rm",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pinned-state /scratch/pinned_epoch.json",
        "--diff-log /scratch/registry_diff.jsonl",
        "--registry-root /app/params",
        "--from-allowlist",
        IMAGE,
    ):
        assert needle in run, (needle, run)
    mount = re.search(r"--mount type=bind,src=(\S+),dst=/scratch", run)
    assert mount, run
    assert mount.group(1).startswith(rig.runtime_dir.as_posix()), mount.group(1)
    assert "logs" not in mount.group(1).split("/")[-1]
    assert run.count("--mount") == 1 and "-v " not in run and "--volume" not in run
    names = re.findall(r"(?:^| )-e (\w+)", run)
    assert names == ["PAPER_TICK_SOURCE", "PAPER_TICK_ID", "PAPER_EVENT_SCHEDULE"], run
    assert "PAPER_TICK_SOURCE=host" in run
    assert f"PAPER_EVENT_SCHEDULE={CRON}" in run
    assert not rig.runtime_dir.joinpath(mount.group(1).rsplit("/", 1)[-1]).exists(), "scratch kept"


def test_the_script_has_no_docker_verb_besides_inspect_cp_and_run() -> None:
    text = _strip_comments((DEPLOY / SCRIPT).read_text(encoding="utf-8"))
    verbs = set(re.findall(r"\bdocker[ \t]+([a-z][a-z-]*)", text))
    assert verbs <= {"inspect", "cp", "run"}, verbs
    compose_verbs = set(re.findall(r'compose-soak\.sh"?\s+(\S+)', text))
    assert compose_verbs == {"ps"}, compose_verbs
    for banned in (" exec ", "rm -f ", "update-ref", "git "):
        assert banned not in text, banned


# --- Test 4: the credential -----------------------------------------------------------------------


def test_without_the_systemd_credential_the_script_exits_4_and_runs_nothing(rig: Rig) -> None:
    (rig.cred_dir / "freeze-witness").unlink()
    # a file at the plain host path must never be used as a fallback
    _write(rig.credential_path, make_credential())
    proc = rig.run()
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)
    unset = rig.run(env={"CREDENTIALS_DIRECTORY": None})
    assert unset.returncode == 4, unset.stdout + unset.stderr
    assert rig.lines() == []


BAD_CREDENTIALS = {
    "missing region": make_credential(region=None),
    "missing secret": make_credential(secret_access_key=None),
    "extra key": make_credential() + "session_token=abc\n",
    "duplicate key": make_credential() + f"region={REGION}\n",
    "blank line": make_credential() + "\n",
    "comment": make_credential() + "# note\n",
    "space in value": make_credential(secret_access_key=SECRET + " tail"),
    "quote in value": make_credential(secret_access_key=SECRET + '"x'),
    "backslash in value": make_credential(secret_access_key=SECRET + "\\x"),
    "http url": make_credential(bucket_url=f"http://{BUCKET_HOST}"),
    "userinfo in url": make_credential(bucket_url=f"https://user@{BUCKET_HOST}"),
    "query in url": make_credential(bucket_url=f"{BUCKET_URL}?x=1"),
    "two path segments": make_credential(bucket_url=f"{BUCKET_URL}/a/b"),
    "dot dot prefix": make_credential(witness_prefix="a/../b"),
    "dot prefix": make_credential(witness_prefix="a/./b"),
    "leading slash prefix": make_credential(witness_prefix="/witness"),
    "empty prefix": make_credential(witness_prefix=""),
    "uppercase region": make_credential(region="EU-WEST-1"),
    "short key id": make_credential(access_key_id="SHORT"),
    "crlf": make_credential().replace("\n", "\r\n"),
}


@pytest.mark.parametrize("name", sorted(BAD_CREDENTIALS))
def test_an_invalid_credential_exits_4_runs_nothing_and_echoes_no_value(
    rig: Rig, name: str
) -> None:
    rig.write_credential(BAD_CREDENTIALS[name])
    proc = rig.run()
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert_no_secret(proc, rig)


def test_a_path_style_bucket_url_is_accepted_and_joined_without_a_double_slash(rig: Rig) -> None:
    rig.write_credential(make_credential(bucket_url=f"{BUCKET_URL}:9000/evidence-bucket"))
    proc = _run_tick(rig)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    url = re.search(r'url = "([^"]+)"', rig.curl_config())
    assert url, rig.curl_config()
    assert url.group(1).startswith(f"{BUCKET_URL}:9000/evidence-bucket/{PREFIX}/{EPOCH}/")


# --- Test 5: the secret survives the whole path --------------------------------------------------


def test_the_key_and_secret_are_only_in_the_curl_stdin_config(rig: Rig) -> None:
    proc = _run_tick(rig)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert_no_secret(proc, rig)
    config = rig.curl_config()
    assert KEY_ID in config and SECRET in config and BUCKET_HOST in config
    for line in rig.docker_lines() + rig.curl_lines():
        assert "https://" not in line and "AKIA" not in line
    # the stub argv log never holds the environment, so the docker argv check is the argv itself
    assert not any(marker in "\n".join(rig.docker_lines()) for marker in SECRET_MARKERS)


@pytest.mark.parametrize("mode", ["old", "wrongtick", "twolines", "big", "noline"])
def test_a_failed_tick_never_echoes_the_credential(rig: Rig, mode: str) -> None:
    proc = _run_tick(rig, STUB_LINE_MODE=mode)
    assert proc.returncode != 0
    assert_no_secret(proc, rig)


# --- Test 6: the line must carry the host identity ------------------------------------------------


def test_a_line_without_the_host_source_and_tick_id_is_never_uploaded(rig: Rig) -> None:
    proc = _run_tick(rig, STUB_LINE_MODE="old")
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert rig.curl_lines() == []
    assert "plan A" in proc.stderr or "predates" in proc.stderr
    assert_no_secret(proc, rig)


@pytest.mark.parametrize("mode", ["wrongtick", "twolines", "big"])
def test_a_line_that_is_not_one_short_host_line_of_this_tick_is_never_uploaded(
    rig: Rig, mode: str
) -> None:
    proc = _run_tick(rig, STUB_LINE_MODE=mode)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert rig.curl_lines() == []


# --- Test 7: non-clean outcomes -------------------------------------------------------------------


def test_a_registry_diff_line_is_uploaded_and_exits_3(rig: Rig) -> None:
    proc = _run_tick(rig, STUB_LINE_MODE="diff")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert len(rig.curl_lines()) == 1
    assert rig.upload() == (rig.state / "line-written").read_bytes()
    assert "(REGISTRY_DIFF)" in proc.stderr
    assert_no_secret(proc, rig)


def test_a_skipped_line_is_uploaded_and_exits_0(rig: Rig) -> None:
    proc = _run_tick(rig, STUB_LINE_MODE="skipped")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(rig.curl_lines()) == 1
    assert "(SKIPPED)" in proc.stderr


def test_a_cli_failure_without_a_usable_line_exits_1_and_uploads_nothing(rig: Rig) -> None:
    for env in ({"STUB_LINE_MODE": "noline"}, {"STUB_RUN_RC": "2", "STUB_LINE_MODE": "noline"}):
        proc = _run_tick(rig, **env)
        assert proc.returncode == 1, proc.stdout + proc.stderr
    assert rig.curl_lines() == []


# --- Test 8: no overwrite, no retry ---------------------------------------------------------------


def test_an_existing_object_is_refused_once_with_the_create_only_header_and_never_retried(
    rig: Rig,
) -> None:
    proc = _run_tick(rig, STUB_CURL_RC="22")
    assert proc.returncode == 6, proc.stdout + proc.stderr
    curl = rig.curl_lines()
    assert len(curl) == 1, curl
    assert all("If-None-Match: *" in ln for ln in curl)
    assert "never re-sent" in proc.stderr and "412" in proc.stderr
    assert "nothing was replaced" in proc.stderr
    assert_no_secret(proc, rig)


@pytest.mark.parametrize("rc", [6, 28, 35])
def test_any_failed_upload_exits_6_after_one_call(rig: Rig, rc: int) -> None:
    proc = _run_tick(rig, STUB_CURL_RC=str(rc))
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert len(rig.curl_lines()) == 1
    assert f"curl exit {rc}" in proc.stderr
    assert "nothing was replaced" not in proc.stderr
    assert_no_secret(proc, rig)


def test_the_script_never_sends_an_upload_without_the_create_only_header() -> None:
    text = _strip_comments((DEPLOY / SCRIPT).read_text(encoding="utf-8"))
    assert len(re.findall(r"^\s*curl\b", text, re.MULTILINE)) == 1
    statement = text[text.index("curl --silent") : text.index("2>/dev/null")]
    assert "If-None-Match: *" in statement and "x-amz-content-sha256" in statement
    assert statement.count("If-None-Match: *") == 1
    assert "--retry" not in text and "--upload-file" in statement


# --- Test 9: no container, no pin -----------------------------------------------------------------


@pytest.mark.parametrize("missing", ["STUB_NO_CONTAINER", "STUB_NO_PIN"])
def test_no_paper_container_or_no_pin_exits_1_with_no_run_and_no_upload(
    rig: Rig, missing: str
) -> None:
    proc = _run_tick(rig, **{missing: "1"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not any(ln.startswith("docker run") for ln in rig.docker_lines())
    assert rig.curl_lines() == []


def test_a_malformed_container_or_image_id_exits_1(rig: Rig) -> None:
    assert _run_tick(rig, STUB_CID="not-hex!").returncode == 1
    assert _run_tick(rig, STUB_IMAGE="latest").returncode == 1
    assert rig.curl_lines() == []
    assert not any(ln.startswith("docker run") for ln in rig.docker_lines())


# --- Test 10: xtrace and the schedule -------------------------------------------------------------


def test_the_script_refuses_xtrace_before_it_reads_the_credential(rig: Rig) -> None:
    proc = rig.run(env={"SHELLOPTS": "xtrace"})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "xtrace" in proc.stderr
    assert rig.lines() == []
    for marker in (KEY_ID, SECRET):
        assert marker not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "schedule",
    [
        None,
        "",
        "17 * * * 1",
        "*/5 * * * *",
        "60 * * * *",
        "17 3 * * *",
        "17 * * * * *",
        "x * * * *",
    ],
)
def test_a_missing_or_non_hourly_schedule_exits_2(rig: Rig, schedule: str | None) -> None:
    proc = rig.run(env={"FREEZE_WITNESS_SCHEDULE": schedule})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert rig.lines() == []


def test_a_bad_step_timeout_is_a_usage_error(rig: Rig) -> None:
    for value in ("0", "abc", "-5"):
        proc = rig.run(env={"FREEZE_WITNESS_STEP_TIMEOUT_SECONDS": value})
        assert proc.returncode == 2, proc.stdout + proc.stderr
    assert rig.lines() == []


# --- Test 11: dry run -----------------------------------------------------------------------------


def test_dry_run_makes_no_docker_or_curl_call_and_prints_the_plan(rig: Rig) -> None:
    proc = rig.run("--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert "+ upload (create-only, If-None-Match: *)" in proc.stdout
    assert "URL and credential not shown" in proc.stdout
    assert "docker run --rm" in proc.stdout
    assert_no_secret(proc, rig)


def test_dry_run_still_refuses_a_bad_credential_or_schedule(rig: Rig) -> None:
    rig.write_credential(make_credential(bucket_url=f"http://{BUCKET_HOST}"))
    proc = rig.run("--dry-run")
    assert proc.returncode == 4, proc.stdout + proc.stderr
    rig.write_credential()
    bad = rig.run("--dry-run", env={"FREEZE_WITNESS_SCHEDULE": "*/5 * * * *"})
    assert bad.returncode == 2, bad.stdout + bad.stderr
    assert rig.lines() == []


# --- Test 12: --set-credential --------------------------------------------------------------------


def test_set_credential_stores_the_five_lines_with_mode_0600_and_never_shows_them(
    rig: Rig,
) -> None:
    proc = rig.run("--set-credential", stdin=make_credential())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rig.credential_path.read_text(encoding="utf-8") == make_credential()
    if _posix_modes():
        assert rig.credential_path.stat().st_mode & 0o777 == 0o600
    assert_no_secret(proc, rig)
    assert rig.lines() == []


def test_set_credential_twice_with_the_same_input_writes_nothing_the_second_time(
    rig: Rig,
) -> None:
    assert rig.run("--set-credential", stdin=make_credential()).returncode == 0
    second = rig.run("--set-credential", stdin=make_credential())
    assert second.returncode == 0, second.stdout + second.stderr
    assert "+ write " not in second.stdout


@pytest.mark.parametrize("name", ["missing region", "extra key", "http url", "quote in value"])
def test_set_credential_refuses_invalid_input_and_writes_nothing(rig: Rig, name: str) -> None:
    proc = rig.run("--set-credential", stdin=BAD_CREDENTIALS[name])
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert not rig.credential_path.exists()
    assert_no_secret(proc, rig)


def test_set_credential_dry_run_writes_nothing(rig: Rig) -> None:
    proc = rig.run("--set-credential", "--dry-run", stdin=make_credential())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not rig.credential_path.exists()
    assert_no_secret(proc, rig)


# --- Test 13: --install-timer ---------------------------------------------------------------------

SOAK_ENV = "/home/trading/soak.env"


def _install(*extra: str) -> list[str]:
    return ["--install-timer", "--soak-env-file", SOAK_ENV, *extra]


def _unit_dir(made: Rig) -> Path:
    return made.prefix / "etc" / "systemd" / "system"


def _systemctl(made: Rig) -> list[str]:
    return [ln for ln in made.lines() if ln.startswith("systemctl ")]


@pytest.fixture
def install_rig(rig: Rig) -> Rig:
    _write(rig.credential_path, make_credential())
    _write(rig.prefix / "home" / "trading" / "soak.env", "# fake soak env\n")
    return rig


def test_install_timer_writes_both_units_and_enables_the_timer(install_rig: Rig) -> None:
    rig = install_rig
    proc = rig.run(*_install())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    service = (_unit_dir(rig) / SERVICE).read_text(encoding="utf-8")
    timer = (_unit_dir(rig) / TIMER).read_text(encoding="utf-8")
    for text in (service, timer):
        assert "@" not in text, "a substitution token was left behind"
    lines = service.splitlines()
    assert f"Environment=TRADING_ENV_FILE={SOAK_ENV}" in lines
    assert f'Environment="FREEZE_WITNESS_SCHEDULE={CRON}"' in lines
    assert f"LoadCredential=freeze-witness:{CREDENTIAL_FILE}" in lines
    assert any(ln.startswith("ExecStart=/usr/bin/env bash ") for ln in lines)
    assert f"OnCalendar=*-*-* *:{MINUTE:02d}:00 UTC" in timer.splitlines()
    assert _systemctl(rig) == [
        "systemctl daemon-reload",
        f"systemctl enable --now {TIMER}",
        f"systemctl restart {TIMER}",
    ]
    assert rig.docker_lines() == [] and rig.curl_lines() == []
    assert_no_secret(proc, rig)


def test_a_second_identical_install_writes_nothing_but_still_enables_the_timer(
    install_rig: Rig,
) -> None:
    rig = install_rig
    assert rig.run(*_install()).returncode == 0
    before = len(rig.lines())
    second = rig.run(*_install())
    assert second.returncode == 0, second.stdout + second.stderr
    assert "+ write " not in second.stdout
    assert rig.lines()[before:] == [f"systemctl enable --now {TIMER}"]


def test_install_dry_run_writes_nothing(install_rig: Rig) -> None:
    rig = install_rig
    proc = rig.run(*_install("--dry-run"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (rig.prefix / "etc" / "systemd").exists()
    assert rig.lines() == []
    assert proc.stdout.count("+ write ") == 2


def test_install_needs_the_credential_file_but_a_dry_run_only_warns(install_rig: Rig) -> None:
    rig = install_rig
    rig.credential_path.unlink()
    real = rig.run(*_install())
    assert real.returncode == 4, real.stdout + real.stderr
    assert "--set-credential" in real.stderr
    assert not (rig.prefix / "etc" / "systemd").exists()
    assert rig.lines() == []
    dry = rig.run(*_install("--dry-run"))
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "--set-credential" in dry.stderr


def test_install_needs_the_soak_env_file_but_a_dry_run_only_warns(install_rig: Rig) -> None:
    rig = install_rig
    (rig.prefix / "home" / "trading" / "soak.env").unlink()
    real = rig.run(*_install())
    assert real.returncode != 0, real.stdout + real.stderr
    assert not (rig.prefix / "etc" / "systemd").exists()
    dry = rig.run(*_install("--dry-run"))
    assert dry.returncode == 0, dry.stdout + dry.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--install-timer"],
        ["--install-timer", "--soak-env-file"],
        ["--install-timer", "--soak-env-file", "relative/soak.env"],
        ["--install-timer", "--soak-env-file", "/home/trading/soak env"],
        ["--soak-env-file", SOAK_ENV],
        ["--set-credential", "--install-timer", "--soak-env-file", SOAK_ENV],
        ["--unknown"],
        ["--install-timer", "--soak-env-file", SOAK_ENV, "extra"],
    ],
    ids=[
        "no env file",
        "missing value",
        "relative",
        "space",
        "env file without install",
        "two modes",
        "unknown flag",
        "stray argument",
    ],
)
def test_a_mode_combination_the_script_does_not_know_exits_2(
    install_rig: Rig, args: list[str]
) -> None:
    proc = install_rig.run(*args)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert install_rig.lines() == []
    assert not (install_rig.prefix / "etc" / "systemd").exists()


def test_the_script_names_every_flag_in_its_help(rig: Rig) -> None:
    proc = rig.run("--help")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for flag in ("--set-credential", "--install-timer", "--soak-env-file", "--dry-run"):
        assert flag in proc.stderr
    for code in range(7):
        assert re.search(rf"^\s*{code}\s", proc.stderr, re.MULTILINE), code


# --- Test 14: the unit files ----------------------------------------------------------------------

LINK_DIRECTIVE = re.compile(
    r"^(Requires|Requisite|BindsTo|PartOf|Conflicts|Restart|OnFailure|OnSuccess|Upholds)\w*\s*=",
    re.IGNORECASE,
)


def _directive_lines(text: str) -> list[str]:
    return [ln.strip() for ln in _strip_comments(text).splitlines() if ln.strip()]


def test_the_service_is_a_oneshot_with_the_credential_and_no_link_to_any_other_unit() -> None:
    lines = _directive_lines((UNITS / SERVICE).read_text(encoding="utf-8"))
    assert "Type=oneshot" in lines and "User=trading" in lines
    assert "LoadCredential=freeze-witness:@CREDENTIAL_FILE@" in lines
    assert "WorkingDirectory=@TRADING_DIR@" in lines
    assert "Environment=TRADING_ENV_FILE=@SOAK_ENV_FILE@" in lines
    assert 'Environment="FREEZE_WITNESS_SCHEDULE=@SCHEDULE@"' in lines
    assert "RuntimeDirectory=trading-freeze-witness" in lines
    assert "RuntimeDirectoryMode=0700" in lines
    assert "TimeoutStartSec=15min" in lines
    assert "ExecStart=/usr/bin/env bash @TRADING_DIR@/deploy/freeze-witness.sh" in lines
    assert "Wants=network-online.target" in lines
    after = [ln for ln in lines if ln.startswith("After=")]
    assert after and "network-online.target" in after[0] and "docker.service" in after[0]
    assert [ln for ln in lines if LINK_DIRECTIVE.match(ln)] == []
    text = (UNITS / SERVICE).read_text(encoding="utf-8")
    for other in ("paper.service", "trading-soak-backup", "heartbeat", "trading-soak-paper"):
        assert other not in "\n".join(lines), other
    assert "16-DEC-HOST-TICK" in text and "O-01" in text and "no catch-up" in text.lower()


def test_the_timer_fires_at_the_workflow_minute_without_catch_up_or_random_delay() -> None:
    text = (UNITS / TIMER).read_text(encoding="utf-8")
    lines = _directive_lines(text)
    assert "OnCalendar=*-*-* *:@CRON_MINUTE@:00 UTC" in lines
    assert "Persistent=false" in lines
    assert "AccuracySec=1s" in lines
    assert f"Unit={SERVICE}" in lines and "WantedBy=timers.target" in lines
    assert [ln for ln in lines if re.match(r"^(RandomizedDelaySec|FixedRandomDelay)", ln)] == []
    assert [ln for ln in lines if re.match(r"^(OnBootSec|OnUnitActiveSec|OnStartupSec)", ln)] == []
    assert "16-DEC-HOST-TICK" in text and "server time" in text.lower()


def test_no_host_name_account_id_or_url_is_in_the_units_or_the_script() -> None:
    script = _strip_comments((DEPLOY / SCRIPT).read_text(encoding="utf-8"))
    literal = [ln for ln in script.splitlines() if "https://" in ln or "http://" in ln]
    assert len(literal) == 1 and literal[0].startswith("BUCKET_URL_PATTERN="), literal
    for path in (DEPLOY / SCRIPT, UNITS / SERVICE, UNITS / TIMER):
        text = path.read_text(encoding="utf-8")
        assert "amazonaws" not in text.lower(), path.name
        assert not re.search(r"\b\d{12}\b", text), path.name
        assert "AKIA" not in text, path.name
    for path in (UNITS / SERVICE, UNITS / TIMER):
        assert "://" not in path.read_text(encoding="utf-8")


def test_the_script_never_passes_the_credential_to_a_command() -> None:
    text = _strip_comments((DEPLOY / SCRIPT).read_text(encoding="utf-8"))
    assert "export " in text  # MSYS_NO_PATHCONV and DRY_RUN only
    exported = re.findall(r"^\s*export ([A-Za-z_]+)", text, re.MULTILINE)
    assert set(exported) <= {"MSYS_NO_PATHCONV", "DRY_RUN"}, exported
    assert "set -x" not in text and "set -o xtrace" not in text
    assert "--config -" in text
    holders = [
        ln
        for ln in text.splitlines()
        if re.search(r"\$\{?CRED_(SECRET|KEY_ID|BUCKET_URL)\b", ln) and not ln.startswith("local ")
    ]
    assert len(holders) == 1 and holders[0].lstrip().startswith("printf 'url = "), holders
