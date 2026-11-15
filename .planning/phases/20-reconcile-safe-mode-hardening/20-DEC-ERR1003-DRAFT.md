# 20-DEC-ERR1003-DRAFT: proposed D-10 exception for the HTTP 418 ban end time (draft for the owner)

Status: ACCEPTED as D083 on 2026-10-22; text unchanged. The owner's instruction of 2026-10-22 ('làm 1 và 2 trước đi') adopted the assistant's recommendation, with the condition that the clock-margin key stays NOT_CONFIGURED until the owner sets it; nothing is built; build in Phase 24. Earlier the same day the owner agreed with the direction ("ok tôi đồng ý với khuyên nghị của bạn").

## Problem

D072 (2026-10-16, `18-DEC-O-18-01.md`) sets the wait after an HTTP 418 without a usable `Retry-After` to 259200 s (3 days). The Futures pages read on 2026-10-22 (`usds-margined-futures/general-info`, `futures-data/general-info`) do not mention `Retry-After` at all `[DOC]`. The Spot page does ("A Retry-After header is sent with a 418 or 429 responses") `[DOC]`, but Spot is not Futures. So the 3-day fallback is the expected path, and a first ban of a few minutes would block REST for 3 days. The documented range is "from 2 minutes to 3 days" `[DOC]`; no source read reports how long any real ban lasted `[NOT_TESTED]`.

## Proposed text

1. Precedence stays: a valid `Retry-After` (capped by `signed_calls.rate_limit_retry_after_cap_seconds`) first.
2. Without it, and only when the answer is HTTP 418 AND the error CODE is -1003 (classified by code, never by text), the gate may take the ban end time from the response body. It extracts exactly one integer of 13 digits that follows the literal `IP banned until ` in the `msg` field, read as epoch milliseconds. Nothing else in the text is read, kept or logged; the text never classifies anything.
3. The extracted time is accepted only if it is in the future against the injected clock and not later than `now + 259200 s`. Anything else (no match, two matches, past, too far) is ignored and the 259200 s fallback applies.
4. The accepted time is padded by an owner-set margin for clock difference (new key, `NOT_CONFIGURED` until the owner sets it; no number is proposed here). The restriction never ends earlier than the padded time.
5. The result is stored in the gate state file of plan 20-07 like any other deadline, so a restart keeps it; the alert on entering the ban carries the deadline.
6. This is an exception to D-10 ("message text is never parsed") limited to point 2. It is a NEW owner policy, not part of D072.

## Evidence

- Third-party sample, not Binance documentation: ccxt issue 23970 quotes `{"code":-1003,"msg":"Way too much request weight used; IP banned until 1728708414116. Please use WebSocket Streams for live updates to avoid bans."}` with a 418. The number is epoch milliseconds. The issue does not say Spot or Futures and shows no headers `[DOC, third party]`.
- The error-code page read on 2026-10-22 gives a second wording, "Way too many requests; IP banned until %s", and does not give the format of `%s` `[DOC]`. The two texts differ, so point 2 anchors on the shared literal `IP banned until ` only.
- No text in either source says how a ban escalates between 2 minutes and 3 days `[DOC]`.
- Developer-forum and issue-tracker searches found no report of an observed ban length (2026-10-22).

## Open items for the owner

- The clock margin number of point 4.
- Whether a Futures `Retry-After` should be looked for in the first real 418 (it must not be provoked; if one ever happens the evidence record is kept).
- The build is a later plan. Suggested home: with the REST gate composition (Phase 24), tests using both texts above. The remote clear command (Phase 23, `[P20-OPS-REMOTE]`) stays the way to end a wrong long wait without ssh.
