# Run the guarded Windows desktop

The MSI Thin A15 has a dedicated CPython 3.12.13 interpreter and headless Ollama 0.40.17 installation under `%LOCALAPPDATA%\StylusJarvis\runtime`. Four persistent Windows Firewall outbound rules cover the dedicated interpreter, server and two shipped native tools. The normal Python environment and the user's Ollama tray installation have separate paths.

## Start a session on the provisioned MSI

From the repository root, run the model in one normal PowerShell terminal and leave it open.

```powershell
.\packaging\windows\start-offline.ps1 -Component Model
```

Start the desktop in a second normal terminal.

```powershell
.\packaging\windows\start-offline.ps1 -Component Desktop
```

Both read `%LOCALAPPDATA%\StylusJarvis\config\settings.toml`. The default endpoint is `127.0.0.1:11434`. If the user's tray service owns that port, choose a free port such as `11436` in the existing settings file (`port = 11436`) and relaunch the two components. For a new profile the settings file can contain just that line. The verifier rejects a listener owned by another program, even on loopback. The desktop can reopen history when the private server is stopped. Close the desktop normally and stop the foreground model using Ctrl+C.

## Prepare another Windows development machine

Begin with this repository's working Python 3.12 environment in `.venv`, the M0-verified local model store and the M0 Ollama 0.40.17 per-user installation. Use the *same Windows account* for staging, rule installation and desktop execution. Rules bind to absolute image paths. These steps copy files already present on disk.

```powershell
$ErrorActionPreference = 'Stop'
.\.venv\Scripts\python.exe -B packaging\windows\provision_assets.py verify
if ($LASTEXITCODE -ne 0) { throw 'M0 verification failed.' }
$runtime = Join-Path $env:LOCALAPPDATA 'StylusJarvis\runtime'
$sourcePython = & .\.venv\Scripts\python.exe -c 'import sys; print(sys.base_prefix)'
$sourceOllama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
if (Test-Path -LiteralPath $runtime) { throw 'An existing runtime needs verification before re-staging.' }
New-Item -ItemType Directory -Path (Join-Path $runtime 'ollama') -Force | Out-Null
Copy-Item -LiteralPath $sourcePython -Destination (Join-Path $runtime 'python') -Recurse
Copy-Item -LiteralPath (Join-Path $sourceOllama 'ollama.exe') -Destination (Join-Path $runtime 'ollama')
Copy-Item -LiteralPath (Join-Path $sourceOllama 'lib') -Destination (Join-Path $runtime 'ollama') -Recurse
```

From the repository root in elevated Windows PowerShell, install and verify the program-specific rules. Repeat after an intentional runtime replacement. An incomplete effective rule or a disabled firewall profile stops verification. Inspect the effective policy if Windows reports an error.

```powershell
$python = Join-Path $env:LOCALAPPDATA 'StylusJarvis\runtime\python\python.exe'
.\src\stylus_jarvis\runtime\offline-policy.ps1 -Mode Install -PythonImage $python
Get-NetFirewallRule -PolicyStore ActiveStore -Group 'STYLUS JARVIS offline' |
    Select-Object DisplayName, Enabled, Direction, Action, Profile
```

The foreground launcher supplies a fresh environment, pins the model store and sets `OLLAMA_NO_CLOUD=1`. The profile excludes the Windows tray executable that handles automatic updates. The application checks the listening program, effective firewall rules, disabled-cloud status, local model metadata and release digest before sending a prompt. The desktop uses a local JSONL diagnostic sink. A normal session has no provisioning, pull, telemetry export or updater step. [Ollama local-only mode and Windows updates](https://docs.ollama.com/faq)

## Repeat Windows acceptance

For backlog 1.3.1.2 use the separate two-boot procedure. Its workload measures ordinary assistant behavior. The firewall denial test below intentionally attempts an external connection and must run outside the traffic capture. [Two-boot trace procedure](windows-cold-boot-trace.md)

Run in normal PowerShell from the repository root. The live test launches its own private server on a free loopback port, makes a synthetic Qwen request and stops the test process tree. It also requires Windows to return Winsock error 10013 on an outbound TCP connection to the documentation address `192.0.2.1`. A timeout or unreachable network fails that assertion.

```powershell
$python = Join-Path $env:LOCALAPPDATA 'StylusJarvis\runtime\python\python.exe'
$env:PYTHONPATH = (Resolve-Path src).Path + ';' + (Resolve-Path .venv\Lib\site-packages).Path
$env:STYLUS_NATIVE_ACCEPTANCE = '1'
& $python -B -m unittest discover -s tests -v
```

To retire this profile, close its desktop and model first. Review the four entries with the inspection command above, then run the following in elevated PowerShell. Removing its rules makes the desktop fail its next startup check.

```powershell
Get-NetFirewallRule -PolicyStore PersistentStore -Group 'STYLUS JARVIS offline' |
    Remove-NetFirewallRule
```
