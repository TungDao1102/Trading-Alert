# 16-DEC-S-B-interval-impl: authorization of plan 01 of quick 261014-nnl and re-fetch of the evidence

option: authorize-refetch
decided by: user
date: 2026-10-14
words:
lấy lại từ binance đi

context (recorded for audit): the words above are the user's whole reply. They answered the assistant's question of the same day, which offered (i) copying the three evidence files from the other machine or (ii) re-fetching them from Binance, and asked for an explicit go for plans 01 and 08. The user chose re-fetch. Earlier the user had written "nếu ok thì có thể bắt đầu execute" (conditional on the assistant's design check, which found the design sound and found the scratch evidence missing on this machine).

## Scope of this authorization (the assistant's reading; the user did not state a narrower or wider one)
- Authorized: plan 01 of quick 261014-nnl only (evidence provenance, evidence folder commit, `.gitattributes -text` line, the pure recompute module with its tests), and one re-fetch per evidence URL (one retry on a network error, then report). The re-fetched bytes must hash-equal the known sha256 of the lost scratch files; a mismatch stops the plan (history would then be revised and the bounds must be re-examined).
- NOT covered by these words (each needs its own go from the user): plans 02-06 code and test changes, plan 07 (version bump and regeneration), plan 08 (protocol v2.4.0 text), plan 09 (landing, `holdout_consumed.json` marker), and everything the decision record 16-DEC-S-B-interval.md lists as not authorized.
- Public data only: no key, no account, no `.env`. The requests are unauthenticated GETs to the public Binance futures market-data endpoints.

request_url A_klines_after_settlement: refetch
request_url B_indexPriceKlines_before_settlement: refetch
request_url F_indexklines_sample_day: refetch
dropped_at_planning: D_settlement_day_access_check.body.bin, E_free_day_0830_0900.ndjson (user, 2026-10-14, "ok theo khuyến nghị")
