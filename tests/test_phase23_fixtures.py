"""The Phase 23 golden texts are generated, reproducible and checked (plan 23-03).

`scripts/gen_phase23_fixtures.py` renders every golden text from fixed inputs. Nothing under
`tests/fixtures/phase23` (except `DERIVATIONS.md`, which is documentation) is typed by hand.
The comparison ignores a CRLF that a Windows checkout may add: the generator writes LF.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from src.ops.alert_wording import CLOSE_REQUIRED_WORDING, EVENT_WORDING

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = REPO_ROOT / "scripts" / "gen_phase23_fixtures.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "phase23"
GENERATED_SUFFIX = ".txt"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_phase23_fixtures", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _on_disk(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        .replace(b"\r\n", b"\n")
        .decode("utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix == GENERATED_SUFFIX
    }


def test_render_all_equals_the_files_on_disk() -> None:
    generator = _load_generator()

    rendered = generator.render_all()

    assert rendered  # something is generated
    assert rendered == _on_disk(FIXTURE_ROOT)


def test_one_golden_alert_text_per_wording_entry() -> None:
    names = sorted(_on_disk(FIXTURE_ROOT / "alerts"))
    expected = {f"CLOSE_REQUIRED__{code}.txt" for code in CLOSE_REQUIRED_WORDING}
    expected.add("CLOSE_REQUIRED__GENERIC.txt")
    expected.update(f"{event}.txt" for event in EVENT_WORDING)

    assert names == sorted(expected)
    assert len(names) == 18  # nine branch codes, the generic one and eight events


def test_the_message_goldens_exist_and_name_no_local_zone() -> None:
    names = sorted(_on_disk(FIXTURE_ROOT / "messages"))

    assert names == [
        "approve_base.txt",
        "approve_request_demo.txt",
        "approve_request_live.txt",
        "confirm_card_demo.txt",
        "confirm_final_confirmed_demo.txt",
        "confirm_final_expired_demo.txt",
        "simulate.txt",
    ]
    for text in _on_disk(FIXTURE_ROOT / "messages").values():
        assert "Asia/Ho_Chi_Minh" not in text


def test_every_generated_text_is_lf_and_ends_with_one_newline() -> None:
    for text in _load_generator().render_all().values():
        assert "\r" not in text
        assert text.endswith("\n") and not text.endswith("\n\n")


def test_check_is_clean_on_the_committed_files() -> None:
    assert _load_generator().main(["--check", "--out", str(FIXTURE_ROOT)]) == 0


def test_check_fails_when_one_golden_file_differs(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    assert generator.main(["--check", "--out", str(tmp_path)]) == 0

    victim = sorted(tmp_path.rglob("*.txt"))[0]
    victim.write_bytes(victim.read_bytes() + b"x\n")

    assert generator.main(["--check", "--out", str(tmp_path)]) == 1


def test_check_fails_when_a_golden_file_is_missing(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    sorted(tmp_path.rglob("*.txt"))[0].unlink()

    assert generator.main(["--check", "--out", str(tmp_path)]) == 1


def test_generator_rerun_is_byte_identical(tmp_path: Path) -> None:
    generator = _load_generator()
    first, second = tmp_path / "first", tmp_path / "second"
    assert generator.main(["--out", str(first)]) == 0
    assert generator.main(["--out", str(second)]) == 0
    assert _on_disk(first) == _on_disk(second)
