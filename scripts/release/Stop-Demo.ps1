[CmdletBinding()]
param(
    [switch]$KeepRuntime
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRoot = Join-Path $repoRoot 'apps\core-api\.runtime\stage10-demo'
$statePath = Join-Path $runtimeRoot 'processes.json'

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host 'Stage 10 demo 沒有可管理的 process state；未停止其他程序。'
    return
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
function Get-DescendantPids([int]$ParentPid) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentPid" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Get-DescendantPids ([int]$child.ProcessId)
        [int]$child.ProcessId
    }
}

foreach ($entry in @($state.processes | Sort-Object role -Descending)) {
    $targetProcessId = [int]$entry.pid
    foreach ($targetPid in @(Get-DescendantPids $targetProcessId) + $targetProcessId) {
        $process = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Stopping $($entry.role) PID $targetPid"
            Stop-Process -Id $targetPid -Force
        }
    }
}
Remove-Item -LiteralPath $statePath -Force
Write-Host 'Stage 10 demo stopped. Logs and health metadata remain for review.'

if (-not $KeepRuntime) {
    Write-Host "Runtime directory retained at $runtimeRoot; use Reset-Demo.ps1 to clear generated state."
}
