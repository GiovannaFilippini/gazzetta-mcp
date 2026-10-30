# Esegue UN comando dell'archivio (aggiorna, recupera, controlla, stato) con un lucchetto, cosi'
# due lavori non si sovrappongono, e salva il testo di cio' che e' successo in un file di registro.
#
# Uso (da PowerShell, nella cartella del progetto):
#   .\deploy\windows\lavoro.ps1 -Comando stato
#   .\deploy\windows\lavoro.ps1 -Comando recupera -Argomenti "--max-numeri 5 --max-atti 50"
param(
    [Parameter(Mandatory = $true)][ValidateSet('aggiorna', 'recupera', 'controlla', 'stato')][string]$Comando,
    [string]$Argomenti = ''
)

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$dati = Join-Path $env:LOCALAPPDATA 'gazzetta-mcp'
$cartellaLog = Join-Path $dati 'log'
New-Item -ItemType Directory -Force -Path $cartellaLog | Out-Null
$lucchetto = Join-Path $dati 'lavoro.lock'

if (Test-Path -LiteralPath $lucchetto) {
    $eta = (Get-Date) - (Get-Item -LiteralPath $lucchetto).LastWriteTime
    if ($eta.TotalHours -lt 6) {
        Write-Host ("Un altro lavoro e' in corso (iniziato {0} minuti fa). Non faccio nulla." -f [int]$eta.TotalMinutes)
        exit 0
    }
    # Un lucchetto vecchio di piu' di 6 ore e' di un lavoro interrotto: si toglie.
    Remove-Item -LiteralPath $lucchetto -Force
}
New-Item -ItemType File -Path $lucchetto -Force | Out-Null

$registro = Join-Path $cartellaLog ('{0}-{1:yyyyMMdd-HHmm}.log' -f $Comando, (Get-Date))
$extra = @($Argomenti -split ' ' | Where-Object { $_ })
$codice = 1
try {
    Push-Location $repo
    $env:PYTHONIOENCODING = 'utf-8'
    # uv scrive messaggi di avanzamento sull'errore standard: non sono errori.
    $ErrorActionPreference = 'Continue'
    & uv run python -m gazzetta_mcp.archivio $Comando @extra 2>&1 | ForEach-Object {
        $riga = "$_"
        Write-Host $riga
        Add-Content -LiteralPath $registro -Value $riga -Encoding UTF8
    }
    $codice = $LASTEXITCODE
}
finally {
    Pop-Location
    Remove-Item -LiteralPath $lucchetto -Force -ErrorAction SilentlyContinue
}

# Si tengono gli ultimi 30 registri.
Get-ChildItem -LiteralPath $cartellaLog -Filter '*.log' |
    Sort-Object LastWriteTime -Descending | Select-Object -Skip 30 | Remove-Item -Force
exit $codice
