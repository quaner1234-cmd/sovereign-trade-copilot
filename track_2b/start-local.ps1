[CmdletBinding()]
param(
    [ValidateSet('Demo', 'Live')][string]$Mode = 'Demo',
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.-]+$')][string]$Container = 'track2b-local',
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.:/-]+$')][string]$Image = 'hackapertus-track2b-light',
    [string]$MakePath,
    [string[]]$SourceFakeIpHosts = @()
)

$ErrorActionPreference = 'Stop'
$docker = (Get-Command docker -ErrorAction Stop).Source
if (-not $MakePath) {
    $makeCommand = Get-Command make -ErrorAction SilentlyContinue
    if ($makeCommand) { $MakePath = $makeCommand.Source }
}
if (-not $MakePath -or -not (Test-Path -LiteralPath $MakePath -PathType Leaf)) {
    throw 'GNU Make is required. Supply -MakePath with the existing make executable.'
}
if ((& $docker info --format '{{.OSType}}' 2>$null) -ne 'linux') {
    throw 'Start Docker Desktop with its Linux engine, then run this command again.'
}
$base = "http://127.0.0.1:$Port"
$expectedMode = if ($Mode -eq 'Live') { 'live_apertus' } else { 'recorded_replay' }
$configuredHosts = if ($SourceFakeIpHosts.Count) { $SourceFakeIpHosts -join ',' } else {
    [Environment]::GetEnvironmentVariable('SOURCE_FAKE_IP_HOSTS', 'Process')
}
if (-not $configuredHosts) {
    $configuredHosts = [Environment]::GetEnvironmentVariable('SOURCE_FAKE_IP_HOSTS', 'User')
}
if ($configuredHosts -and $configuredHosts -notmatch '^[a-zA-Z0-9.,-]+$') {
    throw 'SourceFakeIpHosts must contain exact DNS hostnames, without URLs or wildcards.'
}

# Existing records are never automatically removed or replaced.
$names = @(& $docker container ls -a --format '{{.Names}}')
if ($LASTEXITCODE -ne 0) { throw 'Could not list local containers.' }
if ($names -contains $Container) {
    $owner = & $docker inspect -f '{{.Config.Labels.copilot}}' $Container
    if ($owner -ne 'light-harness') { throw 'This container name belongs to an unmanaged container. Choose another name.' }
    $ports = (& $docker inspect -f '{{json .HostConfig.PortBindings}}' $Container | ConvertFrom-Json).'8000/tcp'
    if (-not $ports -or $ports[0].HostPort -ne "$Port" -or $ports[0].HostIp -ne '127.0.0.1') {
        throw 'Existing port configuration differs. Choose another container name; existing records were kept.'
    }
    $running = & $docker inspect -f '{{.State.Running}}' $Container
    if ($running -eq 'false') {
        & $docker start $Container | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not start the existing container.' }
    }
    # Only the non-secret source configuration is inspected; never enumerate Env.
    $hostMatch = & $docker exec $Container python -c "import os,sys; print(os.getenv('SOURCE_FAKE_IP_HOSTS','')==(sys.argv[1] if len(sys.argv)>1 else ''))" ([string]$configuredHosts)
    if ($hostMatch -ne 'True') {
        throw 'Existing source-host configuration differs. Choose another container name; existing records were kept.'
    }
    $health = Invoke-RestMethod "$base/health" -TimeoutSec 10
    if ($health.mode -ne $expectedMode -or $health.sending_enabled -ne $false) {
        throw 'Existing mode differs or sending is enabled. Existing records were kept.'
    }
    Write-Host "Reused $Container ($expectedMode): $base/ui"
    Write-Host 'Existing source, endpoint, key and image configuration were retained. No model call was made.'
    return
}

$environmentNames = @('PATH', 'SHELL', 'LLM_NAME', 'LLM_BASE_URL', 'LLM_API_KEY', 'SOURCE_FAKE_IP_HOSTS')
$previous = @{}
foreach ($name in $environmentNames) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    if ($Mode -eq 'Demo') {
        $env:LLM_NAME = ''; $env:LLM_BASE_URL = ''; $env:LLM_API_KEY = ''
    } else {
        if (-not $env:LLM_BASE_URL) {
            $env:LLM_BASE_URL = [Environment]::GetEnvironmentVariable('CSCS_BASE_URL', 'Process')
            if (-not $env:LLM_BASE_URL) { $env:LLM_BASE_URL = [Environment]::GetEnvironmentVariable('CSCS_BASE_URL', 'User') }
            $env:LLM_API_KEY = [Environment]::GetEnvironmentVariable('CSCS_INFERENCE_API_KEY', 'Process')
            if (-not $env:LLM_API_KEY) { $env:LLM_API_KEY = [Environment]::GetEnvironmentVariable('CSCS_INFERENCE_API_KEY', 'User') }
            if (-not $env:LLM_API_KEY) { throw 'CSCS_INFERENCE_API_KEY is missing. No key value is requested or logged.' }
        }
        if (-not $env:LLM_BASE_URL) { throw 'Set LLM_BASE_URL or CSCS_BASE_URL before live startup.' }
        if (-not $env:LLM_NAME) { $env:LLM_NAME = 'swiss-ai/Apertus-v1.5-70B' }
    }
    $env:SOURCE_FAKE_IP_HOSTS = $configuredHosts
    $env:PATH = (Split-Path -Parent $docker) + [IO.Path]::PathSeparator + $env:PATH
    # Avoid selecting the Windows WSL bash shim for GNU Make.
    $gitBash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
    if (Test-Path -LiteralPath $gitBash) { $env:SHELL = $gitBash.Replace('\', '/') }
    & $MakePath -C $PSScriptRoot run "PORT=$Port" "CONTAINER=$Container" "IMAGE=$Image" 'RUN_OPTIONS=--restart unless-stopped'
    if ($LASTEXITCODE -ne 0) { throw 'make run failed. No existing container was replaced.' }
    $health = Invoke-RestMethod "$base/health" -TimeoutSec 10
    if ($health.mode -ne $expectedMode -or $health.sending_enabled -ne $false) {
        throw 'Started service did not report the expected mode with sending disabled.'
    }
    Write-Host "Ready ($expectedMode): $base/ui"
    Write-Host 'Docker will restart this container when its engine starts unless it was explicitly stopped.'
    Write-Host 'Server restart expires approval records; recovered browser text requires fresh review.'
} finally {
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
