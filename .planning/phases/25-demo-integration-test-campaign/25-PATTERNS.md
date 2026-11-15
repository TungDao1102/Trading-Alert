# Phase 25: Binance Demo Integration Test Campaign - Pattern Map

**Mapped:** 2026-11-07
**Files analyzed:** 14 (new or modified)
**Analogs found:** 13 / 14 (soak evaluator: partial)

All analog paths were checked as tracked source (they live under `tests/`, `src/`, `scripts/`). The
`demo` skip hook must NOT go through `infra_skip` (it would turn into a FAILURE under
`TRADING_CI_STRICT=1`).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `tests/support/demo_scenarios/*.py` (`s01_happy` ... `s20`, `catalog.py`, `evidence_index.py`) | scenario fn | request-response / event-driven | `scripts/demo_rehearsal.py` `run_composed_smoke` + `SmokeEnv` (2314-2342) | role-match |
| `tests/support/fault_edge.py` | test double (exchange edge wrapper) | request-response | `ComposedExchangeEdge` + `edge()` in `tests/support/live_composed_rig.py:362-369` | exact |
| `tests/support/demo_env.py` (Demo factory; name free, may live in fault_edge) | env factory | request-response | `build_fake_smoke_env` `tests/support/live_smoke_env.py:152` and `default_assemble` `src/live/runtime.py:468-482` | role-match |
| `tests/demo/conftest.py` | fixture / env guard | config | `admit_smoke_environment` (`scripts/demo_rehearsal.py:2364`) | role-match |
| `tests/demo/test_demo_sNN_*.py` | test (owner-run) | request-response | `tests/test_live_demo_smoke.py` (imports `scripts.demo_rehearsal as dr`) | role-match |
| `tests/test_demo_twin_*.py` | test (CI twin) | request-response | `tests/test_live_demo_smoke.py:31-50` (`forbid_real_sleep`, `build_fake_smoke_env`) | exact |
| `tests/test_phase25_gate.py` | test (structural gate) | batch | `tests/test_phase24_gate.py` | exact |
| `tests/test_demo_no_branch_guard.py` (D-08 allow-list; may sit in gate) | test (AST guard) | transform | `tests/test_live_ast_guards.py:35-41,237-243` | exact |
| `tests/conftest.py` (collection hook) | config | event-driven | no hook exists; RESEARCH "Collection hook" snippet | no analog |
| `pyproject.toml` (`demo` marker) | config | n/a | `pyproject.toml:55-57` (`docker` marker) | exact |
| `src/persistence/uow.py` (R-24) | service/UoW | CRUD | itself, lines 39-52 | exact |
| `src/live/health.py` (R-25) | service | event-driven | itself, `health_tick_once` 481-512 | exact |
| `scripts/evaluate_demo_soak.py` | script/CLI | batch | `scripts/evaluate_trial_soak.py` (argparse `_parser`/`main`, line 77/131), `scripts/export_soak_evidence.py` (manifest+sha256) | partial |
| `docs/operations/DEMO_VS_MAINNET.md` | doc | n/a | `docs/operations/RUNBOOK.md` (+ evidence-label style of `09-EXCHANGE-FACTS.md`) | role-match |

## Pattern Assignments

### `tests/support/fault_edge.py` (test double, request-response)

**Analog:** `tests/support/live_composed_rig.py:362-369` over the production seam
`src/live/wiring.py:554-557`.

```python
def edge(bundle: ExchangeBundle) -> ExchangeBundle:
    composed = ComposedExchangeEdge(real=bundle.adapter, fake=fake, day_reader=day_reader)
    holder["edge"] = composed
    return dataclasses.replace(
        bundle,
        adapter=composed,  # type: ignore[arg-type]
        public=FakePublic(fake, bundle.gate),  # type: ignore[arg-type]
    )
```
```python
if exchange_edge is not None:
    # production passes None. It may replace the signed adapter and the public reader, never the gate.
    self.exchange = exchange_edge(self.exchange)
```
Copy: a wrapper with `__getattr__` routing by method name (as `ComposedExchangeEdge`) that applies
fault modes (`raise_before_send`, `mutate_payload`, `drop_response_after_send`, `hold/release`,
`stale_mark`) then delegates to `real`. Return it via `dataclasses.replace(bundle, adapter=...)`.
Never edit `src`. The fake already has `hold/release/fail_next/reject_next_algo` for the CI twin.
Demo factory must call `build_wiring(exchange_edge=...)` directly: `default_assemble` does not pass it.

---

### `tests/support/demo_scenarios/*.py` (scenario fn, request-response)

**Analog:** `scripts/demo_rehearsal.py:2314-2342` `SmokeEnv`; extend by subclass, as
`tests/support/live_smoke_env.py:54-59` does:
```python
@dataclass
class FakeSmokeEnv(SmokeEnv):
    fake: Any = None
    rig: ComposedRig | None = None
```
Shape: `async def run(env, recorder)` (same signature for twin and Demo). Presses go through
`FakeOwner.act` (`live_smoke_env.py:83-107`): `rig.press("APR"|"CNF", short_id, query_id=...)`,
then `await rig.wiring.service.drain()` after CNF. Precondition step (flat account, no stale
plan) and ending `account_clean` per Pitfall 8. Evidence via `dr.EvidenceRecorder` (labels
`SYNTHETIC`, `DEMO_OBSERVED`, add `DEMO_FAULT_INJECTED`); never write a new JSON writer.
Never `import` from `scripts` into `src` (the live AST guard forbids it; tests may).

---

### `tests/test_demo_twin_*.py` (CI twin)

**Analog:** `tests/test_live_demo_smoke.py:9-50`
```python
import pytest
from scripts import demo_rehearsal as dr
from tests.support.live_rig import forbid_real_sleep
from tests.support.live_smoke_env import build_fake_smoke_env

@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)

def _recorder(environ=None) -> dr.EvidenceRecorder:
    return dr.EvidenceRecorder(mode=dr.RunMode.DRY_RUN, scenario=dr.SCENARIO_SMOKE,
        symbol=dr.SYMBOL, base_url=dr.DEMO_BASE_URL, environ=environ or {}, clock=lambda: FAKE_NOW)

async def _run(tmp_path, recorder):
    env = build_fake_smoke_env(tmp_path)
    outcome = await dr.run_composed_smoke(env, recorder)
```
Use `SENTINELS` (fake key/secret strings, lines 24-28) to assert evidence scrubbing. Docstring
convention: `TEST_ONLY:` and "labelled SYNTHETIC; nothing here is Demo-observed".

---

### `tests/demo/conftest.py` + `tests/demo/test_demo_*.py` (owner-run)

**Analog:** RESEARCH "Env guard" snippet over `admit_smoke_environment`
(`scripts/demo_rehearsal.py:2364-2379`), `assert_demo_base_url` (375), `demo_guarded_sdk_factory`
(2345). Credential names: `BINANCE_DEMO_API_KEY/SECRET` (`src/adapters/binance_client.py:265-276`).
```python
@pytest.fixture(scope="session", autouse=True)
def _demo_guard() -> None:
    if [n for n in os.environ if n.startswith("BINANCE_LIVE_")]:
        pytest.fail("BINANCE_LIVE_* present: refusing to run the Demo suite", pytrace=False)
    from scripts.demo_rehearsal import admit_smoke_environment
    admit_smoke_environment(os.environ)
```
Every test function carries `@pytest.mark.demo` (or module `pytestmark`); refuse xdist (one
listenKey per account). Thin tests: build env, call the shared scenario.

---

### `tests/conftest.py` collection hook (no analog; follows pytest docs)

Current file has only fixtures and `from tests import infra_helpers`. Add (RESEARCH snippet):
```python
def pytest_collection_modifyitems(config, items):
    expr = (config.getoption("markexpr") or "").replace(" ", "")
    if "demo" in expr and "notdemo" not in expr and os.environ.get("TRADING_DEMO_RUN") == "1":
        return
    skip = pytest.mark.skip(reason="demo scenario: owner-run only")
    for item in items:
        if item.get_closest_marker("demo") is not None:
            item.add_marker(skip)
```
Plain `skip`, not `infra_skip`. Needs `os` import. Reason: CI/AGENTS `-m "not docker"` does not
exclude `demo`.

### `pyproject.toml` marker

**Analog:** lines 55-57:
```toml
markers = [
  "docker: needs a reachable Docker daemon and the built trading-alert images (cutover, backup drill, image checks)",
]
```
Add `"demo: owner-run Binance Demo scenario; skipped unless -m demo with TRADING_DEMO_RUN=1"`.

---

### `tests/test_phase25_gate.py` and D-08 guard

**Analog:** `tests/test_phase24_gate.py` (docstring lists inventory, requirement-to-test via `ast`,
decision table, register; lines 1-25; `ROOT`/`PHASE_DIR` at 41-42; frozenset inventory at 49-78;
`PHASE24_OTHER_FILES` tuple at 81). Imports:
```python
import ast, re
from pathlib import Path
import pytest
from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls
```
Copy: `REQUIREMENT_TESTS` resolved with `ast` (never imported), scenario catalog id to twin test,
demo test, DEMO_VS_MAINNET row; guard that each `tests/demo` test has the `demo` mark.
For D-08 copy the allow-list style of `tests/test_live_ast_guards.py:35-37`:
```python
WALL_CLOCK_EDGE_ALLOW_LIST: dict[str, str] = {
    "src/live/runtime.py": "CLI edge reads the process clock",
}
# test: reason.strip() != "" and path startswith "src/live/"
```
Pin the files in `src/live` containing `Environment.DEMO` (enablement.py, startup.py, wiring.py,
wiring_parts.py, smoke_injection.py) with a reason each, and assert zero in `src/execution` and
`src/risk` (Pitfall 4). A new `src/live` module requires updating `LIVE_MODULES` in the Phase 24 gate.

---

### `src/persistence/uow.py` (R-24)

**Analog:** itself, `transaction()` lines 39-52. Add before `except IntegrityError`/`DBAPIError`:
```python
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
...
        except SQLAlchemyTimeoutError:
            raise StoreUnavailable("PostgreSQL pool exhausted (TimeoutError)") from None
```
Keep the convention: type names only, `from None` (the SQL text/params leak otherwise). Existing
imports at line 14 are `DBAPIError, IntegrityError, InterfaceError, OperationalError`. Test: engine
`pool_size=1, max_overflow=0, pool_timeout=1`, hold a connection, expect `StoreUnavailable`
(`*_pg.py` style if real PG is needed; `TEST_DATABASE_URL`).

### `src/live/health.py` (R-25)

**Analog:** itself, `health_tick_once` 481-512:
```python
    results = producer.produce(now_utc=now_utc)
    verdict = producer.verdict(results)
    producer._latest = verdict          # stored BEFORE any write: keep this order
    ...
    for result in results:
        await record(health_check_event(result, extra=extra))
    await record(_verdict_event(verdict, now_utc, diag))
```
Change: keep the one `HEALTH_VERDICT` row per tick (it keeps `db_writes` fresh; `DB_WRITE_MAX_AGE`
60 s, `src/live/wiring.py:168`, `self.record = self.db_writes.track(write_journal)` at 533); write the
ten `HEALTH_CHECK` rows only on first tick, a status change, or every N-th tick (needs per-check
last-status state on the caller or producer). Journal ids use `content_hash_event_id(...)`
(`_verdict_event`, 464-471), so an unchanged payload is deterministic.

---

### `scripts/evaluate_demo_soak.py` (partial analog)

**Analogs:** `scripts/evaluate_trial_soak.py` (`_parser()` at 77, `main(argv, *, <injected seam>) -> int`
at 131; injectable dependency parameter as `parity=`) and `scripts/export_soak_evidence.py`
(manifest, SHA-256, create-only publish; pattern only, paper epoch logic not reusable). Follow
module conventions: `from __future__ import annotations`, `argparse`, `main(argv) -> int`, injected
clock. Contract is in RESEARCH "Soak registration check". Enumerate real journal event names from
`src/domain/journal.py` first; names confirmed so far: `OPERATIONAL_ALERT`, `ALERT_DELIVERED`,
`ALERT_SEND_FAILED`, `HEALTH_VERDICT`, `HEALTH_CHECK`, `DEMO_SIGNAL_COMMAND`.

### `docs/operations/DEMO_VS_MAINNET.md`

No code analog. Structure: one table, a row per difference (liquidity, fills, filters, fees,
resets, stream behaviour), columns: difference, evidence label (`DEMO_OBSERVED`, `DOCS`,
`NOT_OBSERVED`, plus `DEMO_FAULT_INJECTED` if used), source (evidence file or order id),
Phase 26 implication. English only. Docs may be CRLF-sensitive: edit bytes-aware.

## Shared Patterns

### Fakes only at the edges
**Source:** `src/live/wiring.py:554-557` seam; `tests/support/live_composed_rig.py:340-369`
(`make_composed_rig(tmp_path, stores=, clock=, fake=, session_id=)`; restart passes the SAME
`stores`, `clock`, `fake`). **Apply to:** all twins and fault edge.

### Evidence recording and scrubbing
**Source:** `scripts/demo_rehearsal.py` `EvidenceRecorder` (480-637, atomic write, post-write secret
scan), `src/ops/redaction.py`. **Apply to:** every scenario and the soak index.

### No real sleep, virtual clock
**Source:** `tests.support.live_rig.forbid_real_sleep`; `rig.clock.advance(n)`;
`tests/support/virtual_time.py`. **Apply to:** all twins. No wall clock in `src` (inject).

### Tick order for the composed process
**Source:** `tests/support/live_smoke_env.py:40-49,168-182` (`_TICK_TASKS`; `specs[name].run()`;
`_set_prices` stamps fake marks with the clock). **Apply to:** twins that need task cadence.

### Owner-only execution
**Apply to:** all `tests/demo` and soak. Agents run only the twins; no `--execute`, no signed
call. A refused CONFIRM leaves a plan APPROVED about 26 min: scenarios start from a clean
precondition and failures print the `scripts/demo_clear.py` instruction.

## No Analog Found

| File | Role | Reason |
|---|---|---|
| `tests/conftest.py` `pytest_collection_modifyitems` | config | No collection hook exists in the repo; use the pytest-docs pattern in RESEARCH |
| `evaluate_demo_soak.py` journal evaluation logic | script | Existing soak evaluators read paper-runtime epochs, not the live journal (Pitfall 2) |
| `DEMO_FAULT_INJECTED` evidence label | evidence | Only `SYNTHETIC` and `DEMO_OBSERVED` exist (`scripts/demo_rehearsal.py:2269-2270`) |

## Metadata

**Analog search scope:** `tests/support/`, `tests/`, `scripts/`, `src/live/`, `src/persistence/`, `pyproject.toml`
**Files read:** 9 (plus RESEARCH.md); line numbers verified this session; no code run, no signed call
**Pattern extraction date:** 2026-11-07
