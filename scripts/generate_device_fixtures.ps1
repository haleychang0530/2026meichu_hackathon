[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot 'fixtures\device'
}
$audioDirectory = Join-Path $OutputDirectory 'audio'
$imageDirectory = Join-Path $OutputDirectory 'lesson-images'
New-Item -ItemType Directory -Path $audioDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $imageDirectory -Force | Out-Null

function Write-SyntheticWav {
    param(
        [string]$Path,
        [double]$DurationSeconds,
        [int]$SampleRate,
        [scriptblock]$SampleFunction
    )
    $sampleCount = [int]($DurationSeconds * $SampleRate)
    $dataLength = $sampleCount * 2
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $writer = New-Object System.IO.BinaryWriter($stream)
    try {
        $ascii = [System.Text.Encoding]::ASCII
        $writer.Write($ascii.GetBytes('RIFF'))
        $writer.Write([int](36 + $dataLength))
        $writer.Write($ascii.GetBytes('WAVE'))
        $writer.Write($ascii.GetBytes('fmt '))
        $writer.Write([int]16)
        $writer.Write([short]1)
        $writer.Write([short]1)
        $writer.Write([int]$SampleRate)
        $writer.Write([int]($SampleRate * 2))
        $writer.Write([short]2)
        $writer.Write([short]16)
        $writer.Write($ascii.GetBytes('data'))
        $writer.Write([int]$dataLength)
        for ($sampleIndex = 0; $sampleIndex -lt $sampleCount; $sampleIndex++) {
            $time = $sampleIndex / $SampleRate
            $normalized = [double](& $SampleFunction $time)
            $normalized = [math]::Max(-1.0, [math]::Min(1.0, $normalized))
            $writer.Write([short]([math]::Round($normalized * 32767)))
        }
    } finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}

# These are deterministic transport/playback fixtures, not speech goldens. Their
# neutral names and generated waveforms keep them free of personal data.
Write-SyntheticWav (Join-Path $audioDirectory 'synthetic-prompt.wav') 1.2 16000 {
    param($t)
    $envelope = [math]::Min(1.0, $t * 20) * [math]::Min(1.0, (1.2 - $t) * 20)
    $tone = if ($t -lt 0.6) { 440 } else { 660 }
    0.22 * $envelope * [math]::Sin(2 * [math]::PI * $tone * $t)
}
Write-SyntheticWav (Join-Path $audioDirectory 'synthetic-response.wav') 1.8 16000 {
    param($t)
    $envelope = [math]::Min(1.0, $t * 18) * [math]::Min(1.0, (1.8 - $t) * 18)
    $tone = if ($t -lt 0.6) { 523.25 } elseif ($t -lt 1.2) { 659.25 } else { 783.99 }
    0.22 * $envelope * [math]::Sin(2 * [math]::PI * $tone * $t)
}
Write-SyntheticWav (Join-Path $audioDirectory 'synthetic-fallback.wav') 0.9 16000 {
    param($t)
    $pulse = if (([math]::Floor($t * 6) % 2) -eq 0) { 1.0 } else { 0.2 }
    $envelope = [math]::Min(1.0, $t * 25) * [math]::Min(1.0, (0.9 - $t) * 25)
    0.18 * $pulse * $envelope * [math]::Sin(2 * [math]::PI * 330 * $t)
}

$files = @()
Get-ChildItem -LiteralPath $OutputDirectory -Recurse -File | Where-Object {
    $_.FullName -match '(?i)[\\/]audio[\\/]|[\\/]lesson-images[\\/]'
} | Sort-Object FullName | ForEach-Object {
    $relativePath = $_.FullName.Substring($repoRoot.Length + 1).Replace('\', '/')
    $kind = if ($_.Extension -ieq '.wav') { 'audio' } elseif ($_.Extension -ieq '.svg') { 'image' } else { 'other' }
    $files += [ordered]@{
        path = $relativePath
        kind = $kind
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$manifest = [ordered]@{
    schema_version = 'device-fixtures.v1'
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    privacy = 'Synthetic audio and geometric educational illustrations only; no names, faces or identifiable data.'
    audio_note = 'Waveforms are transport/playback fixtures. Do not use them as ASR semantic accuracy goldens.'
    files = $files
}
$manifestPath = Join-Path $OutputDirectory 'manifest.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Output "Generated fixture manifest: $manifestPath"
