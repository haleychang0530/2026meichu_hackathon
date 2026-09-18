[CmdletBinding()]
param(
    [string]$OutputPath
)

$ErrorActionPreference = 'Continue'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRoot = Join-Path $repoRoot 'apps\core-api\.runtime\stage10-demo'
$statePath = Join-Path $runtimeRoot 'processes.json'

function Get-Endpoint([string]$Name, [string]$Uri) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 4
        $watch.Stop()
        return [ordered]@{ name = $Name; status = 'ready'; http_status = [int]$response.StatusCode; latency_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 2); uri = $Uri; error = $null }
    } catch {
        $watch.Stop()
        return [ordered]@{ name = $Name; status = 'offline'; http_status = $null; latency_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 2); uri = $Uri; error = '服務未回應或尚未啟動' }
    }
}

function Get-JsonEndpoint([string]$Name, [string]$Uri) {
    $base = Get-Endpoint -Name $Name -Uri $Uri
    if ($base.status -ne 'ready') { return [ordered]@{ endpoint = $base; payload = $null } }
    try {
        $payload = Invoke-RestMethod -UseBasicParsing -Uri $Uri -TimeoutSec 4
        return [ordered]@{ endpoint = $base; payload = $payload }
    } catch {
        $base.status = 'degraded'
        $base.error = '服務回應不是可解析的 JSON'
        return [ordered]@{ endpoint = $base; payload = $null }
    }
}

function Get-ResourceSnapshot {
    $snapshot = [ordered]@{
        memory = [ordered]@{
            status = 'not_available'
            physical_total_bytes = $null
            available_bytes = $null
            reserve_target_bytes = $null
            available_after_reserve_bytes = $null
        }
        storage = [ordered]@{
            status = 'not_available'
            drive = 'C:'
            total_bytes = $null
            free_bytes = $null
        }
        temperature = [ordered]@{
            status = 'not_available'
            celsius_max = $null
            source = 'Windows thermal zone; availability depends on firmware'
        }
    }
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        $total = [int64]$os.TotalVisibleMemorySize * 1KB
        $available = [int64]$os.FreePhysicalMemory * 1KB
        $reserve = [math]::Max($total * 0.25, 6GB)
        $snapshot.memory = [ordered]@{
            status = 'ready'
            physical_total_bytes = $total
            available_bytes = $available
            reserve_target_bytes = [int64]$reserve
            available_after_reserve_bytes = [int64]($available - $reserve)
        }
    } catch { }
    try {
        $drive = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='C:'" -ErrorAction Stop
        $snapshot.storage = [ordered]@{
            status = if ([int64]$drive.FreeSpace -ge 100GB) { 'ready' } else { 'degraded' }
            drive = 'C:'
            total_bytes = [int64]$drive.Size
            free_bytes = [int64]$drive.FreeSpace
        }
    } catch { }
    try {
        $zones = @(Get-CimInstance -Namespace 'root/wmi' -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop)
        $temperatures = @($zones | Where-Object { $_.CurrentTemperature -gt 0 } | ForEach-Object {
            [math]::Round(([double]$_.CurrentTemperature / 10) - 273.15, 1)
        })
        if ($temperatures.Count -gt 0) {
            $snapshot.temperature = [ordered]@{
                status = 'ready'
                celsius_max = ($temperatures | Measure-Object -Maximum).Maximum
                source = 'Windows thermal zone; availability depends on firmware'
            }
        }
    } catch { }
    return $snapshot
}

$endpoints = @(
    [ordered]@{ endpoint = (Get-Endpoint -Name 'frontend' -Uri 'http://127.0.0.1:5173/health'); payload = $null },
    (Get-JsonEndpoint -Name 'core-api' -Uri 'http://127.0.0.1:8000/api/health'),
    (Get-JsonEndpoint -Name 'speech-gateway' -Uri 'http://127.0.0.1:8200/local/health')
)
$core = ($endpoints | Where-Object { $_.endpoint.name -eq 'core-api' }).payload
$serviceChecks = [System.Collections.Generic.List[object]]::new()
if ($core -and $core.services) {
    foreach ($service in $core.services) {
        $serviceChecks.Add([ordered]@{
            name = $service.service
            status = $service.status
            device = $service.device
            model_revision = $service.model_revision
            queue_depth = $service.queue_depth
            error = if ($service.last_error) { $service.last_error.message } else { $null }
        })
    }
}

$processes = @()
if (Test-Path -LiteralPath $statePath) {
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        foreach ($entry in @($state.processes)) {
            $process = Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue
            $processes += [ordered]@{
                role = $entry.role
                pid = [int]$entry.pid
                alive = $null -ne $process
                working_set_bytes = if ($process) { [int64]$process.WorkingSet64 } else { $null }
                cpu_seconds = if ($process) { [math]::Round($process.TotalProcessorTime.TotalSeconds, 3) } else { $null }
            }
        }
    } catch { }
}

$overall = 'ready'
if (($endpoints | Where-Object { $_.endpoint.status -eq 'offline' }).Count -gt 0) { $overall = 'offline' }
elseif (($endpoints | Where-Object { $_.endpoint.status -eq 'degraded' }).Count -gt 0 -or ($serviceChecks | Where-Object { $_.status -ne 'ready' }).Count -gt 0) { $overall = 'degraded' }
$report = [ordered]@{
    schema_version = 'stage10-health.v1'
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    overall_status = $overall
    profile = if (Test-Path -LiteralPath $statePath) { (Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json).mode } else { $null }
    cpu_only_profile = [ordered]@{ status = 'ready'; npu = 'disabled'; note = 'NPU is not a release gate; ASR/TTS use CPU.' }
    endpoints = $endpoints
    services = @($serviceChecks)
    browser_media = [ordered]@{ status = 'operator_check'; note = 'Open /health and press 檢查相機與麥克風; PowerShell cannot grant browser permissions.' }
    resources = Get-ResourceSnapshot
    processes = @($processes)
    privacy = [ordered]@{ status = 'ready'; note = 'Stage 10 runtime keeps logs/metadata under .runtime; raw student audio/photos are not written by the services.' }
}
$json = $report | ConvertTo-Json -Depth 8
if ($OutputPath) {
    $parent = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $json | Set-Content -LiteralPath $OutputPath -Encoding utf8
}
Write-Host "Stage 10 health: $overall"
@($report.services) | ForEach-Object { [pscustomobject]$_ } | Format-Table name, status, device, model_revision, queue_depth -AutoSize | Out-String | Write-Host
@($report.processes) | ForEach-Object { [pscustomobject]$_ } | Format-Table role, pid, alive, working_set_bytes, cpu_seconds -AutoSize | Out-String | Write-Host
if ($OutputPath) { Write-Host "Health metadata: $OutputPath" }
