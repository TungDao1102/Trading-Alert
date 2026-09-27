# Phase 7: User Setup Required

**Generated:** 2026-09-27
**Phase:** 07-paper-forward-observation
**Plan:** 07-04 (PAPER-03 — pinned-epoch freeze monitor + SIMULATE notify + soak readiness)
**Status:** Complete (operator smoke run 2026-09-27; WS leg blocked-follow-up — see Issues Encountered in 07-04-SUMMARY.md)

Complete these items for the Phase 7 paper soak to function. The agent automated everything possible (freeze monitor, journal-first notify, fixtures, tests, .env.example documentation); these items require human access to external dashboards/accounts.

## Environment Variables

| Status | Variable | Source | Add to |
|--------|----------|--------|--------|
| [x] | `TELEGRAM_BOT_TOKEN` | Telegram BotFather-issued token (https://t.me/BotFather) | `.env` |
| [x] | `TELEGRAM_AUTHORIZED_CHAT_ID` | Operator-provisioned allowlisted chat id (discover via `getUpdates`) | `.env` |
| [x] | `PAPER_DATABASE_URL` | Operator-provisioned `postgresql+psycopg://...` URL for the soak database (Compose PostgreSQL 17) | `.env` |

All three resolve off-source from the local gitignored `.env`. No literals in `src/` or `tests/` (grep-verified by executor Task 3).

## Account Setup

- [x] **Create Telegram bot via BotFather**
  - URL: https://t.me/BotFather
  - Steps: `/newbot` → name → username → copy token to `TELEGRAM_BOT_TOKEN`
  - Skip if: Already have a bot for this project

- [x] **Discover authorized chat id**
  - Send any message to the bot from the target chat
  - Run: `curl https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates`
  - Copy `result[0].message.chat.id` to `TELEGRAM_AUTHORIZED_CHAT_ID`
  - Note: For group chats the id is negative; for direct messages it is positive

## Dashboard Configuration

- [x] **Apply Alembic migrations to the soak database**
  - Command: `uv run alembic upgrade head`
  - Expected: 0001_baseline + 0002_domain_registry applied
  - Verified: 2026-09-27 (see `logs/paper/soak_smoke.log` env provenance section)

- [x] **Verify Compose PostgreSQL 17 is reachable**
  - Command: `docker compose ps postgres`
  - Expected: `postgres:17-bookworm` container running, port 5432 published

## Local Development

### PowerShell .env loader (Windows dev)

The repo's `.env` is gitignored. To load it into the current PowerShell session without leaking values into the shell history:

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^([^#][^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') } }
```

This sets each variable in the **Process** scope (current session only — does not persist to User or Machine). Verify with:

```powershell
$env:TELEGRAM_BOT_TOKEN.Substring(0,8) + '...'   # first 8 chars + ellipsis
$env:TELEGRAM_AUTHORIZED_CHAT_ID
$env:PAPER_DATABASE_URL -replace '://[^@]+@', '://***@'   # redact password
```

### Pre-soak smoke commands

Run from the repo root after loading `.env`. Append the dated entry to `logs/paper/soak_smoke.log` with timestamps for each check.

**1. REST klines (one page)**

```powershell
uv run python -c "from src.adapters.binance_rest import BinanceRestAdapter; from decimal import Decimal; from datetime import datetime, UTC; a = BinanceRestAdapter(); rows = a.klines(symbol='BTCUSDT', interval='1h', limit=5); print('rows=', len(rows), 'last_close_utc=', rows[-1].close_time_utc.isoformat())"
```

Expected: `rows= 5 last_close_utc= <ISO timestamp within last hour>`

**2. Journal round-trip (one PaperRecord)**

```powershell
uv run python -c "from src.paper.journal import assemble_paper_record, paper_records_digest; from src.paper.attribution import AttributionKind; from src.db.session import session_scope; from src.db.models import SignalRow; from datetime import datetime, UTC; from decimal import Decimal; sig_id = 'SMOKE-' + 'a'*64; with session_scope() as s: s.add(SignalRow(signal_id=sig_id, strategy_version='v2.0.0', parameter_set_id='trend-pullback/baseline-v3', parameter_set_hash='a'*64, symbol='BTCUSDT', source_timeframe='1h', source_candle_close_utc=datetime.now(UTC), setup_fingerprint='smoke', detected_at_utc=datetime.now(UTC), payload_json='{}')); s.commit(); print('inserted', sig_id); rows = s.query(SignalRow).filter_by(signal_id=sig_id).all(); print('read_back=', len(rows)); s.query(SignalRow).filter_by(signal_id=sig_id).delete(); s.commit(); print('cleaned')"
```

Expected: `inserted SMOKE-aaaa...`, `read_back= 1`, `cleaned`

**3. SIMULATE send (one Telegram message)**

```powershell
uv run python -c "import asyncio; from src.paper.notify import format_simulate, notify_simulate; from src.adapters.telegram_notify import TelegramBot; from decimal import Decimal; from datetime import datetime, UTC; from src.domain.enums import ApprovalAction; plan = {'symbol':'BTCUSDT','direction':'LONG','setup':'TREND_PULLBACK_LONG','entry_zone_low':Decimal('60000.00'),'entry_zone_high':Decimal('60100.00'),'stop_loss':Decimal('59500.00'),'take_profits':[Decimal('61000.00'),Decimal('62000.00')],'risk_reward':Decimal('2.0'),'risk_pct':Decimal('0.005'),'expiry_utc':datetime.now(UTC),'invalidation':'candle_close_below_59500','exposure':'0/3 positions open','reason_codes':['SETUP_DETECTED']}; text = format_simulate(plan, signal_id='SMOKE-sig', strategy_version='v2.0.0', parameter_set_id='trend-pullback/baseline-v3', parameter_set_hash='a'*64); outcome = asyncio.run(notify_simulate(text=text, signal_id='SMOKE-sig', bot=TelegramBot())); print('outcome=', outcome)"
```

Expected: `outcome= NotifyOutcome(kind=<NotifyOutcomeKind.SENT: 'sent'>, signal_id='SMOKE-sig', error_class=None, attempts=1)` and a message arriving in the authorized Telegram chat.

**4. WS subscribe (one Live-5 1H stream)**

```powershell
uv run python -c "import asyncio; from src.paper.supervisor import PaperSupervisor; from src.adapters.paper_ws import PaperWsAdapter; from src.adapters.binance_rest import BinanceRestAdapter; ws = PaperWsAdapter(); rest = BinanceRestAdapter(); events = []; sup = PaperSupervisor(ws, rest, symbols=['btcusdt'], intervals=['1h'], on_closed_candle=lambda c: events.append(c)); asyncio.run(sup.start()); asyncio.run(asyncio.sleep(30)); asyncio.run(sup.stop()); print('events=', len(events))"
```

Expected: `events= >=1` (1H stream normally pushes every ~250ms; 30s window should yield many).

**KNOWN BLOCKER (2026-09-27):** This leg is currently BLOCKED — `PaperWsAdapter` and `PaperSupervisor` expose only `subscribe`/`reconnect`/`schedule_reconnect`/`close`; the SDK connect path was never wired. Live smoke delivered 0 events in 30s. Wave 1/2 tests use injected fakes. Soak must not start until a live WS smoke passes. See `07-04-SUMMARY.md` Issues Encountered for the follow-up routing.

## Verification

After completing setup, verify with:

```powershell
# 1. All three env vars resolve (redacted output)
$env:TELEGRAM_BOT_TOKEN.Substring(0,8) + '...'
$env:TELEGRAM_AUTHORIZED_CHAT_ID
$env:PAPER_DATABASE_URL -replace '://[^@]+@', '://***@'

# 2. No token literals in tree
git grep -nE 'TELEGRAM_BOT_TOKEN\s*=\s*[0-9]+:[A-Za-z0-9_-]+' src/ tests/   # expect: no matches

# 3. Alembic head
uv run alembic current   # expect: 0002_domain_registry (head)

# 4. Full test suite green
uv run pytest -q   # expect: all pass
```

Expected results:
- All three env vars print without error
- `git grep` returns no matches (secrets stay off-source)
- `alembic current` shows `0002_domain_registry (head)`
- Full test suite green (no regressions from the freeze + notify additions)

---

**Once all items complete:** Mark status as "Complete" at top of file. (Already complete as of 2026-09-27 — see `logs/paper/soak_smoke.log` for the dated smoke entry.)
