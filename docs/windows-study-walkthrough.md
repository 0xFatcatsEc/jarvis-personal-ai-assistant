# 5.3.1.1 · Windows offline study walkthrough

This record tracks the current checkout against PRD A1–A5. Use synthetic data in an isolated local profile. Keep release-candidate evidence separate from Foundation traces, stand-alone subsystem tests and the later performance and release-decision gates. [PRD](../STYLUS%20JARVIS%20Product%20Requirements%20Document.docx)

**Initial checkout tested · 25 November 2026.** Build `0.1.0`, schema 9, guarded Ollama with `qwen3:4b`. Source fingerprint `bc793839f7c95654a8b3f1dc52efc0ed5ac86d84478a87c7ffce2ffe68c4afa6` covers 74 files under `src`, excluding bytecode caches. The digest hashes sorted repository-relative paths, a NUL separator and each file's binary SHA-256 digest. Later test runs record their own fingerprints. Release packaging has its own digest.

| Gate | Evidence from this increment | Remaining acceptance |
| --- | --- | --- |
| A1 · Offline start and history | The guarded Qt checkout persisted two real Qwen completions and reopened both in submission order in a new process. Earlier Foundation cold-boot traces passed both network modes. | Bind fresh disconnected and connected cold-boot traffic traces to the candidate build and verify zero external assistant-stack activity. |
| A2 · Grounded recall | The Windows Qt **Answer from evidence** workflow scored 20/20 on the frozen two-project questions. It rendered 16 cited answers and four expected abstentions, with zero cross-project disclosures. It also surfaced the OCR requirement for a PDF page without text. | Carry the checkout result into the candidate evidence pack and repeat against the packaged candidate. The score covers extractive answers in Evidence. Ordinary chat has no automatic grounding or inline turn citations. |
| A3 · Memory lifecycle | Windows desktop acceptance captured a fact through **Evidence → Remember this**. It verified cancellation, confirmation, historical citation access after restart and replacement, scoped export, correction, forgetting through reindex and restart, and grant revocation before save. | Repeat the desktop lifecycle on the packaged candidate and record its identity. |
| A4 · Voice and keyboard | Windows controller and desktop tests passed for capture controls, transcript editing, Stop and typed fallback. The installed Piper model synthesized non-silent PCM and Qt played it three times at zero volume. | Dictate and correct a question on the MSI, hear the local answer, stop speech, then remove a removable microphone during a fresh recording and finish in the same conversation by typing. Verify no temporary audio remains. |
| A5 · Saved code and editor | The live guarded Qt desktop completed the saved-code explanation at the normal 512-token cap. Both live turns reopened in order and the source bytes matched the original. The native broker opened the uniquely named synthetic project in installed VS Code and recorded a successful launch. Windows boundary tests verified no foreign disclosure or additional dispatch. | Covered on the checkout. Retain this evidence with the candidate identity when assembling the release evidence pack. |

## Reproduce the Windows checks

The focused Windows run completed 59 tests with 57 passes and two opt-in Piper tests skipped. A separate run with `STYLUS_PIPER_NATIVE=1` passed all nine Piper tests, including both skipped cases. The native playback check uses zero volume.

The live desktop saved-code retry ended in `token_limit` at 384 output tokens. A direct guarded ordinary chat asking for a two-letter reply also returned visible text and ended in `token_limit` at 96 output tokens. Both checks used synthetic prompts. The desktop run also emitted an HTTP stream-finalization exception during cleanup. Neither result establishes a normally completed turn or a release latency measurement. Diagnose the live completion and cleanup behavior before repeating the full walkthrough.

### Live completion remediation

The guarded Ollama 0.40.17 server returned a pinned Qwen template that opens a thinking block at the end of a user turn. On this build, `think: false` put the reasoning in the visible content and used up the token budget. The adapter requests split thinking and answer fields and delivers only the answer. It uses the temperature and seed from the existing model qualification settings. The model digest and configured output cap are unchanged. [Ollama thinking response fields](https://github.com/ollama/ollama/blob/main/docs/capabilities/thinking.mdx)

The stream reader now consumes the HTTP body boundary after the final NDJSON record, under a two-second deadline. It closes the reader explicitly on exit. The focused Windows regressions passed 36 checks with one opt-in native offline test skipped. The ordinary prompt completed in the real Qt desktop. The saved-code prompt still hit both the configured 512-token cap and the 1,024-token cap tested with a temporary profile. Increasing the cap did not resolve A5. A separate 128-token smoke test reopened the completed and token-limited turns in order and verified the source bytes were unchanged. The cleanup exception did not recur in these reruns.

### Saved-code completion follow-up

The shorter saved-code prompt puts the untrusted-evidence instruction in a system message and sends only the question and retained excerpts to the model. The broker still resolves the exact approved revision. The conversation keeps the path and full revision ID as application-owned provenance. A longer fence contains embedded backtick fences, with the existing bounded JSON representation used for unusually long runs.

In the live comparison a short Python excerpt with the scoped system instruction returned `42` and stopped at 215 generated tokens. In the desktop, the normal 512-token profile completed ordinary chat and the saved-code turn. Both reopened in order on the same isolated profile and the code bytes stayed unchanged. The native broker opened a separate synthetic project in installed VS Code. The Windows tests covered the exact historical source, embedded fences, scoped grants, journal redaction, and no tool dispatch from the evidence. The updated source fingerprint is `822c9eeef4258bb0eb258256e717caca423faffd50f2460ef440532bb98cabc6` for 74 source files. A1–A4 still have the gaps itemized above.

From normal PowerShell at the repository root, with the guarded runtime and the development dependencies provisioned, run the focused evidence suites.

```powershell
$python = Join-Path $env:LOCALAPPDATA 'StylusJarvis\runtime\python\python.exe'
$env:PYTHONPATH = (Get-Location).Path + ';' + (Resolve-Path src).Path + ';' + (Resolve-Path .venv\Lib\site-packages).Path
$env:STYLUS_VSCODE_NATIVE = '1'
foreach ($suite in 'test_desktop.py','test_cited_context.py','test_evidence_locators.py',
    'test_memory_capture.py','test_memory_export.py','test_voice_capture.py','test_whisper.py',
    'test_piper.py','test_editor_launch.py','test_tool_journal.py') {
    & $python -B -P -s -m unittest discover -s tests -p $suite
    if ($LASTEXITCODE -ne 0) { throw "Qualification failed in $suite" }
}
```

### Grounded recall follow-up

The Windows Qt acceptance test drove all 20 frozen questions with the model unavailable. It verified the displayed quotes, exact citations, project isolation, keyboard activation and the warning for a PDF page without text. Companion tests checked a historical text range, revocation during citation inspection, discarded results after a project switch, and conflicting passages with their original citations. The checkout source fingerprint for this run is `e9f232e36237e62934b8bd22c17573dac5b4aaf27b2b7a53a6e35af1793e5a8b` across 75 source files.

All 35 checks in the desktop, cited-context, locator, dashboard, journal and request-grant suites passed across the regression runs. The combined desktop suite passed once and also encountered intermittent native access violations under Windows Qt/qasync on reruns. Record that instability separately from the A2 score.

### Citation-linked memory follow-up

The 26 November Windows run passed all 41 targeted checks, including six desktop cases run in fresh processes. The A3 scenario used the desktop to index the source and capture, correct, export and forget the cited fact across three launches. Only the comparison facts for personal and other-project export isolation were seeded through the repository. The tested source fingerprint was `3521566608d37f5e1e0ef7a7bda9b53c7593728e7c1960ff1c7d8a066b72e8b8` across 75 files.

## Complete the candidate walkthrough

1. Record the candidate build identity, runtime manifest and schema version before testing. Use the same candidate for each case. Use fresh capture IDs and follow the ordinary-user and administrator boundaries in the trace procedure. A laptop shutdown requires saving work and an operator to power the machine back on. [Cold-boot trace procedure](windows-cold-boot-trace.md)
2. In two isolated projects, save excerpts from the frozen fixture sources. Open **Evidence**, enter each question and use **Answer from evidence**. Record the displayed quote and citation or the abstention. Inspect the exact retained page or text range. Include the scanned-page check. Keep answers out of general diagnostics. [Frozen cases](../tests/fixtures/m0-v1/cases.json) · [Windows desktop acceptance](../tests/test_desktop.py)
3. Select an Evidence citation and choose **Remember this**. Write a decision and confirm it in project memory. Restart, replace and reindex the source, then inspect the original citation from Memory. Export and verify the cited fact is present while personal and other-project facts are absent. Correct and forget the decision, then reindex and restart. Verify the forgotten fact stays absent from recall and export, and inspect the original citation using the historical revision filter in Evidence.
4. Hold the configured push-to-talk key, say a short fixture question, release, edit the transcript and send it. With **Speak replies** enabled, check audible playback and Stop. Repeat with a removable microphone and finish by typing after removal. [Voice design](phase-3-technical-design.md)
5. Attach an approved saved source revision, ask for a brief explanation and verify the file hash. Use **Open in VS Code** and confirm the displayed workspace. Record the wrong-root and untrusted-document denial evidence.

Keep 5.3.1.1 open until the candidate passes all five gates. The 20 warm-turn measurement and release decision are later tasks.

## A1 and A4 closure plan

1. Record the bundle manifest digest, application source fingerprint, schema, model digest and runtime. Use the same source fingerprint for both traces and the voice walkthrough. The boot collector loads the guarded checkout. Keep the packaged installation and its own test results identifiable in the evidence.
2. Confirm the private Ollama listener owns the configured numeric loopback endpoint. In the desktop select **Recheck model** and verify **Verified · local only**. Resolve an endpoint collision before arming WPR. [Guarded runtime and listener check](windows-offline-profile.md)
3. Execute the two cold-boot captures and keep their report pair. Record the ordered history result separately. Both captures must have verified trace coverage, positive controls, no unresolved attribution issues and zero outbound assistant-stack activity.
4. Execute the physical voice walkthrough. Record each outcome as pass, fail or blocked on the same candidate. Keep the record to synthetic text, model and build identifiers, and observations. Store no voice recording.
5. Review the captured evidence and close the item only when the remaining acceptance scenarios pass. Delay the next performance task until the walkthrough disposition is recorded.

### MSI preflight evidence · 26 November 2026

- Offline bundle `m2-candidate-20261126-01` built successfully under `%LOCALAPPDATA%\StylusJarvis-Releases`. Manifest SHA-256 `3c23fdcfd158317df00758000552174ea46b88e974331d540e044a9ffdcb49f7`. Application wheel SHA-256 `65a0ebb356279b23bffca40000c71caa4526e96b78d1af7a7350acbeb17dc5fa`. The 69 shipped files under `src/stylus_jarvis` matched the wheel byte for byte. Their source fingerprint is `0d5e707c345bbf603f77a7b73b57015a0292eefc5e399c362367899aaf85736e`. This count excludes generated package metadata. Build `0.1.0`, schema 9, CPython 3.12.13, SQLite 3.50.4, Ollama 0.40.17. The bundle was built and compared. Installed-candidate validation remains pending.
- The dedicated desktop policy check and the live model probe passed. The configured numeric endpoint is `127.0.0.1:11436`, owned by the guarded runtime, with cloud disabled and the pinned `qwen3:4b` digest `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`. The normal Ollama installation owns `127.0.0.1:11434`. A CLI success on that port cannot satisfy the guarded-process check. The prior owner mismatch applies when the desktop targets that listener. The current configured endpoint passed and no application fix was needed.
- The exact trace prompt completed with visible output on the guarded adapter at both 96 and 512 tokens. This verifies the current prompt and cap without awarding a cold-boot pass.
- The live offscreen Qt rehearsal persisted two normally completed Qwen turns in an isolated synthetic profile. Its initial harness aborted cleanup after a single shutdown request while work was pending. A follow-up that waited for model readiness on the partially cleaned profile also timed out. After recreating the synthetic project folder and settings, a fresh guarded Qt process showed both saved turns in submission order and exited successfully. The production history flow required no change. This was a process restart with the laptop already running.
- Windows capture, Whisper and Piper suites passed all 24 checks, including muted native playback. The trace suite passed 11 checks with the actual cold-boot-pair test pending. The first trace test invocation lacked `COMPUTERNAME` in the tool shell. The rerun supplied the machine's actual name and passed.
- The qualification tool shell has no Windows administrator token. WPR arming and finishing require the operator's administrator PowerShell; the operator must also power the laptop back on. Native audio endpoint enumeration found the built-in microphone and speakers. The operator confirmed a USB input is available for the removal test.

### A1 · Two cold boots

Use the complete [cold-boot procedure](windows-cold-boot-trace.md). Use the following candidate IDs if they are unused. Run **Arm** in administrator PowerShell, save work, perform the full shutdown and physically power the MSI back on. Run **Run** in ordinary PowerShell, then **Finish** in administrator PowerShell after the workload succeeds. Keep each run in its required network state through **Finish**.

| Network condition | Run ID | Evidence |
| --- | --- | --- |
| Wi-Fi off and all other network links disconnected | `m2-disconnected-20261126-01` | Disconnected pass, boot type 0, all controls and zero external assistant events |
| Windows connected with the app in offline mode | `m2-connected-20261126-01` | Connected pass, boot type 0, all controls and zero external assistant events |

```powershell
# Use this example first. Substitute Connected and its run ID for the second boot.
# Administrator PowerShell, before the shutdown
.\packaging\windows\trace-offline.ps1 -Action Arm -Mode Disconnected -RunId m2-disconnected-20261126-01

# Ordinary PowerShell, after the full power cycle
.\packaging\windows\trace-offline.ps1 -Action Run -Mode Disconnected -RunId m2-disconnected-20261126-01

# Administrator PowerShell, after Run succeeds
.\packaging\windows\trace-offline.ps1 -Action Finish -Mode Disconnected -RunId m2-disconnected-20261126-01
```

After both runs finish, verify the pair from the repository root and record the two ETL digests from the reports.

```powershell
$traces = Join-Path $env:LOCALAPPDATA 'StylusJarvis\traces'
.\.venv\Scripts\python.exe -B packaging\windows\trace_report.py "$traces\m2-disconnected-20261126-01" "$traces\m2-connected-20261126-01"
if ($LASTEXITCODE -ne 0) { throw 'The two-boot trace pair did not pass.' }
```

### A4 · Physical voice and keyboard

Use a synthetic project and conversation. Start the guarded model and use the desktop with a real user-facing window. Plug in a removable microphone or USB headset for the removal case. Keep output on the laptop speakers if unplugging the headset would otherwise also remove the selected output.

From ordinary PowerShell at the repository root, use a separate, empty temporary directory for the checkout desktop. Keep the guarded model terminal open separately. Close the desktop after the voice exercise to print the scratch directory contents.

```powershell
$scratch = Join-Path $env:LOCALAPPDATA ('StylusJarvis-A4-temp-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $scratch | Out-Null
$oldTemp, $oldTmp = $env:TEMP, $env:TMP
try {
    $env:TEMP = $env:TMP = $scratch
    .\packaging\windows\start-offline.ps1 -Component Desktop
} finally {
    $env:TEMP, $env:TMP = $oldTemp, $oldTmp
    Get-ChildItem -LiteralPath $scratch -Force -Recurse
}
```

1. Focus the composer and hold **F8** (or the displayed push-to-talk key). Say “What is three plus six?” and release. Verify that transcription opens in the editable review, correct the text to “What is three plus seven?”, then select **Use transcript**. Verify the corrected text is in the composer. Press **Send** only after reviewing it.
2. Enable **Speak replies** before sending. Hear a complete reply sentence through the selected output. For Stop, make a second request for several short sentences and press **Stop** while a sentence is audible. Confirm speech stops and the queued sentences stay silent. The Stop button can also cancel an active generation.
3. In the same conversation, type a partial synthetic draft and select the removable microphone. Hold **F8** until recording starts, unplug the selected device while holding the key, then release. Confirm the disconnect or capture-failure message, the absence of a partial transcript, and preservation of the existing draft and conversation. Finish the draft by typing and send it using the keyboard.
4. Launch the desktop with a fresh, dedicated `TEMP` and `TMP` directory for the voice run. After stopping speech, unplugging the device and closing the desktop, inspect that directory for residual audio. Keep the PCM buffer and pipe tests as companion evidence. Record whether the directory was empty and list any unexpected audio artifacts without opening or sharing them.

### Closure evidence status · 26 November 2026

| Acceptance check | Evidence on record |
| --- | --- |
| Candidate identity | Built candidate manifest matches the recorded SHA-256. The existing installed rehearsal still has the Foundation bundle manifest. |
| A1 · Disconnected cold boot | The Foundation run `cold-disconnected-06` verified zero assistant-stack outbound events with all eight controls. The M2 run `m2-disconnected-20261126-01` has no local capture directory or report. |
| A1 · Connected cold boot with JARVIS offline | The Foundation run `cold-connected-01` verified zero assistant-stack outbound events with all eight controls. The M2 run `m2-connected-20261126-01` has no local capture directory or report. |
| A1 · Ordered completed history | Passed in a fresh guarded Qt process on the candidate checkout. |
| A4 · Transcript correction and submission | Automated desktop check passed. Physical observation pending. |
| A4 · Audible local playback and Stop | Muted native playback and automated Stop checks passed. Audible playback and interruption observations pending. |
| A4 · USB microphone removal and typed fallback | Simulated disconnect passed. Physical removal observation pending. |
| A4 · Temporary audio cleanup | Pipe and buffer tests passed. No dedicated physical voice scratch directory was present for inspection. |

**Disposition.** Keep 5.3.1.1 open. The candidate is ready to enter the two cold-boot captures and the physical voice walkthrough. A Windows administrator needs to arm and finish the traces. The operator must perform the power cycles and observe the audio behavior. Record each run ID and its verified report, then record the physical observations and scratch inspection against the candidate identity.
