# test.ps1 - run the whole unit test suite via uv/pytest with monitoring output.
#
# Output:
#   - one line per test with [NN%] progress and PASSED/FAILED (-v)
#   - "[timing] collection" line right after collection
#   - failure/skip/xfail reasons summary (-ra)
#   - 15 slowest tests (setup/call/teardown), hiding those under 0.1s
#   - phase timing: collection vs execution vs total
#
# Extra arguments are forwarded to pytest and win over the defaults, e.g.:
#   scripts/dev/test.ps1 -k approval -x
#   scripts/dev/test.ps1 tests/test_approval_message.py
#   scripts/dev/test.ps1 --durations=30 --durations-min=0.5

. (Join-Path $PSScriptRoot '_common.ps1')
try {
    Assert-Uv

    # Make scripts/dev importable so `-p pytest_timing` resolves.
    $pp = if ($env:PYTHONPATH) { "$PSScriptRoot;$env:PYTHONPATH" } else { $PSScriptRoot }
    Set-ScopedEnv 'PYTHONPATH' $pp

    # -o addopts= drops pyproject's "-q" (it would cancel -v).
    uv run pytest -o addopts= -p pytest_timing -v -ra --durations=15 --durations-min=0.1 @args
    $code = $LASTEXITCODE
} finally {
    Exit-RepoRoot
}
exit $code
