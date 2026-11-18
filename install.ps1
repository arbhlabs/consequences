# Install or update the latest ship-gate skill (Windows).
# irm https://raw.githubusercontent.com/arbhlabs/consequences/main/install.ps1 | iex
$url  = "https://raw.githubusercontent.com/arbhlabs/consequences/main/skills/ship-gate/SKILL.md"
$dest = Join-Path $HOME ".claude\skills\ship-gate"
New-Item -ItemType Directory -Force $dest | Out-Null
Invoke-WebRequest $url -OutFile (Join-Path $dest "SKILL.md")
Write-Host "ship-gate installed/updated at $dest\SKILL.md"
