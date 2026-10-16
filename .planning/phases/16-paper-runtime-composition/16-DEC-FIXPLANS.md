# 16-DEC-FIXPLANS: owner decisions for the gap-fix plans 16-55 to 16-61

decided by: user
date: 2026-10-16

words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

The reviewer text (pasted by the user on 2026-10-16, "Phase 16 - Owner decisions") is adopted as written, except where the seven corrections below amend it. This record authorizes nothing beyond what that text and the user's line state. It does not authorize live trading, Holdout use, parameter or strategy_version changes, or a push.

## Decisions adopted (summary of the reviewer text)

- 16-55 Q1: A, `restart: unless-stopped` plus a held (not exited) refused start; Q2: B, a separate paper heartbeat (interval 60 s, period 60 s, grace 120 s, separate secret URL); Q3: A, `--pin-epoch` pins and exits 0, then the managed service starts at once. The single-instance guard stays.
- 16-56 Q1: B, new key `health.feed_silence_timeout_seconds: 120` in `paper-runtime-v2.toml`; Q2: A, the loader rejects `minute_close_lag_seconds` = 0 (value 5 stays).
- 16-57 Q1: B, SHA-256 of the canonical, schema-validated effective values, refused on mismatch with exit 6 and the held state; the raw file hash is recorded for provenance only.
- 16-59 Q1: A, key `<epoch>/<as_of>-<sha12>/` for hourly and final bundles, create-only; Q2: B, merge run artifacts deduplicated by run id (derived file, originals kept).
- 16-60: Q0 accept 50 days; Q1 A (D072 = protocol v2.5.0 amendment, D073 = regeneration inventory and disposition of the original records); Q2 yes, change only `protocol_version` v2.4.0 to v2.5.0 in the Holdout marker (entries stay empty); Q3 A, `docs/research/experiments/research-run-1-v2-2-0/`; Q4 B, required sixth key `simulator_semantics_version: "2.2.0"` enforced by the runner.
- 16-61: fresh authorization for one regenerated run under simulator_semantics_version 2.2.0 / protocol v2.5.0 (3 families, 48 parameter sets, 5 windows, up to 240 records, 50-day price-only warm-up, no Holdout); the agent may write and commit the three new authorization files only after the runner enforces the sixth key and all gates pass; sequential runs in the order trend-pullback, breakout-retest, range-mr; the supersession wording for the original 240 records is the reviewer's paragraph, used verbatim in D073.
- B1-WR-09: wire `rest_backfill_depth_bars` (value 1500) into the REST backfill path in a separate plan, with a test and docs; B1-WR-04 and the 23 low items stay deferred; the two Phase 26 items stay deferred.

## Seven corrections by the assistant, adopted with the decision

1. 16-55 Q1: `unless-stopped` keeps a stopped state only after `docker stop` / `compose stop`; a runtime-initiated exit 0 would be restarted. The plan tests that case. The held refused-start state needs an explicit marker that makes the healthcheck report unhealthy (the existing probe only checks bar age, 3900 s).
2. 16-55 Q2 / 16-56 Q1: the paper heartbeat must be driven by the 120 s feed-liveness or loop-alive signal, not the 3900 s bar-age probe. A qualifying message is any frame on the connection, not per symbol. The user must provide a second secret heartbeat URL.
3. 16-59 Q2: GitHub keeps at most one pending run per concurrency group, so "queue so no required run is replaced" is not achievable. The requirement becomes: detect and record each missing tick explicitly; never infer a clean result from a missing artifact.
4. 16-59 Q1: with `sha12` in the key, re-exporting identical bytes hits the same key: identical bytes count as success, different bytes are an error.
5. 16-56 and B1-WR-09 land in one `paper-runtime-v2.toml`; the REST backfill wiring lands before the epoch is pinned.
6. D072 numbering: the Phase 18 worktree already holds a DECISIONS row D072. At integration the Phase 18 row is renumbered to the next free number; Phase 16 keeps D072 and D073.
7. 16-61: it must verify that the frozen manifest hash is valid under simulator 2.2.0 before writing any authorization file; if the exact expected hashes cannot be verified, stop.

## Not yet done

Nothing is implemented. Execution order stays 16-55, 56, 57, 58, 59, then the B1-WR-09 plan, 16-60, 16-43, 16-61, 16-44. Remaining owner inputs: the second secret heartbeat URL (before 16-43/EC2), and nothing else (the B1-WR-09 plan is now written as 16-62). On 2026-10-16 the user kept option B for 16-55 Q2: a separate paper heartbeat URL (user words: "giu phuong an B, lam tiep di").

## Amendment 2026-10-16 (user): freeze workflow queueing

decided by: user
words:
> Thêm queue: max cho workflow freeze, kèm ghi tick thiếu.

This amends correction 3. The GitHub concurrency documentation read on 2026-10-16 (not verified live) documents `queue: max` (up to 100 pending runs; invalid together with `cancel-in-progress: true`). Plan 16-59 adds `queue: max` beside `cancel-in-progress: false` in the freeze-check workflow and keeps the explicit missing-tick records; absence of an artifact is never read as clean. The first live run on GitHub is the proof that the key is accepted; the plan's workflow test only checks the text.

## Renumbering 2026-10-16

Bookkeeping only; the owner's decisions above are unchanged (owner informed 2026-10-16). Phase 18 was merged into develop first (merge 6610bd6) and holds the DECISIONS row D072 ("Phase 18 client configuration, user-data stream and exchange error taxonomy"), which keeps its number; docs/DECISIONS.md ends at D072 and gate DC-02 requires contiguous ids. Phase 16's two new rows are therefore:

- D073: protocol v2.5.0 warm-up amendment (named D072 in 16-60 Q1 above and in the reviewer text).
- D074: regeneration inventory and disposition of the original 240 records (named D073 in 16-60 Q1 and 16-61 above and in the reviewer text).

This replaces the integration step of correction 6: no Phase 18 row is renumbered. The text above and decisions/16-DEC-FIXPLANS-reviewer-text.md are not edited; where they name D072 or D073 for Phase 16, read D073 or D074. Plans 16-60 and 16-61 and ROADMAP.md use the new numbers, and every record that copies the owner's or reviewer's text verbatim adds the mapping line.
