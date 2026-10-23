# Step 3: write changes.csv from tags.sqlite + schema.toml.
# Extra arguments are passed through, e.g. .\3_propose.ps1 --only genre,style
. "$PSScriptRoot\config.ps1"
if (-not (Test-Path schema.toml)) {
    [Console]::Error.WriteLine("schema.toml not found: Copy-Item schema.proposed.toml schema.toml and edit it")
    exit 1
}
& $Python propose_changes.py @args
exit $LASTEXITCODE
