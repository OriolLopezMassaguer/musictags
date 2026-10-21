#!/bin/sh
# GUI web para todo el proceso. Se abre desde cualquier equipo de la red local.
#   ./gui.sh                 http://<ip-del-nas>:8765
#   ./gui.sh --port 9000     otro puerto
#   ./gui.sh --token secreto exige ?t=secreto (recomendado si la red no es de fiar)
. "$(dirname "$0")/config.sh"
"$PYTHON" -c "import flask, markdown" 2>/dev/null || {
    echo "faltan dependencias: $PYTHON -m pip install --user -r requirements.txt" >&2
    exit 1
}
exec "$PYTHON" -m gui.app "$@"
