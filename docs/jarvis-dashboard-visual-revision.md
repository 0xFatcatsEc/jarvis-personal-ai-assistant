# STYLUS JARVIS visual revision · Core status panel

This visual revision applies to the [approved dashboard architecture](jarvis-dashboard-architecture.md). The C.Y.B.E.R. reference informs the thin-framed side panels, near-black surfaces and central status circle. STYLUS JARVIS uses that circle to communicate the current task and keeps the conversation in the center. Scope, navigation, workflows, permissions and service ownership follow the approved design.

## 1. Revised visual layout

The **JARVIS Core** becomes a shallow status panel across the top of the Conversation column. Center the roundel and its adjacent label as one group. Place the current action beside the status when available. The left and right panel headings align with the top of the Core to frame it. Give the Core the strongest cyan accent and reserve brighter fills for the primary action and keyboard focus. Use the approved canvas `#0B1118`, surface `#111C27`, divider `#304357`, text `#E4EDF6` and cyan `#62D9F5`.

Below the Core, **Conversation** gets the largest uninterrupted surface. Its search stays at the top, its transcript grows into all remaining height, and its composer and voice controls stay at the bottom. The first visible message sits directly below the Conversation heading. The status panel never overlays the transcript, and changes in status never resize it.

[Wide desktop concept](../outputs/jarvis-dashboard/visual-revision-desktop.png)

## 2. Updated wireframes

**Wide · 1920×1080 at 125% Windows scaling.** Use the approved approximately 250 / 920 / 320 DIP rail targets, negotiating around native chrome and available width. At the illustrative 864-DIP screen height, budget about 112 DIPs for the Core. Keep enough vertical space for the transcript and an expanded voice review or multiline draft.

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ STYLUS JARVIS   Offline   Project ▾   Conversation ▾   Qwen 3 4B              │
├──────────────────┬───────────────────────────────────┬────────────────────────┤
│ OPERATIONS       │    ◉    JARVIS Core               │ CODING ASSISTANT       │
│ Local model      │         Generating locally  Stop  │ Saved revision        │
│ Recheck model    ├───────────────────────────────────┤ Select / Remove       │
│                  │ Conversation                  ⌕ │                        │
│ Data protection  │                                   │ VS Code session       │
│ Backup status    │ Ordered transcript                │ Open / Pair           │
│                  │ Streaming turn                    │ Last shared context   │
│ Diagnostics      │                                   │                        │
│ Sink / queue     │                                   │ Patch review          │
│ Dropped events   ├───────────────────────────────────┤ Commands in VS Code   │
│                  │ Saved revision · Draft            │                        │
│                  │ Hold to talk · Speak replies  Send│                        │
├──────────────────┴───────────────────────────────────┴────────────────────────┤
│          Conversation       Evidence       Memory       Coding       System  │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Compact · 1000–1319 DIPs.** Conversation and Coding share the screen when Coding is selected and space allows. Operations is under System. At narrow widths the same content uses the approved one-view layout. A short window or larger text reduces the status presentation first.

```text
┌───────────────────────────────────────────────────────────────────────┐
│ STYLUS JARVIS   Offline   Project ▾   Conversation ▾                  │
├───────────────────────────────────────────────┬───────────────────────┤
│ ◉  JARVIS Core   Generating locally     Stop  │ CODING ASSISTANT      │
├───────────────────────────────────────────────┤ Saved revision        │
│ Conversation                              ⌕ │ VS Code session       │
│ Ordered transcript                            │ Patch review          │
│                                               │                       │
│ Draft · Voice controls · Send                  │                       │
├───────────────────────────────────────────────┴───────────────────────┤
│     Conversation      Evidence      Memory      Coding      System   │
└───────────────────────────────────────────────────────────────────────┘
```

## 3. JARVIS Core design specification

- **An event-driven status indicator.** Use one circular outline and one state glyph. The outline is the boundary of the indicator. The glyph, outline treatment and adjacent text convey the same current state. The circle represents no scale, progress, resource use or elapsed time.
- **Dimensions.** Target a 76–84 DIP circle within a 104–120 DIP wide-layout band. Cap the band at roughly 18% of the available central work area and choose compact treatment sooner if the timeline, draft or voice review needs space. Use a 32–40 DIP circle within a roughly 56 DIP compact band. At minimum height, a 20–24 DIP status glyph and wrapping label are enough. Focus indicators and critical text retain full size.
- **Layout stability.** The ring and glyph are read-only and outside the tab order. Stop and Retry save remain explicit controls with their existing availability. When leaving Conversation, the shared task controls in the scope strip retain the current status and the available Stop action. Within Conversation, the wide Core presents that same task control to avoid duplicate buttons.
- **Accessibility.** Announce meaningful transitions once and expose the full status as text. Keep focus on the current control during streaming and background updates. Shapes and text carry meaning when color is unavailable. Static rendering is the default in all states, including High Contrast and reduced-motion settings.

| Observed state | Roundel treatment and visible label | Existing action or context |
| --- | --- | --- |
| Model verified and idle | Thin muted-blue outline with check · **Ready** | Composer stays available |
| Local generation or stopping | Solid cyan outline with ellipsis · **Generating locally** or **Stopping** | Existing **Stop** while eligible |
| Microphone recording | Solid outline with microphone glyph · **Recording** | Existing hold-to-talk control and release behavior |
| Local transcription | Blue outline with text glyph · **Transcribing locally** | Existing transcript review when available |
| Speech playback | Blue outline with speaker glyph · **Speaking** | Existing **Stop**, including after the written response ends |
| Reply needs saving | Amber outline with alert glyph · **Reply needs saving** | Existing **Retry save** |
| Model unavailable | Muted outline with alert glyph · **Local model unavailable** | **Recheck model** in Operations |

If channels overlap, use one label at a time. Show pending-save and stopping feedback ahead of active work. Prefer current microphone capture or transcription over ordinary generation, then show speech when it outlasts the written turn. Voice and Conversation retain their own contextual status. Keep cancellation, interruption, token limit and failure on the relevant turn and present existing actionable feedback without obscuring an active operation.

## 4. Visual hierarchy changes

1. **First glance** goes to the roundel, current state and any immediate action. The center accent tells the user whether JARVIS is busy or needs attention.
2. **Reading and typing** stay dominant by area. Conversation has the largest scrollable region and its composer retains a fixed position. Keep the approved 75–95 character reading measure as space allows.
3. **Peripheral checks** use quieter borders and compact labels. Highlight degraded or unavailable states where they occur. Keep the dock visible and use an active underline or fill plus focus indication.

## 5. Widget placement rationale

| Placement | Rationale |
| --- | --- |
| Shared scope strip | Project, conversation, model and offline policy remain visible while the user changes views. |
| Top of Conversation | The activity header gains a distinct shape and immediate status without inserting UI into the reading or writing surface. |
| Operations left | Model readiness, backup state and diagnostics remain grouped. Their details stay reachable in System. |
| Coding Assistant right | Saved revisions and the last shared VS Code context stay in sight during code discussions. Patch guidance still points to the editor for review and recovery. |
| Dock bottom | Destination labels and keyboard routes retain the same positions. Compact layouts reuse the same navigation when rails move. |

## 6. Comparison with the previous dashboard proposal

| Area | Previous proposal | Visual revision |
| --- | --- | --- |
| Central identity | Compact task text above conversation | Bounded, circular status indicator and explicit task label form the focal point |
| Workspace balance | Conversation header and uniform card framing | Bright status accent above a larger, quieter chat surface framed by the two rails |
| Conversation | Central transcript, search and anchored composer | Same workspace and controls, with the Core yielding space first on short windows |
| Rails | Three operational summaries and three coding groups | Same groups, with denser alignment and subdued surfaces that frame the center |
| Compact layout | Conversation and optional Coding, Operations under System | Same routing with a single-line Core status treatment |

The concept image uses a streaming example and illustrative project values. These wireframes and specifications define control availability, focus order and dimensions where a static image simplifies them. Before adopting the visual layout, check that a multiline draft, a transcript review and a visible Stop action can coexist at 1080p with 125% and 150% scaling.
