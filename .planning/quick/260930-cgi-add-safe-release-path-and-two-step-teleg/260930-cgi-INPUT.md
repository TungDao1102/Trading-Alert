# Quick task input: safe release path + two-step Telegram confirm (260930-cgi)

On 2026-09-30 the user approved the following. Test on the Binance sandbox until the system is bug-free before any real order; profit is not the concern here. Add an approve-without-real-order ("shadow") mode so history is recorded early. Add a second Telegram confirmation step so that a mis-tapped APPROVE never places an order.

All edits are exact text operations. Keep CRLF line endings as they are in each file. Use explicit `git add <paths>` only. NEVER stage `.planning/state.json` or `.gsd/`. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Part A — docs/DECISIONS.md: append two rows after D039

Keep the table format `| ID | Decision | Status | Rationale |`. Each row is a single line and contains no `|` inside a cell.

```
| D040 | Safe release path: SHADOW → DEMO → CANARY → LIVE, no stage skipped, each stage with written exit criteria. SHADOW: signals and APPROVE/SKIP decisions are journaled with simulated fills on real market data; no trade-capable API key is loaded and no order adapter is constructed. DEMO: APPROVE+CONFIRM places orders on Binance Demo Trading (demo-fapi.binance.com); an automated demo scenario suite passes and a multi-week demo soak shows zero unexplained divergences, zero unprotected positions and zero duplicate entries. CANARY: mainnet read-only key verifies real exchangeInfo, commission, mark price and balance; then a dedicated small isolated sub-account (order of USD 50–100, minimum size) trades while the operator watches. LIVE only after CANARY exit criteria are met. | Accepted (2026-09-30, user) | User requirement: prove the system bug-free on the sandbox before real money, because the demo differs from production and a production bug is costly; record approval history early without real orders. Audit refs F-501, F-104, F-124, F-961, F-953. |
| D041 | Two-step Telegram confirmation. APPROVE never places an order: the bot edits the message into a confirmation card (mode SHADOW/DEMO/LIVE, symbol, side, quantity, notional, estimated loss at SL, current mark price vs entry/SL, remaining validity) with CONFIRM and CANCEL buttons. Only CONFIRM triggers placement. The confirm token is separate from the approval token, single-use, bound to the same authorized user id and plan hash, and expires after a short TTL (default 60 s, configurable). CANCEL or expiry places nothing and is journaled. All pre-placement checks re-run at confirm time. The same two-step flow runs in SHADOW (for realistic delay measurement) but never places orders. | Accepted (2026-09-30, user) | User requirement: prevent an accidental APPROVE tap from placing an order immediately. Complements APRV-01/APRV-02 and audit F-508, F-405, F-509, F-007. |
```

## Part B — .planning/ROADMAP.md edits

The phases are renumbered: the old 25 (Go-Live Readiness Gate) becomes **26**, the old 26 (Configurable Quote Asset) becomes **27**, and a NEW **Phase 25: Binance Demo Integration Test Campaign** is inserted. Phases 1–24 keep their numbers.

### B1. Overview paragraph

- Replace the line `- old 17 → 26` with `- old 17 → 27`.
- Replace the line `- Live enablement (25) requires 11–24 complete.` with:
  `- Live enablement (26) requires 11–25 complete, and follows the D040 release path SHADOW → DEMO → CANARY → LIVE.`
- In the sentence `Phases 11–26 below replace the earlier backlog-promoted phases 11–17 and carry their scope forward:`, change `11–26` to `11–27`.

### B2. Phase list

Replace the two lines starting with `- [ ] **Phase 25: Go-Live Readiness Gate**` and `- [ ] **Phase 26: Configurable Quote Asset (USDC readiness)**` with these three lines:

```
- [ ] **Phase 25: Binance Demo Integration Test Campaign** - Automated failure-scenario suite on Binance Demo, APPROVE+CONFIRM→demo orders, multi-week demo soak (D040)
- [ ] **Phase 26: Go-Live Readiness Gate** - Affirmative enablement gate, verification closure, real backups, CI, mainnet read-only check + small canary (D040)
- [ ] **Phase 27: Configurable Quote Asset (USDC readiness)** - Remove USDT hard-coding; deliberate USDC evaluation (was Phase 17)
```

Also update the Phase 16 and Phase 23 list lines:

- Replace `- [ ] **Phase 16: Paper Runtime Composition** - Runnable paper process (M3), fixed WS await, simulated fills, measured approval delay; soak can start` with:
  `- [ ] **Phase 16: Paper Runtime Composition + SHADOW Approval Mode** - Runnable paper process (M3), fixed WS await, simulated fills, SHADOW APPROVE/SKIP journaled with no order path (D040); soak can start`
- Replace `- [ ] **Phase 23: Telegram Approval Hardening + Money Amounts** - User-id auth, working SKIP, keyboard removal, $ amounts in messages (was Phase 16)` with:
  `- [ ] **Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts** - User-id auth, working SKIP, APPROVE→CONFIRM card (D041), keyboard removal, $ amounts (was Phase 16)`

### B3. Phase 16 details

- Heading: `### Phase 16: Paper Runtime Composition` becomes `### Phase 16: Paper Runtime Composition + SHADOW Approval Mode`.
- Goal line: replace it with
  `**Goal**: A runnable paper process observes the corrected families forward, so the wall-clock-bound soak can finally start. The operator can already APPROVE/SKIP (with the D041 confirm step) in SHADOW mode to build a decision history, with no possible path to a real order (D040).`
- After success criterion 4, add:

```
5. SHADOW mode (D040): SIMULATE/APPROVE messages are clearly labelled "SHADOW — no real order"; APPROVE → CONFIRM (D041) / SKIP / expiry are journaled with timestamps and approval delay; each confirmed plan gets a simulated position using the Phase-14 fill semantics on live market data, and the journal reports system vs user vs opportunity outcomes (F-961).
6. Hard isolation: in SHADOW the process loads no trade-capable API key and never constructs an order adapter; a test proves that no code path from a SHADOW confirm reaches `execute_approved_plan` or any order endpoint.
```

- Audit refs line: append `, D040, D041`.

### B4. Phase 23 details

- Heading: `### Phase 23: Telegram Approval Hardening + Money Amounts` becomes `### Phase 23: Telegram Approval Hardening + Two-Step Confirm + Money Amounts`.
- Goal line: replace it with
  `**Goal**: Only the authorized user in a private chat can approve. SKIP works. An APPROVE tap alone never places an order: a second CONFIRM step on a confirmation card is required (D041). Decided messages cannot be tapped again. Every SIMULATE/APPROVE message shows the money at stake.`
- After success criterion 3, add:

```
4. Two-step confirm (D041): APPROVE edits the message into a confirmation card (mode SHADOW/DEMO/LIVE, symbol, side, quantity, notional, estimated loss at SL, current mark price vs entry/SL, remaining validity) with CONFIRM/CANCEL. Only CONFIRM triggers placement. The confirm token is distinct, single-use, bound to the same user id and plan hash, with a short TTL (default 60 s); CANCEL/expiry places nothing and is journaled; pre-placement checks re-run at confirm time. Tests cover: double-tap, replayed CONFIRM callback, CONFIRM after TTL, CONFIRM by another user, CONFIRM after the plan expired or price crossed SL.
```

- Audit refs line: append `, D041`.

### B5. Phase 24 details

- In success criterion 1, replace `   - Telegram bot runner (APPROVE → \`execute_approved_plan\`);` with `   - Telegram bot runner (APPROVE → CONFIRM → \`execute_approved_plan\`, D041);`.
- In success criterion 2, replace `   - signal → approve → entry → SL/TP;` with `   - signal → approve → confirm → entry → SL/TP;`.

### B6. Replace the old Phase 25 and Phase 26 detail sections

Replace everything from `### Phase 25: Go-Live Readiness Gate` up to, but not including, `## Progress` with the following. It is the three sections, verbatim.

```
### Phase 25: Binance Demo Integration Test Campaign

**Goal**: The complete system is proven correct and robust on Binance Demo Trading (D040 DEMO stage) — including failure paths — before any real money. Profitability is explicitly out of scope; correctness is the only goal.

**Depends on**: Phase 24

**Requirements**: EXEC-01, EXEC-02, EXEC-03, APRV-01, APRV-02, OPS-01, OPS-02

**Success Criteria**:
1. An automated demo scenario suite runs against Binance Demo, separated from unit tests (e.g. `pytest -m demo`, credentials from env, never in CI by default). It covers at least:
   - happy path;
   - partial fill;
   - price crossed SL before placement (-2021);
   - SL rejected after fill → reduce-only close;
   - cancel racing a fill;
   - duplicate/replayed APPROVE and CONFIRM callbacks;
   - restart mid-flow (before entry ACK, between entry and SL, after fill);
   - WS disconnect and listenKey expiry;
   - clock skew;
   - rate limit / 418;
   - DB outage during a risk-reducing action;
   - DAILY_STOP;
   - liquidation-guard and available-margin rejections;
   - SAFE_MODE entry and operator exit;
   - foreign order and doubled position detected by reconcile.
2. APPROVE → CONFIRM places real orders on the Demo account through the same code path as live (only the endpoint and keys differ); journal, reconcile and alerts behave as in live.
3. A continuous demo soak of at least 3 weeks (duration pre-registered) ends with zero unexplained local-vs-exchange divergences, zero positions without an exchange-side SL, zero duplicate entries, and every alert explained. Any defect found restarts the soak clock after the fix.
4. Known demo-vs-mainnet differences (liquidity, fills, filters, fees, resets) are documented, so that CANARY (Phase 26) targets exactly what demo cannot prove.

**Audit refs**: F-501, F-104, F-124, F-702, F-701, F-401, F-126, D040, D041

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 25 to break down)

### Phase 26: Go-Live Readiness Gate

**Goal**: Live trading can only be enabled affirmatively: a family has passed under protocol v1.1.0, the paper exit gate is met, the demo campaign passed, all safety phases are verified, operations are real, and a small canary on the real exchange succeeded (D040). Otherwise it cannot be enabled.

**Depends on**: Phase 25

**Requirements**: GOV-01, OPS-01, OPS-02, PAPER-03

**Success Criteria**:
1. `enable()` requires a recorded passing candidate, a met paper exit gate, a passed Phase-25 demo campaign and a minimum capital. WITHIN_BUDGET is refused. The skipped Phase-10 review items WR-01/06/10/12/13 are resolved (F-953, F-105, F-960).
2. Phases 06–25 each have a VERIFICATION.md written after their last review-fix wave. The ~30 "requires human verification" fixes are confirmed, and 05-VERIFICATION is reopened (F-807, F-808, F-109, F-956). One-way checkpoints carry recorded human decisions (F-124, F-809).
3. Backups are off-host and encrypted, run on a schedule and follow a retention policy. The pg_dump URL is fixed. A real PostgreSQL restore drill passes (F-108, F-910, F-121, F-704).
4. CI on a real remote runs pytest, ruff, mypy and the registry gate, and all are green (F-101, F-605). The Docker healthcheck uses the venv. The images are pinned. Postgres binds to localhost. Secrets are scrubbed from errors (F-705, F-709, F-708).
5. CANARY (D040): a mainnet READ-ONLY API key (trade and withdraw disabled, IP-restricted) verifies real exchangeInfo filters, commission rates, mark prices and balances against what the system assumes; then a dedicated small isolated sub-account (order of USD 50–100, minimum size, leverage ≤ cap) executes a pre-registered number of trades with the operator watching, with zero divergences before full LIVE is allowed.

**Audit refs**: F-953, F-105, F-960, F-807, F-808, F-109, F-124, F-809, F-108, F-121, F-704, F-101, F-605, F-705, F-709, F-708, D040

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 26 to break down)

### Phase 27: Configurable Quote Asset (USDC readiness)

**Goal**: The quote/margin asset becomes configuration instead of a constant, so a USDC pair can be evaluated deliberately. This was former Phase 17; its priority is lowered below all safety work.

The following are hard-coded today:
- `LIVE_5` in `src/data/backfill.py:549` and `src/backtest/report.py:34`;
- `QUOTE_ASSET = "USDT"` in `src/analytics/live_outcomes.py:65`.

Switching an instrument requires a DECISIONS entry, new data, a new versioned parameter set with current fees, and re-research. USDT evidence does not transfer.

**Depends on**: Phase 26

**Requirements**: DATA-01, DOMN-02, BKTS-02, JRN-01

**Audit refs**: F-208 (live-5 list duplicated in 4 places), F-031

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 27 to break down)

```

### B7. Progress section

- In the execution-order line, change `→ 26.` to `→ 27.`, and change `No live order before Phase 25 is complete.` to `No real-money order before Phase 26 is complete (D040: SHADOW → DEMO → CANARY → LIVE).`
- Update the progress table rows:
  - Replace the row `| 16. Paper Runtime Composition | 0/TBD | Not started | - |` with `| 16. Paper Runtime Composition + SHADOW Approval Mode | 0/TBD | Not started | - |`.
  - Replace the row `| 23. Telegram Approval Hardening + Money Amounts | 0/TBD | Not started | - |` with `| 23. Telegram Approval Hardening + Two-Step Confirm + Money Amounts | 0/TBD | Not started | - |`.
  - Replace the two rows for 25 and 26 with:

```
| 25. Binance Demo Integration Test Campaign | 0/TBD | Not started | - |
| 26. Go-Live Readiness Gate | 0/TBD | Not started | - |
| 27. Configurable Quote Asset (USDC readiness) | 0/TBD | Not started | - |
```

## Part C — phase directories (use `git mv` / `git add`)

- `.planning/phases/26-configurable-quote-asset` → `.planning/phases/27-configurable-quote-asset`. Do this FIRST.
- `.planning/phases/25-go-live-readiness-gate` → `.planning/phases/26-go-live-readiness-gate`
- Create `.planning/phases/25-demo-integration-test-campaign/.gitkeep`, an empty file.

## Verification (automated)

- `docs/DECISIONS.md` gains exactly 2 added lines (D040, D041) and 0 deleted lines versus HEAD.
- `node ~/.claude/gsd-core/bin/gsd-tools.cjs query roadmap.analyze` reports 28 phases. Phase 25/26/27 have the new names and goals. Depends-on reads 25→Phase 24, 26→Phase 25, 27→Phase 26.
- `find-phase 25`, `find-phase 26` and `find-phase 27` resolve to the new directories.
- Relative to HEAD, `git diff .planning/ROADMAP.md` changes no line belonging to Phases 1–15, 17–22, or 07.1.
- `grep -c "D041" .planning/ROADMAP.md` ≥ 4, and `grep -c "D040" .planning/ROADMAP.md` ≥ 5.
