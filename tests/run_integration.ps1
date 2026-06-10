# Thin wrapper: the cross-platform launcher lives in run_integration.py.
# Usage: tests/run_integration.ps1 [pytest args...]
$ErrorActionPreference = "Stop"
& python "$PSScriptRoot/run_integration.py" @args
exit $LASTEXITCODE
