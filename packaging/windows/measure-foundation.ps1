[CmdletBinding()]
param()

# Emit only hardware and power characteristics used to interpret M0 timings.
$ErrorActionPreference = 'Stop'
$computer = Get-CimInstance Win32_ComputerSystem
$processor = Get-CimInstance Win32_Processor | Select-Object -First 1
$os = Get-CimInstance Win32_OperatingSystem
$drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($os.SystemDrive)'"
$adapters = @(Get-CimInstance Win32_VideoController | ForEach-Object {
    [ordered]@{
        name = $_.Name
        windows_driver = $_.DriverVersion
    }
})
# Win32_VideoController.AdapterRAM is a 32-bit field and can truncate VRAM.
$nvidia = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
$graphics = @()
if ($nvidia) {
    $metrics = & $nvidia.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits
    if ($LASTEXITCODE -ne 0) { throw 'NVIDIA dedicated-memory query failed.' }
    $graphics = @($metrics | ConvertFrom-Csv -Header Name,MiB,Driver | ForEach-Object {
        [ordered]@{ name = $_.Name.Trim(); dedicated_mib = [int]$_.MiB; driver = $_.Driver.Trim() }
    })
}
# GetSystemPowerStatus reports AC attachment independently of battery charge.
Add-Type -Namespace StylusInventory -Name Power -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError=true)]
public static extern bool GetSystemPowerStatus(out Status status);
[System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
public struct Status {
    public byte ACLineStatus, BatteryFlag, BatteryLifePercent, SystemStatusFlag;
    public uint BatteryLifeTime, BatteryFullLifeTime;
}
'@ -ErrorAction Stop
$power = New-Object StylusInventory.Power+Status
if (-not [StylusInventory.Power]::GetSystemPowerStatus([ref]$power)) { throw 'AC power state unavailable.' }
$plan = & powercfg.exe /GETACTIVESCHEME
if ($LASTEXITCODE -ne 0) { throw 'Windows power scheme query failed.' }
[ordered]@{
    collected_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    manufacturer = $computer.Manufacturer
    model = $computer.Model
    cpu = $processor.Name
    windows = $os.Caption
    build = $os.BuildNumber
    ram_bytes = [long]$computer.TotalPhysicalMemory
    system_volume_total_bytes = [long]$drive.Size
    system_volume_free_bytes = [long]$drive.FreeSpace
    display_adapters = $adapters
    nvidia_gpus = $graphics
    ac_line = switch ($power.ACLineStatus) { 0 {'battery'} 1 {'connected'} default {'unknown'} }
    power_scheme = ($plan -join ' ').Trim()
} | ConvertTo-Json -Depth 4

