"""Plan 15-17: the paper stream-start gate on run_paper_tick (G-15-11, D-16, D-27).

`run_paper_tick` checks the parameter set at its very top, before any candle is parsed.
A set whose rationale is missing or incomplete, or that carries a PLACEHOLDER key, cannot
start a paper stream. A set without rationale tables may start only when the approved
allowlist (`PAPER_START_ALLOWLIST`, src/paper/freeze.py) holds an entry with the same ids and
the exact `parameter_set_hash`. By the user's decision at checkpoint 15-17-01 (Option B,
2026-10-07) that allowlist is empty and D-27 is unchanged.

Sets are written into pytest tmp_path registries only; nothing here writes under params/ or
tests/fixtures/.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from src.domain.canonical import sha256_hex
from src.domain.rationale import UnrationalizedParameterSet
from src.domain.registry import load_parameter_set

from tests.test_paper_parity import (
    PARITY_FIXTURE_DIR,
    _bar_to_ws_event,
    _paper_constraint_snapshot,
)
from tests.test_rationale import (
    BASE_SET,
    SET_ID,
    STRATEGY_ID,
    complete_rationale,
    parsed_params,
    write_rationalized_set,
    write_set,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"
CLEAN_RUN_DIR = PHASE7_FIXTURES_DIR / "clean_run"
PINS_PATH = REPO_ROOT / "tests" / "fixtures" / "phase4" / "parameters.json"

SPIED_NAMES = (
    "_parse_candle",
    "_is_closed_event",
    "evaluate",
    "plan",
    "evaluate_risk",
    # Review WR-03: everything run_paper_tick does with the caller's account, constraint,
    # position, cost and warm-up inputs sits behind the gate too.
    "_parse_account_state",
    "_parse_constraint_snapshot",
    "_parse_open_positions",
    "_coerce_money",
    "build_cost_model",
    "assert_sizing_costs_bind_registry",
    "check_feature_validity",
    "check_feed_freshness",
)
GATE_READ_KEYS = frozenset({"strategy_id", "strategy_version", "parameter_set_id", "now_utc"})


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _clean_run_input() -> dict[str, Any]:
    return json.loads((CLEAN_RUN_DIR / "input.json").read_text(encoding="utf-8"))


def _clean_run_digest() -> str:
    expected = json.loads((CLEAN_RUN_DIR / "expected.json").read_text(encoding="utf-8"))
    return str(expected["outcome_digest"])


def _parity_tick_input() -> dict[str, Any]:
    """One paper tick on trend-pullback baseline-v6 (built like _replay_paper_through_bars)."""
    fixture = json.loads((PARITY_FIXTURE_DIR / "input.json").read_text(encoding="utf-8"))
    strategy_bars = fixture["strategy_bars"]
    context_bars = fixture["context_bars"]
    (symbol,) = fixture["symbols"]
    i = len(strategy_bars) - 1
    bar = strategy_bars[i]
    bar_close = bar["close_time_utc"]
    return {
        "strategy_id": fixture["strategy_id"],
        "strategy_version": fixture["strategy_version"],
        "parameter_set_id": fixture["parameter_set_id"],
        "account_state": fixture["account_state"],
        "cost_model": fixture["cost_model"],
        "constraint_snapshot": _paper_constraint_snapshot(fixture, bar_close),
        "open_positions": [],
        "daily_loss_quote": "0",
        "ttl_seconds": "0",
        "symbol": symbol,
        "warmed_up_1h": strategy_bars[:i],
        "warmed_up_4h": [c for c in context_bars if c["close_time_utc"] <= bar_close],
        "feed_events": [_bar_to_ws_event(bar)],
        "now_utc": bar_close,
    }


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[int]]:
    """Replace the five candle-and-engine entry points on src.paper.loop with call recorders."""
    import src.paper.loop as loop

    calls: dict[str, list[int]] = {name: [] for name in SPIED_NAMES}
    for name in SPIED_NAMES:
        original = getattr(loop, name)

        def recorder(
            *args: Any, _name: str = name, _original: Any = original, **kwargs: Any
        ) -> Any:
            calls[_name].append(1)
            return _original(*args, **kwargs)

        monkeypatch.setattr(loop, name, recorder)
    return calls


def _assert_no_candle_work(calls: dict[str, list[int]]) -> None:
    assert {name: len(v) for name, v in calls.items()} == {name: 0 for name in SPIED_NAMES}


class _RecordingCase(dict[str, Any]):
    """case_input that records every key the loop reads, so the gate's reach can be proven."""

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> Any:
        self.reads.append(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        self.reads.append(key)
        return super().get(key, default)


@pytest.mark.parametrize("tick_input", [_clean_run_input, _parity_tick_input], ids=["v3", "v6"])
def test_a_refused_set_never_reads_any_other_case_input_field(
    tick_input: Any, spies: dict[str, list[int]]
) -> None:
    """Review WR-03: the gate precedes every account, constraint, cost and feed-event read."""
    from src.paper.loop import run_paper_tick

    case = _RecordingCase(tick_input())
    with pytest.raises(UnrationalizedParameterSet):
        run_paper_tick(case)
    assert set(case.reads) <= GATE_READ_KEYS, sorted(set(case.reads) - GATE_READ_KEYS)
    _assert_no_candle_work(spies)


@pytest.mark.parametrize("tick_input", [_clean_run_input, _parity_tick_input], ids=["v3", "v6"])
def test_a_refused_set_is_refused_even_when_every_other_field_is_missing(
    tick_input: Any,
) -> None:
    from src.paper.loop import run_paper_tick

    full = tick_input()
    stripped = {k: full[k] for k in GATE_READ_KEYS}
    with pytest.raises(UnrationalizedParameterSet):
        run_paper_tick(stripped)


def _entry(strategy_id: str, parameter_set_id: str, parameter_set_hash: str) -> Any:
    from src.paper.freeze import PaperAllowlistEntry

    return PaperAllowlistEntry(
        strategy_id=strategy_id,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set_hash,
        purpose="test-only entry",
        approved_at="2026-10-07",
        basis="tests/test_paper_start_gate.py (injected, never production)",
    )


def _production_hash(strategy_id: str, parameter_set_id: str) -> str:
    """Hash of the committed params/ file through the registry parse path (freeze.py's root)."""
    from src.paper.freeze import REGISTRY_ROOT, _load_parameter_set_with_root

    return _load_parameter_set_with_root(
        strategy_id, parameter_set_id, REGISTRY_ROOT
    ).parameter_set_hash


def _inject(monkeypatch: pytest.MonkeyPatch, *entries: Any) -> None:
    import src.paper.freeze as freeze

    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", tuple(entries))


# --------------------------------------------------------------------------- #
# Empty allowlist branch and the decision record.
# --------------------------------------------------------------------------- #


def test_empty_allowlist_refuses_set_without_rationale_before_any_candle(
    monkeypatch: pytest.MonkeyPatch, spies: dict[str, list[int]]
) -> None:
    from src.paper.loop import run_paper_tick

    _inject(monkeypatch)
    actual_hash = load_parameter_set("trend-pullback", "baseline-v3").parameter_set_hash
    with pytest.raises(UnrationalizedParameterSet) as excinfo:
        run_paper_tick(_clean_run_input())
    message = str(excinfo.value)
    assert "trend-pullback/baseline-v3" in message
    assert "missing rationale tables" in message
    assert "not in the approved allowlist" in message
    assert "the approved allowlist is empty" in message
    assert actual_hash in message
    _assert_no_candle_work(spies)


def test_production_allowlist_is_empty_by_user_decision() -> None:
    from src.paper.freeze import PAPER_START_ALLOWLIST

    assert PAPER_START_ALLOWLIST == (), (
        "PAPER_START_ALLOWLIST ships empty by the user's decision at checkpoint 15-17-01 "
        "(Option B, 2026-10-07); an entry needs a new user checkpoint and a D054 update"
    )


def test_placeholder_set_is_refused_before_any_candle(spies: dict[str, list[int]]) -> None:
    from src.paper.loop import run_paper_tick

    with pytest.raises(UnrationalizedParameterSet) as excinfo:
        run_paper_tick(_parity_tick_input())
    message = str(excinfo.value)
    assert "PLACEHOLDER keys" in message
    assert "baseline-v6" in message
    _assert_no_candle_work(spies)


# --------------------------------------------------------------------------- #
# Non-empty allowlist branch (entries injected with monkeypatch, tests only).
# --------------------------------------------------------------------------- #


def test_injected_exact_hash_match_lets_a_set_without_rationale_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.paper.loop import run_paper_tick

    parameter_set = load_parameter_set("trend-pullback", "baseline-v3")
    pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    assert parameter_set.parameter_set_hash in json.dumps(pins), (
        "the computed hash must equal the pinned one in tests/fixtures/phase4/parameters.json"
    )
    flagged = run_paper_tick(_clean_run_input(), allow_unrationalized=True)

    _inject(monkeypatch, _entry("trend-pullback", "baseline-v3", parameter_set.parameter_set_hash))
    outcome = run_paper_tick(_clean_run_input())
    assert sha256_hex(outcome) == _clean_run_digest()
    assert sha256_hex(outcome) == sha256_hex(flagged)


def test_injected_hash_mismatch_is_refused(
    monkeypatch: pytest.MonkeyPatch, spies: dict[str, list[int]]
) -> None:
    from src.paper.loop import run_paper_tick

    actual = load_parameter_set("trend-pullback", "baseline-v3").parameter_set_hash
    listed = load_parameter_set("trend-pullback", "baseline-v2").parameter_set_hash
    assert listed != actual
    _inject(monkeypatch, _entry("trend-pullback", "baseline-v3", listed))
    with pytest.raises(UnrationalizedParameterSet) as excinfo:
        run_paper_tick(_clean_run_input())
    message = str(excinfo.value)
    assert "not in the approved allowlist" in message
    assert listed in message
    assert actual in message
    assert "the approved allowlist is empty" not in message
    _assert_no_candle_work(spies)


def test_injected_entry_does_not_match_a_neighbouring_set_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.paper.freeze import pin_stream_epoch

    v3 = load_parameter_set("trend-pullback", "baseline-v3").parameter_set_hash
    _inject(monkeypatch, _entry("trend-pullback", "baseline-v3", v3))
    with pytest.raises(UnrationalizedParameterSet) as excinfo:
        pin_stream_epoch(
            strategy_id="trend-pullback",
            parameter_set_id="baseline-v2",
            opened_at_utc=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
        )
    assert "not in the approved allowlist" in str(excinfo.value)


def test_injected_entry_never_admits_a_set_that_has_rationale_tables(
    monkeypatch: pytest.MonkeyPatch, spies: dict[str, list[int]], tmp_path: Path
) -> None:
    import src.domain.registry as domain_registry
    import src.paper.freeze as freeze
    from src.paper.freeze import pin_stream_epoch
    from src.paper.loop import run_paper_tick

    # (a) baseline-v6 (PLACEHOLDER keys) listed by its exact hash: still refused.
    v6 = load_parameter_set("trend-pullback", "baseline-v6").parameter_set_hash
    _inject(monkeypatch, _entry("trend-pullback", "baseline-v6", v6))
    with pytest.raises(UnrationalizedParameterSet) as excinfo:
        run_paper_tick(_parity_tick_input())
    assert "PLACEHOLDER keys" in str(excinfo.value)
    _assert_no_candle_work(spies)

    # (b) a tmp set with rationale tables (one entry missing, no PLACEHOLDER basis), listed by hash.
    spec = complete_rationale(parsed_params(BASE_SET))
    del spec[sorted(spec)[0]]
    write_set(tmp_path, spec=spec)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(freeze, "REGISTRY_ROOT", tmp_path)
    tmp_hash = load_parameter_set(STRATEGY_ID, SET_ID).parameter_set_hash
    _inject(monkeypatch, _entry(STRATEGY_ID, SET_ID, tmp_hash))
    with pytest.raises(UnrationalizedParameterSet) as excinfo2:
        pin_stream_epoch(
            strategy_id=STRATEGY_ID,
            parameter_set_id=SET_ID,
            opened_at_utc=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
            registry_root=tmp_path,
        )
    assert "missing rationale entry" in str(excinfo2.value)


# --------------------------------------------------------------------------- #
# A fully rationalized set is not blanket-refused; the hash guard; import.
# --------------------------------------------------------------------------- #


def test_fully_rationalized_set_runs_without_the_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import src.domain.registry as domain_registry
    import src.paper.freeze as freeze
    from src.backtest.costs import cost_slice
    from src.paper.loop import run_paper_tick

    write_rationalized_set(tmp_path)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", tmp_path)
    monkeypatch.setattr(freeze, "REGISTRY_ROOT", tmp_path)
    parameter_set = load_parameter_set(STRATEGY_ID, SET_ID)

    case = _clean_run_input()
    case["parameter_set_id"] = SET_ID
    case["strategy_version"] = parameter_set.strategy_version
    case["cost_model"] = {k: str(v) for k, v in cost_slice(parameter_set.params).items()}

    strict = run_paper_tick(case)
    flagged = run_paper_tick(case, allow_unrationalized=True)
    assert strict["feed_events_processed"] >= 1
    assert sha256_hex(strict) == sha256_hex(flagged)


def test_gate_and_loop_must_judge_the_same_file(
    monkeypatch: pytest.MonkeyPatch, spies: dict[str, list[int]], tmp_path: Path
) -> None:
    import src.domain.registry as domain_registry
    from src.paper.loop import run_paper_tick

    source = REPO_ROOT / "params" / "trend-pullback" / "baseline-v3.toml"
    text = source.read_text(encoding="utf-8")
    target = tmp_path / "trend-pullback" / "baseline-v3.toml"
    target.parent.mkdir(parents=True)
    key_line = next(line for line in text.splitlines() if line.startswith("zone_tolerance_atr"))
    target.write_text(text.replace(key_line, "zone_tolerance_atr = 0.6", 1), encoding="utf-8")
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", tmp_path)
    loaded = load_parameter_set("trend-pullback", "baseline-v3").parameter_set_hash
    production = _production_hash("trend-pullback", "baseline-v3")
    assert loaded != production

    with pytest.raises(ValueError, match="parameter_set_hash") as excinfo:
        run_paper_tick(_clean_run_input(), allow_unrationalized=True)
    assert loaded in str(excinfo.value)
    assert production in str(excinfo.value)
    assert spies["_parse_candle"] == []


def test_import_with_the_empty_allowlist_emits_no_error_or_warning() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "import src.paper.loop; from src.paper.freeze import PAPER_START_ALLOWLIST",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


# --------------------------------------------------------------------------- #
# Guards over src/ (IN-01): the test-only flag and the allowlist stay untouchable.
# --------------------------------------------------------------------------- #


FLAG = "allow_unrationalized"
ALLOWLIST = "PAPER_START_ALLOWLIST"
FLAG_FILES = frozenset({"paper/freeze.py", "paper/loop.py"})
ALLOWLIST_FILE = "paper/freeze.py"


def _bound_names(node: ast.AST) -> list[str]:
    """Names (or attribute names) a statement binds, rebinds or deletes."""
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    elif isinstance(node, ast.Delete):
        targets = list(node.targets)
    names: list[str] = []
    for target in targets:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
            elif isinstance(sub, ast.Attribute):
                names.append(sub.attr)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        names.extend((alias.asname or alias.name) for alias in node.names)
    return names


def _allowlist_binding_violations(tree: ast.Module, rel: str) -> list[str]:
    """Exactly one module-level tuple-literal binding of the allowlist; nothing else touches it."""
    found: list[str] = []
    module_level = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and ALLOWLIST in _bound_names(node)
    ]
    if len(module_level) != 1:
        found.append(
            f"{rel}: {ALLOWLIST} needs exactly one module-level binding, found {len(module_level)}"
        )
    for node in module_level:
        value = node.value
        if not isinstance(value, ast.Tuple):
            found.append(f"{rel}:{node.lineno}: {ALLOWLIST} value is not a tuple literal")
    allowed = {id(node) for node in module_level[:1]}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)) and ALLOWLIST in node.names:
            found.append(f"{rel}:{node.lineno}: {ALLOWLIST} declared global or nonlocal")
        elif ALLOWLIST in _bound_names(node) and id(node) not in allowed:
            found.append(f"{rel}:{node.lineno}: {ALLOWLIST} rebound, extended or deleted")
    return found


def _scan_src_violations(root: Path) -> list[str]:
    """AST scan of every *.py under root: the test-only flag and the allowlist (plan 15-17).

    Reports, sorted: a call passing the flag as the constant True; a dict literal keyed by the
    flag name; any mention of the flag outside paper/freeze.py and paper/loop.py; any mention
    of the allowlist name outside paper/freeze.py; and in paper/freeze.py anything but one
    module-level tuple-literal binding (rebinding, augmented assignment, global, del,
    setattr/delattr naming it). A name built at runtime is not visible to this check.
    """
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (
                        kw.arg == FLAG
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        found.append(
                            f"{rel}:{node.lineno}: call passes {FLAG} as the constant True"
                        )
                if isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"}:
                    if any(isinstance(a, ast.Constant) and a.value == ALLOWLIST for a in node.args):
                        found.append(f"{rel}:{node.lineno}: {node.func.id} names {ALLOWLIST}")
            elif isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value == FLAG:
                        found.append(f"{rel}:{node.lineno}: dict key {FLAG}")
        if rel not in FLAG_FILES and FLAG in source:
            found.append(f"{rel}: mentions {FLAG} outside paper/freeze.py and paper/loop.py")
        if rel != ALLOWLIST_FILE and ALLOWLIST in source:
            found.append(f"{rel}: mentions {ALLOWLIST} outside {ALLOWLIST_FILE}")
        if rel == ALLOWLIST_FILE:
            found.extend(_allowlist_binding_violations(tree, rel))
    return sorted(found)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_guard_helper_reports_every_seeded_violation(tmp_path: Path) -> None:
    _write(tmp_path, "paper/x.py", "def f(g):\n    return g(allow_unrationalized=True)\n")
    _write(tmp_path, "other/y.py", 'CFG = {"allow_unrationalized": True}\n')
    _write(tmp_path, "other/z.py", "allow_unrationalized = 1\n")
    _write(tmp_path, "other/w.py", "import freeze\nfreeze.PAPER_START_ALLOWLIST = ()\n")
    _write(
        tmp_path,
        "paper/freeze.py",
        "PAPER_START_ALLOWLIST = []\n"
        "def rebind():\n"
        "    global PAPER_START_ALLOWLIST\n"
        "    PAPER_START_ALLOWLIST = ()\n"
        "def poke(mod):\n"
        '    setattr(mod, "PAPER_START_ALLOWLIST", ())\n',
    )
    found = _scan_src_violations(tmp_path)
    joined = "\n".join(found)
    assert "paper/x.py" in joined and "constant True" in joined
    assert "other/y.py" in joined and "dict key" in joined
    assert "other/z.py" in joined and "allow_unrationalized" in joined
    assert "other/w.py" in joined and "PAPER_START_ALLOWLIST" in joined
    assert "not a tuple literal" in joined
    assert "global" in joined
    assert "setattr" in joined
    assert "rebound" in joined


def test_guard_helper_accepts_the_allowed_forms(tmp_path: Path) -> None:
    _write(tmp_path, "paper/freeze.py", "PAPER_START_ALLOWLIST: tuple[int, ...] = ()\n")
    _write(tmp_path, "paper/loop.py", "def f(allow_unrationalized=False):\n    return 1\n")
    assert _scan_src_violations(tmp_path) == []


def test_no_module_under_src_enables_the_flag_or_touches_the_allowlist() -> None:
    assert _scan_src_violations(REPO_ROOT / "src") == []


NON_BOOL_FLAGS: tuple[Any, ...] = ("False", "0", "no", "yes", "", 1, 0, 1.0, None, [], ["x"])


@pytest.mark.parametrize("bad", NON_BOOL_FLAGS, ids=repr)
def test_pin_stream_epoch_rejects_a_non_bool_flag(bad: Any) -> None:
    """Review WR-01: only the bool True may switch the gate off; anything else is a TypeError."""
    from src.paper.freeze import pin_stream_epoch

    with pytest.raises(TypeError, match="allow_unrationalized"):
        pin_stream_epoch(
            strategy_id="trend-pullback",
            parameter_set_id="baseline-v3",
            opened_at_utc=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
            allow_unrationalized=bad,
        )


@pytest.mark.parametrize("bad", NON_BOOL_FLAGS, ids=repr)
def test_run_paper_tick_rejects_a_non_bool_flag_before_anything_else(
    bad: Any, spies: dict[str, list[int]]
) -> None:
    from src.paper.loop import run_paper_tick

    with pytest.raises(TypeError, match="allow_unrationalized"):
        run_paper_tick({}, allow_unrationalized=bad)
    _assert_no_candle_work(spies)


def test_the_flag_is_honoured_only_as_the_bool_true() -> None:
    from src.paper.freeze import pin_stream_epoch

    opened = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    kwargs: dict[str, Any] = {
        "strategy_id": "trend-pullback",
        "parameter_set_id": "baseline-v3",
        "opened_at_utc": opened,
    }
    with pytest.raises(UnrationalizedParameterSet):
        pin_stream_epoch(**kwargs, allow_unrationalized=False)
    assert pin_stream_epoch(**kwargs, allow_unrationalized=True).evidence_claim_open is True


def _traversal_registry(tmp_path: Path) -> tuple[Path, str]:
    """A tmp registry whose `trend-pullback` dir can be walked out of to a real set file."""
    registry = tmp_path / "reg"
    (registry / STRATEGY_ID).mkdir(parents=True)
    write_rationalized_set(tmp_path / "outside")
    return registry, f"../../outside/{STRATEGY_ID}/{SET_ID}"


@pytest.mark.parametrize("allow", [False, True])
def test_pin_stream_epoch_rejects_a_traversing_parameter_set_id(
    tmp_path: Path, allow: bool
) -> None:
    """Review WR-04: the gate entry validates registry path segments like load_parameter_set."""
    from src.domain.registry import UnregisteredParameterSet
    from src.paper.freeze import pin_stream_epoch

    registry, escaping_id = _traversal_registry(tmp_path)
    assert (registry / STRATEGY_ID / f"{escaping_id}.toml").resolve().is_file()
    with pytest.raises(UnregisteredParameterSet, match="invalid registry path segment"):
        pin_stream_epoch(
            strategy_id=STRATEGY_ID,
            parameter_set_id=escaping_id,
            opened_at_utc=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
            registry_root=registry,
            allow_unrationalized=allow,
        )


@pytest.mark.parametrize(
    ("strategy_id", "parameter_set_id"),
    [
        ("../trend-pullback", "baseline-v3"),
        ("trend-pullback", "../baseline-v3"),
        ("trend-pullback", "a/b"),
        ("trend-pullback", "a\\b"),
        ("trend-pullback", ""),
        ("", "baseline-v3"),
        ("trend-pullback", "baseline-v3\x00"),
        ("C:/abs", "baseline-v3"),
    ],
)
def test_pin_stream_epoch_rejects_unsafe_registry_segments(
    strategy_id: str, parameter_set_id: str
) -> None:
    from src.domain.registry import UnregisteredParameterSet
    from src.paper.freeze import pin_stream_epoch

    with pytest.raises(UnregisteredParameterSet, match="invalid registry path segment"):
        pin_stream_epoch(
            strategy_id=strategy_id,
            parameter_set_id=parameter_set_id,
            opened_at_utc=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
        )


def test_recompute_parameter_set_hash_rejects_a_traversing_id(tmp_path: Path) -> None:
    from src.domain.registry import UnregisteredParameterSet
    from src.paper.freeze import _recompute_parameter_set_hash

    registry, escaping_id = _traversal_registry(tmp_path)
    with pytest.raises(UnregisteredParameterSet, match="invalid registry path segment"):
        _recompute_parameter_set_hash(
            strategy_id=STRATEGY_ID, parameter_set_id=escaping_id, registry_root=registry
        )


def test_gate_reads_the_set_file_once_and_judges_the_bytes_it_hashed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review WR-05: hash, rationale verdict and allowlist all come from one read of the file.

    The first read of the set file returns content A (no rationale tables). Every later read
    returns content B (an incomplete rationale). A gate that read the file again would judge B
    while it hashed A; the single-read gate judges A end to end.
    """
    import src.paper.freeze as freeze
    from src.paper.freeze import _load_parameter_set_with_root, pin_stream_epoch

    path_a = write_set(tmp_path, spec=None)
    bytes_a = path_a.read_bytes()
    hash_a = _load_parameter_set_with_root(STRATEGY_ID, SET_ID, tmp_path).parameter_set_hash
    spec = complete_rationale(parsed_params(BASE_SET))
    del spec[sorted(spec)[0]]
    bytes_b = write_set(tmp_path, spec=spec).read_bytes()
    path_a.write_bytes(bytes_a)
    assert bytes_a != bytes_b

    _inject(monkeypatch, _entry(STRATEGY_ID, SET_ID, hash_a))
    reads: list[Path] = []
    original = Path.read_bytes

    def flaky_read_bytes(self: Path) -> bytes:
        if self == path_a:
            reads.append(self)
            return bytes_a if len(reads) == 1 else bytes_b
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)
    epoch = pin_stream_epoch(
        strategy_id=STRATEGY_ID,
        parameter_set_id=SET_ID,
        opened_at_utc=datetime(2026, 10, 7, 10, 0, tzinfo=UTC),
        registry_root=tmp_path,
    )
    assert len(reads) == 1
    assert epoch.parameter_set_hash == hash_a
    assert freeze.PAPER_START_ALLOWLIST[0].parameter_set_hash == hash_a


def test_flag_is_keyword_only_and_strict_by_default() -> None:
    from src.paper.freeze import pin_stream_epoch
    from src.paper.loop import run_paper_tick

    for func in (run_paper_tick, pin_stream_epoch):
        parameter = inspect.signature(func).parameters[FLAG]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is False


def test_run_paper_tick_passes_its_own_flag_through_by_name() -> None:
    tree = ast.parse((REPO_ROOT / "src" / "paper" / "loop.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "pin_stream_epoch"
    ]
    assert len(calls) == 1
    (keyword,) = [kw for kw in calls[0].keywords if kw.arg == FLAG]
    assert isinstance(keyword.value, ast.Name)
    assert keyword.value.id == FLAG
    assert {kw.arg for kw in calls[0].keywords}.isdisjoint({"cost_model", "registry_root"})


def test_allowlist_entry_shape_and_privacy() -> None:
    import src.paper as paper_pkg
    import src.paper.freeze as freeze
    from src.paper.freeze import PaperAllowlistEntry

    assert dataclasses.is_dataclass(PaperAllowlistEntry)
    assert PaperAllowlistEntry.__dataclass_params__.frozen  # type: ignore[attr-defined]
    fields = dataclasses.fields(PaperAllowlistEntry)
    assert [f.name for f in fields] == [
        "strategy_id",
        "parameter_set_id",
        "parameter_set_hash",
        "purpose",
        "approved_at",
        "basis",
    ]
    assert all(f.type in (str, "str") for f in fields)
    for name in ("PaperAllowlistEntry", ALLOWLIST):
        assert name not in freeze.__all__
        assert not hasattr(paper_pkg, name)
