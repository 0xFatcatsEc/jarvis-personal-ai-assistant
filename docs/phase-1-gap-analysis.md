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
| 1.2.2.1 Create local store | Complete for M1 | Foreign-key enforcement and live WAL placement verified on Windows. Upgrade, rollback and FTS5 passed on the identified application runtime. The distribution binary passed the local-store suite in 1.3.2.1. See [local store verification](#local-store-verification). |
| 1.2.2.2 Stream and reopen history | Complete for M1 | Windows process-restart and Qt tests cover ordered history, distinct terminal states, final-write recovery, model-independent replay and bounded close attempts. See [history verification](#history-verification). |
| 1.3.1.1 Guard model and worker traffic | Complete for the provisioned Windows profile | The dedicated desktop and headless Ollama run under effective outbound rules. Windows acceptance covered real Qwen inference, native outbound denial, worker policy, cloud refusal and updater exclusion. See [offline traffic verification](#offline-traffic-verification). |
| 1.3.1.2 Trace offline modes | Complete | Both cold boots passed on the MSI with offline mode enabled. The Windows acceptance test verified the pair and both ETL fingerprints. See [trace evidence](#cold-boot-trace-evidence). |
| 1.3.2.1 Pin and reinstall | Complete on the MSI | The standalone offline bundle installed into a fresh rehearsal profile, generated a local Qwen reply, and reopened it. The packaged interpreter passed the SQLite and schema rollback checks. See [release qualification](#windows-offline-release-qualification). |
| 1.3.2.2 Bounded diagnostics | Complete on the Windows checkout | The local Qt view, terminal outcomes, privacy, queue saturation, degraded sink and rotation passed Windows acceptance. See [bounded diagnostics verification](#bounded-diagnostics-verification). |

## Completed behaviors and verification

The 11-test Windows suite passed at the review point. It exercised SQLite WAL/foreign keys, invalid schema refusal, duplicate submission with a healthy model, scoped switching, cancel/stream failure, stale checkpoints, restart reconciliation, oversized input, validated settings, digest mismatch and redirect refusal. The desktop test drove PySide6 against an HTTP fixture over actual loopback, closed the application services, removed the fixture server and read the saved reply on a second launch. It did not load Qwen weights. At the initial review the PRD’s A1, A6 and A9 gates were open. Full A2–A5 and A7 have companion work in other phases.

## File review and module explanations

Paths are relative to `src/stylus_jarvis/` unless marked as repository files.

| Files inspected | What they implement | Assessment |
|---|---|---|
| `bootstrap.py`, `__main__.py` | Windows SID, Qt lock, composition, startup/close, user commands and event dispatch | Desktop path exercised. Bootstrap also owns session and presentation logic assigned elsewhere in the blueprint. |
| `settings.py`, `release-manifest.toml` | Immutable Pydantic preferences, atomic replace, release facts and loopback validation | Defaults and validation tested. Profile selection, repair UI and expanded manifest are pending. |
| `runtime/diagnostics.py` | Typed events, bounded queue, rotating JSONL and memory health state | Desktop exposes the sink status, queue depth, drops and recent events. |
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
3. **High — offline traffic evidence. Resolved for the tested Foundation profile in 1.3.1.2.** Both cold boots produced zero external events attributed to the assistant.
4. **Medium — replay required Ollama. Resolved in 1.2.2.2.** Stored terminal submissions replay after payload and grant checks without model access.
5. **Medium — shutdown deadline covered only the slot. Resolved in 1.2.2.2.** Startup, slot drain, desktop tasks and service cleanup share a deadline. An expired attempt reports the outstanding work and keeps the window available.
6. **Medium — resolved data directory could differ from checked profile. Resolved in 1.2.2.1.** The database writer checks the canonical target and its Windows volume type before opening SQLite. The Windows suite covers junctions into a configured OneDrive root and denial of a remote drive type.
7. **Medium — stale UI state can lose work or mislead.** Selection clears the draft, older command failures can update the new selection’s status, and startup failure re-enables controls without a valid runtime. Add scoped draft retention and a distinct recovery screen.
8. **Medium — long histories still accumulate in UI memory.** Reads are paginated, but the widget displays the entire matching conversation. The same-scope refresh race was fixed and tested in 1.2.2.2. A bounded display window remains a separate large-history improvement.
9. **Low — migration checkout bytes pinned in 1.3.2.1.** Git enforces LF for migration SQL. The release manifest pins the exact bytes used by the packaged database ledger.

## Architecture deviations and technical debt

Session ownership lives across bootstrap, repository and coordinator rather than the blueprint’s session service. Prompt assembly spans repository and router. The UI controller has direct access to concrete repositories and model routing. Scope records reside in messages rather than the planned context module. Move boundaries incrementally when addressing the corresponding lifecycle defects. Preserve the tested SQLite and transport contracts. Future-phase modules have no delivery obligation in this increment.

The database actor has one connection and an unbounded executor work queue. Per-frame authorization and full reply-prefix concatenation each add overhead. Profile sustained streams, large history and mixed workloads before changing these paths. The diagnostics schema and failure envelope need contract tests. An abrupt Windows process exit is covered. Physical disk exhaustion, suspend/resume and callbacks after native window destruction remain open operational tests.

## Implementation increment at the initial audit

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

The packaged CPython interpreter passed all nine Windows local-store tests, including FTS5, in 1.3.2.1.

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

**1.3.1.2 Trace offline modes is complete.** Packaging qualification followed in 1.3.2.1. [Windows acceptance tests](../tests/test_offline_policy.py) · [Launch, repeat acceptance and remove rules](windows-offline-profile.md)

## Cold-boot trace evidence

**Initial rehearsal.** On 23 November 2026, a connected MSI rehearsal exercised a real completed Qt/Qwen turn with offline mode enabled. Kernel-Boot reported type 2. During the measured turn, ETW attributed 27 socket events, 256 transport events and four local name-resolution events to the assistant stack. All were loopback. The ETL header reported zero lost events and zero lost buffers. The reserved-name observer control was visible separately. Some background traffic lacked process identity in this first capture. The report preserves that uncertainty. [Measured rehearsal](evidence/1.3.1.2/rehearsal.json)

The collector now takes a process snapshot before each workload in addition to recording process lifetimes. A release verdict requires two distinct full boots, correct network conditions and complete attribution of external activity. The synthetic classifier tests cover PID reuse, unrelated Ollama processes, blocked attempts, DNS, loss, missing activity, network changes and duplicate boots. [Windows capture procedure](windows-cold-boot-trace.md) · [Acceptance tests](../tests/test_offline_trace.py)

**Disconnected capture `cold-disconnected-01` is inconclusive.** Windows recorded a full boot and a completed offline turn. The original appended ETL reused the previous boot's clock origin. Reanalysis using 786 native process-start timestamps recovered the desktop, launcher, model server, runner, DNS and socket controls. All 29 attributed assistant socket events and four DNS events were local. The trace contained no independent kernel transport events during the workload. The saved default-route counts also lacked interface state. Neither fact can be recovered by repeating classification. [Disconnected reanalysis](evidence/1.3.1.2/disconnected-01-reanalysis.json)

**The replacement collector is ready for cold-boot acceptance.** A fresh WPR profile records process and socket events in nonpaged buffers and independently observes the model connection in the TCP/IP driver. Network snapshots record each default route's interface state. MSI rehearsal `repair-rehearsal-05` recovered all eight controls, with 37 assistant socket events, 37 transport events and four DNS events, all loopback. Both source loggers reported zero lost events. The boot registration and cancellation check also succeeded. Nine classifier tests passed. At this point the native two-boot test still needed both captures. [Collector rehearsal](evidence/1.3.1.2/collector-rehearsal.json) · [Exact execution steps](windows-cold-boot-trace.md)

**Disconnected attempt `cold-disconnected-02` stopped before the workload.** The network snapshot showed no active physical links. Kernel-Boot record 75341 reported type 1 and the kernel boot time matched the Arm snapshot. Run rejected the hybrid boot. The subsequent Finish cancelled the pending recording. There is no workload journal or ETL for this attempt. Finish now checks the completed workload and final snapshot before stopping the recorder. The next planned pair is `cold-disconnected-04` and `cold-connected-01`.

**Disconnected capture `cold-disconnected-04` is inconclusive.** The full boot and offline workload completed with all eight controls, zero source or merged trace losses, and zero attributed external assistant events. Before and after the workload, Windows reported no active physical links. At Finish, Windows reported a connected IPv4 route and internet access. This was the only failed evidence check. The next disconnected run is `cold-disconnected-05`; keep the MSI disconnected through Finish. The connected cold boot is also pending. [Disconnected report](evidence/1.3.1.2/disconnected-04.json)

**Disconnected capture `cold-disconnected-05` is inconclusive.** The recovered instance-named WPR output showed all eight controls, zero lost events and zero attributed external assistant events. All three snapshots were disconnected. Windows WLAN history recorded association at 22:24:45 and disconnection at 22:26:27 (Singapore time), before the workload began at 22:26:37. The profile transition was the only issue. Acceptance still requires a continuously disconnected boot and a separate connected boot with offline mode selected. [Recovered report](evidence/1.3.1.2/disconnected-05.json)

**Disconnected capture `cold-disconnected-06` passed.** The original report left one external DNS lookup unattributed. The raw ETL places DNS Client event 3006 at 14:48:52.099 UTC (PID 18560, thread 18632), after the recorded start of the separate ChatGPT.exe process at 14:48:30.091 UTC. The XML mixed +07:59 and +08:00 offsets, and applying the header correction uniformly moved this event back one minute. Reclassification of the same fingerprinted ETL with per-record offset handling recovered the owner. All eight controls were present. The 28 socket, 28 transport and four DNS events attributed to the assistant were loopback. No events or buffers were lost. This completed the disconnected half of the pair. [Passing disconnected report](evidence/1.3.1.2/disconnected-06.json)

**1.3.1.2 closed on 23 November 2026.** Windows had internet access during `cold-connected-01` while the completed desktop workload used offline mode. All 40 socket, 40 transport and four DNS events attributed to the assistant were loopback. Both captures recorded all eight positive controls, zero external assistant events and zero lost events or buffers. The native acceptance test reclassified both recordings, checked their ETL fingerprints and verified distinct full boots on the same MSI. All 12 offline trace tests passed with native acceptance enabled. [Connected report](evidence/1.3.1.2/connected-01.json) · [Disconnected report](evidence/1.3.1.2/disconnected-06.json)

## Windows offline release qualification

**1.3.2.1 closed on the MSI Thin A15 on 24 November 2026.** The 8,202,771,648-byte Foundation bundle installs build 0.1.0, CPython 3.12.13, SQLite 3.50.4, schema 2, headless Ollama 0.40.17 and Qwen 3 4B. It includes 19 wheels and the 11 verified M0 assets. The manifest identifies every payload by SHA-256. [Release manifest](evidence/1.3.2.1/bundle.json) · [Offline installation and rollback](windows-foundation-release.md)

The Windows account used a fresh assistant profile with separate executable paths and outbound firewall rules. Installation read local wheels with the package index disabled. The Qt desktop created a sample project, completed a Qwen conversation, exited, and reopened its saved reply in a second process. The desktop and model ran with their outbound blocks active and without cloud credentials. The host network remained available during this packaging rehearsal.

The installed interpreter passed all nine Windows local-store tests, including WAL, FTS5, failed migration rollback and backup restoration. The earlier application revision f6c7aad created a schema-1 project and completed turn. The installed release opened them under schema 2. After restoring the pre-upgrade database to a separate directory, the earlier revision reopened the same project, conversation ID and ordered messages. The Windows repository suite ran 81 tests with 79 passes and two skips. The next sequential item is **1.3.2.2 Record bounded diagnostics**.

## Bounded diagnostics verification

Backlog 1.3.2.2 is complete for the Windows checkout as of 2026-11-24. The local PySide6 diagnostics view showed the release manifest build and pinned model digest. SQLite writer events included executor wait and transaction duration. Terminal-frame fixtures exercised normal stop, explicit length, reasonless budget exhaustion at 96 tokens and provider failure. A separate cancellation test preserved the partial reply during saturation. The original packaged reply has no saved stop metadata to reclassify.

| Windows acceptance check | Observed result |
|---|---|
| Queue and recent view | A stalled writer with one in-flight entry accepted 256 queued events. Ten subsequent events were dropped. The recent view retained 32 entries. |
| Write failure and cancellation | Counting saturation, the failed in-flight write, the queued entries and the final rejected event produced 270 drops and an empty queue. The cancelled reply reopened from SQLite. |
| Owner visibility | With the log directory obstructed, the desktop showed degraded status. Stop saved a cancelled turn and its outcome appeared in the local view. |
| Rotation and privacy | At a test threshold of 1,400 bytes, the active file and both backups stayed within the limit. The scan found no seeded private markers. Production uses 2 MiB per file. |
| Regression run | The Windows checkout ran 84 tests in 31.827 seconds, with 82 passes and two skips. The skipped checks required the opt-in native firewall/model runtime and permission to create a directory symlink. All diagnostic acceptance checks ran. |

The packaging qualification above applies to the previously built bundle. This run exercised the updated checkout with deterministic provider frames and a real SQLite database. [Operator guide and repeatable commands](windows-bounded-diagnostics.md)

## Phase 2 handoff and source registry verification

**2.1.1.1 Assign source revisions is complete on the Windows checkout, 24 November 2026.** The first registry acceptance test approved a file, replaced it atomically, approved its new content, and verified one stable source ID and two distinct revision IDs. Both receipts and byte digests remained addressable after file deletion and database restart. Historical evidence at this stage consists of metadata.

The suite also verified simultaneous approvals, project isolation, grant revocation during hashing, direct update refusal, desktop file approval, and preservation of the schema-2 conversation in the pre-upgrade snapshot. The final Windows run executed 87 tests in 31.726 seconds with 85 passes and two skips (opt-in live model/firewall and directory-symlink privilege). All source registry tests ran. This evidence covers the checkout. The installed Foundation bundle remains the separately qualified schema-2 artifact.

The next item is **2.1.1.2 Extract page and text locators**. Feature 2.1 and PRD A2/A3 remain open. [Phase 2 technical design and acceptance criteria](phase-2-technical-design.md) · [Windows source registry tests](../tests/test_source_revisions.py)

## Phase 2 locator verification

**2.1.1.2 Extract page and text locators is complete on the Windows checkout.** Schema 4 retains versioned excerpts for explicitly selected source revisions. The Windows PDF case resolved page 2 after source deletion and database reopen, preserved the original three page numbers and flagged the image-only page for OCR. The text case recovered the second Unicode range after replacement and restart. Supplying its locator ID with the newer revision or another project's scope was denied. Concurrent extraction returned identical records. Changed source bytes and a grant revoked during extraction each prevented publication.

The final Windows suite ran 90 tests in 34.506 seconds, with 88 passes and two skips (opt-in live firewall/model check and directory-symlink privilege). All locator acceptance checks and the Qt excerpt action passed. The evidence covers the checkout. The next backlog item is **2.1.2.1 Build scoped FTS5 index**. End-to-end retrieval and grounded citations still have their own acceptance gates. [Phase 2 design](phase-2-technical-design.md) · [Windows locator acceptance tests](../tests/test_evidence_locators.py)

## Phase 2 scoped FTS5 verification

**2.1.2.1 Build scoped FTS5 index is complete on the Windows checkout.** All six primary scenarios passed. Every text-bearing locator of the two-part fixture remained searchable after database reopen. An independent SQLite reader observed the old active revision and zero candidate matches after the writer inserted the first new posting. Aborting the second insertion left no partial historical or active result. Retry published both locators. Explicit replacement and rename switched active results, while revision-specific searches retained the old evidence.

The same search term in two projects returned only each project's own locator. A foreign predecessor was denied. Revocation after extraction prevented publication and stale-grant search. The final suite ran 93 tests in 34.894 seconds, with 91 passes and two skips (opt-in live native firewall/model test and directory-symlink privilege). All scoped index tests ran. This records schema-5 checkout evidence. The next backlog item is **2.1.2.2 Assemble cited context**. [Design and repository APIs](phase-2-technical-design.md#2121-atomic-publication-in-scoped-fts5) · [Windows acceptance tests](../tests/test_scoped_index.py)

## Phase 2 cited context verification

**2.1.2.2 Assemble cited context is complete for the Windows checkout.** The repository assembles a bounded extractive bundle from schema-5 postings in a project-authorized snapshot. On the frozen two-project PDFs, all 16 grounded questions returned their expected fact on the first cited page, all four missing-evidence questions returned an empty insufficient-evidence bundle, and every returned citation resolved within its project. This qualifies retrieval for Feature 2.1. Generated-answer qualification remains part of the integrated A2 gate.

Additional Windows tests grouped identical copies with both citations, merged overlapping ranges, retained disagreeing CSV and JSON claims in one project, resolved a retired revision and denied delivery after grant revocation. Exact UTF-8 payload and passage caps were exercised. The next sequential item is **2.2.1.1 Capture explicit scope**. [Technical design and API](phase-2-technical-design.md#2122-assemble-deduplicated-cited-context) · [Windows acceptance tests](../tests/test_cited_context.py)

Final Windows regression evidence used a fresh interpreter for each module after shared-process reruns failed to finish. All 96 tests were accounted for, with 94 passes and two existing skips (live native firewall/model qualification and Windows directory-symlink permission). The standalone cited-context suite also passed all three tests.

## Phase 2 explicit memory capture verification

**2.2.1.1 Capture explicit scope is complete on the Windows checkout.** The Qt editor displayed the project destination, discarded an abandoned draft, and saved the owner's explicitly selected personal fact after confirmation. Repository acceptance verified that an unapproved inferred proposal produced no durable fact, exact confirmation retries were idempotent, changed retries failed, and reads stayed within the chosen owner and destination. A grant revoked before confirmation prevented storage. After SQLite reopen the confirmed statement, original version and evidence citation remained addressable.

Schema 6 adds the fact registry and version records. The migration test inspected the pre-6 schema-5 snapshot and its original conversation. Windows regression ran 99 tests in isolated modules with 97 passes and two existing skips (native firewall/model opt-in and directory-symlink permission). A final focused rerun passed all 17 memory, migration and desktop tests. This is checkout qualification. The next item is **2.2.1.2 Resolve supersession**. [Design and API](phase-2-technical-design.md#2211-capture-explicit-scope) · [Memory acceptance tests](../tests/test_memory_capture.py)

## Phase 2 confirmed fact supersession verification

**2.2.1.2 Resolve supersession is complete on the Windows checkout.** Confirmation appended version 2 under the original fact ID. Across SQLite reopen, active recall returned only version 2, and exact reads of versions 1 and 2 resolved their corresponding retained excerpts after external source replacement and removal. A declined correction left version 1 active. Concurrent corrections using two database connections yielded one successor and one stale-predecessor conflict. A revoked grant created no version. Tests also verified project isolation, explicit personal selection and owner boundaries. The Qt flow selected a personal fact, displayed its predecessor, locked its destination and required a fresh confirmation.

Schema 6 already supplies the immutable version chain. This increment required no migration or reindex. Windows regression accounted for 102 tests across isolated modules, with 100 passes and two existing skips (opt-in live firewall/model check and directory-symlink permission). The final five-test desktop rerun passed. The next sequential item is **2.2.2.1 Suppress deleted facts**. [Supersession design and APIs](phase-2-technical-design.md#2212-resolve-supersession) · [Windows acceptance tests](../tests/test_memory_capture.py)

## Phase 2 forgotten-fact verification

**2.2.2.1 Suppress deleted facts is complete on the Windows checkout.** The first acceptance test failed on the missing forget API before implementation. It now passes through explicit forget, source replacement and FTS5 publication, SQLite reopen, and attempted inference under fresh fact IDs. Recall, historical fact reads and corrections with the forgotten ID are blocked. A matching fact in another project and the original document citation remain accessible under their own scopes.

Qt acceptance exercised cancellation and explicit personal-memory confirmation. Repository tests covered scope and grant denial, stale versions, repeat confirmation, and a failure between independent ledger commit and primary cleanup. SQLite reopen finished cleanup. Opening an older primary with a newer matching ledger replayed the deletion. Missing and detectably older ledgers blocked startup. Schema 7 adds the ledger binding; the independent ledger is required alongside the primary store. Restore coverage verification remains assigned to 2.3.2.1.

The Windows regression ran each module in a fresh interpreter with recorded boot acceptance enabled. **104 passed and two existing tests skipped** (opt-in live firewall/model and directory-symlink permissions). All ten memory tests, five desktop tests and nine local-store tests passed. The next backlog item is **2.2.2.2 Export scoped history and facts**. [Implementation and recovery rules](phase-2-technical-design.md#2221-suppress-deleted-facts) · [Memory tests](../tests/test_memory_capture.py)

## Phase 2 scoped export verification

**2.2.2.2 Export scoped history and facts is complete on the Windows checkout.** The repository test exported two conversations and the latest fact from one project, with the exact original evidence reference after file replacement and removal. It excluded the second project's records, personal memory, active turns, superseded versions and a forgotten fact whose primary cleanup had failed. Additional checks verified revoked-grant denial, temporary-file cleanup and preservation of a preexisting destination. Qt acceptance chose the file and parsed the resulting manifest.

The Windows regression ran 108 tests in isolated modules with 106 passes and two existing skips (opt-in live firewall/model test and directory-symlink permission). Both export tests and all five desktop tests passed. Schema stays at 7. The next sequential item is **2.3.1.1 Schedule consistent snapshots**. [Design and format](phase-2-technical-design.md#2222-export-scoped-history-and-facts) · [Windows export tests](../tests/test_memory_export.py)

## Phase 2 scheduled snapshot verification

**2.3.1.1 Schedule consistent snapshots is complete on the Windows checkout.** The configurable desktop schedule publishes verified AES-256-GCM snapshots of the committed SQLite database and a separately encrypted deletion-ledger artifact. The Windows fixture held an independent write transaction open throughout backup. Decrypted SQLite passed integrity checks and contained the committed owner value, and the live writer could still update and commit. Wrong keys and modified ciphertext failed authentication. The scheduler fixture verified restart-safe daily timing, retained the last-success receipt after failed publication, and retried successfully. Key separation and shutdown were also verified.

Windows regression ran 111 tests across isolated modules with 109 passes and two existing skips (opt-in live firewall/model test and directory-symlink permission). All three snapshot tests passed. No live profile was configured by these tests. The 24-hour loss and 30-minute restore targets still require clean-profile qualification. The next sequential item is **2.3.1.2 Expose recovery status**. [Configuration and format](phase-2-technical-design.md#2311-schedule-consistent-snapshots) · [Windows snapshot tests](../tests/test_snapshots.py)

## Phase 2 recovery status verification

**2.3.1.2 Expose recovery status is complete on the Windows checkout.** The Qt panel shows the configured destination and elapsed time since the last verified backup. Removing the destination or a backup artifact reported the problem without clearing the success age. Snapshot-time source dependencies remained scoped to the selected project and identified the unavailable original after deletion. Sources approved after capture were excluded from that inventory.

Windows regression ran 113 tests in isolated modules, with **111 passes and two existing skips** (opt-in live firewall/model test and directory-symlink permission). All five snapshot tests and five desktop tests passed. No live profile was configured. The next sequential item is **2.3.2.1 Reconcile deleted records** during staged restore. [Recovery panel and receipt design](phase-2-technical-design.md#2312-expose-recovery-status) · [Snapshot tests](../tests/test_snapshots.py)

## Phase 2 staged deletion reconciliation verification

**2.3.2.1 Reconcile deleted records is complete on the Windows checkout.** The older encrypted primary was staged using its authenticated ledger and a later independent ledger set. The report recorded sequence 0 to 1 and one removed fact. The staged pair reopened in a fresh database and returned only the surviving fact. The staged ledger blocked re-inference under a fresh fact ID. Absent independent evidence, insufficient sequence coverage, an unavailable ledger path, missing ledger artifacts and tampering produced report-only quarantine. Invalid primary authentication published nothing. The CLI protects the active profile and publishes no changes to it.

Windows regression ran 116 tests in isolated modules with **114 passes and two existing skips** (opt-in live firewall/model and directory-symlink permission). All three staged-restore tests passed again after the final path checks. Schema remains 7. The next item is **2.3.2.2 Rehearse migration and rollback**. [Procedure and report](phase-2-technical-design.md#2321-reconcile-deleted-records) · [Windows acceptance tests](../tests/test_staged_restore.py)

## Phase 2 migration and rollback rehearsal

**2.3.2.2 Rehearse migration and rollback is complete for the versioned sample on the MSI Thin A15 B7UC.** The final offline run upgraded schema 6 to 7 and used the older matching wheel with the original pre-upgrade snapshot for rollback to schema 6. Staged encrypted restore and content verification took **0.184 s**. The simulated recovery point was **23 h 59 min** old. The surviving conversation, fact and citation reopened; a later deletion was replayed; missing coverage quarantined the backup. Recovery status identified the removed original. Matched-binary rollback and verification took **0.886 s**. The run used temporary profiles and did not activate a restore or use the live database.

This completes the Phase 2 backlog and supplies M1 recovery evidence for the rehearsal fixture. The timing does not establish a production backup cadence or installed offline MVP qualification. Phase 3 starts at **3.1.1.1 Select microphone and hotkey**. [Machine-readable MSI evidence](evidence/2.3.2.2/msi-rehearsal.json) · [Rehearsal procedure](phase-2-technical-design.md#2322-rehearse-migration-and-rollback)

## Phase 3 microphone and hotkey verification

**3.1.1.1 is implemented on the Windows checkout.** The UI supports endpoint selection, foreground F8/F9/F12 hold-to-record, and a visible recording indicator. Automated tests passed selected-device dispatch, auto-repeat handling, key and mouse release, cancelling on window deactivation, no-device keyboard input, and whole-frame PCM handling. The MSI reported one native input endpoint. No physical microphone was activated during the automated checks.

The Windows regression ran 120 tests with 118 passes and two existing skips. The final focused run passed all five voice tests. Physical start and release remain a short hands-on check. The next implementation item is **3.1.1.2 Handle device loss**. [Technical design and MSI smoke test](phase-3-technical-design.md)

**3.1.1.1 interactive MSI acceptance passed.** The owner supplied a live trace showing successful start and release for both the button and selected hotkey with no Qt state-conversion error. This closes the outstanding physical control check. Next is **3.1.1.2 Handle device loss**. [Voice acceptance record](phase-3-technical-design.md#3111-select-microphone-and-hotkey)

## Phase 3 device-loss verification

**3.1.1.2 Handle device loss passed Windows checkout acceptance with simulated device removal.** The selected endpoint disappearing during hold stopped and discarded the partial capture. The loss message directed the owner to typing, and the composer retained its draft and focus. The desktop test completed the typed draft, sent it over local loopback and confirmed the reply in the original conversation. The voice tests also covered release before the removal notification, backend failure and a fresh press after reconnect. Physical USB unplug remains an optional hardware smoke test and part of the integrated voice qualification.

Windows regression ran 125 tests across isolated modules with **123 passes and two existing skips**. All nine voice tests and five desktop tests passed. The next sequential item is **3.1.2.1 Run local Whisper worker**. [Device-loss design and smoke test](phase-3-technical-design.md#3112-handle-device-loss)
