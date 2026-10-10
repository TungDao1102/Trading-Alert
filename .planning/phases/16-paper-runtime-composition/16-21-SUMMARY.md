---
phase: 16-paper-runtime-composition
plan: 21
requirements-completed: []
---

# 16-21 SUMMARY: live WS smoke (SC7)

Live public-data smoke against Binance (BTCUSDT, 1m/1h/4h), 15000 s, no BINANCE_* variable, no credentials.
Evidence: `evidence/16-21-ws-smoke-live.json` (proof_class REAL_SMOKE), check: `evidence/16-21-ws-smoke-check.txt`. All SC7 criteria PASS; measurements are observations for 16-27, not thresholds.

Deviation: `--out` is a directory, not a file path, so the output was copied to the expected file name (plan defect). `evidence/16-21-ws-smoke-dryrun.json` is a FAKE dry run, not evidence.
Note: host clock was 182..580 ms behind Binance, which explains negative arrival latencies.
requirements-completed stays empty: PAPER-01/02 close only with real soak evidence (SC9).
