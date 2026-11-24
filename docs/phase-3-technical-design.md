# Phase 3 technical design

## 3.1.1.1 Select microphone and hotkey

Choose an input in **Microphone** and a foreground key in **Push-to-talk**. F8 is the default, with F9 and F12 as alternatives. Hold the selected key or the **Hold to record** button. The microphone status shows **Recording…** from successful start until release, cancellation, backend stop or the 30-second capture limit. The key applies to the focused JARVIS window, including while the chat editor has focus. Selection is session-local. Typing and ordinary keyboard shortcuts work independently of voice capture.

Qt Multimedia enumerates local endpoints and puts the system default first. The controller selects the current device by ID, ignores repeated key events, gives the first pressed control ownership of the recording and discards on window deactivation or close. Capture requests mono 16 kHz signed 16-bit PCM and records the actual device format when a fallback is necessary. It returns whole PCM frames in a typed clip to an in-process signal. Buffers are limited to 30 seconds and 32 MiB. This item leaves the signal without a transcript consumer and creates no recording file. The capture does not send a chat message. Device-loss workflow and offline Whisper integration belong to subsequent items.

### Acceptance

On Windows, select the second fixture microphone and F9. Confirm F8 does not start capture, F9 starts once, auto-repeat keeps the indicator visible, and release stops capture once. Hold and release the mouse button, then switch windows with the key held to verify discard. Confirm the ordinary editor works when no microphone is available. Backend tests use known PCM bytes to confirm complete frames and cancellation behavior. Native input enumeration does not activate a microphone. [Windows tests](../tests/test_voice_capture.py)

On the MSI desktop, select the built-in microphone, hold the selected key for two seconds, and release it. Expect **Recording…** while held and **Recording stopped** on release. If the keyboard uses media keys by default, use Fn with the selected function key. Switch away while holding the key and expect **Recording cancelled**. A physical session verifies the microphone permission and hardware path, alongside the automated interaction tests.

**Live MSI follow-up.** The manual run reported that PySide6 6.12.0 could not convert the native `QAudio::State` callback argument. The capture backend now reads state on its owning Qt thread with a 100 ms timer that runs only while capturing. The final voice and desktop tests passed (five each), including simulated backend stop without the state signal. Repeat the physical hold-and-release check after restarting the checkout.

For a live session with no visible feedback, set `$env:STYLUS_VOICE_DIAGNOSTICS = '1'` in PowerShell before launching the checkout. The console then reports push-to-talk presses and state transitions. It prints neither audio content nor device identifiers.

**Interactive MSI acceptance passed.** The owner ran the guarded checkout with voice diagnostics enabled and observed `button pressed → Recording... → Recording stopped` and `key pressed → Recording... → Recording stopped`. The trace contained no Qt state-conversion errors. This verifies hold and release through both controls. Audio quality and transcription remain separate checks.

## 3.1.1.2 Handle device loss

While push-to-talk is held, JARVIS tracks the selected microphone by endpoint ID. If Windows removes that input, the app stops capture, discards partial PCM, refreshes the microphone list and shows **Microphone disconnected. Continue by typing.** An unexpected backend stop produces similar feedback. The chat composer gets focus and preserves its existing draft and conversation. Releasing the old control cannot deliver its partial clip. Reconnecting an input never resumes recording on its own. Start a fresh hold to capture again.

The controller checks the selected endpoint on device-list changes and again immediately before delivering a recording. The backend retains its Qt-thread state monitor and treats a disposed audio stream as a failed capture. These paths produce no temporary audio files and do not require Ollama. Submitting the typed fallback still requires the normal local model service.

Windows tests simulate removal while held, release before the device notification, backend failure, and reconnect without auto-recording. The desktop integration test preserves a partial draft, finishes typing in the same conversation, and verifies the reply over local loopback. For a hardware smoke test, use a removable USB microphone or headset and keep JARVIS focused. Start with a partial typed draft, hold F8, unplug the selected input, then release. Check the interruption message and complete the typed draft. [Voice tests](../tests/test_voice_capture.py) · [Desktop acceptance](../tests/test_desktop.py)

## 3.1.2.1 Run local Whisper worker

Release push-to-talk after speaking. The desktop shows **Transcribing locally…**, then a separate transcript review. The chat draft remains intact and no message is submitted. An interrupted recording is discarded. A project or conversation switch cancels an in-flight job and clears the review. An unavailable worker leaves the existing typing path available.

The parent sends framed PCM over stdin to one dedicated Python subprocess per completed clip. The executable is the same firewall-protected Windows interpreter as the desktop. The offline audit hook permits that exact worker command; the child also installs its worker policy. The child downmixes, resamples to mono 16 kHz, and validates the pinned local multilingual base GGML file before native whisper.cpp CPU inference. This increment uses English decoding. It bypasses model-name resolution and download helpers. stdout carries the transcript back to the parent, and native diagnostics are discarded. The worker creates no audio file and expires after the request. Only one job runs at a time; cancellation or a 45-second deadline terminates the child.

The Windows synthetic qualification uses three versioned course sentences generated by local System.Speech, temporarily materializes those test WAVs, and runs the actual guarded subprocess against the staged base model. The fixture audio is cleaned up after the run. These are synthetic results. A spoken MSI sample still checks the physical path and the owner's pronunciation. To repeat the synthetic qualification from the repository root, use the guarded interpreter as follows.

```powershell
$python = Join-Path $env:LOCALAPPDATA 'StylusJarvis\runtime\python\python.exe'
$env:PYTHONPATH = (Resolve-Path src).Path + ';' + (Resolve-Path .venv\Lib\site-packages).Path
& $python -B -P -s packaging/windows/qualify_whisper.py --output .\whisper-qualification.json
```

[MSI synthetic result](evidence/3.1.2.1/msi-whisper.json) · [Versioned vocabulary](../tests/fixtures/voice-v1.json) · [Normalization and pipe tests](../tests/test_whisper.py)

For inaccurate live transcription, enable `STYLUS_VOICE_DIAGNOSTICS=1` and repeat a known sentence. The `[voice] Audio:` line reports duration, peak and RMS in dBFS, and the percentage of normalized samples near full scale. These are measurements of the mono signal supplied to Whisper. They help distinguish quiet or possibly clipped input from decoding errors. They do not identify the cause by themselves. The diagnostic output contains no transcript or audio samples.

For the reported “Jarvis” → “Jerry, please” substitution, set `$env:STYLUS_WHISPER_NAME_HINT = '1'` in PowerShell before launching the desktop to try a decoder spelling hint. The default is off. The worker uses “Jarvis.” as Whisper's initial prompt and displays the decoder's own transcript. The local Microsoft David voice produced the correct words for “Jarvis”, “Jarvis, open my notes” and “Jerry, please” under both settings. Live accuracy with the hint still needs a microphone comparison. The synthetic comparison can be repeated using the qualification command above with `--fixture tests/fixtures/voice-names-v1.json` and a fresh output path for each run.

## 3.1.2.2 Edit transcript and dispose of audio

Correct any misheard words in **Review transcript**, then choose **Add transcript to message**. This appends the edited text to the existing draft on a new line when needed. The composer receives focus so the user can edit again or choose **Send**. **Discard** clears the review and leaves the draft intact. The application pauses new recording during transcription and editable review. Empty results and worker failures appear as status messages.

Capture clears its PCM buffer after release or cancellation. A completed clip passes to the executor and then to the one-shot Whisper worker over stdin. The review holds the resulting text. The production path creates no recording file. Discard while transcribing, a scope change, and shutdown signal the worker to stop and suppress late results. The worker process exits after a result or is terminated and reaped after cancellation or timeout. These are buffer lifetime and file persistence guarantees. Python and the OS may still retain transient memory copies.

Windows acceptance corrects a fixture transcript in the GUI, verifies that it is appended to the draft and that the model receives the edited message only after **Send**. It also discards a pending result and a completed transcript. Capture tests check that PCM buffers are empty after release and cancellation, and pipe tests check that the temporary profile remains empty on silence and worker failure. [Desktop acceptance](../tests/test_desktop.py) · [Capture tests](../tests/test_voice_capture.py) · [Whisper worker tests](../tests/test_whisper.py)

## 3.2.1.1 Stream sentences to Piper

Enable **Speak replies** before sending a message. The desktop extracts complete sentences from the authorized reply stream and sends them to Piper in order. Punctuation at a fragment boundary may need the next fragment or the terminal event to confirm the sentence. Fenced code, inline code, Markdown links, and HTTP(S) URLs remain visible in the original reply. Those spans are omitted from speech. An incomplete tail at a token limit stays visible. Speech defaults to off each session. Turn it off to clear pending speech.

The desktop bounds its parser to 65,536 characters, its queue to 24 pending sentences and each worker request to 2,048 UTF-8 bytes. A single queue consumer performs synthesis and playback in order. Each sentence uses a fixed command in the firewall-guarded interpreter, a 20-second worker deadline, and the SHA-256-pinned LJ Speech ONNX model, configuration, and model card from M0. Piper runs on the CPU and returns at most 30 seconds of 22.05 kHz mono PCM. Qt's `QAudioSink` plays the raw audio from an in-memory buffer. The app revalidates the project's grant immediately before starting each clip. Scope changes, a new reply, and shutdown clear old speech. A synthesis or playback failure leaves the full written reply available. [Qt raw playback API](https://doc.qt.io/qt-6/qaudiosink.html)

The Windows desktop acceptance server withholds the final response frame until playback of the first sentence starts. It checks speech order, unchanged visible code and links, and unchanged saved content. Native acceptance uses the provisioned model and tests Qt playback from memory with muted output. An audible smoke test can be done by opening the checkout, enabling **Speak replies**, and asking for two short sentences and a code block. Confirm that both sentences are audible in order and the code remains visible. Microphone and playback coordination and the dedicated interruption acceptance belong to **3.2.1.2**. [Windows tests](../tests/test_piper.py) · [Desktop acceptance](../tests/test_desktop.py) · [Piper API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md)

The installed runtime is `piper-tts==1.8.0`, with runtime dependencies pinned in `uv.lock`. A future distributable bundle that includes the GPL-licensed Piper runtime should account for its redistribution terms. The Foundation qualification record identifies the earlier bundle. [Pinned package](https://pypi.org/project/piper-tts/1.8.0/) · [Piper license](https://github.com/OHF-Voice/piper1-gpl/blob/main/COPYING)

## 3.2.1.2 Coordinate microphone and stop

The desktop gates the microphone before handing PCM to Qt playback. During playback, the record button and hotkey reject capture and show how to stop speech. A microphone capture already in progress postpones playback until release. The queue rechecks the project grant and microphone state immediately before starting each clip. **Stop** remains available while the speech queue is active, including after the written reply completes. It cancels active synthesis or playback, clears queued sentences and displays **Speech stopped.**

The Windows voice tests exercise the button and hotkey during playback. The queue tests start with the microphone held, release it, stop ongoing playback within one second and confirm that the second queued clip never starts. The Qt desktop test verifies immediate feedback when **Stop** is clicked after the written turn ends. [Voice tests](../tests/test_voice_capture.py) · [Speech tests](../tests/test_piper.py) · [Desktop tests](../tests/test_desktop.py)

## 3.2.2.1 Exercise voice with indexing

The Windows rehearsal starts a private guarded Ollama listener and an isolated VS Code window. The fixture sends locally synthesized speech through Whisper, the Qwen turn coordinator and Piper. The fixture appends Qwen's `/no_think` instruction to the transcript and sets a 128-token generation budget for the timed short-answer workload. Qt drives the native playback path at zero volume. In each trial the scoped repository approves, extracts and publishes eight synthetic UTF-8 files while the voice turn is underway. This benchmark exercises the repository indexing pipeline directly, which provides a reference for the unthrottled mixed workload. [Qwen thinking modes](https://qwen.readthedocs.io/en/stable/getting_started/quickstart.html)

Voice-turn time runs from handing off recorded PCM through the last clip and the written turn's terminal state. First-text time starts at transcript submission and ends on the first streamed text fragment. The runner reports one initial trial and warm-trial median and nearest-rank p95. It identifies token-limit results explicitly and reports a separate duration summary for normally completed warm replies when available. A valid measurement requires at least one complete sentence to finish playback. The memory sampler records system-wide peak RAM and available NVIDIA VRAM observations, with a baseline taken after the listener becomes reachable. The results describe a synthetic workload and the sampled hardware.

The mixed run exposed a Windows version lookup that could fall back to a shell command when WMI was unavailable. Piper now caches platform information with a native Windows version fallback before importing ONNX Runtime. The worker's subprocess policy continues to deny shell launches. A stack trace also captured a multimedia player teardown stall during repeated in-memory WAV playback, so playback now feeds raw PCM directly to Qt's audio output.

An exploratory 512-token run saturated the 24-sentence speech queue on a warm reply. The on-screen reply remained available. Token-limit trials also exposed an HTTP transport generator cleanup warning. The report separates terminal outcomes, and the integrated laptop performance gate still requires the representative 20-turn run.

From the repository root, use the guarded interpreter and a fresh report path.

```powershell
$python = Join-Path $env:LOCALAPPDATA 'StylusJarvis\runtime\python\python.exe'
$code = Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\Code.exe'
$env:PYTHONPATH = (Get-Location).Path + ';' + (Resolve-Path src).Path + ';' + (Resolve-Path .venv\Lib\site-packages).Path
$env:QT_QPA_PLATFORM = 'offscreen'
& $python -B -P -s packaging/windows/qualify_voice.py --warm-turns 3 --code $code --output .\voice-mixed-run.json
```

## 3.2.2.2 Prioritize foreground work

**Save source excerpts…** queues extraction and scoped FTS publication for the explicitly selected local path. **Approve source file…** continues to register file metadata. The bounded queue has one worker and at most 24 pending paths. Repeated requests for the same path in the same selection replace pending work and cancel superseded work at its next checkpoint. The worker reads the latest requested file, validates its bytes against the registered revision and publishes atomically. The previous active revision remains historically addressable.

Mic capture, Whisper transcription, reply generation and Piper work have foreground priority. The indexer waits at stage boundaries, between fingerprint chunks and between PDF pages. An extraction operation or SQLite transaction already underway can finish its current unit of work. Scope changes and shutdown discard queued requests and cancel remaining work at its next checkpoint. File changes enter the queue through the explicit file selection. This preserves the Phase 2 approval boundary.

Windows acceptance holds the foreground gate, submits two revisions of the same path and confirms neither is published during foreground work. After release, active search returns the final revision and historical search still returns the previously published revision. [Index queue tests](../tests/test_index_queue.py)
