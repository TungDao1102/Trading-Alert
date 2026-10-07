# Phase 16: Paper Runtime Composition + SHADOW Approval Mode - Research

**Researched:** 2026-10-07
**Domain:** asyncio composition of an existing, fake-tested paper library layer (Binance USDⓈ-M WS + REST, PostgreSQL Phase 17 stores, Telegram approvals) into a runnable SHADOW process on a pinned-image Docker host; evidence tooling; research runner; kill-gate guard
**Confidence:** MEDIUM overall. In-repo code facts and installed-SDK facts: HIGH (files read this session). Binance docs: MEDIUM (WebFetch summaries of 2 pages; the kline-stream and REST-kline pages were unreadable, see Verification gaps). Telegram Bot API and AWS EC2/EBS/S3 encryption pages: not read (HTTP 403), so those facts are `[ASSUMED]`. Live-exchange behaviour of the SDK on the real host: unverified by design (SC7 is a blocking-human smoke).

**Machine note:** this research ran without committing anything, started no stream, called no Binance WS, Telegram or AWS endpoint. It read the worktree `C:/Users/admin/Music/Trading-phase16` (branch `plan/phase-16`, base `89bac3d`), the installed SDK in `C:/Users/admin/Music/Trading/.venv`, ran the 11 existing `tests/test_paper_*.py` files (157 tests, all passed, command `PYTHONPATH=. <venv python> -m pytest <file> -q -p no:cacheprovider`), one read-only public REST GET (`/fapi/v1/klines`) and one 20-line in-memory experiment against `backfill_missed_closes`.

<user_constraints>
## User Constraints (from CONTEXT.md)

Copied verbatim from `16-CONTEXT.md` (sections "Decisions", "Open user decisions", "Claude's Discretion", "Deferred Ideas"). The planner MUST honor these. Source order when they conflict: `docs/DECISIONS.md` > `docs/` > `AGENTS.md` > `.planning/` (D031).

### Locked Decisions

#### A. Locked from DECISIONS.md (copied, never altered; changing any needs the user)

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

#### B. Runtime composition (PAPER-01; SC1, SC2, SC7)

- **D-01:** The runnable process is a new module `src/paper/runtime.py` with a `python -m src.paper.runtime` entrypoint, an asyncio main that composes `PaperWsAdapter`, `PaperSupervisor`, the REST backfill adapter, the per-closed-bar tick, the journal sink and the SHADOW approval loop. The compose `paper` service replaces its placeholder command with this entrypoint and defines a real healthcheck (the placeholder disables the inherited collector HEALTHCHECK; D-06 of 13.1 says Phase 16 defines the probe). The runtime refuses to start when `PAPER_START_ALLOWLIST` admits nothing for the requested parameter set, logs `SKIPPED (allowlist empty)` and exits 0 without subscribing (L-05). — **Reversibility:** reversible.
- **D-02:** `run_paper_tick` is a stateless batch function (it takes warm-up bars plus `feed_events` and re-runs the gate every call, review IN-03). The runtime therefore owns the incremental state: warm-up buffers per (symbol, interval), the pinned epoch, dedup of seen open times, and per-restart warm-up from REST before the first evaluated bar (L-04). The runtime pins the epoch once at start (`pin_stream_epoch` then `write_pinned_state`), then calls a thin per-closed-bar wrapper that passes the already-pinned hash. It must not change `run_paper_tick` semantics or its digest on existing parity fixtures. — **Reversibility:** costly (many callers and tests rely on the current tick contract).
- **D-03:** Review IN-01..IN-05 (G4-018) are fixed here because this phase is the first production consumer: `PaperAllowlistEntry` gets `__post_init__` validation (64 lowercase hex, non-empty ids, ISO date for `approved_at`, non-empty `purpose` and `basis`); docstrings of `run_paper_tick`, the module and `_load_parameter_set_with_root` are corrected; the "stream-start gate" naming is aligned with what runs (a once-per-process gate in the runtime plus a per-call gate in the function); `REGISTRY_ROOT` is bound once (resolve at call time or pass the loaded set), with a test that gate and loop can never judge different files; test nits tightened. The earlier Phase 15 warnings (WR-01..WR-05 of `15-REVIEW-PAPER-GATE.md`) are checked against `15-REVIEW-PAPER-GATE-FIX.md` and anything still open is folded in. — **Reversibility:** reversible.
- **D-04:** Process state that must survive a restart (pinned epoch, last seen close per pair, open simulated positions, pending approvals) lives in the SOAK PostgreSQL through the Phase 17 stores (`PgJournalStore`, approvals, `system_state_events`), plus the `logs/paper/pinned_epoch.json` file for the freeze CLI. The paper journal sink writes through `PgJournalStore.record` (replay-idempotent, append-only). No second persistence mechanism is invented. — **Reversibility:** costly (schema consumers).
- **D-05:** Feed events: the WS callback runs on the SDK thread; the runtime hands closed events to the asyncio loop through a thread-safe queue (the supervisor already uses a lock for `_last_close`). Only `is_closed` events enter the tick (SC7: the stream also delivers open candles). `event["interval"]` is set per stream, REST-backfilled klines convert into the same `feed_events` path (G2-007), and `CONTEXT_BAR` is confirmed as a feed-gate reason code and added to `docs/GLOSSARY.md`. — **Reversibility:** reversible.
- **D-06:** Gaps: a bar closed while the process was down is recorded as a gap and produces no signal (L-11); backfill during warm-up may restore context bars (`CONTEXT_BAR`) but never evaluates a missed bar as a fresh signal. The runtime writes a `RUNTIME_START`, `RUNTIME_STOP` and `WS_DISCONNECT/RECONNECT` journal row so every gap is explainable (L-04).
- **D-07:** Runtime coverage and uptime (L-01, L-04): a heartbeat row per closed bar processed plus an expected-bar schedule derived from the interval grid; a small pure function computes "expected closed bars vs processed or explained-gap bars" over a window. It is evidence tooling that reports; the 95 percent figure is L-04. What counts as a "healthy feed" (silence limits) is OPEN (O-07).

#### C. WS adapter fix (SC2, SC7; F-125, F-607)

- **D-08:** `src/adapters/paper_ws.py` is fixed in the three places the 2026-10-04 live probe found: `await` the coroutines `create_connection` and `kline_candlestick_streams`; pass the plain string interval (`"1h"`, `"4h"`, `"1m"`) instead of the SDK interval Enum; set `stream_url` from the SDK PROD constant in the default `ConfigurationWebSocketStreams`. The handle exposes `.on("message", cb)` (no `on_message`), so dispatch registration changes accordingly. The adapter's methods that cross into the SDK become `async`; the supervisor's `WsAdapterLike` protocol follows. SDK types stay behind the adapter (domain boundary). — **Reversibility:** reversible.
- **D-09:** Fakes are contract-bound to the SDK's async signatures: a contract test introspects the installed SDK (`inspect.iscoroutinefunction`, parameter names and types of `create_connection`, `kline_candlestick_streams`, the handle's `.on`) and asserts the fake mirrors them, so a fake that is synchronous where the SDK is asynchronous fails CI (F-125, F-607). The test must run in CI without network.
- **D-10:** The live smoke (SC7) is a blocking-human step on the connected machine: run the runtime against mainnet public market data only (no key), observe `ws_subscribe` succeeding and at least one closed 1h or 4h event per subscribed interval reaching the supervisor (`soak_smoke.log` no longer reads `BLOCKED`), measurable acceptance recorded in a smoke evidence file. The 1m interval is used to prove the path quickly (a closed 1m candle arrives within about a minute); the 1h/4h closed events are proven by waiting a real bar close. One real fetch from data.binance.vision is observed in the same smoke (G3-026). Prerequisite: a network path that does not return 502 for the WS host (D061 G observed 502 through the proxy on 2026-10-07).
- **D-11:** The Binance WebSocket facts (URL split to `/public`, `/market`, `/private` of 2026-04, the 24-hour connection lifetime, reconnect behaviour) are re-read from the official pages by the planner/researcher with URL and date; `docs/SOURCES.md` line 44 records the 24-hour lifetime as "not fetched". Nothing is coded from memory.

#### D. SHADOW mode, simulated fills, approvals (PAPER-02; SC3, SC5, SC6)

- **D-12:** A `Mode` value (SHADOW first; DEMO and LIVE exist as names only) is carried by the runtime and printed in every Telegram message. SHADOW messages carry the exact label `SHADOW — no real order` (SC5, text from the ROADMAP). No other mode is constructible by the Phase 16 runtime.
- **D-13:** Hard isolation (SC6), three layers. (1) Structure: the SHADOW runtime module graph must not import `src.execution.manager`, `src.execution.placement` or the Binance order adapter methods (`src.adapters.binance_usdm` order functions); enforced by an AST/import test (pattern of `tests/test_paper_start_gate.py`). (2) Environment: the runtime constructs its config from an allowlist of variable names and the startup check refuses to run when any `BINANCE_LIVE_*` or `BINANCE_TESTNET_*` or other trade-capable key variable is present in the process environment. (3) Behavior: a test drives a full SHADOW confirm and proves with a spy that `execute_approved_plan` and every order endpoint call are unreachable, with a negative control that shows the spy would catch a call. The market-data adapter used by the paper runtime is the public-data one with no credentials.
- **D-14:** Simulated fills reuse Phase 14 semantics by calling the same lifecycle functions (`src/backtest/lifecycle.py` `new_plan_state` / `advance`, entry eligibility and touch rules in `src/backtest/entry.py`, exit ladder in `src/backtest/exits.py`, costs in `src/backtest/costs.py` and `funding.py`) on closed 1m trade bars and 1m mark-price bars from live data. They are called, not copied, so the semantics hash (`simulator_semantics_version`) stays authoritative; any need to modify the simulator stops the work and needs a new decision (L-02). The source of live 1m mark-price bars (REST `markPriceKlines` poll vs a WS stream) is a research item for the planner with a source URL and read date (`docs/SOURCES.md` already records the REST endpoint); recommendation is the REST poll through the existing `src/data` minute source because the semantics are already proven there. — **Reversibility:** costly (evidence comparability).
- **D-15:** Approval delay is measured, not a fixed 30 s: `APPROVAL_DELAY_LAG_SECONDS` in `src/paper/attribution.py` is replaced as the delay source by `acted_at_utc - requested_at_utc` from the approval row (and confirm timestamps); the constant stays only as a documented default for records with no human action. System vs user-executed-sim vs opportunity attribution (existing `AttributionKind`) is produced for every signal: APPROVE then CONFIRM gives `user-executed-sim`; SKIP, CANCEL and expiry give `opportunity` with the reason; plans nobody touched are `system` or `opportunity` per the existing PAPER-02 rule in `src/paper/attribution.py` (planner confirms against `07-CONTEXT.md`).
- **D-16:** SIMULATE buttons become functional in SHADOW (F-961): `send_simulate` and `build_simulate_keyboard` (`src/adapters/telegram_notify.py`) lead to the approval flow through the existing `dispatch_callback` / `on_callback` and `src/approval` replay (idempotent, at-least-once callbacks replay to existing state, no auto-approve on notification failure, `src/paper/notify.py` journal-first ordering). The CONFIRM card of L-13 is implemented for SHADOW in this phase as a minimal module reusable by Phase 23 (separate single-use confirm token, 60 s default TTL from D041, same plan hash, re-run pre-checks at confirm). Phase 23 extends it to money amounts, full user-id auth and keyboard removal; this phase uses the existing `authorized_chat_gate` and states plainly that user-id auth is Phase 23. The SHADOW approval expiry value is OPEN (O-08).
- **D-17:** A confirmed SHADOW plan opens a simulated position tracked by a minimal paper ledger built on `src/backtest/ledger.py`, so `open_positions` and `daily_loss_quote` inputs to the risk verdict come from simulated state (G4-010, D052 item (i)). The simulated account equity used for sizing is a sizing value and is OPEN (O-09).
- **D-18:** The journal reports system vs user vs opportunity outcomes through the existing analytics path (`src/analytics`, `src/adapters/analytics_files.py`): the plan extends the Phase 10 reporting inputs with the SHADOW records and adds no new metric definitions. The report states plainly that the soak evidence never feeds a value into trading logic.
- **D-19:** The labelled test signal (L-04): a CLI or runtime flag that injects exactly one clearly labelled test signal to exercise the chain once, marked `TEST_SIGNAL` in every record, excluded from every strategy count by the analytics reader, and requiring an explicit operator command at run time (blocking-human on the execution machine or EC2). It is never a strategy decision and never passes through the allowlist gate as strategy evidence.

#### E. Parity of the decision surface (L-02)

- **D-20:** A pure function `decision_surface(...)` over the shared `src/core` functions (features, `evaluate`, `plan`) and `src/risk` verdict produces, per closed bar, a record {bar, feature digest, signal or NO_TRADE reason, plan hash, risk verdict}. The paper loop emits it from live bars; a replay test feeds the same recorded closed bars through the same function and compares digests with tolerance zero. The Phase 14 simulator is not changed and its hashes do not move. Parity covers strategy-stage NO_TRADE and signal-less bars (G2-008) because the observer does not depend on the simulator emitting them. If a comparison against the backtest trades is needed, it is trade-level only and unchanged (`tests/test_paper_parity.py`). If this turns out impossible without a simulator change: stop and record a decision (L-02). — **Reversibility:** reversible.

#### F. Freeze check and evidence (L-01)

- **D-21:** `src/paper/freeze.py` CLI gains an allowlist-driven mode (`--from-allowlist`): with an empty allowlist it writes one `SKIPPED` line to `registry_diff.jsonl` (reason `allowlist empty`) and exits 0; it never prints CLEAN, never exits red, never falls back to any set. With an entry it checks that exact `strategy_id`/`parameter_set_id` and the pinned hash. `.github/workflows/paper_freeze_check.yml` drops the two hard-coded flags and uses the new mode. A test proves the empty-allowlist path and that no hard-coded id remains in the workflow. Exit-code semantics for the non-empty case stay as today (0 clean, 1 error, 2 missing pinned state, 3 rollover); a SKIPPED line written before the pin is expected and not counted against L-04.
- **D-22:** CLEAN ticks cannot prove the host ran (L-01), so the uptime and coverage measure (D-07) is a separate evidence artifact produced from the runtime's heartbeat rows. The workflow on GitHub runs against the repository checkout (registry files), not the host; the plan states that it proves registry immutability only. The durable export location is OPEN (O-01).
- **D-23:** The exit-criteria evaluator: one script computes each L-04 criterion from the exported evidence (window length, coverage fraction with the healthy-feed rule once ratified, consecutive CLEAN freeze lines from the pin, parity digests, gap explanations, restart warm-up checks, duplicate-signal and missing-journal-row checks) and prints PASS/FAIL per criterion with the evidence it read. It evaluates; it never changes a threshold; the values come from L-04 as constants with their D061 label.

#### G. Research runner (L-03; D059 item 5; BKTS-03)

- **D-24:** The research runner is a separate plan and a new module (recommended `src/research/` with a CLI `python -m src.research.run`), infrastructure only. It builds case input from the collected datasets (`src/data/case_input.py`), runs the Phase 14 `simulate` on a named parameter set, reads `read_code_version` and calls `experiment.assemble` (D052-open), and writes the experiment record. It never writes `PAPER_START_ALLOWLIST`, never ranks or selects, and prints no verdict. Its inputs (hypothesis, grid, run authorization) are files supplied by the user (O-02, O-03).
- **D-25:** The runner refuses to run without a user-written authorization artifact whose recorded grid hash equals the hash of the grid it is about to run (the separate user command of L-10). The runner implements the check; what the artifact says and when it is written are the user's (O-03).
- **D-26:** Feasibility and sample-size gate: a reporting step that counts closed trades pooled and per validation fold against the protocol floors (G1: 100 pooled and 30 per fold; G5: 30 in the holdout) and reports any shortfall (G3-027, D043). The floors are never lowered, nothing is ranked by the count, and a shortfall is a report, not a parameter change. It uses the G1 counting rule of D060 (closed filled trades with exit SL or TP2; `END_OF_DATA` counted apart).
- **D-27:** BKTS-03: the runner prints the parameter-plateau analysis the report currently leaves as `not computed (BKTS-03 pending)` (`src/backtest/report.py:50`), as reporting only, over the pre-registered grid. The REQUIREMENTS re-map stays with the requirements batch.
- **D-28:** Candidate registration: a registered candidate is a parameter-set TOML under `params/<family>/` with a complete rationale table (provenance label per value; never PLACEHOLDER), hashed by the registry loader, never edited in place; any change is a new set plus a new `strategy_version` (AGENTS.md conventions). Candidates come only from pre-registered values with a rationale, never from a backtest result (L-03, D059 item 5). The runner provides a validator ("structurally valid, rationalized, preregistered, no PLACEHOLDER, registered and hashed") and prints the exact 64-hex hash for the user to read. It does not edit the allowlist.
- **D-29:** `modeled_costs_per_unit` (None on v2 filled `TradeRecord`s) is surfaced as a documented limitation in the runner output; restoring it is OPEN (O-10). OQ-1 treatment of mark-hole trades is OPEN (O-06): the runner reports the count of trades held through mark-price holes, separately and unclassified, so the user decides with the real number.
- **D-30:** G4-009: before any incremental-feature change, the runner's first real run is timed once without tracemalloc; the incremental feature series stays deferred and any later change must be an exact-equivalence refactor (D052 item (h)). G3-012: `max_cost_to_risk` 0.15 is not touched; a revisit is a new parameter set chosen before any result is seen, user-owned (D046 item 6).

#### H. Kill-gate guard (L-06)

- **D-31:** A plan adds an enforced guard: the kill-gate report entrypoints (`src/analytics/killgate.py`, `render_killgate.py`, `src/analytics/cli.py` kill-gate path) refuse to conclude on real evidence while a registry of the four unresolved items (WR-01, WR-06, WR-12, WR-13) lists any as unresolved. The registry is a small versioned file listing each item with state `UNRESOLVED` until Phase 26 flips it with its fix commit; the guard reads it. An automated test proves the refusal on real-evidence input and the pass on synthetic/fixture input, and that flipping any one item back to UNRESOLVED blocks again. The guard changes no WR design; the WR designs stay open (H, Phase 26).

#### I. Deployment and operations on the soak host (L-11; D061-deploy, D061-ec2, D061-iso)

- **D-32:** One concrete tested configuration, a dedicated Compose project name (for example `trading-soak`) with its own PostgreSQL volume, distinct from the development stack and its test databases; the `paper` service runs from the digest-pinned image tag produced by CI, never from a working-tree bind mount; the `paper` service env lists no `BINANCE_*` trade key; the collector and the paper process run in the same Compose project on the host. A guard script and test refuse `docker compose ... down -v` against the soak project name (wrapper script plus a test that greps the RUNBOOK and scripts for an unguarded `down -v` against that project). Backups exist and a restore drill ran before the long soak starts (the existing backup chain, RUNBOOK section 11).
- **D-33:** Data path (D061-deploy): the plan defines the exact command that pulls the research data to the development machine over the existing backup chain (encrypted `pg_dump` plus append-only Parquet to a private S3 store, `deploy/restore.sh`, `src/ops/backup_remote.py`), the migration of the existing collector, Parquet store and database with `deploy/migrate.sh` (it reports Parquet fingerprints, watermarks and the OI gap), and the real-host checks of 13.1 UAT 8 to 10. These are blocking-human steps on the connected machine; the OI gap the switch causes is recorded as a coverage gap (L-14).
- **D-34:** EC2 provisioning (D061-ec2) is a blocking-human runbook on the connected machine with measurable acceptance for each D042 condition; facts about AWS and rclone and the distro come from the official docs or `docs/SOURCES.md`, never from memory, with URL and read date. The plan adds the runbook text; it does not create the host.
- **D-35:** Time: the host runs chrony and the runtime reads UTC only (strategy and tick use injected clocks; there is one runtime clock source) and logs a clock-skew check at start against a public time source; Telegram messages show UTC and Asia/Ho_Chi_Minh per the stack.

#### J. Plan decomposition (Claude's discretion for the planner; one phase, several plans, no 16.1)

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

### Open user decisions (NOT decided by auto mode; blocking-human checkpoints; no option selected, no agent may fill a default)

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

### Deferred Ideas (OUT OF SCOPE)

- D055 execution model, Demo probe and the unprotected-position policy: Phases 18, 24, 25.
- Full Telegram hardening (user-id auth, working SKIP everywhere, money amounts, keyboard removal): Phase 23.
- User-data stream and error taxonomy (18), reconcile and SAFE_MODE hardening (20), equity and daily loss (21), leverage and margin (22), live runtime (24), Demo campaign (25), go-live gate and kill-gate WR fixes (26).
- WR-06 per-service `env_file` split: before any live key (Phase 24).
- Incremental feature series (G4-009) and TP1 far-half rule (Backlog 999.1), maker/post-only entries, container registry push and deploy-on-tag: deferred by their own decisions.
- Requirements re-map for BKTS-03 and the stale `ROADMAP.md` Phase 17 checkbox: requirements and bookkeeping batch.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAPER-01 | Realtime paper engine ingests WS market data with warm-up/reconnect/resync, evaluates closed candles only, and journals gaps without fabricating signals (closes when ROADMAP criteria 1, 2 and 7 hold, D061 J) | The WS adapter and supervisor lifecycle do not match the installed SDK (section "WS adapter defects"); the runtime needs restored last-close state, REST warm-up with the 1000/300 engine windows, source-tagged backfill that can never evaluate, and a 1 ms off-by-one in `resync` found against real Binance close times (Pitfalls P1-P8). Criterion 7 can only be proven by a real run (section "Real versus fake proof"). |
| PAPER-02 | Paper loop records system vs user-executed vs opportunity attribution with signal/approve/order/fill timestamps (closes when criteria 3 and 5 hold) | `assemble_paper_record` hard-codes the 30 s lag and refuses a caller timestamp (`journal.py:229-243`); no production approval sender or binding resolver exists (only `scripts/demo_rehearsal.py`); `PaperRecord` has no mode/test-signal/confirm fields and analytics flags user-sim rows `synthetic_lag=True` (`lifecycle.py:200`); no PG-to-evidence-file exporter exists. The fill producer must be a small driver over public `lifecycle` / `ledger` functions (the engine's `_Engine` is private and batch). |
| BKTS-03 | Reports show trade counts and slices, R distribution, bootstrap intervals and parameter-plateau analysis (re-mapped to Phase 16, runner-owned; not on the ROADMAP Requirements line) | `src/backtest/report.py:50` `PLATEAU_NOTE = "not computed (BKTS-03 pending)"`; the runner is a new `src/research/` module; the G5 feasibility count must not run on the holdout block (Q-O below). |
</phase_requirements>

## Project Constraints (from AGENTS.md; no CLAUDE.md exists in the repository)

The planner must verify compliance with each directive (copied from `AGENTS.md`, Constraints and Conventions):

- Determinism: same market snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs.
- No-AI core: an LLM may assist code/docs/tests/explanations only; it never decides direction, entry, SL, TP, size, risk, parameters or signal validity.
- Exchange authority: Binance is canonical; dynamic exchangeInfo (stepSize/tick/notional); facts about Algo orders, position mode and the 200-conditional-order headroom are re-verified against current official docs before implementation, never hard-coded from memory.
- Quantization: floor to stepSize, reject below min quantity / min notional / `minimum_risk_utilization_after_rounding`; NO_TRADE preferred over round-up; identical logic backtest/paper/live (D031).
- Approval safety: explicit, auditable, idempotent, expiring; at-least-once Telegram callbacks replay to existing state; no auto-approve on notification failure; stale or invalid plans unapprovable.
- Fail closed: uncertain data/connection/account/risk gives NO_TRADE and no new orders.
- Tech stack: Python 3.13, asyncio, official Binance Python connector behind adapters, PostgreSQL operational + Parquet/DuckDB research, `Decimal` for all exchange-sensitive values, pytest + Ruff + mypy, Docker.
- Commands (the same ones CI runs): `uv sync --frozen --extra dev`, `uv run pytest -m "not docker"`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check`. Live-PostgreSQL tests need `TEST_DATABASE_URL` and skip without it. Ruff line length 100; mypy strict on `src`; pytest `asyncio_mode = "auto"`.
- Money-sensitive values use `Decimal`; the pure core (`src/core`) imports only stdlib and `Decimal`.
- Parameter sets are versioned, hash-locked TOML files: never edited in place; a behaviour change is a new set plus a new `strategy_version`. Every value carries a provenance label (STRUCTURAL, COST_GUARD, DECISION, EXPERIMENT or PLACEHOLDER); a value is never chosen or tuned from backtest results.
- Decisions live in `docs/DECISIONS.md`; conflict order DECISIONS.md > `docs/` > AGENTS.md > `.planning/` (D031).
- GSD workflow enforcement: file edits go through a GSD command. Project memory (user, private): tell spawned agents to run `codegraph explore` first; Binance/Telegram/internet errors get at most one retry, then report to the user (put this in every subagent prompt).

## Summary

Phase 16 is mostly composition and gap-closing around a library layer that has only ever been exercised with fakes. Reading the real SDK source showed that the fakes do not merely differ by `await`: the real `RequestStreamHandle` exposes only `on` and `unsubscribe`, so the project's `reconnect`, `close` and `schedule_reconnect` handle methods (and the supervisor's whole reconnect/rotation path built on them) have no counterpart. The SDK instead owns reconnection (a scheduled replacement of each connection every 23 hours, a 5 second `reconnect_delay`, a `serverShutdown` path) and reports it through `on_connection("open"|"reconnect"|"close"|"error", cb)`. An unsolicited close or error discards the connection and does NOT reconnect, leaving stale entries in a module-global stream map. The WS adapter therefore needs a lifecycle redesign on top of the three fixes named in CONTEXT, and the supervisor's backfill-after-reconnect must be driven by those connection events. The plan should de-risk this first with a small public-data smoke on the execution machine.

The second cluster is state and idempotency. `run_paper_tick` is stateless and re-pins an epoch with `opened_at_utc=now_utc` on every call (so `epoch_id` differs per call); its return value is dicts that lose the objects a fill driver needs (TradePlan, sized quantity, realized risk). The recommended seam is a byte-identical extraction of the per-bar body into a typed outcome that both the runtime and `decision_surface` consume. State that must survive restarts has no obvious home: `system_state_events` has a CHECK constraint that admits only `SAFE_MODE`, `LIVE_ENABLEMENT`, `KILL_GATE`, its values cannot be numbers, `PaperRecord` has no table, and nothing exports PG rows into the `analytics-evidence/2` file the Phase 10 reports read. No production approval sender or binding-context resolver exists (only an in-memory book inside `scripts/demo_rehearsal.py`), so the SHADOW approval loop is new construction, not wiring. Journal ids must be deterministic (bar-close keyed) for the "no duplicate, no missing row after restart" criterion to be provable.

The third cluster is where CONTEXT and the code disagree and a human must confirm before planning is final (listed as Q-A.. Q-O under Open Questions, none resolved here): fully rationalized sets never consult `PAPER_START_ALLOWLIST` in `pin_stream_epoch`, so the runtime needs its own exact-hash start gate if L-05 is to mean what it says; fill eligibility start (signal close vs confirm time) changes what "same fill semantics" means; the GitHub freeze check has no way to obtain the host's pinned epoch; scheduled workflows run only on the default branch and may drop hourly jobs; the G5 feasibility count must not touch the holdout block. All numeric thresholds stay open (O-07, O-08, O-09, O-12).

**Primary recommendation:** Build in this order: (1) WS adapter lifecycle on the real SDK shape plus contract-bound fakes plus a public-data smoke script run early on the execution machine; (2) byte-identical typed extraction of the per-bar tick and the `decision_surface` observer; (3) runtime state ports (restore last close, deterministic journal ids, gap/heartbeat rows) before composing the process; (4) SHADOW approval, fill driver and exporter on top; (5) research runner, kill-gate guard and freeze/evidence tooling in parallel; (6) deployment config last, and treat every fake-based result as non-closing for PAPER-01/02.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Market-data ingestion (WS klines, REST warm-up/backfill) | Adapter edge (`src/adapters/paper_ws.py`, `binance_usdm.py`) | Runtime (supervisor/queue) | SDK types must never leave adapters; runtime sees frozen `Kline` only |
| Closed-bar gating, dedup, windows, gap rows | Runtime state layer (`src/paper/runtime*`) | Pure tick (`src/paper/loop.py`) | The tick is stateless by design; incremental state belongs to the process |
| Strategy decision (features, evaluate, plan, risk verdict) | Pure core (`src/core`, `src/risk`) | none | Determinism; no I/O; shared with backtest |
| Simulated fills / ledger / funding | Pure backtest functions (`src/backtest/lifecycle.py`, `ledger.py`, `records.py`) driven by a thin SHADOW driver | Minute-bar source adapter (REST poll) | "Called, not copied"; semantics hash stays authoritative |
| Approval state, replay idempotency | PostgreSQL stores (`src/persistence/approvals.py`) + `src/approval` | Telegram adapter | Correctness comes from PG constraints, not Python |
| Telegram I/O (send, callbacks, edit message) | Adapter (`src/adapters/telegram_*.py`) | Runtime event loop | PTB confined to adapters |
| Journal / durable runtime state | PostgreSQL (`PgJournalStore`, UoW) | Evidence files (freeze CLI, exports) | Append-only, replay-idempotent |
| Freeze check / registry immutability proof | GitHub Actions (default branch checkout) | Host-side optional self-check | Proves registry files only, not host liveness |
| Uptime / coverage evidence | Runtime heartbeat rows + pure evaluator | Durable export location (O-01) | CLEAN ticks never prove the host ran |
| Process hosting, pinned image, backups | Docker Compose on EC2 (`deploy/`, `docker-compose.yml`) | S3 backup chain | Soak must be isolated from dev/test databases |
| Research runner / registration | Offline CLI (`src/research/`) | Registry gate in CI | Infrastructure only; never authorizes a candidate |

## Standard Stack

No new external package is required by this phase; everything below is already in `uv.lock`. Do not add numpy/scipy/pandas/FastAPI for Phase 16 (AGENTS.md "Installed State": none of them is installed; plateau and bootstrap code in `src/backtest/report.py` is pure stdlib/Decimal).

### Core
| Library | Version (uv.lock) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 | WS Streams + REST for public market data | Project rule: official SDK behind adapters. `[VERIFIED: uv.lock "version = \"17.4.0\""]` |
| `binance-common` | 4.4.0 (transitive) | WebSocket base classes, config, constants | Source of all WS lifecycle behaviour read below `[VERIFIED: uv.lock]` |
| `aiohttp` | 3.14.3 (transitive) | Transport under the SDK WS | `[VERIFIED: uv.lock]` |
| `python-telegram-bot` | 22.8 | Callback receive + send | `[VERIFIED: uv.lock]` |
| `SQLAlchemy` / `psycopg` / `alembic` | 2.0.54 / 3.3.6 / 1.20.0 | Sync PG stores (Phase 17) | `[VERIFIED: uv.lock]` |
| `tenacity` | 9.1.4 | Bounded retries | `[VERIFIED: uv.lock]` |
| `structlog` | 26.1.0 | Structured logs | `[VERIFIED: uv.lock]` |
| `pytest` / `pytest-asyncio` / `respx` | 9.1.1 / 1.4.0 / 0.23.1 | Tests (`asyncio_mode = "auto"`) | `[VERIFIED: uv.lock, pyproject.toml]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Project `PaperWsAdapter` wrapping the SDK | Raw `aiohttp` WS to `wss://fstream.binance.com/market/stream` | Allowed by AGENTS.md only where the SDK lacks an operation; the SDK covers kline streams, so no. Keep the SDK, but treat its lifecycle as the source of truth |
| SDK-owned rotation (23 h) | Project-owned 24 h rotation in the supervisor | Two rotation mechanisms would race (see Pitfall P3). Planner decision; research recommendation is one owner |

**Version drift (informational):** PyPI latest is `binance-sdk-derivatives-trading-usds-futures` 17.6.0 (released 2026-10-06; 17.4.1 2026-09-21, 17.5.0 2026-09-23) and `binance-common` 4.5.1, against 17.4.0 / 4.4.0 locked. `[VERIFIED: pypi.org JSON API, read 2026-10-07]`. The WS lifecycle facts in this document come from the LOCKED 17.4.0/4.4.0 source. Do not bump mid-phase (AGENTS.md: re-verify SDK on every bump); record the SDK and binance-common versions in the smoke evidence file.

**Installation:** none. `uv sync --frozen --extra dev` only.

## Package Legitimacy Audit

No package is added, so no `checkpoint:human-verify` install gate is required. For completeness the `gsd-tools query package-legitimacy check --ecosystem pypi` seam was run on 2026-10-07 for the four already-locked runtime packages:

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| python-telegram-bot | PyPI | latest 2026-06-12 | not returned by seam | python-telegram-bot.org | SUS (reason `unknown-downloads` only) | Already locked in `uv.lock`; no new install; seam lacks download data |
| binance-sdk-derivatives-trading-usds-futures | PyPI | latest 2026-10-06 | not returned | none in metadata | SUS (`too-new`, `unknown-downloads`, `no-repository`) | Already locked 17.4.0 and mandated by AGENTS.md; do NOT bump to the 2026-10-06 release in this phase |
| tenacity | PyPI | latest 2026-02-07 | not returned | github.com/jd/tenacity | SUS (`unknown-downloads`) | Already locked |
| structlog | PyPI | latest 2026-06-06 | not returned | none in metadata | SUS (`unknown-downloads`) | Already locked |

The SUS verdicts are artifacts of missing download counts in the seam, not findings about these packages; because nothing is installed in this phase the planner needs no install checkpoint. Packages removed due to SLOP: none. Flagged for install checkpoint: none (nothing installed).

## Existing Code Shape (what the runtime must compose)

All line references are the worktree files at base `89bac3d`, read 2026-10-07. Facts marked `[VERIFIED: path:lines]` were read with `Read` this session.

### Paper library layer (`src/paper/`, `src/adapters/paper_ws.py`)

| Module | Public surface | Facts the plan depends on |
|--------|----------------|----------------------------|
| `src/paper/loop.py` | `run_paper_tick(case_input, *, allow_unrationalized=False)` (`:312`), `check_feature_validity` (`:267`), `check_feed_freshness` (`:287`) | Stateless batch function over one `case_input` dict. Order: `require_bool_flag` (`:338`), gate (`:344-363`: `load_parameter_set`, version check, `pin_stream_epoch(... opened_at_utc=now_utc ...)`, hash equality), parse inputs (`:365-379`), per event `_is_closed_event` (`:412`), freshness (`:421`), warm-up reject (`:437`), 4h branch emitting `CONTEXT_BAR` (`:450-460`), dedup `DUPLICATE_BAR` (`:468-477`), `evaluate` (`:494`), `plan` (`:515`), `evaluate_risk` (`:540-556`), then a record `{"reason_code": "OK", "stage": "risk_passed", ...}` (`:571-579`) with the comment "tracer slice: no simulated fill yet". Returns only dicts: `signals`, `trade_plans`, `no_trade_records`, `feed_events_processed`, `feed_events_dropped` (`:581-587`). `_event_to_candle` accepts only `"1h"`/`"4h"` (`:241`). |
| constants | `STALENESS_THRESHOLD_SECONDS: int = 60` (`loop.py:175`), `WARMUP_MIN_BARS: int = 200` (`loop.py:181`) | Implementation values, not ratified (O-07). |
| `src/paper/freeze.py` | `StreamEpoch` (`:95`), `DiffLogEntry` (`:146`), `pin_stream_epoch` (`:484`), `check_registry_unchanged` (`:581`), `write_pinned_state`/`load_pinned_state` (`:697`, `:716`), `run_check_cli` (`:742`), `_cli_main` (`:805`), `PaperAllowlistEntry` (`:375`), `PAPER_START_ALLOWLIST: tuple[PaperAllowlistEntry, ...] = ()` (`:402`), `_require_allowlisted` (`:422`), `_require_rationalized` (`:450`) | `epoch_id` is `sha256` over (ids, hash, `opened_at_utc`) (`:256-278`), so every `run_paper_tick` call mints a different epoch. `DiffLogEntry.__post_init__` accepts only `("clean", "REGISTRY_DIFF")` (`:165-166`), so a `SKIPPED` line needs a new line shape. The allowlist is consulted only when the set has NO `rationale` tables (`:460-466`); a rationalized set returns at `:467-476` without reading the allowlist (see Q-A). The CLI requires `--strategy-id`, `--parameter-set-id`, `--diff-log` (`:828-841`). |
| `src/paper/supervisor.py` | `PaperSupervisor` (`:98`), `WsAdapterLike` (`:63-77`, sync methods), `RestAdapterLike` (`:80-90`) | `start()` is sync and never calls a connect (`:159-185`); `_on_kline` drops `is_closed=False` and non-advancing closes (`:187-208`); `on_disconnect` awaits `_resubscribe_and_backfill(...)` and DISCARDS its `(backfilled, outage_gaps)` return (`:235`); gaps are only logged (`:386-403`), nothing journals them; `_reconnect_with_retry` calls `self._ws.reconnect(handle)` (`:259`); `_last_close` starts empty so a cold start backfills nothing and logs `no_last_close` (`:350-363`); `record_close(...)` (`:132`) is the public seeding path. Constants `SUPERVISOR_MAX_ATTEMPTS: int = 7`, `SUPERVISOR_MAX_DELAY_SECONDS: int = 120`, `SUPERVISOR_WAIT_MAX_SECONDS: int = 60` (`:52-55`). |
| `src/paper/resync.py` | `backfill_missed_closes` (`:134`) | Pages `adapter.klines` from `ms(last_close_utc)`, drops forming bars, diffs expected slots. Expected slots start AT `last_close_utc` and step by the interval (`:122-123`), which is wrong by 1 ms against real Binance close times (Pitfall P1). Constants `RESYNC_MAX_ATTEMPTS: int = 7`, `RESYNC_MAX_DELAY_SECONDS: int = 120` (`:45-46`). |
| `src/paper/journal.py` | `assemble_paper_record` (`:162`), `assemble_no_trade_record` (`:379`), `paper_records_digest` (`:425`), `PaperRecord` (`:59`) | Filled-in-simulation case ignores any real approval time: acted_at = `signal_detected_at_utc + timedelta(seconds=APPROVAL_DELAY_LAG_SECONDS)` (`:229-231`) and raises if the caller's `approval["acted_at_utc"]` differs (`:235-243`). `PaperRecord` has 15 fields, no mode, no test-signal flag, no confirm timestamps. |
| `src/paper/attribution.py` | `AttributionKind`, `APPROVAL_DELAY_LAG_SECONDS: int = 30` (`:51`) | Also imported by `src/analytics/approval_delay.py` and `provenance.py`, which label paper delay `SYNTHETIC LAG`. |
| `src/paper/notify.py` | `format_simulate`, `notify_simulate` (journal-first, tenacity), constants `NOTIFY_MAX_ATTEMPTS: int = 3` (`:111`) | Uses `build_simulate_keyboard` whose callback prefixes are the inert `SIM:` / `SKIP:` (`src/adapters/telegram_notify.py:94-132`). |
| `src/adapters/paper_ws.py` | `PaperWsAdapter` (`:116`), `Kline` (`:47`) | See "WS adapter defects" below. |
| `src/adapters/binance_usdm.py` | `BinanceUsdmAdapter` (`:650`) with `klines` (`:664`), `mark_klines` (`:694`), `exchange_info` (`:838`), `server_time` (`:824`), `funding_rate` (`:777`) AND order methods `place_entry` (`:1195`), `place_algo_protective` (`:1262`), `cancel_*` | One class mixes public market data and order placement, so D-13 layer 1 cannot simply forbid importing the module (the supervisor already imports `Kline` from it, `supervisor.py:38`). Constructor builds `DerivativesTradingUsdsFutures()` with no credentials by default (`:659-660`). |

### Phase 14 pieces the SHADOW fill driver composes (public API only)

| Module | Callable | Facts |
|--------|----------|-------|
| `src/backtest/lifecycle.py` | `new_plan_state` (`:186`), `advance` (`:454`), `cancel_plan` (`:620`), `finalize_at_data_end` (`:640`) | `advance(state, *, source: MinuteSource, start_exclusive, end_inclusive, bar)` is pure and window-parameterized ("the same input gives the same output", docstring `:1-41`); `start_exclusive` is clamped to at least `state.signal_close_utc` (`:485`), so a LATER start (confirm time) is expressible without changing the simulator. |
| `src/backtest/series.py` | `MinuteSource` protocol (`:37-51`), `ListMinuteSource` (`:110`) | Both methods return minutes whose close lies in `(start_exclusive, end_inclusive]`. `ListMinuteSource` validates whole series at construction and raises for an unknown symbol. |
| `src/data/minute_source.py` | `ParquetMinuteSource` | Reads PUBLISHED per-day Parquet partitions only (docstring: "lazy Parquet-backed"); it is not a live source. CONTEXT D-14 says "REST poll through the existing `src/data` minute source": the REST poll must feed a new in-memory `MinuteSource` (validated through `validate_minute_series`, `series.py:67`), not `ParquetMinuteSource`. |
| `src/backtest/ledger.py` | `Ledger.start` (`:~73`), `apply_booking` (`:172`), `register_exposure` (`:246`), `update_exposure` (`:281`), `remove_exposure` (`:312`), `open_positions_for_risk` (`:321`), `daily_loss_quote` (`:201`) | Pure value object; `Ledger.start(equity=...)` needs the O-09 equity. |
| `src/backtest/records.py` | `booking_for_event` (`:199`), `Booking` (`:131`) | Converts lifecycle events to ledger bookings (costs from the cost model). |
| `src/backtest/engine.py` | `simulate` (`:867`), private `_Engine._size_and_register` (`:734-833`) | The per-plan sizing sequence is: `select_constraints` (point in time) then `risk_fn(...)` (`:747-761`) then `fill_quantity = floor_to_step(planned * partial_fill_fraction)`, `protective_levels_for_fill`, `new_plan_state`, `register_exposure` (`:813-830`). This is private and batch; a SHADOW driver must re-express the same calls in order (see Pattern 5) rather than import `_Engine`. Windows: `STRATEGY_WINDOW_BARS = 1000`, `CONTEXT_WINDOW_BARS = 300` (`semantics.py:48-49`, applied at `engine.py:695-702`); one active plan per symbol, label `NO_TRADE_CONFLICT = "CONFLICT_WITH_OPEN_POSITION"` (`semantics.py:80`). |

### Phase 17 stores the runtime writes through

| Store | Facts |
|-------|-------|
| `PgJournalStore.record(event)` (`src/persistence/journal.py:85`), `.append(tx, event)` (`:90`) | Sync SQLAlchemy `Session`; `ON CONFLICT (journal_event_id) DO NOTHING` then compares identity fields and payload, excluding `occurred_at_utc`/`created_at_utc` (`:51-64`); different content under an existing id raises `JournalConflict`; a missing parent row raises `ParentRowMissing` (insert parents first in the same unit of work). |
| `PgTradingEntityStore.insert_signal` / `insert_trade_plan` (`src/persistence/entities.py:309`, `:346`) | Replay of identical content is a no-op, different content is `RowConflict` (`:235-266`). This makes "no duplicate signal after restart" provable for deterministic `signal_id`s. |
| `PgApprovalStore` (`src/persistence/approvals.py:88`) | `insert_pending`, `save_atomic`, `lookup_by_token_hash`, `lookup_by_short_id`; one decided approval per plan enforced by `uq_approvals_one_decided_per_plan`. |
| `PgSystemStateStore` (`src/persistence/system_state.py:136`) | Key CHECK `"state_key IN ('SAFE_MODE', 'LIVE_ENABLEMENT', 'KILL_GATE')"` (`src/db/models.py:883`), state values only `str | bool | None` (`system_state.py:84-97`). Paper runtime state does not fit without a migration (Q-J). |
| `OperationalDatabase.transaction()` (`src/persistence/uow.py`), `make_sync_engine` (`engine.py`) | Sync engine; bounded waits (`DEFAULT_STATEMENT_TIMEOUT_MS = 10_000`, `DEFAULT_POOL_TIMEOUT_S = 5`, `DEFAULT_CONNECT_TIMEOUT_S = 3`, `DEFAULT_LOCK_TIMEOUT_MS = 5000`). Every call blocks the event loop up to those bounds. |

### Telegram and approval pieces

- `dispatch_callback` (`src/adapters/telegram_callbacks.py:244-488`) is synchronous, takes `binding_context` with `plan_hash`, `strategy_version`, `parameter_set_id`, `parameter_set_hash`, `expiry_utc` and a `raw_token` (`:349-376`, `:431`); `on_callback` (`:627-722`) takes a `binding_context_resolver(short_id)` that must return the raw token (`:697-700`). `authorized_chat_gate` compares chat ids only (`:183-196`). A `SIM:`/`SKIP:` press resolves to `SIMULATE_RECORDED` and never advances approval state (`:319-328`).
- No production code issues the one-time token, inserts the PENDING approval or implements the resolver: `grep` over `src` and `scripts` finds `issue_one_time_token` and `binding_context_resolver` only in `src/approval/tokens.py`, `telegram_callbacks.py` and the in-memory book of `scripts/demo_rehearsal.py:927-955`. The raw token is never persisted (`src/approval/tokens.py:25-37`), so a process restart loses every pending approval's token.
- `build_application` (`:735-768`) builds a PTB `Application`; PTB documents the manual lifecycle for running beside other asyncio code: `initialize()`, `start()`, `updater.start_polling()`, then `updater.stop()`, `stop()`, `shutdown()` in that order `[CITED: python-telegram-bot wiki "Frequently requested design patterns" via Context7 /python-telegram-bot/python-telegram-bot, read 2026-10-07]`.

### Deployment pieces

- `docker-compose.yml`: `name: trading` (`:14`), shared `env_file: ${TRADING_ENV_FILE:-.env}` for every `x-app` service (`:18`), `paper` is a placeholder with `restart: "no"` and `healthcheck: disable` (`:101-110`), image tag `trading-alert:${IMAGE_TAG:-dev}` built on the host by `db-upgrade` (`:17`); there is no registry push (deferred, D050; STATE "Open user decisions").
- `Dockerfile` pins `python:3.13.15-slim-bookworm@sha256:...`; runtime user UID 10001; `HEALTHCHECK` probes the collector.
- WR-05 status: implemented on `develop` in commit `7148528` (`fix(deploy): trading user joins sudo with a password (D062 WR-05)`) but NOT in this worktree; CR-01 is NOT implemented anywhere as of 2026-10-07 (`src/ops/backup_remote.py:334` still passes `"--size-only"` in both trees). `[VERIFIED: git log and grep in both trees]`

## WS Adapter Defects (F-125, F-607) and the SDK Signatures to Bind Fakes To

Source of truth: installed `binance_common` 4.4.0 and `binance-sdk-derivatives-trading-usds-futures` 17.4.0 under `C:/Users/admin/Music/Trading/.venv/Lib/site-packages`, read 2026-10-07 (the uv cache was not needed).

### Introspected signatures (verbatim output of `inspect.signature` / `iscoroutinefunction`, 2026-10-07)

```text
DerivativesTradingUsdsFuturesWebSocketStreams kline_candlestick_streams coroutine= True (self, symbol: Optional[str], interval: Optional[...KlineCandlestickStreamsIntervalEnum], id: Optional[str] = None) -> binance_common.websocket.RequestStreamHandle
DerivativesTradingUsdsFuturesWebSocketStreams create_connection coroutine= True (self)
DerivativesTradingUsdsFuturesWebSocketStreams close_connection coroutine= True (self, connection: ...WebSocketConnection = None, close_session: bool = True)
DerivativesTradingUsdsFuturesWebSocketStreams on_connection coroutine= False (self, event: str, callback: Callable[..., NoneType], connection: Union[...WebSocketConnection, str, int, NoneType] = None) -> None
DerivativesTradingUsdsFuturesWebSocketStreams subscribe coroutine= True (self, streams, response_model: Optional[~T] = None, stream_url: Optional[str] = None)
DerivativesTradingUsdsFuturesWebSocketStreams unsubscribe coroutine= True (self, streams)
RequestStreamHandle on coroutine= False (self, event: str, callback: Callable[[~T], NoneType]) -> None
RequestStreamHandle unsubscribe coroutine= True (self) -> None
WebSocketCommon reconnect coroutine= True (self, connection, configuration, close_old_connection: bool = True)
WebSocketCommon schedule_reconnect coroutine= True (self, connection, configuration, delay: int, close_old_connection: bool = True)
RequestStreamHandle public members: ['on', 'unsubscribe']
ConfigurationWebSocketStreams.__init__(self, stream_url: Optional[str] = None, reconnect_delay: int = 5000, reconnect_attempts: int = 3, compression: int = 0, proxy=None, mode: WebsocketMode = <WebsocketMode.SINGLE: 'single'>, pool_size: int = 2, time_unit=None, https_agent=None)
PROD wss://fstream.binance.com   AUTO_RECONNECT 82800
```

`PROD` is `DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL = "wss://fstream.binance.com"` (`binance_common/constants.py:76`); `AUTO_RECONNECT_INTERVAL_SECONDS = 23 * 3600` (`constants.py:16`); `DEFAULT_RECONNECT_ATTEMPTS = 3`, `MAX_RECONNECT_ATTEMPTS = 10`, `SUBSCRIBE_MESSAGE_DELAY_SECONDS = 0.5` (`:17-19`); `SUPPORTED_CONNECTION_EVENTS = {"open", "ping", "pong", "reconnect", "close", "error"}` (`:20`).

### The three defects CONTEXT names, confirmed against the installed source

| # | Defect in `src/adapters/paper_ws.py` | Evidence |
|---|--------------------------------------|----------|
| (a) | `connect()` calls `factory()` without `await` (`:225-228`) and `subscribe()` calls `self._ws.kline_candlestick_streams(...)` without `await` (`:160-164`) | Both SDK methods are coroutine functions (table above). The returned object is a coroutine, not a handle. |
| (b) | `subscribe()` passes the SDK interval Enum (`:159`, `_INTERVAL_TO_ENUM` `:276-291`) | `ws_streams_placeholder` builds the stream name with `str(v[nf])` for every non-symbol parameter (`binance_common/utils.py:690-710`); `KlineCandlestickStreamsIntervalEnum` is a plain `Enum` (not `str, Enum`), so `str()` yields `KlineCandlestickStreamsIntervalEnum.INTERVAL_1m`, an invalid stream name. A plain string `"1h"` yields `btcusdt@kline_1h`. (The 3.13 formatting is stated in ROADMAP SC7; the `str(v[nf])` mechanism is read in the source. Not re-run live.) |
| (c) | `ConfigurationWebSocketStreams()` has no `stream_url` (`:138`) | `WebSocketStreamBase.__init__` only appends `/stream` when a `stream_url` is set (`websocket.py:1085-1086`); `create_connection` passes `self.configuration.stream_url` (`:1090-1099`). With `None` the connect path fails inside `connect()`, whose `except Exception` swallows it (see D4). |

### Further defects found by reading the SDK (not in CONTEXT; the plan must absorb them)

| # | Finding | Evidence | Consequence |
|---|---------|----------|-------------|
| D1 | The handle has only `on` and `unsubscribe`. `reconnect`, `close`, `schedule_reconnect` and `on_message` do not exist on it | introspection above; `websocket.py:1610-1645` | `PaperWsAdapter.reconnect/close/schedule_reconnect` always raise `RuntimeError` against the real SDK; the supervisor's `_reconnect_with_retry` (`supervisor.py:245-263`) exhausts 7 attempts or 120 s and `_close_all_handles` (`:425-453`) swallows a failed close while clearing the handle list, leaving the real subscription alive; the following `start()` then re-subscribes (a second callback on the same stream). `tests/test_paper_ws_connect.py` and `tests/test_paper_supervisor_backfill.py` pin the fictional API (fakes with `on_message`, `reconnect`, `close`). |
| D2 | The SDK owns reconnection. Every connection gets a task that replaces it in place after 23 h (`init_connection`: `schedule_reconnect(..., AUTO_RECONNECT_INTERVAL_SECONDS)`, `websocket.py:196-270`); a `serverShutdown` event schedules a reconnect after 5 s (`:296-307`); `reconnect()` (`:773-921`) closes the old socket BEFORE opening the new one, waits `reconnect_delay` (default 5000 ms) and re-sends SUBSCRIBE for streams mapped to the old connection (`:951-988`), copying `connection_callback_map` to the new connection (`:908-911`) | source | Each rotation leaves a gap of at least `reconnect_delay` in which no kline can arrive. A bar that closes inside that gap is missed on WS and must be recovered by REST. The runtime learns about it only through `ws.on_connection("reconnect" \| "open" \| "close" \| "error", cb)`. |
| D3 | An unsolicited WS CLOSE or ERROR message calls `_emit_close_event` and `_discard_connection` and ends the receive loop; it does not reconnect (`websocket.py:397-418`, `:465-490`). `_discard_connection` does not call `_forget_connection_streams` (only a user-initiated `_close_one` and a failed reconnect do, `:1043-1066`, `:895-898`) | source | After an unsolicited drop the stream names stay in the module-global `global_stream_connections` map pointing at the dead connection; `WebSocketStreamBase.subscribe` filters out every stream already in that map (`:1101-1154`), so a later `subscribe` of the same streams silently sends nothing. `close_connection()` with an empty connection list only logs "No WebSocket connections to close" (`:1019-1041`) and does not clean the map. Recovery path is UNVERIFIED and must be proven by a forced-disconnect step in the live smoke (Pitfall P4). |
| D4 | `WebSocketCommon.connect` wraps everything in `except Exception as e: logging.error(...)` and returns `None` on failure (`:160-194`, handler at `:193`). `create_connection` therefore does not raise on a failed connect | source | The adapter must check `ws.connections` is non-empty after `await create_connection()`; the SDK reports through stdlib `logging`, not structlog, so a log handler must be configured or the failure is invisible. |
| D5 | `create_connection` opens one connection per path in `url_paths=["market", "public", "private"]` (`websocket_streams.py:57`, `websocket.py:177-183`), each with its own 23 h timer. Kline streams use `stream_url="market"` (`streams/market_api.py:552-565`). Whether Binance accepts an unauthenticated `/private/stream` connection was not verified (the 2026-10-04 probe received klines, per ROADMAP SC7) | source | Three sockets per client; the `private` one is unused by this phase. |
| D6 | Callbacks are invoked synchronously inside the SDK `receive_loop` coroutine on the event loop that created the connection (`websocket.py:349-384`, `callback(parsed)` at `:360` and `:380`), NOT on a separate SDK thread. Server PING frames are answered inside the same loop (`autoping=False` for stream connections at `:254`, PING branch `:388-396`) | source | Corrects CONTEXT D-05 ("WS callback runs on the SDK thread; thread-safe queue"): `asyncio.Queue.put_nowait` from the callback is safe, the supervisor's `threading.Lock` is not needed for the WS path, and a blocking callback (DB write, tick compute) stalls the receive loop and the pong replies. Exceptions in a callback are caught by the SDK and emitted as a connection `error` event (`:384`). |
| D7 | `global_stream_connections` is a module-level dict shared by all client instances (`websocket.py:39-40`) | source | Tests that construct more than one real client in a process leak state between tests; contract tests must not instantiate connected clients, and any behavioural test must reset the map. |
| D8 | The callback payload for a kline is a Pydantic `KlineCandlestickStreamsResponse` (`e`, `E`, `s`, `k`), not the `{stream, data}` envelope, because the stream is registered with `response_model=KlineCandlestickStreamsResponse` (`market_api.py:560-565`; `websocket.py:349-362`); `to_dict()` uses `exclude_none=True` (`kline_candlestick_streams_response_k.py:93-118`). `_extract_kline_payload` (`paper_ws.py:333-356`) already handles `k`-keyed dicts via `_as_dict`, so the normalisation path survives the fix; keep a test with a real model instance. | source | Fake events should be built from the SDK model classes, not hand-written dicts. |
| D9 | The installed SDK has no WS mark-price KLINE stream: `market_api.py` exposes `mark_price_stream` (mark price updates) and `mark_price_stream_for_all_market` but no `markPriceKline` method (`grep "async def "` over `streams/market_api.py`, 16 methods) | source | The 1m mark series for SHADOW fills must come from REST `markPriceKlines` (`BinanceUsdmAdapter.mark_klines`, `:694`) or be derived from mark-price ticks (a project-built bar, a semantic risk). Whether the exchange offers such a stream outside the SDK was not verified. |

### Binance documentation facts (official pages, WebFetch summaries, read 2026-10-07, NOT verified live)

- Connection lifetime: "A single connection is only valid for 24 hours; expect to be disconnected at the 24 hour mark". `[CITED: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Connect]` This closes the `docs/SOURCES.md:44` "not fetched" gap at MEDIUM confidence (summary produced by the fetch tool; the page text itself was returned for this sentence in two separate fetches).
- Ping/pong: "The websocket server will send a `ping frame` every 3 minutes. If the websocket server does not receive a `pong frame` back from the connection within a 10 minute period, the connection will be disconnected." Limits: 10 incoming messages per second per connection (over the limit: disconnect, repeat offenders may be banned); 1024 streams per connection; all symbols lowercase. `[CITED: same Connect page]`
- Endpoints: `wss://fstream.binance.com/public` (high-frequency data), `/market` (regular market data), `/private` (user data); connections without a routed path receive only `/public` data. `[CITED: .../websocket-market-streams/Connect and .../Important-WebSocket-Change-Notice]`. The notice page lists klines on the `market` endpoint and states "Legacy URLs will remain available until 2026-04-23"; that date has passed, so legacy `/ws` URLs are retired (consistent with `docs/SOURCES.md:41`).
- Klines "push updates to the current klines/candlestick every 250 milliseconds" `[VERIFIED: installed SDK docstring, websocket_streams.py:436-443]`.
- Real kline close time is open + interval − 1 ms: a live public `GET https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2` on 2026-10-07 returned `[1791360000000,...,1791363599999,...]` (open 1791360000000, close 1791363599999). `[VERIFIED: live REST observation, 2026-10-07; not a docs page]`
- REST klines weight table (limit [1,100) → 1, [100,500) → 2, [500,1000] → 5, > 1000 → 10) and "Klines are uniquely identified by their open time" `[VERIFIED: installed SDK docstring, rest_api/api/market_data_api.py:667-700]`; `markPriceKlines` weights and 1500 max `[CITED: docs/SOURCES.md:65, read earlier by a prior session]`.

## Architecture Patterns

### System Architecture Diagram

```text
 Binance fstream /market (public, no key)           Binance fapi REST (public, no key)
        │ kline 1h/4h/1m (x=true once per bar)              │ klines, markPriceKlines, exchangeInfo, fundingRate, time
        ▼                                                   ▼
┌─────────────────────────┐  connection events   ┌──────────────────────────┐
│ PaperWsAdapter (async)   │──open/reconnect/────▶│ REST adapter (public     │
│ create_connection,       │  close/error         │ methods only)            │
│ kline_candlestick_streams│                      └──────────┬───────────────┘
│ handle.on("message")     │                                 │ warm-up (last 1000 / 300 closed bars),
└───────────┬─────────────┘                                 │ backfill, 1m poll for confirmed plans
            │ callback on the loop thread: ONLY queue.put_nowait(Kline)
            ▼                                                ▼
   ┌──────────────────────────────  Runtime (asyncio main, src/paper/runtime.py)  ──────────────────────────────┐
   │ start gate: env allowlist → SKIPPED if allowlist admits nothing → pin epoch once → restore state from PG     │
   │ closed-bar consumer: dedup (symbol,interval,open) → group by close time (4h before 1h) → source tag LIVE      │
   │                                BACKFILL/WARMUP bars → history buffers only, never evaluated                   │
   │ per-bar: tick (typed outcome) ─► decision_surface digest ─► journal sink (deterministic ids, parents first)   │
   │   signal+plan+risk OK ─► SHADOW approval loop ─► Telegram SIMULATE/APPROVE ─► CONFIRM card (60 s token)      │
   │   CONFIRMED ─► fill driver: lifecycle.advance over live 1m trade+mark minutes, ledger, funding ─► bookings    │
   │ heartbeat row per processed bar; RUNTIME_START/STOP; WS_DISCONNECT/RECONNECT; gap rows with reason           │
   └───────┬───────────────────────────────┬───────────────────────────────┬───────────────────────────────────┘
           ▼                               ▼                               ▼
   Soak PostgreSQL (Phase 17 stores)   logs/paper/pinned_epoch.json   Telegram (send, long-poll callbacks)
   journal_events, signals, plans,     (freeze CLI input)             one poller per bot token
   approvals, (state, Q-J)                     │
           │                                   ▼
           ▼                      Evidence export (O-01) ◄── GitHub Actions hourly freeze check (default branch,
   Backup chain (pg.dump + Parquet → S3)                    registry files only; SKIPPED while allowlist empty)
           ▼
   Exit-criteria evaluator (pure): coverage, CLEAN streak, parity digests, gap explanations, restart checks
```

### Recommended Project Structure (names are Claude's discretion per CONTEXT)

```text
src/
├── adapters/paper_ws.py          # async SDK-shaped lifecycle + connection-event hooks (rewrite)
├── paper/
│   ├── runtime.py                # asyncio composition root + __main__ (new)
│   ├── runtime_state.py          # restore/persist ports: last close, epoch, gaps, heartbeats (new)
│   ├── bars.py                   # warm-up buffers, windows 1000/300, source tags, ordering (new, pure)
│   ├── surface.py                # decision_surface observer (new, pure)
│   ├── shadow.py                 # Mode, SHADOW labels, confirm token + card, approval loop (new)
│   ├── shadow_fill.py            # live minute source + fill driver over lifecycle/ledger (new)
│   └── coverage.py               # expected-vs-processed bars, exit-criteria evaluator (new, pure)
├── research/                     # runner, feasibility, plateau, registration validator (new, offline)
└── analytics/killgate_guard.py   # + versioned registry file for WR-01/06/12/13 (new)
```

### Pattern 1: SDK-shaped async adapter with connection events
**What:** one `async connect()` that builds `ConfigurationWebSocketStreams(stream_url=<PROD constant>)`, awaits `create_connection()`, then FAILS if `ws.connections` is empty (D4); `async subscribe(symbol, interval_str, on_kline)` awaits `kline_candlestick_streams(symbol, "1h")` and calls `handle.on("message", cb)` with a callback that only normalises and enqueues; `async unsubscribe(handle)` awaits `handle.unsubscribe()`; `async close()` awaits `ws.close_connection()`; `on_connection(event, cb)` registered after connect for `open`, `reconnect`, `close`, `error` (the SDK copies connection callbacks to the replacement connection, `websocket.py:908-911`).
**When to use:** always; this replaces the `hasattr` guards that hid D1.
**Example (illustrative; values `[VERIFIED]` above, the structure is the planner's to confirm):**
```python
# Source: installed SDK signatures (see introspection block); not run against a live socket.
config = ConfigurationWebSocketStreams(stream_url=DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL)
ws = DerivativesTradingUsdsFuturesWebSocketStreams(config)
await ws.create_connection()
if not ws.connections:            # D4: the SDK swallowed a failed connect
    raise ConnectionError("WS connect produced no connection")
handle = await ws.kline_candlestick_streams(symbol="btcusdt", interval="1h")  # plain str, not the Enum
handle.on("message", lambda msg: queue.put_nowait(normalise(msg)))           # runs on the loop thread (D6)
ws.on_connection("reconnect", on_ws_reconnect)   # also "open", "close", "error"
```

### Pattern 2: Loop-thread dispatch with a bounded asyncio queue
The WS callback only enqueues; one consumer task drains, groups by close time and runs the tick in `asyncio.to_thread` (or an executor). DB calls (`PgJournalStore.record`, approvals) go through one small port so the Phase 24 decision G4-040 (`asyncio.to_thread` vs async pool) is not pre-empted: the port can wrap `to_thread` locally without declaring that decision made.

### Pattern 3: Deterministic runtime journal ids
Use `correlated_event_id(prefix, correlation_id, event_type, entity_id, step)` (`src/domain/journal.py`, a pure function with no clock) with correlation id `"paper:<epoch_id>:<symbol>:<interval>:<close_ms>"`, or `content_hash_event_id` with `occurred_at_utc` set to the BAR CLOSE (not `datetime.now`). `content_hash_event_id` hashes `occurred_at_utc.isoformat()` into the id (`domain/journal.py:40-48`), so a retry after a crash with a new wall-clock stamp would insert a second row and break "no duplicate, no missing journal row".

### Pattern 4: Byte-identical extraction of the per-bar body
Extract lines `:462-579` of `run_paper_tick` into a function returning a typed result (closed candle, `setup_result`, `plan_result`, `verdict` with `sized`, reason, stage), and have `run_paper_tick` project that result into exactly the same dict as today. Consumers: the runtime (needs `TradePlan` object, `verdict.sized.quantity`, `realized_risk`, none of which survive in the dict) and `decision_surface`. Proof of byte-identity: the pinned digests in `tests/test_paper_start_gate.py:_clean_run_digest` and `tests/test_paper_parity.py` must be unchanged. Alternatively keep `run_paper_tick` untouched and add a sibling function that re-uses the same helpers; either way D-02's "must not change its digest" is checkable.

### Pattern 5: Fill driver as a re-expression of `_size_and_register` + `advance`
Per confirmed plan: build `risk_fn` inputs from the ledger (`open_positions_for_risk`, `daily_loss_quote`), call `evaluate_risk` (already done by the tick), `fill_quantity = floor_to_step(planned * cost_model.partial_fill_fraction)`, `protective_levels_for_fill`, `new_plan_state`, `register_exposure`; then on each closed 1m minute `advance(state, source, start_exclusive, end_inclusive, bar)`, book events with `booking_for_event`, `apply_booking`, and funding via `funding.funding_events`. State is rebuilt after a restart by replaying `advance` over REST-fetched 1m history from the persisted (plan, quantity, eligibility start), which works because `advance` is pure and window-parameterized. This avoids a bespoke `PlanState` serializer, but REST history for the outage window may contain holes (the lifecycle annotates them in `coverage_note`).

### Pattern 6: Source-tagged bars
Tag every bar `LIVE_WS`, `REST_WARMUP` or `REST_BACKFILL`. Only `LIVE_WS` bars that satisfy the closed-bar gate may reach `evaluate`; the other two only extend history buffers and gap accounting. This implements L-11 structurally and does not depend on the unratified 60 s freshness constant (Pitfall P2).

### Pattern 7: Runtime start gate separate from the per-call pin gate
`pin_stream_epoch` stays as is; the runtime adds its own exact-hash admission check (strategy id, parameter set id, 64-hex hash equal to the entry) before subscribing, logs `SKIPPED (allowlist empty)` and exits 0 when no entry matches (Q-A).

### Anti-Patterns to Avoid
- **Keeping fakes that expose `on_message`, `reconnect`, `close`:** they pass CI while the SDK has none of them (D1).
- **Evaluating any bar not received live over WS:** a REST-sourced bar younger than 60 s passes `check_feed_freshness`.
- **Using the `epoch` returned by `run_paper_tick`'s internal pin:** a new `epoch_id` per call.
- **Calling `PgJournalStore.record` from the SDK callback:** blocks the receive loop and pong replies.
- **Importing `_Engine` or copying engine code into the fill driver:** private and batch; copying breaks "called, not copied".
- **Counting trades on the holdout window in the feasibility gate (Q-O).**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Plan fill/exit/funding semantics | A second fill model in the paper tree | `lifecycle.new_plan_state/advance`, `exits`, `funding`, `records.booking_for_event`, `ledger` | Semantics hash `2.0.0` and evidence comparability; L-02 |
| Approval idempotency / single decision per plan | An in-process "seen callbacks" set | `PgApprovalStore.save_atomic` + `resolve_callback` (PG constraint `uq_approvals_one_decided_per_plan`) | Correctness must survive restarts and races (Phase 17 D-17) |
| Canonical hashing, ids | New hash helpers | `src/domain/canonical.sha256_hex`, `content_hash_event_id`, `correlated_event_id`, `derive_short_id` | Byte-stable ids |
| Token issue/compare | Custom RNG or `==` | `issue_one_time_token`, `token_hash_of`, `verify_token_hash` (`secrets`, `hmac.compare_digest`) | Constant-time compare |
| Retry/backoff | `while True: sleep` | `tenacity` (`AsyncRetrying`) as in `resync.py`, `notify.py` | Bounded, jittered; fail closed |
| WS reconnect/rotation | A parallel project-owned 24 h timer | SDK `reconnect` + `on_connection` events | Two owners race (P3) |
| Registry hashing/validation of candidates | Ad-hoc TOML hashing in the runner | `src/domain/registry` loaders, `rationale.check_rationale`, `verify_parameter_set`, and the `tests/fixtures/phase4/parameters.json` pin file used by `registry-gate.yml` | The CI gate re-hashes every `params/**/*.toml` against that file |
| Telegram polling loop | A custom `getUpdates` loop | PTB `Application` manual lifecycle | Offset handling, shutdown order |
| Container down-volume guard | Documentation only | A wrapper script plus a test | Operator error is the failure mode |
| Redaction of secrets in evidence files | New scrubbers | `src/ops/redaction.py` and the `EvidenceRecorder` pattern in `scripts/demo_rehearsal.py` | Already post-write scanned |

**Key insight:** every difficult part of this phase already exists as a pure, tested function; what is missing is the stateful glue, and the glue's correctness properties (idempotency after restart, no late signals, no duplicate rows) are exactly what fakes cannot prove on their own.

## Common Pitfalls

### Pitfall P1: One-millisecond phantom gaps in REST backfill
**What goes wrong:** with real Binance bars (close = open + interval − 1 ms) `backfill_missed_closes` returns the closes AND one `exchange_returned_no_candle_for_expected_close` gap per bar. **Evidence:** a fake adapter returning three 1h bars shaped like the real REST rows, `last_close_utc = 12:59:59.999`, produced `3 3` (3 closes, 3 gaps, all that reason) on 2026-10-07; cause: `_expected_open_times` starts at `last_close_utc` (`resync.py:122-123`) while real open times are on the hour. The existing fixtures use close = open + step exactly (`tests/test_paper_resync.py`), so the suite cannot see it. **Why it matters:** L-04 requires every gap to be explained and none unexplained; phantom gaps make the evaluator meaningless. **How to avoid:** anchor expected slots on open times (`last_open + interval`), add a test with real-shaped 1 ms-short closes, and pin the shape from the live observation above. This is a bug fix in `src/paper/resync.py`, not a semantics change. **Warning sign:** gap rows appear in the journal for every reconnect even when bars were returned.

### Pitfall P2: The 60 s freshness gate does not implement L-11
`STALENESS_THRESHOLD_SECONDS: int = 60` rejects bars older than 60 s only. A process down 12:59:50 to 13:00:20 that warms up from REST would receive the 12:00 bar (closed 12:59:59.999) 20 s old, pass `check_feed_freshness`, and evaluate it as a fresh signal, contradicting L-11 ("bars that closed while the process was down never produce signals"). Use source tags (Pattern 6) so the rule does not depend on an unratified number (O-07).

### Pitfall P3: Two rotation owners
The SDK replaces each connection every 23 h (constants above) while `PaperSupervisor.on_disconnect(scheduled=True)` models a 24 h rotation by close, backfill, resubscribe. If both run, the project closes handles that do not exist (D1) and re-subscribes streams the SDK already re-subscribed (callbacks duplicate: `RequestStreamHandle.on` appends, `websocket.py:1195-1215`). Pick one owner. Research recommendation (a design choice, not a user decision): the SDK owns rotation and the supervisor reacts to `reconnect`/`open`/`close`/`error` events with a REST verification backfill.

### Pitfall P4: Dead subscription after an unsolicited close
D3 above. Evidence is source reading only. Acceptance for the live smoke must include a deliberate drop (for example brief network cut or killing the socket) and a proof that closed events resume and the gap row is journaled; otherwise PAPER-01 criterion 7 is not demonstrated for the failure path.

### Pitfall P5: `create_connection` failure is silent
D4. Without a post-call `connections` check and a stdlib-logging handler the process looks healthy with no stream; the healthcheck must be tied to "last closed bar processed" age, not to process liveness.

### Pitfall P6: 1h/4h ordering at 4h boundaries
At 00, 04, 08, 12, 16, 20 UTC a 1h and a 4h bar close at the same instant (both `T` end in `:59:59.999`). `run_paper_tick` evaluates a 1h event with context bars whose `close_time_utc <= closed_candle.close_time_utc` (`loop.py:483-485`), and the engine uses `bisect_right` on the same boundary (`engine.py:700-702`), so the backtest includes the simultaneous 4h bar. The tick sees it only if the 4h event precedes the 1h event in the same `feed_events` call or was appended to the 4h history earlier. WS arrival order across two streams is not deterministic. The runtime must process events grouped by close time with 4h before 1h, and decide how long to wait for the sibling event (a collection window is a timing number; ask in O-07 or derive from "the 4h bar is due at this boundary, wait for it or REST-fetch it").

### Pitfall P7: Window mismatch breaks tolerance-zero parity
The engine feeds `evaluate` the trailing `STRATEGY_WINDOW_BARS = 1000` setup bars and `CONTEXT_WINDOW_BARS = 300` context bars (`semantics.py:48-49`, `engine.py:695-702`); `run_paper_tick` uses whatever lists it is given (`loop.py:374-387`, no trailing cut). EMA-type features depend on history length, so a runtime buffer longer or shorter than 1000/300 can change a decision. Keep the runtime buffers exactly the engine's windows (a documented constant import from `src.backtest.semantics`, which `src/paper/loop.py` already imports from `src.backtest`), and state it in the decision-surface test.

### Pitfall P8: Cold start and restart with an empty `_last_close`
`PaperSupervisor._last_close` is empty at construction (`supervisor.py:125`), `_backfill_pairs` then skips every pair with a logged `no_last_close` (`:350-363`). A restarted process would neither see the downtime gap nor dedup. Restore last-close from durable rows and seed through `record_close` (`:132`) before subscribing; compute the downtime gap as expected closes between the restored last close and the warm-up snapshot time, journal it with a reason `PROCESS_DOWN`, and append those bars to history only.

### Pitfall P9: `on_disconnect` throws away the backfill
`await self._resubscribe_and_backfill(...)` returns `(backfilled, outage_gaps)` and `on_disconnect` ignores both (`supervisor.py:235`); gaps are only `log.warning`ed (`:386-403`). The composition root needs an injected sink (`on_backfill`, `on_gap`) or `on_disconnect` must return them; otherwise there is nothing to journal and the L-04 "gap explained" criterion cannot be evidenced.

### Pitfall P10: Event-loop blocking
The Phase 17 stores are synchronous with up to 10 s statement timeouts (`engine.py` constants), `dispatch_callback` is synchronous and called from an async PTB handler, and the tick computes features over up to 1000 bars per symbol (`G4-009` deferral). The SDK callback and PTB handler share the loop with the WS receive loop. Do DB and tick work off-loop (`asyncio.to_thread`), keep callbacks to `put_nowait`, and keep ONE port so G4-040 (Phase 24) stays open.

### Pitfall P11: Non-deterministic journal ids produce duplicates after a crash
See Pattern 3. Also insert parents before children in one unit of work (`ParentRowMissing`, `journal.py:107-112`): signal row, plan row, approval row, then journal events that reference them.

### Pitfall P12: Where durable runtime state lives (Q-J)
`system_state_events` is constrained to three keys by a database CHECK (`models.py:883`) and to string/bool values, so "last seen close per pair" and "pinned epoch" cannot be stored there without a migration and a new `SystemStateKey`. `PaperRecord` has no table. D-04's "no second persistence mechanism" can be met by journal events alone (restore = read the latest `BAR_PROCESSED`/`EPOCH_PINNED` events by correlation id), which needs no schema change but needs a "latest per key" read path; the alternative is migration `0005` with ORM parity tests. Present both to the user/planner.

### Pitfall P13: Approvals cannot survive a restart as built
The raw approval token exists only in process memory (tokens are hashed on storage, `tokens.py:25-37`; the resolver returns `raw_token` from memory, `telegram_callbacks.py:697-700`). After a restart every PENDING approval's callback fails closed (`INVALIDATED`). Options (not selected): treat pending approvals as expired on restart and journal `EXPIRED` with reason `RUNTIME_RESTART`; or derive the raw token deterministically from a persisted secret and the approval id (a design change to Phase 8 token semantics, needs a decision). The default fail-closed option needs no new design.

### Pitfall P14: The SIMULATE keyboard is inert and the approval flow has no sender
`build_simulate_keyboard` builds `SIM:`/`SKIP:` buttons labelled "SIMULATE-recorded" and "SKIP (Phase 8)" (`telegram_notify.py:94-132`); a press resolves to `SIMULATE_RECORDED` (`telegram_callbacks.py:319-328`). F-961 "SIMULATE buttons are functional" requires a SHADOW message that carries `APR:`/`SKP:` buttons backed by a PENDING approval row, a short-id mapping and an in-memory token, none of which a production module creates today.

### Pitfall P15: Records and analytics assume a synthetic lag
`_normalize_paper_group` hard-sets `synthetic_lag = True` for every user-executed paper row (`src/analytics/lifecycle.py:200`) and `approval_delay.py`/`provenance.py` print `SYNTHETIC LAG (APPROVAL_DELAY_LAG_SECONDS=30)`. A measured delay needs an explicit marker on the record (new field or a distinct evidence kind) and the loader `_load_paper_record` builds `PaperRecord(**fields)` (`analytics_files.py:683-698`), so adding a field changes the evidence-file schema and `paper_records_digest` pins in `tests/test_paper_attribution.py`. There is also no PG-to-evidence-file exporter: PAPER evidence is read from an `analytics-evidence/2` JSON file, LIVE from PG (`analytics_store.read_live_rows`). D-18's "no new metric definitions" holds only if the exporter maps SHADOW rows onto existing fields.

### Pitfall P16: D-13 layer 1 cannot ban the module
Because `BinanceUsdmAdapter` carries both market-data and order methods, an import-graph test that bans `src.adapters.binance_usdm` fails on the supervisor's own import. Options: split the market-data methods into a separate class/module and ban the order class; or ban attribute use (AST: calls to `place_entry`, `place_algo_protective`, `cancel_normal_order`, `cancel_algo_order` and any import of `src.execution.*`) over the runtime's transitive module set.

### Pitfall P17: Telegram is single-consumer per bot token
Long polling with one token from two places (the execution machine and EC2) conflicts. `[ASSUMED]` (Bot API pages returned HTTP 403; see Verification gaps). Use separate bot tokens or never run both pollers.

### Pitfall P18: The GitHub hourly check cannot see the host's pin
`paper_freeze_check.yml` restores `logs/paper` from the Actions cache and calls the CLI with a hard-coded id pair (`:77-90`); the pinned state file is written by `write_pinned_state` on the HOST under `logs/paper/pinned_epoch.json` (a Docker volume) and nothing carries it to the runner. Facts: scheduled workflows run only on the default branch's latest commit; the schedule "can be delayed ... High load times include the start of every hour ... some queued jobs may be dropped" (the cron is `0 * * * *`, exactly the loaded minute); caches unused for over 7 days are removed, default 10 GB per repository, cache contents are immutable (new key per save, as the workflow does); artifacts and logs are kept 90 days by default; the repository is private. `[CITED: docs.github.com events-that-trigger-workflows, dependency-caching, remove-workflow-artifacts, read 2026-10-07; not verified live]` Consequences: (1) how the runner learns the pinned epoch is an open design question (Q-F); (2) a dropped hourly job leaves no line, which L-04's "CLEAN on every tick" wording does not cover (Q-E); (3) the workflow change must land on the default branch (`master`) while development runs on `develop`.

### Pitfall P19: Compose and image provenance
`name: trading` is fixed in the compose file (`:14`), so a second isolated project needs `-p`/`COMPOSE_PROJECT_NAME` (RUNBOOK 13.6 says the deploy scripts honour both); the `down -v` guard must resolve the effective project name from all three sources. Every `x-app` service shares one `env_file`, so the paper container would also receive any `BACKUP_*` secrets present in `.env` (WR-06 split stays Phase 24). D-32's "digest-pinned image tag produced by CI" has no producer: CI pushes no image (D050; `ci.yml` header). The achievable pin is an image built on the host at a recorded commit with the image id recorded by `deploy/update.sh` into `.deploy/last-good.env` (RUNBOOK 14.2); whether that satisfies "pinned" is Q-I.

### Pitfall P20: Clock skew silently drops closed events
`_is_closed_event` drops an event whose `T` is later than the tick's `now_utc` (`loop.py:227`) and counts it under `feed_events_dropped`; a host clock behind by more than the arrival latency discards valid bars with no NO_TRADE row. chrony offset is checked only at bootstrap (`RUNBOOK 13.4`, `--max-drift-ms` default 100). The runtime should journal the tick's `now_utc` and dropped-event counts, and log a skew measurement at start (`BinanceUsdmAdapter.server_time`, `binance_usdm.py:824`, is a public option).

### Pitfall P21: The feasibility gate and the single-use holdout
Protocol v2.1.0: G5 evaluates the final 20 percent block "exactly once, after G1-G4 pass, with parameters frozen" and a candidate that ran on it is consumed (`docs/research/RESEARCH_PROTOCOL.md` G5, line 244; v2.1.0 amendment line 35). D-26 asks the runner to report the G5 floor (30 in the holdout). Simulating the holdout window to count trades is running the candidate on the holdout. See Q-O.

### Pitfall P22: Candidate "registered and hashed" is a CI-gated repository change
`registry-gate.yml` re-hashes every `params/**/*.toml` against the pin list `tests/fixtures/phase4/parameters.json` (`{"parameter_sets": [...]}`) and fails a TOML without a pin ("no pinned hash — register it"). The runner's validator and the user's registration commit must include that pin entry; the allowlist entry (O-04) is a separate later user commit.

### Pitfall P23: New modules and the guard lists
`tests/test_domain_no_float.py` scans an explicit file list (`:57-67` lists `src/paper/__init__.py`, `loop.py`, `attribution.py`, `journal.py`, `freeze.py`, `notify.py`, `src/adapters/paper_ws.py`); new money/time modules must be added by hand. `src/paper/__init__.py` states the package imports no SDK/SQLAlchemy; a runtime module with PG ports belongs outside the pure barrel (do not re-export it from `__init__`).

## Code Examples

### Contract test skeleton binding fakes to the installed SDK (network-free)
```python
# Source: introspection output above (iscoroutinefunction / signature). Names are proposals.
import inspect
from binance_common.websocket import RequestStreamHandle
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams as Sdk,
)

def _params(fn):  # parameter names without self
    return [p for p in inspect.signature(fn).parameters if p != "self"]

def test_fake_client_mirrors_sdk_async_surface(fake_client):
    for name in ("create_connection", "kline_candlestick_streams", "close_connection"):
        assert inspect.iscoroutinefunction(getattr(Sdk, name))
        assert inspect.iscoroutinefunction(getattr(fake_client, name)), name   # fails for a sync fake
    assert _params(fake_client.kline_candlestick_streams) == _params(Sdk.kline_candlestick_streams)
    assert not inspect.iscoroutinefunction(RequestStreamHandle.on)
    assert not hasattr(fake_client_handle(), "on_message")   # the real handle has none
```
A meta-test must prove the negative control: a deliberately synchronous fake makes `test_fake_client_mirrors_sdk_async_surface` fail.

### Deterministic bar journal event (sketch)
```python
# Source: src/domain/journal.py correlated_event_id signature (read); event_type names are proposals.
event = JournalEvent(
    journal_event_id=correlated_event_id(prefix="paper", correlation_id=f"{epoch_id}:{symbol}:{interval}:{close_ms}",
                                         event_type="PAPER_BAR_PROCESSED", entity_id=f"{symbol}:{interval}", step="v1"),
    occurred_at_utc=bar_close_utc,            # the bar close, never datetime.now()
    event_type="PAPER_BAR_PROCESSED", entity_type="PaperBar", entity_id=f"{symbol}:{interval}",
    correlation_id=f"{epoch_id}:{symbol}:{interval}:{close_ms}", payload_json=canonical_payload)
```

### Real-shaped fixture rows for backfill tests
```python
# Source: live GET /fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2, 2026-10-07 (prices are exchange data).
ROW0 = [1791360000000, "84094.70", "84139.20", "83902.50", "83909.90", "5844.590", 1791363599999, "490868445.00560", 179437, "2473.352", "207729461.40190", "0"]
ROW1 = [1791363600000, "83909.90", "83965.50", "83603.00", "83749.00", "7821.908", 1791367199999, "655296503.76730", 125134, "3519.234", "294835835.39980", "0"]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single legacy `wss://fstream.binance.com/ws` | Routed `/public`, `/market`, `/private`; unmigrated connections get `/public` only | legacy URLs available until 2026-04-23 `[CITED]` | Klines are on `/market`; the SDK routes via `stream_url="market"` |
| Sync project fakes (`on_message`, `reconnect`) | SDK async `RequestStreamHandle.on/unsubscribe`, client `on_connection`, SDK-owned reconnect | SDK 17.x / binance-common 4.x | Adapter and supervisor lifecycle redesign |
| 24 h rotation modelled by the project | SDK rotation every 23 h | binance-common constant | Design one owner |
| `binance-sdk-...` 17.4.0 locked | 17.6.0 / binance-common 4.5.1 on PyPI (2026-10-06) | after lock | Do not bump mid-phase; re-verify lifecycle facts on any bump |

**Deprecated/outdated:** `PaperWsAdapter.reconnect/close/schedule_reconnect` (no SDK counterpart); the "tracer slice: no simulated fill yet" `risk_passed` record (`loop.py:569-579`); the `SKIP (Phase 8)` button label.

## Supplementary Research (coordinator request of 2026-10-07; research only, nothing decided)

### S1. GitHub Actions scheduled workflows (the hourly freeze check)

Source pages (WebFetch summaries, read 2026-10-07, not verified live): `[CITED: docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows]`, `[CITED: docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows]`, `[CITED: docs.github.com/en/rest/actions/workflow-runs]`, `[CITED: docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching]`, `[CITED: docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository]`.

| Topic | Documented fact | Consequence for the freeze check |
|-------|-----------------|----------------------------------|
| Syntax and floor | POSIX cron, five fields; "The shortest interval you can run scheduled workflows is once every 5 minutes." | Hourly is allowed. The repo cron is `0 * * * *` (`.github/workflows/paper_freeze_check.yml`, `on.schedule`). |
| Branch | "Scheduled workflows will only run on the default branch"; `GITHUB_SHA` is the "Last commit on default branch", `GITHUB_REF` the "Default branch" | The workflow edit for D-21 must be on `master`; development is on `develop`. A tick checks master's registry files at that moment, not the host's image. |
| Delay | "The `schedule` event can be delayed during periods of high loads of GitHub Actions workflow runs. High load times include the start of every hour. If the load is sufficiently high enough, some queued jobs may be dropped." No numeric bound on delay is documented in the fetched text | A tick can be late (a line exists but `checked_at_utc` is later than the nominal slot) or missing (no run, no line). The fetched documentation gives no delay figure, so a "late versus missing" grace period is a number the user must own (it behaves like an O-07 freshness threshold). `0 * * * *` is the documented high-load minute. |
| Auto-disable | "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days"; also disabled by default in forks. Re-enable: Actions tab "Enable workflow" or `gh workflow enable WORKFLOW`. | This repository is PRIVATE (`gh repo view`: `"visibility":"PRIVATE"`, 2026-10-07), so the documented inactivity rule is stated for public repositories only. The fetched pages say nothing about private-repository auto-disable; treat "not applicable" as `[ASSUMED]` (A7). If the repository ever becomes public the 60-day rule applies and a quiet soak could silently stop its own freeze checks. |
| Identifying a scheduled run | `github.event_name == 'schedule'` and `github.event.schedule` (the cron string that fired). REST: `GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs` with query `event`, `status`, `created` (date-time range), `head_sha`, `per_page` (max 100, default 30); run objects carry `created_at`, `run_started_at`, `event`, `run_attempt`. | The workflow can stamp every line with `GITHUB_RUN_ID`, the `event.schedule` value and `run_started_at`. A manual `workflow_dispatch` run has `event` = `workflow_dispatch` and must not be counted as a scheduled tick. |
| Caches | Entries not accessed for over 7 days are removed (default retention 7 days; configurable up to 365 days for private repositories); default repository limit 10 GB, configurable; contents immutable (new key to change); a run cannot restore caches of child or sibling branches | The cache is operational state (L-01). A hiatus of more than 7 days (disabled workflow, dropped ticks) loses the cached pinned state and the next tick would exit 2 (missing pinned state). |
| Artifacts, logs, run records | Default retention 90 days; configurable 1 to 90 days for public and 1 to 400 days for private repositories; "Starting October 1, 2026, these policies will apply to checks, workflow runs, and commit statuses in addition to artifacts and logs" | The `registry-diff-<run_id>` artifact and, from 2026-10-01, the run records themselves expire after the retention period (90 days unless changed), so the API evidence that a tick existed also expires. A 14-day trial fits inside the default; the long soak does not, so the durable export (O-01) must copy run metadata too. |

**Missing ticks, designed so they can never read as CLEAN (input to the plan; nothing selected).**
- A workflow that did not run cannot write its own absence. The only writer of a missing-tick record is an external reconciler, which is naturally the exit-criteria evaluator (D-23): it generates the expected hourly slot grid from the pin time to the window end, then looks each slot up in (a) the `registry_diff.jsonl` lines (matching `checked_at_utc` within a grace) and (b) the Actions API run list (`event=schedule`, `created` range). A slot with neither is emitted as an `EVIDENCE_GAP` record with fields such as `slot_utc`, `schedule` (the cron string), `reason` (`NO_RUN_FOUND`, `RUN_LATE_BEYOND_GRACE`, `RUN_WITHOUT_LINE`), `detected_by`, `detected_at_utc`. `EVIDENCE_GAP` is a new vocabulary item (add to `docs/GLOSSARY.md`; it is not an existing line type: `DiffLogEntry` accepts only `clean` and `REGISTRY_DIFF`, `freeze.py:165-166`).
- Continuity: the freeze-continuity window is the maximal run of consecutive slots each satisfied by a CLEAN line. Any `EVIDENCE_GAP`, `REGISTRY_DIFF`, SKIPPED-after-pin or error line ends it; the evaluator reports each continuous segment and its length instead of one boolean, and PASS for L-04 "CLEAN on every tick" requires one segment from the pin to the window end. A missing tick makes the window non-continuous by construction. The evaluator never writes a CLEAN for a missing slot and never edits the append-only `registry_diff.jsonl` (the gap record is a separate artifact).
- A run can exist but fail before it writes its line (setup/sync failure). Run status `failure`/`cancelled` from the API with no line is therefore reported as `RUN_WITHOUT_LINE`, not as CLEAN.
- Numbers the user must own (L-08/L-09): the grace period that separates "late" from "missing", and whether a single `EVIDENCE_GAP` fails the trial or is reported (Q-E). The research found no documented delay bound to base either on.
- Evidence stamping suggestion for the workflow change (no decision involved): write `GITHUB_RUN_ID`, `github.event.schedule`, `GITHUB_SHA`, `run_started_at` into every line so a line is attributable to a scheduled run and to the master commit it judged.

### S2. Durable evidence storage: S3 versioning and Object Lock, and the existing backup chain

Design under study (from the reviewer): S3 holds the canonical evidence objects; a Git manifest (path, sha256, size, written-at, S3 version id) is the tamper-evident index. Facts and constraints (nothing selected):

| Topic | Fact | Source / confidence |
|-------|------|----------------------|
| Object Lock | "S3 Object Lock blocks permanent object deletion during a customer-defined retention period" and provides WORM protection | `[CITED: aws.amazon.com/s3/features/object-lock/, read 2026-10-07]` |
| Governance vs compliance | Governance: "Users can't overwrite or delete an object version or alter its lock settings unless they have special permissions". Compliance: "A protected object version can't be overwritten or deleted by any user, including the root user" | same page `[CITED]` |
| Versioning | Mandatory: "With S3 Object Lock, S3 Versioning is automatically enabled" | same page `[CITED]` |
| Existing buckets | The page says locks can be placed on existing objects with S3 Batch Operations. Whether Object Lock can be switched on for an existing bucket, or must be enabled at bucket creation, was NOT confirmed: the S3 user-guide pages on docs.aws.amazon.com returned HTTP 403 | `[ASSUMED]` (A3); see Verification gaps. If unknown, the evidence bucket should be created with Object Lock enabled; the planner must verify before the EC2 weekend creates buckets. |
| Cost | The pricing page excerpt lists S3 Standard requests (PUT/COPY/POST/LIST "$0.005 per 1,000 requests", GET "$0.0004 per 1,000 requests"; region not stated) and does not mention an extra charge for Object Lock or Versioning. The Singapore storage rate was not shown. | `[CITED: aws.amazon.com/s3/pricing/]` for the request prices only; "no extra Object Lock/Versioning charge" and "noncurrent versions are billed as storage" are `[ASSUMED]` (A4; absence in an excerpt is not evidence) |
| rclone and Object Lock | rclone has `--s3-object-lock-mode` (GOVERNANCE or COMPLIANCE), `--s3-object-lock-retain-until-date`, `--s3-object-lock-legal-hold-status`; "If you configure a default retention period on a bucket, requests to upload objects in such a bucket must include the Content-MD5 header" (rclone handles it); `--s3-bypass-governance-retention` deletes/overwrites under GOVERNANCE | `[CITED: rclone.org/s3/, read 2026-10-07]` |
| rclone and versioning | `rclone backend versioning` enables bucket versioning; `--s3-versions`, `--s3-version-at`; "`delete` will cause the current versions of the files to become hidden old versions"; `rclone backend cleanup-hidden` removes hidden old versions | same page `[CITED]` |
| rclone IAM | `rclone sync` needs `ListBucket`, `DeleteObject`, `GetObject`, `PutObject`, `PutObjectACL`, `CreateBucket` (unless `--s3-no-check-bucket`); `rclone lsd` needs `ListAllMyBuckets` | same page `[CITED]`; Object Lock retention actions were not listed in the excerpt |
| rclone crypt | "Hashes are not stored for crypt. However the data integrity is protected by an extremely strong crypto authenticator."; use `rclone cryptcheck` rather than `rclone check`; names are encrypted segment by segment by default | `[CITED: rclone.org/crypt/, read 2026-10-07]` |
| `--immutable` | "Treat source and destination files as immutable and disallow modification"; an existing differing file gives "immutable file modified" | `[CITED: rclone.org/docs/]`. Behaviour of `--checksum` when crypt exposes no hash (CR-01, D062) is not stated in the fetched text: `[ASSUMED]` (A6) |

**Interactions with the existing backup chain (read from `src/ops/backup_remote.py`, RUNBOOK section 11):**
1. The chain writes through an rclone `crypt` remote layered on the S3 remote, so object names and contents in the bucket are ciphertext (`backup_remote.py:1-12`, RUNBOOK 11). A reader that is not the host (the GitHub runner, an auditor) needs the crypt passphrases (`BACKUP_CRYPT_PASSWORD`, `BACKUP_CRYPT_PASSWORD2`) to read evidence stored through it; handing those to GitHub widens the secret's exposure. Evidence stored outside the crypt layer (a separate plaintext-or-SSE bucket, protected by the Git manifest hashes) avoids that but is a different remote from the backup chain.
2. Crypt stores no plaintext hash, so S3 ETags and rclone checksums say nothing about plaintext content; the project relies on `rclone cryptcheck` after each push (`push_snapshot`, `:300-340`) and a sha256 manifest inside each snapshot. A Git manifest of sha256 values gives the same independent plaintext check for evidence files.
3. `--immutable` on `parquet/` (`:334`) is compatible with versioning and Object Lock (no overwrite is attempted). A pure append-only evidence prefix would behave the same way.
4. Retention deletes `snapshots/<id>` with `rclone purge` and raises `RemoteError` on a non-zero exit (`apply_retention`, `:515-557`; purge call `:551-556`). Under a bucket default retention in COMPLIANCE mode that purge is refused until the lock expires, which would turn the scheduled backup (`scheduled`, `:611-631`) red after the first retention cut. With versioning only, a purge becomes hidden old versions and storage is not freed until `cleanup-hidden` or a lifecycle rule for noncurrent versions (an operator control; none exists in the repository). Therefore a backup bucket and an evidence bucket should not silently share one default-retention setting (A5: `[ASSUMED]` that default retention is bucket-wide, not per prefix; per-object retention flags on evidence writes are the alternative).
5. RUNBOOK 11.1 item 4 already asks the operator to enable "bucket versioning or object lock with a retention period" as provider-side protection; it is an operator control with no code check, so no test can prove it is on (real-host only, RUNBOOK 17 row 11.7).
6. The sentinel/empty-bucket logic (`check_sentinel`, `:233-260`) assumes a dedicated, initially empty bucket; an evidence prefix in the same crypt remote does not conflict with it, a second remote needs its own config mapping (`RCLONE_CONFIG_*`, `:128-140`).
7. EC2 host loss: journal rows reach the development machine through `pg.dump` in the daily snapshot (RUNBOOK 11.4), so the last up-to-24-hour window of evidence is exposed unless the evidence is written at event time.

### S3. Readers of `TradeRecord.modeled_costs_per_unit` (None on v2 filled records)

Grep over `src`, `scripts`, `tests` on 2026-10-07, then each hit read. Distinguish the TRADE RECORD field from the unrelated same-named `SizedResult` field and the `costs.modeled_costs_per_unit()` function.

| Where | What it does with the record field | Treats None as zero? |
|-------|------------------------------------|----------------------|
| `src/backtest/records.py:99` | field declaration `modeled_costs_per_unit: Decimal \| None` | n/a |
| `src/backtest/records.py:318` | filled records always built with `"modeled_costs_per_unit": None` in `common` | writer of None |
| `src/backtest/records.py:425,475` | `build_reject_record(modeled_costs_per_unit=None default)`; REJECT records carry the value passed in | n/a |
| `src/backtest/engine.py:713,728,789,808` | passes `sized.modeled_costs_per_unit` into REJECT records only (min-quantity reject, protective-level reject); the generic `_reject` default is None | writer |
| `src/backtest/experiment.py:790` (`_DECIMAL_TRADE_FIELDS`, loop `:890`) | round-trip parse for `reproduce`; `_coerce_trade_decimal(None)` returns None (`:815-817`) | No: None stays None |
| `src/adapters/analytics_files.py:85` (`_TRADE_DECIMAL_FIELDS`, loop `:473-476`) | validation of an evidence file's trade rows: only `if raw is not None` values are parsed | No: None is skipped, not defaulted |
| record serialization (`TradeRecord.to_dict`, Decimal to `str`, None to JSON null, `records.py:~121`) | the field is part of the trade payload and therefore of `trades_digest` | n/a (presence changes digests) |
| `src/backtest/report.py`, `src/analytics/*`, `scripts/*` | no reference to the field. `core_metrics.py:14` states realized R "is already net of the modeled costs"; gate G03 "Costs modeled" is derived from `cost_model_hash_present` (`gates.py:57-90`) | No reader |

Same-named but different objects (not readers of the record field): `src/risk/types.py:130` (`SizedResult` field), `src/risk/gating.py:144-306`, `src/risk/sizing.py` (the sizing computation), `src/execution/manager.py:555` (refuses a removed kwarg), `src/backtest/costs.py:356` (helper function), re-exports in `src/backtest/__init__.py`.

Tests touching it: record/evidence builders with None (`tests/backtest_plan_helpers.py:41,180`, `tests/phase10_helpers.py:37,77`), field-list parity (`tests/test_backtest_chain.py:61`, `tests/test_backtest_experiment.py:447`), a report test fixture with a literal `"0.0008"` that `report.py` never reads (`tests/test_backtest_report.py:544`; also `tests/fixtures/phase6/report_slices/input.json`, 15 occurrences), an evidence sample with one value and one null (`tests/fixtures/phase10/loaders/evidence_sample.json:107,146`), a simulator test that documents the None and reads the sizing value from the verdict instead (`tests/test_backtest_simulator.py:131-148`), and tests of the helper or `SizedResult` (`tests/test_cost_parity.py`, `test_cost_per_unit.py`, `test_risk_cost_guards.py`, `test_risk_quantization.py`, `test_risk_sizing.py`, `test_sl_loss_property.py`, `test_execution_manager.py`). **Answer:** no report or metric interprets a None `modeled_costs_per_unit` as zero cost; the only consumers of the field are the round-trip parsers, which preserve None. O-10's three options therefore change record bytes and digests (`trades_digest`, experiment reproducibility) but no existing metric.

## Plan Decomposition and Risks (what makes this phase heavy)

### Why it is heavy
1. Unknown live behaviour of the SDK lifecycle (D1-D5): the largest uncertainty; only a real run resolves it.
2. A `run_paper_tick` seam change with "costly" reversibility and pinned digests.
3. Missing inputs the tick needs live: constraint snapshots (exchangeInfo), `ttl` (a threshold, Q-G), equity (O-09), cost model from the registry, open positions and daily loss from a ledger.
4. New construction hidden behind the word "wiring": approval sender, token/binding resolver, confirm token store, fill driver, live 1m source, PG-to-evidence exporter, state restore.
5. Evidence tooling and a GitHub workflow that must land on `master` while work happens on `develop`.
6. Three independent subsystems (runner, kill-gate guard, deployment) plus about ten blocking-human checkpoints, one of which (EC2) happens before the runtime exists.
7. Several CONTEXT statements that read differently against the code (Q-A to Q-P).

### Suggested plans and dependency edges (names and splitting are the planner's; "Depends on" means must finish first)

| Plan | Scope | Depends on | Risk |
|------|-------|-----------|------|
| 16-01 | Async `PaperWsAdapter` on the real SDK shape, connection-event hooks, SDK-bound fakes + contract test, supervisor async protocol with backfill/gap sinks, `resync` 1 ms fix with real-shaped fixtures, `scripts/` public-data smoke recorder | none | HIGH (live unknowns) |
| 16-02 | IN-01..IN-05, `PaperAllowlistEntry` validation, GLOSSARY (`CONTEXT_BAR`, `DUPLICATE_BAR`, `SHADOW`, `EVIDENCE_GAP`), runtime start-gate function, `SKIPPED` line shape and `--from-allowlist`, `paper_freeze_check.yml` edit | none (but edits `loop.py`/`freeze.py`, so before 16-03) | LOW-MEDIUM |
| 16-03 | Byte-identical typed per-bar extraction + `decision_surface` + replay parity test | 16-02 | MEDIUM-HIGH (digest pins) |
| 16-04 | Runtime state ports, deterministic journal sink, gap/heartbeat/start/stop rows, restore, coverage function (needs Q-J) | 16-01 (gap sink shape) | MEDIUM |
| 16-05 | `src/paper/runtime.py` composition, graceful shutdown, queue/executor, compose `paper` service, healthcheck, env allowlist, structural + env isolation tests | 16-01, 16-03, 16-04 | HIGH |
| 16-06 | SHADOW approvals: sender, resolver, `Mode` and label, confirm card/token/TTL, journaled timestamps, expiry on restart | 16-04 (ports); wiring needs 16-05 | HIGH |
| 16-07 | Live 1m trade/mark source, fill driver over `lifecycle`/`ledger`/`funding`, position replay after restart | 16-03, 16-04 | HIGH (semantics, Q-B, Q-C) |
| 16-08 | Measured delay, `PaperRecord` extension or SHADOW evidence kind, PG-to-evidence exporter, analytics labels, `TEST_SIGNAL` | 16-06, 16-07 | MEDIUM-HIGH (digest/schema pins, Q-K) |
| 16-09 | Exit-criteria evaluator, `EVIDENCE_GAP` reconciler, freeze-continuity segments, durable export tooling | 16-02, 16-04; O-01 decision for the location | MEDIUM |
| 16-10 | Research runner (`src/research/`), feasibility gate, plateau, registration validator (may be split in two) | none (reads Phase 14 APIs) | MEDIUM (Q-O, pin file, Pitfall P22) |
| 16-11 | Kill-gate guard + versioned registry file + tests | none | LOW (Q-H) |
| 16-12 | Deployment: soak compose project, pinned-image recipe, `down -v` guard, RUNBOOK additions, EC2/runbook text | 16-05 | MEDIUM |
| 16-13 | Blocking-human checkpoints (smoke, EC2, closure chain, trial soak) | per checkpoint | n/a |

Critical path: 16-01 then the smoke on the execution machine, then 16-04/16-03, then 16-05, then 16-06/16-07, then 16-08, then 16-12, then the checkpoints. Independent tracks: 16-10, 16-11, and most of 16-09. Run the public-data smoke as soon as 16-01 exists: it retires the largest risk before the rest is built on assumptions.

### Risk list with mitigations
| Risk | Mitigation |
|------|------------|
| SDK reconnect/close semantics differ from the model (D3) | smoke includes a forced disconnect; adapter rebuilds the client on `close`/`error`; never rely on `subscribe` re-sending for known streams |
| `run_paper_tick` digest drift | extraction behind unchanged pinned digests; run `tests/test_paper_start_gate.py`, `test_paper_parity.py`, `test_paper_reviewfix_pins.py` after every edit |
| Fake-only green mistaken for closure | evaluator emits `proof_class`; SC9 rule test (Validation Architecture) |
| Late or duplicate signals after restart | source tags, deterministic ids, restart integration test on PG |
| Hidden event-loop blocking | `put_nowait` only in callbacks; blocking-call test (a slow fake DB must not delay queue draining) |
| Decision creep (thresholds) | every number is read from a ratified constants module with D061 label; O-07/O-08/O-09/O-12 stop at checkpoints (L-09) |
| Workflow on `master`, code on `develop` | explicit task and verification that the file on the default branch matches |
| Two bot pollers | separate bot tokens per environment (Q-L) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Telegram allows one long-polling consumer per bot token (409 conflict otherwise) | Pitfall P17 | A second poller on the dev machine silently steals callbacks from the soak |
| A2 | Binance accepts an unauthenticated connection to `/private/stream` (the SDK opens it for every client) | D5 | A connect refusal could make `create_connection` produce fewer connections than expected |
| A3 | Object Lock can be enabled for an existing bucket, or must be set at creation (unconfirmed; docs.aws returned 403) | S2 | An evidence bucket without Object Lock cannot be fixed later |
| A4 | No extra charge for Object Lock/Versioning; noncurrent versions billed as storage | S2 | Cost estimate for O-12 wrong |
| A5 | S3 default retention is bucket-wide, not per prefix | S2 point 4 | Backup retention purge could break under a shared bucket |
| A6 | `rclone --checksum` over a crypt remote (no stored hash) falls back to size-based comparison | S2 | CR-01 does not give the tamper detection the user expects |
| A7 | GitHub does not auto-disable scheduled workflows in a PRIVATE repository for inactivity (fetched pages state it for public repositories only) | S1 | Silent end of freeze ticks |
| A8 | Binance offers no mark-price KLINE websocket stream (inferred only from the SDK having none) | D9 | A cheaper live mark source may exist |
| A9 | EBS encryption-by-default and S3 default encryption (SSE-S3) behave as D042 assumes (pages not fetched) | Environment | D042 acceptance checks wrongly skipped |
| A10 | The tick (features over up to 1000 bars x 5 symbols) completes well within a bar interval on the EC2 instance type chosen in O-12 | Pitfall P10 | Backlog at the 1h/4h boundary |
| A11 | REST `markPriceKlines` returns the just-closed 1m bar within a short time of the minute close (lag unknown) | D9, Pattern 5 | Fill detection delayed or holes |
| A12 | Binance delivers each closed kline (`x=true`) once per stream between reconnects | Pitfall P6 | Dedup must still be kept (it is) |

## Open Questions

### Research findings that need a human or planner decision (NOT in CONTEXT; recommendations are not selections)

- **Q-A Does a fully rationalized candidate need an allowlist entry to start?** `pin_stream_epoch` consults `PAPER_START_ALLOWLIST` only for sets without rationale tables (`freeze.py:460-466`; rationalized sets return at `:467-476`), and tests pin that behaviour (`test_injected_entry_never_admits_a_set_that_has_rationale_tables`, `test_fully_rationalized_set_runs_without_the_flag`). L-05/D061 E says only a user-authorized exact-hash entry may start paper, and D-01 says the runtime exits SKIPPED when the allowlist admits nothing. A runtime-level exact-hash gate (Pattern 7) satisfies L-05 without changing `pin_stream_epoch`; whether that is the user's intent touches O-13 and D054 item (i), so it needs the user. Evidence needed: user confirmation of the rule; the decision row text.
- **Q-B When does fill eligibility start for a confirmed SHADOW plan?** Backtest: from the signal close (`advance` clamps to `signal_close_utc`). Real operator: only after APPROVE+CONFIRM. Using the signal close lets a "confirmed" plan fill on minutes before the human acted; using the confirm time (a later `start_exclusive`, no simulator change) matches reality but is not "identical to backtest". Options: signal close; confirm instant floored to the minute; confirm instant plus one minute. Evidence: user statement on what SHADOW evidence is meant to represent; one fixture comparing the two on a real day.
- **Q-C Exposure registration for plans awaiting a decision.** The engine registers a resting plan's risk at signal time (`engine.py:824-830`). In SHADOW a plan may wait for APPROVE (O-08 window): does it reserve exposure, and what happens to its exposure on SKIP/expiry/CANCEL? Options: reserve at signal (backtest parity), reserve at confirm, reserve at approve and release on expiry. Evidence: parity requirement of L-04 ("same signals, plans and risk verdicts") and the cap values.
- **Q-D Are bars recovered by REST after a WS reconnect (process up) evaluated?** L-11 says bars closed "while the process was down" never produce signals. A WS drop with the process alive is not "down". Options: backfilled bars are history only (Pattern 6); backfilled bars younger than the freshness bound may evaluate; evaluate all (contradicts the spirit of "no late signals"). Evidence: user wording.
- **Q-E Missing hourly freeze ticks versus L-04.** See S1: "CLEAN on every tick" does not say what a missing tick does. Options: any `EVIDENCE_GAP` fails the trial; gaps are reported and a user-ratified count/grace is tolerated; gaps restart the window. A missing tick must never count as CLEAN and makes the continuity window non-continuous (reviewer rule). Evidence: user ratification; the grace figure has no documented basis.
- **Q-F How does the GitHub check obtain the pinned epoch?** The pin is written on the host (`write_pinned_state`, `freeze.py:697`). Options: the user commits `pinned_epoch.json` (hash-bound to the allowlist entry commit) to `master`; the workflow reads it from the durable store with a read-only credential stored as a GitHub secret; the check runs on the host (contradicts L-01). Evidence: O-01 decision; secrets policy.
- **Q-G Constraint-snapshot freshness (`ttl_seconds`) and exchangeInfo refresh cadence.** `evaluate_risk(ttl=...)` returns `STALE_CONSTRAINTS` when `age > ttl or age < 0` (`src/risk/portfolio.py:287-294`), and `loop.py:366` takes `ttl_seconds` from the input; existing fixtures use `"0"`. A live value is a freshness threshold (L-08). Fold into O-07.
- **Q-H What counts as "real evidence" for the kill-gate guard?** No marker distinguishes real from fixture evidence in `analytics-evidence/2` or `provenance.py`. Options: default-deny with an explicit synthetic/fixture marker that tests must set; default-allow with a real-evidence marker the soak export sets; guard on the presence of PAPER rows with a live `epoch_id`. A planner proposal (not selected) would be default-deny.
- **Q-I What does "pinned image produced by CI" mean without a registry?** No CI step pushes an image (D050; `ci.yml` header). Options: build on the host at a recorded commit, tag with the commit and record the image id (`deploy/update.sh` writes `.deploy/last-good.env`); add a registry (deferred decision); build in CI and `docker save`/transfer. Evidence: user decision on registry.
- **Q-J Where does durable runtime state live?** Pitfall P12: journal-only restore (no migration) versus migration `0005` adding a state key/table. D-04 says "no second persistence mechanism"; a new table would arguably be one. Evidence: planner's choice with test cost; user only if a schema is added.
- **Q-K How is measured delay represented in evidence?** New `PaperRecord` field or a distinct evidence kind versus reusing `synthetic_lag`; affects loader, digests and report labels (Pitfall P15). Evidence: D-18 "no new metric definitions" interpretation.
- **Q-L Telegram bot tokens per environment.** One token for the EC2 soak, another for the dev/execution machine (A1).
- **Q-M Live 1m source for open plans:** WS `1m` kline streams versus REST polling for trade bars; mark bars REST only (D9, A8). Evidence: smoke measurement of REST lag (A11) and weight budget (1 to 2 per call, SDK docstring).
- **Q-N One family per runtime:** the runtime evaluates the single allowlisted `strategy_id`/set; multi-family concurrency is not asked for by CONTEXT.
- **Q-O Feasibility gate and the single-use holdout.** Counting trades on the final 20 percent block is running the candidate on the holdout (Pitfall P21). Options: report Development and Validation counts only and state G5 floor "not assessed"; report a clearly labelled extrapolation by period length from Development/Validation (a statistical method, user-approved); let the user ratify a holdout peek rule (needs a protocol statement). Evidence: user decision; protocol text at G5.
- **Q-P (small) D-21 SKIPPED line shape** needs a vocabulary decision recorded in GLOSSARY; and the line before the pin has no `epoch_id` (the `DiffLogEntry` requires one).

### Per open decision O-01..O-13: options and evidence still needed (no selection)

| ID | Options (from CONTEXT, with research facts) | Evidence still needed from the user or the planner |
|----|---------------------------------------------|-----------------------------------------------------|
| O-01 durable evidence location | (a) S3 evidence prefix/bucket; (b) private Git repository; (c) Actions artifacts/cache only; (d) EC2 disk + backup chain; (e) S3 canonical + Git manifest. Facts: S1 (cache 7 days, artifacts 90 days default, run records expire too, hourly drops, private repo) and S2 (Object Lock needs versioning; compliance vs governance; crypt ciphertext unreadable off-host without passphrases; backup retention purge conflict; host loss exposure window) | who needs read access (GitHub runner? auditor?); whether evidence goes through the crypt remote or a separate bucket; lock mode and retention length (a number); confirmation of A3-A5 against AWS docs; cost line for O-12 |
| O-02 hypothesis and grid | draft only after runtime exists; N = 25 per family `[VERIFIED: docs/research/RESEARCH_PROTOCOL.md:238, "**Variant budget:** N = 25 per family"]` | the user's grid; nothing pre-filled by research |
| O-03 run authorization | file, CLI flag, both | form chosen by the user; data window, symbols, `research-universe-v1`, split dates (protocol: 40/40/20 split with four walk-forward Validation folds, `RESEARCH_PROTOCOL.md:58`); how the runner proves "never touches the holdout" (Q-O) |
| O-04 exact-hash allowlist entry | user commit adding `PaperAllowlistEntry` | requires Q-A answered; rebuild of the pinned image after the commit (the allowlist is a source constant, `freeze.py:402`) |
| O-05 D055 | open, Phase 18 | none for Phase 16 |
| O-06 OQ-1 | annotate / count against coverage / exclude / void | the runner's reported count of trades with `coverage_note` mark holes (lifecycle annotation, `lifecycle.py:20-36`) from the first real run |
| O-07 healthy feed and freshness | table below of every existing constant and documented Binance fact | the user's numbers for: WS silence per interval, stale-bar age, reconnect backoff/bounds, DEGRADED duration, REST backfill depth, constraint-snapshot ttl (Q-G), 4h/1h sibling wait (P6), freeze-tick grace (S1) |
| O-08 approval window | derive from plan `expiry_utc` (a field on `TradePlan`, `domain/trade_plan.py:64`) or a user number | which; D041 confirm TTL (60 s default) is locked |
| O-09 simulated equity/risk inputs | user sets equity, daily-loss base, leverage, margin type; `Ledger.start(equity=...)` and `AccountState` consume them | the values; AGENTS.md context only (500 to 1,000 USD capital) |
| O-10 `modeled_costs_per_unit` | leave None; restore at record time; restore post-run | S3 above: no report treats None as zero; any restoration changes trade payload bytes, `trades_digest` and `reproduce` equality; the user's choice |
| O-11 closure triggers | user commands | none |
| O-12 EC2 numbers | instance type, EBS size, budget alert, S3 lifecycle/retention | AWS pricing for Singapore (not retrieved), A9/A10; public IPv4 is charged "$0.005 per IP per hour for all public IPv4 addresses, whether attached to a service or not", effective 2024-02-01, Elastic IPs included `[CITED: aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/, read 2026-10-07]` (about 3.65 USD per month for one address at 730 h, arithmetic only) |
| O-13 | closed | none |

**Existing constants and documented facts for the O-07 table (nothing here is ratified):**

| Constant / fact | Value | Where |
|-----------------|-------|-------|
| Tick staleness gate | `STALENESS_THRESHOLD_SECONDS: int = 60` | `src/paper/loop.py:175` |
| Warm-up minimum | `WARMUP_MIN_BARS: int = 200` | `loop.py:181` |
| Engine windows | `STRATEGY_WINDOW_BARS = 1000`, `CONTEXT_WINDOW_BARS = 300` | `src/backtest/semantics.py:48-49` |
| Supervisor reconnect bounds | attempts 7, delay cap 120 s, wait max 60 s, multiplier 1 | `src/paper/supervisor.py:52-55` |
| Resync bounds | attempts 7, delay cap 120 s | `src/paper/resync.py:45-48` |
| Notify bounds | attempts 3 | `src/paper/notify.py:111-114` |
| REST backfill page | `limit=1500`, at most 200 pages | `resync.py:195`, `:213` |
| SDK rotation | 82800 s (23 h) | `binance_common/constants.py:16` |
| SDK reconnect delay / attempts | 5000 ms / 3 (max 10) | `ConfigurationWebSocketStreams` defaults |
| SDK subscribe spacing | 0.5 s per SUBSCRIBE | `constants.py:18` |
| Binance connection lifetime | 24 h | Connect page `[CITED]` |
| Binance server ping / pong deadline | every 3 min / 10 min | Connect page `[CITED]` |
| Binance incoming messages | 10 per second per connection; 1024 streams per connection | Connect page `[CITED]` |
| DB waits | statement 10,000 ms, lock 5,000 ms, connect 3 s, pool 5 s | `src/persistence/engine.py` |
| Staleness of constraints | caller-supplied `ttl`; fixtures use 0 | `portfolio.py:287-294`, `loop.py:366` |

## Environment Availability

Probed 2026-10-07 on the research machine (Windows 10, Git Bash):

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 venv | all tests | yes (main tree `.venv`) | 3.13.15 | system `python` is 3.14.3: do not use it; use `uv run` or the `.venv` |
| uv | commands, CI parity | yes | 0.12.20 (CI/Dockerfile pin 0.12.21) | none needed for local runs |
| Docker | compose config, image builds | client present | 29.5.3 (daemon state not probed) | docker-marked tests run only in CI |
| PostgreSQL / `psql`, `TEST_DATABASE_URL` | `*_pg.py` tests | no (`psql`, `pg_isready` missing; variable unset) | none | PG tests skip locally (fail in CI strict mode); use a disposable `_test` database via Docker on the execution machine |
| git, gh, bash | workflows, scripts | yes | git 2.49.0, gh 2.102.0, bash 5.2.37 | none |
| rclone, aws CLI, shellcheck, chronyc | backup chain, EC2 runbook, deploy tests | no | none | real-host only (RUNBOOK 17) |
| Public Binance REST (`fapi.binance.com`) | live observation | yes (one GET succeeded) | none | none |
| Binance WS from this machine | smoke | NOT probed here (D061 G recorded 502 through a proxy on the discuss machine) | none | blocking-human smoke on the execution machine |
| Telegram and AWS docs sites | facts | docs pages returned 403 from this machine | none | Verification gaps |

**Missing with no fallback for Phase 16 execution:** a PostgreSQL instance for the `*_pg.py` tests on the execution machine (Docker or service); the real EC2 host for criteria 7 and 8.

## Validation Architecture

(`workflow.nyquist_validation` is `true` in `.planning/config.json`.)

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 with pytest-asyncio 1.4.0, `asyncio_mode = "auto"`; respx 0.23.1 for httpx-level mocks (`pyproject.toml`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]`, marker `docker` |
| Quick run command | `PYTHONPATH=. uv run pytest tests/<file>.py -q -p no:cacheprovider` (file by file on Windows) |
| Full suite command | `uv run pytest -m "not docker" -rs -p no:cacheprovider` (the CI command; `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set so PG tests run) plus `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` |
| Baseline | 11 paper test files, 157 tests, all passed on 2026-10-07 (command: `PYTHONPATH=. <main .venv python> -m pytest <file> -q -p no:cacheprovider` from the worktree) |

### Phase Requirements to Test Map (test file names are proposals; all are Wave 0 gaps unless noted)

| Criterion | Behavior | Test type | Command | Must FAIL on |
|-----------|----------|-----------|---------|--------------|
| SC1 composition (PAPER-01) | supervisor, queue, tick, journal sink wired; empty allowlist exits 0 `SKIPPED (allowlist empty)` without subscribing; graceful stop writes `RUNTIME_STOP` | unit with SDK-bound fakes + in-memory ports | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_compose.py -q` | subscribe before the gate; non-zero exit on empty allowlist; an open candle reaching the tick; a DB call executed inside the WS callback |
| SC1 restart/gap | restore last close; downtime gap row `PROCESS_DOWN`; REST/warm-up bars never evaluated; no duplicate signal; no missing journal row | integration on PG | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_restart_pg.py -q` (needs `TEST_DATABASE_URL`) | an evaluated backfilled bar (including one younger than 60 s); a second `signal_id` row or a second journal id after a replayed bar; wall-clock-keyed journal ids |
| SC1 resync | real-shaped klines (close = open + interval - 1 ms) give zero phantom gaps | unit | `PYTHONPATH=. uv run pytest tests/test_paper_resync.py -q` (extended) | the current code (3 returned bars, 3 gaps) |
| SC2 contract (PAPER-01) | fakes mirror SDK async surface: coroutine-ness, parameter names, no `on_message` on the handle, handle has `on`/`unsubscribe`; negative control with a sync fake | unit, network-free | `PYTHONPATH=. uv run pytest tests/test_paper_ws_contract.py -q` | a sync `create_connection`/`kline_candlestick_streams` in a fake; a handle exposing `on_message`/`reconnect`; adapter passing the Enum or not awaiting |
| SC2 adapter | awaits calls, passes `"1h"` string, sets `stream_url` PROD, checks `ws.connections` non-empty, hooks `on_connection` | unit | `PYTHONPATH=. uv run pytest tests/test_paper_ws_connect.py -q` (rewritten) | `connections == []` accepted silently; Enum interval; missing `stream_url` |
| SC3 fills | confirmed plan fills through the public lifecycle functions; a one-plan fixture equals the `simulate` trade for the same minutes (byte-equal trade payload) when eligibility start equals the signal close | unit + golden | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_fill.py -q` | any reimplemented fill rule (spy on `advance`, `new_plan_state`); different bytes versus `simulate` |
| SC3 delay | `acted_at - requested_at` used; 30 s constant only when no human action; confirm timestamps recorded | unit | `PYTHONPATH=. uv run pytest tests/test_paper_approval_delay_measured.py -q` | the assembler overriding a real timestamp with signal + 30 s |
| SC3 buttons | SIMULATE message carries functional `APR:`/`SKP:` buttons backed by a PENDING approval | unit | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_buttons.py -q` | inert `SIM:` payloads in SHADOW |
| SC4 criteria | evaluator constants equal D061 D (14 days, 95 percent, tolerance zero) and evaluate synthetic evidence; D061 row text witness | unit | `PYTHONPATH=. uv run pytest tests/test_paper_exit_evaluator.py -q` | a changed constant without a DECISIONS change; any threshold derived from results |
| SC5 SHADOW chain | every outgoing message carries the exact label `SHADOW — no real order`; APPROVE then CONFIRM, CANCEL, SKIP, expiry journaled with timestamps; replayed callbacks idempotent; confirm token single-use and TTL-bound; restart expires pending approvals | unit + PG | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_messages.py tests/test_paper_shadow_pg.py -q` | a message without the label; second CONFIRM accepted; confirm after TTL; approve of an expired plan |
| SC6 isolation | AST import-graph over the runtime's module closure; env refusal for `BINANCE_LIVE_*`/`BINANCE_TESTNET_*`; spy test with negative control | unit (AST + env) | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_isolation.py -q` | import of `src.execution.manager`/`placement`; calls to `place_entry`/`place_algo_protective`/cancel methods; startup with a live-key variable; a spy that cannot detect a deliberate call (negative control) |
| SC7 smoke | smoke evidence file schema and redaction scan (precursor only); the real run is blocking-human | unit (schema) + HUMAN | `PYTHONPATH=. uv run pytest tests/test_paper_ws_smoke_evidence.py -q` | an evidence file without SDK versions, per-interval closed-event counts, forced-disconnect result |
| SC8 freeze | `--from-allowlist`: empty gives one SKIPPED line, exit 0, never CLEAN; no hard-coded id left in the workflow; non-empty path unchanged | unit + text | `PYTHONPATH=. uv run pytest tests/test_paper_freeze_allowlist_mode.py tests/test_paper_freeze.py -q` | CLEAN or red exit on empty allowlist; fallback to `baseline-v3`; `trend-pullback` in the workflow |
| SC8 coverage and gaps | coverage function; `EVIDENCE_GAP` for a missing slot; continuity segments | unit | `PYTHONPATH=. uv run pytest tests/test_paper_coverage.py -q` | a missing slot counted as CLEAN |
| SC9 closure rule | evaluator output carries `proof_class`; fake-adapter evidence can never yield PASS for SC1/SC2/SC7 closure | unit | `PYTHONPATH=. uv run pytest tests/test_paper_closure_rule.py -q` | PASS on evidence produced by fakes |
| D-20 parity | recorded closed bars replayed through `decision_surface` give identical digests; windows 1000/300; 4h before 1h at shared closes | unit | `PYTHONPATH=. uv run pytest tests/test_paper_decision_surface.py -q` | arrival-order dependence; unwindowed history |
| Tick seam | typed extraction leaves `run_paper_tick` bytes unchanged | unit (existing) | `PYTHONPATH=. uv run pytest tests/test_paper_start_gate.py tests/test_paper_parity.py tests/test_paper_reviewfix_pins.py tests/test_paper_feed_gates.py tests/test_paper_closed_candle.py -q` | any digest change |
| D-31 guard | refuses real evidence while any of WR-01/06/12/13 is UNRESOLVED; passes fixtures; flipping one back blocks | unit | `PYTHONPATH=. uv run pytest tests/test_killgate_guard.py -q` | a conclusion produced on real evidence with an unresolved item |
| D-24..30 runner | refuses without authorization whose grid hash matches; prints no verdict; never writes the allowlist; holdout block never simulated by the feasibility gate | unit | `PYTHONPATH=. uv run pytest tests/test_research_runner.py tests/test_research_feasibility.py -q` | run without artifact; allowlist write; a holdout-window simulate call |
| D-32 deployment | compose config renders for a soak project; `paper` env lists no `BINANCE_*`; `down -v` guard refuses the soak project (project resolved from `-p`, `COMPOSE_PROJECT_NAME`, `name:`) | static + docker config | `PYTHONPATH=. uv run pytest tests/test_soak_compose.py -q` | an unguarded `down -v`; a trade key in the paper env |

### Sampling Rate
- **Per task commit:** the touched test files (`PYTHONPATH=. uv run pytest <files> -q -p no:cacheprovider`).
- **Per wave merge:** every `tests/test_paper_*.py` file one by one, plus `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`.
- **Phase gate:** CI-equivalent full run with `TEST_DATABASE_URL` set, then the blocking-human evidence below before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] All new test files in the table above.
- [ ] SDK-shaped fake client and handle builders (reuse SDK model classes for events, D8).
- [ ] Real-shaped kline fixtures (Code Examples rows).
- [ ] Rewrite `tests/test_paper_ws_connect.py` and `tests/test_paper_supervisor_backfill.py` (they pin the fictional handle API).
- [ ] Disposable PG for `*_pg.py` on the execution machine.
- [ ] Add new modules to the explicit file list in `tests/test_domain_no_float.py`.

## Real Versus Fake: What Can Only Be Proven on the EC2 Host or a Real Exchange

**Stated plainly (ROADMAP criterion 9, D061 item J): fake-level tests, contract tests against installed SDK signatures, in-memory PG ports and AST checks must never be counted as closing PAPER-01 or PAPER-02.** They prove wiring and contracts; they do not prove behaviour against Binance, Telegram or a host. Phase 7 was closed with requirements unmet on exactly that evidence.

| Claim | Fake or CI can prove | Only a real run proves |
|-------|----------------------|-------------------------|
| WS contract (SC2) | Fakes mirror SDK signatures; adapter awaits; plain-string interval; `stream_url` set | A real `create_connection` yields connections; `ws_subscribe` succeeds; closed 1m, 1h and 4h events reach the supervisor (SC7); behaviour of rotation (23 h), `serverShutdown`, unsolicited drop and recovery (D3); `/private` connection acceptance (A2); stdlib-logging visibility of failures (D4) |
| Closed-bar-only | Gate logic on synthetic events | Real `x` semantics, arrival latency against the freshness bound, clock skew effects (P20) |
| Gaps and restart | Restore, dedup, deterministic ids on PG fixtures | Real downtime/restart with Docker `stop`/`kill`, SIGTERM within `stop_grace_period: 30s`, volume persistence, journal completeness over days |
| Backfill | Fixture-driven | REST pagination and rate limits against the real API; gap/forming behaviour at the real boundary (the 1 ms close arithmetic is already evidenced by the live row above) |
| Approval and Telegram | Replay idempotency, token TTL, labels via fake bot | Real bot delivery, real taps with human delay, edit-message behaviour, 409 pollers (A1), keyboard rendering |
| Fills (SC3) | Equality with `simulate` on shared minutes; ledger bookkeeping | Real 1m trade/mark REST availability and lag (A11), funding polling, holes, a confirmed position carried across a restart on live data |
| Parity | Replay digest equality on recorded bars | That the recorded bars/inputs from the real soak are complete (journal stores consumed bars and tick inputs) |
| Freeze check | CLI, SKIPPED path, text of the workflow | GitHub scheduling on `master`, dropped/late ticks, cache and artifact retention, `EVIDENCE_GAP` reconstruction from the real run list |
| Deployment | Static compose config, guard scripts, env allowlist | `docker compose up` on EC2, healthcheck behaviour, restart policy, pinned image identity, backups to the real bucket and a restore drill, Object Lock configuration, chrony offset, public ping to `fapi.binance.com` from the instance, budget alert, Elastic IP, encrypted EBS (RUNBOOK 17 "Only a real host can show") |
| Coverage 95 percent over 14 days (L-04) | The arithmetic | Only the 14-day run on the host; the execution machine never produces soak evidence (L-11) |

Evidence a human must produce (blocking-human, measurable): the smoke evidence file (SDK/binance-common versions, per-interval closed-event counts, forced-disconnect recovery, the data.binance.vision fetch of G3-026), the EC2 acceptance table per D042 condition, the real Telegram tap log with timestamps, and the trial-soak exports.

## Security Domain

`security_enforcement` is `true` in `.planning/config.json` (ASVS level 1, block on high).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (limited) | Telegram: the authorized-chat gate runs before any state lookup (`authorized_chat_gate`, `telegram_callbacks.py:183-196`); user-id binding is Phase 23 and must be stated plainly |
| V3 Session Management | partial | One-time approval token (hashed, constant-time compare, `tokens.py`) and a separate single-use CONFIRM token with TTL (L-13) |
| V4 Access Control | yes | SHADOW isolation in three layers (D-13); `trading` user, sudo with password (D062); no live key in the paper env |
| V5 Input Validation | yes | Strict callback parse (`parse_callback_data`, 64-byte ceiling); WS payload normalisation with try/except per message (`paper_ws.py:166-194`); env-variable allowlist; evidence-file loaders fail closed |
| V6 Cryptography | yes | `hashlib.sha256`, `hmac.compare_digest`, `secrets.token_urlsafe` already used; never hand-roll; rclone crypt for backups |
| V7 Error handling and logging | yes | `src/ops/redaction.py` scrubbing; the SDK logs through stdlib `logging` (it logs the connection URL and proxy in `init_connection`) so the root logger must be configured and checked for secrets; never log raw tokens |
| V9 Communications | yes | TLS to Binance, Telegram, S3 (library defaults); no webhook edge in this phase |
| V14 Configuration | yes | `.env` mode 0600; shared `env_file` currently also carries `BACKUP_*` into the paper container (WR-06 stays Phase 24, document the exposure); image digest pins |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Replayed or duplicated Telegram callback | Tampering/Repudiation | PG conditional update + `uq_approvals_one_decided_per_plan`; replay returns the stored row |
| Callback from an unauthorized chat | Spoofing/Elevation | chat gate before lookup; journaled rejection |
| Raw token in logs or journal | Information disclosure | store hash only; redaction; tests that scan journal payloads |
| Malformed or hostile WS payload | Tampering/DoS | per-message try/except, `Decimal(str(...))`, no `eval`; bounded queue |
| Trade-capable key present in the paper process | Elevation | env refusal at startup + AST import test + no order adapter constructed |
| Silent loss of feed | Denial/Repudiation | healthcheck tied to last processed bar age; gap rows; evaluator |
| Evidence tampering or loss | Tampering | Object Lock + versioning, Git manifest hashes, append-only journal trigger |
| Registry file edited on the host | Tampering | hash-pinned TOML, hourly check on `master`, optional in-process `check_registry_unchanged` |
| Clock manipulation/skew | Tampering | chrony, start-of-run skew log, journaled tick `now_utc` |
| Second bot poller hijacking updates | Spoofing/DoS | separate bot tokens (A1, Q-L) |

## Sources

### Primary (HIGH confidence)
- Repository files read this session (paths with line ranges cited inline): `src/paper/*`, `src/adapters/paper_ws.py`, `binance_usdm.py`, `telegram_*.py`, `src/persistence/*`, `src/backtest/*`, `src/analytics/*`, `src/ops/backup_remote.py`, `docker-compose.yml`, `Dockerfile`, `.github/workflows/*`, `docs/DECISIONS.md` rows D040, D041, D055-D062, `docs/research/RESEARCH_PROTOCOL.md`, `docs/operations/RUNBOOK.md`, `.planning/*`.
- Installed packages: `binance-sdk-derivatives-trading-usds-futures` 17.4.0 and `binance-common` 4.4.0 source in `C:/Users/admin/Music/Trading/.venv/Lib/site-packages` (`websocket_streams/websocket_streams.py`, `streams/market_api.py`, `binance_common/websocket.py`, `constants.py`, `configuration.py`, `utils.py`).
- Live public REST observation `GET https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2` (2026-10-07).
- PyPI JSON API for SDK and binance-common latest versions (2026-10-07).

### Secondary (MEDIUM confidence, WebFetch summaries read 2026-10-07)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Connect
- https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows
- https://docs.github.com/en/rest/actions/workflow-runs
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository
- https://aws.amazon.com/s3/features/object-lock/ ; https://aws.amazon.com/s3/pricing/ ; https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/
- https://rclone.org/s3/ ; https://rclone.org/crypt/ ; https://rclone.org/docs/
- Context7 `/python-telegram-bot/python-telegram-bot` and `/websites/python-telegram-bot_en_stable` (manual Application lifecycle, `callback_data` 1-64 bytes)

### Tertiary (LOW confidence)
- Items tagged `[ASSUMED]` in the Assumptions Log.

## Verification Gaps

Network retries: one retry per failed URL, then recorded here. Nothing below was worked around or guessed.

| URL / source | Error | Unverified as a result |
|--------------|-------|------------------------|
| https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Kline-Candlestick-Streams (and the `/en/docs/products/derivatives-trading-usds-futures/...` variant) | page returned the developer-docs landing page, twice | stream payload field documentation; the `x`/`T` semantics were taken from the installed SDK models and one live REST row only |
| https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data | landing page, twice | official REST kline page text; weight table taken from the installed SDK docstring; close = open + interval - 1 ms taken from one live REST response |
| https://core.telegram.org/bots/faq and https://core.telegram.org/bots/api | HTTP 403 (also via curl) on the first and second attempt | Telegram rate limits, one-poller-per-token rule (A1), `answerCallbackQuery` and edit-message details; `callback_data` 1-64 bytes comes from the python-telegram-bot docs via Context7 |
| https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-encryption-faq.html, https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSEncryption.html, https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html | HTTP 403 on each (first two retried once) | S3 default encryption, EBS encryption by default, Object Lock enablement on existing buckets and bucket-creation requirements (A3), default-retention scope (A5), AWS Budgets and EC2 instance pricing for ap-southeast-1; D042 conditions must be accepted on the host, not from this document |
| https://aws.amazon.com/s3/features/versioning/ | HTTP 404 | S3 versioning feature details (delete markers, MFA delete, lifecycle for noncurrent versions) |
| https://aws.amazon.com/s3/pricing/ | page excerpt had no Singapore rates | storage price per GB-month for ap-southeast-1; Object Lock/Versioning charges (A4) |
| rclone docs fetch | summary did not state `--checksum` behaviour without a common hash (and its `--size-only` sentence was garbled, so it is not relied on) | A6; CR-01 is a quick task outside Phase 16 plan scope |
| Binance WS rate limit for new connections, mark-price kline stream existence outside the SDK, `/private` without a listenKey | not on any fetched page | A2, A8 |
| GitHub: numeric delay bound for scheduled runs; auto-disable rules for private repositories | not stated in the fetched pages | S1 grace period; A7 |
| Live WS, live Telegram, EC2, GitHub schedule behaviour | not exercised (by design, blocking-human) | everything in "Real versus fake" |

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH (nothing new; versions from `uv.lock`).
- Architecture and code shape: HIGH (files read; one in-memory experiment and 157 passing baseline tests).
- SDK lifecycle: HIGH for what the source says, LOW for how it behaves live (D3 recovery path unproven).
- Binance, GitHub, AWS, rclone docs: MEDIUM (fetch-tool summaries; several pages unreadable, see gaps).
- Pitfalls: HIGH where evidenced by source or the experiment (P1, P8, P9, P11); MEDIUM where inferred (P6, P13, P18).

**Research date:** 2026-10-07
**Valid until:** 2026-10-14 for SDK/PyPI drift (fast-moving: three releases in three weeks); 30 days for repository facts, until the base commit changes.


