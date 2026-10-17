"""16-63 Task 5 Part B: the owner signs the three authorization files of the 2.3.0 rerun.

Run by the OWNER in their own terminal, at the repository root, with the repository interpreter:

    .venv\\Scripts\\python.exe .planning\\phases\\16-paper-runtime-composition\\scripts\\16-63-sign-authorizations.py

The agent never runs this script without --check, and never writes an authorization file.

--check   run every read-only check, print the three target paths, the scope text and the three
          statements, and write NOTHING.
(default) run the same checks, print the scope text, ask for the exact confirmation
          `AUTHORIZE 2.3.0`, and only on that input create the three files (exclusive creation:
          an existing file is an error, nothing is overwritten), then verify each file with the
          repository's own `load_authorization` and `require_authorized` (no simulation).

The script runs no git command that changes anything (only `git status` and `git rev-parse`), never
deletes and never touches another file. Exit 0 on success, 2 on any failed check (one-line cause).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION  # noqa: E402
from src.research.authorization import (  # noqa: E402
    RunNotAuthorized,
    load_authorization,
    require_authorized,
)
from src.research.manifest import (  # noqa: E402
    grid_hash,
    load_grid,
    load_manifest,
    manifest_hash,
)

CONFIRMATION = "AUTHORIZE 2.3.0"
FAMILIES = ("trend-pullback", "breakout-retest", "range-mr")
PREREG = Path("docs/research/preregistration")
PHASE = Path(".planning/phases/16-paper-runtime-composition")
SCRIPT_REL = PHASE / "scripts" / "16-63-sign-authorizations.py"
MANIFEST_PATH = PREREG / "research-run-1-manifest.json"
OWNER_WORDS = "chọn A và đọc chặt, làm đi"

SCOPE_TEXT = (
    "I authorize one regenerated research run under `simulator_semantics_version = 2.3.0` and "
    "`protocol_version = v2.6.0`, using the accepted 50-day price-only warm-up where pre-window "
    "history is available. The run covers exactly the 3 registered strategy families, their "
    "existing 48 immutable parameter sets and the five existing Development/Validation windows, "
    "generating up to 240 records, one family at a time in the order trend-pullback, "
    "breakout-retest, range-mr. The only allowed market-price history is that required by the "
    "registered windows and their pre-window warm-up. Do not run the Holdout window, read "
    "Holdout prices/returns/metrics or modify the Holdout consumption entries. This "
    "authorization is limited to rerunning the registered Development/Validation research under "
    "the new semantics. It does not authorize changing parameters, choosing a new candidate from "
    "the new results, changing `strategy_version`, consuming Holdout, or making any live-trading "
    "decision. The already designated candidate `research-run-1-a01` remains the designated "
    "candidate unless I issue a separate decision. The three 2.2.0 authorization files are not "
    "used."
)


def target(family: str) -> Path:
    return ROOT / PREREG / f"research-run-1-v2-3-0-authorization-{family}.json"


def _run(args: list[str]) -> str:
    done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def head_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"]).strip()


def _read(rel: Path) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _recorded_hashes() -> dict[str, str]:
    """The hashes recorded at registration (evidence/16-46-hashes.txt), parsed, never typed."""
    lines = _read(PHASE / "evidence" / "16-46-hashes.txt").splitlines()
    out: dict[str, str] = {}
    for index, line in enumerate(lines):
        label = None
        if line.startswith("manifest_sha256 ("):
            label = "manifest"
        else:
            match = re.match(r"grid_sha256 (trend-pullback|breakout-retest|range-mr) \(", line)
            if match:
                label = match.group(1)
        if label is not None:
            candidate = lines[index + 1].strip()
            if not re.fullmatch(r"[0-9a-f]{64}", candidate):
                raise RuntimeError(f"evidence/16-46-hashes.txt: no hash after {label}")
            out[label] = candidate
    if set(out) != {"manifest", *FAMILIES}:
        raise RuntimeError("evidence/16-46-hashes.txt: the four recorded hashes were not found")
    return out


def _file_hashes(rel: Path) -> tuple[str, str]:
    payload = json.loads(_read(rel))
    return payload["manifest_sha256"], payload["grid_sha256"]


def preflight() -> list[str]:
    """Every read-only check; returns the list of failure causes (empty when all pass)."""
    problems: list[str] = []

    def check(condition: bool, cause: str) -> None:
        if not condition:
            problems.append(cause)

    try:
        dirty = _run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", "src", "tests",
             "params", "docs", "scripts"]
        ).strip()
        check(not dirty, f"tracked tree is not clean: {dirty.splitlines()[:3]}")
        check(
            SIMULATOR_SEMANTICS_VERSION == "2.3.0",
            f"SIMULATOR_SEMANTICS_VERSION is {SIMULATOR_SEMANTICS_VERSION!r}, not '2.3.0'",
        )
        protocol = _read(Path("docs/research/RESEARCH_PROTOCOL.md")).splitlines()
        check("> **Protocol version:** v2.6.0" in protocol[:8], "protocol header is not v2.6.0")
        decisions = _read(Path("docs/DECISIONS.md")).splitlines()
        for number in (72, 73, 74, 75, 76):
            rows = [ln for ln in decisions if ln.startswith(f"| D{number:03d} |")]
            check(len(rows) == 1, f"DECISIONS row D{number:03d} count is {len(rows)}")
        marker = json.loads(_read(Path("docs/research/holdout_consumed.json")))
        check(
            marker == {"schema": "holdout-consumed/2", "protocol_version": "v2.6.0", "entries": []},
            "the Holdout marker is not holdout-consumed/2, v2.6.0, empty entries",
        )
        gate = _read(PHASE / "evidence" / "16-63-gate.txt")
        check(
            len(re.findall(r"(?m)^exit=0 ", gate)) == 7 and not re.findall(r"(?m)^exit=[1-9]", gate),
            "evidence/16-63-gate.txt does not hold seven exit=0 lines and none non-zero",
        )
        for name in ("research-run-1-v2-3-0", "research-run-1-v2-2-0"):
            check(
                not (ROOT / "docs" / "research" / "experiments" / name).exists(),
                f"docs/research/experiments/{name}/ already exists",
            )
        for family in FAMILIES:
            check(not target(family).exists(), f"{target(family).name} already exists")
        recorded = _recorded_hashes()
        manifest = load_manifest(ROOT / MANIFEST_PATH)
        check(manifest_hash(manifest) == recorded["manifest"], "manifest hash mismatch")
        for family in FAMILIES:
            grid = load_grid(ROOT / PREREG / f"research-run-1-grid-{family}.json")
            check(grid_hash(grid) == recorded[family], f"{family} grid hash mismatch")
            for pattern in (
                f"research-run-1-authorization-{family}.json",
                f"research-run-1-v2-2-0-authorization-{family}.json",
            ):
                m_hash, g_hash = _file_hashes(PREREG / pattern)
                check(m_hash == recorded["manifest"], f"{pattern}: manifest hash differs")
                check(g_hash == recorded[family], f"{pattern}: grid hash differs")
    except Exception as exc:  # noqa: BLE001 - any failure is a failed check, never a crash
        problems.append(f"{type(exc).__name__}: {exc}")
    return problems


def statement(family: str, sha: str) -> str:
    return (
        f"Research run 1 rerun under simulator_semantics_version 2.3.0 and protocol v2.6.0, "
        f"grid {family}, frozen manifest, 50-day price-only warm-up, no Holdout. File written by "
        f"the owner's own script ({SCRIPT_REL.as_posix()}, run by the owner at repository HEAD "
        f"{sha}) on the owner's explicit decision (decisions/16-DEC-V260.md); the agent did not "
        f"write this file. Owner's words: \"{OWNER_WORDS}\". Typed confirmation: "
        f"\"{CONFIRMATION}\"."
    )


def document(family: str, manifest_sha: str, grid_sha: str, stamp: str, sha: str) -> dict[str, str]:
    """Exactly the six keys, in this order."""
    return {
        "grid_sha256": grid_sha,
        "manifest_sha256": manifest_sha,
        "authorized_at_utc": stamp,
        "statement": statement(family, sha),
        "authorized_by": "Tung Dao",
        "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
    }


def render(doc: dict[str, str]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _show(sha: str) -> None:
    print(f"repository HEAD: {sha}")
    print("files to create (exclusive creation, nothing is overwritten):")
    for family in FAMILIES:
        print(f"  {target(family).relative_to(ROOT).as_posix()}")
    print("\nSCOPE TEXT:\n")
    print(SCOPE_TEXT)
    print("\nSTATEMENTS (one per file):")
    for family in FAMILIES:
        print(f"  [{family}] {statement(family, sha)}")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    unknown = [a for a in argv if a != "--check"]
    if unknown:
        print(f"refused: unknown argument {unknown[0]!r}", file=sys.stderr)
        return 2
    check_only = "--check" in argv
    problems = preflight()
    if problems:
        print(f"refused: {problems[0]}", file=sys.stderr)
        for extra in problems[1:]:
            print(f"  also: {extra}", file=sys.stderr)
        return 2
    print("all read-only checks pass (clean tree, version 2.3.0, protocol v2.6.0, D072-D076, "
          "marker, gate, no output directory, manifest and grid hashes equal the recorded ones)")
    sha = head_sha()
    _show(sha)
    if check_only:
        print("\n--check: nothing was written.")
        return 0
    print(f"\nTo authorize, type exactly {CONFIRMATION} and press Enter (anything else aborts).")
    typed = input("> ").strip("\r\n")
    if typed != CONFIRMATION:
        print("aborted: the confirmation did not match; nothing was written.")
        return 2
    manifest_sha = manifest_hash(load_manifest(ROOT / MANIFEST_PATH))
    stamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    created: list[Path] = []
    for family in FAMILIES:
        grid_sha = grid_hash(load_grid(ROOT / PREREG / f"research-run-1-grid-{family}.json"))
        path = target(family)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(render(document(family, manifest_sha, grid_sha, stamp, sha)))
        created.append(path)
        print(f"created {path.relative_to(ROOT).as_posix()}")
    manifest = load_manifest(ROOT / MANIFEST_PATH)
    for family, path in zip(FAMILIES, created, strict=True):
        grid = load_grid(ROOT / PREREG / f"research-run-1-grid-{family}.json")
        try:
            require_authorized(load_authorization(path), manifest=manifest, grid=grid)
        except RunNotAuthorized as exc:
            print(f"VERIFY FAILED {family}: {exc.reason}", file=sys.stderr)
            return 2
        print(f"pass: {family}: load_authorization and require_authorized accept the file")
    print("done. Tell the agent \"signed\".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
