# Phase 2 technical design

## 2.1.1.1 Assign source revisions

The source registry implements the first part of PRD F3. An owner explicitly selects a file with **Approve source file…** in the active project. The desktop sends the selected path and the captured scope to the repository. This action authorizes registration of that file's fingerprint. Further versions are registered by selecting the replacement. File discovery, extraction and indexing have their own backlog items.

### Identity and retention

A source is identified by an opaque ID and a unique pair of project ID and canonical project-relative file path. This makes an atomic file replacement at the same path independent of the filesystem object ID. A move to a different path has a different identity under this contract. A revision denotes distinct byte content observed for a source. Reapproving identical bytes, including a reversion to a previously observed version, returns the existing revision ID. Concurrent approvals converge through SQLite uniqueness constraints.

Each historical revision retains its ID, source ID, SHA-256 and byte count. The path belongs to the source. Historical metadata remains addressable even after the external file disappears. The registry retains no private file copy. A later consumer that needs the bytes must verify the digest or use separately authorized evidence for that revision. It must report unavailable evidence when neither is available.

### Repository and filesystem boundaries

| Interface | Contract |
|---|---|
| `Repositories.approve_source(scope, selected)` | Check owner, project, conversation, mode and live grant. Fingerprint the explicit absolute file selection on a worker thread. Recheck the grant inside the single writer transaction before inserting source and revision. Validate again before returning the receipt. |
| `Repositories.source_revision(scope, source_id, revision_id)` | Read an exact revision through its owning project. A wrong project, mismatched pair or stale grant produces a scope error. Revalidate before returning metadata. |
| `knowledge.ingestion.fingerprint(root, selected)` | Check the local route and resolve aliases before comparing canonical path components. On Windows verify the final path of the open handle before hashing. Require a regular, single-link file. Check size, modification time and file identity around the streaming read. |

The receipt is a frozen `SourceRevision` record. The UI checks its captured selection before displaying the result. SQL remains inside storage and file hashing runs outside SQLite transactions and the Qt event loop.

### Database and migration

Migration 0003 adds `sources` and `source_revisions` with foreign keys, uniqueness on project/path and source/digest, and a trigger rejecting updates to existing revisions. The existing database actor verifies migration checksums, snapshots a populated database before the upgrade and applies the DDL and migration ledger entry transactionally. Existing project, grant and conversation data need no backfill. For rollback, restore the pre-3 snapshot to a separate clean location with the matching schema-2 binary. Records created after that snapshot belong to the newer store. [Migration](../src/stylus_jarvis/storage/migrations/0003_source_revisions.sql)

### Windows acceptance

1. Approve version one, atomically replace it with different bytes at the same path and approve version two. Require equal source IDs, distinct revision IDs and correct digests. Delete the external file, reopen SQLite and resolve each original receipt by its IDs.
2. Approve identical bytes concurrently. Require one receipt. Repeat in a second project and require independent identity and denied cross-project lookup. Reject outside-root and hard-linked files, wrong owner and incorrect mode.
3. Revoke the project grant during fingerprinting. Require a denied approval and zero inserted sources.
4. Exercise approval through Qt, reject direct mutation of a revision, and inspect the pre-3 snapshot for the schema-2 conversation.

Run the focused registry checks with `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_source_revisions.py -v`. The desktop and local-store suites cover the UI and migration checks. [Registry tests](../tests/test_source_revisions.py)

## 2.1.1.2 Extract page and text locators

**Save source excerpts…** explicitly selects a file for local excerpt retention. The desktop registers its current revision, extracts its evidence and reports the number of locators and pages needing OCR. The existing approval-only action continues to retain metadata. Excerpts may collectively contain the entire extractable text and remain in the local project database after the original file changes or disappears.

### Coordinates and citation identity

| Source | Version-one locator semantics |
|---|---|
| PDF | One locator for each physical page in file order, numbered from 1. Store the page's extracted text and the extraction format and pypdf version. Any page without extractable non-whitespace text, including an image-only page, is marked OCR needed. Blank pages can also produce this flag. |
| UTF-8 text | Decode strictly, remove an optional leading UTF-8 BOM and preserve line endings. Store contiguous half-open ranges of at most 1,024 Unicode code points. A CRLF counts as two positions. An empty document has one empty range. Binary text containing NUL and unsupported encodings are rejected. |

Use the tuple (source ID, revision ID, locator ID) under a fresh project grant for future citations. A page number or character offset by itself is ambiguous across replacements. An opaque locator ID is assigned on first publication and reused on subsequent extraction requests, including after parser upgrades. The schema records which extractor produced the excerpt. Search and future indexing can derive results from these immutable rows.

### Repository and migration contract

- `extract_locators(scope, source, revision)` returns locators in document order. It looks up the approved revision within scope. On a cache miss the worker checks the opened file and hashes the very bytes it will parse. A changed digest rejects extraction. Parsing happens outside the SQLite writer. Concurrent requests recheck existing rows inside the publication transaction and converge on the same IDs. The complete set commits together.
- `resolve_locator(scope, source, revision, locator)` resolves one retained excerpt, including its coordinates and OCR status. Both APIs revalidate the grant before delivery. Publication rechecks the grant inside the writer transaction. Wrong-project, wrong-revision and unknown locator requests receive the same scope error.
- Migration 0004 adds the revision foreign key, unique per-revision page or text start, coordinate checks and update protection. Existing revisions acquire locators only on explicit extraction. The standard migration actor snapshots a populated schema-3 database before upgrading. Rollback uses that pre-4 snapshot and matching schema-3 binary in a clean profile.
- Extraction limits are 16 MiB of input, 2,000 PDF pages and two million extracted characters per revision. These limits bound accepted records. PDF parsing runs in a local worker thread and has no OS-level memory or time quota. Encrypted PDFs require a separately supported workflow.

### Acceptance and reproduction

The Windows tests use a PDF with two text pages and an image-only page, and a UTF-8 text revision containing a BOM, CRLF and a supplementary Unicode character. They check exact coordinates, OCR status, immutable ID reuse after reopen, different IDs after replacement, denied foreign-project and wrong-revision access, rejection of changed bytes, atomic refusal after revocation and convergence under concurrent extraction. The Qt integration test exercises the explicit save action.

Run `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_evidence_locators.py -v` after syncing the locked dependencies. [Windows locator tests](../tests/test_evidence_locators.py) · [Schema migration](../src/stylus_jarvis/storage/migrations/0004_evidence_locators.sql)

## 2.1.2.1 Atomic publication in scoped FTS5

Approval identifies a file revision. Extraction records its immutable locators. Publication is a separate repository operation on that complete, retained locator set. It requires neither the original file nor an inference service.

### Database and visibility

Migration 0005 adds a stable integer posting ID for each indexed locator, a contentless FTS5 table using the Unicode tokenizer, and an active source-to-revision table with a composite foreign key. A trigger copies each locator's terms to FTS5 as its posting is inserted. Text for display continues to come from the authorized locator resolver. Empty or OCR-needed locators participate in publication but contribute no searchable terms when they contain no text.

The database actor opens one immediate write transaction. It verifies the current grant and revision ownership, checks the expected predecessor, inserts all postings, and activates the revision. SQLite WAL readers retain their last committed view until commit. A failed insertion, stale predecessor or missing extraction rolls back the entire transaction. The caller revalidates its grant before acknowledging publication. A revocation committed before admission blocks publication. A revocation committed after publication blocks subsequent reads under the stale grant.

Upgrading an existing profile creates the normal pre-5 snapshot and empty derived index tables. Schema-4 sources and excerpts remain addressable, and callers may publish them explicitly. Restore the pre-5 snapshot to a clean location with the matching schema-4 binary for rollback. [Migration](../src/stylus_jarvis/storage/migrations/0005_scoped_index.sql)

### Repository interfaces

| Operation | Behavior |
|---|---|
| `publish_revision(scope, source, revision)` | Publish an extracted revision for a new source. Repeating publication of the currently active pair succeeds without additional postings. A historical revision needs an explicit predecessor to become active again. |
| `publish_revision(scope, source, revision, replaces=(old_source, old_revision))` | Atomically retire the expected active pair and publish the target. A replacement at the same path uses the same source ID. For an owner-identified rename, approve and extract the new path, then pass the old pair. Both must belong to the selected project. Content equality alone never establishes a rename. |
| `search_evidence(scope, phrase, revision=None, limit=50)` | Return source, revision, locator and project-relative path for literal phrase matches. Default searches include active revisions only. An explicit revision can find historical published locators. The SQL joins through the authorized project before ordering and limiting. Results use stable document order, with at most 200 hits per call. Resolve a hit with the existing scoped locator API. |

The index is shared physically in the local profile. Project ownership and the current grant constrain both writes and results. The repository accepts literal phrases and escapes embedded quotes. This increment exposes repository APIs for the retrieval layer. The existing desktop approval and excerpt actions keep their original semantics.

### Windows acceptance

The tests publish a two-locator revision, reopen SQLite, resolve every matching hit, replace the revision and explicitly publish an approved rename. Historical queries continue to find retired revisions. A temporary SQLite trigger interrupts the writer before its second candidate posting. An independent WAL reader checks visibility while the transaction is open, and a retry checks that the whole new revision becomes visible. Two projects sharing a search term exercise scoped reads, historical reads and rejection of a foreign predecessor. A revoked grant blocks a prepared revision from being published.

Run `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_scoped_index.py -v`. [Windows FTS5 acceptance tests](../tests/test_scoped_index.py)

## 2.1.2.2 Assemble deduplicated cited context

**Repository API.** Call `Repositories.cited_context(scope, question, *, revision=None, max_bytes=8192, max_passages=8)` to obtain an immutable `EvidenceBundle`. A passage contains extracted text and one or more citations. Each citation carries the source, revision, locator, project-relative file name and either a one-based PDF page or half-open text range. Use the existing scoped locator resolver to inspect the original evidence. Treat excerpt text as untrusted document content. This API neither generates an answer nor executes instructions in a document.

**Search and ranking.** The repository queries published FTS5 postings, resolves them to excerpts and ranks them within one SQLite read snapshot. The live scope is authorized on entry and revalidated before delivery. Project and revision predicates apply before aggregation. The default searches active revisions. An explicit revision restricts retrieval to that published revision within the selected project. Schema 5 already holds every required field.

The query is limited to 512 characters and 32 distinct concepts. It tokenizes words, removes common English question scaffolding and expands a small fixed list of lexical equivalents, including common database engine names for a generic database query. Explicit engine names keep their specific meaning. Each concept contributes one vote per locator, regardless of repetition. A strict majority of query concepts must match. More matching concepts rank first, with ties resolved by relative path, page, offset and locator ID. No corpus-wide ranking statistics or answer-key values are consulted. This is lexical retrieval: a matching passage still needs a consumer to verify that it supports a proposed answer.

**Deduplication and limits.** Identical text is returned once with its contributing citations when they fit. Compatible overlapping text ranges from the same source revision merge only when their shared characters agree. Distinct claims remain separate candidates. The assembler tries passages in rank order and preserves whole quotes. It skips a proposal that exceeds the passage count or serialized UTF-8 budget, including citation metadata. Callers can request up to 32 passages and 65,536 bytes. A whole page larger than the budget can be omitted. The status is `insufficient_evidence` with an empty payload when no eligible passage fits. A larger budget may expose additional conflicting evidence.

**Acceptance.** Publish the two frozen handbooks in their respective projects and use the original 20 questions. Require expected facts on the first cited page for grounded cases, zero foreign citations and empty bundles for the four expected abstentions. In additional scenarios, publish identical and conflicting copies within one project, combine overlapping text observations, resolve each citation back to its locator, restrict retrieval to a retired revision, revoke a grant just before delivery, and exercise exact payload and passage limits. [Windows cited-context tests](../tests/test_cited_context.py)

To repeat on the Windows checkout, run `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_cited_context.py -v`.

## 2.2.1.1 Capture explicit scope

**User workflow.** Select a project and conversation and choose **Remember a fact…**. The fact editor displays the destination and editable statement together. The initial destination shows the selected project path. Choosing personal memory explicitly changes the destination to the signed-in owner. **Confirm and save** approves the displayed statement and destination together. Cancel, window dismissal and an abandoned proposal perform no fact write. Suggestions can enter the same editor through `Desktop.review_fact(text, Origin.INFERRED)`. They stay in memory until the owner confirms. The draft is intentionally lost after dismissal or restart.

**Admission and access.** A frozen `FactDraft` contains a random identity, the captured runtime scope, statement, destination, origin and optional evidence locator. The UI discards an approval if selection changes before dispatch. The trusted UI calls `Repositories.confirm_fact(scope, draft, confirmed=True)` only from explicit acceptance. A false confirmation returns no receipt and does no I/O. The repository requires the original scope and rechecks owner, project, conversation, offline mode and current grant inside the SQLite write transaction. It validates an optional locator against the destination project. Personal memory rejects project evidence links to avoid carrying project-scoped evidence into a broader destination. The boolean records a decision at the trusted UI boundary; model or document text cannot invoke this repository API through the chat route.

**Fact identity and provenance.** The fact UUID identifies one assertion in one destination. The first confirmation creates immutable version 1. Exact retry of the same draft returns its original receipt. Reusing its ID with a changed statement, origin, destination or provenance is rejected. Independently authored identical statements have distinct identities. Each version records its text, origin, admitting conversation and grant revision, optional evidence locator and confirmation timestamp. Project versions with evidence return a source/revision/locator triple for the existing citation resolver. A consumer can retain (fact ID, version) as a stable fact citation.

**Reads.** `get_fact(scope, fact_id, *, destination=Destination.PROJECT, version=1)` resolves one exact version. The project read requires the fact's owner and selected project. Explicit personal reads require the same owner and a valid current session, and can be made from another authorized project belonging to that owner. A missing or inaccessible fact gives a scope error. Reads and post-commit receipt delivery perform fresh authorization. A revocation after commit can withhold the receipt for an already durable version.

**Correction contract for 2.2.1.2.** A correction must receive fresh confirmation, preserve fact ID and destination, and append the next version against an explicitly expected predecessor. Competing corrections must reject a stale predecessor. Active recall will select the superseding version; exact historical citations will continue to resolve to their original version and evidence. Capture currently exposes creation and exact reads. Correction and active recall are the following subtask.

**Schema and migration.** Migration 0006 adds the owner and optional destination project in `facts`, plus immutable `fact_versions` keyed by fact and version. A null destination project represents explicitly personal memory. Identity and version commit together or roll back together. Existing chats, revisions and excerpts produce zero facts during migration. The database actor snapshots populated schema 5 before applying schema 6. For rollback, restore the pre-6 snapshot into a clean location with the matching schema-5 binary. Newer facts remain in the schema-6 store.

**Windows acceptance.** Verify cancel, explicit personal selection and confirmation through Qt. Verify in-memory inferred proposals write zero rows, successful confirmation, idempotent replay, conflict rejection, grant revocation before admission, project/owner isolation, separate personal reads and evidence resolution after reopening SQLite. Inspect the pre-6 snapshot for the previous schema and its conversation. [Repository acceptance](../tests/test_memory_capture.py) · [Desktop acceptance](../tests/test_desktop.py) · [Migration](../src/stylus_jarvis/storage/migrations/0006_confirmed_facts.sql)

## 2.2.1.2 Resolve supersession

**Correction workflow.** Choose **Correct a fact…**, explicitly select project or personal memory, and select a current statement. The picker shows each fact's identity and current version. The editor starts with the reviewed text, locks the destination and requires **Confirm correction**. Dismissal discards the proposal. A stale-version conflict asks the owner to reopen the latest statement. The desktop treats manually entered corrections as owner statements and shows when the preceding version had evidence. It does not silently reuse that evidence for a changed claim.

**Repository APIs.** `correct_fact(scope, draft, expected_version=n, confirmed=True)` uses the draft's existing fact UUID, destination, statement, origin and optional replacement locator. False confirmation performs no write. Within one immediate SQLite write transaction, it checks the draft scope, current grant, evidence ownership, destination and maximum committed version. Only a match with the reviewed predecessor allows inserting version n+1. The unchanged fact identity keeps the chain in its original owner/project partition. Two writers competing from n can produce only one successor. Retrying a committed correction with the same predecessor reports a conflict; callers can inspect active recall before proposing another correction.

`recall_facts(scope, destination=Destination.PROJECT)` returns exactly the highest committed version of each fact in the authorized destination, ordered by fact ID. An empty destination returns an empty list. Owner-wide personal recall requires explicit selection and a valid current session. Both recall and correction receipts revalidate authorization before delivery. `get_fact(scope, id, version=n, destination=...)` continues to resolve the exact historical version; its existing default remains version 1. Either receipt exposes the source/revision/locator triple for that version's optional evidence. Resolvers can still open the retained original excerpt after external file replacement or removal.

**Schema and migration.** Keep schema 6. Its composite primary key supports a per-fact version chain, and the existing trigger rejects in-place version updates. The predecessor of version n+1 is version n. The transactional comparison enforces a contiguous sequence for repository writes. There is no mutable active pointer to migrate or repair. An existing single-version fact is immediately eligible for active recall. Supersession involves no backfill and leaves the published FTS5 index independent of fact versions.

**Windows acceptance.** Replace an evidence file, confirm a correction with the new locator, delete the file and reopen SQLite. Require the same fact ID, distinct immutable versions, newest-only recall, and correct historical excerpts. Race corrections from two independent database connections, require one winner and one conflict, revoke the grant and verify the version count. Check project, personal and other-owner boundaries, explicit nonconfirmation, and the desktop version picker and confirmation action. [Repository tests](../tests/test_memory_capture.py) · [Qt test](../tests/test_desktop.py)

## 2.2.2.1 Suppress deleted facts

**Confirmation and scope.** Choose **Forget a fact…**, select project or personal memory, and review the current statement and destination before choosing **Confirm forget**. The statement is read-only and confirmation covers every version under that fact ID. The repository API is `forget_fact(scope, fact_id, expected_version=n, confirmed=True, destination=...)`. Cancellation performs no write. Owner, destination, live project grant and expected version are checked before the deletion is recorded. Retrying the same confirmed ID and version completes cleanup without creating another deletion entry.

**Independent ledger.** Schema 7 adds only a binding to the primary SQLite store. The ledger lives in a separate local SQLite file named by adding `.deletions.sqlite3` to the primary database filename. It has an independent commit and must travel separately from conversation snapshots. An immutable deletion entry stores its sequence, opaque fact ID, keyed destination tag, confirmed version, and suppression fingerprints. HMAC-SHA256 fingerprints use a profile ledger key and include owner and destination. The ledger contains no raw statements or file paths. Preserve the key with the ledger and restrict access to both. The primary binding identifies the ledger and records the last applied sequence. Missing, corrupt, mismatched or detectably older ledgers block schema-7 startup. A matched pair rolled back together cannot prove newer deletions never happened. Phase 2 restore must verify coverage against an independently retained ledger before activation.

**Ordering and restart.** The database actor uses a primary immediate transaction to serialize grant checks and memory writes. Forget commits the ledger first, then removes all fact versions and the fact identity and advances the primary sequence. If cleanup fails, the ledger still hides the fact and rejects recreation under its old ID. Startup replays later entries and finishes cleanup before opening the store. Existing schema-6 memory migrates without synthetic deletions. The ordinary pre-7 snapshot remains a schema-6 artifact and must be handled as staged data if later deletions exist.

**Re-extraction.** Inferred saves check all forgotten statement versions using normalized case and whitespace. For evidence-linked facts they also check source identity and content digest. A matching source blocks inferred saves in that destination, including paraphrases from a replacement revision. This is deliberately conservative and can block unrelated inferred statements from the same source. The owner can author a new fact explicitly under a new ID. For a paraphrase with neither stable provenance nor a matching statement fingerprint, the ledger supplies no semantic identity match. There is currently no automatic extractor. Future extractors must supply provenance and use the guarded save path. Approved files, locators, historical document citations, and FTS5 publication remain available. Forget removes fact records from active storage. Older snapshots and retained documents may still contain the statement.

**Acceptance.** On Windows, confirm an evidence-linked fact, forget it, replace and republish its source, restart, and attempt inferred recreation under fresh IDs. Verify recall and historical fact lookup hide the forgotten identity while another project and the original document citation remain available. Also exercise project and personal isolation, cancellation, stale review, grant revocation, repeat confirmation, failure between commits, matching-ledger replay, missing ledger, and stale ledger. [Memory acceptance tests](../tests/test_memory_capture.py) · [Desktop tests](../tests/test_desktop.py) · [Migration](../src/stylus_jarvis/storage/migrations/0007_deletion_ledger.sql)

## 2.2.2.2 Export scoped history and facts

Choose **Export project…** in the desktop, review the selected project in the destination dialog, and select a new local JSON filename. The result is a human-readable, unencrypted UTF-8 file. Treat it as project data. Cancellation leaves no output. The destination must be on a local Windows volume outside OneDrive and the filename must be unused. Existing files and links are refused. This export is an interchange artifact. Disaster-recovery snapshots and encryption belong to 2.3.

`Repositories.export_project(scope, target)` validates the selected conversation's live grant and exports all saved conversations in its project. It includes settled messages in sequence, with turn state, and the current confirmed version of each project fact. Personal facts, other projects, active turns, superseded versions and facts suppressed by the deletion ledger are excluded. The same ledger-aware query serves recall and export. Forgetting a fact leaves independently retained chat and document evidence under their existing rules. An already exported copy remains a standalone file.

The manifest has `format: stylus-jarvis-project` and `version: 1`, an opaque project ID, conversations with ordered messages, and facts with ID, version, origin, text and optional evidence. Evidence identifies original source, revision and locator, with relative path, SHA-256 and page or text range. References remain precise when the file is replaced or removed. There are no copied source excerpts or ledger secrets in the manifest. No migration is required.

Publication runs as one serialized database operation, so a grant update or forget cannot interleave with its authorized snapshot and file publication. The worker writes and flushes a sibling temporary file, then publishes without overwriting an existing path. A failed write removes the temporary file during ordinary exception handling. The operation materializes the project snapshot and holds the writer for the duration of publication, which should be measured on larger projects.

Acceptance uses two projects and multiple conversations. It verifies readable JSON, current fact versions, retained evidence coordinates, isolation, suppression even after a failed primary cleanup, revocation, failed-write cleanup, and no overwrite. The desktop test exercises the destination dialog and reads the exported artifact. [Repository acceptance](../tests/test_memory_export.py) · [Desktop acceptance](../tests/test_desktop.py)

## 2.3.1.1 Schedule consistent snapshots

Configure the checkout once from the repository root with the same Windows account and interpreter used to run the desktop. Both selected directories must exist on reachable local volumes outside OneDrive. The key file must be outside the application profile and backup destination. Keep an independent recovery copy of that key. This command creates a 32-byte random key when the file is absent and reuses a valid existing key.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.\.venv\Scripts\python.exe -m stylus_jarvis.storage.snapshots --destination 'E:\JarvisBackups' --key 'F:\JarvisKeys\recovery.key'
```

The command writes the profile's `config/snapshots.json`. A running desktop checks at startup and approximately once a minute, taking the first configured snapshot immediately and then one when 24 hours have elapsed since the last verified success. The local receipt survives process restart. A failed attempt preserves the previous receipt and retries on the next check. The scheduler runs only while the desktop is open and the chosen volumes and key are available. No OS wake or background service is configured. Diagnostics record only a safe failure code. The status panel belongs to 2.3.1.2.

A dedicated worker opens read-only SQLite connections and uses SQLite's online backup API in 32-page steps. The live WAL writer remains independent. It verifies both in-memory databases with SQLite checks. It captures the primary first, then its paired deletion ledger, requiring the ledger identity to match and its sequence to cover the primary binding. The ledger is a separate encrypted artifact and can be retained independently. This pair proves coverage through the captured primary watermark. Checking for deletions newer than the pair belongs to staged restore.

Each published UUID directory contains `primary.aesgcm` and `ledger.aesgcm`. Both use AES-256-GCM with random 96-bit nonces and authenticated format version, set ID and artifact purpose. Envelope layout is the bytes `STYLUS-JARVIS-SNAPSHOT`, one format byte (1), 16 UUID bytes, the ASCII purpose, the nonce, then ciphertext with authentication tag. The worker reads and authenticates the files before publishing the directory by rename. No plaintext database is staged on the backup volume. Schema remains 7. Project originals, local migration snapshots, pending-write recovery files, assets and configuration are outside this scheduled artifact.

Each SQLite input has a 64 MiB limit, and the online backup phase has a per-input 60-second deadline. Encryption and verification use in-memory buffers. Monitor growth on the MSI before raising the bound. The scheduler does not remove prior backup sets. Encrypted restoration to a staged profile, post-snapshot deletion coverage, and the PRD's timed recovery targets still require qualification.

Windows acceptance verifies committed content while another connection has an active write transaction, restored SQLite integrity, key separation, authentication failure with a wrong key or modified ciphertext, receipt persistence, daily timing, failed-publication cleanup and prompt scheduler shutdown. [Snapshot tests](../tests/test_snapshots.py)

## 2.3.1.2 Expose recovery status

Open **Recovery status** in the desktop status bar. While open, the panel refreshes approximately every five seconds. It shows the configured destination, elapsed time since the most recent verified backup, and any current backup problem. A receipt from a previous configuration is identified separately. A missing destination, missing recovery key, or missing artifact does not erase the last-success time. File presence is checked on refresh; ciphertext is authenticated during backup verification and again during the future restore workflow. Failure details in the panel are safe summaries. Diagnostics continue to receive failure codes only.

New backup receipts record source dependencies from the exact SQLite image captured for the primary snapshot. For the selected authorized project the panel lists project-relative original source paths and whether each currently resolves to a readable location within its project root. Availability here means a locally resolvable regular file. It does not establish that its bytes match the captured revision. Project originals are outside the encrypted snapshot. Sources registered after that snapshot appear after the next successful backup. Older receipts keep their last-success time and gain an inventory on the next successful backup. The local receipt includes source path metadata and stays under the user profile. It contains no source text or key bytes.

The UI checks the active grant before and after the local status read and drops results if selection changes. The panel shows the count and checks at most 100 source paths per refresh. Backup-level information remains visible without a project selection. No migration or backup envelope change was required.

Windows acceptance checks elapsed age after schedule recreation, a destination removed after success, a missing backup artifact, availability of captured sources, exclusion of another project's source and one registered after the snapshot, and opening the Qt panel. [Snapshot tests](../tests/test_snapshots.py) · [Desktop tests](../tests/test_desktop.py)

## 2.3.2.1 Reconcile deleted records

Stage a schema-7 backup into an unused local directory outside the active profile and the backup directories. Start with the intended primary snapshot, its bundled ledger, the separately held recovery key, a separately retained current ledger artifact, and a trusted deletion checkpoint. The checkpoint is the latest deletion sequence known independently from a surviving authoritative ledger or recovery record. The bundled sequence alone cannot show whether a later deletion occurred.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.\.venv\Scripts\python.exe -m stylus_jarvis.storage.staged_restore --snapshot $olderSet --key $recoveryKey --latest-ledger-set $latestLedgerSet --expected-sequence $knownDeletionSequence --target $newStagingPath
```

The staging command authenticates the backup envelopes, checks SQLite integrity and matches the primary migration ledger to the running code. It checks the archived and latest ledgers against the primary binding, compares their identity and key, verifies contiguous sequences and requires the latest ledger's deletion and fingerprint history to include the archived prefix. The latest sequence must also reach the independently supplied checkpoint. The command applies later deletions transactionally through the existing reconciliation code before publishing paired databases. Inferred memory suppression remains active in the staged copy.

The report at `restore-report.json` records the outcome, snapshot ID, primary watermark, required sequence, and, when verified, the replayed ledger sequence and removed-fact count. `ready_for_review` publishes the database and ledger together under `data/`. `quarantined` publishes only the report and returns exit status 2; the original encrypted inputs remain available for inspection. Missing, stale, incompatible, unreadable or tampered ledger coverage cannot yield a reviewable database. Invalid primary authentication or schema yields an error and no published stage. Neither outcome activates a profile. Use a private local staging directory because successful staging and temporary verification material are plaintext. A hard process interruption can leave staging scratch files.

The Windows scenarios exercise a real later deletion across encrypted sets, reopening the staged database and checking inference suppression, report-only quarantine, invalid primary rejection and live-profile protection. The timed rehearsal, independent coverage after the last externally retained checkpoint, source-file reporting during restore and matching-binary rollback still need their designated acceptance runs. [Windows staged-restore tests](../tests/test_staged_restore.py)

## 2.3.2.2 Rehearse migration and rollback

From the repository root on the MSI, with locked dependencies installed and the pinned build backend cached, run the qualification script. Use a fresh report filename.

```powershell
.\.venv\Scripts\python.exe -B packaging/windows/qualify_recovery.py --output .\recovery-rehearsal.json
```

The script builds rehearsal wheels offline from the schema-6 commit and current checkout, using the same Python interpreter that runs them. Separate isolated workers load the matching wheel. The schema-6 worker seeds a versioned sample with a conversation, two facts and source evidence. The schema-7 worker upgrades the sample, takes an encrypted backup and records a later deletion in an independently retained ledger set. It stages the older primary into an unused profile, verifies the remaining conversation and fact, resolves the original citation, and checks that the forgotten fact cannot return. A missing original is reported in recovery status, and missing ledger coverage produces report-only quarantine. The earlier wheel separately opens the exact pre-upgrade SQLite snapshot in its own temporary profile. That historical rollback fixture is never activated as a live profile.

The committed evidence records the target model, interpreter and SQLite version, wheel digests, pre-upgrade database digest and timings. Restore timing begins with the encrypted inputs and separate key available and ends after checking reopened content. The 24-hour recovery point is a simulated fixture clock anchored to the backup receipt. [MSI rehearsal evidence](evidence/2.3.2.2/msi-rehearsal.json)
