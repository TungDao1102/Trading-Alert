# Operations Runbook

## 1. Purpose

This is the operational response guide for incidents involving live approval mode, positions, orders, market data, or infrastructure.

The default objective is **preserve capital and state integrity**, not resume trading quickly.

## 2. Immediate emergency: SAFE_MODE

Trigger when:

- state cannot be reconciled;
- market data is stale;
- protective orders are missing or uncertain;
- duplicate execution is suspected;
- exchange/API behavior is unexpected;
- database state is corrupt or unavailable.

Actions:

```text
1. Set SAFE_MODE.
2. Block new ENTRY orders (protective and reduce-only orders remain allowed, D034).
3. Verify Binance positions directly.
4. Verify open normal orders.
5. Verify open algo/conditional orders.
6. Verify each live position has the expected protection; a missing protection goes to section 3.
7. Reconcile local state.
8. Only then consider resuming.
```

## 3. Position without confirmed stop

```text
SAFE_MODE
→ alert immediately
→ query Binance authoritative position
→ query protective/algo orders
→ if stop is absent or canceled, automatically re-place it at the original plan SL after risk validation (never wider)
→ if the SL is rejected or not acknowledged, close the position with a reduce-only order, then send a HIGH alert
→ manual intervention is optional, not required
```

The automatic ladder is per D034: the operator works full-time and cannot be assumed to react within minutes.

**Implementation status:** the ladder above is the target behaviour (D034) and is built in Phase 20 (EXEC-06, OPS-05). Until then the system does not re-place a stop-loss or close the position by itself: on an entry without a protective stop it enters SAFE_MODE and alerts, and the operator must place the stop-loss or close the position manually on the exchange. Do not wait for an automatic action.

Never assume a locally stored order ID means the exchange order exists.

## 4. Orphan protective orders

Definition:

> A protective order remains active when its associated position is already zero or the plan is otherwise closed/invalid.

Action:

```text
identify orphan
→ verify position = zero
→ cancel associated protective/algo orders
→ journal cancellation
→ re-scan for remaining orphan orders
```

This must run both on event-driven reconciliation and periodic sweeps.

A protective stop paired with a still-working ENTRY order is not an orphan: the position is zero only because the entry has not filled yet, so the sweeper must leave that stop in place (F-401, D034).

## 5. Suspected duplicate approval/order

```text
SAFE_MODE
→ do not retry blindly
→ look up approval token/hash
→ inspect clientOrderId/algoClientId/exchange order state
→ reconcile
→ continue only when unique execution intent is established
```

## 6. Telegram callback replay

A repeated callback for the same approval token must return the current state.

It must never create another execution intent.

## 7. Market feed stale

Trigger when:

```text
now - last_expected_closed_candle > configured freshness threshold
```

Action:

```text
NO NEW SIGNALS
NO NEW ENTRY ORDERS
→ reconnect/re-bootstrap
→ validate candle continuity
→ resume only after health check
```

## 8. WebSocket disconnect

For every reconnect:

```text
reconnect
→ refresh server time if needed
→ bootstrap authoritative account/market state
→ compare local state
→ restore subscriptions
→ verify latest closed candle
→ resume
```

## 9. Database failure

```text
SAFE_MODE
→ block new entry orders only
→ a database failure must not prevent risk-reducing actions (D034)
→ preserve existing exchange-side protection
→ restore DB or switch to read-only monitoring
→ reconcile after recovery
```

## 10. Binance API degradation

Do not infer absence of an order from a timeout.

Use query/reconciliation before retrying signed order requests.

## 11. Backup and restore

At minimum:

- automated PostgreSQL logical backup or equivalent;
- encrypted backup copy outside the primary VPS/host;
- retention policy;
- periodic restore drill.

The collected OI/time-series dataset is considered irreplaceable research data.

A backup is not considered valid until a restore test succeeds.

## 12. Manual close

A manual position close must be explicit and recorded as:

```text
ManualExit
actor
reason
requested_at_utc
exchange_confirmation
```

After manual close, the reconciliation process must cancel orphan protective orders.

## 16. Image and action pins

Every base image is pinned by exact tag plus the multi-architecture index digest, every GitHub Action by full commit SHA, and uv and Python by exact version (D050; 13.1 D-05). The values below were read from the registries and from `git ls-remote` on 2026-10-01 (research session, re-read when plans 02 and 03 were executed; method in `SOURCES.md`, "Facts verified for Phase 13.1"). `tests/test_deploy_docs.py` parses these tables and fails when they differ from what `Dockerfile`, `docker-compose.yml`, `.github/workflows/*.yml`, `tests/docker_helpers.py`, `tests/fixtures/cutover/Dockerfile.sshd` and `.python-version` actually use, so the table and the files can only move together.

| Image | Tag | Digest | Used in |
| --- | --- | --- | --- |
| python | 3.13.15-slim-bookworm | sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 | Dockerfile, tests/fixtures/cutover/Dockerfile.sshd |
| postgres | 17.11-bookworm | sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652 | docker-compose.yml, .github/workflows/ci.yml, tests/docker_helpers.py |
| uv | 0.12.21 | sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 | Dockerfile |
| rclone | 1.75.1 | sha256:45401ad7410db1d67ffdb58e19059ad20b0d8e0285a60e38bbec55cc1019c7a5 | Dockerfile, tests/docker_helpers.py |

| Tool | Version | Used in |
| --- | --- | --- |
| uv | 0.12.21 | `version:` of every `astral-sh/setup-uv` step in the four workflows; equals the uv image tag |
| python | 3.13.15 | `.python-version` (read by CI) and the python image tag |

| Action | Tag | Commit SHA |
| --- | --- | --- |
| actions/checkout | v7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| actions/setup-python | v7.0.0 | 5fda3b95a4ea91299a34e894583c3862153e4b97 |
| astral-sh/setup-uv | v10.2.0 | c18668ad3cf93ea998bef934396af7bb5c839dc7 |
| actions/cache | v6.1.0 | 55cc8345863c7cc4c66a329aec7e433d2d1c52a9 |
| actions/upload-artifact | v7.0.1 | 043fb46d1a93c77aae656e7c1c64a875d1fc6a0a |

`actions/cache` covers both the `restore` and the `save` sub-actions. The pinned `docker compose` and `docker` versions on a host are whatever Docker's apt repository serves at bootstrap time; they are not pinned (bootstrap installs the current packages).

### 16.1 Reading the pins

`deploy/refresh-pins.sh --list` runs offline and prints every pin parsed from the repository files, one line per image as `<name>:<tag>@sha256:<digest>`, then `uv-version`, `python-version` and one `<owner/repo>@<sha> <tag>` line per action. A test proves that output equals the tables above.

### 16.2 Deliberate refresh procedure

Bumps are never automatic (automatic image and action bumps are a deferred idea, D050). To refresh:

1. Run `deploy/refresh-pins.sh --lookup`. It asks each registry (anonymous token, then a HEAD request for `docker-content-digest`) and `git ls-remote` for the current value and prints `unchanged` or `MOVED` next to every pin. It needs `curl` and `git`, reads only, and never edits a file.
2. Read the release notes of every moved item before accepting it (uv, Python, PostgreSQL 17 minor, rclone, each action).
3. Change every occurrence and this section's tables in one commit: `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `registry-gate.yml`, `research-gate.yml`, `paper_freeze_check.yml`, `tests/docker_helpers.py`, `tests/fixtures/cutover/Dockerfile.sshd`, `.python-version`. Use the index digest of the tag (it is stable across amd64 and arm64), not a per-architecture digest.
4. Run `uv run pytest tests/test_deploy_docs.py tests/test_deploy_images.py tests/test_deploy_workflows.py`, then let CI build and run the docker job before deploying. After a Python or PostgreSQL major or minor change, rehearse `deploy/update.sh --ref <tag>` on a non-production host first.

The single conscious exception to D-05 is `postgresql-client-17` in the `ops` image target. It comes from the PostgreSQL project's apt repository (key fingerprint checked at build time) and floats within major 17 by design, because that repository drops old minor versions and a pinned minor would break the image build. The server image stays pinned. A `pg_dump`/`pg_restore` 17 client must be at least as new as the 17 server.
