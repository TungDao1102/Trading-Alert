# Phase 16 research gaps: hand-off for a machine with internet access

Created 2026-10-07. This file is SELF-CONTAINED. The first research pass (`16-RESEARCH.md`) ran on a machine where several official pages returned HTTP 403, the Binance developer pages returned the landing page, and some facts could not be read. This file lists exactly what must be re-checked from official sources on a connected machine. Nothing here asks for a decision: it asks for facts with sources.

## How to use this file (for the person at the connected machine)

1. Open a Claude Code session on the connected machine. Paste the PROMPT block at the bottom into it, and give it this file (copy the file next to the session, or paste its content).
2. The session writes ONE new file named `16-RESEARCH-GAPS-RESULT.md`. It edits nothing else.
3. Copy `16-RESEARCH-GAPS-RESULT.md` back to the planning machine, into `.planning/phases/16-paper-runtime-composition/`. The planning machine then merges the confirmed facts into `16-RESEARCH.md` (changing `[ASSUMED]` into `[CITED]` with the read date) before planning starts.

## Project context (so the connected session understands what the facts are for)

A deterministic Binance USDⓈ-M Futures research and semi-automated execution system, Python 3.13, Decimal-only core. Phase 16 builds a runnable paper process that receives closed candles over WebSocket, journals decisions, simulates fills, and offers a SHADOW approval flow over Telegram (APPROVE then CONFIRM, no real orders). It will run on one AWS EC2 host in region ap-southeast-1 (Singapore) with an encrypted S3 bucket for backups and evidence, and a GitHub Actions workflow checks parameter-set immutability every hour. Hard rules of the project: facts about Binance, AWS, Telegram, rclone and GitHub come from the official documentation with the URL and the read date, never from memory; a connection error is retried once and then recorded, never worked around; money, risk and safety decisions are not made by the agent.

## Rules for the connected session

- Read official pages only (developers.binance.com, core.telegram.org, docs.aws.amazon.com, aws.amazon.com, docs.github.com, rclone.org). Third-party blogs are not sources.
- For every question give: the answer, the exact URL, the date read (UTC), a short verbatim quotation (at most 25 words) that supports the answer, a confidence label (CITED for text you read on the page, or UNVERIFIED if you could not read it), and which item of this file it answers.
- If a page fails (403, landing page, 404, timeout), retry ONCE, then record the URL, the error and what stays unverified. Do not guess, do not use memory, do not use another site for the same fact, and do not try to bypass the error.
- Do not change any repository file other than creating `16-RESEARCH-GAPS-RESULT.md`. Do not run trading code, never read `.env`, never use or paste any API key, bot token or AWS credential.
- Do not decide anything. If a page leaves a choice open, say so.

## Items to verify

### Binance (docs `developers.binance.com`, USDⓈ-M Futures)

- **G1. Kline stream payload.** Page: WebSocket Market Streams, Kline/Candlestick Streams (the first pass got the landing page twice; try the page tree under `https://developers.binance.com/docs/derivatives/usds-margined-futures/` and the URL shown by the site's own navigation). Confirm the exact payload field names and meaning for the open time, the close time, the closed-candle flag (`x`) and the update speed. Why: the runtime must evaluate only closed bars. Feeds `resync.py` and the closed-bar event rule.
- **G2. REST kline endpoint.** Page: Market Data, Kline/Candlestick Data. Confirm what `closeTime` means (the first pass saw `open + interval - 1 ms` in one live row and wants the documentation), the maximum `limit`, the weight by `limit`, and whether the last row can be an unfinished candle. Why: gap detection in `resync.py` currently assumes a close time on the exact boundary.
- **G3. Connection facts.** Pages: WebSocket Market Streams, general "Connect" information. Confirm (a) the 24-hour connection lifetime, (b) the ping/pong deadline, (c) the limit on NEW connection attempts per IP and per time window, (d) incoming message limit per connection, (e) the maximum streams per connection. (a), (b) and (d) were already read once; re-read and quote them, and find (c).
- **G4. Mark-price kline stream.** Does the USDⓈ-M documentation define a mark-price kline stream (and an index-price kline stream)? Give the page and the stream name if it exists. The installed SDK exposes none; the question is whether the exchange documentation does.
- **G5. Unauthenticated private path.** The installed SDK opens connections for the paths `market`, `public` and `private`. Does the documentation say what a connection to the `private` path does without a listen key? One sentence with the page.

### Telegram (`core.telegram.org`, python-telegram-bot docs)

- **G6. One poller per token.** What does the Bot API do when two processes call `getUpdates` with the same bot token (the documented error and its code)? What does the documentation say about using a webhook and `getUpdates` together?
- **G7. Rate limits.** The documented limits for messages per second to one chat, per group, and in total; and the documented behaviour on exceeding them (`retry_after`).
- **G8. Callback queries.** `answerCallbackQuery`: is it required, how long does a client wait without it, how long a callback query stays valid, and the maximum size of `callback_data` (the first pass has 1 to 64 bytes from python-telegram-bot docs; confirm on the Bot API page). `editMessageText` and `editMessageReplyMarkup`: constraints when the content is unchanged (error "message is not modified") and any time limit for editing.

### AWS (`docs.aws.amazon.com`, `aws.amazon.com`), region ap-southeast-1 where a price is asked

- **G9. S3 Object Lock enablement.** Can Object Lock be switched on for an EXISTING bucket, or only when the bucket is created? Is versioning required? State the page text.
- **G10. Object Lock retention.** Governance versus compliance mode: what each prevents and who can override. Is default retention set per bucket or per prefix, and does a default retention apply to objects uploaded later? What happens to a delete request on a locked object (delete marker versus error)? Are Object Lock or Versioning separately charged?
- **G11. S3 default encryption.** What is the current default encryption of a new bucket, and how does a bucket policy or setting require SSE-KMS instead? Is there a charge difference?
- **G12. EBS encryption.** Is EBS encryption on by default in a new account or region, and how is "encrypt by default" turned on? Which key is used by default?
- **G13. Prices in ap-southeast-1, read from the official price pages (record the page and the date; do not estimate).** For these example instance types only (examples for comparison, NOT a choice): `t3.micro`, `t3.small`, `t4g.small`, `t3.medium`. On-demand Linux hourly price. EBS gp3 per GB-month. S3 Standard per GB-month storage, PUT/LIST and GET request prices, data transfer out. Elastic IP price when attached to a running instance. AWS Budgets price for an alert. If the pricing pages cannot be read, say so; do not use remembered numbers.
- **G14. EC2 network and clock.** The documented default time service on Amazon Linux and on Ubuntu images (chrony and the Amazon Time Sync Service endpoint), in case the host runs a different distribution than assumed.

### GitHub (`docs.github.com`)

- **G15. Scheduled workflows.** Quote the documentation on: delays at high-load times (the first pass read that jobs may be dropped at the start of the hour), whether a delayed or dropped run is retried, whether a missed run can be detected afterwards, any numeric bound on the delay, whether the 60-day auto-disable applies to private repositories, and whether `workflow_dispatch` can be used for a manual run.
- **G16. Retention.** Cache eviction rules (time and size), artifact retention default and maximum for a private repository, and whether workflow run records are kept as long as artifacts. Re-quote what the first pass read.

### rclone (`rclone.org`, pinned version 1.75.1; the version in use is `rclone/rclone:1.75.1`)

- **G17. S3 provider hashes and crypt.** On the S3 backend page: which hash the S3 backend exposes, how multipart-uploaded objects are handled (the ETag is not an MD5; does rclone store an MD5 in metadata?), and the documented effect on `rclone cryptcheck`. On the crypt page: what `cryptcheck` requires of the underlying remote.
- **G18. Object Lock and versioning with rclone.** Does the S3 backend documentation say anything about Object Lock, versioned buckets, or what `rclone purge` does on a locked or versioned bucket (the project uses `rclone purge` for retention of old backup snapshots)? Flags such as `--s3-versions` and `--s3-version-at` only if the page documents them.

### Optional real-S3 check (only if the connected machine has a THROWAWAY bucket and throwaway keys; never the production backup bucket)

- **G19. Same-size change on a real crypt remote.** The planning machine proved on a local S3 double that `rclone copy --immutable --checksum` falls back to `--size-only` on a crypt remote (so it misses a same-size changed file). Repeat with a real S3 bucket, a crypt remote over it, two small local files of equal length and different content: (1) copy, (2) change one file keeping the length and the modification time, copy again with `--immutable --checksum`, (3) run `rclone cryptcheck <local> <crypt>:path` and record whether it reports the difference. Record rclone's exact output, including any NOTICE line and the exit codes. Use keys only through the environment of that one shell session and never write them into the result file.

## Result file format (`16-RESEARCH-GAPS-RESULT.md`)

For each item G1 to G19: `Gn | status (CITED / UNVERIFIED / NOT ATTEMPTED) | answer | URL | read date UTC | quotation | confidence | note`. End with a list of every URL that failed, the error, and what remains unverified. Do not summarise away a failure.

## PROMPT to paste into Claude Code on the connected machine

```text
Read the file 16-RESEARCH-GAPS.md (given with this message). Do exactly what its "Rules for the connected session" and "Items to verify" sections say. Create only one new file, 16-RESEARCH-GAPS-RESULT.md, in the format of its "Result file format" section. Use official documentation only. For every network error retry once, then record the URL and error and leave that item UNVERIFIED; do not guess and do not work around errors. Do not modify any other file, do not run any trading code, never read .env, and never print or save credentials. G19 is optional: do it only if I give you a throwaway S3 bucket and throwaway keys in this session. When finished, tell me which items are CITED, which are UNVERIFIED, and which failed.
```
