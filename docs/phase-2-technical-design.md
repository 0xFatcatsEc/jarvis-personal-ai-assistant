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
