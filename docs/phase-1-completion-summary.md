# STYLUS JARVIS — Phase 1 Foundation completion summary

**Decision, 24 November 2026.** Close Phase 1 Foundation and proceed to **2.1.1.1 Assign source revisions**. The Windows checkout at `28ed2c3` meets all 12 Foundation subtask criteria, covering six tasks and three features. M0 is complete. M1 still requires Phase 2 memory and recovery. M2 still requires the integrated offline assistant and its owner's release decision.

This is a review of the committed implementation, tests and recorded qualification runs. The latest Windows run recorded 82 passes from 84 tests. The opt-in native model/firewall test passed in the earlier offline qualification. Directory symlink creation lacked Windows permission, while real junction and case-alias tests passed. Neither skip leaves a Foundation criterion open. The review used the [development backlog](../outputs/stylus-development-backlog/STYLUS%20JARVIS%20Development%20Backlog.xlsx), [architecture review](../STYLUS%20JARVIS%20Architecture%20Review%20and%20V2%20Design.docx), [PRD](../STYLUS%20JARVIS%20Product%20Requirements%20Document.docx), [technical design](phase-1-technical-design.md) and dated closure entries in the [gap analysis](phase-1-gap-analysis.md). Its initial audit table predates several of those closures.

## Foundation acceptance register

| Backlog item | Accepted evidence |
|---|---|
| 1.1.1.1 Inventory the laptop | Recorded RAM, disk space, 4 GiB GPU, driver and AC power profile on the MSI. [Hardware receipt](evidence/m0-hardware.json) |
| 1.1.1.2 Freeze evaluation fixtures | Two conflicting projects, 16 grounded questions, four abstentions, and pinned fixture hashes. [Fixture contract](../tests/fixtures/m0-v1/README.md) |
| 1.1.2.1 Provision local assets | Verified 11 pinned files, including Qwen's blob chain and the Piper voice card. [Asset receipt](evidence/m0-assets.json) |
| 1.1.2.2 Compare Qwen builds | With VS Code open, 4B scored 20/20 recall with zero disclosures and 0.584 s warm p95 to first visible content. 8B exhausted GPU memory on load in the tested configuration. [Measured decision](../outputs/qwen-msi-02/decision.md) |
| 1.2.1.1 Create project picker | Identically named roots retained distinct IDs after reopening. Keyboard selection and junction aliases passed. [Picker tests](../tests/test_project_picker.py) |
| 1.2.1.2 Bind requests to grants | Dispatch preserved scope. Revocation stopped delivery while allowing terminal bookkeeping. [Grant tests](../tests/test_request_grants.py) |
| 1.2.2.1 Create local store | Resolved WAL location outside OneDrive, foreign keys, FTS5, migration and rollback verified. [Store tests](../tests/test_local_store.py) |
| 1.2.2.2 Stream and reopen history | Process restart preserved ordering, cancelled and interrupted states and recoverable final text. Completed submissions replayed with the model unavailable. [Lifecycle tests](../tests/test_history_lifecycle.py) |
| 1.3.1.1 Guard model and worker traffic | Dedicated interpreter and headless model processes exercised under outbound firewall rules. Worker DNS, cloud fallback and updater controls verified. [Offline qualification](windows-offline-profile.md) |
| 1.3.1.2 Trace both network modes | Distinct full boots, all eight controls, zero attributed external assistant events and zero losses in both accepted captures. [Disconnected](evidence/1.3.1.2/disconnected-06.json) · [Connected](evidence/1.3.1.2/connected-01.json) |
| 1.3.2.1 Pin runtime and schema versions | Fresh-profile install from local assets, chat reopening, schema 1 → 2 upgrade and restoration to the prior binary and schema 1 passed. [Bundle manifest](evidence/1.3.2.1/bundle.json) · [Qualification record](phase-1-gap-analysis.md#windows-offline-release-qualification) |
| 1.3.2.2 Record bounded diagnostics | Qt exposed build, digest, stage timings, sink health and drops. Tests exercised rotation, privacy, saturation and cancellation. Token-limited replies retained a distinct outcome in history and replay. [Windows verification](phase-1-gap-analysis.md#bounded-diagnostics-verification) |

**Qualification boundary.** The packaged 0.1.0 wheel has a recorded SHA-256 and predates the diagnostics changes. Its fresh-profile rehearsal ran with outbound blocks on a connected host. The cold-boot trace pair separately demonstrated offline behavior. Bounded diagnostics passed on the subsequent checkout using deterministic provider frames. For the eventual release, identify the candidate by digest and exercise the installed artifact through the integrated gates.

## PRD gates and remaining MVP blockers

| Gate | Current status and evidence needed for the release decision |
|---|---|
| A1 Offline start and history | Foundation evidence accepted for the tested profile. Exercise the integrated candidate in the 5.3 offline workflow and associate the evidence with its digest. |
| A2 Grounded recall | Open. Test real ingestion and retrieval across both projects, scanned-page handling and citations or abstentions. Require at least 18/20 and zero disclosures. The M0 benchmark supplied the evidence passages. |
| A3 Memory lifecycle | Open. Demonstrate confirmation, restart recall, supersession, citation resolution, forgetting through reindex and scoped export. |
| A4 Voice and keyboard | Open. Integrate offline Whisper and Piper, edit dictated input, interrupt playback, fall back to keyboard and verify temporary audio cleanup. |
| A5 Files and editor | Open. Explain a saved file and launch the approved project in VS Code under grants. Verify unchanged source hash, denied outside-root reads and denied document-requested uploads. |
| A6 Laptop performance | Open. Measure cold and 20 warm desktop turns with VS Code, repeat under indexing load, measure peak memory, voice latency and one-second stop feedback. Meet the five-second trial p95 or record the owner's explicit target revision. |
| A7 Disaster recovery | Open. Restore an encrypted snapshot using a separate key on a clean profile within 30 minutes and the 24-hour loss target. Verify deletion replay, missing-ledger quarantine and missing-source reporting. |
| A8 Advanced releases | Deferred to the releases introducing reviewed editor writes, connected accounts, sends, MCP and handoffs. These capabilities have no offline MVP dependency. |
| A9 Release reproducibility | Partial. The prior bundle proved install, conversation upgrade and rollback. The checkout proved diagnostic privacy. The release candidate still needs an installed rehearsal covering the reference fact alongside the conversation and diagnostics. |

The MVP decision belongs to **5.3 Offline MVP qualification** after **1.3, 2.3, 3.2, 4.1 and 5.1**. Record the build digest, passing results and any owner-approved performance revision, then obtain owner acceptance of F1–F8. The Phase 1 baseline supports starting Phase 2 now.

## Phase 2 implementation order

| Order and backlog items | Deliverable and reason for sequence |
|---|---|
| 1. **2.1.1.1 → 2.1.1.2** | Assign approved sources stable IDs and immutable revisions, then extract page/text locators. Replacement must retain source identity, and scanned pages must surface OCR-needed status. Citations depend on both identity and location. |
| 2. **2.1.2.1 → 2.1.2.2** | Publish complete revisions atomically in scoped FTS5, then assemble deduplicated cited context. Apply project filters before ranking and exercise conflicting evidence and abstentions against the frozen fixtures. |
| 3. **2.2.1.1 → 2.2.1.2** | Expose the destination before saving a fact, keep inferred facts pending and implement supersession. Historical citations must resolve to their original revision or report it unavailable. |
| 4. **2.2.2.1 → 2.2.2.2** | Persist suppression through restart and reindex, then export approved facts and history with scoped references. This establishes the deletion semantics needed during restoration. |
| 5. **2.3.1.1 → 2.3.1.2** | Schedule verified encrypted snapshots during local writes, keep the recovery key separate and expose last success, destination failure and external-source dependencies. |
| 6. **2.3.2.1 → 2.3.2.2** | Restore into staging, replay the independent deletion ledger and quarantine uncertain records before activation. Rehearse timed clean-profile restore and matching-binary rollback with known facts before M1 sign-off. |

## Technical debt to carry forward

| Priority and point of action | Risk and recommended treatment |
|---|---|
| High at indexing integration | SQLite has one writer and an unbounded executor submission queue. Bound ingestion batches and measure writer wait, chat responsiveness and cancellation under mixed load. Preserve the single transaction owner. |
| High at retrieval integration | The MSI reached 7,294 MiB sampled system RAM in qualification. Qwen 4B scored 4/10 on coding, and its first visible content sometimes contained deliberation. Measure useful answer latency and quality under realistic retrieval budgets. Keep partial generations distinguishable from completed answers. |
| Medium as new modules land | Session ownership spans bootstrap, coordinator and repositories. Prompt assembly spans storage and routing. Keep source identity, authorization and evidence selection behind explicit interfaces as those features arrive. Preserve grant revalidation at delivery. |
| Medium at UI and error handling | Drafts can clear on switching projects, stale errors can target the new selection, and full transcripts accumulate in the widget. Scope drafts and status updates, bound rendering, and expose retry and durability information in recovery flows. |
| Medium at recovery qualification | Exercise disk exhaustion, suspend/resume and window teardown under active work. Run the existing directory-symlink case on a suitably privileged account. Keep migration snapshots and the separate deletion-aware disaster-recovery rehearsal identifiable in the evidence. |

**Disposition.** Accept Foundation for further development. Carry the listed debt into its owning work, preserve the current qualification artifacts, and begin with approved source identity and revisioning.
