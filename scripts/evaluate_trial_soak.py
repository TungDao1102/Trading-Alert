"""Evaluate one exported soak evidence bundle against the ratified trial criteria (plan 16-25).

    python scripts/evaluate_trial_soak.py --bundle <dir> --config <toml> --out <file>
        [--workflow .github/workflows/paper_freeze_check.yml]

The bundle (`soak-evidence-bundle/1`) is verified file by file against its manifest SHA-256, then
`src/paper/exit_criteria.evaluate_trial` prints PASS or FAIL per criterion with the evidence it
read, and the same text is written to `--out`. The numbers the user owns (health silence and
lateness, the continuous-uncovered ceiling, the freeze-tick grace) come only from `--config`, the
ratified runtime configuration (`load_runtime_config`); the scheduled cron string is read from the
freeze workflow file. Nothing here changes a threshold, reads a clock or touches the network.

Exit codes: 0 every criterion passes; 1 at least one criterion fails; 2 the input is unusable (a
bundle that is incomplete or edited after export, a configuration that is not ratified, a workflow
file without exactly one schedule cron). A message names the file or key, never a value.
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

from src.paper.evidence_bundle import BundleError, load_evidence_bundle  # noqa: E402
from src.paper.exit_criteria import ParityReplay, evaluate_trial, read_backfill_rule  # noqa: E402
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
        "--workflow",
        type=Path,
        default=DEFAULT_WORKFLOW,
        help="freeze workflow file holding the schedule cron",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, parity: ParityReplay | None = None) -> int:
    """Run the evaluation. `parity` is a seam for the replay context: the command line has no
    context of its own (the constraint snapshots and account state of the live run are not part of
    the bundle), so without it the parity criterion reads NOT EVALUATED and fails."""
    args = _parser().parse_args(argv)
    try:
        bundle = load_evidence_bundle(args.bundle)
        config = load_runtime_config(args.config)
        cron = read_workflow_cron(args.workflow)
        rule = read_backfill_rule(args.q_d_decision)
    except (BundleError, ConfigNotRatified, WorkflowError, ValueError, OSError) as exc:
        print(f"cannot evaluate: {exc}", file=sys.stderr)
        return EXIT_INPUT
    evaluation = evaluate_trial(
        bundle,
        thresholds=config.health,
        cron=cron,
        symbols=config.symbols,
        backfill_rule=rule,
        parity=parity,
    )
    text = evaluation.render()
    print(text)
    args.out.write_text(text + "\n", encoding="utf-8")
    return EXIT_PASS if evaluation.passed else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
