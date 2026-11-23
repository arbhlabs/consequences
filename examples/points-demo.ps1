# Replay an explicit award and read the next task's watch list.
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repo = Split-Path -Parent $PSScriptRoot
$cli = Join-Path $repo 'addons/points/points.mjs'
$data = Join-Path ([IO.Path]::GetTempPath()) ('ship-gate-demo-' + [guid]::NewGuid())
New-Item -Path $data -ItemType Directory | Out-Null
try {
    $sample = Get-Content -Raw -LiteralPath (Join-Path $repo 'templates/points/rules.json') | ConvertFrom-Json
    $sample[0].created = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    ConvertTo-Json -InputObject @($sample[0]) | Set-Content -Path (Join-Path $data 'rules.json')
    node $cli propose '-3 points: missed the packaged entrypoint' --data-dir $data
    node $cli award agent-a package -3 'Missed the packaged entrypoint' --tag smoke-test --source auto --data-dir $data
    node $cli board --data-dir $data
    node $cli lessons --agent agent-a --active-only --data-dir $data
}
finally {
    [IO.Directory]::Delete($data, $true)
}
