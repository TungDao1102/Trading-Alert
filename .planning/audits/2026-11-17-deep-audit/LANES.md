# LANE ASSIGNMENTS (common rules: LANE_BRIEF.md)

Each lane: output `lanes/<lane>.md` + `lanes/<lane>.findings.json`, finding IDs from its own range.
"Scope files" are the files whose coverage row the lane owns. A lane may read any other file.

Two kinds of lane:
- **M-lanes (module lanes)**: deep read of a code area against the rules.
- **X-lanes (cross-cutting techniques, new in this audit)**: failure scenarios, mutation probes,
  evidence reproduction, operator view, prior-finding closure.

---

## WAVE 1 — the money path, and the intent itself (X09, X10; X01 runs in wave 2)

### M01 core_strategy_risk — G-0100..0199
Scope files: `src/core/*`, `src/domain/*` except `exchange_errors.py`, `algo_status.py`, `stream_records.py`;
`src/risk/{sizing,quantization,portfolio,gating,cost_rates,cost_guards,realized_risk,types}.py`; `params/**`.
- Geometry per family and direction (entry / SL / TP1 / TP2, long vs short sign, tick rounding
  direction: a rounded stop must never increase risk), min stop distance, confirmed pivots (D-rows
  of Phase 15), TP2 positivity guard, closed-candle only, no lookahead, prefix invariance.
- Sizing and quantization order (AGENTS "Quantization floors, never rounds up"), fee/cost units
  (old F-126 family: quote currency everywhere), minimum risk utilisation, portfolio caps.
- Probe with numbers: equity 500 and 1000 USDT; BTC ~100k, ETH, a low-price alt with coarse
  stepSize; SL 0.3 %, 1 %, 3 %. Show realised risk after rounding vs budget, both directions.
- Parameter registry: hash lock, provenance labels, unknown key handling, canonical serialisation
  and hashing stability (Decimal normalisation, key order), transitions table completeness.
- Decimal-only and purity: do the AST guards really cover every module they claim?

### M02 exec_placement — G-0200..0299
Scope files: `src/execution/{manager,approval_desk,confirm_flow,confirm_recheck,pre_placement,placement,binding,gates,enablement,execution_limits,constraint_snapshot,order_ids,intent_store,intent_recovery,prior_outcome,lot_split,lot_filter_source,tp_sizing}.py`, `src/approval/*`.
- Plan binding (symbol/side from the hashed plan, quantity ≤ approved, D078), APPROVE → CONFIRM
  (D041), expiry, one-time consumption, replay of at-least-once callbacks, two presses racing.
- Gate order before a placement: enablement, SAFE_MODE, kill gate, constraint freshness, price
  check, day-risk, margin, "no entry while any position is unprotected". Any path that reaches
  `place_entry` without all gates? Alternate entry points (recovery, scripts, smoke injection).
- **Never re-send a placement** (D080): one POST per approval; ambiguous → probe once by client
  order id → not found or probe error ⇒ UNKNOWN + SAFE_MODE. Look for any retry decorator,
  loop, recovery or restart path that can POST a second time. Client order id determinism.
- Write-ahead intent: what is persisted before the POST, crash between persist and POST, and
  between POST and result persist; `intent_recovery` decisions.
- `LIVE_ORDERS_DISABLED`: is the disable affirmative and impossible to bypass by config/env?

### M03 exec_protection — G-0300..0399
Scope files: `src/execution/{protection,emergency_close,protection_rebuild,protection_replay,pending_actions,fill_monitor,cancel_verification,liquidation_watch,live_context}.py`, `src/persistence/pending_actions.py`.
- Fill-driven protection (D079): after any fill (full, partial, several partials, fill seen only
  by REST, fill seen twice, fill seen out of order) is a stop placed for exactly the filled
  quantity? Stop quantity vs position after TP1; reduceOnly / closePosition; MARK_PRICE trigger.
- Stop placement fails / is rejected / is ambiguous / is confirmed then lost (D077) → emergency
  close; emergency close itself fails or is ambiguous → what then? Time bounds (D113, D114).
- GTD entry expiry with a partial fill; cancel verification; a late fill after cancel.
- State machine of `protection.py`: list the states and transitions you find, and every
  transition with no handler. Idempotency of replay/rebuild after restart.
- Liquidation watch and post-fill checks: active or inert in the composition?

### M04 live_risk_state — G-0400..0499
Scope files: `src/execution/{day_risk_service,daily_stop,margin_guard,symbol_config_guard,bracket_cache,account_equity,live_risk_inputs}.py`, `src/risk/{daily_loss,live_equity,margin_check,liquidation,reservations,money_at_stake,live_commission}.py`, `src/live/{risk_inputs,reservation_release,commission}.py`, `src/persistence/{risk_reservations,day_risk}.py`.
- Equity from Binance: which field, staleness bound (`account.max_equity_age_ms`), failure → NO_TRADE?
- Daily loss (D033): day boundary and timezone, realised + unrealised, fees and funding
  (FundingPolicy), restart in the middle of a day, the stop is sticky for the day.
- Reservations: reserve-at-approve, release on every terminal outcome (fill, cancel, expiry,
  reject, UNKNOWN, restart). Leak or double release? Concurrent approvals of two plans.
- Margin, leverage and liquidation guard: ISOLATED, 5x cap, liquidation beyond SL with buffer,
  available balance netting resting orders (flag stays False), bracket cache age.
- Probe the formulas with numbers (isolated liquidation price long/short vs Binance's formula).

### M05 reconcile_safemode — G-0500..0599
Scope files: `src/reconcile/*`, `src/live/reconcile.py`, `src/persistence/{safe_mode_store,system_state}.py`.
- Every mismatch class (exchange has position / order / algo order that local does not, and the
  reverse; quantity or side differs; unknown intent) → classification → action. Blind spots
  (old F-701). The protective of a resting entry is never an orphan (old F-401).
- SAFE_MODE: durable across restart, blocks every entry path, monitoring continues, who can
  clear it and on what evidence; can any automatic path clear it?
- Sweeper: can it cancel or close something that is legitimately ours and in flight (race with
  placement / protection)? Feed freshness gate.
- Startup reconcile ordering vs stream start vs scheduler start.

### X09 decisions_trading_soundness — G-2100..2199  (technique: judge the intent, not the code)
Role: an experienced crypto-futures risk manager and research methodologist reviewing a design
that AI agents wrote and a non-expert owner accepted. Read `docs/DECISIONS.md` (all rows, focus
D031–D114), `docs/trading/*`, `docs/strategy/*`, `docs/backtest/*`, `docs/research/RESEARCH_PROTOCOL.md`,
`docs/00_PRODUCT_SCOPE.md`, the phase `*-CONTEXT.md` / `*-DISCUSSION-LOG.md` / `*-OWNER-DECISIONS.md` / `decisions/`
for Phases 11–25, `params/**` and `config/**` values with their `[rationale]`.
- For EVERY decision that affects money or safety: restate it in one line, then verdict
  SOUND / DOUBTFUL / WRONG / CANNOT_JUDGE with the yardstick (arithmetic, exchange fact, risk
  practice, owner goal). Table in the lane file, one row per D-number, written as you go.
- Was it really the owner's decision? From the discussion logs: which options were offered,
  was a real alternative shown with consequences in numbers, or was "recommended" simply taken?
  List decisions where a materially different option was never put to the owner.
- Whole-design questions nobody may have asked: is the system viable at 500–1000 USDT
  (min notional, fees and funding as a share of 1R, number of trades needed for the kill-gate
  statistics, months to any conclusion)? Are risk per trade, daily loss, leverage 5x ISOLATED,
  liquidation buffer, MARK_PRICE triggers, GTD LIMIT entry with no entry-time stop (D079),
  "never re-send, UNKNOWN + SAFE_MODE" (D080), stall bound 60 s observe-only (D114), the 3
  confirm rereads (D113), the TP ladder, funding policy `TRADES_WITH_UNVERIFIED_FUNDING`
  mutually consistent? Where does a chain of individually reasonable decisions add up to an
  unsafe or pointless whole?
- Numbers without derivation (PLACEHOLDER/DECISION provenance): list each, say what it
  controls and what a wrong value costs. Probe with numbers where it helps.
- Research method: can the protocol (v2.6.0) still produce a false "go"? Was anything tuned on
  results despite the rule (the amendments v2.1 → v2.6 came after run 1 was seen)?
Methodology and safety only; no opinion on whether a strategy is profitable.

### X10 exchange_facts — G-2200..2299  (technique: check every exchange "fact" at the source)
Collect every statement about how Binance USDⓈ-M Futures or Telegram behaves that the design
relies on: in `docs/integration/*`, `docs/operations/DEMO_VS_MAINNET.md`, `docs/DECISIONS.md`,
`docs/trading/EXECUTION_SPEC.md`, phase `*-RESEARCH.md` of Phases 18–24, `19-OWNER-GAPS.md`,
`22-DEMO-RESULTS.md`, and constants/comments in `src/adapters/binance_*.py`,
`src/domain/exchange_errors.py`, `config/binance/*`.
For each: source in the project, the claim, the check against the official docs
(developers.binance.com; core.telegram.org) and the installed SDK
(`C:\Users\admin\Music\Trading\.venv\Lib\site-packages\binance_sdk_derivatives_trading_usds_futures\`),
verdict VERIFIED / CONTRADICTED / DEMO_ONLY (seen once on Demo, not documented) / UNVERIFIABLE.
Table written as you go. Priority: algo/conditional order endpoints and their migration; -4509
and stop placement without a position; GTD semantics and minimum goodTillDate; error codes
classed as definitive vs ambiguous (-1007, -1008, -1021, timeouts, 503 "unknown"); order status
after a timeout; client order id uniqueness window and length; STOP_MARKET trigger rules
(-2021); MARK_PRICE vs CONTRACT_PRICE; reduceOnly/closePosition rules; position mode, margin
mode and leverage endpoints; liquidation price formula and maintenance margin brackets;
availableBalance meaning; income types (FUNDING_FEE, COMMISSION); funding interval variability;
rate limits, 429/418 and ban duration; listenKey lifetime and expiry event; event ordering
guarantees; Demo Trading base URLs and documented differences from mainnet; exchangeInfo filter
names; MIN_NOTIONAL for reduce-only orders. A design decision that rests on a CONTRADICTED or
DEMO_ONLY fact is a finding. Network: one retry at most per page, then mark
UNVERIFIABLE(network) and go on.

### X01 failure_scenarios — G-1800..1899  (technique: FMEA on the order lifecycle)
Read `lanes/decisions_trading_soundness.md` and `lanes/exchange_facts.md` first if they exist.
"Expected safe outcome" means what keeps the owner's money safe, not merely what a D-row says.
Not a module read. Build a table of failure scenarios over the whole lifecycle
(signal → plan → notify → APPROVE → CONFIRM → intent → POST entry → fill(s) → stop → TP →
exit → journal → reconcile) and decide each one by tracing the code, and where practical by a
probe that drives the project's own fakes (`tests/support/`, fake exchange/clock) with that sequence.
For each scenario: trigger, expected safe outcome (from DECISIONS), actual outcome with file:line, verdict.
Minimum scenario set (add your own):
- process killed at each boundary: after intent persist / after POST before response / after
  fill before stop / after stop before TP / during emergency close / during reconcile;
- network: POST timeout with the order actually accepted; 5xx; -1021 clock; 429/418 ban in the
  middle of protection; user-data stream silent or disconnected for N minutes around a fill;
- exchange: partial fill then GTD expiry; fill after cancel; stop rejected (-2021 would trigger
  immediately, -4509); position closed manually by the owner on the exchange; position mode or
  leverage changed outside; liquidation; funding settlement during a position;
- database: unavailable at fill time; unavailable at approval time; commit failure after the POST;
- human: APPROVE at the last second before expiry; CONFIRM twice; two plans approved together;
  approval while SAFE_MODE is being entered; operator command during protection;
- time: day roll at 00:00 UTC with an open position; DST is irrelevant (UTC) — verify; clock skew.
Report scenarios whose outcome is an unprotected position, a duplicate order, a silent stall, or
an unbounded wait. Mark the ones you only reasoned about (not probed) as such.

---

## WAVE 2 — composition, exchange, research

### M06 live_composition — G-0600..0699
Scope files: `src/live/*` except `risk_inputs.py`, `reservation_release.py`, `commission.py`, `reconcile.py`.
- Start sequence (D098–D107, RUNBOOK §22): order of locks, DB, clock check, exchange config
  checks, reconcile, stream, scheduler; a refusal at each step (`--hold-on-refusal`).
- One process / one loop: every task in `scheduler.py` — what happens when it raises, hangs or
  is cancelled; stall watchdog (D111/D114) is observe-only: what does a stalled protection task mean?
- Is everything built in Phases 19–23 actually wired (compare `wiring.py` with the library
  modules; list anything constructed but never called, or called with a stub/None)?
- `smoke_injection.py`: can test injection be active outside a Demo smoke?
- Operator commands: authority, effect, journal. Health/liveness truthfulness.
- Refusal when `BINANCE_LIVE_*`/mainnet is configured; Demo vs live endpoint selection.

### M07 binance_adapters — G-0700..0799
Scope files: `src/adapters/binance_*.py`, `src/domain/{exchange_errors,algo_status,stream_records}.py`, `config/binance/*`.
- Against the INSTALLED SDK (`C:\Users\admin\Music\Trading\.venv\Lib\site-packages\binance_sdk_derivatives_trading_usds_futures\`, read-only) and the
  official docs: method names, parameter names, enums, response fields; algo order endpoints;
  exchangeInfo filters; position mode; user-data events (ORDER_TRADE_UPDATE, ALGO_UPDATE,
  ACCOUNT_UPDATE, listenKey expiry); recvWindow/timestamp.
- Error taxonomy: every code → class; is any "definitive reject" actually ambiguous on the
  exchange (order may exist)? Is any ambiguous one treated as definitive? Unknown code default.
- Rate-limit gate and ban handling: does the gate ever block a protective or emergency action?
- User-data supervisor/router: reconnect, gap detection, dedupe, ordering, what is lost while
  disconnected and how it is recovered. Demo-only observations coded as facts (list them).
- SDK types must not leave `src/adapters`.

### M08 telegram_alerts — G-0800..0899
Scope files: `src/adapters/telegram_*.py`, `src/ops/{alerts,alert_wording}.py`, `src/live/{approval_sender,telegram_runner,alerts}.py`, `src/paper/notify.py`.
- Authorisation by user id on every callback and command; callback_data ≤ 64 bytes; replay;
  keyboard removal; message edit failures; long polling offset handling (a lost or repeated update).
- Money amounts on the card (old F-0xx): are the numbers the ones that will be executed
  (same plan hash, same quantity, risk in USDT, fees)? Stale card after the plan changed.
- Notification failure never approves; alert delivery failure for a HIGH alert → what then?
- Alert contract (closed set): every raise site, dedupe/rate limiting that could hide a repeat.

### M09 backtest_research_analytics — G-0900..0999
Scope files: `src/backtest/*`, `src/research/*`, `src/analytics/*` (render_* at NORMAL_READ), `docs/research/RESEARCH_PROTOCOL.md`, `docs/backtest/*`.
- Causality (old F-901/F-120): fills only after the signal bar, same-bar ambiguity rule, 1m
  intrabar order, mark-price triggers, funding, gaps, expiry clock. Probe it: build a small case
  where lookahead would change the result and show it does not.
- Costs: taker/maker, slippage on exit, funding sign, units.
- Research integrity: pre-registration, authorization files, multiplicity correction, holdout
  consumption, plateau, kill-gate stickiness and bypass, "no parameter chosen from results".
- Is the simulator the same logic as paper/live for sizing, quantization, expiry (parity)?
- Methodology only; no opinion on profitability.

### M10 paper_runtime — G-1000..1099
Scope files: `src/paper/*`, `src/adapters/paper_ws.py`, `config/paper/*` (priority: runtime, shadow*, freeze, loop, supervisor, pipeline, restart, resync, runtime_state, liveness; the rest NORMAL_READ).
- Paper refuses to start with any `BINANCE_*` variable; SHADOW mode has no order path (prove by imports/call graph).
- Closed-candle detection, reconnect gap → resync/backfill, duplicate or late bars, restart.
- Freeze / pin epoch: what is frozen, how a drift is detected, can the soak evidence be produced
  from a build other than the pinned one?
- Shadow fills vs backtest fill semantics (same engine or a fork?). Exit criteria computation.

### X02 mutation_probe — G-1900..1999  (technique: do the tests notice when safety code breaks?)
Work in your OWN scratch clone: `git clone --no-hardlinks AUDIT\snapshot AUDIT\tmp\mutation_probe\clone`
(never mutate `AUDIT\snapshot` or the original repo). For about 25–35 hand-picked safety
behaviours, apply ONE small mutation each (flip a comparison, drop a guard, change floor to
round, remove a SAFE_MODE check, allow a second POST, skip the unprotected-position check,
change a day boundary, drop a user-id check, swallow an exception, widen a staleness bound…),
run only the relevant test files (`-p no:cacheprovider -x -q`, PYTHONPATH = your clone), record
KILLED (a test fails) or SURVIVED, then `git checkout -- .` before the next one.
Pick targets across: `src/risk/{sizing,quantization,daily_loss,margin_check,liquidation,reservations}.py`,
`src/execution/{placement,manager,protection,emergency_close,gates,enablement,binding,pre_placement}.py`,
`src/approval/*`, `src/reconcile/{safe_mode,compare,sweeper}.py`, `src/core/planner.py`,
`src/backtest/{engine,entry,exits}.py`, `src/adapters/{telegram_callbacks,binance_errors}.py`, `src/domain/exchange_errors.py`.
A SURVIVED mutation of a money/safety guard is a finding (GAP, with the exact diff and the test
files you ran). Check a survivor is not an equivalent mutation before reporting. Keep a table
of all mutations in the lane file as you go (one row each, written right after it runs).
Do not run the whole suite; cap each pytest call at a few files.

---

## WAVE 3 — data, ops, tests, evidence

### M11 data_persistence_db — G-1100..1199
Scope files: `src/data/*`, `src/persistence/*` except those owned by M03/M04/M05, `src/db/**`, `src/adapters/analytics_*.py`, `alembic.ini`.
- Models vs migrations 0001–0015 vs `docs/data/DATA_MODEL.md`: constraints, nullable money
  columns, Numeric precision, tz-aware timestamps, enum drift, chain linearity, downgrade.
- Transaction boundaries and unit of work: approval consumption + intent atomic? unique
  idempotency keys? isolation level; lost update on concurrent writers; append-only journal.
- Collector/backfill: closed-day publishing, gaps, dedupe, raw immutability, Parquet types,
  point-in-time universe, mark-price klines, sufficiency rules.

### M12 ops_deploy_security — G-1200..1299
Scope files: `src/ops/*` except `alerts.py`, `alert_wording.py`; `deploy/**`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/*`, `pyproject.toml`, `uv.lock`, `.gitignore`, `.dockerignore`.
- Secrets: redaction coverage (which shapes are missed?), secrets in logs/exceptions/journal/
  evidence bundles, committed evidence files containing account data, `.env` handling in
  shell scripts, heartbeat URL by stdin.
- Backups: encrypted, off-host, restore drill real, backup gate; update/migrate/rollback scripts
  (shell correctness: `set -euo pipefail`, quoting, partial failure, idempotency).
- Container: non-root, pinned digests, exposed ports, healthcheck truthful, compose secrets.
- CI: what runs, what does not (PG tests? docker? mypy?), pinned actions, required checks.
- Dependencies: pins vs lock, pre-release or deprecated packages, anything forbidden by AGENTS.

### M13 scripts_tooling — G-1300..1399
Scope files: `scripts/**`, `tests/demo/**` (read only, never run).
- Owner-run Demo scripts (`demo_rehearsal.py`, `demo_probe.py`, `demo_clear.py`,
  `user_data_smoke.py`, …): what stops them from touching mainnet (URL pinning, credential
  names, `--execute`), what they can cancel/close (`demo_clear`), size limits.
- `scripts/decision_alignment/*`: does the gate check meaning or only strings? What drift would it miss?
- Fixture generators: are expectations computed by the implementation under test (self-confirming goldens)?
- Soak/evidence evaluators (`evaluate_*`, `export_soak_evidence.py`, `soak_host_acceptance.py`): can they pass on bad input?

### X03 test_effectiveness_ci — G-1400..1499
Scope files: `tests/**` (sampled), `tests/support/*`, `tests/conftest.py`, `AUDIT\tool-output\*`.
- Interpret the tool output: failures, skips (list every skip reason and what is therefore never
  exercised, e.g. all `*_pg.py`), slow tests, ruff/mypy results.
- For the critical behaviours (charter §4 items 1–3): is there a test that would FAIL if the
  behaviour broke? Look for assertions on mocks only, fakes that are more permissive than the
  real exchange (compare the fake exchange with Demo-observed behaviour), tests weakened in
  history (`git log -p --since=2026-10-01 -- tests/ | grep` for added skip/xfail, widened tolerances, deleted asserts).
- AST guards and structural tests: what do they not cover (new packages added after the guard)?
- Do not duplicate X02 (mutations); read `lanes/mutation_probe.md` if it exists and build on it.

### X04 evidence_reproducibility — G-1500..1599  (technique: re-derive, do not trust)
- Re-hash every `params/**/*.toml` against `tests/fixtures/phase4/parameters.json` and the registry.
- Determinism by execution: run a small backtest/research case twice (and with a shuffled dict
  order / different `PYTHONHASHSEED`) and compare bytes; prefix invariance on a fixture.
- Recompute a sample of committed research records (`docs/research/experiments/research-run-1-v2-3-0/`)
  from their inputs if the inputs are in the repo; otherwise say exactly what is missing.
- Gate records and evidence under `.planning/phases/*/evidence/` and `evidence/`: does each
  record prove what STATE.md/SUMMARY claim (commit hash present in history, counts consistent,
  the tree it ran on)? Demo smoke 21/21 of 2026-11-06 and 2026-11-15: what do the 21 steps
  actually assert, which are Demo-only, single-sample or injected?
- Kill-gate decision files and `holdout_consumed.json`: consistent with the records?

### X05 decisions_requirements_process — G-1600..1699
Scope files: `docs/**` except `docs/research/experiments/**`, `AGENTS.md`, `.planning/{PROJECT,REQUIREMENTS,ROADMAP,STATE}.md`, phase `*-OWNER-*`, `*-DEFERRED*`, `*-VERIFICATION.md`, `19-OWNER-GAPS.md`.
- (Soundness of the decisions is X09's job, exchange facts are X10's: read their lane files if present.)
- DECISIONS D040–D114: for each, is it
  implemented where it says, does a later row contradict it, is any row still a draft/OPEN
  while code depends on it (D055?). Money/safety rows first.
- Canonical docs vs code for the execution model (EXECUTION_SPEC, RISK_MANAGEMENT, BINANCE.md,
  RUNBOOK §22): stale statements that would mislead the operator.
- Requirements: Pending vs Complete vs reality; phases ticked complete with `human_needed`
  verification; one consolidated register of everything still open for the owner
  (decisions, NOT_CONFIGURED keys and what each does when unset — refuse or default?, Demo checks, attestations).
- Plans vs outcome for Phases 16–24: take 3 success criteria per phase from ROADMAP and check
  them in code yourself, ignoring SUMMARY/VERIFICATION claims. Count how often a claim did not hold.

### X06 prior_findings_closure_a — G-1700..1749
Input: `.planning/audits/2026-09-29-deep-audit/findings.json`. Take every primary finding with
severity HIGH or MEDIUM whose id is F-2xx…F-8xx (code lanes). For each: FIXED (cite the code
and the test that pins it) / PARTIAL / OPEN / SUPERSEDED (design changed; say by which D-row) /
WRONGLY_CLOSED (a plan or summary says fixed, the code does not). Table in the lane file, one
row per old id, written as you go. Only non-FIXED rows that matter become G-findings.

### X07 prior_findings_closure_b — G-1750..1799
Same method for the primary findings F-0xx, F-1xx, F-9xx (docs, requirements, planning
decisions) of severity HIGH or MEDIUM, plus a 15-item spot check of LOW ones.

### X08 operator_golive_gap — G-2000..2099  (technique: walk in the operator's shoes)
The owner is one part-time person without trading expertise. Read `docs/operations/*`
(RUNBOOK, DEPLOY_GUIDE.vi.md, DEMO_VS_MAINNET.md, SECURITY_AND_OPERATIONS.md), the phase
`*-OWNER-RUNBOOK.md` files, alert wording and the Telegram cards.
- Walk through: first start, a normal trade, SAFE_MODE at 3 a.m., an UNKNOWN placement, a
  position without a stop, a ban, a restore from backup, an update with a migration, key rotation.
  At each step: does the runbook say exactly what to do, is the command real (exists in code,
  right flags), can a wrong but plausible action lose money, how does the owner learn it
  happened if Telegram is down (external heartbeat?).
- Demo → mainnet delta: list every behaviour that is only Demo-observed or injected, every
  flag that must flip, and what would first be exercised with real money (P3, P7, A2 …).
- What the system cannot do without the owner (single point of failure, sleep, travel).

---

## WAVE 5 — added at the owner's request (2026-11-18)

### X11 strategy_viability — G-2300..2399  (technique: is the project worth continuing?)
Owner's question, in his words: "I care most about whether the project should keep going; capital can be increased later." Scope change: the 2026-09-29 rule "methodology only, no judgment of profitability" is relaxed for this lane only. You still do not forecast future profit; you judge, from the evidence that exists, whether continuing on this path is a reasonable investment of the owner's time, and what would change that judgment. Neutral both ways.
1. **Edge evidence:** what the committed research says (read `lanes/backtest_research_analytics.md` G-0901..G-0905 and `lanes/backtest_gapfill.md` first, do not redo them). Per family: best candidate, mean R, its distance from break-even and from the protocol gates, and whether more data could plausibly change the verdict.
2. **Strategy rationale:** read the family specs (`docs/strategy/*`, `docs/research/families/*`, `docs/research/TRADING_STRATEGY_RESEARCH.md`, D054, `params/*`). For each family: the market behaviour it relies on, whether that behaviour is documented in public research or practice, known reasons it would fail on crypto perpetuals at 4H/1H, and whether the parameters were derived or picked.
3. **Economics:** with the project's own cost model (fees, slippage, funding), compute the cost per trade in R for typical stop distances, and the win rate needed to break even at the planned R:R. Show how this changes with capital 500, 1000, 5000, 20000 USDT (min notional, which symbols become tradable, quantization loss). Say plainly whether more capital fixes anything or only scales the result.
4. **Statistical power:** with the observed trade frequency and R dispersion, how many trades and how many months are needed to detect an edge of +0.05R, +0.1R, +0.2R at the protocol's alpha. Compare with the kill-gate date and the roadmap timeline.
5. **Cost of continuing:** what remains on the roadmap before any real-money trade (phases 25-27 and the missing strategy signal source G-1052), roughly in weeks for a part-time owner, versus the evidence so far.
6. **Options for the owner**, each with what it costs, what it would prove, and a clear decision criterion: (a) continue as planned; (b) pause engineering, run research run 2 under a fresh, pre-registered protocol first; (c) change strategy family/timeframe/market; (d) stop. Recommend one, with the reasons and what evidence would make you change the recommendation.
Probe with numbers wherever possible (project's own code for costs and quantization). Mark every claim about the market that is not from the repo or an official source as an opinion.
