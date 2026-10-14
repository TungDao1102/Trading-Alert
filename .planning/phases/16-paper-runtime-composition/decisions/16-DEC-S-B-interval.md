# 16-DEC-S-B-interval: REEFUSDT terminal settlement bounded by an interval (user decision)

date: 2026-10-14. Decided by: user. Design: `16-DRAFT-S-B-interval-design.md` (rev3).

## User's own words (verbatim, Vietnamese)
- "ok theo khuyến nghị của bạn" (adopting the four recommendations: widen bounds and store nominal; single record at the adverse bound with a fail-closed guard; cancel resting plans at terminal with a new kind flagged as an unverified assumption; pin the Validation/Holdout-only invariant with a test in v2.4.0).
- "tạo sub agent review đầy đủ rồi chốt luôn giúp tôi được không"
- "nếu bạn cũng recommend như thế thì: chọn (a), T=09:00Z và URL đúng, chốt đi"

## What the user decided
1. Option (a): settlement interval = union of the index-klines bound and the 09:00 trade candle (lower 0.000845, upper 0.000887), no proxy price.
2. T = 2025-01-22 09:00:00Z and the announcement URL `https://www.binance.com/en/support/announcement/detail/572715f2d96e47769ebbb967c2a6e445` are confirmed by the user as correct. This closes the "Still open" item of `16-DEC-GAP-REASON.md`. The "no new positions from 08:30" sentence stays unverified and unused.
3. The design of `16-DRAFT-S-B-interval-design.md` rev3 is closed, including the reviews' fixes: separate manifest entry `terminal_settlements` (TerminalDeclaration keeps its four fields), optional key in `backtest-case/2` (no `/3`), SETTLEMENT counted apart from "closed trade", manifest guard (settlement not at or after validation_start), one Holm over 48, `SIMULATOR_SEMANTICS_VERSION` 2.1.0 and protocol v2.4.0 as a separate amendment.

## Evidence and limits (not decisions)
- Two independent model reviews (agents a87c123628b2bb737, adb512e1ce8e4f526; verdict SOUND WITH FIXES, fixes applied). Model output, not reviewer authority; the reviewer did not review this closed design.
- The settlement formula, tick rounding and equal weighting remain unverified assumptions, stated as such in the manifest condition text.

## Still NOT authorized (separate approval required)
Code changes, version bumps, protocol v2.4.0 text, manifest freeze (16-37 Task 3), O-03/16-46, any Holdout read, ExperimentRecord, editing `holdout_consumed.json`, commits of these two files.
