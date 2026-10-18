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

### CLOSED 2026-10-18 (quick task, Demo credential name alignment)

The 18-16 item above is closed. The Demo key is now `BINANCE_DEMO_API_KEY` /
`BINANCE_DEMO_API_SECRET` everywhere it is set or documented: `.env.example`,
`scripts/demo_rehearsal.py` (`ENV_BINANCE_KEY`, `ENV_BINANCE_SECRET`, docstring),
`tests/test_env_example.py`, `tests/test_demo_rehearsal_safety.py`,
`tests/test_demo_rehearsal_flow.py`, and the operator docs (`DEPLOY_GUIDE.vi.md`,
`SECURITY_AND_OPERATIONS.md`, `RUNBOOK.md`). TESTNET stays NOT_CONFIGURED (O-18-01): no
`BINANCE_TESTNET_*` name exists in the template, and `tests/test_env_example.py` pins that.
The OPS-06 guard is the `BINANCE_` prefix refusal in `src/paper/runtime_config.py`, which is
name-independent, so it is unchanged; the paper machine still must hold no `BINANCE_*` variable
(a stale `BINANCE_TESTNET_*` name still refuses, pinned in `tests/test_paper_runtime_env.py`).
Left untouched by rule: `docs/DECISIONS.md`, decision records, SUMMARY/PLAN files and other
recorded evidence, which still mention the old names historically.
