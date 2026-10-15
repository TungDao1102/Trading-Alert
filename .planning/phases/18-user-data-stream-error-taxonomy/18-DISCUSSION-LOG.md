# Phase 18: Discussion Log (--auto)

**Date:** 2026-10-15. Mode: `--auto` (no questions asked; recommended default chosen for each area). Human reference only; downstream agents read 18-CONTEXT.md.

| Area | Choice (recommended default) | Alternative not chosen |
|------|------------------------------|------------------------|
| Stream architecture | New adapter module behind a Protocol, official SDK, one supervisor, library + smoke script only | Wire into a running process now (belongs to Phases 24 and 25) |
| State authority | Stream is a hint plus evidence, REST snapshot after any gap, `fold_fills` unchanged | Treat events as authoritative |
| Error taxonomy | Pure int-code table, unknown code = ambiguous, message regex removed | Keep message-text fallbacks |
| Client config | Explicit `DEMO/TESTNET/LIVE`, no inferred default, secret redaction tested | Infer environment from the host |
| Demo probe | Script with dry-run, user types confirmation, evidence JSON, records facts only | Probe also decides D055 |
| Work split | Offline plans plus blocking-human plans for the connected machine | One end-to-end plan |
| Thresholds | Left OPEN (O-18-01): user-owned safety numbers, ratified at a checkpoint | Agent fills defaults (forbidden by D061 H and I) |

User instructions applied: branch and worktree separate (`phase-18`), stop before execute, one retry then note on connection errors, no guessing.

Auto-advance into execute was NOT followed: the chain stops after planning, per the user's instruction.
