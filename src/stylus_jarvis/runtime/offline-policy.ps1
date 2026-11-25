[CmdletBinding()]
param(
    [ValidateSet('CheckApp', 'Verify', 'Install', 'Serve')][string]$Mode = 'Verify',
    [Parameter(Mandatory)][string]$PythonImage,
    [ipaddress]$ListenAddress = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 11434
)

$ErrorActionPreference = 'Stop'
if (-not [ipaddress]::IsLoopback($ListenAddress)) { throw 'The listener must be loopback.' }
$profileRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'StylusJarvis'
$rehearsalRoot = "$profileRoot-Rehearsal"
if ([IO.Path]::GetFullPath($PythonImage) -eq (Join-Path $rehearsalRoot 'runtime\python\python.exe')) {
    $profileRoot = $rehearsalRoot
}
$runtime = Join-Path $profileRoot 'runtime\ollama'
$python = (Get-Item -LiteralPath $PythonImage).FullName
if ($python -ne (Join-Path $profileRoot 'runtime\python\python.exe')) {
    throw 'Start the dedicated STYLUS JARVIS Python image from the offline profile.'
}
$images = @($python)
if ($Mode -ne 'CheckApp') {
    $server = (Get-Item -LiteralPath (Join-Path $runtime 'ollama.exe')).FullName
    $null = Get-Item -LiteralPath (Join-Path $runtime 'lib\ollama\llama-server.exe')
    $images += @(Get-ChildItem -LiteralPath $runtime -Recurse -File -Filter '*.exe' |
        ForEach-Object { $_.FullName })
    if (Test-Path -LiteralPath (Join-Path $runtime 'ollama app.exe')) {
        throw 'Use the private headless server directory without the tray application/updater.'
    }
}
$remote = @('0.0.0.0-126.255.255.255', '128.0.0.0-255.255.255.255', '::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')

function Get-RuleName([string]$Image) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Image.ToLowerInvariant()))
        return 'StylusJarvis-Offline-' + [BitConverter]::ToString($hash).Replace('-', '')
    } finally { $sha.Dispose() }
}

function Assert-ProgramRule([string]$Image) {
    $name = Get-RuleName $Image
    $rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $name
    $app = $rule | Get-NetFirewallApplicationFilter
    $addr = $rule | Get-NetFirewallAddressFilter
    $ports = $rule | Get-NetFirewallPortFilter
    $interfaces = $rule | Get-NetFirewallInterfaceFilter
    $types = $rule | Get-NetFirewallInterfaceTypeFilter
    $service = $rule | Get-NetFirewallServiceFilter
    $security = $rule | Get-NetFirewallSecurityFilter
    if ($rule.Enabled -ne 'True' -or $rule.Action -ne 'Block' -or $rule.Direction -ne 'Outbound' -or
        $rule.Profile -ne 'Any' -or $rule.PrimaryStatus -ne 'OK' -or $app.Program -ne $Image -or
        @($rule.EnforcementStatus | Where-Object { $_ -notin @('Enforced','Full','ProfileInactive') }).Count -or
        $app.PolicyAppId -or $rule.Platform.Count -or
        $app.Package -notin @($null, '', 'Any') -or (Compare-Object $remote @($addr.RemoteAddress)) -or
        (@($addr.LocalAddress) -join ',') -ne 'Any' -or $ports.Protocol -ne 'Any' -or
        (@($ports.LocalPort) -join ',') -ne 'Any' -or (@($ports.RemotePort) -join ',') -ne 'Any' -or
        (@($interfaces.InterfaceAlias) -join ',') -ne 'Any' -or $types.InterfaceType -ne 'Any' -or
        $service.Service -ne 'Any' -or $security.LocalUser -ne 'Any' -or
        $security.RemoteUser -ne 'Any' -or $security.RemoteMachine -ne 'Any' -or
        $security.Authentication -ne 'NotRequired' -or $security.Encryption -ne 'NotRequired') {
        throw "Incomplete effective outbound rule for $Image"
    }
}

$profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
if ($profiles.Count -ne 3 -or @($profiles | Where-Object { $_.Enabled -ne 'True' -or $_.DisabledInterfaceAliases -notin @($null, '', 'NotConfigured') }).Count) {
    throw 'Windows Firewall must cover all profiles and interfaces.'
}
foreach ($image in $images) {
    $ruleName = Get-RuleName $image
    if ($Mode -eq 'Install' -and -not (Get-NetFirewallRule -PolicyStore PersistentStore -Name $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name $ruleName -DisplayName "STYLUS JARVIS offline - $image" -Group 'STYLUS JARVIS offline' -Program $image -Direction Outbound -Action Block -Profile Any -RemoteAddress $remote | Out-Null
    }
    Assert-ProgramRule $image
}

if ($Mode -in @('Verify', 'Serve')) {
    $listeners = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq $Port })
    if (@($listeners | Where-Object { -not [ipaddress]::IsLoopback([ipaddress]$_.LocalAddress) }).Count) {
        throw 'A non-loopback listener is bound to the model port.'
    }
    $matches = @($listeners | Where-Object { $_.LocalAddress -eq $ListenAddress.IPAddressToString })
    if ($Mode -eq 'Verify' -and $matches.Count -eq 0) {
        Write-Error 'The guarded model endpoint is not listening.' -ErrorAction Continue
        exit 22
    }
    if ($matches.Count -gt 0) {
        $guarded = $matches.Count -eq 1 -and (Get-Process -Id $matches[0].OwningProcess).Path -eq $server
        if (-not $guarded) {
            Write-Error ("Another program owns the configured model endpoint on port $Port. Use a free loopback port " +
                'in the STYLUS JARVIS settings, then launch the guarded model and restart the desktop.') -ErrorAction Continue
            exit 21
        }
        if ($Mode -eq 'Serve') {
            Write-Output "The guarded model server is already listening on port $Port."
            exit 0
        }
    }
}
if ($Mode -eq 'Serve') {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $server
    $start.Arguments = 'serve'
    $start.UseShellExecute = $false
    $start.WorkingDirectory = $runtime
    $start.EnvironmentVariables.Clear()
    foreach ($key in @('SYSTEMROOT','WINDIR','TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE','PROGRAMDATA')) {
        $start.EnvironmentVariables[$key] = [Environment]::GetEnvironmentVariable($key)
    }
    $start.EnvironmentVariables['PATH'] = "$runtime;$env:SystemRoot\System32"
    $start.EnvironmentVariables['OLLAMA_HOST'] = ([Net.IPEndPoint]::new($ListenAddress, $Port)).ToString()
    $start.EnvironmentVariables['OLLAMA_NO_CLOUD'] = '1'
    $start.EnvironmentVariables['OLLAMA_MODELS'] = (Get-Item -LiteralPath (Join-Path $profileRoot 'assets\m0-v1\ollama\models')).FullName
    $start.EnvironmentVariables['OLLAMA_NOPRUNE'] = '1'
    $process = [Diagnostics.Process]::Start($start)
    try {
        $process.WaitForExit()
        exit $process.ExitCode
    } finally {
        if (-not $process.HasExited) {
            & (Join-Path ([Environment]::SystemDirectory) 'taskkill.exe') /PID $process.Id /T /F | Out-Null
        }
        $process.Dispose()
    }
}
