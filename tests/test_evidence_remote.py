"""Plan 16-47: the fixed configuration names of the evidence remote (decision O-01, option a).

The evidence prefix has its own remote and its own credentials: `EVIDENCE_S3_*` names, mapped to
the rclone remote `EVIDENCES3`, with no crypt layer. They mirror the `BACKUP_S3_*` pattern of
`src/ops/backup_remote.py` but never share a name, a remote or (when both are set) a credential
with the backup chain, and the paper runtime neither reads them nor starts differently because
of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.ops import backup_remote
from src.ops import evidence_remote as ev
from src.paper.runtime_config import (
    ALLOWED_ENV_NAMES,
    TRADE_KEY_PREFIX,
    read_env,
    refuse_trade_capable_env,
)

ROOT = Path(__file__).resolve().parent.parent

GOOD = {
    "EVIDENCE_S3_PROVIDER": "AWS",
    "EVIDENCE_S3_REGION": "ap-southeast-1",
    "EVIDENCE_S3_BUCKET": "evidence-bucket",
    "EVIDENCE_S3_PREFIX": "paper/soak",
    "EVIDENCE_S3_ACCESS_KEY_ID": "EVID-access-id",
    "EVIDENCE_S3_SECRET_ACCESS_KEY": "evidence-secret-value",
}


def test_the_evidence_names_are_disjoint_from_the_backup_names() -> None:
    backup_names = {*backup_remote.S3_VARIABLES, *backup_remote.CRYPT_VARIABLES}
    assert set(ev.EVIDENCE_VARIABLES).isdisjoint(backup_names)
    assert all(name.startswith("EVIDENCE_S3_") for name in ev.EVIDENCE_VARIABLES)
    assert not any(name.startswith("BACKUP_") for name in ev.EVIDENCE_VARIABLES)


def test_the_evidence_remote_is_not_a_backup_remote_and_has_no_crypt_layer() -> None:
    assert ev.EVIDENCE_REMOTE not in {backup_remote.S3_REMOTE, backup_remote.CRYPT_REMOTE}
    assert not any("CRYPT" in name for name in ev.EVIDENCE_VARIABLES)
    mapped = ev.rclone_env(GOOD)
    assert set(mapped) <= {k for k in mapped if k.startswith("RCLONE_CONFIG_EVIDENCES3_")}
    assert mapped["RCLONE_CONFIG_EVIDENCES3_TYPE"] == "s3"
    assert not any("CRYPT" in key for key in mapped)
    assert not any(key.startswith("RCLONE_CONFIG_BACKUPS3") for key in mapped)


def test_the_mapping_mirrors_the_backup_s3_mapping() -> None:
    mapped = ev.rclone_env({**GOOD, "EVIDENCE_S3_PROVIDER": "Other", "EVIDENCE_S3_ENDPOINT": "e"})
    prefix = "RCLONE_CONFIG_EVIDENCES3_"
    assert mapped[prefix + "PROVIDER"] == "Other"
    assert mapped[prefix + "ENDPOINT"] == "e"
    assert mapped[prefix + "REGION"] == "ap-southeast-1"
    assert mapped[prefix + "ACCESS_KEY_ID"] == "EVID-access-id"
    assert mapped[prefix + "SECRET_ACCESS_KEY"] == "evidence-secret-value"
    assert mapped[prefix + "NO_CHECK_BUCKET"] == "true"
    assert ev.destination(GOOD) == "EVIDENCES3:evidence-bucket/paper/soak"


def test_the_endpoint_is_an_operator_value_needed_only_for_other_providers() -> None:
    assert ev.rclone_env(GOOD)["RCLONE_CONFIG_EVIDENCES3_ENDPOINT"] == ""
    with pytest.raises(ev.EvidenceConfigError) as raised:
        ev.rclone_env({**GOOD, "EVIDENCE_S3_PROVIDER": "Other"})
    assert "EVIDENCE_S3_ENDPOINT" in str(raised.value)


def test_missing_and_empty_names_are_listed_and_no_value_is_printed() -> None:
    bad = {**GOOD, "EVIDENCE_S3_REGION": "", "EVIDENCE_S3_SECRET_ACCESS_KEY": "  "}
    del bad["EVIDENCE_S3_PREFIX"]
    with pytest.raises(ev.EvidenceConfigError) as raised:
        ev.rclone_env(bad)
    message = str(raised.value)
    for name in ("EVIDENCE_S3_REGION", "EVIDENCE_S3_SECRET_ACCESS_KEY", "EVIDENCE_S3_PREFIX"):
        assert name in message
    for other in ("EVIDENCE_S3_BUCKET", "EVIDENCE_S3_PROVIDER", "EVIDENCE_S3_ACCESS_KEY_ID"):
        assert other not in message
    assert "EVID-access-id" not in message and "evidence-bucket" not in message


@pytest.mark.parametrize("prefix", ["", "/", "/abs", "a/../b", "a//b", "two words", "a?b", "a:b"])
def test_an_empty_or_unsafe_prefix_is_refused(prefix: str) -> None:
    with pytest.raises(ev.EvidenceConfigError) as raised:
        ev.destination({**GOOD, "EVIDENCE_S3_PREFIX": prefix})
    assert "EVIDENCE_S3_PREFIX" in str(raised.value)


def test_a_credential_looking_prefix_or_bucket_is_refused() -> None:
    for name, value in (
        ("EVIDENCE_S3_PREFIX", "secret_access_key=abc"),
        ("EVIDENCE_S3_BUCKET", "my-token-bucket"),
    ):
        with pytest.raises(ev.EvidenceConfigError) as raised:
            ev.destination({**GOOD, name: value})
        assert name in str(raised.value)
        assert value not in str(raised.value)


def test_the_evidence_credential_must_not_be_the_backup_credential() -> None:
    shared = {**GOOD, "BACKUP_S3_ACCESS_KEY_ID": GOOD["EVIDENCE_S3_ACCESS_KEY_ID"]}
    with pytest.raises(ev.EvidenceConfigError) as raised:
        ev.destination(shared)
    assert "EVIDENCE_S3_ACCESS_KEY_ID" in str(raised.value)
    assert "EVID-access-id" not in str(raised.value)
    other = {**GOOD, "BACKUP_S3_ACCESS_KEY_ID": "a-different-id"}
    assert ev.destination(other).startswith("EVIDENCES3:")


def test_the_paper_runtime_does_not_know_or_refuse_the_evidence_names() -> None:
    assert set(ev.EVIDENCE_VARIABLES).isdisjoint(ALLOWED_ENV_NAMES)
    assert read_env(GOOD) == {}, "the paper runtime reads none of the evidence names"
    assert refuse_trade_capable_env(GOOD) == [], "they are not trade-capable names"
    assert not any(name.startswith(TRADE_KEY_PREFIX) for name in ev.EVIDENCE_VARIABLES)
    # An exchange key beside them is still refused, by name only.
    with_key = {**GOOD, "BINANCE_API_KEY": "x"}
    assert refuse_trade_capable_env(with_key) == ["BINANCE_API_KEY"]


def test_the_evidence_template_lists_exactly_the_names_and_no_value() -> None:
    template = ROOT / "deploy" / "evidence.env.example"
    assert template.is_file(), "deploy/evidence.env.example does not exist"
    assigned: dict[str, str] = {}
    for line in template.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        assigned[name] = value
    # One more optional name since quick task 261114-12e: the host witness prefix.
    expected = (*ev.EVIDENCE_VARIABLES, ev.WITNESS_PREFIX_VARIABLE)
    assert tuple(sorted(assigned)) == tuple(sorted(expected))
    assert all(value == "" for value in assigned.values())


def test_the_shared_soak_environment_file_does_not_carry_the_evidence_names() -> None:
    """The paper container shares that file; the evidence credential stays out of it."""
    text = (ROOT / "deploy" / "soak.env.example").read_text(encoding="utf-8")
    assert "EVIDENCE_" not in text


# --------------------------------------------------------------------------- #
# Host witness prefix (quick task 261114-12e; 16-DEC-HOST-TICK).
# --------------------------------------------------------------------------- #


def test_the_witness_source_is_a_sibling_prefix_of_the_same_bucket() -> None:
    environ = {**GOOD, "EVIDENCE_S3_WITNESS_PREFIX": "paper/witness"}
    assert ev.witness_source(environ) == "EVIDENCES3:evidence-bucket/paper/witness"
    assert ev.witness_source({**GOOD, "EVIDENCE_S3_WITNESS_PREFIX": "witness"}) == (
        "EVIDENCES3:evidence-bucket/witness"
    )
    # The evidence names are unchanged: the witness prefix is one more, optional, name.
    assert len(ev.EVIDENCE_VARIABLES) == 7
    assert ev.WITNESS_PREFIX_VARIABLE == "EVIDENCE_S3_WITNESS_PREFIX"
    assert ev.WITNESS_PREFIX_VARIABLE not in ev.EVIDENCE_VARIABLES
    assert ev.destination(environ) == "EVIDENCES3:evidence-bucket/paper/soak"


@pytest.mark.parametrize(
    "value",
    [
        "",  # unset behaves the same
        "paper/soak",  # equal to the evidence prefix
        "paper/soak/witness",  # inside it
        "paper",  # contains it
        "/",
        "/abs",
        "a/../b",
        "a//b",
        "two words",
        "a?b",
        "a:b",
        "p?secret_access_key=abc",
        "token-in-the-prefix",
    ],
)
def test_an_overlapping_or_unsafe_witness_prefix_is_refused_naming_only_the_variable(
    value: str,
) -> None:
    environ = {**GOOD, "EVIDENCE_S3_WITNESS_PREFIX": value}
    with pytest.raises(ev.EvidenceConfigError) as raised:
        ev.witness_source(environ)
    message = str(raised.value)
    assert "EVIDENCE_S3_WITNESS_PREFIX" in message
    if len(value) > 6:
        assert value not in message
    assert "evidence-bucket" not in message and "evidence-secret-value" not in message


def test_the_witness_source_still_needs_the_evidence_configuration() -> None:
    bad = {**GOOD, "EVIDENCE_S3_WITNESS_PREFIX": "witness", "EVIDENCE_S3_REGION": ""}
    with pytest.raises(ev.EvidenceConfigError) as raised:
        ev.witness_source(bad)
    assert "EVIDENCE_S3_REGION" in str(raised.value)
