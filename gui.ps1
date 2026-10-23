# GUI web para todo el proceso. Se abre desde cualquier equipo de la red local.
#   .\gui.ps1                 http://<ip>:8765
#   .\gui.ps1 --port 9000     otro puerto
#   .\gui.ps1 --token secreto exige ?t=secreto (recomendado si la red no es de fiar)
. "$PSScriptRoot\config.ps1"
& $Python -c "import flask, markdown" 2>$null
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("faltan dependencias: $Python -m pip install --user -r requirements.txt")
    exit 1
}
& $Python -m gui.app @args
exit $LASTEXITCODE
