"""The Phase 13.1 operations documents stay equal to the files they describe (13.1-11, D-16, D-26).

The runbook pin table (section 16) is parsed and compared with what the Dockerfile, the compose
file, the four workflows, ``tests/docker_helpers.py``, the sshd sidecar Dockerfile and
``.python-version`` actually use, so a bump that forgets the table (or the other way round) fails
here. ``deploy/refresh-pins.sh --list`` is checked against the same table through real bash.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"
SEC_OPS = REPO_ROOT / "docs" / "operations" / "SECURITY_AND_OPERATIONS.md"
DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
DOC_STATUS = REPO_ROOT / "docs" / "DOC_STATUS.md"
SOURCES = REPO_ROOT / "docs" / "SOURCES.md"
REFRESH = REPO_ROOT / "deploy" / "refresh-pins.sh"

DOCKERFILE = REPO_ROOT / "Dockerfile"
SSHD_DOCKERFILE = REPO_ROOT / "tests" / "fixtures" / "cutover" / "Dockerfile.sshd"
COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKER_HELPERS = REPO_ROOT / "tests" / "docker_helpers.py"
PYTHON_VERSION = REPO_ROOT / ".python-version"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

IMAGE_NAMES = ("python", "postgres", "uv", "rclone")
SHA256 = r"sha256:[0-9a-f]{64}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _runbook() -> str:
    return _read(RUNBOOK)


def _section(text: str, number: int) -> str:
    """Body of ``## <number>. ...`` up to the next level-2 heading ('' when absent)."""
    match = re.search(rf"^## {number}\. [^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(0) if match else ""


def _table_rows(section: str, first_header: str) -> list[dict[str, str]]:
    """Rows of the markdown table whose header row starts with ``| <first_header> |``."""
    lines = section.split("\n")
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith(f"| {first_header} |")),
        None,
    )
    if start is None:
        return []
    headers = [c.strip() for c in lines[start].strip().strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for ln in lines[start + 2 :]:
        if not ln.startswith("|"):
            break
        cells = [c.strip().strip("`") for c in ln.strip().strip("|").split("|")]
        rows.append(dict(zip(headers, cells, strict=False)))
    return rows


# --------------------------------------------------------------------------- pins in the files


def _image_refs(text: str) -> list[tuple[str, str, str]]:
    """(name, tag, digest) for each ``<repo>/<name>:<tag>@sha256:...`` in ``text``."""
    joined = re.sub(r'"\s*\n\s*"', "", text)  # python string literals split over lines
    found = []
    for name, tag, digest in re.findall(rf"([\w./-]+):([\w.\-]+)@({SHA256})", joined):
        base = name.rsplit("/", 1)[-1]
        if base in IMAGE_NAMES:
            found.append((base, tag, digest))
    return found


def _repo_images() -> dict[str, tuple[str, str]]:
    """Map name -> (tag, digest) from the Dockerfile and compose file (others must agree)."""
    pins: dict[str, tuple[str, str]] = {}
    for path in (DOCKERFILE, COMPOSE):
        for name, tag, digest in _image_refs(_read(path)):
            assert pins.setdefault(name, (tag, digest)) == (tag, digest), (
                f"{path.name}: two different pins for {name}"
            )
    return pins


def _workflow_actions() -> dict[str, tuple[str, str]]:
    """Map owner/repo -> (sha, tag) over every ``uses:`` line of every workflow."""
    actions: dict[str, tuple[str, str]] = {}
    for path in WORKFLOWS:
        for repo, sha, tag in re.findall(
            r"uses:\s*([\w.-]+/[\w.-]+)(?:/[\w./-]+)?@([0-9a-f]{40})\s*#\s*(v[\w.]+)",
            _read(path),
        ):
            assert actions.setdefault(repo, (sha, tag)) == (sha, tag), (
                f"{path.name}: two different pins for {repo}"
            )
    return actions


def test_the_files_pin_exactly_four_images_and_five_actions() -> None:
    assert sorted(_repo_images()) == sorted(IMAGE_NAMES)
    assert len(_workflow_actions()) == 5


def test_every_occurrence_of_an_image_uses_the_same_digest() -> None:
    pins = _repo_images()
    expected_files = {
        "python": (DOCKERFILE, SSHD_DOCKERFILE),
        "postgres": (COMPOSE, REPO_ROOT / ".github" / "workflows" / "ci.yml", DOCKER_HELPERS),
        "uv": (DOCKERFILE,),
        "rclone": (DOCKERFILE, DOCKER_HELPERS),
    }
    for name, files in expected_files.items():
        for path in files:
            refs = [r for r in _image_refs(_read(path)) if r[0] == name]
            assert refs, f"{path.name} does not pin {name}"
            for _, tag, digest in refs:
                assert (tag, digest) == pins[name], f"{path.name}: {name} differs from the pin"


def test_uv_version_is_identical_in_workflows_and_dockerfile() -> None:
    uv_tag = _repo_images()["uv"][0]
    for path in WORKFLOWS:
        text = _read(path)
        if "astral-sh/setup-uv" not in text:
            continue
        versions = re.findall(r'^\s+version:\s*"([^"]+)"', text, re.M)
        assert versions, f"{path.name}: setup-uv has no exact version"
        assert set(versions) == {uv_tag}, f"{path.name}: uv {set(versions)} != image {uv_tag}"


def test_python_patch_is_identical_in_python_version_and_images() -> None:
    patch = _read(PYTHON_VERSION).strip()
    assert re.fullmatch(r"3\.13\.\d+", patch)
    assert _repo_images()["python"][0] == f"{patch}-slim-bookworm"
    sidecar = [r for r in _image_refs(_read(SSHD_DOCKERFILE)) if r[0] == "python"]
    assert sidecar and sidecar[0][1] == f"{patch}-slim-bookworm"


# --------------------------------------------------------------------------- the pin table


def _pin_section() -> str:
    section = _section(_runbook(), 16)
    assert section, "RUNBOOK has no '## 16. Image and action pins' section"
    return section


def test_runbook_section_16_heading_and_digests_present() -> None:
    text = _runbook()
    assert re.search(r"^## 16\. Image and action pins$", text, re.M)
    assert len(re.findall(r"sha256:", text)) >= 4


def test_pin_table_images_equal_the_files() -> None:
    rows = _table_rows(_pin_section(), "Image")
    table = {r["Image"]: (r["Tag"], r["Digest"]) for r in rows}
    assert table == _repo_images()


def test_pin_table_versions_equal_the_files() -> None:
    rows = _table_rows(_pin_section(), "Tool")
    table = {r["Tool"]: r["Version"] for r in rows}
    assert table == {
        "uv": _repo_images()["uv"][0],
        "python": _read(PYTHON_VERSION).strip(),
    }


def test_pin_table_actions_equal_the_workflows() -> None:
    rows = _table_rows(_pin_section(), "Action")
    table = {r["Action"]: (r["Commit SHA"], r["Tag"]) for r in rows}
    assert table == _workflow_actions()


def test_pin_section_states_the_refresh_procedure_and_the_one_exception() -> None:
    section = _pin_section()
    for phrase in (
        "deploy/refresh-pins.sh --lookup",
        "release notes",
        "one commit",
        "never automatic",
        "postgresql-client-17",
        "floats within major 17",
        "D-05",
    ):
        assert phrase in section, f"section 16 lacks: {phrase}"


# --------------------------------------------------------------------------- refresh-pins.sh


def _bash() -> str:
    bash = find_bash()
    if bash is None:
        infra_skip("bash not found")
    return bash


def _run_refresh(
    args: list[str], *, path_prefix: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix.as_posix()}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        [_bash(), REFRESH.as_posix(), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )


def _failing_stubs(directory: Path) -> Path:
    """curl and git that log every call and fail: --list must never reach for the network."""
    log = directory / "net.log"
    for name in ("curl", "git"):
        stub = directory / name
        stub.write_text(
            f'#!/usr/bin/env bash\necho "{name} $*" >> "{log.as_posix()}"\nexit 99\n',
            encoding="utf-8",
            newline="\n",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return log


def test_refresh_pins_script_exists_with_the_hygiene_header() -> None:
    lines = _read(REFRESH).split("\n")
    assert lines[0] == "#!/usr/bin/env bash"
    assert "set -Eeuo pipefail" in lines[:15]


def test_refresh_pins_list_is_offline_and_equals_the_table(tmp_path: Path) -> None:
    log = _failing_stubs(tmp_path)
    proc = _run_refresh(["--list"], path_prefix=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert not log.exists(), "--list must not call curl or git"

    images = {}
    for line in proc.stdout.splitlines():
        match = re.fullmatch(rf"([a-z]+):([\w.\-]+)@({SHA256})", line.strip())
        if match:
            images[match.group(1)] = (match.group(2), match.group(3))
    assert images == _repo_images()

    assert f"uv-version {_repo_images()['uv'][0]}" in proc.stdout.splitlines()
    assert f"python-version {_read(PYTHON_VERSION).strip()}" in proc.stdout.splitlines()
    actions = {}
    for line in proc.stdout.splitlines():
        match = re.fullmatch(r"([\w.-]+/[\w.-]+)@([0-9a-f]{40}) (v[\w.]+)", line.strip())
        if match:
            actions[match.group(1)] = (match.group(2), match.group(3))
    assert actions == _workflow_actions()


def test_refresh_pins_rejects_unknown_options_and_no_arguments() -> None:
    assert _run_refresh(["--bogus"]).returncode == 2
    assert _run_refresh([]).returncode == 2


def _lookup_stubs(directory: Path, *, moved: bool) -> None:
    """curl: token JSON for token endpoints, a digest header per manifest tag; git: ls-remote."""
    new_digest = "sha256:" + "f" * 64
    manifest_cases = "".join(
        f"  *manifests/{tag}*) printf 'HTTP/2 200\\r\\n"
        f"docker-content-digest: {new_digest if moved else digest}\\r\\n\\r\\n' ;;\n"
        for tag, digest in _repo_images().values()
    )
    curl_lines = [
        "#!/usr/bin/env bash",
        'case "$*" in',
        manifest_cases + '  *token*) printf \'{"token":"stubtoken"}\' ;;',
        "esac",
        "",
    ]
    (directory / "curl").write_text("\n".join(curl_lines), encoding="utf-8", newline="\n")
    sha_moved = "e" * 40
    git_cases = "".join(
        f"  *{repo}*) printf '{sha_moved if moved else sha}\\trefs/tags/{tag}\\n' ;;\n"
        for repo, (sha, tag) in _workflow_actions().items()
    )
    git_lines = ["#!/usr/bin/env bash", 'case "$*" in', git_cases + "esac", ""]
    (directory / "git").write_text("\n".join(git_lines), encoding="utf-8", newline="\n")
    for name in ("curl", "git"):
        (directory / name).chmod((directory / name).stat().st_mode | stat.S_IEXEC)


def _digest_of_files() -> dict[Path, str]:
    paths = [DOCKERFILE, COMPOSE, PYTHON_VERSION, RUNBOOK, *WORKFLOWS]
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_refresh_pins_lookup_is_read_only_and_reports_moves(tmp_path: Path) -> None:
    before = _digest_of_files()
    _lookup_stubs(tmp_path, moved=False)
    same = _run_refresh(["--lookup"], path_prefix=tmp_path)
    assert same.returncode == 0, same.stderr
    assert "MOVED" not in same.stdout

    _lookup_stubs(tmp_path, moved=True)
    moved = _run_refresh(["--lookup"], path_prefix=tmp_path)
    assert moved.returncode == 0, moved.stderr
    assert "MOVED" in moved.stdout
    assert "sha256:" + "f" * 64 in moved.stdout
    assert before == _digest_of_files(), "--lookup must never edit a repository file"
