[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'SilentlyContinue'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot 'docs\device\runtime'
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

function Convert-ToGiB {
    param([double]$Bytes)
    return [math]::Round($Bytes / 1GB, 2)
}

function Format-DriverDate {
    param($Value)
    if ($null -eq $Value) { return $null }
    try { return ([datetime]$Value).ToString('yyyy-MM-dd') } catch { return [string]$Value }
}

function Protect-Path {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    return ($Path -replace '(?i)^[A-Z]:\\Users\\[^\\]+', '<user-profile>')
}

function Get-CommandVersion {
    param([string]$Name, [string[]]$Arguments = @('--version'))
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        return [ordered]@{ found = $false; version = $null; path = $null }
    }
    $path = $command.Source
    $version = $null
    try {
        $version = (& $path @Arguments 2>$null | Select-Object -First 1)
        if ($null -ne $version) { $version = ([string]$version).Trim() }
    } catch { $version = $null }
    if ([string]::IsNullOrWhiteSpace($version) -and (Test-Path -LiteralPath $path)) {
        try { $version = (Get-Item -LiteralPath $path).VersionInfo.ProductVersion } catch {}
    }
    return [ordered]@{ found = $true; version = $version; path = (Protect-Path $path) }
}

function Get-BrowserBinary {
    param([string]$Name, [string[]]$Candidates)
    foreach ($candidate in ($Candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate) {
            $file = Get-Item -LiteralPath $candidate
            return [ordered]@{
                found = $true
                name = $Name
                version = $file.VersionInfo.ProductVersion
                path = (Protect-Path $candidate)
            }
        }
    }
    return [ordered]@{ found = $false; name = $Name; version = $null; path = $null }
}

$computer = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$processor = Get-CimInstance Win32_Processor | Select-Object -First 1
$bios = Get-CimInstance Win32_BIOS | Select-Object -First 1
$systemDisk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" | Select-Object -First 1
$video = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match '(?i)890M|Radeon' } | Select-Object -First 1
$signedDrivers = @(Get-CimInstance Win32_PnPSignedDriver)

$pnpDevices = @()
if (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue) {
    $pnpDevices = @(Get-PnpDevice -PresentOnly)
}

$cameraDevices = @($pnpDevices | Where-Object {
    $_.Class -match '(?i)^Camera$|^Image$'
} | ForEach-Object {
    [ordered]@{ name = $_.FriendlyName; status = $_.Status; class = $_.Class }
})

$audioDevices = @($pnpDevices | Where-Object {
    $_.Class -match '(?i)^MEDIA$' -and $_.FriendlyName -notmatch '(?i)Bluetooth|A2DP'
} | ForEach-Object {
    [ordered]@{ name = $_.FriendlyName; status = $_.Status; class = $_.Class }
})

$npuDevice = $pnpDevices | Where-Object {
    $_.FriendlyName -match '(?i)\bNPU\b|XDNA|Compute Accelerator'
} | Select-Object -First 1
$npuDriver = $signedDrivers | Where-Object {
    $_.DeviceName -match '(?i)\bNPU\b|XDNA|Compute Accelerator' -and $_.DriverProviderName -match '(?i)AMD'
} | Select-Object -First 1
$gpuDriver = $signedDrivers | Where-Object {
    $_.DeviceName -match '(?i)Radeon.*890M'
} | Select-Object -First 1

$totalMemoryBytes = [double]$computer.TotalPhysicalMemory
$freeMemoryBytes = [double]$os.FreePhysicalMemory * 1KB
$totalMemoryGiB = Convert-ToGiB $totalMemoryBytes
$freeMemoryGiB = Convert-ToGiB $freeMemoryBytes
$safeReserveGiB = [math]::Round([math]::Max($totalMemoryGiB * 0.25, 6), 2)
$runtimeCapacityGiB = [math]::Round($totalMemoryGiB - $safeReserveGiB, 2)
$diskFreeGiB = Convert-ToGiB ([double]$systemDisk.FreeSpace)
$diskSizeGiB = Convert-ToGiB ([double]$systemDisk.Size)
$diskFloorGiB = 100

$powerText = (& powercfg /getactivescheme 2>$null | Select-Object -First 1)
$powerPlan = $null
if ($powerText -match '\(([^)]+)\)') { $powerPlan = $Matches[1] }
$battery = Get-CimInstance Win32_Battery | Select-Object -First 1

$browserCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path ${env:ProgramFiles} 'Microsoft\Edge\Application\msedge.exe')
)
$chromeCandidates = @(
    (Join-Path ${env:ProgramFiles} 'Google\Chrome\Application\chrome.exe'),
    (Join-Path ${env:LocalAppData} 'Google\Chrome\Application\chrome.exe')
)

$checks = [ordered]@{
    memory_reserve = [ordered]@{
        status = if ($freeMemoryGiB -ge $safeReserveGiB) { 'pass' } else { 'degraded' }
        detail = "free=${freeMemoryGiB} GiB; reserve=${safeReserveGiB} GiB"
    }
    storage_floor = [ordered]@{
        status = if ($diskFreeGiB -ge $diskFloorGiB) { 'pass' } else { 'degraded' }
        detail = "free=${diskFreeGiB} GiB; floor=${diskFloorGiB} GiB"
    }
    npu_pnp = [ordered]@{
        status = if ($null -ne $npuDevice -and $npuDevice.Status -eq 'OK') { 'pass' } else { 'degraded' }
        detail = if ($null -ne $npuDevice) { "$($npuDevice.FriendlyName): $($npuDevice.Status)" } else { 'NPU PnP device not detected' }
    }
    camera_pnp = [ordered]@{
        status = if ($cameraDevices.Count -gt 0 -and (@($cameraDevices | Where-Object { $_.status -eq 'OK' }).Count -gt 0)) { 'pass' } else { 'offline' }
        detail = "$($cameraDevices.Count) camera device(s) detected"
    }
    audio_pnp = [ordered]@{
        status = if ($audioDevices.Count -gt 0) { 'pass' } else { 'offline' }
        detail = "$($audioDevices.Count) audio device(s) detected"
    }
    browser_media = [ordered]@{
        status = 'not_run'
        detail = 'Run the local browser device check and inspect browser-check-result.json'
    }
}

$browserResultPath = Join-Path $OutputDirectory 'browser-check-result.json'
if (Test-Path -LiteralPath $browserResultPath) {
    $browserResult = Get-Content -LiteralPath $browserResultPath -Raw | ConvertFrom-Json
    $cameraStatus = if ($browserResult.camera.status -eq 'pass' -and $browserResult.camera.captured -eq $true) { 'pass' } else { 'degraded' }
    $micStatus = if ($browserResult.microphone.status -eq 'pass') { 'pass' } else { 'not_run' }
    $playbackStatus = if ($browserResult.playback.status -eq 'pass') { 'pass' } else { 'degraded' }
    $browserStatus = if ($cameraStatus -eq 'pass' -and $micStatus -eq 'pass' -and $playbackStatus -eq 'pass') { 'pass' } else { 'degraded' }
    $checks.browser_media = [ordered]@{
        status = $browserStatus
        detail = "camera=$cameraStatus; microphone=$micStatus; playback=$playbackStatus; secure_context=$($browserResult.secure_context)"
    }
}

$overallStatus = 'ready'
if (@($checks.Values | Where-Object { $_.status -eq 'offline' -or $_.status -eq 'fail' }).Count -gt 0) {
    $overallStatus = 'offline'
} elseif (@($checks.Values | Where-Object { $_.status -eq 'degraded' }).Count -gt 0) {
    $overallStatus = 'degraded'
}

$snapshot = [ordered]@{
    schema_version = 'device-health.v1'
    checked_at = (Get-Date).ToUniversalTime().ToString('o')
    status = $overallStatus
    os = [ordered]@{
        caption = $os.Caption
        version = $os.Version
        build = $os.BuildNumber
        architecture = $os.OSArchitecture
        locale = $os.Locale
    }
    firmware = [ordered]@{
        manufacturer = $bios.Manufacturer
        version = $bios.SMBIOSBIOSVersion
        release_date = Format-DriverDate $bios.ReleaseDate
    }
    platform = [ordered]@{
        manufacturer = $computer.Manufacturer
        model = $computer.Model
        family = $computer.SystemFamily
    }
    cpu = [ordered]@{
        name = ([string]$processor.Name).Trim()
        manufacturer = $processor.Manufacturer
        cores = $processor.NumberOfCores
        logical_processors = $processor.NumberOfLogicalProcessors
        max_clock_mhz = $processor.MaxClockSpeed
        current_clock_mhz = $processor.CurrentClockSpeed
        load_percent = $processor.LoadPercentage
        l3_cache_kib = $processor.L3CacheSize
    }
    memory = [ordered]@{
        physical_total_gib = $totalMemoryGiB
        currently_free_gib = $freeMemoryGiB
        safe_reserve_gib = $safeReserveGiB
        runtime_capacity_after_reserve_gib = $runtimeCapacityGiB
        reserve_rule = 'max(physical_ram * 25%, 6 GiB)'
    }
    storage = [ordered]@{
        drive = 'C:'
        filesystem = $systemDisk.FileSystem
        total_gib = $diskSizeGiB
        free_gib = $diskFreeGiB
        operational_floor_gib = $diskFloorGiB
    }
    gpu = [ordered]@{
        name = $video.Name
        driver_version = $gpuDriver.DriverVersion
        driver_date = Format-DriverDate $gpuDriver.DriverDate
        status = $video.Status
        resolution = if ($video.CurrentHorizontalResolution) { "$($video.CurrentHorizontalResolution)x$($video.CurrentVerticalResolution)" } else { $null }
        refresh_hz = $video.CurrentRefreshRate
        policy = 'reserve for display, browser and Camera; not required for inference'
    }
    npu = [ordered]@{
        name = if ($null -ne $npuDevice) { $npuDevice.FriendlyName } else { $null }
        pnp_status = if ($null -ne $npuDevice) { $npuDevice.Status } else { 'not_detected' }
        driver_version = $npuDriver.DriverVersion
        driver_date = Format-DriverDate $npuDriver.DriverDate
        runtime_status = 'not_benchmarked'
        evidence = 'Windows PnP ComputeAccelerator device and signed AMD driver; Stage 06 must run an actual NPU probe.'
    }
    camera = $cameraDevices
    audio = $audioDevices
    power = [ordered]@{
        active_plan = $powerPlan
        battery_percent = if ($null -ne $battery) { $battery.EstimatedChargeRemaining } else { $null }
        battery_status = if ($null -ne $battery) { $battery.BatteryStatus } else { $null }
    }
    runtimes = [ordered]@{
        node = Get-CommandVersion 'node'
        npm = Get-CommandVersion 'npm'
        python = Get-CommandVersion 'python'
        powershell = Get-CommandVersion 'pwsh'
        edge = Get-BrowserBinary 'Microsoft Edge' $browserCandidates
        chrome = Get-BrowserBinary 'Google Chrome' $chromeCandidates
    }
    resource_budget = [ordered]@{
        system_browser_camera_reserve_gib = $safeReserveGiB
        core_backend_rag_planning_cap_gib = 4.0
        asr_cpu_planning_cap_gib = 4.0
        tts_cpu_planning_cap_gib = 2.0
        frontend_speech_overhead_planning_cap_gib = 1.5
        unallocated_capacity_after_reserve_gib = [math]::Round($runtimeCapacityGiB - 11.5, 2)
        cpu_policy = 'single Core worker; ASR CPU and TTS serialized; keep iGPU for display/browser'
        storage_policy = 'pause new model/RAG downloads below 100 GiB free on C:'
    }
    checks = $checks
}

$jsonPath = Join-Path $OutputDirectory 'device-health.json'
$markdownPath = Join-Path $OutputDirectory 'device-health.md'
$snapshot | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$markdown = @()
$markdown += '# Device health snapshot'
$markdown += ''
$markdown += "- Status: **$($snapshot.status)**"
$markdown += "- Checked at (UTC): ``$($snapshot.checked_at)``"
$markdown += "- Schema: ``$($snapshot.schema_version)``"
$markdown += ''
$markdown += '## Inventory'
$markdown += ''
$markdown += "- OS: $($snapshot.os.caption), build $($snapshot.os.build), $($snapshot.os.architecture)"
$markdown += "- Platform: $($snapshot.platform.manufacturer) $($snapshot.platform.model)"
$markdown += "- BIOS: $($snapshot.firmware.version)"
$markdown += "- CPU: $($snapshot.cpu.name), $($snapshot.cpu.cores) cores / $($snapshot.cpu.logical_processors) logical processors"
$markdown += "- RAM: $($snapshot.memory.physical_total_gib) GiB total; $($snapshot.memory.currently_free_gib) GiB free at capture"
$markdown += "- Storage: C: $($snapshot.storage.free_gib) GiB free of $($snapshot.storage.total_gib) GiB"
$markdown += "- GPU: $($snapshot.gpu.name), driver $($snapshot.gpu.driver_version), $($snapshot.gpu.resolution) @ $($snapshot.gpu.refresh_hz) Hz"
$markdown += "- NPU: $($snapshot.npu.name), PnP ``$($snapshot.npu.pnp_status)``, driver $($snapshot.npu.driver_version); runtime benchmark **not yet run**"
$markdown += "- Power: $($snapshot.power.active_plan); battery $($snapshot.power.battery_percent)%"
$markdown += ''
$markdown += '## Resource budget'
$markdown += ''
$markdown += '| Bucket | Planning value | Rule |'
$markdown += '| --- | ---: | --- |'
$markdown += "| Windows / browser / Camera reserve | $($snapshot.resource_budget.system_browser_camera_reserve_gib) GiB | max(25% RAM, 6 GiB) |"
$markdown += "| Runtime capacity after reserve | $($snapshot.memory.runtime_capacity_after_reserve_gib) GiB | physical RAM minus reserve |"
$markdown += "| Core Backend + Local RAG cap | $($snapshot.resource_budget.core_backend_rag_planning_cap_gib) GiB | single worker, lightweight embedding |"
$markdown += "| ASR CPU cap | $($snapshot.resource_budget.asr_cpu_planning_cap_gib) GiB | must be measured again in Stage 05 |"
$markdown += "| TTS CPU cap | $($snapshot.resource_budget.tts_cpu_planning_cap_gib) GiB | CPU default; do not overlap with CPU ASR |"
$markdown += "| Frontend + Speech overhead cap | $($snapshot.resource_budget.frontend_speech_overhead_planning_cap_gib) GiB | browser and local gateway overhead |"
$markdown += "| Unallocated capacity after reserve | $($snapshot.resource_budget.unallocated_capacity_after_reserve_gib) GiB | measurement headroom |"
$markdown += ''
$markdown += '## Device checks'
$markdown += ''
$markdown += '| Check | Status | Detail |'
$markdown += '| --- | --- | --- |'
foreach ($checkName in $snapshot.checks.Keys) {
    $check = $snapshot.checks[$checkName]
    $markdown += "| $checkName | $($check.status) | $($check.detail) |"
}
$markdown += ''
$markdown += 'The browser media check reports metadata only; it does not persist camera frames or microphone bytes. A `degraded` browser result means at least one manual media capability still needs a user-run test or fallback.'
$markdown -join "`n" | Set-Content -LiteralPath $markdownPath -Encoding UTF8

Write-Output "Wrote $jsonPath"
Write-Output "Wrote $markdownPath"
Write-Output "Status: $overallStatus"
