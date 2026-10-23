# Step 1: read the tags of every file into tags.sqlite (+ tags.csv).
# Extra arguments are passed through, e.g. .\1_scan.ps1 --full
. "$PSScriptRoot\config.ps1"
& $Python scan_tags.py $MusicDir --csv tags.csv @args
exit $LASTEXITCODE
