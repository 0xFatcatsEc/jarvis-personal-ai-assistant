# MSI cold-boot traffic acceptance

Use this page locally while the laptop is disconnected. Save your work before each shutdown. Run all commands from the repository root, under the Windows account that owns the guarded runtime. The **Arm** and **Finish** commands require administrator PowerShell. **Run** uses an ordinary PowerShell window. The collector never changes adapters, firewall rules, boot settings or power state.

## Disconnected boot

1. In administrator PowerShell, arm the named WPR boot capture. The example uses a fresh ID for the retry. Keep the first disconnected run for comparison. Wait for **Arm** to succeed and write `boot-sources.json` before shutting down.

   ```powershell
   .\packaging\windows\trace-offline.ps1 -Action Arm -Mode Disconnected -RunId cold-disconnected-02
   ```

2. Turn off Wi-Fi, unplug Ethernet and disconnect any tether, dock network or VPN. Leave those connections off. Use **Shift + Shut down** for a full shutdown. Wait until the MSI is off, power it on, and sign in. A Fast Startup or resumed boot makes the result inconclusive.
3. In ordinary PowerShell, run the synthetic desktop conversation and wait for the command to return.

   ```powershell
   Set-Location -LiteralPath "$env:OneDrive\Documents\ChatGPT\Jarvis"
   .\packaging\windows\trace-offline.ps1 -Action Run -Mode Disconnected -RunId cold-disconnected-02
   ```

4. While still disconnected, open administrator PowerShell in the same repository and finish the recording. Keep the resulting files, including an inconclusive or failed result.

   ```powershell
   Set-Location -LiteralPath "$env:OneDrive\Documents\ChatGPT\Jarvis"
   .\packaging\windows\trace-offline.ps1 -Action Finish -Mode Disconnected -RunId cold-disconnected-02
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
   .\.venv\Scripts\python.exe -B packaging\windows\trace_report.py "$traces\cold-disconnected-02" "$traces\cold-connected-01"
   ```

Each run ID owns a new private directory. For a repeat, use a new ID throughout that run. WPR writes sequential files under that directory, so run the workload promptly after sign-in and stop recording as soon as it finishes. **Run** checks the fresh boot, network state and registered source files before submitting the prompt. If a check or workload fails, preserve the diagnostics and use `-Action Stop` with the same mode and run ID. **Stop** can also cancel an armed capture before shutdown. If only decoding fails, rerun **Finish** against the stopped trace.

To include the saved native pair in the Windows acceptance suite, set `$env:STYLUS_BOOT_ACCEPTANCE = '1'` and run `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_offline_trace.py -v`. Set `STYLUS_DISCONNECTED_RUN` and `STYLUS_CONNECTED_RUN` if the completed runs used different IDs.

## What the evidence establishes

**Arm** registers two named AutoLoggers for the next boot. Windows starts them at boot with fresh files and **Finish** merges them into one ETL. This keeps a single boot clock in each recording. The mode check combines Kernel-Boot event 27, boot time, physical link state, network-profile history and default routes joined to their IP interfaces. A route on an explicitly disconnected interface can remain configured. A connected or unresolved default route prevents a disconnected pass. [Windows Performance Recorder boot commands](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/wpr-command-line-options)

The workload starts the guarded headless server and real Qt runtime, submits a synthetic prompt, waits for the completed turn in history and closes the desktop. The observer issues a run-specific, cache-only DNS lookup and sends a UDP datagram between two loopback sockets. Its PID and ports distinguish those controls from assistant activity.

The classifier follows process start and exit events, full private image paths and launcher descendants. It attributes kernel TCP/UDP activity by the event's payload PID, and DNS and socket attempts by the caller PID. This also covers short-lived PowerShell helpers, the native model runner and a child updater if one starts. An independently launched Ollama from a different installation belongs to background traffic. A denied external connection attempt or an external-name lookup still fails the run. One request can yield several ETW events. [Windows tracing with netsh](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/netsh-trace)

A pass requires the completed turn, boot and network evidence, trace coverage, loss checks, zero attributed external activity and positive controls for the process tree, DNS, TCP socket attempts, UDP sends and independent transport. The TCP/IP driver's outbound connect-completion event carries the caller PID and remote endpoint. A successful connection from the desktop to the assigned model port provides an independent transport witness when the generic kernel-network provider is silent. Failed external connect attempts still count. Kernel-mode event providers use nonpaged buffers. Unknown external ownership or an unparsed assistant destination makes the result inconclusive. Both modes must pass on the same laptop across distinct cold boots. [Microsoft kernel-provider recording guidance](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/capture-and-view-tracelogging-data)

Private artifacts are under `%LOCALAPPDATA%\StylusJarvis\traces\<RunId>`. Keep the ETL, decoded XML, tracerpt summary, workload journal, process snapshot, network evidence and JSON report together. The ETL and XML include unrelated applications' network metadata and DNS names. The shareable report contains counters, component basenames and PIDs, control results, UTC times and a SHA-256 fingerprint of the ETL. Copy only the reviewed report into the repository evidence folder.
