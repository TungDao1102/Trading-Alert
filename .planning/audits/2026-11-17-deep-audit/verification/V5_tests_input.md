# Verification input V5_tests
Claims and locations only. Retrace independently (VERIFIER_BRIEF.md).

## G-1400
- Claim: The Binance-semantics fake used by 30 test files has zero read lag: positions move in the same call as fill(), and by-id queries find an order immediately after placement; only a post-cancel algo lag exists and it is opt-in (3 files). Three escaped defects of this audit (G-0250, G-0253, G-0300) share this cause.
- Location: tests/support/fake_binance_exchange.py:265-819
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: GAP
