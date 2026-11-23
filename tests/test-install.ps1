$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$destination = Join-Path ([IO.Path]::GetTempPath()) ('ship-gate install ' + [guid]::NewGuid())
$files = @{
    'skills/ship-gate/SKILL.md' = 'SKILL.md'
    'templates/gate.sh' = 'templates/gate.sh'
    'templates/CHECKLIST.md' = 'templates/CHECKLIST.md'
}

# Replace downloads with local fixtures so the branch is tested offline.
function Invoke-WebRequest {
    param([uri] $Uri, [string] $OutFile, [switch] $UseBasicParsing)
    $relative = $Uri.AbsolutePath -replace '^/arbhlabs/consequences/main/', ''
    if (-not $files.ContainsKey($relative)) { throw 'Unexpected installer URL' }
    Copy-Item -LiteralPath (Join-Path $repo $relative) -Destination $OutFile
}

try {
    & (Join-Path $repo 'install.ps1') -Destination $destination
    foreach ($source in $files.Keys) {
        $expected = (Get-FileHash -LiteralPath (Join-Path $repo $source)).Hash
        $installed = (Get-FileHash -LiteralPath (Join-Path $destination $files[$source])).Hash
        if ($installed -ne $expected) { throw ('Installer content mismatch for ' + $source) }
    }
    Write-Host 'TEST PASS: PowerShell installer deploys all three files to a path containing spaces (offline fixture)'
}
finally {
    if ([IO.Directory]::Exists($destination)) { [IO.Directory]::Delete($destination, $true) }
}
