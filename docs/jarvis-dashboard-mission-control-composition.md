# STYLUS JARVIS · Mission-control composition

**Visual design only.** This revision supersedes the shallow Core arrangement in the [previous visual proposal](jarvis-dashboard-visual-revision.md). The [approved dashboard architecture](jarvis-dashboard-architecture.md) remains the authority for scope, widgets, capability ownership, navigation and workflows.

## 1. Revised layout composition

Use the attached CYBER dashboard as the composition reference. Its strongest cues are an open dark field, a large circle near the optical center, quiet instrument groups at the edges, and a low-profile dock. The STYLUS JARVIS version uses that silhouette with its approved tools.

Give **JARVIS Core** the open upper half of the center column. Set the ring directly on the canvas, with generous space around the circumference and with the title and live status inside it. Position the existing **Stop** action immediately beneath it when available. **Conversation** occupies the lower center in a recessed panel, with search above the scrollable transcript and the composer anchored below it. It remains the default workspace, and typing and sending work from that screen.

**Operations** and **Coding Assistant** frame the open center as slim side rails with individually framed groups. Their outer edges align with the window margins. They use thin dividers and subdued surfaces so the center reads as one large field. The existing scope strip spans the top and the five-destination dock sits at the bottom.

[Revised desktop mockup](../outputs/jarvis-dashboard/mission-control-desktop.png)

## 2. Revised visual hierarchy

1. **Core first.** Make the ring the largest single graphic and give its active stroke the strongest sustained cyan accent. Keep the surrounding canvas visually quiet so the glyph and status read immediately.
2. **Conversation for work.** Make the lower-center workspace clear through type, labeled controls and a visible composer. Keep the accent on Send when enabled, with standard focus treatment throughout. The transcript can use the full panel width while conversational prose retains the approved readable line length.
3. **Side rails for checks.** Use smaller headings, aligned values and modest borders. Bring attention to an actual warning or unresolved state in the panel that owns it. Keep the selected dock destination visible with its label and accent underline.

Use the approved dark palette. Canvas `#0B1118`, panels `#111C27`, dividers `#304357`, text `#E4EDF6`, secondary text `#A9BDD0`, active cyan `#62D9F5` and secondary blue `#8BAFFF`. Event text and focus cues retain higher priority than the ring when the user is interacting with a control.

## 3. Updated wireframes

**Wide · three columns.** The circle stands free of a card. The top strip and dock span all three columns.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ STYLUS JARVIS     Offline     Project ▾     Conversation ▾     Local model  │
├─────────────────────────────────────────────────────────────────────────────┤
│ OPERATIONS                                                     CODING ASSISTANT
│ ┌──────────────┐                                               ┌────────────┐
│ │ Local model  │                  ╭───────────╮               │ Saved code │
│ │ Recheck      │               ╭──╯           ╰──╮            │ Revision   │
│ └──────────────┘              │    JARVIS CORE    │           └────────────┘
│ ┌──────────────┐              │         •••       │           ┌────────────┐
│ │ Recovery     │              │ Generating locally│           │ VS Code    │
│ │ Backup age   │               ╰──╮           ╭──╯            │ Last shared│
│ └──────────────┘                  ╰───────────╯               └────────────┘
│ ┌──────────────┐                       Stop                    ┌────────────┐
│ │ Diagnostics  │   ┌───────────────────────────────────────┐   │ Patch      │
│ │ Sink / queue │   │ Conversation                   Search │   │ guidance   │
│ │ Drops        │   │ Scrollable ordered transcript         │   └────────────┘
│ └──────────────┘   │                                       │
│                    │ Saved revision · Draft                │
│                    │ Hold to talk   Speak replies     Send │
│                    └───────────────────────────────────────┘
│           Conversation    Evidence    Memory    Coding    System          │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Compact laptop.** Follow the approved compact routing. Operations moves to System. Coding stays on the right when selected and space permits. With less height, the Core contracts before the transcript, composer or voice review.

```text
┌──────────────────────────────────────────────────────────────────┐
│ STYLUS JARVIS  Offline  Project ▾  Conversation ▾  Local model    │
├──────────────────────────────────────────┬───────────────────────┤
│              ╭───────────╮               │ CODING ASSISTANT      │
│              │JARVIS CORE│               │ Saved revision        │
│              │   Ready   │               │ VS Code session       │
│              ╰───────────╯               │ Patch guidance        │
│ Conversation                      Search │                       │
│ Scrollable ordered transcript            │                       │
│ Saved revision · Draft · Voice · Send    │                       │
├──────────────────────────────────────────┴───────────────────────┤
│     Conversation    Evidence    Memory    Coding    System       │
└──────────────────────────────────────────────────────────────────┘
```

At narrow widths use the approved one-view layout. The Core can collapse to a status line above Conversation. Evidence, Memory, Coding and System continue to occupy their approved views.

## 4. JARVIS Core visual specification

| Layer | Visual treatment | Meaning |
| --- | --- | --- |
| Outer boundary | 1 DIP quiet blue-gray stroke | Defines the indicator's extent and separates it from the background |
| State arcs | 2–3 DIP strokes in a fixed, separated pattern | The arcs act as a single state indicator. Their endpoints and coverage stay fixed across activity. |
| Inner boundary | Thin subdued outline around the readout | Separates the live label from the state ring |
| Readout | **JARVIS CORE**, state glyph and plain-language state centered inside | Reports the current task through text and shape as well as color |
| Action slot | One compact control centered below the ring when relevant | Presents existing **Stop** or **Retry save** with their approved eligibility and actions |

Use a **256 DIP** circle on the wide reference canvas, about **320 physical pixels at 125% scale**. The display can step down to a 144 DIP or 88 DIP circle when vertical space is limited, then use the 20–24 DIP status treatment on short or narrow windows. Keep the status label legible at each size. Preserve the 36 DIP action target where available. The state indicator itself stays out of the tab order.

Keep the existing state choices and priority. Use blue-gray with a check for **Ready**, cyan with an ellipsis for **Generating locally**, a microphone for **Recording**, a text glyph for **Transcribing locally**, a speaker for **Speaking**, and an amber alert for **Reply needs saving**. Show **Stopping** and **Local model unavailable** when applicable. Turn-specific terminal states remain on the turn. State changes update the glyph and label without shifting the layout or focus. A static state ring is the baseline. Leave the display free of tick marks, percentages, sweep animations and invented telemetry. Every ring stroke either defines the readout boundary or indicates state.

## 5. Exact panel placement

Coordinates are proposed **device-independent pixels**, measured from the drawable window origin. The reference is a nominal 1536 × 864 DIP canvas for a 1920 × 1080 display at 125% scaling. Rectangles use left/top origins. Adapt to real native chrome and available work area using the reduction rules below.

| Panel | X / Y | Width × height | Placement details |
| --- | --- | --- | --- |
| Shared scope strip | 0 / 0 | 1536 × 48 | Brand, offline policy, project, conversation and model in existing order. Shared task controls remain reachable when the active view is outside Conversation. |
| Operations | 20 / 80 | 250 × 724 | Heading at y=80. Model card at y=116, Recovery at y=244, Diagnostics at y=356. Use 12 DIP gaps and allow vertical scrolling for content growth. |
| Core stage | 282 / 56 | 902 × 394 | Open canvas. Put the 256 DIP circle at x=640, y=120, centered on x=768, y=248. Put the existing action slot below at y=392. |
| Conversation | 282 / 450 | 902 × 354 | Header and search in the first 44 DIPs. Transcript starts at y=494 and has about 198 DIPs in the nominal state. Composer and voice transport occupy the lower 112 DIPs and can grow when review is visible. |
| Coding Assistant | 1196 / 80 | 320 × 724 | Heading at y=80. Saved revision at y=116, VS Code session at y=264, Patch guidance at y=456. Use 12 DIP gaps and allow vertical scrolling. |
| Bottom dock | 444 / 816 | 648 × 40 | Centered. Conversation, Evidence, Memory, Coding and System retain their approved order and routing. Future destinations still follow existing availability rules. |

The nominal layout reserves a **160 DIP transcript viewport** wherever the content area permits. If the composer grows, transcript review opens, or Windows scaling reduces the useful height, reclaim space from the Core first. Start by reducing its open margins, then step down the diameter and move the Conversation boundary upward. Keep the composer, Stop and dock reachable throughout. In the shortest windows the body scrolls as needed and the Core falls back to a compact text indicator. These are layout rules only. They never change selection, microphone behavior or task state.

## 6. Comparison against the current approved dashboard

| Area | Approved baseline and previous visual proposal | Mission-control composition |
| --- | --- | --- |
| Central silhouette | Conversation-led column with a compact activity header. The previous mockup set the ring beside its text in a shallow panel. | The ring stands alone in an open central field with the live label inside. It sets the overall silhouette. |
| Conversation | Central primary workspace under the task header. | Same controls and default workflow in a recessed lower-center workspace. The Core yields height first when more room is needed for work. |
| Side rails | Operations left and Coding Assistant right, with the approved groups. | Same side and widget assignments. Quiet separated cards and aligned upper edges visually frame the circle. |
| Scope and dock | Shared scope strip and fixed-order five-item dock. | Same destinations and actions. A lower-profile centered dock gives the composition a clear bottom edge. |
| Status and ownership | Existing task, model, voice and editor states. VS Code owns patch review, approval, edits and recovery. | The same task state gets a larger visual treatment. Patch affordances still direct the user to VS Code. |

The desktop image depicts a streaming turn with illustrative project values. The wireframes and placement table govern the exact sizing and control visibility where the image simplifies them. This is design evidence. Laptop-scale fit and keyboard behavior remain subject to the existing dashboard acceptance checks.
