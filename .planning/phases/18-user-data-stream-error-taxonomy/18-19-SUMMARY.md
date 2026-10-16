---
phase: 18-user-data-stream-error-taxonomy
plan: 19
subsystem: evidence gate
status: complete
tags: [transport-decision, sdk-route, skipped-by-design]
requires: [18-11, 18-14, 18-17, 18-18, 18-23]
provides:
  - "evidence/18-transport-decision.txt (transport: sdk)"
key-files:
  created:
    - .planning/phases/18-user-data-stream-error-taxonomy/evidence/18-transport-decision.txt
decisions:
  - "The live smoke of plan 18-18 delivered typed ORDER_TRADE_UPDATE NEW and CANCELED through the SDK user_data route (sdk_route_delivery PASS), so no direct transport is built."
metrics:
  completed: 2026-10-16
  tasks: 1
---

# Phase 18 Plan 19: transport decision Summary

Task 1 (the gate) ran and recorded `transport: sdk`, derived from `user-data-smoke-EVIDENCE-20261016T140446Z.json` (`sdk_route_delivery` PASS, criterion c PASS).

Tasks 2 to 4 are SKIPPED BY DESIGN, as the plan states: they build the direct documented-URL transport only when `sdk_route_delivery` is FAIL. This is a recorded skip, not a blocked task. No dependency was added, `pyproject.toml`, `uv.lock` and the scripts are unchanged, and `aiohttp` stays an indirect dependency.

Open point kept for later: the documentation conflict about the `/private` URL form (path form against `?listenKey=&events=`) was not tested directly, because the SDK route worked. A future direct transport would have to test both forms.
