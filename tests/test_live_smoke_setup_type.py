"""The Demo smoke signal must persist on PostgreSQL (first Demo run, 2026-11-01).

`ck_signals_setup_type` allows only the six `SetupType` values; a smoke-only setup name raised an
`IntegrityError` at issue time on the real database while every in-memory suite stayed green.
"""

from __future__ import annotations

from src.domain.enums import SetupType
from src.live.signal_source import DEMO_SMOKE_REASON_CODES, DEMO_SMOKE_SETUP


def test_the_smoke_setup_is_a_value_the_signals_check_constraint_allows() -> None:
    assert DEMO_SMOKE_SETUP in {member.value for member in SetupType}


def test_the_smoke_label_travels_in_the_reason_codes() -> None:
    assert "DEMO_SMOKE" in DEMO_SMOKE_REASON_CODES
