# Removes the Consequences Brain window (the skills and your points ledger stay; delete those folders yourself if you want).
$ErrorActionPreference = 'SilentlyContinue'
$AppDir = $PSScriptRoot
Get-Process ConsequencesBrain | Where-Object { $_.Path -like "$AppDir*" } | Stop-Process -Force
foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Consequences Brain.lnk'),
                   (Join-Path ([Environment]::GetFolderPath('Programs')) 'Consequences Brain.lnk'))) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ConsequencesBrain' -Recurse -Force
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', ('timeout /t 2 >nul & rmdir /s /q "' + $AppDir + '"') -WindowStyle Hidden
