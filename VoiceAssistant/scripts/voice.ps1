param(
    [ValidateSet("Toggle", "Start", "Stop", "Status", "Ensure", "Watch", "Build")]
    [string]$Action,
    [switch]$Toggle,
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Ensure,
    [switch]$Watch,
    [switch]$Build
)

$ErrorActionPreference = "Stop"

if ($Watch)    { $Action = "Watch" }
elseif ($Ensure) { $Action = "Ensure" }
elseif ($Build)  { $Action = "Build" }
elseif ($Status) { $Action = "Status" }
elseif ($Stop)   { $Action = "Stop" }
elseif ($Start)  { $Action = "Start" }
elseif ($Toggle) { $Action = "Toggle" }
if (-not $Action) { $Action = "Toggle" }

$Root = Split-Path -Parent $PSScriptRoot
$WebDir = Join-Path $Root "web"
$PidFile = Join-Path $Root ".voice-pids.json"
$WindowStateFile = Join-Path $Root ".voice-window-state.json"
$LogFile = Join-Path $Root ".voice-hotkey.log"
$BackendOut = Join-Path $Root ".voice-backend.log"
$BackendErr = Join-Path $Root ".voice-backend.err.log"
$BrowserProfile = Join-Path $Root ".voice-browser-profile"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DefaultPort = 45123
$MiniTitle = "Voice Assistant Mini"
$Sw = [System.Diagnostics.Stopwatch]::StartNew()

function Write-VoiceLog {
    param([string]$Message)
    $line = "[{0}] [{1,6}ms] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Sw.ElapsedMilliseconds, $Message
    Add-Content -Path $LogFile -Value $line
}

function Write-VoicePhase {
    param([string]$Name, [long]$StartedAt)
    Write-VoiceLog ("PHASE {0}: {1}ms" -f $Name, ($Sw.ElapsedMilliseconds - $StartedAt))
}

function Get-VoicePort {
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        $match = Select-String -Path $envFile -Pattern '^\s*PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
        if ($match) { return [int]$match.Matches[0].Groups[1].Value }
    }
    if ($env:PORT) { return [int]$env:PORT }
    return $DefaultPort
}

$BackendPort = Get-VoicePort

function Test-VoicePort {
    param([int]$Number)
    return [bool](Get-NetTCPConnection -LocalPort $Number -State Listen -ErrorAction SilentlyContinue)
}

function Test-BackendHealth {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health" `
            -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Get-PortOwnerPid {
    $connection = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) { return [int]$connection.OwningProcess }
    return $null
}

function Read-WindowState {
    if (-not (Test-Path $WindowStateFile)) { return $null }
    try {
        return Get-Content $WindowStateFile -Raw | ConvertFrom-Json
    } catch {
        Write-VoiceLog "Could not read window state: $_"
        return $null
    }
}

function Save-WindowState {
    param([long]$MiniHandle = 0, [long]$WarmHandle = 0)
    @{ MiniHandle = $MiniHandle; WarmHandle = $WarmHandle } | ConvertTo-Json | Set-Content $WindowStateFile
}

function Get-BrowserWindows {
    # Enumerate real top-level windows instead of trusting MainWindowTitle.
    # Chrome keeps the warm window and the app window on the same browser PID,
    # so the only reliable identity is the Win32 HWND.
    $windows = [System.Collections.Generic.List[object]]::new()
    foreach ($window in [VoiceWindowApi]::ListVisibleWindows()) {
        $process = Get-Process -Id ([int]$window.ProcessId) -ErrorAction SilentlyContinue
        if (-not $process -or $process.ProcessName -notmatch '^(chrome|msedge)$') { continue }
        $windows.Add([pscustomobject]@{
            Handle      = $window.Handle
            HandleValue = $window.Handle.ToInt64()
            Id          = [int]$window.ProcessId
            Title       = $window.Title
        })
    }
    return @($windows)
}

function Get-MiniWindows {
    $state = Read-WindowState
    $saved = 0
    if ($state -and $state.MiniHandle) { $saved = [long]$state.MiniHandle }

    $windows = [System.Collections.Generic.List[object]]::new()
    foreach ($window in @(Get-BrowserWindows)) {
        if (($saved -ne 0 -and $window.HandleValue -eq $saved) -or
            $window.Title -like "*$MiniTitle*") {
            $windows.Add($window)
        }
    }

    # Last-resort fallback: the saved HWND is still alive even if enumeration
    # transiently misses it. This makes Toggle-close deterministic.
    if ($saved -ne 0) {
        $hwnd = [IntPtr]::new([int64]$saved)
        if ([VoiceWindowApi]::IsWindow($hwnd) -and
            -not @($windows | Where-Object { $_.HandleValue -eq $saved }).Count) {
            Write-VoiceLog ("Mini window found via saved handle {0}" -f $saved)
            $windows.Add([pscustomobject]@{
                Handle      = $hwnd
                HandleValue = $saved
                Id          = 0
                Title       = [VoiceWindowApi]::GetTitle($hwnd)
            })
        }
    }
    return @($windows)
}

function Read-SavedPid {
    if (-not (Test-Path $PidFile)) { return $null }
    try {
        $value = Get-Content $PidFile -Raw | ConvertFrom-Json
        if ($value -and $value.BackendPid) { return [int]$value.BackendPid }
    } catch {
        Write-VoiceLog "Could not read PID file: $_"
    }
    return $null
}

function Save-BackendPid {
    param([int]$Id)
    @{ BackendPid = $Id } | ConvertTo-Json | Set-Content $PidFile
}

function Test-IsOurBackend {
    param([int]$Id)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $Id" -ErrorAction SilentlyContinue
    if (-not $process -or $process.Name -notmatch '^python') { return $false }
    return [bool]($process.CommandLine -match 'app\.py')
}

function Get-ChildPids {
    param([int]$Id)
    return @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $Id" -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.ProcessId })
}

function Rotate-BackendLog {
    if (-not (Test-Path $BackendErr)) { return }
    $item = Get-Item $BackendErr
    if ($item.Length -lt 2MB) { return }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Move-Item $BackendErr (Join-Path $Root ".voice-backend.err.$stamp.log") -Force
    Get-ChildItem -Path $Root -Filter ".voice-backend.err.*.log" |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 |
        Remove-Item -Force -ErrorAction SilentlyContinue
    "" | Set-Content $BackendErr
    Write-VoiceLog "Rotated backend error log (>2 MB)"
}

function Build-Frontend {
    param([switch]$Force)

    if (-not (Test-Path (Join-Path $WebDir "node_modules"))) {
        Write-VoiceLog "node_modules missing; running npm install"
        Push-Location $WebDir
        try {
            & npm install 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
        } finally { Pop-Location }
    }

    $distIndex = Join-Path $WebDir "dist\index.html"
    if (-not $Force -and (Test-Path $distIndex)) {
        $watchedFiles = @(Get-ChildItem (Join-Path $WebDir "src") -Recurse -File)
        $watchedFiles += @(Get-ChildItem $WebDir -File | Where-Object {
            $_.Name -in @("index.html", "package.json", "vite.config.ts", "tsconfig.json", "tsconfig.node.json")
        })
        $newestSource = ($watchedFiles | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
        $builtAt = (Get-Item $distIndex).LastWriteTimeUtc
        if ($newestSource -le $builtAt) {
            Write-VoiceLog "Frontend cache HIT (dist is newer than all sources)"
            return
        }
        Write-VoiceLog "Frontend cache MISS (newer source than dist)"
    } elseif ($Force) {
        Write-VoiceLog "Frontend build forced"
    } else {
        Write-VoiceLog "Frontend cache MISS (dist/index.html missing)"
    }

    $started = $Sw.ElapsedMilliseconds
    Write-VoiceLog "Building frontend"
    Push-Location $WebDir
    try {
        $output = & npm run build 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    if ($code -ne 0) { throw "npm run build failed (exit $code): $output" }
    Write-VoicePhase "frontend-build" $started
}

function Start-Backend {
    if (Test-BackendHealth) {
        Write-VoiceLog "Backend already healthy on $BackendPort"
        return
    }
    if (-not (Test-Path $Python)) { throw "Missing Python interpreter: $Python" }

    Rotate-BackendLog
    $started = $Sw.ElapsedMilliseconds
    $process = Start-Process -FilePath $Python -ArgumentList "app.py" `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr
    Save-BackendPid -Id $process.Id
    Write-VoiceLog "Started backend PID $($process.Id) on port $BackendPort"

    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        if (Test-BackendHealth) {
            Write-VoiceLog "Backend healthy on $BackendPort"
            Write-VoicePhase "backend-start" $started
            return
        }
        Start-Sleep -Milliseconds 250
    }
    $tail = @(Get-Content $BackendErr -Tail 8 -ErrorAction SilentlyContinue)
    throw "Backend did not become healthy on $BackendPort; see $BackendErr :: $($tail -join ' | ')"
}

function Stop-Backend {
    $candidates = [System.Collections.Generic.List[int]]::new()
    $savedPid = Read-SavedPid
    if ($savedPid) {
        $candidates.Add($savedPid)
        foreach ($child in Get-ChildPids $savedPid) { $candidates.Add($child) }
    }
    $owner = Get-PortOwnerPid
    if ($owner) { $candidates.Add($owner) }

    $killed = 0
    foreach ($candidate in ($candidates | Sort-Object -Unique)) {
        if (-not (Test-IsOurBackend $candidate)) {
            Write-VoiceLog "Skip PID $candidate (port owner is not this backend)"
            continue
        }
        & taskkill /PID $candidate /T /F 2>&1 | Out-Null
        Write-VoiceLog "Stopped backend PID $candidate"
        $killed += 1
    }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    Write-VoiceLog "Backend stop complete (killed $killed process(es))"
}

function Get-BrowserPath {
    return @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Collections.Generic;
using System.Text;
using System.Runtime.InteropServices;

public sealed class VoiceWindowInfo
{
    public IntPtr Handle;
    public uint ProcessId;
    public string Title;

    public override string ToString()
    {
        return String.Format("{0} pid={1} title={2}", Handle.ToInt64(), ProcessId, Title);
    }
}

public static class VoiceWindowApi
{
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int maxCount);
    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_SHOWWINDOW = 0x0040;
    public const int SW_RESTORE = 9;
    public const uint WM_CLOSE = 0x0010;

    public static List<VoiceWindowInfo> ListVisibleWindows()
    {
        List<VoiceWindowInfo> list = new List<VoiceWindowInfo>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hWnd)) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            StringBuilder title = new StringBuilder(512);
            GetWindowTextW(hWnd, title, title.Capacity);
            VoiceWindowInfo info = new VoiceWindowInfo();
            info.Handle = hWnd;
            info.ProcessId = pid;
            info.Title = title.ToString();
            list.Add(info);
            return true;
        }, IntPtr.Zero);
        return list;
    }

    public static string GetTitle(IntPtr hWnd)
    {
        StringBuilder title = new StringBuilder(512);
        GetWindowTextW(hWnd, title, title.Capacity);
        return title.ToString();
    }

    public static List<IntPtr> FindWindowsByTitle(string needle)
    {
        List<IntPtr> matches = new List<IntPtr>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hWnd)) return true;
            if (GetTitle(hWnd).IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0)
                matches.Add(hWnd);
            return true;
        }, IntPtr.Zero);
        return matches;
    }

    public static string Describe(IntPtr hWnd)
    {
        RECT rect;
        if (!GetWindowRect(hWnd, out rect)) return "rect=unknown";
        return String.Format("rect={0},{1} {2}x{3}", rect.Left, rect.Top,
            rect.Right - rect.Left, rect.Bottom - rect.Top);
    }
}
'@

function Warm-Browser {
    $browser = Get-BrowserPath
    if (-not $browser) { throw "Neither Chrome nor Edge was found" }
    $existing = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(chrome|msedge)\.exe$' -and $_.CommandLine -like "*$BrowserProfile*" })
    if ($existing.Count -gt 0) {
        Write-VoiceLog "Browser profile already warm (PID $($existing[0].ProcessId))"
        return
    }

    $started = $Sw.ElapsedMilliseconds
    $state = Read-WindowState
    $mini = 0
    if ($state -and $state.MiniHandle) { $mini = [long]$state.MiniHandle }
    $before = @(Get-BrowserWindows | ForEach-Object { $_.HandleValue })

    # A normal (non-app) window keeps the process/profile warm without ever
    # being reused as the panel: --app=<url> always creates its own window.
    Start-Process -FilePath $browser -ArgumentList @(
        "about:blank",
        "--window-position=-32000,-32000",
        "--window-size=420,320",
        "--user-data-dir=$BrowserProfile",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble"
    )

    $warm = 0
    for ($i = 0; $i -lt 20; $i += 1) {
        $new = @(Get-BrowserWindows | Where-Object { $before -notcontains $_.HandleValue })
        if ($new.Count -gt 0) { $warm = $new[0].HandleValue; break }
        Start-Sleep -Milliseconds 200
    }
    Save-WindowState -MiniHandle $mini -WarmHandle $warm
    Write-VoiceLog ("Warmed browser profile (warm handle {0})" -f $warm)
    Write-VoicePhase "browser-warm" $started
}

function Close-MiniWindow {
    $windows = @(Get-MiniWindows)
    if ($windows.Count -eq 0) { return }
    foreach ($window in $windows) {
        Write-VoiceLog ("Closing mini window handle={0} PID={1} title='{2}'" -f `
            $window.HandleValue, $window.Id, $window.Title)
        [void][VoiceWindowApi]::PostMessage(
            $window.Handle, [VoiceWindowApi]::WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    $state = Read-WindowState
    $warm = 0
    if ($state -and $state.WarmHandle) { $warm = [long]$state.WarmHandle }
    Save-WindowState -MiniHandle 0 -WarmHandle $warm
}

function Open-MiniWindow {
    $started = $Sw.ElapsedMilliseconds
    Warm-Browser
    $before = @(Get-BrowserWindows | ForEach-Object { $_.HandleValue })
    $stamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $url = "http://127.0.0.1:$BackendPort/?compact=1&autostart=1&t=$stamp"
    $browser = Get-BrowserPath

    Start-Process -FilePath $browser -ArgumentList @(
        "--app=$url",
        "--window-size=420,320",
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-ui-for-media-stream",
        "--user-data-dir=$BrowserProfile",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble"
    )
    Write-VoiceLog "Opened mini window with autostart: $url"

    $handle = 0
    $source = "new-window"
    for ($i = 0; $i -lt 60; $i += 1) {
        $new = @(Get-BrowserWindows | Where-Object { $before -notcontains $_.HandleValue })
        if ($new.Count -gt 0) {
            $preferred = @($new | Where-Object { $_.Title -like "*$MiniTitle*" } | Select-Object -First 1)
            $candidate = if ($preferred.Count -gt 0) { $preferred[0] } else { $new[0] }
            $handle = $candidate.HandleValue
            break
        }
        Start-Sleep -Milliseconds 200
    }

    if ($handle -eq 0) {
        $fallback = @(Get-MiniWindows | Select-Object -First 1)
        if ($fallback.Count -gt 0) {
            $handle = $fallback[0].HandleValue
            $source = "title-fallback"
        }
    }

    if ($handle -eq 0) {
        $byTitle = @([VoiceWindowApi]::FindWindowsByTitle($MiniTitle) | Select-Object -First 1)
        if ($byTitle.Count -gt 0) {
            $handle = $byTitle[0].ToInt64()
            $source = "win32-title-fallback"
        }
    }

    if ($handle -eq 0) {
        Write-VoiceLog "Mini window handle not found after 12s; skipping topmost positioning"
        Write-VoicePhase "mini-window" $started
        return
    }

    $hwnd = [IntPtr]::new([int64]$handle)
    [void][VoiceWindowApi]::ShowWindow($hwnd, [VoiceWindowApi]::SW_RESTORE)
    $work = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $x = $work.Right - 420 - 16
    $y = $work.Bottom - 320 - 16
    [void][VoiceWindowApi]::SetWindowPos(
        $hwnd,
        [VoiceWindowApi]::HWND_TOPMOST,
        $x, $y, 0, 0,
        [VoiceWindowApi]::SWP_NOSIZE -bor [VoiceWindowApi]::SWP_SHOWWINDOW
    )
    $state = Read-WindowState
    $warm = 0
    if ($state -and $state.WarmHandle) { $warm = [long]$state.WarmHandle }
    Save-WindowState -MiniHandle $handle -WarmHandle $warm
    Write-VoiceLog ("Pinned mini window at {0},{1} (handle {2}, source {3}, {4})" -f `
        $x, $y, $handle, $source, [VoiceWindowApi]::Describe($hwnd))
    Write-VoicePhase "mini-window" $started
}

function Ensure-Backend {
    if (Test-BackendHealth) {
        Write-VoiceLog "Ensure: backend already healthy"
        return
    }
    Build-Frontend
    Start-Backend
}

$launcherMutex = $null
$watchdogMutex = $null
if ($Action -eq "Watch") {
    $watchdogMutex = [System.Threading.Mutex]::new($false, "Local\VoiceAssistantWatchdog")
    if (-not $watchdogMutex.WaitOne(0)) {
        Write-VoiceLog "Watchdog already running; exiting"
        exit 0
    }
} else {
    $launcherMutex = [System.Threading.Mutex]::new($false, "Local\VoiceAssistantLauncher")
    if (-not $launcherMutex.WaitOne(0)) {
        Write-VoiceLog "Ignored ${Action}: another launcher action is active"
        exit 0
    }
}

$exitCode = 0
try {
    Write-VoiceLog "Action $Action started (port $BackendPort)"
    switch ($Action) {
        "Status" {
            $distIndex = Join-Path $WebDir "dist\index.html"
            $windowState = Read-WindowState
            $miniWindows = @(Get-MiniWindows)
            Write-VoiceLog ("Status: detected {0} mini window(s)" -f $miniWindows.Count)
            [pscustomobject]@{
                Port = $BackendPort
                BackendListening = Test-VoicePort $BackendPort
                BackendHealthy = Test-BackendHealth
                TrackedPid = Read-SavedPid
                MiniWindows = $miniWindows.Count
                MiniHandle = if ($windowState) { $windowState.MiniHandle } else { 0 }
                FrontendBuilt = (Test-Path $distIndex)
            } | ConvertTo-Json
        }
        "Build" {
            Build-Frontend -Force
        }
        "Ensure" {
            $started = $Sw.ElapsedMilliseconds
            Ensure-Backend
            Write-VoicePhase "ensure" $started
        }
        "Watch" {
            $started = $Sw.ElapsedMilliseconds
            try {
                Ensure-Backend
                Warm-Browser
            } catch {
                Write-VoiceLog "Watchdog startup error: $_"
            }
            Write-VoicePhase "watchdog-boot" $started
            while ($true) {
                Start-Sleep -Seconds 10
                try {
                    if (-not (Test-BackendHealth)) {
                        Write-VoiceLog "Watchdog: backend unhealthy; restarting"
                        Ensure-Backend
                    }
                } catch {
                    Write-VoiceLog "Watchdog restart failed: $_"
                }
            }
        }
        "Stop" {
            Close-MiniWindow
            Stop-Backend
        }
        "Start" {
            $started = $Sw.ElapsedMilliseconds
            Build-Frontend
            Start-Backend
            Open-MiniWindow
            Write-VoicePhase "start" $started
        }
        "Toggle" {
            $started = $Sw.ElapsedMilliseconds
            $windows = @(Get-MiniWindows)
            Write-VoiceLog ("Toggle: detected {0} mini window(s)" -f $windows.Count)
            if ($windows.Count -gt 0) {
                Write-VoiceLog "Toggle: panel visible; closing panel (backend stays warm)"
                Close-MiniWindow
                Write-VoicePhase "toggle-close-panel" $started
            } else {
                Write-VoiceLog "Toggle: panel hidden; opening panel"
                $backendStarted = $Sw.ElapsedMilliseconds
                Ensure-Backend
                Write-VoicePhase "toggle-backend-ready" $backendStarted
                Open-MiniWindow
                Write-VoicePhase "toggle-open-panel" $started
            }
        }
    }
    if ($Action -ne "Watch") {
        Write-VoiceLog ("Action {0} complete (total {1}ms)" -f $Action, $Sw.ElapsedMilliseconds)
    }
} catch {
    Write-VoiceLog "ERROR: $_"
    Write-Error $_
    $exitCode = 1
} finally {
    if ($launcherMutex) { $launcherMutex.ReleaseMutex() | Out-Null; $launcherMutex.Dispose() }
}

exit $exitCode
