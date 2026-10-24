# Phase 22 owner decisions (plan 22-16)

Recorded on 2026-10-24. Each section has the lines "Status:", "Built default in Phase 22:", "Who decides:" and "Source:". Every default named below was checked against the code on 2026-10-24 before it was written. Demo facts are demo-observed, not mainnet.

All four items are OPEN. No number is written for any of them: the three margin limit keys stay `NOT_CONFIGURED` in value and provenance, so the live path still refuses (`tests/test_phase22_gate.py` pins this). The owner-run Demo cases of 2026-10-24 (`22-DEMO-RESULTS.md`) recorded exchange facts; none of them sets a number, flips a flag or chooses a parameter.

## O-1 Target leverage and who else changes the symbol (D-02, D-04)

Status: OPEN

Built default in Phase 22: the target is the D035 cap itself, 5, held as the constant `TARGET_LEVERAGE` in `src/execution/symbol_config_guard.py` (with `TARGET_MARGIN_TYPE` = `ISOLATED`) and passed to `SymbolConfigGuard` as a required keyword argument with no default; the composition of Phase 24 passes it. The guard changes a symbol only when it is flat with no open order and no open algo order (D-04); it journals the previous configuration (`MARGIN_CONFIG_CHANGED`) and never restores it. A lower target, or a rule about symbols the owner also trades by hand (the guard would change the margin type and leverage of such a symbol on its own), is the owner's.

Fact from the Demo run of 2026-10-24 (not a decision): the owner's probe limits file used `order.config_target_leverage` = 5, a value the assistant proposed; BTCUSDT on the Demo account is now ISOLATED x5 (it was CROSSED x20) and the probe does not restore it. Changing it back is the owner's choice. This does not settle whether the system may change a symbol the owner uses by hand.

Who decides: the owner. The assistant did not decide it.

Source: `22-CONTEXT.md` D-02, D-04, OWNER-OPEN O-1; `22-DEMO-RESULTS.md` R-1.

## O-2 The liquidation buffer: number, definition and home (D-10)

Status: OPEN

Built default in Phase 22: the buffer is basis points of the entry price, held in the REQUIRED key `margin.liquidation_buffer_bps` of `config/execution/execution-limits-v1.toml`, value and provenance `NOT_CONFIGURED` (plan 22-02). It is not a registry parameter, because a hash-locked registry parameter would force a new parameter set, a new `strategy_version` and regenerated research records while the backtest has no liquidation model (D075, D076). The pure predicate is strict (the liquidation price must lie beyond the stop minus the buffer, never equal). `docs/trading/RISK_MANAGEMENT.md` section 9 still says "registry parameter" until the owner's DECISIONS row settles the home; a DECISIONS row is needed before any number is set, as for D084. The owner-run isolated case (`isolated_position_liquidation_price`) only records the exchange's figure; it chooses nothing.

Fact from the Demo run of 2026-10-24 (not a decision): on one long sample, tier 1, the exchange liquidation price matched the local formula only with the entry fee netted from the isolated wallet; the local functions therefore take a required `entry_fee_rate` (no default). No short sample and no higher tier was observed. This bears on the formula, not on the buffer number.

Who decides: the owner. The assistant did not decide it.

Source: `22-CONTEXT.md` D-10, OWNER-OPEN O-2; `22-DEMO-RESULTS.md` R-7; `docs/trading/RISK_MANAGEMENT.md` section 9.

## O-3 Bracket maximum age, margin headroom and the free-margin basis (D-11, D-13)

Status: OPEN

Built default in Phase 22: `margin.max_bracket_age_ms` (milliseconds) and `margin.headroom_bps` (basis points of the margin needed) are REQUIRED keys, value and provenance `NOT_CONFIGURED` (plan 22-02); `BracketCache` and `MarginGuard` refuse to be built while they are unset. The free-margin basis is evidence-gated: `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` in `src/risk/margin_check.py` stays False until the owner has read `22-DEMO-RESULTS.md` and a DECISIONS row says so. While it is False the guard counts PLACED entries again on top of `availableBalance`, which can only over-refuse.

Fact from the Demo run of 2026-10-24 (not a decision): in two samples (CROSSED x20 and ISOLATED x5) `availableBalance` fell by exactly the resting order's initial margin (notional divided by leverage) while the order rested. That is two samples on one host. The constant is still False, as stated.

Who decides: the owner. The assistant did not decide it.

Source: `22-CONTEXT.md` D-11, D-13, OWNER-OPEN O-3; `22-DEMO-RESULTS.md` R-4, R-5.

## O-4 A failed post-fill liquidation check: close or only alert (D-12)

Status: OPEN

Built default in Phase 22: both members of `LiquidationFailurePolicy` (`CLOSE_POSITION`, `ALERT_ONLY`) exist in `src/execution/liquidation_watch.py` behind a required constructor argument with no default and no module default; the D-12 default is `CLOSE_POSITION` and the composition of Phase 24 passes the value. The watch itself is built and tested but is NOT active: `ProtectionCoordinator` defaults `liquidation_watch` to None and nothing composes it before Phase 24. A watch that raises inside the coordinator is a close whatever the policy (rare error case, stated so the owner can decide).

Who decides: the owner. The assistant did not decide it.

Source: `22-CONTEXT.md` D-12, OWNER-OPEN O-4; `22-13-SUMMARY.md`.

## Evidence-gated switch (not a numbered item)

`AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` (see O-3) is the only evidence-gated constant of Phase 22. The Demo observed the netting twice; the constant changes only with a DECISIONS row, and that row is the owner's.

The assistant recorded these items and decided none of them.
