# Verification input V2_design_risk
Claims and locations only. Retrace independently (VERIFIER_BRIEF.md).

## G-2100
- Claim: D042 condition 1 says the protective SL always resides on the exchange so a VPS outage never leaves a position unprotected. Since D079 the entry is a GTD LIMIT with no stop until the process sees a fill. A crash, reboot or network partition while an entry rests leaves an order that can fill with nothing to place its stop; the live service has restart "no". The risk was named a Phase 24 blocker in 20-DEFERRED and then dropped; the Demo-accepted alternative (pre-placed reduceOnly stop) and the outage risk were never compared for the owner.
- Location: docs/DECISIONS.md:None
- Claimed severity: now LOW, mainnet HIGH
- Classification claimed: DESIGN

## G-2201
- Claim: D079 places the stop only after the fill; its stated premise (-4509) covers only the closePosition variant, the project's own Demo probe showed a pre-placed reduce-only stop works, and no reason for rejecting that alternative is recorded.
- Location: docs/DECISIONS.md:83-83
- Claimed severity: now LOW, mainnet HIGH
- Classification claimed: DESIGN

## G-0403
- Claim: enforce_daily_state has no caller in the live process (known 25-15-F1): at DAILY_STOP resting entries are not cancelled and no daily alert is sent. New here: a code comment claims the placement path does it, and evaluate() consumes the one-shot alert marks for callers that send nothing.
- Location: src/execution/daily_stop.py:229-325
- Claimed severity: now LOW, mainnet HIGH
- Classification claimed: GAP

## G-0700
- Claim: One HTTP 418 without a usable Retry-After closes every REST call of the process for 259200 s (3 days), protective stop, entry cancel, emergency close and listenKey keepalive included, even when the answer body states a ban end two minutes away; the code that would use the body time (D083) ships switched off because rest_gate.ban_end_clock_margin_ms is NOT_CONFIGURED. The deadline is persisted and nothing can clear it.
- Location: src/adapters/binance_ratelimit_gate.py:334-393
- Claimed severity: now LOW, mainnet HIGH
- Classification claimed: DESIGN
