param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [Parameter(Mandatory = $true)]
    [string]$TagName,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseName,
    [Parameter(Mandatory = $true)]
    [string]$AssetPath
)

$ErrorActionPreference = "Stop"

if (-not $env:GITHUB_TOKEN) {
    throw "The GITHUB_TOKEN environment variable is required."
}

if (-not (Test-Path $AssetPath)) {
    throw "Release asset was not found: $AssetPath"
}

$apiHeaders = @{
    Authorization           = "Bearer $env:GITHUB_TOKEN"
    Accept                  = "application/vnd.github+json"
    "X-GitHub-Api-Version"  = "2022-11-28"
    "User-Agent"            = "NetOpsToolkit-Release"
}

function Invoke-GitHubRest {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST", "DELETE")]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [object]$Body = $null
    )

    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 10
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $apiHeaders -Body $json -ContentType "application/json"
    }

    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $apiHeaders
}

$releaseApi = "https://api.github.com/repos/$Repository/releases/tags/$TagName"
$release = $null

try {
    $release = Invoke-GitHubRest -Method GET -Uri $releaseApi
}
catch {
    $response = $_.Exception.Response
    $statusCode = $null
    if ($response) {
        $statusCode = [int]$response.StatusCode
    }

    if ($statusCode -ne 404) {
        throw
    }
}

if (-not $release) {
    $release = Invoke-GitHubRest -Method POST -Uri "https://api.github.com/repos/$Repository/releases" -Body @{
        tag_name              = $TagName
        name                  = $ReleaseName
        draft                 = $false
        prerelease            = $false
        generate_release_notes = $true
    }
}

$assetName = Split-Path -Path $AssetPath -Leaf
$existingAsset = @($release.assets | Where-Object { $_.name -eq $assetName }) | Select-Object -First 1
if ($existingAsset) {
    Invoke-GitHubRest -Method DELETE -Uri "https://api.github.com/repos/$Repository/releases/assets/$($existingAsset.id)" | Out-Null
}

$uploadUrl = ($release.upload_url -replace "\{.*$", "")
$escapedAssetName = [System.Uri]::EscapeDataString($assetName)
$uploadUri = "$uploadUrl?name=$escapedAssetName"

Invoke-RestMethod `
    -Method POST `
    -Uri $uploadUri `
    -Headers $apiHeaders `
    -InFile $AssetPath `
    -ContentType "application/octet-stream" | Out-Null

Write-Host "Uploaded release asset: $assetName"
