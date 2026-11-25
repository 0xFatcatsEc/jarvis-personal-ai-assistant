# STYLUS JARVIS dashboard architecture

**Design baseline · 25 November 2026 · Windows 11 and PySide6.** This specification covers the completed Phase 1–4 capabilities in the checkout and the dashboard surfaces that Phase 5 can enable once their backlog dependencies pass acceptance. It defines desktop information architecture and interaction. The current Phase 4 bridge, schema 8, local runtime and repository boundaries remain the implementation baseline.

The reference image informs the dark canvas, cyan highlights, compact framed panels, central status landmark and bottom dock. In STYLUS JARVIS, the landmark is the active conversation and the right-hand feature panel is **Coding Assistant**. Both answer an immediate question for a person using the workstation. The center shows what JARVIS is doing. The right rail shows exactly what JARVIS can see or act on.

**Implementation baseline.** The current Qt window connects through the desktop controller to scoped conversations, source approval, saved excerpts, memory, recovery status, diagnostics, voice and the VS Code bridge. Retrieval and citation resolution exist in the repository layer. The current desktop transcript is plain text and does not deliver interactive citation cards or automatically ground every turn. The proposed Evidence view is new UI over existing retrieval services. Inline turn citations need an explicit typed delivery contract, with durable citation receipts as a separate follow-up if required. VS Code already owns patch proposals, diffs, approvals, writes and conflict recovery.

[Current desktop view](../src/stylus_jarvis/ui/main_window.py) · [Desktop controller](../src/stylus_jarvis/bootstrap.py) · [PRD](../STYLUS%20JARVIS%20Product%20Requirements%20Document.docx) · [Architecture review](../STYLUS%20JARVIS%20Architecture%20Review%20and%20V2%20Design.docx) · [Phase 4 design and recovery workflow](phase-4-technical-design.md) · [Development backlog](../outputs/stylus-development-backlog/STYLUS%20JARVIS%20Development%20Backlog.xlsx)

## 1. Information architecture

| Layer | Contents and ownership | Roadmap |
| --- | --- | --- |
| Application and scope | Offline mode, active project and conversation, verified model identity and availability, task state. Project picker uses full roots to disambiguate similar names. | Phase 1 · F1–F2 |
| Primary work | Conversation and composer, scoped Evidence, Project memory and Personal memory. Explicit selection controls what is shown and what is attached to a request. | Phases 1–2 · F2–F4, F8 |
| Coding context | Selected saved revision, explicitly shared editor metadata and the route to VS Code patch review and receipts. These are separate kinds of state. | Phase 4 · F6–F7, F9 |
| Operational status | Model readiness, unsaved response recovery, backup status, voice availability and redacted diagnostics. | Phases 1–3 · F2, F5, F8, N6 |
| Local actions | Future scoped Coding, System, Files and Memory tools, durable run receipts, reviewed file changes and named desktop controls. | Planned 5.1–5.2 · F7, F9 |

The visual order is **scope → active task → evidence or editor context → health and recovery**. Changing the project or conversation immediately invalidates scoped panels, attachments and actionable dialogs. Late results from a previous scope must never populate the new scope.

## 2. Screen architecture

- **Conversation** is the default center view, with chronological history, in-conversation search, composer, optional saved-code attachment and voice controls. Conversation selection returns to the current project's saved history.
- **Evidence** replaces the center body with scoped source actions, query results and an excerpt inspector. An evidence deep link selects the exact revision and preserves a return point to the originating turn or fact.
- **Memory** replaces the center body with scoped fact recall and explicit capture, correction and forget review. Project and Personal are separate destinations.
- **System** switches the center body to operational detail with Diagnostics and Recovery as two views. The left rail retains compact health summaries and direct links to those views.
- **Coding Assistant** owns the right inspector on wide layouts. The dock focuses it or opens it as a full-height view on narrow layouts. There is one inspector state per active scope.
- **Actions**, planned for Phase 5, is a center view added after the broker and journal are available. File operation review and desktop controls are enabled only after their own acceptance gates.

The shared scope strip and dock persist across views. Navigating between views in the same scope restores position and focus. Scope changes follow the existing controller's reset behavior. The active turn can be stopped from the shared task controls even when another view is open.

## 3. Three-column dashboard layout

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ STYLUS JARVIS   Offline   Project ▾   Conversation ▾   Model status   Stop* │
├──────────────────┬───────────────────────────────────┬───────────────────────┤
│ OPERATIONS       │ JARVIS CORE                       │ CODING ASSISTANT      │
│ Model readiness  │ Current task and scoped feedback  │ Saved revision        │
│ Recheck model    │ Conversation search               │ Select / remove       │
│                  │                                   │                       │
│ Data protection  │ Ordered, readable conversation    │ VS Code session       │
│ Backup status    │ Streaming response and turn state │ Launch / pair         │
│ Recovery details │ Evidence links where available    │ Last shared buffer    │
│                  │                                   │                       │
│ Diagnostics      │ Draft and attached revision       │ Patch workflow        │
│ Sink / drops     │ Hold to talk · Speak replies      │ Review and outcome    │
│ Recent events    │ Review transcript when needed     │ commands in VS Code   │
│                  │ Send · Retry save when needed     │                       │
├──────────────────┴───────────────────────────────────┴───────────────────────┤
│     Conversation       Evidence       Memory       Coding       System      │
└──────────────────────────────────────────────────────────────────────────────┘
* Stop appears in the shared strip while generation or speech can be stopped.
```

At 1920×1080 with 125% Windows scaling, target approximately **250 / 920 / 320 device-independent pixels** for the left, center and right regions, with the remainder for margins, split handles and window chrome. The center gets all spare width by default. A transcript reading measure of about 75–95 characters keeps prose scannable. Code, paths and hashes allow selection and preserve meaningful line breaks. Side cards stack and scroll independently when needed. The composer and transport stay anchored within the Conversation view.

**Visual system.** Use near-black canvas `#0B1118`, panel `#111C27`, subdued border `#304357`, main text `#E4EDF6`, secondary text `#A9BDD0`, cyan focus/selection `#62D9F5` and blue secondary emphasis `#8BAFFF`. Use visible text and icons for warning, failure and success. Keep dense metadata in a monospace face and long prose in a Windows-native text face. Target 4.5:1 for normal text and 3:1 for focus and meaningful control boundaries. Validate actual rendered palette combinations, Windows High Contrast and scale settings. Use small typography variations and restrained dividers in place of animated rings, textures and decorative telemetry.

## 4. Widget inventory

| Widget | Data, action and empty state | Source |
| --- | --- | --- |
| Scope strip | Offline policy, project and conversation selectors, Add project, New conversation and task summary. At startup show initialization. With no project, focus Add project. | Phase 1 |
| Conversation surface | Search, ordered turns and status, streaming text, draft, Send, Stop and Retry save. A history-only state is available when the local model is unavailable. | Phase 1 |
| Model readiness | Verified local Ollama/model status and Recheck model. Show unavailable or checking as distinct states. | Phase 1 |
| Evidence view and locator inspector | Approve local source, save excerpts, retrieve matches, inspect retained page or text ranges. Show no matches, insufficient evidence, unavailable revision or extraction limitation as appropriate. | Phase 2 repository APIs and existing source actions |
| Scoped Memory view | Destination, confirmed fact list, version, provenance when available, Remember, Correct, Forget and Export project. | Phase 2 |
| Recovery card and view | Last verified backup age, configured destination and safe failure detail. Distinguish missing configuration from failed verification. | Phase 2 · 2.3 |
| Diagnostics card and view | Queue depth/capacity, dropped count, sink condition, recent events, build identity and available writer timings. | Phase 1 · 1.3.2.2 |
| Voice transport and review | Device and hold-key controls, recording state, editable transcript, Add transcript to message, Discard, Speak replies and Stop. | Phase 3 |
| Saved code card | Selected project-relative path, exact source revision, Select and Remove. If no eligible revision exists, direct the user to save source excerpts. | Phase 4 · 4.1.1.1 |
| Editor card | Approved project launch, pair and disconnect, metadata from the last explicit share and access to its details. | Phase 4 · 4.1.1.2, 4.2.1 |
| Patch card | VS Code workflow instructions and command names. Open the editor for the approved project. Outcome and acknowledgment dialogs are rendered inside the extension. | Phase 4 · 4.2.2 |
| Navigation dock | Conversation, Evidence, Memory, Coding and System. Labels are always visible. | Phases 1–4 |
| Conditional Actions surface | Scoped role and tool descriptions, broker outcomes and operation review when supported. Hidden until the matching availability and policy contracts exist. | Planned Phase 5 · 5.1–5.2 |

## 5. Central JARVIS Core panel design

The Core is the working conversation, with a single compact activity header. It shows the current operation in plain language and highlights the action the user can take. Examples include **Ready**, **Generating locally**, **Stopping**, **Response truncated by token limit** and **Reply needs saving**. Render per-turn badges from runtime state. Keep completion, token limit, cancellation, interruption and failure distinct. A recovery notice identifies the pending write and shows **Retry save** where supported, without implying a new model request.

The transcript is the largest scrollable surface. Auto-follow streaming only while the user is at the end. Preserve selection and position when they scroll back and offer **Jump to latest** only when new content is below the viewport. Group each turn by role and state. Keep the composer below it, with a removable saved revision attachment and voice controls close to drafting. Citation affordances are attached only to verified structured evidence. The active task indicator mirrors application events and has no independent state or animation loop.

## 6. Left-side operational panels

1. **Local model.** Show the offline runtime mode, model readiness and an explicit recheck. Explain that chat submission depends on the local model while saved history remains available. Omit numeric performance meters when the runtime supplies no live measurement.
2. **Data protection.** Show backup age, status and the next relevant action. Opening detail reveals the configured destination and a safe failure summary. This routes to existing recovery status. The staged restore tooling remains a separate workflow.
3. **Diagnostics.** Show disk sink condition, utilization of the bounded queue and dropped-event count. Recent events are collapsed into a short preview or opened in System. Use the existing bounded health refresh cadence and avoid repeatedly announcing rolling event updates.

The operational panels summarize results from runtime services. A stale or unavailable value is labeled as such. There are no weather, camera, clock, network radar or decorative system monitors in the shell.

## 7. Right-side coding assistant panels

The Coding Assistant replaces the reference's body display. Its vertical order follows **select evidence → inspect editor state → review changes**.

- **Saved revision.** Display the approved relative path and revision, shortening for layout only. Provide access to the full selectable ID and any available retained excerpt. Label historical selections when the service can establish that status. The card mirrors the composer attachment.
- **VS Code session.** Distinguish launch requested, waiting for pairing, paired with no shared context, last context shared, and disconnected. Show approved workspace, last shared file, version, dirty state and selection summary. IDs and bounded diagnostics belong in details. Label metadata as **Last shared** because edits since the last share may make it stale.
- **Patch review and recovery.** Show the editor-side entry points and a concise explanation of current trust and pairing prerequisites. Patch status is available from the VS Code extension, which displays its own actual results. The current desktop bridge does not drive editor commands or supply a desktop receipt feed. A later read-only summary requires an explicit scoped status contract before it can appear here.

The design keeps saved evidence, shared metadata and edit approval visibly separate. Switching the selected saved revision never substitutes an unsaved open buffer or alters an existing patch approval.

## 8. Bottom navigation dock

Use five consistently labeled destinations in this order. **Conversation · Evidence · Memory · Coding · System**. A sixth **Actions** destination appears only after the Phase 5 contract is available. Each item has a selected state, visible focus ring, accessible name and keyboard equivalent in the View menu. Coding focuses the inspector on wide layouts and opens it in compact layouts. Showing the dock changes views only. It never starts recording, pairs an editor, launches a tool or grants approval.

Use proposed shortcuts **Ctrl+1–5** for those destinations and **Ctrl+6** for Actions when available. **Ctrl+F** targets search in the active searchable view. **Ctrl+Enter** sends from the composer only. **Esc** dismisses a transient view or dialog without approving. **F6** and **Shift+F6** cycle visible dashboard regions, excluding the configured push-to-talk key from navigation assignments. Actions remain accessible by Tab and menu even if a shortcut is unavailable.

## 9. Conversation workflow

1. Select the approved project and a saved conversation or choose **New conversation**. The full path is available to distinguish projects with identical folder names. Restore only the current scoped history in sequence.
2. Draft or insert reviewed speech, optionally attach a saved revision, then explicitly **Send**. Display the verified local model and an actionable unavailable state if inference cannot start.
3. Stream the response, expose Stop immediately and retain meaningful terminal state. Keep a pending-save response visible with **Retry save**. Reload and search persisted history without requiring a working Ollama server.
4. For document questions, use **Evidence** to query approved excerpts. Show file, revision and page or text range, plus the excerpt itself. Show conflicting passages separately. When the retrieval layer returns insufficient evidence, state that result directly. If inline citation delivery is added later, an answer link resolves the same source, revision and locator under the live grant and returns focus to the link on close. Persisted links remain conditional on a durable receipt design.

### Evidence browser in the desktop

Open **Evidence** with **Ctrl+2**. Choose **Approve source file** or **Save source excerpts** through the existing source controls. Type search terms and press Enter to search the current published revisions. To search one historical published revision, paste its full 32-character ID in **Revision**. The inspector provides a selectable revision ID for future use.

Select a result with the arrow keys and press Enter or choose **Inspect selected citation**. Each result shows its passage number, project-relative path, page or text range, and a short revision ID. The inspector resolves the exact locator and shows selectable full IDs and retained text. Separate conflicting passages remain separately inspectable, and multiple citations for one deduplicated passage share its number. Empty searches report insufficient evidence. Image-only PDF pages need text extraction before they can produce matches. This browser uses the local store without Ollama.

The repository checks the live grant for search and lookup. Changing project, conversation or query clears the affected view and discards late results. The Windows acceptance scenario covers a keyboard-opened PDF locator, a historical text locator, a late result from a prior project and a grant revoked before inspection. [Desktop acceptance](../tests/test_desktop.py)

## 10. Code-context workflow

1. Choose **Select saved code** from the inspector or composer. List only eligible approved text revisions with saved excerpts. Surface the approved relative path and exact revision, including a historical revision when the user selects one.
2. Attach the chosen revision to the current conversation draft and return focus to the composer. Both views show the same attachment identity. Remove it explicitly or let the existing scope-change behavior clear it.
3. Submit an explanation request. The narrow saved-code broker validates the live scope and passes retained excerpts of that exact revision. The conversation identifies the file and revision used. The source file stays untouched.
4. If the revision is inaccessible, surface the reason and return to selection. Require a fresh user choice for any replacement revision. Shared editor metadata cannot become a code attachment.

## 11. VS Code workflow

1. Choose **Open in VS Code** for the approved project. Report that the launch was requested. Pairing has its own explicit state.
2. In JARVIS choose **Pair VS Code**, then enter the one-time invitation in the trusted local VS Code window using **STYLUS JARVIS: Pair**. Keep the invitation confined to the transient dialog and existing flow. It does not appear in the transcript, diagnostics, or remembered dashboard state.
3. From the intended editor window invoke **STYLUS JARVIS: Share Editor Context**. Display the last shared approved workspace, buffer identity summary, dirty state, version, selection and available diagnostics. Different windows and similarly named roots remain distinguishable.
4. On expiry, disconnect, context change or grant refusal, clear stale editor details immediately and show how to pair again. A new pair does not restore the previous session's approval.

The Coding card labels the workspace and buffer as **Last shared**. Version and unsaved state describe that snapshot. **View shared context** opens the full metadata after grant validation. The card lists the real VS Code commands for patch preview and outcome reconciliation.

## 12. Patch review workflow

1. In VS Code run **STYLUS JARVIS: Review Patch from Clipboard** for a supplied patch against open buffers. Inspect every target using the native diff and **Open Patch Diff**. The editor confirmation names the workspace and targets and binds approval to the digest.
2. Explicitly choose **Approve and Apply Patch** in VS Code. The bridge and extension revalidate grant, workspace, session, target versions and hashes. On drift, open a fresh proposal and review. The extension keeps native Undo available and saving remains under VS Code's control.
3. After disconnect, pair again with the same approved project. Select its workspace in a multi-root window, open the relevant buffers, and invoke **View and Reconcile Patch Outcome** in VS Code. Inspect per-target **Applied**, **Unchanged** or **Unresolved** results. Applied means the observed buffer matches the approved replacement hash.
4. Inspect unresolved targets before explicitly acknowledging them in VS Code. The project holds additional patch approvals while an operation remains uncertain. Acknowledgment permits a fresh proposal, while the recorded digest stays duplicate-blocked. Recovery performs no writes and provides no replay button.

## 13. Memory workflow

1. Open **Memory** and explicitly choose **Project memory** or **Personal memory**. Show the destination beside every write action. Keep Personal separate from project recall and export.
2. **Remember a fact** opens an editable statement and destination review. Store it only after confirmation. Show retained provenance and version where available. Resolve an evidence reference with the same scoped locator UI.
3. **Correct** shows the original and proposed text with the current version. Confirmation creates a superseding version under the same fact ID. A version conflict sends the user back to the latest confirmed fact. Preserve historical references where still authorized.
4. **Forget** identifies the destination and the effect on all fact versions before confirmation. The fact disappears from recall through the deletion ledger. Independently retained source and conversation evidence stays governed by its own rules.
5. **Export project** uses the existing confirmed local destination flow. Identify it as readable project data and scope it to current project records, excluding personal facts. Recovery and encrypted backups have a separate view.

### Memory browser in the desktop

Open **Memory** with **Ctrl+3**. Start in **Project memory** or explicitly select **Personal memory**. Select a fact to read its full text, current version, origin and stable ID. Linked facts offer **Inspect source citation**, which opens the same exact-locator readout used by Evidence. Close it to return to the fact.

Use **Correct selected fact** or **Forget selected fact** and confirm in the review dialog. An approved change refreshes the list. Changing the project or conversation clears the list and resets it to Project memory. A revoked grant or forgotten fact blocks a new inspection. The browser uses the local store without Ollama, and project export keeps its existing scope. [Windows desktop tests](../tests/test_desktop.py)

## 14. Diagnostics workflow

1. Open **System → Diagnostics** from the dock, the left card or a relevant error. Show a compact current health summary and the recent redacted event list.
2. Distinguish normal sink health, saturation with dropped events and degraded disk sink with the memory view still available. Show queue count/capacity, process-local drops, build identification and recorded writer timings with units. Identify counters that reset at restart.
3. Preserve focus and scroll position during refresh. Copy only the selected redacted records if the user explicitly requests it. Prompts, replies, transcripts, audio, pairing invitations and credentials stay outside diagnostics.
4. Route **Recovery** separately to backup age and destination checks. A diagnostic error or unavailable sink must leave chat cancellation operable. [Bounded diagnostics contract](windows-bounded-diagnostics.md)

**Ctrl+5** opens System. Use the arrow keys on the tab bar to switch between Diagnostics and Recovery. The Operations buttons open their matching tabs. Diagnostic refresh follows the latest event when the view is at the end and preserves the scroll position when reading earlier events.

## 15. Voice workflow

1. In Conversation choose a microphone and hold the configured key or **Hold to talk**. Display explicit recording feedback and show the assigned key. Keep the keyboard and typed path available with no mic.
2. Release to transcribe locally. Show a distinct transcription state followed by an editable review. **Add transcript to message** appends to the existing draft. **Discard** leaves the draft intact. Sending remains a separate action.
3. Turn on **Speak replies** explicitly. Reflect synthesis, playback and unavailable states visibly. Keep **Stop** accessible until playback and queued speech finish, even after the written reply completes. Respect microphone/playback coordination.
4. On device loss, scope change or interrupted capture, follow the existing cancellation and discard behavior. Device loss returns focus to the preserved draft. No microphone restart on reconnect. Leaving Conversation ends an active capture as an interruption and disables new capture until the composer is visible again. Keep an already reviewed transcript available in the same scope and keep shared Stop available for playback. Raw recording stays in the existing transient worker path. [Voice technical design](phase-3-technical-design.md)

The recording button displays the configured push-to-talk key. In transcript review, Tab moves from the text to **Add transcript to message** and **Discard**. Stop stays reachable when the Core shrinks or the user switches views.

## 16. PySide6 component hierarchy

```text
MainWindow (QMainWindow, existing close lifecycle)
├─ Menu bar and shared QActions
└─ Central shell (QWidget with QVBoxLayout)
   ├─ Scope and task strip (QToolBar or keyboard-ordered QWidget)
   ├─ Workspace splitter (QSplitter)
   │  ├─ Operational rail (QScrollArea → health and recovery cards)
   │  ├─ Work views (QStackedWidget)
   │  │  ├─ Conversation (QListView with typed turn model and text detail,
   │  │  │   search field, QPlainTextEdit composer, VoiceControls and review)
   │  │  ├─ Evidence (QListView or QTreeView and selectable excerpt detail)
   │  │  ├─ Memory (QListView, destination control and existing FactEditor)
   │  │  ├─ System (diagnostics and recovery views)
   │  │  └─ Actions (Phase 5 feature gate)
   │  └─ Coding inspector (QScrollArea → revision, editor and patch cards)
   └─ Navigation dock (exclusive QToolButtons, shared QAction routing)
```

Keep native widgets and accessible roles. The initial migration can retain the existing selectable plain-text transcript while the turn model is introduced. A structured turn view must retain keyboard text selection and full per-turn text access through a selectable detail widget. Use standard dialogs for fact confirmation, pairing and sensitive reviews. Set names, label buddies, reading order and visible focus. Restore focus to the originating control when a dialog closes. Do not move focus on stream fragments, health polling or background navigation changes. Verify Narrator can read the active destination, status and focused control without per-token announcements.

Use a UI presenter or adapters to map existing typed runtime, desktop, repository and bridge events into read-only views. Qt owns UI state and explicit intent. Existing services own authorization, effects and persistence. Keep widgets on the Qt thread, work on the existing async/runtime paths, and batch visual stream updates without modifying stored message order or Stop responsiveness. Scope-key asynchronous results and clear cached view data on grant or scope changes. Render retrieved text, file paths and diagnostics as text, with citation activation routed only through validated IDs. Save layout preferences separately from application records and credentials.

## 17. Window states and responsive behavior

| Condition | Behavior |
| --- | --- |
| Wide, at least 1320 DIPs | Three columns. Keep rails resizable and the center dominant. Preserve widths within minimum bounds. Target the main 1080p laptop at 100–125% scaling. |
| Compact, about 1000–1319 DIPs | Conversation plus Coding when selected. Move the operational rail into System. Collapse the Coding rail if it would compress the composer below its useful width. |
| Narrow or large Windows text | One work view at a time. Coding and System use the center surface through the same dock. Wrap scope controls and consolidate secondary actions into menus. Preserve labels and access to Send, Stop and navigation. |
| Short window | Limit panel heights, scroll inner content and keep composer transport and dock reachable. Allow the transcript and diagnostics to scroll independently. |
| First run or startup | Show local initialization and explicit project setup when ready. Do not enable project actions before scope validation. |
| Offline model unavailable | Keep saved history, Evidence and Memory accessible when the store and scope are valid. Disable Send with a reason and offer Recheck model. |
| Active generation, pending save, or lost connection | Keep the appropriate Stop or Retry save available. Show the affected subsystem and current state. Keep operation receipts separate from conversation save recovery. |
| Revoked grant or scope switch | Immediately clear prior evidence, fact list, saved attachment and editor details. Dismiss scoped review dialogs. Revalidate before delivering new content. |
| Restore after display change | Clamp saved geometry to the current screen's available work area. Apply the current layout breakpoint without discarding the in-scope draft. |

Test at 1920×1080 with 100%, 125% and 150% Windows scaling, plus a narrow window and increased text size. Breakpoints are design starting points in Qt logical pixels and should move if measured content width or accessibility needs demand it. Stop, focus indicators and dialog cancellation must remain reachable by keyboard in every layout.

## 18. Dashboard implementation roadmap

| Increment | Work | Dependency and exit check |
| --- | --- | --- |
| 1 · Shell and accessibility | Introduce palette, scope strip, three-column splitter and dock behind the existing desktop entry point. Reposition existing conversation, controls and dialogs. | Phases 1 and 3. Reopen history, verify focus order and Narrator at laptop scaling, stream and stop under representative load, and retain pending-save recovery. |
| 2 · Evidence and memory | Surface scoped evidence search and locator inspection over existing APIs. Add explicit fact browsing and move memory and export actions into the Memory view. | Phase 2. Verify PDF page and text range, historical revision resolution, conflicting evidence and abstention, strict project isolation, correction, forget and scoped export. Treat inline durable turn citations as separate contract work. |
| 3 · Coding, System and voice polish | Compose saved revision, approved VS Code launch and last-shared editor state in the inspector. Add editor-side guidance for patch recovery. Integrate bounded diagnostics, recovery details and voice review in their designated views. | Phase 4 core plus Phases 1–3. Verify exact historical revision and unchanged saved source hash, wrong-workspace refusal, stale versions, undo and disconnect recovery, voice/typing fallback, and diagnostic saturation without blocking Stop. |
| 4 · Phase 5 read surfaces | Add Actions only when the scoped role registry, policy broker and journal offer real data. Show intent, scope, dispatch/result state and actionable denials. | 5.1. Test typed scope, revoked grants, wrong targets and untrusted document instructions. Email and Research remain inactive in the offline role registry. |
| 5 · Integrated qualification | Run the approved offline study walkthrough on the MSI using the dashboard. Retain the build identity, owner disposition and acceptance evidence. | M2 · 5.3 after 5.1 and its existing prerequisites. Require at least 18 of 20 cited or abstention cases and zero cross-project disclosure. Measure warm first-text p95 against the five-second trial target and Stop feedback within one second. Include restore and offline evidence. |
| 6 · Phase 5 reviewed actions | Add exact file-operation review and per-target reconciliation. Show only supported named desktop actions, with explicit stopped or unresolved outcomes. | M3 · 5.2 after 5.1 and 4.2. Test changed targets, wrong-window focus changes, partial outcomes and no blind retry. |

Prioritize the shell and existing workflow regressions before moving authorization or runtime wiring. Keep the existing Qt test entry points until each replacement proves equivalent behavior on Windows. Dashboard completion should be tracked separately from the application release gates and from the remaining 4.3 verification work.
