# Phase 5 technical design

## 5.1.1.1 · Role tool contracts

The offline registry exposes version-one proposal contracts for existing MVP capabilities. `offline_tools(role)` lists the allowed names and models. `prepare_proposal(scope, role, payload)` validates a decoded proposal and binds it to the scope already owned by the runtime. The payload carries tool arguments. Its keys cannot select the owner, project, conversation, grant or role. [Development backlog](../outputs/stylus-development-backlog/STYLUS%20JARVIS%20Development%20Backlog.xlsx)

| Role and tool | Inputs | Existing capability mapped for the next broker stage |
| --- | --- | --- |
| Coding · `coding.read_saved_code` | Source and exact revision IDs, bounded excerpt bytes | Retained saved-code context via the existing read broker |
| System · `system.open_approved_project` | None beyond the tool name | Existing explicitly requested VS Code launch for the selected project. The broker supplies the target and executable. |
| Files · `files.search_evidence` | Query up to 512 characters and optional exact revision ID | Scoped, published evidence search |
| Files · `files.inspect_citation` | Exact source, revision and locator IDs | Retained PDF or text locator |
| Memory · `memory.recall_facts` | Explicit `project` or `personal` destination | Confirmed, deletion-aware recall for the selected scope |
| Email and Research | Empty offline inventories | Inactive offline |

Contracts reject extra fields, type coercion and tools outside the selected role. A valid proposal has passed shape and role checks. The policy in 5.1.1.2 handles live authorization and dispatch. A launch still requires explicit user intent through the existing desktop flow. Memory mutations still use the existing confirmation dialogs. This task introduces no schema or UI changes.

Acceptance covers every active tool, exact scope binding, inactive offline roles and refusal of malformed or cross-role requests, injected grant and destination fields, arbitrary launch targets and executables. Existing scoped reads and approved launch retain their own tests. [Role tests](../tests/test_local_roles.py)

## 5.1.1.2 · Path and target policy

The existing saved-code explanation, Evidence search and citation inspection, Memory recall, and **Open in VS Code** actions now enter through the tool policy in the broker. It validates each request against its role and checks that the runtime still holds the original selection. Read adapters verify the live owner, project, conversation and grant before dispatch. The repository enforces the same scope while reading and revalidates at delivery. The broker checks that the selection is still current before returning data to the caller.

Saved-code and Evidence reads identify retained content through source, revision and locator IDs. They do not open the current file on disk. This preserves historical evidence after file replacement. Memory requires an explicit project or personal destination inside the current owner's scope.

The desktop's explicit VS Code action is the launch entry point. The broker obtains the root from the active grant and checks the canonical local directory. The adapter resolves stable VS Code from its approved install locations, pins the executable, and verifies its Microsoft signature and product identity. The broker pins the approved root, rechecks the live grant and runtime selection, and then issues the fixed launch. An unrelated root, junction redirect or unsupported executable is refused before launch.

Windows acceptance covers valid scoped reads, foreign IDs, malformed inputs, grant revocation, selection changes during reads, unsigned executables and a junction introduced during executable verification. This item preserves the current UI and schema 8. [Local read acceptance](../tests/test_local_roles.py) · [Windows launch acceptance](../tests/test_editor_launch.py)

## 5.1.2.1 · Execution transitions

Schema 9 adds the metadata-only `local_tool_runs` journal. The desktop wires one journal into all five registered local tool entry points. The approved tool name records intent, and each operation carries a request ID, project, conversation, grant revision, selection generation, state and timestamps. Saved-code reads use their conversation submission ID. Standalone tools use their operation ID as the request ID. Argument values, source excerpts, file paths, credentials, prompt and result text stay outside this journal and its diagnostics.

Once a typed request has been admitted, the broker records `requested`, checks authority, and commits `dispatching` before the adapter can run. It checks authority again after the journal write. Normal outcomes are `succeeded`, `denied`, `failed` or `cancelled`. Terminal bookkeeping is tied to the admitted operation and can complete after revocation. Read results must pass live grant and active selection checks again after the terminal write. Success records the adapter outcome, so a later grant change can still withhold delivery.

On reopen, a requested operation or unfinished read becomes `interrupted`. A launch with an unfinished dispatch boundary becomes `uncertain` because the process creation might have occurred. Reopen performs no dispatch or replay. The migration uses the existing pre-upgrade snapshot mechanism and leaves established records in place. The Actions view is a separate increment. [Journal acceptance](../tests/test_tool_journal.py) · [Migration acceptance](../tests/test_local_store.py)

## 5.1.2.2 · Untrusted evidence

The acceptance fixture sends an approved retained excerpt containing requests for an upload and an out-of-root read through the real scoped broker, coordinator and Ollama request parser. The Ollama HTTP fixture is local and returns a tool-shaped message alongside its text. Assertions verify that no tool definitions were exposed to the model, no extra operation was journaled, the launch adapter was never called, and no foreign file content was included. The test also checks that fixture text and prompt text do not reach the journal or diagnostics. [Boundary fixture](../tests/test_tool_journal.py)

## 5.3.1.1 · Offline study qualification

The walkthrough matrix maps the current checkout to PRD A1–A5 and tracks candidate evidence separately from subsystem and Foundation evidence. [Windows study walkthrough](windows-study-walkthrough.md)

### A3 · Capture from an Evidence citation

**Remember this** resolves the selected source, revision and locator through the existing read broker. The controller checks the active selection before opening the review. The dialog displays the retained citation, locks the destination to the current project and requires the owner to write and confirm the fact. The confirmed draft carries the resolved locator ID. The existing memory transaction revalidates the grant and verifies the locator belongs to that project. No schema migration is required.

A linked fact keeps its original locator across source replacement. The existing correction flow creates a new owner-statement version, with the attachment retained on version 1. Forgetting suppresses all fact versions through the existing deletion ledger and leaves published source evidence independently addressable. [Windows lifecycle acceptance](../tests/test_desktop.py)
