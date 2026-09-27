# Phase 8 — API Coverage Matrix

**Phase:** 8 (Approval + Reconciliation Hardening)
**Date:** 2026-09-27
**Detector:** manual scope run over ROADMAP Phase 8 section + CONTEXT D-01–D-05 + RESEARCH §Endpoint map

> Intel surface (`.planning/intel/API-SURFACE.md`) is empty (0 symbols, regex/JS-only extraction).
> Absence treated as *unknown*. Coverage below is decided from RESEARCH-verified
> installed-package probes (PTB 22.8 + SDK 17.4.0, method names confirmed via
> `dir()` this research session) and in-repo adapter reads.

## External integrations in scope

| # | External API | Library (locked) | Used by | Plan | Mode |
|---|--------------|------------------|---------|------|------|
| 1 | Telegram Bot API (send + inline-keyboard callbacks) | `python-telegram-bot` 22.8 (`Application`, `CallbackQueryHandler`, `query.answer()`, 64-byte `callback_data`) | APPROVE/SKIP intake, authorized-chat gate, 12-field alert keyboard | 08-02 | Polling `Application` behind `src/adapters/` only; core consumes Protocol-typed bot |
| 2 | Binance USDⓈ-M Futures REST — `GET /fapi/v1/openOrders` | `binance-sdk-derivatives-trading-usds-futures` 17.4.0 (`current_all_open_orders`) | Reconciler truth source ① open normal orders | 08-04 | REST fallback tick; WS user-data preferred realtime |
| 3 | Binance USDⓈ-M Futures REST — `GET /fapi/v1/openAlgoOrders` | same SDK (`current_all_algo_open_orders`) | Reconciler truth source ② open algo (conditional) orders | 08-04 | Same as above |
| 4 | Binance USDⓈ-M Futures REST — `GET /fapi/v1/positionRisk` | same SDK (`position_information_v3`) | Reconciler truth source ③ positions | 08-04 | Same as above |
| 5 | Binance USDⓈ-M Futures REST — `DELETE /fapi/v1/order` + `DELETE /fapi/v1/algoOrder` | same SDK (`cancel_order` [ASSUMED — re-verify sig], `cancel_algo_order`) | Orphan sweeper cancel-only path | 08-04 | Bounded batches; query-by-ID before retry (EXECUTION_SPEC §10) |
| 6 | Binance USDⓈ-M Futures REST — `GET /fapi/v1/algoOrder` | same SDK (`query_algo_order`) | No-blind-retry probe before cancel retry | 08-04 | Same as above |
| 7 | Binance user-data WS — `ORDER_TRADE_UPDATE` + `ALGO_UPDATE` (incl. `o.rm` rejections) | same SDK WS-stream models (`algo_update` / `algo_update_o` in manifest) | Opportunistic fast-path hints into the same compare function | 08-04 | Hints only; REST tick is authoritative truth |

## No-integration declarations

- **FastAPI inbound webhook for Telegram callbacks:** explicitly deferred per CONTEXT (V1 uses PTB polling). No FastAPI task appears in any Phase 8 plan.
- **Live credential paths (Telegram token, Binance keys):** operator-provisioned; all Phase 8 tests use the fake-`TelegramBot` seam + fake-exchange adapter + recorded fixtures. Live wiring is a `checkpoint:human-verify` gate, never a unit-test dependency.
- **No new PyPI packages:** stdlib (`hashlib`/`secrets`/`hmac`) + locked `tenacity`/`structlog`/SQLAlchemy only (RESEARCH §Package Legitimacy Audit — zero new packages).

## Per-plan API touch summary

| Plan | External calls | Fake/seam used in tests |
|------|---------------|-------------------------|
| 08-01 approval core tracer | none (pure core) | n/a — no I/O |
| 08-02 callback intake + message | Telegram Bot API send/answer | Fake `TelegramBot` (Phase-7 seam); no network |
| 08-03 deterministic order IDs | none (pure derivation) | n/a — no I/O |
| 08-04 reconciler + sweeper + SAFE_MODE | Binance REST 6 methods above | Fake three-source exchange adapter with recorded calls |
| 08-05 drill harness | none directly (drives 08-01/02/04 fakes) | Injected faults only; never real unprotected exposure |

**Decision:** matrix decided — Phase 8 is an API-integrating phase with the seven rows above; seal permitted.
