# journal-report.ps1 - generate the offline journal-depth + kill-gate report.
#
# Thin wrapper over `uv run python -m src.analytics.cli`: reads the evidence / decision /
# universe files (and, when a database URL is configured in .env or the shell, read-only journal and live rows), then writes
# exactly two files under data/reports/ (git-ignored): journal-depth-<UTC>-<digest12>.md and
# the matching .json sidecar. Identical inputs and the same -AsOf give byte-identical files.
#
# Output (stdout): "Report: <path>", "Sidecar: <path>", "Digest: sha256:<hex>", "Kill gate: <STATE>".
#
# Parameters (relative paths are resolved from the repo root):
#   -AsOf <ISO-8601 with UTC offset>  report instant; omitted = the clock is read once at the edge
#   -OutDir <path>                    output directory (must stay under data/reports)
#   -Universe <path>                  research-universe file
#   -Evidence <path>                  analytics evidence file (backtest + paper records)
#   -Decisions <path>                 human decision record (default docs/research/kill_gate_decisions.json)
#   -RawRoot <path>                   1m candle store root (default data/raw)
#   -Record                           append ONE KILL_GATE_EVALUATION journal event (idempotent);
#                                     -Record is the only write besides the two report files
#   -NoDb                             never read a database, even when one is configured
#
# Exit codes: 0 report produced (also for a terminal INSUFFICIENT_EDGE state), 1 report could
# not be produced (nothing written), 2 invalid arguments.
#
# Usage:
#   scripts/dev/journal-report.ps1 -NoDb -AsOf 2027-04-01T00:00:00+00:00 -Evidence <file>
#   scripts/dev/journal-report.ps1 -Record

[CmdletBinding()]
param(
    [string]$AsOf,
    [string]$OutDir,
    [string]$Universe,
    [string]$Evidence,
    [string]$Decisions,
    [string]$RawRoot,
    [switch]$Record,
    [switch]$NoDb
)

. (Join-Path $PSScriptRoot '_common.ps1')
try {
    Assert-Uv
    if (-not $NoDb) { Import-DotEnv }

    # Map each supplied parameter to its CLI flag (array splatting; nothing is echoed).
    $cliArgs = @()
    if ($AsOf)      { $cliArgs += @('--as-of', $AsOf) }
    if ($OutDir)    { $cliArgs += @('--out-dir', $OutDir) }
    if ($Universe)  { $cliArgs += @('--universe', $Universe) }
    if ($Evidence)  { $cliArgs += @('--evidence', $Evidence) }
    if ($Decisions) { $cliArgs += @('--decisions', $Decisions) }
    if ($RawRoot)   { $cliArgs += @('--raw-root', $RawRoot) }
    if ($Record)    { $cliArgs += '--record' }
    if ($NoDb)      { $cliArgs += '--no-db' }

    uv run python -m src.analytics.cli @cliArgs
    $code = $LASTEXITCODE
} finally {
    Exit-RepoRoot
}
exit $code
