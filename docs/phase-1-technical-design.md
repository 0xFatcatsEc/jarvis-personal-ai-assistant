# STYLUS JARVIS Phase 1 technical design

**Foundation · Design baseline 1.0 · 22 November 2026**

Phase 1 delivers one complete path on Windows 11: start from provisioned local assets, select a project, send a text turn to Qwen 3 through Ollama, stop it if needed, and recover the conversation after restart. A missing model must still let the owner inspect saved history. A database that cannot safely accept writes must prevent the application from claiming a message was saved.

## Scope and decision authority

| Backlog feature | Foundation output | Handoff |
|---|---|---|
| 1.1 Local runtime baseline · M0 | Hardware inventory, versioned 20-question fixture, verified offline asset manifest and measured model decision | Supplies the profile used for subsequent runtime tests |
| 1.2 Project session and chat · M1 | Project picker, immutable request scope, SQLite store, streamed replies, cancellation and searchable ordered history | Memory and knowledge features can use the same scoped repositories |
| 1.3 Offline controls and packaging · M2 | Offline startup, network evidence, pinned install, bounded diagnostics and clean-profile rehearsal | Contributes evidence to M2 qualification, backlog 5.3 |

M1 and M2 are product milestones shared with other phases. Foundation provisions Whisper and Piper assets and records voice license information under 1.1.2.1. Voice capture, speech output, document indexing, durable facts, user-facing backup/restore, desktop tools, editor IPC and online providers retain their assigned backlog owners. The Phase 1 test corpus supplies fixed prompt evidence for model evaluation until retrieval is available.

**Baselines:** [V2 architecture](../STYLUS%20JARVIS%20Architecture%20Review%20and%20V2%20Design.docx), [PRD](../STYLUS%20JARVIS%20Product%20Requirements%20Document.docx), [development backlog](../outputs/stylus-development-backlog/STYLUS%20JARVIS%20Development%20Backlog.xlsx), [repository blueprint](repository-structure.md). Module paths below are relative to `src/stylus_jarvis/`. Interface names describe contracts for implementation. Proposed operational defaults are subject to the M0 measurements.

## 1. Application bootstrap flow

**Responsibilities.** `__main__.py` delegates to `bootstrap.py`, the sole composition root. Bootstrap establishes one owner per Windows user profile, publishes startup progress and exposes only operations whose dependencies are healthy. Qt owns the main thread throughout.

**Internal interfaces.** The entry point requests a launch for the current user. Bootstrap reports a startup stage and a capability snapshot to the window: configuration valid, store available, history readable, model verified, project active. Shutdown returns a disposition distinguishing clean exit from recovery required.

**Data flow.**

1. Create the Qt application and acquire a per-user process lock before opening storage. A second launch reports that JARVIS is already open.
2. Resolve the user profile, start bounded in-memory diagnostics and show a keyboard-accessible startup window. Read and validate settings and the release manifest.
3. Initialize the persistent log sink if available. Start the storage owner off the UI thread, validate or migrate the store and reconcile interrupted turns.
4. Construct scoped services and the local-only inference adapter. Probe the configured Ollama instance asynchronously. Load the project list from the validated store.
5. Enable history when storage is ready. Enable Send only when the current project is valid, persistence is writable, the model is verified and a generation slot is available. Status changes reach Qt as queued events.

**Dependencies.** Windows user identity and profile, PySide6, settings, diagnostics, packaged migrations, repositories, scheduler and inference adapter. Provisioning runs separately so imports and startup cannot download assets.

**Failure scenarios.** A failed lock cannot trigger a second writable instance. Invalid settings open the repair view. A failed schema check blocks normal startup and preserves the database. An Ollama timeout disables generation while history remains accessible. A partially constructed application closes acquired resources in reverse order.

**Testing strategy.** Exercise clean and existing profiles, duplicate launch, missing manifest, unreadable data directory, forced failure after each acquisition and absent Ollama. Verify the window remains responsive and a subsequent launch can reacquire every released resource. Repeat clean startup in both offline test conditions in the release matrix.

## 2. Configuration system

**Responsibilities.** `settings.py` owns validated nonsecret configuration. Distinguish packaged deployment facts, user preferences and live session authority so changing a preference cannot grant file access or redirect prompts to a remote server.

| Source | Contents | Resolution and persistence |
|---|---|---|
| Packaged release manifest | Build and schema versions, permitted local model tags and expected digests, supported asset profiles | Validate against the pinned offline distribution. A user setting may select a provisioned profile. |
| Application defaults | Offline mode, loopback address, one generation slot, bounded timeouts and queues | Establish safe values on first launch. |
| Per-user settings | Versioned TOML under local app data, selected permitted profile, UI preferences and diagnostic level | Valid user values override defaults within manifest and policy limits. Write a temporary sibling then atomically replace. |
| Session context | Active project, grant revision, run identity and cancellation | Resolve from the authenticated session and repositories. Scope and authority never come from a settings file. |

**Internal interfaces.** Load returns a typed, immutable settings snapshot or field-level validation issues. Save accepts a validated change set and returns a new settings revision. A separate path resolver supplies config, data, log and asset locations. Runtime gets only the view it needs.

**Data flow.** Resolve Windows local app data → load manifest and defaults → validate supported file version → overlay allowed preferences → validate the combined profile → publish snapshot. Apply UI preferences immediately. Apply model changes between turns after a fresh digest check. Foundation keeps external providers disabled for every configuration.

**Dependencies.** Standard TOML reader, typed validation, OS path resolution and packaged manifest. Proposed data filename is `%LOCALAPPDATA%\StylusJarvis\data\jarvis.sqlite3`. Validate the resolved data location as local and outside synced project roots. Production settings cannot override this with a coursework path.

**Failure scenarios.** Preserve malformed or newer-version settings for recovery and explain which field needs attention. First launch with an absent file uses defaults. Reject non-loopback model endpoints, unrecognized profiles and out-of-range limits. A failed save leaves the previous snapshot active.

**Testing strategy.** Table-driven tests cover precedence, missing and future versions, invalid values, external addresses, failed replacement and a model change during generation. A standard-user install must load without elevated privileges or credentials.

## 3. Dependency injection design

**Responsibilities.** Bootstrap manually constructs concrete implementations and injects narrow ports into consumers. This keeps the same coordinator usable in the desktop application, deterministic tests and fault-injection runs.

| Consumer | Interface supplied | Lifetime and ownership |
|---|---|---|
| Main window | Session commands, turn commands and typed runtime events | Window subscribes for its lifetime and renders events on the Qt thread |
| Session service | Project and conversation repositories, identity source and grant reader | Process service; active selection has a changing revision |
| Coordinator | Scope validator, conversation repository, scheduler, model generation port, event sink, clock and ID source | Process service; creates one cancellation handle and immutable context per accepted turn |
| Model adapter | Validated local profile, bounded loopback transport and monotonic clock | Process adapter; stream resources belong to the active run |
| SQLite repositories | Thread-owned connection factory and one writer queue | Process storage owner; connections close on their creating threads |

**Internal interfaces.** Ports in `contracts/ports.py` describe model probing and generation, scoped reads and writes, scheduling and cancellation. `contracts/context.py` carries immutable identities and grants. `contracts/messages.py` defines commands, streamed events, receipts and failure categories. Callers see committed results or typed failures.

**Data flow.** Bootstrap constructs adapters from validated settings, binds ports to services and supplies a small command surface to the window. Events return through a UI-thread dispatcher. The repository accesses SQLite and the inference adapter accesses Ollama. Neither dependency leaks into the window or contracts.

**Dependencies.** Python constructor injection, shared contracts and Qt dispatch at the UI edge. The production graph contains only Phase 1 capabilities. No tool execution path is registered in Foundation.

**Failure scenarios.** Missing required bindings stop composition before Send becomes available. Partially initialized resources have exactly one shutdown owner. A stale event cannot obtain a new session from a global registry.

**Testing strategy.** Substitute an in-memory repository, scripted model stream, deterministic IDs and fake clock independently. Contract-test real adapters against the same port expectations. Check import direction in `tests/architecture/` and exercise the actual production composition with a temporary profile.

## 4. Logging architecture

**Responsibilities.** `runtime/diagnostics.py` supplies local performance and reliability evidence. SQLite remains authoritative for conversations and turn outcomes. Diagnostic loss must never change whether a turn is considered committed.

**Internal interfaces.** A diagnostic event carries an allowlisted event name, UTC time, severity, component, opaque correlation ID, outcome code and optional numeric measurements. Use monotonic time for durations. Examples are model probe duration, first visible answer latency, database writer wait, queue depth, build version and model digest.

**Data flow.** Adapter or runtime → structured field validation → bounded process queue → background rotating local JSON-lines sink under `logs\`. The UI reads a small health summary. Proposed defaults are three 2 MiB files and a 256-event queue. Coalesce low-priority events under pressure and count drops. A startup ring buffer bridges the interval before paths are verified.

**Dependencies.** Python logging infrastructure, local filesystem, wall and monotonic clocks. Opt-in verbose diagnostics use the same allowlist. Prompts, transcripts, paths, project names, model thinking, raw exception strings, provider bodies and environment dumps are excluded.

**Failure scenarios.** On a full disk or denied permission, retain a bounded in-memory summary, surface degraded diagnostics and keep history writes governed by their own commit result. Avoid recursively logging sink failures.

**Testing strategy.** Seed secret-like markers in a prompt, file path and transport error. Scan active and rotated files for those markers. Saturate the queue and simulate an unwritable sink. Verify bounded disk usage, observable drop count and uninterrupted UI cancellation.

## 5. Ollama integration architecture

**Responsibilities.** `inference/ollama.py` implements the generation port. `inference/router.py` selects the provisioned local profile. Start qualification with Qwen 3 4B, a 4,096-token context trial and one in-flight generation. Record the selected digest and actual hardware behavior before fixing the release profile.

**Internal interfaces.** Probe returns reachable, model missing, digest mismatch or verified. Generate accepts scoped ordered messages, profile, output budget and cancellation handle. It emits answer fragments, terminal metadata or a typed failure. The adapter accepts only a numeric loopback destination, bypasses proxy discovery and refuses redirects.

**Data flow.** Query the local model inventory and compare its digest to the manifest before enabling generation. The context builder selects only completed turns from the active conversation plus the new user message, preserves order and trims oldest complete turns to fit the budget. Reject an oversized current message with an editable draft. Send the request to the streaming chat endpoint, parse complete frames across arbitrary network chunk boundaries, and expose only visible answer content. Require a valid terminal frame; commit completion through storage before displaying “saved.” [Model inventory](https://docs.ollama.com/api/tags) · [Streaming chat](https://docs.ollama.com/api/chat)

**Dependencies.** Pinned Ollama runtime, verified locally installed Qwen profile, scheduler, bounded HTTP transport and local app packaging. Use a managed local-only runtime profile with cloud functionality disabled. Qualify the exact distribution and updater behavior. An offline-mode toggle alone cannot enforce the Windows updater’s network behavior. Verify process-level outbound restrictions for the packaged stack while allowing loopback. [Ollama local configuration and Windows updates](https://docs.ollama.com/faq)

**Failure scenarios.** Missing model or wrong digest leads to offline provisioning guidance and a manual recheck. Connection loss, malformed frames and model errors terminate the attempt. Memory exhaustion offers a smaller provisioned profile for a new attempt. Close the stream on stop and discard late frames by run ID. Never auto-replay a partially streamed answer. Proposed initial limits are 3 seconds for the local probe, 60 seconds for first activity and 30 seconds of subsequent inactivity; benchmark cold-start behavior separately.

**Testing strategy.** Replay split UTF-8 frames, multiple frames in one read, model errors, missing terminal frames, slow streams, cancellation and mismatched digests. On the MSI, measure user-visible text rather than first transport activity or thinking output. Record 20 warm turns with VS Code open, cold start separately, peak RAM/VRAM and fixture answer quality.

## 6. Database initialization architecture

**Responsibilities.** `storage/database.py` owns initialization, version checks and connection lifetimes. `storage/repositories.py` owns all application writes. The data file, WAL and shared-memory sidecars stay on the same local disk. [SQLite WAL behavior](https://sqlite.org/wal.html)

**Internal interfaces.** Open returns a store capability and schema version. Migrate accepts the packaged ordered migration set and yields a verified version. Reconcile reports counts of unfinished turns marked interrupted. Repository commands return a durable receipt only after commit.

| Initial record | Identity and essential constraints |
|---|---|
| Schema migrations | Unique migration version and immutable package checksum; update the ledger in the migration transaction |
| Projects | Stable UUID, Windows owner identity, display name, canonical root identity, grant revision and archive state; unique root per owner |
| Conversations | UUID, owning project foreign key, title and timestamps; project scope required for every query |
| Turns | UUID, conversation foreign key, client submission ID, state, model digest, start/end times and sanitized failure code; unique submission per conversation |
| Messages | UUID, conversation and turn references, sequence, role and text; unique sequence per conversation and one message per turn/role; enforce matching conversation for each turn |

**Data flow.** Acquire the process lock → validate data path and write access → open the writer connection on its owning thread → enable and verify foreign keys on each connection, WAL and the chosen durability setting (proposed FULL) → inspect migration ledger → take a consistent pre-upgrade snapshot for an existing store → apply each pending migration transactionally → verify schema and constraints → reconcile interrupted turns → open scoped readers and publish readiness. Use SQLite’s snapshot facility for live stores. [SQLite backup API](https://sqlite.org/backup.html)

**Dependencies.** Bundled SQLite with FTS5 available for later evidence indexing, packaged `0001_initial.sql` and subsequent migrations, a serialized writer and short-lived read transactions. Only schema work and its own version marker share a migration transaction. Initialize WAL before beginning migrations.

**Failure scenarios.** Too-new schema, corrupt file, checksum disagreement, failed snapshot or failed migration blocks normal writes. Preserve the original store and show a recovery action. Never replace a failed store with a blank database. Use a bounded busy wait, then return store busy; a pinned reader delaying a checkpoint raises a diagnostic. Rollback pairs the matching application build with its snapshot.

**Testing strategy.** Use real files on a Windows temporary local volume. Cover first open, second open, concurrent readers, foreign-key violations, duplicate sequences, newer schemas, interrupted migrations and full-disk simulation. Compare records before and after a migration rehearsal. Test the frozen earlier-schema fixture for the first release.

## 7. Project selection architecture

**Responsibilities.** `runtime/sessions.py` owns the active selection. The PySide6 picker renders labels and canonical roots to distinguish similarly named projects. Selecting a project opens a scoped conversation context. File access is a separate brokered capability introduced later.

**Internal interfaces.** List projects for the signed-in owner, register a local root, activate a project, open a conversation within it and capture an immutable request context. Context includes user ID, project ID, conversation ID, offline mode, grant revision, selection generation and request ID. An account field stays empty in Foundation.

**Data flow.** User chooses a folder → resolve local root and canonical identity → look up or register within owner scope → confirm selection in the UI → increase selection generation → query only that project’s conversations. Resolve IDs from the session at submit time. Check scoped membership on storage access and check grant revision before dispatch and delivery.

**Dependencies.** Windows path resolution, project repository, grant reader, runtime and keyboard-accessible picker. Use case-insensitive identity rules for normal Windows roots and resolve aliases before duplicate checks. Store labels independently from identity.

**Request binding.** The coordinator retains the immutable owner, project, conversation, offline mode, grant revision and selection generation, and associates each event with the submission UUID. The local model receives the scoped message list. SQLite validates owner and membership against the live project revision. The coordinator checks again after the root filesystem check, before emitting each fragment, and before returning a content-bearing receipt. The desktop validates the captured scope before publishing buffered history or refreshed conversation titles.

**Failure scenarios.** A missing or moved root is marked unavailable; allow scoped history inspection and require explicit rebind before starting new work. A folder path that resolves outside the permitted local-root policy is rejected. Switching projects cancels outstanding delivery, clears the previous view and invalidates queued UI events. Pending terminal bookkeeping can settle only against the original turn.

**Testing strategy.** Register identical display names at two roots, two aliases for the same root, an inaccessible folder and a renamed root. Switch projects and revoke a grant while frames are in flight. Check history, search results, UI events and submission behavior for zero cross-project disclosure.

## 8. Conversation persistence architecture

**Responsibilities.** The coordinator controls turn state. Repositories guarantee ordering and idempotent submission. The window may show streamed text as provisional while it awaits a durable receipt.

**Internal interfaces.** Begin turn accepts a scoped submission ID and user text. It returns the original turn on a same-payload retry and rejects a conflicting payload reusing that ID. Checkpoint accepts a run ID, increasing checkpoint ordinal and a bounded partial reply. Finalize accepts an expected active state and one terminal outcome. History and search accept scope, conversation filter and page cursor.

**Data flow.**

1. Validate current grant, conversation membership and model readiness; reserve the single slot. In one transaction allocate the next sequence numbers, save the user message and assistant placeholder, and create the turn. A failed transaction releases the reservation and preserves the draft.
2. Dispatch after commit. Forward answer fragments to the current view as provisional. Coalesce partial snapshots, initially at most once per second per active turn. Persist an absolute text prefix with a monotonic ordinal so repeated or out-of-order writes cannot duplicate text.
3. Serialize terminal decisions in the coordinator. On success, commit final text and completed state in one transaction; on stop, retain the available prefix and mark cancelled. Transport failures record failed; startup reconciliation marks still-active turns interrupted. Only completed exchanges enter automatic history context.
4. Reopen history from the scoped repository, ordered by stable sequence and paginated. Search within the chosen project and return the originating thread and message. Begin with a scoped text query for chat history; Phase 2 owns the document evidence index.

**Grant revocation.** Schema migration 0002 records the admission grant revision on each new turn. During finalization, a changed revision permits a single status-only transition for that original active turn. SQLite commits `failed`, the `scope` error and the end time, preserving the last authorized checkpoint. The caller then receives a scope failure. Retrying a pending save uses the original revision even after the user reselects the conversation. If revocation follows a completed commit, the completed row remains durable and the stale receipt is withheld. Earlier schema versions have no admission revision to recover. Their terminal records remain readable under a current grant, and startup reconciliation handles any interrupted legacy turn.

**Dependencies.** Session context, coordinator, scheduler, model events, writer queue and monotonic IDs for checkpoints. The database assigns conversation order transactionally. Wall-clock timestamps are for display.

**Failure scenarios.** If the process dies after submit but before generation, the saved user message survives and the turn reopens interrupted. Crash after completion commit but before UI acknowledgment returns the existing completed turn on retry. A late chunk cannot overwrite a terminal row. On disk-full at finalization, label the visible reply unsaved and retain it in memory for an explicit save retry. Reconcile ambiguous commits by reading the turn first.

**Testing strategy.** Kill the process between submit, first chunk, checkpoint, terminal commit and UI receipt. Double-submit a command, race cancel with completion, delay a checkpoint until after finalization and switch projects during search. Assert exactly one user message per submission, deterministic order, truthful state and no cross-scope history.

## 9. Runtime lifecycle

**Responsibilities.** `runtime/coordinator.py` owns active turns, `runtime/scheduler.py` owns the single inference reservation, and bootstrap owns application shutdown. Model state, database readiness and application lifecycle are independent so a failed probe cannot make an otherwise healthy database inaccessible.

| Application state | Entry and allowed behavior | Exit |
|---|---|---|
| Starting | Show progress and allow closing. Run validation and recovery. | Ready, degraded, recovery required or stopping |
| Ready | Project picker and history available. Send also requires an active valid scope and free slot. | Degraded on dependency loss; stopping on exit |
| Degraded | Show capability-specific status. History remains usable if storage is verified. | Reprobe or repair the failed dependency and recompute readiness |
| Recovery required | Show recovery diagnostics and safe retry for a blocked store or configuration. | Restart validation after repair or stop |
| Stopping | Reject new work, cancel active transport, settle writes and close owned resources. | Stopped |

**Internal interfaces.** Runtime exposes submit, stop turn, switch project, retry dependency and request shutdown. Events carry run identity, selection generation and event sequence. A slot remains held until the old transport is closed and its worker has settled. Foundation rejects a second submission as busy and preserves its draft.

**Data flow.** UI commands enter via queued delivery. Blocking HTTP and store operations execute off the Qt main thread. Workers post typed events back; widgets update only on the Qt thread. Stop immediately acknowledges the UI, requests cancellation, suppresses further visible text and settles the stored state. A completion already durably committed remains completed.

**Dependencies.** Qt event loop, bounded worker queues, writer and model transport. On exit, disable commands, stop active work, drain accepted writes with a proposed five-second grace period, close owned readers/writer, flush diagnostics and release the process lock. An independently running Ollama service remains owned by its operator.

**Failure scenarios.** Repeated close or cancel is idempotent. On shutdown timeout, show the unresolved save state while the UI is available; an OS-forced exit relies on startup reconciliation. After sleep/resume, reprobe model health and recheck the active grant. An interrupted turn is never silently resent.

**Testing strategy.** Use a fake clock and stalled workers to test stop feedback within one second, close during migration or finalization, suspend/resume, repeated close, and late callbacks after window destruction. Follow with a real Windows reboot and a timed stop during local generation.

## 10. Error handling strategy

**Responsibilities.** Translate vendor errors at adapter boundaries into a shared failure envelope. Preserve enough information to recover the operation and give the owner one useful next action.

**Internal interfaces.** Failure envelope fields are stable category, component, request/run correlation ID, retry policy, durability status, user-facing action and safe diagnostic code. Cancellation is a user outcome. Central error presentation consumes the same envelope across startup, session and model views.

| Failure category | Visible behavior and recovery |
|---|---|
| Configuration or manifest invalid | Identify the invalid field or asset, keep original files and allow local repair and recheck. |
| Store busy or unavailable | Keep draft, wait within a bounded deadline and report uncommitted work. Inspect an uncertain commit by submission ID before offering retry. |
| Schema incompatible or corrupt | Block mutation, preserve files, and offer matched-build/snapshot recovery. |
| Project or grant changed | Stop delivery, clear stale events and require a new selection or authorized submission. |
| Model unavailable or stream invalid | Keep history available, mark the attempt truthfully and offer a fresh explicitly requested attempt after recheck. |
| Offline policy violation | Block before outbound dispatch and record a sanitized event. Keep the user’s local draft. |
| Unexpected internal fault | Stop the affected operation, retain its correlation ID, settle resources and show restart or local recovery according to durability state. |

**Data flow.** Adapter catches and classifies failure → coordinator selects permitted recovery → storage reconciles any uncertain result → UI displays outcome → diagnostics records allowlisted fields. Retry read-only health checks with a deadline. Each explicit regeneration gets a new attempt identity and links to the original exchange.

**Dependencies.** Shared message contracts, per-component translators, transaction receipts, scoped event dispatcher and local diagnostics. UI messages and diagnostic events have separate data policies.

**Failure scenarios.** A failure while logging cannot mask the primary failure. An exception during shutdown cannot turn a failed save into a successful exit acknowledgment. When storage is unavailable, keep the unsaved indication in memory and reconcile on next open.

**Testing strategy.** Inject one failure at each boundary and combined faults such as transport loss followed by failed persistence. Assert the displayed action, durable state, correlation ID and permitted retry behavior. Search all logs and UI error details for seeded sensitive values.

## Implementation gates and evidence

| Gate | Required evidence | Exit decision |
|---|---|---|
| M0 · 1.1.1–1.1.2 | Record laptop RAM, VRAM, disk, driver, power mode, Ollama and model digests, context size and fixture revision. Verify provisioned installer, Qwen, Whisper and Piper assets. Run the same two-project benchmark on each candidate. | Select Qwen 3 profile from measured quality and resource use. Record deviations and cold-start timing. |
| M1 Foundation · 1.2.1–1.2.2 | Demonstrate keyboard project selection, fresh session binding, one-slot stream, searchable history, cancellation, scope switch, mid-turn process death and ordered restart. | Accept the scoped text-chat slice. Carry durable facts and owner-facing disaster recovery to Phase 2. |
| M2 Foundation · 1.3.1–1.3.2 | Rehearse pinned clean install and upgrade/rollback with a fixture. Cold-boot offline; repeat with working internet and offline mode active. Attribute DNS and outbound traffic to the app, Ollama, helpers and updater; require zero external requests. Inspect logs for sensitive data. | Submit Foundation evidence for A1 and A9. Complete integrated MVP evidence under backlog 5.3. |
| Performance and quality · A2/A6 contributions | Run 20 representative warm turns with VS Code open. Use nearest-rank p95 (19th sorted observation), measure from accepted submit to first visible answer, report cold starts separately, and check stop feedback within one second. Track peak RAM and quality against the frozen expected answers. | Target warm p95 ≤5 seconds. Tune and rerun quality after a profile change. A revised trial target needs an explicit owner decision. Repeat with real indexing, citations and voice at the integrated gate, including the PRD threshold of 18/20 and zero cross-project disclosures. |

**Implementation choices to validate on the target laptop.** The single-instance policy, settings format, snapshot cadence for streaming text, log bounds, network deadlines and shutdown grace period are proposed Foundation design decisions. They have not been benchmarked. Record the values actually used with the release manifest and evidence pack.

