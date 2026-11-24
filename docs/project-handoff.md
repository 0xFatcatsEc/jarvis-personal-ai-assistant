# STYLUS JARVIS — engineering handoff

**24 November 2026 · Windows checkout · schema 6.** Phase 1 Foundation is accepted. Phase 2 retrieval and confirmed fact capture/correction are complete. M0 is closed, M1 still needs forgetting, export and disaster recovery, and M2 offline MVP qualification remains open. **Resume at 2.2.2.1 — Suppress deleted facts.**

**Preserve the working tree.** HEAD is `a8fe03d`. The completed memory increment includes uncommitted edits and untracked files, notably the memory package, schema-6 migration, Qt fact editor and memory acceptance tests. A clone of HEAD alone omits them. Check `git status --short` before branching or transferring the project. The separately qualified Windows rehearsal bundle is build 0.1.0 with schema 2. Qualification of that artifact does not extend to the schema-6 checkout. [Bundle manifest](evidence/1.3.2.1/bundle.json)

## Vision and architecture

Build a personal Windows assistant that can work offline on the owner's MSI Thin A15, remember approved decisions, and answer from verifiable project evidence without a cloud subscription. Voice, scoped tools and optional online integrations extend the local core.

The application is a Python 3.12 modular monolith. PySide6 and qasync handle interaction and confirmation. The runtime coordinator binds owner, project, conversation, mode and grant revision to requests. The scheduler admits one generation at a time. The inference router uses a pinned Qwen 3 4B model through loopback Ollama; Windows outbound rules and worker checks enforce the qualified offline profile. Repositories own SQL. A single SQLite worker serializes transactions using WAL in the local user profile outside OneDrive. Recheck authorization inside writes and immediately before delivering scoped data. Diagnostics retain bounded, allowlisted events. [Foundation design](phase-1-technical-design.md) · [Offline runbook](windows-offline-profile.md)

## Subsystem status

| Subsystem | Implemented behavior and entry points |
|---|---|
| Retrieval | Approve a source, extract revision-bound PDF pages or UTF-8 ranges, then publish the complete revision atomically in scoped FTS5. The desktop exposes approval and excerpt capture; publication and cited-context assembly are repository APIs. `cited_context` returns deduplicated excerpts with source, revision and locator IDs. Historical publications remain addressable. All 16 grounded fixture questions retrieved the expected first page; all four missing-evidence cases abstained. |
| Memory | The Qt editor requires confirmation and an explicit choice for personal scope. `confirm_fact` creates version 1; `correct_fact` appends against an expected predecessor. `recall_facts` returns the latest version per fact in the selected destination; `get_fact` resolves an exact version and its evidence. Project and personal reads remain separate. Fact forgetting and scoped export are pending. |
| Recovery | Chat restart reconciles interrupted turns. Failed terminal writes support retry or local recovery, and completed submissions replay without Ollama. The migration actor checks SQL digests and snapshots a populated database before upgrading. Scheduled encrypted backups, a separately recoverable key, deletion-ledger replay and staged restore qualification belong to Phase 2. |

Schema **6** adds `facts` and immutable `fact_versions`. Supersession uses their existing composite key. Earlier migrations introduced core chat, turn grants, source revisions, locators and the FTS5 index in that order. Add migrations without rewriting applied SQL. [Migrations](../src/stylus_jarvis/storage/migrations) · [Repository APIs](../src/stylus_jarvis/storage/repositories.py) · [Phase 2 design](phase-2-technical-design.md)

## Backlog position

| Complete | Accepted items, in backlog order |
|---|---|
| 1.1 · Baseline | 1.1.1.1 laptop inventory, 1.1.1.2 frozen fixtures, 1.1.2.1 provisioned assets, 1.1.2.2 measured Qwen selection. |
| 1.2 · Local session | 1.2.1.1 project picker, 1.2.1.2 request grants, 1.2.2.1 local store, 1.2.2.2 streamed and reopened history. |
| 1.3 · Offline release | 1.3.1.1 guarded traffic, 1.3.1.2 paired cold-boot traces, 1.3.2.1 pinned reinstall and rollback, 1.3.2.2 bounded diagnostics. |
| 2.1 · Retrieval | 2.1.1.1 source revisions, 2.1.1.2 extraction and locators, 2.1.2.1 atomic indexing, 2.1.2.2 cited context. |
| 2.2.1 · Memory | 2.2.1.1 explicit scope and confirmation, 2.2.1.2 versioned corrections and supersession. |

| Remaining | Scope |
|---|---|
| Phase 2 · M1 | **2.2.2.1** suppress deleted facts, **2.2.2.2** export scoped history and facts, **2.3.1.1–2** schedule consistent snapshots and expose recovery status, **2.3.2.1–2** reconcile deletions and rehearse restore/rollback. |
| Phases 3–5 | 3.1–3.2 Whisper input and Piper output; 4.1–4.3 saved-source explanations, trusted editor bridge and restricted coding verification; 5.1–5.3 capability broker, reviewed local actions and offline MVP qualification. M2 qualification (5.3) depends on 1.3, 2.3, 3.2, 4.1 and 5.1. |
| Phases 6–7 | 6.1–6.5 gateway/credentials, research and forecasts, Gmail/Outlook, optional cloud inference and daily-use release. 7.1–7.4 personal knowledge library, MCP, bounded multi-agent workflows and project planning. |

The workbook owns dependency order and acceptance criteria. Dated closure entries in the gap analysis supersede its initial audit statuses. [Development backlog](../outputs/stylus-development-backlog/STYLUS%20JARVIS%20Development%20Backlog.xlsx) · [Gap analysis and qualification evidence](phase-1-gap-analysis.md)

## Verification and open gates

**Latest recorded Windows regression:** 102 tests, 100 passes and two existing skips (opt-in native firewall/model check and directory-symlink permission). All six memory acceptance tests passed; the final desktop rerun passed all five tests. For a development profile with locked dependencies installed, run this from the repository root in PowerShell. The recorded full regression used a fresh interpreter per test module. [Memory tests](../tests/test_memory_capture.py) · [Windows provisioning](windows-foundation-release.md)

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_memory_capture.py -v
```

| PRD gate | Remaining acceptance |
|---|---|
| A1, A9 · Offline operation and reproducibility | Foundation passed both network-mode cold boots and the earlier package reinstall/rollback. Repeat integrated offline operation on the release candidate and tie install, conversation **and fact** restore, rollback and diagnostic privacy to its digest. |
| A2, A3 · Grounding and memory | Validate generated answers against the frozen set (at least 18/20, zero cross-project disclosures). Complete forgetting through reindex/restart and scoped export alongside the accepted capture and correction evidence. |
| A4, A5 · Voice and editor | Verify interruptible voice, keyboard fallback and audio cleanup. Verify read-only file explanation, authorized VS Code launch, unchanged source hash and denied outside-root reads/uploads. |
| A6, A7 · Performance and recovery | Measure integrated warm p95, stop feedback, voice latency and indexing load on the MSI. Prove clean-profile encrypted restore within 30 minutes and a 24-hour loss target, including later deletions and missing-ledger handling. |
| A8 · Advanced releases | Editor writes, connected-account isolation, send reconciliation, MCP and handoff tests belong to their later releases. |

## Technical debt and next change

- **Writer pressure and memory.** The single writer has an unbounded submission queue. Measure writer wait, WAL growth and UI cancellation under mixed indexing/chat load. Qwen 4B reached 7,294 MiB sampled system RAM and scored 4/10 on coding; 8B exhausted GPU memory on the tested profile. [Model decision](../outputs/qwen-msi-02/decision.md)
- **Retrieval limits.** Ranking is lexical, and whole excerpts larger than the context budget can be omitted. PDF parsing runs in-process on a worker thread without a hard memory or time quota. Keep generated-answer qualification distinct from retrieval fixture scores.
- **UI and lifecycle.** Selection can clear drafts, stale failures can update a newer view, and long transcripts accumulate in the widget. Disk exhaustion, suspend/resume and native window teardown remain operational test gaps. [Foundation review](phase-1-completion-summary.md)

**Next implementation step:** Start 2.2.2.1 with a failing Windows acceptance test. Confirm an evidence-linked project fact, forget it, retain the source, reindex, restart SQLite, and attempt automatic re-extraction. Require the fact to stay absent and an equivalent fact in a second project to remain available. The backlog deliverable is an **independent deletion ledger**. Specify its owner/destination scope, opaque identifiers, retry behavior and recovery after a partial write before implementing it. Preserve enough ledger history for later restore to replay deletions or quarantine uncertain memories. Scoped export follows in 2.2.2.2. [PRD](../STYLUS%20JARVIS%20Product%20Requirements%20Document.docx) · [Architecture review](../STYLUS%20JARVIS%20Architecture%20Review%20and%20V2%20Design.docx)
