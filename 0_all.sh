#!/bin/sh
# Steps 1-4 one after another, stopping at the first failure.
#
#   ./0_all.sh                 scan, analyze, propose, and a dry run of apply
#   ./0_all.sh --skip-scan     start at step 2 (the library has not changed)
#
# Nothing is written to your music files: step 4 runs as a dry run, exactly as
# the "Todo seguido" button in the GUI does. Writing stays ./4_apply.sh --apply.
#
# Ctrl-C stops the running step at its next safe point (exit 130) and the
# remaining steps are skipped.
#
# It takes no other arguments: per-step flags go on the individual wrappers
# (./3_propose.sh --only genre), or in the GUI, where each step keeps its form.
cd "$(dirname "$0")" || exit 1

steps="./1_scan.sh ./2_analyze.sh ./3_propose.sh ./4_apply.sh"
[ "$1" = "--skip-scan" ] && steps="./2_analyze.sh ./3_propose.sh ./4_apply.sh"

for step in $steps; do
    echo
    echo "===== $step ====="
    # Run it, then read $? on its own line: inside `if ! cmd` the status is
    # the negation's (always 0), which silently loses the real exit code.
    "$step"
    code=$?
    if [ "$code" -ne 0 ]; then
        if [ "$code" = 130 ]; then
            echo "Interrumpido en $step; los pasos siguientes no se lanzan." >&2
        else
            echo "$step ha fallado con el código $code; la cadena se detiene." >&2
        fi
        exit "$code"
    fi
done

echo
echo "Listo. Revisa changes.csv (o la pestaña Cambios) y aplica con ./4_apply.sh --apply"
