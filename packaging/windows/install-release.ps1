[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ManifestSha256,
    [switch]$Rehearsal
)
$ErrorActionPreference = 'Stop'
$manifest = Join-Path $PSScriptRoot 'bundle.json'
if ((Get-FileHash -LiteralPath $manifest).Hash -ne $ManifestSha256) { throw 'Bundle manifest hash mismatch.' }
$release = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
$base = [Environment]::GetFolderPath('LocalApplicationData')
$name = if ($Rehearsal) { 'StylusJarvis-Rehearsal' } else { 'StylusJarvis' }
$dest = Join-Path $base $name
if (Test-Path -LiteralPath $dest) { throw "Destination already exists: $dest. Use a fresh profile or follow the offline rollback procedure." }
$wheels = @(foreach ($entry in $release.files.PSObject.Properties) {
    $file = Join-Path $PSScriptRoot $entry.Name
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.Value) { throw "Digest mismatch: $file" }
    if ($entry.Name -like 'wheels/*.whl') { $file }
})
if (-not $wheels.Count) { throw 'Bundle contains no wheels.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stage = Join-Path $base ($name + '-stage-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path $stage
[IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $PSScriptRoot 'runtime.zip'), (Join-Path $stage 'runtime'))
[IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $PSScriptRoot 'assets.zip'), (Join-Path $stage 'assets\m0-v1'))
# pip launchers embed the absolute Python path. Install only after publishing the final directory.
[IO.Directory]::Move($stage, $dest)
try {
    $python = Join-Path $dest 'runtime\python\python.exe'
    $previousConfig = $env:PIP_CONFIG_FILE
    try {
        $env:PIP_CONFIG_FILE = 'NUL'
        # The unpacked private CPython retains uv's externally-managed marker.
        & $python -I -B -m pip --isolated --disable-pip-version-check install --break-system-packages --no-index --no-deps --no-compile --no-cache-dir @wheels
        if ($LASTEXITCODE) { throw 'Offline wheel installation failed.' }
        & $python -I -B -m pip --isolated --disable-pip-version-check check
        if ($LASTEXITCODE) { throw 'Installed dependency versions are inconsistent.' }
    } finally { $env:PIP_CONFIG_FILE = $previousConfig }
    Copy-Item -LiteralPath $manifest -Destination (Join-Path $dest 'bundle.json')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launch-release.ps1') -Destination $dest
} catch {
    [IO.Directory]::Move($dest, $stage)
    throw
}
Write-Output "Installed $($release.build) to $dest"
