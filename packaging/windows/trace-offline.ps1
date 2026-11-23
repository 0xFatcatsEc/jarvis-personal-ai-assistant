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
    $interfaces = @(Get-NetIPInterface)
    $routeStates = @(foreach ($route in $routes) {
        $match = @($interfaces | Where-Object {
            $_.InterfaceIndex -eq $route.InterfaceIndex -and $_.AddressFamily -eq $route.AddressFamily
        })
        $state = if ($match.Count -eq 1) { [string]$match[0].ConnectionState } else { 'Unknown' }
        @{index=$route.InterfaceIndex; family=[string]$route.AddressFamily; state=$state}
    })
    return [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        bootUtc = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
        bootRecord = $boot.RecordId
        bootEventUtc = $boot.TimeCreated.ToUniversalTime().ToString('o')
        bootType = [int]$boot.Properties[0].Value
        internet = [bool]@($net | Where-Object { $_.IPv4Connectivity -eq 'Internet' -or $_.IPv6Connectivity -eq 'Internet' }).Count
        physicalLinks = $adapters.Count
        defaultRoutes = $routes.Count
        routeInterfaces = $routeStates
        profiles = $net.Count
    }
}
if ($Action -eq 'Arm') {
    if (Test-Path -LiteralPath $dir) { throw 'Choose a fresh RunId for each capture.' }
    $null = New-Item -ItemType Directory -Path $dir -Force
    $snapshot = Snapshot
    $runtime = (Get-Item -LiteralPath (Join-Path $profileRoot 'runtime')).FullName
    Save-Json ([ordered]@{mode=$Mode; run=$RunId; machine=$env:COMPUTERNAME; before=$snapshot; runtime=$runtime; collector='wpr-boot-v1'}) 'arm.json'
    $start = if ($Mode -eq 'Rehearsal') { '-start' } else { '-addboot' }
    $profile = (Join-Path $PSScriptRoot 'offline-trace.wprp') + '!StylusOffline'
    & wpr.exe $start $profile -filemode -recordtempto $dir -instancename $name
    if ($LASTEXITCODE) { throw 'Could not arm the ETW session.' }
    if ($Mode -ne 'Rehearsal') {
        try {
            $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\WMI\Autologger'
            $sources = @(Get-ChildItem -LiteralPath $key | Where-Object PSChildName -like ('WPR_initiated_' + $name + '_boottr_*') |
                ForEach-Object {
                    $config = Get-ItemProperty -LiteralPath $_.PSPath
                    if ($config.Start -ne 1 -or (Split-Path -Parent $config.FileName) -ne $dir) {
                        throw 'Boot logger is disabled or points outside the run directory.'
                    }
                    @{name=$_.PSChildName; file=$config.FileName}
                })
            if ($sources.Count -lt 2) { throw 'Boot logger registrations are incomplete.' }
            Save-Json $sources 'boot-sources.json'
        } catch {
            & wpr.exe -cancelboot -instancename $name
            throw
        }
    }
    return
}
$arm = Get-Content -LiteralPath (Join-Path $dir 'arm.json') -Raw | ConvertFrom-Json
if ($arm.mode -ne $Mode -or $arm.run -ne $RunId -or $arm.machine -ne $env:COMPUTERNAME) { throw 'Journal mismatch.' }
if ($Action -eq 'Run') {
    if (Test-Path -LiteralPath (Join-Path $dir 'workload.json')) { throw 'This run already has a workload journal.' }
    # Creation time prevents a snapshot from assigning earlier events to a recycled PID.
    Save-Processes 'processes.json'
    $before = Snapshot
    Save-Json $before 'before-workload.json'
    if ($Mode -ne 'Rehearsal') {
        if ($before.bootType -ne 0 -or $before.bootRecord -eq $arm.before.bootRecord) {
            throw 'Run requires a fresh full boot after Arm.'
        }
        if ($Mode -eq 'Disconnected' -and ($before.internet -or $before.profiles -or $before.physicalLinks -or
            @($before.routeInterfaces | Where-Object state -ne 'Disconnected').Count)) {
            throw 'A network path is active or unknown. Inspect before-workload.json before proceeding.'
        }
        if ($Mode -eq 'Connected' -and (-not $before.internet -or
            -not @($before.routeInterfaces | Where-Object state -eq 'Connected').Count)) {
            throw 'Windows has not confirmed internet connectivity on a connected route.'
        }
        if ($arm.collector -eq 'wpr-boot-v1') {
            foreach ($source in (Get-Content -LiteralPath (Join-Path $dir 'boot-sources.json') -Raw | ConvertFrom-Json)) {
                if (-not (Test-Path -LiteralPath $source.file -PathType Leaf)) {
                    throw "Boot capture file missing for $($source.name). Stop and inspect this run."
                }
            }
        }
    }
    $env:PYTHONPATH = (Join-Path $repo 'src') + ';' + (Join-Path $repo '.venv\Lib\site-packages')
    & (Join-Path $repo '.venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'trace_workload.py') $dir
    $result = $LASTEXITCODE
    Save-Json (Snapshot) 'after-workload.json'
    if ($result) { throw 'The measured desktop workload failed.' }
    return
}
if (-not (Test-Path -LiteralPath (Join-Path $dir 'stopped.json'))) {
    if ($arm.collector -eq 'wpr-boot-v1') {
        if ($Action -eq 'Stop' -and $Mode -ne 'Rehearsal' -and (Snapshot).bootRecord -eq $arm.before.bootRecord) {
            & wpr.exe -cancelboot -instancename $name
            if ($LASTEXITCODE) { throw 'Unable to cancel the named boot recording.' }
            Save-Json (Snapshot) 'stopped.json'
            return
        }
        # Read source counters before WPR merges the sessions into one ETL.
        $losses = @(Get-CimInstance Win32_PerfRawData_Counters_EventTracingforWindowsSession -ErrorAction SilentlyContinue |
            Where-Object Name -like ('WPR_initiated_' + $name + '_*') | Select-Object Name, EventsLost)
        Save-Json @{sessions=$losses} 'source-loss.json'
        $stop = if ($Mode -eq 'Rehearsal') { '-stop' } else { '-stopboot' }
        & wpr.exe $stop $etl -skipPdbGen -instancename $name
    } else {
        & netsh.exe trace stop "sessionname=$name"
    }
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
