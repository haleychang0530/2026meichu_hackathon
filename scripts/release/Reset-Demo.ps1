[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRoot = Join-Path $repoRoot 'apps\core-api\.runtime\stage10-demo'
$coreDataRoot = Join-Path $runtimeRoot 'core-data'
$ragRoot = Join-Path $runtimeRoot 'rag-indexes'
$audioRoot = Join-Path $runtimeRoot 'audio-cache'

& (Join-Path $PSScriptRoot 'Stop-Demo.ps1') -KeepRuntime
foreach ($target in @($coreDataRoot, $ragRoot, $audioRoot)) {
    if (Test-Path -LiteralPath $target) {
        $resolved = (Resolve-Path -LiteralPath $target).Path
        if (-not $resolved.StartsWith($runtimeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to reset path outside Stage 10 runtime: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
        Write-Host "Cleared $resolved"
    }
}
Write-Host 'Stage 10 demo state reset. Logs and reports were retained.'
