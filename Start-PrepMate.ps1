<#
.SYNOPSIS
Starts the PrepMate RAG backend, the bundled Voice Assistant, and the frontend.

.EXAMPLE
.\Start-PrepMate.ps1
Starts all three services and writes their PIDs to .prepmate-pids.json.

.EXAMPLE
.\Start-PrepMate.ps1 -NoFrontend
Starts only the two Python services.

.EXAMPLE
.\Start-PrepMate.ps1 -Status
.EXAMPLE
.\Start-PrepMate.ps1 -Stop
#>
param(
    [switch]$Stop,
    [switch]$Status,
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pidFile = Join-Path $root ".prepmate-pids.json"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Vite prints its chosen port in the log; use it so -Status and startup messages
# show a real URL instead of "check the npm output".
$frontendUrl = "http://localhost:8080/"
$frontendLog = Join-Path $logDir "frontend.out.log"
if (Test-Path $frontendLog) {
    $localLine = Get-Content $frontendLog |
        Where-Object { $_ -match "Local:" } |
        Select-Object -Last 1
    if ($localLine) {
        $cleanLine = $localLine -replace "\x1b\[[0-9;]*m", ""
        if ($cleanLine -match "https?://[A-Za-z0-9._:-]+/") { $frontendUrl = $Matches[0] }
    }
}

$services = @(
    @{
        Name = "backend"
        Exe = (Join-Path $root "Backend\venv\Scripts\python.exe")
        Fallback = "python"
        Args = @("-m", "src.api")
        Cwd = Join-Path $root "Backend"
        Health = "http://127.0.0.1:8000/health"
        Url = "http://localhost:8000/docs"
    },
    @{
        Name = "voice"
        Exe = (Join-Path $root "VoiceAssistant\.venv\Scripts\python.exe")
        Fallback = "python"
        Args = @("app.py")
        Cwd = Join-Path $root "VoiceAssistant"
        Health = "http://127.0.0.1:45124/health"
        Url = "http://127.0.0.1:45124/"
    }
)

if (-not $NoFrontend) {
    $services += @{
        Name = "frontend"
        Exe = (Join-Path $env:SystemRoot "System32\cmd.exe")
        Fallback = "cmd.exe"
        # npm is a .cmd shim, so it must be launched through cmd /c.
        Args = @("/c", "npm", "run", "dev")
        Cwd = Join-Path $root "Frontend"
        Health = $frontendUrl
        Url = $frontendUrl
    }
}

function Test-Health([string]$Url) {
    if (-not $Url) { return $false }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $Url
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-PidByPort([string]$Url) {
    try {
        $port = ([uri]$Url).Port
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
    } catch {
        return $null
    }
    return $null
}

function Resolve-Exe($Service) {
    if (Test-Path $Service.Exe) { return $Service.Exe }
    $fallback = Get-Command $Service.Fallback -ErrorAction SilentlyContinue
    if ($fallback) { return $fallback.Source }
    return $null
}

function Read-Pids {
    if (-not (Test-Path $pidFile)) { return @{} }
    try { return (Get-Content $pidFile -Raw | ConvertFrom-Json -AsHashtable) } catch { return @{} }
}

if ($Status) {
    foreach ($svc in $services) {
        $healthy = if ($svc.Health) { Test-Health $svc.Health } else { "n/a" }
        Write-Host ("{0,-9} health={1,-5} url={2}" -f $svc.Name, $healthy, $svc.Url)
    }
    return
}

if ($Stop) {
    $pids = Read-Pids
    # Also discover live listeners by port, in case an earlier run lost the PID file.
    foreach ($svc in $services) {
        if ($svc.Health -and -not $pids.ContainsKey($svc.Name)) {
            $existingPid = Get-PidByPort $svc.Health
            if ($existingPid) { $pids[$svc.Name] = $existingPid }
        }
    }
    foreach ($name in @($pids.Keys)) {
        $processId = [int]$pids[$name]
        # taskkill /T also removes children (e.g. the node process behind npm/cmd).
        & taskkill /PID $processId /T /F 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Stopped $name (PID $processId) and its children"
        } else {
            Write-Host "$name (PID $processId) was not running"
        }
    }
    Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
    return
}

$pids = Read-Pids
foreach ($svc in $services) {
    if ($svc.Health -and (Test-Health $svc.Health)) {
        Write-Host "$($svc.Name) is already healthy at $($svc.Health)"
        # Keep (or rediscover) its PID so -Stop can still shut it down later.
        if (-not $pids.ContainsKey($svc.Name)) {
            $existingPid = Get-PidByPort $svc.Health
            if ($existingPid) { $pids[$svc.Name] = $existingPid }
        }
        continue
    }

    $exe = Resolve-Exe $svc
    if (-not $exe) {
        Write-Warning "$($svc.Name): no interpreter found; skipping"
        continue
    }
    if (-not (Test-Path $svc.Cwd)) {
        Write-Warning "$($svc.Name): missing directory $($svc.Cwd); skipping"
        continue
    }

    $out = Join-Path $logDir "$($svc.Name).out.log"
    $err = Join-Path $logDir "$($svc.Name).err.log"
    $proc = Start-Process -FilePath $exe -ArgumentList $svc.Args -WorkingDirectory $svc.Cwd `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    $pids[$svc.Name] = $proc.Id
    Write-Host "Started $($svc.Name) (PID $($proc.Id)) -> $($svc.Url)"
}

$pids | ConvertTo-Json | Set-Content $pidFile -Encoding utf8
Write-Host "`nPrepMate is starting. Frontend: $frontendUrl  |  Voice service: http://127.0.0.1:45124/ (use the inline Voice button in chat)"
Write-Host "Run .\Start-PrepMate.ps1 -Status to check, -Stop to shut everything down."
