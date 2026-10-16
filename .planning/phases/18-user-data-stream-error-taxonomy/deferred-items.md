# Phase 18 deferred items (out of scope of the plan that found them)

## From plan 18-16 (2026-10-16)

- **Demo credential names in `.env.example` and `scripts/demo_rehearsal.py`.** The ratified
  credential names for DEMO are `BINANCE_DEMO_API_KEY` / `BINANCE_DEMO_API_SECRET`
  (`decisions/18-DEC-O-18-01.md`, `CREDENTIAL_SPECS` in `src/adapters/binance_client.py`).
  `.env.example` (lines 70-71) and `scripts/demo_rehearsal.py` (`ENV_BINANCE_KEY`,
  `ENV_BINANCE_SECRET`, module docstring) still name the Demo key `BINANCE_TESTNET_API_KEY` /
  `BINANCE_TESTNET_API_SECRET`. Plan 18-16 does not list those files, so nothing was changed.
  Effect: `scripts/user_data_smoke.py --execute` reads only the `BINANCE_DEMO_API_*` names (or
  their `_FILE` forms); the operator of plan 18-18 must export those, not the rehearsal's names.
  A later plan should align `.env.example` and the rehearsal (and `tests/test_env_example.py`,
  `tests/test_demo_rehearsal_safety.py`) with the ratified names.
