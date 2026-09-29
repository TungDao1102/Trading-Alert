---
phase: 10-journal-depth-kill-gate-operations
plan: 11
subsystem: analytics
tags: [renderer, markdown-report, json-sidecar, digest-verification, byte-determinism, golden-fixture, governance-scan, tdd, tracer]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-08 JournalDepthReport (evidence blocks, incomplete ledger, provenance, digest); 10-10 render_common primitives, render_killgate sections 0-2 and the byte-rule check; 10-04 to 10-07 metric sections; 10-UI-SPEC renderer contract"
provides:
  - "src/analytics/render_metrics.py: render_section_full_report (3), render_section_dual_universe (4), render_section_approval_delay (5), render_section_execution_quality (6), render_section_mfe_mae (7), render_section_slices (8), render_section_incomplete (9), render_section_provenance (10) plus M1_ROW_LABELS, E1_ROW_LABELS, X1_ROW_LABELS, LOW_N_LEGEND, SLICE_NOTE, DESCRIPTIVE_NOTE"
  - "src/analytics/render_sidecar.py: SIDECAR_SCHEMA_VERSION analytics-sidecar/1, to_plain, build_sidecar, sidecar_text, markdown_sha256, verify_render"
  - "src/analytics/render.py: render_markdown emitting all ten sections in the fixed order, report_file_stem, render_telegram_pointer (formatter only, no send)"
  - "Byte-exact goldens tests/fixtures/phase10/render_golden/expected.md and expected.json; tests/test_analytics_sidecar.py and 25 new render tests"
affects: [10-12]

actuals:
  tokens: 39900
  tasks: 3
  commits: 6
plan_head_before: a23a44efcdf33ae17b7cb8d4fa9df01516f3fb20
plan_head_after: 504abaf5d10aaafb478fce2297445ed1e6050fd1

tech-stack:
  added: []
  patterns:
    - "One shared M-1 row builder feeds Sections 3 and 4 so the unsliced report and the dual-universe view cannot disagree"
    - "Every measurement cell is either a number under the pinned formatters, an estimate in the '<v> [<lo>, <hi>] n=<n>' shape, 'no data', or 'INCOMPLETE (<reasons>)'; a dash marks a structurally undefined statistic (a rate has no median)"
    - "Section 9 truncation count is read from the fixed md_cell marker in the already rendered sections, so it also covers the 10-10 sections without touching them"
    - "Sidecar = structural conversion (dataclass, mapping, sequence) then canonical_scalars; anything not JSON-plain afterwards raises TypeError"
    - "verify_render returns fixed-vocabulary problem strings and never echoes parser error text"

key-files:
  created:
    - src/analytics/render_metrics.py
    - src/analytics/render_sidecar.py
    - tests/test_analytics_sidecar.py
    - tests/fixtures/phase10/render_golden/expected.md
    - tests/fixtures/phase10/render_golden/expected.json
  modified:
    - src/analytics/render.py
    - tests/test_analytics_render.py

key-decisions:
  - "The Live-5 line is built from the sorted LIVE5_SYMBOLS (BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT). The plan text gave the UI-SPEC literal order (BTC, ETH, BNB, SOL, XRP) and also said 'built from sorted'; the two conflict, and deriving from the single source wins over a second hard-coded copy of the universe"
  - "M-1 n column: Trades (n) shows the trade count; every other row shows n_r_valued (Mean R uses the estimate's own n_valued), as the plan states. The Zero-risk excluded and INCOMPLETE count rows therefore carry the R-valued sample as their n"
  - "Section 4 renders an empty side (either universe) as 'no data' in every value cell and 0 in n; the plan fixed the live-5 note only, so a parallel 'Research slice has no rows for this evidence kind. Nothing is imputed or hidden.' note was added for an empty research side"
  - "Section 4 tables also carry the LOW_N legend (the copywriting contract puts the legend under every n-bearing table); Low-n cell reads 'LOW_N / -', with '-' for a side that is not low-n"
  - "Section 5 R-based cells: a block with no R-valued signal shows 'INCOMPLETE (no hypothetical outcome)' when NO_HYPOTHETICAL_OUTCOME is among its reasons, otherwise 'INCOMPLETE (<reasons>)', otherwise 'no data'; the INCOMPLETE row carries the total plus per-reason counts"
  - "Section 6 unmeasured rows: Mean shows 'INCOMPLETE (<reasons joined by ; >)', Median and p90 show plain 'INCOMPLETE'; the seen leg always names NO_SEEN_TIMESTAMP while unmeasured; rate rows use '-' in n INCOMPLETE, Median and p90. The SYNTHETIC LAG label is also printed above the PAPER table in Section 6 because the PAPER approved-leg values are the constant"
  - "Section 7 Mean cells use the estimate shape (the global rule); the four METRICS section 6 diagnostic tables use the question as the first header cell and a single 'Distribution' row (no H4 exists in the contract)"
  - "Section 8 puts the per-kind slice counts on the line directly under the H3 (the H3 text stays '### 8.k <Title>') and the session and volatility notes after the evidence caption"
  - "Section 9 truncation row is (Evidence '-', Input 'render', Reason 'TEXT_TRUNCATED', count) and the count is the number of md_cell markers in the rendered header and sections 1-8 and 10; when the ledger is empty and nothing was truncated the sentence 'No incomplete or excluded inputs.' is printed"
  - "Section 10 renders one row per experiment named 'experiment identity (<KIND>)'; 40 to 64 hex character values (experiment id, parameter set, snapshot, cost model, code version when it is a commit hash) are shown as 12-hex prefixes, the sidecar keeps them in full"
  - "sidecar_text takes the payload dict; verify_render takes an optional report keyword that additionally recomputes the report digest and compares the sidecar body with the tree (without it, it can only check the Markdown hash and the header/sidecar digest agreement, since the digest is computed over the dataclass tree)"
  - "Governance allow-list is explicit and tiny: the sidecar field name key (slice-row key) and the two UI-SPEC-mandated Markdown phrases 'Slice key' and 'ordered by key'; each is asserted present so the list cannot go stale"
  - "The Telegram pointer is a pure formatter with md_cell sanitisation of the file name; no send is wired because the existing notify Protocol only carries inline-keyboard messages (a plain-text send would need a new adapter helper, deferred per D-04)"

patterns-established:
  - "Golden from reviewed output: expected.md and expected.json were generated only after the rendered text was read against the UI-SPEC, then pinned as bytes under the -text gitattribute"
  - "Scan helpers (secret-like fragments, absolute paths, hostnames, reserved vocabulary) live in tests/test_analytics_render.py and are imported by the sidecar tests"

requirements-completed: [JRN-01, GOV-01]

coverage:
  - id: D1
    description: "Full report (Section 3) and dual-universe view (Section 4) render per evidence kind from one shared M-1 row builder; estimate cells are never bare, empty slices are explicit no data with 0 n and fixed notes, low-n rows stay in place"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section3_full_report_m1_row_labels_in_exact_order_for_every_kind"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section3_estimate_cell_shapes_for_n0_n1_and_n2"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section4_empty_live5_cells_note_and_zero_n"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_tracer_sections_3_and_4"
        status: pass
  - id: D2
    description: "Sections 5-7: approval-delay impact with the SYNTHETIC LAG label on paper and a LIVE-only four-row bucket table, execution quality with the ten fixed rows and INCOMPLETE reasons, MFE/MAE with the four descriptive tables and fixed sentences"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section5_paper_carries_synthetic_lag_label_and_no_bucket_table"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section5_live_prints_four_bucket_rows_in_fixed_order_and_distribution_line"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section6_row_labels_units_seen_sentence_and_rate_rows"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section7_rows_units_diagnostic_tables_and_fixed_lines"
        status: pass
  - id: D3
    description: "Section 8 renders eight dimension tables each led by the ALL row per evidence kind, ordered by key and never by result; Section 9 counts every INCOMPLETE bucket, exclusion, unmatched join, rejected row and truncation; Section 10 lists provenance in the fixed field order with 12-hex hash prefixes"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section8_eight_dimension_tables_each_led_by_the_all_row_per_kind"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section8_slices_are_ordered_by_key_low_n_rows_stay_and_nothing_is_emphasised"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section9_empty_ledger_unmatched_sentence_and_zero_risk_rows"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_section10_field_order_hash_prefixes_and_experiment_sub_rows"
        status: pass
  - id: D4
    description: "All ten sections render in the fixed order regardless of data, byte-identical for identical inputs, pinned by a full Markdown golden"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_render.py#test_full_document_golden_is_byte_exact"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_full_document_has_all_ten_sections_in_order_and_every_section_renders_when_empty"
        status: pass
  - id: D5
    description: "JSON sidecar with schema version, report digest and Markdown SHA-256; verify_render detects one-byte Markdown tampering and digest edits; stem and pointer formatter; the pointer carries no decision surface and no send is wired"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_sidecar.py#test_verify_render_detects_one_byte_markdown_tampering"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_sidecar.py#test_verify_render_detects_sidecar_digest_and_hash_tampering"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_sidecar.py#test_sidecar_golden_is_byte_exact"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_sidecar.py#test_telegram_pointer_is_the_exact_plain_text_and_carries_no_decision_surface"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_sidecar.py#test_no_telegram_send_is_wired_into_the_renderer_modules"
        status: pass
  - id: D6
    description: "Governance scans over the rendered Markdown and sidecar: no secret-like words beyond the explicit allow-list, no absolute paths, hostnames or CR, no reserved advisory vocabulary, no emphasis in the metric sections"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_sidecar.py#test_governance_scans_over_markdown_and_sidecar"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_full_document_has_no_secret_like_words_absolute_paths_or_hostnames"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_render.py#test_full_document_governance_scans"
        status: pass
  - id: D7
    description: "Legibility of the 11-column K-2b gate matrix and the eight S-1 slice tables in a plain terminal and rendering as tables in a Markdown viewer (UI-SPEC backstop)"
    requirement: JRN-01
    human_judgment: true
    verification: []
    rationale: "Viewer rendering and terminal wrapping are visual; only column count and line widths were measured automatically"

duration: 35min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 11: Metric Sections, JSON Sidecar and Governance Scans Summary

**The offline report now renders all ten UI-SPEC sections (full report before any slice, dual universe, approval-delay, execution quality, MFE/MAE, eight ALL-first slice tables, INCOMPLETE ledger, provenance) as byte-exact Markdown, with a sorted-key JSON sidecar carrying the report digest and the Markdown SHA-256, a tamper-detecting `verify_render`, a deterministic file stem and a decision-free Telegram pointer formatter.**

## Performance

- **Duration:** about 35 min (start time was not captured at executor start; commits span 15:08 to 15:21 +07:00)
- **Completed:** 2026-09-29
- **Tasks:** 3 (tracer plus two auto tasks, all TDD with separate RED and GREEN commits)
- **Files:** 7 created or modified (5 new, 2 modified)

## Accomplishments

- Sections 3 and 4 render the ten M-1 rows per evidence kind from one shared builder. Estimate cells are always `<v> [<lo>, <hi>] n=<n>`, `<v> [interval absent] n=<n>` or `no data`; an empty universe side is `no data` with 0 n and a fixed note; LOW_N rows stay in place. The 10-10 golden became a prefix test of the growing document.
- Sections 5-10 complete the document. PAPER approval timing carries the SYNTHETIC LAG label and never reaches the LIVE-only bucket table; every unmeasured latency or deviation row says `INCOMPLETE (<reason>)`; each of the eight slice tables is grouped BACKTEST, PAPER, LIVE with its own `ALL (unsliced)` row first; Section 9 also counts `md_cell` truncations; Section 10 follows the P-1 field order with 12-hex prefixes.
- `render_sidecar` builds the machine-readable twin under the canonical scalar policy (Decimal as string, UTC ISO datetimes, float and set refused), `verify_render` recomputes the Markdown SHA-256 and checks the header digest (and, when given the report, the recomputed digest and body), `report_file_stem` and `render_telegram_pointer` add the stem and the pointer text with no send wired.
- Governance scans lock the output posture: secret-like words, absolute paths, hostnames, CR and reserved vocabulary, with detector self-checks and a non-stale allow-list.

## Task Commits

1. **Task 1 (tracer): Sections 3 and 4** - `d75c236` (test, RED), `ba50bcd` (feat, GREEN)
2. **Task 2: Sections 5-10 and the full golden** - `1f8fe97` (test, RED), `2c94cc4` (feat, GREEN)
3. **Task 3: sidecar, stem, pointer, scans** - `4874907` (test, RED), `504abaf` (feat, GREEN)

**Plan metadata:** recorded by the docs commit that follows this summary.

_Tracer gate: the tracer `<verify>` is automated only, HUMAN_VERIFY_MODE defaults to end-of-phase, so it was re-run after the GREEN commit (11 passed) and expansion continued._

## Files Created/Modified

- `src/analytics/render_metrics.py` - Sections 3-10 renderers, row builders and fixed sentences
- `src/analytics/render_sidecar.py` - sidecar payload, text, hashing and verification
- `src/analytics/render.py` - full ten-section composition, file stem, pointer formatter
- `tests/test_analytics_render.py` - tracer, Sections 5-10, golden and scan tests (plus shared scan helpers)
- `tests/test_analytics_sidecar.py` - sidecar, verification, stem, pointer, governance and golden tests
- `tests/fixtures/phase10/render_golden/expected.md` - full Markdown golden (643 lines)
- `tests/fixtures/phase10/render_golden/expected.json` - sidecar golden

## Decisions Made

See `key-decisions` in the frontmatter. The two that most affect a reader: the Live-5 symbol line is sorted (the plan gave two contradictory orders), and `verify_render` needs the report to recompute the report digest itself.

## Deviations from Plan

None - plan executed exactly as written. Points where the plan text was ambiguous or self-contradictory were resolved as recorded decisions (Live-5 order, the n column of count rows, an added research-side empty note, the placement of the slice counts line); none change a contract the UI-SPEC pins.

## Issues Encountered

- The Bash tool converts backslash escapes inside heredocs, which corrupted two scripted edits to test files (a stray real newline inside a string). Both were caught by ruff before commit and fixed with the Edit tool. No committed file was affected.
- `ruff format src/analytics` briefly reformatted `src/analytics/stats.py` (not a file of this plan); it was reverted with `git checkout -- src/analytics/stats.py` before the commit.
- Pre-existing baselines untouched: one mypy error in `src/adapters/telegram_notify.py` and the repo-wide ruff findings outside `src/analytics` and the plan's test files.

## Human Check (recorded, not performed by an automated run)

The plan's `<human-check>` (plain-terminal legibility and Markdown-viewer rendering of the K-2b matrix and the S-1 tables) needs a person. Measured proxies only: K-2b has 11 columns and is 70 characters wide; the widest table lines are the fixed 10-10 read-only statement row (429 characters) and the Section 10 experiment-identity row (231 characters), which will wrap in a narrow terminal; every table row was verified to keep its column count. The viewer check remains open.

## Known Stubs

None.

## Threat Flags

None. The renderers are pure formatters over the frozen report tree; no new endpoint, auth path, file access or schema change. T-10-37 to T-10-40 are covered by the governance scans, `verify_render`, the reserved-vocabulary scan, and the decision-free pointer plus the no-send-wired test.

## Next Phase Readiness

Ready for 10-12: `render_markdown`, `sidecar_text(build_sidecar(...))`, `verify_render`, `report_file_stem` and `render_telegram_pointer` are the surfaces the CLI wrapper needs; the CLI must write both files with `newline="\n"`, print the digest and state lines, and treat the pointer as text only.

## Self-Check: PASSED
