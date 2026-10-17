# 16-DEC-RERUN-AUTH-V230: the owner's authorization of the 2.3.0 rerun of research run 1

option: authorized-by-owner-script
decided by: user
date: 2026-10-17
source: .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V260.md
words:
> chọn A và đọc chặt, làm đi

(the owner's decision of 2026-10-17 for Option A and the strict reading; adopted again for the rerun by "adapt-all", read as adopt-all, in 16-DEC-V260.md) and the typed confirmation:

> AUTHORIZE 2.3.0

The owner ran the script themself in their own terminal. The agent ran only its `--check` form and wrote none of the three files.

## Scope text (as shown by the script, the owner's authorization of 2026-10-16 in 16-DEC-RERUN-AUTH.md with only the versions replaced)

> I authorize one regenerated research run under `simulator_semantics_version = 2.3.0` and `protocol_version = v2.6.0`, using the accepted 50-day price-only warm-up where pre-window history is available. The run covers exactly the 3 registered strategy families, their existing 48 immutable parameter sets and the five existing Development/Validation windows, generating up to 240 records, one family at a time in the order trend-pullback, breakout-retest, range-mr. The only allowed market-price history is that required by the registered windows and their pre-window warm-up. Do not run the Holdout window, read Holdout prices/returns/metrics or modify the Holdout consumption entries. This authorization is limited to rerunning the registered Development/Validation research under the new semantics. It does not authorize changing parameters, choosing a new candidate from the new results, changing `strategy_version`, consuming Holdout, or making any live-trading decision. The already designated candidate `research-run-1-a01` remains the designated candidate unless I issue a separate decision. The three 2.2.0 authorization files are not used.

## Files written by the owner's script (exclusive creation, six keys, committed unchanged by the executor)

- docs/research/preregistration/research-run-1-v2-3-0-authorization-trend-pullback.json
- docs/research/preregistration/research-run-1-v2-3-0-authorization-breakout-retest.json
- docs/research/preregistration/research-run-1-v2-3-0-authorization-range-mr.json

Each binds the recorded manifest hash ec161733076f99e626da6900b7cc354ed68aa3104f5ac60de486b3b39f7ac569, its own family's registered grid hash, `simulator_semantics_version` "2.3.0", `authorized_by` "Tung Dao" and `authorized_at_utc` 2026-10-17T14:54:52+00:00. They were verified by the executor with `load_authorization` and `require_authorized` against the real manifest and grids, without simulation (evidence/16-63-hashes.txt section 6).

## Script

Path: .planning/phases/16-paper-runtime-composition/scripts/16-63-sign-authorizations.py (sha256 3bb61687bad860cc8a1d5e2776d8a456a2d703a7a96f051b979b8064fd20a9d9). It recorded the repository HEAD at the owner's run: be98fd93ee0c7b7fd01ba39fb90cb25dd8d60cdc (a plan 18-26 docs commit landed after the commit 8bea35b that carries the script; docs only).

## Not used

The three 2.2.0 authorization files (docs/research/preregistration/research-run-1-v2-2-0-authorization-*.json), 16-DEC-RERUN-AUTH.md and the three five-key files stay in the repository, unused and unedited; the runner refuses them under 2.3.0 (evidence/16-63-hashes.txt section 3).
