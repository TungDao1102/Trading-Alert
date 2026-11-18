# Verification input V4_alerting
Claims and locations only. Retrace independently (VERIFIER_BRIEF.md).

## G-2003
- Claim: Telegram is the only human channel: the live heartbeat probe checks only loop liveness and the held marker, so SAFE_MODE, a naked position or a Telegram outage all keep the off-host check green.
- Location: src/live/config.py:395-426
- Claimed severity: now LOW, mainnet HIGH
- Classification claimed: DESIGN
