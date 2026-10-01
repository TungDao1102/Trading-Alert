"""`src.db.models.make_engine` never echoes the database URL (17-REVIEW WR-04, T-17-03).

A mistyped scheme such as the common `postgres://` alias is refused, and the refusal must
not leak the userinfo (password) into logs or tracebacks.
"""

from __future__ import annotations

import pytest
from src.db.models import make_engine

PASSWORD = "secret-pw-123"


@pytest.mark.parametrize(
    "url",
    [
        f"postgres://user:{PASSWORD}@db.example.com:5432/trading",
        f"mysql+aiomysql://user:{PASSWORD}@db.example.com/trading",
        f"user:{PASSWORD}@db.example.com/trading",
    ],
)
def test_a_refused_url_never_leaks_its_password_or_userinfo(url: str) -> None:
    with pytest.raises(ValueError) as info:
        make_engine(url)

    message = str(info.value)
    assert PASSWORD not in message
    assert "user:" not in message
    assert "db.example.com" not in message
    assert "refusing engine" in message
    assert "postgresql+psycopg://" in message  # the expected form is still named


def test_the_refusal_names_only_the_scheme_class() -> None:
    with pytest.raises(ValueError, match=r"scheme 'postgres'"):
        make_engine(f"postgres://user:{PASSWORD}@db.example.com/trading")
