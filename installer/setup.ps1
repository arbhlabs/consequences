# Consequences installer (Windows). Double-click ConsequencesSetup.exe, tick what you want, press Install.
#   Consequences skill   -> ~/.claude/skills/ship-gate            (the ship gate for AI agents)
#   Points add-on        -> ~/.claude/skills/consequences-points  (score agent work with + and - points)
#   Consequences Brain   -> %LOCALAPPDATA%\Programs\Consequences Brain  (optional live 3D window, no Python needed)
# Unattended:  powershell -File setup.ps1 -Silent [-NoBrain] [-NoPoints] [-NoSkill] [-NoShortcut] [-Root <test folder>]
param(
    [switch]$Silent, [switch]$NoSkill, [switch]$NoPoints, [switch]$NoBrain, [switch]$NoShortcut,
    [string]$Root = '', [string]$Payload = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
$Version = '1.6.1'

# Where things go. -Root redirects everything (used by the automated test; nothing touches the real profile then).
if ($Root) {
    $UserHome = Join-Path $Root 'home'; $LocalApp = Join-Path $Root 'local'; $Desktop = Join-Path $Root 'desktop'
    $StartMenu = Join-Path $Root 'startmenu'
} else {
    $UserHome = $HOME; $LocalApp = $env:LOCALAPPDATA
    $Desktop = [Environment]::GetFolderPath('Desktop'); $StartMenu = [Environment]::GetFolderPath('Programs')
}
$SkillsDir = Join-Path $UserHome '.claude\skills'
$AppDir = Join-Path $LocalApp 'Programs\Consequences Brain'
$Exe = Join-Path $AppDir 'ConsequencesBrain.exe'

function Expand-Payload {
    $zip = Join-Path $Payload 'payload.zip'
    $dir = Join-Path ([IO.Path]::GetTempPath()) ('consequences-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $zip -DestinationPath $dir -Force
    return $dir
}

function New-Shortcut([string]$Path, [string]$Target, [string]$WorkDir, [string]$Icon) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Path) | Out-Null
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
    $s.TargetPath = $Target; $s.WorkingDirectory = $WorkDir; $s.IconLocation = "$Icon,0"
    $s.Description = 'Consequences Brain - live scoreboard for your AI agents'
    $s.Save()
}

function Install-Consequences([bool]$Skill, [bool]$Points, [bool]$Brain, [bool]$Shortcut, [scriptblock]$Progress) {
    $src = Expand-Payload
    $done = @()
    try {
        if ($Skill) {
            & $Progress 'Installing the Consequences skill...'
            $d = Join-Path $SkillsDir 'ship-gate'
            New-Item -ItemType Directory -Force -Path (Join-Path $d 'templates') | Out-Null
            Copy-Item (Join-Path $src 'skill\ship-gate\*') $d -Recurse -Force
            $done += "skill: $d"
        }
        if ($Points) {
            & $Progress 'Installing the points add-on...'
            $d = Join-Path $SkillsDir 'consequences-points'
            New-Item -ItemType Directory -Force -Path $d | Out-Null
            Copy-Item (Join-Path $src 'skill\consequences-points\*') $d -Recurse -Force
            $done += "points: $d"
        }
        if ($Brain) {
            & $Progress 'Installing the Consequences Brain window...'
            Get-Process ConsequencesBrain -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$AppDir*" } | Stop-Process -Force
            New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
            Copy-Item (Join-Path $src 'brain\ConsequencesBrain\*') $AppDir -Recurse -Force
            Copy-Item (Join-Path $src 'brain\uninstall.ps1') $AppDir -Force
            $icon = Join-Path $AppDir '_internal\consequences.ico'
            New-Shortcut (Join-Path $StartMenu 'Consequences Brain.lnk') $Exe $AppDir $icon
            if ($Shortcut) { New-Shortcut (Join-Path $Desktop 'Consequences Brain.lnk') $Exe $AppDir $icon }
            if (-not $Root) {   # Apps & Features entry (current user only, no admin rights needed)
                $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ConsequencesBrain'
                New-Item -Path $k -Force | Out-Null
                Set-ItemProperty $k DisplayName 'Consequences Brain'
                Set-ItemProperty $k DisplayVersion $Version
                Set-ItemProperty $k Publisher 'ARBH Labs'
                Set-ItemProperty $k DisplayIcon $icon
                Set-ItemProperty $k InstallLocation $AppDir
                Set-ItemProperty $k UninstallString ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $AppDir 'uninstall.ps1') + '"')
                Set-ItemProperty $k NoModify 1 -Type DWord
                Set-ItemProperty $k NoRepair 1 -Type DWord
            }
            $done += "brain: $Exe"
        }
        & $Progress 'Done.'
        return $done
    } finally {
        Remove-Item -LiteralPath $src -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($Silent) {
    $r = Install-Consequences (-not $NoSkill) (-not $NoPoints) (-not $NoBrain) (-not $NoShortcut) { param($m) }
    $out = if ($Root) { Join-Path $Root 'install-result.json' } else { Join-Path ([IO.Path]::GetTempPath()) 'consequences-install-result.json' }
    @{ ok = $true; version = $Version; installed = $r } | ConvertTo-Json | Set-Content -LiteralPath $out -Encoding UTF8
    exit 0
}

# ------------------------------------------------------------------ the window
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$bg = [Drawing.Color]::FromArgb(14, 26, 38); $ink = [Drawing.Color]::FromArgb(216, 246, 255)
$muted = [Drawing.Color]::FromArgb(143, 179, 196); $holo = [Drawing.Color]::FromArgb(95, 227, 255)
$f = New-Object Windows.Forms.Form
$f.Text = "Install Consequences $Version"; $f.ClientSize = '520,400'; $f.StartPosition = 'CenterScreen'
$f.FormBorderStyle = 'FixedDialog'; $f.MaximizeBox = $false; $f.BackColor = $bg; $f.ForeColor = $ink
$f.Font = New-Object Drawing.Font('Segoe UI', 10)
$ico = Join-Path $Payload 'consequences.ico'
if (Test-Path $ico) { $f.Icon = New-Object Drawing.Icon($ico) }
$title = New-Object Windows.Forms.Label
$title.Text = 'CONSEQUENCES'; $title.Font = New-Object Drawing.Font('Segoe UI Semibold', 18); $title.ForeColor = $holo
$title.Location = '28,22'; $title.AutoSize = $true; $f.Controls.Add($title)
$sub = New-Object Windows.Forms.Label
$sub.Text = 'Make your AI agents prove their work, and see who earns trust.'; $sub.ForeColor = $muted
$sub.Location = '30,64'; $sub.AutoSize = $true; $f.Controls.Add($sub)
$y = 108; $boxes = @{}
foreach ($o in @(
    @('skill', 'Consequences skill', 'The ship gate for Claude Code and other agents.'),
    @('points', 'Points add-on', 'Score agent work with + and - points. Agents ask for points when they finish.'),
    @('brain', 'Consequences Brain window', 'Live 3D scoreboard: who is working, who leads, who is waiting for points.'),
    @('shortcut', 'Desktop shortcut', 'For the Consequences Brain window.'))) {
    $cb = New-Object Windows.Forms.CheckBox
    $cb.Text = $o[1]; $cb.Checked = $true; $cb.Location = "30,$y"; $cb.AutoSize = $true; $cb.ForeColor = $ink
    $cb.Font = New-Object Drawing.Font('Segoe UI Semibold', 10.5)
    $f.Controls.Add($cb); $boxes[$o[0]] = $cb
    $d = New-Object Windows.Forms.Label
    $d.Text = $o[2]; $d.ForeColor = $muted; $d.Location = "52,$($y + 25)"; $d.AutoSize = $true; $f.Controls.Add($d)
    $y += 58
}
$boxes['brain'].Add_CheckedChanged({ $boxes['shortcut'].Enabled = $boxes['brain'].Checked })
$status = New-Object Windows.Forms.Label
$status.Text = 'Nothing is installed until you press Install. No admin rights needed.'; $status.ForeColor = $muted
$status.Location = '30,350'; $status.Size = '300,40'; $f.Controls.Add($status)
$btn = New-Object Windows.Forms.Button
$btn.Text = 'Install'; $btn.Location = '390,348'; $btn.Size = '100,34'; $btn.FlatStyle = 'Flat'
$btn.BackColor = [Drawing.Color]::FromArgb(20, 60, 80); $btn.ForeColor = $ink; $btn.FlatAppearance.BorderColor = $holo
$f.AcceptButton = $btn; $f.Controls.Add($btn)
$btn.Add_Click({
    if ($btn.Text -eq 'Open') { Start-Process -FilePath $Exe -WorkingDirectory $AppDir; $f.Close(); return }
    if ($btn.Text -eq 'Close') { $f.Close(); return }
    $btn.Enabled = $false
    foreach ($b in $boxes.Values) { $b.Enabled = $false }
    try {
        $null = Install-Consequences $boxes['skill'].Checked $boxes['points'].Checked $boxes['brain'].Checked ($boxes['brain'].Checked -and $boxes['shortcut'].Checked) {
            param($m) $status.Text = $m; $status.Refresh() }
        $status.Text = 'All set. Agents now use the skill automatically.'
        $btn.Text = $(if ($boxes['brain'].Checked) { 'Open' } else { 'Close' })
    } catch {
        $status.Text = 'Install failed: ' + $_.Exception.Message
        $btn.Text = 'Close'
    }
    $btn.Enabled = $true
})
[void]$f.ShowDialog()
