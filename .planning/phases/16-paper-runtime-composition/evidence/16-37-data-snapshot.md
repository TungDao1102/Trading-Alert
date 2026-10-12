# 16-37 second tracer: data snapshot, coverage at data level, REEFUSDT and the engine, constraint source

Plan: 16-37 (O-03b), read-only. Checked 2026-10-13 (UTC), working tree `master`, no worktree. Nothing was edited except this file and the 16-37 SUMMARY. No network, no `.env`, no container, no simulator run, no research run. Throwaway scripts lived in the session scratchpad, not in the repo.

This file reports facts and options with consequences. It proposes no date, symbol or value (REV-14, O-03b are the user's).

The reviewer's tentative window used for every computation below: `[2024-10-03T00:00:00Z, 2026-10-03T00:00:00Z)`, 730 days; Development `[2024-10-03, 2025-07-22)` 292 days; Validation folds `[2025-07-22, 2025-10-03)`, `[2025-10-03, 2025-12-15)`, `[2025-12-15, 2026-02-26)`, `[2026-02-26, 2026-05-10)`, 73 days each; Holdout `[2026-05-10, 2026-10-03)` 146 days; all 12 symbols of `docs/research/universe/research-universe-v1.toml`; strategy and context intervals 1h and 4h (the runner defaults, `src/data/case_input.py:548-549`; the manifest fields would name them, `src/research/manifest.py:91-92`). Verified by arithmetic: 292 + 4 x 73 + 146 = 730; every boundary is 00:00Z; the Validation block (292 days) divides by 4 (`manifest.py:148-160`); the blocks are contiguous (`manifest.py:127-137`). The same boundaries already appear in `docs/research/universe/research-universe-v1.sufficiency-report.json` `split_coverage` (run_date 2026-10-03).

Holdout statement: the runner never reads the Holdout days (`research_splits`, `manifest.py:245-256`; `run.py:128-138` and `:158-168` read at most up to `validation_end_utc`). For the Holdout days `[2026-05-10, 2026-10-03)` this tracer read only (a) the sha256 of each file's bytes and (b) the timestamp columns (`open_time_utc`, `funding_time_utc`) for integrity and gap counting. No price, return, volume, trade count or strategy metric was computed from any file, Holdout or not.

## 1. Local snapshot (sha256 listing)

### Files the runner reads (derived from code)

- `ENGINE_SERIES = ("trade", "intrabar_1m", "mark_1m", "funding")`, open interest is not requested: `src/data/case_input.py:73-74`; `src/research/run.py:136` and `:166`.
- Per symbol and requested day `_symbol_files` (`case_input.py:520-537`) lists: strategy interval trade klines (`:531`), context interval trade klines (`:532`), 1m trade klines (`:533`), 1m mark klines under `dataset=mark_klines` (`:534`), funding `sweep-*.parquet` (`:535`). The OI listing at `:536` is built but not used because OI is not in `wanted` (`:674-678`).
- The same 1m trade and mark partitions are opened lazily by `ParquetMinuteSource` (`src/data/minute_source.py:192-207`, `run.py:177-182`).
- Identity: `dataset_id = dataset_identity(raw_root, used)` over exactly those files (`case_input.py:252-263`, `:680-695`).
- Layout (`src/data/store.py:39`, `:144-151`): `interval=<1m|1h|4h>/symbol=<S>/date=<D>/part.parquet`, `dataset=mark_klines/interval=1m/symbol=<S>/date=<D>/part.parquet`, `data_class=funding/symbol=<S>/date=<D>/sweep-<time>.parquet`.

### Listing

File: `C:\Users\daotu\local-data-snapshot-16-37.sha256` (outside the repo working tree). One line per file, `<sha256>  <path relative to data/raw>`, sorted by path (byte order), LF endings, no CR (checked), 61,665 lines. Window: 12 symbols, days `2024-10-03` through `2026-10-02` (the last local partition is `date=2026-10-02`); 1h/4h mark klines are not in the listing because the runner does not read them (`case_input.py:534`).

| Kind | Files |
|------|------:|
| trade 1m | 8,142 |
| trade 1h | 8,142 |
| trade 4h | 8,142 |
| mark 1m | 8,142 |
| funding sweep files | 29,097 |
| total | 61,665 |

8,142 = 11 x 730 + 112 (REEFUSDT has 112 day partitions). Runner-read part (date before 2026-05-10): 49,549 files. Holdout days (2026-05-10 .. 2026-10-02): 12,116 files, hashed for integrity only. Symbol counts: REEFUSDT 1,077 lines; DOGSUSDT and WIFUSDT 7,299 each (4 h funding cadence, 6 sweep files a day); the other nine symbols 5,110 each.

- sha256 of the listing file: `b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34`
- First 3 lines:
  ```
  6d12839add9fa00112bd00a19cacf84dcf8f2d5deaf8ef4501d0b3c45aeb3b35  data_class=funding/symbol=1000PEPEUSDT/date=2024-10-03/sweep-20241003T000000Z.parquet
  114f7cc2cf150c0f3ee1d29587a7dfb7734acef23457f13e4db2ae79d1b73fce  data_class=funding/symbol=1000PEPEUSDT/date=2024-10-03/sweep-20241003T080000Z.parquet
  0f21d425aa3b5e81ceb811446548ce796831508f91691db8655b2fb3bfcadcbd  data_class=funding/symbol=1000PEPEUSDT/date=2024-10-03/sweep-20241003T160000Z.parquet
  ```
- Last 3 lines:
  ```
  81fb1b8d86082d934bcc5222cdd57e6ed2a7c7001cc6e5fdcb647b9eeecd5cd6  interval=4h/symbol=XRPUSDT/date=2026-09-30/part.parquet
  f6feeb54c04594e1b622d7e75799d1426477469e2b506abc00f7b4f287e34b85  interval=4h/symbol=XRPUSDT/date=2026-10-01/part.parquet
  a4d87d3f301ab92aa55a13661c8de9929ab728f9f776fe9e6cb05511172de8dd  interval=4h/symbol=XRPUSDT/date=2026-10-02/part.parquet
  ```
- Derived fact: `dataset_identity()` (the project function) over the 49,549 runner-read files of this local copy returns `34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2`. This is the value `build_case_input_data(...).dataset_id` would carry for the 12 symbols over `[2024-10-03, 2026-05-10)` if it reads the same file set (`case_input.py:680-695`); the builder itself was not run end to end (it loads the rows), and the manifest `dataset_id` is not set or proposed here. If the EC2 listing is byte-identical for the lines with a date before 2026-05-10, the dataset id is identical.

### Read-only command for the EC2 host

Facts from `docker-compose.yml`: project name `trading` (line 14), named volume `rawdata` (line 194), so the volume is expected to be `trading_rawdata`; the collector mounts it at `/app/data/raw` (line 88); the `backup` service mounts it read-only (lines 167-171). `deploy/migrate.sh:145` already uses the pattern `docker run --rm -i -v <project>_rawdata:/data/raw:ro ... trading-alert-ops:${IMAGE_TAG:-dev}`. The image is Debian based (`Dockerfile:17`, python slim bookworm): `find`, `awk`, `sort`, `xargs`, `sha256sum` exist (not verified on the host).

The command mounts the volume read-only, has no network (`--network none`), reads only, uses no secret and no `.env`. The script changes into the raw root itself, so the paths match whatever directory it is launched from. Run on the EC2 host:

```sh
docker volume ls --format '{{.Name}}' | grep rawdata    # expect: trading_rawdata
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep trading-alert   # pick the ops image, e.g. trading-alert-ops:<tag>

docker run --rm -i --network none -v trading_rawdata:/data/raw:ro \
  --entrypoint sh trading-alert-ops:${IMAGE_TAG:-dev} -s -- /data/raw \
  > "$HOME/local-data-snapshot-16-37.ec2.sha256" <<'EOF'
cd "$1" || exit 1
find interval=1m interval=1h interval=4h dataset=mark_klines/interval=1m data_class=funding -type f \( -name part.parquet -o -name 'sweep-*.parquet' \) |
awk 'BEGIN { n = split("1000PEPEUSDT BNBUSDT BTCUSDT DOGEUSDT DOGSUSDT ETHUSDT REEFUSDT SOLUSDT SUIUSDT WIFUSDT WLDUSDT XRPUSDT", a, " "); for (i = 1; i <= n; i++) ok["symbol=" a[i]] = 1 }
{ s = ""; d = ""; m = split($0, p, "/"); for (i = 1; i <= m; i++) { if (p[i] ~ /^symbol=/) s = p[i]; if (p[i] ~ /^date=/) d = substr(p[i], 6) }
  if ((s in ok) && d >= "2024-10-03" && d <= "2026-10-02") print }' |
LC_ALL=C sort |
xargs -d '\n' sha256sum --text
EOF

wc -l "$HOME/local-data-snapshot-16-37.ec2.sha256"       # local copy: 61665
sha256sum "$HOME/local-data-snapshot-16-37.ec2.sha256"   # local copy: b9b8426a...5982b34
```

If `sha256sum` reports permission denied inside the container, add `--user 0` to the `docker run` line (the mount stays `:ro`). Alternative on a running stack: `docker compose exec -T collector sh -s -- /app/data/raw` with the same script on stdin (that mount is read-write; the script only reads). To compare, copy the EC2 file next to the local one and run `cmp` (Git Bash) or `fc /b` (cmd); `diff` of the two files lists the differing paths. Lines for partitions after `2026-10-02` are excluded by the date filter on both sides, so a current EC2 host still compares equal.

Verification of the command: the script body (without the `docker run` wrapper, which was not run: no container may be started here) was run in Git Bash against the local `data/raw`; its output is byte-identical to the Python-written listing (61,665 lines, `cmp` equal) when `--text` is used. Without `--text`, the Windows build of `sha256sum` prints ` *` instead of two spaces; GNU `sha256sum` on Linux prints two spaces by default and `--text` keeps that explicit.

Not verified: that the host volume is named `trading_rawdata`, that an ops image is present on the host, that the container user can read every file.

## 2. Coverage at data level (timestamp columns only)

Method: for each of the 12 symbols and each series the runner reads, `src.data.case_input._symbol_files` listed the explicit files, `src.data.coverage._observed_times_ms` read only the time column (DuckDB, in memory), and `src.data.coverage.gap_ranges_for_files` (side-effect free, the single gap definition, `coverage.py:340-398`) was called with the same step and tolerance as `case_input._collect_gaps` (`case_input.py:364-408`): klines step = interval, no tolerance; funding step = inferred cadence (`case_input.py:481-499`), tolerance 8 h + 60 s (`case_input.py:81`). Three ranges per symbol: FULL `[2024-10-03, 2026-10-03)`, RUNNER `[2024-10-03, 2026-05-10)` (what the runner reads), HOLDOUT `[2026-05-10, 2026-10-03)` (integrity). "Expected" = range length / step (funding: / inferred cadence). Present counts equal unique counts for every series (no duplicate timestamps).

### The 11 symbols with the full history

1000PEPEUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, DOGSUSDT, ETHUSDT, SOLUSDT, SUIUSDT, WIFUSDT, WLDUSDT, XRPUSDT. All 55 series (11 symbols x 5 series) in the RUNNER range: present = expected, zero gaps, first bar `2024-10-03T00:00Z`. Last observed in RUNNER: 1m `2026-05-09T23:59Z`, 1h `23:00Z`, 4h `20:00Z`, funding `2026-05-09T16:00Z` (8 h symbols) or `20:00Z` (DOGS, WIF).

| Series | First | Last (FULL) | Present / expected (FULL) | RUNNER present / expected | Missing ranges |
|--------|-------|-------------|--------------------------:|--------------------------:|----------------|
| trade 1h | 2024-10-03T00:00Z | 2026-10-02T23:00Z | 17,520 / 17,520 | 14,016 / 14,016 | none |
| trade 4h | 2024-10-03T00:00Z | 2026-10-02T20:00Z | 4,380 / 4,380 | 3,504 / 3,504 | none |
| trade 1m (intrabar) | 2024-10-03T00:00Z | 2026-10-02T23:59Z | 1,051,200 / 1,051,200 | 840,960 / 840,960 | none |
| mark 1m | 2024-10-03T00:00Z | 2026-10-02T23:59Z | 1,051,200 / 1,051,200 | 840,960 / 840,960 | none |
| funding, 8 h cadence (9 symbols) | 2024-10-03T00:00Z | 2026-10-02T16:00Z | 2,190 / 2,190 | 1,752 / 1,752 | none |
| funding, 4 h cadence (DOGSUSDT, WIFUSDT) | 2024-10-03T00:00Z | 2026-10-02T20:00Z | 4,379 / 4,380 | 3,504 / 3,504 | none reported (see note 1) |

HOLDOUT range for the 11 symbols (timestamps only): 1m 210,240, 1h 3,504, 4h 876 present = expected, funding 438 (8 h) present = expected; DOGS and WIF funding 875 of 876, no gap reported.

Note 1 (DOGSUSDT, WIFUSDT funding): the 4 h series has one 8 h spacing, `2026-06-24T00:00Z` to `2026-06-24T08:00Z` (the 04:00 instant is absent). It lies in the Holdout range, not in the range the runner reads. It is not a `GapRange` because 8 h <= tolerance 8 h + 60 s (`coverage.py:392-394`, `case_input.py:81`); the engine's own funding coverage rule uses the same tolerance (`funding.py:229-246`). Verified from the timestamps; nothing else was read from those files.

Note 2 (SOLUSDT 1h): two stray partitions `date=2023-11-14` and `2023-11-15` exist outside the window; they are not in the listing and not read (`_utc_days` lists the requested days, `case_input.py:336-343`).

Note 3: funding cadence by timestamp spacing: DOGSUSDT and WIFUSDT have 4,377 spacings of about 4 h and the one 8 h spacing of note 1; BTCUSDT (checked as the example of the 8 h group) has 2,189 spacings of about 8 h; REEFUSDT is mixed (below).

### REEFUSDT (data ends 2025-01-22T08:59Z)

| Series | First | Last | Present | Files | Notes |
|--------|-------|------|--------:|------:|-------|
| trade 1h | 2024-10-03T00:00Z | 2025-01-22T08:00Z | 2,673 | 112 | last partition holds 9 hourly bars |
| trade 4h | 2024-10-03T00:00Z | 2025-01-22T08:00Z | 669 | 112 | last bar opens 08:00 |
| trade 1m | 2024-10-03T00:00Z | 2025-01-22T08:59Z | 160,380 | 112 | 111 x 1,440 + 540 |
| mark 1m | 2024-10-03T00:00Z | 2025-01-22T08:59Z | 160,380 | 112 | same |
| funding | 2024-10-03T00:00Z | 2025-01-22T08:00Z | 629 | 629 | 40 spacings of about 8 h, the last ending `2024-10-16T08:00Z`, and 588 of about 4 h; majority 4 h, so the inferred label is `4h` over the whole range (`case_input.py:481-499`) |

No interior missing range in any REEFUSDT series. One trailing hole per series in every range the runner builds, computed by the gap function:

- FULL `[2024-10-03, 2026-10-03)`: 1h `2025-01-22T09:00Z..2026-10-03T00:00Z` missing 14,847; 4h `12:00Z..` 3,711; 1m trade and mark `09:00Z..` 890,820; funding(4h) `12:00Z..` 3,711.
- RUNNER `[2024-10-03, 2026-05-10)`: ends `2026-05-10T00:00Z`; 1h 11,343; 4h 2,835; 1m trade and mark 680,580; funding(4h) 2,835.
- HOLDOUT `[2026-05-10, 2026-10-03)`: no file at all, one hole covering the range (1h 3,504; 4h 876; 1m 210,240; funding(8h) 438).
- The per-window lists the runner needs are in section 3.

Cross-check with existing records: the sufficiency report (`research-universe-v1.sufficiency-report.json`) lists REEFUSDT with cause `DELISTED_CAPPED`, `expected_end_utc` `2025-01-22T09:00:00Z`, 160,380 / 2,673 / 669 / 629 bars present = expected, and `split_coverage` `have_1m` 160,380 for Development and 0 for the four folds and the Holdout. My counts match.

## 3. REEFUSDT and the engine

### What the code does with a symbol whose series ends before the window end (verified from code, simulator not run)

1. Gap detection, per call of `build_case_input_data` (`case_input.py:540-698`): the trailing hole is a `GapRange` (`coverage.py:396-397`); a symbol with no file in a window is one hole covering the window (`coverage.py:384-386`). Unacknowledged gaps raise `CaseInputGapError` (`case_input.py:411-426`, `:130-144`): the run does not skip the symbol and does not continue with an unacknowledged gap.
2. Acknowledgement: `allow_gaps=manifest.known_gaps` (`run.py:137`, `:167`). `_apply_allowed` accepts a gap only when an entry is equal to the actual `GapRange`; an entry that matches nothing is ignored and never recorded (`case_input.py:411-426`, docstring). The equality includes `series`, `symbol`, `interval`, `start_utc`, `end_utc`, `missing` (frozen dataclass, `coverage.py:286-302`).
3. Where it is called: once for the whole research range in `_check_manifest_against_store` (`run.py:122-143`, `[development_start, validation_end)`), and once per window per grid point in `_run_split` (`run.py:158-168`; windows from `research_splits`: Development and four folds, `manifest.py:245-256`). So `known_gaps` must contain the entries for all six calls, with different `end_utc`.
4. With the acknowledgement the run continues. The case carries the gaps as `allowed_gaps` (`case_input.py:207-216`, keys `series, symbol, start_utc, end_utc, missing`; `interval` is dropped; `case.py:108`, `:385-410`). The engine indexes bars per symbol (`engine.py:273-279`) and evaluates a signal only where a strategy bar exists (`engine.py:625-626`), so a symbol with no bars simply produces no signal; no error and no explicit skip. `ParquetMinuteSource` returns an empty tuple for an unpublished day (`minute_source.py:201-204`). Every acknowledged non-funding gap is written to `run_summary.allowed_gaps_used` (`engine.py:313-325`, `:329-337`), which is part of the run identity passed to the record (`run.py:197`).
5. Conditional failure (verified from code, occurrence not verified): a position of REEFUSDT that is open when the engine's window passes the last funding instant cannot be funded. `_process_window` pushes funding for every open position (`engine.py:400-401`, `:565-598`); `check_funding_coverage` requires a funding instant at or after the window end within 8 h + 60 s, otherwise it builds a hole whose start is the last real funding instant `2025-01-22T08:00Z` (`funding.py:229-246`), and accepts it only when an allowed funding gap of the same symbol has `start_utc <= hole.start` and `end_utc >= hole.end` (`funding.py:250-262`). The `GapRange` the data produces starts at `2025-01-22T12:00Z` (last + step, `coverage.py:397`), later than 08:00, and an entry that does not equal an actual gap is dropped before the engine sees it (point 2). So no manifest entry can cover that hole; the run would raise `FundingCoverageError` (`funding.py:51`, a `ValueError`, not a `ManifestError`; `run.py:428-436` does not catch it, so the run aborts with a traceback and, because records are written only after all windows (`run.py:262-281`), writes no record). Whether any of the 48 grid points (3 families x 16) holds a filled REEFUSDT position at that moment in the Development window is unknown without a simulator run, which this tracer was not allowed to do. A trailing mark/trade minute hole alone is tolerated (`engine.py:452-468` comment, END_OF_DATA close priced at the last mark minute).
6. Without any acknowledgement: `CaseInputGapError` at the first `_check_manifest_against_store` call (`run.py:128-138`), before any simulation.
7. Not verified: behaviour of a resting (unfilled) REEFUSDT plan at the end of its data, and the positions in `end_of_data` handling beyond the comment cited.

### What a `GapRange` can and cannot say

Fields: `series, symbol, interval, start_utc, end_utc, missing` (`src/data/coverage.py:287-302`). It says where a series has no observations and how many expected slots are inside the hole. It cannot say why (delisting, collector outage, exchange halt): there is no reason field; `start_utc` is the first missing expected point, `end_utc` the range end for a trailing hole (`coverage.py:288-295`), so the same type describes a delisting and an outage. The manifest canonical form (`src/research/manifest.py:178-188`) hashes exactly those six fields and no reason; the loader refuses any other key (`_GAP_KEYS`, `manifest.py:351`, `:377`, `_exact_keys` `:282-287`). `Period` (excluded periods) does have a `reason` (`manifest.py:51-60`), but the runner refuses a non-empty `excluded_periods` (`run.py:122-127`). The sufficiency report separates a delivery from a gap with a `cause` (`DELISTED_CAPPED`, `src/data/sufficiency.py:9`, `:353`, `:390`); the case-input builder does not.

### The `GapRange` entries REEFUSDT needs for the tentative window (computed from the data)

30 entries (5 series x 6 builder calls). Format `series/interval start_utc .. end_utc missing`; every `start_utc`/`end_utc` is UTC, `Z` omitted.

Whole research range `[2024-10-03, 2026-05-10)` (`_check_manifest_against_store`):
```
trade/1h        2025-01-22T09:00 .. 2026-05-10T00:00  11343
trade/4h        2025-01-22T12:00 .. 2026-05-10T00:00   2835
intrabar_1m/1m  2025-01-22T09:00 .. 2026-05-10T00:00 680580
mark_1m/1m      2025-01-22T09:00 .. 2026-05-10T00:00 680580
funding/4h      2025-01-22T12:00 .. 2026-05-10T00:00   2835
```
Development `[2024-10-03, 2025-07-22)`:
```
trade/1h        2025-01-22T09:00 .. 2025-07-22T00:00   4335
trade/4h        2025-01-22T12:00 .. 2025-07-22T00:00   1083
intrabar_1m/1m  2025-01-22T09:00 .. 2025-07-22T00:00 260100
mark_1m/1m      2025-01-22T09:00 .. 2025-07-22T00:00 260100
funding/4h      2025-01-22T12:00 .. 2025-07-22T00:00   1083
```
Validation folds 1 to 4 (no file in any of them, so one hole = the whole fold; the funding label is `8h` because with no funding rows the inferred cadence defaults to 8 h, `case_input.py:496-499`, `:596-606`). For each fold `[s, e)` the five entries are trade/1h `s..e` 1752, trade/4h `s..e` 438, intrabar_1m/1m `s..e` 105120, mark_1m/1m `s..e` 105120, funding/8h `s..e` 219, with:
```
fold 1  2025-07-22T00:00 .. 2025-10-03T00:00
fold 2  2025-10-03T00:00 .. 2025-12-15T00:00
fold 3  2025-12-15T00:00 .. 2026-02-26T00:00
fold 4  2026-02-26T00:00 .. 2026-05-10T00:00
```
Note: the entries depend on the exact boundaries and on the data in the store at the time (a later publication of REEFUSDT partitions, none expected for a delivered contract, would change them). The Holdout range is not built by the runner, so it needs no entry.

### Four options (facts and consequences, none recommended)

| | (a) trailing GapRanges only; delisting stated in the decision record | (b) optional `reason` field in the schema | (c) exclude REEFUSDT | (d) shorten the window to REEFUSDT's 112 days |
|---|---|---|---|---|
| What changes | `known_gaps` holds the 30 entries above; `16-DEC-O-03b.md` states "delivered 2025-01-22T09:00Z (sufficiency report cause DELISTED_CAPPED)" | `GapRange`/manifest/loader gain an optional text field | manifest `symbols` lists 11 symbols | window `[2024-10-03, 2025-01-23)` (112 days) for all 12 symbols, or `[2024-10-03, 2025-01-22)` (111 days) |
| Reproducibility | The reason is not in the manifest, not in the hash, not in any record; it exists only in a prose decision file. Records carry the gap series/symbol/start/end (non-funding gaps always, funding gaps only when a position needed them; `engine.py:313-325`), not the interval, count or reason | Reason inside the hashed manifest; but it must be kept out of the case input (`case.py:108` `_GAP_KEYS` refuses extra keys) and out of the equality used by `_apply_allowed`, or detected gaps (reason empty) stop matching the manifest entries | Nothing to acknowledge; the 11 symbols have zero gaps in the window (section 2) | 112-day end is not a gap-free end: REEFUSDT's last partition ends 08:59Z, so a trailing hole of 900 one-minute slots remains (1h missing 15, 4h missing 3, funding(4h) missing 3, all `2025-01-22T09:00/12:00 .. 2025-01-23T00:00`, computed). The 111-day end `2025-01-22T00:00Z` has zero gaps for REEFUSDT (computed) |
| Hash effects | `manifest_hash` includes 30 entries; `dataset_id` includes REEF files; no schema change | Depends on the design: if the key is emitted only when set, hashes of manifests without a reason are unchanged; if always emitted, every manifest with a `known_gaps` entry changes. No frozen manifest exists in the repo (no manifest JSON is tracked), so no existing hash moves; test fixtures build manifests in code | `manifest_hash` and `dataset_id` computed without REEF files (1,077 listing lines out of 61,665 are REEF) | all hashes differ (different window, files, folds) |
| Code change | None to the loader or runner (verified: any number of entries is accepted, `manifest.py:374-390`) | `src/data/coverage.py` (`GapRange`), `src/research/manifest.py` (`canonical` `:178-188`, `_GAP_KEYS` `:351`, loader `:374-390`), possibly `src/data/case_input.py` (`:207-216` emission), `src/data/sufficiency.py` (`_gap_dict` `:520-527`) and `src/ops/cutover.py` (consumers of `GapRange`); tests: `tests/test_research_runner.py` (`known_gaps` at `:103`, `:425-434`), `tests/test_case_input_builder.py` (`:353`, `:456`), `tests/test_coverage.py` (`:712`). Whether it passes the post-freeze process (protocol v2.2.0 FROZEN, D067) is the user's | None | None to the runner; the manifest dates change |
| 12-symbol universe | Kept | Kept | 11 of 12; `RESEARCH_PROTOCOL.md:77` defines the research universe with "delisted symbols included"; `research-universe-v1.toml` header (lines 3-6, `include_delisted = true`) says delisted symbols stay in to avoid survivorship bias; the manifest `universe_id` is free text and `run.py` does not compare the symbols with the universe file (grep: no such check in `src/research`) | Kept, but every other symbol is cut to 112 days; the D049 decision to extend 1m to 24 months (`DECISIONS.md` D049 (b)) and the Development/Validation/Holdout sizes no longer apply |
| Risk | The `FundingCoverageError` condition (point 5) cannot be removed by any `GapRange`: the first REEFUSDT position still open after `2025-01-22T08:00Z` aborts the run | Same funding condition; it is an engine rule independent of the schema | No REEFUSDT-specific risk | The funding condition remains for a 112-day end; a 111-day end avoids data beyond REEFUSDT's last full day, so no REEFUSDT position can be open past its last funding (not run to confirm) |

Mark of what is verified: all code behaviour and line citations above are read from the source; all counts and gap lists are computed from the local files with the project's own gap function; the funding-coverage failure is a code-derived condition whose occurrence is not verified. Not verified: any behaviour of a real run; whether the EC2 copy equals the local copy (section 1); whether option (b) can pass the project's post-freeze process.

## 4. Constraint source

### What the consumer needs per row

`src/research/run.py:84-103` (`_load_constraints`): the manifest names `constraint_source` and `constraint_sha256`; the file is read as bytes, its sha256 must equal `constraint_sha256`, it must be JSON, either a list or an object with the key `constraint_history` (`:69`, `:96`); rows are kept when `symbol` is in the manifest symbols; a manifest symbol without a row raises `ManifestError`.

`src/backtest/constraints.py:113-135` (`parse_constraint_row`) requires per row the keys `symbol`, `price_tick_size`, `quantity_step_size`, `min_quantity`, `min_notional`, `metadata_observed_at_utc` (`:33-34`, `:122-124`). Values: the four numbers as Decimal strings (floats, ints, bools are refused, `:89-98`), finite and > 0 (`:62-67`); the timestamp an ISO-8601 string or aware datetime in UTC (`:72`, `:101-110`, `:41-45`). Unknown extra keys are not rejected by the parser. Two rows of one symbol with the same `observed_at` are refused (`:158-164`). `case.py:328-340` requires a row for every case symbol and refuses rows for other symbols. Selection: the latest row with `observed_at <= bar close`; a bar before the first row uses the first row and is flagged `extrapolated` (`constraints.py:183-189`), counted in `run_summary.constraints_extrapolated_count` (`engine.py:338`). The designed producer is `src/data/metadata.py:137-192` (`read_constraint_history`, reads the PostgreSQL `symbol_metadata` table) which emits exactly this row shape.

### Sources checked

| Source | What it is, date | Rows for the 12 symbols | Layout matches the consumer? |
|--------|------------------|--------------------------|------------------------------|
| `tests/fixtures/exchange_info_sample.json` (commit 53fdfce, 2026-09-19; one commit in `git log --follow`) | Binance `exchangeInfo` projection, `serverTime` 1789806688644 = 2026-09-19T08:31:28Z, `timezone` UTC; 5 symbols with `filters` (`PRICE_FILTER.tickSize`, `LOT_SIZE.stepSize`/`minQty`, `MIN_NOTIONAL.notional`): BTCUSDT tick 0.10 step 0.001 minQty 0.001 notional 50; ETHUSDT 0.01/0.001/0.001/20; XRPUSDT 0.0001/0.1/0.1/5; BNBUSDT 0.010/0.01/0.01/5; SOLUSDT 0.0100/0.01/0.01/5. The file has no provenance note | BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT (5 of 12). None for REEFUSDT | No. It is the raw exchange shape (nested `filters`, camelCase, one `serverTime`), not flat rows with `price_tick_size`, `quantity_step_size`, `min_quantity`, `min_notional`, `metadata_observed_at_utc`. A conversion is required. It is also a single observation on 2026-09-19, so every bar of the window up to then would be `extrapolated` (`constraints.py:183-189`) |
| `tests/fixtures/phase13/collect_list/exchange_info.json` (commit 9aec911) | Public REST `exchangeInfo` trimmed for the collect-list tests, fetched 2026-09-30 per its `_fixture_note` | 1000PEPEUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, SUIUSDT, WLDUSDT, XRPUSDT have a record, but each record holds only `symbol, contractType, status, quoteAsset, deliveryDate, onboardDate`: no tick, step, minimum quantity or notional. DOGSUSDT, WIFUSDT, REEFUSDT are absent | No: no constraint values at all |
| `tests/fixtures/phase5`, `phase6`, `phase7`, `phase9`, `phase14` `input.json` | Synthetic test cases (`scripts/gen_phase14_fixtures.py:279-290` writes the same placeholder `0.10 / 0.001 / 0.001 / 5` for every symbol, observed 2025-12-01); symbols BTCUSDT (47 files), and BNBUSDT, DOGEUSDT, ADAUSDT, LTCUSDT once | DOGEUSDT, BNBUSDT with placeholder values only | Layout yes (flat rows); values are test placeholders, not exchange facts |
| `.planning/phases/09-live-execution-rollout/09-DEMO-REHEARSAL-*.json` (5 files, runner clock 2026-10-05, `demo-fapi.binance.com`) | Demo-environment rehearsal evidence, `constraints` object | BTCUSDT only | Partly: has `price_tick_size`, `quantity_step_size`, `min_quantity`, `min_notional`, `symbol` but no `metadata_observed_at_utc`; a demo-environment record, not a point-in-time history |
| `docs/research/universe/research-universe-v1.freeze-report.json`, `.sufficiency-report.json`, `collect-list-v1.toml` | Ranking, data depth and collect list | REEFUSDT appears (ranking, `DELISTED_CAPPED`) | No filter values |
| `data/` | `data/raw` (klines, funding, cursors), `data/backup` and `data/reports` are empty of constraint data | none | n/a |
| `params/`, `config/paper/paper-runtime-v1.toml`, `.planning/phases/16-*/evidence/*`, `docs/**/*.md` | grep for `tickSize`, `stepSize`, `price_tick_size`, `min_notional` and for the seven missing symbols near tick/step/notional words | no per-symbol constraint values for the 12 symbols | n/a (prose and parameters only) |
| PostgreSQL `symbol_metadata` (the table `read_constraint_history` reads; EC2 or local) | **Not checked** (no database access in this tracer). From code: written only by `refresh_symbol_metadata` (`src/data/metadata.py:67-134`), insert-only, `observed_at` = the run time (`src/data/backfill_cli.py:649-651`), universe-filtered; the history therefore starts at the first refresh, not at 2024-10-03. A symbol missing from `exchangeInfo` gets no row (`backfill_cli.py:354-357`, `:645-646`). The sufficiency report records `source: REST` for REEFUSDT, which suggests `exchangeInfo` still listed it at the 2026-10-03 backfill (inference, not verified); if so a row may exist there | unknown | Yes (it is the designed producer) |

Git history: `git log --oneline -- tests/fixtures/exchange_info_sample.json` returns only 53fdfce; the phase13 fixture only 9aec911. No earlier or other versions.

### Plain statement

Of the 12 symbols, **5 (BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT) have an exchange-origin constraint row in a stored file** (`exchange_info_sample.json`, one observation, 2026-09-19, in a layout that needs conversion). **7 symbols have no verified constraint row in any stored file I checked: 1000PEPEUSDT, DOGEUSDT, DOGSUSDT, REEFUSDT, SUIUSDT, WIFUSDT, WLDUSDT.** No file in the repository or `data/` is a constraint source with a row per symbol (the runner's `constraint_source`), and none holds a history covering 2024-10-03 to 2026-05-10 for any symbol. The only place a history could exist is the PostgreSQL `symbol_metadata` table, which was not examined. Not used: the current exchangeInfo, any network call, any invented value.

## 5. Not verified

- That the local copy equals the EC2 host (the user's comparison, section 1).
- The EC2 command's `docker run` wrapper (not run; script body verified locally byte-for-byte).
- Whether a REEFUSDT position is ever open past `2025-01-22T08:00Z` in the Development windows of the 48 grid points (needs a simulator run).
- Behaviour of a resting REEFUSDT plan at the end of its data and any other engine path beyond those cited.
- The content of PostgreSQL `symbol_metadata` (local or EC2).
- That the exchange values in `exchange_info_sample.json` are current or were in force on any date of the window; its provenance is not stated in the file.
- Minute-level gaps inside the Holdout were counted from timestamps only; no value of any Holdout file was read.
