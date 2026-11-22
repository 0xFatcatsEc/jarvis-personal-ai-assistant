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
| 1.1.2.2 Compare Qwen builds | Missing | No measured cold/warm timings, RAM/VRAM, scored results or selected-profile decision. The manifest identifies a candidate. |
| 1.2.1.1 Project picker | Partial | Local roots, canonical identity, per-owner listing, project/thread selectors work. Test similarly named roots and alias collisions on Windows. |
| 1.2.1.2 Bind request scope | Partial | Owner, project, conversation, grant and generation captured. Repository queries are scoped; switch during streaming is tested. Live revocation and settlement need work. |
| 1.2.2.1 Create local store | Partial | WAL, FK enforcement, schema ledger and atomic operations tested. Validate the actual DB location after reparse resolution; exercise upgrade, rollback and FTS5 capability on shipped binaries. |
| 1.2.2.2 Stream and reopen history | Partial | Offscreen desktop test streams, saves and reopens with model offline. Tests verify ordered checkpoints, cancellation, deduplication and interrupted reconciliation. Retry and shutdown gaps below. |
| 1.3.1.1 Guard stack traffic | Partial | Application transport pins numeric loopback, disables proxies and redirects, exposes no cloud route. External Ollama runtime and updater remain independently configured. |
| 1.3.1.2 Trace offline modes | Missing | No process-attributed cold-boot trace detached from network and connected with offline mode selected. |
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
| `storage/repositories.py` | Project registration, grant checks, history, idempotent creation, checkpoints and finalization | Core transaction behavior is covered. Missing project-wide search and proper settlement after grant change. |
| `runtime/scheduler.py` | One inference reservation, cancellation and idle signaling | Busy rejection and active cancellation tested. Full shutdown duration remains unbounded. |
| `runtime/coordinator.py` | Request validation, context budget, generation, checkpoints, terminal receipt and unsaved retry | Primary lifecycle works. Duplicate retry still depends on live inference. |
| `inference/ollama.py` | Bounded local HTTP, verified model inventory, NDJSON parser and stream cleanup | Mock and loopback tests pass. Real runtime performance and update behavior unverified. |
| `inference/router.py` | Local profile, verified status and conservative context budgeting | Phase 1 local path implemented; avoid concurrent probe races. |
| `contracts/messages.py`, `contracts/ports.py` | Immutable records, stable failure codes and structural interfaces | Usable injection boundary. Failure lacks structured durability and retry fields specified in design. |
| `ui/main_window.py` | PySide6 layout, plain-text transcript, scope and stop controls | UI smoke test passes. No repair or recovery view. |
| All six package `__init__.py` files | Import-safe package markers | No changes needed. |
| Repository `pyproject.toml`, `uv.lock`, `.gitignore` | Entry point, Python 3.12+, runtime dependencies, resource and build exclusions | Dependency resolution recorded; build backend and native assets still require reproducible offline provisioning. |
| Repository `tests/test_foundation.py`, `tests/test_desktop.py` | Storage/model/scheduler/settings tests and offscreen Qt integration | Tests run successfully; planned architecture, acceptance and fixture suites have limited or no coverage. |

## Bugs and operational risks

Priority reflects impact within Foundation. These are code-inspection findings unless identified by the test descriptions above.

1. **High — unsaved final text can be discarded on close.** The coordinator retains failed finalization in memory. Desktop shutdown can return success while that pending save exists. Keep the window recoverable and offer retry before clean exit. Test a failed final commit followed by Close.
2. **High — changed grant prevents terminal bookkeeping.** Finalization calls the same live-grant check as content delivery. Revocation during generation can leave a turn active until restart. Permit scoped, status-only internal settlement without disclosing new content. Test revocation between last fragment and commit.
3. **High — release-mode offline guarantee is unproven.** Provider loopback checks cover application requests only. Establish a qualified local-only runtime and validate egress from the entire stack.
4. **Medium — idempotent replay unnecessarily requires Ollama.** Coordinator probes and builds context before looking up a previously committed submission. Resolve scoped prior receipts first. Test replay of an acknowledged submission with the model stopped.
5. **Medium — shutdown deadline only covers slot waiting.** Desktop subsequently gathers all tasks without a deadline. Report unresolved durability and distinguish forced exit from a clean close.
6. **Medium — resolved data directory can differ from checked profile.** A junction underneath the accepted base or a mapped network drive can violate local-disk policy. Revalidate final DB directory and volume type before open.
7. **Medium — stale UI state can lose work or mislead.** Selection clears the draft, older command failures can update the new selection’s status, and startup failure re-enables controls without a valid runtime. Add scoped draft retention and a distinct recovery screen.
8. **Medium — no last-page bound in history rendering.** The repository paginates, but the UI collects all pages in RAM. Two concurrent renders within the same scope can reorder the display. Use bounded pages and view-generation checks.
9. **Low — migration checksum depends on checkout line endings.** The ledger hashes raw SQL bytes. Enforce LF for packaged SQL or canonicalize bytes consistently before recording the first distributed migration.

## Architecture deviations and technical debt

Session ownership lives across bootstrap, repository and coordinator rather than the blueprint’s session service. Prompt assembly spans repository and router. The UI controller has direct access to concrete repositories and model routing. Scope records reside in messages rather than the planned context module. Move boundaries incrementally when addressing the corresponding lifecycle defects. Preserve the tested SQLite and transport contracts. Future-phase modules have no delivery obligation in this increment.

The database actor has one connection and an unbounded executor work queue. Per-frame authorization and full reply-prefix concatenation each add overhead. Profile sustained streams, large history and mixed workloads before changing these paths. The diagnostics schema and failure envelope need contract tests. End-to-end fault coverage still lacks a real process kill, full disk, suspend/resume, failed upgrade, grant revocation and closed-window late callbacks.

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

**1.1.2.2 is partially complete.** The [qualification harness and runbook](../benchmarks/README.md) compare digest-pinned 4B and 8B candidates on the same recall and coding cases. Automated tests exercise the paired run, residency, scoring and selection logic with a simulated server. The Windows RAM and NVIDIA memory counters were smoke-tested on the MSI. Closing M0 still requires real model measurements, graded answers and an owner decision. No runtime model pin has been changed.

