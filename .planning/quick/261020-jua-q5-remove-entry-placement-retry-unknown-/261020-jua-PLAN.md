---
phase: quick-261020-jua
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - tests/test_execution_manager.py
  - tests/test_adapter_not_found_mapping.py
  - src/execution/manager.py
  - docs/trading/EXECUTION_SPEC.md
  - .planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md
  - .planning/STATE.md
autonomous: true
requirements: [Q5]

estimate:
  tokens: 70000
  raw_tokens: 70000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "execute_approved_plan calls adapter.place_entry exactly once per approval for every failure kind (pre-send refusal, definitive rejection, 5xx, timeout, None response, unknown error) and for every probe answer (found True, found False, probe raises, indeterminate)"
    - "An ambiguous placement failure followed by found=False, a probe error or an indeterminate probe leaves the ENTRY intent UNKNOWN, enters SAFE_MODE once with reason ENTRY_STATE_UNKNOWN and returns RECONCILIATION_REQUIRED; it is never recorded REJECTED and never returns NO_TRADE EXCHANGE_CONSTRAINT"
    - "An ambiguous failure whose probe finds the order records the ENTRY ACKED and hands it to the protection registry, with no SAFE_MODE"
    - "A PreSendRefusal stays NO_TRADE ENTRY_REFUSED_BEFORE_SEND and a REJECTED_DEFINITIVE answer stays NO_TRADE EXCHANGE_CONSTRAINT; both have no probe and no SAFE_MODE"
    - "_place_entry_no_blind_retry has no loop, no recursion and no attempt-count knob, and an AST test fails if any of them comes back"
    - "EXECUTION_SPEC section 10 says a placement is never re-sent and that not-found after an ambiguous error is UNKNOWN; docs/DECISIONS.md and .planning/ROADMAP.md are unchanged"
    - "A DRAFT decision for the owner exists at .planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md, with the evidence and the owner-open numbers (O-04) left unset"
    - ".planning/STATE.md shows current_plan 17 in the frontmatter and Current Plan 17 in the body"
  artifacts:
    - path: src/execution/manager.py
      provides: "_place_entry_no_blind_retry as straight-line code (one place_entry, one probe); execute_approved_plan with no ABSENT or UNKNOWN_ERROR branch"
    - path: tests/test_execution_manager.py
      provides: "test_q5_place_entry_is_sent_once_for_every_error_kind (18 parametrized cases) and test_q5_entry_placement_has_no_resend_construct (AST guard)"
    - path: docs/trading/EXECUTION_SPEC.md
      provides: "section 10 rewritten for the never-resend rule"
    - path: .planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md
      provides: "proposed decision row text for the owner (DRAFT)"
  key_links:
    - from: "src/execution/manager.py::execute_approved_plan"
      to: "src/execution/manager.py::_place_entry_no_blind_retry"
      via: "single await, not inside a loop; its state ENTRY_STATE_UNKNOWN maps to SAFE_MODE + intent UNKNOWN + RECONCILIATION_REQUIRED"
      pattern: "entry_state == _ENTRY_STATE_UNKNOWN"
    - from: "tests/test_execution_manager.py::test_q5_entry_placement_has_no_resend_construct"
      to: "src/execution/manager.py"
      via: "ast.parse of inspect.getsource(src.execution.manager)"
      pattern: "_entry_resend_constructs"
---

<objective>
Q5, owner decision of 2026-10-20 (phase 19, branch p19-15): remove the second entry-placement attempt. Each approval sends exactly ONE `place_entry` POST; no code path sends it again (no loop, no recursion, no knob). After an ambiguous failure the order is probed once by its client id. If the probe answers found=False, raises, or gives an indeterminate answer, the result is UNKNOWN + SAFE_MODE + RECONCILIATION_REQUIRED, not REJECTED / NO_TRADE.

Purpose: `newClientOrderId` is unique only among OPEN orders. Binance documents no idempotency and no immediate query visibility, and `-1007` reads "Send status unknown; execution status unknown". So found=False right after an ambiguous error does not prove the order is absent. If a resting GTD entry that nobody tracks later fills, the position has no stop, because the coordinator places the stop only after a fill (D-10). Failing closed is better than missing a trade.

Output: one RED commit `test(q5): ...`, one GREEN commit `feat(q5): ...`, a docs commit (EXECUTION_SPEC section 10 plus the draft decision 19-DEC-Q5-DRAFT.md) and a STATE.md fix (current_plan 17).
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@AGENTS.md
@.planning/phases/19-execution-plan-binding-price-check/19-DEC-D055-DRAFT.md
@C:/Users/admin/.claude/projects/C--Users-admin-Music-Trading/memory/no-order-placement-retry.md

Working tree: ONLY this worktree (branch p19-15). Do not touch the main checkout. Do not push. Do not touch any plan 19-17 file. Do not edit docs/DECISIONS.md or the ROADMAP criteria. Every path below is relative to the repo root, and every command runs from the repo root.

CodeGraph: the `.codegraph` index lives in the main checkout and indexes master, not this branch. You may run `codegraph explore "<symbols>"` via Bash to get oriented, but read the worktree file before you Edit, because its line numbers and contents can differ from master.

Network: there are no Binance or Telegram calls. Unit tests use fakes. If anything network-related fails, retry at most once, then report.

Facts the planner found (do not re-derive):
- src/execution/manager.py, lines 227-358: the entry-state constants, the attempt-count constant (value 2) and its comment, `_placement_failure_category`, and `_place_entry_no_blind_retry`. The loop is `for _attempt in range(...)`. A `never_retry` flag is set from `safe_mode_eligible(category)`. When the probe answers found=False, the loop either returns the UNKNOWN_ERROR state or goes round again.
- src/execution/manager.py, lines 1049-1126: the `entry_state` branches in `execute_approved_plan`. UNKNOWN goes to SAFE_MODE `ENTRY_STATE_UNKNOWN` + intent UNKNOWN + RECONCILIATION_REQUIRED. REFUSED goes to intent REJECTED + NO_TRADE `ENTRY_REFUSED_BEFORE_SEND`. UNKNOWN_ERROR goes to SAFE_MODE `UNKNOWN_EXCHANGE_ERROR` + intent UNKNOWN. ABSENT and REJECTED go to intent REJECTED + NO_TRADE `EXCHANGE_CONSTRAINT`. Every other state goes to ACKED + hand-off.
- Grep of src/ and tests/ for the names that become dead, `ENTRY_ABSENT`, `ENTRY_UNKNOWN_EXCHANGE_ERROR`, the manager's `_UNKNOWN_EXCHANGE_ERROR` SAFE_MODE reason and `never_retry`: they appear only in src/execution/manager.py. The SAFE_MODE reason string "UNKNOWN_EXCHANGE_ERROR" is pinned only by three tests in tests/test_execution_manager.py (lines 1188, 1206, 1226), which this plan rewrites. docs/GLOSSARY.md section 9.4 lists `ENTRY_STATE_UNKNOWN` and does not list `UNKNOWN_EXCHANGE_ERROR`. `safe_mode_eligible` is used in manager.py only for the flag. It stays exported by src/domain/exchange_errors.py and pinned by tests/test_phase18_gate.py and tests/test_exchange_errors.py, so do not touch the domain module.
- `ENTRY_REFUSED_BEFORE_SEND` (a public constant) and `ENTRY_STATE_UNKNOWN` (in GLOSSARY 9.4) stay.
- The manager module has exactly one `.place_entry(` call site (line 319). Line 147 is the Protocol stub. The other placements, `place_algo_protective` (manager.py line 1425, protection.py line 868) and `place_market_close` (emergency_close.py line 342), have no attempt loop. Grep 2026-10-20 found `_MAX_ATTEMPTS` / `for _attempt` only in non-placement modules.
- FakeExecutionAdapter (tests/test_execution_manager.py lines 105-246): `entry_exceptions` and `query_exceptions` / `query_responses` are popped front-first. Once `entry_exceptions` is empty, `place_entry` returns the canned `_entry_response`, so a second send would show up as count 2. The constructor replaces `entry_response=None` with a default dict, so a None response needs `adapter._entry_response = None` after construction. With nothing queued, the probe answers `_query_response`, which is None by default (indeterminate).
- Helpers that already exist: `_run_plan`, `_status_unknown()` (SDK ServerError 503), `_probe(found)`, `_refusals()`, `PRE_PLACEMENT_READS`, `RecordingSafeModeController.entered_reasons`, `StubProtectionRegistry` (`.entries`, `.register_attempts`), `_build_live_context(case_input, protection_registry=...)`, `InMemoryExecutionIntentStore` (tests/support/intent_store_fakes.py, `.get_entry(approval_id=...)`).
- tests/test_binance_usdm_source_guard.py lines 295-360: `placement_retry_constructs` is the AST guard pattern (loops, awaits in loops, tenacity) for the adapter. Mirror it for the manager.
- tests/test_exchange_error_rejections.py lines 270-288 already asserts one `place_entry` and no probe for -1106/-4016/-4024 and stays green. It has no second-send or UNKNOWN_EXCHANGE_ERROR SAFE_MODE assertion, so no edit is expected.
- The PG suites (write-ahead, approval replay, exactly-once, callback redelivery) have no ambiguous-entry + found=False scenario. Their -4116 negative control (`test_negative_control_open_entry_is_rejected_with_4116_by_the_exchange`) reaches found=True, which is unchanged. They are regression gates only.
- workflow.tdd_mode is on: RED first, then GREEN, as separate atomic commits.
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: One place_entry per approval, end to end: RED table test + AST guard, then GREEN removal of the attempt loop</name>
  <files>tests/test_execution_manager.py, tests/test_adapter_not_found_mapping.py, src/execution/manager.py</files>
  <read_first>
    - src/execution/manager.py lines 60-75 (exchange_errors import), 227-358 (`_place_entry_no_blind_retry` and its constants), 1041-1136 (`entry_state` branches)
    - tests/test_execution_manager.py lines 105-300 (fake adapter, safe-mode recorder, StubProtectionRegistry) and 818-1227 (the CR-09 and Q5 block)
    - tests/test_binance_usdm_source_guard.py lines 295-360 (AST guard to mirror)
    - tests/test_exchange_error_rejections.py lines 270-288 (stays as is)
    - C:/Users/admin/.claude/projects/C--Users-admin-Music-Trading/memory/no-order-placement-retry.md (owner decision record)
  </read_first>
  <behavior>
    Each case below is one `_run_plan` call through execute_approved_plan (fake adapter, InMemoryExecutionIntentStore, RecordingSafeModeController, StubProtectionRegistry). In EVERY case, place_entry is called exactly once and place_algo_protective is never called by the manager (D-10).
    - pre_send_refusal (RestGateRefusal("RATE_LIMIT_PAUSE_429", 7)): 0 probes, (True, "ENTRY_REFUSED_BEFORE_SEND"), intent REJECTED, SAFE_MODE [], nothing registered.
    - definitive_rejection (BadRequestError(error_message="rejected", status_code=-1106)): 0 probes, (True, "EXCHANGE_CONSTRAINT"), intent REJECTED, SAFE_MODE [], nothing registered.
    - Four ambiguous kinds (server_5xx = `_status_unknown()`, timeout = TimeoutError("read timeout"), none_response = no exception with `_entry_response` None, unknown_error = RuntimeError("unmapped")) crossed with four probe answers, each with exactly 1 probe:
      - found (`_probe(found=True)`): (False, "OK"), intent ACKED, SAFE_MODE [], `len(registry.entries) == 1`.
      - absent (`_probe(found=False)`): (True, "RECONCILIATION_REQUIRED"), intent UNKNOWN, SAFE_MODE ["ENTRY_STATE_UNKNOWN"], `register_attempts == 0`.
      - probe_raises (a RuntimeError in `query_exceptions`): same as absent.
      - indeterminate (nothing queued, so the probe answers None): same as absent.
    - AST guard: `_place_entry_no_blind_retry` contains no For/AsyncFor/While/comprehension/generator, no call to itself and no tenacity/retry helper. The manager module has exactly one `.place_entry(...)` call, and it is inside that function. No loop in the module contains a call to `.place_entry` or to `_place_entry_no_blind_retry`. No module attribute name contains "MAX_ATTEMPTS". The guard reports a snippet that has the old loop shape, so it cannot pass vacuously.
  </behavior>
  <action>
<!-- planner-discipline-allow: _ENTRY_MAX_ATTEMPTS -->
<!-- planner-discipline-allow: never_retry -->
<!-- planner-discipline-allow: ENTRY_ABSENT -->
<!-- planner-discipline-allow: ENTRY_UNKNOWN_EXCHANGE_ERROR -->
<!-- planner-discipline-allow: safe_mode_eligible -->
RED (Q5, owner decision 2026-10-20). Edit tests/test_execution_manager.py:
(a) Add `test_q5_place_entry_is_sent_once_for_every_error_kind`, parametrized over the 18 cases in the behavior block. Use readable ids such as `server_5xx-absent`. Build each case's exception objects inside a factory function, called once per case and shaped like `_refusals()`, so no exception instance is shared between parametrized cases. Seed the adapter for the case and run `_run_plan` with `safe_mode_controller`, `intent_store` and `live_context=_build_live_context(case_input, protection_registry=registry)`. Assert the count of place_entry calls (always 1), the count of query_order_by_client calls (0 or 1), the absence of place_algo_protective, the outcome pair, `entered_reasons`, the ENTRY `intent_status` from `store.get_entry`, and the registry state. Put the reason in the docstring: an id unique only among open orders, no documented idempotency or immediate query visibility, the -1007 text, and D-10 (the stop is placed only after a fill).
(b) Replace `test_q5_the_second_entry_attempt_is_kept_and_pinned_at_two` with `test_q5_entry_placement_has_no_resend_construct`. Add a helper `_entry_resend_constructs(source: str) -> list[str]` that mirrors `placement_retry_constructs` in tests/test_binance_usdm_source_guard.py and reports what the AST-guard line of the behavior block lists, including "not defined" when the function is missing. Run it on `ast.parse(inspect.getsource(src.execution.manager))` and expect []. Assert that `[n for n in vars(manager) if "MAX_ATTEMPTS" in n] == []`. Assert that the helper gives a non-empty report for a short source string defining an async `_place_entry_no_blind_retry` that awaits `adapter.place_entry()` inside `for _ in range(2)`.
(c) Rename `test_definitive_absence_allows_exactly_one_retry` to `test_definitive_absence_after_an_ambiguous_error_is_unknown_not_a_resend`. The scenario is 5xx then `_probe(found=False)`. Assert the exact call list `[*PRE_PLACEMENT_READS, "get_position_mode", "place_entry", "query_order_by_client"]`, (True, "RECONCILIATION_REQUIRED"), SAFE_MODE ["ENTRY_STATE_UNKNOWN"], and ENTRY intent UNKNOWN (pass an InMemoryExecutionIntentStore).
(d) Delete `test_repeated_definitive_absence_is_bounded_no_trade`, `test_refusal_on_the_second_attempt_is_also_no_trade_before_send` and `test_a_second_unknown_exchange_error_is_not_retried_either`. Each needs a second send that can no longer happen, and (a) and (b) now cover them.
(e) In `test_an_unknown_exchange_error_absent_by_the_probe_is_never_retried` (rename it `..._is_unknown_and_never_resent`) and in `test_a_failing_error_facts_is_treated_as_an_unknown_exchange_error`, change the expected SAFE_MODE reason from "UNKNOWN_EXCHANGE_ERROR" to "ENTRY_STATE_UNKNOWN" and update the docstrings. Keep the intent UNKNOWN and the single-POST asserts.
(f) Docstring and naming only. Rename `test_ambiguous_entry_response_triggers_query_before_retry` to `test_ambiguous_entry_response_is_probed_and_never_resent`; its docstring and inline comments should say the probe decides between hand-off and UNKNOWN and never leads to a resend. Make the `_status_unknown` docstring say "an ambiguous placement failure" instead of "the retry rule". In tests/test_adapter_not_found_mapping.py, change the parenthetical on module docstring line 7 to say that a placement is never re-sent because of a found=False answer (Q5).
Do not edit tests/test_exchange_error_rejections.py; it stays green unchanged. Run the verify command. The expected failures are the four `*-absent` cases (three with 2 POSTs, unknown_error with the wrong reason), the AST guard, test (c) and the two tests in (e). Record the failing ids in the commit body. Commit `test(q5): pin one place_entry per approval and UNKNOWN on not-found after an ambiguous error`.

GREEN. Edit src/execution/manager.py:
- Delete the attempt-count constant `_ENTRY_MAX_ATTEMPTS` with its comment block, `_ENTRY_STATE_ABSENT`, `_ENTRY_STATE_UNKNOWN_ERROR`, and the `_UNKNOWN_EXCHANGE_ERROR` SAFE_MODE-reason constant with its comment. Also remove `safe_mode_eligible` from the `src.domain.exchange_errors` import, because its only use was the deleted flag. Keep `ENTRY_REFUSED_BEFORE_SEND`, `_ENTRY_STATE_PLACED`, `_ENTRY_STATE_EXISTS`, `_ENTRY_STATE_UNKNOWN`, `_ENTRY_STATE_REFUSED`, `_ENTRY_STATE_REJECTED` and `_placement_failure_category`.
- Rewrite the body of `_place_entry_no_blind_retry` as straight-line code and keep its name and signature. It makes one awaited `adapter.place_entry(**entry_kwargs)` in a try. A PreSendRefusal returns the REFUSED state. Any other Exception is classified with `_placement_failure_category`: REJECTED_DEFINITIVE returns the REJECTED state, and every other category leaves the response None. A non-None response returns PLACED with the same identity extraction as today. Otherwise it makes one probe with `query_order_by_client`. A probe exception returns UNKNOWN. A literal `found is True` returns EXISTS with order_id and status as today. Anything else (False, None, non-bool) returns UNKNOWN. The function has no flag, no loop and no second call.
- Rewrite the docstring: list the states without the two deleted ones. State the Q5 rule: exactly one POST per approval and no code path re-sends. Explain why found=False after an ambiguous error is UNKNOWN: the id is unique among open orders only, Binance documents no idempotency or immediate query visibility, -1007 reads "execution status unknown", and D-10 means a resting GTD entry nobody tracks would fill with no stop. Refer to the removed second attempt by concept. Never write the deleted constant or flag names in a comment or docstring (the acceptance grep counts comments). Add "Q5" to the section header comment.
- In `execute_approved_plan`, delete the UNKNOWN_ERROR branch and replace the `in (ABSENT, REJECTED)` test with `entry_state == _ENTRY_STATE_REJECTED`. Its comment becomes: definitively rejected by the exchange, so no exposure exists, NO_TRADE without SAFE_MODE. The UNKNOWN branch comment becomes: the probe could not tell, or did not find the order right after an ambiguous error, which is not proof of absence (Q5); the entry is never re-sent and nothing is handed off; SAFE_MODE `ENTRY_STATE_UNKNOWN` blocks new entries while reconciliation (Phase 20) resolves the truth. Do not change its behavior.
- Run the verify command, `uv run ruff check`, `uv run ruff format --check` and `uv run mypy src`. Fix only what this change caused. Commit `feat(q5): send the entry once; not-found after an ambiguous error is UNKNOWN + SAFE_MODE`.
  </action>
  <verify>
    <automated>uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_exchange_error_rejections.py tests/test_adapter_not_found_mapping.py -rs</automated>
  </verify>
  <acceptance_criteria>
    - RED commit `test(q5): ...` exists and its message names the failing test ids. GREEN commit `feat(q5): ...` follows it.
    - The verify command passes, and `uv run pytest -m "not docker" tests/test_execution_manager.py -k "q5" -q` collects at least 19 tests (18 table cases plus the AST guard) and all pass.
    - `grep -cE "_ENTRY_MAX_ATTEMPTS|never_retry|ENTRY_ABSENT|ENTRY_UNKNOWN_EXCHANGE_ERROR|safe_mode_eligible" src/execution/manager.py` prints 0.
    - `grep -c "ENTRY_STATE_UNKNOWN" src/execution/manager.py` prints at least 1. `grep -c "ENTRY_REFUSED_BEFORE_SEND" src/execution/manager.py` prints at least 1.
    - `uv run ruff check`, `uv run ruff format --check` and `uv run mypy src` all exit 0.
    - `git diff --quiet c3574d9 HEAD -- src/domain/exchange_errors.py tests/test_exchange_error_rejections.py` exits 0 (both files unchanged since the planning base c3574d9).
  </acceptance_criteria>
  <done>Each approval sends exactly one entry POST. After an ambiguous failure, found=False, a probe error or an indeterminate probe leads to intent UNKNOWN + SAFE_MODE ENTRY_STATE_UNKNOWN + RECONCILIATION_REQUIRED. found=True leads to hand-off. A refusal and a definitive rejection stay NO_TRADE. The AST guard and the 18-case table pin all of this, and RED and GREEN are committed separately.</done>
</task>

<task type="auto">
  <name>Task 2: EXECUTION_SPEC section 10 and the owner DRAFT decision 19-DEC-Q5-DRAFT.md</name>
  <files>docs/trading/EXECUTION_SPEC.md, .planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md</files>
  <read_first>
    - docs/trading/EXECUTION_SPEC.md lines 138-237 (sections 7 to 10.1)
    - docs/integration/BINANCE.md lines 97-114 (sections 6.1 and 6.2)
    - docs/SOURCES.md line 121 (Phase 17 live re-read row of newClientOrderId) and lines 219-249 ("Demo-observed facts")
    - src/domain/exchange_errors.py lines 173-179 (`_BASELINE` provenance) and lines 243-257 (-1006, -1007 rows)
    - .planning/phases/19-execution-plan-binding-price-check/19-DEC-D055-DRAFT.md (style to mirror)
  </read_first>
  <action>
<!-- planner-discipline-allow: only retry if absence is confirmed -->
docs/trading/EXECUTION_SPEC.md, section 10 ("No blind recovery"). Keep the heading and its number, because other documents point at "section 10". Leave subsection 10.1 word for word. Replace the three numbered rules (the third one reads "only retry if absence is confirmed") with prose that says:
- A placement is sent once. No code path re-sends it because of its own error or because of the probe that follows (Q5, owner decision 2026-10-20; the proposal for a DECISIONS row is `.planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md`, pending the owner). The adapter makes one attempt per placement call (source guard `tests/test_binance_usdm_source_guard.py`).
- For the entry (`_place_entry_no_blind_retry`, `src/execution/manager.py`), as a numbered list:
  1. A PreSendRefusal sent nothing: NO_TRADE `ENTRY_REFUSED_BEFORE_SEND`, no probe, no SAFE_MODE.
  2. REJECTED_DEFINITIVE: NO_TRADE `EXCHANGE_CONSTRAINT`, no probe, no SAFE_MODE.
  3. Any other failure or an empty response (timeout, 5xx, STATUS_UNKNOWN, UNKNOWN_EXCHANGE_ERROR, a failure that cannot be classified) is ambiguous, and the order is queried once by its deterministic client order id.
  4. Found: the ENTRY is recorded ACKED and handed to the protection coordinator.
  5. Not found, a probe error or an indeterminate answer: the ENTRY intent is UNKNOWN, SAFE_MODE is entered with reason `ENTRY_STATE_UNKNOWN`, and the outcome is `RECONCILIATION_REQUIRED`, never REJECTED.
- Why not-found is not absence here. The client id is unique only among open orders (`BINANCE.md` section 6.1). The Binance pages read do not document idempotency or immediate query visibility for a new order. `-1007` reads "Send status unknown; execution status unknown". The entry is a GTD LIMIT and its stop is placed only after a fill (D-10), so an entry wrongly recorded as REJECTED could fill with nothing protecting it.
- The UNKNOWN entry is resolved by query only, never by placing (section 10.1, Phase 20). Restart recovery (10.1) still records a not-found intent younger than the lookup window as REJECTED. Whether that rule may apply to an entry that went UNKNOWN after an ambiguous placement error, and any numbers for bounded reconciliation (windows, re-probe counts), are owner-open (O-04). This section sets none.
In section 7.2, change "is never re-sent blindly (section 10)" to "is never re-sent (section 10)". Section 7.1 does not mention a retry and stays unchanged.
docs/integration/BINANCE.md: no edit expected. Section 6.1 does not state a placement retry, and 6.2 already says a placement is never retried because of a classification. Confirm with `grep -n -i "retr" docs/integration/BINANCE.md`. If, against expectation, a line states that a placement is re-sent after a not-found answer, edit only that line and record it in the SUMMARY.

Create `.planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md` in the style of 19-DEC-D055-DRAFT.md, in plain English with short sentences:
- Title `# 19-DEC-Q5-DRAFT: proposed closure of Q5 (draft for the owner)`.
- Status line: DRAFT, not a DECISIONS row, docs/DECISIONS.md was not edited. The owner accepts, edits or rejects it, and a row (the next free id, D077 or later; the D055 draft also waits for a row) is written only after that.
- Basis: the owner's decision of 2026-10-20 (Q5) that answers the Phase 18 review item src/WR-02 and 19-RESEARCH Q5 (the second `place_entry` attempt), and quick task 261020-jua.
- Proposed text, numbered:
  (1) No order placement is re-sent after any error, whatever the error category and whatever the probe answers: no loop, no recursion, no configuration knob. This covers entries, protective stops, take-profits and closes.
  (2) The entry outcome table: refusal goes to NO_TRADE ENTRY_REFUSED_BEFORE_SEND; definitive rejection goes to NO_TRADE EXCHANGE_CONSTRAINT; an ambiguous error gets one probe, where found goes to ACKED + hand-off, and not-found, a probe error or an indeterminate answer go to intent UNKNOWN + SAFE_MODE ENTRY_STATE_UNKNOWN + RECONCILIATION_REQUIRED, never REJECTED or NO_TRADE.
  (3) An UNKNOWN entry is resolved by query only (intent recovery, Phase 20), and entries stay blocked until then.
  (4) Open part, owned by the owner (O-04): the numbers for bounded reconciliation (windows, re-probe counts) and whether the 3-day not-found rule of restart recovery (EXECUTION_SPEC 10.1) may apply to an entry that went UNKNOWN after an ambiguous error. None are proposed here.
- Evidence, each item with its source and confidence, copied and not re-fetched:
  - Binance New Order `newClientOrderId` "A unique id among open orders" (SOURCES.md, Phase 17 rows of 2026-10-01 and the live re-read of 2026-10-07; BINANCE.md 6.1). `-1007` TIMEOUT "Send status unknown; execution status unknown." and `-1006` "... Execution status unknown." (ERROR_CODE_TABLE in src/domain/exchange_errors.py, label documented, from research baseline B7 of 2026-10-15, a WebFetch summary that is not character-exact).
  - BINANCE.md 6.1: once an order is FILLED or CANCELED its id is free again; Query Order does not find old CANCELED or EXPIRED orders.
  - The Demo observations of 2026-10-16 in SOURCES.md "Demo-observed facts" (demo, not mainnet): a reused client id was accepted after CANCELED (normal and algo order) and after FILLED (normal order, second run); a duplicate clientAlgoId while the first order was open was rejected with -4116.
  - Say plainly that the pages read contain no statement of idempotency or immediate visibility. This is the absence of a statement, not a quote.
- Implementation status: done by quick task 261020-jua (the test(q5) and feat(q5) commits). The entry path was the only placement with a second attempt.
- Affected lines, to edit only after acceptance: the docs/DECISIONS.md row (new); no ROADMAP criterion names Q5. The owner-gap register of plan 19-17 lists Q5 and is not touched here.
Commit `docs(q5): execution spec section 10 never re-sends a placement; draft Q5 decision for the owner`.
  </action>
  <verify>
    <automated>grep -c "only retry if absence is confirmed" docs/trading/EXECUTION_SPEC.md; grep -c "ENTRY_STATE_UNKNOWN" docs/trading/EXECUTION_SPEC.md; grep -c "19-DEC-Q5-DRAFT" docs/trading/EXECUTION_SPEC.md; grep -cE "A unique id among open orders|execution status unknown|O-04|DRAFT" .planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md; git diff --quiet c3574d9 -- docs/DECISIONS.md .planning/ROADMAP.md && echo unchanged</automated>
  </verify>
  <acceptance_criteria>
    - In order, the verify prints 0, then at least 1, then at least 1, then at least 4, then `unchanged`.
    - `git show --stat <sha of the docs(q5) spec+draft commit>` lists only docs/trading/EXECUTION_SPEC.md and the new draft file (plus docs/integration/BINANCE.md only if the conditional edit was needed and is recorded).
    - Subsection 10.1 of EXECUTION_SPEC.md is byte-identical to the planning base (`git diff c3574d9 -- docs/trading/EXECUTION_SPEC.md` shows no changed line under "### 10.1").
    - The draft names no number for windows or re-probe counts.
  </acceptance_criteria>
  <done>Section 10 states the never-resend rule and the UNKNOWN outcome. The owner's draft decision exists with its evidence and the open O-04 part. DECISIONS.md and ROADMAP are untouched.</done>
</task>

<task type="auto">
  <name>Task 3: Fix STATE.md current_plan to 17 and run the full gate</name>
  <files>.planning/STATE.md</files>
  <read_first>
    - .planning/STATE.md lines 1-40 (frontmatter `current_plan: 11`, body `Current Plan: 1`)
  </read_first>
  <action>
Phase 19 plans 01-16 are done, so the next plan is 17. Both the frontmatter `current_plan` (11) and the body "Current Plan:" line (1) are stale. First try the GSD state verb: `node "$HOME/.claude/gsd-core/bin/gsd-tools.cjs" state update "Current Plan" 17`. Then read `git diff .planning/STATE.md`. The diff may change only the current-plan lines and the `last_updated` timestamp. If the verb changed anything else (progress counts, stopped_at, other fields), restore the file with `git checkout -- .planning/STATE.md` and make the minimal manual edit instead. If either line is still stale after the verb, fix that line with a minimal manual Edit. Do not add a quick-task row; the quick workflow owns that. Commit `docs(q5): STATE current_plan 17 (phase 19 plans 01-16 done)`.
Then run the full gate in this order, one pytest at a time. TEST_DATABASE_URL is set, so the PG tests must run and not skip.
1. `uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_exchange_error_rejections.py tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_execution_exactly_once_pg.py tests/test_callback_redelivery_pg.py tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py tests/test_protection_branches.py tests/test_binance_usdm_source_guard.py -rs`
2. `uv run ruff check`
3. `uv run ruff format --check`
4. `uv run mypy src`
If a PG test is SKIPPED, stop and report it; do not count it as a pass. If a failure is outside this change, report it with the test id and do not widen the scope.
  </action>
  <verify>
    <automated>grep -nE "^current_plan: 17$|^Current Plan: 17$" .planning/STATE.md</automated>
  </verify>
  <acceptance_criteria>
    - The verify prints two lines (frontmatter and body).
    - The full pytest command passes, and its `-rs` summary shows no SKIPPED line for any `*_pg.py` file. Ruff check, ruff format --check and mypy src exit 0.
  </acceptance_criteria>
  <done>STATE.md points at plan 17, and the full gate (the 10 test files, ruff, format, mypy) is green with the PG tests actually run.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| manager to Binance REST (placement) | The response to a POST can be lost or ambiguous; the exchange does not deduplicate a client id that is no longer open |
| manager to Binance REST (probe) | found=False right after an ambiguous POST is not authoritative |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-Q5-01 | Tampering (duplicate exposure) | `_place_entry_no_blind_retry` | high | mitigate | Exactly one `place_entry` call, with no loop, recursion or knob. The AST guard `test_q5_entry_placement_has_no_resend_construct` and the 18-case table test fail if a resend comes back |
| T-Q5-02 | Elevation of risk (unprotected fill) | `execute_approved_plan` UNKNOWN branch | high | mitigate | Not-found, a probe error or an indeterminate answer after an ambiguous error gives intent UNKNOWN + SAFE_MODE ENTRY_STATE_UNKNOWN + RECONCILIATION_REQUIRED (never REJECTED), so new entries stay blocked until reconciliation resolves the resting GTD entry |
| T-Q5-03 | Denial of service (missed trades, more SAFE_MODE) | entry path | low | accept | The owner chose fail-closed over a missed trade (Q5). Bounded reconciliation numbers are owner-open (O-04) |
| T-Q5-SC | Tampering | npm/pip/cargo installs | high | accept | No package is installed or changed by this plan; uv.lock is untouched |
</threat_model>

<verification>
- `uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_exchange_error_rejections.py tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_execution_exactly_once_pg.py tests/test_callback_redelivery_pg.py tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py tests/test_protection_branches.py tests/test_binance_usdm_source_guard.py -rs` passes, with no PG skip.
- `uv run ruff check`, `uv run ruff format --check` and `uv run mypy src` exit 0.
- `git log --oneline -5` shows test(q5), then feat(q5), then docs(q5) (spec + draft), then docs(q5) (STATE), on branch p19-15, not pushed.
- `git diff --quiet c3574d9 HEAD -- docs/DECISIONS.md .planning/ROADMAP.md` exits 0 (c3574d9 is the planning base), and `git diff --name-only c3574d9 HEAD` lists no `.planning/phases/19-execution-plan-binding-price-check/19-17-*` file.
</verification>

<success_criteria>
- Exactly one `place_entry` POST per approval for every error kind and probe answer, pinned by a parametrized table test and an AST guard.
- Ambiguous error + not-found / probe error / indeterminate gives UNKNOWN + SAFE_MODE ENTRY_STATE_UNKNOWN + RECONCILIATION_REQUIRED. found gives hand-off. Refusal and definitive rejection stay NO_TRADE.
- Dead entry states, the extra SAFE_MODE reason, the flag, the knob and the unused import are gone from src/execution/manager.py. ENTRY_REFUSED_BEFORE_SEND and ENTRY_STATE_UNKNOWN stay.
- EXECUTION_SPEC section 10 is updated. The owner DRAFT 19-DEC-Q5-DRAFT.md exists with the evidence and the O-04 open part. STATE current_plan is 17.
</success_criteria>

<output>
Create `.planning/quick/261020-jua-q5-remove-entry-placement-retry-unknown-/261020-jua-SUMMARY.md` when done. Include: the RED failing ids, the GREEN commit, the deleted and renamed tests with the reason for each, whether BINANCE.md needed an edit, the STATE method used (gsd-tools verb or manual), the full-gate results with the PG pass counts, and the open items for the owner (accept 19-DEC-Q5-DRAFT, O-04 numbers, the restart-recovery 3-day rule versus Q5 for Phase 20).
</output>
