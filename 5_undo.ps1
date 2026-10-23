# Undo a previous apply. Dry run unless --apply is given.
#   .\5_undo.ps1 undo_20261020_140000.jsonl [--apply]
. "$PSScriptRoot\config.ps1"
if (-not $args) {
    [Console]::Error.WriteLine("usage: .\5_undo.ps1 undo_XXXX.jsonl [--apply]")
    Get-ChildItem undo_*.jsonl -ErrorAction SilentlyContinue | ForEach-Object Name
    exit 1
}
$log, $rest = $args
& $Python apply_changes.py --undo $log @rest
exit $LASTEXITCODE
