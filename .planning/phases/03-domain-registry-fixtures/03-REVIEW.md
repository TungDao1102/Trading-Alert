---
phase: 03-domain-registry-fixtures
reviewed: 2026-09-23T00:00:00Z
depth: deep
files_reviewed: 35
files_reviewed_list:
  - .github/workflows/registry-gate.yml
  - params/trend-pullback/baseline-v1.toml
  - pyproject.toml
  - src/db/alembic/versions/0002_domain_registry.py
  - src/db/mappers.py
  - src/db/models.py
  - src/domain/__init__.py
  - src/domain/approval.py
  - src/domain/canonical.py
  - src/domain/enums.py
  - src/domain/fill.py
  - src/domain/ids.py
  - src/domain/journal.py
  - src/domain/order.py
  - src/domain/position.py
  - src/domain/registry.py
  - src/domain/signal.py
  - src/domain/trade_plan.py
  - tests/conftest.py
  - tests/fixtures/phase3/candles.csv
  - tests/fixtures/phase3/expected_plans.json
  - tests/fixtures/phase3/expected_signals.json
  - tests/fixtures/phase3/parameters.json
  - tests/test_candle_close_timing.py
  - tests/test_domain_boundary.py
  - tests/test_domain_entities.py
  - tests/test_domain_enums.py
  - tests/test_domain_ids.py
  - tests/test_domain_mappers.py
  - tests/test_domain_no_float.py
  - tests/test_fixture_harness.py
  - tests/test_no_lookahead.py
  - tests/test_prefix_invariance.py
  - tests/test_registry.py
  - tests/test_registry_gate.py
findings:
  critical: 6
  warning: 13
  info: 6
  total: 25
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-09-23T00:00:00Z
**Depth:** deep
**Files Reviewed:** 35
**Status:** issues_found

## Summary

Deep review of the Phase 03 domain-registry-fixtures slice: canonical hashing,
content-hash IDs, seven frozen domain entities, TOML parameter registry, ORM
mirror + mappers + migration 0002, golden-fixture harness, determinism suites,
and the registry-gate CI workflow. Cross-file tracing (registry → canonical →
IDs → entities → mappers → models → migration; workflow → loader) was performed.

Verified healthy: `parameters.json` pinned hash `e1579900…` reproduces exactly
through `load_parameter_set` (re-ran locally); mapper `approval_from_row`
correctly uses `ApprovalResult` for `status` (matches the domain type —
no bug there); migration/model column parity holds 1:1 including the fills
unique constraint and nullable never-happened timestamps.

Nevertheless the review finds 6 Critical issues that must be fixed before this
code carries real trading identity or gates merges: a cross-strategy SignalId
collision (missing `strategy_id` binding), zero validation on the `Signal`
entity, a vacuous CI re-hash gate, a workflow that cannot run (`uv` never
installed), an under-validating `verify_parameter_set`, and fail-open defaults
for missing `strategy_version`/`[parameters]`. A further 13 Warnings (UTC
normalization, string-field validation gaps, TOML comment fragility, path
traversal, vacuous determinism suites, SQLite-only mapper coverage) and 6 Info
items follow.

## Critical Issues

### CR-01: `make_signal_id` omits `strategy_id` — cross-strategy ID collision

**File:** `src/domain/ids.py:19-42`
**Issue:** The D-03 identity tuple is documented as strategyVersion +
parameterSetId + symbol + timeframe + close + fingerprint, and the function
binds exactly that — but never `strategy_id`. Two different strategies
(e.g. `trend-pullback` vs a future `mean-reversion`) sharing
`strategy_version="v1.0.0"`, `parameter_set_id="baseline-v1"`, symbol,
timeframe, close, and fingerprint produce the **same** `signal_id`. The
registry hash (`registry.py:213-218`) does bind `strategy_id`, so the
parameter sets are distinct while the signals derived from them collide.
Content-hash PKs that collide across strategies risk row overwrites or
mis-attributed plans/orders downstream (all child IDs derive from the parent
signal hash via `derive_child_id`).
**Fix:**
```python
def make_signal_id(
    *,
    strategy_id: str,
    strategy_version: str,
    ...
) -> str:
    return sha256_hex(
        {
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            ...
        }
    )
```
Keep the old scheme out of the codebase — do not accept both shapes. Add a
test that same version/id/symbol/time/close/fingerprint under two
`strategy_id` values yields different digests. Related design gap (at least
document): the signal ID binds `parameter_set_id` but not
`parameter_set_hash`, so a mutated-then-rehashed parameter set with the same
id yields identical signal IDs for semantically different parameters.

### CR-02: `Signal` entity has no validation at all — naive datetimes accepted

**File:** `src/domain/signal.py:21-43`
**Issue:** Every sibling entity (`TradePlan`, `Approval`, `Order`, `Fill`,
`Position`, `JournalEvent`) enforces D-12 in `__post_init__` (Decimal-only,
UTC-aware datetimes). `Signal` — the root identity entity whose
`source_candle_close_utc` feeds `make_signal_id` → canonical hash — has **no
`__post_init__`**. A naive `source_candle_close_utc`/`detected_at_utc`/
`expires_at_utc` constructs silently; the canonicalizer then either raises far
from the boundary (for the close field, inside `sha256_hex`) or, worse,
serializes naive `detected_at_utc`/`expires_at_utc` without an offset wherever
they are hashed downstream, producing unstable or misleading identities.
Compounding this, `tests/test_domain_entities.py:500-549` (`test_all_entities_
reject_naive_datetimes`) covers the other six entities but never constructs a
`Signal` — the gap is untested.
**Fix:**
```python
def __post_init__(self) -> None:
    _require_utc_aware(self.source_candle_close_utc, "source_candle_close_utc")
    _require_utc_aware(self.detected_at_utc, "detected_at_utc")
    _require_utc_aware(self.expires_at_utc, "expires_at_utc")
    if self.invalidated_at_utc is not None:
        _require_utc_aware(self.invalidated_at_utc, "invalidated_at_utc")
```
Add `Signal` to the naive-datetime test.

### CR-03: CI re-hash gate is vacuous — compares a load against itself

**File:** `.github/workflows/registry-gate.yml:32-55`
**Issue:** The "Re-hash registry" step loads each TOML via
`load_parameter_set`, then loads it **again** and compares the two hashes
(`recorded != rehashed`, lines 46-48). Both values come from the same file
through the same code path in the same second, so they agree by construction
unless the file changes mid-step (TOCTOU). A mutated seed TOML passes this
gate: both loads hash the mutated content identically. The gate never compares
against the pinned `tests/fixtures/phase3/parameters.json` hash or calls
`verify_parameter_set(path, expected_hash)`, which is the actual D-04/D-05
tripwire (covered only in unit tests, not in CI).
**Fix:**
```python
import json

pinned = json.loads(Path("tests/fixtures/phase3/parameters.json").read_text())
ps = load_parameter_set(strategy_id, parameter_set_id)
assert ps.parameter_set_hash == pinned["parameter_set_hash"], f"{toml_path} mutated"
```
or iterate pinned sets and call `verify_parameter_set(toml_path, expected_hash)`.

### CR-04: Workflow never installs `uv`/Python — both steps fail on a fresh runner

**File:** `.github/workflows/registry-gate.yml:11-61`
**Issue:** Both steps invoke `uv run python` / `uv run pytest`, but the job
has no `actions/setup-python` and no `astral-sh/setup-uv` step. `ubuntu-latest`
runners do not ship `uv` on PATH by default, so `uv: command not found`
fails the gate on every run (or, if a preinstalled `uv` exists, the Python
version is uncontrolled — `pyproject.toml` pins `requires-python ==3.13.*`
while the environment here resolves `python --version` → 3.14.3, under which
`datetime.fromisoformat("...Z")` behavior and TOML/fixture assumptions are
unverified). A gate that cannot execute is fail-open by absence.
**Fix:**
```yaml
- uses: actions/setup-python@v5
  with: { python-version: "3.13" }
- uses: astral-sh/setup-uv@v5
- run: uv sync --frozen
```
before the re-hash step.

### CR-05: `verify_parameter_set` skips every validation `load_parameter_set` enforces

**File:** `src/domain/registry.py:230-253`
**Issue:** `load_parameter_set` validates schema version, strategy/path
identity, ASCII keys, and the unknown-key whitelist; `verify_parameter_set`
re-hashes with **none** of those checks. Consequences: (a) a file with an
unknown strategy-semantic key or wrong `schema_version` can pass `verify`
while `load` rejects it (or vice versa — the two gates disagree on what a
valid registry file is); (b) `verify` binds `strategy.get("strategy_id","")`
from the file while `load` binds the path-derived `strategy_id`, so a
renamed/copied file verifies against a different identity than it loads
under. The mutation test (`test_registry.py:171-203`) only flips one digit,
so this divergence is untested.
**Fix:** Factor the parse-validate-normalize path into one helper used by both
functions (validate schema, identity, ASCII, whitelist in `verify` too), with
`verify` additionally comparing the digest. Add a test: unknown key added to a
copied TOML must raise under `verify`, not just under `load`.

### CR-06: Missing `strategy_version` / `[parameters]` silently default instead of raising

**File:** `src/domain/registry.py:196-208`
**Issue:** `strategy_version = strategy.get("strategy_version", "")` and
`params = doc.get("parameters", {})` fail open: a TOML missing the version or
the entire `[parameters]` table loads successfully with an empty version /
empty params and produces a stable-looking hash over nothing. An accidentally
truncated file becomes a valid, hashable, empty parameter set. Fail-closed
(D-04/D-05) requires rejection of absent identity/semantic sections.
**Fix:**
```python
if "strategy_version" not in strategy or not strategy["strategy_version"]:
    raise RegistrySchemaMismatch(f"{path}: missing strategy.strategy_version")
if "parameters" not in doc or not isinstance(doc["parameters"], dict):
    raise RegistrySchemaMismatch(f"{path}: missing [parameters] table")
```
Add tests for both truncations.

## Warnings

### WR-01: Canonical datetime uses raw `isoformat()` — same instant, different offset, different hash

**File:** `src/domain/canonical.py:46-49`
**Issue:** Any aware datetime passes, and its `isoformat()` (with its original
offset) is hashed. `2026-09-19T12:00:00+00:00` and the same instant as
`2026-09-19T19:00:00+07:00` hash differently, so identical market instants
produce different SignalIds/plan hashes depending on caller timezone
representation. Determinism (same snapshot → same decision, byte-equivalent)
requires normalizing to UTC first.
**Fix:** `return value.astimezone(timezone.utc).isoformat()` (and document the
`"Z"` vs `"+00:00"` spelling — `fromisoformat` round-trips both on 3.11+, but
pick one canonical rendering explicitly).

### WR-02: `_require_utc_aware` accepts any aware tz, not UTC

**File:** `src/domain/approval.py:20-23`, mirrored in `trade_plan.py`,
`order.py`, `fill.py`, `position.py`, `journal.py`
**Issue:** The check is `value.tzinfo is None` → reject; a `+07:00`-aware
datetime passes a function named "require UTC". Combined with WR-01, non-UTC
aware datetimes flow into hashes and DB rows. Either rename to
`_require_aware` (if any tz is genuinely acceptable) or enforce
`value.utcoffset() == timedelta(0)`.
**Fix:** Enforce UTC and update the six copies (or share one helper — six
duplicated copies of the same 4-line function is itself duplication worth
collapsing into one import).

### WR-03: String fields documented as "validated non-empty" are not validated

**File:** `src/domain/order.py:76-87`, `src/domain/position.py:60-74`, `src/domain/signal.py`, `src/domain/fill.py:56-67`, `src/domain/trade_plan.py:70-85`
**Issue:** `Order`'s docstring promises `order_role`/`side`/`position_side`/
`order_type`/`time_in_force` are "validated non-empty strings", `Position`
promises the same for `position_side`/`mode`, `TradePlan` for
`entry_model`/`quantization_decision` — but the `__post_init__` methods check
only Decimals and datetimes. Empty-string `side=""`, `symbol=""`,
`direction=""` all construct successfully and can be persisted via the total
mappers. Only `JournalEvent.event_type`/`entity_type` actually enforce
non-empty. Either implement the validation or correct the docstrings before
Phase 4 relies on the promise.
**Fix:** Add `_require_non_empty` checks for the documented fields (share the
helper from `journal.py`).

### WR-04: Raw TOML value regex breaks on inline comments and quoted keys

**File:** `src/domain/registry.py:94-119`
**Issue:** `_extract_raw_param_strings` captures `value = match.group(2).strip()`
verbatim, including trailing comments: `zone_tolerance_atr = 0.5  # tuned`
yields raw `"0.5  # tuned"` → `Decimal("0.5  # tuned")` raises
`decimal.InvalidOperation` (an untyped, confusing error, not a registry
exception). Quoted keys (`"lookback_ñ" = 10`, as used in the non-ASCII test)
don't match `^([A-Za-z0-9_\-]+)` at all, so raw strings silently miss them
and fractional quoted-key values fall back to `Decimal(str(float))` with
binary noise — the trailing-precision guarantee becomes spelling-dependent.
**Fix:** Strip inline comments outside string literals (or use
`tomllib` + `Decimal` via a documented TOML_FLOAT→string pass), and support
quoted keys in the regex (`^"([^"]+)"\s*=` alternative).

### WR-05: Registry path built from unsanitized inputs — path traversal read

**File:** `src/domain/registry.py:176`
**Issue:** `REGISTRY_ROOT / strategy_id / f"{parameter_set_id}.toml"` with no
charset validation: `load_parameter_set("../../etc", "x")` escapes `params/`
and reads/parses an arbitrary file as TOML. Impact is local-file read +
`tomllib` parse (low severity, no secrets returned to a remote caller in V1),
but it violates the fail-closed posture and makes error messages probeable.
**Fix:** Validate `re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", ...)` on both
segments and raise `UnregisteredParameterSet` on mismatch.

### WR-06: No per-key type validation — wrong-typed values hash happily

**File:** `src/domain/registry.py:196-207`
**Issue:** Membership in `STRATEGY_KEYS` is the only check:
`swing_lookback = "20"` (string), `risk_rate = true` (bool — and
`True == 1` in Python, so equality-based tests can confuse it with int),
`signal_expiry_hours = [4]` all load and hash. The type error surfaces late
in Phase 4 arithmetic instead of at the registry boundary.
**Fix:** Add an expected-type table (int keys vs Decimal keys) and raise
`StrategyKeyOutsideRegistry` (or a dedicated `RegistryTypeMismatch`) at load.

### WR-07: `Approval` permits incoherent action/result/status/timestamp combinations

**File:** `src/domain/approval.py:27-57`
**Issue:** `action`, `result`, `status`, `acted_at_utc` are independent with
no transition invariant: `status=PENDING` with `acted_at_utc` set,
`status=APPROVED` with `acted_at_utc=None`, `action=CANCEL` with
`result=APPROVED` all construct. The docstring says "`status` alone answers
state (D-11)" but nothing enforces coherence, so idempotent-replay logic in
later phases cannot trust the entity. The mapper round-trip test pins
`PENDING/None` only.
**Fix (Phase 4 or now):** Enforce at minimum `PENDING ⟺ acted_at_utc is None`
in `__post_init__`; document the full transition table (REQUESTED → APPROVED /
SKIPPED / EXPIRED) before the Telegram callback loop lands.

### WR-08: `JournalEvent.correlation_id` / `entity_id` may be empty

**File:** `src/domain/journal.py:40-61`
**Issue:** The model docstring states "every event must be correlatable" via
`correlation_id`, but only `event_type`/`entity_type` are non-empty-checked.
`correlation_id=""`, `entity_id=""`, `payload_json` garbage all construct.
An empty correlation id silently breaks the audit-trail join the journal
exists to provide.
**Fix:** `_require_non_empty(self.correlation_id, ...)` and
`_require_non_empty(self.entity_id, ...)`; optionally validate `payload_json`
parses as JSON.

### WR-09: Determinism suites exercise their own helpers, not production code

**File:** `tests/test_no_lookahead.py:32-50`, `tests/test_prefix_invariance.py:32-46`, `tests/test_candle_close_timing.py:33-47`, `tests/test_domain_boundary.py:21-29`
**Issue:** `_signal_entries` (per-candle independent loop) and
`_placeholder_decide` are test-local functions. Prefix-invariance and
no-lookahead hold **by construction of the helper** — the suites cannot fail
no matter how broken the real Phase 4 pipeline is. They pin the invariant
statement, not the mechanism, and give false confidence if read as coverage
of strategy code. Acknowledged as D-09 placeholders, but the REVIEW must
record that zero production lines are covered by these four files.
**Fix:** Keep, but assert each suite fails if the helper is made stateful
(e.g. a test that injects a lookahead leak into the helper and asserts
detection), so the suite is proven capable of catching the bug class before
Phase 4 swaps in real logic.

### WR-10: No-float static guard misses literals and `Decimal(float)` noise

**File:** `tests/test_domain_no_float.py:34-58`
**Issue:** The AST walker flags only `float(...)` call nodes. It misses float
literals (`x: Decimal = 0.5` — fails only at runtime via the dataclass guard),
`Decimal(0.5)` (constructs from binary float — silent precision noise, the
exact failure mode D-12 exists to prevent), `numpy.float64`, and
`tomllib`-produced floats that escape `_normalize_params` via nested
structures (see WR-13). A green guard does not mean float-free.
**Fix:** Also flag `ast.Constant` float values and `Decimal(<float>)` call
shapes in scanned files; document that TOML floats are the known exception
handled by normalization.

### WR-11: Mapper tests are SQLite-only — PG enforcement gaps untested

**File:** `tests/test_domain_mappers.py:78-94`
**Issue:** SQLite does not enforce `VARCHAR(n)` lengths, drops tzinfo, and
stores NUMERIC as REAL (the file's own `CapturingSession` docstring admits
both). Consequences untested: overlong status strings (e.g. 20-char status
into `String(16)`) pass in tests but fail/truncate on PG; timezone loss on
round-trip through a real DB; `NUMERIC(38,18)` overflow; duplicate-PK and
fills `(order_id, exchange_trade_id)` unique-constraint races; FK-less orphans
(there are no DB FKs — see IN-05). The `CapturingSession` snapshot covers
mapper output, not DB behavior.
**Fix:** Add a live-PG-gated test module (skipped without `TEST_DATABASE_URL`)
covering length enforcement, tz round-trip, unique-constraint violation, and
38,18 overflow; record the gap explicitly in the file header until then.

### WR-12: `check_strategy_key_outside_registry` inspects only top-level keys

**File:** `src/domain/registry.py:256-272`
**Issue:** `set(ambient.keys()) & STRATEGY_KEYS` catches `{"swing_lookback":
50}` but not nested smuggling (`{"strategy": {"swing_lookback": 50}}`,
`{"parameters": {...}}`) or prefixed env-var forms (`TREND_SWING_LOOKBACK`).
D-06 claims ambient strategy-semantic keys "raise instead of silently
altering semantics" — the check covers only the shallowest shape.
**Fix:** Recurse into nested mappings (and document the env-var naming rule
so the check can normalize it), or narrow the D-06 claim to top-level keys.

### WR-13: `_normalize_params` ignores floats nested in lists/dicts

**File:** `src/domain/registry.py:122-150`
**Issue:** Only top-level `isinstance(value, float)` is converted. A
list/dict-valued parameter containing floats (legal TOML) reaches
`canonical_scalars` → `TypeError("float in canonical hash input")` at hash
time — a fail-closed but mistyped and message-poor failure far from the
boundary. Bool-subclass subtlety also unhandled (see WR-06).
**Fix:** Recurse `_normalize_params` into lists/tuples/dicts.

## Info

### IN-01: Barrel export omits half the public registry API

**File:** `src/domain/__init__.py:29-69`
**Issue:** `ParameterSetMutated`, `check_strategy_key_outside_registry`,
`SCHEMA_VERSION`, `STRATEGY_KEYS`, `REGISTRY_ROOT` are importable from
`src.domain.registry` (and used by tests that way) but absent from the barrel
whose docstring claims "re-exports the public symbols". Inconsistent import
surface for Phase 4.
**Fix:** Export the full public set or document that registry internals stay
outside the barrel.

### IN-02: `pyproject.toml` mypy `files` key is not a valid config option

**File:** `pyproject.toml:75-82`
**Issue:** `[tool.mypy] files = ["src"]` — `files` is a command-line
positional, not a recognized mypy config-file key (mypy warns
`Unrecognized option`). Harmless if mypy is invoked as `mypy src`, but the
config suggests the author believes it scopes the run.
**Fix:** Remove `files` (invoke `mypy src` explicitly, e.g. in CI/pre-commit)
or use `mypy_path`/`exclude` as appropriate.

### IN-03: Fixture digest tripwire is tautological today

**File:** `tests/test_fixture_harness.py:143-166`
**Issue:** `test_harness_output_matches_expected_files_digest_exactly`
compares `sha256_hex({"signals": []})` (test-local empty list) against
`sha256_hex({"signals": <contents of expected_signals.json>})` where the file
is `{"signals": []}` — both sides are empty by construction. It pins the
placeholder bytes (any edit trips it, as intended) but verifies no
candle→signal computation. Fine as a D-09 placeholder; must be replaced by a
real pipeline-output comparison in Phase 4, not merely re-pinned.
**Fix:** No change now; Phase 4 must wire the real harness output into this
test rather than regenerating digests around it.

### IN-04: `JournalEventRow.created_at_utc` nullable while sibling timestamps are not

**File:** `src/db/models.py:448-450`, `src/db/alembic/versions/0002_domain_registry.py:227`
**Issue:** Migration and model agree (`nullable=True`), so no parity bug —
but an append-only audit event with NULL creation time is semantically odd
next to non-nullable `created_at_utc`/`occurred_at_utc` elsewhere. If NULL
means "not yet persisted", document it; otherwise make non-nullable with a
server default.
**Fix:** Document or tighten in a future migration (not this one — 0002 is
already the schema authority).

### IN-05: No DB-level FK or check constraints on domain tables

**File:** `src/db/models.py:190-451`, `src/db/alembic/versions/0002_domain_registry.py:32-241`
**Issue:** `signal_id`/`trade_plan_id`/`order_id` linkages are logical only —
no `ForeignKey`, no status check constraints, no FK indexes beyond the three
created. Orphan trade_plans/orders/fills are insertable. Likely deliberate
(keep Phase 3 storage-half minimal, enforce in application), but unrecorded:
a reader cannot tell intent from omission.
**Fix:** Record the decision (application-enforced linkages + reconciler
ownership) in the models module docstring, or add FKs in a later migration.

### IN-06: `derive_child_id` discriminator uniqueness is convention-only

**File:** `src/domain/ids.py:45-56`
**Issue:** Entry/SL/TP orders for the same signal need distinct
discriminators (`"order:entry"`, …) or they collide to one ID. The function
cannot enforce this; the `"trade_plan:v1"` example is the only anchor. A
Phase 4 caller reusing one discriminator for two children silently merges
their identities.
**Fix:** Publish the discriminator registry (constants, not free strings) in
Phase 4; consider binding `order_role` into the payload.

---

_Reviewed: 2026-09-23T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
