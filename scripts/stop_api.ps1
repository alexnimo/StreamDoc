# Stop any running StreamDoc API processes and their leftover child workers.
# Run from just:  powershell -File scripts/stop_api.ps1

$ErrorActionPreference = 'SilentlyContinue'

function Get-ProcessList {
    return Get-CimInstance Win32_Process | Select-Object ProcessId, Name, CommandLine, ParentProcessId
}

function Stop-ProcessSafe ($id) {
    try { Stop-Process -Id $id -Force } catch { }
}

$all = Get-ProcessList

# 1. Kill the API console script / uvicorn directly.
$targets = $all | Where-Object {
    $_.Name -eq 'streamdoc-api.exe' -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'streamdoc-api|uvicorn.*main:app')
}

foreach ($p in $targets) {
    Write-Host "Stopping API process $($p.ProcessId) ($($p.Name))"
    Stop-ProcessSafe $p.ProcessId
}

if ($targets) {
    Start-Sleep -Seconds 2
}

# Refresh process list after the main API processes are gone.
$all = Get-ProcessList

# 2. Multiprocessing.spawn children from the API can keep the .venv\Scripts\streamdoc-api.exe
#    handle open after the parent exits. Their command line contains 'multiprocessing.spawn'
#    and their parent PID is either gone or was the API.
$spawnChildren = $all | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -match 'multiprocessing\.spawn'
}

$currentIds = $all | ForEach-Object { $_.ProcessId }
foreach ($p in $spawnChildren) {
    $parentAlive = $currentIds -contains $p.ParentProcessId
    $parent = $all | Where-Object { $_.ProcessId -eq $p.ParentProcessId } | Select-Object -First 1
    $parentIsApi = $parent -and ($parent.Name -eq 'streamdoc-api.exe' -or $parent.CommandLine -match 'streamdoc-api|uvicorn')

    if (-not $parentAlive -or $parentIsApi) {
        Write-Host "Stopping orphaned multiprocessing child $($p.ProcessId)"
        Stop-ProcessSafe $p.ProcessId
    }
}
