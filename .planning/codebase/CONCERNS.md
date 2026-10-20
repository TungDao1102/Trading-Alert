---
last_mapped_commit: 4e37e15d10c652818053e9e5d36895f64ed2c561
last_mapped_at: 2026-10-19
---
# Codebase Concerns

**Analysis Date:** 2026-10-19

Scope: the whole repository at branch `phase-19` (HEAD `4e37e15`). Every finding below was
verified against the live tree, not copied from a planning note. Where a recorded concern is
named by the project (`.planning/WINDOWS.md`, `docs/DECISIONS.md`, `.planning/STATE.md`), the
current state is stated explicitly, including where the record is now stale.

---

## Tech Debt

**`src/risk/portfolio.py` — F841 dead assignments hide a latent daily-loss gating gap (D-18)**
- Issue: `warning_threshold_quote` and `stop_threshold_quote` are assigned at `src/risk/portfolio.py:302-303` and never read. The thresholds are actually consumed earlier by `_derive_daily_state` (`src/risk/portfolio.py:243-247`), so the DAILY_STOP gate works today — but only because of that call site.
- Files: `src/risk/portfolio.py:302-303`, `pyproject.toml:81-85`
- Impact: a future refactor that removes or reorders the `_derive_daily_state` call silently disables the DAILY_STOP gate with no lint signal. This is the money-safety path.
- Fix approach: delete the two dead assignments and drop the per-file ignore. `pyproject.toml:84` already states the intent ("remove this ignore when the risk code is next touched"). Per D031, treat that edit as a deliberate, tested risk change — do not fold it into an unrelated plan.

**`tests/test_domain_no_float.py` — the Decimal-only guard does not cover the whole risk/domain/core path**
- Issue: `SCANNED_GLOBS` (`tests/test_domain_no_float.py:130`) globs only `src/backtest/*.py`, `src/paper/*.py`, `src/research/*.py`. `src/risk`, `src/domain`, `src/core`, `src/approval` and `src/db` rely on a hand-maintained explicit list, so a **new** module in those packages is silently not scanned (a removed one fails via the `is_file()` assertion at line 152 — the trap only runs one way).
- Currently unscanned modules: `src/risk/cost_guards.py`, `src/risk/cost_rates.py`, `src/risk/live_commission.py`, `src/domain/algo_status.py`, `src/domain/exchange_errors.py`, `src/domain/lot_filters.py`, `src/domain/stream_records.py`, `src/domain/transitions.py`, `src/core/_decimal.py`, and every file in `src/approval/`.
- Impact: D-12 ("Decimal-only on the domain/registry/risk path") is enforced on the modules listed, but a new cost-rate or transition module can introduce `float(...)` without turning CI red.
- Fix approach: extend `SCANNED_GLOBS` to `src/risk/*.py`, `src/domain/*.py`, `src/core/*.py`, `src/approval/*.py` and add the same drift assertion that `test_every_paper_and_research_module_is_scanned_by_the_float_guard` (line 155) provides.

**No import-purity or wall-clock guard for `src/core`, `src/risk`, `src/domain`, `src/approval`**
- Issue: `AGENTS.md` lists "**`src/core` stays pure** — no Polars/pandas/NumPy/Pydantic/SDK/network imports" and "**No wall clock in pure modules.**" as machine-enforced invariants. The machinery exists and works — `tests/test_analytics_purity.py::find_violations` and `tests/support/ast_guards.py::wall_clock_calls` — but only `src/analytics` and `src/backtest` are guarded (`tests/test_backtest_purity.py:17-21` reuses the analytics walker). `src/approval` purity is checked for **one** file only: `src/approval/mapping.py` (`tests/test_approval_message.py:462-477`).
- Files: `tests/test_analytics_purity.py`, `tests/test_backtest_purity.py`, `tests/support/ast_guards.py:19-30`
- Impact: the invariant is a convention, not a gate. A `import polars` inside `src/core/features.py` or a `datetime.now()` inside `src/risk/portfolio.py` would pass the whole suite.
- Fix approach: add `tests/test_core_purity.py` and `tests/test_risk_purity.py` mirroring `tests/test_backtest_purity.py` verbatim (same walker, same forbidden sets, glob discovery). This is the cheapest high-value gate in the repository.

**`pyproject.toml:80` — the E501 ignore covers a whole 1539-line file, not the docstring table**
- Issue: `"src/adapters/binance_usdm.py" = ["E501"]` is a per-file ignore. The comment says the ignore exists because the "SDK signature table in docstring is inherently long" — but that table already carries per-line `# noqa: E501` on `src/adapters/binance_usdm.py:56-62`. The per-file ignore is therefore redundant *and* suppresses real over-long code lines across the entire adapter.
- Impact: the largest Binance-touching module has no line-length signal at all.
- Fix approach: delete the per-file ignore entry; the inline `# noqa: E501` markers already carry the exception. Verify with `uv run ruff check`.

**Oversized modules — the D055 probe logic lives in the least-reviewed code**
- Issue: `scripts/demo_probe.py` (3283 lines), `scripts/demo_rehearsal.py` (2316), `scripts/user_data_smoke.py` (2199), `scripts/paper_ws_smoke.py` (1525), `scripts/export_soak_evidence.py` (~1100). On the `src/` side: `src/adapters/binance_usdm.py` (1539), `src/execution/manager.py` (1504), `src/paper/exit_criteria.py` (1489), `src/paper/runtime.py` (1489), `src/paper/shadow_confirm.py` (1433).
- Impact: `scripts/demo_probe.py` carries the entire D055 probe matrix (the 11 cases listed in `.planning/phases/19-execution-plan-binding-price-check/19-NOTES.md`) in one 3283-line file. A 3283-line file is un-reviewable in a diff and un-testable in isolation; only 5 test files reference it.
- Fix approach: move the probe matrix into a declarative data file (one row per case: id, preconditions, actions, expected states) and keep the runner generic. Same for `scripts/user_data_smoke.py`.

**Untracked working-tree artifacts — the current evidence set is not committed**
- Issue: `git status` on `phase-19` shows `docs/research/experiments/research-run-1-v2-3-0/` (50 files) untracked, plus `package.json`, `package-lock.json`, `.gsd/` and `.planning/milestone.lock`.
- Files: `docs/research/experiments/research-run-1-v2-3-0/*.json`, `package.json` (contents `{}`), `package-lock.json` (`"packages": {}`)
- Impact: D075/D076 name `research-run-1-v2-3-0/` as the current regenerated evidence set; a fresh clone has none of it. `package.json`/`package-lock.json` are accidental npm artifacts with empty contents — they are not project files and should be deleted, not committed.
- Fix approach: commit the 50 records with the plan that produced them; delete `package.json` and `package-lock.json` (or add them to `.gitignore` if a tool keeps recreating them).

**`src/paper/shadow.py` is excluded from the float guard with a permanent exemption**
- Issue: `FLOAT_SCAN_EXCLUDED` (`tests/test_domain_no_float.py:139-144`) excludes `src/paper/shadow.py` wholesale because of one tenacity wait expression (`src/paper/shadow.py:730`).
- Impact: the whole 1047-line module is un-scanned, so a `float(...)` in a price or quantity expression there would pass CI. The stated reason ("no price, quantity or risk value is computed with it") is true of the tenacity call but not of the rest of the file.
- Fix approach: narrow the exemption to a line-level `# noqa` or move the retry-wait arithmetic into a tiny helper module that *is* scanned.

---

## Known Bugs

**The live execution model always ends `ENTRY_WITHOUT_PROTECTIVE` + SAFE_MODE (D055, OPEN)**
- Symptoms: `src/execution/manager.py:851-875` places the LIMIT entry and then immediately places the "pre-fill safety net" — a `close_position=True` `STOP_MARKET` — while the entry is typically still unfilled. Binance rejects that with `-4509` ("TIF GTE can only be used with open positions"). The 2026-10-05 Demo rehearsal observed exactly this.
- Files: `src/execution/manager.py:851-875` (placement), `src/execution/manager.py:888-907` (SAFE_MODE + entry cancel), `src/execution/manager.py:1214-1240` (`_sl_only_then_hold`), `src/adapters/binance_usdm.py:1276-1350` (`place_algo_protective`)
- Trigger: any live entry, every time. The flow can never reach a protected live position.
- Status: **D055 is OPEN in `docs/DECISIONS.md`.** The owner's adopted direction (model (a): protection *after* the first fill) exists only in `.planning/phases/19-execution-plan-binding-price-check/19-NOTES.md` and `19-DEC-D055-DRAFT.md` — neither is a DECISIONS row. `docs/DECISIONS.md` D055 explicitly says "the execution model is NOT chosen now".
- Workaround: none. LIVE is blocked by D040 (SHADOW → DEMO → CANARY → LIVE, no stage skipped). The failure is fail-closed by design: SAFE_MODE blocks entries while monitoring and reconciliation continue.

**`src/paper/shadow.py` renders a non-positive TP2 without a guard (D075 KNOWN LIMITATION)**
- Symptoms: `src/paper/shadow.py:354-356` reads `tp1`/`tp2` out of `plan.take_profit_json` and checks only finiteness (`_json_decimal`, `src/paper/shadow.py:330-335`). There is no `> 0` check.
- Files: `src/paper/shadow.py:354-356`, `src/core/planner.py:389` (the D075 planner guard that now prevents such a plan from being created)
- Trigger: a plan produced by a build that predates the D075 guard. The soak image of plan 16-62 (`IMAGE_COMMIT efae1f3`) predates it, and D075 explicitly excludes "hardening of `src/paper/shadow.py`" from the amendment. D075 also records R7 (rebuild the soak image) as an **open owner decision**.
- Impact: a negative TP leg can appear in a SHADOW alert. No orders are possible in SHADOW (D040), so the blast radius is the alert text, not money.
- Workaround: rebuild the soak image (owner decision R7, still open).

**`config/execution/execution-limits-v1.toml` — the four safety numbers are `NOT_CONFIGURED`, so Phase 19's pre-placement checks are inert**
- Symptoms: `protection.max_unprotected_ms`, `protection.entry_terminal_timeout_ms`, `pre_placement.min_remaining_validity_seconds` and `pre_placement.max_mark_price_age_ms` are all the literal string `NOT_CONFIGURED`.
- Files: `config/execution/execution-limits-v1.toml:15-24`, `src/execution/execution_limits.py`, `src/execution/pre_placement.py`
- Trigger: any live placement attempt — the live path refuses while the keys are unset (the intended fail-closed behavior, per the file header).
- Impact: the D055 deadlines and the Phase 19 live-price check cannot run until the owner fills the values after the Demo probes. This is correct fail-closed behavior, but it means Phase 19's pre-placement criteria are not yet *proven*.
- Workaround: none — the values are user-owned (OWNER-OPEN O-04) and need a DECISIONS row when set.

**`src/execution/manager.py` — `ExecutionAdapter` has no close/MARKET method, so D034's emergency close cannot be automated**
- Symptoms: the Protocol at `src/execution/manager.py:91-111` declares only `place_entry`, `place_algo_protective`, `query_order_by_client`, `query_algo_order_by_client`, `cancel_normal_order` and `cancel_algo_order`. The underlying adapter *does* have `place_market_close` (`src/adapters/binance_usdm.py:1190`, plan 19-08 D-15) and the v2 fake exchange implements it — but the Protocol the manager consumes does not expose it.
- Files: `src/execution/manager.py:91-111` (Protocol), `src/execution/manager.py:1572-1612` (`emergency_manual_close` docstring: "Closing the strategy-generated POSITION itself … is an operator-directed exchange action outside this function's adapter surface"), `src/execution/manager.py:1687`
- Trigger: the D055 "close the position by MARKET" branch, or any automatic reduce-only emergency close.
- Impact: `emergency_manual_close` cancels the pending entry and the untriggered protectives and then leaves the position open for a human to close in the exchange UI. That is safe, but it means the `CLOSE_REQUIRED` states in `19-NOTES.md` have no automatic implementation.
- Workaround: the operator closes manually (the documented, intended V1 posture).
- Related: `src/execution/lot_split.py` holds the pure MARKET_LOT_SIZE splitting arithmetic, but `src/execution/tp_sizing.py:35` is its only production importer — the emergency-close splitting path is not wired into an order flow.

**`attach_protectives_to_fill` has no in-`src/` caller — no fill detection drives protection**
- Symptoms: `attach_protectives_to_fill` (`src/execution/manager.py:1146`) is called only from `scripts/demo_rehearsal.py:127` and `scripts/demo_rehearsal.py:2120`. Nothing in `src/` observes a fill and then attaches protection.
- Files: `src/execution/manager.py:1146`, `src/execution/manager.py:1214-1240`
- Impact: the D055 adopted direction ("stop placed after the first fill") has no production implementation. The "no rescue placement is ever issued (D-02)" statement in that path also conflicts with D034, which supersedes D-02 — `19-NOTES.md` calls this out explicitly.
- Trigger: the D055 model (a) implementation.
- Workaround: none — this is planned work for Phase 19/20, not a regression.

---

## Security Considerations

**Verified-good posture (no action needed, but do not regress):**
- Secrets live only in `.env` (mode 0600) and `secrets.env` — **both files exist in the working tree; contents were not read.** `.gitignore` excludes `.env`, `.env.*` (except `.env.example`), `secrets*.env`, `*.pem`, `id_ed25519*`.
- `src/ops/redaction.py` masks on three layers: value-based (env var names containing `PASSWORD`/`SECRET`/`TOKEN`/`API_KEY`/`ACCESS_KEY`/`CRYPT`/`PRIVATE`, `src/ops/redaction.py:54-62`), shape-based (PEM blocks, URL userinfo passwords, Telegram bot tokens, `signature=<64 hex>`, `X-MBX-APIKEY`, AWS key ids, `listenKey=` in query and JSON form — `src/ops/redaction.py:89-117`), and key-name-based (`src/ops/redaction.py:65-76`). `register_runtime_secret` (`src/ops/redaction.py:206-219`) additionally covers API keys read from a file and Binance listenKeys.
- `src/paper/runtime_config.py:112-118` — `refuse_trade_capable_env` refuses **any** `BINANCE_`-prefixed variable in the paper runtime; presence alone refuses, an empty value included.
- `docker-compose.yml:51` publishes PostgreSQL on `127.0.0.1` only. Data lives only in named volumes (`docker-compose.yml:219-223`). No `container_name` anywhere (`docker-compose.yml:12`). `init: true` gives PID 1 a real SIGTERM handler (`docker-compose.yml:22-23`).
- `deploy/bootstrap.sh:338-353` — `sudo_lockout_guard` refuses to write the SSH drop-in (disabling root login) unless the trading user is in the sudo group **and** `passwd -S` reports status `P`. Sudo is password-protected; no NOPASSWD rule is written (`deploy/bootstrap.sh:247-251`).
- `deploy/bootstrap.sh:531-537` enforces a URL-safe `POSTGRES_PASSWORD` of at least 16 characters.
- Demo and live credential names are disjoint and ratified: `BINANCE_DEMO_API_KEY`/`BINANCE_DEMO_API_SECRET` vs `BINANCE_LIVE_API_KEY`/`BINANCE_LIVE_API_SECRET` (`docs/DECISIONS.md` D072, `src/adapters/binance_client.py` `CREDENTIAL_SPECS`).

**Risk — the paper runtime shares one `env_file` with every other service (WR-06, still open)**
- Risk: `docker-compose.yml:18` gives every `x-app` service `env_file: ${TRADING_ENV_FILE:-.env}`. The paper container therefore sees every `BACKUP_*` credential that is present. The mitigation today is only the `BINANCE_` refusal in the paper runtime — a second barrier, not isolation.
- Files: `docker-compose.yml:16-28` (the `x-app` anchor), `docker-compose.yml:119-122` (the WR-06 note), `src/paper/runtime_config.py:112-118`
- Current mitigation: the `BINANCE_` name refusal at paper start.
- Recommendation: land the WR-06 per-service `env_file` split **before** any live key enters `.env` — `docs/DECISIONS.md` D062 states this explicitly ("must precede any live key in .env (Phase 24)").

**Risk — `src/ops/redaction.py` never masks a secret shorter than 8 characters**
- Risk: `MIN_SECRET_LENGTH = 8` (`src/ops/redaction.py:80`) and `_variants` (`src/ops/redaction.py:130-133`) drop anything shorter. A short `POSTGRES_PASSWORD` or a short API key would print in a log line unredacted.
- Files: `src/ops/redaction.py:80`, `src/ops/redaction.py:130-133`
- Current mitigation: `deploy/bootstrap.sh:531-537` rejects a `POSTGRES_PASSWORD` under 16 characters; `src/adapters/binance_client.py` reads credentials only from the variable or `<NAME>_FILE`.
- Recommendation: raise the floor for `*_PASSWORD`-shaped names specifically, or fail closed at startup when a `*_PASSWORD` value is shorter than the minimum.

**Risk — D058 (live mark-price must fail closed) is a decision, not yet an implemented gate**
- Risk: `docs/DECISIONS.md` D058 requires the live path to fail closed when the mark-price data needed for risk or protection is missing or stale, and states that "degraded or stale mark price while LIVE is enabled" is an invalid state. The owner of that gate is still to be registered: stale-feed handling in Phase 20, enablement in Phase 24. OQ-1 (how a backtest trade held through a mark-price hole is treated) stays an open user decision.
- Files: `docs/DECISIONS.md` (D058), `src/ops/health.py` (the probes), `src/execution/gates.py`
- Current mitigation: `src/ops/health.py:508` fails closed on probe exceptions.
- Recommendation: treat "D058 implemented" as a Phase 20/24 gate item in the roadmap, not as done.

**Risk — the research-gate identity and registry-tripwire checks pass vacuously on an empty repo**
- Risk: `.github/workflows/research-gate.yml:94-98` exits 0 with a warning when no `experiment*.json`/`backtest*.json` file exists, and `.github/workflows/registry-gate.yml` exits 0 when no `params/*.toml` exists. Today neither is empty (73 pinned `params/**` files; 240 + 50 experiment records), so the gates are real.
- Files: `.github/workflows/research-gate.yml:94-98`, `.github/workflows/registry-gate.yml` (rehash step)
- Recommendation: none needed now; keep the warning visible in CI output so a future mass-deletion is noticed.

---

## Performance Bottlenecks

**`src/ops/backup_remote.py` — the pre-push whole-tree check grows linearly with the Parquet store**
- Problem: per D066, a snapshot is complete only when `manifest.json` is on the remote, and `push_snapshot` publishes it only after the whole Parquet tree **and** `pg.dump` have passed `rclone cryptcheck`. The tree check runs before every push.
- Files: `src/ops/backup_remote.py` (`push_snapshot`), `docs/DECISIONS.md` (D066)
- Cause: the completeness rule is defined per-tree, not per-snapshot, so the check cost is proportional to the whole append-only dataset rather than to the delta.
- Improvement path: `docs/DECISIONS.md` D066 already records the open item — "the 2 hour unit timeout against the 6 hour per-call rclone timeout". A manifest-of-manifests (per-directory digests) would make the check proportional to the delta. Do not change the coupling without a new DECISIONS row: D066 explicitly says the strict coupling stays and "Separating the PostgreSQL dump from Parquet integrity is considered only after operational evidence shows that the coupling causes real harm".

**`src/data/collector.py` — the OI/funding poll is the irreplaceable data path and runs on a fixed cadence**
- Problem: the collector polls on a fixed 5-minute cadence (`docker-compose.yml:82-96`, healthcheck every 60 s, `start_period: 6m`). A missed tick is a **permanent** coverage gap: `openInterestHist` serves only the latest 1 month (`docs/SOURCES.md`), and `docs/DECISIONS.md` D059(4) commits that the collector must be writing OI no later than 2026-10-08 and that "every OI gap after that date is recorded as a coverage gap and the dataset is never called full history while a known gap exists".
- Files: `src/data/collector.py`, `docker-compose.yml:82-96`, `docs/DECISIONS.md` (D059)
- Cause: a single-process loop with no off-host redundancy.
- Improvement path: the collector's own `--healthcheck` is the only signal today. Run it on the soak host and add an external heartbeat (the same mechanism as `deploy/heartbeat.sh`) so a missed tick is detected within minutes rather than at the next coverage report.

**`src/research/multiplicity.py` — the G3 p-value producer does not exist, so acceptance is not computable end to end**
- Problem: D069 records that only the Holm-Bonferroni correction step is implemented and tested on supplied p-values; "the seeded one-sided stationary block-bootstrap p-value producer on pooled Validation trades (it does not exist in src)", and the G-cells in `src/analytics/gates.py` are "still pending by its own docstring". D069 states plainly: "multiplicity is therefore not complete end to end".
- Files: `src/research/multiplicity.py`, `src/analytics/gates.py`, `src/analytics/killgate.py`
- Cause: the correction rule was adopted before the estimator it corrects.
- Impact: no candidate can pass G3, therefore no family can hold a recorded passing decision, therefore the kill gate can never reach `PASSING_CANDIDATE`. This is the critical path to the D013 clock.

**`src/execution/manager.py` — the intent store is synchronous on the event loop**
- Problem: the manager's own docstring states it — "The store is synchronous and is called directly on the event loop (short indexed queries; the engine bounds connect, lock wait, statement, pool checkout and a half-open socket with `connect_timeout`, `lock_timeout`, `statement_timeout`, `pool_timeout` and TCP keepalives, see `src.persistence.engine`; a call can still block the loop for up to the longest of those bounds, and Phase 24 may wrap it in `asyncio.to_thread`)" (`src/execution/manager.py:425-435`). `src/paper/runtime_state.py:342-344` repeats the same note for the runtime state port.
- Files: `src/execution/manager.py:425-435`, `src/paper/runtime_state.py:342-344`, `src/persistence/engine.py`
- Impact: a slow database can stall the WebSocket event loop; the silence watchdog (`feed_silence_timeout_seconds`) then trips on a *healthy* feed and reports a false divergence.
- Improvement path: Phase 24's `asyncio.to_thread` wrap, or a bounded statement timeout below the watchdog bound.

---

## Fragile Areas

**The paper runtime's start gate is a nine-way refusal ladder — a single point of operational failure**
- Why fragile: `src/paper/runtime.py:1427-1664` `main` walks usage (2) → trade-capable env (3) → config not ratified (4) → admission/epoch mismatch (6) → instance lease held (8) → no pinned epoch (5). `src/paper/runtime_config.py:101-109` holds the `REFUSAL_CODES` frozenset. `docker-compose.yml:109-117` documents the exact set the compose restart policy depends on ("The refusal codes are 3, 4, 5, 6 and 8").
- Files: `src/paper/runtime.py:1427-1664`, `src/paper/runtime_config.py:88-109`, `docker-compose.yml:109-117`
- Safe modification: change one `ExitCode` at a time and update `REFUSAL_CODES`, the `docker-compose.yml` comment and `tests/test_paper_runtime_admission.py` in the same change. The compose comment is a load-bearing contract, not documentation.
- Test coverage: `tests/test_paper_runtime_admission.py`, `tests/test_paper_runtime_compose.py` — both run against the in-memory port only; the PostgreSQL lease path is the WINDOWS entry 1 gap.

**The instance lease is a never-wait lock, and `unless-stopped` fights it**
- Why fragile: `acquire_instance_lease` never waits — a held lease is a refusal of the start (`src/paper/runtime_state.py:376-382`, `:452-457`). The PostgreSQL implementation treats an *unverifiable* lease as a **lost** lease (`src/persistence/paper_runtime_state.py:136-152`), so a database hiccup refuses the start. With `restart: unless-stopped` (`docker-compose.yml:126`), a container that has not fully released its PostgreSQL session lease can be restarted straight into exit 8, which then holds forever.
- Files: `src/paper/runtime_state.py:376-382,452-457`, `src/persistence/paper_runtime_state.py:136-152`, `docker-compose.yml:126`
- Safe modification: keep the lease's lifetime bound to the holding session (`src/paper/runtime_state.py:379-381`) and verify `src/persistence/paper_runtime_state.py` closes the session on every exit path, including the `_hold` path (`src/paper/runtime.py:278-295`).
- Test coverage: `tests/test_paper_runtime_state_pg.py` is **skipped without `TEST_DATABASE_URL`** (WINDOWS entry 1). The in-memory behaviour is proven; the PostgreSQL behaviour is not.

**The pinned epoch is a single file that the runtime and the freeze workflow read independently**
- Why fragile: `logs/paper/pinned_epoch.json` is gitignored (`.gitignore`, "Paper soak runtime state"), but `.github/workflows/paper_freeze_check.yml:36-43` reads a **committed** copy at `evidence/paper/pinned_epoch.json` and copies it into `logs/paper` before each hourly tick. The runtime reads its own default (`src/paper/runtime.py:255-257`). If the committed pin and the runtime pin diverge, the freeze check and the running runtime disagree with no error; `src/paper/restart.py:371` `EpochMismatch` only fires when the two *stored* records disagree.
- Files: `src/paper/runtime.py:255-257`, `src/paper/freeze.py` (`load_pinned_state`, `write_pinned_state`), `.github/workflows/paper_freeze_check.yml:36-43`, `.gitignore`
- Safe modification: treat the committed pin as the single source of truth and always re-copy it before the runtime starts, exactly as the workflow does.
- Test coverage: `tests/test_paper_runtime_config_pin.py`, `tests/test_paper_freeze.py`; the restart path is the WINDOWS entry 9 gap.

**The conditional-order rejection path depends on `ALGO_UPDATE.o.rm` after the Dec 2025 Binance Algo migration**
- Why fragile: `CONDITIONAL_ORDER_TRIGGER_REJECT` — the event Binance removed — is classified as a `DEPRECATED_EVENT` anomaly (`src/adapters/binance_userdata_events.py:31`, `:1334`), and the live rejection reason now arrives inside `ALGO_UPDATE.o.rm`, parsed as `reject_reason` (`src/adapters/binance_userdata_events.py:518`). `src/domain/algo_status.py:85-143` classifies `TRIGGERING`, `TRIGGERED`, `FINISHED` and `CANCELED` as **`UNKNOWN`** (the owner's recorded decision, D072), and only `NEW` is `ACTIVE`. `is_protection_confirmed` (`src/domain/algo_status.py:170-172`) therefore returns True for `NEW` only.
- Files: `src/adapters/binance_userdata_events.py:173-176,518,551-552,1328-1336`, `src/domain/algo_status.py:85-172`
- Why it matters: a stop that has triggered but not filled is `UNKNOWN` by policy, so it does **not** count as confirmed protection. That is the intended fail-closed posture, but it means a resting stop whose status flips to `TRIGGERING` will read as "not protected" to any consumer of `is_protection_confirmed`.
- Safe modification: never widen the `ACTIVE` set without a new DECISIONS row and a Binance docs citation (`docs/SOURCES.md`, "Facts read for Phase 18" — a WebFetch summary, not verified live).
- Test coverage: `tests/test_algo_status.py`, `tests/test_userdata_parsers.py`.

**The kill-gate code carries five unresolved review items**
- Why fragile: `docs/research/kill_gate_review_registry.json` lists WR-01, WR-06, WR-10, WR-12 and WR-13, all with `"state": "UNRESOLVED"` and `"fix_commit": null`. WR-01/06/12/13 are `blocks_report: true`; WR-10 is `blocks_live_enable: true`. The specifics: the family-independence check is partly vacuous (WR-01); the BACKTEST block pools every experiment's trades (WR-06); `--record` accepts an arbitrary decisions file and file-only resets bypass the journal (WR-12); gate cells G07/G08/G10 turn MET from self-reported booleans (WR-13); `LiveEnablementController.enable` trusts a caller-supplied kill-gate state (WR-10).
- Files: `src/analytics/killgate.py`, `src/analytics/killgate_guard.py`, `src/analytics/gates.py`, `docs/research/kill_gate_review_registry.json`
- Safe modification: `src/analytics/killgate_guard.py` is the only thing keeping a report from concluding on real evidence while those items are open — do not weaken it. Phase 26 owns the fixes.
- Test coverage: `tests/test_killgate_guard.py`, `tests/test_kill_gate_docs.py`, `tests/test_kill_gate_clock.py` — the guard is well tested; the underlying defects are not fixed.

**`src/ops/redaction.py` — the process-wide redactor is module-level mutable state**
- Why fragile: `_active`, `_runtime_values` and `_merged_cache` (`src/ops/redaction.py:196-203`) are module globals mutated under a lock. `install_global_hooks` swaps `sys.excepthook` and `threading.excepthook` process-wide (`src/ops/redaction.py:397-412`). In a test process that also runs a real runtime, the hooks are global and the redactor is shared.
- Files: `src/ops/redaction.py:196-245,397-434`
- Safe modification: call `configure_logging()` first in every `main()` that has secrets in its environment (the module docstring says so at line 444) and use `uninstall_global_hooks()` / `clear_runtime_secrets()` in tests.
- Test coverage: `tests/test_redaction.py` (and the deployment secret-posture suite `tests/test_execution_secret_posture.py`).

---

## Scaling Limits

**Single host, single process, single database**
- Current capacity: one asyncio process, one PostgreSQL 17 instance, one Parquet store, one compose project (`name: trading`, `docker-compose.yml:14`). The soak runs as a *second* project (`trading-soak`, its own `pgdata` volume) — two stacks on one host, not one stack scaled.
- Limit: for 4H/1H swing trading on $500–1,000 capital there is orders of magnitude of compute headroom. The binding constraint is the OI data window, not CPU or connections.
- Scaling path: none needed for V1. If the soak and a live stack must share a host, use the second compose project as `deploy/compose-soak.sh` already does — never `docker compose down -v` on the soak project (`docs/DECISIONS.md` D061).

**The 200-conditional-order headroom is account-wide and never cached**
- Current capacity: Binance removed the `MAX_NUM_ALGO_ORDERS` exchangeInfo filter on 2025-12-29, so the open algo-order count must be read from the account at runtime (`docs/SOURCES.md`; `src/execution/gates.py` `HEADROOM_LIMIT`).
- Limit: with SL + TP1 + TP2 per position, the headroom binds at roughly 66 concurrent positions — far above V1 sizing, but the count is recomputed per placement and is never cached, so it is an extra signed REST read on the critical path.
- Scaling path: none needed. Never hard-code 200; re-verify against current docs before any use.

**The OI retention window is one month and a missed day is unrecoverable**
- Current capacity: `openInterestHist` serves only the latest 1 month (`docs/SOURCES.md`).
- Limit: a single missed collection day destroys that day's OI permanently. `docs/DECISIONS.md` D059(4) records the commitment deadline (2026-10-08) and the rule that "the dataset is never called full history while a known gap exists".
- Scaling path: none — the only mitigation is uptime and out-of-band detection of a missed tick.

---

## Dependencies at Risk

**`binance-sdk-derivatives-trading-usds-futures >=17.3,<18` (17.4.0 installed)**
- Risk: the SDK is auto-generated and its minor bumps track REST/WS changes. The `ALGO_UPDATE.o.rm` field semantics (Dec 2025 Algo migration) and the `algoOrder` endpoint family are documented in `src/adapters/binance_usdm.py:56-67` as WebFetch summaries, **not verified live**.
- Impact: an SDK signature change is contained by the adapter boundary, but `tests/test_binance_usdm_signed_calls.py` pins all eleven `recv_window` parameters and will fail loudly rather than silently — that is the intended tripwire.
- Migration plan: read the SDK CHANGELOG on every minor bump, especially the Trade and Algo sections. Do not upgrade inside a phase; a version bump changes every `clientOrderId`/`algoClientId` derivation input (`src/execution/order_ids.py`).

**`polars>=1.44,<2.0` (1.44.2) — deliberately pinned below 2.0**
- Risk: a Polars upgrade changes Parquet bytes, and `dataset_id` is a SHA-256 over the file bytes (`docs/data/DATA_MODEL.md` §2.13, D-18; `src/data/case_input.py`). Every experiment record, pin and digest derived from those bytes would move.
- Impact: high blast radius, and it is a *known* trap — `docs/TECHNOLOGY_STACK.md` says "Polars 2.0.0rc1 exists — do NOT take the RC".
- Migration plan: upgrade only in a dedicated phase with a full regeneration inventory in the style of D071/D074/D076. Never upgrade mid-phase.

**`python-telegram-bot>=22.8,<23` (22.8) — major pinned**
- Risk: v20→v22 had breaking changes; the approval callback loop depends on the exact API surface.
- Migration plan: pin the major and treat upgrades as deliberate. Check the Bot API changelog when the approval UX needs a new message feature.

**`sqlalchemy>=2.0,<2.1` (2.0.x) — 2.1 is still RC**
- Risk: `src/db/models.py` uses the 2.0-style declarative API; `src/db/alembic/versions/` holds five revisions (0001–0005).
- Migration plan: stay on 2.0.x. `alembic compare_metadata` is asserted to show zero diff (D051) — run it after any ORM change.

**The `float` at the SDK boundary is a permanent, documented exception**
- Risk: `src/adapters/binance_usdm.py:496-501` documents that `quantity`/`price` are `float` at the SDK boundary and are converted through a string-mediated Decimal-to-edge; every call site carries a `type: ignore`. The Decimal guarantee therefore **ends** at the adapter.
- Mitigation already in place: `src/adapters/binance_usdm.py:1746` keeps `_MAX_COMMISSION_RATE = Decimal("0.01")` so an out-of-range or wrong-symbol commission parse raises instead of sizing on garbage, and `src/adapters/binance_usdm.py:1463` states "never zero".
- Migration plan: none — but any new adapter method must repeat the string-mediated conversion, not pass a float through.

---

## Missing Critical Features

**The D055 execution model is neither decided in `docs/DECISIONS.md` nor implemented**
- Problem: the owner adopted direction (a) on 2026-10-18, but the only records are `.planning/phases/19-execution-plan-binding-price-check/19-NOTES.md` and `19-DEC-D055-DRAFT.md` — explicitly "Status: DRAFT. Not a DECISIONS row. `docs/DECISIONS.md` was not edited."
- Blocks: any live order; the protective-stop path; the D034 emergency close; the `CLOSE_REQUIRED` state machine.
- Required: a `docs/DECISIONS.md` row (provisional id D079) plus the 11 Demo probes listed in `19-NOTES.md`, all run by the owner with `--execute`. D072 records that the user "did not approve running the Demo smoke or the Demo probe".

**A live fill-driven protection path in `src/`**
- Problem: `attach_protectives_to_fill` is only called from `scripts/demo_rehearsal.py` (`src/execution/manager.py:1146`).
- Blocks: D055 model (a) — "on the first fill (stream or REST; PARTIALLY_FILLED counts) start BOTH the stop placement and the cancel of the entry remainder at once" (`19-NOTES.md`).

**The G3 p-value producer and the G-cell derivations**
- Problem: `src/research/multiplicity.py` has the Holm correction step only; `src/analytics/gates.py` G07/G08/G10 are pending (D069).
- Blocks: G3 evaluation, the kill gate, D013, and therefore every live-enablement path.

**The holdout is single-use and has never been read — and the first use is irreversible**
- Problem: `docs/research/holdout_consumed.json` is `{"schema": "holdout-consumed/2", "protocol_version": "v2.6.0", "entries": []}`. D060: fewer than 30 closed holdout trades still **consumes** the holdout for that lineage; the split or cutoff is never changed to raise the sample (D063(4)).
- Blocks: G5.
- Required: the D065/D067 `dataManifestHash` must be in the experiment identity before the first holdout read, and the manifest freeze (O-03b) must be complete.

**The D013 kill-gate clock and its earliest terminal state**
- Problem: `docs/research/RESEARCH_PROTOCOL.md` "Kill gate D013" fires only when at least three independently specified families have been tested **and** at least six calendar months have elapsed since the header `Frozen on: 2026-09-19` date (taken at 00:00Z), **and** no family holds a recorded passing decision. Earliest terminal state: **2027-03-19**. `docs/research/kill_gate_decisions.json` is `{"schema": "kill-gate-decisions/1", "families": [], "resets": [], "recorded_terminal": null}`.
- Blocks: nothing today (the state is legitimately `WITHIN_BUDGET`), but it is the hard deadline on the project.

**The research manifest freeze (O-03b) and the S1 constraint scenario**
- Problem: D068 records "the S1 file does not exist yet and is created at manifest freeze"; S1 is S0 with `BTCUSDT.min_notional = 100`, a descriptive stress test on Development and Validation only, never the Holdout, never a selection input. D070 adds the `terminal_settlements` row, which **changes the manifest hash**, so the run authorization O-03 must be re-issued.
- Files: `docs/research/preregistration/research-run-1-manifest.json`, `docs/research/preregistration/research-run-1-constraints-baseline.json`, `docs/research/preregistration/research-run-1-constraints-S1.json`
- Blocks: the six S0/S1 execution bindings of plan 16-46 and any run authorization.

**Per-service `env_file` split (WR-06)**
- Problem: every compose service shares one `.env` (`docker-compose.yml:18`).
- Blocks: any live key in `.env` (`docs/DECISIONS.md` D062: "must precede any live key in .env (Phase 24)").

---

## Test Coverage Gaps

**The 26 `tests/*_pg.py` files skip silently on this machine**
- What's not tested: every PostgreSQL round trip. `TEST_DATABASE_URL` is **not set** in the current process environment (verified), and `tests/pg_support.py` does not load `.env`.
- Files: `tests/test_paper_runtime_state_pg.py`, `tests/test_paper_test_signal_rehearsal.py`, `tests/test_paper_replay_inputs.py`, `tests/test_paper_runtime_restart_pg.py`, `tests/test_soak_evidence_export.py`, and the `PgShadowStores`/`PgJournalStore` path in `src/paper/shadow_runtime.py` — these are exactly `.planning/WINDOWS.md` entries 1, 4, 8, 9, 10 and 11.
- Risk: the instance lease, the restart seam, the gap ledger, the `config_identity_sha256` in `EPOCH_PINNED`/`RUNTIME_START`, and the `SHADOW_SIGNAL_LOST` row (null foreign keys) are proven **only against the in-memory port**. A PostgreSQL-only defect in those paths would ship.
- Priority: **High**. CI does run them (`.github/workflows/ci.yml:31-46` provides a PostgreSQL 17.11 service; `TEST_DATABASE_URL` is set at line 72), so the risk is local-verification confidence, not a red CI. Set `TEST_DATABASE_URL` locally (throwaway DB whose name ends in `_test`, role needs CREATEDB) or accept the gap explicitly.

**`.planning/WINDOWS.md` entry 7 is now stale**
- What changed: the entry says "shellcheck not installed on the dev machine (12 shellcheck tests skipped in the deploy test set)". Shellcheck **0.11.0 is installed and on PATH** on this machine (verified by running `shellcheck --version`). Docker and bash are also available.
- Risk: the ledger no longer describes reality, so a reader treats a now-satisfied condition as an open defect.
- Priority: **Low** (bookkeeping), but mark the entry fixed via `gsd-tools windows fixed 7` or record that the 12 tests now run.
- The other ten open entries remain accurate: `TEST_DATABASE_URL` is still unset; the Phase 16 restart drill (RUNBOOK 20.8: refused start, requested stop, process crash, host reboot, Docker daemon restart) is still soak-host-only; the heartbeat systemd credential and the 60 s timer are still operator actions; the silence watchdog is still proven only with fakes; the `queue: max` concurrency key is still unverified live.

**The silence watchdog is proven only with fakes (WINDOWS entry 6)**
- What's not tested: a real half-open Binance WebSocket, and the 120 s bound on live time. `src/paper/runtime.py` uses an injected feed clock and an injected sleep.
- Risk: the bound could be violated on a real connection without any local signal.
- Priority: **High** for the soak — first exercised on the soak host (plan 16-43).

**The `queue: max` GitHub concurrency key is unverified live (WINDOWS entry 12)**
- What's not tested: `.github/workflows/paper_freeze_check.yml:69-72` uses `group: paper-freeze-check`, `cancel-in-progress: false`, `queue: max`. The key was read from GitHub docs on 2026-10-16 without a live run.
- Risk if the key is invalid: two runs overlap; each restores the newest cache and saves under its own key, so the next run gets a log without the other run's line — a **silent EVIDENCE_GAP** in the freeze continuity, which under D065(4) restarts the 14-day qualifying trial window.
- Priority: **High** — the first live run on `master` is the proof, and plan 16-43 checks `origin/master` for the block before the pin.

**The `src/core` import purity and wall-clock freedom are unasserted**
- What's not tested: that `src/core/*.py` imports nothing outside the standard library and `src.domain`/`src.core._decimal`, and reads no clock. `tests/test_domain_no_float.py` covers floats for `src/core`; nothing covers imports or clocks.
- Risk: the invariant listed in `AGENTS.md` as machine-enforced is only convention.
- Priority: **High** — cheap to add, high blast radius if it silently breaks.

**The kill-gate guard is the only thing between five unresolved review items and a report conclusion**
- What's not tested: the defects themselves. `docs/research/kill_gate_review_registry.json` has all five items `UNRESOLVED` with `fix_commit: null`.
- Files: `src/analytics/gates.py` (G07/G08/G10 self-reported MET booleans), `src/analytics/cli.py` (`--record` with an arbitrary decisions file), `src/analytics/killgate.py` (the BACKTEST block that pools every experiment's trades), `src/execution/enablement.py` (`LiveEnablementController.enable` trusting a caller-supplied kill-gate state).
- Risk: a kill-gate report could conclude on real evidence with WR-01/06/12/13 unresolved if the guard is weakened.
- Priority: **High** — Phase 26 owns the fixes; until then, never read `docs/research/kill_gate_decisions.json` as evidence.

**The decision-alignment gates cover 9 of ~24 canonical documents**
- What's not tested: `scripts/verify_decision_alignment.py:41-72` runs 9 steps with 66 minimum gates, over `AGENTS.md`, `.planning/research/STACK.md`, `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `docs/GLOSSARY.md`, `docs/DECISIONS.md`, `docs/DOC_STATUS.md`, `docs/SOURCES.md`, `docs/trading/RISK_MANAGEMENT.md`, `docs/trading/EXECUTION_SPEC.md`, `docs/trading/SIGNAL_AND_ALERTS.md`, `docs/data/DATA_MODEL.md`, `docs/configuration/CONFIGURATION.md`, `docs/operations/RUNBOOK.md`, `docs/operations/SECURITY_AND_OPERATIONS.md`, `docs/integration/BINANCE.md`, `docs/integration/TRADINGVIEW.md`, `docs/research/RESEARCH_PROTOCOL.md` and `params/**`.
- **Not covered — doc drift is possible with no gate:** `docs/00_PRODUCT_SCOPE.md`, `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/README.md`, `docs/TECHNOLOGY_STACK.md`, `docs/architecture/ARCHITECTURE.md`, `docs/architecture/DATA_PIPELINE.md`, `docs/backtest/BACKTEST_SPEC.md`, `docs/backtest/METRICS.md`, `docs/implementation/AGENT_INSTRUCTIONS.md`, `docs/implementation/IMPLEMENTATION_PLAN.md`, `docs/integration/TELEGRAM.md`, `docs/operations/DEPLOY_GUIDE.vi.md`, `docs/research/GEOMETRY_AUDIT.md`, `docs/research/TRADING_STRATEGY_RESEARCH.md`, `docs/research/families/*.md`, `docs/strategy/TRADING_STRATEGY_SPEC.md`, `docs/testing/TESTING_STRATEGY.md`.
- Risk: `docs/strategy/TRADING_STRATEGY_SPEC.md` is the family-sheet authority and its §12 rule (a strategy change needs a new `strategy_version`) is the rule `docs/DECISIONS.md` D070/D075 rely on — and nothing checks it. `docs/testing/TESTING_STRATEGY.md` is the golden-fixture protocol and is likewise ungated.
- Priority: **Medium**. The cheapest additions are `docs/strategy/TRADING_STRATEGY_SPEC.md` (the §12 rule) and `docs/backtest/BACKTEST_SPEC.md` (the acceptance-gate wording the protocol cites).

**The `src/risk/portfolio.py` F841 ignore is a standing suppression on the money-safety path**
- What's not tested: nothing asserts that the daily-loss thresholds are actually read at the point of gating. The gate works only because `_derive_daily_state` (`src/risk/portfolio.py:243-247`) consumes them.
- Priority: **Medium** — resolve together with the dead assignments.

**`src/paper/shadow.py` is exempt from the float guard as a whole file**
- What's not tested: any float in `src/paper/shadow.py` other than the tenacity wait.
- Priority: **Medium**.

**The `tests/*_pg.py` skip mechanism fails closed only in CI**
- `tests/infra_helpers.py::infra_skip` turns a missing-infrastructure skip into a failure when `TRADING_CI_STRICT=1`. CI sets it (`.github/workflows/ci.yml:24`); a local run does not, so a local green run can hide 26 skipped files.
- Recommendation: set `TRADING_CI_STRICT=1` locally to see exactly what CI sees, and always read the skip summary (`-rs`) before claiming a green suite.

---

*Concerns audit: 2026-10-19*
