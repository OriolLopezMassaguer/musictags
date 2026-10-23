# Arranca la GUI escuchando SOLO en 127.0.0.1.
#   .\gui-local.ps1
# Argumentos extra van a gui.ps1, p.ej. .\gui-local.ps1 --port 9000
& "$PSScriptRoot\gui.ps1" --host 127.0.0.1 @args
exit $LASTEXITCODE
