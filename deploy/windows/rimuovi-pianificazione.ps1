# Toglie le attivita' pianificate create da installa-pianificazione.ps1 (ferma anche quelle in corso).
foreach ($nome in 'GazzettaArchivio-Aggiorna', 'GazzettaArchivio-Recupera') {
    if (Get-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $nome -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $nome -Confirm:$false
        Write-Host "Tolta: $nome"
    }
    else {
        Write-Host "Non c'era: $nome"
    }
}
