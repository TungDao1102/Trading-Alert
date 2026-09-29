# _common.ps1 - shared helpers for scripts/dev/*.ps1 (dot-source, do not run directly).

$ErrorActionPreference = 'Stop'

# Repo root = two levels above this file (scripts/dev -> scripts -> root).
$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
# Push (not Set) so the caller's location can be restored by Exit-RepoRoot.
Push-Location $script:RepoRoot
$script:EnvBackup = @{}

function Set-ScopedEnv {
    # Set an env var for this script run only; Exit-RepoRoot restores the old value.
    param([string]$Name, [string]$Value)
    if (-not $script:EnvBackup.ContainsKey($Name)) {
        $script:EnvBackup[$Name] = [Environment]::GetEnvironmentVariable($Name)
    }
    [Environment]::SetEnvironmentVariable($Name, $Value)
}

function Exit-RepoRoot {
    # Call from a `finally` block: restore location and env vars to the caller's state.
    foreach ($k in $script:EnvBackup.Keys) {
        [Environment]::SetEnvironmentVariable($k, $script:EnvBackup[$k])
    }
    Pop-Location
}

function Import-DotEnv {
    # Load KEY=VALUE lines from .env into the process env (existing vars win).
    param([string]$Path = (Join-Path $script:RepoRoot '.env'))
    if (-not (Test-Path $Path)) {
        Write-Warning ".env not found at $Path - relying on the current shell environment."
        return
    }
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([^=\s]+)\s*=\s*(.*)$') { continue }
        $name = $Matches[1]
        $value = $Matches[2].Trim().Trim('"').Trim("'")
        if (-not [Environment]::GetEnvironmentVariable($name)) {
            Set-ScopedEnv $name $value
        }
    }
}

function Assert-Uv {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv not found on PATH. Install it first: https://docs.astral.sh/uv/"
    }
}
