# MSI cold-boot traffic acceptance

Use this page locally while the laptop is disconnected. Save your work before each shutdown. Run all commands from the repository root, under the Windows account that owns the guarded runtime. The **Arm** and **Finish** commands require administrator PowerShell. **Run** uses an ordinary PowerShell window. The collector never changes adapters, firewall rules, boot settings or power state.

## Disconnected boot

1. In administrator PowerShell, arm the named trace once. If this run has already been armed, continue with step 2.

   ```powershell
   .\packaging\windows\trace-offline.ps1 -Action Arm -Mode Disconnected -RunId cold-disconnected-01
   ```

2. Turn off Wi-Fi, unplug Ethernet and disconnect any tether, dock network or VPN. Leave those connections off. Use **Shift + Shut down** for a full shutdown. Wait until the MSI is off, power it on, and sign in. A Fast Startup or resumed boot makes the result inconclusive.
3. In ordinary PowerShell, run the synthetic desktop conversation and wait for the command to return.

   ```powershell
   Set-Location -LiteralPath "$env:OneDrive\Documents\ChatGPT\Jarvis"
   .\packaging\windows\trace-offline.ps1 -Action Run -Mode Disconnected -RunId cold-disconnected-01
   ```

4. While still disconnected, open administrator PowerShell in the same repository and finish the recording. Keep the resulting files, including an inconclusive or failed result.

   ```powershell
   Set-Location -LiteralPath "$env:OneDrive\Documents\ChatGPT\Jarvis"
   .\packaging\windows\trace-offline.ps1 -Action Finish -Mode Disconnected -RunId cold-disconnected-01
   ```

## Connected boot with offline mode enabled

1. Reconnect to working internet. In administrator PowerShell, arm the second trace.

   ```powershell
   .\packaging\windows\trace-offline.ps1 -Action Arm -Mode Connected -RunId cold-connected-01
   ```

2. Perform another **Shift + Shut down**, power the laptop back on, and sign in. Allow Windows to report internet access before running the workload. Keep connectivity stable through **Finish**. The workload creates an isolated profile with `offline=True`.
3. In ordinary PowerShell, return to the repository and run the workload.

   ```powershell
   Set-Location -LiteralPath "$env:OneDrive\Documents\ChatGPT\Jarvis"
   .\packaging\windows\trace-offline.ps1 -Action Run -Mode Connected -RunId cold-connected-01
   ```

4. In administrator PowerShell, finish the capture. Then verify the pair from the repository root.

   ```powershell
   Set-Location -LiteralPath "$env:OneDrive\Documents\ChatGPT\Jarvis"
   .\packaging\windows\trace-offline.ps1 -Action Finish -Mode Connected -RunId cold-connected-01
   $traces = Join-Path $env:LOCALAPPDATA 'StylusJarvis\traces'
   .\.venv\Scripts\python.exe -B packaging\windows\trace_report.py "$traces\cold-disconnected-01" "$traces\cold-connected-01"
   ```

Each run ID owns a new private directory. For a repeat, use a new ID throughout that run. If the workload fails, stop its named trace promptly with `-Action Stop` and the same mode and run ID. If analysis alone fails, rerun **Finish** against the stopped trace. The capture uses a 512 MB file limit. Collect promptly after sign-in. Events after the trace reaches its limit cannot support a pass.

To include the saved native pair in the Windows acceptance suite, set `$env:STYLUS_BOOT_ACCEPTANCE = '1'` and run `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_offline_trace.py -v`. Set `STYLUS_DISCONNECTED_RUN` and `STYLUS_CONNECTED_RUN` if the completed runs used different IDs.

## What the evidence establishes

ETW starts before shutdown and resumes across boot. Windows Kernel-Boot event 27, the kernel boot time, the pre-boot journal and network-profile history identify the condition. The workload starts the guarded headless server, opens the real Qt desktop runtime with a temporary project, submits a synthetic prompt, waits for a completed turn in history and closes the runtime. The test driver independently resolves a reserved name using the Windows DNS cache as a positive control. The application and its helpers receive no test instruction to initiate an external connection.

The classifier follows process start and exit events, full private image paths and launcher descendants. It attributes kernel TCP/UDP activity by the event's payload PID, and DNS and socket attempts by the caller PID. This also covers short-lived PowerShell helpers, the native model runner and a child updater if one starts. An independently launched Ollama from a different installation belongs to background traffic. A denied external connection attempt or an external-name lookup still fails the run. One request can yield several ETW events. [Windows tracing with netsh](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/netsh-trace)

A pass requires a completed offline turn, positive controls for all four providers, boot and network evidence, trace coverage, zero reported lost events and buffers, and zero attributed external activity. Unknown external ownership or an unparsed assistant destination makes the result inconclusive. The pair must pass on the same laptop across distinct cold boots. A current-session rehearsal can establish that the collector works.

Private artifacts are under `%LOCALAPPDATA%\StylusJarvis\traces\<RunId>`. Keep the ETL, decoded XML, tracerpt summary, workload journal, process snapshot, network evidence and JSON report together. The ETL and XML include unrelated applications' network metadata and DNS names. The shareable report contains counters, component basenames and PIDs, control results, UTC times and a SHA-256 fingerprint of the ETL. Copy only the reviewed report into the repository evidence folder.
