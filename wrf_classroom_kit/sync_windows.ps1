#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Remote,
    [Parameter(Mandatory=$true)][Alias('Local')][string]$LocalFolder,
    [Alias('Host')][string]$SshHost = '10.1.4.95',
    [Alias('User')][string]$SshUser = 'neha.palak_ug2023',
    [int]$Port = 22,
    [switch]$Watch,
    [int]$IdleMinutes = 30,
    [int]$PollSeconds = 60,
    [Alias('Key')][string]$KeyFile = '',
    [string]$KnownHosts = '',
    [switch]$Agent
)
$ErrorActionPreference = 'Stop'
$runtimeFile = Join-Path $PSScriptRoot '.runtime.json'
if (-not (Test-Path -LiteralPath $runtimeFile)) { throw 'Run setup_windows.ps1 first in this extracted kit folder.' }
$runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $runtime.conda)) { throw 'The recorded Conda executable is missing. Rerun setup_windows.ps1.' }
$cliArgs = @((Join-Path $PSScriptRoot 'sync_hpc.py'), '--remote', $Remote, '--local', $LocalFolder,
             '--host', $SshHost, '--user', $SshUser, '--port', "$Port",
             '--poll-seconds', "$PollSeconds", '--idle-minutes', "$IdleMinutes")
if ($Watch) { $cliArgs += '--watch' }
if ($KeyFile) { $cliArgs += @('--key-file', $KeyFile) }
if ($KnownHosts) { $cliArgs += @('--known-hosts', $KnownHosts) }
if ($Agent) { $cliArgs += '--agent' }
& $runtime.conda run --no-capture-output --prefix $runtime.prefix python @cliArgs
exit $LASTEXITCODE
