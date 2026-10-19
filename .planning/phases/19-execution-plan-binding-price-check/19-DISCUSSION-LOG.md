# Phase 19: Execution Plan Binding + Pre-Placement Checks - Discussion Log

> Audit trail only; not consumed by downstream agents. Mode: `--auto` (recommended option chosen without prompting). Date: 2026-10-19.

## Gray areas (all auto-selected)

| Area | Question | Selected | Source of the choice |
|---|---|---|---|
| Binding | Where do symbol and side come from? | The hashed plan, never the caller | ROADMAP criterion 1 |
| Binding | Quantity above approved? | Reject, never resize | ROADMAP criterion 1, F-302 |
| Pre-placement | Numeric validity and staleness bounds? | `NOT_CONFIGURED` limits, live refuses while unset | Repo pattern for ratified keys; no value invented |
| Protection | Stop before or after the fill? | After the first fill, closePosition=true, REST-confirmed | Owner adoption 2026-10-18 (19-NOTES) |
| Protection | Hedge Mode? | Unsupported in V1, fail closed | 19-NOTES |
| Emergency close | Mechanism? | MARKET reduce-only, deterministic id, split by MARKET_LOT_SIZE | D034, 19-NOTES |
| TP legs | Resize on late fills? | No; place after entry terminal | G2-032 settled in 19-NOTES |
| TP legs | Single-TP fallback vs NO_TRADE | Implement NO_TRADE, fallback OWNER-OPEN | Backtest parity (G4-007) |
| EXEC-07 | Registry parameter for TP1 fraction? | Not changed; OWNER-OPEN | D052 item c |
| Taxonomy | Wire exchange-error taxonomy in manager? | Yes (src/WR-02) | Phase 18 review |
| Persistence | `realized_risk` with the fill | Yes, with migration | G4-008 |

## Notes
- Todos: none matched.
- No DECISIONS row, ROADMAP line or code was changed by this discussion. The D055 text is a draft only.
- Scope creep redirected to Deferred: model (b), Hedge, 999.1, maker entries, Phase 18 skipped review items.
