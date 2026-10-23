# Phase 22: Leverage, Margin + Liquidation Guard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-23
**Phase:** 22-leverage-margin-liquidation-guard
**Areas discussed:** all four, auto-selected (when and how margin/leverage is set; the liquidation buffer; the pre-entry liquidation price; the available-margin check)

---

The owner was offered the four areas as a multi-select question and answered: "chạy với mode --auto giúp tôi, vì tôi không có nhiều kiến thức lắm" (run it in --auto mode for me, I do not have much knowledge). Per `modes/auto.md` the assistant selected all areas and chose the recommended option for every question, without further prompts. The `--auto` auto-advance into plan-phase and execute-phase was NOT run: the owner asked for the discussion in auto mode only, and the phase adds mutating Binance calls, so planning and execution wait for the owner's go-ahead.

## When and how margin type and leverage are set

| Option | Description | Selected |
|--------|-------------|----------|
| Guard before each approved entry: read, set only if different, read back, else NO_TRADE | REST is the truth; never inherits account defaults (D035); one call per run, never retried | ✓ |
| Set once per symbol at startup | Fewer calls, but a manual change on the account between runs goes unnoticed | |
| Set on every entry unconditionally | Simple, but a needless mutating call each time and a failure mode on a symbol with open orders | |

**Choice (auto):** read, change only when different, verify by a second read (D-01 to D-07).
**Notes:** target leverage is the D035 cap (5); a lower value is OWNER-OPEN O-1. A symbol with a position or orders and a mismatching configuration is NO_TRADE, nothing is cancelled to make room (protects manual positions).

## The liquidation buffer

| Option | Description | Selected |
|--------|-------------|----------|
| Fraction of the entry price, an execution-limits key (owner number) | Slippage and gaps scale with price; no strategy version change | ✓ |
| Fraction or multiple of the entry-to-stop distance | Scales with the setup's own risk | |
| Hash-locked registry parameter | Matches the wording of RISK_MANAGEMENT section 9, but needs a new parameter set, a new strategy_version and regenerated research records, and the backtest has no liquidation model | |

**Choice (auto):** fraction of the entry price, kept in `config/execution/execution-limits-v1.toml` (D-10); the number and the home are OWNER-OPEN O-2.
**Notes:** RISK_MANAGEMENT section 9 says "registry parameter"; the planner records the deviation for the owner's DECISIONS row. No number is chosen from backtest results.

## The liquidation price before entry

| Option | Description | Selected |
|--------|-------------|----------|
| Compute locally from the leverage bracket and maintenance margin, then compare with the exchange value after the fill | The exchange has no liquidationPrice before a position exists | ✓ |
| Wait for the exchange value after the fill | Too late to refuse the plan | |
| Hard-coded maintenance margin | Forbidden by criterion 2 | |

**Choice (auto):** local pure module, formula taken from the official docs by the researcher (D-08, D-09, D-11); post-fill comparison feeds the protection path (D-12); whether a failed check closes (default) or only alerts is OWNER-OPEN O-4.

## The available-margin check

| Option | Description | Selected |
|--------|-------------|----------|
| availableBalance covers new initial margin + fees + approved-but-unplaced plans + headroom; resting entries are already netted by the exchange | Counted inside the approval transaction through the Phase 21 reservation rows | ✓ |
| Subtract resting entries again | Risks double counting; to be confirmed by an owner-run Demo case | |
| Use equity instead of availableBalance | Ignores margin already locked | |

**Choice (auto):** D-13 to D-15, with a new reservation column and migration 0012. The headroom number is OWNER-OPEN O-3.
**Notes:** the claim that `availableBalance` already deducts resting orders is to be proven from the docs and one owner-run Demo case before the planner relies on it.

---

## Claude's Discretion

Module placement, adapter method names, reason-code names, migration column design, check order, fixtures and plan/wave split.

## Deferred Ideas

Open-position liquidation-distance monitoring, dynamic leverage, automatic margin top-up, a registry-parameter buffer with a backtest liquidation model, mainnet attestation.
