---
phase: 13-research-data-foundation-fixes
plan: 10
subsystem: research-universe-freeze
tags: [universe, freeze, survivorship-bias, ranking, decimal, two-witness, cli, archive-fallback]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-04 adapter (exchange_info with delivery_date_ms, klines, mark_klines, is_invalid_symbol_error, is_rate_limit_error); 13-05 archive (ArchiveKlineSource, list_archive_symbols, ArchiveError family)"
provides:
  - "src/data/universe_freeze.py: propose/freeze CLI, CandidateEvidence, FreezeReport, FreezeError, discover_candidates, build_freeze_report, write_report, load_report, render_frozen_manifest, freeze, dataset_start_for"
  - "Hashed, reviewable freeze report (proposal_sha256 over every report field) and an explicit two-witness freeze writer that reuses the gate's own compute_content_sha256"
  - "tests/fixtures/phase13/freeze/research-universe-v1.draft.toml: byte copy of the DRAFT manifest so freeze tests never depend on the real manifest state"
affects: [13-11, 13-12, 13-13]

actuals:
  tokens: 15850
  tasks: 3
  commits: 4
plan_head_before: e303ab5a9b4b4994522ffdd4b082f04004802ed3
plan_head_after: bffb910e295e98bb2a0b82c018f4ae416dccdb4a

tech-stack:
  added: []
  patterns:
    - "src module imports the gate (scripts.decision_alignment.universe) so the freeze hashes with the gate's own routine (D-09), never a re-implementation"
    - "Two-file write: validate everything first, tmp + os.replace for each file, restore the manifest bytes if the witness write fails"
    - "Report hash covers the whole report body (not only the ranking); load_report recomputes it, so any edit is detected"
    - "Module-level seams (_make_adapter, _make_archive_client, list_archive_symbols, ArchiveKlineSource, _retry_sleep, REST_PACE_SECONDS) read at call time so tests inject fakes without a network"

key-files:
  created:
    - src/data/universe_freeze.py
    - tests/test_universe_freeze.py
    - tests/fixtures/phase13/freeze/research-universe-v1.draft.toml
  modified: []

key-decisions:
  - "proposal_sha256 is computed over the complete report body (candidates, ranked, proposed symbols, unrankable, availability), a superset of the plan's minimal payload, so an edited evidence row is detected as well as an edited ranking"
  - "Archive-only symbols that exchangeInfo lists with another contract type or quote asset (for example TRADIFI_PERPETUAL) are excluded from candidates instead of re-entering through the archive listing"
  - "Only -1121 switches a symbol from REST to the archive; rate-limit errors are retried (5 attempts, random exponential wait) and, when exhausted, fail the run; any other REST error also fails the run (fail closed) rather than being classified as unavailable"
  - "The archive is also tried when REST returns fewer than 30 window bars; the archive window is fetched in a loop because ArchiveKlineSource.klines serves one month per call and a 30-day window can span two months"
  - "An archive failure (ArchiveError, including checksum mismatch) counts as no archive data for that symbol; with REST also failing the symbol is UNAVAILABLE and listed as unrankable"
  - "Availability mark probe is REST only (no archive mark source exists), so archive-only proposed symbols show mark UNAVAILABLE and are flagged in the review output; they stay proposed (data unavailability never changes the ranking)"
  - "A partial (29 bar) or zero-trade window records no volume sum for that symbol; the evidence keeps days, source and reason"

patterns-established:
  - "Freeze safety ladder: hash-checked report, approval hash, DRAFT-only manifest, unset-witness-only, validate_manifest and check_second_witness on the rendered text, dry run by default"

requirements-completed: [DATA-01, BKTS-02]

coverage:
  - id: D1
    description: "propose ranks PERPETUAL USDT contracts (any status) plus archive-only symbols by 30-day mean daily quote volume at the dataset start (run date minus two years), Decimal only, ties by symbol, top 12, including symbols delisted later"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_build_report_ranks_top_12_including_delisted_later"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_equal_sums_at_the_cut_are_ordered_by_symbol"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_discover_candidates_filters_and_dedupes"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_module_has_no_float_call_or_annotation"
        status: pass
    human_judgment: false
  - id: D2
    description: "Eligibility and evidence: delivered before window, listed after window start, incomplete window, zero-trade day; REST to archive fallback on -1121 or short window; unavailable symbols listed as unrankable, never dropped; rate limits retried without a source switch; availability per proposed symbol"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_delivered_before_window_is_ineligible_without_a_request"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_listed_after_window_start_is_ineligible_without_a_request"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_incomplete_and_zero_trade_windows_are_ineligible"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_rest_invalid_symbol_falls_back_to_archive"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_unavailable_symbol_is_listed_not_dropped"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_rate_limit_is_retried_and_never_switches_source"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_availability_records_trade_and_mark_per_proposed_symbol"
        status: pass
    human_judgment: false
  - id: D3
    description: "Reviewable, tamper-evident, byte-deterministic report (ranking evidence, deliveryDate per candidate, availability, proposal_sha256) outside the hashed manifest payload"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_report_round_trips_and_detects_tampering"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_freeze_report_is_byte_deterministic"
        status: pass
    human_judgment: false
  - id: D4
    description: "freeze writes FROZEN manifest (header comments preserved) and sets the witness to the digest from the gate's own hash routine; validate_manifest, check_second_witness and the gate CLI digest all agree (D-20)"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_freeze_writes_matching_witnesses"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_frozen_manifest_preserves_header_comments"
        status: pass
    human_judgment: false
  - id: D5
    description: "Freezing is never a side effect: dry run by default, wrong approval hash, edited report, already FROZEN manifest, preset witness, a short proposal and a witness write failure all refuse or roll back with no file changed; propose exit codes"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_freeze_without_flag_writes_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_wrong_approval_hash_refuses"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_refreeze_refuses"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_already_set_witness_refuses"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_witness_write_failure_restores_the_manifest"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_fewer_eligible_than_top_n_reports_short_and_freeze_refuses"
        status: pass
      - kind: unit
        ref: "tests/test_universe_freeze.py#test_propose_exits_3_when_too_few_symbols_are_eligible"
        status: pass
    human_judgment: false
  - id: D6
    description: "A real propose run against live Binance REST and the data.binance.vision archive (about 700 candidates, 6-7 minutes) and the operator freeze of the real manifest"
    requirement: DATA-01
    verification: []
    human_judgment: true
    rationale: "Unit tests use in-test fakes. The real ranking, the real -1121 and archive-only population, and the one-way freeze are the operator plan 13-12 and need a human decision on the printed proposal."

duration: 15min
completed: 2026-09-30
status: complete
---

# Phase 13 Plan 10: Point-in-time universe freeze tool Summary

**`python -m src.data.universe_freeze propose|freeze` ranks every USDT perpetual (any status, plus archive-only symbols) by trailing 30-day mean daily quote volume at the dataset start, writes a hashed reviewable report, and freezes an approved report into a FROZEN manifest plus the second witness using the gate's own hash routine, tested only on temporary copies.**

## Performance

- **Duration:** about 15 min
- **Completed:** 2026-09-30
- **Tasks:** 3
- **Files created:** 3 (`src/data/universe_freeze.py`, `tests/test_universe_freeze.py`, the DRAFT fixture)

## Accomplishments

- `propose --run-date D --out R`: dataset start is D minus two years (29 Feb maps to 28 Feb), window is the 30 days before it. Candidates are exchangeInfo PERPETUAL/USDT of any status plus archive-only symbols, deduped and `SYMBOL_RE`-validated. Ranking is by Decimal sum (mean computed under a fixed 60-digit local context), ties by symbol, top 12 kept, symbols delisted later included.
- Evidence rules: `DELIVERED_BEFORE_WINDOW` and `LISTED_AFTER_WINDOW_START` decided from exchangeInfo without a request; `INCOMPLETE_WINDOW` (not 30 bars), `ZERO_TRADE_DAY`, `UNAVAILABLE` (no source), else `ELIGIBLE`. REST 1d first, archive on -1121 or a short window, source recorded per symbol; rate limits retried (bounded) and never a reason to switch source.
- The report records per-candidate status, contract type, onboard time, `deliveryDate`, source, days, sum/mean, eligibility and reason, the full ranking, unrankable symbols and trade/mark availability for each proposed symbol, and a `proposal_sha256` over all of it. `load_report` recomputes the hash; any edit raises `FreezeError`. Identical inputs give byte-identical report files.
- `freeze --report R --approve <sha> [--freeze]`: dry run by default (prints the manifest and digest, writes nothing). With `--freeze` it validates first (`validate_manifest`, `check_second_witness`, digest equality on the re-parsed rendered text), then writes manifest and witness via tmp + `os.replace` and restores the manifest bytes if the witness write fails. Header comments are preserved except the three-line "State: DRAFT." paragraph.
- Refusals with no file change (exit 2): wrong approval hash, edited report, manifest not DRAFT, witness already set, a proposal that fails `validate_manifest` (for example fewer than 12 eligible symbols). `propose` exits 3 when fewer than `top_n` are eligible (report still written).
- The real manifest and `scripts/decision_alignment/universe.py` are untouched: `git diff --stat e303ab5..HEAD` over both is empty, the manifest is still DRAFT, and `scripts/verify_decision_alignment.py universe` ends with `ALL_PASS universe`.

## Task Commits

1. **Task 1 (tracer): report to two-witness freeze on copies** - RED `99c3605` (test), GREEN `4ab7cd1` (feat)
2. **Task 2: ranking and evidence rules** - `b0d779e` (test; behaviour already implemented in Task 1 GREEN, see TDD note)
3. **Task 3: freeze safety gates and propose/freeze CLI** - `bffb910` (test; CLI and refusals already implemented in Task 1 GREEN, see TDD note)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified

- `src/data/universe_freeze.py` - discovery, ranking, evidence, report I/O and hash, manifest render, freeze, CLI
- `tests/test_universe_freeze.py` - 29 tests over in-test fakes (exchange, archive) and temporary manifest/witness copies
- `tests/fixtures/phase13/freeze/research-universe-v1.draft.toml` - byte copy of the DRAFT manifest

## Decisions Made

See `key-decisions` in the frontmatter. The two that matter most to the operator plan 13-12: the report hash covers the whole report, and only -1121 (not any other REST error) triggers the archive; every other REST failure stops the run so a flaky network can never silently shrink the candidate set.

## Deviations from Plan

### Auto-fixed / judgement calls

**1. [Rule 2 - Missing critical functionality] Archive listing must not readmit non-perpetual contracts**
- **Found during:** Task 1 (`discover_candidates`)
- **Issue:** the plan says candidates are exchangeInfo PERPETUAL/USDT plus archive USDT symbols; a symbol exchangeInfo lists as TRADIFI_PERPETUAL (or a non-USDT quote) that also appears in the archive would have re-entered as "archive-only" and could have been ranked.
- **Fix:** archive symbols that exchangeInfo lists with another contract type or quote asset are excluded; tested in `test_discover_candidates_filters_and_dedupes`.
- **Files modified:** `src/data/universe_freeze.py`, `tests/test_universe_freeze.py`
- **Commit:** `4ab7cd1`

**2. [Rule 2 - Missing critical functionality] Report hash covers the full report**
- **Found during:** Task 1 (`build_freeze_report`)
- **Issue:** the plan's minimal proposal payload (dates, top_n, proposed symbols, ranked list) would not detect an edited candidate evidence row, availability entry or unrankable list that the operator reviews before approving.
- **Fix:** `proposal_sha256` is computed over every report field except itself.
- **Commit:** `4ab7cd1`

**3. [Interpretation] Tracer fixture has 13 TRADING symbols, not 12**
- The plan's behaviour text lists 15 exchangeInfo symbols (12 TRADING, 2 SETTLING, 1 TRADIFI) but expects 16 candidates with one archive-only symbol, which is inconsistent by one. The test uses 13 TRADING + 2 SETTLING + 1 TRADIFI + 1 archive-only so that 16 candidates and a top-12 cut both hold.

**Total deviations:** 2 auto-added (Rule 2), 1 test-fixture interpretation. **Impact on plan:** none on scope; both additions tighten the safety properties the plan asks for.

## TDD Gate Compliance

- Task 1 has a `test(13-10)` RED commit (`99c3605`) followed by a `feat(13-10)` GREEN commit (`4ab7cd1`). The RED failure was an `ImportError` for the not-yet-existing module (the target tests could not even be collected), so it is not an assertion failure on planned behaviour; `gsd_run check tdd-red-evidence` was not run because the plan gives no evidence-record path. Flagged as advisory, same as 13-09.
- Task 2 and Task 3: the eligibility order, source choice, retry, availability probes, refusal paths and CLI were implemented in the Task 1 GREEN commit (they form one function chain that could not be written half-way without stubbing), so every Task 2 and Task 3 test passed on first run. They are committed as `test(13-10)` with no `feat` commit. The plan allows this ("confirm RED for any that fail"). No refactor commits.
- Git protocol note: HEAD is `master` (protected by name). The dispatch designates `master` as the sequential execution branch and prior 13-0x plans committed there; no config was changed.

## Issues Encountered

- One heredoc-based append to the test file failed on shell quoting before anything was applied; redone with the edit tools.
- `test_propose_writes_report_and_prints_the_review_block` first asserted the wrong flagged symbol list (my test forgot the archive-only symbol also has no REST mark series); the tool was right, the assertion was corrected.

## Deferred Issues

- The full suite still shows the 7 known decision-alignment failures (`FAIL RQ-01 :: OPS-06 row is Phase 13.1` / `RQ-04`), recorded in `deferred-items.md` and owned by plan 13-11. Nothing in this plan touches them.

## Known Stubs

None. `REST_PACE_SECONDS`, the retry policy and all constants are real values; tests override them only to avoid sleeping.

## Threat Flags

None beyond the plan's register: the module makes REST calls through the existing adapter and archive calls through the 13-05 client (fixed hosts, `SYMBOL_RE`-validated names); it writes only the report path and, on an explicit approved `--freeze`, the manifest and witness paths.

## Threat Mitigations Verified

| Threat | Mitigation | Test |
|--------|-----------|------|
| T-13-39 half-written freeze | validate before writing, tmp + os.replace, manifest restored on witness failure | `test_witness_write_failure_restores_the_manifest`, `test_fewer_eligible_than_top_n_reports_short_and_freeze_refuses` |
| T-13-40 unreviewed/edited proposal | hash recomputed on load, `--approve` must equal it, `--freeze` required | `test_wrong_approval_hash_refuses`, `test_edited_report_refuses_even_with_its_old_hash`, `test_freeze_without_flag_writes_nothing` |
| T-13-41 survivorship bias | all statuses plus archive-only, unrankable listed | `test_build_report_ranks_top_12_including_delisted_later`, `test_unavailable_symbol_is_listed_not_dropped` |
| T-13-42 float/context arithmetic | Decimal sums, fixed local context, AST no-float test, byte-determinism | `test_module_has_no_float_call_or_annotation`, `test_freeze_report_is_byte_deterministic` |
| T-13-43 hostile archive names | `SYMBOL_RE` in discovery and render | `test_discover_candidates_filters_and_dedupes` |

## Verification Results

- `pytest tests/test_universe_freeze.py tests/test_decision_alignment_universe.py`: 79 passed (29 freeze tests + 50 universe gate tests).
- `mypy src/data/universe_freeze.py`: Success, no issues; `ruff check` clean.
- `python -m src.data.universe_freeze --help` lists `propose` and `freeze`.
- `python scripts/verify_decision_alignment.py universe`: `ALL_PASS universe` (real manifest still DRAFT).
- `git diff --stat e303ab5..HEAD -- docs/research/universe/research-universe-v1.toml scripts/decision_alignment/universe.py`: empty.

## Next Phase Readiness

Plan 13-12 can run `propose` (needs live Binance REST and the archive; about 700 weight, 6-7 minutes), review the printed proposal (unrankable list and `UNAVAILABLE proposed data` line first), and then run `freeze --approve <proposal_sha256> --freeze` plus update `tests/test_decision_alignment_universe.py::test_real_manifest_is_draft_with_empty_freeze_fields` in the same commit. This plan did not freeze the real manifest and did not touch `FROZEN_CONTENT_SHA256`.

## Self-Check: PASSED
