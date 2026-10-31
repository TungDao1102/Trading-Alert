"""Phase 20 gate (plan 20-23): the structural invariants of the reconcile / SAFE_MODE phase.

This file asserts, against the real tree and without any network or live evidence:

- the new pure modules read no wall clock, build no float and import no SDK, network or
  database client (`PHASE20_PURE_MODULES`); the orchestrators read no wall clock and import no
  SDK (`PHASE20_ORCHESTRATOR_MODULES`);
- no module under `src/reconcile` calls a placement method (`PHASE20_RECONCILE_MODULES`); a
  protective action the reconciler delegates is placed by the coordinator in `src/execution`
  (F-604, D034/D077; asserted by role, id and price in `tests/test_drills.py`);
- every new Phase 20 limit key is `NOT_CONFIGURED` (value and provenance) in the execution limits
  file and is guarded against an invented default (`PHASE20_LIMIT_KEYS`);
- the `RejectionReason` enum has 21 members and GLOSSARY 9.1 lists exactly those;
- each Phase 20 requirement has its named automated tests, resolved with `ast` and never
  imported or run (`REQUIREMENT_TESTS`);
- no Phase 20 plan wrote a `docs/DECISIONS.md` row; the rows after D078 are D079 to D083, written
  by quick task 261022-t2l at the owner's instruction of 2026-10-22, and the D055 row names D079.

A failure message names the missing path, symbol or test. Nothing here changes behavior and
nothing here claims an owner item is solved: the `NOT_CONFIGURED` limit keys and what Demo
cannot show (a partial fill P3, the order of a cancel against a fill P7, a GTD expiry A2; D079
item 6) stay with the owner (`19-OWNER-GAPS.md`). The ROADMAP success criteria of Phase 20 stay
pinned by `tests/test_phase19_gate.py`.

Evidence label: executed structural tests. Nothing here touches Binance, Telegram or a database.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# The module inventory.
# --------------------------------------------------------------------------- #

#: New pure modules: stdlib plus project types only. No wall clock, no float, no SDK.
PHASE20_PURE_MODULES: tuple[str, ...] = (
    "src/execution/protection_replay.py",
    "src/execution/protection_rebuild.py",
    "src/execution/cancel_verification.py",
    "src/reconcile/compare.py",
    "src/reconcile/classify.py",
    "src/reconcile/local_intent.py",
    "src/reconcile/feed_freshness.py",
    "src/execution/pending_actions.py",
    "src/domain/transitions.py",
)

#: Orchestrators of Phase 20: they take an injected clock and read no wall clock.
PHASE20_ORCHESTRATOR_MODULES: tuple[str, ...] = (
    "src/reconcile/loop.py",
    "src/reconcile/startup.py",
    "src/ops/alerts.py",
    "src/ops/spill.py",
    "src/ops/risk_first.py",
    "src/adapters/binance_ratelimit_gate.py",
)

#: Every module of the reconcile package. A new module must be added here on purpose, so the
#: placement guard below can never skip it by accident.
PHASE20_RECONCILE_MODULES: tuple[str, ...] = (
    "src/reconcile/__init__.py",
    "src/reconcile/classify.py",
    "src/reconcile/compare.py",
    "src/reconcile/feed_freshness.py",
    "src/reconcile/local_intent.py",
    "src/reconcile/loop.py",
    "src/reconcile/safe_mode.py",
    "src/reconcile/startup.py",
    "src/reconcile/sweeper.py",
)

# A pure module imports none of these (SDK, network, database, validation or dataframe clients).
PURE_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "binance*",
    "requests",
    "aiohttp",
    "httpx",
    "websockets",
    "sqlalchemy",
    "pydantic",
    "polars",
)
# An orchestrator may use the project adapters, but never the vendor SDK or a raw network client.
ORCHESTRATOR_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "binance*",
    "requests",
    "aiohttp",
    "httpx",
    "websockets",
)


def test_phase20_module_inventory_exists() -> None:
    missing = [
        relative
        for relative in (
            *PHASE20_PURE_MODULES,
            *PHASE20_ORCHESTRATOR_MODULES,
            *PHASE20_RECONCILE_MODULES,
        )
        if not (ROOT / relative).is_file()
    ]
    assert missing == [], f"missing Phase 20 modules: {missing}"
    on_disk = sorted(
        f"src/reconcile/{path.name}" for path in (ROOT / "src" / "reconcile").glob("*.py")
    )
    assert on_disk == sorted(PHASE20_RECONCILE_MODULES), (
        "src/reconcile changed: add the new module to PHASE20_RECONCILE_MODULES so the "
        "placement guard covers it"
    )


@pytest.mark.parametrize("relative", PHASE20_PURE_MODULES)
def test_invariant_1_pure_modules_have_no_wall_clock_no_float_and_no_sdk(relative: str) -> None:
    path = ROOT / relative
    assert wall_clock_calls(path) == [], f"{relative} reads a wall clock"
    assert float_constructor_calls(path) == [], f"{relative} builds a float"
    assert forbidden_imports(path, PURE_FORBIDDEN_IMPORTS) == [], f"{relative} imports a client"


@pytest.mark.parametrize("relative", PHASE20_ORCHESTRATOR_MODULES)
def test_invariant_1b_orchestrators_read_no_wall_clock_and_import_no_sdk(relative: str) -> None:
    path = ROOT / relative
    assert wall_clock_calls(path) == [], f"{relative} reads a wall clock"
    assert forbidden_imports(path, ORCHESTRATOR_FORBIDDEN_IMPORTS) == [], (
        f"{relative} imports the SDK or a network client"
    )


# --------------------------------------------------------------------------- #
# The reconciler places nothing (F-604, D034/D077, criterion 5).
# --------------------------------------------------------------------------- #

_PLACEMENT_CALL_NAMES: frozenset[str] = frozenset({"new_order", "new_algo_order"})


def placement_calls(path: Path) -> list[tuple[int, str]]:
    """`(line, name)` of every call whose function name is a placement name.

    Matches `place_*` (place_order, place_algo_order, place_entry, place_algo_protective,
    place_market_close, ...), `new_order` and `new_algo_order`, as a plain name or as an
    attribute of anything. Imports are looked at too: importing a placement function is as
    forbidden as calling it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(func.attr)
        elif isinstance(node, ast.ImportFrom):
            names.extend(alias.name for alias in node.names)
        for name in names:
            if name.startswith("place_") or name in _PLACEMENT_CALL_NAMES:
                found.append((node.lineno, name))
    return sorted(found)


def test_invariant_2_no_module_under_src_reconcile_calls_a_placement_method() -> None:
    offenders = {
        relative: placement_calls(ROOT / relative)
        for relative in PHASE20_RECONCILE_MODULES
        if placement_calls(ROOT / relative)
    }
    assert offenders == {}, (
        f"src/reconcile places an order: {offenders}. A delegated protective action is placed "
        "by the coordinator in src/execution (D034/D077), never by the reconciler."
    )


def test_invariant_2b_the_placement_guard_is_armed(tmp_path: Path) -> None:
    """The scan above finds a placement call, a placement import and ignores a cancel."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from adapter import place_entry\n"
        "async def go(a):\n"
        "    await a.place_algo_protective(x=1)\n"
        "    await a.new_order(x=1)\n"
        "    await a.cancel_algo_order(x=1)\n",
        encoding="utf-8",
    )
    assert placement_calls(sample) == [
        (1, "place_entry"),
        (3, "place_algo_protective"),
        (4, "new_order"),
    ]
    # The coordinator, which legitimately places the delegated stop, is found by the same scan.
    assert placement_calls(ROOT / "src" / "execution" / "protection.py") != []


# --------------------------------------------------------------------------- #
# Limit keys: new, unset, guarded.
# --------------------------------------------------------------------------- #

#: The seven keys Phase 20 (plan 20-01) added to `EXECUTION_LIMIT_KEYS`.
PHASE20_LIMIT_KEYS: tuple[str, ...] = (
    "reconcile.tick_interval_ms",
    "reconcile.entry_unknown_probe_count",
    "reconcile.entry_unknown_probe_interval_ms",
    "reconcile.lot_filter_refresh_interval_ms",
    "stale_feed.max_mark_price_age_ms",
    "stale_feed.max_user_data_silence_ms",
    "alerts.dedupe_window_ms",
)
# DECISIONS D089: the owner did not answer this one, so the shipped file keeps it NOT_CONFIGURED.
UNANSWERED_PHASE20_KEY = "stale_feed.max_user_data_silence_ms"
EXECUTION_LIMITS_FILE = ROOT / "config" / "execution" / "execution-limits-v1.toml"


def test_invariant_3_every_new_limit_key_is_decided_or_unset_and_guarded() -> None:
    from src.execution.execution_limits import (
        EXECUTION_LIMIT_FIELDS,
        EXECUTION_LIMIT_KEYS,
        NOT_CONFIGURED_WORD,
        load_execution_limits,
    )

    from tests import test_no_unratified_defaults as unratified

    declared = {
        f"{section}.{key}" for section, keys in EXECUTION_LIMIT_KEYS.items() for key in keys
    }
    assert set(PHASE20_LIMIT_KEYS) <= declared, (
        f"keys not declared: {sorted(set(PHASE20_LIMIT_KEYS) - declared)}"
    )
    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    problems: list[str] = []
    for dotted in PHASE20_LIMIT_KEYS:
        section, key = dotted.split(".")
        value = document[section][key]
        label = document["provenance"][section][key]
        if dotted == UNANSWERED_PHASE20_KEY:
            if value != NOT_CONFIGURED_WORD or label != NOT_CONFIGURED_WORD:
                problems.append(f"{dotted}: value {value!r} label {label!r} (not answered)")
        elif not isinstance(value, int) or isinstance(value, bool) or label != "DECISION":
            problems.append(f"{dotted}: value {value!r} label {label!r} (D089 sets it)")
        field = EXECUTION_LIMIT_FIELDS.get(dotted)
        if field is None:
            problems.append(f"{dotted}: no ExecutionLimits field")
            continue
        for guarded in (key, field):
            if guarded not in unratified.GUARDED_NAMES:
                problems.append(f"{dotted}: {guarded!r} is not in the unratified-default guard")
    assert problems == [], f"Phase 20 limit keys: {problems}"
    # The shipped file loads: DECISIONS D089 (owner answer 2026-10-31) set every key but one.
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    for dotted in PHASE20_LIMIT_KEYS:
        loaded = getattr(limits, EXECUTION_LIMIT_FIELDS[dotted])
        assert (loaded is None) == (dotted == UNANSWERED_PHASE20_KEY), dotted
    assert unratified.ALLOW_LIST == {}


# --------------------------------------------------------------------------- #
# Enum and GLOSSARY counts.
# --------------------------------------------------------------------------- #


def test_invariant_4_the_rejection_reason_enum_and_glossary_91_agree_on_21_codes() -> None:
    from src.domain.enums import RejectionReason

    text = (ROOT / "docs" / "GLOSSARY.md").read_text(encoding="utf-8")
    block = text[text.index("### 9.1 ") : text.index("### 9.2 ")]
    codes = re.search(r"```text\n(.*?)```", block, re.DOTALL)
    assert codes is not None, "GLOSSARY 9.1 has no code block"
    listed = codes.group(1).split()
    assert len(RejectionReason) == 23, (
        "G3-005 (D-35): Phase 24 promoted NO_FILL and HEALTH_CHECK_FAILED, 23 members"
    )
    assert len(listed) == len(set(listed)) == 23, f"GLOSSARY 9.1 lists {len(listed)} codes"
    enum_codes = {member.value for member in RejectionReason}
    assert set(listed) == enum_codes, (
        f"GLOSSARY 9.1 and the enum differ: {sorted(set(listed) ^ enum_codes)}"
    )


# --------------------------------------------------------------------------- #
# Requirement -> named tests (resolved with ast, never imported).
# --------------------------------------------------------------------------- #

REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "EXEC-02": (
        (
            "tests/test_reconcile_loop.py",
            "test_position_without_stop_is_delegated_once_and_alerted_as_unprotected",
        ),
        ("tests/test_reconcile.py", "test_no_place_order_path_in_src_reconcile"),
        (
            "tests/test_protection_supervision.py",
            "test_notify_divergence_journals_once_and_places_and_cancels_nothing",
        ),
        (
            "tests/test_drills.py",
            "test_reconcile_never_places_and_delegated_stops_keep_the_plan_price",
        ),
    ),
    "OPS-01": (
        ("tests/test_drills.py", "test_unprotected_drill_blocks_entries_through_the_loop"),
        (
            "tests/test_drills.py",
            "test_stale_feed_drill_enters_safe_mode_through_the_loops_feed_check",
        ),
        (
            "tests/test_drills.py",
            "test_manual_close_drill_orphan_variant_sweeps_the_legs_that_stayed",
        ),
        (
            "tests/test_drills.py",
            "test_manual_close_drill_auto_cancel_variant_has_nothing_to_sweep",
        ),
        ("tests/test_drills.py", "test_safe_mode_exit_only_via_restore_drill"),
        (
            "tests/test_safe_mode_exit_operator.py",
            "test_the_restore_drill_exits_with_an_operator_id",
        ),
    ),
    "RISK-03": (
        (
            "tests/test_manual_controls.py",
            "test_manual_close_never_cancels_an_open_positions_stop",
        ),
        ("tests/test_cancel_verification.py", "test_manual_close_outside_system_orphan_swept"),
        (
            "tests/test_drills.py",
            "test_manual_close_drill_with_the_position_still_open_never_cancels_the_stop",
        ),
    ),
    "EXEC-06": (
        ("tests/test_manual_controls.py", "test_exec06_five_controls_exist"),
        ("tests/test_manual_controls.py", "test_operator_close_flattens_through_the_coordinator"),
        (
            "tests/test_manual_controls.py",
            "test_operator_protect_delegates_to_the_coordinator_step",
        ),
    ),
    "OPS-05": (
        (
            "tests/test_alerts_ops05_matrix.py",
            "test_the_matrix_has_exactly_one_row_per_ops05_alert",
        ),
        ("tests/test_alert_producers.py", "test_entry_state_unknown_alerts_once"),
        (
            "tests/test_feed_freshness.py",
            "test_a_stale_mark_price_for_a_tracked_symbol_enters_safe_mode_and_alerts",
        ),
    ),
}


def _test_function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_invariant_5_each_phase20_requirement_has_its_named_tests() -> None:
    assert set(REQUIREMENT_TESTS) == {"EXEC-02", "OPS-01", "RISK-03", "EXEC-06", "OPS-05"}
    problems: list[str] = []
    for requirement, pairs in REQUIREMENT_TESTS.items():
        assert pairs, f"{requirement} names no test"
        for relative, prefix in pairs:
            path = ROOT / relative
            if not path.exists():
                problems.append(f"{requirement}: {relative} does not exist")
            elif not any(name.startswith(prefix) for name in _test_function_names(path)):
                problems.append(f"{requirement}: {relative} defines no test starting {prefix!r}")
    assert problems == [], f"requirement-to-test pairs missing: {problems}"


def test_invariant_5b_every_requirement_name_is_a_known_requirement() -> None:
    planning = ROOT / ".planning" / "REQUIREMENTS.md"
    if not planning.is_file():
        pytest.skip("REQUIREMENTS.md is not in this checkout (filtered)")
    text = planning.read_text(encoding="utf-8")
    for requirement in REQUIREMENT_TESTS:
        assert f"**{requirement}**" in text, requirement


# --------------------------------------------------------------------------- #
# DECISIONS: no Phase 20 plan wrote a row; D079 to D083 come from quick task 261022-t2l.
# --------------------------------------------------------------------------- #


def test_invariant_6_decisions_gained_no_row_and_d055_stays_open() -> None:
    lines = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if re.match(r"\| D\d+ \|", line)]
    ids = [re.match(r"\| (D\d+) \|", row).group(1) for row in rows]  # type: ignore[union-attr]
    after_d078 = ids[ids.index("D078") + 1 :]
    assert after_d078 == [
        "D079",
        "D080",
        "D081",
        "D082",
        "D083",
        "D084",
        "D085",
        "D086",
        "D087",
        "D088",
        "D089",
        "D090",
    ], (
        f"the rows after D078 are {after_d078}: quick task 261022-t2l wrote D079 to D083, "
        "Phase 21 wrote D084 (the equity age, 2026-10-23) and the owner answer of 2026-10-24 "
        "wrote D085 (Phase 22 O-1 to O-4) and D086 (Phase 21 O-3 to O-6); the owner answer of "
        "2026-10-25 wrote D087 (Phase 21 WR-08 and WR-05); the owner answer of 2026-10-26 "
        "wrote D088 (Phase 23 O-2, the G4-042 expiry rule); the owner answer of 2026-10-31 "
        "wrote D089 (Phase 24 execution limit values, plan 24-06); the assistant proposed "
        "D090 (Phase 24 REST gate alert events, plan 24-13)"
    )
    first = ids.index("D078") + 1
    for row in rows[first : first + 5]:
        assert "2026-10-22, owner instruction" in row, row[:40]
    assert "2026-10-23, owner answer" in rows[first + 5], rows[first + 5][:40]
    for row in rows[first + 6 : first + 8]:
        assert "2026-10-24, owner answer" in row, row[:40]
    assert len(ids) == len(set(ids)), "a DECISIONS row id is duplicated"
    d055 = [row for row in rows if row.startswith("| D055 |")]
    assert len(d055) == 1
    assert "stays OPEN" in d055[0], "the D055 row must keep its 2026-10-07 text"
    assert "decided by D079" in d055[0], "the D055 row must name D079"
    lowered = d055[0].lower()
    for claim in ("closes d055", "d055 is closed", "d055 closed", "closing d055"):
        assert claim not in lowered, f"the D055 row claims it is closed: {claim!r}"
