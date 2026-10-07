---
phase: 15-strategy-geometry-correction
reviewed: 2026-10-07T00:00:00Z
depth: deep
files_reviewed: 3
files_reviewed_list:
  - src/paper/freeze.py
  - src/paper/loop.py
  - tests/test_paper_start_gate.py
findings:
  critical: 0
  warning: 5
  info: 5
  total: 10
status: issues_found
---

# Phase 15: Code Review Report (plan 15-17 paper-start gate)

**Reviewed:** 2026-10-07
**Depth:** deep (cross-checked tests/test_paper_parity.py, test_paper_closed_candle.py, test_paper_feed_gates.py, test_paper_reviewfix_pins.py, src/domain/registry.py, src/domain/rationale.py, src/paper/supervisor.py)
**Files Reviewed:** 3
**Status:** issues_found

## Summary

The gate is structurally sound for its stated threat model. In `run_paper_tick` the gate sits before any candle, account, constraint or cost parse. The strategy_version check, `pin_stream_epoch` and the loop-versus-gate hash equality check all fail closed. The allowlist is read at call time, and a set with rationale tables never reaches the allowlist branch. The 16 tests in `test_paper_start_gate.py` pass, and ruff and mypy are clean on `src/paper`.

No production caller of `run_paper_tick` exists in `src/` (the supervisor only mentions it in a comment). The gate therefore protects the function, and the review found no path that skips it.

I found no BLOCKER, but there are fail-open edges and guard or test weaknesses. The main ones:
- Any truthy value for `allow_unrationalized` disables the gate (verified).
- The AST guard has verified blind spots.
- The refusal tests do not prove all of what the docstring claims.
- The rationale verdict and the hash come from different reads of the file.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Any truthy `allow_unrationalized` disables the gate (fail-open on type confusion)

**File:** `src/paper/freeze.py:494`, `src/paper/loop.py:315,355`
**Issue:** The gate is skipped with `if not allow_unrationalized:`. The annotation is `bool`, but nothing enforces it. A caller that forwards a config or CLI string (`"False"`, `"0"`, `"no"`) or an int gets a non-empty or non-zero value and silently skips the gate. I verified this: `pin_stream_epoch(strategy_id="trend-pullback", parameter_set_id="baseline-v3", opened_at_utc=..., allow_unrationalized="False")` returns an epoch for a set with no rationale tables, with the allowlist empty. For a fail-closed safety gate the bypass should be exactly `is True`, and anything else should be refused or rejected as a type error.
**Fix:**
```python
if allow_unrationalized is not True:
    _require_rationalized(...)
```
Optionally, at the top of `pin_stream_epoch` and `run_paper_tick`, raise `TypeError` when `not isinstance(allow_unrationalized, bool)`. Add a test that passes `"False"` and `1` and expects refusal or `TypeError`.

### WR-02: The AST guard "no src module enables the flag" has verified blind spots

**File:** `tests/test_paper_start_gate.py:424-446, 363-406`
**Issue:** The guard flags only `kw.value.value is True`. I ran `_scan_src_violations` over a seeded tree and it returned `[]` for each of these:
- `g(allow_unrationalized=1)` in `paper/loop.py`. `1` is truthy, so it disables the gate (see WR-01).
- Other non-literal-True truthy values: a variable bound to True, `not False`, and a `"yes"` string. Files outside `FLAG_FILES` are caught by the substring check. `paper/loop.py` and `paper/freeze.py` are not.
- `globals()['PAPER_START_ALLOWLIST'] = (...)` inside `paper/freeze.py`. `_bound_names` walks a Subscript target and sees only the Name `globals` and a Constant, so the allowlist name is not recognised. `_bound_names` also ignores for-targets, with-as, walrus, `def` and `class` rebinding.
- The module-level binding check requires a tuple literal but not an empty one. `(entry,)` passes the AST guard. Emptiness rests only on `test_production_allowlist_is_empty_by_user_decision` and `test_kill_gate_docs`. That is acceptable, but the docstring of `_scan_src_violations` implies more coverage than exists.

The docstring admits "a name built at runtime is not visible", but it does not list these cheap static forms.
**Fix:**
- In the call check, flag any keyword `allow_unrationalized` whose value is not the literal `False` or a bare `Name` equal to `allow_unrationalized`. The `Name` case is valid only in `run_paper_tick`.
- In `_bound_names`, also handle `ast.Subscript` with a string-Constant slice, `ast.NamedExpr`, `For`/`With` targets, and `FunctionDef`/`ClassDef` names.
- Add seeded cases for each to `test_guard_helper_reports_every_seeded_violation`.

### WR-03: The refusal tests do not prove the docstring's "before any candle is parsed or feed event read"

**File:** `tests/test_paper_start_gate.py:51, 95-115`; `src/paper/loop.py:319`
**Issue:** `SPIED_NAMES = (_parse_candle, _is_closed_event, evaluate, plan, evaluate_risk)`. In `run_paper_tick`, `_parse_account_state`, `_parse_constraint_snapshot`, `build_cost_model`, `_parse_open_positions`, `_coerce_money`, `assert_sizing_costs_bind_registry`, `resolve_absolute_thresholds` and `check_feature_validity` all run before `_parse_candle`. If a refactor moved the gate to just above `_parse_candle`, all refusal tests would still pass, yet the loop would already have parsed the caller's account state, constraint snapshot and cost model for a refused set. `loop.py:319` says "before any candle is parsed or feed event read", and `_is_closed_event` is the only feed-event spy. Reading `case_input["feed_events"]` is not observed at all.

`test_gate_and_loop_must_judge_the_same_file` asserts only `spies["_parse_candle"] == []`.
**Fix:** Cheaper and stronger: pass a `case_input` whose every field after `parameter_set_id` and `now_utc` is poisoned (for example `symbol` or `feed_events` missing, `account_state` malformed). Then assert `UnrationalizedParameterSet` is raised rather than `KeyError`/`TypeError`. Alternatively extend `SPIED_NAMES` with `_parse_account_state`, `_parse_constraint_snapshot`, `build_cost_model`, `check_feature_validity` and `assert_sizing_costs_bind_registry`.

### WR-04: The public gate entry `pin_stream_epoch` does not validate registry path segments

**File:** `src/paper/freeze.py:309-326, 490-499`
**Issue:** `load_parameter_set` runs `_check_registry_segment` on both ids (WR-05 in registry.py). The gate's own loader `_load_parameter_set_with_root` does not. The rationale check also derives its ids from the path (`path.parent.name`, `path.stem` in `rationale._parameters`). `run_paper_tick` is protected only because it calls `load_parameter_set` first. `pin_stream_epoch` is exported from `src.paper` and is the real policy decision point, but its `strategy_id` and `parameter_set_id` flow unvalidated into `registry_root / strategy_id / f"{parameter_set_id}.toml"`. Ids such as `../x` or an absolute segment steer the read outside the registry, limited only by the in-file `strategy.strategy_id` equality check. `_recompute_parameter_set_hash` has the same gap.
**Fix:** Call `_check_registry_segment` (export it or add a public wrapper) at the top of `_load_parameter_set_with_root` and `_recompute_parameter_set_hash`, raising `UnregisteredParameterSet`. Add a test for `pin_stream_epoch(strategy_id="../trend-pullback", ...)`.

### WR-05: The rationale verdict and the hash come from different reads of the file

**File:** `src/paper/freeze.py:380, 420-428, 492-499`; `src/domain/rationale.py:67, 171, 185`
**Issue:** In one gate pass the file at `root/strategy_id/<id>.toml` is read and parsed several separate times:
- `load_parameter_set` in the loop.
- `_load_parameter_set_with_root`, which determines the hash.
- `_has_rationale_tables`.
- `check_rationale`, which reads twice (`_parameters` and `_read_doc`).
- `placeholder_keys`.

The loop's equality check proves only that the loader's two reads agree. It does not prove that the bytes judged for rationale, or the placeholder verdict, are the bytes whose hash was compared (or allowlisted). A file replaced between reads (the soak host edits registry files, and the freeze monitor exists precisely because they can change) can pass the allowlist or rationale check as one content and run as another. The window is narrow, but this is the one place a fail-closed policy check is explicitly TOCTOU-prone, and fixing it is cheap.
**Fix:** Read `path.read_bytes()` once in `pin_stream_epoch` and thread the text through (`_parse_and_validate(text, ...)`, `tomllib.loads(text)`, and text-accepting variants of `check_rationale` and `placeholder_keys`). Alternatively re-hash after the rationale check and compare to `parameter_set.parameter_set_hash`.

## Info

### IN-01: `PaperAllowlistEntry` promises a "64-hex lowercase" hash but validates nothing

**File:** `src/paper/freeze.py:348-368`
**Issue:** The docstring says "Full 64-hex lowercase parameter_set_hash". There is no `__post_init__`. An uppercase, truncated or empty hash, or empty ids, is accepted silently. It then never matches, which is fail-closed, but the user's approved entry would be dead with only a generic refusal message. `purpose`, `approved_at` and `basis` are free text and unchecked, although the module treats them as the audit record of the user's checkpoint decision.
**Fix:** Add `__post_init__` mirroring `StreamEpoch` (64 lowercase hex, non-empty ids, ISO date for `approved_at`, non-empty `purpose` and `basis`). Add a test.

### IN-02: Stale or misleading docstrings

**File:** `src/paper/loop.py:334-337`, `src/paper/loop.py:10-15`, `src/paper/freeze.py:316`
**Issue:**
- `run_paper_tick` still says "pure function of the input dict ... No clock reads, no I/O". It now performs several registry file reads, and its outcome depends on the mutable module global `PAPER_START_ALLOWLIST` and on the files on disk. That was already true of `load_parameter_set`, but 15-17 widens it.
- The docstring has no `Raises:` section for the new refusal paths (`UnrationalizedParameterSet`, the `ValueError` for hash mismatch, `UnregisteredParameterSet`, bare `KeyError` from the cost slice).
- The module docstring says it imports "NOTHING" beyond stdlib, Decimal and `src/core/_decimal.py`, but it imports `src.backtest`, `src.domain`, `src.risk` and now `src.paper.freeze` (which pulls `structlog`).
- `_load_parameter_set_with_root` cites `src/domain/registry.py:372`. `load_parameter_set` is at line 568.
**Fix:** Update the docstrings. State that registry reads occur and that the verdict depends on `PAPER_START_ALLOWLIST`.

### IN-03: "Stream-start" gate actually runs per tick; the pinned epoch is discarded; exception type depends on order

**File:** `src/paper/loop.py:343-362`
**Issue:**
- `pin_stream_epoch` is called with `opened_at_utc=now_utc` on every call, and the returned epoch is used only for its hash. No `write_pinned_state` is performed, so the "stream-start" label and `epoch.evidence_claim_open` are cosmetic here. Per-call enforcement is stricter and safe, but the docs and comments should not imply a persisted stream epoch.
- The strategy_version `ValueError` at lines 345-350 precedes the rationale gate. A stale fixture version on a refused set raises `ValueError`, not `UnrationalizedParameterSet`. A caller that catches only the latter to mean "refused by policy" will mis-handle it.
- The error messages and ordering are otherwise fail-closed.
**Fix:** Either rename the comments and docs to "per-call gate", or move the version check after `pin_stream_epoch`. Document the exception contract.

### IN-04: Test-quality nits in `test_paper_start_gate.py`

**File:** `tests/test_paper_start_gate.py:263-278, 296, 304-307, 334-349, 456-480`
**Issue:**
- Part (b) of `test_injected_entry_never_admits...` patches `freeze.REGISTRY_ROOT` although `registry_root=tmp_path` is passed explicitly, so the patch is redundant.
- `strict["feed_events_processed"] >= 1` in `test_fully_rationalized_set_runs_without_the_flag` counts closed events that passed the closed-candle gate. It does not show that evaluate ran. The digest equality with the flagged run is the real assertion.
- `test_import_with_the_empty_allowlist_emits_no_error_or_warning` spawns a subprocess and asserts that import works. It proves nothing specific about the allowlist or the gate.
- The seeded-violation test ties each message to the right file only for some conjunctions. For `other/w.py` and `freeze.py`, `"PAPER_START_ALLOWLIST" in joined` is satisfied by any line.
- An empty `[rationale]` table, a `rationale = "x"` scalar and a non-trend-pullback family are not tested against the allowlist-versus-rationale branch decision in `_has_rationale_tables`.
- Every pre-existing paper suite (parity, closed-candle, feed-gates, reviewfix-pins) now runs with the gate off, so only one test exercises the gate-on happy path.
**Fix:** Tighten the assertions as above. Add an empty-`[rationale]` case and the scalar case, and assert each message is tied to the expected path.

### IN-05: Two independent `REGISTRY_ROOT` bindings let the gate and the loop read different files

**File:** `src/paper/freeze.py:81-85, 491`; `src/domain/registry.py:41, 579`
**Issue:** `freeze.REGISTRY_ROOT` is bound at import time and the loop's `load_parameter_set` uses `registry.REGISTRY_ROOT`. The hash equality check in `loop.py` catches content divergence, which is why `test_gate_and_loop_must_judge_the_same_file` exists. But the rationale and allowlist verdict is formed from the freeze-root file while the loop's parameters come from the registry-root file. When the two files are byte-identical in `[parameters]` but differ in rationale tables (the hash excludes `[rationale]`), the verdict applies to a different file than the one that runs.
**Fix:** Have `run_paper_tick` pass the registry root it actually used, or have `pin_stream_epoch` accept an already-loaded `ParameterSet` and path. Alternatively resolve `registry.REGISTRY_ROOT` at call time inside `pin_stream_epoch` instead of binding it at import.

---

_Reviewed: 2026-10-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
