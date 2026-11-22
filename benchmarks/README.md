# Qualify Qwen 3 on the MSI Thin A15

Backlog 1.1.2.2 compares the pinned Q4_K_M builds of Qwen 3 4B and 8B using the same 4,096-token context, 512-token generation cap, seed 41, temperature zero and disabled thinking output. The runner uses the Foundation Python environment and a dedicated loopback Ollama service. It does not change the application model pin. The owner records the final decision after reviewing the real outputs.

## Execute on Windows

Run from the repository root in PowerShell. Connect AC, open this workspace in VS Code, keep the same power scheme and editor workload throughout, and close other model clients. Allow roughly 8 GB of additional model storage for the separate benchmark store, plus room for the installed runtime. The larger model may offload only partly to this 4 GiB GPU.

1. Verify the previously staged assets, check the benchmark harness, and install the staged runtime if Ollama v0.40.17 is absent. Use the default per-user installation directory. Complete installation before starting the server.

   ```powershell
   .\.venv\Scripts\python.exe packaging/windows/provision_assets.py verify
   .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_model_qualification.py -v
   $installer = Join-Path $env:LOCALAPPDATA 'StylusJarvis/assets/m0-v1/installers/OllamaSetup-0.40.17.exe'
   Start-Process -FilePath $installer -Wait
   ```

2. In terminal A, start the dedicated server. This copies and verifies only the staged 4B model files in a separate store. Leave this terminal running.

   ```powershell
   .\benchmarks\start-server.ps1
   ```

3. In terminal B, point the Ollama CLI to the benchmark server, verify its version and fetch the 8B candidate. Pulling requires network access once. A changed tag fails the runner's digest check. Preserve the pinned manifest and recover the intended revision before proceeding.

   ```powershell
   $env:OLLAMA_HOST = '127.0.0.1:11435'
   $ollama = Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
   Invoke-RestMethod http://127.0.0.1:11435/api/version
   & $ollama pull qwen3:8b
   if ($LASTEXITCODE -ne 0) { throw '8B provisioning failed' }
   & $ollama list
   code .
   ```

4. Run the comparison with 4B first. The output directory must be new. The runner checks the target hardware, AC status, VS Code process, model digests and initial empty model residency. Each model gets one cold request, 20 warm recall requests and five warm coding requests. Data is saved after each completed turn. If a run fails, retain the partial directory for diagnosis and rerun into a fresh directory.

   ```powershell
   .\.venv\Scripts\python.exe -m benchmarks.qualify run outputs/qwen-msi-01
   ```

5. Open each model's `trials.json` and fill in `review.csv` with the rubric below. Save as UTF-8 CSV. Calculate the comparison and copy the decision form into the run directory.

   ```powershell
   .\.venv\Scripts\python.exe -m benchmarks.qualify score outputs/qwen-msi-01
   Copy-Item benchmarks/decision-template.md outputs/qwen-msi-01/decision.md
   ```

6. For a close result, a change in free RAM, or suspected thermal or order effects, repeat with the other order, grade again and compare both runs. Keep both evidence directories. Stop the dedicated server with Ctrl+C in terminal A when finished.

   ```powershell
   .\.venv\Scripts\python.exe -m benchmarks.qualify run outputs/qwen-msi-02 --reverse
   ```

## What the measurements mean

| Metric | Collection and interpretation |
|---|---|
| Cold start | Time from sending a fresh streaming chat request until the first non-whitespace answer content, with no model in the server's residency list. Also records full response time and server-reported load duration. The OS file cache may be warm. This measures model cold start, not a Windows reboot or Qt application launch. |
| Warm response | Before each request the runner verifies only the expected digest is resident. For the 20 recall turns report median and nearest-rank p95 time to first answer text (19th sorted observation). Report the five coding turns separately. Every turn also records complete response time and terminal reason. Timing ends at the benchmark client, so the full desktop A6 test still has UI and persistence overhead. |
| Physical RAM | Windows total physical memory minus available memory. Values cover the whole machine, including VS Code, OS caching and other processes. Record baseline before the cold request, highest sampled usage, and peak above baseline. |
| Dedicated VRAM | NVIDIA GPU 0 memory.used, in MiB, from nvidia-smi. A background thread samples both resources approximately every 0.5 s plus sampling cost and once at each endpoint. The observed peak is a lower bound; the sampler raises on unavailable counters. Compare system totals alongside the final Ollama residency report, including size_vram. |
| Quality | A fresh single-turn prompt per case. Only the active project's passages are supplied. The two models see the same case order and no answer keys or coding rubrics. Project recall at this gate uses supplied evidence. Full application retrieval is evaluated later. |

`run.json` records input hashes, model metadata, options, order, server version and hardware. Each model directory contains its hardware snapshot, raw answers and timings, memory samples and summary metrics. An interrupted run stays incomplete and cannot be scored. Keep synthetic outputs and the completed review alongside the decision record.

## Review and choose

For each Q row use the frozen answer key in `tests/fixtures/m0-v1/cases.json`. Enter 0 or 1 in each check. Check 1 is semantic correctness or explicit abstention. Check 2 is the correct project/file/page citation for an answer; for an abstention, verify there is no invented answer or citation. Set disclosure to 1 if another project's evidence was revealed, otherwise 0. Award one recall point only when both checks pass and disclosure is zero. Explain misses and leaks in the note field.

For each C row read its two task-specific criteria in `coding-v1.json`. Score each independently as 0 or 1; leave disclosure blank. Inspect the answer as delivered, including truncation. Review generated snippets as text. This produces a coding score out of ten. Use the same reviewer and rubric for both models.

**Eligibility:** require complete measurements, at least 18/20 recall, zero cross-project disclosures and warm recall p95 at or below the 5-second trial target. If only one qualifies, it is the provisional candidate. If neither qualifies, report neither and rerun after a documented tuning decision. An owner-approved change to the trial latency target is a separate recorded decision.

**Trade-off:** when both qualify, prefer 4B for the laptop. The harness proposes 8B if it gains at least two of ten coding points. This is a proposed materiality threshold for this comparison. Review cold delay, sampled RAM/VRAM peaks and editor responsiveness before accepting 8B. If paging, instability or slower cold starts outweigh its coding gain, record why 4B is preferable. If conditions change or results are close, use the reverse-order run before selecting. Complete the decision template and record any exception explicitly.

Protocol references: [Ollama chat streaming](https://docs.ollama.com/api/chat), [model residency](https://docs.ollama.com/api/ps), [model inventory](https://docs.ollama.com/api/tags).
