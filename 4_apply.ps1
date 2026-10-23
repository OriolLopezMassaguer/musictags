# Step 4: apply approved rows of changes.csv. Dry run unless --apply is given.
#   .\4_apply.ps1                      dry run
#   .\4_apply.ps1 --apply --limit 20   try on 20 files
#   .\4_apply.ps1 --apply              everything
. "$PSScriptRoot\config.ps1"
if (-not (Test-Path changes.csv)) {
    [Console]::Error.WriteLine("changes.csv not found: run .\3_propose.ps1 first")
    exit 1
}
& $Python apply_changes.py changes.csv @args
exit $LASTEXITCODE
