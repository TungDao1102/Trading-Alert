---
phase: "9"
slug: "live-execution-rollout"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-28"
audited: "2026-09-29"
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `09-RESEARCH.md` § Validation Architecture (verified: pyproject.toml
> `asyncio_mode = "auto"`, `testpaths = ["tests"]`, pytest ≥ 9 + pytest-asyncio,
> SDK 17.4.0 introspected this session).
>
> **Audited 2026-09-29** (`/gsd-validate-phase`, State A): all four plans executed,
> a full code-review cycle applied (21 findings fixed), one automatable coverage
> gap found and closed. `nyquist_compliant: false` because four behaviors are
> irreducibly manual (real-exchange round-trip, exchange-side account settings,
> real Telegram taps) — see Manual-Only. Those are what PARTIAL means here, not
> missing automation.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥ 9 + pytest-asyncio (auto mode) |
| **Config file** | pyproject.toml (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| **Quick run command** | `uv run --python 3.13 pytest tests/ -q -x` |
| **Full suite command** | `uv run --python 3.13 pytest tests/ -q` (+ `ruff check` + `mypy src` per AGENTS.md) |
| **Measured full-suite size** | 737 tests (732 passed, 5 skipped), ~152 s — verified 2026-09-29 |
| **Phase-9 execution surface** | 122 tests across 11 `tests/test_execution_*.py` suites |

---

## Sampling Rate

- **After every task commit:** Run `uv run --python 3.13 pytest tests/ -q -x`
- **After every plan wave:** Run full suite + `ruff check` + `mypy src`
- **Before `/gsd-verify-work`:** Full suite green + testnet placement rehearsal
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-T2 | 09-01 | 1 | EXEC-01 | — | LIMIT entry + CONDITIONAL SL leg with deterministic `x-`/`xa-` IDs; ambiguous responses probe by ID before any retry (no blind retry) | unit | `uv run --python 3.13 pytest tests/test_execution_manager.py -q` | ✅ 32 tests | ✅ green |
| 09-01-T3 | 09-01 | 1 | EXEC-01 | T-9-SC | Adapter placement surface matches installed SDK 17.4.0 signatures (contract test, no live call) | unit | `uv run --python 3.13 pytest tests/test_execution_adapter_contract.py -q` | ✅ 7 tests | ✅ green |
| 09-02-T2 | 09-02 | 2 | EXEC-01 | — | Mode-correct protective legs: one-way `closePosition`/`reduceOnly` vs hedge explicit `positionSide` | unit | `uv run --python 3.13 pytest tests/test_execution_modes.py -q` | ✅ 6 tests | ✅ green |
| 09-02-T3 | 09-02 | 2 | EXEC-01 | — | Protectives sized to actual filled qty (never planned qty); out-of-order and replayed fills fold idempotently | unit | `uv run --python 3.13 pytest tests/test_execution_partials.py -q` | ✅ 9 tests | ✅ green |
| 09-03-T2 | 09-03 | 2 | EXEC-01 | T-9-16 | Placement-time constraint revalidation, 200-algo headroom reject, `STALE_CONSTRAINTS` fail-closed past TTL | unit | `uv run --python 3.13 pytest tests/test_execution_gates.py -q` | ✅ 8 tests | ✅ green |
| 09-03-T2b | 09-03 | 2 | EXEC-01 | — | DAILY_STOP and portfolio caps evaluated on live reconciled state, first-failing-gate reason code | unit | `uv run --python 3.13 pytest tests/test_execution_gates.py -q` | ✅ (same suite) | ✅ green |
| 09-03-T3 | 09-03 | 2 | OPS-02 | — | `LIVE_ORDERS_DISABLED` default blocks; explicit operator enable journaled; emergency + SAFE_MODE block new entries | unit | `uv run --python 3.13 pytest tests/test_execution_enablement.py -q` | ✅ 6 tests | ✅ green |
| 09-04-T1 | 09-04 | 3 | OPS-02 | T-9-15 | Ten canonical health probes, one `HEALTH_CHECK` journal event each, RED/partial/incomplete verdict blocks enablement | unit | `uv run --python 3.13 pytest tests/test_execution_health.py -q` | ✅ 16 tests | ✅ green |
| 09-04-T2 | 09-04 | 3 | EXEC-01 | T-9-14 | Entry fill → SL+TP1+TP2 attach sized to folded filled qty with per-leg confirmation; unconfirmed leg holds `ENTRY_WITHOUT_PROTECTIVE` + SAFE_MODE with zero rescue placement; non-live-5 symbol rejected before any adapter call | unit | `uv run --python 3.13 pytest tests/test_execution_attach.py -q` | ✅ 20 tests | ✅ green |
| 09-04-T2b | 09-04 | 3 | EXEC-01 | T-9-16 | Pending-entry expiry cancels by deterministic `x-` ID, untriggered protectives cancel per-leg in isolation, emergency close blocks first then runs every step | unit | `uv run --python 3.13 pytest tests/test_execution_emergency.py -q` | ✅ 6 tests | ✅ green |
| WR-01 | review-fix | 3 | EXEC-01 | — | Limit and trigger prices snapped onto the tick grid before placement | unit | `uv run --python 3.13 pytest tests/test_execution_price_ticks.py -q` | ✅ 8 tests | ✅ green |
| AUDIT-09-01 | validate-phase | audit | OPS-02 | T-9-15 | No credential-shaped literal in exchange-facing modules; no log site emits a credential field or whole SDK response; SDK client constructed with no project-held key material; no target module reads credentials from the environment | unit (source purity) | `uv run --python 3.13 pytest tests/test_execution_secret_posture.py -q` | ✅ 4 tests (added by this audit) | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Threat refs cite only IDs verified in `09-04-PLAN.md`'s threat register (T-9-13…T-9-16, T-9-SC). Earlier plans' registers were not re-read during this audit; `—` means "not cross-referenced", not "no threat".*

---

## Wave 0 Requirements

- [x] `tests/fixtures/phase9/` — placement sequences, partial-fill sizing, mode branches, retry/headroom/DAILY_STOP rejects (byte-exact golden files). Verified present: `placement_sequences/`, `mode_branches/{one_way,hedge}/`, `partial_fills/`, `gates/{headroom_reject,daily_stop_block,stale_constraints}/`, `enablement/{disabled,enabled,emergency}/`, `attach/`
- [x] `tests/test_execution_*.py` — manager, modes, partials, gates, enablement suites, plus health, attach, emergency, adapter-contract, price-ticks, and secret-posture (11 files, 122 tests)
- [ ] Testnet rehearsal task — real LIMIT + CONDITIONAL round-trip on smallest qty before live enablement — **OPEN** (09-04 task 3, blocking-human)
- [ ] 08-02 LIVE-TAP GATE clearance (Telegram token + chat) — **OPEN** (09-04 task 3, blocking-human)

`wave_0_complete: false` reflects only the two operator-gated items above; all test
infrastructure is in place and green.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions | State |
|----------|-------------|------------|-------------------|-------|
| Testnet LIMIT + all three CONDITIONAL legs round-trip on smallest qty | EXEC-01 | Real exchange round-trip cannot exist in a unit sandbox | 09-04 task 3 (`gate="blocking-human"`): operator runs the rehearsal on testnet and records entry + SL/TP1/TP2 order IDs with UTC timestamps in `09-04-SUMMARY.md` | 🔒 **OPEN** |
| RESEARCH A1 — TP1-partial then TP2 close-all closes exactly the remainder (no dust) | EXEC-01 | Exchange-side semantics; fixtures currently *pin the assumption*, they do not prove it | 09-04 task 3: operator confirms or records corrected semantics as a follow-up. Main-suite fixtures hold the pre-rehearsal assumption until then | 🔒 **OPEN** |
| RESEARCH A4 — `ALGO_UPDATE.o.rm` rejection payload shape | EXEC-01 | Live user-data stream payload; reuses the paper WS supervision shape on assumption | 09-04 task 3: operator confirms; any payload-shape delta is recorded as a follow-up, never patched silently | 🔒 **OPEN** |
| Live credential posture: no-withdrawal keys, IP allowlisting, off-source encrypted storage, paper/live separation | OPS-02 | Exchange-side account settings and operator secret storage — code can assert its own posture but cannot prove exchange configuration | 09-04 task 3: operator attests each item by name. Code-side half is now automated by `tests/test_execution_secret_posture.py` | 🔒 **OPEN** (code half ✅) |
| 08-02 LIVE-TAP GATE: real APPROVE tap, SKIP tap, unknown-chat rejection | OPS-02 | Real Telegram taps from an authorized chat cannot be fabricated | 09-04 task 3: operator records tap evidence lines | 🔒 **OPEN** |
| Health-green attestation across all ten probes | OPS-02 | Probe *logic* is automated; a green *live environment* is an operator fact | 09-04 task 3: operator attests health-green against the live stack | 🔒 **OPEN** (logic ✅) |
| ACK-ONE-WAY — live-order permanence acknowledgement | EXEC-01 | `checkpoint:decision` in 09-01 | Recorded in `09-01-SUMMARY.md` as `operator=auto-executor` (auto-selected in auto-mode, **not** human-typed). If a human acknowledgement is required before live enablement, re-confirm at the 09-04 gate | ⚠️ auto-recorded |

---

## Validation Audit 2026-09-29

| Metric | Count |
|--------|-------|
| Gaps found | 1 |
| Resolved | 1 |
| Escalated | 0 |
| Manual-only (unchanged, irreducible) | 6 |

**Gap closed:** OPS-02 had no source-level guard over the exchange-facing modules.
The pre-existing scan (`test_secret_free_log_scan_across_enablement_and_health_events`)
checks *emitted* enablement/health log records only; nothing covered
`src/adapters/binance_usdm.py` — where the SDK client is built and every payload is
marshalled — against 09-04's prohibition on logging keys, signatures, tokens, or whole
SDK responses. Closed by `tests/test_execution_secret_posture.py` (4 AST-based tests over
9 target modules), mirroring the existing precedent at `tests/test_backup.py:611` and
following the WR-12 convention that a purity test fails — never skips — on a missing target.
It carries an anti-vacuity guard that fails if the log-site scan finds zero sites.

**Observations recorded, not enforced:**
- `src/adapters/binance_usdm.py` embeds `{sym.filters!r}` / `{sym!r}` in two `ValueError`
  messages (~lines 699, 718). These are public exchangeInfo records, not credentials, so
  they do not violate the 09-04 prohibition — but they are whole-SDK-object reprs flowing
  into exception text. Extending the prohibition to exception messages is a judgment call
  left open.
- Secret-posture coverage is static by construction; it cannot catch a credential injected
  at runtime into a dynamically built log field. The runtime scan in
  `test_execution_enablement.py` is its complement — the two together cover both sides.
- 24 `ruff` findings and 5 `mypy` errors exist repo-wide, all pre-existing and outside this
  phase's files (`src/ops/drills.py`, `src/risk/*`, `src/approval/replay.py`,
  `src/adapters/telegram_callbacks.py`, `src/paper/supervisor.py`, and several older test
  files). Confirmed pre-existing by stash-and-recheck. `src/ops/drills.py` is already logged
  in `deferred-items.md`.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — the two exceptions are
      the 09-01 `checkpoint:decision` and the 09-04 `gate="blocking-human"` task, both
      inherently non-automatable
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test infrastructure complete; two operator
      items remain open by design)
- [x] No watch-mode flags
- [x] Feedback latency < 300s (full suite ~152 s measured)
- [ ] `nyquist_compliant: true` — **withheld**: 6 manual-only behaviors remain, 5 of them
      gated behind the still-open 09-04 task 3 operator attestation

**Approval:** validated (PARTIAL) — automated coverage complete for every automatable
behavior; live-readiness blocked on the 09-04 operator gate.
