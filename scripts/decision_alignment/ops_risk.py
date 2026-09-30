"""Operations and risk documents gate module (Phase 11, plan 11-04; D031-D038, D042).

Executable checks that keep SECURITY_AND_OPERATIONS, RUNBOOK, RISK_MANAGEMENT,
DATA_MODEL, CONFIGURATION and SIGNAL_AND_ALERTS aligned with the accepted decisions,
so the stale pre-decision wording cannot return unnoticed. ``run()`` returns
``(name, ok, detail)`` tuples OR-01..OR-10; every check is also a pure function over
text so tests can inject good and bad input.

Required phrases are matched after ``normalise`` (emphasis markers and backticks removed,
whitespace collapsed). Forbidden wording is matched per normalised line.

Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEC_OPS_PATH = REPO_ROOT / "docs" / "operations" / "SECURITY_AND_OPERATIONS.md"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "RUNBOOK.md"
RISK_PATH = REPO_ROOT / "docs" / "trading" / "RISK_MANAGEMENT.md"
DATA_MODEL_PATH = REPO_ROOT / "docs" / "data" / "DATA_MODEL.md"
CONFIGURATION_PATH = REPO_ROOT / "docs" / "configuration" / "CONFIGURATION.md"
ALERTS_PATH = REPO_ROOT / "docs" / "trading" / "SIGNAL_AND_ALERTS.md"

Gate = tuple[str, bool, str]


def normalise(text: str) -> str:
    """Strip ``**`` and backticks, then collapse all whitespace to single spaces."""
    return " ".join(text.replace("**", "").replace("`", "").split())


def _lines(text: str) -> list[str]:
    """Normalised, non-empty lines."""
    out: list[str] = []
    for raw in text.splitlines():
        line = normalise(raw)
        if line:
            out.append(line)
    return out


def _section(text: str, number: int) -> str:
    """Body of the ``## <number>.`` section, up to the next ``## <n>.`` heading."""
    text = text.replace("\r\n", "\n")
    match = re.search(rf"^## {number}\.[^\n]*\n", text, flags=re.MULTILINE)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^## \d+\.", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _missing(text: str, phrases: tuple[str, ...]) -> list[str]:
    haystack = normalise(text)
    return [p for p in phrases if p not in haystack]


def _forbidden_hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    """Normalised lines matching any forbidden regex (case-insensitive)."""
    compiled = [re.compile(p, flags=re.IGNORECASE) for p in patterns]
    return [line for line in _lines(text) if any(c.search(line) for c in compiled)]


def _verdict(name: str, missing: list[str], forbidden: list[str]) -> Gate:
    problems: list[str] = []
    if missing:
        problems.append("missing: " + "; ".join(missing))
    if forbidden:
        problems.append("forbidden: " + "; ".join(forbidden))
    if problems:
        return (name, False, " | ".join(problems))
    return (name, True, "ok")


# --------------------------------------------------------------------------- OR-01

SAFE_MODE_SEC_OPS_PHRASES = (
    "SAFE_MODE blocks new entry orders only",
    "Protective and reduce-only orders are always allowed",
    "automatically re-placed",
    "original plan stop-loss",
    "never wider",
    "reduce-only market close",
    "HIGH-priority alert",
    "D034",
)
SAFE_MODE_SEC_OPS_FORBIDDEN = (r"^-? ?no new live order placement[;.]?$",)

SAFE_MODE_RUNBOOK_PHRASES = (
    "Block new ENTRY orders",
    "NO NEW ENTRY ORDERS",
    "not an orphan",
    "D034",
)
SAFE_MODE_RUNBOOK_FORBIDDEN = (
    r"block new live orders",
    r"^NO NEW ORDERS$",
    r"^(→ )?block new orders$",
)


def check_safe_mode_sec_ops(text: str) -> Gate:
    """SECURITY_AND_OPERATIONS section 7: entries-only SAFE_MODE and the D034 ladder."""
    return _verdict(
        "OR-01a",
        _missing(_section(text, 7), SAFE_MODE_SEC_OPS_PHRASES),
        _forbidden_hits(text, SAFE_MODE_SEC_OPS_FORBIDDEN),
    )


def check_safe_mode_runbook(text: str) -> Gate:
    """RUNBOOK: entry-only blocking, automatic stop ladder and the orphan carve-out."""
    return _verdict(
        "OR-01b",
        _missing(text, SAFE_MODE_RUNBOOK_PHRASES),
        _forbidden_hits(text, SAFE_MODE_RUNBOOK_FORBIDDEN),
    )


# --------------------------------------------------------------------------- OR-02

SECRETS_PHRASES = ("permission-restricted", "0600", "D042", "disk encryption")
SECRETS_FORBIDDEN = (r"^-? ?Encrypt secrets at rest\.?$",)


def check_secrets(text: str) -> Gate:
    """SECURITY_AND_OPERATIONS section 1: the D042 secrets-at-rest control."""
    return _verdict(
        "OR-02",
        _missing(_section(text, 1), SECRETS_PHRASES),
        _forbidden_hits(text, SECRETS_FORBIDDEN),
    )


# --------------------------------------------------------------------------- OR-03

WEBHOOK_PHRASES = ("TRADINGVIEW.md", "cannot sign")


def check_webhook_pointer(text: str) -> Gate:
    """Webhook bullet points at TRADINGVIEW.md and never claims a signature scheme."""
    section = _section(text, 1)
    webhook_lines = [ln for ln in _lines(section) if "webhook" in ln.lower()]
    missing = _missing(" ".join(webhook_lines), WEBHOOK_PHRASES)
    claims = [
        ln
        for ln in _lines(text)
        if "webhook" in ln.lower()
        and re.search(r"hmac|signature|signed", ln, flags=re.IGNORECASE)
        and "cannot sign" not in ln
    ]
    verdict = _verdict("OR-03", missing, [])
    if claims:
        detail = "signature claim without 'cannot sign': " + "; ".join(claims)
        if not verdict[1]:
            detail = verdict[2] + " | " + detail
        return ("OR-03", False, detail)
    return verdict


# --------------------------------------------------------------------------- OR-04..OR-08

DAILY_LOSS_PHRASES = (
    "UTC day",
    "00:00 UTC",
    "07:00 Asia/Ho_Chi_Minh",
    "realized PnL",
    "commissions",
    "funding",
    "equity at the UTC day start",
    "0.5%",
    "1.0%",
    "cancel pending entry orders",
    "protective stop-loss orders",
    "daily_loss_warning_threshold",
    "daily_loss_stop_threshold",
    "D033",
)
DAILY_LOSS_FORBIDDEN = (r"daily loss stop: TBD",)

MARGIN_PHRASES = (
    "ISOLATED",
    "5x",
    "marginType",
    "explicitly",
    "liquidation price",
    "buffer",
    "registry parameter",
    "resting entry",
    "D035",
)
# A concrete liquidation-buffer number must never be hard-coded in the document.
MARGIN_FORBIDDEN = (
    r"buffer (of|=|is|:) ?\d",
    r"\d+(\.\d+)?x (SL|stop) distance",
)

QUANTIZATION_CANONICAL_LABEL = "Canonical order (D031):"
QUANTIZATION_ORDER_TOKENS = (
    "stepSize",
    "min quantity",
    "min notional",
    "minimum_risk_utilization_after_rounding",
)
QUANTIZATION_REASON_TOKENS = ("MIN_QTY_REJECT", "NOTIONAL_REJECT", "UTILIZATION_REJECT", "D031")
QUANTIZATION_SYNONYM = "QUANTIZATION_REJECT"

SNAPSHOT_PHRASES = (
    "market_lot_size",
    "percent_price",
    "working_type",
    "margin_type",
    "leverage",
    "equity_used",
    "metadata_observed_at_utc",
    "persisted per plan",
    "verify",
)

SL_COMPENSATION_PHRASES = ("never a wider", "averaging down", "D034")


def check_daily_loss(text: str) -> Gate:
    """RISK_MANAGEMENT sections 4 and 8: the D033 daily-loss definition."""
    body = _section(text, 4) + " " + _section(text, 8)
    return _verdict(
        "OR-04",
        _missing(body, DAILY_LOSS_PHRASES),
        _forbidden_hits(text, DAILY_LOSS_FORBIDDEN),
    )


def check_margin(text: str) -> Gate:
    """RISK_MANAGEMENT section 9: D035 margin rules, no hard-coded buffer number."""
    body = _section(text, 9)
    return _verdict(
        "OR-05",
        _missing(body, MARGIN_PHRASES),
        _forbidden_hits(body, MARGIN_FORBIDDEN),
    )


def check_quantization(text: str) -> Gate:
    """RISK_MANAGEMENT section 11: one canonical quantization order, no synonym."""
    body = _section(text, 11)
    missing = _missing(body, QUANTIZATION_REASON_TOKENS)
    forbidden: list[str] = []
    if QUANTIZATION_SYNONYM in text:
        forbidden.append(f"{QUANTIZATION_SYNONYM} synonym present")
    canonical = [ln for ln in _lines(body) if ln.startswith(QUANTIZATION_CANONICAL_LABEL)]
    if not canonical:
        missing.append(f"labelled line '{QUANTIZATION_CANONICAL_LABEL}'")
    else:
        cursor = 0
        line = canonical[0]
        for token in QUANTIZATION_ORDER_TOKENS:
            found = line.find(token, cursor)
            if found < 0:
                missing.append(
                    f"canonical order violated at '{token}' (expected after position {cursor})"
                )
                break
            cursor = found + len(token)
    reason_positions = [body.find(tok) for tok in QUANTIZATION_REASON_TOKENS[:3]]
    if -1 not in reason_positions and reason_positions != sorted(reason_positions):
        missing.append("reason codes not in canonical order MIN_QTY, NOTIONAL, UTILIZATION")
    return _verdict("OR-06", missing, forbidden)


def check_snapshot(text: str) -> Gate:
    """RISK_MANAGEMENT section 12: extended exchange constraint snapshot."""
    return _verdict("OR-07", _missing(_section(text, 12), SNAPSHOT_PHRASES), [])


def check_sl_and_compensation(text: str) -> Gate:
    """RISK_MANAGEMENT sections 6 and 7: SL restore never wider, no averaging down."""
    body = _section(text, 6) + " " + _section(text, 7)
    return _verdict("OR-08", _missing(body, SL_COMPENSATION_PHRASES), [])


# --------------------------------------------------------------------------- OR-09, OR-10

DATA_MODEL_PLAN_FIELDS = (
    "constraint_snapshot_json",
    "constraint_snapshot_hash",
    "working_type",
    "margin_type",
    "leverage",
    "equity_used",
)

CONFIGURATION_PHRASES = (
    "working_type",
    "MARK_PRICE",
    "CONTRACT_PRICE",
    "partial_fill_fraction",
    "fee_rate_entry",
    "taker",
    "D036",
    "D037",
    "D038",
    "baseline-v4",
    "research-universe-v1.toml",
    "not a parameter set",
)

ALERT_PHRASES = (
    "Expected R:R: 2.0 / 4.0",
    "TP1: 105275",
    "TP2: 106625",
    "Asia/Ho_Chi_Minh",
)
ALERT_FORBIDDEN = (
    r"Expected R:R: 1\.8 / 3\.9",
    r"^TP1: 105200$",
    r"^TP2: 106000$",
    r"Valid until: 16:00 UTC",
)


def _subsection(text: str, heading_prefix: str) -> str:
    """Body of a ``### <prefix>`` subsection, up to the next ``###`` or ``##`` heading."""
    text = text.replace("\r\n", "\n")
    pattern = rf"^### {re.escape(heading_prefix)}[^\n]*\n"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if match is None:
        return ""
    rest = text[match.end() :]
    nxt = re.search(r"^##", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def check_data_model_plan_fields(text: str) -> Gate:
    """DATA_MODEL section 2.4: persisted constraint snapshot and execution fields."""
    block = _subsection(text, "2.4")
    fields = {ln.split()[0] for ln in _lines(block) if ln.split()[0].isidentifier()}
    missing = [f for f in DATA_MODEL_PLAN_FIELDS if f not in fields]
    return _verdict("OR-09", missing, [])


def check_configuration(text: str) -> Gate:
    """CONFIGURATION: registry key guidance and section 10 cost assumptions."""
    return _verdict("OR-10a", _missing(text, CONFIGURATION_PHRASES), [])


def check_alert_example(text: str) -> Gate:
    """SIGNAL_AND_ALERTS section 5: example satisfies minimum_rr, uses Ho Chi Minh time."""
    return _verdict(
        "OR-10b",
        _missing(_section(text, 5), ALERT_PHRASES),
        _forbidden_hits(text, ALERT_FORBIDDEN),
    )


# --------------------------------------------------------------------------- run


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _combine(name: str, gates: list[Gate]) -> Gate:
    bad = [f"{g[0]}: {g[2]}" for g in gates if not g[1]]
    if bad:
        return (name, False, " | ".join(bad))
    return (name, True, "ok")


def run() -> list[Gate]:
    """Evaluate every gate against the real repository documents."""
    sec_ops = _read(SEC_OPS_PATH)
    runbook = _read(RUNBOOK_PATH)
    risk = _read(RISK_PATH)
    return [
        _combine(
            "OR-01",
            [check_safe_mode_sec_ops(sec_ops), check_safe_mode_runbook(runbook)],
        ),
        check_secrets(sec_ops),
        check_webhook_pointer(sec_ops),
        check_daily_loss(risk),
        check_margin(risk),
        check_quantization(risk),
        check_snapshot(risk),
        check_sl_and_compensation(risk),
        check_data_model_plan_fields(_read(DATA_MODEL_PATH)),
        check_configuration(_read(CONFIGURATION_PATH)),
        check_alert_example(_read(ALERTS_PATH)),
    ]


if __name__ == "__main__":  # pragma: no cover
    import sys

    results = run()
    for gate_name, gate_ok, gate_detail in results:
        print(("PASS" if gate_ok else "FAIL"), gate_name, gate_detail)
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
