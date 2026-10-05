---
status: complete
quick_id: 261005-vb2
date: 2026-10-05
---

# Quick 261005-vb2: Demo not-found mapping (-2013)

**Finding:** the Phase 9 `far` dry-run ended ENTRY_WITHOUT_PROTECTIVE because Demo answers a missing algo order with `BadRequestError(status_code=-2013, 'Order does not exist.')` (read-only probe, 2026-10-05) and the adapter only mapped `-2011` / `UNKNOWN_ORDER`. This is audit finding F-501 / F-503, now confirmed on the exchange.

**Change:** `_is_order_not_found_error` in `src/adapters/binance_usdm.py` (int `status_code` in {-2013, -2011}; message fallback only when no int code). Used by `query_algo_order_by_client` and `query_order_by_client`. All other codes still raise. Cancel paths untouched.

**Tests:** `tests/test_adapter_not_found_mapping.py` (shape taken from the real exception; other codes and look-alike text still raise).

**Docs:** `09-EXCHANGE-FACTS.md` Fact 1 updated. Query Order on Demo remains unobserved.

**Next:** rerun `--scenario far` dry-run; no `--execute` yet.
