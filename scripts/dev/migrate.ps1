# migrate.ps1 - apply Alembic migrations to the operational PostgreSQL DB.
#
# DATABASE_URL is read from .env (or the current shell). Postgres must be up
# (e.g. `docker compose up -d postgres`).
#
# Usage:
#   scripts/dev/migrate.ps1                 # upgrade to head
#   scripts/dev/migrate.ps1 -Revision <id>  # upgrade to a specific revision
#   scripts/dev/migrate.ps1 -Current        # show current revision only

[CmdletBinding()]
param(
    [string]$Revision = 'head',
    [switch]$Current
)

. (Join-Path $PSScriptRoot '_common.ps1')
try {
    Assert-Uv
    Import-DotEnv

    if ($Current) {
        uv run alembic current
    } else {
        uv run alembic upgrade $Revision
    }
    $code = $LASTEXITCODE
} finally {
    Exit-RepoRoot
}
exit $code
