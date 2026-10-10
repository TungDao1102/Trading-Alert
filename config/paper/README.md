# Paper runtime configuration

This directory holds the ratified runtime configuration of the paper process
(`python -m src.paper.runtime`). The values file `paper-runtime-v1.toml` is written only by plan
16-34 from the user's answers. **This README lists the required keys and what they mean. It
carries no value, and the code carries no default for any of them.** The runtime refuses to start
(`CONFIG_NOT_RATIFIED`) when `PAPER_RUNTIME_CONFIG` is unset, the file is missing or not valid
TOML, or any key below is absent or invalid.

The file is named by the environment variable `PAPER_RUNTIME_CONFIG`. Integers are written as
TOML integers; money and rates are written as TOML strings (`"..."`), because a TOML float would
lose digits.

## Required keys

One key per line, so the checks of plans 16-27 and 16-34 can parse the list.

### `[health]` (owner: O-07, REV-07; unit: seconds)

- `max_ws_message_silence_seconds` - longest silence of the market stream before the feed counts as lost.
- `max_closed_bar_lateness_seconds` - longest delay of a closed bar before it counts as late.
- `continuous_uncovered_ceiling_seconds` - longest continuous uncovered time before the run is degraded.
- `freeze_tick_grace_seconds` - grace of the freeze check, described below.

Grace of the freeze check (REV-02, REV-18), one sentence per line:

- `freeze_tick_grace_seconds` bounds only how late a valid scheduled run may start.
- The grace never turns a missing tick into CLEAN, so an absent tick stays a gap in the evidence.
- The value must be strictly smaller than the slot interval of the workflow cron, otherwise one slot could be taken for the next one.

### `[timing]` (owner: O-07, O-09; unit: seconds, except the last key)

- `sibling_4h_wait_seconds` - how long a closed one-hour bar waits for its four-hour sibling.
- `constraint_snapshot_ttl_seconds` - lifetime of a constraint snapshot before it is stale.
- `exchange_info_refresh_seconds` - period between exchange-info refreshes.
- `minute_poll_interval_seconds` - period of the REST minute poll.
- `minute_close_lag_seconds` - how long after a minute closes it is read (may be zero, all others are strictly positive).
- `healthcheck_max_bar_age_seconds` - oldest bar the container healthcheck still accepts.
- `rest_backfill_depth_bars` - unit: bars; how many bars a REST backfill reads.

### `[account]` (owner: O-07; exact decimals written as strings)

- `initial_equity` - starting paper equity in the quote asset.
- `risk_rate` - fraction of equity risked per trade.

### `[scope]` (owner: O-07)

- `symbols` - the non-empty list of distinct symbols the run covers.

## Two gate layers: do not confuse them

- **Layer one, the runtime process gate** (`src/paper/runtime.py`, user decision Q-A,
   `runtime-exact-hash-all`) requires an exact-hash allowlist entry for **every** parameter set:
   strategy id, parameter set id and the 64-hex hash of the registry file must all match. It runs
   once per process, before any candle is parsed, before any strategy code and before
   `pin_stream_epoch`. An empty allowlist ends the process as `SKIPPED (allowlist empty)` with
   exit status zero and no fallback to any set. A missing entry or a different hash is a refusal
   (`ADMISSION_OR_EPOCH_MISMATCH`). Note that rationale tables never replace runtime authorization: a fully
   rationalized set without an entry does not start.
- **Layer two, the per-call rule of `pin_stream_epoch`** (`src/paper/freeze.py`, unchanged, Phase-15 gate) is the
   validation every pin and every tick still runs. It consults the allowlist only for a set
   without rationale tables, and it checks rationale completeness and PLACEHOLDER keys. A hash
   match at layer one only lets this validation continue; it never skips it. Changing this layer
   needs the separate D054 item (i) checkpoint.

The allowlist is empty by the user's decision. Adding an entry is a user decision, not part of
this plan.

## Exit codes and restarts

The named table is `ExitCode` in `src/paper/runtime_config.py`.

- `OK` is a clean stop, or `SKIPPED`. It is not restarted.
- `TRADE_KEY_REFUSED`, `CONFIG_NOT_RATIFIED`, `NO_PINNED_EPOCH` and `ADMISSION_OR_EPOCH_MISMATCH`
  are refusals. They can never succeed on a retry, so they are not restartable by themselves. A
  restart policy would loop on them, which is why the compose service passes `--hold-on-refusal`:
  the process then logs the refusal, stays up (the healthcheck reports it unhealthy) and exits
  with the refusal code only when it is stopped.
- `FAIL_CLOSED_RUNTIME` and the interpreter's own crash status are restartable.
- `USAGE` is a malformed command line.

## Epoch pin

The epoch is pinned only by the operator command `--pin-epoch`, and only when no pinned state
exists. Every restart loads the stored epoch and reuses its `epoch_id`, so a restart never starts
a new trial. A new pin while a pinned state exists is refused: it would restart the qualifying
trial (REV-18), so the operator archives the old state first.
