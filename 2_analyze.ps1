# Step 2: write report.md and schema.proposed.toml from tags.sqlite.
. "$PSScriptRoot\config.ps1"
if (-not (Test-Path tags.sqlite)) {
    [Console]::Error.WriteLine("tags.sqlite not found: run .\1_scan.ps1 first")
    exit 1
}
& $Python analyze_tags.py --fuzzy @args
if ($LASTEXITCODE -ne 0) { exit 1 }
if (-not (Test-Path schema.toml)) {
    ""
    "Next: review report.md, then  Copy-Item schema.proposed.toml schema.toml  and edit it."
}
