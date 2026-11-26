# Dashboard Increment 1

The [dashboard architecture](jarvis-dashboard-architecture.md) defines workflows. The [mission-control composition](jarvis-dashboard-mission-control-composition.md) defines the dark three-column layout and centered Core.

## Implementation plan

1. Build a PySide6 shell with project, conversation and configured model in the scope strip. Keep the Core on the open center canvas above Conversation, frame it with Operations and Coding Assistant, and anchor the dock below.
2. Drive model readiness, task state, microphone and playback feedback, recovery status and diagnostic health from the existing application services. Use the existing Stop and Retry save actions in the Core.
3. Rehouse the existing Evidence, Memory, Coding and System controls in the approved dock destinations. Test keyboard focus, wide and compact arrangements, draft retention, and the existing Windows workflow tests.

## Files and migration

| File | Responsibility |
| --- | --- |
| `ui/main_window.py` | Shell, layout and navigation. The original controls and signals remain the desktop controller's entry points. |
| `ui/dashboard.py` | Dark styling and a static, event-driven Qt status ring with a text label. |
| `bootstrap.py` | Binds configured model identity, runtime state and existing service summaries to the view. |
| `voice/controller.py` | Bounds recording input to the visible Conversation controls. Leaving Conversation cancels an active capture. |
| `tests/test_dashboard.py` and `tests/test_desktop.py` | Exercise layout, keyboard routing and the real desktop workflow with local fixtures. |

The current desktop entry point launches the shell. It uses the existing profile, SQLite schema, Ollama verification, source and memory dialogs, editor bridge, voice workers, and bounded shutdown. Resize moves the same rail widgets between panels, preserving their state. Conversation remains the default view. At compact widths Operations moves to System, and Coding can open beside Conversation or as a single view depending on width. A short window or voice review reduces the Core first.

Evidence exposes the existing file approval and excerpt actions. Memory exposes capture, correction, forgetting and project export. The later evidence explorer, richer memory browsing and Phase 5 Actions remain on their established roadmap. VS Code retains patch review, approval and recovery.

## Keyboard and verification

- **Ctrl+1–5** opens Conversation, Evidence, Memory, Coding and System. **Ctrl+F** focuses conversation search. **Ctrl+Enter** sends from the composer.
- **Tab** and **Shift+Tab** traverse controls. **F6** and **Shift+F6** move between visible dashboard regions. The Core readout itself stays out of the tab order. Push-to-talk retains the user's configured key.
- Windows regression exercised 164 tests across isolated modules. There were 158 passes and six environment-dependent skips. The offline trace suite passed on rerun with the Windows machine name supplied to the shell. The live Narrator and physical display-scaling walkthrough remains open.
