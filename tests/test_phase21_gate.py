"""Phase 21 gate (plan 21-14): the structural invariants of the live account state phase.

This file asserts, against the real tree and without any network or live evidence:

- the new pure modules read no wall clock, build no float, hold no quote-asset literal and import
  nothing outside the standard library and the project's pure layers
  (`PHASE21_PURE_MODULES`); the new execution modules read no wall clock, hold no quote-asset
  literal and import no adapter, persistence module, SDK or database client
  (`PHASE21_EXECUTION_MODULES`);
- the limit `account.max_equity_age_ms` is required and holds the owner's number 15000 with the
  provenance `DECISION` (O-1, DECISIONS D084, 2026-10-23); the other required keys stay
  `NOT_CONFIGURED`, so the live path still refuses;
- the `RejectionReason` enum still has 21 members; both verification flags
  (`LIVE_NET_PNL_SEMANTICS_VERIFIED`, `FUNDING_SOURCE_VERIFIED`) are False; `daily_stop` is an
  expiry trigger; the migration head is `0013_approval_money`; the OPS-05 rows of the daily
  state name `src/execution/daily_stop.py`;
- no Phase 21 fixture carries the account alias field of `GET /fapi/v3/balance` at any depth;
- each Phase 21 requirement has its named automated tests, resolved with `ast` and never imported
  or run (`REQUIREMENT_TESTS`); the owner records name O-1 to O-6.

A failure message names the missing path, symbol or test. Nothing here changes behavior and nothing
here claims an owner item is solved or a requirement complete. The owner answered O-3 to O-6 on
2026-10-24 (DECISIONS D086): multi-asset margin is not supported in V1, the conservative
realizedPnl default is kept until one small mainnet trade at the Phase 26 canary, the equity basis
is the smaller of the wallet and the margin balance, and the live latch is kept. The mainnet
evidence behind them is still NOT collected: `LIVE_NET_PNL_SEMANTICS_VERIFIED` and
`FUNDING_SOURCE_VERIFIED` stay False (the funding check joined the Phase 26 canary checklist)
(`21-OWNER-DECISIONS.md`, `21-DEFERRED.md`).
EXEC-01 and OPS-02 stay Pending; OPS-02 is an owner
attestation (D-21) and appears below only through its secret-free reads and logs.

Evidence label: executed structural tests. Nothing here touches Binance, Telegram or a database;
the Alembic head is read from the script directory and needs no connection.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = ROOT / ".planning" / "phases" / "21-account-equity-daily-loss"

# --------------------------------------------------------------------------- #
# The module inventory.
# --------------------------------------------------------------------------- #

#: New pure modules (D-04): stdlib plus project types only. No clock, no float, no SDK.
PHASE21_PURE_MODULES: tuple[str, ...] = (
    "src/risk/live_equity.py",
    "src/risk/daily_loss.py",
    "src/risk/reservations.py",
)

#: New execution modules: they take injected clocks and ports and import no adapter, store or SDK.
PHASE21_EXECUTION_MODULES: tuple[str, ...] = (
    "src/execution/account_equity.py",
    "src/execution/day_risk_service.py",
    "src/execution/daily_stop.py",
    "src/execution/live_risk_inputs.py",
)

# A pure module imports none of these (adapters, stores, orchestration, clients, dataframes).
PURE_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "src.adapters",
    "src.persistence",
    "src.execution",
    "src.ops",
    "src.paper",
    "sqlalchemy",
    "binance*",
    "polars",
    "pandas",
    "numpy",
    "httpx",
)
# An execution module is wired to its adapter and store by ports, never by import.
EXECUTION_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "src.adapters",
    "src.persistence",
    "binance*",
    "sqlalchemy",
)

#: The quote asset is a parameter of the live path, never a literal (research Pitfall 10).
QUOTE_ASSET_LITERAL = "USDT"


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_phase21_module_inventory_exists() -> None:
    missing = [
        relative
        for relative in (*PHASE21_PURE_MODULES, *PHASE21_EXECUTION_MODULES)
        if not (ROOT / relative).is_file()
    ]
    assert missing == [], f"missing Phase 21 modules: {missing}"


@pytest.mark.parametrize("relative", PHASE21_PURE_MODULES)
def test_invariant_1_pure_modules_have_no_clock_no_float_no_client_and_no_quote_literal(
    relative: str,
) -> None:
    path = ROOT / relative
    assert wall_clock_calls(path) == [], f"{relative} reads a clock"
    assert float_constructor_calls(path) == [], f"{relative} builds a float"
    assert forbidden_imports(path, PURE_FORBIDDEN_IMPORTS) == [], f"{relative} imports a client"
    assert QUOTE_ASSET_LITERAL not in _string_constants(path), (
        f"{relative} holds the literal {QUOTE_ASSET_LITERAL!r}"
    )


@pytest.mark.parametrize("relative", PHASE21_EXECUTION_MODULES)
def test_invariant_1b_execution_modules_read_no_clock_and_import_no_adapter_or_store(
    relative: str,
) -> None:
    path = ROOT / relative
    assert wall_clock_calls(path) == [], f"{relative} reads a clock"
    assert forbidden_imports(path, EXECUTION_FORBIDDEN_IMPORTS) == [], (
        f"{relative} imports an adapter, a store or the SDK"
    )
    assert QUOTE_ASSET_LITERAL not in _string_constants(path), (
        f"{relative} holds the literal {QUOTE_ASSET_LITERAL!r}"
    )


# --------------------------------------------------------------------------- #
# The equity-age limit: required, set by the owner on 2026-10-23 (D-03, O-1, DECISIONS D084).
# --------------------------------------------------------------------------- #

EXECUTION_LIMITS_FILE = ROOT / "config" / "execution" / "execution-limits-v1.toml"
EQUITY_AGE_KEY = "account.max_equity_age_ms"


def test_invariant_2_the_equity_age_limit_is_the_owner_number_and_required() -> None:
    from src.execution.execution_limits import (
        ALERT_ONLY_LIMIT_KEYS,
        NOT_CONFIGURED_WORD,
        load_execution_limits,
    )

    section, key = EQUITY_AGE_KEY.split(".")
    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    assert document[section][key] == 15000, "the owner number of D084 (O-1)"
    assert document["provenance"][section][key] == "DECISION"
    assert EQUITY_AGE_KEY not in ALERT_ONLY_LIMIT_KEYS, "the key must be required, not alert-only"
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    assert limits.account_max_equity_age_ms == 15000
    assert EQUITY_AGE_KEY not in limits.unset_keys()
    # Setting this key does not open the live path: other required keys stay NOT_CONFIGURED.
    assert limits.unset_keys(), "the live path must still refuse while other keys are unset"
    assert NOT_CONFIGURED_WORD in EXECUTION_LIMITS_FILE.read_text(encoding="utf-8")
    decisions = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    assert any(
        line.startswith("| D084 |") and "15000" in line and EQUITY_AGE_KEY in line
        for line in decisions.splitlines()
    ), "DECISIONS D084 must record the equity age number"


DAILY_LOSS_AGE_KEY = "account.max_daily_loss_age_ms"


def test_invariant_2b_the_daily_loss_age_limit_is_the_owner_number_and_required() -> None:
    # Phase 21 review WR-05: a known daily loss expires 300 s after the backfill that made it
    # known (owner answer 2026-10-25, DECISIONS D087). Required, no default in the service.
    from src.execution.execution_limits import ALERT_ONLY_LIMIT_KEYS, load_execution_limits

    section, key = DAILY_LOSS_AGE_KEY.split(".")
    document = tomllib.loads(EXECUTION_LIMITS_FILE.read_text(encoding="utf-8"))
    assert document[section][key] == 300000, "the owner number of D087 (300 seconds)"
    assert document["provenance"][section][key] == "DECISION"
    assert DAILY_LOSS_AGE_KEY not in ALERT_ONLY_LIMIT_KEYS
    limits = load_execution_limits(EXECUTION_LIMITS_FILE)
    assert limits.account_max_daily_loss_age_ms == 300000
    assert DAILY_LOSS_AGE_KEY not in limits.unset_keys()
    assert limits.unset_keys(), "the live path must still refuse while other keys are unset"


# --------------------------------------------------------------------------- #
# Vocabulary, flags, trigger, migration head, producer rows.
# --------------------------------------------------------------------------- #


def test_invariant_3_the_rejection_reason_enum_still_has_21_members() -> None:
    from src.domain.enums import RejectionReason

    assert len(RejectionReason) == 21, "Phase 21 adds no rejection reason (D-12)"


def test_invariant_4_both_verification_flags_are_false() -> None:
    from src.analytics import live_outcomes
    from src.risk import daily_loss

    assert live_outcomes.LIVE_NET_PNL_SEMANTICS_VERIFIED is False, (
        "mainnet realizedPnl semantics are unverified (O-4, G2-042); a DECISIONS row changes it"
    )
    assert daily_loss.FUNDING_SOURCE_VERIFIED is False, (
        "no FUNDING_FEE row was observed (O-2); only a DECISIONS row changes it"
    )


def test_invariant_4b_decisions_d086_records_the_phase_21_answers() -> None:
    decisions = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    rows = [line for line in decisions.splitlines() if line.startswith("| D086 |")]
    assert len(rows) == 1, "DECISIONS must carry exactly one D086 row"
    for needle in ("2026-10-24, owner answer", "equity_basis", "SMALLER", "Phase 26 canary"):
        assert needle in rows[0], f"D086 does not mention {needle!r}"
    assert "FUNDING_SOURCE_VERIFIED" in rows[0] and "LIVE_NET_PNL_SEMANTICS_VERIFIED" in rows[0]


def test_invariant_4c_decisions_d087_records_the_wr08_reading_and_the_loss_age() -> None:
    decisions = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    rows = [line for line in decisions.splitlines() if line.startswith("| D087 |")]
    assert len(rows) == 1, "DECISIONS must carry exactly one D087 row"
    for needle in (
        "2026-10-25, owner answer",
        "any earlier stored day",
        "fresh",
        "account.max_daily_loss_age_ms",
        "300000",
    ):
        assert needle in rows[0], f"D087 does not mention {needle!r}"


def test_invariant_5_daily_stop_is_an_expiry_trigger() -> None:
    from src.execution.manager import _EXPIRY_TRIGGERS

    assert "daily_stop" in _EXPIRY_TRIGGERS


def test_invariant_6_the_migration_head_is_0013_approval_money() -> None:
    from tests.pg_support import alembic_head_revision

    assert alembic_head_revision() == "0013_approval_money", (
        "Phase 23 plan 23-04 moved the head to 0013; a later migration must update this gate "
        "on purpose"
    )


def test_invariant_7_the_daily_state_ops05_rows_name_the_daily_stop_producer() -> None:
    from src.ops.alerts import OPS05_MATRIX

    rows = {row.alert: row for row in OPS05_MATRIX}
    for alert in ("DAILY_STOP", "DAILY_LOSS_WARNING"):
        assert alert in rows, f"OPS05_MATRIX has no {alert} row"
        assert rows[alert].producer == "src/execution/daily_stop.py", alert


# --------------------------------------------------------------------------- #
# Fixtures carry no account alias (OPS-02 hygiene, D-21).
# --------------------------------------------------------------------------- #

#: The account alias field of GET /fapi/v3/balance. It identifies the account and is dropped.
ACCOUNT_ALIAS_FIELD = "accountAlias"
PHASE21_FIXTURES = ROOT / "tests" / "fixtures" / "phase21"


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        for child in value.values():
            keys |= _json_keys(child)
        return keys
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found |= _json_keys(child)
        return found
    return set()


def test_invariant_8_no_phase21_fixture_carries_the_account_alias_key() -> None:
    import json

    files = sorted(PHASE21_FIXTURES.rglob("*.json"))
    assert files, "tests/fixtures/phase21 holds no JSON fixture"
    offenders = [
        str(path.relative_to(ROOT))
        for path in files
        if ACCOUNT_ALIAS_FIELD in _json_keys(json.loads(path.read_text(encoding="utf-8")))
    ]
    assert offenders == [], f"fixtures carry {ACCOUNT_ALIAS_FIELD!r}: {offenders}"


# --------------------------------------------------------------------------- #
# Requirement -> named tests (resolved with ast, never imported).
# --------------------------------------------------------------------------- #

REQUIREMENT_TESTS: dict[str, tuple[tuple[str, str], ...]] = {
    "RISK-01": (
        # The live equity resolver.
        ("tests/test_live_equity.py", "test_fresh_demo_shaped_reading_resolves_to_account_state"),
        (
            "tests/test_live_equity.py",
            "test_equity_basis_is_the_smaller_of_wallet_and_margin_balance",
        ),
        ("tests/test_live_equity.py", "test_one_millisecond_past_max_age_is_no_trade"),
        ("tests/test_live_equity.py", "test_multi_assets_margin_is_no_trade"),
        # The account equity source, end to end over the recorded Demo payloads.
        (
            "tests/test_account_equity_source.py",
            "test_recorded_demo_payloads_reach_account_state_through_the_real_adapter",
        ),
        (
            "tests/test_account_equity_source.py",
            "test_any_failed_read_is_no_trade_recorded_by_type_and_never_retried",
        ),
        # The live risk inputs and the parity with the backtest ledger.
        (
            "tests/test_live_risk_inputs.py",
            "test_sources_assemble_into_the_four_risk_inputs",
        ),
        (
            "tests/test_live_risk_inputs.py",
            "test_thresholds_do_not_move_with_current_equity",
        ),
        ("tests/test_live_risk_parity.py", "test_open_positions_and_thresholds_are_the_same"),
        ("tests/test_live_risk_parity.py", "test_check_portfolio_gives_the_same_verdict"),
    ),
    "RISK-02": (
        # The daily loss fold and the sticky latch.
        (
            "tests/test_daily_loss.py",
            "test_one_fill_pnl_and_commission_give_loss_5_and_warning_boundary",
        ),
        (
            "tests/test_daily_loss.py",
            "test_second_fill_brings_loss_to_10_and_daily_stop_boundary",
        ),
        ("tests/test_daily_loss.py", "test_a_held_latch_wins_over_any_loss"),
        # The day risk service and its stream path.
        (
            "tests/test_day_risk_service.py",
            "test_a_derived_stop_is_latched_in_the_store_before_the_verdict_returns",
        ),
        (
            "tests/test_day_risk_service.py",
            "test_a_restart_inside_the_day_keeps_the_stored_base_and_the_latch",
        ),
        (
            "tests/test_day_risk_stream.py",
            "test_an_invalidation_makes_the_loss_unknown_until_the_next_backfill",
        ),
        (
            "tests/test_day_risk_stream.py",
            "test_a_stream_fill_between_backfills_adds_to_the_loss",
        ),
        # The recorded Demo SL close.
        (
            "tests/test_daily_loss_recorded.py",
            "test_the_recorded_sl_close_becomes_the_two_stream_components",
        ),
        ("tests/test_daily_loss_recorded.py", "test_the_stream_fill_and_the_rest_row_count_once"),
        # The reservation verdict, its release coverage and the persisted transition table.
        (
            "tests/test_risk_reservations.py",
            "test_aggregate_cap_rejects_one_cent_over",
        ),
        (
            "tests/test_risk_reservations.py",
            "test_latched_day_refuses_with_daily_stop_even_when_everything_fits",
        ),
        (
            "tests/test_risk_reservations.py",
            "test_every_status_but_released_has_an_exit_and_released_is_never_a_source",
        ),
        (
            "tests/test_risk_reservations_pg.py",
            "test_release_follows_the_transition_table_cell_by_cell",
        ),
        # The race at approval (PostgreSQL).
        (
            "tests/test_risk_reservation_approval_pg.py",
            "test_two_concurrent_approvals_that_only_one_fits_cannot_both_pass",
        ),
        (
            "tests/test_risk_reservation_approval_pg.py",
            "test_a_skip_cancel_or_expire_releases_the_request_with_the_decision",
        ),
        # The release-reason mappings of every terminal plan state.
        ("tests/test_live_risk_inputs.py", "test_release_reason_for_approval_status"),
        ("tests/test_live_risk_inputs.py", "test_release_reason_for_entry_intent"),
        ("tests/test_live_risk_inputs.py", "test_release_reason_for_protection_state"),
        ("tests/test_live_risk_inputs.py", "test_release_reason_for_plan_over_every_status"),
        (
            "tests/test_live_risk_inputs.py",
            "test_every_public_pre_placement_constant_is_classified",
        ),
        # The persisted day state (PostgreSQL).
        (
            "tests/test_day_risk_pg.py",
            "test_a_second_open_returns_the_stored_row_and_keeps_the_base",
        ),
        ("tests/test_day_risk_pg.py", "test_latch_stop_is_set_once_and_survives_a_restart"),
    ),
    "EXEC-01": (
        # The snapshot carries the live equity (D-18); it stays INCOMPLETE until Phase 22.
        (
            "tests/test_snapshot_live_equity.py",
            "test_live_equity_with_stubbed_phase22_inputs_is_valid_for_live",
        ),
        (
            "tests/test_snapshot_live_equity.py",
            "test_live_equity_without_margin_type_and_leverage_is_not_valid_for_live",
        ),
        # The daily stop cancels resting entries and keeps the stops.
        (
            "tests/test_daily_stop.py",
            "test_latched_daily_stop_cancels_the_entry_keeps_the_stop_and_alerts_after",
        ),
        (
            "tests/test_daily_stop.py",
            "test_daily_stop_is_an_accepted_trigger_and_an_unknown_one_still_raises",
        ),
    ),
    "OPS-02": (
        # Secret-free reads and logs only; OPS-02 itself stays an owner attestation (D-21).
        (
            "tests/test_account_reads_adapter.py",
            "test_a_successful_account_information_read_logs_no_balance",
        ),
        (
            "tests/test_account_reads_adapter.py",
            "test_a_successful_balance_read_logs_neither_a_balance_nor_the_alias",
        ),
        (
            "tests/test_account_reads_adapter.py",
            "test_the_balance_read_never_touches_the_alias_attribute",
        ),
        ("tests/test_account_equity_source.py", "test_logs_carry_no_balance_and_no_exception_text"),
        (
            "tests/test_phase21_fixtures.py",
            "test_no_fixture_carries_the_account_alias_key_at_any_depth",
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


def test_invariant_9_each_phase21_requirement_has_its_named_tests() -> None:
    assert set(REQUIREMENT_TESTS) == {"RISK-01", "RISK-02", "EXEC-01", "OPS-02"}
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


def test_invariant_9b_every_requirement_name_is_a_known_requirement() -> None:
    planning = ROOT / ".planning" / "REQUIREMENTS.md"
    if not planning.is_file():
        pytest.skip("REQUIREMENTS.md is not in this checkout (filtered)")
    text = planning.read_text(encoding="utf-8")
    for requirement in REQUIREMENT_TESTS:
        assert f"**{requirement}**" in text, requirement


# --------------------------------------------------------------------------- #
# The owner records name O-1 to O-6 (T-21-31).
# --------------------------------------------------------------------------- #

OWNER_ITEMS: tuple[str, ...] = tuple(f"O-{number}" for number in range(1, 7))


def test_invariant_10_the_owner_decisions_and_the_deferred_register_name_o1_to_o6() -> None:
    if not PHASE_DIR.is_dir():
        pytest.skip(".planning/phases/21-* is not in this checkout (filtered)")
    problems: list[str] = []
    for name in ("21-OWNER-DECISIONS.md", "21-DEFERRED.md"):
        path = PHASE_DIR / name
        if not path.is_file():
            problems.append(f"{name} does not exist")
            continue
        text = path.read_text(encoding="utf-8")
        problems.extend(f"{name} does not name {item}" for item in OWNER_ITEMS if item not in text)
    assert problems == [], f"owner records incomplete: {problems}"
