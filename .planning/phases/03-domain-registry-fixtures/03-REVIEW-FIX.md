---
phase: 03-domain-registry-fixtures
fixed_at: 2026-09-23T14:17:53+00:00
review_path: C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/03-domain-registry-fixtures/03-REVIEW.md
iteration: 1
findings_in_scope: 19
fixed: 19
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-09-23T14:17:53+00:00
**Source review:** C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/03-domain-registry-fixtures/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 19 (6 Critical + 13 Warning; 6 Info out of scope per fix_scope=critical_warning)
- Fixed: 19
- Skipped: 0

**Verification environment:** main checkout (`.planning/config.json`
`workflow.use_worktrees=false`, so no isolated worktree was created;
all edits, test runs, and commits ran in the repo working tree).

**Final gates (after all fixes):**
- `uv run pytest`: 209 passed, 5 skipped (the 5 skips are the new
  WR-11 live-PG tests, gated on `TEST_DATABASE_URL` which is unset)
- `uv run ruff check src tests`: all checks passed
- `uv run mypy src`: no issues found in 29 source files
- Pinned registry hash unchanged:
  `e1579900b1be20b8a6db76c554255cbec8125d5d317f6df7dadd5de78d2afae5`
  still reproduces via `load_parameter_set("trend-pullback", "baseline-v1")`;
  `tests/fixtures/phase3/parameters.json` untouched.

## Fixed Issues

### CR-01: `make_signal_id` omits `strategy_id` — cross-strategy ID collision

**Files modified:** `src/domain/ids.py`, `tests/test_domain_ids.py`, `tests/test_no_lookahead.py`, `tests/test_prefix_invariance.py`, `tests/test_candle_close_timing.py`
**Commit:** db3f82d
**Applied fix:** Added required keyword-only `strategy_id` as the first
bound field of `make_signal_id` (D-03 docstring updated); old
scheme removed, no dual-shape acceptance. Updated every caller
(domain test + three determinism suites with a shared `STRATEGY_ID`
constant). Extended `test_make_signal_id_different_inputs...` with the
`strategy_id` axis and added
`test_make_signal_id_binds_strategy_id` (two strategy_ids, all else
equal, digests differ).

### CR-02: `Signal` entity has no validation at all — naive datetimes accepted

**Files modified:** `src/domain/signal.py`, `tests/test_domain_entities.py`
**Commit:** ef47546
**Applied fix:** Added `_require_utc_aware` helper plus
`__post_init__` enforcing UTC-aware
`source_candle_close_utc`/`detected_at_utc`/`expires_at_utc` and
optional `invalidated_at_utc`. Added `_signal_kwargs` helper and
`Signal` to `test_all_entities_reject_naive_datetimes` (naive close
raises at the boundary, before the canonical hash).

### CR-03: CI re-hash gate is vacuous — compares a load against itself

**Files modified:** `.github/workflows/registry-gate.yml`
**Commit:** 087816a
**Applied fix:** Re-hash step now loads the pinned
`tests/fixtures/phase3/parameters.json` and calls
`verify_parameter_set(toml_path, pinned_hash)` per registry TOML;
mutated seeds raise `ParameterSetMutated` (verified locally: a
one-digit mutation is rejected). TOML files with no pin fail closed
with "no pinned hash — register it".

### CR-04: Workflow never installs `uv`/Python — both steps fail on a fresh runner

**Files modified:** `.github/workflows/registry-gate.yml`
**Commit:** 309a1e0
**Applied fix:** Added `actions/setup-python@v5` (python-version
"3.13", matching `requires-python ==3.13.*`), `astral-sh/setup-uv@v5`,
and `uv sync --frozen` before the re-hash step. Step order verified
in-file (setup → sync → re-hash → negative tests).

### CR-05: `verify_parameter_set` skips every validation `load_parameter_set` enforces

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** 95b5e9d
**Applied fix:** Factored parse-validate-normalize into shared
`_parse_and_validate` (schema, path-vs-content identity, CR-06
required sections, ASCII, whitelist, WR-06 types) used by both entry
points. `verify_parameter_set` now derives identity from the file
path (parent dir + stem, segment-checked) and runs the full
validation before comparing digests. Added
`test_verify_rejects_unknown_key_like_load` and
`test_verify_rejects_renamed_identity` (both raise
`StrategyKeyOutsideRegistry` under verify).

### CR-06: Missing `strategy_version` / `[parameters]` silently default instead of raising

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** a244aa3
**Applied fix:** `load_parameter_set` raises `RegistrySchemaMismatch`
on absent/empty `strategy.strategy_version` or missing/non-dict
`[parameters]` (fail closed; no empty-set hash). Added
`test_missing_strategy_version_raises` and
`test_missing_parameters_table_raises`.

### WR-01: Canonical datetime uses raw `isoformat()` — same instant, different offset, different hash

**Files modified:** `src/domain/canonical.py`
**Commit:** e2bb25a (plus ruff follow-up 2a39721, `datetime.UTC` alias for UP017)
**Applied fix:** `canonical_scalars` normalizes aware datetimes via
`astimezone(UTC).isoformat()`; canonical rendering documented as the
`+00:00` spelling (never `Z`). Verified: `+00:00` vs `+07:00` views
of one instant hash identically; UTC-input digests and the pinned
registry hash are byte-identical to before.

### WR-02: `_require_utc_aware` accepts any aware tz, not UTC

**Files modified:** `src/domain/approval.py`, `src/domain/signal.py`, `src/domain/trade_plan.py`, `src/domain/order.py`, `src/domain/fill.py`, `src/domain/position.py`, `src/domain/journal.py`, `tests/test_domain_entities.py`
**Commit:** 3f0e81f
**Applied fix:** All seven helpers now reject non-UTC offsets
(`value.utcoffset() != timedelta(0)` raises; `None` utcoffset also
fails closed). Kept the per-file helper shape (no new shared module,
minimal churn). Added `test_all_entities_reject_non_utc_aware_datetimes`
locking `+07:00` rejection across all seven entities.

### WR-03: String fields documented as "validated non-empty" are not validated

**Files modified:** `src/domain/signal.py`, `src/domain/trade_plan.py`, `src/domain/order.py`, `src/domain/fill.py`, `src/domain/position.py`, `tests/test_domain_entities.py`
**Commit:** 03fcd09
**Applied fix:** Added local `_require_non_empty` helpers and
`__post_init__` checks for the documented fields plus core IDs
(Signal 9 fields; TradePlan IDs + `entry_model` +
`quantization_decision`; Order 9 fields; Fill 7 fields; Position 4
fields). Docstring promises are now true; Phase 4 can rely on them.
Added `test_documented_string_fields_reject_empty`.

### WR-04: Raw TOML value regex breaks on inline comments and quoted keys

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** c9d6f0d
**Applied fix:** Added `_strip_inline_comment` (cuts at `#` outside
single/double-quoted literals, escape-aware) applied to extracted
values, and extended the key regex with a `"quoted"` alternative.
`zone_tolerance_atr = 0.5  # tuned` now yields `Decimal("0.5")`
instead of `InvalidOperation`. Added
`test_inline_comment_and_quoted_key_load`.

### WR-05: Registry path built from unsanitized inputs — path traversal read

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** 2361c8c
**Applied fix:** `_check_registry_segment` enforces
`[A-Za-z0-9][A-Za-z0-9_-]*` fullmatch on both ids in
`load_parameter_set` (and `verify_parameter_set` after CR-05),
raising `UnregisteredParameterSet` on mismatch — fail closed before
any filesystem access. Added `test_path_traversal_segments_raise_unregistered`.

### WR-06: No per-key type validation — wrong-typed values hash happily

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** 6eef89c
**Applied fix:** Added `INT_KEYS` (count keys: int-only) /
`DECIMAL_KEYS` (ratio/threshold keys: int-or-Decimal, since
whole-number TOML spellings like `minimum_rr = 2.0` normalize to int
2 and the seed must keep loading with an unchanged hash) plus
`_check_param_types`, with explicit bool rejection (bool subclasses
int). Violations raise `StrategyKeyOutsideRegistry` (no new
exception type; API stable). Seed hash unchanged. Added
`test_wrong_typed_values_raise_at_load` (str/bool/list).

### WR-07: `Approval` permits incoherent action/result/status/timestamp combinations

**Files modified:** `src/domain/approval.py`, `tests/test_domain_entities.py`
**Commit:** 9e7e95e
**Applied fix:** Enforced the minimum invariant `PENDING ⟺
acted_at_utc is None` in `__post_init__` (both directions; decided
statuses must carry their transition time). Full transition table
(REQUESTED → APPROVED/SKIPPED/EXPIRED) remains a Phase 4 Telegram-loop
concern, as the review allows. Added
`test_approval_rejects_incoherent_status_timestamps` (both
directions plus the valid decided-approval case).

### WR-08: `JournalEvent.correlation_id` / `entity_id` may be empty

**Files modified:** `src/domain/journal.py`, `tests/test_domain_entities.py`
**Commit:** 88a7766
**Applied fix:** `_require_non_empty` on `correlation_id` and
`entity_id`; `payload_json` must parse as JSON when non-empty
(`""` still means "no payload", preserving the field default).
Added `test_journal_event_rejects_empty_correlation_or_entity_id`
(empty ids, garbage payload, and the `""` default acceptance).

### WR-09: Determinism suites exercise their own helpers, not production code

**Files modified:** `tests/test_no_lookahead.py`, `tests/test_prefix_invariance.py`, `tests/test_candle_close_timing.py`, `tests/test_domain_boundary.py`
**Commit:** fff8471
**Applied fix:** Added one green canary per suite proving the
comparison is sensitive to its bug class: leaky length-binding
fingerprint detected by prefix comparison; stateful counter detected
by run-identical digest comparison; forming-close emission detected
by the absence check; raising helper detected by the never-raises
contract. Phase 4 swaps in real logic with sensitivity already pinned.

### WR-10: No-float static guard misses literals and `Decimal(float)` noise

**Files modified:** `tests/test_domain_no_float.py`
**Commit:** 3247c7c
**Applied fix:** Walker now flags `float(...)` calls, float literals,
`Decimal(<float literal>)` shapes, and numpy floating attrs
(`float16/32/64`, `floating`); TOML floats documented as the known
exception handled by `_normalize_params`. Pre-verified zero float
literals exist on the scanned path, so the tightened guard stays
green. Added `test_float_guard_catches_literals_and_decimal_float`.

### WR-11: Mapper tests are SQLite-only — PG enforcement gaps untested

**Files modified:** `tests/test_domain_mappers_pg.py` (new), `tests/test_domain_mappers.py`
**Commit:** 9e41a6d
**Applied fix:** New live-PG module gated on `TEST_DATABASE_URL`
(skips without it): TIMESTAMPTZ round-trip, String(16) length
enforcement, duplicate-PK and fills `(order_id, exchange_trade_id)`
unique races, NUMERIC(38,18) overflow. SQLite suite header now
records the gap explicitly and points at the PG module.

### WR-12: `check_strategy_key_outside_registry` inspects only top-level keys

**Files modified:** `src/domain/registry.py`, `tests/test_registry_gate.py`
**Commit:** 1057717
**Applied fix:** Ambient scan recurses into nested mappings and
normalizes env-var spelling (case-insensitive full or
`PREFIX_KEY` suffix match), with the naming rule documented in the
helper docstring — D-06 now covers nested/prefixed smuggling, not
just top-level keys. Added nested-dict and `TREND_SWING_LOOKBACK`
tests.

### WR-13: `_normalize_params` ignores floats nested in lists/dicts

**Files modified:** `src/domain/registry.py`, `tests/test_registry.py`
**Commit:** 2aaf91b
**Applied fix:** Added recursive `_normalize_value` (lists/tuples/
dicts; raw TOML spelling applies to top-level scalar floats only,
nested floats use `Decimal(str(...))`). Added
`test_normalize_params_recurses_into_nested_floats` (white-box unit
test: nested values are unreachable via `load` since WR-06 rejects
non-scalar params, so the function is tested directly).

## Skipped Issues

None — all findings were fixed.

---

_Fixed: 2026-09-23T14:17:53+00:00_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
