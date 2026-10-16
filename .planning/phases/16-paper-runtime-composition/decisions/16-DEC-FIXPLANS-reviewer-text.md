# 16-DEC-FIXPLANS reviewer text: the owner decisions adopted by 16-DEC-FIXPLANS.md (verbatim copy)

source: the block "Phase 16 — Owner decisions" that the user pasted on 2026-10-16 in the conversation where 16-DEC-FIXPLANS.md was recorded (commit bdbdc11). The user's framing line before the block named "phase 18"; the block itself is about Phase 16 plans 16-55 to 16-61.
copied by: the planner on 2026-10-16, byte for byte from the conversation log, so that plans can quote it. Nothing below was edited.
authority: 16-DEC-FIXPLANS.md. Where its seven corrections amend this text, the correction wins: (1) unless-stopped restarts a runtime-initiated exit 0, so the held refused start needs an explicit unhealthy marker; (2) the paper heartbeat follows the 120 s feed-liveness or loop-alive signal, any frame on the connection qualifies, and the user provides a second secret URL; (3) the 16-59 Q2 queueing sentence is replaced by "detect and record each missing tick explicitly; never infer a clean result from a missing artifact"; (4) identical bytes at an existing key are a success, different bytes an error; (5) 16-56 and the B1-WR-09 wiring land in one paper-runtime-v2.toml before the epoch pin; (6) Phase 16 keeps D072 and D073; (7) 16-61 verifies the frozen manifest hash under simulator 2.2.0 before writing any authorization file and stops if the exact hashes cannot be verified.

---- verbatim text begins on the next line ----
# Phase 16 — Owner decisions

Prepared 2026-10-16. These are the owner decisions for the specified Phase 16 gates. They authorize only the actions explicitly stated below.

## 16-55 — Image and deploy

### Q1 — Restart after host reboot or Docker daemon restart

**Decision: A — `restart: unless-stopped` plus hold on refused start.**

Reason: A Docker restart policy must cover both an application exit and a daemon restart. The official Docker documentation states that `on-failure` does not restart a container when the daemon restarts, whereas `unless-stopped` does. The trial cannot rely on an operator being present to restart a service after a reboot.

The startup-refusal behavior is an explicit amendment to the prior "a refused start exits at once" rule. When startup is refused, the process must enter a held, non-operational state: no paper tick, no signal processing, no new journal event that suggests a healthy runtime, and no order-related action. The healthcheck and heartbeat must report startup refusal as unhealthy, not healthy. A refused startup must remain clearly observable and must never be confused with a running soak.

The managed service must preserve the requested-stop behavior: an intentional stop must remain stopped until the operator starts it again.

Rejected options and failure scenarios:
- B: rejected because changing the exit code does not solve the documented `on-failure` daemon-restart limitation. A host or daemon restart may leave the runtime stopped and exceed the coverage gap ceiling.
- C: rejected as written because a boot unit alone does not establish recovery after an independent Docker daemon restart. A manual stop being undone on the next boot is also an avoidable operational surprise.
- D: rejected because manual recovery after a reboot is not guaranteed within the 900-second uncovered-gap ceiling.

Before landing, test the refused-start, requested-stop, process-crash, host-reboot and Docker-daemon-restart paths. If the held refusal state cannot be distinguished reliably from a healthy runtime, stop and report a blocker rather than weakening the guard.

### Q2 — Hung-runtime detection

**Decision: B — a separate heartbeat check for the paper runtime.**

Chosen monitoring values:
- Heartbeat interval: 60 seconds.
- Expected check period: 60 seconds.
- Grace period: 120 seconds.
- Use a separate secret heartbeat URL from the existing host/service heartbeat.

Reason: The paper runtime must have an independently observable liveness signal. One combined alert cannot distinguish failure of the general host heartbeat from failure of the paper process. A dedicated check should detect a missed paper heartbeat well before the 900-second uncovered-gap ceiling, allowing time for human investigation or restart.

The heartbeat must be emitted only while the paper runtime is genuinely healthy. A held startup refusal or hung event loop must not continue to report success.

Rejected options and failure scenarios:
- A: rejected because one shared alert obscures which service failed and delays diagnosis.
- C: rejected because the existing unhealthy probe takes approximately 3900 seconds to declare the runtime unhealthy, already beyond the 900-second ceiling. A timer acting only on that probe cannot protect this trial's coverage criterion.
- D: rejected because documentation alone does not detect a hung process.

The heartbeat is an alerting mechanism, not proof of recovery. If the runtime stays down long enough to exceed the coverage ceiling, the trial must fail that criterion.

### Q3 — `--pin-epoch`

**Decision: A — pin the epoch and exit 0; immediately start the managed service.**

Reason: Pinning and running are separate operations. The pin command must finish before the managed runtime starts, allowing one clear process owner and a deterministic transition to the soak.

The pin-to-service gap counts toward the 900-second uncovered-gap ceiling. The operator must start the managed service as the next operational step, without an unrelated task in between.

Rejected option:
- B: rejected because the one-off Compose process may interact unpredictably with its restart policy and the single-instance guard. The guard could reject the managed service while the one-off process remains the active or ambiguous instance.

The existing single-instance guard remains mandatory. Do not weaken or bypass it.

## 16-56 — Feed fails closed

### Q1 — In-process silence watchdog

**Decision: B — add a new health threshold in `paper-runtime-v2.toml`.**

Register the new key:

`health.feed_silence_timeout_seconds: 120`

The watchdog must detect when the expected inbound feed has stopped, including a half-open connection for which the SDK supplies no receive timeout. At 120 seconds without a qualifying inbound message, the runtime must fail closed, mark feed health as unhealthy/unknown, and enter the existing bounded recovery path. It must not generate late signals for missed candles.

This threshold is distinct from the ratified 3900-second coverage-silence and healthcheck-bar-age values. The configuration and plan 16-43 must explicitly name and pin `paper-runtime-v2.toml`.

Rejected options and failure scenarios:
- A: rejected because reusing 3900 seconds means silence is detected too late to protect the 900-second coverage ceiling.
- C: rejected because a half-open connection may never reach the existing retries-exhausted path, leaving the process apparently alive while feed input is stale.

Test normal feed activity, a clean disconnect, a half-open connection and recovery. A watchdog timeout must not be treated as permission to process missed candles.

### Q2 — Zero `minute_close_lag_seconds`

**Decision: A — the loader must reject zero.**

Keep the existing value 5 seconds. Enforce the same positive-value rule in the configuration validator and the poller contract.

Rejected option:
- B: rejected because polling exactly at candle close has no demonstrated guarantee that the final bar is complete. Reading a partial or not-yet-published bar could create non-deterministic candle processing.

## 16-57 — Crash consistency and configuration identity

### Q1 — Bind effective runtime configuration to the pinned epoch

**Decision: B — hash canonical, parsed configuration values and refuse a semantic mismatch.**

The pin and every service start must record the SHA-256 of the canonical, validated effective configuration values. Every start must recompute this hash and refuse to operate on a mismatch, using exit code 6 and the held/non-operational refusal state from 16-55.

Canonicalization must:
- Validate the complete schema before hashing.
- Reject missing and unknown keys rather than silently ignoring them.
- Include all effective values; do not inject implicit defaults that are absent from the registered configuration.
- Use deterministic key ordering and deterministic serialization.

A change to any effective value during a trial invalidates the pinned configuration and must not be allowed to continue under the same epoch. Whitespace or comment-only edits must not create a different effective configuration identity.

The raw file SHA-256 may be recorded separately for forensic provenance, but it is not the semantic comparison used by the guard.

Rejected options and failure scenarios:
- A: rejected because a comment or whitespace edit would refuse a semantically unchanged configuration. This creates unnecessary trial interruption without strengthening the effective-value guarantee beyond the canonical hash.
- C: rejected because a changed configuration would continue operating during the trial and only be found by the evaluator afterwards. For example, changed `risk_rate` could affect the trial without an immediate refusal.
- D: rejected because an audit-only hash does not prevent a mismatched configuration from operating.

## 16-59 — Evidence export

### Q1 — Hourly and final evidence object keys

**Decision: A — each bundle gets its own immutable key.**

Use:

`<epoch>/<as_of>-<sha12>/`

Apply this layout to hourly and final bundles. Use create-only/immutable publication semantics consistent with O-01; do not replace an existing object at the same key. Retain the configured bucket versioning and the existing no-retention/no-Object-Lock decisions.

Reason: A uniform unique-key scheme removes the collision that currently breaks the second hourly publish and preserves each bundle independently.

Rejected options and failure scenarios:
- B: rejected because it introduces separate hourly/final publication semantics and a special final location without providing a necessary advantage over unique per-bundle keys.
- C: rejected because replacing an hourly object violates the immutability requirement even if bucket versioning can retain older versions.
- D: rejected because it reverses O-01 hourly publication timing and leaves the soak dependent on host-disk survival until the final bundle is published.

### Q2 — Freeze-check diff-log aggregation

**Decision: B — merge available run artifacts and deduplicate by run ID.**

Retain the original workflow artifacts unchanged. Produce a deterministic derived log that merges the relevant lines from all available workflow-run artifacts, with provenance back to each run ID. Do not describe the merged file as a byte-for-byte copy of a single artifact.

The concurrency group remains enabled. Where supported by the repository's GitHub Actions configuration, configure queueing so required runs are not silently replaced by newer pending runs. If a required run is cancelled before producing an artifact, record that missing run/tick explicitly; do not infer a clean result from the absence of an artifact.

Rejected option:
- A: rejected because reading only the newest artifact can permanently lose lines from earlier runs and make the evidence incomplete while appearing clean.

## 16-60 — Research warm-up fix

### Q0 — 50-day warm-up span

**Decision: ACCEPT.**

Use:

`warmup_span_days = 50`

This follows `ceil(max(1000 × 1h, 300 × 4h))`: the 4-hour context requirement is 1200 hours, which is 50 days. Load price history only before each Development or Validation window as required to initialize indicators. Do not read Holdout data or use prices from the Holdout period.

The first Development window remains cold because the available dataset begins at `2024-10-03T00:00:00Z`. Do not pretend the missing pre-window history exists. Record this boundary limitation explicitly in the new evidence and evaluation. Do not move the Development start just to hide it.

Rejected option: stopping the warm-up fix would leave the previously identified warm-up-insufficient bars in every window, including Validation folds for which historical price candles are available. The new warm-up process must not change the strategy parameter grid.

### Q1 — Decision record numbering

**Decision: A.**

- D072: protocol v2.5.0 warm-up amendment.
- D073: regeneration inventory and disposition of the original records.

D071 is already occupied. Preserve its existing decision and do not reuse its number.

Rejected option B: rejected because one row would combine a protocol amendment and a research regeneration inventory, weakening traceability between the semantic change and its generated evidence.

### Q2 — Holdout marker metadata

**Decision: YES — authorize the one-field edit.**

Authorize changing only the `protocol_version` metadata field from v2.4.0 to v2.5.0 in the Holdout marker file. Keep its entries empty. Do not read Holdout data, add any consumption record, alter other fields, or treat this metadata update as Holdout use.

Rejected option: refusing the field update would leave the marker version inconsistent with the protocol header and fail the required alignment test. This is a metadata alignment action only, not authorization to evaluate Holdout.

### Q3 — Directory for regenerated records

**Decision: A — use a separate directory.**

Use:

`docs/research/experiments/research-run-1-v2-2-0/`

Keep the original directory and every original record untouched. The new location must not cause directory-wide globs, reports or digest generation to mix the original and regenerated record sets.

Rejected options:
- B: rejected because relying on every reader to filter by simulator version is fragile; one reader that omits the filter could silently combine incompatible evidence.
- C: rejected because a separate owner-named path is unnecessary when a version-specific path has already been designated here.

### Q4 — Fresh authorization for the rerun

**Decision: B — add a required sixth authorization field and enforce it in the runner.**

Add the required key:

`simulator_semantics_version: "2.2.0"`

The runner must reject an authorization whose semantics version is absent or differs from the active simulator. Create three new family-specific authorization files. Bind each to the exact frozen manifest hash and the matching registered grid hash. Do not use or modify the old authorization files for the new run.

Rejected option A: rejected because file names and dates are human conventions, not machine-enforced safety constraints. The old authorization could still pass the grid/manifest hash checks while authorizing runs under different simulator semantics.

## 16-61 — Fresh research authorization and execution

### Fresh authorization in the owner's words

I authorize one regenerated research run under `simulator_semantics_version = 2.2.0` and `protocol_version = v2.5.0`, using the accepted 50-day price-only warm-up where pre-window history is available.

The run covers exactly the 3 registered strategy families, their existing 48 immutable parameter sets and the five existing Development/Validation windows, generating up to 240 records. The only allowed market-price history is that required by the registered windows and their pre-window warm-up. Do not run the Holdout window, read Holdout prices/returns/metrics or modify the Holdout consumption entries.

I authorize the agent to create the three fresh authorization files after the runner enforces the required `simulator_semantics_version` field and the relevant gates and tests pass. Each file must use the exact frozen manifest hash and the exact grid hash for that family, along with the existing required authorization fields. The sixth field must be `simulator_semantics_version: "2.2.0"`. Do not manufacture or guess hashes; stop if the exact expected hashes cannot be verified.

This authorization is limited to rerunning the registered Development/Validation research under the new semantics. It does not authorize changing parameters, choosing a new candidate from the new results, changing `strategy_version`, consuming Holdout, or making any live-trading decision. The already designated candidate `research-run-1-a01` remains the designated candidate unless I issue a separate decision.

### Assistant/agent permission to write the authorization files

**Approved**, subject to the conditions above. The agent may write and commit the three new authorization files when the plan, exact hashes, schema and validation tests are ready. It must not start the research run before the fresh authorization files and runner checks are validated.

### Sequential or parallel runs

**Decision: sequential.**

Run one strategy family at a time in this fixed order:
1. trend-pullback
2. breakout-retest
3. range-mr

Allow only one heavy research process at a time on the memory-limited development machine. Do not run families or heavyweight test suites in parallel with the research runner. Do not inspect intermediate performance summaries to change later family runs, parameters or the authorization. If a family run fails, stop and report its technical state; do not silently skip it or label the whole rerun complete.

### Wording for the original 240 records

Use this wording in D073 or the regeneration inventory:

"The original 240 records are retained unchanged as immutable historical evidence under the simulator semantics and protocol versions recorded in those records. They are superseded for the current confirmatory evaluation by the regenerated records produced under simulator_semantics_version 2.2.0 and protocol v2.5.0. The original records must not be pooled with the regenerated records, combined into their digests, or used as if both sets were produced under the same protocol and simulator semantics. The original artifacts and hashes remain available for historical audit and reproduction of the original run."

Do not edit, delete or rewrite the original record files. The supersession note must be a new decision/inventory artifact.

### Conditions before running

Before authorizing the actual execution:
- Complete 16-55 through 16-59 in the prescribed order.
- Complete the 16-60 semantics/version changes and required validation tests.
- Ensure D072 and D073 are recorded.
- Ensure the Holdout marker has only the authorized `protocol_version` change and its consumption entries remain empty.
- Ensure the runner enforces the sixth authorization field.
- Ensure all three fresh authorization files bind exactly to the frozen manifest and registered grid hashes.
- Ensure the new output directory is isolated from old records.

If any precondition fails, stop and report. Do not run a partial or differently configured study under the same authorization.

## Items with no plan yet

### B1-WR-09 — `rest_backfill_depth_bars`

**Decision: wire the key into the actual code path.**

Create a separate implementation plan. Preserve the currently recorded value `1500`, and ensure that the configured value is actually consumed by the intended REST backfill path. Add a test proving that changing the effective configured depth changes the requested history depth. Update the configuration and runbook documentation.

Do not silently remove a ratified setting, and do not leave an operator-facing configuration key that appears to control behavior but is ignored. The change must be landed and its effective value pinned before any trial that relies on it begins.

### B1-WR-04 and the 23 low-severity items

**Decision: remain deferred under their existing recorded dispositions.**

Do not expand the current plans to address them opportunistically. Preserve each disposition and do not mark an item resolved without evidence.

If the shutdown-order issue is found to corrupt or lose required evidence, prevent safe shutdown, or undermine a required fail-closed gate, reopen it before relying on affected evidence. Deferral is not permission to ignore a discovered safety or integrity failure.

### Items already deferred to Phase 26

Keep the kill-gate JSON-sidecar disclosure issue and the fixture evidence issue involving a real `DATABASE_URL` deferred to Phase 26 as already registered. Do not broaden Phase 16 to modify these items; do not use a real database URL in fixture tests.

## Overall execution boundary

The agent may execute the approved plans and author the specified records/files in the stated order. The decisions above do not authorize live trading, do not consume Holdout, and do not authorize any change to the registered parameter sets or strategy version.

All existing evidence must be preserved. If any plan cannot satisfy the approved semantics, hash binding, test gates or evidence integrity requirements, stop and report rather than substituting an unapproved behavior.
---- verbatim text ends on the previous line ----
