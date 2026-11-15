# Phase 25: Binance Demo Integration Test Campaign - Research

**Researched:** 2026-11-07
**Domain:** Fault-injection scenario suite on Binance Demo Trading (USD-M Futures), owner-run campaign, multi-week Demo soak, Demo-vs-mainnet record. Python 3.13, `uv`, pytest 9.1.1, no new dependency.
**Confidence:** HIGH on the in-repo harness, seams and conflicts (every one read this session); MEDIUM on Binance Demo behaviour (docs and earlier Demo evidence only; nothing was run, no signed call was made).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

`[auto]` marks a choice made without asking, using the recommended option. Each is grounded in AGENTS.md, the
ROADMAP entry or Phase 24 artifacts. The owner may overrule any of them in review.

#### Who runs what (hard rule)
- **D-01 [auto]:** Any step that sends an order or any signed request to Binance Demo (`--execute`, `pytest -m demo`, soak start) is run **by the owner only**. Agents write, review and dry-run the suite against fakes; they never run it. Source: AGENTS.md "Demo smoke/probe scripts (--execute) are run by the owner only". - **Reversibility:** reversible - a process rule.
- **D-02 [auto]:** Every agent-run test in this phase uses fakes or the project's own stores (`tests/support/`, fake exchange), as in Phase 24.

#### Suite shape (criterion 1)
- **D-03 [auto]:** Register a `demo` pytest marker; the default and CI selection (`-m "not docker"`) excludes it, and a guard test fails if a `demo`-marked test is collected without the marker. Credentials come from `BINANCE_DEMO_*` env names only; the suite refuses to start if any `BINANCE_LIVE_*` variable is present or the base URL is not `demo-fapi.binance.com`. - **Reversibility:** costly - marker and env names become the owner's run procedure.
- **D-04 [auto]:** Reuse the Phase 24 harness (`scripts/demo_rehearsal.py`, `tests/support/live_rig.py`, the fake exchange) instead of a second framework. Scenario results are recorded as evidence JSON under the phase `evidence/` directory with the `DEMO_OBSERVED` label, the same shape as the Phase 24 smoke files.
- **D-05 [auto]:** One scenario per ROADMAP bullet (happy path, partial fill, -2021 before placement, SL rejected after fill, cancel racing a fill, replayed APPROVE/CONFIRM, restart at three points, WS disconnect and listenKey expiry, clock skew, 418/429, DB outage during a risk-reducing action, DAILY_STOP, liquidation-guard and margin rejections, SAFE_MODE entry and exit, foreign order and doubled position). Each scenario first gets a fake-exchange twin that runs in CI, so the logic is tested before the owner spends Demo time.
- **D-06 [auto]:** Add the three RUNBOOK drills the ROADMAP list omits (G2-016): manual close outside the system, stale feed, unprotected-position drill; and the P20-DEMO operator-command scenarios (`rest_gate_cli status/clear` after a false restriction).
- **D-07 [auto]:** Questions only Demo can answer are scenarios with an explicit evidence label and a NOT_OBSERVED default until the owner runs them: A2 (GTD expiry terminal status), A3 (does Binance cancel `closePosition` legs when the position closes), whether a real 418 ban outlives 259200 s, 429/418 queue order, B2/B3 same-id stop re-place, user-data stream states used by SAFE_MODE exit row 7.

#### Same code path as live (criterion 2)
- **D-08 [auto]:** No Demo-only branch in `src/execution`, `src/live` or `src/risk`. Only the endpoint and keys differ, enforced by an AST or wiring test. Demo runs in a DEGRADED health state are never evidence of live readiness (D056): scenarios and soak also run healthy.

#### Soak (criterion 3)
- **D-09 [auto]:** Pre-register the soak before it starts: duration (minimum 21 days), symbols (live-5 universe), pass criteria (zero unexplained local-vs-exchange divergence, zero position without an exchange-side SL, zero duplicate entry, every alert explained) and the restart rule (any defect restarts the clock after the fix). The registration is a committed file with a hash, written before the first soak order. The soak is started and stopped by the owner.
- **D-10 [auto]:** The soak reuses the Phase 16/24 soak tooling (`scripts/export_soak_evidence.py`, `soak_host_acceptance.py`, `deploy/` soak scripts) rather than new tooling.
- **D-11 [auto]:** Before the soak, reduce the health-tick journal volume (R-25, about 63,000 rows a day): write on change only or lengthen the cadence, with a test.

#### Demo-vs-mainnet differences (criterion 4)
- **D-12 [auto]:** A single document `docs/operations/DEMO_VS_MAINNET.md` lists each difference (liquidity, fills, filters, fees, resets) with an evidence label (DEMO_OBSERVED, DOCS, NOT_OBSERVED), and Phase 26 reads it. Fill the "Demo cross-check" lines of `09-EXCHANGE-FACTS.md` from recorded Demo order ids (G2-030).

#### Inherited code items that gate the campaign
- **D-13 [auto]:** R-25 (health tick volume) and R-24 (wrap a pool-exhaustion TimeoutError as `StoreUnavailable`) are small and are done in this phase before the soak.
- **D-14 [auto]:** R-23, R-28 and the other Info-level review items stay deferred unless a scenario exposes them.

#### OWNER decisions (NOT decided here)
- **OWNER-1 (R-21 / WR-03):** margin reservations never advance (`mark_placed`, `mark_open` have no caller). The recommendation agreed 2026-11-07 is to stamp `mark_placed` at the acknowledgement and `mark_open` at the first fill through `StoreExecutor.write`, but it needs a DECISIONS row first. Planning may prepare the plan; execution waits for the row.
- **OWNER-2 (R-22 / WR-04):** cancel-on-stop for the live process touches D079 and the never-resend rule; needs an owner decision. The interim stop procedure (RUNBOOK 22.5) applies; restarting the process during the campaign follows it.
- **OWNER-3 (P20-ERR1003):** parsing the text of Binance error -1003 needs an owner exception to D-10 and a DECISIONS row. Until then the assumed 259200 s wait stays, and the scenario only observes and records the text.
- **OWNER-4:** which owner session slots and dates run the scenarios, and the soak start date. No plan sets a date.

### Claude's Discretion
- Scenario file layout, evidence JSON field names (within the Phase 24 shape), wave split and plan count.

### Deferred Ideas (OUT OF SCOPE)
- Mainnet CANARY runs and anything with real money: Phase 26.
- Full async rewrite of `OperatorCommands` database work (R-23): later phase.
- Strategy or parameter changes based on Demo results: out of scope by the research rule.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXEC-01 | Execution manager places LIMIT-zone entries and Algo-Order protective exits, partial-fill sizing; Pending until Demo-proven (REQUIREMENTS.md:63) | Scenario catalog S01-S05, S07 (happy path re-run, partial fill, -2021, SL rejected, cancel race, restart cuts); exchange-fact cross-check (G2-030) |
| EXEC-02 | Reconcile compares local vs normal orders, algo orders, positions; sweeps orphans; forces SAFE_MODE (REQUIREMENTS.md:64) | S14, S15, S16 (foreign order, doubled position, manual close), soak invariant "zero unexplained divergence" |
| EXEC-03 | Deterministic client/algo ids prevent duplicate entries across retries/restarts/replays (already Complete) | S06 replay/concurrent press, S07 restart cuts; soak invariant "zero duplicate entry" |
| APRV-01 | Telegram alerts carry symbol, direction, entry, SL, TP, RR, risk, expiry... (Complete at library level) | S01 real-Telegram smoke re-run; card text asserted by `assert_live_text` in twins |
| APRV-02 | Approval bound to SignalId + version + plan hash + expiry + chat + one-time token, idempotent across replays (Complete) | S06 (replayed and concurrent APPROVE/CONFIRM against real Demo: exactly one POST) |
| OPS-01 | SAFE_MODE blocks entries while monitoring continues; RUNBOOK drills rehearsed (Pending) | S14 SAFE_MODE, S16-S19 drills (manual close, stale feed, unprotected, api_down via injected 429/418, db_failure), OWNER stop procedure 22.5 |
| OPS-02 | No-withdrawal keys, IP allowlist, off-source secrets, secret-free logging, health checks (Pending) | Env guard (BINANCE_LIVE_* refusal), evidence scrubbing (`Redactor`), post-write secret scan; key attestation stays owner-only (24-OWNER-RUNBOOK C1) |
</phase_requirements>

## Project Constraints (from AGENTS.md; no `./CLAUDE.md` exists in the repo)

- Demo/probe `--execute` and any signed call: **owner only**. Agents never run them, never read `.env`, never touch mainnet. Live placement stays disabled (`LIVE_ORDERS_DISABLED`).
- `uv run ...` always; ruff line length 100; mypy `strict` on `src` only; `from __future__ import annotations`; absolute `src.*` imports; `asyncio_mode = "auto"`.
- Decimal-only on the domain/risk/backtest/core/analytics path (`tests/test_domain_no_float.py`); no wall clock in pure modules (inject clocks); `src/core` stays pure.
- Parameter sets are hash-locked (`params/**`): never edit in place. Nothing in this phase may tune a parameter from Demo results.
- No AI in the decision path. Fail closed. A placement is never re-sent (D080); fill-driven protection (D079).
- Fixtures regenerated by scripts, never hand-typed. Missing contract means TBD, never invent.
- Do not add a dependency without a DECISIONS row (`uv add` + committed `uv.lock`). **This phase needs none.**
- `AGENTS.md` is gated: cap 230 lines (`tests/test_agents_md.py:15`, file is 217 lines), and `scripts/verify_decision_alignment.py all` must pass after editing it.
- Run one heavy pytest process at a time; full suite `uv run pytest -m "not docker" -n 4`; recorded gates run sequentially on a clean tree with `TEST_DATABASE_URL`.
- Commit trailer = the model that did the work (`Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` for this model); never push; stage explicit paths only.
- Repo docs and evidence in English; some files CRLF-sensitive.

## Summary

The Phase 24 harness is a good base but it is a *script* (`scripts/demo_rehearsal.py`, 3,506 lines), not a pytest suite, and it exercises exactly one flow (happy path, restart after fill, replays, SAFE_MODE drill). The reusable core is `SmokeEnv` (`scripts/demo_rehearsal.py:2314-2342`), a dataclass that holds one composed process plus `tick`, `pause`, `owner`, `restart`, `deliver_fill` callbacks. It already has two interchangeable factories: `_real_smoke_env_factory` (Demo, `scripts/demo_rehearsal.py:3254`) and `build_fake_smoke_env` (fake exchange, `tests/support/live_smoke_env.py:152`). That is the "same assertions, two environments" shape D-05 and the CONTEXT `<specifics>` ask for. The recommended design is: each scenario is an `async def scenario_x(env, recorder)` function in a non-test module; a CI test runs it on the fake twin and a `demo`-marked test runs it on the Demo environment. Failure paths that Demo cannot produce on demand (a SL rejection, -2021, a lost response, a 429/418, a DB outage, stale feed, a DAILY_STOP loss) are produced by a **test-only fault-injecting exchange edge** passed through the existing production seam `build_wiring(exchange_edge=...)` (`src/live/wiring.py:490,554-557`), so no `src` change and no Demo-only branch (D-08) is needed. The system's *reaction* is then real (real reduce-only close, real reconcile, real SAFE_MODE) while the *trigger* is labelled injected.

Six findings change the plan and must be resolved before or while planning (details in Open Questions and Common Pitfalls): (1) **D-03 is wrong as written**: CI runs `uv run pytest -m "not docker"` (`.github/workflows/ci.yml:73`) and AGENTS.md prescribes the same command, which does NOT exclude a `demo` marker, so the exclusion needs a `conftest.py` collection hook, not only a marker. (2) **D-10 is only partly feasible**: `export_soak_evidence.py` and `evaluate_trial_soak.py` are *paper-runtime* tools (paper epoch, freeze check, parity); a live-Demo soak needs a new evaluator over the live journal, reusing only the bundle/hash/publish patterns. (3) **The live process tracks one symbol** (`DEMO_SYMBOLS = ("BTCUSDT",)`, `src/live/runtime.py:420`) and has **no strategy-driven signal source** (only the owner-triggered `/demo_signal` injector, `src/live/signal_source.py:6-9`), so D-09's "live-5 universe" and "continuous soak" cannot be met as written without owner decisions. (4) **OWNER-3 is stale**: DECISIONS D083 already accepted the -1003 exception and the code exists (`src/adapters/binance_ratelimit_gate.py:23-28`); only the margin key `rest_gate.ban_end_clock_margin_ms` is open. (5) **D-07's real 418 ban must not be provoked**: the owner decided on 2026-10-22 not to (20-DEFERRED.md:77) and the owner runbook says "Never provoke a 418 or 429 on purpose" (`.planning/DEMO-EVIDENCE-PLAN.md`). (6) **The scenario campaign and the soak cannot overlap on one Demo account** (the listenKey is an account-level singleton), and "any defect restarts the soak clock", so scenarios and fixes must finish before the soak starts.

**Primary recommendation:** Build `tests/support/demo_scenarios/` (shared scenario functions) + `tests/support/fault_edge.py` (test-only fault edge via the existing `exchange_edge` seam) + `tests/demo/` (`demo`-marked owner-run tests, gated by a `conftest.py` hook and an env guard) + `tests/test_demo_twin_*.py` (CI twins on the fake), reuse `scripts/demo_rehearsal.py` by import (precedent: `tests/test_live_demo_smoke.py`), write a new `scripts/evaluate_demo_soak.py` over the live journal, and resolve the five Open Questions below with the owner before the soak registration is written.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Scenario logic (what to do, what to assert) | Test layer `tests/support/demo_scenarios/` | - | Shared by CI twin and owner Demo run so assertions cannot drift (D-05) |
| Fault injection (SL reject, -2021, lost ack, 418/429, stale mark) | Test layer `tests/support/fault_edge.py` via `build_wiring(exchange_edge=)` | Fake exchange `hold/release/fail_next/reject_next_algo` | Seam already exists in `src`; production passes `None`; keeps D-08 |
| Placement, protection, reconcile, SAFE_MODE under test | `src/live`, `src/execution`, `src/reconcile` (unchanged) | Real Binance Demo REST/WS | The thing being proven; must stay one code path with live |
| Gating of `demo` tests (never CI, never LIVE) | `tests/conftest.py` hook + `tests/demo/conftest.py` env guard | CI workflow command | A marker alone does not exclude under `-m "not docker"` |
| Evidence recording and scrubbing | `scripts/demo_rehearsal.py:EvidenceRecorder` (imported) | `src/ops/redaction.py` | Already scrubs and post-write scans (`scripts/demo_rehearsal.py:624-637`) |
| Soak pre-registration and evaluation | New `scripts/evaluate_demo_soak.py` + committed registration file | PostgreSQL journal (live process) | Existing soak tools read paper-runtime epochs, not the live journal |
| Journal volume (R-25) and pool-timeout wrap (R-24) | `src/live/health.py`, `src/persistence/uow.py` | - | Small `src` fixes with unit tests, done before the soak |
| Demo-vs-mainnet record | `docs/operations/DEMO_VS_MAINNET.md` | `09-EXCHANGE-FACTS.md` | Read by Phase 26 canary planning |

## Standard Stack

### Core (all already installed and locked; nothing to add)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 9.1.1 [VERIFIED: `uv run pytest --version`] | Test runner, markers, collection hooks | Project runner; `asyncio_mode = "auto"` (pyproject `[tool.pytest.ini_options]`) |
| `scripts/demo_rehearsal.py` (in-repo) | n/a | `SmokeEnv`, `EvidenceRecorder`, `ConsoleOwner`, `_bring_up`, `_wait_until`, `_inject` | The Phase 24 harness D-04 says to reuse |
| `tests/support/fake_binance_exchange.py` (in-repo) | n/a | Binance-semantics fake with `fill(quantity=)`, `hold/release`, `fail_next`, `reject_next_algo`, `trigger_stop` | CI twin exchange |
| `tests/support/live_composed_rig.py`, `live_smoke_env.py` (in-repo) | n/a | Composed process on fakes; `build_fake_smoke_env` | CI twin environment |
| binance SDK (`binance_sdk_derivatives_trading_usds_futures`, `binance_common`) | locked in `uv.lock` | Real Demo transport behind `BinanceUsdmAdapter` | Already behind project-owned adapter; SDK types never leave |
| SQLAlchemy + psycopg, PostgreSQL | locked | Real stores for Demo run (`make_sync_engine`) | Needed for DB-outage and soak journal |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `src/ops/redaction.py` `Redactor` | in-repo | Scrub evidence and post-write secret check | Every evidence write |
| `src/paper/evidence_bundle.py` patterns | in-repo | Manifest + SHA-256 bundle, create-only publish | Pattern only for the soak bundle; do not import paper epoch logic |
| `scripts/demo_probe.py` (7,155 lines, ~50 cases) | in-repo | Exchange-fact observations (P3 partial fill, P7 races, -2019, -1021, GTD expiry, manual close) | Owner opt-in cases already cover exchange facts; the new suite tests the *system's reaction*, not the exchange |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Fault edge in `tests/support` | Demo-only branches in `src` | Violates D-08; rejected |
| Programmatic owner (calls `wiring.runner.handler`) for most scenarios | Real Telegram taps for every scenario | Taps cost owner minutes per scenario; keep real taps for the S01 smoke only (transport proof) |
| New `scripts/evaluate_demo_soak.py` | Reuse `evaluate_trial_soak.py` | The latter evaluates paper epochs (see Pitfall 2); cannot judge the live journal |

**Installation:** none. `uv sync --frozen --extra dev` is enough. [VERIFIED: pyproject.toml has pytest, pytest-xdist in `dev` extra]

**Version verification:** no new package. pytest 9.1.1 and uv 0.12.17, Python 3.13.15 confirmed in this session.

## Package Legitimacy Audit

No external package is added by this phase (D-02 plus the "no new dependencies" constraint). Audit table intentionally empty.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | - | - | - | - | - | - |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                        owner session (OWNER-4 dates)                         agent / CI
                                  |                                                |
        uv run pytest -m demo -p no:xdist  (env guard: BINANCE_DEMO_* only)        uv run pytest -m "not docker"
                                  |                                                |  (demo tests SKIPPED by conftest hook)
                                  v                                                v
                      tests/demo/test_demo_*.py                      tests/test_demo_twin_*.py
                                  \                                               /
                                   +----> tests/support/demo_scenarios/*.py <----+     (ONE set of assertions)
                                                    |
                          ScenarioEnv = SmokeEnv + fault controls + evidence kind
                          /                                              \
        DEMO factory (owner)                                      FAKE factory (CI)
   build_wiring(sdk_factory=demo_guarded_sdk_factory,         make_composed_rig(...)  (fake exchange,
      engine=make_sync_engine(PG), exchange_edge=FaultEdge)      memory stores, virtual clock)
                  |                                                       |
        FaultEdge(real adapter)                                  FaultEdge(fake adapter)
        modes: pass | raise_before | mutate_payload | drop_response_after_send | stale_mark
                  |                                                       |
          real Binance Demo (demo-fapi / demo-fstream)           BinanceSemanticsFakeAdapter
                  |
   composed live process: signal pump -> approval card -> APPROVE -> CONFIRM -> GTD LIMIT entry
   -> fill on user-data stream -> coordinator places STOP -> TP legs -> reconcile / SAFE_MODE / alerts
                  |
        EvidenceRecorder (schema-1) -> .planning/phases/25-*/evidence/*.json + per-session INDEX
                  |
   (separately, owner-started, after campaign is green)  soak: `live` compose service, DEMO mode
        journal (PostgreSQL) --> scripts/evaluate_demo_soak.py --> PASS/FAIL vs committed registration hash
```

### Recommended Project Structure
```
tests/
  conftest.py                         # + pytest_collection_modifyitems: skip `demo` unless explicitly selected
  demo/
    conftest.py                       # env guard fixture: refuses BINANCE_LIVE_*, non-demo host, xdist
    test_demo_s01_happy.py ... test_demo_sNN_*.py   # @pytest.mark.demo, thin: build env, call scenario
  support/
    fault_edge.py                     # FaultEdge (wraps real or fake adapter), SDK-shaped errors
    demo_scenarios/
      __init__.py, catalog.py          # SCENARIOS registry: id, title, evidence_kind rules, twin test name
      s01_happy.py ... sNN_*.py        # async def run(env, recorder)
      evidence_index.py                # per-session index file writer
  test_demo_twin_*.py                 # CI: same scenario functions on build_fake_smoke_env
  test_phase25_gate.py                # structural gate (pattern of tests/test_phase24_gate.py)
scripts/
  evaluate_demo_soak.py               # new: journal-based soak evaluator
docs/operations/DEMO_VS_MAINNET.md    # criterion 4
.planning/phases/25-demo-integration-test-campaign/
  25-SOAK-REGISTRATION.md (+ recorded sha256), 25-OWNER-RUNBOOK.md, evidence/
```

### Pattern 1: Scenario = function over `SmokeEnv`, two factories
**What:** A scenario takes the same environment object the smoke already uses (`SmokeEnv`: `assembly`, `clock`, `tick`, `pause`, `owner`, `synthetic`, `wait_ticks`, `restart`, `deliver_fill`) and returns after recording steps. CI passes `build_fake_smoke_env(tmp_path)`; the owner run passes a Demo env.
**When to use:** every scenario S01-S20.
**Example (the real shape, from the file):**
```python
# Source: scripts/demo_rehearsal.py:2314-2342 (read this session)
@dataclass
class SmokeEnv:
    assembly: Any
    clock: Callable[[], datetime]
    tick: Callable[[], Awaitable[None]]
    pause: Callable[[float], Awaitable[None]]
    owner: SmokeOwner
    synthetic: bool
    wait_ticks: int
    ports_transform: Callable[[Any], Any] = field(default=lambda ports: ports)
    deliver_fill: Callable[[Any], Awaitable[None]] | None = None
    placements: Callable[[], int] | None = None
    restart: Callable[[], Awaitable[SmokeEnv]] | None = None
    initialize_gate_state: bool = False
```
Extend by subclassing (as `FakeSmokeEnv` does in `tests/support/live_smoke_env.py:54-59`) with a `faults: FaultEdge` field; do not edit the script's dataclass.

### Pattern 2: Fault edge through the existing production seam
**What:** `build_wiring(..., exchange_edge=fn)` calls `fn(self.exchange)` and uses the returned `ExchangeBundle` (`src/live/wiring.py:554-557`; comment there: "It may replace the signed adapter and the public reader, never the gate"). `make_composed_rig` already uses it for the fake (`tests/support/live_composed_rig.py:362-369`, `ComposedExchangeEdge.__getattr__` routes by name). `default_assemble` does **not** pass `exchange_edge` (`src/live/runtime.py:468-482`), so the Demo environment factory must call `build_wiring` directly (mirror `default_assemble`: `make_sync_engine(url)`, `load_binance_limits`, `load_parameter_set`) from `tests/support`, or add an optional `exchange_edge=None` parameter to `default_assemble` (a one-line, behaviour-neutral change; the planner picks one, test-side is the lower risk).
**Fault modes (all in `tests/support/fault_edge.py`, none in `src`):**
- `raise_before_send(method, sdk_error)` - raise an SDK-shaped `BadRequestError`/HTTP-status error before the call reaches Binance (SL rejection, -2021, 418/429, -2019).
- `mutate_payload(method, fn)` - alter the request (e.g. a stop trigger on the wrong side of the mark) so Binance returns its own real error (real -2021).
- `drop_response_after_send(method)` - let the real call through, then raise a timeout-shaped error (restart before ACK, ambiguous entry, D080 probe path).
- `hold(method)` / `release(method)` - mirror the fake's gates for restart-between-entry-and-SL.
- `stale_mark(age)` - serve an old `MarkPriceReading` (stale feed, D058).
**Evidence labelling (recommended; the file has only two kinds today):** keep `SYNTHETIC` and `DEMO_OBSERVED` (`scripts/demo_rehearsal.py:2269-2270`) and add a third value `DEMO_FAULT_INJECTED` for a step whose *trigger* was injected but whose reaction hit the real Demo exchange; never count it as exchange behaviour. [ASSUMED: label name is a design choice; CONTEXT allows field names "within the Phase 24 shape"]

### Pattern 3: Programmatic owner for presses
`FakeOwner.act` (`tests/support/live_smoke_env.py:62-107`) calls `rig.press("APR"|"CNF", short_id, query_id=...)`, which is `await self.wiring.runner.handler(update, None)` with `make_callback_update` (`tests/support/live_composed_rig.py:300-312`) - the runner's one `on_callback` handler, identical to what Telegram polling invokes. A `ProgrammaticOwner` for the Demo env can do the same against `env.wiring.runner.handler`, so `pytest -m demo` needs no terminal interaction. Telegram *transport* is proven only by S01 (the existing owner-tap smoke) and by `ConsoleOwner`. [VERIFIED: code read]

### Pattern 4: Restart and crash cuts
The smoke restarts by building a second wiring over the same stores (`env.restart`, `scripts/demo_rehearsal.py:3287-3288`) after a clean `shutdown_in_order`. For the three required cut points, abandon the first assembly **without** `shutdown_in_order` (no drain, no `close_listen_key`) to model a crash; because the listenKey is a singleton, the second process's POST returns or extends the active key (Binance docs) [CITED: developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Start-User-Data-Stream via search summary]. Cut points: (a) before ENTRY ACK = `drop_response_after_send("place_entry")` then abandon; expected per D080 `[VERIFIED: DECISIONS.md D080]`: probe by client id, found -> ACKED, not found or probe error -> UNKNOWN + SAFE_MODE `ENTRY_STATE_UNKNOWN`, never re-sent; (b) between fill and SL = `hold("place_algo_protective")` then abandon; expected: restart rebuilds the plan UNPROTECTED and the coordinator places the stop or closes (`tests/test_live_restart_rehydrate.py:333` pins the protected case); (c) after fill + stop = the existing smoke `restart_rehydrate` step.

### Pattern 5: Phase gate for structure
Mirror `tests/test_phase24_gate.py` (inventory, requirement to named tests via `ast`, decision table, register) as `tests/test_phase25_gate.py`: every scenario id in `catalog.py` must have (a) a twin test function, (b) a demo test function, (c) a row in `DEMO_VS_MAINNET.md` or the owner runbook, and the `demo` marker guard.

### Anti-Patterns to Avoid
- **A Demo-only code path in `src`** to make a scenario easy (violates D-08). Use the edge.
- **Reading D-08 as "zero `Environment.DEMO` in `src/live`"**: it is not zero today (see Pitfall 4); pin an allow-list instead.
- **Running `pytest -m demo -n 4`**: one Demo account, one listenKey; demo tests must never run in parallel or with xdist.
- **Treating a DEGRADED run as readiness evidence** (D056) - see Open Question 3 for what "healthy" can mean.
- **Provoking a real 418/429** (owner rule). Inject it at the edge.
- **Asserting exchange behaviour from an injected fault.** An injected `-2021` proves the system's reaction, not Binance's rule.

## Scenario Catalog (the planner's main input)

Twin = fake-exchange CI test. "Existing" means a file name seen in `tests/` this session; the exact coverage of each is a Wave 0 inventory task (do not assume it is complete).

| ID | ROADMAP bullet | Demo trigger (owner run) | Evidence label expected | CI twin starting point |
|----|---------------|--------------------------|------------------------|------------------------|
| S01 | happy path | existing `demo_rehearsal --execute` (21/21 on 2026-11-06, real Telegram taps); optional re-run from the VPS | DEMO_OBSERVED (already) | `tests/test_live_demo_smoke.py` (exists) |
| S02 | partial fill | Cannot be forced: `demo_probe` case `partial_fill_attempt` "can stay NOT_OBSERVED on Demo for ever" [VERIFIED: `scripts/demo_probe.py` docstring]. Run it best-effort, otherwise NOT_OBSERVED; Phase 26 canary owns it | NOT_OBSERVED expected; twin is the proof | fake `fill(client_id, quantity=...)` keeps PARTIALLY_FILLED [VERIFIED: fake docstring]; `tests/test_protection_take_profits.py`, `test_protection_branches.py` to inventory |
| S03 | price crossed SL before placement (-2021) | `mutate_payload` on the stop so real Binance answers -2021; local pre-placement mark gate scenario via `stale/moved mark` | DEMO_FAULT_INJECTED (real error code) | `tests/test_emergency_market_close.py`, `test_demo_probe_cases.py` mention 2021; inventory |
| S04 | SL rejected after fill -> reduce-only close | `raise_before_send("place_algo_protective", reject)`; close is a real reduce-only MARKET with an `xc-` id | DEMO_FAULT_INJECTED | `tests/test_protection_stop_lost.py`, `test_protection_close_first.py`, `test_emergency_market_close.py` |
| S05 | cancel racing a fill | `demo_probe` `entry_cancel_fill_race` (P7, best effort); system-level race via `expire_pending_entry` racing a fill | DEMO_OBSERVED if it races, else NOT_OBSERVED | fake `hold/release` makes the D-12 race deterministic [VERIFIED: fake docstring]; `test_protection_cancel_lag.py` |
| S06 | replayed/duplicate APPROVE and CONFIRM | smoke already shows replays place nothing; add two concurrent presses on real Demo (exactly one entry POST) | DEMO_OBSERVED | `tests/test_live_replay_restart.py` (`..._two_concurrent_confirm_presses_lead_to_exactly_one_place_entry`, exists) |
| S07 | restart mid-flow x3 | Pattern 4 cuts (a), (b), (c) | DEMO_FAULT_INJECTED for (a),(b); DEMO_OBSERVED for (c) | `tests/test_live_restart_rehydrate.py`, `test_live_replay_restart.py`, `test_intent_recovery*.py` |
| S08 | WS disconnect and listenKey expiry | forced stream drop (Phase 20 saw `UNKNOWN, SYNCING, LIVE` and no replay of frames sent during the gap [VERIFIED: 20-DEFERRED.md:96]); real expiry = suppress keepalive for >60 min (slow, owner opt-in); the 24 h connection cut-off [CITED: Binance user-data-streams docs via search] recurs about 21 times in the soak | DEMO_OBSERVED (drop), DEMO_FAULT_INJECTED (keepalive suppressed) | `tests/test_userdata_supervisor.py`, `test_reconcile_stream_divergences.py`, `test_live_stream_to_protection.py` |
| S09 | clock skew | inject a skewed process clock so the drift guard blocks entries (the smoke already refuses on +540 ms host drift, `_bring_up` lines 2632-2648); `demo_probe` `timestamp_outside_recv_window` (-1021) for the exchange side | DEMO_OBSERVED for the guard, exchange side from probe | `tests/test_clock_drift.py`, `test_live_smoke_...` (`test_a_start_whose_clock_drift_guard_blocks_entries_stops_before_any_card`) |
| S10 | rate limit / 418 | **inject only** (`raise_before_send` with HTTP 429/418 shape). Never provoke (owner rule). Assert gate state file, alert `REST_GATE_BAN_ENTERED`, refusal of entries, no re-send | SYNTHETIC / DEMO_FAULT_INJECTED, never "observed 418" | `tests/test_binance_ratelimit_gate.py`, `test_gate_restart.py`, `test_rest_gate_ban_end.py`, `test_reconcile_queue_order.py` |
| S11 | DB outage during a risk-reducing action | wrap the stores (raise `StoreUnavailable`) around S04's close; optional owner-only real outage `docker compose stop postgres` (`[NOT_TESTED]` in 20-DEFERRED.md:56) | DEMO_FAULT_INJECTED; real-PG variant manual | `tests/test_protection_sweep_spill.py`, `test_execution_emergency.py`, `test_risk_first*` |
| S12 | DAILY_STOP | feed a loss through the day-risk reader edge (`user_trades_in_window`/`income_in_window` on the composed edge); resting entries cancelled on the real Demo | DEMO_FAULT_INJECTED | `tests/test_daily_stop.py`, `test_day_risk_stream.py`, `test_daily_loss*.py` |
| S13 | liquidation-guard and margin rejections | real: consume margin with a far resting order (probe case `available_balance_with_resting_order`) then request; `-2019` real via `insufficient_margin_order`; liquidation: `isolated_position_liquidation_price` | DEMO_OBSERVED | `tests/test_margin_guard.py`, `test_liquidation_watch.py`, `test_live_liquidation_and_tp.py` |
| S14 | SAFE_MODE entry and operator exit | smoke covers a drill entry; add real triggers (reconcile divergence, unknown entry) and `/safemode_exit` + `/confirm` | DEMO_OBSERVED | `tests/test_live_safe_mode_drill.py`, `test_safe_mode_exit_operator.py` |
| S15 | foreign order and doubled position | a scripted "foreign actor" places a non-system-id order and an extra small position through the adapter; reconcile must flag and enter SAFE_MODE; clean up afterwards (`demo_clear.py`) | DEMO_OBSERVED | `tests/test_live_reconcile_divergences.py`, `test_reconcile_compare_v2.py` |
| S16 | (G2-016) manual close outside the system | already DEMO_OBSERVED at exchange level 2026-10-22 (legs end EXPIRED, no orphan, 20-DEFERRED.md:91,95); add a system-level run: close outside, assert reconcile FLAT and no divergence | DEMO_OBSERVED | `tests/test_drills.py`, `test_reconcile_tp1_fill.py` |
| S17 | (G2-016) stale feed | `stale_mark(age)` on the public reader; expect stale-feed SAFE_MODE and refused entries (D058) | DEMO_FAULT_INJECTED | `tests/test_live_feed_source.py`, `test_reconcile_stream_divergences.py` |
| S18 | (G2-016) unprotected-position drill | S04 plus a failing close: expect CLOSE_REQUIRED/CLOSE_FAILED alert, then operator `/close` or `/protect` (RUNBOOK 21.1a). Leaves a real Demo position until the operator acts; owner runs `demo_clear.py` after | DEMO_FAULT_INJECTED | `tests/test_protection_stop_lost.py`, `test_live_operator_commands.py` |
| S19 | P20-DEMO operator command scenarios | inject a false 429/418 (S10 edge), then `rest_gate_cli status` / `clear` against the state file; confirm the clear audit line (`<state file>.clear-audit.jsonl`) | DEMO_FAULT_INJECTED | `tests/test_rest_gate_cli.py`, `test_rest_gate_clear_audit.py` |
| S20 | D-07 observation-only items | A2 via `demo_probe` `gtd_entry_expiry_status`; A3 and manual close already observed; B2/B3 same-id re-place already observed (-4116, query -2013 right after NEW [VERIFIED: 20-DEFERRED.md:94]); stream row 7 partly observed; **real 418 beyond 259200 s and 429/418 queue order: leave NOT_OBSERVED permanently** | per item | n/a (observation records, no twin) |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exchange fault injection | Patches inside `src` or monkeypatching SDK internals | `build_wiring(exchange_edge=...)` wrapper in `tests/support` | Seam exists, documented as the one exchange test seam (`src/live/wiring.py:555-556`) |
| Press simulation | A second Telegram client | `wiring.runner.handler` + `make_callback_update` (`FakeOwner`) | Same handler as polling; already proven in 24-29 twins |
| Evidence writer | New JSON writer | `EvidenceRecorder` (scrub + atomic write + post-write secret scan, `scripts/demo_rehearsal.py:480-637`) | Secret-safety is already tested |
| Demo-host and credential guard | New URL/env checks | `assert_demo_base_url`, `demo_guarded_sdk_factory`, `admit_smoke_environment` (`scripts/demo_rehearsal.py:375,2345,2364`) and `parse_live_environment` (refuses LIVE credentials next to DEMO) | Same guard as the smoke; add only the pytest-level refusal |
| Cleanup between scenarios | Hand-made cleanup | `scripts/demo_clear.py` logic (closes stale plans via DOMN-04 `APPROVED -> EXPIRED`) and the probe's cleanup (cancel-all, one reduce-only close, verify flat) | A refused CONFIRM leaves a plan APPROVED for about 26 min and blocks the symbol (`_safe_mode_drill` docstring) |
| Ordered start/stop of the process | Custom lifecycle | `run_start_sequence` (`_bring_up`) and `shutdown_in_order` | The same sequence production uses |
| Soak evidence integrity | Ad hoc hashing | Manifest + SHA-256 + create-only publish pattern of `src/paper/evidence_bundle.py` / `export_soak_evidence.py` | Proven pattern; only the data source differs |

**Key insight:** the expensive, easy-to-get-wrong parts (guards, scrubbing, process lifecycle, press path, fake exchange semantics) already exist; Phase 25's new work is the fault edge, the scenario functions, the gating hook, a journal-based soak evaluator and the records.

## Common Pitfalls

### Pitfall 1: The `demo` marker is not excluded by the CI/default command
**What goes wrong:** `uv run pytest -m "not docker"` (CI: `.github/workflows/ci.yml:73`; AGENTS.md "Commands") selects every test whose marker is not `docker`, including `demo`. Demo tests would run in CI and in the agent's full-suite run, and would try signed calls (or fail on missing creds).
**Why:** `markers = ["docker: ..."]` is the only registered marker and `addopts = "-q"` (pyproject.toml `[tool.pytest.ini_options]`). A `-m` in `addopts` would be overridden by the CLI `-m`.
**How to avoid:** (1) register `demo` in `pyproject.toml`; (2) add `pytest_collection_modifyitems` in `tests/conftest.py` that adds a skip marker to every `demo` item unless the run explicitly selects it (for example `config.getoption("markexpr")` contains `demo` and not `not demo`, or an env switch such as `TRADING_DEMO_RUN=1`; pytest documents this exact skip-by-default hook pattern [CITED: docs.pytest.org example/simple.rst `--runslow`]); (3) the skip must stay a skip under `TRADING_CI_STRICT=1`, so do **not** route it through `infra_skip`; (4) optionally also change CI and AGENTS.md commands to `-m "not docker and not demo"` (AGENTS.md has 13 spare lines under the 230 cap, and needs `verify_decision_alignment.py all`); (5) a guard test that scans `tests/demo/**` for a `demo` mark on every test function (D-03's "guard test").
**Warning signs:** a CI log line listing demo tests as passed or errored; `-n 4` runs touching `tests/demo`.

### Pitfall 2: "Reuse the soak tooling" (D-10) points at paper tools
**What goes wrong:** `export_soak_evidence.py` exports one *paper-runtime epoch* (pinned epoch file, freeze-check diff log, GitHub runs, paper runtime records); `evaluate_trial_soak.py` evaluates `src/paper/exit_criteria.evaluate_trial` (health silence, parity, freeze ticks); `soak_host_acceptance.py` validates D042 *host* conditions; `deploy/compose-soak.sh` runs project `trading-soak` whose env file explicitly lists **no exchange credential** (`deploy/soak.env.example`: "this template lists no exchange credential, and none belongs in the soak file") and the paper runtime refuses to start if any `BINANCE_` name is present. The live Demo process is the `live` compose service (profile `live`, own env file `.env.live`, own volume `livestate`, `restart: "no"`) [VERIFIED: docker-compose.yml comments lines 198-238; RUNBOOK 11.1/22.4].
**How to avoid:** run the Demo soak as the `live` service under the **default** compose project with `.env.live`, not under `compose-soak.sh`; reuse `soak_host_acceptance.py` only for the host conditions it already checks; write `scripts/evaluate_demo_soak.py` (new, journal-based) and reuse only the manifest/hash pattern. State this deviation from D-10 explicitly in the plan so the owner can confirm.
**Warning signs:** a plan task that says "run `evaluate_trial_soak.py` on the Demo soak".

### Pitfall 3: The live process cannot produce a continuous soak by itself
**What goes wrong:** the only signal source is `DemoSmokeSignalSource`, fed by the owner's `/demo_signal` Telegram command; "A strategy-driven DEMO source ... stays with the owner-named later phase and is NOT built" [VERIFIED: `src/live/signal_source.py:6-9`]. Every entry needs a human APPROVE and CONFIRM (no auto-approve, APRV-02). A 21-day soak therefore has no trades unless the owner drives them. Also `DEMO_SYMBOLS = ("BTCUSDT",)` (`src/live/runtime.py:420`), so "live-5" is one symbol, and R-21 (reservations never advance) says "Do this before any second symbol" (ROADMAP Phase 25 inherited items).
**How to avoid:** do not invent a signal source or an auto-approver in this phase. Pre-register (OWNER decision, Open Question 1 and 2) a soak of the **process** (uptime, reconcile clean every tick, health, stream cycles, 24 h reconnects, alerts) **plus a fixed number of owner-driven round trips per week**, on BTCUSDT only, and write the pass criteria against that. Anything else needs a new owner decision outside Phase 25 scope ("no new strategy work").

### Pitfall 4: D-08 "no Demo-only branch" is already false in `src/live`
**What goes wrong:** `Environment.DEMO` branches exist at `src/live/enablement.py:234` (`enable_demo`), `src/live/startup.py:1014`, `src/live/wiring.py:957` (`demo_degraded_allowed=self.config.mode is Environment.DEMO`), `src/live/wiring.py:1464-1466`, `src/live/wiring_parts.py:268`, `src/live/smoke_injection.py:93,298`, plus config-level mode handling. [VERIFIED: grep of `src` this session; none under `src/execution` or `src/risk`]. A naive AST test "no DEMO branch in src/live" fails on day one.
**How to avoid:** the AST/wiring test asserts (a) **zero** `Environment.DEMO`/`mode is ...` branches in `src/execution` and `src/risk` (true today), and (b) in `src/live` the set of files containing them equals a pinned allow-list with reasons (the pattern of `WALL_CLOCK_EDGE_ALLOW_LIST` in `tests/test_live_ast_guards.py`), so a new Demo branch must be added on purpose. Also assert the placement call chain (`execute_approved_plan`, `place_entry`) takes no `mode` parameter.

### Pitfall 5: R-25 can break the `db_writes` health check
**What goes wrong:** `self.record = self.db_writes.track(write_journal)` (`src/live/wiring.py:533`): every successful journal write updates the tracker that `check_db_writes` reads; `DB_WRITE_MAX_AGE = timedelta(seconds=60)` (`src/live/wiring.py:168`). On a quiet account the 15 s health tick's own rows are the only writes. If R-25 lengthens the cadence beyond 60 s or removes the per-tick row, `db_writes` goes FAIL on an idle process.
**How to avoid:** follow the reviewer's fix: keep **one `HEALTH_VERDICT` row per tick** (keeps the tracker fresh and costs about 5,760 rows/day, about 121,000 over 21 days) and journal the ten `HEALTH_CHECK` rows **only when a check's status changes** (plus the first tick and every N-th tick as a heartbeat of detail). Test: idle process, 10 ticks, expect 10 verdict rows and 10 check rows total (first tick) and `db_writes` PASS; a status flip writes exactly one more check row; a failing journal makes `db_writes` stale. Note `health_tick_once` stores the verdict on the producer before writing (`src/live/health.py:~483`), keep that order.

### Pitfall 6: Campaign and soak collide on one Demo account
**What goes wrong:** the user-data listenKey is an account-level singleton (`stop(close_listen_key=...)` docstring, `src/adapters/binance_userdata_supervisor.py:416`; owner runbook: "One process per Demo account"). A scenario run while the soak process is up steals or closes the soak's stream; and a defect "restarts the soak clock".
**How to avoid:** sequence: twins and fixes (agent) -> owner campaign sessions -> fixes -> soak registration -> soak. If the owner wants overlap, a second Demo account/key is required (Open Question 6).

### Pitfall 7: Real 418 or 429 provocation
Owner decision 2026-10-22 (20-DEFERRED.md:77) and the DEMO-EVIDENCE-PLAN safety rule forbid it. Also IP bans are per IP across weights, "from 2 minutes to 3 days" [CITED: developers.binance.com general-info], and the VPS IP will also be the IP-restricted key's address. Inject at the edge instead (S10, S19).

### Pitfall 8: A refused CONFIRM or a failed scenario leaves state that blocks the next one
A refused CONFIRM leaves the plan APPROVED (about 26 min), blocking the symbol (`ACTIVE_PLAN`, `PENDING_OR_APPROVED_APPROVAL`, `CONFLICT_WITH_OPEN_POSITION`); a failed run can leave a Demo position or orders. **How to avoid:** every scenario begins with a "flat account + no stale plan" precondition step (reads: open normal orders, algo orders, positions, open approvals) and ends with the smoke's `account_clean`; failures print the `demo_clear.py` instruction (as `_main_smoke` does at lines 3371-3374).

### Pitfall 9: Injected faults mislabelled as exchange behaviour
Phase 26 reads `DEMO_VS_MAINNET.md` to decide what the canary must prove. An injected -2021 recorded as DEMO_OBSERVED would hide a gap. Use the three-label scheme (Pattern 2) and make the evidence index list label per step.

### Pitfall 10: Windows/dev-machine limits for a 3-week soak
The soak needs the VPS (24-33 owner steps B1-B7, C1-C5, D1-D4, E1-E3 are all NOT_OBSERVED per `24-OWNER-RUNBOOK.md`), `restart: "no"` on the `live` service (owner switch G2) and a chrony-synced clock. A dev PC for 21 days is not credible. These are owner prerequisites (CONTEXT says this phase does not close them).

## Code Examples

### Collection hook: skip `demo` unless explicitly selected
```python
# Source: pattern from pytest docs (example/simple.rst, --runslow); adapted. [CITED: docs.pytest.org]
# tests/conftest.py (addition)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    expr = (config.getoption("markexpr") or "").replace(" ", "")
    selected = "demo" in expr and "notdemo" not in expr
    if selected and os.environ.get("TRADING_DEMO_RUN") == "1":
        return
    skip = pytest.mark.skip(reason="demo scenario: owner-run only (-m demo with TRADING_DEMO_RUN=1)")
    for item in items:
        if item.get_closest_marker("demo") is not None:
            item.add_marker(skip)
```
(Plus `config.addinivalue_line` is not needed if `demo` is in `pyproject.toml` `markers`.) Under `--strict-markers` an unregistered marker fails collection; register it.

### Env guard for the demo directory
```python
# Source: names verified at src/adapters/binance_client.py:265-276 (CREDENTIAL_SPECS):
#   Environment.DEMO -> BINANCE_DEMO_API_KEY / BINANCE_DEMO_API_SECRET
#   Environment.LIVE -> BINANCE_LIVE_API_KEY / BINANCE_LIVE_API_SECRET
# tests/demo/conftest.py
@pytest.fixture(scope="session", autouse=True)
def _demo_guard() -> None:
    live = [n for n in os.environ if n.startswith("BINANCE_LIVE_")]
    if live:
        pytest.fail("BINANCE_LIVE_* present: refusing to run the Demo suite", pytrace=False)
    from scripts.demo_rehearsal import admit_smoke_environment   # DEMO mode only, names not values
    admit_smoke_environment(os.environ)                            # raises SmokeRefused
    # host: demo_guarded_sdk_factory re-reads the SDK base path after the build.
```
`admit_smoke_environment` (`scripts/demo_rehearsal.py:2364-2379`) already refuses a non-DEMO mode and LIVE credentials via `parse_live_environment`; the pytest-level check is the additional "any `BINANCE_LIVE_*`" rule of D-03.

### R-24: wrap the pool-timeout in the transaction seam
```python
# Source: src/persistence/uow.py:26-52 (read this session). Add one clause before DBAPIError:
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

        except SQLAlchemyTimeoutError as exc:   # QueuePool limit reached: not a DBAPIError
            raise StoreUnavailable(
                f"PostgreSQL pool exhausted ({type(exc).__name__})"
            ) from None
```
Place it inside the same `try` that wraps `Session(...) as session, session.begin()`; connection checkout happens at `session.begin()`, so the exception arises there. Twin test: `create_engine(..., pool_size=1, max_overflow=0, pool_timeout=1)` with one connection held open, then `transaction()` must raise `StoreUnavailable` (and the manager's `StoreUnavailable` path then fails closed after the approval was consumed). Do not change `src/ops/store_executor.py`: its docstring pins "standard library only" and it lives outside `src/live` on purpose. [ASSUMED: that `sqlalchemy.exc.TimeoutError` is the class raised on pool exhaustion; standard SQLAlchemy behaviour, confirm in the twin test]

### Soak registration check (new evaluator, sketch of the contract)
```text
25-SOAK-REGISTRATION.md   fields: duration_days (>=21), symbol(s), owner_round_trips_per_week, pass criteria,
                          restart rule, process/image identity (IMAGE_COMMIT), registered_at_utc
sha256 of that file       recorded in a commit BEFORE the first soak order
evaluate_demo_soak.py     (1) recompute hash == recorded hash  (2) first soak journal order event time >
                          registration commit time  (3) criteria from the journal:
                          - zero unexplained divergence: every reconcile divergence row has an owner-annotated explanation
                          - zero position without exchange-side SL: no ENTRY_WITHOUT_PROTECTIVE / UNPROTECTED beyond max_unprotected_ms
                          - zero duplicate entry: one ENTRY intent per plan hash, one place_entry per client id
                          - every alert explained: each OPERATIONAL_ALERT row matched to an annotation
                          (4) a defect annotation resets window_start (restart rule)
```
Journal event names to read were confirmed only partially (`OPERATIONAL_ALERT`, `ALERT_DELIVERED`, `ALERT_SEND_FAILED` in `src/ops/alerts.py` docstring; `HEALTH_VERDICT`, `DEMO_SIGNAL_COMMAND`); the planner must enumerate the exact event types by reading `src/domain/journal.py` and the reconcile/protection producers before writing the evaluator. [ASSUMED for any name not listed above]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Entry with an entry-time `closePosition` stop | GTD LIMIT entry, stop placed after the first fill, REST-confirmed | D079, 2026-10-22 (Demo rejects with -4509) | Scenarios S03/S04/S07(b) test fill-driven protection, not pre-placed stops |
| Re-send placement after errors | Never re-send; one probe by client id; UNKNOWN + SAFE_MODE | D080 | S07(a) must assert exactly one `place_entry` and an UNKNOWN outcome, never a retry |
| Rehearsal as one script | Scenario functions with a CI twin | this phase | Owner session time is spent only on logic already green in CI |
| Assumed -1003 ban wait (259200 s) only | Ban end read from the 418 body when present, else 259200 s fallback | D083 (accepted 2026-10-22), built in 24-03 | OWNER-3 in CONTEXT is stale (Open Question 4) |

**Deprecated/outdated:** the CONTEXT line "parsing -1003 text needs an owner exception and a DECISIONS row" (superseded by D083); the paper-soak tooling as a Demo-soak base (Pitfall 2); the live-5 universe for the live process (Pitfall 3).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `DEMO_FAULT_INJECTED` as a third evidence-kind label is acceptable under "Phase 24 shape" | Pattern 2 | Owner may prefer two labels plus a flag field; low cost to change |
| A2 | `mutate_payload` on the stop trigger makes real Binance return -2021 on Demo | S03 | The code may differ; S03 would need the local-gate variant only |
| A3 | The SDK stamps request timestamps from the system clock, not the injected process clock, so an injected clock skews only the drift guard comparison (S09) | S09 | Skew scenario might also corrupt signed calls (-1021) and abort; check `binance_clock.py` first |
| A4 | Suppressing keepalive for >60 min reproduces a real `listenKeyExpired` on Demo | S08 | Demo may behave differently; scenario stays NOT_OBSERVED |
| A5 | `sqlalchemy.exc.TimeoutError` is the exception on pool exhaustion and is not a `DBAPIError` | R-24 example | Wrong class means the clause never fires; the twin test catches it |
| A6 | `rest_gate_cli status/clear` can run against the state file while the process is stopped (and `clear` needs the process stopped or accepts a live one) | S19 | Scenario ordering changes |
| A7 | One-process-per-Demo-account also holds for a second Demo key on the same Binance login | Pitfall 6 | A second key might share the singleton; overlap impossible |
| A8 | A 21-day soak on BTCUSDT plus owner round trips satisfies D040 "multi-week soak shows zero unexplained divergences..." | Pitfall 3 | Owner may require strategy-driven flow, a different phase |
| A9 | Journal event type names beyond those quoted are discoverable and sufficient for the soak evaluator | Soak sketch | Evaluator may need new journal producers (src change) |
| A10 | Binance Demo can produce a partial fill only with luck; therefore S02 stays NOT_OBSERVED | S02 | If Demo can, S02 is observable; low harm |

## Open Questions

1. **How does the soak generate trades?**
   - What we know: only `/demo_signal` exists; every entry needs APPROVE+CONFIRM; no strategy-driven source (`src/live/signal_source.py:6-9`).
   - What's unclear: whether owner-driven round trips satisfy D040 "multi-week demo soak", or whether a strategy-driven DEMO source (a new build, likely its own phase) is wanted.
   - Recommendation: pre-register process-level soak + N owner round trips per week; ask the owner for N and to confirm that a strategy-driven source is out of scope.
2. **Soak symbols: BTCUSDT only or live-5?**
   - What we know: `DEMO_SYMBOLS = ("BTCUSDT",)`; R-21 must be fixed before a second symbol; OWNER-1 is not decided.
   - Recommendation: register BTCUSDT only. Multi-symbol = R-21 + wiring change = separate owner-approved scope. Present D-09 "live-5" as needing owner revision.
3. **What is a "healthy" Demo run for D056 2(d)?**
   - What we know: `last_closed_candle_time` is permanently DEGRADED "not applicable: the live process has no candle feed" (`src/live/health.py:394-399`, `src/ops/health.py:646-665`), and DEMO enables under `demo_degraded_allowed=True` (`src/live/wiring.py:957`). So every live-process Demo verdict is DEGRADED by construction.
   - Recommendation: define in the registration and runbook "healthy" = all checks PASS except that one named not-applicable check, journaled as such; owner to confirm this reading (it is an interpretation, not a code change). `[ASSUMED]`
4. **OWNER-3 is superseded by D083.** Confirm and drop it from the plan; the open item is only `rest_gate.ban_end_clock_margin_ms` (`NOT_CONFIGURED`, AGENTS.md). The scenario to run is S10/S19 with injection; the real -1003 text is observable only if a ban ever happens by accident.
5. **D-07 real 418:** keep as a permanently NOT_OBSERVED record with the reason "owner decision 2026-10-22: not provoked", not as a scenario to run.
6. **Same Demo account for campaign and soak?** Decide sequencing (recommended) or provision a second Demo key.
7. **Where does the soak run and with which restart policy?** Needs the 24-33 owner steps and the `restart: "no"` to `unless-stopped` switch (24-OWNER-RUNBOOK G2). Any unplanned restart must follow RUNBOOK 22.5 (R-22 is undecided; `deploy/update.sh` refuses while the live service runs).
8. **R-21 timing:** OWNER-1 needs a DECISIONS row first. Planning may prepare it; for a BTCUSDT-only soak, R-21's effect is hidden over-refusal on one symbol, so it is not a soak blocker. The planner should gate execution of the R-21 plan on the row and keep it out of the critical path to the soak.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all commands | yes | 0.12.17 [VERIFIED] | - |
| Python 3.13 (uv managed) | everything | yes | 3.13.15 [VERIFIED] | - |
| pytest | suite | yes | 9.1.1 [VERIFIED] | - |
| Docker | `docker`-marked tests, DB-outage owner variant, compose `live` service | yes | 29.8.0 [VERIFIED] | skip docker tests |
| `TEST_DATABASE_URL` | `*_pg.py` twins (pool-timeout test, PG store scenarios) | set in this shell [VERIFIED: presence only, value not read] | - | `*_pg.py` silently skip if unset; use `TRADING_CI_STRICT=1` to see |
| psql / pg_isready | optional | not found on PATH | - | tests use the psycopg harness |
| Binance Demo REST/WS, Telegram | owner runs only | NOT PROBED (no signed or network call was made, by rule) | - | twins on fakes for agents |
| VPS host, `.env.live`, healthchecks.io | soak | owner prerequisites, NOT_OBSERVED (24-OWNER-RUNBOOK B-E) | - | none: blocks the soak, not the twins |
| Second Telegram account | G2-014 (24-33 F1) | owner has none (24-OWNER-RUNBOOK notes) | - | does not block Phase 25 twins |

**Missing dependencies with no fallback:** the VPS and owner Demo sessions for the Demo runs and the soak (owner-only, cannot be agent-closed).
**Missing dependencies with fallback:** none relevant to agent work.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 with `asyncio_mode = "auto"` (+ pytest-xdist in `dev` extra) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (marker registration goes here) |
| Quick run command | `uv run pytest tests/test_demo_twin_s04_sl_rejected.py -x` (one twin) |
| Phase suite command | `uv run pytest tests/test_demo_twin_*.py tests/test_phase25_gate.py tests/test_demo_marker_guard.py -x -q` |
| Full suite command | `uv run pytest -m "not docker" -n 4` (sequential for a recorded gate: drop `-n 4`, set `TEST_DATABASE_URL`, `TRADING_CI_STRICT=1`) |
| Owner Demo command | `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s` (owner only; never an agent) |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXEC-01 | entry/stop/TP placed, partial fill sized, SL-rejected closes, -2021 handled | twin (fake) + owner demo | `uv run pytest tests/test_demo_twin_s01_happy.py tests/test_demo_twin_s02_partial.py tests/test_demo_twin_s03_crossed_sl.py tests/test_demo_twin_s04_sl_rejected.py -x` | Wave 0 (S01 base exists: `tests/test_live_demo_smoke.py`) |
| EXEC-01 | cancel racing fill, restart cuts | twin | `uv run pytest tests/test_demo_twin_s05_cancel_race.py tests/test_demo_twin_s07_restart_cuts.py -x` | Wave 0 |
| EXEC-02 | foreign order, doubled position, manual close, stale feed, divergence to SAFE_MODE | twin | `uv run pytest tests/test_demo_twin_s14_safe_mode.py tests/test_demo_twin_s15_foreign.py tests/test_demo_twin_s16_s17_drills.py -x` | Wave 0 |
| EXEC-03 | replayed/concurrent APPROVE+CONFIRM place exactly one entry; restart does not re-send | twin | `uv run pytest tests/test_demo_twin_s06_replay.py tests/test_live_replay_restart.py -x` | S06 Wave 0; `test_live_replay_restart.py` exists |
| APRV-01 | card text carries required fields in the live process | twin (via `assert_live_text`) | `uv run pytest tests/test_demo_twin_s01_happy.py -x` | Wave 0 |
| APRV-02 | one-time token, plan hash, replay idempotence on the composed runner | twin | same as S06 | Wave 0 |
| OPS-01 | SAFE_MODE enter/exit, drills (unprotected, stale feed, manual close, api_down via injected 429/418, db failure), operator commands | twin | `uv run pytest tests/test_demo_twin_s10_gate.py tests/test_demo_twin_s11_db_outage.py tests/test_demo_twin_s18_unprotected.py tests/test_demo_twin_s19_operator.py -x` | Wave 0 |
| OPS-02 | live credentials refused in the Demo suite; evidence has no secret; mode/host guard | unit | `uv run pytest tests/test_demo_marker_guard.py tests/test_demo_env_guard.py -x` | Wave 0 |
| D-03 | `demo` tests skipped under `-m "not docker"`; every `tests/demo` test carries the marker | unit | `uv run pytest tests/test_demo_marker_guard.py -x` | Wave 0 |
| D-08 | zero DEMO branches in `src/execution`, `src/risk`; pinned allow-list in `src/live` | AST | `uv run pytest tests/test_demo_same_code_path.py -x` | Wave 0 |
| D-11 | health tick: one verdict row per tick, check rows on change, `db_writes` stays fresh | unit | `uv run pytest tests/test_live_health_journal_volume.py -x` | Wave 0 |
| D-13 (R-24) | pool timeout becomes `StoreUnavailable` | unit/PG | `uv run pytest tests/test_persistence_pool_timeout.py -x` | Wave 0 |
| criterion 3 | soak evaluator: hash check, order-after-registration, criteria, restart rule | unit (fixture journal) | `uv run pytest tests/test_evaluate_demo_soak.py -x` | Wave 0 |
| criterion 4 | `DEMO_VS_MAINNET.md` rows all carry an evidence label; every scenario id appears in the catalog and runbook | gate | `uv run pytest tests/test_phase25_gate.py -x` | Wave 0 |
| (owner) all S01-S20 on Demo | owner-run | manual / `-m demo` | owner command above | owner session; evidence files are the proof |

### Sampling Rate
- **Per task commit:** the single twin or unit file the task touched (< 30 s each; scenario twins run on virtual time with `forbid_real_sleep`).
- **Per wave merge:** the phase suite command above.
- **Phase gate:** full suite sequential on a clean tree with `TEST_DATABASE_URL` set and `TRADING_CI_STRICT=1`, saved under `evidence/`, then `uv run ruff check && uv run ruff format --check`, `uv run mypy src`, `uv lock --check`, `uv run python scripts/verify_decision_alignment.py all`.

### Wave 0 Gaps
- [ ] `pyproject.toml` marker `demo`; `tests/conftest.py` collection hook; `tests/demo/conftest.py` env guard; `tests/test_demo_marker_guard.py`
- [ ] `tests/support/fault_edge.py` (FaultEdge) with its own unit tests
- [ ] `tests/support/demo_scenarios/` skeleton, `catalog.py`, `evidence_index.py`
- [ ] A Demo-side environment factory (`build_demo_env`) that calls `build_wiring(... exchange_edge=...)` (or the optional `default_assemble` parameter)
- [ ] Coverage inventory: one table mapping S01-S20 to the existing tests that already assert the behaviour (so twins reuse, not duplicate)
- [ ] `tests/test_demo_same_code_path.py` (D-08 allow-list), `tests/test_phase25_gate.py`
- [ ] R-24 and R-25 failing tests first (`tdd_mode` is true in `.planning/config.json`)
- [ ] `scripts/evaluate_demo_soak.py` + `tests/test_evaluate_demo_soak.py` with a fixture journal

## Security Domain

`security_enforcement` is enabled, ASVS level 1 (`.planning/config.json`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (exchange API keys, Telegram allow-list) | BINANCE_DEMO_* only in the process env; Telegram chat and user-id gates already in `src/live` (`authorized_chat_gate`, `authorized_user_gate`); the programmatic owner uses the authorized ids of the test config, never a bypass in `src` |
| V3 Session Management | partial (listenKey lifecycle, approval tokens) | existing supervisor keepalive/rekey; one-time token (`issue_one_time_token`) |
| V4 Access Control | yes | Demo-only commands (`/demo_signal`) built only when mode is DEMO (`src/live/smoke_injection.py:287-300`); owner-only run rule (D-01) |
| V5 Input Validation | yes | evidence and journal payloads are fixed codes and enum fields; scenario inputs are Decimal; do not copy exception text into evidence (class name only, as `record_failure`) |
| V6 Cryptography | partial | SHA-256 for the soak registration and bundle manifest (stdlib `hashlib`); never hand-roll signing (SDK signs) |
| V7 Error handling and logging | yes | `Redactor.scrub` + post-write scan; listenKey replaced by `LISTEN_KEY_MARKER` |
| V14 Configuration | yes | env guard refusing `BINANCE_LIVE_*`, LIVE mode, non-Demo host; no secret in repo, commit, log, chat |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Demo suite run against mainnet by an env mistake | Elevation / Tampering | `admit_smoke_environment` (DEMO only, LIVE creds refused), `demo_guarded_sdk_factory` re-reads the host after SDK build, pytest-level `BINANCE_LIVE_*` refusal |
| Demo tests running in CI or the agent's suite | Information disclosure / DoS | collection hook (Pitfall 1), guard test, no credentials in CI |
| Secret leakage into evidence (keys, listenKey, Telegram token, order ids are fine) | Information disclosure | `EvidenceRecorder.write` scrub and post-write re-scan, deterministic redaction; test seeds sentinel secrets like `tests/test_live_demo_smoke.py:SENTINELS` |
| Injected fault edge reaching production | Tampering | edge lives only in `tests/support`; AST test that `src` never imports `tests`/`scripts` (`LIVE_FORBIDDEN_IMPORTS` already enforced) and that `exchange_edge` stays `None` in `default_assemble` |
| Real 418/429 ban of the owner/VPS IP | DoS | inject only; never provoke (owner rule); edge throttles any real loop |
| Replay of APPROVE/CONFIRM | Spoofing / Repudiation | one-time token, plan hash binding, durable intent row, deterministic client ids (EXEC-03, APRV-02) - scenario S06 proves it on Demo |
| Foreign actor on the Demo account (S15) | Tampering | reconcile flags and SAFE_MODE; the scripted foreign actor uses a clearly non-system client-id prefix and cleans up |

## Sources

### Primary (HIGH confidence, read this session)
- In-repo: `.planning/phases/25-demo-integration-test-campaign/25-CONTEXT.md`; `AGENTS.md`; `.planning/REQUIREMENTS.md` (lines 58-75, 146-153); `.planning/ROADMAP.md` Phase 25 entry (lines 1382-1430) and Phase 20 inherited items; `scripts/demo_rehearsal.py` (docstring, `EvidenceRecorder`, `SmokeEnv`, `_bring_up`, `_smoke_sequence`, `_safe_mode_drill`, `main`); `scripts/demo_probe.py` (docstring, `CASE_HANDLERS`); `scripts/export_soak_evidence.py`, `scripts/soak_host_acceptance.py`, `scripts/evaluate_trial_soak.py` (headers); `deploy/compose-soak.sh`, `deploy/soak.env.example`; `docker-compose.yml` comments; `tests/support/live_smoke_env.py`, `live_composed_rig.py`, `fake_binance_exchange.py` (docstring and method list); `tests/conftest.py`; `tests/test_phase24_gate.py`, `tests/test_live_ast_guards.py`, `tests/test_live_demo_smoke.py` (test list); `src/live/smoke_injection.py`, `signal_source.py`, `runtime.py` (`default_assemble`, `shutdown_in_order`, `DEMO_SYMBOLS`), `wiring.py` (`exchange_edge`, `record`, `DB_WRITE_MAX_AGE`), `health.py`; `src/ops/store_executor.py`, `src/persistence/uow.py`, `src/ops/drills.py`; `src/adapters/binance_client.py:255-276`; `docs/DECISIONS.md` D040, D056, D079, D080, D083, D098, D102; `.planning/phases/20-reconcile-safe-mode-hardening/20-DEFERRED.md` (Demo section and 2026-10-22 results); `.planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md` (R-21..R-28), `24-REVIEW.md` IN-02, `24-OWNER-RUNBOOK.md`; `.planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md`; `.planning/DEMO-EVIDENCE-PLAN.md` (safety section); `.github/workflows/ci.yml:73`; `pyproject.toml` pytest config; the COMPLETE smoke evidence file shape (`09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json`, structure inspected).
- Context7 `/pytest-dev/pytest`: skip-by-default marker via `pytest_collection_modifyitems` (the `--runslow` example).
- pytest version: `uv run pytest --version` -> 9.1.1.

### Secondary (MEDIUM confidence)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info (WebFetch): Demo REST `https://demo-fapi.binance.com`, WS `wss://demo-fstream.binance.com`; 418 bans "from 2 minutes to 3 days"; limits per IP; page lists no Demo-vs-mainnet differences.
- https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams (and Keepalive/Start/Close/Event-User-Data-Stream-Expired pages) via WebSearch summary: listenKey valid 60 minutes, PUT extends, -1125 means recreate, `listenKeyExpired` event, single connection valid 24 h.
- https://www.binance.com/en/support/faq/9be58f73e5e14338809e3b705b9687dd (search summary only): Demo Trading unsupported-feature list and virtual-fund resets; the Terms of Use carry the differences (not read).

### Tertiary (LOW confidence)
- None used for a recommendation. Binance Demo matching-engine and liquidity differences are **not documented in any source read**; they feed `DEMO_VS_MAINNET.md` only as `NOT_OBSERVED`/`DOCS` rows until the owner records evidence.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new package; everything is in-repo and was read.
- Architecture (twin + fault edge + gating): HIGH on seams and feasibility (code read); MEDIUM on the real-Demo effect of each injected fault (A2-A4).
- Pitfalls: HIGH for 1-6 (each verified by reading the cited lines); MEDIUM for 9-10 (judgement).
- Binance Demo behaviour: MEDIUM-LOW; no Demo-vs-mainnet differences list exists in the docs read.

**Research date:** 2026-11-07
**Valid until:** 2026-12-07 for repo-derived findings (changes if Phase 24 owner steps or R-21/R-22 decisions land); Binance doc facts 30 days.
