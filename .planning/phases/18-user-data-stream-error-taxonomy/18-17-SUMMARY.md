---
phase: 18-user-data-stream-error-taxonomy
plan: 17
subsystem: scripts/operator-tools
status: complete
tags: [demo-probe, D055, D-15, D-16, D-17, D-18, G2-029, EXEC-01, EXEC-02, evidence, dry-run, operator-tool, T-18-51, T-18-52, T-18-53, T-18-54]
requires: [18-09, 18-12, 18-13, 18-16]
provides:
  - scripts/demo_probe.py (EVIDENCE_SCHEMA, CASE_ORDER, REQUIRED_CASES, OPTIONAL_CASES, READ_ONLY_CASES, CASE_HANDLERS with the four read-only cases, CaseResult, CaseContext, CaseHandler, ProbeRig, ProbePort, StreamControl, wait_up_to, ProbeRecorder, run_probe, account_state, cleanup_symbol, build_dry_run_rig, check_probe_evidence, probe_acceptance_verdict, GuardedProbePort, MutationRefused, FrameLog, event_record, LiveStream, live_clock, build_live_rig, evidence_stem, parse_config, main)
  - tests/probe_fakes.py additions (FakeProbePort, RecordingProbePort, write_probe_limits, ok_observation, error_observation, MUTATING_OPERATIONS)
  - tests/test_demo_probe_cases.py, tests/test_demo_probe_evidence.py, tests/test_demo_probe_cli.py
affects:
  - plan 18-23 (registers the cases that send orders in CASE_HANDLERS, consumes ProbeRig, CaseContext, CaseResult, wait_up_to, cleanup_symbol and the port unchanged, adds the registry-completeness test and the per-order quantity and notional bound)
  - plan 18-20 (blocking-human: the owner runs `--execute` on Demo; the first connected run of this code)
  - plan 18-21 (corrects the semantics fake from the recorded evidence)
tech-stack:
  added: []
  patterns:
    - case registry walked in a fixed order; each handler returns exchange answers as data, ProbeBanned is the only exception that crosses it on purpose
    - one wait helper (one sleep of the owner's timeout, no polling cadence); injected clock and sleep; a single wall-clock function, pinned by an AST guard with negative controls
    - dry run invokes every registered handler against a recording port; serialization rewrites the cases to NOT_REHEARSED and keeps the planned requests
key-files:
  created:
    - scripts/demo_probe.py
    - tests/test_demo_probe_cases.py
    - tests/test_demo_probe_evidence.py
    - tests/test_demo_probe_cli.py
  modified:
    - tests/probe_fakes.py
decisions:
  - "The symbol must be flat (no open order, no algo order, no position) and the position mode readable before the probe; otherwise nothing is sent and the run exits 3. Cancel-all would otherwise cancel orders the probe did not open."
  - "In hedge mode the cleanup's closing market order uses the row's position side and omits reduceOnly (hedge mode rejects any reduceOnly, plan 18-12); in one-way mode it is position side BOTH with reduce-only true. An unknown position mode sends no close."
  - "A 418 or 429 answer recorded as data (not only a ProbeBanned refusal) stops the run: no per-case cleanup, no final cleanup; the final cleanup is NOT_VERIFIED and the operator is told to check the account by hand."
  - "ProbePort also carries marker() and raw_frames_since(marker) (one sequence number over events, raw payloads and states) so fixtures can be cut per case."
metrics:
  duration: "about 21 minutes (2026-10-16T08:03Z to 08:25Z)"
  completed: 2026-10-16
  tasks: 2
  files: 5
estimate:
  tokens: 98000
  tasks: 2
actuals:
  tokens: 52000
  tasks: 2
  commits: 3
plan_head_before: 046c318a22c90831b1cbcf921bbfebb6348e2fef
plan_head_after: df51ccb36d276a5b02791bc3ee865d2e0036de4f
---

# Phase 18 Plan 17: Demo probe safety envelope and the read-only cases Summary

`scripts/demo_probe.py` is the Demo probe of D055, D-16 and G2-029. It walks a case registry in the D-16 order of risk against a project-owned port and records every exchange answer as data. After every case and at the end it cleans up and verifies the account is flat. It writes one scrubbed `demo-probe-evidence/schema-1` file. Every record is labelled "demo-observed, not mainnet" and says that D055 stays OPEN.

This plan builds the safety envelope (runner, clock, sleep and wait contracts, cleanup, evidence contract, verdict and CLI gates) and the four read-only not-found cases. The dry run walks all 16 required cases, plus each enabled optional case. It invokes the four registered handlers against the recording port and records what they would send. Plan 18-23 registers the cases that send orders.

Nothing in this plan contacted Binance. Every run was a dry run or a test on fakes; `--execute` was never passed.

## Commits

`commits: 3`, measured as `git rev-list --count 046c318..df51ccb`. All three are this plan's.

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 54b642d | runner, registry, clock and sleep contracts, `wait_up_to`, read-only cases, cleanup, recorder, checker, dry-run `main`; `FakeProbePort`, `RecordingProbePort`; case and evidence tests |
| 2 | 8e3f95c | `GuardedProbePort`, `FrameLog`, `LiveStream`, `live_clock`, `build_live_rig` (one gate), per-case frames and fixtures, `probe_acceptance_verdict`, banner, the execute path of `main`; CLI gate, source-scan and AST-guard tests; verdict and frame tests |
| 2 (test) | df51ccb | `build_live_rig` assembles offline with the real SDK client and one shared gate |

## What was built

- **Cases and order.**
  - `CASE_ORDER` holds the 16 required ids in the D-16 order: the four read-only not-found cases, `duplicate_client_algo_id`, three id-reuse cases, the D055 cases and the G2-029 additions.
  - The three optional ids follow; they run only when enabled in the probe limits file.
  - `--only` narrows a run. It refuses unknown, empty, repeated or not-enabled ids.
- **Handler contract.**
  - The signature is `async handler(context: CaseContext) -> CaseResult`.
  - `CaseResult` refuses an OBSERVED result without observations and a NOT_OBSERVED or ERROR result without a reason.
  - `ProbeBanned` is the only exception a handler lets through on purpose: it stops the run. Any other exception becomes ERROR "the handler raised <Type>" and the run continues.
  - In an `--execute` run, an id without a handler is ERROR "no handler registered". In a dry run it is NOT_REHEARSED with `handler_registered` false.
- **Read-only cases.** Each probes a client id the run never used and records the answer as data: query order, query algo order, cancel order and cancel algo order. An unexpected success is OBSERVED with the note `unexpected: the id existed`. Client ids have the form `dprobe-<tag>-<start stamp>-<n>`, checked against the exchange's 36-character id shape.
- **Time.**
  - `ProbeRig(port, clock, sleep, …)`: every evidence time and the file-name stamp come from `rig.clock()`. A clock that is naive or not UTC raises ValueError before the first port call.
  - `wait_up_to(rig, predicate, timeout_seconds)` checks the predicate once, sleeps once through `rig.sleep(timeout)` if it is false, then checks once more. It refuses a timeout that is not a positive int.
  - `live_clock` is the only wall-clock read.
- **Cleanup (`cleanup_symbol`).**
  - Runs cancel-all for normal orders, cancel-all for algo orders, then reads positions.
  - Each residual row gets one market order on the opposite side for the absolute amount, using the hedge-mode or one-way rule from the decisions above.
  - Then it checks for zero orders, zero algo orders and a flat position through `wait_up_to(…, cleanup_timeout_seconds)`, recording the exact remaining state.
  - The run ends `CLEANUP_FAILED` (exit 1) when the final cleanup is not flat, and prints an OPERATOR line.
- **Outcomes and exit codes.**

  | Outcome | Exit code | When |
  |---------|-----------|------|
  | `ABORTED_NO_ORDER` | 3 | the symbol was not flat, or its state was unreadable, before the probe |
  | `ABORTED_BAN` | 1 | a ban or a rate-limit answer stopped the run; every case not yet run is NOT_OBSERVED "run aborted: ban" |
  | `CLEANUP_FAILED` | 1 | the final cleanup is not flat |
  | `FAILED` | 1 | a case ERROR, a failed per-case cleanup, or a crash |
  | `COMPLETE` | 0 | none of the above |

- **Evidence.**
  - Required keys: schema, mode, proof_class (FAKE or REAL_DEMO), label, environment, symbol, started_utc, finished_utc, account_before, account_after, cases, cleanup, d055, outcome.
  - Additional keys: settings (file names and sha256 values, owner values), market (mark price, filters), stream, ban, failures, fixtures, live_port_calls, notes and acceptance.
  - `check_probe_evidence` enforces every rule the plan lists. It also flags a repeated case id, cases out of `CASE_ORDER` order, a proof class that does not match the mode, and an error answer missing class, code, category or message.
- **Dry run.**
  - `RecordingProbePort` reads come from a static FAKE market fixture of a flat account. Every mutating call and every per-case query is a planned request answered `ok=True {"dry_run": "true"}`.
  - The sleep moves `VirtualTime` itself, so the dry run never waits.
  - For serialization, every case becomes NOT_REHEARSED with the reason `dry run: nothing was sent`. Observations and notes are dropped; planned requests are kept.
- **Live path.**
  - `GuardedProbePort` runs the environment guard before every call and delegates each method explicitly. In dry-run mode it refuses every mutating operation with `MutationRefused`. `position_mode()` returns an observation: a gate refusal becomes `ProbeBanned`, and an exchange error becomes data.
  - `build_live_rig` checks the configured row, then loads credentials. Any LIVE variable refuses the run.
  - It builds the client with `build_sdk_client` and the ratified client limits. The streams config uses `sdk_reconnect_*`. The guard is `assert_environment` plus the streams-URL check.
  - It constructs ONE `RestRateLimitGate` and shares it with `BinanceProbeAdapter`, its `BinancePublicMarketData`, the `BinanceUsdmAdapter` position-mode reader, `SdkListenKeyPort` and the supervisor.
  - `LiveStream` runs `UserDataSupervisor` under `capture_raw_user_events` for the whole run and stops with `close_listen_key=True`.
- **Frames and fixtures.**
  - Each case records the typed events, the stream states and, with `--fixtures-dir`, scrubbed raw frames named `<case id>-<NNN>-<event>.json`. `provenance.md` labels them RECORDED_DEMO, or FAKE_DRYRUN for a dry run.
  - If the stream does not start, the cases still run and every frame field is NOT_OBSERVED with the reason.
  - A dry run aimed at `tests/fixtures/phase18/recorded_demo` is refused.
- **Verdict and CLI.**
  - `probe_acceptance_verdict` returns PASS or FAIL with a reason for each expected case, then the rules cleanup, account_state, label_and_d055, evidence and proof_class (FAKE never passes), then `overall`. `main` stores it in the evidence.
  - The banner covers the label, the D055 rule, the listenKey singleton and the owner's approval of the limits file (O-18-03).

## Verification

All commands ran as `UV_OFFLINE=1 uv run --frozen --extra dev …`. The full suite was not run (memory limit).

- Task 1 verify: `pytest -m "not docker" tests/test_demo_probe_cases.py tests/test_demo_probe_evidence.py tests/test_operator_evidence.py -x` gave 176 passed.
- Task 2 verify: the three probe files gave 218 passed:

  | File | Passed |
  |------|--------|
  | `test_demo_probe_cases.py` | 47 |
  | `test_demo_probe_evidence.py` | 78 |
  | `test_demo_probe_cli.py` | 93 |

- Plan verification set plus the smoke files: the three probe files, `test_binance_probe.py`, `test_binance_probe_contract.py`, `test_operator_evidence.py`, the three `test_user_data_smoke_*` files, `test_no_unratified_defaults.py`, `test_binance_client_config.py`, `test_execution_secret_posture.py`, `test_binance_secret_redaction.py` and `test_redaction.py` gave 736 passed.
- Scans over `scripts/` also passed (239 passed): `test_analytics_edge_guards`, `test_decision_alignment`, `test_paper_exit_evaluator`, `test_universe_freeze`, `test_env_example`, `test_kill_gate_clock`, `test_paper_shadow_isolation`, `test_code_version`, `test_demo_rehearsal_safety`.
- Linting and types:
  - `ruff check`: all checks passed.
  - `ruff format --check`: 603 files already formatted.
  - `mypy src`: no issues in 199 source files.
  - `mypy scripts/demo_probe.py` (outside the gate): no error in the script. It reports two existing errors in `tests/support/limits.py:191`, which this plan does not touch.
  - `uv lock --check`: 60 packages, unchanged.
- The dry-run tests patch `asyncio.sleep`, `time.sleep`, `socket.getaddrinfo`, `socket.create_connection`, `requests.Session.request` and `build_sdk_client` to fail. `socket.socket` refuses any non-loopback connect, as in plan 18-16.
- Mutation check: with `refuse_if_present=()` in `build_live_rig`, the four LIVE-variable refusal tests and the source test fail (5 failed). The source was restored from a scratch copy.
- The offline construction test builds the real SDK client with sockets still patched. It shows that `build_live_rig` composes without error and that every holder (probe adapter, public reader, position-mode reader, listenKey port, stream) holds the same gate.

## TDD Gate Compliance

- **Task 1 (tracer).** The tests failed first (ImportError: `scripts.demo_probe` missing), then passed after the script was written. The tracer gate re-ran the Task 1 verify end to end: 176 passed.
- **Task 2.** 91 of the new tests failed first (missing `GuardedProbePort`, `probe_acceptance_verdict`, `FrameLog`, `live_clock` and the `main` seams), then passed. The offline construction test was added after the implementation; the mutation check above stands in for its red step.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Correctness] The symbol must be flat before the probe**
- **Found during:** Task 1.
- **Issue:** cleanup cancels every open normal and algo order of the symbol and closes any position. On a symbol that already holds orders or a position, the probe would destroy state it did not create, and the after-state check would mean nothing.
- **Fix:** `account_before` aborts with outcome ABORTED_NO_ORDER (exit 3) before any order when the symbol is not flat, or when its state or position mode is unreadable. Every case is then NOT_OBSERVED. Tested. The smoke has the same rule (plan 18-16, deviation 3).
- **Commit:** 54b642d.

**2. [Rule 1 - Bug avoided] Hedge-mode cleanup omits reduceOnly**
- **Issue:** the plan says the closing market order uses "reduce_only true". Hedge mode rejects any reduceOnly parameter (plan 18-12 interpretation note), so the close would fail and the account would stay unflattened.
- **Fix:** one-way mode sends position side BOTH with reduce-only true. Hedge mode sends the row's LONG or SHORT position side with `reduce_only=None` (the parameter is omitted). Tested for long and short in both modes.
- **Commit:** 54b642d.

**3. [Rule 3 - Blocking] The dry-run sleep advances virtual time itself**
- **Issue:** `VirtualTime.sleep` suspends until another task calls `advance`. A dry-run wait (for example a non-flat re-read) would hang forever.
- **Fix:** `build_dry_run_rig` records the duration in `VirtualTime.sleeps` and calls `advance(seconds)`. Nothing sleeps in real time; the tests patch `asyncio.sleep` and `time.sleep` to fail.
- **Commit:** 54b642d.

**4. [Rule 3] The supervisor needs a float sleep**
- **Issue:** `UserDataSupervisor` types its sleep `Callable[[float], …]`.
- **Fix:** `build_live_rig` and `main` take `sleep: Callable[[float], Awaitable[None]]`. That is also a valid `ProbeRig.sleep`, which is `Callable[[int], …]`.
- **Commit:** 8e3f95c.

### Interpretation notes (no behavior beyond the plan)

- **`tests/probe_fakes.py`.** The file already existed (plan 18-12, SDK-level fakes). The plan's project-level fakes were appended to it, together with the TEST_ONLY `write_probe_limits` helper.
- **`ProbePort`.** The plan names `frames_since(marker)` and `stream_states_since(marker)`. The port also has `marker()` and `raw_frames_since(marker)`, which share one sequence number, so each case can cut its frames and fixtures.
- **`ProbeRig`.** It has the plan's `port`, `clock` and `sleep`, plus optional `real`, `stream`, `planned` and `live_calls`, like `SmokeRig`.
- **Per-case cleanup.** When a per-case cleanup is not flat but the final cleanup is flat, the outcome is FAILED (exit 1). It is CLEANUP_FAILED only when the final state is not flat.
- **Ban during the run.** After a ban, neither the per-case cleanup nor the final cleanup runs (every REST call would be refused or extend the ban). The final cleanup is NOT_VERIFIED, and an OPERATOR line asks for a manual check of the Demo account.
- **Drift.** The probe preflight does not measure server-time drift; the smoke does. Every signed call carries the ratified `recvWindow`, and a -1021 answer would be recorded as data. See the findings.

## Findings (not changed: outside the plan's files)

- **Credential names.** `scripts/demo_rehearsal.py` and `.env.example` still use the `BINANCE_TESTNET_API_*` names for Demo (already in `deferred-items.md` from plan 18-16). The probe reads only `BINANCE_DEMO_API_KEY` / `BINANCE_DEMO_API_SECRET`, or their `_FILE` forms.
- **No drift check in the probe preflight.** Plan 18-20 or 18-23 may want the smoke's `measure_clock_drift` gate before the first order. It would need the gated public `server_time`, which `BinanceProbeAdapter` does not expose.
- **Left for plan 18-23.** The registry-completeness test (every `CASE_ORDER` id has a handler) and the per-order quantity and notional bound against `max_notional_quote` belong to plan 18-23, as the plan states. Until then, an `--execute` run records 12 required cases as ERROR "no handler registered", plus any enabled optional case.

## Known Stubs

The cases that send orders are not registered yet, by design of this plan. The 12 required ids from `duplicate_client_algo_id` to `triggered_market_exit_lifecycle` and the 3 optional ids have no handler (`scripts/demo_probe.py`, `CASE_HANDLERS`). They are NOT_REHEARSED with `handler_registered` false in a dry run and ERROR in an executed run. Plan 18-23 registers them. `.planning/WINDOWS.md` does not exist, so no ledger entry was appended.

## Threat Flags

None beyond the plan's register. T-18-51 to T-18-54 are mitigated as follows:

- There is no host, key, secret or LIVE option.
- The guard runs before every call.
- A LIVE credential variable refuses the run.
- `--execute` needs a terminal and the exact phrase.
- A dry-run port cannot reach a mutating method.
- Cleanup runs after every case and in the final path, with one bounded wait.
- The label and D055-OPEN are checked by the schema.
- A ban or a rate-limit answer stops the run with no retry.

## Self-Check: PASSED

- FOUND: scripts/demo_probe.py, tests/probe_fakes.py, tests/test_demo_probe_cases.py, tests/test_demo_probe_evidence.py, tests/test_demo_probe_cli.py
- FOUND commits: 54b642d, 8e3f95c, df51ccb
