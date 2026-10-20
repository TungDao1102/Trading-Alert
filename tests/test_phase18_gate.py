"""Phase 18 gate (plan 18-22): the inventory and the structural invariants in one place.

This file asserts, against the real tree and without any network or live evidence:

- every module, script, config, test-support, fixture and decision artifact the Phase 18
  plans promise exists (`PHASE18_ARTIFACTS`); evidence produced by blocking-human steps or by
  later plans is listed apart (`PHASE18_EVIDENCE`) and is reported, never required;
- every public symbol later phases import is importable (`PHASE18_SYMBOLS`);
- each of EXEC-01, EXEC-02, EXEC-05 and OPS-02 has its named automated tests
  (`REQUIREMENT_TESTS`, resolved with `ast`, never imported or run);
- the structural invariants hold together (the nine `test_invariant_*` tests).

A failure message names the exact missing path, symbol or test, so a Phase 19 or 20 planner can
run this file first.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path

import pytest

from tests import (
    test_binance_client_config as client_config_tests,
)
from tests import (
    test_binance_limits_ratified_file as ratified_file_tests,
)
from tests import (
    test_binance_usdm_source_guard as source_guard_tests,
)
from tests import (
    test_no_unratified_defaults as unratified_tests,
)
from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = ROOT / ".planning" / "phases" / "18-user-data-stream-error-taxonomy"

# --------------------------------------------------------------------------- #
# The inventory.
# --------------------------------------------------------------------------- #

PHASE18_ARTIFACTS: tuple[str, ...] = (
    # Pure and adapter source (plans 18-03 to 18-15).
    "src/domain/algo_status.py",
    "src/domain/exchange_errors.py",
    "src/domain/stream_records.py",
    "src/adapters/binance_client.py",
    "src/adapters/binance_clock.py",
    "src/adapters/binance_errors.py",
    "src/adapters/binance_limits.py",
    "src/adapters/binance_probe.py",
    "src/adapters/binance_ratelimit_gate.py",
    "src/adapters/binance_userdata.py",
    "src/adapters/binance_userdata_events.py",
    "src/adapters/binance_userdata_router.py",
    "src/adapters/binance_userdata_supervisor.py",
    "src/ops/operator_evidence.py",
    # Scripts (18-16, 18-17).
    "scripts/user_data_smoke.py",
    "scripts/demo_probe.py",
    # The ratified configuration (18-09, 18-07).
    "config/binance/binance-limits-v1.toml",
    "config/binance/README.md",
    # Test support and fakes.
    "tests/support/ast_guards.py",
    "tests/support/fake_binance_exchange.py",
    "tests/support/limits.py",
    "tests/support/stream_sinks.py",
    "tests/support/userdata_frames.py",
    "tests/support/virtual_time.py",
    "tests/probe_fakes.py",
    "tests/userdata_fakes.py",
    # Fixtures (18-24 synthetic; the recorded Demo frames are evidence, see below).
    "tests/fixtures/phase18/README.md",
    "tests/fixtures/phase18/synthetic/order_trade_update_trade.json",
    "tests/fixtures/phase18/synthetic/algo_update_new.json",
    # Tests, one per plan deliverable.
    "tests/test_sources_phase18_section.py",
    "tests/test_userdata_events.py",
    "tests/test_userdata_parsers.py",
    "tests/test_userdata_fixtures.py",
    "tests/test_userdata_adapter.py",
    "tests/test_userdata_contract.py",
    "tests/test_userdata_supervisor.py",
    "tests/test_userdata_rig.py",
    "tests/test_userdata_router.py",
    "tests/test_userdata_replay.py",
    "tests/test_userdata_recorded_frames.py",
    "tests/test_binance_client_config.py",
    "tests/test_binance_secret_redaction.py",
    "tests/test_exchange_errors.py",
    "tests/test_exchange_error_rejections.py",
    "tests/test_sdk_error_mapping_contract.py",
    "tests/test_adapter_not_found_mapping.py",
    "tests/test_algo_status.py",
    "tests/test_binance_limits.py",
    "tests/test_binance_limits_ratified_file.py",
    "tests/test_clock_drift.py",
    "tests/test_no_unratified_defaults.py",
    "tests/test_stream_records.py",
    "tests/test_persistence_exit_evidence_pg.py",
    "tests/test_binance_ratelimit_gate.py",
    "tests/test_binance_usdm_error_routing.py",
    "tests/test_binance_usdm_source_guard.py",
    "tests/test_binance_usdm_signed_calls.py",
    "tests/test_binance_probe.py",
    "tests/test_binance_probe_contract.py",
    "tests/test_operator_evidence.py",
    "tests/test_user_data_smoke_dry_run.py",
    "tests/test_user_data_smoke_evidence.py",
    "tests/test_user_data_smoke_cli.py",
    "tests/test_demo_probe_cases.py",
    "tests/test_demo_probe_evidence.py",
    "tests/test_demo_probe_cli.py",
    "tests/test_fake_binance_semantics.py",
    # Decision records and planning inputs the plans promise.
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-O-18-01-table.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-D01-event-types.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DESIGN-REVIEW-event-types.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-03.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-03-smoke.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-TAXONOMY-CODES.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-smoke-limits.toml",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-probe-limits.toml",
    ".planning/phases/18-user-data-stream-error-taxonomy/evidence/18-transport-decision.txt",
)

# Produced by blocking-human steps (live smoke and probe), by plan 18-25 (documents and the
# D055 draft) or by the user (integration). Reported, never required: the gate must run before
# or after those steps, and when the smoke or the probe was postponed.
PHASE18_EVIDENCE: tuple[str, ...] = (
    ".planning/phases/18-user-data-stream-error-taxonomy/evidence/18-smoke-check.txt",
    ".planning/phases/18-user-data-stream-error-taxonomy/evidence/18-probe-check.txt",
    ".planning/phases/18-user-data-stream-error-taxonomy/evidence/18-error-code-page-reread-20261017.txt",
    "tests/fixtures/phase18/recorded_demo/smoke",
    "tests/fixtures/phase18/recorded_demo/probe",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DRAFT-D055-evidence-for-user.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-INTEGRATION.md",
    ".planning/phases/18-user-data-stream-error-taxonomy/18-TRACEABILITY.md",
)


# The planning files below are only required while the phase directory is in the checkout:
# `/gsd-cleanup` archives it and `/gsd-pr-branch` leaves `.planning/` out (review WR-05). The
# code-and-fixture inventory (src, scripts, tests, config) stays a hard requirement.
requires_phase18_planning = pytest.mark.skipif(
    not PHASE_DIR.is_dir(),
    reason="the Phase 18 planning directory is not in this checkout (archived or filtered)",
)


def test_phase18_artifacts_exist() -> None:
    planning_present = PHASE_DIR.is_dir()
    missing = [
        path
        for path in PHASE18_ARTIFACTS
        if not (ROOT / path).exists() and (planning_present or not path.startswith(".planning/"))
    ]
    assert missing == [], f"missing Phase 18 artifacts: {missing}"
    assert len(set(PHASE18_ARTIFACTS)) == len(PHASE18_ARTIFACTS)


def test_phase18_evidence_is_reported_not_required(capsys: pytest.CaptureFixture[str]) -> None:
    present = [path for path in PHASE18_EVIDENCE if (ROOT / path).exists()]
    absent = [path for path in PHASE18_EVIDENCE if not (ROOT / path).exists()]
    print(f"phase 18 evidence present: {present}")
    print(f"phase 18 evidence not (yet) present: {absent}")
    # Presence is only reported, but the list itself is checked (a partition of the list into
    # present and absent is true for any filesystem state, so it asserts nothing; review WR-03).
    assert len(set(PHASE18_EVIDENCE)) == len(PHASE18_EVIDENCE)
    assert not set(PHASE18_EVIDENCE) & set(PHASE18_ARTIFACTS), "optional and required overlap"
    for path in PHASE18_EVIDENCE:
        parts = Path(path).parts
        assert not Path(path).is_absolute() and ".." not in parts, path
        assert path.startswith((".planning/", "tests/fixtures/")), path


# --------------------------------------------------------------------------- #
# Public symbols.
# --------------------------------------------------------------------------- #

PHASE18_SYMBOLS: dict[str, tuple[str, ...]] = {
    "src.adapters.binance_userdata_events": (
        "AccountUpdateEvent",
        "AlgoUpdateEvent",
        "ListenKeyExpiredEvent",
        "OrderUpdateEvent",
        "IgnoredEvent",
        "StreamAnomaly",
        "StreamAnomalyKind",
        "StreamOutcome",
        "parse_stream_message",
        "parse_order_trade_update",
        "parse_algo_update",
        "parse_account_update",
        "parse_listen_key_expired",
        "to_fill_event",
        "unwrap_message",
    ),
    "src.domain.exchange_errors": (
        "ERROR_CODE_TABLE",
        "CodeEntry",
        "ErrorFacts",
        "ExchangeErrorCategory",
        "RateLimitDecision",
        "classify",
        "rate_limit_decision",
        "retry_eligible",
        "safe_mode_eligible",
    ),
    "src.domain.algo_status": (
        "ALGO_STATUS_TABLE",
        "AlgoStatusClass",
        "classify_algo_status",
        "is_known_algo_status",
        "is_protection_confirmed",
    ),
    "src.adapters.binance_errors": ("error_facts_from_exception",),
    "src.adapters.binance_client": (
        "Environment",
        "build_sdk_client",
        "load_api_credentials",
        "parse_environment",
        "assert_endpoint_url",
        "assert_environment",
        "credential_spec_for",
        "SdkClientBundle",
    ),
    "src.adapters.binance_limits": (
        "CANONICAL_KEYS",
        "BinanceLimits",
        "RateLimitPolicy",
        "load_binance_limits",
        "parse_binance_limits",
        "LimitsNotRatified",
    ),
    "src.adapters.binance_clock": (
        "ClockDriftGuard",
        "evaluate_clock_drift",
        "measure_clock_drift",
        "ServerTimeSource",
    ),
    "src.adapters.binance_ratelimit_gate": (
        "RestRateLimitGate",
        "RateLimitBanActive",
        "RateLimitPauseActive",
        "RestGateRefusal",
    ),
    "src.adapters.binance_userdata": (
        "UserDataAdapter",
        "SdkListenKeyPort",
        "SdkUserDataTransport",
        "ListenKeyPort",
        "UserDataTransport",
    ),
    "src.adapters.binance_userdata_supervisor": (
        "UserDataSupervisor",
        "StreamState",
        "StreamSnapshot",
        "stream_is_stale",
    ),
    "src.adapters.binance_userdata_router": (
        "UserDataRouter",
        "FillTotalsTracker",
        "StreamDivergence",
        "ExchangeStateUpdate",
        "OrderStatusHint",
    ),
    "src.adapters.binance_probe": ("BinanceProbeAdapter", "ProbeObservation", "ProbeBanned"),
    "src.domain.stream_records": (
        "ExitEvidence",
        "EvidenceSource",
        "exit_evidence_event",
        "stream_anomaly_event",
    ),
    "src.ops.operator_evidence": (
        "confirm_execute",
        "load_demo_order_limits",
        "write_evidence_atomic",
        "TextScrubber",
        "DemoOrderLimits",
    ),
}


def test_phase18_public_symbols_importable() -> None:
    problems: list[str] = []
    for module_name, names in PHASE18_SYMBOLS.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - the gate reports any import failure by name
            problems.append(f"{module_name}: import failed ({type(exc).__name__})")
            continue
        problems.extend(
            f"{module_name}.{name}: missing" for name in names if not hasattr(module, name)
        )
    assert problems == [], f"Phase 18 public symbols not importable: {problems}"


# --------------------------------------------------------------------------- #
# Requirement to test.
# --------------------------------------------------------------------------- #

# requirement id -> (test file, test function name prefix) pairs.
REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "EXEC-05": (
        ("tests/test_userdata_adapter.py", "test_tracer_sdk_order_trade_update"),
        ("tests/test_userdata_supervisor.py", "test_tracer_start_live_close_unknown"),
        ("tests/test_userdata_replay.py", "test_every_ordering_of_duplicates_and_reorders"),
        ("tests/test_userdata_router.py", "test_fill_total_mismatch_journals"),
        ("tests/test_userdata_events.py", "test_trade_frame_parses_to_a_typed_order_update"),
        ("tests/test_userdata_parsers.py", "test_algo_update_frame_parses_to_a_typed_event"),
        ("tests/test_userdata_fixtures.py", "test_fixture_file_equals_its_builder"),
        ("tests/test_userdata_contract.py", "test_fakes_mirror_the_installed_sdk_surface"),
        ("tests/test_userdata_recorded_frames.py", "test_every_recorded_frame_parses"),
        ("tests/test_execution_partials.py", "test_replayed_fills_count_exactly_once"),
    ),
    "EXEC-01": (
        ("tests/test_algo_status.py", "test_table_keys_equal_the_vocabulary"),
        ("tests/test_algo_status.py", "test_attach_behavior_unchanged_from_new_only_allow_list"),
        # Rewritten by Phase 19 (plans 19-15 and 19-16): attach places no stop, and a rejected
        # protective stop is decided by the coordinator (B5, close required).
        (
            "tests/test_execution_attach.py",
            "test_absent_stop_holds_without_placing_a_stop_or_a_take_profit",
        ),
        (
            "tests/test_exchange_error_rejections.py",
            "test_tracer_1106_on_the_protective_stop_after_a_fill_goes_close_required",
        ),
        ("tests/test_binance_usdm_error_routing.py", "test_placement_calls_the_sdk_exactly_once"),
        (
            "tests/test_binance_usdm_signed_calls.py",
            "test_protective_blocked_by_pause_or_ban_surfaces_unprotected_position",
        ),
        ("tests/test_binance_probe.py", "test_query_algo_order_missing_returns_the_exact_code"),
        ("tests/test_demo_probe_cases.py", "test_case_order_is_the_d16_order_of_risk"),
    ),
    "EXEC-02": (
        ("tests/test_exchange_errors.py", "test_sdk_2013_on_query_is_order_absent"),
        ("tests/test_exchange_errors.py", "test_normalizer_never_reads_message_text"),
        (
            "tests/test_exchange_error_rejections.py",
            "test_each_owner_code_classifies_rejected_definitive_on_placement_only",
        ),
        ("tests/test_sdk_error_mapping_contract.py", "test_tracer_sdk_bad_request_2013"),
        ("tests/test_adapter_not_found_mapping.py", "test_algo_query_maps_not_found_codes"),
        (
            "tests/test_persistence_exit_evidence_pg.py",
            "test_unknown_exit_without_evidence_raises_and_writes_nothing",
        ),
        ("tests/test_stream_records.py", "test_evidence_sources_are_exactly"),
        ("tests/test_binance_ratelimit_gate.py", "test_418_without_retry_after_bans"),
        ("tests/test_fake_binance_semantics.py", "test_duplicate_open_client_order_id_raises"),
    ),
    "OPS-02": (
        ("tests/test_binance_client_config.py", "test_parse_environment_without_a_value_raises"),
        (
            "tests/test_binance_client_config.py",
            "test_sdk_client_is_constructed_only_at_the_allowed_sites",
        ),
        (
            "tests/test_binance_secret_redaction.py",
            "test_credentials_load_from_environment_variables",
        ),
        ("tests/test_binance_limits.py", "test_tracer_file_to_limits_to_verdict_to_guard"),
        (
            "tests/test_binance_limits_ratified_file.py",
            "test_the_file_has_exactly_the_record_values",
        ),
        ("tests/test_clock_drift.py", "test_measurement_reads_the_clock_around_exactly_one"),
        (
            "tests/test_no_unratified_defaults.py",
            "test_no_canonical_key_gets_a_numeric_constant_in_src_or_scripts",
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


def test_phase18_requirement_tests_exist() -> None:
    problems: list[str] = []
    for requirement, pairs in REQUIREMENT_TESTS.items():
        for relative, prefix in pairs:
            path = ROOT / relative
            if not path.exists():
                problems.append(f"{requirement}: {relative} does not exist")
            elif not any(name.startswith(prefix) for name in _test_function_names(path)):
                problems.append(f"{requirement}: {relative} defines no test starting {prefix!r}")
    assert problems == [], f"requirement-to-test pairs missing: {problems}"
    assert set(REQUIREMENT_TESTS) == {"EXEC-01", "EXEC-02", "EXEC-05", "OPS-02"}


# --------------------------------------------------------------------------- #
# Structural invariants (nine).
# --------------------------------------------------------------------------- #

PURE_MODULES: tuple[str, ...] = (
    "src/domain/exchange_errors.py",
    "src/domain/algo_status.py",
    "src/domain/stream_records.py",
    "src/adapters/binance_userdata_events.py",
    "src/adapters/binance_limits.py",
    "src/adapters/binance_clock.py",
    "src/adapters/binance_ratelimit_gate.py",
)
PURE_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "binance*",
    "requests",
    "aiohttp",
    "sqlalchemy",
    "pydantic",
    "polars",
)
SUPERVISOR_PATH = ROOT / "src" / "adapters" / "binance_userdata_supervisor.py"
SUPERVISOR_MODULE = "src.adapters.binance_userdata_supervisor"
ADAPTER_PATH = ROOT / "src" / "adapters" / "binance_usdm.py"
MANAGER_PATH = ROOT / "src" / "execution" / "manager.py"


def test_invariant_1_one_sdk_construction_path() -> None:
    client_config_tests.test_sdk_client_is_constructed_only_at_the_allowed_sites()


def test_invariant_2_no_src_module_imports_the_supervisor() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "src").rglob("*.py"))
        if path != SUPERVISOR_PATH
        and any(
            name == SUPERVISOR_MODULE or name.startswith(SUPERVISOR_MODULE + ".")
            for name in module_imports(path)
        )
    ]
    assert offenders == [], "Phase 19 wires the supervisor; Phase 18 must not"


@pytest.mark.parametrize("relative", PURE_MODULES)
def test_invariant_3_pure_modules_have_no_sdk_float_or_clock(relative: str) -> None:
    path = ROOT / relative
    assert forbidden_imports(path, PURE_FORBIDDEN_IMPORTS) == []
    assert float_constructor_calls(path) == []
    assert wall_clock_calls(path) == []


def test_invariant_4_the_ratified_limits_file_loads() -> None:
    from src.adapters.binance_limits import CANONICAL_KEYS, load_binance_limits

    limits = load_binance_limits(ROOT / "config" / "binance" / "binance-limits-v1.toml")
    assert limits is not None
    assert sum(len(keys) for keys in CANONICAL_KEYS.values()) == 27
    ratified_file_tests.test_the_real_loader_accepts_the_ratified_file_with_the_record_values()


def test_invariant_5_no_unratified_default_in_src_or_scripts() -> None:
    # Phase 19 adds the execution-limit keys of D-07/D-13 (30 -> 34), then entry_unknown_grace_ms
    # and emergency_close_poll_timeout_ms from the review fixes (34 -> 36), then
    # max_last_price_age_ms from quick task 261020-l4p (36 -> 37).
    assert len(unratified_tests.GUARDED_NAMES) == 37
    assert unratified_tests.ALLOW_LIST == {}
    unratified_tests.test_no_canonical_key_gets_a_numeric_constant_in_src_or_scripts()
    unratified_tests.test_no_production_file_imports_the_test_only_limits()


def test_invariant_6_placement_is_single_attempt_and_decides_on_no_message_text() -> None:
    adapter_source = ADAPTER_PATH.read_text(encoding="utf-8")
    assert source_guard_tests.placement_retry_constructs(adapter_source) == []
    assert source_guard_tests.message_text_reads(adapter_source) == []
    manager_source = MANAGER_PATH.read_text(encoding="utf-8")
    assert source_guard_tests.message_text_reads(manager_source) == []
    assert source_guard_tests.removed_names_present(adapter_source) == []


def test_invariant_7_the_decisions_row_pins_the_limits_file() -> None:
    ratified_file_tests.test_decisions_row_pins_the_limits_file_hash()


def test_invariant_8_d055_stays_open() -> None:
    lines = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines()
    d055 = [line for line in lines if line.startswith("| D055 |")]
    assert len(d055) == 1
    assert "stays OPEN" in d055[0], "D055 execution model must still be recorded as OPEN"
    phase18_row = ratified_file_tests._phase18_row()
    assert "OPEN" in phase18_row
    lowered = phase18_row.lower()
    for claim in ("closes d055", "d055 is closed", "d055 closed", "closing d055"):
        assert claim not in lowered, f"the Phase 18 row claims to close D055: {claim!r}"


@pytest.mark.parametrize(
    ("module_name", "class_name", "required"),
    [
        ("src.adapters.binance_usdm", "BinanceUsdmAdapter", False),
        ("src.adapters.binance_public", "BinancePublicMarketData", False),
        ("src.adapters.binance_userdata", "SdkListenKeyPort", True),
        ("src.adapters.binance_probe", "BinanceProbeAdapter", True),
        ("src.adapters.binance_userdata_supervisor", "UserDataSupervisor", True),
    ],
)
def test_invariant_9_every_rest_holder_takes_the_shared_gate(
    module_name: str, class_name: str, required: bool
) -> None:
    holder = getattr(importlib.import_module(module_name), class_name)
    parameter = inspect.signature(holder.__init__).parameters.get("rest_gate")
    assert parameter is not None, f"{class_name} has no rest_gate parameter"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY or not required
    if required:
        assert parameter.default is inspect.Parameter.empty, f"{class_name} must require a gate"
    else:
        assert parameter.default is None


# --------------------------------------------------------------------------- #
# The traceability document (written by plan 18-22 Task 2).
# --------------------------------------------------------------------------- #

TRACEABILITY = PHASE_DIR / "18-TRACEABILITY.md"
TRACEABILITY_SECTIONS: tuple[str, ...] = (
    "## 1. Goal and ROADMAP success criteria",
    "## 2. Requirements and evidence level",
    "## 3. CONTEXT decisions D-01 to D-22",
    "## 4. Folded inherited items",
    "## 5. Owner-only items",
    "## 6. Research findings, pitfalls and the UNVERIFIED register",
    "## 7. Deferred ideas confirmed not built",
    "## Gate run",
    "## Merge check against develop",
)
_NAMED_TEST = re.compile(r"`(test_[a-z0-9_]+\.py)::(test_[a-z0-9_]+)`")


@requires_phase18_planning
def test_phase18_traceability_has_every_requirement_and_decision_row() -> None:
    text = TRACEABILITY.read_text(encoding="utf-8")
    missing_sections = [s for s in TRACEABILITY_SECTIONS if s not in text]
    assert missing_sections == [], f"traceability sections missing: {missing_sections}"
    lines = text.splitlines()
    for requirement in REQUIREMENT_TESTS:
        assert any(line.startswith(f"| {requirement} ") for line in lines), requirement
    for number in range(1, 23):
        marker = f"| D-{number:02d} "
        assert any(line.startswith(marker) for line in lines), f"decision D-{number:02d}"
    for item in ("G3-001", "G2-028", "G2-029", "G3-009", "G4-034", "G4-043", "D055 probe cases"):
        assert any(line.startswith(f"| {item}") for line in lines), item
    for owner in ("O-18-01", "O-18-02", "O-18-03", "O-18-04"):
        assert any(line.startswith(f"| {owner} ") for line in lines), owner
    assert not re.search(r"\|\s*MISSING\s*\|", text), "a traceability row says MISSING"
    assert "D055" in text and "OPEN" in text


@requires_phase18_planning
def test_phase18_traceability_names_only_existing_tests() -> None:
    text = TRACEABILITY.read_text(encoding="utf-8")
    named = _NAMED_TEST.findall(text)
    assert named, "the traceability document names no test"
    problems = [
        f"{filename}::{name}"
        for filename, name in sorted(set(named))
        if not (ROOT / "tests" / filename).exists()
        or name not in _test_function_names(ROOT / "tests" / filename)
    ]
    assert problems == [], f"traceability names tests that do not exist: {problems}"
