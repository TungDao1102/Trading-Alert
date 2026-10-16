"""Evaluate one exported soak evidence bundle against the ratified trial criteria (plan 16-25).

    python scripts/evaluate_trial_soak.py --bundle <dir> --config <toml> --out <file>
        [--workflow .github/workflows/paper_freeze_check.yml]

The bundle (`soak-evidence-bundle/1`) is verified file by file against its manifest SHA-256, then
`src/paper/exit_criteria.evaluate_trial` prints PASS or FAIL per criterion with the evidence it
read, and the same text is written to `--out`. The numbers the user owns (health silence and
lateness, the continuous-uncovered ceiling, the freeze-tick grace) come only from `--config`, the
ratified runtime configuration (`load_runtime_config`); the scheduled cron string is read from the
freeze workflow file. Nothing here changes a threshold, reads a clock or touches the network.

The parity criterion (tolerance zero) is rebuilt from the bundle alone: its recorded replay
inputs and acceptance log (plan 16-51) and the registry parameter set named by the pinned epoch,
loaded from `--registry-root` (default: the live registry). A bundle without replay inputs, a
registry set whose hash differs from the pin or a set that cannot be loaded gives parity NOT
EVALUATED and FAIL, never exit 2.

Exit codes: 0 every criterion passes; 1 at least one criterion fails; 2 the input is unusable (a
bundle that is incomplete or edited after export, a PARTIAL bundle whose `as_of_utc` is before the
window end plus the freeze-tick grace (plan 16-59), a configuration that is not ratified, a
workflow file without exactly one schedule cron). A message names the file or key, never a value.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.paper.evidence_bundle import (  # noqa: E402
    BundleError,
    EvidenceBundle,
    bundle_is_partial,
    load_evidence_bundle,
)
from src.paper.exit_criteria import (  # noqa: E402
    NO_REPLAY_INPUTS_REASON,
    ParityReplay,
    ParityUnavailable,
    build_parity_replay,
    evaluate_trial,
    has_recorded_replay_inputs,
    read_backfill_rule,
)
from src.paper.freeze import load_parameter_set_at_root, resolve_registry_root  # noqa: E402
from src.paper.runtime_config import ConfigNotRatified, load_runtime_config  # noqa: E402

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INPUT = 2

DEFAULT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "paper_freeze_check.yml"
_CRON_LINE = re.compile(r"^\s*-?\s*cron:\s*[\"']([^\"']+)[\"']\s*(?:#.*)?$", re.MULTILINE)


class WorkflowError(Exception):
    """The freeze workflow file does not name exactly one schedule cron string."""


def read_workflow_cron(path: Path) -> str:
    """The one cron string of the freeze workflow (the recorded schedule of the trial)."""
    if not path.is_file():
        raise WorkflowError(f"{path.name} does not exist")
    crons = sorted(set(_CRON_LINE.findall(path.read_text(encoding="utf-8"))))
    if len(crons) != 1:
        raise WorkflowError(f"{path.name} must name exactly one schedule cron, found {len(crons)}")
    return crons[0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--bundle", required=True, type=Path, help="bundle directory")
    parser.add_argument("--config", required=True, help="ratified runtime configuration (TOML)")
    parser.add_argument(
        "--q-d-decision",
        required=True,
        type=Path,
        help="the user's Q-D decision file (REST_BACKFILL rule); there is no default",
    )
    parser.add_argument("--out", required=True, type=Path, help="evaluation file to write")
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=None,
        help="registry root holding the pinned parameter set (default: the live registry root)",
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        default=DEFAULT_WORKFLOW,
        help="freeze workflow file holding the schedule cron",
    )
    return parser


def bundle_parity(
    bundle: EvidenceBundle, registry_root: Path | None
) -> ParityReplay | ParityUnavailable:
    """The parity replay of a bundle: its recorded inputs and the registry set it pinned.

    Only the epoch's own records are replayed. Every way the replay cannot be built is a
    `ParityUnavailable` with its reason (NOT EVALUATED, FAIL), never an exit code.
    """
    mine = [r for r in bundle.records if r.epoch_id == bundle.epoch_id]
    if not has_recorded_replay_inputs(mine):
        return ParityUnavailable(NO_REPLAY_INPUTS_REASON)
    try:
        parameter_set = load_parameter_set_at_root(
            bundle.pinned.strategy_id,
            bundle.pinned.parameter_set_id,
            resolve_registry_root(registry_root),
        )
    except Exception as exc:  # any load failure is a missing comparison, reported by type name
        return ParityUnavailable(
            f"the pinned parameter set cannot be loaded from the registry ({type(exc).__name__})"
        )
    return build_parity_replay(
        mine,
        parameter_set=parameter_set,
        pinned_parameter_set_hash=bundle.pinned.parameter_set_hash,
    )


def main(argv: Sequence[str] | None = None, *, parity: ParityReplay | None = None) -> int:
    """Run the evaluation. `parity` is a test seam (the 16-25 replay context); without it the
    parity replay is built from the bundle and the pinned registry set (`bundle_parity`)."""
    args = _parser().parse_args(argv)
    try:
        bundle = load_evidence_bundle(args.bundle)
        config = load_runtime_config(args.config)
        cron = read_workflow_cron(args.workflow)
        rule = read_backfill_rule(args.q_d_decision)
    except (BundleError, ConfigNotRatified, WorkflowError, ValueError, OSError) as exc:
        print(f"cannot evaluate: {exc}", file=sys.stderr)
        return EXIT_INPUT
    if bundle_is_partial(bundle, config.health.freeze_tick_grace_seconds):
        print(
            "cannot evaluate: the bundle is a partial export (as_of_utc is before the window end "
            "plus the freeze-tick grace); export the final bundle to judge the trial",
            file=sys.stderr,
        )
        return EXIT_INPUT
    evaluation = evaluate_trial(
        bundle,
        thresholds=config.health,
        cron=cron,
        symbols=config.symbols,
        backfill_rule=rule,
        parity=parity if parity is not None else bundle_parity(bundle, args.registry_root),
    )
    text = evaluation.render()
    print(text)
    args.out.write_text(text + "\n", encoding="utf-8")
    return EXIT_PASS if evaluation.passed else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
