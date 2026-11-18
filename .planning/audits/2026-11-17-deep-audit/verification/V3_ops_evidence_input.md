# Verification input V3_ops_evidence
Claims and locations only. Retrace independently (VERIFIER_BRIEF.md).

## G-1101
- Claim: No production code writes the fills table and orders.local_status never leaves NEW, so live analytics see zero trades; deferred item 20D-01 is recorded CLOSED although the gap is open.
- Location: src/persistence/entities.py:692-739
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: GAP

## G-0801
- Claim: A CRITICAL alert whose Telegram send fails (3 attempts, at most 30 s) is dropped for the life of the process, and the 5 minute dedupe window also swallows its repeats, including a different plan on the same symbol.
- Location: src/ops/alerts.py:733-772
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: DESIGN

## G-1302
- Claim: Window = first..last journal row with no coverage/gap criterion; no-order and null round-trip journals pass; export window free; image_commit never checked.
- Location: scripts/evaluate_demo_soak.py:620-1036
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: DESIGN

## G-1501
- Claim: Demo smoke evidence carries no commit, dirty flag or config hash; the 21/21 runs cannot be tied to HEAD (code and limits changed after both runs).
- Location: scripts/demo_rehearsal.py:584-606
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: GAP

## G-1503
- Claim: 'demo-observed' closures rest on a smoke with an injected signal, an immediate taker fill, a direct SAFE_MODE call, an orderly restart and an operator close; stop/TP triggers, resting/partial fills and emergency close never ran.
- Location: .planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md:9-78
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: DESIGN

## G-1508
- Claim: No recorded sequential PostgreSQL gate since 2026-10-20 (IMAGE_COMMIT 36dcad8); 572 code commits / +43k src lines since, including all of src/live.
- Location: .planning/phases/16-paper-runtime-composition/evidence/16-66-gate-post-phase19.txt:1-30
- Claimed severity: now MEDIUM, mainnet HIGH
- Classification claimed: GAP
