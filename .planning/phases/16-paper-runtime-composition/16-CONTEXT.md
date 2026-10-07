# Phase 16: Paper Runtime Composition + SHADOW Approval Mode - Context

**Gathered:** 2026-10-07
**Status:** Ready for planning, with blocking-human checkpoints (see "Open user decisions")
**Mode:** --auto, single pass, restricted by the owner's hard rule: an agent never auto-picks a money or safety decision. Auto mode picked recommended options for IMPLEMENTATION style only. Everything the owner reserved is listed under "Open user decisions (NOT decided by auto mode)" with no selection.
**Machine note (D061 G):** this context was written on the discuss machine. No code, no tests and no network call were run. Execution needs the connected machine.

<domain>
## Phase Boundary

A runnable paper process (M3) that observes the corrected strategy families forward on live Binance market data, so the wall-clock-bound soak can start. The process composes the existing parts: WS adapter, supervisor, a per-closed-bar paper tick, the journal writer, and a SHADOW approval loop. In SHADOW the operator can APPROVE / CONFIRM / CANCEL / SKIP, and every decision is journaled with timestamps and measured approval delay. A confirmed plan gets a simulated position using the Phase 14 fill semantics on live data. No real order can result (D040).

The phase also owns, by D059 item 5 and D061: the research runner (infrastructure only), the feasibility and sample-size gate, the registration of candidate parameter sets, the enforced kill-gate guard (D061 F), the freeze-check generalization (D061 A), the uptime and coverage measure, the soak-host deployment configuration, and the closure chain that ends in a trial soak. The two D062 items (WR-05, CR-01) are prerequisites (see "Prerequisites").

Requirements closed here: PAPER-01 (criteria 1, 2, 7) and PAPER-02 (criteria 3, 5). BKTS-03 is owned here through the research runner. PAPER-03 stays Pending (Phase 26 closes it). EXEC-01, EXEC-02, OPS-01 and OPS-02 are NOT closed here: they stay Pending until Demo-proven evidence exists (Phases 24 to 26); the SHADOW hard isolation (SC6) is the only place this phase touches them, and only to prove that no order path exists.

Out of scope: any order placement, any trade-capable key, live or Demo orders (Phases 18 to 25), the full Telegram hardening (user-id auth, working SKIP in all paths, money amounts, keyboard removal: Phase 23), user-data stream (18), reconcile (20), the D055 execution model, the kill-gate WR fixes themselves (Phase 26), `PAPER_START_ALLOWLIST` contents (stays empty here, E).

Success criteria are in `.planning/ROADMAP.md` Phase 16 (SC1 to SC9). This file does not restate them.

## Prerequisites

- **WR-05 and CR-01 (D062)** are implemented by quick tasks `261007-mkw` (WR-05: `trading` user joins sudo with a password, no NOPASSWD; `deploy/bootstrap.sh`, checklist, RUNBOOK 13.5) and `261007-mv4` (CR-01: `--checksum` instead of `--size-only` at `src/ops/backup_remote.py` line 334, with tests and RUNBOOK section 11), both before the EC2 bootstrap and the first real backup. They are NOT Phase 16 plan tasks. They become Phase 16 plan tasks only if the executor finds them still unimplemented at execution time (check `git log` and `deploy/bootstrap.sh` for the sudo change, and `src/ops/backup_remote.py` for `--checksum`).
- The EC2 host is created the weekend of 2026-10-10 only after both are implemented and tested, and on that date only the collector moves (the paper runtime does not exist yet).
- WR-06 (per-service `env_file` split, G3-029) is NOT in this phase, but the paper service here must not receive any live key: the paper env needs only `POSTGRES_*`, `TELEGRAM_*`; no `BINANCE_*` trade-capable key (SC6). The plan documents the env-variable list the `paper` service reads.

</domain>

<decisions>
## Implementation Decisions

Numbering: `D-nn` is local to this phase. `D0xx` always means a row in `docs/DECISIONS.md`. Reversibility ratings are given where undoing would be costly.

### A. Locked from DECISIONS.md (copied, never altered; changing any needs the user)

- **L-01 (D061 A, freeze check):** the hourly freeze check stays on GitHub Actions; the hard-coded `trend-pullback` / `baseline-v3` is removed; it reads the parameter set authorized through `PAPER_START_ALLOWLIST`; with an empty allowlist it reports SKIPPED (allowlist empty), never CLEAN, never a red error, never a fallback; the Actions cache is operational state, not canonical evidence; `pinned_epoch.json` and `registry_diff.jsonl` are exported to a durable location the plan proposes and the user approves; a separate uptime and coverage measure is required because CLEAN ticks never prove the runtime ran.
- **L-02 (D061 B, parity):** parity stays at the current level (`tests/test_paper_parity.py`; the simulator emits trades only). The plan compares the decision surface (closed bar, feature, signal, plan, risk verdict) through shared core functions or a non-semantic observer, without changing Phase 14 simulator semantics or hashes. If a simulator change is unavoidable, work stops and a new decision is recorded.
- **L-03 (D061 C):** one Phase 16 with several plans, no Phase 16.1. The research runner is its own plan and is infrastructure only: it never authorizes a candidate. Its feasibility and sample-size gate may count trades to check whether the protocol floors are reachable (floors never lowered) and never to rank, select or tune.
- **L-04 (D061 D, ratified 2026-10-07; DECISION labels; changing any before the trial soak starts needs a new user approval):** trial soak 14 calendar days on the EC2 host; runtime coverage at least 95 percent of the trial window with a healthy feed; time of day is reported as a distribution, not a pass condition; freeze check CLEAN on every tick from the epoch pin to the end of the trial (any other line fails it); parity tolerance zero for the decision logic (the same closed bars give the same signals, plans and risk verdicts); every gap is explained by a recorded process stop or disconnect, with no fabricated bar and no unexplained gap; after every restart warm-up completes before the first evaluated bar, with no duplicate signal and no missing journal row; no minimum trade count, and one clearly labelled test signal may exercise the SHADOW chain once and never counts as strategy evidence. The plan may refine wording only.
- **L-05 (D061 E):** `PAPER_START_ALLOWLIST` stays empty; only the user authorizes an entry by exact `strategy_id`, `parameter_set_id` and 64-hex SHA-256 with `purpose`, `approved_at` and `basis`; no fallback to `baseline-v3` or any legacy set; nothing moves automatically from the research runner to the allowlist; an empty allowlist is a valid fail-closed state, not a failure of the phase.
- **L-06 (D061 F):** the kill-gate code stays owned by Phase 26. This phase carries one plan with an enforced guard and an automated test: no kill-gate report concludes on real evidence while WR-01, WR-06, WR-12 and WR-13 (Phase 10 review) are unresolved. Research evidence is not a kill-gate conclusion; if the research runner needs the kill gate before Phase 26 a separate decision is required.
- **L-07 (D061 G):** execution machine builds, tests and produces the WebSocket smoke, Telegram and Demo evidence; every step touching Binance or Telegram is blocking-human with measurable acceptance and stated prerequisites; plans are self-contained and cite only repository files; research facts carry a source URL, the read date and a not-verified-live label.
- **L-08 (D061 H):** an agent may recommend, implement approved decisions and verify, and never silently decide: paper exit criteria, the allowlist, candidate parameter values, reconciliation and freshness thresholds, the D055 execution model, OQ-1, protocol acceptance thresholds, the kill-gate WR design, safety policy and go-live gates, anything that changes strategy semantics, and any value chosen or adjusted from backtest or research results.
- **L-09 (D061 I):** where a number is not yet known the plan stops at a blocking-human checkpoint and never fills a default.
- **L-10 (D061 J, closure chain):** runtime ready; a hypothesis and parameter grid written or explicitly approved by the user; a research run authorized by a separate user command (approving the grid does not authorize the run); a valid candidate (rationalized, preregistered, structurally valid, no PLACEHOLDER, registered and hashed; it does NOT need to pass G1 to G5 and G1 to G5 never rank candidates); the user authorizes the exact hash; paper starts; the epoch is pinned; a trial soak meets the ratified criteria. PAPER-01 and PAPER-02 can complete here; PAPER-03 stays Pending (Phase 26).
- **L-11 (D061 hosts, decided later 2026-10-07):** trial soak and long soak run on one AWS EC2 host in ap-southeast-1 (Singapore); the execution machine never produces soak evidence; bars that closed while the process was down never produce signals (a gap is recorded, no late or fabricated signal); the OI collector moves to EC2 before the long soak; the long soak starts right after Phase 16 closes and runs through Phases 18 to 25 with the EC2 cost accepted; the hypothesis and grid are drafted by an agent in plain language with rationale and sources and approved or changed by the user. The soak database is separate from the development and test database, the soak runs from a pinned image, backups exist before the long soak, and `docker compose down -v` is never run on the soak project. D042 host conditions: public ping to `fapi.binance.com` from the instance first, fixed Elastic IP, encrypted EBS, private encrypted S3 backup bucket, external heartbeat monitor, chrony, budget alert, paid plan.
- **L-12 (D040):** SHADOW means signals and APPROVE/SKIP decisions are journaled with simulated fills on real market data; no trade-capable API key is loaded and no order adapter is constructed. Release path SHADOW then DEMO then CANARY then LIVE, no stage skipped.
- **L-13 (D041):** APPROVE never places an order: the bot edits the message into a confirmation card (mode SHADOW/DEMO/LIVE, symbol, side, quantity, notional, estimated loss at SL, current mark price vs entry/SL, remaining validity) with CONFIRM and CANCEL. The confirm token is separate from the approval token, single-use, bound to the same authorized user id and plan hash, and expires after a short TTL (default 60 s, configurable). CANCEL or expiry places nothing and is journaled. All pre-placement checks re-run at confirm time. The same two-step flow runs in SHADOW for realistic delay measurement and never places orders.
- **L-14 (D059 items 1, 2, 3, 4):** TP1 far-half-zone rule stays deferred; maker/post-only entries deferred; D013 stays Provisional and does not move because Phase 16 finishes; OI collector running and writing no later than 2026-10-08, every later gap recorded as a coverage gap, dataset never called full history while a known gap exists (user commitment, not enforceable by the repository).
- **L-15 (D060 / D057):** protocol v2.1.0 is frozen (G5 floor of 30 qualifying closed trades, counted as G1 counts them); nothing is applied backwards; no protocol amendment is part of this phase.
- **L-16 (D058):** live mark-price data fails closed for LIVE; simulation and paper may follow a different policy. This is not the answer to OQ-1.
- **L-17 (D056, D055):** no health or enablement change here; D055 execution model stays OPEN (waits for the Phase 18 Demo probe); Phase 16 touches no order path so it depends on neither.

### B. Runtime composition (PAPER-01; SC1, SC2, SC7)

- **D-01:** The runnable process is a new module `src/paper/runtime.py` with a `python -m src.paper.runtime` entrypoint, an asyncio main that composes `PaperWsAdapter`, `PaperSupervisor`, the REST backfill adapter, the per-closed-bar tick, the journal sink and the SHADOW approval loop. The compose `paper` service replaces its placeholder command with this entrypoint and defines a real healthcheck (the placeholder disables the inherited collector HEALTHCHECK; D-06 of 13.1 says Phase 16 defines the probe). The runtime refuses to start when `PAPER_START_ALLOWLIST` admits nothing for the requested parameter set, logs `SKIPPED (allowlist empty)` and exits 0 without subscribing (L-05). — **Reversibility:** reversible.
- **D-02:** `run_paper_tick` is a stateless batch function (it takes warm-up bars plus `feed_events` and re-runs the gate every call, review IN-03). The runtime therefore owns the incremental state: warm-up buffers per (symbol, interval), the pinned epoch, dedup of seen open times, and per-restart warm-up from REST before the first evaluated bar (L-04). The runtime pins the epoch once at start (`pin_stream_epoch` then `write_pinned_state`), then calls a thin per-closed-bar wrapper that passes the already-pinned hash. It must not change `run_paper_tick` semantics or its digest on existing parity fixtures. — **Reversibility:** costly (many callers and tests rely on the current tick contract).
- **D-03:** Review IN-01..IN-05 (G4-018) are fixed here because this phase is the first production consumer: `PaperAllowlistEntry` gets `__post_init__` validation (64 lowercase hex, non-empty ids, ISO date for `approved_at`, non-empty `purpose` and `basis`); docstrings of `run_paper_tick`, the module and `_load_parameter_set_with_root` are corrected; the "stream-start gate" naming is aligned with what runs (a once-per-process gate in the runtime plus a per-call gate in the function); `REGISTRY_ROOT` is bound once (resolve at call time or pass the loaded set), with a test that gate and loop can never judge different files; test nits tightened. The earlier Phase 15 warnings (WR-01..WR-05 of `15-REVIEW-PAPER-GATE.md`) are checked against `15-REVIEW-PAPER-GATE-FIX.md` and anything still open is folded in. — **Reversibility:** reversible.
- **D-04:** Process state that must survive a restart (pinned epoch, last seen close per pair, open simulated positions, pending approvals) lives in the SOAK PostgreSQL through the Phase 17 stores (`PgJournalStore`, approvals, `system_state_events`), plus the `logs/paper/pinned_epoch.json` file for the freeze CLI. The paper journal sink writes through `PgJournalStore.record` (replay-idempotent, append-only). No second persistence mechanism is invented. — **Reversibility:** costly (schema consumers).
- **D-05:** Feed events: the WS callback runs on the SDK thread; the runtime hands closed events to the asyncio loop through a thread-safe queue (the supervisor already uses a lock for `_last_close`). Only `is_closed` events enter the tick (SC7: the stream also delivers open candles). `event["interval"]` is set per stream, REST-backfilled klines convert into the same `feed_events` path (G2-007), and `CONTEXT_BAR` is confirmed as a feed-gate reason code and added to `docs/GLOSSARY.md`. — **Reversibility:** reversible.
- **D-06:** Gaps: a bar closed while the process was down is recorded as a gap and produces no signal (L-11); backfill during warm-up may restore context bars (`CONTEXT_BAR`) but never evaluates a missed bar as a fresh signal. The runtime writes a `RUNTIME_START`, `RUNTIME_STOP` and `WS_DISCONNECT/RECONNECT` journal row so every gap is explainable (L-04).
- **D-07:** Runtime coverage and uptime (L-01, L-04): a heartbeat row per closed bar processed plus an expected-bar schedule derived from the interval grid; a small pure function computes "expected closed bars vs processed or explained-gap bars" over a window. It is evidence tooling that reports; the 95 percent figure is L-04. What counts as a "healthy feed" (silence limits) is OPEN (O-07).

### C. WS adapter fix (SC2, SC7; F-125, F-607)

- **D-08:** `src/adapters/paper_ws.py` is fixed in the three places the 2026-10-04 live probe found: `await` the coroutines `create_connection` and `kline_candlestick_streams`; pass the plain string interval (`"1h"`, `"4h"`, `"1m"`) instead of the SDK interval Enum; set `stream_url` from the SDK PROD constant in the default `ConfigurationWebSocketStreams`. The handle exposes `.on("message", cb)` (no `on_message`), so dispatch registration changes accordingly. The adapter's methods that cross into the SDK become `async`; the supervisor's `WsAdapterLike` protocol follows. SDK types stay behind the adapter (domain boundary). — **Reversibility:** reversible.
- **D-09:** Fakes are contract-bound to the SDK's async signatures: a contract test introspects the installed SDK (`inspect.iscoroutinefunction`, parameter names and types of `create_connection`, `kline_candlestick_streams`, the handle's `.on`) and asserts the fake mirrors them, so a fake that is synchronous where the SDK is asynchronous fails CI (F-125, F-607). The test must run in CI without network.
- **D-10:** The live smoke (SC7) is a blocking-human step on the connected machine: run the runtime against mainnet public market data only (no key), observe `ws_subscribe` succeeding and at least one closed 1h or 4h event per subscribed interval reaching the supervisor (`soak_smoke.log` no longer reads `BLOCKED`), measurable acceptance recorded in a smoke evidence file. The 1m interval is used to prove the path quickly (a closed 1m candle arrives within about a minute); the 1h/4h closed events are proven by waiting a real bar close. One real fetch from data.binance.vision is observed in the same smoke (G3-026). Prerequisite: a network path that does not return 502 for the WS host (D061 G observed 502 through the proxy on 2026-10-07).
- **D-11:** The Binance WebSocket facts (URL split to `/public`, `/market`, `/private` of 2026-04, the 24-hour connection lifetime, reconnect behaviour) are re-read from the official pages by the planner/researcher with URL and date; `docs/SOURCES.md` line 44 records the 24-hour lifetime as "not fetched". Nothing is coded from memory.

### D. SHADOW mode, simulated fills, approvals (PAPER-02; SC3, SC5, SC6)

- **D-12:** A `Mode` value (SHADOW first; DEMO and LIVE exist as names only) is carried by the runtime and printed in every Telegram message. SHADOW messages carry the exact label `SHADOW — no real order` (SC5, text from the ROADMAP). No other mode is constructible by the Phase 16 runtime.
- **D-13:** Hard isolation (SC6), three layers. (1) Structure: the SHADOW runtime module graph must not import `src.execution.manager`, `src.execution.placement` or the Binance order adapter methods (`src.adapters.binance_usdm` order functions); enforced by an AST/import test (pattern of `tests/test_paper_start_gate.py`). (2) Environment: the runtime constructs its config from an allowlist of variable names and the startup check refuses to run when any `BINANCE_LIVE_*` or `BINANCE_TESTNET_*` or other trade-capable key variable is present in the process environment. (3) Behavior: a test drives a full SHADOW confirm and proves with a spy that `execute_approved_plan` and every order endpoint call are unreachable, with a negative control that shows the spy would catch a call. The market-data adapter used by the paper runtime is the public-data one with no credentials.
- **D-14:** Simulated fills reuse Phase 14 semantics by calling the same lifecycle functions (`src/backtest/lifecycle.py` `new_plan_state` / `advance`, entry eligibility and touch rules in `src/backtest/entry.py`, exit ladder in `src/backtest/exits.py`, costs in `src/backtest/costs.py` and `funding.py`) on closed 1m trade bars and 1m mark-price bars from live data. They are called, not copied, so the semantics hash (`simulator_semantics_version`) stays authoritative; any need to modify the simulator stops the work and needs a new decision (L-02). The source of live 1m mark-price bars (REST `markPriceKlines` poll vs a WS stream) is a research item for the planner with a source URL and read date (`docs/SOURCES.md` already records the REST endpoint); recommendation is the REST poll through the existing `src/data` minute source because the semantics are already proven there. — **Reversibility:** costly (evidence comparability).
- **D-15:** Approval delay is measured, not a fixed 30 s: `APPROVAL_DELAY_LAG_SECONDS` in `src/paper/attribution.py` is replaced as the delay source by `acted_at_utc - requested_at_utc` from the approval row (and confirm timestamps); the constant stays only as a documented default for records with no human action. System vs user-executed-sim vs opportunity attribution (existing `AttributionKind`) is produced for every signal: APPROVE then CONFIRM gives `user-executed-sim`; SKIP, CANCEL and expiry give `opportunity` with the reason; plans nobody touched are `system` or `opportunity` per the existing PAPER-02 rule in `src/paper/attribution.py` (planner confirms against `07-CONTEXT.md`).
- **D-16:** SIMULATE buttons become functional in SHADOW (F-961): `send_simulate` and `build_simulate_keyboard` (`src/adapters/telegram_notify.py`) lead to the approval flow through the existing `dispatch_callback` / `on_callback` and `src/approval` replay (idempotent, at-least-once callbacks replay to existing state, no auto-approve on notification failure, `src/paper/notify.py` journal-first ordering). The CONFIRM card of L-13 is implemented for SHADOW in this phase as a minimal module reusable by Phase 23 (separate single-use confirm token, 60 s default TTL from D041, same plan hash, re-run pre-checks at confirm). Phase 23 extends it to money amounts, full user-id auth and keyboard removal; this phase uses the existing `authorized_chat_gate` and states plainly that user-id auth is Phase 23. The SHADOW approval expiry value is OPEN (O-08).
- **D-17:** A confirmed SHADOW plan opens a simulated position tracked by a minimal paper ledger built on `src/backtest/ledger.py`, so `open_positions` and `daily_loss_quote` inputs to the risk verdict come from simulated state (G4-010, D052 item (i)). The simulated account equity used for sizing is a sizing value and is OPEN (O-09).
- **D-18:** The journal reports system vs user vs opportunity outcomes through the existing analytics path (`src/analytics`, `src/adapters/analytics_files.py`): the plan extends the Phase 10 reporting inputs with the SHADOW records and adds no new metric definitions. The report states plainly that the soak evidence never feeds a value into trading logic.
- **D-19:** The labelled test signal (L-04): a CLI or runtime flag that injects exactly one clearly labelled test signal to exercise the chain once, marked `TEST_SIGNAL` in every record, excluded from every strategy count by the analytics reader, and requiring an explicit operator command at run time (blocking-human on the execution machine or EC2). It is never a strategy decision and never passes through the allowlist gate as strategy evidence.

### E. Parity of the decision surface (L-02)

- **D-20:** A pure function `decision_surface(...)` over the shared `src/core` functions (features, `evaluate`, `plan`) and `src/risk` verdict produces, per closed bar, a record {bar, feature digest, signal or NO_TRADE reason, plan hash, risk verdict}. The paper loop emits it from live bars; a replay test feeds the same recorded closed bars through the same function and compares digests with tolerance zero. The Phase 14 simulator is not changed and its hashes do not move. Parity covers strategy-stage NO_TRADE and signal-less bars (G2-008) because the observer does not depend on the simulator emitting them. If a comparison against the backtest trades is needed, it is trade-level only and unchanged (`tests/test_paper_parity.py`). If this turns out impossible without a simulator change: stop and record a decision (L-02). — **Reversibility:** reversible.

### F. Freeze check and evidence (L-01)

- **D-21:** `src/paper/freeze.py` CLI gains an allowlist-driven mode (`--from-allowlist`): with an empty allowlist it writes one `SKIPPED` line to `registry_diff.jsonl` (reason `allowlist empty`) and exits 0; it never prints CLEAN, never exits red, never falls back to any set. With an entry it checks that exact `strategy_id`/`parameter_set_id` and the pinned hash. `.github/workflows/paper_freeze_check.yml` drops the two hard-coded flags and uses the new mode. A test proves the empty-allowlist path and that no hard-coded id remains in the workflow. Exit-code semantics for the non-empty case stay as today (0 clean, 1 error, 2 missing pinned state, 3 rollover); a SKIPPED line written before the pin is expected and not counted against L-04.
- **D-22:** CLEAN ticks cannot prove the host ran (L-01), so the uptime and coverage measure (D-07) is a separate evidence artifact produced from the runtime's heartbeat rows. The workflow on GitHub runs against the repository checkout (registry files), not the host; the plan states that it proves registry immutability only. The durable export location is OPEN (O-01).
- **D-23:** The exit-criteria evaluator: one script computes each L-04 criterion from the exported evidence (window length, coverage fraction with the healthy-feed rule once ratified, consecutive CLEAN freeze lines from the pin, parity digests, gap explanations, restart warm-up checks, duplicate-signal and missing-journal-row checks) and prints PASS/FAIL per criterion with the evidence it read. It evaluates; it never changes a threshold; the values come from L-04 as constants with their D061 label.

### G. Research runner (L-03; D059 item 5; BKTS-03)

- **D-24:** The research runner is a separate plan and a new module (recommended `src/research/` with a CLI `python -m src.research.run`), infrastructure only. It builds case input from the collected datasets (`src/data/case_input.py`), runs the Phase 14 `simulate` on a named parameter set, reads `read_code_version` and calls `experiment.assemble` (D052-open), and writes the experiment record. It never writes `PAPER_START_ALLOWLIST`, never ranks or selects, and prints no verdict. Its inputs (hypothesis, grid, run authorization) are files supplied by the user (O-02, O-03).
- **D-25:** The runner refuses to run without a user-written authorization artifact whose recorded grid hash equals the hash of the grid it is about to run (the separate user command of L-10). The runner implements the check; what the artifact says and when it is written are the user's (O-03).
- **D-26:** Feasibility and sample-size gate: a reporting step that counts closed trades pooled and per validation fold against the protocol floors (G1: 100 pooled and 30 per fold; G5: 30 in the holdout) and reports any shortfall (G3-027, D043). The floors are never lowered, nothing is ranked by the count, and a shortfall is a report, not a parameter change. It uses the G1 counting rule of D060 (closed filled trades with exit SL or TP2; `END_OF_DATA` counted apart).
- **D-27:** BKTS-03: the runner prints the parameter-plateau analysis the report currently leaves as `not computed (BKTS-03 pending)` (`src/backtest/report.py:50`), as reporting only, over the pre-registered grid. The REQUIREMENTS re-map stays with the requirements batch.
- **D-28:** Candidate registration: a registered candidate is a parameter-set TOML under `params/<family>/` with a complete rationale table (provenance label per value; never PLACEHOLDER), hashed by the registry loader, never edited in place; any change is a new set plus a new `strategy_version` (AGENTS.md conventions). Candidates come only from pre-registered values with a rationale, never from a backtest result (L-03, D059 item 5). The runner provides a validator ("structurally valid, rationalized, preregistered, no PLACEHOLDER, registered and hashed") and prints the exact 64-hex hash for the user to read. It does not edit the allowlist.
- **D-29:** `modeled_costs_per_unit` (None on v2 filled `TradeRecord`s) is surfaced as a documented limitation in the runner output; restoring it is OPEN (O-10). OQ-1 treatment of mark-hole trades is OPEN (O-06): the runner reports the count of trades held through mark-price holes, separately and unclassified, so the user decides with the real number.
- **D-30:** G4-009: before any incremental-feature change, the runner's first real run is timed once without tracemalloc; the incremental feature series stays deferred and any later change must be an exact-equivalence refactor (D052 item (h)). G3-012: `max_cost_to_risk` 0.15 is not touched; a revisit is a new parameter set chosen before any result is seen, user-owned (D046 item 6).

### H. Kill-gate guard (L-06)

- **D-31:** A plan adds an enforced guard: the kill-gate report entrypoints (`src/analytics/killgate.py`, `render_killgate.py`, `src/analytics/cli.py` kill-gate path) refuse to conclude on real evidence while a registry of the four unresolved items (WR-01, WR-06, WR-12, WR-13) lists any as unresolved. The registry is a small versioned file listing each item with state `UNRESOLVED` until Phase 26 flips it with its fix commit; the guard reads it. An automated test proves the refusal on real-evidence input and the pass on synthetic/fixture input, and that flipping any one item back to UNRESOLVED blocks again. The guard changes no WR design; the WR designs stay open (H, Phase 26).

### I. Deployment and operations on the soak host (L-11; D061-deploy, D061-ec2, D061-iso)

- **D-32:** One concrete tested configuration, a dedicated Compose project name (for example `trading-soak`) with its own PostgreSQL volume, distinct from the development stack and its test databases; the `paper` service runs from the digest-pinned image tag produced by CI, never from a working-tree bind mount; the `paper` service env lists no `BINANCE_*` trade key; the collector and the paper process run in the same Compose project on the host. A guard script and test refuse `docker compose ... down -v` against the soak project name (wrapper script plus a test that greps the RUNBOOK and scripts for an unguarded `down -v` against that project). Backups exist and a restore drill ran before the long soak starts (the existing backup chain, RUNBOOK section 11).
- **D-33:** Data path (D061-deploy): the plan defines the exact command that pulls the research data to the development machine over the existing backup chain (encrypted `pg_dump` plus append-only Parquet to a private S3 store, `deploy/restore.sh`, `src/ops/backup_remote.py`), the migration of the existing collector, Parquet store and database with `deploy/migrate.sh` (it reports Parquet fingerprints, watermarks and the OI gap), and the real-host checks of 13.1 UAT 8 to 10. These are blocking-human steps on the connected machine; the OI gap the switch causes is recorded as a coverage gap (L-14).
- **D-34:** EC2 provisioning (D061-ec2) is a blocking-human runbook on the connected machine with measurable acceptance for each D042 condition; facts about AWS and rclone and the distro come from the official docs or `docs/SOURCES.md`, never from memory, with URL and read date. The plan adds the runbook text; it does not create the host.
- **D-35:** Time: the host runs chrony and the runtime reads UTC only (strategy and tick use injected clocks; there is one runtime clock source) and logs a clock-skew check at start against a public time source; Telegram messages show UTC and Asia/Ho_Chi_Minh per the stack.

### J. Plan decomposition (Claude's discretion for the planner; one phase, several plans, no 16.1)

Suggested waves, to be adjusted by the planner without changing any locked item:
1. WS adapter fix and SDK-bound fakes (D-08 to D-11 code part) and the review IN fixes (D-03).
2. Runtime composition, journal sink, restart and gap handling, coverage measure (D-01, D-02, D-04 to D-07).
3. SHADOW mode: isolation tests, simulated fills and ledger, approvals with CONFIRM, attribution and report (D-12 to D-19).
4. Decision-surface parity (D-20); freeze-check generalization and evidence evaluator (D-21 to D-23).
5. Research runner (D-24 to D-30) and the kill-gate guard (D-31): independent of waves 2 to 4.
6. Deployment configuration, RUNBOOK, soak guards (D-32 to D-35).
7. Blocking-human checkpoints, in order: live WS smoke; EC2 provisioning and data migration; durable-location approval; grid approval; run authorization; exact-hash allowlist entry; epoch pin; trial soak start; trial soak evaluation. The execution plan marks each checkpoint "blocking-human, never auto-selected".

### Claude's Discretion

Module and file names where not given above, test file names, structlog event names, queue sizes, internal data-class names, the exact form of the evidence file layouts (provided no threshold or location is decided), the order of waves, and the wording of runbook steps. Anything that would be a number a human must own is NOT discretionary (see the next section).

</decisions>

## Open user decisions (NOT decided by auto mode)

Each item below is a blocking-human checkpoint in the plan. Options and a recommendation are given for the user's convenience; **no option is selected, and no agent may fill a default** (D061 H and I). Where D061 already ratified a value it is in the Locked section, not here.

- **O-01 Durable evidence location** (for `pinned_epoch.json`, `registry_diff.jsonl`, coverage artifacts, exit-criteria evaluation output). The plan proposes, the user approves (D061 A and 5). Options: (a) the private encrypted S3 backup bucket under a separate append-only evidence prefix, written from the EC2 host; (b) a dedicated private Git repository or branch holding committed evidence files and digests (not the code repository history); (c) GitHub Actions artifacts and cache only (the Actions cache is operational state, not canonical evidence per L-01; retention not verified here); (d) EC2 local disk plus the existing backup chain only; (e) a combination with the S3 copy canonical and digests committed to the repository. Recommendation (not selected): (e). Trade-offs to document with sources: tamper evidence, retention, who can read, cost, loss if the host dies.
- **O-02 Hypothesis and parameter grid approval** (closure chain, L-10). An agent drafts in plain language with rationale and sources; the user approves, changes or writes it. Nothing about candidate values is pre-filled here. Recommendation: draft only after the runtime exists, keep the grid inside the protocol variant budget N = 25 per family.
- **O-03 Research-run authorization** (a separate user command; approving the grid does not authorize the run). Options for the form of the artifact: (a) a user-committed JSON/TOML authorization file with the grid hash, date and the user's statement; (b) a CLI confirmation flag with the grid hash typed by the user; (c) both. Recommendation: (a). The data window, the symbols and the universe (`research-universe-v1`), and the split dates (the protocol fixes the 40/40/20 proportions, not the dates) are decided with this checkpoint (G4-003).
- **O-04 Exact-hash allowlist entry** (the first non-empty `PAPER_START_ALLOWLIST`): exact `strategy_id`, `parameter_set_id`, 64-hex hash, `purpose`, `approved_at`, `basis`. Only the user authorizes it. This phase's code and tests keep it empty; the plan treats the entry as a later user commit.
- **O-05 D055 execution model** (protective stop before or after the entry fill, -4509): OPEN, waits for the Phase 18 Demo probe. Phase 16 contains no order path and depends on neither candidate.
- **O-06 OQ-1** (a backtest trade held through mark-price holes: annotate only, count against coverage, exclude from pooled R, or void). Decided with the real count from the first real-data run; this phase's runner only reports the count (D-29). D058 is not the answer.
- **O-07 Healthy-feed definition and freshness thresholds for the runtime** (the L-04 coverage criterion says "with a healthy feed" but does not define it): maximum WS silence per interval, maximum tolerated stale bar age, reconnect backoff and retry bounds, how long a gap may last before the runtime reports DEGRADED, and the REST backfill depth. Current constants in `src/paper/supervisor.py` and `src/paper/resync.py` are implementation values and are not ratified safety thresholds. Recommendation: the planner collects the existing constants and the Binance connection facts (D-11) into one table and the user ratifies the numbers before the trial soak. Related reconcile cadence and WS-silence thresholds for LIVE (T-06, G2-026) are Phase 20, not here.
- **O-08 SHADOW approval validity window** (how long an APPROVE button stays valid before expiry, if it is not simply the plan expiry from the parameter set). The D041 confirm TTL default (60 s, configurable) is locked; the approval-expiry duration is not stated in D041. Recommendation: derive it from the plan's own expiry already in the parameter set, adding no new number; if a separate number is needed, the user sets it.
- **O-09 SHADOW simulated account equity and risk inputs** (the equity used to size simulated trades, daily loss base, leverage assumption, margin type). Any sizing or risk value is the user's. Context only: AGENTS.md states research capital of 500 to 1,000 USD. No default is filled; D-17 consumes whatever is ratified.
- **O-10 Restoring `modeled_costs_per_unit` on v2 filled `TradeRecord`s** (D052-open) and any protocol or evidence-semantics consequence: open user decision. Options: leave None and document; restore from the cost model at record time; restore from a post-run recomputation. Recommendation: leave unchanged until the first real run shows whether any report needs it.
- **O-11 Closure-chain triggers on the soak host:** the user's go for (i) creating the EC2 host (target weekend of 2026-10-10 per D061, only after WR-05 and CR-01 are implemented and tested), (ii) moving the collector, (iii) starting the trial soak, (iv) injecting the single labelled test signal, (v) declaring the trial soak met. Each is an explicit user command; none is auto-advanced.
- **O-12 Budget and instance numbers for EC2** (instance type, EBS size, budget-alert amount, S3 lifecycle and retention): user decisions with the cost accepted in D061. The plan proposes with sources and the user approves.
- **O-13 Whether older rationale-less sets may start paper** is already answered by 15-17 (allowlist empty) and is not reopened. Any change to `test_production_allowlist_is_empty_by_user_decision` or to D054 item (i) needs a new user checkpoint (G4-021).

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.** Source order when they conflict: `docs/DECISIONS.md` > `docs/` > `AGENTS.md` > `.planning/` (D031).

### Decisions and roadmap
- `docs/DECISIONS.md` rows D040, D041, D042, D043, D046, D050, D052, D054, D055 to D062 — SHADOW path, two-step confirm, host conditions, trade floor, paper start gate, the Phase 16 pre-decisions A to J, WR-05 / CR-01.
- `.planning/ROADMAP.md` Phase 16 section (about line 692 to 744), Phase 18, 20, 23, 24, 26 sections for ownership boundaries.
- `.planning/REQUIREMENTS.md` PAPER-01..03, BKTS-03, EXEC-01/02, OPS-01/02 and the traceability note at the end.
- `.planning/STATE.md` "Open user decisions (2026-10-07)" and "Commitments with dates".
- `AGENTS.md` (Constraints, Conventions, Architecture), `docs/TECHNOLOGY_STACK.md`, `docs/SOURCES.md`, `docs/GLOSSARY.md`.

### Research protocol and strategy
- `docs/research/RESEARCH_PROTOCOL.md` (v2.1.0): section 1 splits, section 3 execution assumptions and exit ladder, section 4 gates G1 to G5 and holdout marker, section 5 parameter-registry linkage and identity tuple.
- `docs/research/holdout_consumed.json`, `docs/backtest/BACKTEST_SPEC.md`, `docs/strategy/` (family specs).
- `params/trend-pullback/`, `params/breakout-retest/`, `params/range-mr/` (the Phase 15 sets; all carry PLACEHOLDER keys; none may start paper).

### Paper, freeze and gate evidence
- `.planning/phases/15-strategy-geometry-correction/15-REVIEW-PAPER-GATE.md`, `15-REVIEW-PAPER-GATE-FIX.md`, `15-17-SUMMARY.md`, `15-CONTEXT.md`, `15-VERIFICATION.md` (D054 items (h), (i)).
- `.planning/phases/07-paper-forward-observation/07-VERIFICATION.md` (behavior_unverified_items), `07-REVIEW-FIX.md`, `07-CONTEXT.md`.
- `.planning/phases/14-backtest-causality-rewrite/14-CONTEXT.md`, `deferred-items.md` (OQ-1, D052 items), `.planning/phases/12-fee-cost-model-correctness/12-VERIFICATION.md` (max_cost_to_risk).
- `.planning/phases/10-journal-depth-kill-gate-operations/10-VERIFICATION.md` (WR-01, WR-06, WR-12, WR-13, lines about 188 to 196).
- `.planning/phases/13-research-data-foundation-fixes/13-UAT.md` (G3-026), `.planning/phases/11-decision-alignment/11-01-SUMMARY.md` (G3-027).
- `.github/workflows/paper_freeze_check.yml`, `tests/test_paper_parity.py`, `tests/test_paper_start_gate.py`.

### Persistence, deployment and operations
- `.planning/phases/17-operational-persistence-layer/17-CONTEXT.md`, `17-VERIFICATION.md` (stores, `execution_intents`, disposable PG test database).
- `.planning/phases/13.1-deployment-ci/13.1-OPEN-DECISIONS.md`, `13.1-CONTEXT.md`, `13.1-UAT.md` (UAT 8 to 10), D042, D050.
- `docs/operations/RUNBOOK.md` sections 7, 8, 11 (backup and restore), 13 (bootstrap), 15 (provider migration), 17; `docs/operations/SECURITY_AND_OPERATIONS.md`.
- `docker-compose.yml`, `Dockerfile`, `deploy/bootstrap.sh`, `deploy/migrate.sh`, `deploy/backup.sh`, `deploy/restore.sh`, `src/ops/backup_remote.py`, `.env.example`.
- `.planning/quick/261007-mkw-wr-05-d062-trading-user-joins-sudo-with-/` and `.planning/quick/261007-mv4-cr-01-parquet-push-checksum/` (WR-05 and CR-01; these directories exist in the main working tree, untracked, and were not visible in this worktree).

### Telegram, approvals, execution boundary
- `docs/trading/SIGNAL_AND_ALERTS.md`, `docs/trading/EXECUTION_SPEC.md`, `docs/trading/RISK_MANAGEMENT.md` (section 11 quantization, D031).
- `.planning/LIVE-TEST-2026-10-04.md` (WS probe findings, Telegram findings, owners).

## Inherited ROADMAP items and the decision that covers each

| Item | Covered by |
|------|-----------|
| G2-007 (interval per stream, backfill into feed_events, CONTEXT_BAR in GLOSSARY) | D-05 |
| G2-008 (parity cannot cover strategy-stage NO_TRADE) | L-02, D-20 |
| G4-010 (paper loop has no ledger) | D-17 |
| G2-009 (freeze workflow hard-coded set) | L-01, D-21 |
| G4-021 (no committed set can start paper; PLACEHOLDER keys) | L-05, O-04, O-13 |
| G4-018 (IN-01..IN-05, REGISTRY_ROOT bound once) | D-03 |
| G3-026 (one real data.binance.vision fetch in the smoke) | D-10 |
| D059-5 (runner, feasibility gate, candidate registration) | L-03, D-24 to D-28 |
| D052-open (`modeled_costs_per_unit`, runner calls `read_code_version` and `assemble`) | D-24, D-29, O-10 |
| T-01 (BKTS-03 plateau and sweep runner) | D-27 |
| G4-003 (research re-run, candidate freeze, window and split, universe, floor reachability, baseline-v6 PLACEHOLDER resolution) | D-26, D-28, O-02, O-03 |
| G3-027 (D043 trade-floor feasibility measured, never lowered) | D-26 |
| G3-012 (`max_cost_to_risk` 0.15 revisit only via new set) | D-30 |
| G4-009 (incremental feature series deferred, re-time without tracemalloc) | D-30 |
| OQ-1 | O-06 (open), D-29 (report only) |
| G2-038 / D061-F (kill-gate guard) | L-06, D-31 |
| D057 / D060 (G5 floor, protocol v2.1.0) | L-15, D-26 |
| D059-4 (OI collector no later than 2026-10-08) | L-14 (user commitment; OI gap on migration recorded in D-33) |
| D061-A | L-01, D-21, D-22, O-01 |
| D061-B | L-02, D-20 |
| D061-D | L-04, D-23, O-07 |
| D061-F | L-06, D-31 |
| D061-req (PAPER-03 not in this phase) | Domain section, L-10 |
| D061-J | L-10, O-02 to O-04, O-11 |
| D061-iso | L-11, D-32 |
| D061-open (still-open items) | O-01, O-02 to O-04 |
| D061-deploy | D-33 |
| D061-ec2 | L-11, D-34, O-12 |
| D062 (WR-05, CR-01) | Prerequisites section |
| G3-029 / WR-06 (mentioned in Phase 24; relevant to the paper env) | Prerequisites note, D-13 environment layer; the split itself stays Phase 24 |

Inherited items that could NOT be mapped to a decision: none. Two are mapped as "report or defer only": G4-009 (deferred, one timing step) and OQ-1 (open user decision).

<code_context>
## Existing Code Insights

CodeGraph note: no `.codegraph/` index exists in the worktree (the index is not committed). Orientation queries used the main tree's index read-only (`codegraph_explore` with `projectPath` on the main tree, at the same base commit 157ffc7 plus the other task's uncommitted work); every code fact below was cross-checked against the worktree files with Grep or Read. The planner should re-run `codegraph explore` after indexing the worktree, or read the files named here.

### Reusable Assets
- `src/adapters/paper_ws.py` `PaperWsAdapter` (line 116): wraps `DerivativesTradingUsdsFuturesWebSocketStreams`; `subscribe` registers `handle.on_message` and raises when absent; `connect` calls `create_connection` without awaiting; the interval goes through `_interval_to_enum`; default config has no `stream_url`. This is where SC2 and SC7 bugs (a) to (c) live.
- `src/paper/supervisor.py` `PaperSupervisor` and `WsAdapterLike` / `RestAdapterLike` protocols: subscribe all (symbol, interval) pairs, monotonic `_advance_last_close`, `on_disconnect`, `_resubscribe_and_backfill`, `_backfill_pairs`, journaled outage gaps (`data_class` `paper-<interval>`). Composition root is missing.
- `src/paper/resync.py` `backfill_missed_closes`: REST backfill with bounded retry, expected open times.
- `src/paper/loop.py` `run_paper_tick`: the gate, warm-up check (`check_feature_validity`), dedup (`seen_open_times`), feed gates, `CONTEXT_BAR`. No production caller exists yet.
- `src/paper/freeze.py`: `pin_stream_epoch`, `write_pinned_state`, `load_pinned_state`, `run_check_cli` (exit codes 0, 1, 2, 3), `PaperAllowlistEntry`, `PAPER_START_ALLOWLIST = ()` at line 402, `require_bool_flag`.
- `src/paper/journal.py` `assemble_paper_record`, `assemble_no_trade_record`, `paper_records_digest`; `src/paper/attribution.py` `AttributionKind` (`system`, `user-executed-sim`, `opportunity`) and `APPROVAL_DELAY_LAG_SECONDS`; `src/paper/notify.py` `notify_simulate` (journal-first, tenacity-bounded retry, `NotifyOutcome`).
- `src/adapters/telegram_notify.py` (`send_simulate`, `build_simulate_keyboard`, `build_approve_keyboard`, `build_skip_keyboard`, `format_approve`), `src/adapters/telegram_callbacks.py` (`parse_callback_data`, `authorized_chat_gate`, `dispatch_callback`, `on_callback`, `build_application`), `src/approval/` (`tokens`, `binding`, `mapping`, `replay`) with at-least-once replay semantics.
- `src/backtest/lifecycle.py` (`new_plan_state`, `advance`, `cancel_plan`, `finalize_at_data_end`), `entry.py`, `exits.py`, `costs.py`, `funding.py`, `ledger.py`, `engine.py` (`simulate`), `experiment.py` (`assemble`, `ExperimentRecord`), `report.py` (BKTS-03 gap at line 50): the Phase 14 fill semantics to call, not copy.
- `src/data/case_input.py` (`CaseInputData.to_case_input`), `src/data/collector.py`, `minute_source.py`, `backfill.py`: dataset and minute-bar sources for the runner and for live 1m bars.
- `src/persistence/` (`PgJournalStore.record`, approvals, `execution_state`, `system_state`, `uow`, `engine`) and `src/db`: Phase 17 stores to reuse for runtime state.
- `src/analytics/` (`killgate.py`, `render_killgate.py`, `cli.py`, `lifecycle.py`, `no_trade.py`, `approval_delay.py`, `live_outcomes.py`) and `src/adapters/analytics_files.py`: reporting inputs.
- `src/ops/` (`backup_remote.py`, `health.py`, `cutover.py`, `drills.py`, `redaction.py`) and `deploy/*.sh`: soak-host operations.
- `scripts/demo_rehearsal.py` evidence recorder (`EvidenceRecorder.write` with scrub and post-write secret scan): a pattern for the smoke evidence file and its redaction.

### Established Patterns
- Pure core (`src/core`) imports only stdlib and Decimal; SDK types never leave `src/adapters`; Decimal for all exchange-sensitive values.
- Fail closed: a refused or empty-allowlist state is a valid terminal state; no fallback parameter set; `require_bool_flag` for safety flags; AST guards over `src/` (`tests/test_paper_start_gate.py` pattern) for "no module enables the escape hatch".
- Parameter sets are hash-locked TOML with provenance labels; a behavior change is a new set and a new `strategy_version`.
- Determinism: injected clocks (`now_utc`), no wall-clock reads in pure paths, canonical JSON digests, byte-equivalent outputs.
- Journal-first before notify; at-least-once callbacks replay to existing state; no auto-approve on notification failure.
- PG tests use a disposable `_test` database and `TRADING_CI_STRICT=1` (missing infrastructure fails in CI).

### Integration Points
- New: `src/paper/runtime.py` (composition root and entrypoint), `src/research/` (runner), a SHADOW confirm module under `src/approval` or `src/paper`, a kill-gate guard registry beside `src/analytics/killgate.py`.
- Changed: `src/adapters/paper_ws.py`, `src/paper/supervisor.py` protocols (async), `src/paper/freeze.py` (CLI mode, entry validation), `src/paper/attribution.py` (measured delay), `docker-compose.yml` `paper` service, `.github/workflows/paper_freeze_check.yml`, `docs/GLOSSARY.md` (`CONTEXT_BAR`, SHADOW terms), `docs/operations/RUNBOOK.md` (soak host).
- Unchanged and protected: Phase 14 simulator semantics and hashes, protocol v2.1.0, the contents of `PAPER_START_ALLOWLIST`, every `params/` set already committed.

</code_context>

<specifics>
## Specific Ideas

- Verification gaps (nothing here was fetched or run on this machine; all facts below are repository facts unless marked):
  - No network call to Binance, Telegram, AWS or the web was attempted in this discuss pass, so there were no connection errors and nothing was retried.
  - The Binance WebSocket facts (connection lifetime, URL split, whether a mark-price kline stream exists for the 1m mark series) are NOT verified here; `docs/SOURCES.md` line 44 marks the 24-hour lifetime "not fetched". The WS handle API (`.on("message", cb)`, `RequestStreamHandle`, awaited `create_connection`) comes from the 2026-10-04 probe recorded in ROADMAP SC7 and is not re-verified live.
  - AWS, rclone, S3, EBS, GitHub Actions cache and artifact retention specifics are not verified; planner must cite official pages with read dates.
  - `.planning/quick/261007-mkw...` and `261007-mv4...` are untracked in the main tree and were not visible in this worktree, so their implementation state was not checked here.
  - CodeGraph index absent in the worktree (see `code_context`).
- Sanity of the label: the SHADOW text is exactly `SHADOW — no real order` (ROADMAP SC5).
- The trial soak, the long soak and the research runs are separate things: the trial soak (14 days) proves the runtime and the freeze chain; the long soak accumulates evidence for PAPER-03 (Phase 26); the research run produces a candidate registration, not evidence of an edge.
- Nothing in this phase starts paper, pins an epoch or authorizes a hash by itself. Every transition in the closure chain is an explicit user command.

</specifics>

<deferred>
## Deferred Ideas

- D055 execution model, Demo probe and the unprotected-position policy: Phases 18, 24, 25.
- Full Telegram hardening (user-id auth, working SKIP everywhere, money amounts, keyboard removal): Phase 23.
- User-data stream and error taxonomy (18), reconcile and SAFE_MODE hardening (20), equity and daily loss (21), leverage and margin (22), live runtime (24), Demo campaign (25), go-live gate and kill-gate WR fixes (26).
- WR-06 per-service `env_file` split: before any live key (Phase 24).
- Incremental feature series (G4-009) and TP1 far-half rule (Backlog 999.1), maker/post-only entries, container registry push and deploy-on-tag: deferred by their own decisions.
- Requirements re-map for BKTS-03 and the stale `ROADMAP.md` Phase 17 checkbox: requirements and bookkeeping batch.

</deferred>

---

*Phase: 16-Paper Runtime Composition + SHADOW Approval Mode*
*Context gathered: 2026-10-07*
