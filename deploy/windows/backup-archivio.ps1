# Copia di sicurezza dell'archivio nella cartella Documenti\gazzetta-backup (zip, ultime 7).
# Usa la copia "a caldo" di SQLite, quindi e' coerente anche se il file e' in uso, ma e' meglio
# lanciarla quando non c'e' un lavoro in corso (lo controlla da solo).
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$dati = Join-Path $env:LOCALAPPDATA 'gazzetta-mcp'
$origine = Join-Path $dati 'archivio.sqlite3'
$cartella = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'gazzetta-backup'

if (-not (Test-Path -LiteralPath $origine)) { Write-Host "Nessun archivio in $origine."; exit 0 }
if (Test-Path -LiteralPath (Join-Path $dati 'lavoro.lock')) {
    Write-Host 'Un lavoro e'' in corso: riprova piu'' tardi.'
    exit 0
}

New-Item -ItemType Directory -Force -Path $cartella | Out-Null
$nome = 'archivio-{0:yyyyMMdd-HHmm}' -f (Get-Date)
$copia = Join-Path $cartella ($nome + '.sqlite3')

Push-Location $repo
try {
    $ErrorActionPreference = 'Continue'
    & uv run python -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $origine $copia
    if ($LASTEXITCODE -ne 0) { Write-Host 'La copia non e'' riuscita.'; exit 1 }
}
finally { Pop-Location }

Compress-Archive -LiteralPath $copia -DestinationPath ($copia + '.zip') -Force
Remove-Item -LiteralPath $copia -Force
Get-ChildItem -LiteralPath $cartella -Filter 'archivio-*.zip' |
    Sort-Object LastWriteTime -Descending | Select-Object -Skip 7 | Remove-Item -Force
Write-Host "Copia fatta: $($copia).zip"
