# clean.ps1 - remove caches and logs from the project.
#
# Removes: __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, .coverage, htmlcov, logs/
# Never touches: .venv, data/ (immutable raw Parquet store), backup/, .env
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/clean.ps1
#   ... -File scripts/dev/clean.ps1 -WhatIf    # preview only

[CmdletBinding(SupportsShouldProcess)]
param()

. (Join-Path $PSScriptRoot '_common.ps1')

try {
    $dirNames = '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'logs'
    $fileNames = '.coverage'
    $skip = '[\\/](\.venv|\.git)([\\/]|$)'

    $targets = @()
    $targets += Get-ChildItem -Path $RepoRoot -Recurse -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch $skip }
    foreach ($n in $dirNames) {
        $p = Join-Path $RepoRoot $n
        if (Test-Path $p) { $targets += Get-Item $p -Force }
    }
    foreach ($n in $fileNames) {
        $p = Join-Path $RepoRoot $n
        if (Test-Path $p) { $targets += Get-Item $p -Force }
    }

    foreach ($t in $targets) {
        if ($PSCmdlet.ShouldProcess($t.FullName, 'Remove')) {
            Remove-Item -LiteralPath $t.FullName -Recurse -Force
        }
    }
    Write-Host "Cleaned $($targets.Count) item(s)."
} finally {
    Exit-RepoRoot
}
