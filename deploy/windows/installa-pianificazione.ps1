# Crea due attivita' in "Utilita' di pianificazione" di Windows, per l'utente che le crea:
#   - GazzettaArchivio-Aggiorna : ogni giorno alle 05:30, mette in coda e scarica i numeri nuovi
#   - GazzettaArchivio-Recupera : ogni giorno alle 01:00, recupera un lotto di numeri piu' vecchi
# Non servono i diritti di amministratore. Il PC deve essere acceso (o in sospensione: lo risveglia).
# Per toglierle: .\deploy\windows\rimuovi-pianificazione.ps1
$script = Join-Path $PSScriptRoot 'lavoro.ps1'
$ps = (Get-Command powershell.exe).Source

function Nuova-Attivita([string]$nome, [string]$ora, [string]$parametri, [int]$oreMassime) {
    $argomento = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" $parametri"
    $azione = New-ScheduledTaskAction -Execute $ps -Argument $argomento
    $quando = New-ScheduledTaskTrigger -Daily -At $ora
    $impostazioni = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
        -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours $oreMassime)
    Register-ScheduledTask -TaskName $nome -Action $azione -Trigger $quando `
        -Settings $impostazioni -Description 'Archivio gazzetta-mcp' -Force | Out-Null
    Write-Host "Creata: $nome (ogni giorno alle $ora)"
}

Nuova-Attivita 'GazzettaArchivio-Aggiorna' '05:30' '-Comando aggiorna' 3
Nuova-Attivita 'GazzettaArchivio-Recupera' '01:00' '-Comando recupera -Argomenti "--max-numeri 40 --max-atti 300"' 5
Write-Host 'Fatto. Per vederle: Utilita'' di pianificazione > Libreria. Per provarle subito: Start-ScheduledTask -TaskName GazzettaArchivio-Aggiorna'
