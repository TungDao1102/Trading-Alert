"""Provenance block tests (Phase 10, plan 10-08, D-05).

RED first: authored before `src/analytics/provenance.py` exists. Provenance is derived
from frozen `ReportInputs` with no file access and lists BACKTEST / PAPER / LIVE identity
separately while also stating which evidence kinds are present.
"""

from __future__ import annotations

import dataclasses
import re

from src.analytics.approval_delay import APPROVAL_DELAY_LAG_SECONDS
from src.analytics.live_outcomes import LIVE_NET_PNL_SEMANTICS_VERIFIED
from src.analytics.provenance import ExperimentIdentity, ProvenanceBlock, build_provenance
from src.analytics.slices import SESSION_BANDS, SLICE_VOCABULARY_VERSION
from src.analytics.types import LOW_N_THRESHOLD, MIN_RESAMPLES, EvidenceKind

from tests.phase10_helpers import load_input
from tests.test_analytics_report import (
    _shuffle_inputs,
    assert_no_pooled_fields,
    build_report,
    build_report_inputs,
    plain,
    secret_hits,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SIX_IDENTITY_FIELDS = (
    "experiment_id",
    "strategy_version",
    "parameter_set_id",
    "parameter_set_hash",
    "data_snapshot_id",
    "code_version",
    "cost_model_hash",
)


def _provenance(**overrides: object) -> ProvenanceBlock:
    inputs = dataclasses.replace(build_report_inputs(), **overrides)  # type: ignore[arg-type]
    seed = load_input("report_composite")["base_seed"]
    return build_provenance(inputs, base_seed=seed, resamples=MIN_RESAMPLES)


def test_provenance_lists_the_experiment_identity_fields_and_evidence_tag() -> None:
    block = _provenance()
    raw = load_input("report_composite")["backtest"]["experiments"][0]
    assert len(block.experiments) == 1
    identity = block.experiments[0]
    assert isinstance(identity, ExperimentIdentity)
    for name in SIX_IDENTITY_FIELDS:
        assert getattr(identity, name) == raw[name]
    assert identity.universe_hash == raw["universe_hash"]
    assert identity.run_type == "CANDIDATE"
    assert identity.evidence is EvidenceKind.BACKTEST


def test_research_universe_status_verified_unverified_and_not_applicable() -> None:
    assert _provenance().research_universe_status == "VERIFIED"
    wrong = _provenance(expected_universe_hash="0" * 64)
    assert wrong.research_universe_status == "UNVERIFIED_UNIVERSE"
    assert _provenance(expected_universe_hash=None).research_universe_status == "NOT_APPLICABLE"
    block = _provenance()
    assert HEX64.match(block.research_universe_hash)
    assert block.research_universe_hash == load_input("report_composite")["expected_universe_hash"]


def test_provenance_states_constants_and_kinds_present() -> None:
    block = _provenance()
    assert block.low_n_threshold == LOW_N_THRESHOLD
    assert block.resamples == MIN_RESAMPLES
    assert block.base_seed == load_input("report_composite")["base_seed"]
    assert block.approval_delay_lag_seconds == APPROVAL_DELAY_LAG_SECONDS
    assert block.slice_vocabulary_version == SLICE_VOCABULARY_VERSION
    assert block.session_bands == SESSION_BANDS
    assert block.evidence_kinds_present == ("BACKTEST", "PAPER")
    assert block.live_net_pnl_semantics_verified is LIVE_NET_PNL_SEMANTICS_VERIFIED
    assert block.live_r_excludes == ("funding",)


def test_provenance_ids_are_sorted_unique_and_kept_per_evidence_kind() -> None:
    block = _provenance()
    assert block.strategy_versions == ("v2.0.0",)
    assert block.parameter_set_ids == ("PS-1",)
    assert block.parameter_set_hashes == ("a" * 64,)
    assert block.data_snapshot_ids == ("d1" * 32,)
    assert block.paper_epoch_ids == ("EPOCH-1",)
    assert [item.kind for item in block.by_evidence] == [
        EvidenceKind.BACKTEST,
        EvidenceKind.PAPER,
        EvidenceKind.LIVE,
    ]
    backtest, paper, live = block.by_evidence
    assert backtest.has_data and paper.has_data and not live.has_data
    assert backtest.data_snapshot_ids == ("d1" * 32,)
    assert paper.data_snapshot_ids == ()
    assert paper.paper_epoch_ids == ("EPOCH-1",)
    assert backtest.paper_epoch_ids == ()
    assert live.strategy_versions == ()


def test_provenance_digest_is_stable_and_sensitive() -> None:
    block = _provenance()
    assert HEX64.match(block.digest())
    assert block.digest() == _provenance().digest()
    other = build_provenance(build_report_inputs(), base_seed=1, resamples=MIN_RESAMPLES)
    assert other.digest() != block.digest()
    assert build_report().provenance.digest() == block.digest()


def test_provenance_is_order_independent_and_secret_free() -> None:
    inputs = build_report_inputs()
    seed = load_input("report_composite")["base_seed"]
    base = build_provenance(inputs, base_seed=seed, resamples=MIN_RESAMPLES)
    for shuffle_seed in range(4):
        shuffled = build_provenance(
            _shuffle_inputs(inputs, shuffle_seed), base_seed=seed, resamples=MIN_RESAMPLES
        )
        assert shuffled == base
    assert secret_hits(plain(base)) == []
    assert_no_pooled_fields(base, "provenance")
