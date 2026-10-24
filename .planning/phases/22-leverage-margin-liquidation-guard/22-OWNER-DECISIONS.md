# Phase 22 owner decisions (plan 22-16)

Recorded on 2026-10-24 and updated the same day with the owner's answer. Each section has the lines "Status:", "Built default in Phase 22:", "Who decides:" and "Source:". Every default named below was checked against the code on 2026-10-24 before it was written. Demo facts are demo-observed, not mainnet.

Owner answer of 2026-10-24, verbatim (as relayed to the assistant that applied it):

> O-1: đòn bẩy x5, isolated, có thể config thông qua telegram. còn lại chọn hết theo recommend

The four items are DECIDED and APPLIED, recorded as DECISIONS D085. The owner adopted the assistant's recommendation for O-2, O-3 and O-4 ("the rest as recommended") and set O-1 to leverage 5, ISOLATED. Setting the three margin keys does not open the live path: fourteen required keys stay `NOT_CONFIGURED` and `LIVE_ORDERS_DISABLED` stays (`tests/test_phase22_gate.py` and `tests/test_execution_limits.py` pin this). The owner-run Demo cases of 2026-10-24 (`22-DEMO-RESULTS.md`) recorded exchange facts; they are single samples, demo-observed, not mainnet, and criteria 1 to 3 are still NOT Demo-proven through the guard.

## O-1 Target leverage and who else changes the symbol (D-02, D-04)

Status: DECIDED and APPLIED (owner, 2026-10-24; DECISIONS D085)

Owner answer, verbatim: "đòn bẩy x5, isolated, có thể config thông qua telegram" (the part of the answer above that names O-1).

Decision: the target leverage is 5 and the margin type is ISOLATED. `TARGET_LEVERAGE` = 5 and `TARGET_MARGIN_TYPE` = `ISOLATED` in `src/execution/symbol_config_guard.py` are unchanged, and so is the 5x cap check of the guard (commit 01ddc37f, verification W1). The system MAY change the margin type and the leverage of a FLAT symbol (no position, no open order, no open algo order) on the owner's own Demo or live account, through `SymbolConfigGuard` only; it journals the previous configuration (`MARGIN_CONFIG_CHANGED`) and never restores it. This is the owner's permission to change a symbol the owner may also trade by hand.

New owner requirement, NOT built and NOT designed: the owner wants to set the leverage and the margin type from Telegram. It is recorded in `22-DEFERRED.md` with the owner "future phase (Phase 24 composition or a new phase)". A design must keep: owner chat only, a two-step confirm, a flat symbol only, never above the D035 cap of 5 (raising the cap needs its own DECISIONS row), and the mutation only through `SymbolConfigGuard`.

Built default in Phase 22 (unchanged by the answer): the target is the D035 cap itself, held as the constant `TARGET_LEVERAGE` and passed to `SymbolConfigGuard` as a required keyword argument with no default; the composition of Phase 24 passes it.

Fact from the Demo run of 2026-10-24 (not a decision): the owner's probe limits file used `order.config_target_leverage` = 5; BTCUSDT on the Demo account is now ISOLATED x5 (it was CROSSED x20) and the probe does not restore it.

Who decides: the owner (decided above). The assistant recorded the answer and applied it.

Source: `22-CONTEXT.md` D-02, D-04, OWNER-OPEN O-1; `22-DEMO-RESULTS.md` R-1; `docs/DECISIONS.md` D085.

## O-2 The liquidation buffer: number, definition and home (D-10)

Status: DECIDED and APPLIED (owner, 2026-10-24; DECISIONS D085)

Owner answer: the assistant's recommendation, adopted ("the rest as recommended"): `margin.liquidation_buffer_bps` = 300, provenance `DECISION`, in `config/execution/execution-limits-v1.toml`; it stays an execution-limits key and is not a registry parameter. The deviation from `docs/trading/RISK_MANAGEMENT.md` section 9 (which says "registry parameter") is accepted and recorded there. The number is the owner's choice, not a Demo result.

Built default in Phase 22 (unchanged): the buffer is basis points of the entry price, held in the REQUIRED key `margin.liquidation_buffer_bps` (plan 22-02). It is not a registry parameter, because a hash-locked registry parameter would force a new parameter set, a new `strategy_version` and regenerated research records while the backtest has no liquidation model (D075, D076). The pure predicate is strict (the liquidation price must lie beyond the stop minus the buffer, never equal).

Fact from the Demo run of 2026-10-24 (not a decision): on one long sample, tier 1, the exchange liquidation price matched the local formula only with the entry fee netted from the isolated wallet; the local functions therefore take a required `entry_fee_rate` (no default). No short sample and no higher tier was observed. This bears on the formula, not on the buffer number.

Who decides: the owner (decided above).

Source: `22-CONTEXT.md` D-10, OWNER-OPEN O-2; `22-DEMO-RESULTS.md` R-7; `docs/trading/RISK_MANAGEMENT.md` section 9; `docs/DECISIONS.md` D085.

## O-3 Bracket maximum age, margin headroom and the free-margin basis (D-11, D-13)

Status: DECIDED and APPLIED (owner, 2026-10-24; DECISIONS D085)

Owner answer: the assistant's recommendation, adopted: `margin.max_bracket_age_ms` = 60000 and `margin.headroom_bps` = 1000 (both `DECISION`), and `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` in `src/risk/margin_check.py` is flipped to True. Evidence for the flip: the owner's Demo run of 2026-10-24, two samples (CROSSED x20 and ISOLATED x5), `availableBalance` fell by exactly the resting order's initial margin (`22-DEMO-RESULTS.md` R-4 and R-5). Effect: a PLACED claim placed at or before the reading is no longer counted a second time; a PLACED claim placed after the reading still counts, and a RESERVED claim always counts. A mainnet sample at the Phase 26 canary re-checks the netting; a wrong True can only let the exchange reject with -2019 at placement.

Built default in Phase 22 (before D085): the two keys were REQUIRED and `NOT_CONFIGURED` (plan 22-02); the constant was False, so the guard counted PLACED entries again on top of `availableBalance`, which could only over-refuse.

Who decides: the owner (decided above).

Source: `22-CONTEXT.md` D-11, D-13, OWNER-OPEN O-3; `22-DEMO-RESULTS.md` R-4, R-5; `docs/DECISIONS.md` D085.

## O-4 A failed post-fill liquidation check: close or only alert (D-12)

Status: DECIDED (owner, 2026-10-24; DECISIONS D085), recorded only; nothing is composed before Phase 24

Owner answer: the assistant's recommendation, adopted: the policy is `CLOSE_POSITION` (`LiquidationFailurePolicy`).

Built default in Phase 22 (unchanged): both members of `LiquidationFailurePolicy` (`CLOSE_POSITION`, `ALERT_ONLY`) exist in `src/execution/liquidation_watch.py` behind a required constructor argument with no default and no module default. The watch itself is built and tested but is NOT active: `ProtectionCoordinator` defaults `liquidation_watch` to None and nothing composes it before Phase 24. The Phase 24 composition MUST pass `CLOSE_POSITION`. A watch that raises inside the coordinator is a close whatever the policy.

Who decides: the owner (decided above).

Source: `22-CONTEXT.md` D-12, OWNER-OPEN O-4; `22-13-SUMMARY.md`; `docs/DECISIONS.md` D085.

## Evidence-gated switch (not a numbered item)

`AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` (see O-3) is the only evidence-gated constant of Phase 22. It is True since D085 (2026-10-24); the Demo observed the netting twice (demo-observed, not mainnet), and a mainnet sample at the Phase 26 canary re-checks it.

The assistant recorded the owner's answers and applied them; it decided none of these items itself.
