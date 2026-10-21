<#
.SYNOPSIS
    Abre un tunel SSH al NAS y la GUI de musictags en el navegador.

.DESCRIPTION
    La GUI no tiene login, asi que lo prudente es no publicarla en la red local: se
    arranca en el NAS escuchando solo en 127.0.0.1 (./gui-local.sh) y se llega a ella
    por un tunel SSH. Asi no hay que abrir nada en el cortafuegos de DSM.

    El tunel sigue abierto mientras este script corra. Ctrl+C lo cierra.

.PARAMETER NasHost
    IP o nombre del NAS.

.PARAMETER User
    Usuario SSH del NAS.

.PARAMETER Port
    Puerto en el que escucha la GUI dentro del NAS.

.PARAMETER LocalPort
    Puerto en este ordenador. Por defecto, el mismo que el remoto.

.PARAMETER RepoPath
    Carpeta del repo en el NAS. Solo se usa con -Start.

.PARAMETER Token
    Si arrancaste la GUI con --token, pasalo aqui y la URL lo llevara.

.PARAMETER Start
    Arrancar tambien la GUI en el NAS si no estuviera ya corriendo.

.PARAMETER NoBrowser
    No abrir el navegador.

.EXAMPLE
    .\tunnel.ps1
    Tunel contra una GUI que ya esta corriendo en el NAS.

.EXAMPLE
    .\tunnel.ps1 -Start
    Arranca la GUI en el NAS si hace falta, abre el tunel y el navegador.

.EXAMPLE
    .\tunnel.ps1 -NasHost 192.168.1.3 -User oriol -LocalPort 9000
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string] $NasHost   = '192.168.1.2',
    [string] $User      = 'biblioteca',
    [int]    $Port      = 8765,
    [int]    $LocalPort = 0,
    [string] $RepoPath  = '/volume1/musica/musictags',
    [string] $Token     = '',
    [switch] $Start,
    [switch] $NoBrowser
)

$ErrorActionPreference = 'Stop'

if ($LocalPort -le 0) { $LocalPort = $Port }
$target = '{0}@{1}' -f $User, $NasHost
$url    = 'http://localhost:{0}/{1}' -f $LocalPort, $(if ($Token) { "?t=$Token" } else { '' })

function Test-Listening {
    param([int] $TcpPort)
    $client = New-Object System.Net.Sockets.TcpClient
    try     { $client.Connect('127.0.0.1', $TcpPort); return $true }
    catch   { return $false }
    finally { $client.Dispose() }
}

# --- comprobaciones previas --------------------------------------------------
$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $ssh) {
    throw 'No encuentro ssh.exe. Instalalo en Configuracion -> Aplicaciones -> ' +
          'Caracteristicas opcionales -> Agregar -> Cliente OpenSSH.'
}

if (Test-Listening $LocalPort) {
    throw ('El puerto local {0} ya esta ocupado; quiza el tunel ya esta abierto en ' +
           'otra ventana. Prueba -LocalPort con otro numero.') -f $LocalPort
}

# --- arrancar la GUI en el NAS -----------------------------------------------
if ($Start) {
    Write-Host "Comprobando la GUI en $NasHost ..." -ForegroundColor Cyan
    # Se mira el puerto, no el proceso: es lo que de verdad importa, y este NAS no
    # trae pgrep. El comando remoto no lleva ni una comilla doble, porque PowerShell
    # 5.1 no las escapa bien al pasar argumentos a un .exe nativo como ssh.
    $alive  = "netstat -tln | grep -q '127.0.0.1:$Port '"
    $remote = "cd '$RepoPath' && " +
              "if $alive; then echo 'ya estaba corriendo'; " +
              "else nohup ./gui-local.sh --port $Port >gui.log 2>&1 & sleep 8; " +
              "if $alive; then echo arrancada; " +
              "else echo 'NO ha arrancado; mira gui.log en el NAS'; exit 1; fi; fi"

    & $ssh.Source $target $remote
    if ($LASTEXITCODE -ne 0) { throw 'No se ha podido arrancar la GUI en el NAS.' }
}

# --- el tunel ----------------------------------------------------------------
Write-Host ''
Write-Host ('Tunel  localhost:{0}  ->  {1}:{2}' -f $LocalPort, $target, $Port) -ForegroundColor Green
Write-Host "       $url"
Write-Host '       Ctrl+C para cerrarlo.'
Write-Host ''

$sshArgs = @(
    '-N',                               # solo reenvio de puertos, sin shell remota
    '-o', 'ExitOnForwardFailure=yes',   # fallar si el puerto local no se puede ceder
    '-o', 'ServerAliveInterval=30',
    '-L', ('{0}:127.0.0.1:{1}' -f $LocalPort, $Port),
    $target
)

$proc = Start-Process -FilePath $ssh.Source -ArgumentList $sshArgs -NoNewWindow -PassThru

try {
    # Esperar a que el tunel levante, vigilando por si ssh se muere por el camino.
    $ready = $false
    foreach ($attempt in 1..40) {
        if ($proc.HasExited) { break }
        if (Test-Listening $LocalPort) { $ready = $true; break }
        Start-Sleep -Milliseconds 400
    }

    if ($proc.HasExited) {
        throw ('ssh ha terminado con codigo {0}. Revisa el usuario y la IP, y que el ' +
               'servicio SSH este activo en DSM (Panel de control -> Terminal y SNMP).' -f $proc.ExitCode)
    }
    if (-not $ready) {
        throw 'El tunel no responde. Puede que la GUI no este corriendo en el NAS: ' +
              'vuelve a lanzarlo con -Start.'
    }

    Write-Host 'Tunel abierto.' -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process $url }

    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) { Write-Warning ('ssh ha salido con codigo {0}.' -f $proc.ExitCode) }
}
finally {
    if (-not $proc.HasExited) {
        Write-Host 'Cerrando el tunel...' -ForegroundColor Yellow
        $proc.Kill()
    }
    Write-Host 'Tunel cerrado.' -ForegroundColor Yellow
    if ($Start) {
        Write-Host 'La GUI sigue corriendo en el NAS. Para pararla:' -ForegroundColor DarkGray
        Write-Host ('  ssh {0} ''pkill -f "[g]ui[.]app"''' -f $target) -ForegroundColor DarkGray
    }
}
