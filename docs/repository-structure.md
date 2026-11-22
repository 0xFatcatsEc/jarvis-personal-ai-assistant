# STYLUS JARVIS repository foundation

**Baseline 1.0 · Windows 11 · Single-user, local-first desktop application**

## 1. Repository structure

Use a single repository with one installable Python application, one separately packaged TypeScript extension, and one versioned wire contract between them. The Python application is a modular monolith. Ollama runs locally, and the application supervises speech, parsing and restricted execution workers as needed. The six agent roles share one Qwen 3 inference budget.

This is the target layout for staged implementation. The three planning documents and backlog remain at their existing paths. Create each implementation file when its backlog feature starts. The proposed package manager is uv for Python and npm for the extension. These choices give each release a reproducible lockfile.

| Release | Backlog features | Repository work |
|---|---|---|
| M0 | 1.1 | Pin candidate local assets, capture hardware measurements and freeze the evaluation fixtures. |
| M1 | 1.2, 2.1–2.3 | Introduce sessions, request scope, local chat, SQLite, evidence revisions, memory and restore. |
| M2 | 1.3, 3.1–3.2, 4.1, 5.1, 5.3 | Ship offline packaging, voice, local role registry, broker, read-only coding and approved VS Code launch. Build the broker before exposing Phase 4 file tools. |
| M3 | 4.2, 5.2 | Add the editor extension and trusted IPC, reviewed file mutations and named desktop controls. |
| M4 | 6.1–6.3 | Add gateway, vault, scoped caches, research providers and both mail providers. |
| M5 | 6.5 | Qualify the same packages through a seven-day pilot, clean restore and release decision. |
| Later | 4.3, 6.4, 7.1–7.4 | Add isolated coding verification, optional cloud, curated knowledge, MCP, handoffs and scheduled work behind their respective gates. |

### Local data outside Git

| Location | Owner and contents |
|---|---|
| `%LOCALAPPDATA%\StylusJarvis\data\` | Storage owns the SQLite database, WAL and shared-memory sidecars on a local disk. Keep this outside the OneDrive repository. |
| `%LOCALAPPDATA%\StylusJarvis\config\` | Per-user nonsecret settings, selected models and provisioned asset references. |
| `%LOCALAPPDATA%\StylusJarvis\assets\` | Verified Whisper and Piper assets, voice configuration and model card. Ollama manages Qwen weights in its own local model store. |
| `%LOCALAPPDATA%\StylusJarvis\cache\`, `temp\` and `logs\` | Rebuildable artifacts, short-lived audio and redacted diagnostics. Clear temporary audio after transcription. |
| Windows credential vault | Per-account OAuth credentials. The database holds opaque vault references. |
| Owner-selected independent backup destination | Encrypted consistent snapshots and a separately recoverable deletion ledger. Keep the recovery key separately. |
| Approved coursework roots | User-owned originals. Project registration grants scoped access. Include external sources in backup only when selected. |

## 2. Directory tree

The tree names major files and directory ownership boundaries. Standard Python package markers, individual tests, subsequent migrations and generated build output are omitted for readability.

```text
stylus-jarvis/
├── outputs/
│   └── stylus-development-backlog/
│       └── STYLUS JARVIS Development Backlog.xlsx
├── docs/
│   ├── decisions/
│   ├── repository-structure.md
│   └── recovery.md
├── src/
│   └── stylus_jarvis/
│       ├── contracts/
│       │   ├── context.py
│       │   ├── messages.py
│       │   └── ports.py
│       ├── runtime/
│       │   ├── coordinator.py
│       │   ├── sessions.py
│       │   ├── context_builder.py
│       │   ├── scheduler.py
│       │   └── diagnostics.py
│       ├── ui/
│       │   ├── main_window.py
│       │   └── review.py
│       ├── agents/
│       │   ├── registry.py
│       │   ├── coding.py
│       │   ├── system_control.py
│       │   ├── file_management.py
│       │   ├── email.py
│       │   ├── research.py
│       │   └── memory.py
│       ├── security/
│       │   ├── broker.py
│       │   ├── capabilities.py
│       │   └── grants.py
│       ├── memory/
│       │   ├── service.py
│       │   └── export.py
│       ├── knowledge/
│       │   ├── ingestion.py
│       │   ├── retrieval.py
│       │   └── library.py
│       ├── storage/
│       │   ├── migrations/
│       │   │   └── 0001_initial.sql
│       │   ├── database.py
│       │   ├── repositories.py
│       │   └── recovery.py
│       ├── tools/
│       │   ├── filesystem.py
│       │   └── desktop.py
│       ├── inference/
│       │   ├── ollama.py
│       │   └── router.py
│       ├── voice/
│       │   ├── controller.py
│       │   ├── whisper.py
│       │   └── piper.py
│       ├── workers/
│       │   ├── supervisor.py
│       │   ├── pdf.py
│       │   └── restricted.py
│       ├── editor/
│       │   └── bridge.py
│       ├── online/
│       │   ├── gateway.py
│       │   ├── credentials.py
│       │   ├── gmail.py
│       │   ├── outlook.py
│       │   ├── research.py
│       │   └── cloud.py
│       ├── mcp/
│       │   └── client.py
│       ├── workflows/
│       │   ├── handoffs.py
│       │   └── planning.py
│       ├── __main__.py
│       ├── bootstrap.py
│       └── settings.py
├── extensions/
│   └── vscode/
│       ├── src/
│       │   ├── extension.ts
│       │   ├── bridge.ts
│       │   └── edits.ts
│       ├── package.json
│       ├── package-lock.json
│       └── tsconfig.json
├── extension_contracts/
│   └── editor_v1.schema.json
├── packaging/
│   └── windows/
│       ├── release-manifest.toml
│       └── offline-install.md
├── tests/
│   ├── unit/
│   ├── contracts/
│   ├── integration/
│   ├── acceptance/
│   ├── fixtures/
│   └── architecture/
├── README.md
├── pyproject.toml
├── uv.lock
├── .gitignore
├── STYLUS JARVIS Project Plan.docx
├── STYLUS JARVIS Architecture Review and V2 Design.docx
└── STYLUS JARVIS Product Requirements Document.docx
```

## 3. Purpose of every directory

| Directory | Responsibility |
|---|---|
| `./` | Repository root for the Windows desktop product and its planning baseline. |
| `outputs/` | Existing location for planning deliverables. |
| `outputs/stylus-development-backlog/` | Holds the approved work breakdown. |
| `docs/` | Versioned engineering decisions and operator instructions. |
| `docs/decisions/` | Short architectural decision records covering changes with long-term consequences. |
| `src/` | Installable Python source, isolated from tests and build inputs. |
| `src/stylus_jarvis/` | Application package and composition root. |
| `src/stylus_jarvis/contracts/` | Inward-facing types and interfaces shared across boundaries. Contracts carry data and express permitted operations. |
| `src/stylus_jarvis/runtime/` | Coordinates a request across roles, evidence, inference and approved tools. |
| `src/stylus_jarvis/ui/` | PySide6 desktop surface for keyboard and voice interactions. |
| `src/stylus_jarvis/agents/` | Six task roles sharing Qwen 3. Each selects relevant evidence and proposes typed actions. |
| `src/stylus_jarvis/security/` | Policy and consent boundary shared by every operation with side effects. |
| `src/stylus_jarvis/memory/` | Owns durable personal and project facts and their lifecycle. |
| `src/stylus_jarvis/knowledge/` | Owns source identity, indexing and retrieval semantics. |
| `src/stylus_jarvis/storage/` | Implements repository ports and owns SQLite persistence. |
| `src/stylus_jarvis/storage/migrations/` | Packaged, ordered schema transitions shared by clean installs and upgrades. |
| `src/stylus_jarvis/tools/` | Native local adapters invoked under brokered authority. |
| `src/stylus_jarvis/inference/` | Local model adapter and routing choice. |
| `src/stylus_jarvis/voice/` | Controls local audio device state, transcription, synthesis and interruption. |
| `src/stylus_jarvis/workers/` | Owns managed subprocess lifetimes and resource boundaries. |
| `src/stylus_jarvis/editor/` | Python endpoint for a trusted local VS Code extension. |
| `src/stylus_jarvis/online/` | Sole application boundary for external connections and credential use. |
| `src/stylus_jarvis/mcp/` | Future host-side MCP client integration behind the broker. |
| `src/stylus_jarvis/workflows/` | Future durable multi-role coordination and project scheduling. |
| `extensions/` | Separately packaged clients of the local core. |
| `extensions/vscode/` | TypeScript editor extension for trusted local workspaces, introduced at M3. |
| `extensions/vscode/src/` | Editor-host code that has access to unsaved documents. |
| `extension_contracts/` | Language-neutral wire schemas consumed by the Python bridge and TypeScript client. |
| `packaging/` | Release inputs and build instructions for a clean offline Windows install. |
| `packaging/windows/` | Windows bundle configuration and asset provenance. |
| `tests/` | Verification suite outside the shipped application. |
| `tests/unit/` | Fast policy, context, retrieval, memory and state-machine tests using injected ports. |
| `tests/contracts/` | Fixtures and checks for adapter, editor-wire and optional MCP compatibility, including unsupported revisions. |
| `tests/integration/` | Local SQLite, migration, filesystem, worker and bridge tests with disposable projects and simulated providers. |
| `tests/acceptance/` | Owner-visible PRD A1–A9 scenarios covering offline use, recall, voice, permissions, performance, restore and upgrades. |
| `tests/fixtures/` | Synthetic two-project corpus, versioned PDFs, conflicting evidence, mailbox doubles and migration snapshots. |
| `tests/architecture/` | Checks import direction, isolation of provider SDKs, packaging boundaries and single ownership of writes. |

## 4. Purpose of every major file

Names in each table are relative to its heading.

### `./`

| File | Purpose |
|---|---|
| `README.md` | Entry point for installation, offline provisioning, first run and links to the PRD, backlog and this blueprint. |
| `pyproject.toml` | Python distribution metadata, supported interpreter range, desktop entry point, dependency groups, package data and test configuration. |
| `uv.lock` | Reproducible Python dependency resolution for development and offline release builds. |
| `.gitignore` | Exclude local environments, credentials, user databases, backups, model weights, generated packages and temporary audio. |
| `STYLUS JARVIS Project Plan.docx` | Original project vision and planning history. |
| `STYLUS JARVIS Architecture Review and V2 Design.docx` | Approved technical baseline for V2 ownership and trust boundaries. |
| `STYLUS JARVIS Product Requirements Document.docx` | Product scope, release gates and acceptance criteria A1–A9. |

### `outputs/stylus-development-backlog/`

| File | Purpose |
|---|---|
| `STYLUS JARVIS Development Backlog.xlsx` | Authoritative feature IDs, task dependencies and release gates. |

### `docs/`

| File | Purpose |
|---|---|
| `repository-structure.md` | This foundation document. Update alongside approved changes to module ownership. |
| `recovery.md` | Owner procedure for key recovery, staged restore, deletion reconciliation and rollback. |

### `src/stylus_jarvis/`

| File | Purpose |
|---|---|
| `__main__.py` | Starts the desktop application through bootstrap and propagates shutdown. |
| `bootstrap.py` | Constructs configured ports and adapters, registers enabled capabilities, wires workers and owns process shutdown. |
| `settings.py` | Loads validated nonsecret settings and resolves per-user data paths and local model profiles. |

### `src/stylus_jarvis/contracts/`

| File | Purpose |
|---|---|
| `context.py` | Authenticated user, project, optional account, online mode, grant revision, budget and cancellation identity. |
| `messages.py` | Typed requests, citations, proposals, approvals, worker results, error categories and receipts. |
| `ports.py` | Interfaces for model generation, repositories, authorized tool dispatch, external providers and worker scheduling. |

### `src/stylus_jarvis/runtime/`

| File | Purpose |
|---|---|
| `coordinator.py` | Owns run transitions and cancellation. Persists intent before dispatch and reconciles uncertain outcomes. |
| `sessions.py` | Manages project selection, persistent conversations, interrupted streams and active turn scope. |
| `context_builder.py` | Combines confirmed facts, recent turns and cited evidence within the selected model’s context budget. |
| `scheduler.py` | Prioritizes interactive work, bounds queues and serializes local generation and conflicting writes. |
| `diagnostics.py` | Emits local redacted timings, status and correlation IDs for acceptance tests and troubleshooting. |

### `src/stylus_jarvis/ui/`

| File | Purpose |
|---|---|
| `main_window.py` | Displays chat, project and mode, citations, transcript editing, audio controls and task state. |
| `review.py` | Displays memory, scopes, pending approvals, exact action previews and recovery choices. |

### `src/stylus_jarvis/agents/`

| File | Purpose |
|---|---|
| `registry.py` | Maps roles to available capabilities by release and session grant. |
| `coding.py` | Explains a saved revision and later proposes versioned editor patches. |
| `system_control.py` | Proposes approved application launches and supported desktop interactions. |
| `file_management.py` | Proposes project reads, searches and later reviewed file operations. |
| `email.py` | Summarizes selected mailbox evidence and proposes drafts or reviewed sends. |
| `research.py` | Selects search, publisher feeds or weather and returns attributed results. |
| `memory.py` | Interprets recall, correction and forget requests and proposes scoped operations to the memory service. |

### `src/stylus_jarvis/security/`

| File | Purpose |
|---|---|
| `broker.py` | Validates capability, exact arguments, current scope, risk and approval at dispatch. Calls an authorized adapter through its port. |
| `capabilities.py` | Defines trusted tool IDs, schema versions, risk, deadlines, allowed origins and retry classes. |
| `grants.py` | Binds permissions and expiring approvals to user, scope and exact request revision. Revalidates grants before delivery. |

### `src/stylus_jarvis/memory/`

| File | Purpose |
|---|---|
| `service.py` | Confirms inferred facts, supersedes corrections, resolves source links and orchestrates forgetting. |
| `export.py` | Produces readable scoped facts and history with evidence references. |

### `src/stylus_jarvis/knowledge/`

| File | Purpose |
|---|---|
| `ingestion.py` | Registers stable source IDs, revisions, extraction versions and page or text locators. |
| `retrieval.py` | Requests scope-filtered candidates, ranks and deduplicates them, and labels stale or unavailable evidence. |
| `library.py` | Later maintains user-authored notes, decision links, tags and portable exports. |

### `src/stylus_jarvis/storage/`

| File | Purpose |
|---|---|
| `database.py` | Opens the local database, enables foreign keys and WAL, applies migrations and manages the writer queue. |
| `repositories.py` | Persists scoped chat, facts, evidence, FTS5 indexes, runs, receipts, drafts and partitioned caches. |
| `recovery.py` | Coordinates consistent encrypted snapshots, a separately recoverable deletion ledger and staged restoration. |

### `src/stylus_jarvis/storage/migrations/`

| File | Purpose |
|---|---|
| `0001_initial.sql` | Initial project, conversation and versioning schema. Later migrations add features at their owning gate. |

### `src/stylus_jarvis/tools/`

| File | Purpose |
|---|---|
| `filesystem.py` | Validates root and resolved target, reads approved files and later performs guarded mutations. Defers open-buffer writes to the editor. |
| `desktop.py` | Resolves allowlisted executables and known Windows controls, verifies focus and reports outcomes. |

### `src/stylus_jarvis/inference/`

| File | Purpose |
|---|---|
| `ollama.py` | Streams the pinned Qwen 3 profile from loopback Ollama and handles cancellation and unavailability. |
| `router.py` | Selects local inference by default and delegates optional cloud proposals to the same consent and gateway path. |

### `src/stylus_jarvis/voice/`

| File | Purpose |
|---|---|
| `controller.py` | Coordinates push-to-talk, editable transcripts, device loss, speech queues and temporary recording cleanup. |
| `whisper.py` | Adapts whisper.cpp transcription using the provisioned Whisper model. |
| `piper.py` | Adapts local Piper synthesis with its pinned voice configuration and model card. |

### `src/stylus_jarvis/workers/`

| File | Purpose |
|---|---|
| `supervisor.py` | Starts and cancels bounded workers, enforces deadlines and collects typed outcomes. |
| `pdf.py` | Extracts text by PDF page with pypdf and identifies pages requiring OCR. |
| `restricted.py` | Later enforces verified Windows isolation for approved test profiles and third-party MCP processes. |

### `src/stylus_jarvis/editor/`

| File | Purpose |
|---|---|
| `bridge.py` | Authenticates per-user named-pipe requests, identifies workspace and document revision and journals editor receipts. |

### `src/stylus_jarvis/online/`

| File | Purpose |
|---|---|
| `gateway.py` | Checks online mode, destination, redirects, current grant, budget and data scope before network access. |
| `credentials.py` | Manages delegated OAuth and Windows vault references scoped to each provider account. |
| `gmail.py` | Maps Gmail search and reviewed send operations to gateway requests and provider receipts. |
| `outlook.py` | Maps Microsoft Graph delegated mail operations to the same mailbox contract. |
| `research.py` | Maps SearXNG search, publisher feeds and weather to dated, attributed results. |
| `cloud.py` | Later constructs the approved provider payload and enforces cloud spending limits with the gateway. |

### `src/stylus_jarvis/mcp/`

| File | Purpose |
|---|---|
| `client.py` | Maps pinned server capabilities to trusted local IDs, validates version and result bounds, and uses a restricted stdio worker. |

### `src/stylus_jarvis/workflows/`

| File | Purpose |
|---|---|
| `handoffs.py` | Tracks dependent steps, narrowed child grants, leases, budgets, cancellation and restart. |
| `planning.py` | Manages project tasks, due dates, scheduled summaries and revocable standing grants. |

### `extensions/vscode/`

| File | Purpose |
|---|---|
| `package.json` | Extension identity, supported VS Code versions, activation conditions, commands and build dependencies. |
| `package-lock.json` | Pinned extension build dependencies for reproducible packaging. |
| `tsconfig.json` | TypeScript compiler and output boundaries for the extension. |

### `extensions/vscode/src/`

| File | Purpose |
|---|---|
| `extension.ts` | Registers extension commands, handles trust state and owns activation and teardown. |
| `bridge.ts` | Authenticates local IPC, exchanges versioned messages and handles disconnects. |
| `edits.ts` | Previews exact changes, validates URI and buffer versions and applies approved editor-owned edits. |

### `extension_contracts/`

| File | Purpose |
|---|---|
| `editor_v1.schema.json` | Defines workspace identity, document revision, request correlation, approval binding and mutation receipt. |

### `packaging/windows/`

| File | Purpose |
|---|---|
| `release-manifest.toml` | Pins Python environment, app and schema versions, model digests, voice configuration, checksums and third-party notices. |
| `offline-install.md` | Documents staging verified assets, disabling external traffic and validating a clean standard-user install. |

Regular Python packages use lightweight `__init__.py` markers. They declare package membership and must be safe to import offline. The migrations directory holds SQL package data. Build artifacts and wheelhouses are produced from the locks and release manifest.

## 5. Internal module boundaries

| Decision or state | Single owner | Interaction |
|---|---|---|
| Active project, turn, run and cancellation | Runtime | UI and authenticated editor requests enter the same coordinator. A turn carries an immutable scope and grant revision. |
| Task interpretation | Agents | A role returns evidence references, text or typed proposals. The runtime routes proposals to the broker. Retrieved instructions have no authority. |
| Permission to act | Security broker | Validates scope and exact arguments before dispatch. Recheck the grant before delivering a result. Adapters verify resource-specific preconditions at execution. |
| Durable facts versus extracted evidence | Memory owns assertions. Knowledge owns source identity and retrieval. | Facts point to stable revisions and locators. Reindexing replaces derived excerpts. A citation to missing historical evidence reports that state. |
| Durable writes | Storage repositories | Services submit scoped operations through ports. One SQLite writer queue commits changes. The journal records dispatch before external effects and stores the receipt afterward. |
| File changes | Filesystem adapter for closed files. VS Code extension for open buffers. | Coordinate per-resource changes through the broker. If editor ownership cannot be established for a proposed disk edit, defer it. Never overwrite a dirty buffer through the filesystem adapter. |
| Audio and processing | Voice controller owns device state. Worker supervisor owns subprocess lifetimes. | Whisper returns editable text. Piper receives answer sentences. Stop cancels queued audio and generation. |
| External traffic and private caches | Online gateway owns egress. Storage owns scoped cache records. | Bind private entries to provider, account, project/scope and grant revision. Validate destination and consent before network or token refresh. |
| Future extensions | MCP adapter translates protocol calls. Workflow scheduler owns multi-step progress. | Both reuse the broker. Child grants narrow and ambiguous writes enter reconciliation before retry. |

**Example — offline coding question.** The PySide6 project picker binds the selected root to the request. The Coding role proposes a scoped read. The broker authorizes it, the filesystem adapter returns the saved revision, the context builder prepares the prompt and Ollama streams the answer. The UI identifies the revision and the runtime persists the turn. This path works before the VS Code extension exists.

**Example — reviewed send.** The Email role proposes a draft in the selected account. The desktop UI displays the exact sender, recipients and content. The broker checks approval for that revision, the runtime records dispatch, and the gateway executes the provider request. A timeout after dispatch leaves an uncertain outcome that the coordinator reconciles using provider evidence.

## 6. Dependency rules

1. **Compose at the edge.** Only bootstrap imports the full set of concrete services and adapters. Inject narrow interfaces at startup. An unconfigured later-stage integration must leave offline startup usable.
2. **Keep dependencies inward.** Contracts depend only on standard-library types and the approved validation library. Runtime, roles, memory, knowledge and policy depend on contracts. Runtime may orchestrate these application services. They must never import bootstrap, UI, SQLite implementation, provider clients or each other in a cycle.
3. **Keep presentation local to its package.** PySide6 belongs in UI and startup wiring. UI submits requests and renders events. The TypeScript extension talks only through the authenticated versioned IPC contract. It never opens the database or queries Ollama directly.
4. **Restrict effects to their owners.** Agents cannot import native tools, launch processes, access credentials, perform network calls or write SQLite. Authorized concrete adapters implement ports. Local Ollama loopback and authenticated editor IPC are local transports. Every internet request, including cloud inference, goes through the online gateway.
5. **Preserve scope end to end.** Filter before retrieval and cache lookup. Pass scoped references to providers and workers. Enforce path, file or buffer revision and grant checks again at the point of use. Cancellation does not undo a dispatched external write.
6. **Separate process management from isolation.** Limits on queues and timeouts protect responsiveness. Restricted coding and MCP workers additionally need tested Windows file, credential and network restrictions. Keep these capabilities disabled until the corresponding isolation tests pass.
7. **Keep schemas aligned.** Ship migrations with the Python distribution. Both editor endpoints test against the same wire schema. Model, parser and index changes carry version identifiers so retrieval and release fixtures remain reproducible.
8. **Verify boundaries in their owning suite.** Architecture tests detect forbidden imports. Contract tests validate adapter and IPC behavior. Integration tests check storage, conflicts and cancellation. Acceptance tests cover the PRD gates on the Windows target, including offline mode with a working network.

## 7. Naming conventions

| Artifact | Convention and example |
|---|---|
| Repository and distribution | Lowercase kebab-case, `stylus-jarvis`. Python import package uses `stylus_jarvis`. |
| Python modules, functions and variables | Short descriptive snake_case. Use domain names such as `context_builder` and verbs for operations such as `resolve_revision`. |
| Python types and constants | PascalCase for types such as `SourceRevision`. UPPER_SNAKE_CASE for module constants. |
| TypeScript | Lowercase descriptive module names, camelCase values and PascalCase types. Preserve wire-field spelling at the bridge. |
| Wire fields and capability IDs | Versioned snake_case wire fields such as `grant_revision`. Stable dotted tool names such as `files.read` carry a separate contract version. |
| Database | Plural snake_case tables, singular foreign keys such as `project_id`, UTC timestamps ending in `_at`. Use immutable IDs for identity and explicit revisions for mutable content. |
| Migrations and protocols | Four-digit monotonic migrations such as `0001_initial.sql`. Introduce a new versioned wire schema for incompatible changes. Released migrations are immutable. |
| Tests and fixtures | Python tests use `test_<behavior>.py`. Acceptance records carry the PRD ID and fixture revision, for example `A5` for scoped file access and editor launch. |
| Documents and decisions | Kebab-case Markdown names. Number decisions in chronological order, for example `0001-local-runtime.md`. Preserve existing approved artifact names. |

**First implementation boundary.** Start with backlog feature 1.1 and the M0 hardware and model fixtures. Add M1 packages as scoped chat, evidence and recovery become executable. M2 is complete when the PRD’s offline acceptance gates pass on the owner’s laptop.

