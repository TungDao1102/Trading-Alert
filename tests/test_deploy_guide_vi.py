"""Traceability checker for the Vietnamese operator guide ``docs/operations/DEPLOY_GUIDE.vi.md``.

The guide is read by a non-expert who types its commands on a real host, so every command line,
flag, compose service and module in it must trace back to the repository, and every capability the
repository does not have yet must be labelled instead of given a runnable command. This file reads
files only: no network, no ``.env``, no host.

Test names carry a group word so a partially written guide can be checked in stages
(``-k "common or part1"``): ``common`` tests pass on any partial guide, ``part1``, ``part2`` and
``part3`` hold what each writing stage owns, and ``final`` is the whole-guide gate.

Document contract enforced here (see the quick plan 261009-jqi):

* machine tags and status labels on step headings, nine-field operation cards;
* every ``deploy/`` command and flag, ``docker compose`` call, ``python -m`` module and script is
  checked against the real scripts, ``docker-compose.yml`` and ``src``;
* any other command is a generic OS helper, a line found verbatim in the repository operations
  documents and scripts, or labelled ``CHƯA XÁC MINH`` / ``CHƯA XÂY``;
* no secret, token, key, real public IP address, instance-type name or passwordless-sudo tag;
* built-state labels never over-claim (Phase 16 plans, ROADMAP phases 18 to 26).
"""

from __future__ import annotations

import ast
import re
import shlex
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest
from scripts import soak_host_acceptance as sha

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE = REPO_ROOT / "docs" / "operations" / "DEPLOY_GUIDE.vi.md"
RUNBOOK = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"
SEC_OPS = REPO_ROOT / "docs" / "operations" / "SECURITY_AND_OPERATIONS.md"
DEPLOY_DIR = REPO_ROOT / "deploy"
SYSTEMD_DIR = DEPLOY_DIR / "systemd"
SCRIPTS_DIR = REPO_ROOT / "scripts"
COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ROADMAP = REPO_ROOT / ".planning" / "ROADMAP.md"
PHASE16_DIR = REPO_ROOT / ".planning" / "phases" / "16-paper-runtime-composition"

HAS_PLANNING = (REPO_ROOT / ".planning").is_dir()


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# --------------------------------------------------------------------------------------------
# Contract constants
# --------------------------------------------------------------------------------------------

STATUS_LABELS = tuple(_nfc(s) for s in ("ĐÃ XÂY", "CHƯA XÂY", "CHƯA XÁC MINH", "THỦ CÔNG"))
MACHINE_TAGS = tuple(_nfc(s) for s in ("MÁY CÓ MẠNG", "MÁY EC2", "MÁY CŨ", "MÁY PHÁT TRIỂN"))
CARD_LABELS = tuple(
    _nfc(s)
    for s in (
        "Mục đích",
        "Khi nào chạy",
        "Chạy ở máy nào",
        "Lệnh",
        "Chạy thử",
        "Dấu hiệu thành công",
        "Mã thoát",
        "Khi lỗi",
        "Không bao giờ",
    )
)
TITLES = {
    n: _nfc(title)
    for n, title in enumerate(
        (
            "Cách đọc hướng dẫn này",
            "Bức tranh tổng thể",
            "Chuẩn bị trước khi bắt đầu",
            "Tạo và nghiệm thu máy EC2",
            "Dựng máy chủ với bootstrap",
            "Triển khai collector và chuyển dữ liệu từ máy cũ",
            "Sao lưu, khôi phục và diễn tập",
            "Paper runtime và soak SHADOW (Phase 16)",
            "Telegram, Binance và giám sát bên ngoài",
            "Lộ trình SHADOW, DEMO, CANARY, LIVE",
            "Vận hành hằng ngày",
            "Cập nhật và quay lại phiên bản cũ",
            "Khẩn cấp",
            "Xử lý sự cố",
            "Bảng tra nhanh mọi lệnh",
            "Danh sách kiểm tra cuối cùng",
        )
    )
}
SOURCE_LINE = _nfc("Nguồn:")
LABEL_MARKERS = (_nfc("chưa xác minh"), _nfc("chưa xây"))

CHECKED_LANGS = {"bash", "sh", "powershell"}
KNOWN_LANGS = CHECKED_LANGS | {"text", "sql", "json"}
GENERIC_COMMANDS = {
    "cd",
    "ls",
    "cat",
    "mkdir",
    "chmod",
    "ssh",
    "scp",
    "ssh-keygen",
    "exit",
    "df",
    "du",
    "date",
    "uptime",
    "whoami",
    "id",
    "pwd",
}
GENERIC_GIT = {"archive", "status", "log", "rev-parse", "describe", "tag"}
COMPOSE_SUBCOMMANDS = {
    "up",
    "ps",
    "logs",
    "stop",
    "start",
    "restart",
    "build",
    "rm",
    "run",
    "exec",
    "config",
    "down",
}
COMPOSE_SERVICE_SUBCOMMANDS = COMPOSE_SUBCOMMANDS - {"config", "down"}
COMPOSE_VALUE_OPTIONS = {
    "--tail",
    "--since",
    "--until",
    "--timeout",
    "--wait-timeout",
    "--user",
    "--scale",
    "--entrypoint",
    "--env-file",
    "--project-directory",
    "--project-name",
    "-p",
}
ALLOWED_IPS = {"127.0.0.1", "0.0.0.0", "169.254.169.123"}
ALLOWED_IP_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")
SECRET_NAME_PARTS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "ACCESS_KEY", "CRYPT")
DECISION_IDS = ("D040", "D041", "D042", "D050", "D059", "D061", "D062", "D064")


# --------------------------------------------------------------------------------------------
# Reading helpers
# --------------------------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _flat(text: str) -> str:
    """Whitespace-normalised text with backslash continuations joined."""
    return " ".join(re.sub(r"\\\n", " ", text).split())


@cache
def _guide() -> str:
    assert GUIDE.is_file(), f"{GUIDE.relative_to(REPO_ROOT)} does not exist"
    return _nfc(_read(GUIDE))


def _script_flags(script: Path) -> set[str]:
    """Flags of a deploy script, from its ``parse_args`` case arms (as tests/test_deploy_docs)."""
    text = _read(script)
    flags: set[str] = set()
    pattern = r"^\s+((?:-h \| )?--[a-z][a-z-]*(?: \| --[a-z][a-z-]*)*)\)"
    for group in re.findall(pattern, text, re.M):
        flags.update(re.findall(r"--[a-z][a-z-]*", group))
    flags.discard("--help")
    return flags


def _deploy_scripts() -> list[Path]:
    return sorted(DEPLOY_DIR.glob("*.sh"))


def _deploy_files() -> list[Path]:
    return sorted(p for p in DEPLOY_DIR.rglob("*") if p.is_file())


@cache
def _compose_services() -> frozenset[str]:
    text = _read(COMPOSE)
    block = re.search(r"^services:\n(.*?)(?=^\S)", text, re.M | re.S)
    assert block, "no services block in docker-compose.yml"
    return frozenset(re.findall(r"^  ([a-z][\w-]*):\s*$", block.group(1), re.M))


@cache
def _compose_profiles() -> frozenset[str]:
    return frozenset(re.findall(r'profiles:\s*\["([^"]+)"\]', _read(COMPOSE)))


def _module_header(path: Path) -> str:
    """Comment header of a script: the module docstring (.py) or the ``#`` lines (.ps1)."""
    text = _read(path)
    if path.suffix == ".py":
        try:
            return ast.get_docstring(ast.parse(text)) or ""
        except SyntaxError:
            return ""
    return "\n".join(
        re.sub(r"^#\s?", "", ln) for ln in text.split("\n") if ln.lstrip().startswith("#")
    )


@cache
def _corpus() -> str:
    """Text a command line may be found in verbatim (rule d of the contract)."""
    parts = [_read(RUNBOOK), _read(SEC_OPS), _read(COMPOSE), _read(DOCKERFILE)]
    parts.append(_read(ENV_EXAMPLE))
    parts.extend(_read(p) for p in _deploy_files())
    for path in sorted(SCRIPTS_DIR.glob("*")):
        if path.suffix in {".py", ".ps1"}:
            parts.append(_module_header(path))
    return _nfc(_flat("\n".join(parts)))


@cache
def _known_variable_names() -> frozenset[str]:
    texts = [_read(ENV_EXAMPLE), _read(COMPOSE), _read(DOCKERFILE)]
    texts.extend(_read(p) for p in _deploy_scripts())
    return frozenset(re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", "\n".join(texts)))


# --------------------------------------------------------------------------------------------
# Guide structure
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fence:
    lang: str
    start: int  # 1-based line number of the opening fence line
    body: tuple[str, ...]


@cache
def _fences(text: str) -> tuple[Fence, ...]:
    lines = text.split("\n")
    out: list[Fence] = []
    i = 0
    while i < len(lines):
        match = re.match(r"^```(\S*)\s*$", lines[i])
        if not match:
            i += 1
            continue
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not re.match(r"^```\s*$", lines[j]):
            body.append(lines[j])
            j += 1
        out.append(Fence(match.group(1), i + 1, tuple(body)))
        i = j + 1
    return tuple(out)


@cache
def _prose_lines(text: str) -> tuple[tuple[int, str], ...]:
    out: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.split("\n"), start=1):
        if re.match(r"^```", line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((number, line))
    return tuple(out)


@cache
def _inline_spans(text: str) -> tuple[tuple[int, str], ...]:
    return tuple(
        (number, span)
        for number, line in _prose_lines(text)
        for span in re.findall(r"`([^`]+)`", line)
    )


@cache
def _sections(text: str) -> dict[int, str]:
    """Body of each ``## N. title`` section (the heading line included)."""
    matches = list(re.finditer(r"^## (\d+)\. .*$", text, re.M))
    out: dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        out[int(match.group(1))] = text[match.start() : end]
    return out


@dataclass(frozen=True)
class Card:
    path: str
    line: int
    body: str


@cache
def _cards(text: str) -> tuple[Card, ...]:
    heading = _nfc("### Thẻ lệnh:")
    lines = text.split("\n")
    out: list[Card] = []
    for index, line in enumerate(lines):
        if not line.startswith(heading):
            continue
        end = index + 1
        while end < len(lines) and not re.match(r"^#{1,4} ", lines[end]):
            end += 1
        path = line[len(heading) :].strip().strip("`")
        out.append(Card(path, index + 1, "\n".join(lines[index:end])))
    return tuple(out)


def _card(text: str, path: str) -> Card | None:
    for card in _cards(text):
        if card.path == path:
            return card
    return None


def _card_fields(card: Card) -> dict[str, str] | None:
    """Text of each of the nine labelled fields, in order; None when a label is missing."""
    positions: list[tuple[str, int, int]] = []
    cursor = 0
    for label in CARD_LABELS:
        marker = f"**{label}:**"
        at = card.body.find(marker, cursor)
        if at < 0:
            return None
        positions.append((label, at, at + len(marker)))
        cursor = at + len(marker)
    fields: dict[str, str] = {}
    for index, (label, _start, text_start) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(card.body)
        fields[label] = card.body[text_start:end].strip()
    return fields


def _is_labelled(text_lines: list[str], fence: Fence) -> bool:
    low = max(0, fence.start - 4)
    high = fence.start + len(fence.body) + 1
    window = _nfc("\n".join(text_lines[low:high])).casefold()
    return any(marker in window for marker in LABEL_MARKERS)


# --------------------------------------------------------------------------------------------
# Command checks
# --------------------------------------------------------------------------------------------

_FORBIDDEN = (
    (re.compile(r"\bdocker\s+volume\s+(?:rm|remove|prune)\b"), "docker volume removal"),
    (re.compile(r"\bdocker\s+system\s+prune\b"), "docker system prune"),
)


def _logical_lines(fence: Fence) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    buf = ""
    first = 0
    for offset, raw in enumerate(fence.body):
        if not buf:
            first = fence.start + 1 + offset
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1].strip() + " "
            continue
        buf += line.strip()
        out.append((first, buf))
        buf = ""
    if buf:
        out.append((first, buf.strip()))
    return out


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _deploy_problems(cmd: str) -> list[str]:
    problems: list[str] = []
    matches = list(re.finditer(r"deploy/([\w.-]+\.sh)", cmd))
    for index, match in enumerate(matches):
        name = match.group(1)
        script = DEPLOY_DIR / name
        if not script.is_file():
            problems.append(f"deploy/{name} does not exist")
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cmd)
        allowed = _script_flags(script) | {"--help"}
        for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", cmd[match.end() : end]):
            if flag not in allowed:
                problems.append(f"{flag} is not a flag of deploy/{name}")
    return problems


def _compose_problems(cmd: str) -> list[str]:
    problems: list[str] = []
    match = re.search(r"\bdocker compose\b(.*)$", cmd)
    if not match:
        return problems
    tokens = _split(match.group(1))
    sub: str | None = None
    flags: list[str] = []
    positional: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            name = token.split("=")[0]
            flags.append(name)
            if name == "--profile":
                value = tokens[i + 1] if i + 1 < len(tokens) else ""
                if value not in _compose_profiles():
                    problems.append(f"compose profile '{value}' is not in docker-compose.yml")
                i += 2
                continue
            if name in COMPOSE_VALUE_OPTIONS and "=" not in token:
                i += 2
                continue
        elif sub is None:
            sub = token
        else:
            positional.append(token)
            if sub in {"run", "exec"}:
                break
        i += 1
    if sub is None:
        return problems
    if sub not in COMPOSE_SUBCOMMANDS:
        problems.append(f"docker compose subcommand '{sub}' is not one the guide may use")
        return problems
    if sub == "config" and "-q" not in flags and "--quiet" not in flags:
        problems.append("docker compose config without -q prints the resolved secrets")
    if sub == "down" and ({"-v", "--volumes"} & set(flags)):
        problems.append("docker compose down with a volumes flag deletes data")
    if sub in COMPOSE_SERVICE_SUBCOMMANDS:
        for word in positional:
            if word.isdigit() or word.startswith(("<", "/")) or word.endswith(">"):
                continue
            if word not in _compose_services():
                problems.append(f"'{word}' is not a service of docker-compose.yml")
    return problems


def _python_problems(cmd: str, labelled: bool) -> tuple[bool, list[str]]:
    """(handled, problems) for ``python -m src.x`` and ``python scripts/x.py`` commands."""
    problems: list[str] = []
    handled = False
    module = re.search(r"python3?\s+-m\s+(src(?:\.\w+)+)(.*)$", cmd)
    script = re.search(r"python3?\s+(scripts/[\w./-]+\.py)(.*)$", cmd)
    if module:
        handled = True
        dotted, rest = module.group(1), module.group(2)
        base = REPO_ROOT / dotted.replace(".", "/")
        source_path = base.with_suffix(".py")
        if not source_path.is_file() and (base / "__main__.py").is_file():
            source_path = base / "__main__.py"
        if not source_path.is_file():
            if not labelled:
                problems.append(f"module {dotted} does not exist and the command is not labelled")
        else:
            problems.extend(_source_flag_problems(dotted, source_path, rest))
    if script:
        handled = True
        path, rest = script.group(1), script.group(2)
        source_path = REPO_ROOT / path
        if not source_path.is_file():
            if not labelled:
                problems.append(f"{path} does not exist and the command is not labelled")
        else:
            problems.extend(_source_flag_problems(path, source_path, rest))
    return handled, problems


def _source_flag_problems(name: str, source_path: Path, rest: str) -> list[str]:
    problems: list[str] = []
    source = _read(source_path)
    for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", rest):
        if f'"{flag}"' not in source and f"'{flag}'" not in source:
            problems.append(f"{flag} is not a quoted option of {name}")
    parsers = re.findall(r'add_parser\(\s*"([\w-]+)"', source)
    if parsers:
        words = [t for t in _split(rest) if not t.startswith("-")]
        if words and re.fullmatch(r"[a-z][a-z-]*", words[0]) and words[0] not in parsers:
            problems.append(f"'{words[0]}' is not a subcommand of {name}")
    return problems


def _command_problems(raw: str, labelled: bool) -> list[str]:
    """Problems of one logical command line of a code fence (empty when it is traceable)."""
    cmd = _nfc(re.sub(r"^(?:\$\s+|PS>\s*)", "", raw.strip()))
    if not cmd or cmd.startswith("#"):
        return []
    problems: list[str] = []
    for pattern, why in _FORBIDDEN:
        if pattern.search(cmd):
            problems.append(why)
    rule_matched = False
    if re.search(r"deploy/[\w.-]+\.sh", cmd):
        rule_matched = True
        problems.extend(_deploy_problems(cmd))
    if re.search(r"\bdocker compose\b", cmd):
        rule_matched = True
        problems.extend(_compose_problems(cmd))
    handled, py_problems = _python_problems(cmd, labelled)
    if handled:
        rule_matched = True
        problems.extend(py_problems)
    if rule_matched or labelled:
        return problems
    stripped = re.sub(r"^sudo\s+", "", cmd)
    words = stripped.split()
    if words and words[0] in GENERIC_COMMANDS:
        return problems
    if len(words) > 1 and words[0] == "git" and words[1] in GENERIC_GIT:
        return problems
    corpus = _corpus()
    if _flat(cmd) in corpus or _flat(stripped) in corpus:
        return problems
    problems.append("not traceable: no script/compose/module match, not generic, not verbatim")
    return problems


def _span_problems(span: str, labelled: bool) -> list[str]:
    """Rules 4 to 6 and the forbidden list for an inline code span."""
    cmd = _nfc(span.strip())
    problems: list[str] = []
    for pattern, why in _FORBIDDEN:
        if pattern.search(cmd):
            problems.append(why)
    if re.search(r"deploy/[\w.-]+\.sh", cmd):
        problems.extend(_deploy_problems(cmd))
    if re.search(r"\bdocker compose\b", cmd):
        problems.extend(_compose_problems(cmd))
    problems.extend(_python_problems(cmd, labelled)[1])
    return problems


def _all_command_problems(text: str) -> list[str]:
    lines = text.split("\n")
    out: list[str] = []
    for fence in _fences(text):
        labelled = _is_labelled(lines, fence)
        if fence.lang in CHECKED_LANGS:
            for number, cmd in _logical_lines(fence):
                out.extend(f"line {number}: {p}" for p in _command_problems(cmd, labelled))
        else:
            for offset, body_line in enumerate(fence.body):
                for pattern, why in _FORBIDDEN:
                    if pattern.search(body_line):
                        out.append(f"line {fence.start + 1 + offset}: {why}")
    for number, span in _inline_spans(text):
        labelled = any(m in _nfc(lines[number - 1]).casefold() for m in LABEL_MARKERS)
        out.extend(f"line {number}: {p}" for p in _span_problems(span, labelled))
    return out


# --------------------------------------------------------------------------------------------
# Common tests (pass on any partially written guide)
# --------------------------------------------------------------------------------------------

_VI_CHARS = re.compile(
    "[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I
)
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿️⃣]")


def test_common_guide_is_utf8_lf_vietnamese_and_has_no_emoji() -> None:
    assert GUIDE.is_file(), "docs/operations/DEPLOY_GUIDE.vi.md does not exist"
    raw = GUIDE.read_bytes()
    text = raw.decode("utf-8")  # strict: raises on invalid UTF-8
    # LF in the repository; a Windows checkout with autocrlf may turn all of them into CRLF, so
    # only a mixture (or a stray CR) is a defect.
    crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
    assert crlf in (0, lf), "the guide mixes LF and CRLF line endings"
    assert raw.count(b"\r") == crlf, "the guide has a stray carriage return"
    assert not text.startswith("﻿"), "the guide must not start with a BOM"
    diacritics = len(_VI_CHARS.findall(_nfc(text)))
    assert diacritics >= 2000, f"only {diacritics} Vietnamese diacritic characters"
    emoji = [f"line {text[: m.start()].count(chr(10)) + 1}" for m in _EMOJI.finditer(text)]
    assert not emoji, f"emoji code points at {emoji}"


def test_common_every_fence_has_a_known_language() -> None:
    bad = [f"line {f.start}: '{f.lang}'" for f in _fences(_guide()) if f.lang not in KNOWN_LANGS]
    assert not bad, f"unknown or missing fence language: {bad}"


def test_common_no_secret_shaped_content() -> None:
    text = _guide()
    findings: list[str] = []
    patterns = {
        "aws access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
        "private key header": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "uuid inside a url": re.compile(
            r"https?://\S*[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        ),
    }
    for number, line in enumerate(text.split("\n"), start=1):
        for rule, pattern in patterns.items():
            if pattern.search(line):
                findings.append(f"line {number}: {rule}")
    for fence in _fences(text):
        for offset, line in enumerate(fence.body):
            match = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$", line)
            if not match:
                continue
            name, value = match.group(1), match.group(2).strip().strip("\"'")
            number = fence.start + 1 + offset
            if any(part in name for part in SECRET_NAME_PARTS) and not (
                value == "" or re.fullmatch(r"<[^<>]+>", value)
            ):
                findings.append(f"line {number}: secret-named variable with a value")
    assert not findings, f"secret-shaped content (text withheld): {findings}"


def test_common_no_public_ip_instance_type_or_passwordless_sudo_tag() -> None:
    text = _guide()
    findings: list[str] = []
    ip_pattern = re.compile(r"(?<![\w.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\w.]*\d)")
    instance = re.compile(
        r"\b[a-z]{1,3}\d{1,2}[a-z]{0,2}\.(?:nano|micro|small|medium|large|\d*xlarge|metal)\b"
    )
    for number, line in enumerate(text.split("\n"), start=1):
        for match in ip_pattern.finditer(line):
            octets = [int(g) for g in match.groups()]
            address = match.group(0)
            if max(octets) > 255:
                continue
            if address in ALLOWED_IPS or address.startswith(ALLOWED_IP_PREFIXES):
                continue
            findings.append(f"line {number}: IPv4 address")
        if instance.search(line):
            findings.append(f"line {number}: instance-type name")
        if "NOPASSWD" in line:
            findings.append(f"line {number}: passwordless-sudo tag")
    assert not findings, f"disallowed values (text withheld): {findings}"


def test_common_variable_assignments_use_names_from_the_repository() -> None:
    known = _known_variable_names()
    bad: list[str] = []
    for fence in _fences(_guide()):
        if fence.lang not in {"bash", "text"}:
            continue
        for offset, line in enumerate(fence.body):
            match = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=", line)
            if match and match.group(1) not in known:
                bad.append(f"line {fence.start + 1 + offset}: {match.group(1)}")
    assert not bad, f"variable names that exist nowhere in the repository: {bad}"


def test_common_deploy_commands_compose_calls_and_modules_trace_to_the_repository() -> None:
    problems = _all_command_problems(_guide())
    assert not problems, "untraceable or invalid commands:\n" + "\n".join(problems)


def test_common_sql_fences_are_read_only() -> None:
    bad: list[str] = []
    for fence in _fences(_guide()):
        if fence.lang != "sql":
            continue
        for offset, line in enumerate(fence.body):
            if re.search(r"\b(?:update|delete|insert|drop|alter|truncate|grant)\b", line, re.I):
                bad.append(f"line {fence.start + 1 + offset}")
    assert not bad, f"SQL that is not read-only: {bad}"


_PATH_PREFIXES = ("docs/", "deploy/", "scripts/", "src/", "tests/", "params/", ".planning/")
_TOP_LEVEL_FILES = {
    "docker-compose.yml",
    "Dockerfile",
    ".env.example",
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
    "AGENTS.md",
}


def test_common_every_backticked_repository_path_exists() -> None:
    missing: list[str] = []
    for number, span in _inline_spans(_guide()):
        token = span.strip()
        if any(ch in token for ch in "<>*{|") or " " in token:
            continue
        if not (token.startswith(_PATH_PREFIXES) or token in _TOP_LEVEL_FILES):
            continue
        if token.startswith(".planning/") and not HAS_PLANNING:
            continue
        if not (REPO_ROOT / token).exists():
            missing.append(f"line {number}: {token}")
    assert not missing, f"backticked paths that do not exist: {missing}"


def test_common_step_headings_sit_under_their_section_and_carry_labels_and_machine_tags() -> None:
    text = _guide()
    lines = text.split("\n")
    problems: list[str] = []
    section = -1
    for index, line in enumerate(lines):
        head = re.match(r"^## (\d+)\. ", line)
        if head:
            section = int(head.group(1))
            continue
        step = re.match(r"^#### Bước (\d+)\.(\d+)\b", line)
        if not step:
            continue
        number = index + 1
        if int(step.group(1)) != section:
            problems.append(
                f"line {number}: step {step.group(1)}.{step.group(2)} is in section {section}"
            )
        if not any(f"[{label}]" in line for label in STATUS_LABELS):
            problems.append(f"line {number}: no status label")
        end = index + 1
        while end < len(lines) and not re.match(r"^#{1,4} ", lines[end]):
            end += 1
        body = "\n".join(lines[index:end])
        if not any(f"[{tag}]" in body for tag in MACHINE_TAGS):
            problems.append(f"line {number}: no machine tag")
    assert not problems, "\n".join(problems)


def test_common_operation_cards_are_complete() -> None:
    text = _guide()
    problems: list[str] = []
    for card in _cards(text):
        where = f"card {card.path} (line {card.line})"
        if not (REPO_ROOT / card.path).exists():
            problems.append(f"{where}: path does not exist")
        fields = _card_fields(card)
        if fields is None:
            problems.append(f"{where}: one of the nine bold labels is missing or out of order")
            continue
        for label, content in fields.items():
            if len(content) < 20 and _nfc("Không áp dụng") not in content:
                problems.append(f"{where}: field '{label}' is too short")
        if card.path.startswith("deploy/") and card.path.endswith(".sh"):
            script = REPO_ROOT / card.path
            for flag in sorted(_script_flags(script)):
                if flag not in card.body:
                    problems.append(f"{where}: flag {flag} of the script is not in the card")
            if "--dry-run" in _script_flags(script):
                dry = fields[CARD_LABELS[4]]
                if "--dry-run" not in dry or card.path not in dry:
                    problems.append(f"{where}: 'Chạy thử' has no --dry-run command")
        if card.path == "deploy/migrate.sh":
            codes = set(re.findall(r"^\|\s*(\d)\s*\|", card.body, re.M))
            if not {"0", "1", "2", "3"} <= codes:
                problems.append(f"{where}: no exit-code table with 0, 1, 2 and 3")
    assert not problems, "\n".join(problems)


def test_common_sections_are_ordered_titled_and_end_with_a_source_line() -> None:
    text = _guide()
    problems: list[str] = []
    headings = re.findall(r"^## (.*)$", text, re.M)
    numbered: list[int] = []
    for heading in headings:
        match = re.match(r"^(\d+)\. (.+)$", heading)
        if not match:
            problems.append(f"level-2 heading without a section number: {heading[:40]}")
            continue
        number, title = int(match.group(1)), match.group(2).strip()
        numbered.append(number)
        if TITLES.get(number) != title:
            problems.append(f"section {number} has the title '{title}'")
    if numbered != sorted(set(numbered)):
        problems.append(f"sections are not strictly increasing: {numbered}")
    for number, body in _sections(text).items():
        trimmed = [ln for ln in body.rstrip().split("\n") if ln.strip()]
        last = trimmed[-1] if trimmed else ""
        if not last.startswith(SOURCE_LINE) or not re.search(r"`[^`]+`", last):
            problems.append(f"section {number} does not end with a '{SOURCE_LINE}' line with paths")
    assert not problems, "\n".join(problems)


def _roadmap_done() -> dict[int, bool]:
    text = _read(ROADMAP)
    return {
        int(m.group(2)): m.group(1) == "x"
        for m in re.finditer(r"^- \[( |x)\] \*\*Phase (\d+):", text, re.M)
    }


@pytest.mark.skipif(not HAS_PLANNING, reason="no .planning directory (PR branch)")
def test_common_built_labels_never_over_claim() -> None:
    text = _guide()
    built = f"[{STATUS_LABELS[0]}]"
    problems: list[str] = []
    for number, line in enumerate(text.split("\n"), start=1):
        row = re.match(r"^\|\s*(16-\d\d)\s*\|", line)
        if row and STATUS_LABELS[0] in line:
            summary = PHASE16_DIR / f"{row.group(1)}-SUMMARY.md"
            if not summary.is_file():
                problems.append(
                    f"line {number}: plan {row.group(1)} marked built without a SUMMARY"
                )
        if built in line:
            done = _roadmap_done()
            for phase in re.findall(r"\bPhase (1[89]|2[0-6])\b", line):
                if not done.get(int(phase), False):
                    problems.append(f"line {number}: Phase {phase} marked built, ROADMAP unchecked")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------------------------
# Stage tests
# --------------------------------------------------------------------------------------------


def _require_sections(numbers: range) -> list[str]:
    present = _sections(_guide())
    return [f"section {n} ({TITLES[n]}) is missing" for n in numbers if n not in present]


def _require_cards(paths: list[str]) -> list[str]:
    return [f"operation card for {p} is missing" for p in paths if _card(_guide(), p) is None]


def _require_anchors(anchors: list[str]) -> list[str]:
    text = _guide()
    return [f"anchor '{a}' is missing" for a in anchors if a not in text]


def test_part1_sections_cards_and_anchors() -> None:
    problems = _require_sections(range(0, 6))
    problems += _require_cards(
        ["deploy/bootstrap.sh", "deploy/migrate.sh", "scripts/soak_host_acceptance.py"]
    )
    problems += _require_anchors(
        [
            "ap-southeast-1",
            "16-DEC-O-12",
            "2027-01-25",
            "REGION_PING_FAPI",
            "acceptance.json",
            "Docker Desktop",
            "passwd trading",
            "sudo -v",
            "--max-gap-minutes",
            "D042",
            "D061",
            "D062",
            *sha.REQUIRED_CONDITIONS,
        ]
    )
    assert not problems, "\n".join(problems)


def test_part2_sections_cards_phase_table_and_anchors() -> None:
    text = _guide()
    problems = _require_sections(range(6, 10))
    problems += _require_cards(
        [
            "deploy/backup.sh",
            "deploy/restore.sh",
            "deploy/backup-drill.sh",
            "deploy/systemd/trading-backup.service",
            "deploy/systemd/trading-backup.timer",
            "scripts/backup-drill.ps1",
        ]
    )
    problems += _require_anchors(
        [
            "--init-remote",
            "--install-timer",
            "03:15",
            "cryptcheck",
            "rclone obscure",
            "BACKUP_CRYPT_PASSWORD",
            "D064",
            "D066",
            "python -m src.paper.runtime",
            "PAPER_START_ALLOWLIST",
            "Q-L",
            "BotFather",
            "TELEGRAM_BOT_TOKEN",
            "whitelist",
            "OPS-06",
            "D040",
            "D041",
            "SHADOW",
            "DEMO",
            "CANARY",
            "LIVE",
        ]
    )
    rows = set(re.findall(r"^\|\s*(16-\d\d)\s*\|", text, re.M))
    expected = {f"16-{n:02d}" for n in range(1, 50)}
    if rows != expected:
        problems.append(
            f"Phase 16 table rows differ: missing {sorted(expected - rows)}, "
            f"unexpected {sorted(rows - expected)}"
        )
    for phase in range(18, 27):
        flagged = any(
            re.search(rf"\bPhase {phase}\b", ln) and STATUS_LABELS[1] in ln
            for ln in text.split("\n")
        )
        if not flagged:
            problems.append(f"Phase {phase} is not mentioned with {STATUS_LABELS[1]}")
    assert not problems, "\n".join(problems)


def test_part3_sections_cards_services_and_checklist() -> None:
    text = _guide()
    problems = _require_sections(range(10, 16))
    problems += _require_cards(["deploy/update.sh", "deploy/refresh-pins.sh"])
    problems += _require_anchors(
        [
            "last-good.env",
            "SAFE_MODE",
            "ManualExit",
            "journalctl -u trading-backup",
            "docker compose config -q",
            "alembic",
            "refresh-pins.sh --lookup",
        ]
    )
    section10 = _sections(text).get(10, "")
    problems += [
        f"compose service '{s}' is not named in section 10"
        for s in sorted(_compose_services())
        if s not in section10
    ]
    items = [ln for ln in _sections(text).get(15, "").split("\n") if ln.startswith("- [ ]")]
    if len(items) < 30:
        problems.append(f"section 15 has {len(items)} checklist items, 30 are required")
    problems += [
        f"checklist item without a section reference: {i[:50]}"
        for i in items
        if not re.search(_nfc(r"\(mục \d+(?:\.\d+)?\)"), i)
    ]
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------------------------
# Final gate
# --------------------------------------------------------------------------------------------


def test_final_sections_0_to_15_are_present_and_contiguous() -> None:
    present = sorted(_sections(_guide()))
    assert present == list(range(16)), f"sections present: {present}"
    assert "gsd:write-continue" not in _guide(), "a write-continue sentinel was left behind"


def test_final_a_card_exists_for_every_script_unit_and_helper() -> None:
    paths = [f"deploy/{p.name}" for p in _deploy_scripts() if p.name != "lib.sh"]
    paths += [f"deploy/systemd/{p.name}" for p in sorted(SYSTEMD_DIR.iterdir()) if p.is_file()]
    paths += ["scripts/soak_host_acceptance.py", "scripts/backup-drill.ps1"]
    problems = _require_cards(paths)
    assert not problems, "\n".join(problems)


def test_final_every_deploy_file_is_named_and_the_quick_reference_is_complete() -> None:
    text = _guide()
    problems = [
        f"deploy file {p.name} is never mentioned" for p in _deploy_files() if p.name not in text
    ]
    reference = _sections(text).get(14, "")
    for script in _deploy_scripts():
        if script.name not in reference:
            problems.append(f"section 14 does not name {script.name}")
        problems += [
            f"section 14 lacks {flag} of {script.name}"
            for flag in sorted(_script_flags(script))
            if flag not in reference
        ]
    for service in sorted(_compose_services()):
        if service not in reference:
            problems.append(f"section 14 lacks compose service {service}")
    for unit in sorted(SYSTEMD_DIR.iterdir()):
        if unit.name not in reference:
            problems.append(f"section 14 lacks unit {unit.name}")
    for needed in ("soak_host_acceptance.py", "backup-drill.ps1", "--healthcheck"):
        if needed not in reference:
            problems.append(f"section 14 lacks {needed}")
    assert not problems, "\n".join(problems)


def test_final_governing_decisions_are_cited() -> None:
    text = _guide()
    missing = [d for d in DECISION_IDS if d not in text]
    assert not missing, f"decisions never cited: {missing}"
