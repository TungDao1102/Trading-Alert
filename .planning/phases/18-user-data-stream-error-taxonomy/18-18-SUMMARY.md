---
phase: 18-user-data-stream-error-taxonomy
plan: 18
subsystem: docs / live evidence
status: complete
tags: [live-smoke, demo, user-data-stream, sdk-route, evidence, blocking-human, EXEC-05, OPS-02]
requires: [18-01, 18-09, 18-16]
provides:
  - "evidence/user-data-smoke-EVIDENCE-20261016T140446Z.json (proof_class REAL_SMOKE)"
  - "evidence/18-smoke-check.txt (dry-run line, criteria a to h, sdk_route_delivery, plan 18-19 line)"
  - "decisions/18-smoke-limits.toml and decisions/18-DEC-O-18-03-smoke.md (the user's approval, option values)"
  - "tests/fixtures/phase18/recorded_demo/smoke/ (two RECORDED_DEMO ORDER_TRADE_UPDATE frames, NEW and CANCELED, plus provenance.md)"
  - "docs/SOURCES.md Phase 18 section: the Demo hosts, the conflicting /private URL forms and the blocked re-read, recorded"
affects: [18-19, 18-20, 18-21, 18-22, 18-25]
key-files:
  created:
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-smoke-limits.toml
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-03-smoke.md
    - .planning/phases/18-user-data-stream-error-taxonomy/evidence/18-smoke-check.txt
    - .planning/phases/18-user-data-stream-error-taxonomy/evidence/user-data-smoke-EVIDENCE-20261016T140446Z.json
    - tests/fixtures/phase18/recorded_demo/smoke/
  modified:
    - docs/SOURCES.md
decisions:
  - "The smoke order limits were corrected before the user approved them: the first proposal (quantity at the minimum quantity, far_price_fraction 0.5) would have failed on Demo (MIN_NOTIONAL 50, PERCENT_PRICE multiplierDown 0.95). Approved values: BTCUSDT, quantity 0.0008, far_price_fraction 0.96, event_wait_seconds 30, cleanup_timeout_seconds 60."
  - "Plan 18-19 (direct transport) is not needed: sdk_route_delivery is PASS."
metrics:
  completed: 2026-10-16
  tasks: 4
  commits: 5
---

# Phase 18 Plan 18: live Demo smoke of the user-data stream Summary

The first real proof of the user-data stack against Binance passed. The user ran the Demo smoke (BTCUSDT, one far resting BUY limit, then cancel) on the connected machine with Demo keys set in the shell. The evidence file is REAL_SMOKE, passes `check_smoke_evidence`, ended COMPLETE and FLAT, and has no failures. `sdk_route_delivery` is PASS: typed `ORDER_TRADE_UPDATE` events with execution type NEW and CANCELED reached the project callback through the SDK `user_data` route. So plan 18-19 is not needed.

## Commits

All on branch `phase-18-smoke` (worktree `Trading-Alert-p18`), not merged into `develop` and not pushed.

| Task | Commit | Content |
| --- | --- | --- |
| 1 Dry run on the connected machine | 847271f | check file line "dry run on the connected machine: PASS" (FAKE evidence, no Binance contact, 127 tests) |
| 2 Documentation re-read | e8df78a, 3333957 | SOURCES Phase 18 section: the blocked executor re-read, then the orchestrator's WebFetch findings |
| 3 Approval of the limits | 3f3a13c | `18-smoke-limits.toml` and `18-DEC-O-18-03-smoke.md` (option: values, the user's words verbatim) |
| 3 and 4 Live run and its check | 18cd1c5 | the REAL_SMOKE evidence, the two recorded frames, the check file |

The live run itself was typed by the user (`DEMO SMOKE BTCUSDT`); no agent ran `--execute`.

## Acceptance items (evidence of 2026-10-16T14:04:46Z)

| Item | Result | Detail |
| --- | --- | --- |
| a listenKey start | PASS | |
| b SDK subscription | PASS | one private connection |
| c typed NEW and CANCELED through the SDK route | PASS | |
| d keepalive | PASS | |
| e forced transport drop | PASS | UNKNOWN, SYNCING, LIVE; gap 1431 ms; one snapshot after the drop |
| f PUT after DELETE | OBSERVED | `BAD_REQUEST`, code -1125, category INVALID_LISTEN_KEY; equals the assumed value |
| g no key, secret, signature or listenKey | PASS | also grepped in the committed evidence and fixtures: zero hits |
| h evidence passes `check_smoke_evidence` | PASS | |

Other facts from the file: clock offset -298 ms (uncertainty 139 ms, within limits); symbol filters were read and the order passed the band, step and notional checks; end state FLAT; no failures and no stream failures.

## What the run settled

- Demo serves a listenKey and a user-data socket (`wss://demo-fstream.binance.com`, REST `https://demo-fapi.binance.com`). The documentation says neither; this is observed live only.
- The error code of a keepalive on a closed key is -1125 on Demo (the assumed value).
- The SDK route delivers typed order events for a plain listenKey subscription, so the structural unknown in research C2 is answered for Demo.

## Documentation re-read (Task 2)

The executor session had no WebFetch and curl got the AWS WAF challenge on every page, so the executor recorded the blocked attempt. The orchestrator then read pages with WebFetch (summaries, not character-exact, not verified live) and recorded: the Demo REST and WebSocket base URLs; that general-info says only "Most of the endpoints can be used in the testnet platform"; that the user-data-streams page confirms -1125, the 60-minute key and the 24-hour connection; and that Live-Subscribing documents SUBSCRIBE for public streams only.

## Contradictions and open items

- The `/private` URL form is still unresolved in the documentation. The Important-WebSocket-Change-Notice page lists `wss://fstream.binance.com/private/ws?listenKey=<key>&events=...` and says JSON SUBSCRIBE is supported; the user-data-streams page shows only `/private/ws/<listenKey>`. The smoke ran through the SDK, which worked, but the form the SDK uses was not captured as a separate fact. A direct connection (plan 18-19, not needed now) or a later change of the SDK route must test both forms.
- Still UNVERIFIED in SOURCES: the `o.*`, `a.*`, `B` and `P` field tables of ORDER_TRADE_UPDATE, ALGO_UPDATE and ACCOUNT_UPDATE (never rendered), the SUBSCRIBE parameter format for a listenKey, the new-connection rate limit, and the not-found and duplicate `clientAlgoId` error codes. The two recorded frames now give one real example of the `o` object (keys include `si`, `ss`, `gtd`, `V`, `er`, `pm`).
- The first limits proposal was wrong (see decisions). The tool would have stopped with exit 3 before any order; no order was affected.

## Deviations

- Task 2 did not run as the plan describes (WebFetch in the executor): the orchestrator did the re-read and committed it separately.
- The plan says the executor proposes no limit values. The orchestrator proposed values, found them invalid against the Demo filters, corrected them, and recorded only the user's confirmation of the corrected set.

## Next

- 18-20 (Demo probe) is the next blocking-human plan: the owner approves its own order limits and runs `--execute`.
- 18-21, 18-22 and 18-25 can now use the recorded Demo frames and this evidence.
- Branch `phase-18-smoke` has to be merged into `develop` (STATE.md and ROADMAP.md of `develop` were not touched here).
