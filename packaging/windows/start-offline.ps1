[CmdletBinding()]
param(
    [ValidateSet('Desktop', 'Model')][string]$Component = 'Desktop'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$profileRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'StylusJarvis'
$python = (Get-Item -LiteralPath (Join-Path $profileRoot 'runtime\python\python.exe')).FullName
$packages = (Get-Item -LiteralPath (Join-Path $repo '.venv\Lib\site-packages')).FullName
$previousPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$(Join-Path $repo 'src');$packages"
    if ($Component -eq 'Model') {
        $endpoint = @(& $python -B -P -s -c 'from stylus_jarvis.settings import load, profile_path; s, _ = load(profile_path()); print(s.host, s.port, sep=chr(10))')
        if ($LASTEXITCODE -ne 0 -or $endpoint.Count -ne 2) { throw 'Could not read the validated model endpoint.' }
        $policy = Join-Path $repo 'src\stylus_jarvis\runtime\offline-policy.ps1'
        & $policy -Mode Serve -PythonImage $python -ListenAddress $endpoint[0] -Port $endpoint[1]
    } else {
        & $python -B -P -s -m stylus_jarvis
    }
    exit $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPath
}
