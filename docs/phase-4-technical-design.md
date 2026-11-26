# Phase 4 technical design

## Backlog dependencies

| Item | Depends on | Work and release boundary |
| --- | --- | --- |
| 4.1.1.1 Select code context | 2.1 and 5.1 | M2. Explain an explicitly selected saved revision. Identify its file and revision and verify the file hash is unchanged. |
| 4.1.1.2 Open approved project | 4.1.1.1 | M2. Resolve and authorize the VS Code executable and canonical approved project root before passing the exact launch arguments to the Windows adapter. Reject unrelated roots. |
| 4.2.1.1 Establish per-user IPC | 4.1 | M3. Add a per-user named pipe, ACL, session credential and stale-session rejection. |
| 4.2.1.2 Identify workspace and buffer | 4.2.1.1 | M3. Associate workspace, document URI, selection, diagnostics, version and dirty state with the correct authenticated VS Code window. |
| 4.2.2.1 Preview versioned patches | 4.2.1 | M3. Bind approval to the reviewed patch and revalidate workspace trust, target versions and exact approval before apply. |
| 4.2.2.2 Recover edit conflicts | 4.2.2.1 | M3. Preserve dirty buffers and undo. Reject stale approvals and reconcile partial outcomes after disconnect. |
| 4.3.1.1 Constrain disposable worker | 4.2 and 5.2 | Later. Qualify isolated execution with bounded filesystem, egress, credentials and resources. |
| 4.3.1.2 Report actual checks | 4.3.1.1 | Later. Record named profiles and observed outcomes. Provide a user-run path when isolation is unavailable. |

The desktop, coordinator, local router, scoped source registry, locators, recovery and history are present in the checkout. The v1 editor bridge supports pairing, read-only context, reviewed text edits and conflict reconciliation. The general broker remains planned. [Approved repository boundaries](repository-structure.md) · [Development backlog](../outputs/stylus-development-backlog/STYLUS%20JARVIS%20Development%20Backlog.xlsx)

## Architecture for the remaining Phase 4 work

### Shared ownership and M2 launch

PySide6 exposes explicit commands. The runtime owns the active selection, cancellation and user-visible status. Repositories resolve project IDs and grant revisions. The security broker authorizes each typed action, and a platform adapter performs the authorized effect. Code excerpts, editor payloads and model output enter as data. The existing offline Python audit hook remains the process boundary for the desktop.

For 4.1.1.2, the project picker supplies its existing scope. The broker obtains the root from SQLite with owner, conversation and grant checks. An optional target at the broker boundary must resolve to the same canonical root. The desktop exposes a single **Open in VS Code** action with no path field. The Windows adapter discovers stable VS Code at standard installer locations, checks canonical file location and Microsoft signature and product identity, and dispatches fixed arguments containing the approved root. Recheck selection, root and grant immediately before dispatch. Record a launch request, not a confirmed workspace connection. This explicit desktop capability uses the required app and path checks. Generic tool registration, model-directed dispatch and the broader 5.1 journal remain at their own gate.

The M2 launcher supports Microsoft's standard per-user and machine-wide stable installations. Cache-only Authenticode verification uses the machine's local Windows trust information. It fails closed when trust cannot be established. The adapter holds the checked paths through process creation. Dispatch requests a new window with extensions, telemetry and updates disabled, and passes a limited environment. VS Code remains a separate application with its own profile and network policy. M3 needs a separately authenticated path to the extension. [Windows trust policy](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/ns-wintrust-wintrust_data) · [VS Code command line](https://code.visualstudio.com/docs/configure/command-line) · [VS Code launch flags](https://github.com/microsoft/vscode/blob/main/src/vs/platform/environment/node/argv.ts)

### 4.2.1.1 and 4.2.1.2 — Bridge and editor state

| Area | Design |
| --- | --- |
| Extension | Add the planned TypeScript VS Code extension in its own package at M3. Run in the local desktop extension host, check Workspace Trust, and use the VS Code API to observe documents and apply approved edits. Test the minimum supported editor version and keep activation explicit. Allow typed context reads and approved edit requests through fixed handlers. |
| Connection | Let the desktop own a local-only Windows named pipe with an ACL for the current user SID. Reject remote clients. Pair the intended extension window using an expiring, one-time credential, then issue an in-memory session identity. Revoke on logout, shutdown, re-pairing, or disconnection. The pipe name alone grants no authority. Credentials stay out of logs and the conversation database. |
| Protocol | Use length-prefixed, bounded UTF-8 JSON and the shared editor v1 schema. Negotiate protocol version and capabilities. Carry session ID, request ID, operation, deadline, scope and grant revision in the envelope. Validate schema before dispatch. Return typed outcomes and correlate duplicates by request ID. Reject oversized frames, malformed payloads, unknown operations, replay and stale sessions. |
| Workspace identity | Bind the JARVIS project ID and approved canonical root to the authenticated extension session, window, and selected workspace folder. Resolve local file URIs and validate the mapped folder against the approved root. Rebind when a window changes folders. Initially support one approved folder per action. Unrelated folders, remote authorities and paths that escape through junctions fail closed. |
| Buffer identity | Capture the document URI, a per-open document identity, VS Code document version, dirty state, content digest, bounded selection and diagnostics. Versions are meaningful within the same document instance and session. Reopen and reconnect invalidate the old identity. Use VS Code's UTF-16 position convention and capture encoding and newline behavior when computing edit ranges. |

### 4.2.2.1 and 4.2.2.2 — Exact edits and recovery

1. Build a typed patch proposal against a captured workspace and buffer snapshot. Bind its ordered target list, base versions and digests, exact edits and proposal digest to a review ID.
2. Show the exact diff and receive explicit approval. Bind approval to the proposal digest, workspace, grant, session and expiry. An edited proposal needs fresh approval.
3. Revalidate the current grant, editor trust, canonical target identities and all base versions immediately before applying. The extension performs the final preflight and owns open-buffer changes through VS Code. Preserve the existing undo path. Keep save as a separately authorized operation.
4. Record dispatch before applying and record per-target receipts afterward. On stale versions, keep the dirty buffer and offer a refreshed preview. On disconnect after dispatch, mark the outcome uncertain. Reconnect and reconcile from the receipt and observed versions or digests before allowing a new proposal. Never blindly replay an uncertain edit. Report which files or buffers changed and which remain unresolved.

### Future schema and qualification

4.1.1.2 uses schema 7. Migration 8 adds the editor operation journal. Any future durable citation receipts will use a separate migration. Keep the versioned IPC contract separate from SQLite migrations.

| Gate | Acceptance evidence |
| --- | --- |
| 4.1.1.1–2, M2 | Select a saved revision and preserve its source hash. Verify exact resolved VS Code arguments with paths containing spaces. Reject an unrelated, revoked, or redirected root and an unapproved executable. Verify a real Windows launch of an approved fixture folder and regress the existing offline subprocess restrictions. |
| 4.2.1.1, M3 | Test DACL and local-only access, wrong user and credential, expiry and reconnect, version negotiation, replay, and frame size and deadline bounds. Run contract fixtures in Python and the extension host. |
| 4.2.1.2, M3 | Use two VS Code windows with similarly named folders. Test trusted and untrusted workspaces, remote URI denial, junctions, dirty buffers, and document reopen/version reset. |
| 4.2.2.1–2, M3 | Approve an exact patch and test stale target versions, revoked grants, changed approval digest, undo, and disconnect before, during and after dispatch. Reconcile partial results without duplicate writes. Include Unicode and CRLF fixtures. |
| 4.3, later | Begin after 4.2 and 5.2. Qualify a disposable verification worker with filesystem, egress, credential and resource limits. Report actual checks and offer user-run verification when isolation is unavailable. |

## 4.1.1.1 implementation plan

1. **List eligible revisions.** Add a repository read for approved revisions with retained nonempty text locators in the selected project. Show each relative path and full revision ID. Keep file approval and excerpt indexing in the existing explicit workflows. A metadata-only approval needs **Save source excerpts** before it is eligible.
2. **Attach with the current scope.** Add a keyboard-accessible picker and removable label beside the existing composer. Hold source and revision IDs on the desktop. Clear the attachment and dismiss the picker on scope change or shutdown. Sending through the existing composer supplies that immutable selection to the coordinator. The selected code supplements a typed or reviewed voice question.
3. **Authorize the exact revision.** Route listing, identity resolution and evidence reads through the narrow saved-code broker. The repository revalidates owner, project, conversation and grant. Read from retained locators by both source and revision IDs. This supports historical evidence after replacement and adds no live-file read, process launch or model-directed tool dispatch. The remaining role registry, general path and executable policy, and operation journal stay in 5.1.
4. **Build the local request.** Fit bounded excerpts and locator identities into the local router's UTF-8 budget. Read eligible text locators in source order. Explain using that revision's supplied evidence and abstain when none fits. Keep prior conversation messages out of this specific model call so other revisions cannot supply evidence. Continue using the existing coordinator for cancellation, grants, streaming and persistence.
5. **Preserve the revision identity.** Append the approved relative path and revision ID to the saved user message, outside the raw editor draft. The same annotated text binds a replay to the same revision using existing turn lookup. Schema 7 and its existing recovery path suffice. The model request includes locator metadata. Clickable, durable per-reply citation receipts require a separate structured schema and recovery design.
6. **Verify on Windows.** Register two revisions at the same path, select the older one by keyboard and inspect the model input. Confirm the replacement content stays outside the evidence, history identifies the older revision, and the current file's SHA-256 remains unchanged. Exercise foreign and revoked scope along with existing desktop, retrieval and history regressions.

### Repository interfaces

| Interface | Purpose |
| --- | --- |
| `saved_code_revisions(scope)` | List eligible source and revision metadata for the picker. |
| `source_revision(scope, source, revision)` | Resolve authoritative file identity for the selected pair. |
| `saved_code_context(scope, source, revision, max_bytes)` | Read bounded retained excerpts with locator identities for exactly that pair. |

Code excerpts are untrusted evidence. The saved-code model call has only the existing local generation route. Full 5.1 remains an M2 dependency before exposing file or launch tools or closing integrated A5.

## 4.2.1.1 implementation plan

1. Add a Windows transport under `editor/` with a random local pipe name, first-instance ownership, a protected current-user DACL, remote-client rejection, effective peer SID validation and bounded overlapped I/O. Limit the bridge to one client at a time.
2. Define the editor v1 pairing and ping contract. Use a four-byte length prefix and strict UTF-8 JSON with size, shape, deadline, version and sequence checks. Unknown operations fail closed. Project operations and their scope envelopes belong to later subtasks.
3. Keep the invitation and connection-bound session in memory. Issue invitations only on an explicit desktop action. Expire invitations and sessions and invalidate credentials on replacement, disconnect and desktop shutdown. Surface pairing status without recording credentials in logs or SQLite.
4. Add a local extension client with explicit pair and disconnect commands. Keep the client limited to handshake and heartbeat. The M2 launcher remains a separate path. Workspace and document identification begin at 4.2.1.2.
5. Test the real Windows pipe, SID and ACL, the Python and extension wire contract, credential reuse, wrong user, reconnect, expiry, malformed frames and bounded shutdown. SQLite stays at schema 7.

### Pairing lifecycle

Use **Editor → Pair VS Code…** in the desktop. In a trusted local VS Code window with the extension loaded, run **STYLUS JARVIS: Pair** and paste the invitation. The invitation is valid for 90 seconds and consumed on successful pairing. A session is tied to one pipe connection, expires after 15 minutes, and closes after 30 seconds without a valid request. The extension pings every 10 seconds. **Disconnect** in either application revokes the session. A fresh desktop invitation replaces the previous endpoint and credential.

The server rejects remote clients at pipe creation and checks the effective client SID after each message. The v1 contract uses a 4-byte little-endian length, a 4 KiB maximum payload, and a five-second request window. Invalid requests close the connection. A rejected pre-pairing connection can be retried until the invitation expires. Clients using the original handshake retain ping-only behavior. Schema 7 remains sufficient. [Editor wire contract](../contracts/editor_v1.schema.json) · [Windows pipe flags](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea) · [Windows peer impersonation](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-impersonatenamedpipeclient)

For development, run these commands from the repository root. The last command opens the local extension development host. The existing **Open in VS Code** action remains the saved-project launcher.

```powershell
npm.cmd --prefix extensions/vscode ci --ignore-scripts
npm.cmd --prefix extensions/vscode run build
code --extensionDevelopmentPath="$(Resolve-Path extensions/vscode)"
```

Run `test_editor_ipc.py` on Windows after building the extension. The suite checks native ACL denial, effective SID mismatch, strict framing, expiry, re-pairing, replay, and a pairing round trip with the compiled client. [Windows acceptance tests](../tests/test_editor_ipc.py)

## 4.2.1.2 implementation plan

1. Extend the editor v1 handshake with an optional extension activation ID and a negotiated snapshot capability. Bind invitations from the desktop to its current project, conversation, generation and grant. Keep one active window per desktop. Pairing another window invalidates the previous connection.
2. Add a bounded snapshot operation for the active file. Capture its workspace-folder URI, document URI, per-open UUID, version, dirty state, SHA-256 digest, UTF-16 selection and bounded diagnostics. The extension sends this metadata only on an explicit command from a trusted local window.
3. Resolve and validate both file URIs under the grant-bound approved root. Reject remote authorities and out-of-scope targets, including junction escapes. Recheck the grant and selection before publishing the snapshot. In memory, track document versions and retire old document IDs when the same file reopens.
4. Add a read-only desktop view of the last shared snapshot. Clear it on selection change, re-pairing and disconnect. No database migration or patch operation is needed.
5. Exercise two VS Code windows with similarly named paths, local URI handling, diagnostic and selection fidelity, dirty-state changes, reopened documents, stale versions, stale windows, and revoked grants on Windows.

### Sharing editor context

Select the project and conversation in JARVIS, then pair the local VS Code window through the **Editor** menu. Run **STYLUS JARVIS: Share Editor Context** with a saved file active. The desktop shows **Editor → View VS Code context…** once a snapshot is accepted. It displays the last explicit share. The extension hashes the active buffer as UTF-8 and sends the digest, metadata and up to four diagnostics. Buffer text and selected text stay in VS Code. Selection endpoints are zero-based UTF-16 coordinates and preserve direction.

The negotiated capability binds each snapshot to the session, window activation ID, project, conversation, generation and grant. The server compares the resolved workspace folder with the approved canonical root, checks an existing local file by its opened path, and revalidates the grant before publishing. A scope change clears the desktop view, and a revoked or stale scope closes the pipe on its next request. Buffer history tracks at most 256 document identities per session. A reopened document gets a new ID and may report a lower version. Once replaced, its old ID is rejected for the rest of that session. Pair again when moving to another workspace or window.

## 4.2.2.1 implementation plan

1. Add a negotiated patch capability to the existing scoped connection. The extension constructs a typed proposal for one to three open local buffers from an explicit clipboard proposal. It captures workspace and document identities, versions and UTF-8 digests, normalizes replacement text to each buffer's line ending convention, and hashes the exact serialized proposal. The existing 4 KiB wire limit applies.
2. Validate the proposal and all canonical targets in the bridge, including distinct files and the active grant. Keep one expiring proposal in connection-local memory. VS Code uses read-only before and after documents to show a diff for every target and requires a separate modal approval before dispatch.
3. Require the proposal digest and fresh target identities in the authorization request. Recheck the session, workspace, grant, canonical targets, and the buffered proposal. Return a one-use authorization for the exact digest. In the extension, recheck workspace trust and each open instance, version and digest immediately before one text-only VS Code workspace edit. Keep file saving separate. [VS Code workspace edit API](https://code.visualstudio.com/api/references/vscode-api)
4. Exercise exact approval, mutated digests, stale buffers, out-of-scope paths and revoked grants in the Windows pipe suite. Verify the diff and text-only apply in an isolated installed VS Code extension host with dirty and CRLF fixtures. Operation journal and uncertain-outcome reconciliation belong to 4.2.2.2. Schema 7 is sufficient here.

### Review and apply a patch

Pair a trusted VS Code window with the selected JARVIS project. Open the targets in VS Code, then copy a JSON array with their file URIs or absolute Windows paths and complete replacement text. A target may have unsaved changes. The preview starts from the exact current buffer, including those changes.

```json
[
  {"uri": "C:\\Projects\\Demo\\example.py", "replacement": "print(\"Hello\")\n"}
]
```

Run **STYLUS JARVIS: Review Patch from Clipboard**. Use **STYLUS JARVIS: Open Patch Diff** to inspect any remaining target, then choose **STYLUS JARVIS: Approve and Apply Patch**. The confirmation names the workspace and targets and shows the proposal digest. The bridge retains a review for up to two minutes. Approved authorization is single-use and expires within two seconds. Re-pairing or disconnect discards the review.

The extension applies one text-only workspace edit to existing open buffers. VS Code owns the edit and its undo behavior. File saving follows the user's VS Code settings and actions. The bridge accepts one to three complete replacements within the 4 KiB frame limit. The release supports supplied patches through the clipboard workflow. [Editor wire contract](../contracts/editor_v1.schema.json)

## 4.2.2.2 implementation plan

1. Add an additive SQLite migration for patch operations and per-target receipts. Persist the project, conversation, grant, original window, exact proposal digest, target paths, base identities and expected content hashes. Commit the unresolved dispatch record before issuing approval. Keep patch text, credentials and session tokens out of the journal.
2. Make reservation transactional. Reject an already recorded digest and hold further approvals for any project with an unresolved operation. Continue to check the live grant, exact review, trusted local workspace, and every target's identity, version and digest before applying.
3. After the VS Code-owned edit, submit observations of each open buffer. On reconnect, fetch the unresolved operation and explicitly inspect the targets again. Resolve the exact approved paths with a current grant. Classify each target as expected content observed, original instance and version unchanged, or unresolved. Keep any previously confirmed outcomes.
4. Give VS Code commands to view or reconcile the last recorded outcome and to acknowledge an unresolved operation after manual inspection. Acknowledgment retains unresolved receipts and permits a fresh proposal. Recovery and acknowledgment carry no replacement payload and perform no editor write.
5. Verify Windows migration and reopen, partial results across reconnect, stale authorization, duplicate denial, lost result receipts, workspace and grant denial, and application and undo in an isolated VS Code host.

### Operator workflow and receipt semantics

After a lost connection, pair again with the same approved project in a trusted local VS Code window. Open any target buffers you want to inspect, then run **STYLUS JARVIS: View and Reconcile Patch Outcome**. For a multi-root window, first select a file in the approved folder. The extension submits identities and hashes for matching open buffers. Missing, closed, and ambiguous targets stay unresolved. Changes in the live buffers remain under VS Code's control.

| Outcome | Evidence |
| --- | --- |
| Applied | The observed buffer matches the approved replacement hash. This records the content seen at inspection time. |
| Unchanged | The originating session reported after its edit attempt settled and observed the exact original document instance, version and hash. |
| Unresolved | Available evidence cannot establish either outcome. This includes a reopened buffer that matches only the original hash. |

An unresolved operation blocks further patch approval for that project. After inspecting the buffers, **STYLUS JARVIS: Acknowledge Unresolved Patch Outcome** asks for explicit confirmation before releasing the hold. Previous observations and unresolved entries remain in the journal. An exact recorded proposal digest cannot be authorized again. A later edit requires its own preview and approval. Recovery and acknowledgment perform no edits or saves.

The journal commits before the short apply permit leaves JARVIS. After reconnect, inspection and acknowledgment wait for that permit to expire. The current grant, local workspace and canonical paths are checked again for recovery. Schema 8 adds operation and target tables without modifying existing conversation or memory records. Live credentials and replacement text stay out of SQLite. A rollback to a pre-8 snapshot omits editor receipts written later, so inspect any uncertain buffers before re-enabling edits after such a rollback. Pair the matching extension and desktop builds for recovery support. [Editor wire contract](../contracts/editor_v1.schema.json)
