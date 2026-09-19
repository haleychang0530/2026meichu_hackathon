[CmdletBinding()]
param(
    [ValidateSet('asr', 'tts', 'all')]
    [string]$Model = 'all'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$speechPython = Join-Path $repoRoot 'services\speech-local\.venv\Scripts\python.exe'

# Windows developer mode/admin rights are not required for the Hugging Face
# cache. The runtime worker uses the same setting before loading a model.
$env:HF_HUB_DISABLE_SYMLINKS = '1'
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'

if (-not (Test-Path -LiteralPath $speechPython -PathType Leaf)) {
    throw "Speech CPU Python runtime 不存在：$speechPython"
}

$models = @(
    [ordered]@{
        name = 'Breeze ASR-26'
        repo = 'paulpengtw/faster-whisper-Breeze-ASR-26'
        revision = '7bf9dadb2f7f2bb418e82b3f074549fda82f7f47'
    },
    [ordered]@{
        name = 'MMS TTS nan'
        repo = 'facebook/mms-tts-nan'
        revision = 'f28526a6caaf9dc55e030da83008c933f6a1978b'
    }
)
if ($Model -eq 'asr') { $models = @($models[0]) }
if ($Model -eq 'tts') { $models = @($models[1]) }

$script = @'
from huggingface_hub import snapshot_download
import sys

repo_id, revision = sys.argv[1:]
path = snapshot_download(repo_id=repo_id, revision=revision)
print(path)
'@

foreach ($item in $models) {
    Write-Host "Provisioning $($item.name) at $($item.revision)..."
    & $speechPython -c $script $item.repo $item.revision
    if ($LASTEXITCODE -ne 0) {
        throw "下載 $($item.name) 失敗。請確認網路、Hugging Face 權限與模型授權。"
    }
}

Write-Host 'Speech model provisioning complete. Model files remain outside Git.'
Write-Host 'MMS-TTS license: CC-BY-NC-4.0 (non-commercial use; review before deployment).'
