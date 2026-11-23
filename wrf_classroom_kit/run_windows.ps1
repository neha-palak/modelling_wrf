#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string[]]$Data,
    [string]$Output = (Join-Path $PSScriptRoot 'classroom_output'),
    [switch]$Watch,
    [switch]$Inspect,
    [string]$Fields = '',
    [int]$MaxFrames = 0,
    [int]$PollSeconds = 60,
    [int]$IdleMinutes = 30,
    [string]$Config = ''
)
$ErrorActionPreference = 'Stop'
$runtimeFile = Join-Path $PSScriptRoot '.runtime.json'
if (-not (Test-Path -LiteralPath $runtimeFile)) { throw 'Run setup_windows.ps1 first in this extracted kit folder.' }
$runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $runtime.conda)) { throw 'The recorded Conda executable is missing. Rerun setup_windows.ps1.' }
$action = if ($Inspect) { 'inspect' } elseif ($Watch) { 'watch' } else { 'run' }
$cliArgs = @((Join-Path $PSScriptRoot 'wrf_classroom.py'), $action, '--data') + $Data
if (-not $Inspect) { $cliArgs += @('--output', $Output) }
if ($Fields) { $cliArgs += @('--fields', $Fields) }
if ($MaxFrames -gt 0) { $cliArgs += @('--max-frames', "$MaxFrames") }
if ($Config) { $cliArgs += @('--config', $Config) }
if ($Watch) { $cliArgs += @('--poll-seconds', "$PollSeconds", '--idle-minutes', "$IdleMinutes") }
& $runtime.conda run --no-capture-output --prefix $runtime.prefix python @cliArgs
exit $LASTEXITCODE
