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

import pytest

from tests.infra_helpers import find_bash, infra_skip

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"
SEC_OPS = REPO_ROOT / "docs" / "operations" / "SECURITY_AND_OPERATIONS.md"
DECISIONS = REPO_ROOT / "docs" / "DECISIONS.md"
DOC_STATUS = REPO_ROOT / "docs" / "DOC_STATUS.md"
SOURCES = REPO_ROOT / "docs" / "SOURCES.md"
REFRESH = REPO_ROOT / "deploy" / "refresh-pins.sh"
DEPLOY_DIR = REPO_ROOT / "deploy"

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
    command = [_bash(), REFRESH.as_posix(), *args]
    if path_prefix is not None:
        # Git Bash re-orders PATH when it starts (/mingw64/bin and /usr/bin first, and a nested
        # bash does it again), so a stub directory prepended through the environment loses to the
        # real curl/git. BASH_ENV is sourced after that start-up, so prepend it from there, as a
        # bash-native path, and the stubs win on Windows and Linux alike.
        hook = path_prefix / "stub-path.sh"
        hook.write_text(
            'if command -v cygpath >/dev/null 2>&1; then d="$(cygpath -u "$STUB_DIR")"; '
            'else d="$STUB_DIR"; fi\nPATH="$d:$PATH"\nexport PATH\n',
            encoding="utf-8",
            newline="\n",
        )
        env["STUB_DIR"] = path_prefix.as_posix()
        env["BASH_ENV"] = hook.as_posix()
    return subprocess.run(
        command,
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


# --------------------------------------------------------------------------- runbook procedures

OPERATION_SECTIONS = {
    13: "Host bootstrap",
    14: "Update and rollback",
    15: "Provider migration (cutover)",
    16: "Image and action pins",
    17: "Tested locally or in CI versus needs a real host",
    18: "CI pipeline",
}
TESTED_BY = {"local test", "CI docker job", "real host (operator)"}

SCRIPT_SECTION = {
    "bootstrap.sh": 13,
    "update.sh": 14,
    "migrate.sh": 15,
    "backup.sh": 11,
    "restore.sh": 11,
    "backup-drill.sh": 11,
    "backup-real-s3-gate.sh": 11,
    "heartbeat.sh": 11,
}


def _missing(section: str, phrases: tuple[str, ...]) -> list[str]:
    return [p for p in phrases if p not in section]


def test_runbook_has_sections_13_to_18_in_order_after_12() -> None:
    text = _runbook()
    headings = re.findall(r"^## (\d+)\. (.+)$", text, re.M)
    numbers = [int(n) for n, _ in headings]
    assert numbers == sorted(numbers), "sections must stay in numeric order"
    assert numbers[:12] == list(range(1, 13)), "sections 1-12 must not be renumbered"
    titles = {int(n): title.strip() for n, title in headings}
    for number, title in OPERATION_SECTIONS.items():
        assert titles.get(number) == title, f"## {number}. {title} is missing or renamed"


def test_section_11_covers_the_backup_scripts_retention_and_key_loss() -> None:
    section = _section(_runbook(), 11)
    missing = _missing(
        section,
        (
            "deploy/backup.sh",
            "deploy/restore.sh",
            "deploy/backup-drill.sh",
            "7/4/6",
            "--init-remote",
            "--install-timer",
            "unrecoverable",
            "passphrase",
            "object lock",
            "heartbeat",
            "restore-",
            "drill-",
        ),
    )
    assert not missing, f"section 11 lacks: {missing}"
    # the original wording stays (gates and readers rely on it)
    assert "A backup is not considered valid until a restore test succeeds." in section


def test_section_15_states_the_cutover_contract() -> None:
    section = _section(_runbook(), 15)
    missing = _missing(
        section,
        (
            "deploy/migrate.sh",
            "pre-sync",
            "permanent loss",
            "recoverable",
            "60 minutes",
            "--max-gap-minutes",
            "docker run",
            "sudo rsync",
            "Phase 13.1 ops image",
            "by hand",
            "human",
        ),
    )
    assert not missing, f"section 15 lacks: {missing}"
    for code in ("0", "1", "2", "3"):
        assert re.search(rf"\| `?{code}`? \|", section), f"exit code {code} is not tabulated"


def test_section_14_warns_that_a_code_rollback_does_not_undo_a_migration() -> None:
    section = _section(_runbook(), 14)
    missing = _missing(
        section,
        (
            "deploy/update.sh --ref",
            "deploy/update.sh --rollback",
            "--skip-backup",
            "last-good.env",
            "schema migration",
            "deploy/restore.sh",
            "roll back first",
        ),
    )
    assert not missing, f"section 14 lacks: {missing}"


def test_section_13_states_bootstrap_prerequisites_and_firewall_facts() -> None:
    section = _section(_runbook(), 13)
    missing = _missing(
        section,
        (
            "deploy/bootstrap.sh",
            "--dry-run",
            "authorized key",
            "second SSH session",
            "unattended-upgrades",
            "UTC",
            "does not govern",
            "127.0.0.1",
            "Ubuntu 22.04",
            "Ubuntu 24.04",
            "Debian 12",
        ),
    )
    assert not missing, f"section 13 lacks: {missing}"


def _subsection(text: str, number: str) -> str:
    """Body of ``### <number> ...`` up to the next heading ('' when absent)."""
    match = re.search(rf"^### {re.escape(number)} [^\n]*\n(.*?)(?=^##|\Z)", text, re.M | re.S)
    return match.group(0) if match else ""


def test_section_13_documents_sudo_with_a_password_after_ssh_hardening() -> None:
    """WR-05 (D062): trading is the administrator once root SSH login is off."""
    section = _section(_runbook(), 13)
    missing = _missing(
        section,
        (
            "passwd trading",
            "sudo -v",
            "sudo group",
            "passwd -S",
            "passwordless sudo rule",
            "`ufw`, `sudo`)",
            "PermitRootLogin no",
        ),
    )
    assert not missing, f"section 13 lacks: {missing}"
    checklist = _subsection(_runbook(), "13.5")
    assert "sudo /opt/trading/deploy/backup.sh --install-timer" in checklist
    assert "passwd trading" in checklist
    assert "sudo -v" in checklist


def test_runbook_no_longer_says_trading_has_no_sudo_or_to_use_the_console_for_root() -> None:
    text = _runbook()
    assert "has no sudo" not in text
    assert "from the provider console" not in text


def test_no_passwordless_sudo_rule_exists_in_deploy_or_the_runbook() -> None:
    keyword = "NOPASSWD"
    files = [p for p in sorted(DEPLOY_DIR.rglob("*")) if p.is_file()] + [RUNBOOK]
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in files
        if keyword in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, f"a passwordless sudo rule is named in: {offenders}"


def _script_flags(script: Path) -> set[str]:
    text = _read(script)
    flags: set[str] = set()
    pattern = r"^\s+((?:-h \| )?--[a-z][a-z-]*(?: \| --[a-z][a-z-]*)*)\)"
    for group in re.findall(pattern, text, re.M):
        flags.update(re.findall(r"--[a-z][a-z-]*", group))
    flags.discard("--help")
    return flags


@pytest.mark.parametrize("name", sorted(SCRIPT_SECTION))
def test_each_deploy_script_and_every_flag_is_named_in_its_runbook_section(name: str) -> None:
    number = SCRIPT_SECTION[name]
    section = _section(_runbook(), number)
    assert f"deploy/{name}" in section, f"section {number} never names deploy/{name}"
    flags = _script_flags(REPO_ROOT / "deploy" / name)
    assert flags, f"no flags parsed from {name}"
    missing = sorted(f for f in flags if f not in section)
    assert not missing, f"section {number} does not document {missing} of {name}"


def _step_ids(text: str) -> set[str]:
    ids: set[str] = set()
    for number in (11, 13, 14, 15):
        ids.update(re.findall(r"^### (\d+\.\d+) ", _section(text, number), re.M))
    return ids


def test_section_17_table_covers_every_step_with_only_the_allowed_labels() -> None:
    text = _runbook()
    rows = _table_rows(_section(text, 17), "Step")
    assert rows, "section 17 has no table"
    table = {r["Step"]: r for r in rows}
    assert set(table) == _step_ids(text), "section 17 must list exactly the steps of 11, 13-15"
    for step, row in table.items():
        labels = {label.strip() for label in row["Tested by"].split(";")}
        assert labels <= TESTED_BY, f"step {step}: unknown label {labels - TESTED_BY}"
        assert row["Notes"], f"step {step}: the Notes column must say what is proven where"


def test_section_17_names_what_only_a_real_host_can_show() -> None:
    section = _section(_runbook(), 17)
    missing = _missing(
        section,
        (
            "real host (operator)",
            "Docker apt",
            "ufw",
            "sshd",
            "chrony",
            "Ubuntu 24.04",
            "docker run",
            "systemd timer",
            "disk encryption",
            "IP whitelist",
            "heartbeat",
            "real bucket",
            "provider-to-provider",
            "not run locally",
        ),
    )
    assert not missing, f"section 17 lacks: {missing}"


def test_section_18_documents_the_ci_pipeline() -> None:
    section = _section(_runbook(), 18)
    missing = _missing(
        section,
        (
            "ci.yml",
            "TRADING_CI_STRICT",
            "test",
            "lint",
            "types",
            "docker",
            "registry-gate",
            "research-gate",
            "paper_freeze_check",
            "test_backfill_cli",
            "serial",
            "uv lock --check",
            "ruff format --check",
            "mypy src",
        ),
    )
    assert not missing, f"section 18 lacks: {missing}"


def test_runbook_keeps_secrets_out_of_the_operator_workflow() -> None:
    text = _runbook()
    missing = _missing(text, ("docker compose config -q", "rclone obscure", "raw passphrase"))
    assert not missing, f"RUNBOOK lacks the secrets rule: {missing}"
    assert "off the VPS" in text
    # a resolved compose config prints the interpolated environment: never run it bare
    assert not re.search(r"docker compose config\s*(?:$|\|)", text, re.M)


# Variables that only select which env file a service reads: the runbook documents them, the
# shared template does not (each service's own template does).
_ENV_FILE_SELECTORS = frozenset(
    {
        "TRADING_ENV_FILE",
        "TRADING_LIVE_ENV_FILE",
        "TRADING_PAPER_ENV_FILE",
        "TRADING_BACKUP_ENV_FILE",
    }
)


def test_every_compose_variable_is_documented_in_env_example() -> None:
    lines = _read(COMPOSE).splitlines()
    compose = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
    variables = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))
    assert {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "IMAGE_TAG"} <= variables
    env_example = _read(ENV_EXAMPLE)
    undocumented = sorted(
        v
        for v in variables - _ENV_FILE_SELECTORS
        if not re.search(rf"^#?\s*{v}=", env_example, re.M)
    )
    assert not undocumented, f".env.example does not document: {undocumented}"
    # TRADING_ENV_FILE selects which env file compose reads; the runbook documents it instead
    assert "TRADING_ENV_FILE" in compose
    assert "TRADING_ENV_FILE" in _runbook()
    # plans 24-30 and 24-36: the live, paper and backup services' own env files are selected the
    # same way and documented there
    for selector in sorted(_ENV_FILE_SELECTORS - {"TRADING_ENV_FILE"}):
        assert selector in compose, selector
        assert selector in _runbook(), selector


def test_security_and_operations_cites_d050_in_the_controlled_sections() -> None:
    text = _read(SEC_OPS)
    assert text.count("D050") >= 5
    for number in (1, 4, 6, 9, 10):
        assert "D050" in _section(text, number), f"section {number} does not cite D050"
    assert not _missing(_section(text, 1), ("0600", "separate", "paper/test", "live", "OPS-06"))
    section_9 = _section(text, 9)
    assert not _missing(section_9, ("7 daily", "4 weekly", "6 monthly", "unrecoverable"))
    assert "off the VPS" in section_9
    assert "redact" in _section(text, 6).lower()
    assert "health" in _section(text, 4).lower()


# --------------------------------------------------------------------------- decision records


def test_d050_follows_d049_and_summarises_the_phase() -> None:
    lines = _read(DECISIONS).split("\n")
    rows = [ln for ln in lines if ln.startswith("| D050 |")]
    assert len(rows) == 1
    row = rows[0]
    for phrase in ("rclone", "127.0.0.1", "Accepted (", "postgresql-client-17", "60 minutes"):
        assert phrase in row, f"D050 lacks: {phrase}"
    for audit_ref in ("F-101", "F-605", "F-705", "F-708", "F-709", "F-108", "F-910"):
        assert audit_ref in row
    index = lines.index(row)
    assert lines[index - 1].startswith("| D049 |"), "D050 must directly follow D049"
    assert row.count(" | ") == 3, "D050 must stay one table row (no stray pipes)"


def test_doc_status_logs_d050_and_sources_has_the_phase_facts() -> None:
    status = [ln for ln in _read(DOC_STATUS).split("\n") if "D050" in ln]
    assert status and status[0].startswith("- 2026-10-01")
    sources = _read(SOURCES)
    assert len(re.findall(r"^## Facts verified for Phase 13\.1 \(", sources, re.M)) == 1
    section = sources.split("## Facts verified for Phase 13.1", 1)[1]
    for digest in _repo_images().values():
        assert digest[1] in section, "SOURCES must carry every pinned image digest"
    for sha, _tag in _workflow_actions().values():
        assert sha in section, "SOURCES must carry every pinned action SHA"
    assert "ASSUMED" in section


# --------------------------------------------------------------------------- plan 16-50 heartbeat

DECISION_O12 = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "16-paper-runtime-composition"
    / "decisions"
    / "16-DEC-O-12.md"
)
HEARTBEAT_COMMANDS = (
    "sudo deploy/heartbeat.sh --set-url",
    "sudo deploy/heartbeat.sh --install-timer --interval-seconds <N>",
)
# a number followed by a unit of time: an interval, grace or period value the user owns
TIME_VALUE = re.compile(r"\b\d+\s?(?:s|sec|secs|seconds?|m|min|mins|minutes?|h|hours?)\b")


def _subsection(text: str, number: str) -> str:
    """Body of ``### <number> ...`` up to the next heading ('' when absent)."""
    match = re.search(rf"^### {re.escape(number)} [^\n]*\n(.*?)(?=^##|\Z)", text, re.M | re.S)
    return match.group(0) if match else ""


def test_section_17_lists_the_heartbeat_sender_with_only_the_allowed_labels() -> None:
    rows = _table_rows(_section(_runbook(), 17), "Step")
    row = next((r for r in rows if r["Step"] == "11.9"), None)
    assert row is not None, "section 17 has no 11.9 row"
    labels = {label.strip() for label in row["Tested by"].split(";")}
    assert labels == {"local test", "real host (operator)"}
    notes = row["Notes"]
    for phrase in ("stub", "loopback", "real host"):
        assert phrase in notes, f"the 11.9 notes lack: {phrase}"
    steps = [r["Step"] for r in rows]
    assert steps.index("11.9") == steps.index("11.8") + 1


def test_section_11_9_describes_the_sender_without_a_monitor_number() -> None:
    body = _subsection(_section(_runbook(), 11), "11.9")
    assert body.startswith("### 11.9 External heartbeat for the collector (healthchecks.io)")
    missing = _missing(
        body,
        (
            "healthchecks.io",
            "2026-10-09",
            "16-DEC-O-12",
            "src.data.collector --healthcheck",
            "only while",
            "/etc/trading/heartbeat.url",
            "--set-url",
            "--install-timer",
            "--interval-seconds",
            "--fail-ping",
            "--url-file",
            "--dry-run",
            "no default",
            "dashboard",
            "grace",
            "exit code",
            "never stops",
            "catch-up",
            "PLACEHOLDER",
            ".env",
            "acceptance.json",
            "shell history",
            "Phase 24",
            "per-bar",
            "docs/SOURCES.md",
            "operator verification of plan 16-50",
        ),
    )
    assert not missing, f"11.9 lacks: {missing}"
    for command in HEARTBEAT_COMMANDS:
        assert f"\n{command}\n" in body, f"11.9 lacks the command line: {command}"
    assert "```text" in body
    for code in ("0", "1", "2", "3", "4"):
        assert re.search(rf"\b{code}\b", body.split("xit code", 1)[1][:900])
    assert not TIME_VALUE.findall(body), TIME_VALUE.findall(body)
    assert "https://" not in body, "11.9 must not name a ping URL"


def test_section_11_4_no_longer_says_the_repository_pings_nothing() -> None:
    body = _subsection(_section(_runbook(), 11), "11.4")
    assert "Nothing in this repository pings an external monitor" not in body
    assert "11.9" in body
    assert "backup unit itself sends no ping" in body


def test_section_13_5_and_19_point_to_the_sender() -> None:
    text = _runbook()
    checklist = _subsection(_section(text, 13), "13.5")
    item = next(ln for ln in checklist.splitlines() if ln.startswith("2."))
    assert "deploy/heartbeat.sh" in item and "11.9" in item
    assert "This repository sends no heartbeat" not in text


def test_sources_records_the_facts_read_for_plan_16_50() -> None:
    sources = _read(SOURCES)
    assert len(re.findall(r"^## Facts read for plan 16-50 \(2026-10-09\)$", sources, re.M)) == 1
    section = sources.split("## Facts read for plan 16-50 (2026-10-09)", 1)[1]
    section = re.split(r"^## ", section, maxsplit=1, flags=re.M)[0]
    rows = [ln for ln in section.splitlines() if ln.startswith("| ") and "https://" in ln]
    urls = ("https://healthchecks.io/docs/http_api/", "https://github.com/systemd/systemd")
    for url in urls:
        row = next((r for r in rows if url in r), None)
        assert row is not None, f"no SOURCES row for {url}"
        assert "2026-10-09" in row and "not verified live" in row
    assert "UNVERIFIED" in section
    for point in ("first systemd release", "owner and mode", "no start timeout"):
        assert point in section, f"the UNVERIFIED sub-points lack: {point}"
    curl_rows = [ln for ln in section.splitlines() if "curl" in ln and ln.startswith("| ")]
    assert curl_rows and "not fetched" in curl_rows[0]


def test_the_o12_record_names_the_service_and_leaves_interval_and_grace_open() -> None:
    text = _read(DECISION_O12)
    lines = text.splitlines()
    assert "option: postpone" in lines
    for line in (
        "heartbeat_service: healthchecks.io",
        "heartbeat_service decided by: user",
        "heartbeat_service date: 2026-10-09",
        "heartbeat_service words: thêm healthchecks.io vào plan",
    ):
        assert line in lines, f"the O-12 record lacks: {line}"
    assert any(ln.startswith("heartbeat_service words (translation") for ln in lines)
    assert any(ln.startswith("heartbeat_interval: open") for ln in lines)
    assert any(ln.startswith("heartbeat_grace: open") for ln in lines)
