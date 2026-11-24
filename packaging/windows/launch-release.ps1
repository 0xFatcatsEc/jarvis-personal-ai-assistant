[CmdletBinding()]
param([ValidateSet('Desktop','Model','InstallRules')][string]$Component = 'Desktop')
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot 'runtime\python\python.exe'
$policy = Join-Path $PSScriptRoot 'runtime\python\Lib\site-packages\stylus_jarvis\runtime\offline-policy.ps1'
if ($Component -eq 'InstallRules') {
    & $policy -Mode Install -PythonImage $python
} elseif ($Component -eq 'Model') {
    $endpoint = @(& $python -I -B -c 'from stylus_jarvis.settings import load, profile_path; s, _ = load(profile_path()); print(s.host, s.port, sep=chr(10))')
    if ($LASTEXITCODE -or $endpoint.Count -ne 2) { throw 'Invalid model endpoint.' }
    & $policy -Mode Serve -PythonImage $python -ListenAddress $endpoint[0] -Port $endpoint[1]
} else {
    & $python -I -B -m stylus_jarvis
    exit $LASTEXITCODE
}
