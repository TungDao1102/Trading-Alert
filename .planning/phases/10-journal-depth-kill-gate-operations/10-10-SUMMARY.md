---
phase: 10-journal-depth-kill-gate-operations
plan: 10
subsystem: analytics
tags: [renderer, markdown-report, kill-gate-view, byte-determinism, escaping, golden-fixture, tdd, tracer]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-08 JournalDepthReport (kill_gate section, evidence blocks, incomplete ledger, live_posture, digest); 10-05/10-07 kill-gate verdict, family facts and gate cells; 10-04 NO_TRADE section; 10-UI-SPEC renderer contract"
provides:
  - "src/analytics/render_common.py: md_cell/md_cell_truncated single escaper, fmt_int/fmt_r/fmt_pct/fmt_seconds/fmt_bps/fmt_months/fmt_price/fmt_estimate, fmt_utc/fmt_display, md_table, join_blocks, evidence_caption, SECTION_TITLES (ten fixed H2 headings), fixed sentences and constants"
  - "src/analytics/render_killgate.py: render_header, render_section_kill_gate (banner, budget, clock provenance, K-2a/K-2b, K-3, decision references, enablement effect), render_section_evidence_overview, STATE_SENTENCES"
  - "src/analytics/render.py: render_markdown(report) composing H1, header and sections 1-2 in the fixed order with byte-rule checks"
  - "tests/test_analytics_render.py (29 tests) and the byte-exact golden tests/fixtures/phase10/render_golden/expected_sections_0_2.md"
affects: [10-11, 10-12]

actuals:
  tokens: 15500
  tasks: 2
  commits: 4
plan_head_before: 753f4e530e3cfe426d77aead5bcc82a27167def7
plan_head_after: 838afb2003e1a3a128b4e17230664998ceb04522

tech-stack:
  added: []
  patterns:
    - "Renderers are pure functions returning lists of lines; sections are joined by one helper (blank line between blocks, blank/---/blank between H2 sections); a final byte-rule check rejects CR, a missing or doubled trailing LF and trailing whitespace"
    - "One md_cell escaper for all sourced text; md_table refuses any cell that has a line break or an unescaped pipe, so a table cannot be broken by data"
    - "Column-level no data: a NO_TRADE column whose total is zero renders no data in every row of that column instead of a column of zeros"
    - "Golden pinned as bytes with a -text gitattribute so autocrlf checkouts cannot change it"

key-files:
  created:
    - src/analytics/render_common.py
    - src/analytics/render_killgate.py
    - src/analytics/render.py
    - tests/test_analytics_render.py
    - tests/fixtures/phase10/render_golden/expected_sections_0_2.md
    - .gitattributes
  modified: []

key-decisions:
  - "Section 1 carries numbered H3 headings for every block (1.1 Budget progress, 1.2 Clock provenance, 1.3 Family acceptance, 1.4 Family gate matrix, 1.5-1.7 NO_TRADE by reason category per kind, 1.8 Decision references, 1.9 Enablement effect) so each table has its preceding-heading caption per the UI-SPEC global table rule; the plan only named the K-3 headings"
  - "md_cell also escapes backslash (so a raw backslash before a pipe cannot defeat the pipe escape) and drops Unicode format/control/line-separator characters (bidi overrides, zero-width, U+2028/9, C1 controls); truncation happens before escaping so an escape is never split"
  - "Hashes and enum tokens are rendered plain in table cells (no backticks), as the plan's behavior text lists them; the output contains no backtick at all, which the hostile-string test asserts"
  - "The Research clock start row shows verdict.cycle_start_utc (equal to the protocol clock start unless a recorded reset restarted the cycle, in which case the Reopened line explains it)"
  - "SECTION_TITLES lives in render_common (re-exported from render) to avoid a render <-> render_killgate import cycle"
  - "The Section 2 INCOMPLETE column is the plain sum of the report's INCOMPLETE ledger counts for that kind (an item can be counted under more than one input name), as the plan states"

patterns-established:
  - "Golden from reviewed output: the golden was generated only after the rendered document was read line by line against the UI-SPEC, then the test compares bytes"
  - "Reserved-vocabulary scan with detector self-check, run over every state variant and over the renderer source files"

requirements-completed: []

coverage:
  - id: D1
    description: "Kill Gate view rendered first after the header per the UI-SPEC: state banner, budget table with the D013 rule sentence, clock provenance with the earliest-possible note, family matrices K-2a/K-2b, NO_TRADE by category K-3 per evidence kind, decision references and enablement effect"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_render.py#test_header_table_rows_in_the_exact_ui_spec_order"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_budget_table_rows_and_rule_sentence"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_clock_provenance_table_and_earliest_note"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_k2a_family_matrix_columns_rows_and_shared_component_note"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_k2b_gate_matrix_has_eleven_columns_and_only_the_four_cell_tokens"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_k3_no_trade_tables_fixed_row_order_and_no_data_columns"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_decision_references_bullets_and_empty_sentence"
        status: pass
  - id: D2
    description: "INSUFFICIENT_EDGE is a calm terminal outcome (TERMINAL token, fixed sentence, sticky note, reset line); PASSING_CANDIDATE is explicitly non-authorizing; every state ends with the fixed line that live trading is never enabled by this report"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_render.py#test_banner_insufficient_edge_is_calm_terminal_and_exact"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_banner_within_budget_and_passing_candidate_sentences_are_filled"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_banner_sticky_terminal_and_reset_event_lines"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_enablement_effect_sentence_per_state_and_the_fixed_closing_line"
        status: pass
  - id: D3
    description: "Both universes and all three evidence kinds are shown unpooled with no data for empty groups: K-2a Universe cell, K-3 Live-5/Research/All columns (a zero-total column is no data in every row), Section 2 rows BACKTEST/PAPER/LIVE with the live-rows-absent sentence"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_render.py#test_k3_empty_live5_column_renders_no_data_while_other_columns_show_counts"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_evidence_overview_rows_caption_and_live_sentence"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_k2a_missing_unknown_and_empty_cells"
        status: pass
  - id: D4
    description: "All sourced text passes one md_cell escape (pipe, backslash, backtick, angle brackets, line breaks, control and format characters, 200-char truncation with the fixed marker); hostile family ids and decision refs cannot break a table or inject markup"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_render.py#test_primitives_md_cell_escapes_pipe_backtick_angle_newline_and_controls"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_primitives_md_cell_truncates_at_200_chars_with_marker"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_hostile_strings_cannot_break_tables_or_inject_markup"
        status: pass
  - id: D5
    description: "Byte-deterministic output: LF only, single trailing LF, no trailing whitespace, ASCII except the banner em dash, no ambient state, pinned number formats and Asia/Ho_Chi_Minh display time; byte-exact golden for header + Sections 1 and 2"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_render.py#test_tracer_document_is_lf_only_single_trailing_lf_and_ascii_but_the_banner_dash"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_primitives_number_formats_exponent_and_negative_zero"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_primitives_utc_and_display_time"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_output_carries_no_ambient_state"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_golden_sections_0_2_is_byte_exact"
        status: pass
  - id: D6
    description: "Reserved vocabulary never appears in rendered output or renderer source, with a detector self-check that finds an injected word; no favorability emphasis"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: test
        ref: "tests/test_analytics_render.py#test_reserved_vocabulary_scan_finds_none_and_detects_an_injected_word"
        status: pass
      - kind: test
        ref: "tests/test_analytics_render.py#test_render_sources_contain_no_advisory_wording"
        status: pass
  - id: D7
    description: "Whether the operator-facing layout (numbered H3 blocks in Section 1, the 11-column gate matrix, plain-text tokens) is legible and reads as neutral in a real Markdown viewer and terminal"
    human_judgment: true
    rationale: "The UI-SPEC lists K-2b width and cross-viewer rendering as manual backstop checks; byte stability is test-enforced but legibility and tone are judged by a person"

duration: 14 min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 10: Offline Report Renderer, Governance Half Summary

**Pure Markdown renderer for the report header, the Kill Gate section (state banner, budgets, clock provenance, family matrices, NO_TRADE by reason category, decision references, enablement effect) and the Evidence Overview, with one md_cell escaper, pinned number and time formats, and a byte-exact golden.**

## Performance

- **Duration:** 14 min (about 07:49Z to 08:03Z)
- **Tasks:** 2 (1 tracer, 1 auto; both TDD)
- **Files:** 6 created, 0 modified (3 source modules, 1 test module, 1 golden fixture, 1 gitattributes)

## Accomplishments

- `render_common` holds every primitive: `md_cell` (pipe and backslash escaped, line breaks and tabs to one space, backtick to apostrophe, angle brackets to entities, control/format/line-separator characters dropped, 200-char cut before escaping plus the fixed `...[truncated]` marker), Decimal formatters under a pinned half-even quantization (4 dp R/win-rate, 2 dp percent and bps, 1 dp seconds and months, exponent-free prices, never `-0.0000`), `fmt_estimate` (`value [lo, hi] n=<n>`, `[interval absent]`, or `no data`; never a bare number), UTC and Asia/Ho_Chi_Minh display time built from numeric fields, and `md_table`, which refuses any cell with a line break or an unescaped pipe.
- The header table follows the exact UI-SPEC field order (digest, both times, timezone note, generator, read-only statement, kill-gate state, live-orders posture). Section 1 leads with the banner (`TERMINAL` only after INSUFFICIENT_EDGE, fixed calm sentences, the non-authorizing PASSING_CANDIDATE sentence), then sticky-terminal and reset lines when the verdict carries them, the budget table plus the D013 rule sentence, the clock provenance table (with the earliest-possible note only while the months budget is unmet), K-2a and K-2b, one K-3 table per evidence kind, decision references and the enablement effect, always closed by "Live trading is never enabled by this report."
- Section 2 renders BACKTEST, PAPER and LIVE as separate rows with the fixed live-rows-absent sentence. `render_markdown` composes H1, header and the two sections; sections 3-10 slot in as later plans land (titles already fixed in `SECTION_TITLES`).
- The composite fixture renders to a 128-line golden pinned as bytes (with a `-text` gitattribute so an autocrlf checkout cannot change it); its report digest matches the 10-08 pin `57bcaab6...`.

## Task Commits

1. **Task 1 (tracer) RED:** `4388625` test(10-10): failing tests for renderer primitives, header, banner, budget and clock
2. **Task 1 GREEN:** `127a4f6` feat(10-10): renderer primitives, header, kill-gate banner, budget and clock provenance
3. **Task 2 RED:** `9ca8800` test(10-10): failing tests for family matrices, NO_TRADE by category, decisions and evidence overview
4. **Task 2 GREEN:** `838afb2` feat(10-10): family matrices, NO_TRADE by category, decisions, enablement effect and evidence overview

Tracer gate: the tracer `<verify>` is automated-only; it passed after the GREEN commit (with the purity and typing guards), so expansion proceeded with no checkpoint.

**Plan metadata:** docs(10-10) commit follows this summary.

## Files Created/Modified

- `src/analytics/render_common.py` - escaping, formatting, table and block-joining primitives; fixed sentences; the ten section titles.
- `src/analytics/render_killgate.py` - header, Kill Gate and Evidence Overview renderers and the state/enablement sentence tables.
- `src/analytics/render.py` - `render_markdown` composition and the byte-rule check.
- `tests/test_analytics_render.py` - 29 tests: primitives, header, banner, budget, clock, matrices, K-3, decisions, enablement, Section 2, spacing, hostile strings, reserved vocabulary, ambient state, golden.
- `tests/fixtures/phase10/render_golden/expected_sections_0_2.md` - byte-exact golden for header + Sections 1 and 2.
- `.gitattributes` - `tests/fixtures/phase10/render_golden/* -text` so the golden is never eol-converted.

## Decisions Made

See key-decisions above. The one with layout impact: Section 1 uses numbered H3 blocks (the plan only named the K-3 headings); K-3 headings are `1.5`-`1.7` by evidence kind, decisions and enablement follow as `1.8`/`1.9`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] md_cell hardening beyond the listed characters**
- **Found during:** Task 1 (T-10-33 mitigation)
- **Issue:** Escaping only `|` leaves a hole: a raw backslash before a pipe turns the escape into an escaped backslash plus a bare pipe, which splits the table cell. Bidi overrides, zero-width and U+2028/9 characters can also spoof or reflow text.
- **Fix:** `md_cell` escapes a backslash as a double backslash, and drops Unicode control/format/surrogate/private/unassigned characters (line and paragraph separators become a space); the cut to 200 characters happens before escaping so an escape sequence is never split.
- **Files modified:** src/analytics/render_common.py, tests/test_analytics_render.py
- **Commit:** 127a4f6

**2. [Rule 2 - Missing critical] md_table and render_markdown fail closed on shape errors**
- **Found during:** Task 1
- **Issue:** A table cell with a line break or an unescaped pipe, or a document with a carriage return or trailing whitespace, would silently break the layout or the byte-identity guarantee.
- **Fix:** `md_table` raises `AnalyticsInputError` for such a cell, a wrong cell count or an unknown alignment token; `render_markdown` raises `RenderError` for CR, a missing or doubled trailing LF, or trailing whitespace.
- **Files modified:** src/analytics/render_common.py, src/analytics/render.py
- **Commit:** 127a4f6

**3. Additions beyond the plan text (no behavior conflict):** numbered H3 headings for the non-K-3 blocks of Section 1 (UI-SPEC "every table caption is the preceding H3/H2"); `SECTION_TITLES` defined in `render_common` and re-exported from `render`; a `.gitattributes` `-text` rule for the golden directory (the repo has `core.autocrlf=true`, which would otherwise rewrite the golden's line endings on a Windows checkout); `join_blocks` and `RenderError` helpers.

**Total deviations:** 2 Rule 2 additions plus additive items. **Impact:** none on plan intent; the escape hardening only makes hostile-string handling stricter than the spec's list.

## TDD Gate Compliance

- Task 1: RED `4388625` (collection error, `src.analytics.render` missing), GREEN `127a4f6`.
- Task 2: RED `9ca8800` (11 tests failing on missing headings and the missing golden), GREEN `838afb2`. The golden was written from the actual output only after reading the whole rendered document against the UI-SPEC. No REFACTOR commits.

## Issues Encountered

None blocking. Baselines unchanged: mypy on `src/analytics` reports only the pre-existing `src/adapters/telegram_notify.py:287` error; `ruff check src/analytics tests/test_analytics_render.py` and `ruff format --check` on the four new files are clean; the full `pytest -q -x` suite passes.

## Verification

- `pytest tests/test_analytics_render.py -k "primitives or header or banner or budget or clock or tracer"`: pass (15 selected).
- `pytest tests/test_analytics_render.py tests/test_analytics_purity.py tests/test_analytics_typing.py`: pass; `ruff check src/analytics tests/test_analytics_render.py`: clean.
- Plan-level verification `pytest tests/test_analytics_render.py tests/test_analytics_report.py tests/test_analytics_purity.py tests/test_analytics_typing.py`: pass.

## Known Stubs

None.

## Threat Flags

None - the modules are pure (no network, auth, file or schema surface). T-10-33 to T-10-36 are covered by the hostile-string, state-sentence/golden, reserved-vocabulary and byte-rule/ambient-state tests above.

## Next Phase Readiness

Ready for 10-11 (Sections 3-10 renderers slot into `render_markdown` and use the same primitives). JRN-01 and GOV-01 are shared with 10-11 and 10-12, so `requirements.ready-ids` reported 0 of 2 ready and they are left unmarked. Open item for the operator (D7): review the real-viewer legibility of the 11-column K-2b table and the H3 layout.

## Self-Check: PASSED

- Created files exist on disk (src/analytics/render_common.py, src/analytics/render_killgate.py, src/analytics/render.py, tests/test_analytics_render.py, tests/fixtures/phase10/render_golden/expected_sections_0_2.md, .gitattributes); commits 4388625, 127a4f6, 9ca8800, 838afb2 exist in `git log`.
