"""Phase 24 gate (plan 24-32): the structural invariants of the live runtime composition.

This file asserts, against the real tree and without any network, Binance, Telegram or database:

- the inventory: the `src/live` modules are exactly the pinned set (a new module must update this
  gate on purpose), and the other Phase 24 files exist;
- purity and import direction (D-04, D-05): no `float(...)` constructor in `src/live`, the wall
  clock is read at exactly one allow-listed CLI edge (its size is pinned), `src/live` imports
  neither the paper runtime, tests nor scripts, and no lower layer imports `src.live`;
- the migration head is `0015_order_event_time` (D-10) and live placement is still disabled;
- each Phase 24 requirement has its named automated tests (`REQUIREMENT_TESTS`, resolved with
  `ast`, never imported or run);
- every CONTEXT decision D-01 to D-35 maps to the plan that built it and to at least one existing
  test function or document anchor (`DECISION_EVIDENCE`); a decision with neither fails by id;
- the Phase 24 decision rows D098 to D107 exist once each and D097 is Accepted;
- the deferred register (`24-DEFERRED.md`) gives every inherited item of the ROADMAP Phase 24
  entry, every id the plan names from earlier phases and every 20-DEFERRED row assigned to
  Phase 24 a status (D-35).

A failure message names the missing path, symbol, test or id. Nothing here changes behavior and
nothing here claims a requirement complete or a Demo or host result: EXEC-01, EXEC-02 and OPS-02
stay Pending until the owner's evidence (plan 24-33), and `LIVE_ORDERS_DISABLED` stays.

Evidence label: executed structural tests. The Alembic head is read from the script directory.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = ROOT / ".planning" / "phases" / "24-live-runtime-composition-demo"

# --------------------------------------------------------------------------- #
# The inventory.
# --------------------------------------------------------------------------- #

#: Every module of the `src/live` package. A module added later must be added here on purpose.
LIVE_MODULES: frozenset[str] = frozenset(
    {
        "__init__",
        "alerts",
        "approval_sender",
        "commission",
        "config",
        "enablement",
        "exchange",
        "execution_service",
        "feeds",
        "health",
        "operator",
        "order_index",
        "reconcile",
        "reservation_release",
        "risk_inputs",
        "runtime",
        "scheduled_cancel",
        "scheduler",
        "signal_source",
        "smoke_injection",
        "startup",
        "stream",
        "stream_persistence",
        "telegram_runner",
        "wiring",
        "wiring_parts",
    }
)

#: Other files Phase 24 added (paths relative to the repository root).
PHASE24_OTHER_FILES: tuple[str, ...] = (
    "src/ops/store_executor.py",
    "src/adapters/code_version.py",
    "src/db/alembic/versions/0015_order_event_time.py",
    "scripts/demo_rehearsal.py",
    "scripts/demo_clear.py",
    "deploy/heartbeat.sh",
    "tests/support/live_rig.py",
    "tests/support/live_composed_rig.py",
    "tests/support/live_pg_rig.py",
    "tests/support/live_store_set.py",
    "tests/support/live_smoke_env.py",
    ".env.live.example",
    ".env.paper.example",
    ".env.backup.example",
    ".planning/phases/24-live-runtime-composition-demo/24-OWNER-RUNBOOK.md",
    ".planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md",
)

#: The CLI edge is the only `src/live` module that reads the process clock, once.
WALL_CLOCK_EDGE: dict[str, int] = {"runtime.py": 1}

LIVE_FORBIDDEN_IMPORTS: tuple[str, ...] = ("src.paper.runtime", "tests", "scripts")

#: These layers must never import `src.live` (the live package sits above them).
PURE_LAYERS: tuple[str, ...] = ("core", "risk", "domain")


def _live_files() -> list[Path]:
    return sorted((ROOT / "src" / "live").glob("*.py"))


def test_the_src_live_inventory_is_exactly_the_pinned_set() -> None:
    found = {path.stem for path in _live_files()}
    assert found == LIVE_MODULES, (
        f"src/live modules differ from the gate: missing {sorted(LIVE_MODULES - found)}, "
        f"unlisted {sorted(found - LIVE_MODULES)}"
    )


def test_the_other_phase24_files_exist() -> None:
    missing = [relative for relative in PHASE24_OTHER_FILES if not (ROOT / relative).is_file()]
    assert missing == [], f"missing Phase 24 files: {missing}"


@pytest.mark.parametrize("path", _live_files(), ids=lambda p: p.name)
def test_invariant_1_src_live_builds_no_float(path: Path) -> None:
    assert float_constructor_calls(path) == [], f"{path.name} builds a float"


@pytest.mark.parametrize("path", _live_files(), ids=lambda p: p.name)
def test_invariant_2_the_wall_clock_is_read_only_at_the_pinned_cli_edge(path: Path) -> None:
    calls = wall_clock_calls(path)
    allowed = WALL_CLOCK_EDGE.get(path.name, 0)
    assert len(calls) == allowed, (
        f"{path.name} reads the wall clock {len(calls)} time(s) ({calls}); "
        f"the gate allows {allowed}"
    )


@pytest.mark.parametrize("path", _live_files(), ids=lambda p: p.name)
def test_invariant_3_src_live_imports_neither_the_paper_runtime_tests_nor_scripts(
    path: Path,
) -> None:
    assert forbidden_imports(path, LIVE_FORBIDDEN_IMPORTS) == [], path.name


def test_invariant_3b_the_layers_below_src_live_import_nothing_from_it() -> None:
    from tests.test_live_ast_guards import imports_of_src_live, lower_layer_files

    pure = sorted(p for layer in PURE_LAYERS for p in (ROOT / "src" / layer).rglob("*.py"))
    assert len(pure) > 20, "the core, risk and domain glob found too few files"
    assert imports_of_src_live(pure) == []
    lower = lower_layer_files()
    assert len(lower) > 100, "the lower-layer glob found too few files"
    assert imports_of_src_live(lower) == []


def test_invariant_4_the_migration_head_is_0015_order_event_time() -> None:
    from tests.pg_support import alembic_head_revision

    assert alembic_head_revision() == "0015_order_event_time", (
        "Phase 24 (D-10, D100) ends at 0015; a later migration must update this gate on purpose"
    )


def test_invariant_5_live_placement_is_still_disabled() -> None:
    from src.execution.enablement import LiveEnablementController

    class _Journal:
        def record(self, event: object) -> None:  # pragma: no cover - never reached
            raise AssertionError("a default controller must not journal")

    controller = LiveEnablementController(journal=_Journal())
    assert controller.is_disabled is True, "Phase 24 must not enable live placement"
    verdict = controller.guard_placement(plan_hash="0" * 64)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "DISABLED"


# --------------------------------------------------------------------------- #
# Requirement -> named tests (resolved with ast, never imported).
# --------------------------------------------------------------------------- #

REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "APRV-01": (
        (
            "tests/test_live_approval_sender.py",
            "test_a_demo_request_becomes_one_card_with_its_money_sent_once",
        ),
        ("tests/test_live_approval_sender.py", "test_missing_money_issues_nothing"),
        (
            "tests/test_paper_shadow_money.py",
            "test_d19_a_v2_alert_stores_the_money_on_both_rows_and_shows_the_money_rows",
        ),
        (
            "tests/test_live_replay_restart.py",
            "test_a_replayed_approve_keeps_one_decision_and_places_nothing",
        ),
    ),
    "EXEC-01": (
        (
            "tests/test_live_composed_tracer.py",
            "test_confirm_places_one_entry_and_its_stream_fill_ends_in_a_protected_position",
        ),
        (
            "tests/test_live_demo_smoke.py",
            "test_one_entry_is_placed_gtd_limit_with_no_entry_time_stop_and_no_replay_places",
        ),
        (
            "tests/test_live_risk_input_producer.py",
            "test_for_plan_returns_complete_inputs_from_the_account",
        ),
        ("tests/test_live_wiring.py", "test_the_completed_wiring_has_no_broken_link"),
    ),
    "EXEC-02": (
        (
            "tests/test_live_stream_to_protection.py",
            "test_a_fill_frame_at_the_transport_edge_ends_in_a_rest_confirmed_stop",
        ),
        (
            "tests/test_live_reconcile_wiring.py",
            "test_a_protected_position_reconciles_clean_through_the_composed_loop",
        ),
        (
            "tests/test_live_reconcile_wiring.py",
            "test_a_local_intent_the_exchange_does_not_show_enters_safe_mode_and_alerts",
        ),
        (
            "tests/test_live_safe_mode_drill.py",
            "test_the_drill_enter_blocked_refused_exit_operator_exit_entry_allowed",
        ),
    ),
    "EXEC-03": (
        (
            "tests/test_live_replay_restart.py",
            "test_a_replayed_confirm_places_exactly_one_entry_with_the_derived_client_id",
        ),
        (
            "tests/test_live_replay_restart.py",
            "test_two_concurrent_confirm_presses_lead_to_exactly_one_place_entry",
        ),
        (
            "tests/test_live_replay_restart.py",
            "test_a_restart_after_an_ambiguous_entry_stays_unknown_and_is_never_re_sent",
        ),
        (
            "tests/test_live_replay_restart_pg.py",
            "test_two_confirm_presses_on_two_processes_place_exactly_once",
        ),
    ),
    "OPS-02": (
        (
            "tests/test_live_compose_env_split.py",
            "test_compose_gives_the_binance_names_to_the_live_service_only",
        ),
        (
            "tests/test_live_config_refusal.py",
            "test_demo_with_live_credentials_present_is_refused_by_name",
        ),
        (
            "tests/test_live_demo_smoke.py",
            "test_no_secret_reaches_the_evidence_file_or_stdout",
        ),
    ),
    "OPS-03": (
        (
            "tests/test_live_start_sequence.py",
            "test_the_steps_run_in_the_d08_order_each_journaled_and_enable_is_last",
        ),
        (
            "tests/test_live_restart_rehydrate.py",
            "test_a_restart_rebuilds_safe_mode_the_resting_entry_and_its_index_entry",
        ),
        (
            "tests/test_live_restart_rehydrate.py",
            "test_outstanding_confirms_expire_with_runtime_restart_and_a_press_places_nothing",
        ),
    ),
    "OPS-04": (
        (
            "tests/test_live_runtime_cli.py",
            "test_healthcheck_prints_one_json_object_and_exits_zero_when_live",
        ),
        (
            "tests/test_live_runtime_cli.py",
            "test_healthcheck_never_fails_for_a_missing_revision",
        ),
        (
            "tests/test_dockerfile_revision_stamp.py",
            "test_the_runtime_stage_declares_the_revision_argument_without_a_default",
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


def _missing_pairs(pairs: tuple[tuple[str, str], ...], label: str) -> list[str]:
    problems: list[str] = []
    for relative, name in pairs:
        path = ROOT / relative
        if not path.exists():
            problems.append(f"{label}: {relative} does not exist")
        elif name not in _test_function_names(path):
            problems.append(f"{label}: {relative} defines no test {name!r}")
    return problems


def test_invariant_6_each_phase24_requirement_has_at_least_two_named_tests() -> None:
    assert set(REQUIREMENT_TESTS) == {
        "APRV-01",
        "EXEC-01",
        "EXEC-02",
        "EXEC-03",
        "OPS-02",
        "OPS-03",
        "OPS-04",
    }
    problems: list[str] = []
    for requirement, pairs in REQUIREMENT_TESTS.items():
        assert len(pairs) >= 2, f"{requirement} names fewer than two tests"
        problems.extend(_missing_pairs(pairs, requirement))
    assert problems == [], f"requirement-to-test pairs missing: {problems}"


def test_invariant_6b_every_requirement_name_is_a_known_requirement() -> None:
    planning = ROOT / ".planning" / "REQUIREMENTS.md"
    if not planning.is_file():
        pytest.skip("REQUIREMENTS.md is not in this checkout (filtered)")
    text = planning.read_text(encoding="utf-8")
    for requirement in REQUIREMENT_TESTS:
        assert f"**{requirement}**" in text, requirement


# --------------------------------------------------------------------------- #
# The decision table: every CONTEXT decision D-01..D-35 to its plan and its evidence.
# An evidence item is ("test", path, function) or ("doc", path, anchor text).
# --------------------------------------------------------------------------- #

Evidence = tuple[str, str, str]


def _t(path: str, name: str) -> Evidence:
    return ("test", path, name)


def _d(path: str, anchor: str) -> Evidence:
    return ("doc", path, anchor)


DECISION_EVIDENCE: dict[str, tuple[str, tuple[Evidence, ...]]] = {
    "D-01": (
        "24-04, 24-27",
        (
            _t("tests/test_live_wiring.py", "test_the_scheduler_specs_are_exactly_the_listed_set"),
            _d("docs/DECISIONS.md", "| D098 |"),
        ),
    ),
    "D-02": (
        "24-11",
        (
            _t(
                "tests/test_live_config_refusal.py",
                "test_live_mode_is_refused_while_live_orders_are_disabled",
            ),
        ),
    ),
    "D-03": (
        "24-11, 24-35",
        (
            _t("tests/test_live_runtime_cli.py", "test_the_two_probes_cannot_be_combined"),
            _t(
                "tests/test_live_compose_service.py",
                "test_the_live_service_with_an_empty_env_file_holds_instead_of_crash_looping",
            ),
        ),
    ),
    "D-04": (
        "24-27",
        (
            _t("tests/test_live_wiring.py", "test_the_completed_wiring_has_no_broken_link"),
            _t(
                "tests/test_live_wiring.py",
                "test_a_completed_assembly_returns_the_same_wiring_twice",
            ),
        ),
    ),
    "D-05": (
        "24-27",
        (
            _t("tests/test_live_wiring.py", "test_the_completed_wiring_has_no_broken_link"),
            _t(
                "tests/test_live_composed_tracer.py",
                "test_the_composed_wiring_has_no_broken_link_on_the_in_memory_stores",
            ),
        ),
    ),
    "D-06": (
        "24-12",
        (
            _t(
                "tests/test_live_exchange_wiring.py",
                "test_a_fresh_bundle_refuses_place_entry_before_any_sdk_call",
            ),
            _t(
                "tests/test_live_wiring.py",
                "test_the_adapter_drift_guard_is_present_and_a_never_measured_guard_blocks",
            ),
        ),
    ),
    "D-07": (
        "24-13",
        (
            _t(
                "tests/test_live_alerts_wiring.py",
                "test_a_safe_mode_entry_of_the_composed_controller_reaches_the_bot_journal_first",
            ),
            _t(
                "tests/test_live_wiring.py",
                "test_the_sink_is_the_one_journal_first_sink_everywhere",
            ),
        ),
    ),
    "D-08": (
        "24-26, 24-37",
        (
            _t(
                "tests/test_live_start_sequence.py",
                "test_the_steps_run_in_the_d08_order_each_journaled_and_enable_is_last",
            ),
            _t(
                "tests/test_live_start_sequence.py",
                "test_the_stream_is_up_when_the_first_reconcile_tick_judges_the_feed",
            ),
        ),
    ),
    "D-09": (
        "24-26, 24-28",
        (
            _t(
                "tests/test_live_restart_rehydrate.py",
                "test_outstanding_confirms_expire_with_runtime_restart_and_a_press_places_nothing",
            ),
            _t(
                "tests/test_live_replay_restart.py",
                "test_a_restart_after_an_ambiguous_entry_stays_unknown_and_is_never_re_sent",
            ),
        ),
    ),
    "D-10": (
        "24-07, 24-19",
        (
            _t("tests/test_persistence_event_time_pg.py", "test_a_new_order_has_no_event_time"),
            _t(
                "tests/test_live_stream_persistence_pg.py",
                "test_order_events_persist_in_order_and_a_late_event_changes_nothing",
            ),
        ),
    ),
    "D-11": (
        "24-10",
        (
            _t(
                "tests/test_live_scheduler.py",
                "test_a_failing_task_does_not_stop_the_other_and_recovers",
            ),
        ),
    ),
    "D-12": (
        "24-06, 24-10",
        (
            _t(
                "tests/test_live_limits_relationships.py",
                "test_the_shipped_limits_satisfy_every_relationship",
            ),
            _t("tests/test_live_wiring.py", "test_every_interval_comes_from_the_cadences"),
        ),
    ),
    "D-13": (
        "24-21",
        (
            _t(
                "tests/test_live_scheduled_cancel.py",
                "test_an_unfilled_entry_past_its_plan_expiry_is_cancelled_by_its_client_id",
            ),
            _t(
                "tests/test_live_scheduled_cancel.py",
                "test_a_partly_filled_entry_is_not_cancelled_and_is_journaled",
            ),
        ),
    ),
    "D-14": (
        "24-18, 24-19",
        (
            _t(
                "tests/test_live_stream_to_protection.py",
                "test_a_fill_frame_at_the_transport_edge_ends_in_a_rest_confirmed_stop",
            ),
            _t(
                "tests/test_live_stream_to_protection.py",
                "test_an_unknown_client_id_is_a_divergence_and_never_a_coordinator_input",
            ),
        ),
    ),
    "D-15": (
        "24-12",
        (
            _t(
                "tests/test_live_exchange_wiring.py",
                "test_every_holder_holds_the_one_gate_instance",
            ),
            _t(
                "tests/test_live_exchange_wiring.py",
                "test_there_is_one_gate_construction_site_under_src_live",
            ),
        ),
    ),
    "D-16": (
        "24-29",
        (
            _t(
                "tests/test_live_demo_smoke.py",
                "test_the_evidence_records_every_field_phase_24_needs_from_demo",
            ),
        ),
    ),
    "D-17": (
        "24-17",
        (
            _t(
                "tests/test_live_telegram_runner.py",
                "test_exactly_one_handler_and_it_is_on_callback_with_the_user_ids",
            ),
            _t(
                "tests/test_live_telegram_runner.py",
                "test_the_runner_source_never_calls_dispatch_callback_and_builds_no_application",
            ),
        ),
    ),
    "D-18": (
        "24-14",
        (
            _t(
                "tests/test_live_approval_sender.py",
                "test_a_demo_request_becomes_one_card_with_its_money_sent_once",
            ),
            _t(
                "tests/test_live_approval_sender.py",
                "test_the_tracer_card_can_only_be_approved_by_a_press",
            ),
        ),
    ),
    "D-19": (
        "24-09",
        (
            _t(
                "tests/test_paper_shadow_money.py",
                "test_d19_a_v2_alert_stores_the_money_on_both_rows_and_shows_the_money_rows",
            ),
            _t(
                "tests/test_paper_shadow_money.py",
                "test_d19_the_money_block_comes_from_the_sizing_not_from_a_recomputation",
            ),
        ),
    ),
    "D-20": (
        "24-28",
        (
            _t(
                "tests/test_live_replay_restart.py",
                "test_two_concurrent_confirm_presses_lead_to_exactly_one_place_entry",
            ),
            _t(
                "tests/test_live_replay_restart_pg.py",
                "test_two_confirm_presses_on_two_processes_place_exactly_once",
            ),
        ),
    ),
    "D-21": (
        "24-16",
        (
            _t(
                "tests/test_live_risk_input_producer.py",
                "test_for_plan_returns_complete_inputs_from_the_account",
            ),
            _t(
                "tests/test_live_risk_input_producer.py",
                "test_each_missing_or_stale_input_refuses_and_sends_nothing",
            ),
        ),
    ),
    "D-22": (
        "24-15",
        (
            _t("tests/test_live_commission_refresh.py", "test_never_refreshed_symbol_is_no_trade"),
            _t(
                "tests/test_live_commission_refresh.py",
                "test_reading_older_than_the_ttl_is_no_trade",
            ),
        ),
    ),
    "D-23": (
        "24-29",
        (
            _t(
                "tests/test_live_demo_smoke.py",
                "test_the_evidence_records_every_field_phase_24_needs_from_demo",
            ),
            _d("src/analytics/live_outcomes.py", "LIVE_NET_PNL_SEMANTICS_VERIFIED"),
        ),
    ),
    "D-24": (
        "24-16",
        (
            _t(
                "tests/test_live_liquidation_and_tp.py",
                "test_the_built_watch_carries_the_owner_policy_close_position",
            ),
            _t(
                "tests/test_live_liquidation_and_tp.py",
                "test_a_failed_post_fill_check_closes_through_the_coordinator_and_alerts",
            ),
        ),
    ),
    "D-25": (
        "24-05",
        (
            _t(
                "tests/test_store_executor.py",
                "test_concurrent_writes_complete_in_submission_order_on_one_writer_thread",
            ),
            _d("docs/DECISIONS.md", "| D099 |"),
        ),
    ),
    "D-26": (
        "24-22",
        (
            _t(
                "tests/test_live_health.py",
                "test_the_producer_emits_exactly_the_ten_names_in_order",
            ),
            _t(
                "tests/test_live_health.py",
                "test_demo_with_the_flag_is_ok_with_exactly_the_candle_check_degraded",
            ),
        ),
    ),
    "D-27": (
        "24-22",
        (
            _t(
                "tests/test_live_enablement_wiring.py",
                "test_a_stale_mark_price_refuses_the_enable_and_names_the_check",
            ),
            _t("tests/test_live_health.py", "test_a_stale_mark_price_fails_market_feed_freshness"),
        ),
    ),
    "D-28": (
        "24-22",
        (
            _t(
                "tests/test_live_enablement_wiring.py",
                "test_an_unevaluated_or_terminal_kill_gate_refuses_the_enable",
            ),
            _t("tests/test_live_enablement_wiring.py", "test_a_second_enable_changes_nothing"),
        ),
    ),
    "D-29": (
        "24-30, 24-36",
        (
            _t(
                "tests/test_live_compose_env_split.py",
                "test_compose_gives_the_binance_names_to_the_live_service_only",
            ),
            _t(
                "tests/test_live_compose_env_split.py",
                "test_each_services_environment_is_inside_its_allow_list",
            ),
        ),
    ),
    "D-30": (
        "24-24",
        (
            _t(
                "tests/test_deploy_heartbeat.py",
                "test_the_live_target_runs_only_the_liveness_probe_and_sends_one_ping",
            ),
            _t(
                "tests/test_deploy_heartbeat.py",
                "test_the_paper_target_runs_only_the_liveness_probe_and_sends_one_ping",
            ),
        ),
    ),
    "D-31": (
        "24-11, 24-25",
        (
            _t(
                "tests/test_live_runtime_cli.py",
                "test_healthcheck_prints_one_json_object_and_exits_zero_when_live",
            ),
            _t(
                "tests/test_dockerfile_revision_stamp.py",
                "test_the_runtime_stage_declares_the_revision_argument_without_a_default",
            ),
        ),
    ),
    "D-32": (
        "24-33",
        (
            _d(
                ".planning/phases/24-live-runtime-composition-demo/24-OWNER-RUNBOOK.md",
                "NOT_OBSERVED",
            ),
            _d("docs/operations/RUNBOOK.md", "src.live.runtime"),
        ),
    ),
    "D-33": (
        "24-29",
        (
            _t(
                "tests/test_live_demo_smoke.py",
                "test_the_whole_sequence_runs_on_the_composed_process_and_is_synthetic",
            ),
            _t(
                "tests/test_live_demo_smoke.py",
                "test_the_executed_run_uses_the_admitted_environment_and_writes_an_evidence_file",
            ),
        ),
    ),
    "D-34": (
        "24-21, 24-34",
        (
            _t(
                "tests/test_live_scheduled_cancel.py",
                "test_the_cancel_leaves_no_algo_order_untouched_in_the_book",
            ),
            _t(
                "tests/test_protection_cancel_lag.py",
                "test_a_lagging_by_id_query_after_the_cancel_is_a_success",
            ),
            _d("docs/DECISIONS.md", "| D107 |"),
        ),
    ),
    "D-35": (
        "24-02, 24-32",
        (
            _t(
                "tests/test_phase23_gate.py",
                "test_invariant_5h_the_two_phase24_promoted_codes_are_enum_rows_of_91_not_93",
            ),
            _d(
                ".planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md",
                "| P20-DEFERRED |",
            ),
        ),
    ),
}


def test_invariant_7_the_decision_table_names_every_context_decision() -> None:
    expected = {f"D-{number:02d}" for number in range(1, 36)}
    assert set(DECISION_EVIDENCE) == expected, (
        f"decision table ids differ: {sorted(expected ^ set(DECISION_EVIDENCE))}"
    )
    context = (PHASE_DIR / "24-CONTEXT.md").read_text(encoding="utf-8")
    for decision in sorted(expected):
        assert f"**{decision}:**" in context, f"{decision} is not a CONTEXT decision"


def test_invariant_7b_every_decision_has_a_plan_and_existing_evidence() -> None:
    problems: list[str] = []
    for decision, (plans, items) in sorted(DECISION_EVIDENCE.items()):
        if not plans.strip() or not items:
            problems.append(f"{decision}: no plan or no evidence")
            continue
        for kind, relative, needle in items:
            path = ROOT / relative
            if not path.is_file():
                problems.append(f"{decision}: {relative} does not exist")
            elif kind == "test":
                if needle not in _test_function_names(path):
                    problems.append(f"{decision}: {relative} defines no test {needle!r}")
            elif needle not in path.read_text(encoding="utf-8"):
                problems.append(f"{decision}: {relative} does not contain {needle!r}")
    assert problems == [], f"decision evidence missing: {problems}"


def test_invariant_7c_the_phase24_decision_rows_exist_once_and_d097_is_accepted() -> None:
    rows = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines()
    for number in range(98, 108):
        found = [line for line in rows if line.startswith(f"| D{number:03d} |")]
        assert len(found) == 1, f"DECISIONS must carry exactly one D{number:03d} row"
    d097 = [line for line in rows if line.startswith("| D097 |")]
    assert len(d097) == 1 and "| Accepted" in d097[0], "D097 must be Accepted (owner, 2026-11-07)"
    d107 = next(line for line in rows if line.startswith("| D107 |"))
    assert "Provisional" in d107, "D107 records defaults the owner was not asked: Provisional"


# --------------------------------------------------------------------------- #
# The deferred register: a status for every inherited item (D-35).
# --------------------------------------------------------------------------- #

REGISTER = PHASE_DIR / "24-DEFERRED.md"
STATUS_WORDS = ("CLOSED", "OWNER", "DEFERRED", "ACCEPTED")

#: Ids the plan names from earlier ROADMAP sections: Phase 24 owns them, the Phase 24 entry
#: does not list them.
EARLIER_SECTION_IDS: tuple[str, ...] = ("G4-034", "G4-043", "G2-019", "T-05", "T-06")


def _roadmap_inherited_ids() -> list[str]:
    text = (ROOT / ".planning" / "ROADMAP.md").read_text(encoding="utf-8")
    start = text.index("### Phase 24: Live Runtime Composition + Demo Rehearsal")
    section = text[start:]
    section = section[: section.index("**Plans:**")]
    section = section[section.index("**Inherited items**") :]
    return re.findall(r"^- \[([A-Za-z0-9-]+)\]", section, re.MULTILINE)


def _register_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] and not set(cells[0]) <= {"-", ":", " "}:
            rows[cells[0].strip("`")] = cells
    return rows


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "")).strip()


def _status_problem(row_id: str, cells: list[str]) -> str | None:
    status = cells[2].split()[0].strip("*:;,.") if cells[2].split() else ""
    if status not in STATUS_WORDS:
        return f"{row_id}: status {cells[2][:30]!r} is none of {STATUS_WORDS}"
    if len(cells) < 4 or not cells[3]:
        return f"{row_id}: no evidence or reason"
    return None


def test_invariant_8_the_roadmap_phase24_entry_lists_the_expected_inherited_ids() -> None:
    ids = _roadmap_inherited_ids()
    assert len(ids) == len(set(ids)), "an inherited id is listed twice in the ROADMAP"
    for needed in ("P20-DEFERRED", "G2-014", "G3-033", "G2-042", "T-04", "16-50"):
        assert needed in ids, f"the ROADMAP Phase 24 entry no longer lists {needed}"
    assert len(ids) >= 20, f"only {len(ids)} inherited ids were parsed"


def test_invariant_8b_every_inherited_item_has_a_status_in_the_register() -> None:
    rows = _register_rows()
    problems: list[str] = []
    for item in [*_roadmap_inherited_ids(), *EARLIER_SECTION_IDS]:
        if item not in rows:
            problems.append(f"{item}: no row in 24-DEFERRED.md")
            continue
        problem = _status_problem(item, rows[item])
        if problem:
            problems.append(problem)
    assert problems == [], f"inherited items without a status: {problems}"


def _phase24_rows_of_20_deferred() -> list[str]:
    path = ROOT / ".planning" / "phases" / "20-reconcile-safe-mode-hardening" / "20-DEFERRED.md"
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and "Phase 24" in line:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            keys.append(_normal(cells[0])[:40])
    return keys


def test_invariant_8c_every_20_deferred_row_assigned_to_phase24_has_a_register_row() -> None:
    keys = _phase24_rows_of_20_deferred()
    assert len(keys) >= 39, f"only {len(keys)} Phase 24 rows were parsed from 20-DEFERRED.md"
    register_text = _normal(REGISTER.read_text(encoding="utf-8"))
    missing = [key for key in keys if key not in register_text]
    assert missing == [], f"20-DEFERRED rows without a register row: {missing}"
    rows = _register_rows()
    twenty = {row_id: cells for row_id, cells in rows.items() if row_id.startswith("20D-")}
    assert len(twenty) >= len(keys), "fewer 20D-NN register rows than 20-DEFERRED Phase 24 rows"
    problems = [p for row_id, cells in twenty.items() if (p := _status_problem(row_id, cells))]
    assert problems == [], f"20D rows without a status: {problems}"


def test_invariant_8d_the_register_residuals_are_listed_with_a_status() -> None:
    rows = _register_rows()
    residuals = [row_id for row_id in rows if row_id.startswith("R-")]
    assert len(residuals) >= 15, "the residual section lists fewer than 15 items"
    problems = [p for row_id in residuals if (p := _status_problem(row_id, rows[row_id]))]
    assert problems == [], f"residuals without a status: {problems}"


def test_invariant_8e_the_register_names_only_existing_test_files() -> None:
    text = REGISTER.read_text(encoding="utf-8")
    named = sorted(set(re.findall(r"tests/[A-Za-z0-9_/]+\.py", text)))
    assert named, "the register names no test file"
    missing = [relative for relative in named if not (ROOT / relative).is_file()]
    assert missing == [], f"the register names test files that do not exist: {missing}"


def test_invariant_8f_nothing_in_the_register_claims_a_host_or_mainnet_result() -> None:
    text = REGISTER.read_text(encoding="utf-8")
    assert "NOT_OBSERVED" in text, "the register must keep NOT_OBSERVED for owner-only items"
    for forbidden in ("mainnet-observed", "live-observed", "host-observed"):
        assert forbidden not in text, f"the register claims {forbidden}"
