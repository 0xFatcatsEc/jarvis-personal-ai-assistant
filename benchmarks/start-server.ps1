[CmdletBinding()]
param()

# Start a separate loopback service and model store for qualification only.
$ErrorActionPreference = 'Stop'
$ollama = Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
if (-not (Test-Path -LiteralPath $ollama -PathType Leaf)) {
    throw 'Install the staged OllamaSetup-0.40.17.exe as described in benchmarks/README.md.'
}
$source = Join-Path $env:LOCALAPPDATA 'StylusJarvis/assets/m0-v1/ollama/models'
$target = Join-Path $env:LOCALAPPDATA 'StylusJarvis/qualification/models'
$lock = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot '../packaging/windows/m0-assets.json') | ConvertFrom-Json
foreach ($asset in $lock.assets) {
    if (-not $asset.path.StartsWith('ollama/models/')) { continue }
    $relative = $asset.path.Substring('ollama/models/'.Length)
    $dest = Join-Path $target $relative
    if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) {
        New-Item -Force -ItemType Directory -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item -LiteralPath (Join-Path $source $relative) -Destination $dest
    }
    if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -ne $asset.sha256) {
        throw "Invalid staged benchmark copy at $dest"
    }
}
$env:OLLAMA_HOST = '127.0.0.1:11435'
$env:OLLAMA_MODELS = $target
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
& $ollama serve
exit $LASTEXITCODE
