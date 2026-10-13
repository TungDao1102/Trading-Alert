# 16-37: REEFUSDT terminal time, user-supplied text from the Binance announcement page

date recorded: 2026-10-13
supplied by: user (pasted into the session; the user did not state which URL they opened, so the page is presumed to be the announcement in evidence/16-37-constraint-history.md line 67 and that is NOT verified by this record)

## Text as pasted by the user
Binance Futures will close all positions and conduct an automatic settlement on the REEFUSDT USDⓈ-M perpetual contract at 2025-01-22 09:00 (UTC). The contract will be delisted after the settlement is complete.

In addition, Binance Futures has adjusted the leverage and margin tiers of the REEFUSDT USDⓈ-M perpetual contract at 2025-01-15 07:30 (UTC). Please note that existing positions opened before the update will not be affected.

## What this confirms
- Settlement and delisting at 2025-01-22 09:00 UTC, in the user's own reading of the page. This agrees with the earlier fetch-tool summary and with the local data (last 1m bar 08:59Z, last 1h bar 08:00Z).
- The 07:30 UTC leverage/margin tier change on 2025-01-15 agrees with the earlier summary.

## What this does not confirm
- The pasted text has no "no new positions from 08:30 UTC" sentence. That time stays unverified and is not used by the declaration rule.
- The exact URL, and the page's publication time, are not part of the pasted text. The URL in the constraint-history evidence still comes from the fetch tool.
- Nothing is written to a manifest. terminal_at_utc and the URL remain the user's O-03b answer.
