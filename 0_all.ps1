# Steps 1-4 one after another, stopping at the first failure.
#
#   .\0_all.ps1                 scan, analyze, propose, and a dry run of apply
#   .\0_all.ps1 --skip-scan     start at step 2 (the library has not changed)
#
# Nothing is written to your music files: step 4 runs as a dry run, exactly as
# the "Todo seguido" button in the GUI does. Writing stays .\4_apply.ps1 --apply.
#
# Ctrl-C stops the running step at its next safe point (exit 130) and the
# remaining steps are skipped.
#
# It takes no other arguments: per-step flags go on the individual wrappers
# (.\3_propose.ps1 --only genre), or in the GUI, where each step keeps its form.
Set-Location $PSScriptRoot

$steps = @(".\1_scan.ps1", ".\2_analyze.ps1", ".\3_propose.ps1", ".\4_apply.ps1")
if ($args -contains "--skip-scan") { $steps = $steps[1..3] }

foreach ($step in $steps) {
    ""
    "===== $step ====="
    & powershell -NoProfile -ExecutionPolicy Bypass -File $step
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        if ($code -eq 130) {
            [Console]::Error.WriteLine("Interrumpido en $step; los pasos siguientes no se lanzan.")
        } else {
            [Console]::Error.WriteLine("$step ha fallado con el código $code; la cadena se detiene.")
        }
        exit $code
    }
}

""
"Listo. Revisa changes.csv (o la pestaña Cambios) y aplica con .\4_apply.ps1 --apply"
