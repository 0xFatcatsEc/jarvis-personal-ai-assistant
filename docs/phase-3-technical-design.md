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
