$ErrorActionPreference = 'Stop'

$ExtensionRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$DistPath = Join-Path $ExtensionRoot 'dist'
$ManifestPath = Join-Path $ExtensionRoot 'manifest.json'
$CreateIconsScript = Join-Path $PSScriptRoot 'create-icons.ps1'

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "extension/manifest.json was not found."
}

& $CreateIconsScript

$Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
if ($Manifest.manifest_version -ne 3) {
    throw "manifest.json must use Manifest V3."
}
if (-not $Manifest.browser_specific_settings.gecko.id) {
    throw "manifest.json must define a stable Gecko add-on ID."
}

$WebExt = Get-Command web-ext -ErrorAction SilentlyContinue
if (-not $WebExt) {
    throw "web-ext was not found on PATH. Install it with npm before building the extension."
}

& $WebExt.Source lint --source-dir $ExtensionRoot
if ($LASTEXITCODE -ne 0) {
    throw "web-ext lint failed."
}

$ResolvedRoot = (Resolve-Path $ExtensionRoot).Path.TrimEnd('\') + '\'
$ResolvedDist = [System.IO.Path]::GetFullPath($DistPath).TrimEnd('\') + '\'
if (-not $ResolvedDist.StartsWith($ResolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clear a dist path outside the extension directory."
}

if (Test-Path -LiteralPath $DistPath) {
    Remove-Item -LiteralPath $DistPath -Recurse -Force
}
New-Item -ItemType Directory -Path $DistPath | Out-Null

& $WebExt.Source build --source-dir $ExtensionRoot --artifacts-dir $DistPath
if ($LASTEXITCODE -ne 0) {
    throw "web-ext build failed."
}

Get-ChildItem -LiteralPath $DistPath -Filter '*.zip' | Select-Object -ExpandProperty FullName
