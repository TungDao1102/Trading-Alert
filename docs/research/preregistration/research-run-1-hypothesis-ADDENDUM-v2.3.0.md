# Research run 1 - addendum for protocol v2.3.0 (G3 global Holm, declared constraint assumption)

> Status: ADDENDUM to `docs/research/preregistration/research-run-1-hypothesis.md`, which is NOT edited and stays byte for byte as approved at decision O-02 (its hash is pinned by `tests/test_research_run1_registration.py`). Written under quick 261014-cvk.
> **This addendum is NOT an authorization to run research.** Every real research run still needs its own user authorization (O-03, plan 16-46). No experiment has been recorded, `docs/research/holdout_consumed.json` has no entries, and the Holdout is neither read nor consumed by this addendum.

## 1. Why an addendum

The hypothesis was approved on 2026-10-12 under protocol v2.2.0, where Holm-Bonferroni (G3) was applied per family. Protocol v2.3.0 (decisions D068 and D069, `docs/DECISIONS.md`) changes that rule and adds a declared constraint assumption before any result exists. A pre-registration may change only before a result is seen; none exists. The user re-affirmed hypothesis O-02 and the 48-point registration under the global Holm and the constraint assumption on 2026-10-14; the record is `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-V230.md`. The approved file is not rewritten; this addendum records what reads differently.

## 2. What changes for the hypothesis

1. **G3 is the global Holm.** G3 is one Holm-Bonferroni procedure at family-wise alpha = 0.05 over ONE set of 48 candidate-level one-sided p-values (16 per family, three families), the set fixed by the three registered grids, never reset per family and never extended by a re-run, a sensitivity scenario or a later look (D069). The set always holds all 48 p-values, including candidates that fail G1; a candidate with no closed Validation trade enters with p = 1. A candidate passes G3 only when its adjusted p-value is below 0.05. G2 stays a separate, uncorrected conjunct. The variant budget stays N = 25 per family. The power note is recomputed: the smallest Holm threshold is 0.05/48, a critical mean of about 0.37 R over 100 trades instead of about 0.35 R; it never changes a grid or a candidate choice. The sentence in section 8 item 1 of the hypothesis file that cites the per-family correction and "about 14%" is superseded by this item.
2. **The declared constraint assumption applies** (D068). The run reads the constraints from the baseline file `docs/research/preregistration/research-run-1-constraints-baseline.json`, sha256 `4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f` (scenario S0). Every constraint selection in the window is expected to carry the `extrapolated` flag; a result is valid only under this stated assumption. Scenario S1 (S0 with `BTCUSDT.min_notional = 100`) is a pre-registered descriptive stress test on Development and Validation only, with its own file, hash, manifest and authorization; the S1 file does not exist yet. S1 is never a selection input, S1 p-values never enter the G3 correction, and the Holdout is never read to compare scenarios.

## 3. What does not change

The three families; the 48 points and their order; the three grid files and their hashes; the 48 immutable parameter sets under `params/` and their hashes; `strategy_version` `v5.0.0` (protocol v2.3.0 changes no detection, entry, SL, TP, invalidation, expiry or feature definition, so TRADING_STRATEGY_SPEC section 12 requires no new strategy version); the hypothesis text itself; G1, G4 and G5 of the protocol; the split; the single-use Holdout rule; the fixed values and labels of the approved file.

## 4. What this addendum does not claim

It does not claim that multiplicity is complete end to end. The correction step is coded and tested on supplied p-values (`src/research/multiplicity.py`); the seeded one-sided stationary block-bootstrap p-value producer that G3 needs does not exist yet. The O-03b manifest and its freeze, the S1 constraint file, the REEFUSDT diagnostic and any run authorization remain separate work that needs its own decision.
