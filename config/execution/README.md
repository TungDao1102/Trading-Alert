# Execution protection and pre-placement limits

This directory holds the four safety limits of the Phase 19 execution path (D-07 and D-13)
that the owner has not chosen yet. The values file `execution-limits-v1.toml` holds only the
word `NOT_CONFIGURED` for every key until the owner fills the numbers in, after the Demo probes
listed in `19-NOTES.md` (OWNER-OPEN O-04 and O-05).
**This README lists the required keys and what they mean. It carries no value, and the code
carries no default for any of them.** `tests/test_no_unratified_defaults.py` scans `src/` and
`scripts/` so that no key name below is ever given a number in code.

The loader is `load_execution_limits(path)` in `src/execution/execution_limits.py`. It returns
an `ExecutionLimits` whose four fields are `None` while the file says `NOT_CONFIGURED`.
`ExecutionLimits.require_live_ready()` raises `ExecutionLimitsNotConfigured` naming the unset
keys, so the live path refuses while any key is `NOT_CONFIGURED` (the manager gate and the
coordinator check that call it are wired by later Phase 19 plans). The loader refuses to load,
with `ExecutionLimitsInvalid` (or `ExecutionLimitsFileMissing` when the file does not exist), a
file that is not valid TOML, a missing key, an unknown key, an unknown section, a value of the
wrong kind, or a missing or invalid provenance label. Refusal messages name keys or sections
only, never a value or a path.

## Separation from the Binance limits file

`config/binance/binance-limits-v1.toml` is ratified and pinned by sha256 in the DECISIONS row
of Phase 18, and its loader and README tests demand exactly the keys of that file. The four keys
here therefore live in a separate file with a separate loader; the Binance file and its README
are not edited.

## File format

- Exactly the sections `[protection]`, `[pre_placement]` and `[provenance]`.
- Exactly the four keys below, each written once; nothing else is accepted.
- Every value is a TOML integer that is not a boolean, strictly positive (a float, a boolean,
  zero or a negative number is refused), or exactly the TOML string `"NOT_CONFIGURED"`, which
  loads as `None` and means "the owner has not chosen yet". No other string is accepted.
- The key `entry_terminal_timeout_ms` carries the `_ms` suffix for unit clarity; D-13 names the
  concept as the entry terminal timeout and keeps `max_unprotected_ms` verbatim.

## Provenance table

Every key carries a provenance label in `[provenance]`, addressed as `section.key`. While a
value is unset its label is `NOT_CONFIGURED`. After the owner sets a number the label becomes
DECISION, and the change needs a new DECISIONS row. The other project labels (STRUCTURAL,
COST_GUARD, EXPERIMENT) are also accepted for a set value. A PLACEHOLDER label refuses to load,
and so does an absent, unknown or misspelled label or a label for an unknown key: no placeholder
number is a decision. A set value cannot carry the `NOT_CONFIGURED` label and an unset value
cannot carry any other.

## Required keys

One key per line, so the checks of plan 19-01 can parse the list.

### `[protection]` (D-13)

- `protection.max_unprotected_ms` - the longest tolerated time an entry fill is open without a protective stop before the fail-closed response starts (milliseconds).
- `protection.entry_terminal_timeout_ms` - how long the entry order may stay non-terminal before it is treated as a timeout (milliseconds).

### `[pre_placement]` (D-07)

- `pre_placement.min_remaining_validity_seconds` - the minimum remaining validity a plan must still have at placement time, otherwise the placement is refused (seconds).
- `pre_placement.max_mark_price_age_ms` - the maximum age of the mark price the pre-placement price check may use, otherwise the check fails closed (milliseconds).
