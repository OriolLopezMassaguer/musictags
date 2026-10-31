# Step 2: write report.md and schema.proposed.toml from tags.sqlite.
# On a first run it also seeds schema.toml from the proposal; an existing one is kept.
. "$PSScriptRoot\config.ps1"
if (-not (Test-Path tags.sqlite)) {
    [Console]::Error.WriteLine("tags.sqlite not found: run .\1_scan.ps1 first")
    exit 1
}
& $Python analyze_tags.py --fuzzy @args
exit $LASTEXITCODE
