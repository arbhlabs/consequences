# Builds dist\ConsequencesSetup.exe: the standalone Consequences Brain app (PyInstaller) + skills, wrapped by IExpress
# (built into Windows). Needs Python 3.10+ with:  pip install pywebview pyinstaller
#   powershell -File installer\build.ps1 [-Python C:\path\to\python.exe]
param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$app = Join-Path $repo 'addons\brain\app'
$out = Join-Path $repo 'dist'
$work = Join-Path ([IO.Path]::GetTempPath()) 'consequences-build'
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work, $out | Out-Null

Write-Host '[1/4] Building the Consequences Brain app (PyInstaller)...'
& $Python -m PyInstaller --noconfirm --windowed --name ConsequencesBrain `
    --icon (Join-Path $app 'consequences.ico') `
    --add-data ((Join-Path $app 'ui') + ';ui') --add-data ((Join-Path $app 'consequences.ico') + ';.') `
    --hidden-import cb_sessions --hidden-import cb_activity --hidden-import cb_sample --hidden-import cb_gate `
    --hidden-import cb_referee --hidden-import cb_refwork --hidden-import cb_learn --hidden-import cb_evidence --collect-submodules webview `
    --distpath (Join-Path $work 'dist') --workpath (Join-Path $work 'pyi') --specpath $work `
    (Join-Path $app 'consequences_brain.py')
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

Write-Host '[2/4] Self-testing the built app (no window)...'
$st = Join-Path $work 'selftest.json'
$env:CB_SELFTEST_OUT = $st; $env:CB_NO_SESSIONS = '1'
Start-Process -FilePath (Join-Path $work 'dist\ConsequencesBrain\ConsequencesBrain.exe') -ArgumentList '--selftest' -Wait
Remove-Item Env:CB_SELFTEST_OUT, Env:CB_NO_SESSIONS
$r = Get-Content $st -Raw | ConvertFrom-Json
if (-not ($r.ok -and $r.ui -and $r.three -and $r.icon)) { throw "Self-test failed: $($r | ConvertTo-Json -Compress)" }

Write-Host '[3/4] Packing skills + app...'
$pay = Join-Path $work 'payload'
New-Item -ItemType Directory -Force -Path "$pay\skill\ship-gate\templates", "$pay\skill\consequences-points", "$pay\brain", "$pay\templates\obsidian" | Out-Null
Copy-Item (Join-Path $repo 'templates\obsidian\Scoreboard.md') "$pay\templates\obsidian\"
Copy-Item (Join-Path $repo 'skills\ship-gate\SKILL.md') "$pay\skill\ship-gate\"
Copy-Item (Join-Path $repo 'templates\gate.sh'), (Join-Path $repo 'templates\CHECKLIST.md') "$pay\skill\ship-gate\templates\"
Copy-Item (Join-Path $repo 'addons\points\*') "$pay\skill\consequences-points\" -Recurse
Copy-Item (Join-Path $work 'dist\ConsequencesBrain') "$pay\brain\" -Recurse
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') "$pay\brain\"
# hook scripts (run with Python 3 from Claude Code hooks; see the README)
New-Item -ItemType Directory -Force -Path "$pay\brain\ConsequencesBrain\hooks" | Out-Null
Copy-Item (Join-Path $app 'cb_chatpoints.py'), (Join-Path $app 'cb_activity.py') "$pay\brain\ConsequencesBrain\hooks\"
$sfx = Join-Path $work 'sfx'
New-Item -ItemType Directory -Force -Path $sfx | Out-Null
Compress-Archive -Path "$pay\*" -DestinationPath (Join-Path $sfx 'payload.zip') -Force
Copy-Item (Join-Path $PSScriptRoot 'setup.ps1'), (Join-Path $app 'consequences.ico') $sfx

Write-Host '[4/4] Wrapping ConsequencesSetup.exe (IExpress)...'
$target = Join-Path $out 'ConsequencesSetup.exe'
$sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$target
FriendlyName=Consequences Setup
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File setup.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="setup.ps1"
FILE1="payload.zip"
FILE2="consequences.ico"
[SourceFiles]
SourceFiles0=$sfx\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@
$sedPath = Join-Path $work 'setup.sed'
Set-Content -LiteralPath $sedPath -Value $sed -Encoding ASCII
Start-Process -FilePath "$env:WINDIR\System32\iexpress.exe" -ArgumentList '/N', '/Q', $sedPath -Wait
if (-not (Test-Path $target)) { throw 'IExpress did not produce the setup exe' }
Copy-Item (Join-Path $sfx 'payload.zip') (Join-Path $work 'payload-check.zip')
Write-Host ("Built {0} ({1:N1} MB)" -f $target, ((Get-Item $target).Length / 1MB))
