---
phase: quick-261108-voe
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/paper/shadow_ledger.py
  - src/paper/shadow_runtime.py
  - src/paper/market_inputs.py
  - src/paper/replay_inputs.py
  - src/paper/shadow_confirm.py
  - src/paper/shadow.py
  - tests/test_paper_market_inputs.py
  - tests/test_paper_replay_inputs.py
  - tests/test_paper_shadow_confirm.py
  - tests/test_paper_shadow_runtime.py
autonomous: true
requirements: [PAPER-02]
user_setup: []

estimate:
  tokens: 150000
  raw_tokens: 150000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "On every 1h bar the paper context factory builds the account state from the SHADOW ledger equity as of the bar close and takes the absolute portfolio thresholds (cluster cap, aggregate cap, daily-loss warning and stop) from the ledger's thresholds as of that close (`ShadowLedger._view_at(close)`). The configured `initial_equity` is read only to start the ledger (16-DEC-EQUITY-BASE, option A)."
    - "With the ledger equity below 600 after realized losses (600 - 7.394061 = 592.605939, the four 16-43 losses), a standard 0.5 % candidate passes the bar pipeline's risk stage AND `ShadowLedger.admit` with the same sized risk. Sized on 600 instead, the same candidate passes the risk stage but `admit` returns CLUSTER_CAP_REJECT (the 16-43 defect); the regression test shows both."
    - "The sizing equity and the thresholds are the ones the backtest engine reads after `roll_to(close)`: the current ledger equity (`engine.py` lines 751/858, `ledger.equity`) and the thresholds resolved against the UTC day-start equity (`ledger.thresholds`)."
    - "Each PAPER_REPLAY_INPUTS record (schema `paper-replay-inputs/2`) carries the per-bar account state AND the four absolute thresholds the risk stage read. The parity replay rebuilds the exact live context (same `context_digest`) and reports zero differences even when the sizing equity is not the day-start threshold base. Records with schema `paper-replay-inputs/1` still rebuild with the derivation that wrote them."
    - "The SHADOW confirm card shows the risk-stage figures: `Quantity` = `verdict.sized.quantity`, `Notional` = that quantity x the adverse-edge entry, `Estimated loss at SL (incl. costs)` = `verdict.sized.realized_risk`. They equal the `planned_quantity` and `sized_realized_risk` the ledger reserves at CONFIRM. When no sizing basis exists, the card says `unavailable` and never shows the planner quantity."
    - "The approval rows keep `approved_quantity` = the planner quantity (`shadow.py` keeps its three `approved_quantity=plan.quantity_after_rounding` sites). No file under `src/live`, `src/execution`, `src/approval`, `params` or `config` changes."
  artifacts:
    - path: src/paper/shadow_ledger.py
      provides: "ShadowLedger.equity_and_thresholds(now_utc) -> (equity, absolute thresholds) from one `_view_at` under the ledger lock"
    - path: src/paper/shadow_runtime.py
      provides: "LedgerRiskInputs.equity_and_thresholds bound by bind_risk_inputs; ConfirmBook(sizing=self._basis_for)"
    - path: src/paper/market_inputs.py
      provides: "RiskInputsProvider.equity_and_thresholds; make_context_factory reads equity and thresholds per bar at the close"
    - path: src/paper/replay_inputs.py
      provides: "REPLAY_INPUTS_SCHEMA paper-replay-inputs/2 with an `absolute_thresholds` group; legacy /1 rebuild kept"
    - path: src/paper/shadow_confirm.py
      provides: "render_confirm_card(..., sized=ReservationBasis | None); ConfirmBook sizing port"
    - path: src/paper/shadow.py
      provides: "ConfirmCardFields quantity/notional/estimated_loss as Decimal | None; the `Estimated loss at SL (incl. costs)` line"
    - path: tests/test_paper_market_inputs.py
      provides: "the 16-43 regression tests of the equity base"
  key_links:
    - from: src/paper/shadow_runtime.py bind_risk_inputs
      to: src/paper/shadow_ledger.py ShadowLedger.equity_and_thresholds
      via: "a lambda field of LedgerRiskInputs (no class in src implements the port; the AST guard stays green)"
      pattern: "equity_and_thresholds"
    - from: src/paper/market_inputs.py make_context_factory.factory
      to: RiskInputsProvider.equity_and_thresholds
      via: "called once per bar with candle.close_time_utc; AccountState(equity=..., risk_rate=account.risk_rate) and absolute_thresholds=..."
      pattern: "equity_and_thresholds\\(close\\)"
    - from: src/paper/pipeline.py _evaluate_live_bar
      to: src/paper/replay_inputs.py replay_inputs_payload
      via: "records context.account_state and the four context.absolute_thresholds values"
      pattern: "absolute_thresholds"
    - from: src/paper/exit_criteria.py parity replay
      to: src/paper/replay_inputs.py context_from_inputs / rebuild_context
      via: "schema /2 rebuilds the thresholds from the recorded group; context_digest verifies"
      pattern: "paper-replay-inputs/2"
    - from: src/paper/shadow_runtime.py ShadowCoordinator.__init__
      to: src/paper/shadow_confirm.py ConfirmBook._new_entry -> render_confirm_card
      via: "sizing=self._basis_for (the same basis ShadowReservations reserves)"
      pattern: "sizing=self._basis_for"
---

<objective>
Apply the owner decision 16-DEC-EQUITY-BASE (option A, 2026-11-08) to the paper runtime:

1. The bar pipeline sizes and gates a candidate with ONE equity base, the SHADOW ledger as of the bar close, as the backtest engine does. Today `make_context_factory` (`src/paper/market_inputs.py` lines 185-188) builds one `AccountState` and one threshold mapping on the constant `initial_equity`, while `ShadowLedger.admit` judges the CONFIRM on the ledger thresholds. After the four losses of 2026-10-27..11-02 every standard candidate was rejected at confirm with CLUSTER_CAP_REJECT and an empty book (evidence `16-43-cap-reject-2026-11-03.md`).
2. The replay-inputs record carries what the risk stage read, so the parity criterion (tolerance zero) still reports zero differences when the equity changes per bar.
3. The SHADOW confirm card shows the risk-stage quantity and risk (what the ledger reserves and the simulated fill reads), not the planner quantity.

Purpose: the trial evidence becomes valid again. Sizing, the portfolio gates at signal time and the gates at confirm time read the same numbers, and the operator sees the quantity that is simulated.
Output: three code changes, each with tests written first (tdd_mode). No parameter set, threshold value, protocol text, allowlist entry, `config/paper/paper-runtime-v2.toml` value, pinned epoch or live-path file changes. This plan does NOT mark PAPER-02 complete (Phase 16 closure rule, ROADMAP criterion 9).

Owner choices this plan applies (locked, from the orchestrator, 2026-11-08):
- The card line is `Estimated loss at SL (incl. costs)` = `verdict.sized.realized_risk`, which includes modeled costs.
- `approved_quantity` of the approval rows (`approval_desk.py`, `shadow.py` lines 436/497/643) keeps the planner quantity. Do not change it.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/phases/16-paper-runtime-composition/decisions/16-DEC-EQUITY-BASE.md
@.planning/phases/16-paper-runtime-composition/evidence/16-43-cap-reject-2026-11-03.md

Run `codegraph explore "<symbols>"` first (`.codegraph/` exists) instead of grep and read loops, e.g. `codegraph explore "make_context_factory bind_risk_inputs ShadowLedger._view_at"`.

## Rules for the executor (read before Task 1)

- Git: never push, never touch `master`. Another session has UNCOMMITTED changes on `develop`: `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, `.planning/config.json`, `.planning/state.json`, plus untracked `.gsd/`, `.planning/milestone.lock`, `package*.json`, `freeze-check/`, `.planning/phases/24-*`. Never stage, commit, restore, stash or edit any of them. Do not edit ROADMAP.md or STATE.md.
- Commit only with explicit paths: `git add -- <path> ...`, then `git commit -o -m "<subject>" -m "<body>" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" -- <path> ...`. Every commit ends with that trailer. TDD order per task: first commit the failing test (`test(quick-261108-voe): ...`), then the fix (`fix(quick-261108-voe): ...`).
- Line endings: the `src/paper/*.py` files and `tests/test_paper_market_inputs.py`, `tests/test_paper_replay_inputs.py`, `tests/test_paper_shadow_runtime.py` are CRLF. `tests/test_paper_shadow_confirm.py` is LF. Keep each file's endings: edit bytes-aware and do not re-save a whole file with other endings. Before each commit, `git diff --stat -- <paths>` must show only the lines you meant to change (a whole-file count means the endings flipped: fix it).
- Every command runs as `uv run ...` from the repository root. Ruff line length 100, mypy strict on `src`, Decimal only, no wall clock in these modules. Run only the tests named in the task; the orchestrator runs the full suite.
- Pinned fixtures: at HEAD, nothing under `tests/fixtures/`, `scripts/` or `docs/` pins a `context_digest`, the replay-inputs schema text or the card text (checked while planning). If a golden or pinned test still moves, do not edit the expected value by hand and do not regenerate anything. Stop and report the test, the old and new value and the cause in the SUMMARY.
- Fail closed: never substitute the configured initial equity, a default or a guessed equity when the ledger gives none. If the ledger equity is not positive, the `AccountState` constructor raises as it does everywhere. Leave that as it is: no context means no candidate.

## Interfaces (current code at HEAD bf41996f; extracted so you need not search)

```python
# src/paper/market_inputs.py (lines 68-77, 168-206)
class RiskInputsProvider(Protocol):
    def open_positions(self, at_utc: datetime) -> Sequence[OpenPosition]: ...
    def daily_loss_quote(self, at_utc: datetime) -> Decimal | None: ...

def make_context_factory(*, parameter_set: ParameterSet, constraints: ConstraintProvider,
                         risk_inputs: RiskInputsProvider, account: AccountConfig,
                         ttl_seconds: int) -> Callable[[Candle], BarContext]: ...
# today: account_state and thresholds are built ONCE before `def factory(candle)`.

# src/paper/loop.py:328
@dataclass(frozen=True)
class BarContext:
    symbol: str; strategy_version: str; parameter_set: ParameterSet
    account_state: AccountState; constraint_snapshot: ConstraintSnapshot; cost_model: CostModel
    open_positions: Sequence[OpenPosition]; daily_loss_quote: Decimal | None
    ttl: timedelta; absolute_thresholds: dict[str, Any]

# src/paper/shadow_ledger.py
class ShadowLedger:
    def __init__(self, *, initial_equity: Decimal, parameter_set_params: Mapping[str, Any],
                 started_at_utc: datetime) -> None: ...
    equity: Decimal            # property, current ledger equity
    ledger: Ledger             # property, the Phase 14 value
    def _view_at(self, at_utc: datetime) -> Ledger: ...  # rolled to the UTC day on a COPY
    def admit(self, *, symbol, direction, sized_realized_risk, planned_quantity, now_utc) -> str | None: ...
    def apply(self, booking: Booking) -> None: ...
    def risk_inputs(self, now_utc: datetime) -> tuple[list[OpenPosition], Decimal]: ...
@dataclass(frozen=True)
class ReservationBasis:
    sized_realized_risk: Decimal
    planned_quantity: Decimal
BasisFn = Callable[[Signal, TradePlan], ReservationBasis | None]

# src/backtest/ledger.py: Ledger(initial_equity, equity, parameter_set_params, thresholds,
#   day_start_utc, equity_at_day_start, day_pnl, last_booking_time_utc, exposures);
#   roll_to(ledger, at_utc); apply_booking(ledger, booking); thresholds re-resolve at day start.

# src/paper/shadow_runtime.py
@dataclass(frozen=True)
class LedgerRiskInputs:                      # lines 237-247
    open_positions: Callable[[datetime], Sequence[OpenPosition]]
    daily_loss_quote: Callable[[datetime], Decimal | None]
def bind_risk_inputs(ledger: ShadowLedger) -> LedgerRiskInputs: ...   # line 250
# ShadowCoordinator.__init__ (lines 425-436): ShadowReservations(ledger, stores, basis_for=self._basis_for),
#   then ConfirmBook(stores, clock=..., ttl_seconds=..., mode=..., mark_price=self._mark_price,
#   on_confirmed=..., recheck=self._open_check, reservations=self._reservations)
# _basis_for(signal, plan) -> ReservationBasis | None  (line 695): from self._plans[plan.plan_hash]
#   .outcome.verdict.sized (quantity, realized_risk); None when the plan context is missing.

# src/paper/replay_inputs.py
REPLAY_INPUTS_SCHEMA = "paper-replay-inputs/1"
def replay_inputs_payload(context, *, setup_window, context_window, window_accept_seq) -> dict[str, Any]
def rebuild_context(payload, *, symbol, parameter_set) -> BarContext   # thresholds = rates x recorded equity
def context_from_inputs(payload, *, symbol, parameter_set) -> BarContext  # checks schema, hashes, context_digest
def context_digest(context: BarContext) -> str   # covers account_state AND the whole absolute_thresholds mapping

# src/paper/shadow_confirm.py
def render_confirm_card(signal, plan, *, mode, mark_price, now_utc, ttl_seconds=CONFIRM_TTL_SECONDS_DEFAULT) -> str
class ConfirmBook(CoreConfirmBook):
    def __init__(self, stores, *, clock, ttl_seconds=..., mode=Mode.SHADOW, mark_price=None,
                 recheck=None, on_confirmed=None, reservations=None) -> None: ...
    def _render_card(self, signal, plan, mark, now_utc, ttl_seconds) -> str: ...
    def _new_entry(self, fields, *, mark, now_utc) -> ConfirmEntry:  # card_text=render_confirm_card(...)

# src/paper/shadow.py:185
@dataclass(frozen=True)
class ConfirmCardFields:
    symbol: str; side: str; quantity: Decimal; entry_ref: Decimal; stop_loss: Decimal
    notional: Decimal; estimated_loss: Decimal; mark_price: Decimal | None
    plan_expiry_utc: datetime; plan_remaining_seconds: int; confirm_ttl_seconds: int
    confirm_until_utc: datetime
# render_shadow_message CONFIRM_CARD lines 282-286: Quantity / Entry (adverse edge) / Stop loss /
#   Notional: {..} quote / Estimated loss at SL: {..} quote
```
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1 (tracer): the bar pipeline sizes and gates with the SHADOW ledger as of the bar close</name>
  <files>src/paper/shadow_ledger.py, src/paper/shadow_runtime.py, src/paper/market_inputs.py, tests/test_paper_market_inputs.py, tests/test_paper_replay_inputs.py</files>
  <behavior>
    - Regression (16-43): ShadowLedger(initial_equity=600, research-run-1-a01 params, started 2026-11-01T00:00Z). Four exit bookings on 2026-11-01 (-1.835028, -1.865155, -1.843585, -1.850293) give ledger equity 592.605939. A 1h BTCUSDT bar closes 2026-11-03T05:59:59.999Z. The factory is bound to `bind_risk_inputs(ledger)`. The standard 0.5 % candidate gives risk-stage verdict "OK", and `ledger.admit(..., sized_realized_risk=verdict.sized.realized_risk, planned_quantity=verdict.sized.quantity, now_utc=close + 40 s)` returns None. On the old code the same test fails with admit == "CLUSTER_CAP_REJECT".
    - The context has account_state.equity == ledger.equity == 592.605939, account_state.risk_rate == 0.005 (config), and absolute_thresholds == `roll_to(ledger.ledger, close).thresholds` (cluster_cap == 0.005 x 592.605939).
    - Discriminating precondition, in the same test: the context rebuilt with `dataclasses.replace` on AccountState(600) and thresholds resolved on 600 (the old arithmetic) still passes the risk stage, but `ledger.admit` returns "CLUSTER_CAP_REJECT".
    - Intraday: add one more loss on 2026-11-03 at 02:00 (-1.85) before the close. Then the context equity is the CURRENT ledger equity (590.755939), the thresholds are the day-start ones (on 592.605939), daily_loss_quote == 1.85, all equal to a Phase 14 `Ledger` reference after the same bookings and `roll_to(close)`. The candidate passes both the risk stage and admit.
    - Factory wiring: a RecordingRisk whose equity (987.65) differs from the config initial equity (1000), with thresholds on another base (990). The context carries equity 987.65, cluster_cap 0.005 x 990, risk_rate from config, and the port is asked three times, each at the bar close.
  </behavior>
  <action>
RED first. In tests/test_paper_market_inputs.py add a section "the equity base (16-DEC-EQUITY-BASE, 16-43 cap reject)" with two tests implementing the first four behavior bullets: `test_a_standard_candidate_passes_the_pipeline_and_the_ledger_after_realized_losses` and `test_the_sizing_equity_and_the_thresholds_are_the_engine_view_at_the_close`. Use real objects: `ShadowLedger` and `bind_risk_inputs` (src.paper.shadow_runtime), `Booking` with kind BOOKING_EXIT (src.backtest.records), `Ledger`, `apply_booking` and `roll_to` (src.backtest.ledger), `load_parameter_set("trend-pullback", "research-run-1-a01")` from src.domain.registry as the ParameterSet (the incident set, cluster_cap 0.005), `AccountConfig(initial_equity=Decimal("600"), risk_rate=Decimal("0.005"))`, ttl 3600 s. For constraints, pass `SimpleNamespace(snapshot_for=lambda symbol, at: SNAPSHOT)` cast to Any, where SNAPSHOT is a `ConstraintSnapshot` for BTCUSDT with price tick 0.1, quantity step 0.000001, min quantity 0.000001, min notional 5, observed one minute before the close. The fine step keeps the sized risk within about 0.05 % of the allowed amount, so the old arithmetic exceeds the 592.6 cap. Run the risk stage with the module's existing `verdict_of(context, close)` helper (it mirrors the `evaluate_risk` call of `src/paper/loop.py` lines 433-449). Put the `admit is None` assertion right after the verdict assertion, so the RED failure shows the incident reason. Write every amount as a Decimal string; no float. Run the tests on the unchanged code, confirm they fail (admit returns CLUSTER_CAP_REJECT; equity 600 != 592.605939), save that output for the SUMMARY, and commit the tests alone.

GREEN, per 16-DEC-EQUITY-BASE option A:
(1) src/paper/shadow_ledger.py: add `ShadowLedger.equity_and_thresholds(self, now_utc: datetime) -> tuple[Decimal, dict[str, Any]]`, next to `risk_inputs`. Under the ledger lock it takes ONE `self._view_at(now_utc)` and returns the view's `equity` and a `dict(...)` copy of the view's `thresholds`. The docstring says these are what the engine reads after `roll_to(close)` (`ledger.equity` for sizing, thresholds re-resolved against the UTC day-start equity) and that the roll is on a copy, never stored. No numeric literal (the module guard `test_the_module_contains_no_numeric_equity_literal` must stay green).
(2) src/paper/shadow_runtime.py: add a third field `equity_and_thresholds: Callable[[datetime], tuple[Decimal, dict[str, Any]]]` to `LedgerRiskInputs` and bind it in `bind_risk_inputs` with a lambda over `ledger.equity_and_thresholds`. Keep functions-as-fields: no class in src may define port methods (`test_src_has_no_default_implementation_of_the_risk_inputs_port`). Update the `LedgerRiskInputs` docstring.
(3) src/paper/market_inputs.py: add `def equity_and_thresholds(self, at_utc: datetime) -> tuple[Decimal, dict[str, Any]]: ...` to the `RiskInputsProvider` Protocol, with a docstring: the equity to size with and the absolute portfolio thresholds, both from the SHADOW ledger as of `at_utc`. In `make_context_factory`, delete the construction-time account state and threshold mapping. Inside `factory(candle)`, call `risk_inputs.equity_and_thresholds(close)` first, then build `AccountState(equity=<that equity>, risk_rate=account.risk_rate)` and pass `absolute_thresholds=<that mapping>`. Open positions and daily loss stay as they are. Remove the now-unused `resolve_absolute_thresholds` import. Update the factory docstring and the module docstring (the "account inputs" bullet): the risk rate comes from the ratified configuration; equity and thresholds come from the port (the SHADOW ledger at the bar close). The `AccountConfig` initial equity is no longer read here; it only starts the ledger (`build_coordinator`). Do not write that config attribute's dotted name anywhere in this module, not even in a docstring: the verify gate counts it.
(4) Test fakes. In tests/test_paper_market_inputs.py, `RecordingRisk` takes the parameter-set params plus keyword-only `equity` (default `ACCOUNT.initial_equity`) and `threshold_equity` (default: the equity). Its `equity_and_thresholds` records the instant and returns the equity and `resolve_absolute_thresholds(parameter_set=params, equity=threshold_equity)`. `build_context` builds the default `RecordingRisk(parameter_set.params)`. Rewrite `test_the_context_carries_config_account_values_and_the_port_inputs` into the factory-wiring bullet; the new name says equity comes from the port. In tests/test_paper_replay_inputs.py, `RiskDouble` keeps its positional signature and gains keyword-only `equity` and `threshold_equity` (both optional) plus a way for `World` to attach the parameter set and the fixture equity (`case["account_state"]["equity"]`) after loading them. Its `equity_and_thresholds` returns (equity or the fixture equity, thresholds resolved on threshold_equity, else on that equity), so every existing World run behaves as before. Leave `FakeRiskInputs` in tests/test_paper_runtime_loop.py unchanged: its harnesses inject `never_called_factory` or never pass the warm-up gate, so the new port method is never asked (the verify run below proves it). Name that in the SUMMARY.

Commit the fix with explicit paths after the verify passes.
  </action>
  <verify>
    <automated>uv run pytest -n 4 tests/test_paper_market_inputs.py tests/test_paper_shadow_ledger.py tests/test_paper_replay_inputs.py tests/test_paper_shadow_runtime.py tests/test_paper_runtime_loop.py tests/test_paper_shadow_reservations.py -q && uv run ruff check src/paper/shadow_ledger.py src/paper/shadow_runtime.py src/paper/market_inputs.py tests/test_paper_market_inputs.py tests/test_paper_replay_inputs.py && uv run ruff format --check src/paper/shadow_ledger.py src/paper/shadow_runtime.py src/paper/market_inputs.py tests/test_paper_market_inputs.py tests/test_paper_replay_inputs.py && uv run mypy src && test "$(grep -v '^\s*#' src/paper/market_inputs.py | grep -c 'account\.initial_equity')" = "0" && test "$(grep -c 'equity_and_thresholds' src/paper/shadow_runtime.py)" -ge 2</automated>
  </verify>
  <done>The two regression tests fail on the old code (recorded RED output: CLUSTER_CAP_REJECT) and pass after the change. The factory reads equity and thresholds per bar from the port at the bar close. `src/paper/market_inputs.py` has 0 non-comment lines with `account.initial_equity` (2 at HEAD). The listed test files, ruff, ruff format and mypy src pass. Two commits (test, fix) with explicit paths and the Sonnet trailer.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: the replay-inputs record carries the absolute thresholds, so parity stays at zero differences</name>
  <files>src/paper/replay_inputs.py, tests/test_paper_replay_inputs.py</files>
  <behavior>
    - The finding behind this task (task_facts item 6): the record already carries the per-bar account state (`_account_form(context.account_state)`), and `context_digest` already covers `absolute_thresholds`. But `rebuild_context` re-derives the thresholds as rates x the RECORDED SIZING equity. Since Task 1, sizing uses the current ledger equity while the thresholds use the day-start equity, so after an intraday booking the rebuilt digest differs and parity refuses the bar ("context_digest differs").
    - New test `test_a_sizing_equity_off_the_day_start_base_replays_with_zero_differences`: World(risk=RiskDouble(equity=9990.00, threshold_equity=10000.00)). The record has account_state.equity "9990.00" and absolute_thresholds.cluster_cap equal to the text of 0.005 x 10000.00. `context_from_inputs` returns the live digest, and `world.parity(world.bundle(tmp_path / "bundle"))` passes. On the Task 1 tree it fails with "context_digest differs".
    - The schema is "paper-replay-inputs/2". `absolute_thresholds` holds exactly the four `RATE_THRESHOLD_KEYS` as Decimal text (values from `resolve_absolute_thresholds` on 10000.00 in the default World). No float.
    - Legacy: a /2 payload from a default World with schema set to "/1" and the group removed still rebuilds to the recorded digest. A /2 payload without the group, or with an extra or missing key in it, raises ReplayInputsError naming `absolute_thresholds`. Any other schema is refused as before.
  </behavior>
  <action>
RED first. In tests/test_paper_replay_inputs.py add the new parity test and the legacy and refusal tests from the behavior list. Update `test_the_replay_inputs_record_carries_what_the_risk_stage_read`: the schema becomes "/2", the expected key set includes "absolute_thresholds", and the group must equal the four values computed in the test with `resolve_absolute_thresholds` and `RATE_THRESHOLD_KEYS` (src.risk.portfolio), not typed by hand. Run them on the Task 1 tree, confirm the new parity test fails with "context_digest differs", save the output, and commit the tests alone.

GREEN in src/paper/replay_inputs.py:
(1) Set `REPLAY_INPUTS_SCHEMA = "paper-replay-inputs/2"` and keep the old text as a private read-only constant for legacy records.
(2) In `replay_inputs_payload`, add `"absolute_thresholds"`: for each key of `RATE_THRESHOLD_KEYS`, the `str` of `context.absolute_thresholds[key]`. If a value is not a Decimal, raise ReplayInputsError (fail closed). Record the four resolved values, not a base equity: the context carries the resolved mapping, the digest already covers it, and no division is needed to rebuild.
(3) In `rebuild_context`, branch on the payload schema. For /2, read the `absolute_thresholds` group with `_group`. It must hold exactly the four keys (missing or extra key: ReplayInputsError naming the group). Build the thresholds as `dict(parameter_set.params)` with those four keys replaced by `_decimal(...)` values. For anything else, keep today's derivation (rates x recorded equity), which is the code that wrote the /1 records.
(4) `context_from_inputs` accepts both schema texts and refuses any other. The digest check is unchanged, and `_CONTEXT_DIGEST_SCHEMA` stays "paper-context/1": existing digests do not move.
(5) Update the module docstring and the `rebuild_context` docstring: /2 rebuilds the thresholds from the record (the ledger's day-start thresholds the risk stage read, 16-DEC-EQUITY-BASE); /1 keeps the old derivation.
Do not change `src/paper/exit_criteria.py`: it already goes through `context_from_inputs`. Commit the fix with explicit paths after the verify passes.
  </action>
  <verify>
    <automated>uv run pytest -n 4 tests/test_paper_replay_inputs.py tests/test_paper_exit_evaluator.py tests/test_soak_evidence_export.py tests/test_paper_decision_surface.py tests/test_paper_market_inputs.py -q && uv run ruff check src/paper/replay_inputs.py tests/test_paper_replay_inputs.py && uv run ruff format --check src/paper/replay_inputs.py tests/test_paper_replay_inputs.py && uv run mypy src && test "$(grep -c '"paper-replay-inputs/2"' src/paper/replay_inputs.py)" = "1" && test "$(grep -c '"paper-replay-inputs/1"' src/paper/replay_inputs.py)" -ge 1</automated>
  </verify>
  <done>New records are schema /2 and carry the four absolute thresholds. Parity passes with zero differences when the sizing equity is off the day-start base; that test failed on the Task 1 tree (RED output recorded). /1 records still rebuild. Malformed groups are refused, naming `absolute_thresholds`. The listed tests, ruff, ruff format and mypy src pass. Two commits with explicit paths and the Sonnet trailer.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: the SHADOW confirm card shows the risk-stage quantity, notional and loss incl. costs</name>
  <files>src/paper/shadow.py, src/paper/shadow_confirm.py, src/paper/shadow_runtime.py, tests/test_paper_shadow_confirm.py, tests/test_paper_shadow_runtime.py</files>
  <behavior>
    - End to end (tests/test_paper_shadow_runtime.py, the real coordinator): `make_outcome` gets a `quantity: str = "0.08"` parameter for the sized quantity. With `make_outcome(quantity="0.05", realized_risk="31.25")`, the planner quantity stays 0.08. After APPROVE the card shows "Quantity: 0.05", "Notional: 2505 quote" (0.05 x 50100, the adverse edge) and "Estimated loss at SL (incl. costs): 31.25 quote", and no "Quantity: 0.08". After CONFIRM, the SHADOW_CONFIRMED payload has reservation.planned_quantity "0.05" and sized_realized_risk "31.25", equal to the card figures. `exposures(rig)` == [(SYMBOL, "LONG", Decimal("31.25"))]. The approval row's `approved_quantity` == Decimal("0.08"), the planner quantity (owner choice). If the CONFIRM is refused for an unrelated reason, pick other numbers with sized quantity != 0.08 that the fill driver accepts, and say so in the SUMMARY.
    - Unit (tests/test_paper_shadow_confirm.py): `render_confirm_card(..., sized=ReservationBasis(sized_realized_risk=Decimal("31.25"), planned_quantity=Decimal("0.05")))` renders those three lines. With `sized=None` the card has "Quantity: unavailable", "Notional: unavailable", "Estimated loss at SL (incl. costs): unavailable" and no planner quantity. Calling `render_confirm_card` without `sized` is a TypeError.
  </behavior>
  <action>
RED first: add the end-to-end test `test_the_confirm_card_shows_what_the_ledger_reserves` and the unit tests from the behavior list. Run them, confirm they fail (the card shows the planner 0.08 and the old label), save the output, and commit the tests alone.

GREEN:
(1) src/paper/shadow.py: in `ConfirmCardFields`, `quantity`, `notional` and `estimated_loss` become `Decimal | None`. Update the docstring: they are the risk-stage figures (`verdict.sized`: what the SHADOW ledger reserves and the simulated fill reads); the loss includes modeled costs; notional = quantity x the adverse-edge entry; None when no sizing basis exists (the reservation then refuses the CONFIRM). In the CONFIRM_CARD branch of `render_shadow_message`, render `Quantity: <plain>` or `Quantity: unavailable`, `Notional: <plain> quote` or `Notional: unavailable`, and a single line `Estimated loss at SL (incl. costs): <plain> quote` or `... unavailable`, through one small helper so the label text appears once. Leave all other lines and every `approved_quantity` site untouched.
(2) src/paper/shadow_confirm.py: `render_confirm_card` gets a keyword-only parameter `sized: ReservationBasis | None` with NO default, so no caller can fall back to the planner figure. Quantity = `sized.planned_quantity`, estimated loss = `sized.sized_realized_risk`, notional = quantity x the adverse-edge `entry_ref`; all three are None when `sized` is None. Stop reading the plan's own quantity field anywhere in this module, and do not name that TradePlan field in a docstring either (a verify gate counts it). Import `BasisFn` and `ReservationBasis` from src.paper.shadow_ledger (no import cycle: shadow_ledger does not import shadow_confirm). `ConfirmBook.__init__` gets keyword `sizing: BasisFn | None = None`, stored on the instance. A private resolver returns None when no port is set; it catches any exception from the port, logs `paper.shadow_confirm.sizing_failed` with `error_class`, and returns None (the `_current_mark` pattern: a card is never blocked by it). `_render_card` and `_new_entry` both pass `sized=<resolver>(signal, plan)`. In `_new_entry`, `card_text=` must stay a direct `render_confirm_card(...)` call (guard `test_the_confirm_entry_card_text_is_assigned_only_from_the_card_composer`). Update the docstrings.
(3) src/paper/shadow_runtime.py: pass `sizing=self._basis_for` to the `ConfirmBook(...)` in `ShadowCoordinator.__init__`. This is how `self._plans[plan_hash].outcome.verdict.sized` reaches the card: the same function `ShadowReservations` reserves with.
(4) tests/test_paper_shadow_confirm.py: `Harness` gets `sizing` with a default that returns `ReservationBasis(sized_realized_risk=Decimal("48"), planned_quantity=Decimal("0.08"))`, so the existing figures hold. Change only the asserted label to "Estimated loss at SL (incl. costs): 48 quote", and add `sized=` to the two direct `render_confirm_card(...)` comparisons.
Do not touch `src/approval/confirm_core.py`, `src/execution/confirm_flow.py` or `approval_desk.py`. Commit the fix with explicit paths after the verify passes.
  </action>
  <verify>
    <automated>uv run pytest -n 4 tests/test_paper_shadow_confirm.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_pg.py tests/test_confirm_core.py tests/test_paper_shadow_reservations.py -q && uv run ruff check src/paper/shadow.py src/paper/shadow_confirm.py src/paper/shadow_runtime.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_runtime.py && uv run ruff format --check src/paper/shadow.py src/paper/shadow_confirm.py src/paper/shadow_runtime.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_runtime.py && uv run mypy src && test "$(grep -v '^\s*#' src/paper/shadow_confirm.py | grep -c 'quantity_after_rounding')" = "0" && test "$(grep -c 'approved_quantity=plan.quantity_after_rounding' src/paper/shadow.py)" = "3" && test "$(grep -c 'Estimated loss at SL (incl. costs)' src/paper/shadow.py)" -ge 1 && test "$(grep -c 'sizing=self._basis_for' src/paper/shadow_runtime.py)" = "1"</automated>
  </verify>
  <done>The card's quantity, notional and loss equal the reserved planned quantity and sized risk (end-to-end test RED then GREEN). With no basis the card says unavailable. `src/paper/shadow_confirm.py` has 0 non-comment lines with `quantity_after_rounding` (1 at HEAD). `shadow.py` still has its 3 `approved_quantity=plan.quantity_after_rounding` sites. The listed tests (the `_pg` file skips without TEST_DATABASE_URL), ruff, ruff format and mypy src pass. Two commits with explicit paths and the Sonnet trailer.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| SHADOW ledger -> bar pipeline | Simulated account state decides sizing and the portfolio gates of every candidate |
| evidence bundle -> parity evaluator | A recorded payload (possibly edited) is rebuilt into a decision context |
| runtime -> Telegram operator | The card figures inform the human CONFIRM decision |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-261108voe-01 | Tampering | src/paper/replay_inputs.py `absolute_thresholds` group | medium | mitigate | `context_digest` covers the full thresholds mapping. `context_from_inputs` recomputes it from the recorded group and refuses on any difference. The group must hold exactly the four `RATE_THRESHOLD_KEYS` (Task 2 refusal tests). Values are Decimal text; the bundle loader already refuses floats. |
| T-261108voe-02 | Spoofing (misleading display) | src/paper/shadow_confirm.py card figures | medium | mitigate | The card reads the same `_basis_for` basis the reservation uses (Task 3 end-to-end test compares card and reservation). With no basis the card shows `unavailable`, never the planner figure. `sized` has no default. |
| T-261108voe-03 | Denial of service | make_context_factory with a non-positive ledger equity | low | accept | `AccountState` raises: no context, no candidate (fail closed, AGENTS). No fallback equity is invented. Reaching it needs about 200 full 0.5 % losses from 600. |
| T-261108voe-04 | Tampering (inconsistent read) | three port calls per bar | low | accept | Equity and thresholds come from one locked `_view_at`. Open positions and daily loss are separate locked reads, as before this plan. All three are dated at the same close, and parity replays whatever was read. |
| T-261108voe-05 | Elevation of privilege | live path | high | mitigate | No file under src/live, src/execution, src/approval, params or config is in `files_modified`. The overall verification checks `git diff --name-only` for those paths. `approved_quantity` stays the planner quantity (Task 3 positive gate). |
| T-261108voe-SC | Tampering | npm/pip/cargo installs | high | mitigate | No package is installed or upgraded by this plan. `uv lock --check` must stay clean (overall verification). No legitimacy checkpoint is needed. |
</threat_model>

<verification>
Run from the repository root after Task 3:
- `uv run pytest -n 4 tests/test_paper_market_inputs.py tests/test_paper_shadow_ledger.py tests/test_paper_replay_inputs.py tests/test_paper_shadow_runtime.py tests/test_paper_shadow_confirm.py tests/test_paper_exit_evaluator.py tests/test_soak_evidence_export.py tests/test_paper_runtime_loop.py -q`
- `uv run ruff check && uv run ruff format --check && uv run mypy src && uv lock --check`
- `git diff --name-only bf41996f..HEAD -- src/live src/execution src/approval params config` prints nothing. If it lists a file, check with `git log --oneline bf41996f..HEAD -- <path>` that the commit is not one of this task's.
- `git status --short` still shows the other session's files exactly as before (modified `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, `.planning/config.json`, `.planning/state.json`; untracked `.gsd/`, `.planning/milestone.lock`, `package*.json`, `freeze-check/`, `.planning/phases/24-*`), none staged or committed.
- `git log --format=%B -6` shows six commits (test + fix per task), each ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
</verification>

<success_criteria>
- The 16-43 defect is reproduced by a test that failed on the old code and passes now: after realized losses, a standard 0.5 % candidate passes the bar pipeline and `ShadowLedger.admit` with no CLUSTER_CAP_REJECT mismatch.
- Sizing equity and thresholds equal the backtest engine's view at the close (current equity, day-start thresholds).
- Parity has zero differences with a per-bar equity (schema /2 records); /1 records still rebuild.
- The SHADOW card quantity, notional and loss incl. costs equal what the ledger reserves; `approved_quantity` unchanged.
- No parameter set, threshold value, protocol, allowlist, paper-runtime config value, pinned epoch, live-path file or dependency changed.
- SUMMARY names the owner follow-ups, which this plan does not do: the change ships as a new paper image and the qualifying trial needs a new epoch pin (D065 item 4, per 16-DEC-EQUITY-BASE). The orchestrator runs the full suite.
</success_criteria>

<output>
Create `.planning/quick/261108-voe-use-the-shadow-ledger-equity-for-sizing-/261108-voe-SUMMARY.md` when done. Include the three RED outputs, the six commit hashes, the `git diff --stat` per commit, the FakeRiskInputs note and any deviation. Do not commit `.planning/` files outside that quick directory; the orchestrator commits the quick directory (PLAN and SUMMARY) with explicit paths.
</output>
