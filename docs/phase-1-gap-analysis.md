# Phase 1 implementation gap analysis

Review point: before the first M0 evidence increment. Scope: repository-owned source, SQL, package metadata and lock, manifest, tests and planning deliverables. Download caches, virtual environment and generated Python bytecode are reproducible dependencies. Status describes this revision; a successful simulated test does not certify the MSI deployment.

## Review basis

The original Project Plan supplies the historical goals. The V2 Architecture Review owns isolation, provenance, editor ownership and execution boundaries. The PRD owns acceptance gates. The [backlog](../outputs/stylus-development-backlog/STYLUS%20JARVIS%20Development%20Backlog.xlsx) owns sequencing. The [repository blueprint](repository-structure.md) owns module placement and the [Phase 1 design](phase-1-technical-design.md) owns Foundation behavior. Later-phase voice execution, cited PDF ingestion, durable personal facts, mail, editor changes and MCP are outside this audit's implementation denominator.

## Requirements against the working tree

| Backlog ID | Starting status | Evidence and outstanding work |
|---|---|---|
| 1.1.1.1 Inventory laptop | Missing | No measured hardware record in the repository. First incomplete subtask. |
| 1.1.1.2 Freeze fixtures | Missing | No versioned set of 20 reference questions, two projects, conflicting evidence and expected abstentions. |
| 1.1.2.1 Provision assets | Partial | Qwen tag and full digest are packaged. No verified Windows installer, Whisper weights, Piper model/config/card or offline asset inventory. |
| 1.1.2.2 Compare Qwen builds | Missing at initial audit; now complete | See the [measured report and model decision](../outputs/qwen-msi-02/decision.md). |
| 1.2.1.1 Project picker | Partial at initial audit; now complete | Windows tests verified distinct IDs for identically named roots, persistence after reopening SQLite, keyboard selection and alias resolution. See [project picker verification](#project-picker-verification). |
| 1.2.1.2 Bind requests to grants | Complete | Windows acceptance tests cover dispatch, revocation during generation, status-only settlement and delivery of receipts and history. See [request grant verification](#request-grant-verification). |
| 1.2.2.1 Create local store | Complete for M1 | Foreign-key enforcement and live WAL placement verified on Windows. Upgrade, rollback and FTS5 passed on the identified application runtime. Final distribution binary verification belongs to packaging. See [local store verification](#local-store-verification). |
| 1.2.2.2 Stream and reopen history | Complete for M1 | Windows process-restart and Qt tests cover ordered history, distinct terminal states, final-write recovery, model-independent replay and bounded close attempts. See [history verification](#history-verification). |
| 1.3.1.1 Guard model and worker traffic | Complete for the provisioned Windows profile | The dedicated desktop and headless Ollama run under effective outbound rules. Windows acceptance covered real Qwen inference, native outbound denial, worker policy, cloud refusal and updater exclusion. See [offline traffic verification](#offline-traffic-verification). |
| 1.3.1.2 Trace offline modes | Partial | An instrumented MSI desktop turn and native trace are recorded. Closure requires passing disconnected and connected cold-boot reports. See [trace evidence](#cold-boot-trace-evidence). |
| 1.3.2.1 Pin and reinstall | Partial | Python lock, project entry point, SQL package data and model digest present. No offline wheelhouse/installer, complete release manifest, clean-profile rollback rehearsal or sample upgrade proof. |
| 1.3.2.2 Bounded diagnostics | Partial | Rotating local allowlisted events, bounded queue and dropped-event counter present. No owner-visible degraded sink, writer timings, build field or saturation/rotation evidence. |

## Completed behaviors and verification

The 11-test Windows suite passed at the review point. It exercised SQLite WAL/foreign keys, invalid schema refusal, duplicate submission with a healthy model, scoped switching, cancel/stream failure, stale checkpoints, restart reconciliation, oversized input, validated settings, digest mismatch and redirect refusal. The desktop test drove PySide6 against an HTTP fixture over actual loopback, closed the application services, removed the fixture server and read the saved reply on a second launch. It did not load Qwen weights. The PRD’s A1, A6 and A9 release gates remain open. Full A2–A5 and A7 have companion work in other phases.

## File review and module explanations

Paths are relative to `src/stylus_jarvis/` unless marked as repository files.

| Files inspected | What they implement | Assessment |
|---|---|---|
| `bootstrap.py`, `__main__.py` | Windows SID, Qt lock, composition, startup/close, user commands and event dispatch | Desktop path exercised. Bootstrap also owns session and presentation logic assigned elsewhere in the blueprint. |
| `settings.py`, `release-manifest.toml` | Immutable Pydantic preferences, atomic replace, release facts and loopback validation | Defaults and validation tested. Profile selection, repair UI and expanded manifest are pending. |
| `runtime/diagnostics.py` | Typed events, bounded queue, rotating JSONL and memory health state | Functional infrastructure; UI does not expose log failures. |
| `storage/database.py`, `storage/migrations/0001_initial.sql` | Thread-owned SQLite, migration checksum ledger, pre-upgrade snapshot, integrity checks, orphan reconciliation | Single executor serializes reads as well as writes. Measure latency before separating readers. |
| `storage/repositories.py` | Project registration, grant checks, history, idempotent creation, checkpoints and finalization | Revocation-safe settlement verified under 1.2.1.2. Project-wide search remains open. |
| `runtime/scheduler.py` | One inference reservation, cancellation and idle signaling | The desktop shares one close deadline across the slot, commands and resource cleanup. |
| `runtime/coordinator.py` | Request validation, context budget, generation, checkpoints, terminal receipt and unsaved retry | Scoped replay precedes model checks. Failed final writes have a local restart recovery path. |
| `inference/ollama.py`, `runtime/offline.py`, `runtime/offline-policy.ps1` | Bounded loopback HTTP, listener ownership, effective Windows policy, local model inventory and NDJSON streaming | Live guarded Qwen generation passed. Integrated latency and the cold-boot trace have separate acceptance gates. |
| `inference/router.py` | Local profile, verified status and conservative context budgeting | Phase 1 local path implemented; avoid concurrent probe races. |
| `contracts/messages.py`, `contracts/ports.py` | Immutable records, stable failure codes and structural interfaces | Usable injection boundary. Failure lacks structured durability and retry fields specified in design. |
| `ui/main_window.py` | PySide6 layout, plain-text transcript, scope and stop controls | UI smoke test passes. No repair or recovery view. |
| All six package `__init__.py` files | Import-safe package markers | No changes needed. |
| Repository `pyproject.toml`, `uv.lock`, `.gitignore` | Entry point, Python 3.12+, runtime dependencies, resource and build exclusions | Dependency resolution recorded; build backend and native assets still require reproducible offline provisioning. |
| Repository `tests/test_foundation.py`, `tests/test_desktop.py` | Storage/model/scheduler/settings tests and offscreen Qt integration | Tests run successfully; planned architecture, acceptance and fixture suites have limited or no coverage. |

## Bugs and operational risks

Priority reflects impact within Foundation. These are code-inspection findings unless identified by the test descriptions above.

1. **High — unsaved final text on close. Resolved in 1.2.2.2.** A close attempt offers retry. A durable recovery record also allows explicit exit for recovery on restart. A memory-only reply blocks clean exit.
2. **High — changed grant prevented terminal bookkeeping. Resolved in 1.2.1.2.** Revocation before final commit now settles the original turn in the same process. The final update preserves checkpointed text and withholds the content-bearing receipt.
3. **High — release-wide offline trace remains open.** Item 1.3.1.1 verified the controls on the MSI. Item 1.3.1.2 still requires process-attributed DNS and traffic capture in both cold-boot conditions before A1 can close.
4. **Medium — replay required Ollama. Resolved in 1.2.2.2.** Stored terminal submissions replay after payload and grant checks without model access.
5. **Medium — shutdown deadline covered only the slot. Resolved in 1.2.2.2.** Startup, slot drain, desktop tasks and service cleanup share a deadline. An expired attempt reports the outstanding work and keeps the window available.
6. **Medium — resolved data directory could differ from checked profile. Resolved in 1.2.2.1.** The database writer checks the canonical target and its Windows volume type before opening SQLite. The Windows suite covers junctions into a configured OneDrive root and denial of a remote drive type.
7. **Medium — stale UI state can lose work or mislead.** Selection clears the draft, older command failures can update the new selection’s status, and startup failure re-enables controls without a valid runtime. Add scoped draft retention and a distinct recovery screen.
8. **Medium — long histories still accumulate in UI memory.** Reads are paginated, but the widget displays the entire matching conversation. The same-scope refresh race was fixed and tested in 1.2.2.2. A bounded display window remains a separate large-history improvement.
9. **Low — migration checksum depends on checkout line endings.** The ledger hashes raw SQL bytes. Enforce LF for packaged SQL or canonicalize bytes consistently before recording the first distributed migration.

## Architecture deviations and technical debt

Session ownership lives across bootstrap, repository and coordinator rather than the blueprint’s session service. Prompt assembly spans repository and router. The UI controller has direct access to concrete repositories and model routing. Scope records reside in messages rather than the planned context module. Move boundaries incrementally when addressing the corresponding lifecycle defects. Preserve the tested SQLite and transport contracts. Future-phase modules have no delivery obligation in this increment.

The database actor has one connection and an unbounded executor work queue. Per-frame authorization and full reply-prefix concatenation each add overhead. Profile sustained streams, large history and mixed workloads before changing these paths. The diagnostics schema and failure envelope need contract tests. An abrupt Windows process exit is covered. Physical disk exhaustion, suspend/resume and callbacks after native window destruction remain open operational tests.

## Next implementation increment

Complete backlog task **1.1.1 Record the target environment**, in dependency order: capture a reproducible Windows hardware baseline, then freeze the reference fixtures. Preserve the existing runtime files for this increment. Next sequential task is **1.1.2 Qualify the inference profile**. Qualification requires provisioned assets and actual target-laptop measurements.

## Implementation outcome after the audit

**1.1.1.1 completed.** The [read-only collector](../packaging/windows/measure-foundation.ps1) captured the [hardware baseline](evidence/m0-hardware.json) on the MSI Thin A15 B7UC. Windows reported 7,738,015,744 bytes of usable physical RAM, 153,039,429,632 bytes free on the system volume and Windows 11 build 26300. NVIDIA reported RTX 3050 Laptop GPU, 4,096 MiB dedicated memory and driver 616.87. AC was connected and the active power scheme was Balanced. Re-run the collector before timing models because power and free space can change.

**1.1.1.2 completed.** [Frozen fixture m0-v1](../tests/fixtures/m0-v1/README.md) contains two conflicting two-page PDFs, page-matched passages, 16 grounded questions and four expected abstentions. The scoring contract requires correct evidence and zero cross-project disclosures. PDF extraction was checked against the frozen text. The [fixture tests](../tests/test_m0_fixtures.py) verify the four input hashes, unique case IDs, project balance and answer-to-page mappings.

## Provisioning outcome

**1.1.2.1 completed.** The [offline asset inventory](../packaging/windows/m0-assets.json) pins 11 files totaling 4,566,729,395 bytes. The [verification receipt](evidence/m0-assets.json) records their sizes and SHA-256 digests. The files are staged under `%LOCALAPPDATA%\StylusJarvis\assets\m0-v1`, outside the repository. A second network-free pass rehashed the staged files and checked the Qwen manifest-to-blob chain against the runtime model pin.

The inventory includes OllamaSetup for Windows v0.40.17, the Qwen 3 4B registry manifest with its config and all four layers, the multilingual Whisper base GGML weights, and the en_US-ljspeech-medium Piper model with its JSON configuration and model card. The installer digest comes from the official GitHub release asset. Qwen blob digests come from the pinned registry manifest. Whisper and Piper weights use commit-pinned Hugging Face LFS digests. The small Piper companions were checked against the repository's Git object IDs before pinning their SHA-256 digests. The voice card records a public-domain LJ Speech training dataset and training from scratch.

Recheck locally with `python packaging/windows/provision_assets.py verify`. The `provision` action can populate a new staging directory from the same pins. Runtime installation and model execution are separate from staging. Four offline provisioning tests cover damaged or missing assets, failed-download cleanup and reuse, incomplete Qwen blob coverage, and required voice companions and path containment.

**Remaining M0 gate.** 1.1.2.2 Compare Qwen builds is next. No comparison run or later backlog work was performed in this provisioning increment.

## Qwen comparison tooling

The [qualification harness and runbook](../benchmarks/README.md) compare digest-pinned 4B and 8B candidates on the same recall and coding cases. A reviewed cold-load CUDA OOM now records a hardware disqualification while preserving the other candidate's complete measurements and all its eligibility gates.

**M0 complete · 23 November 2026.** Both candidates were attempted on the MSI. Select the already-pinned Qwen 3 4B build for the tested local profile. It passed 20/20 recall, zero observed disclosures and 0.584 s warm p95 to first visible content. Its coding score was 4/10. The 8B build exhausted GPU memory before the first trial. No other M0 work remains. Full desktop A6 testing remains at its assigned later gate. [Benchmark report and selection](../outputs/qwen-msi-02/decision.md) · [Scored comparison](../outputs/qwen-msi-02/comparison.json)

## Project picker verification

**1.2.1.1 Create project picker — complete, 23 November 2026.** Two folders named `Shared Project` under different parents received distinct project IDs. After closing and reopening the SQLite database, registering the roots in reverse order returned both original IDs. In the offscreen PySide6 desktop, Shift+Tab reached the picker from Add project. Down and Up selected each canonical path and opened its corresponding saved conversation. The existing picker met the backlog criterion without a production change. [Acceptance tests](../tests/test_project_picker.py)

Registering a case-variant path or a path through a Windows directory junction before its canonical path produced one project entry with the canonical label. The separate directory-symlink test skipped on this account because Windows denied link creation (error 1314). It runs automatically when link creation is available.

The full Windows suite recorded 28 passes and one skip at picker closure. To repeat the picker checks from the repository root, run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_project_picker.py -v`.

## Request grant verification

**1.2.1.2 Bind requests to grants — complete, 23 November 2026.** The coordinator retained the owner, project, conversation, offline mode, grant revision, selection generation and request ID through dispatch and event delivery. Fault injection changed the live SQLite grant during the root check, before the first fragment, between fragments, after the last fragment, and between commit and receipt delivery. The tests also exercised duplicate receipts and save retry after rebinding. [Grant acceptance tests](../tests/test_request_grants.py)

Revoking an active turn blocks subsequent fragments and settles the turn as failed with a scope error and an end time. Only previously checkpointed assistant text remains durable. A later grant cannot finalize an earlier active turn, and the original grant cannot settle a turn admitted under the later revision. If completion committed before revocation, the completed turn remains readable with a fresh grant. The Windows desktop test used the signed-in SID, offscreen Qt, real SQLite and a scripted local stream to verify fragment and history delivery. A separate upgrade test reopened a schema-v1 database and verified that the legacy checkpoint survived. [Desktop acceptance test](../tests/test_desktop.py) · [Upgrade test](../tests/test_foundation.py)

The full Windows suite recorded **40 passes and one skip** at grant closure. All grant tests passed. The existing project-picker symlink case skipped because this Windows account lacks link-creation privileges. Reproduce with `.venv\Scripts\python.exe -B -m unittest discover -s tests -v`.

## Local store verification

**1.2.2.1 Create local store — complete for M1, 23 November 2026.** The approved criterion requires enforced foreign keys and a live WAL database outside OneDrive. The Windows acceptance run used an isolated profile, the normal database filename and the repository's application interpreter. [Acceptance tests](../tests/test_local_store.py)

| Check | Evidence |
|---|---|
| Live location and constraints | With the writer open through a real directory junction, SQLite reported the canonical main filename via `PRAGMA database_list`. The database, `-wal` and `-shm` existed together in the local target. A foreign-key violation rolled back an earlier valid insert in the same transaction. |
| Rejected locations | A junction into a configured sync root was denied before the requested child directory was created. Dangling junctions, UNC names and files hard-linked into the sync root were rejected. The mapped-volume case used a real junction and an injected Windows `DRIVE_REMOTE` result. |
| Upgrade and rollback | The packaged v1-to-v2 migration preserved existing data and created one pre-upgrade snapshot. Reopening v2 did not repeat the upgrade. A snapshot restored into a separate directory opened with the v1 schema and retained its original conversation. Injected SQL and integrity-check failures left v1 schema, data and ledger intact. |
| FTS5 | A temporary FTS5 table indexed two rows on the writer connection. A phrase query matched the expected row alone. Windows 11 build 26300 ran CPython 3.12.13 with SQLite 3.50.4. The loaded `sqlite3.dll` SHA-256 was `c77ee0f3eb34bda3ed95e9072ba12959bb727d078dd3f2d4900f60aa55a4abfd`. |

All nine local-store tests passed. The full Windows suite recorded 49 passes and one skip for the existing picker symlink test. Repeat the store checks with `.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_local_store.py -v`.

The repository has no standalone desktop distribution yet. Item 1.3.2.1 owns the offline release bundle. Run the FTS5 test with its packaged interpreter to verify the shipped binary at that gate.

## History verification

**1.2.2.2 Stream and reopen history — complete for M1.** A Windows child process streamed two completed replies, cancelled another after a fragment and exited abruptly during a fourth turn after a checkpoint. On restart the searchable Qt transcript showed the exact original order, distinct completed, cancelled and interrupted labels, and the checkpointed prefix. A delayed, older refresh could not replace a newer render spanning 104 messages. [Process and rendering tests](../tests/test_history_lifecycle.py)

A separate child held a real SQLite write lock across finalization and process exit. The next launch restored the exact multiline Unicode answer once. Replaying the same submission returned its completed receipt with Ollama unavailable. Revocation between process exit and recovery withheld the final answer. Conflicting payloads and stale grants remained rejected. [Submission tests](../tests/test_foundation.py) · [Grant tests](../tests/test_request_grants.py)

Deadline tests stalled startup, a terminal write, an unrelated desktop task and service cleanup. Each close attempt returned control within its test bound. A close with a durable pending reply offered retry or restart recovery. Simulated failure of both database and recovery writes kept the memory-only reply available for retry. [Windows desktop tests](../tests/test_desktop.py)

The full Windows suite recorded **59 passes and one skip** at Feature 1.2 closure. All history acceptance scenarios passed. The existing picker symlink test skipped because the account lacks link-creation privileges. Feature **1.2 Project session and chat** meets its Foundation backlog criteria. Phase 2 has additional M1 gates.

## Offline traffic verification

**1.3.1.1 completed on the MSI Thin A15, 23 November 2026.** The backlog requires cloud fallback, telemetry and external update traffic to be disabled during offline sessions. The tested profile uses dedicated CPython 3.12.13, headless Ollama 0.40.17 and the M0-pinned Qwen 3 4B. The four persistent outbound rules cover Python, Ollama, llama-server and llama-quantize on all Windows Firewall profiles.

| Requirement | Windows evidence |
|---|---|
| Loopback-only model traffic | A live pinned Qwen chat returned visible text on the desktop Qt event loop. Windows also identified the loaded llama-server child at the private image path and showed only loopback listeners for it. IPv4 and IPv6 socket fixtures verified numeric endpoints, ignored proxy overrides and refusal to follow redirects. An unrelated listener on the requested port failed verification. |
| Worker enforcement | Worker DNS, socket creation, external datagrams and unapproved child-process paths were denied. UNC and mapped project roots were refused before resolution. A worker in the private interpreter with the Python hook absent received Winsock 10013 on an external TCP connect, independently exercising Windows enforcement. |
| Cloud fallback | The real server reported disabled cloud functionality. Missing, false and malformed status, remote model entries and an unverifiable native policy all prevented the chat POST. |
| Telemetry and updates | Diagnostics wrote a local JSONL event with exporter settings present and rejected a network sink. The model launcher supplies a private headless runtime and clean environment. The GUI/updater layout was rejected before launch. |

The full Windows suite recorded **68 passes and one skip**. All nine offline acceptance tests ran, including the opt-in live model and firewall test. The existing directory-symlink test skipped because Windows denied link creation.

**1.3.1.2 Trace offline modes is next.** The release gate still needs process-attributed observations across a disconnected cold boot and a connected cold boot with offline mode selected. Independently running Windows services and the user's separate Ollama installation must be distinguished in that trace. [Windows acceptance tests](../tests/test_offline_policy.py) · [Launch, repeat acceptance and remove rules](windows-offline-profile.md)

## Cold-boot trace evidence

**1.3.1.2 remains open.** On 23 November 2026, a connected MSI rehearsal exercised a real completed Qt/Qwen turn with offline mode enabled. Kernel-Boot reported type 2. During the measured turn, ETW attributed 27 socket events, 256 transport events and four local name-resolution events to the assistant stack. All were loopback. The ETL header reported zero lost events and zero lost buffers. The reserved-name observer control was visible separately. Some background traffic lacked process identity in this first capture. The report preserves that uncertainty. [Measured rehearsal](evidence/1.3.1.2/rehearsal.json)

The collector now takes a process snapshot before each workload in addition to recording process lifetimes. A release verdict requires two distinct full boots, correct network conditions and complete attribution of external activity. The synthetic classifier tests cover PID reuse, unrelated Ollama processes, blocked attempts, DNS, loss, missing activity, network changes and duplicate boots. [Windows capture procedure](windows-cold-boot-trace.md) · [Acceptance tests](../tests/test_offline_trace.py)

The disconnected run was armed and Windows confirmed the named session was running. At handoff, `cold-disconnected-01` contained the arm journal and ETL only. The connected run had yet to start. Five classifier tests passed. The native paired acceptance test awaits both completed captures.

