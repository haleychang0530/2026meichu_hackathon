[CmdletBinding()]
param(
    [string]$BaseUrl = $env:VLM_BASE_URL,
    [string]$ImagePath,
    [string]$ModelRevision = 'd9748a51ae66354c4dad665aab2c71f26cf2c8cd',
    [ValidateRange(1, 300)]
    [int]$TimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'

function Resolve-GatewayOrigin([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw 'BaseUrl 未設定；請傳入當次 Manta 8100/tcp forwarding 的外部 origin。'
    }
    $candidate = $Value.Trim().TrimEnd('/')
    $uri = $null
    if (-not [Uri]::TryCreate($candidate, [UriKind]::Absolute, [ref]$uri)) {
        throw "BaseUrl 必須是完整的 HTTP(S) origin：$candidate"
    }
    if ($uri.Scheme -notin @('http', 'https') -or -not $uri.Host) {
        throw "BaseUrl 必須是完整的 HTTP(S) origin：$candidate"
    }
    if ($uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {
        throw "BaseUrl 不得包含 credentials、path、query 或 fragment：$candidate"
    }
    return $candidate
}

$gatewayOrigin = Resolve-GatewayOrigin $BaseUrl
$healthRequestId = [Guid]::NewGuid().ToString()
$health = Invoke-RestMethod `
    -Method Get `
    -Uri "$gatewayOrigin/internal/health" `
    -Headers @{ 'X-Request-ID' = $healthRequestId } `
    -TimeoutSec $TimeoutSeconds

$result = [ordered]@{
    gateway_origin = $gatewayOrigin
    health = [ordered]@{
        request_id = $healthRequestId
        status = $health.status
        service = $health.service
        model_revision = $health.model_revision
        queue_depth = $health.queue_depth
    }
}

if ($ImagePath) {
    $resolvedImage = (Resolve-Path -LiteralPath $ImagePath).Path
    $extension = [IO.Path]::GetExtension($resolvedImage).ToLowerInvariant()
    $mediaType = switch ($extension) {
        '.jpg' { 'image/jpeg' }
        '.jpeg' { 'image/jpeg' }
        '.png' { 'image/png' }
        '.webp' { 'image/webp' }
        default { throw 'ImagePath 必須是 JPEG、PNG 或 WebP。' }
    }
    $generateRequestId = [Guid]::NewGuid().ToString()
    $schema = [ordered]@{
        '$schema' = 'https://json-schema.org/draft/2020-12/schema'
        title = 'MantaForwardingSmoke'
        type = 'object'
        additionalProperties = $false
        required = @('summary')
        properties = [ordered]@{
            summary = @{ type = 'string'; minLength = 1; maxLength = 200 }
        }
    }
    $payload = [ordered]@{
        schema_version = '0.1.0'
        request_id = $generateRequestId
        image = [ordered]@{
            media_type = $mediaType
            content_base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($resolvedImage))
        }
        prompt = '請用一句話描述圖片，僅回傳符合 JSON Schema 的 summary，不要輸出 Markdown。'
        response_schema = $schema
        model_revision = $ModelRevision
    }
    $generate = Invoke-RestMethod `
        -Method Post `
        -Uri "$gatewayOrigin/internal/vlm/generate" `
        -Headers @{ 'X-Request-ID' = $generateRequestId } `
        -ContentType 'application/json' `
        -Body ($payload | ConvertTo-Json -Depth 12 -Compress) `
        -TimeoutSec ([Math]::Max($TimeoutSeconds, 120))
    $result.generate = [ordered]@{
        request_id = $generate.request_id
        model_revision = $generate.model_revision
        finish_reason = $generate.output.finish_reason
        latency_ms = $generate.latency_ms
        queue_ms = $generate.queue_ms
        inference_ms = $generate.inference_ms
        candidate = $generate.output.parsed_candidate
    }
}

# The output intentionally excludes image bytes, prompt text, and raw model output.
[pscustomobject]$result | ConvertTo-Json -Depth 8
