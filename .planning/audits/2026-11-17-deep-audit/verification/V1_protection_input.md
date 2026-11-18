# Verification input V1_protection
Claims and locations only. Retrace independently (VERIFIER_BRIEF.md).

## G-0250
- Claim: one `found=False` by id closes the whole position at market, enters SAFE_MODE and ends the plan, while the real stop may still rest. The stop is not re-read afterwards ("never read again").
- Location: src/execution/protection.py:2316-2337
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: DESIGN

## G-0300
- Claim: Two back-to-back zero position reads taken under a second after the fill are accepted as proof of flat: the plan goes FLAT and the sweep cancels its REST-confirmed stop while the position exists.
- Location: src/execution/protection.py:2571-2584
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: DEFECT

## G-0301
- Claim: An emergency close whose POST outcome is unknown and that REST never finds is held PENDING_UNKNOWN for ever: no second reduce-only close is sent, no stop is placed in CLOSE_REQUIRED/CLOSE_FAILED, and the coordinator's operator controls refuse.
- Location: src/execution/emergency_close.py:794-873
- Claimed severity: now LOW, mainnet HIGH
- Classification claimed: DESIGN

## G-2203
- Claim: Documented definitive refusals that are not in the code table (-4131, -4118, -2023, -2025, -4045, ...) and the documented 100%-failure 503 variants are treated as an unknown outcome; for the emergency close this freezes the single close attempt as UNKNOWN and no further close is sent.
- Location: src/execution/emergency_close.py:736-819
- Claimed severity: now LOW, mainnet HIGH
- Classification claimed: GAP
