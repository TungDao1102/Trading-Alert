# Paper runtime configuration

This directory holds the ratified runtime configuration of the paper process
(`python -m src.paper.runtime`). The values file in force is `paper-runtime-v2.toml` (plan 16-56):
every value of `paper-runtime-v1.toml`, which plan 16-34 wrote from the user's answers and which
stays unchanged as history, plus the owner's watchdog key (`16-DEC-WS-WATCHDOG`). The loader
refuses the v1 file for that missing key. **This README lists the required keys and what they mean. It
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
- `feed_silence_timeout_seconds` - longest time without any message on the market connection before the live loop enters its bounded recovery; when no message has arrived when this bound expires again, the process fails closed (owner: `16-DEC-WS-WATCHDOG`; distinct from the coverage silence above and from the healthcheck bar age).

Grace of the freeze check (REV-02, REV-18), one sentence per line:

- `freeze_tick_grace_seconds` bounds only how late a valid scheduled run may start.
- The grace never turns a missing tick into CLEAN, so an absent tick stays a gap in the evidence.
- The value must be strictly smaller than the slot interval of the workflow cron, otherwise one slot could be taken for the next one.

### `[timing]` (owner: O-07, O-09; unit: seconds, except the last key)

- `sibling_4h_wait_seconds` - how long a closed one-hour bar waits for its four-hour sibling.
- `constraint_snapshot_ttl_seconds` - lifetime of a constraint snapshot before it is stale.
- `exchange_info_refresh_seconds` - period between exchange-info refreshes.
- `minute_poll_interval_seconds` - period of the REST minute poll.
- `minute_close_lag_seconds` - how long after a minute closes it is read (strictly positive, like every integer of the file; owner: `16-DEC-CLOSE-LAG-ZERO`).
- `healthcheck_max_bar_age_seconds` - oldest bar the container healthcheck still accepts.
- `rest_backfill_depth_bars` - unit: bars; how many bars a REST backfill reads.

### `[account]` (owner: O-07; exact decimals written as strings)

- `initial_equity` - starting paper equity in the quote asset.
- `risk_rate` - fraction of equity risked per trade.

### `[scope]` (owner: O-07)

- `symbols` - the non-empty list of distinct symbols the run covers.

Every key above is required, and a key that is not listed is refused as an unknown key:
nothing reads it, so a value for it would be an unused threshold. A section or top-level key
other than the four above is refused the same way. In particular no age or freshness key exists
for REST backfill bars (decision Q-D, option history-only): such bars only extend history and
are never evaluated.

## Configuration identity

Owner decision `16-DEC-CONFIG-PIN` (16-57 Q1, option `refuse-on-value-change`). The
configuration is bound to the pinned epoch by its identity:

- The identity is the SHA-256 of the canonical form of the validated values
  (`config_identity` in `src/paper/runtime_config.py`), never of the file bytes.
- The loader validates the complete schema first. A missing or unknown key refuses the start
  (`CONFIG_NOT_RATIFIED`) and never reaches the hash, and no default is injected.
- Every key of every section is in the form. Integers stay integers. Decimals are their
  canonical text, so a trailing zero written after the last digit does not make another value.
  The symbols keep their configured order. The canonical serializer sorts the keys.
- A change of any value changes the identity, and so does a different symbol order.
- A comment, a blank line, whitespace or a different key or section order does not change it.
- The pin (`EPOCH_PINNED`) and every `RUNTIME_START` record the identity
  (`config_identity_sha256`). Beside it, under `config_file_provenance`, they record the raw file
  SHA-256 and the path named by `PAPER_RUNTIME_CONFIG`. That provenance is never compared.
- Every start recomputes the identity. A different identity, or a pin record without one, is
  refused with `ADMISSION_OR_EPOCH_MISMATCH` before `RUNTIME_START`, and under
  `--hold-on-refusal` the container holds, unhealthy. A changed value therefore needs a new pin,
  which starts a new qualifying trial (REV-07, REV-18).

## Healthcheck

`python -m src.paper.runtime --healthcheck` is the container probe. It prints `healthy` and exits
with status zero only while the last processed closed bar is younger than
`healthcheck_max_bar_age_seconds`; a freshly started process gets one such age for its first bar.
It prints `unhealthy` with a reason and exits with status one in every other case: no bar
processed in time, a stopped process, and every condition under which the start gate itself would
refuse (a trade-capable variable, an unratified configuration, no admission or no pinned epoch), so
a container held after a refusal is reported unhealthy at once. Before any of these checks and
before any bar age it reads the held marker of its own container (`src/paper/held_marker.py`):
while a refused start holds, the probe reports unhealthy even when the store holds a fresh bar
of an earlier run, for example on a restart refused by an epoch mismatch or by the
single-instance guard (decision `16-DEC-RESTART-POLICY`). A marker of another container does not
change this probe, and the probe never removes a marker. It reads only the allowed environment
names and never prints a value.

## Two gate layers: do not confuse them

- **Layer one, the runtime process gate** (`src/paper/runtime.py`, user decision Q-A,
   `runtime-exact-hash-all`) requires an exact-hash allowlist entry for **every** parameter set:
   strategy id, parameter set id and the 64-hex hash of the registry file must all match. It runs
   once per process, before any candle is parsed, before any strategy code and before
   `pin_stream_epoch`. An empty allowlist is `SKIPPED (allowlist empty)`, with no fallback to
   any set: exit status zero at once, or a hold under `--hold-on-refusal`. A missing entry or a different hash is a refusal
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

- `OK` is a stop the operator requested, the end of a hold, the one-shot `--pin-epoch`, the
  `--healthcheck` probe, or `SKIPPED` without `--hold-on-refusal`. The service command never
  exits with it by itself: under `restart: unless-stopped` Docker restarts any exit that no
  `docker stop` preceded, so no path relies on exit status zero to stay down.
- `TRADE_KEY_REFUSED`, `CONFIG_NOT_RATIFIED`, `NO_PINNED_EPOCH`, `ADMISSION_OR_EPOCH_MISMATCH`
  and `INSTANCE_LEASE_HELD` are refusals. They can never succeed on a retry, so they are not
  restartable by themselves. A restart policy would loop on them, which is why the compose
  service passes `--hold-on-refusal`: the process then logs the refusal and stays up, held and
  non-operational (no record, no loop, no client), leaves its held marker (the healthcheck
  reports it unhealthy) and exits with the refusal code only when it is stopped. `SKIPPED`
  holds the same way under the flag.
- `INSTANCE_LEASE_HELD`: another paper runtime or pin holds the instance lease of the database
  (a PostgreSQL session advisory lock taken before the pin and before any record), so one
  runtime runs per epoch. A held process releases its lease before it waits.
- `FAIL_CLOSED_RUNTIME` and the interpreter's own crash status are restartable. A lost instance
  lease, noticed at the next consumer batch or periodic step of the loop, is one of them.
- `USAGE` is a malformed command line, or `--pin-epoch` together with `--hold-on-refusal`.

## Epoch pin

The epoch is pinned only by the one-shot operator command `--pin-epoch`, and only when no pinned
state exists. The pin takes the instance lease, records the pin, writes the pinned state and
exits with status zero without starting the run (decision `16-DEC-PIN-COMMAND`); the managed
service is started at once as the next step. Every restart loads the stored epoch and reuses its `epoch_id`, so a restart never starts
a new trial. A new pin while a pinned state exists is refused: it would restart the qualifying
trial (REV-18), so the operator archives the old state first.
