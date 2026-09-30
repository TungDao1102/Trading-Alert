# Verification batch V2_execution — BLIND INPUT (claims + locations only)

## F-501
- Claimed severity: HIGH
- Claim: Every SL/TP placement is preceded by query_algo_order_by_client, which maps only an error containing '-2011'/'UNKNOWN_ORDER' to not-found. Officially, -2011 is CANCEL_REJECTED and the query-not-found code is -2013 (the algo not-found code is undocumented). Any other response makes the probe raise or report unknown, so no protective leg is ever placed and every live entry ends in ENTRY_WITHOUT_PROTECTIVE + SAFE_MODE + entry cancel.
- Expected behavior (per claimant): A never-placed xa- id is reliably classified as absent using the exchange's actual response (verified on testnet), so the SL is placed.
- Location(s): src/adapters/binance_usdm.py:858-877
- Component: binance_usdm.query_algo_order_by_client + manager._place_protective_leg

## F-502
- Claimed severity: HIGH
- Claim: Cancel errors containing '-2011' are treated as an 'already canceled' success, but Binance also returns -2011 ('open order not found in the orderbook') for FILLED or expired orders. When the SL fails after an entry fills immediately, expire_pending_entry journals post_cancel and returns NO_TRADE while a live position has no stop.
- Expected behavior (per claimant): On -2011, query the order by client id. If it is FILLED/PARTIALLY_FILLED, run the emergency path (reduce-only close or protect, plus an alert) and never journal post_cancel.
- Location(s): src/adapters/binance_usdm.py:933-943
- Component: binance_usdm.cancel_normal_order/cancel_algo_order + manager.expire_pending_entry

## F-126
- Claimed severity: HIGH
- Claim: EXEC-03 and Phase 8 SC4 ('retries, restarts and replayed events never create duplicate entry orders') are claimed, but approval consumption is explicitly not implemented. Deterministic clientOrderIds only deduplicate against the exchange while the first order is still open. After it fills or is canceled, re-running execute_approved_plan for the same approval (an at-least-once Telegram replay, or a restart) re-places the entry.
- Expected behavior (per claimant): TELEGRAM.md §3/§6 'Replaying an old approval must not place a fresh order'; EXECUTION_SPEC §7; ROADMAP Phase 8 SC4.
- Location(s): src/execution/manager.py:162-240
- Component: src/execution/manager.py execute_approved_plan

## F-951
- Claimed severity: HIGH
- Claim: Phase 8 D-04 claims the exchange dedups deterministic client IDs ('duplicate entry orders are structurally impossible') and explicitly rejects local already-sent state; Binance enforces newClientOrderId uniqueness only among OPEN orders, and execute_approved_plan does not consume the approval.
- Expected behavior (per claimant): Durable local execution-intent record keyed on approval/plan hash + role blocks any re-submission after the first send (Rule 28).
- Location(s): .planning/phases/08-approval-reconciliation-hardening/08-RESEARCH.md:268-305
- Component: Phase 8 D-04 / 08-RESEARCH

## F-603
- Claimed severity: HIGH
- Claim: No-duplicate-entry (EXEC-03, P8 SC4) validated only by ID-determinism tests and a fake that accepts unlimited identical submissions; calling execute_approved_plan twice places two entries.
- Expected behavior (per claimant): Double-invoke and restart tests asserting exactly one place_entry per approval, with a fake modeling Binance open-order-only clientOrderId uniqueness.
- Location(s): tests/test_execution_manager.py:79-136
- Component: tests/test_order_ids.py, tests/test_execution_manager.py FakeExecutionAdapter, 08-VALIDATION 8-0X-04

## F-702
- Claimed severity: HIGH
- Claim: Journal-first ordering means a DB/journal outage blocks every risk-reducing action. No cancel is sent by expire_pending_entry, cancel_untriggered_protectives or emergency_manual_close. LiveEnablementController.disable raises before flipping the flag. enter_safe_mode raises, which aborts execute_approved_plan before the acknowledged-but-unprotected entry is canceled.
- Expected behavior (per claimant): Safety actions (cancel entry, disable live, emergency close) reach the exchange regardless of journal health. The journal write is best-effort with a durable local fallback.
- Location(s): src/execution/manager.py:561-1330
- Component: execution/manager; execution/enablement; reconcile/safe_mode

## F-104
- Claimed severity: HIGH
- Claim: There is no Binance user-data stream client and no fill/trade query. No listenKey, no ORDER_TRADE_UPDATE/ALGO_UPDATE/ACCOUNT_UPDATE parsing, no userTrades. So `attach_protectives_to_fill(fill_events=...)` and `fold_fills` have no production source of fills. The requirement 'user-data WS preferred realtime' (AGENTS, PROJECT constraints, EXECUTION_SPEC §1/§6, PRODUCT_SCOPE §4, 08-CONTEXT D-03) never became a REQ-ID and is not in ROADMAP phases 11-17.
- Expected behavior (per claimant): EXECUTION_SPEC.md:22 'Monitor user-data events'; :89 'After entry fill, verify protective stop exists'; AGENTS 'User-data streams are the preferred realtime source for orders/fills/positions'; 'The reconciler/orphan-sweeper must parse ALGO_UPDATE'; 00_PRODUCT_SCOPE §4 'User-data stream monitoring for orders and positions'.
- Location(s): src/adapters/binance_usdm.py:526-1256
- Component: src/adapters/binance_usdm.py, src/execution/fill_monitor.py
