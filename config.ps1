# Shared settings for the step scripts. Dot-sourced, not run.
# MUSIC_DIR is read from config.sh so the shell and PowerShell steps (and the GUI) share one value.
$MusicDir = ([regex]::Match((Get-Content -Raw "$PSScriptRoot\config.sh"), '(?m)^MUSIC_DIR="([^"]*)"')).Groups[1].Value
$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Set-Location $PSScriptRoot
& $Python -c "import mutagen" 2>$null
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("mutagen missing: $Python -m pip install --user -r requirements.txt")
    exit 1
}
