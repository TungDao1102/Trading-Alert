# backup-drill.ps1 - thin PowerShell wrapper for the backup + scratch-restore drill.
#
# Per 02-05-PLAN.md: the PowerShell wrapper defers ALL logic to the
# Python module (`python -m src.ops.backup`). No SQL / copy / hashing
# logic lives in this script — it only forwards arguments and surfaces
# the module's exit code.
#
# Usage (operator, post-Compose-stack-up):
#   powershell -NoProfile -File scripts/backup-drill.ps1
#
# Environment:
#   BACKUP_TARGET     - off-host backup root (default: data/backup, the
#                       canonical path shared with DEFAULT_BUNDLE_ROOT and
#                       OFF_HOST_BACKUP_TARGET in .env.example).
#                       In production this is the OneDrive-synced
#                       directory selected in plan 01, so a primary-host
#                       loss does NOT destroy the backup (D-12).
#   SCRATCH_ROOT      - scratch root for the restore drill (default:
#                       data/backup-drill).
#   PARQUET_ROOTS     - `;`-separated parquet roots to include
#                       (default: data/raw). Paths containing spaces are
#                       supported — `;` is the ONLY separator (whitespace
#                       never splits, so OneDrive/user-dir roots survive).
#   PYTHON_BIN        - python interpreter to invoke (default: python).

[CmdletBinding()]
param(
    [string]$BackupTarget = $env:BACKUP_TARGET,
    [string]$ScratchRoot  = $env:SCRATCH_ROOT,
    [string]$ParquetRoots = $env:PARQUET_ROOTS,
    [string]$PythonBin    = $env:PYTHON_BIN
)

if (-not $BackupTarget)  { $BackupTarget  = $env:OFF_HOST_BACKUP_TARGET }
if (-not $BackupTarget)  { $BackupTarget  = "data/backup" }
if (-not $ScratchRoot)   { $ScratchRoot   = "data/backup-drill" }
if (-not $ParquetRoots)  { $ParquetRoots  = "data/raw" }
if (-not $PythonBin)     { $PythonBin     = "python" }

# Split on `;` ONLY (the documented separator) so roots under
# space-containing profiles (OneDrive/user dirs) survive as single
# paths; trim each entry and drop empties. Never split on whitespace:
# a space inside a path is data, not a separator.
$RootList = @($ParquetRoots -split ";" | ForEach-Object { $_.Trim() } | Where-Object { $_ })

Write-Host "backup-drill: bundle_root=$BackupTarget scratch_root=$ScratchRoot"

# Resolve the project root from this script's location so the wrapper
# works regardless of the operator's current working directory.
# Push-Location/Pop-Location (in try/finally) leaves the operator's
# shell directory untouched, even on space-containing repo paths.
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Join-Path $ScriptRoot ".."
Push-Location -Path "$ProjectRoot"
try {
    # Phase 1 — backup. The Python module owns the database dump + parquet copy +
    # manifest hashing.
    & $PythonBin -m src.ops.backup backup `
        --bundle-root   "$BackupTarget" `
        --parquet-roots $RootList `
        --pg-dump-path  "$(Join-Path "$BackupTarget" "pg.dump")"

    if ($LASTEXITCODE -ne 0) {
        Write-Error "backup phase failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }

    # Phase 2 — scratch-restore drill. The Python module wipes the scratch
    # root, copies the bundle's database dump + parquet payload back in,
    # then re-hashes and compares to the manifest.
    & $PythonBin -m src.ops.backup drill `
        --bundle-root   "$BackupTarget" `
        --scratch-root  "$ScratchRoot" `
        --pg-dump-path  "$(Join-Path "$ScratchRoot" "pg.dump")" `
        --parquet-roots $RootList

    if ($LASTEXITCODE -ne 0) {
        Write-Error "drill phase failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }

    Write-Host "backup-drill: drill-OK"
    exit 0
}
finally {
    Pop-Location
}
