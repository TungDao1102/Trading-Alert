---
phase: 20-reconcile-safe-mode-hardening
plan: 07
subsystem: execution-gate
tags: [rest-gate, restart-recovery, persistence, fail-closed, operator-cli, tdd]

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "plan 20-01 (limits seam; no config key is added by this plan)"
provides:
  - "GateStateRecord, GateStateStore, GateStateCorrupt, GateNotRestored, GateRecoveryStatus, REST_GATE_RECOVERY_REQUIRED in the pure gate module"
  - "RestRateLimitGate(state_store=..., on_alert=...), restore(), recovery_status()"
  - "FileGateStateStore (atomic canonical JSON, explicit initialize bootstrap, inspect, reinitialize)"
  - "python -m src.ops.rest_gate_cli status | clear"
affects: [20-14 REST action queue, 20-21 queue order, 20-24 deferred items, 20-25 SAFE_MODE exit row 6, Phase 24 composition]

tech-stack:
  added: []
  patterns:
    - "Pure module + injected store Protocol: the gate does no I/O, the file store lives in src/ops"
    - "Restart recovery verdict is one-shot per gate instance; only a restart can lift an unknown state"
    - "Refusal subclass of RestGateRefusal so a refused safety action stays PENDING and never bypasses the gate"

key-files:
  created:
    - src/ops/rest_gate_state.py
    - src/ops/rest_gate_cli.py
    - tests/test_gate_restart.py
    - tests/test_rest_gate_cli.py
  modified:
    - src/adapters/binance_ratelimit_gate.py
    - tests/test_binance_ratelimit_gate.py

key-decisions:
  - "Owner O-C = option-a1-with-commands: loss or corruption of initialized state = restricted with no end until the operator runs clear; a2 quarantine and option-b barrier are not built."
  - "No exemption for any request category: check() has no argument; GateNotRestored is a RestGateRefusal."
  - "Unknown or not-restored restrictions report remaining_seconds 1 and until_utc None, never a long wait."
  - "restore() maps a missing record, a corrupt record and an unreadable store to the same unknown-state verdict (decided by type, never by message text, D-10)."
  - "An unknown state is never saved over: a late record() updates memory only, so no valid-looking file can reopen a closed gate."

patterns-established:
  - "State file written tmp + fsync + replace_with_retry; corrupt file renamed aside (.corrupt-<UTC>) and never deleted"

requirements-addressed: [RISK-03, OPS-01]

actuals:
  tokens: 19000
  tasks: 4
  commits: 7
plan_head_before: d2797dab3ff48a8ed8efeb2189a1d1d0a63bda10
plan_head_after: d7ef3ccfd5988bff59ac65abf4ed35e78788e7b8

duration: about 1h 20min
completed: 2026-10-21
status: complete
---

# Phase 20 Plan 07: REST gate restart recovery Summary

**The REST gate now persists its 418 ban and 429 pause deadlines to a small state file and refuses every request (`GateNotRestored`) until `restore()` has read a valid record; a lost or corrupt file blocks all REST with no end until the owner runs `python -m src.ops.rest_gate_cli clear` (option a1, with the status and clear commands).**

## Owner decision O-C

`option-a1-with-commands`

The owner's own words (Vietnamese, verbatim), given in the orchestrator session on 2026-10-21 after the
options, the purpose of the state file, the 3-day figure (the ratified 259200 s wait) and the
consequences were explained:

> O-C tôi muốn có thể tự gỡ ban, nhưng nếu tôi phát hiện ra ban nhầm thì cũng nên có cơ chế để tôi tắt nó đi trên server chẳng hạn

> O-C chọn a1 kèm status/clear, D-15 accept, thêm mục hoãn vào 20-24.

Accepted operational consequence of option-a1, copied from the checkpoint context of
20-07-PLAN.md: a deleted or corrupt initialized state file blocks every REST call, including
emergency reduce-only closes, protective actions and reconciliation reads, until a human acts
with the clear command (initialize() after checking the account); every restart before that
keeps the block (the loss is re-detected, never read as a fresh install); there is no bypass
for any order category.

Task 1 was satisfied by this answer in the orchestrator session; the executor did not stop for it.

## What was built

### Gate (`src/adapters/binance_ratelimit_gate.py`, still pure)

- `RestRateLimitGate(policy, clock, state_store=None, on_alert=None)`. Without a store nothing
  changes and `recovery_status()` is `LEGACY_IN_MEMORY`.
- With a store the gate starts `NOT_RESTORED`: `check()` raises `GateNotRestored`
  (`GATE_NOT_RESTORED`) and `restriction()` returns `until_utc=None`, `remaining_seconds=1`.
- `restore()` (one verdict per gate instance, no in-process clearing):
  - valid record: adopt the deadlines (they only move later), `RESTORED_DURABLE`; a deadline
    recorded before `restore()` is merged and saved afterwards;
  - no record, record that does not parse, or a store that raises: `GATE_STATE_UNKNOWN` with no
    end, `RESTORED_UNKNOWN_STATE`, `on_alert("REST_GATE_RECOVERY_REQUIRED")` once.
- `record()` saves after every change of a deadline, memory first. A failing save never raises into
  the REST caller, keeps the restriction, and reports `PERSISTENCE_FAILED` until a later save
  succeeds. An unknown state is never saved.
- `GateRestriction.until_utc` is `datetime | None`; `GateNotRestored` is a `RestGateRefusal` so plan
  20-14 keeps a refused emergency action as a PENDING row.

### File store (`src/ops/rest_gate_state.py`)

`FileGateStateStore(path, *, clock)`: canonical JSON (schema_version 1, sorted keys, UTC `Z` text),
strict parse (wrong version, naive datetime, unknown or missing key, non-UTF-8 all corrupt), atomic
write through `replace_with_retry`, `initialize(now_utc, operator_id)` refused while any state
file exists, `load()` renames a corrupt file to `<name>.corrupt-<UTC>` (never deleted), `inspect()`
is read-only, `reinitialize(...)` is the operator overwrite used only by `clear`.

### Operator commands (`src/ops/rest_gate_cli.py`)

```
python -m src.ops.rest_gate_cli status --path STATE_FILE
python -m src.ops.rest_gate_cli clear  --path STATE_FILE --operator-id ID --reason TEXT [--force]
```

- `status`: read-only (never renames, moves or writes). Prints the path, whether the file exists,
  parses and is initialized (by whom, when), `ban_until_utc`, `pause_until_utc`, `recorded_at_utc`,
  any future deadline, the recovery status a restart would report (`RESTORED_DURABLE` or
  `RESTORED_UNKNOWN_STATE`), and the line "A recorded deadline cannot tell a real Binance ban from
  the assumed wait; check once by hand before clearing". Exit 0 when the file is valid, 2 when it
  is missing, corrupt or unreadable.
- `clear`: refuses an empty operator id or reason (exit 2). Writes a fresh valid initialized record
  with no deadline (bootstrap-equivalent, `initialized_by` = the operator id), keeps the previous
  file aside (`.replaced-<UTC>`, or `.corrupt-<UTC>` for a corrupt one), prints that it takes effect
  at the NEXT restart through `restore()`. A persisted ban or pause deadline still in the future is
  refused (exit 3, naming the deadline) unless `--force` is given, in which case the output and the
  log say "forced". A failed write leaves the old file untouched and exits 4. It prints the warning
  to stop the trading process first (a running process can write its in-memory deadlines back over
  the cleared file; a failed save in the running process hides its deadlines from the command).
- Every use is logged through structlog with operator id and reason, no secret, no environment
  value. No network, no `.env`, no clock read in the library functions (`main` reads it once). The
  operator id is audit metadata, not authentication: ssh access is the access control until the
  Phase 23/24 remote operator interface (D-15 accepted by the owner).
- Smoke-run against a scratch file (status on missing, clear, status on valid): output as above.

## Task commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | c35d5bee | docs: record owner decision O-C (answered before the executor started) |
| 2 RED | 8ba988db | test: failing tracer tests (collection ImportError was the RED evidence) |
| 2 GREEN | 97e310dd | feat: persisted deadlines, GateNotRestored, FileGateStateStore, bootstrap |
| 3 RED | 86c63052 | test: 15 failing tests for loss, corruption and persistence failures |
| 3 GREEN | 9f8a6ed4 | feat: fail closed on lost or corrupt state, survive persistence failures |
| 4 RED | 1ea80adf | test: failing tests for status and clear (module not found) |
| 4 GREEN | d7ef3ccf | feat: rest_gate_cli status and clear, FileGateStateStore.reinitialize |

The SUMMARY commit follows these seven.

## TDD Gate Compliance

RED then GREEN commits exist for each of Tasks 2, 3 and 4 and are in order (`test(20-07)` before the
matching `feat(20-07)`). RED evidence is the pytest failure seen before each GREEN commit: Task 2 an
ImportError at collection, Task 3 15 failing tests, Task 4 ModuleNotFoundError at collection. No
REFACTOR commit. The Task 4 GREEN commit was amended once (one ruff line-length fix in a docstring and
a string constant) before anything else was built on it.

## Verification actually run

- `uv run pytest -m "not docker" tests/test_gate_restart.py tests/test_rest_gate_cli.py tests/test_binance_ratelimit_gate.py tests/test_phase18_gate.py tests/test_phase19_gate.py` : passed (25 + 22 new tests; phase 18 and 19 gates green after the last code change).
- Also run and green: `tests/test_binance_usdm_signed_calls.py`, `tests/test_userdata_supervisor.py`, `tests/test_binance_probe.py` (consumers of the gate; they use the legacy gate).
- `uv run mypy src` (222 files) clean; `uv run ruff check` and `uv run ruff format --check` clean.
- `git diff --exit-code -- config/binance/ pyproject.toml uv.lock` exits 0.
- Not run: the full suite (orchestrator owns it). Not tested: behaviour on a real filesystem under
  concurrent processes, POSIX directory fsync (not done), whether a real Binance ban outlives 259200 s
  [NOT_TESTED]. Nothing is a [DEMO] claim.

## Deviations from Plan

**1. [Plan scope - option a1] No a2 or option-b machinery.** The record has no `quarantine_*` fields,
there is no `REST_GATE_QUARANTINED` event and no `restart_barrier_ms` keyword. `RESTORED_BARRIER` is kept
in `GateRecoveryStatus` so the enum values stay stable for plan 20-25, but this mechanism never produces
it. The a2-only named tests (repeated quarantine restart, quarantine expiry, quarantine persistence
failure) are replaced by their a1 variants (restart at +0, +1 and +4 days stays blocked with no end;
`initialize`/`clear` then unblocks the next start), as the plan allows.

**2. [Rule 3 - pinned test assertions]** `tests/test_binance_ratelimit_gate.py` pinned the public
method set of the gate, banned the word "restore" in any public name, and listed the allowed imports
of the pure module. The plan requires `restore` and `recovery_status` and an `enum` import, so only
those assertions were updated (public set, the word list, the allowed-imports set); the test names are
unchanged.

**3. [Design] `FileGateStateStore(path, *, clock)` takes a required clock** (the plan example showed
`FileGateStateStore(path)`): the store names a corrupt file with the detection time and the project
rule is no wall clock inside library code. `initialize` and the CLI functions take `now_utc` explicitly.

**4. [Design] `clear` copies the previous file aside, then replaces atomically**, instead of renaming
it first, so a failed write leaves the old file untouched with no stray copy (removed on failure).

**5. [Test wording] `test_cli_module_has_no_network_or_gate_mutation`** allows one adapter import,
the pure gate module `src.adapters.binance_ratelimit_gate`, for the `GateRecoveryStatus` and
`GateStateRecord` types (the plan wording said "no adapter module"); it asserts `RestRateLimitGate` is
not imported and that no `record/restore/check/restriction` call exists in the CLI module.

**6. [Fact check]** `store.py`'s `replace_with_retry` pulls `src.data.store` (Polars and the SDK adapter
module) into the CLI process as a transitive import. Accepted: it is the plan's named key link.

## Known limits and items for 20-24 (deferred list, owner: "thêm mục hoãn vào 20-24")

1. No composition passes a `state_store` or `on_alert` yet, so every real gate is still
   `LEGACY_IN_MEMORY` until Phase 24 wires it. Plan 20-25 must not accept that status.
2. The deploy bootstrap must call `FileGateStateStore.initialize(...)` once before the first start;
   otherwise the first start is blocked as "loss" (by design). The state file path is a composition
   decision (the CLI takes it as `--path`).
3. The `REST_GATE_RECOVERY_REQUIRED` hook must be wired into the plan 20-13 alert sink.
4. `src/adapters/binance_userdata_supervisor._await_rest_allowed` sleeps `remaining_seconds()` for any
   reason other than `IP_BAN_418`, so while the gate is `GATE_NOT_RESTORED` / `GATE_STATE_UNKNOWN` it will
   re-check about once per second with a log line each time; `binance_probe` raises `ProbeBanned` with the
   reason. Supervisor and probe wiring is Phase 24.
5. The two operator commands above belong in the runbook; the operator id is audit only.
6. Under a1 a transient read error at start (not only a missing or corrupt file) also reads as unknown
   state and needs `clear`.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: operator file write | src/ops/rest_gate_cli.py | `clear --path` writes any path the operator names; mitigated only by host access control (ssh), as accepted for D-15. |

## Self-Check: PASSED

- Files present: src/ops/rest_gate_state.py, src/ops/rest_gate_cli.py, tests/test_gate_restart.py,
  tests/test_rest_gate_cli.py, src/adapters/binance_ratelimit_gate.py (modified),
  tests/test_binance_ratelimit_gate.py (modified).
- Commits present on p20-07: c35d5bee, 8ba988db, 97e310dd, 86c63052, 9f8a6ed4, 1ea80adf, d7ef3ccf.
- STATE.md, ROADMAP.md, config/binance/, pyproject.toml, uv.lock untouched.
