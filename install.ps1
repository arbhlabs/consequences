# Install or update the latest ship-gate skill and its runnable templates (Windows).
# irm https://raw.githubusercontent.com/arbhlabs/consequences/main/install.ps1 | iex
param([string] $Destination = (Join-Path $HOME '.claude\skills\ship-gate'))

$ErrorActionPreference = 'Stop'
$baseUrl = 'https://raw.githubusercontent.com/arbhlabs/consequences/main'
$dest = $Destination
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ('ship-gate-' + [guid]::NewGuid().ToString('N'))

New-Item -ItemType Directory -Force -Path $temp | Out-Null
try {
    Invoke-WebRequest -Uri "$baseUrl/skills/ship-gate/SKILL.md" -OutFile (Join-Path $temp 'SKILL.md') -UseBasicParsing
    Invoke-WebRequest -Uri "$baseUrl/templates/gate.sh" -OutFile (Join-Path $temp 'gate.sh') -UseBasicParsing
    Invoke-WebRequest -Uri "$baseUrl/templates/CHECKLIST.md" -OutFile (Join-Path $temp 'CHECKLIST.md') -UseBasicParsing

    $templateDest = Join-Path $dest 'templates'
    New-Item -ItemType Directory -Force -Path $templateDest | Out-Null
    Copy-Item -LiteralPath (Join-Path $temp 'SKILL.md') -Destination (Join-Path $dest 'SKILL.md') -Force
    Copy-Item -LiteralPath (Join-Path $temp 'gate.sh') -Destination (Join-Path $templateDest 'gate.sh') -Force
    Copy-Item -LiteralPath (Join-Path $temp 'CHECKLIST.md') -Destination (Join-Path $templateDest 'CHECKLIST.md') -Force

    Write-Host "ship-gate installed/updated at $dest\SKILL.md"
    Write-Host "runner: $templateDest\gate.sh"
    Write-Host "checklist: $templateDest\CHECKLIST.md"
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
