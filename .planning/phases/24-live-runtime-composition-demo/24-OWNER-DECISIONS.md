# Phase 24 owner decisions (plan 24-01)

Written 2026-10-31 by the assistant (Claude Sonnet 5.5). Status of this packet: OPEN, no question is answered yet.

## What Phase 24 builds, and what it does not

Phase 24 joins the finished library pieces of Phases 16 to 23 into one running process and proves it on Binance Demo Trading (demo-fapi.binance.com). Today nothing in `src` builds the reconcile loop, the sweeper, the clock-drift guard, the alert sink, the equity source, the daily-loss service or the margin guard; only the rehearsal script builds them by hand (research, "Summary").

- Nothing in this phase enables mainnet. Live placement stays disabled (`LIVE_ORDERS_DISABLED`, `src/execution/enablement.py`).
- Demo runs with `--execute` stay owner-run. The assistant builds the scripts, tests them with fakes and writes down what you must run. No result counts as "Demo-observed" until you run it.
- This packet contains no limit number. Every number is in `24-LIMITS-CHECKPOINT.md`, marked as an assistant recommendation.
- No source, test, config or `docs/` file is edited by this plan. `docs/DECISIONS.md` rows (from D089) are written by later plans after your answers.

## How to read a question

Every question has the same lines: Recommendation (first, in plain words), Why, Alternatives, Undo cost, Plans that depend on it, Answer (blank, filled in after you reply). "Plans" are numbered 24-04 to 24-36 in this phase. Q1, Q2 and Q3 are one-way doors: they are expensive to undo, so they come first and no code walks through them before you answer.

The research found two places where the first context draft disagrees with decisions you already recorded (D085 and D086). They are Q9 and Q14. The assistant did not resolve them silently.

---

## Q1 Process boundary: one live process (D-01, one-way door)

Recommendation: build one live process, started as `python -m src.live.runtime`, with one asyncio loop that runs every live task (Telegram bot runner, user-data stream, protection stepper, reconcile, sweeper, health, clock-drift re-measure, risk-input refresh). It is separate from the paper runtime and from the collector, and it never imports `src.paper.runtime`.

Why: one loop means one shared REST rate-limit gate, one SAFE_MODE state and one place where order of events can be reasoned about. The paper runtime holds no order adapter by design (D040), so mixing it with order placement would break that rule. This is the shape D042 (single VPS) already expects.

Alternatives: (a) several small processes (one for Telegram, one for reconcile): each needs its own gate and its own copy of state, and a 418 ban in one would not stop the others. (b) Put live tasks inside the paper runtime: breaks the SHADOW "no order adapter" rule.

Undo cost: high. The boundary fixes the compose service, the heartbeat probe and the list of environment variables; splitting or merging later means moving state between processes and rewriting all three.

Plans that depend on it: every plan from 24-10 on, in particular 24-11, 24-27 (the composition) and 24-35 (the compose service).

Research: C-8, C-11 and the "Architectural Responsibility Map".

Answer: (blank)

---

## Q2 Database calls on the event loop: the StoreExecutor seam (D-25, G4-040, P16R-03, one-way door)

Recommendation: keep the existing synchronous PostgreSQL stores and send every store call made on the event loop through one small module, `src/ops/store_executor.py`. Ordered writes go through one single-thread writer; reads use `asyncio.to_thread`. The paper runtime's `expire_due` call moves behind the same seam (this closes P16R-03). No async database pool.

Why: a slow database call on the loop would stall Telegram, the stream and the protection step at the same time. The research measured that the default thread pool can reorder two calls (the call started first finished second), which is not acceptable for ordered ledger writes; one writer thread keeps the order. An async pool would be a new dependency with no measured need, and AGENTS.md requires a DECISIONS row for any new dependency.

Alternatives: (a) async pool (SQLAlchemy async + a new driver): new dependency, large rewrite of every store. (b) Call the stores directly on the loop and accept stalls: simplest, but a locked table freezes protection. (c) A separate thread pool of several workers: reintroduces reordering.

Undo cost: high. Every live store call and the paper confirm sweep go through the seam, so removing it touches all of them. The module sits in `src/ops/` so the SHADOW import test (`test_paper_shadow_isolation`) still passes.

Plans that depend on it: 24-05 (the seam), then every plan that touches a store (24-08, 24-17, 24-19, 24-20).

Research: C-11, P-1, P-2, A5, A6.

Answer: (blank)

---

## Q3 Migration 0015: the shape of the order event-time change (D-10, R-7, one-way door)

Recommendation: write one hand-made Alembic migration, `0015_order_event_time`. It adds one nullable "exchange event time" column to the `orders` table and to the `positions` table. The stores then accept an update only when its event time is not older than the one already stored (Binance says to order updates by the `E` field). Add the missing `update_position_snapshot`. No new table: the Order, Fill and Position tables and stores already exist since Phase 17. The downgrade is guarded (it refuses once event times are stored).

Why: the user-data stream can deliver the same order's updates in a different order across event types; a stored value must never go backwards. A nullable column keeps every existing row valid. The current Alembic head is `0014_decided_excl_expired`, so `0015` is the next free number.

Alternatives: (a) a separate new table for event times: more joins, another table family other phases would read. (b) Keep the latest value in memory only: lost at restart, which is exactly when order matters. (c) Skip the event-time column and trust arrival order: wrong whenever two update types race.

Undo cost: high once event times are stored: the guarded downgrade refuses, because dropping the column would destroy evidence. Before any row is written the migration is easy to revert. Other phases will read this schema.

Plans that depend on it: 24-07 (the migration), 24-19 (the stream writers).

Research: C-10 (D-10 paragraph), R-7, "Official-doc facts" row on ordering.

Answer: (blank)

---

## Q4 Where the live process gets a signal and a trade plan (OQ-2, C-4)

Recommendation: define a `SignalSource` interface (a Python Protocol) in `src/live/`. In Phase 24 ship only one implementation: the Demo-smoke injector, which reuses the rehearsal's plan derivation but gives every plan its own Signal and TradePlan ids (never the ids SHADOW uses). Nothing from the `src.paper` strategy pipelines is imported. Then you tell us which later phase owns strategy-driven DEMO signals (and the bar feed they need).

Why: the first context draft lists the live process's tasks, and none of them produces a signal. In the paper process, signals come from the strategy pipeline over the pinned soak epoch, and that code is frozen for the soak. Also, approval ids are built from the plan id, so the same plan cannot be issued in both SHADOW and DEMO against one database (primary-key collision). The interface keeps the door open without importing paper code by accident.

Alternatives: (a) reuse the paper strategy pipeline inside the live process: touches frozen soak code and couples two processes. (b) Build a new strategy-driven DEMO source in Phase 24: large, and the roadmap does not assign it to this phase. (c) Manual plan entry only: no automation path to test.

Undo cost: low. The interface is small; swapping or adding a source later does not change the rest.

Plans that depend on it: 24-14 and 24-29 (the smoke).

Research: C-4, OQ-2, P-8.

Answer: (blank)

---

## Q5 Demo enablement and what the three market-feed health checks mean (OQ-3, C-2, C-3, D-26, D-28, R-3, A4)

Recommendation: keep the execution manager unchanged. In DEMO mode only, the start sequence ends with an in-process `enable()` call by a fixed DEMO operator id, after a passing ten-check health verdict. That call is never reachable in LIVE mode (LIVE keeps the human operator action). Enablement starts DISABLED at every start; a stored "enabled" is never trusted after a restart. The meaning of the three feed checks in the live process:

- `market_feed_freshness` = age of the REST mark price of the tracked symbols.
- `ws_connection_state` = the state of the user-data stream.
- `last_closed_candle_time` = not applicable to the live process; it is reported DEGRADED, with the DEMO mode flag written to the journal.

D056 rows: in LIVE, a DEGRADED verdict cannot enable and blocks new entries once enabled. In DEMO, DEGRADED is allowed only under the explicit DEMO flag and can never lead to LIVE. The kill-gate state comes from the analytics kill-gate source and can only switch things off automatically, never on.

Why: the manager refuses every placement while enablement is disabled (gate 2, `manager.py`), and `enable()` needs a complete verdict of ten non-failing checks (`enablement.py`). Three of those checks describe a market feed the live process does not own (`src/ops/health.py`, `ALL_CHECK_NAMES`). Today nothing produces DEGRADED, so D056 asked for the design to be done together with Phase 24. The rehearsal script already enables in-process the same way.

Alternatives: (a) change the manager so DEMO needs no `enable()`: edits a safety gate for one mode. (b) Keep the human enable also in DEMO: the owner would have to run a command before every smoke run. (c) Give the live process a real market WebSocket feed: a new data source for little value.

Undo cost: medium. The probe meanings and the D056 rows are pinned by tests in this phase; changing them later means editing those tests and a DECISIONS row.

Plans that depend on it: 24-22 and 24-26. Threat T-24-02: plan 24-22 tests that the in-process enable is unreachable in LIVE.

Research: C-2, C-3, OQ-3, A4.

Answer: (blank)

---

## Q6 Telegram identity of the live process (OQ-4, C-7, A11)

Recommendation: create a second Telegram bot for the live process (Telegram allows only one poller per bot token). Its token and chat id use live-only variable names in the live environment file. It uses the same private owner chat and the same `TELEGRAM_AUTHORIZED_USER_IDS`. The live process refuses to start if the SHADOW bot variable is present in its environment.

Why: the project rule `BOT_TOKEN_RULE` (16-DEC-Q-L) says exactly one getUpdates consumer per bot token; two pollers on one token raise a conflict error and steal each other's updates. You already did this for the SHADOW soak host.

Alternatives: (a) share the SHADOW bot: then SHADOW and DEMO cannot run at the same time. (b) A webhook instead of polling: needs a public HTTPS endpoint, which this system does not have.

Undo cost: low. It is a variable name plus a start-up check.

Plans that depend on it: 24-17 and 24-30.

Research: C-7, A2, A11.

Answer: (blank)

---

## Q7 Operator commands from Telegram (OQ-5, R-4, C-6, 20-DEFERRED P20-OPS-REMOTE)

Recommendation: a minimal command set on the same user-id and private-chat gate as the approval buttons:

- `/status` (read only).
- `/disable_entries` (reduces risk, no confirmation needed).
- `/safemode_exit` (two-step confirm).
- `/close SYMBOL` (two-step confirm).

Clearing the REST rate-limit gate stays an ssh command line. No command places an entry or raises risk. Changing leverage and margin type from Telegram (the wish recorded in D085) is not part of Phase 24.

Why: leaving SAFE_MODE needs live state that exists only inside the running process, and the safe-mode exit refuses unless the stream is live and the REST gate is restored (`src/reconcile/safe_mode.py`). So it cannot be a separate command line; it must be a command to the running process. On 2026-10-23 you confirmed this direction; the conditions you set (no new order, two-step confirm for exit and clear) are kept.

Alternatives: (a) no Telegram commands, ssh only: then SAFE_MODE exit is impossible without a restart. (b) The full command set including leverage and margin type: larger design and a new risk surface; better as its own phase. (c) Add gate clear to Telegram: the gate is the last guard against an IP ban, so I would keep a human at a shell for it.

Undo cost: low. Commands are additive and can be removed one by one.

Plans that depend on it: 24-23.

Research: C-6, OQ-5, 20-DEFERRED "Telegram operator commands".

Answer: (blank)

---

## Q8 One database per mode (OQ-6, C-7, A10)

Recommendation: change the approved-approvals reader so it only returns approvals of its own mode. Then SHADOW and DEMO can share the one compose database safely.

Why: today `list_approved_approvals` returns every APPROVED approval of any mode (review item WR-06 in `confirm_core.py`), so the DEMO orphan sweep could act on SHADOW approvals. The compose stack has one `postgres` service.

Alternatives: (a) a second database for the live process: no code change in the reader, but a second volume, a second backup target and a second migration run to look after. The research suggests this only if the reader change turns out to be large.

Undo cost: low to medium. A reader filter is small. Moving to a second database later means a data move.

Plans that depend on it: 24-08.

Research: C-7, A10, OQ-6.

Answer: (blank)

---

## Q9 What happens after a failed post-fill liquidation check (OQ-7, C-10, CONTEXT D-24 versus D085 O-4)

Conflict, stated plainly: the first context draft (D-24, O-3) says "alert and enter SAFE_MODE, no automatic close". Your recorded decision D085 O-4 (2026-10-24) says the policy is `CLOSE_POSITION` and that the Phase 24 composition must pass `CLOSE_POSITION` to the protection coordinator.

Recommendation: follow D085, as research item R-1 says. The composition passes `CLOSE_POSITION`; an alert is also sent. The recorded owner decision wins over a draft default.

Why: D085 is your decision with your words; the context default was written automatically as a placeholder and was marked overridable. A position that already fails the liquidation check is the case where waiting costs the most.

Alternatives: (a) alert and SAFE_MODE without closing, as the draft says: leaves the exposure open until you act; you would have to override D085 with a new DECISIONS row.

Undo cost: low. It is one constructor argument plus the tests that pin it.

Plans that depend on it: 24-16.

Research: C-10, OQ-7, R-1.

Answer: (blank)

---

## Q10 SHADOW money text (O-6, D-19, P23-R1)

What the files say: `.planning/STATE.md` still lists plan 16-43 as the next step on the soak host, and the Phase 16 evidence folder shows that the soak is running. The epoch was pinned on 2026-10-25 (`16-43-freeze-first-clean.md`, hourly freeze checks clean), and one incident was recorded on 2026-10-27 (`16-43-ws-silence-2026-10-27.md`, seven restarts, then healthy). The soak image was built from commit 6f73e5b. The SHADOW alert text is pinned by tests (`tests/test_paper_shadow_*.py`, `test_phase23_gate.py` invariant 7b), and Phase 23 verification (R-1) left the money block for SHADOW to Phase 24.

Recommendation: because a soak is running and its image and tests pin the text, ship the SHADOW money block as a NEW text version and keep the old pins untouched. Do not edit the SHADOW text in place. If you would rather end the soak first, the in-place change with new golden fixtures becomes possible.

Why: changing the text in place would break the old pins and make the running soak's evidence harder to compare with its own history. A new version keeps both.

Alternatives: (a) change in place with new fixtures: simpler code, only after the soak is stopped. (b) Leave SHADOW without a money block: you already accepted this once (R-1), at the cost of SHADOW messages not matching DEMO messages.

Undo cost: medium to high. SHADOW text pins and soak evidence are what is at stake.

Plans that depend on it: 24-09.

Research: D-19, P23-R1, O-6.

Answer: (blank)

---

## Q11 Heartbeat shape (OQ-8, R-8, D-30)

Recommendation: add `deploy/heartbeat.sh --target live`, one external healthchecks.io check per process (collector, paper, live), each with its own secret URL.

Why: the shipped design already has one check per target (`--target collector` and `--target paper`) with its own URL file, credential and unit. A fourth check is the same pattern, and a separate check tells you which process is down. The roadmap wording "one sender covers every process" is met by having one check per process.

Alternatives: (a) one combined check that is green only when every process is healthy: a single alert cannot tell you which process failed, and the paper soak host has no live process.

Undo cost: low. Another URL and another timer.

Plans that depend on it: 24-24.

Research: OQ-8, R-8.

Answer: (blank)

---

## Q12 Where the limits files live in the container (OQ-9, C-8)

Recommendation: bake `config/execution` and `config/binance` into the image, the same way `config/paper` is baked in.

Why: the image currently lacks both files, so the live process could not load its limits. Baking them in means the image hash covers the decision surface: a changed number is a rebuilt and re-pinned image, and nobody edits a number on the host by hand.

Alternatives: (a) a read-only mount from the host: no rebuild for a number change, but the file on the host is then not covered by the image hash.

Undo cost: low. The tests `test_deploy_images` and `test_deploy_compose` are amended either way.

Plans that depend on it: 24-25.

Research: C-8, OQ-9.

Answer: (blank)

---

## Q13 How the application revision gets into `--healthcheck` (OQ-10, C-9, D-31)

Recommendation: stamp the revision at image build time through a build argument that becomes an environment variable in the image; `--healthcheck` prints it together with `sys.version`. `read_code_version` stays for development checkouts.

Why: OPS-04 requires the Python version and the git revision in the health output. Inside the container there is no `.git` directory (`.dockerignore` excludes it) and no git program (the base image is `python:3.13.15-slim-bookworm`), so asking git at run time cannot work.

Alternatives: (a) copy `.git` into the image: large, leaks history, breaks the clean-tree rule. (b) Generate a version file during the build: equivalent; the build-argument form is the smaller change.

Undo cost: low.

Plans that depend on it: 24-25.

Research: C-9, OQ-10.

Answer: (blank)

---

## Q14 The two verification flags (O-4, D-23, C-10, CONTEXT D-23 versus D086)

Conflict, stated plainly: the first context draft (D-23) says to set `LIVE_NET_PNL_SEMANTICS_VERIFIED` from one Demo fill. Your recorded decision D086 O-4 says the flag stays False until a DECISIONS row says otherwise, with the check done by one small mainnet trade at the Phase 26 canary.

Recommendation: follow D086. Record the Demo fill comparison as evidence only; the flag stays False until the Phase 26 canary. `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` is already True (D085) and stays.

Why: Demo and mainnet may treat `realizedPnl` and commission differently; a wrong True would hide a loss in live results. Your own decision asked for the mainnet sample.

Alternatives: (a) set it from the Demo sample: needs a new DECISIONS row that overrides D086 in your words.

Undo cost: low (a constant and a row).

Plans that depend on it: 24-29 (the evidence record) and 24-31 (the documents).

Research: C-10.

Answer: (blank)

---

## Q15 Restart policy of the live service (O-2)

Recommendation: keep `restart: "no"` for the live service until the first clean Demo run, then you switch it to `unless-stopped` yourself.

Why: a process that restarts by itself after a crash can hide a real fault, and the first runs should be watched. The refusal path holds the process instead of crash-looping, so a refusal is still visible to the heartbeat.

Alternatives: (a) `unless-stopped` from the start: less manual work, but a start-up fault could repeat unseen.

Undo cost: low. One line in `docker-compose.yml`.

Plans that depend on it: 24-30 and 24-35.

Research: CONTEXT O-2, D-01.

Answer: (blank)

---

## Q16 Exact signed-quantity compare (O-5)

Recommendation: keep the D-01a bound check in Phase 24 and revisit the exact signed-quantity compare in Phase 25, when Order and fill rows have real Demo data.

Why: the exact compare needs the Order, Fill and Position rows to be written by the stream first (Q3), and there is no Demo data to test it against yet. The bound check is already accepted.

Alternatives: (a) add the exact compare now: more code before any data exists to validate it; it could raise false SAFE_MODE entries.

Undo cost: low.

Plans that depend on it: none changes in Phase 24 (24-19 and 24-20 keep the bound check; the exact compare is a Phase 25 question).

Research: CONTEXT D-10 and O-5.

Answer: (blank)

---

## Answer form

Reply "follow your recommendation" or list overrides as `Qn: option`. The numbers in `24-LIMITS-CHECKPOINT.md` may be answered separately and later ("limits: follow your recommendation"); they block only plan 24-06 and the first Demo run.
