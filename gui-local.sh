#!/bin/sh
# Arranca la GUI escuchando SOLO en 127.0.0.1, para usarla a través de un túnel SSH.
# Nada queda expuesto en la red local: el cortafuegos de DSM deja de importar.
#
#   ./gui-local.sh              en el NAS
#   tunnel.ps1                  desde el portátil Windows (abre el túnel y el navegador)
#
# Argumentos extra van a gui.sh, p.ej. ./gui-local.sh --port 9000
cd "$(dirname "$0")" || exit 1
exec ./gui.sh --host 127.0.0.1 "$@"
