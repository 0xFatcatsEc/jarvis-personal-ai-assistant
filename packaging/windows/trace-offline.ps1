[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Arm','Run','Finish','Stop')][string]$Action,
    [Parameter(Mandatory)][ValidateSet('Disconnected','Connected','Rehearsal')][string]$Mode,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_-]{1,48}$')][string]$RunId
)
$ErrorActionPreference = 'Stop'
$profileRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'StylusJarvis'
$dir = Join-Path $profileRoot "traces\$RunId"
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$name = "StylusTrace-$RunId"
$etl = Join-Path $dir 'traffic.etl'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Action -eq 'Run' -and $admin) { throw 'Run the desktop workload as the ordinary desktop user.' }
if ($Action -ne 'Run' -and -not $admin) { throw 'The trace controller requires elevated Windows PowerShell.' }
function Save-Json($Object,[string]$File) {
    $Object | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $dir $File)
}
function Save-Processes([string]$File) {
    $rows = @(Get-CimInstance Win32_Process | Where-Object CreationDate | ForEach-Object {
        @{pid=$_.ProcessId; parent=$_.ParentProcessId; created=$_.CreationDate.ToUniversalTime().ToString('o'); image=$_.ExecutablePath}
    })
    Save-Json $rows $File
}
function Snapshot {
    $boot = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Boot'; Id=27} -MaxEvents 1
    $net = @(Get-NetConnectionProfile)
    $adapters = @(Get-NetAdapter -IncludeHidden | Where-Object { $_.Status -eq 'Up' -and $_.HardwareInterface })
    $routes = @(Get-NetRoute | Where-Object DestinationPrefix -in @('0.0.0.0/0','::/0'))
    return [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        bootUtc = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
        bootRecord = $boot.RecordId
        bootEventUtc = $boot.TimeCreated.ToUniversalTime().ToString('o')
        bootType = [int]$boot.Properties[0].Value
        internet = [bool]@($net | Where-Object { $_.IPv4Connectivity -eq 'Internet' -or $_.IPv6Connectivity -eq 'Internet' }).Count
        physicalLinks = $adapters.Count
        defaultRoutes = $routes.Count
        profiles = $net.Count
    }
}
if ($Action -eq 'Arm') {
    if (Test-Path -LiteralPath $dir) { throw 'Choose a fresh RunId for each capture.' }
    $null = New-Item -ItemType Directory -Path $dir -Force
    $snapshot = Snapshot
    $runtime = (Get-Item -LiteralPath (Join-Path $profileRoot 'runtime')).FullName
    Save-Json ([ordered]@{mode=$Mode; run=$RunId; machine=$env:COMPUTERNAME; before=$snapshot; runtime=$runtime}) 'arm.json'
    $persistent = if ($Mode -eq 'Rehearsal') { 'no' } else { 'yes' }
    & netsh.exe trace start "sessionname=$name" "persistent=$persistent" "tracefile=$etl" filemode=append maxsize=512 capture=no report=disabled perfmerge=no correlation=disabled overwrite=no provider=Microsoft-Windows-Kernel-Process keywords=0x10 provider=Microsoft-Windows-Kernel-Network provider=Microsoft-Windows-Winsock-AFD provider=Microsoft-Windows-DNS-Client
    if ($LASTEXITCODE) { throw 'Could not arm the ETW session.' }
    return
}
$arm = Get-Content -LiteralPath (Join-Path $dir 'arm.json') -Raw | ConvertFrom-Json
if ($arm.mode -ne $Mode -or $arm.run -ne $RunId -or $arm.machine -ne $env:COMPUTERNAME) { throw 'Journal mismatch.' }
if ($Action -eq 'Run') {
    if (Test-Path -LiteralPath (Join-Path $dir 'workload.json')) { throw 'This run already has a workload journal.' }
    # Creation time prevents a snapshot from assigning earlier events to a recycled PID.
    Save-Processes 'processes.json'
    Save-Json (Snapshot) 'before-workload.json'
    $env:PYTHONPATH = (Join-Path $repo 'src') + ';' + (Join-Path $repo '.venv\Lib\site-packages')
    & (Join-Path $repo '.venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'trace_workload.py') $dir
    $result = $LASTEXITCODE
    Save-Json (Snapshot) 'after-workload.json'
    if ($result) { throw 'The measured desktop workload failed.' }
    return
}
if (-not (Test-Path -LiteralPath (Join-Path $dir 'stopped.json'))) {
    & netsh.exe trace stop "sessionname=$name"
    if ($LASTEXITCODE) { throw 'Unable to stop the named session.' }
    Save-Json (Snapshot) 'stopped.json'
}
if ($Action -eq 'Stop') { return }
if (-not (Test-Path -LiteralPath (Join-Path $dir 'processes-final.json'))) {
    Save-Processes 'processes-final.json'
}
$measured = Get-Content -Raw -LiteralPath (Join-Path $dir 'before-workload.json') | ConvertFrom-Json
$bootTime = [DateTimeOffset]::Parse($measured.bootUtc).LocalDateTime
$channel = 'Microsoft-Windows-NetworkProfile/Operational'
if (-not (Get-WinEvent -ListLog $channel).IsEnabled) { throw 'Network profile history is disabled.' }
$changes = @(Get-WinEvent -FilterHashtable @{LogName=$channel; StartTime=$bootTime; Id=@(10000,10001)} -ErrorAction SilentlyContinue -ErrorVariable profileErrors | ForEach-Object {
    @{id=$_.Id; utc=$_.TimeCreated.ToUniversalTime().ToString('o')}
})
foreach ($err in $profileErrors) { if ($err.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { throw $err } }
Save-Json @{events=$changes} 'network-history.json'
& tracerpt.exe $etl -of XML -gmt -o (Join-Path $dir 'events.xml') -summary (Join-Path $dir 'summary.txt') -y
if ($LASTEXITCODE) { throw 'ETL conversion failed. Preserve the original ETL.' }
& (Join-Path $repo '.venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'trace_report.py') $dir
exit $LASTEXITCODE
