"""The D064 real-S3 gate procedure (261020-bkp C), against a directory-backed fake only.

No rclone binary, no network: the fake models one bucket as a directory, with the crypt layer as
an identity mapping rooted at ``<bucket>/<subpath>`` and the raw remote as the bucket itself, so
a raw overwrite at the "provider" changes the bytes the crypt layer reads. ``cryptcheck`` is the
hash-aware model of ``tests/test_backup_remote.py``. The real result needs the owner's real S3
remote (RUNBOOK 11, "Real-S3 gate").
"""

from __future__ import annotations

import io
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from src.ops import backup_gate as gate
from src.ops import backup_remote as remote
from src.ops.backup import main
from src.ops.backup_remote import RcloneResult, RemoteConfigError

from tests.test_backup_remote import S3_ENV, SECRET_VALUES, StoreRclone
from tests.test_deploy_backup_scripts import DEPLOY, PY, Rig, _write, rig  # noqa: F401

NOW = datetime(2026, 10, 20, 9, 30, 0, tzinfo=UTC)
PREFIX = "d064-gate-20261020T093000Z-0123456789ab"
BUCKET = S3_ENV["BACKUP_S3_BUCKET"]
MULTIPART_MIB = gate.MIN_MULTIPART_MIB
RAW = f"{remote.S3_REMOTE}:"


class BucketRunner(StoreRclone):
    """``StoreRclone`` whose crypt root is ``<bucket>/<sub>`` and which also serves raw calls."""

    def __init__(self, bucket_root: Path, sub: str, log: list[tuple[list[str], dict[str, str]]]):
        self.bucket_root = bucket_root
        self.log = log
        self.calls = []
        self.lists = []
        self.store = bucket_root / BUCKET / sub  # created lazily by the first write

    def _path(self, arg: str) -> Path:
        if arg.startswith(RAW):
            return self.bucket_root / arg[len(RAW) :].rstrip("/")
        return super()._path(arg)

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.log.append((list(argv), dict(env)))
        verb = argv[0]
        if verb == "version":
            self.calls.append(list(argv))
            return RcloneResult(0, "rclone v0.0.0-fake\n- os/version: test\n", "")
        if verb == "lsf" and argv[-1].startswith(RAW):
            self.calls.append(list(argv))
            root = self._path(argv[-1])
            if not root.is_dir():
                return RcloneResult(3, "", "directory not found")
            files = sorted(p for p in root.rglob("*") if p.is_file())
            if "--format" in argv:
                sep = argv[list(argv).index("--separator") + 1]
                lines = [f"{p.relative_to(root).as_posix()}{sep}{p.stat().st_size}" for p in files]
            else:
                lines = [p.relative_to(root).as_posix() for p in files]
            return RcloneResult(0, "".join(f"{line}\n" for line in lines), "")
        if verb == "purge" and argv[1].startswith(RAW):
            self.calls.append(list(argv))
            target = self._path(argv[1])
            if not target.is_dir():
                return RcloneResult(3, "", "directory not found")
            shutil.rmtree(target)
            return RcloneResult(0, "", "")
        if verb == "copyto" and argv[2].startswith(RAW):
            self.calls.append(list(argv))
            target = self._path(argv[2])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(argv[1]).read_bytes())
            return RcloneResult(0, "", "")
        if verb == "cat" and not self._path(argv[1]).is_file():
            self.calls.append(list(argv))
            return RcloneResult(3, "", "object not found")
        return super().__call__(argv, env)


class FakeBucket:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.log: list[tuple[list[str], dict[str, str]]] = []

    def runner_for(self, sub: str) -> BucketRunner:
        return self.runner_class(self.root, sub, self.log)

    runner_class: type[BucketRunner] = BucketRunner

    def raw_for(self, sub: str) -> str:
        return f"{RAW}{BUCKET}/{sub}"

    def remote(self) -> gate.GateRemote:
        return gate.GateRemote(runner_for=self.runner_for, raw_for=self.raw_for)

    def prefix_dir(self, prefix: str = PREFIX) -> Path:
        return self.root / BUCKET / prefix

    def verbs(self) -> list[str]:
        return [argv[0] for argv, _ in self.log]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for name, value in S3_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("BACKUP_REMOTE", raising=False)
    return dict(S3_ENV)


def _run(
    bucket: FakeBucket | None,
    *,
    execute: bool,
    environ: Mapping[str, str],
    prefix: str | None = PREFIX,
    evidence: Path | None = None,
    multipart_mib: int = MULTIPART_MIB,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = gate.cli_real_s3_gate(
        execute=execute,
        prefix=prefix,
        evidence=evidence,
        multipart_mib=multipart_mib,
        remote=bucket.remote() if bucket is not None else None,
        now_utc=NOW,
        out=out,
        err=err,
        environ=environ,
    )
    return code, out.getvalue(), err.getvalue()


def _claims(out: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in out.splitlines():
        if line.startswith("CLAIM "):
            claim, _, rest = line[len("CLAIM ") :].partition(": ")
            found[claim] = rest.split(" ", 1)[0]
    return found


# --- the remote mapping the gate shares with the backup ---------------------------------------


def test_rclone_env_roots_the_crypt_remote_at_a_subpath_of_the_same_bucket() -> None:
    plain = remote.rclone_env(S3_ENV)
    nested = remote.rclone_env(S3_ENV, subpath=f"{PREFIX}/s1")
    key = f"RCLONE_CONFIG_{remote.CRYPT_REMOTE}_REMOTE"
    assert plain[key] == f"{remote.S3_REMOTE}:{BUCKET}"
    assert nested[key] == f"{remote.S3_REMOTE}:{BUCKET}/{PREFIX}/s1"
    assert {k: v for k, v in nested.items() if k != key} == {
        k: v for k, v in plain.items() if k != key
    }
    assert (
        remote.raw_bucket_remote(S3_ENV, subpath=PREFIX) == f"{remote.S3_REMOTE}:{BUCKET}/{PREFIX}"
    )


@pytest.mark.parametrize("sub", ["/abs", "a/../b", "a//b", "a/", "with space", "a\\b", ".."])
def test_rclone_env_refuses_an_unsafe_subpath(sub: str) -> None:
    with pytest.raises(RemoteConfigError):
        remote.rclone_env(S3_ENV, subpath=sub)


def test_the_multipart_options_force_small_parts_on_the_s3_backend() -> None:
    extra = remote.force_multipart_env(S3_ENV)
    assert extra == {
        f"RCLONE_CONFIG_{remote.S3_REMOTE}_UPLOAD_CUTOFF": "5M",
        f"RCLONE_CONFIG_{remote.S3_REMOTE}_CHUNK_SIZE": "5M",
    }


# --- dry run -----------------------------------------------------------------------------------


class NoCalls:
    def runner_for(self, sub: str) -> remote.RcloneRunner:
        raise AssertionError("the dry run built a runner")

    def raw_for(self, sub: str) -> str:
        raise AssertionError("the dry run asked for the raw remote")


def test_the_default_is_a_dry_run_that_prints_the_plan_and_touches_nothing(
    env: dict[str, str], tmp_path: Path
) -> None:
    out, err = io.StringIO(), io.StringIO()
    evidence = tmp_path / "ev.txt"
    code = gate.cli_real_s3_gate(
        execute=False,
        prefix=None,
        evidence=evidence,
        multipart_mib=12,
        remote=gate.GateRemote(runner_for=NoCalls().runner_for, raw_for=NoCalls().raw_for),
        now_utc=NOW,
        out=out,
        err=err,
        environ=env,
    )
    text = out.getvalue()
    assert code == 0, err.getvalue()
    assert "DRY RUN" in text and "--execute" in text
    assert set(_claims(text)) == set(gate.CLAIM_IDS)
    assert set(_claims(text).values()) == {"PLANNED"}
    assert "prefix: d064-gate-20261020T093000Z-" in text
    assert not evidence.exists()
    assert BUCKET not in text


# --- execute: success, failure, interruption ---------------------------------------------------


def test_execute_passes_every_claim_writes_the_evidence_and_purges_the_prefix(
    env: dict[str, str], tmp_path: Path
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    (bucket.root / BUCKET / "existing-backup-object").parent.mkdir(parents=True)
    (bucket.root / BUCKET / "existing-backup-object").write_bytes(b"real backup data")
    evidence = tmp_path / "evidence" / "gate.txt"

    code, out, err = _run(bucket, execute=True, environ=env, evidence=evidence)

    claims = _claims(out)
    assert code == 0, out + err
    assert set(claims) == set(gate.CLAIM_IDS)
    assert set(claims.values()) == {"PASS"}, out
    assert out.rstrip().endswith("RESULT: PASS")
    assert evidence.read_text(encoding="utf-8") == out
    assert not bucket.prefix_dir().exists(), "the throwaway prefix is purged"
    assert (bucket.root / BUCKET / "existing-backup-object").read_bytes() == b"real backup data"
    for value in (*SECRET_VALUES, BUCKET):
        assert value not in out + err
    assert "rclone: rclone v0.0.0-fake" not in out  # an injected remote reports no version
    multipart = [e for argv, e in bucket.log if e]
    assert multipart, "the multipart arm passes its options to every call of its scenario"
    assert all(e[f"RCLONE_CONFIG_{remote.S3_REMOTE}_UPLOAD_CUTOFF"] == "5M" for e in multipart)
    # every write of the gate stayed below the prefix
    for argv, _ in bucket.log:
        for arg in argv[1:]:
            if arg.startswith(RAW):
                assert arg.startswith(f"{RAW}{BUCKET}/{PREFIX}"), argv


class BlindCheck(BucketRunner):
    """A check that sees nothing: every cryptcheck passes. The detection claims must FAIL."""

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        if argv[0] == "cryptcheck":
            self.log.append((list(argv), dict(env)))
            self.calls.append(list(argv))
            return RcloneResult(0, "", "")
        return super().__call__(argv, env)


def test_a_blind_check_fails_the_detection_claims_and_still_cleans_up(
    env: dict[str, str], tmp_path: Path
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    bucket.runner_class = BlindCheck

    code, out, _err = _run(bucket, execute=True, environ=env)

    claims = _claims(out)
    assert code == 1
    assert out.rstrip().endswith("RESULT: FAIL")
    for claim in (
        "detect-modified-through-crypt",
        "detect-modified-at-provider",
        "detect-deleted",
        "upload-then-check-failure-incomplete",
        "failed-manifest-check-removed",
        "multipart-modified-detected",
    ):
        assert claims[claim] == "FAIL", claim
    assert claims["skip-unchanged"] == "PASS"
    assert claims["cleanup"] == "PASS"
    assert not bucket.prefix_dir().exists()


class Interrupting(BucketRunner):
    """Ctrl-C in the middle of the run (the fourth scenario's first write)."""

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        if "s4-provider-modify" in str(self.store) and argv[0] == "copy":
            raise KeyboardInterrupt
        return super().__call__(argv, env)


def test_an_interrupted_run_fails_and_still_purges_the_prefix(
    env: dict[str, str], tmp_path: Path
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    bucket.runner_class = Interrupting

    code, out, _err = _run(bucket, execute=True, environ=env)

    claims = _claims(out)
    assert code == 1
    assert "INTERRUPTED" in out
    assert claims["skip-unchanged"] == "PASS"
    assert claims["detect-modified-at-provider"] == "FAIL"
    assert claims["cleanup"] == "PASS"
    assert not bucket.prefix_dir().exists()


class BrokenPurge(BucketRunner):
    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        if argv[0] == "purge":
            self.log.append((list(argv), dict(env)))
            return RcloneResult(5, "", "temporary error")
        return super().__call__(argv, env)


def test_a_failed_cleanup_is_a_fail_that_names_the_prefix(
    env: dict[str, str], tmp_path: Path
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    bucket.runner_class = BrokenPurge

    code, out, _err = _run(bucket, execute=True, environ=env)

    assert code == 1
    cleanup = next(line for line in out.splitlines() if line.startswith("CLAIM cleanup:"))
    assert "FAIL" in cleanup and PREFIX in cleanup and "by hand" in cleanup


# --- refusals (exit 2, nothing touched) --------------------------------------------------------


def test_a_prefix_that_already_holds_objects_is_refused_before_any_write(
    env: dict[str, str], tmp_path: Path
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    leftover = bucket.prefix_dir() / "s1-manifest" / "object"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"do not touch")

    code, out, err = _run(bucket, execute=True, environ=env)

    assert code == 2
    assert out == ""
    assert "already holds objects" in err and PREFIX in err
    assert leftover.read_bytes() == b"do not touch"
    assert set(bucket.verbs()) == {"lsf"}


@pytest.mark.parametrize(
    "prefix",
    [
        "backups",
        "",
        "d064-gate-20261020T093000Z-0123",
        "d064-gate-20261020T093000Z-0123456789ab/x",
        "snapshots",
        "../d064-gate-20261020T093000Z-0123456789ab",
    ],
)
def test_a_prefix_that_is_not_a_throwaway_gate_prefix_is_refused(
    env: dict[str, str], tmp_path: Path, prefix: str
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    code, _out, err = _run(bucket, execute=True, environ=env, prefix=prefix)
    assert code == 2
    assert "--prefix" in err
    assert bucket.log == []


def test_local_only_mode_has_nothing_to_gate(env: dict[str, str], tmp_path: Path) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    code, _out, err = _run(bucket, execute=True, environ={**env, "BACKUP_REMOTE": "none"})
    assert code == 2 and "BACKUP_REMOTE=none" in err
    assert bucket.log == []


def test_a_missing_variable_is_named_and_nothing_is_touched(
    env: dict[str, str], tmp_path: Path
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    partial = {k: v for k, v in env.items() if k != "BACKUP_CRYPT_PASSWORD2"}
    for execute in (False, True):
        code, _out, err = _run(bucket, execute=execute, environ=partial)
        assert code == 2
        assert "BACKUP_CRYPT_PASSWORD2" in err
        for value in SECRET_VALUES:
            assert value not in err
    assert bucket.log == []


def test_an_existing_evidence_file_or_a_small_multipart_size_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    existing = _write(tmp_path / "ev.txt", "earlier evidence\n")
    code, _out, err = _run(bucket, execute=True, environ=env, evidence=existing)
    assert code == 2 and "already exists" in err
    assert existing.read_text(encoding="utf-8") == "earlier evidence\n"
    code, _out, err = _run(bucket, execute=True, environ=env, multipart_mib=5)
    assert code == 2 and "--multipart-mib" in err
    assert bucket.log == []


def test_the_backup_cli_dispatches_real_s3_gate(
    env: dict[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bucket = FakeBucket(tmp_path / "s3")
    code = main(["real-s3-gate", "--prefix", PREFIX], gate_remote=bucket.remote(), now_utc=NOW)
    out = capsys.readouterr().out
    assert code == 0
    assert "DRY RUN" in out
    assert bucket.log == []
    code = main(["real-s3-gate", "--prefix", "nope"], gate_remote=bucket.remote(), now_utc=NOW)
    assert code == 2


# --- the wrapper -------------------------------------------------------------------------------

GATE_CALL = f"--profile ops run --rm -T --no-deps ops {PY} -m src.ops.backup real-s3-gate"


def test_the_wrapper_default_runs_only_the_python_plan(rig: Rig) -> None:  # noqa: F811
    proc = rig.run("backup-real-s3-gate.sh")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (call,) = rig.docker_lines()
    assert call.endswith(GATE_CALL), call
    assert "--execute" not in call


def test_the_wrapper_dry_run_flag_runs_nothing(rig: Rig) -> None:  # noqa: F811
    proc = rig.run("backup-real-s3-gate.sh", "--execute", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert rig.lines() == []
    assert "real-s3-gate --execute" in proc.stdout


def test_the_wrapper_execute_writes_the_evidence_file_and_passes_the_exit_code(
    rig: Rig,  # noqa: F811
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "gate-evidence"
    proc = rig.run(
        "backup-real-s3-gate.sh",
        "--execute",
        "--evidence-dir",
        evidence_dir.as_posix(),
        env={"STUB_GATE_RC": "1", "STUB_GATE_OUT": "CLAIM x: FAIL\nRESULT: FAIL"},
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    (call,) = rig.docker_lines()
    assert call.endswith(f"{GATE_CALL} --execute"), call
    (written,) = list(evidence_dir.glob("d064-real-s3-gate-*.txt"))
    assert written.read_text(encoding="utf-8") == "CLAIM x: FAIL\nRESULT: FAIL\n"
    assert written.name in proc.stderr


@pytest.mark.parametrize("args", [["--evidence-dir"], ["--bogus"], ["--prefix", "x"]])
def test_the_wrapper_usage_errors_exit_two(rig: Rig, args: list[str]) -> None:  # noqa: F811
    proc = rig.run("backup-real-s3-gate.sh", *args)
    assert proc.returncode == 2
    assert rig.lines() == []


def test_the_wrapper_holds_no_remote_logic() -> None:
    text = (DEPLOY / "backup-real-s3-gate.sh").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "rclone" not in code and "src.ops.backup real-s3-gate" in code
