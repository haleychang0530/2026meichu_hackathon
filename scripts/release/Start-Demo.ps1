[CmdletBinding()]
param(
    [ValidateSet('mock', 'real')]
    [string]$Mode = 'mock',
    [ValidateSet('mock', 'cpu')]
    [string]$SpeechProfile = 'mock',
    [string]$Mi300BaseUrl = $env:VLM_BASE_URL,
    [string]$AsrModelPath = $env:BREEZE_ASR_MODEL_PATH,
    [string]$TtsModelPath = $env:MMS_TTS_MODEL_PATH,
    [switch]$NoBrowser,
    [switch]$SkipRagReindex,
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRoot = Join-Path $repoRoot 'apps\core-api\.runtime\stage10-demo'
$logRoot = Join-Path $runtimeRoot 'logs'
$statePath = Join-Path $runtimeRoot 'processes.json'
$healthPath = Join-Path $runtimeRoot 'health.json'
$coreDataRoot = Join-Path $runtimeRoot 'core-data'
$speechCacheRoot = Join-Path $runtimeRoot 'audio-cache'
$coreDir = Join-Path $repoRoot 'apps\core-api'
$speechDir = Join-Path $repoRoot 'services\speech-local'
$webDir = Join-Path $repoRoot 'apps\web'
$corePython = Join-Path $coreDir '.venv\Scripts\python.exe'
$speechPython = Join-Path $speechDir '.venv\Scripts\python.exe'

function Assert-Path([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description 不存在：$Path"
    }
}

function Resolve-ServiceOrigin([string]$Value, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name 未設定。real mode 必須使用當次 Manta forwarding 的 gateway origin。"
    }
    $candidate = $Value.Trim().TrimEnd('/')
    $uri = $null
    if (-not [Uri]::TryCreate($candidate, [UriKind]::Absolute, [ref]$uri)) {
        throw "$Name 必須是完整的 HTTP(S) origin：$candidate"
    }
    if ($uri.Scheme -notin @('http', 'https') -or -not $uri.Host) {
        throw "$Name 必須是完整的 HTTP(S) origin：$candidate"
    }
    if ($uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {
        throw "$Name 不得包含 credentials、path、query 或 fragment：$candidate"
    }
    return $candidate
}

function Resolve-ModelPath([string]$Path, [string]$Description) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Description 不存在或不是資料夾：$Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Find-HuggingFaceSnapshot([string]$CacheKey, [string]$Revision) {
    $roots = [System.Collections.Generic.List[string]]::new()
    if ($env:HUGGINGFACE_HUB_CACHE) { $roots.Add($env:HUGGINGFACE_HUB_CACHE) }
    if ($env:HF_HOME) { $roots.Add((Join-Path $env:HF_HOME 'hub')) }
    if ($env:TRANSFORMERS_CACHE) { $roots.Add($env:TRANSFORMERS_CACHE) }
    if ($env:USERPROFILE) {
        $roots.Add((Join-Path $env:USERPROFILE '.cache\huggingface\hub'))
    }
    foreach ($root in ($roots | Select-Object -Unique)) {
        $snapshot = Join-Path (Join-Path (Join-Path $root $CacheKey) 'snapshots') $Revision
        if (Test-Path -LiteralPath $snapshot -PathType Container) {
            return (Resolve-Path -LiteralPath $snapshot).Path
        }
    }
    return $null
}

function Test-PidAlive([int]$ProcessId) {
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Start-ManagedProcess {
    param(
        [string]$Role,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [hashtable]$Environment
    )
    $stdout = Join-Path $logRoot "$Role.out.log"
    $stderr = Join-Path $logRoot "$Role.err.log"
    $startParams = @{
        FilePath = $FilePath
        ArgumentList = $ArgumentList
        WorkingDirectory = $WorkingDirectory
        RedirectStandardOutput = $stdout
        RedirectStandardError = $stderr
        WindowStyle = 'Hidden'
        PassThru = $true
        Environment = $Environment
    }
    $process = Start-Process @startParams
    return [ordered]@{
        role = $Role
        pid = $process.Id
        executable = $FilePath
        stdout = $stdout
        stderr = $stderr
    }
}

function Wait-Http([string]$Uri, [string]$Role, [int]$TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "$Role ready: $Uri ($($response.StatusCode))"
                return
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    } while ((Get-Date) -lt $deadline)
    throw "$Role 在 $TimeoutSeconds 秒內沒有回應：$Uri"
}

if ($Mode -eq 'real') {
    $Mi300BaseUrl = Resolve-ServiceOrigin $Mi300BaseUrl 'Mi300BaseUrl'
} elseif (-not [string]::IsNullOrWhiteSpace($Mi300BaseUrl)) {
    $Mi300BaseUrl = Resolve-ServiceOrigin $Mi300BaseUrl 'Mi300BaseUrl'
}

Assert-Path $corePython 'Core API Python runtime'
Assert-Path (Join-Path $webDir 'package.json') 'Web package'
if ($SpeechProfile -eq 'cpu') { Assert-Path $speechPython 'Speech CPU Python runtime' }
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) { throw '找不到 npm.cmd，請先安裝 Node.js。' }

New-Item -ItemType Directory -Force -Path $runtimeRoot, $logRoot, $coreDataRoot, $speechCacheRoot | Out-Null

if ($SpeechProfile -eq 'cpu') {
    $AsrModelPath = Resolve-ModelPath $AsrModelPath 'Breeze ASR model'
    if (-not $AsrModelPath) {
        $AsrModelPath = Find-HuggingFaceSnapshot `
            'models--paulpengtw--faster-whisper-Breeze-ASR-26' `
            '7bf9dadb2f7f2bb418e82b3f074549fda82f7f47'
    }
    if (-not $AsrModelPath) {
        throw '找不到固定 revision 的 Breeze ASR 本機模型；請先執行 scripts\release\Provision-SpeechModels.ps1 -Model asr，或使用 -AsrModelPath 指定 snapshot 資料夾。'
    }

    $TtsModelPath = Resolve-ModelPath $TtsModelPath 'MMS TTS model'
    if (-not $TtsModelPath) {
        $TtsModelPath = Find-HuggingFaceSnapshot `
            'models--facebook--mms-tts-nan' `
            'f28526a6caaf9dc55e030da83008c933f6a1978b'
    }
    if (-not $TtsModelPath) {
        throw '找不到固定 revision 的 MMS TTS 本機模型；請先執行 scripts\release\Provision-SpeechModels.ps1 -Model tts，或使用 -TtsModelPath 指定 snapshot 資料夾。'
    }

    & $speechPython -c 'import faster_whisper, torch, transformers' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'Speech CPU runtime 不完整；請執行 services\speech-local\.venv\Scripts\python.exe -m pip install -r services\speech-local\requirements.txt。'
    }
}
if (Test-Path -LiteralPath $statePath) {
    $oldState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $live = @($oldState.processes | Where-Object { Test-PidAlive ([int]$_.pid) })
    if ($live.Count -gt 0) {
        throw "Stage 10 demo 已在執行中；請先執行 scripts/release/Stop-Demo.ps1。"
    }
    Remove-Item -LiteralPath $statePath -Force
}

$commonEnvironment = @{
    PYTHONUNBUFFERED = '1'
    STAGE10_RUNTIME_ROOT = $runtimeRoot
}
$coreEnvironment = @{
    CORE_PROFILE = if ($Mode -eq 'real') { 'development' } else { 'demo' }
    CORE_PROVIDER = if ($Mode -eq 'real') { 'real' } else { 'fixture' }
    CORE_HOST = '127.0.0.1'
    CORE_PORT = '8000'
    CORE_DATA_DIR = $coreDataRoot
    CORE_ALLOWED_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173'
    SPEECH_BASE_URL = 'http://127.0.0.1:8200'
    RAG_MANIFEST_PATH = (Join-Path $repoRoot 'data\rag\manifest.json')
    RAG_INDEX_ROOT = (Join-Path $runtimeRoot 'rag-indexes')
    PYTHONUNBUFFERED = '1'
}
if ($Mi300BaseUrl) { $coreEnvironment.VLM_BASE_URL = $Mi300BaseUrl }
$speechEnvironment = @{
    SPEECH_ASR_BACKEND = if ($SpeechProfile -eq 'cpu') { 'breeze' } else { 'mock' }
    SPEECH_TTS_BACKEND = if ($SpeechProfile -eq 'cpu') { 'mms' } else { 'mock' }
    BREEZE_ASR_CPU_THREADS = '4'
    BREEZE_ASR_LOCAL_FILES_ONLY = if ($SpeechProfile -eq 'cpu') { '1' } else { '0' }
    MMS_TTS_LOCAL_FILES_ONLY = if ($SpeechProfile -eq 'cpu') { '1' } else { '0' }
    MMS_TTS_CACHE_DIR = $speechCacheRoot
    MMS_TTS_FALLBACK_MANIFEST = (Join-Path $repoRoot 'services\speech-local\fallback\prerecorded_manifest.json')
    BREEZE_ASR_MODEL_PATH = if ($AsrModelPath) { $AsrModelPath } else { '' }
    MMS_TTS_MODEL_PATH = if ($TtsModelPath) { $TtsModelPath } else { '' }
    PYTHONUNBUFFERED = '1'
}
$webEnvironment = @{
    VITE_DATA_MODE = $Mode
    VITE_CORE_API_BASE_URL = 'http://127.0.0.1:8000'
    VITE_SPEECH_MODE = if ($SpeechProfile -eq 'cpu') { 'real' } else { 'mock' }
    VITE_SPEECH_GATEWAY_BASE_URL = 'http://127.0.0.1:8200'
}

if (-not $SkipRagReindex) {
    $ragLog = Join-Path $logRoot 'rag-reindex.log'
    & $corePython (Join-Path $repoRoot 'scripts\rag_reindex.py') --mode full --manifest (Join-Path $repoRoot 'data\rag\manifest.json') --index-root (Join-Path $runtimeRoot 'rag-indexes') *>&1 | Set-Content -LiteralPath $ragLog -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "RAG reindex failed; see $ragLog" }
}

$processes = [System.Collections.Generic.List[object]]::new()
try {
    $speechArgs = @(
        (Join-Path $speechDir 'gateway.py'), '--host', '127.0.0.1', '--port', '8200',
        '--asr-backend', $speechEnvironment.SPEECH_ASR_BACKEND,
        '--tts-backend', $speechEnvironment.SPEECH_TTS_BACKEND,
        '--asr-cpu-threads', '4',
        '--tts-cache-dir', $speechCacheRoot,
        '--tts-fallback-manifest', $speechEnvironment.MMS_TTS_FALLBACK_MANIFEST
    )
    if ($SpeechProfile -eq 'cpu') {
        $speechArgs += @(
            '--asr-model-path', $AsrModelPath,
            '--tts-model-path', $TtsModelPath,
            '--asr-local-files-only',
            '--tts-local-files-only'
        )
    }
    $speechExecutable = if ($SpeechProfile -eq 'cpu') { $speechPython } else { (Get-Command python.exe -ErrorAction Stop).Source }
    $processes.Add((Start-ManagedProcess -Role 'speech' -FilePath $speechExecutable -ArgumentList $speechArgs -WorkingDirectory $speechDir -Environment $speechEnvironment))

    $processes.Add((Start-ManagedProcess -Role 'core' -FilePath $corePython -ArgumentList @('-m', 'core_api') -WorkingDirectory $coreDir -Environment $coreEnvironment))

    $webArgs = @('--prefix', $webDir, 'run', 'dev', '--', '--host', '127.0.0.1')
    $processes.Add((Start-ManagedProcess -Role 'web' -FilePath $npm.Source -ArgumentList $webArgs -WorkingDirectory $repoRoot -Environment $webEnvironment))

    $state = [ordered]@{
        schema_version = 'stage10-processes.v1'
        started_at = (Get-Date).ToUniversalTime().ToString('o')
        mode = $Mode
        speech_profile = $SpeechProfile
        runtime_root = $runtimeRoot
        processes = @($processes)
    }
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8

    Wait-Http 'http://127.0.0.1:8200/local/health' 'Speech Gateway'
    try {
        Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8200/local/warmup' -ContentType 'application/json' -Body '{"services":["asr","tts"]}' -TimeoutSec 120 | Out-Null
        Write-Host 'Speech warmup ready.'
    } catch {
        Write-Warning 'Speech warmup failed; the health page will show the degraded fallback.'
    }
    Wait-Http 'http://127.0.0.1:8000/api/health' 'Core Backend'
    Wait-Http 'http://127.0.0.1:5173/health' 'Web release health page'
    if (-not $SkipHealthCheck) {
        & (Join-Path $PSScriptRoot 'Health-Demo.ps1') -OutputPath $healthPath
    }
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173/health' | Out-Null }
    Write-Host "Stage 10 demo started in $Mode mode ($SpeechProfile speech)."
    Write-Host 'Health page: http://127.0.0.1:5173/health'
    Write-Host 'Stop: scripts/release/Stop-Demo.ps1'
} catch {
    & (Join-Path $PSScriptRoot 'Stop-Demo.ps1') -KeepRuntime -ErrorAction SilentlyContinue
    throw
}
