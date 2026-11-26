"""Local tool policy and authorized adapter calls."""
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, TypeVar
from uuid import UUID

from ..contracts.messages import Code, Failure, SavedCode, Scope
from ..contracts.tools import (InspectCitation, LocalTool, OpenApprovedProject, ReadSavedCode, RecallFacts,
                               SearchEvidence, ToolOutcome)
from ..editor.launch import VSCodeLauncher, canonical_directory, pin_path
from ..knowledge.context import EvidenceBundle
from ..knowledge.ingestion import SourceRevision
from ..knowledge.locators import Locator
from ..memory.service import Destination, Fact
from ..runtime.roles import Role, prepare_proposal

_Tool = TypeVar("_Tool", bound=LocalTool)
_Result = TypeVar("_Result")
DispatchMarker = Callable[[], Awaitable[None]]


class OperationJournal(Protocol):
    async def begin(self, scope: Scope, tool: LocalTool, request: UUID | None = None) -> UUID: ...
    async def mark_dispatch(self, operation: UUID) -> None: ...
    async def finish(self, operation: UUID, outcome: ToolOutcome, code: Code | None = None) -> None: ...


async def _record(journal: OperationJournal | None, scope: Scope, tool: LocalTool,
                  action: Callable[[DispatchMarker | None], Awaitable[_Result]],
                  request: UUID | None = None) -> _Result:
    if journal is None:
        return await action(None)
    operation = await journal.begin(scope, tool, request)

    async def dispatch() -> None:
        await journal.mark_dispatch(operation)

    try:
        result = await action(dispatch)
    except asyncio.CancelledError:
        await journal.finish(operation, "cancelled")
        raise
    except Failure as exc:
        outcome: ToolOutcome = "denied" if exc.code in (Code.SCOPE, Code.OFFLINE, Code.INPUT, Code.EDITOR) else "failed"
        await journal.finish(operation, outcome, exc.code)
        raise
    except Exception:
        await journal.finish(operation, "failed", Code.INTERNAL)
        raise
    await journal.finish(operation, "succeeded")
    return result


def _require_current(current: Callable[[], bool]) -> None:
    if not current():
        raise Failure(Code.SCOPE)


def _permit(scope: Scope, role: Role, payload: dict[str, object], contract: type[_Tool],
            current: Callable[[], bool]) -> _Tool:
    proposal = prepare_proposal(scope, role, payload)
    if not isinstance(proposal.tool, contract):
        raise Failure(Code.INPUT)
    _require_current(current)
    return proposal.tool


async def _read(scope: Scope, current: Callable[[], bool], validate: Callable[[Scope], Awaitable[None]],
                read: Callable[[], Awaitable[_Result]], tool: LocalTool, journal: OperationJournal | None,
                request: UUID | None = None) -> _Result:
    async def run(dispatch: DispatchMarker | None) -> _Result:
        await validate(scope)
        _require_current(current)
        if dispatch is not None:
            await dispatch()
            await validate(scope)
            _require_current(current)
        result = await read()
        _require_current(current)
        return result

    result = await _record(journal, scope, tool, run, request)
    if journal is not None:
        # The terminal write yields the event loop. Recheck access before releasing retained content.
        await validate(scope)
        _require_current(current)
    return result


class SavedCodeStore(Protocol):
    async def validate(self, scope: Scope) -> None: ...
    async def saved_code_revisions(self, scope: Scope) -> list[SourceRevision]: ...
    async def source_revision(self, scope: Scope, source_id: str, revision_id: str) -> SourceRevision: ...
    async def saved_code_context(self, scope: Scope, source: str, revision: str, max_bytes: int) -> EvidenceBundle: ...


class SavedCodeBroker:
    def __init__(self, store: SavedCodeStore, journal: OperationJournal | None = None) -> None:
        self.store = store
        self.journal = journal

    async def choices(self, scope: Scope) -> list[SourceRevision]:
        await self.store.validate(scope)
        return await self.store.saved_code_revisions(scope)

    async def identify(self, scope: Scope, selection: SavedCode) -> SourceRevision:
        await self.store.validate(scope)
        return await self.store.source_revision(scope, selection.source, selection.revision)

    async def read(self, scope: Scope, selection: SavedCode, budget: int, *,
                   current: Callable[[], bool] = lambda: True, request: UUID | None = None) -> EvidenceBundle:
        tool = _permit(scope, Role.CODING, {"tool": "coding.read_saved_code", "source": selection.source,
                                           "revision": selection.revision, "max_bytes": budget}, ReadSavedCode, current)
        return await _read(scope, current, self.store.validate,
                           lambda: self.store.saved_code_context(scope, tool.source, tool.revision, tool.max_bytes),
                           tool, self.journal, request)


class LocalReadStore(Protocol):
    async def validate(self, scope: Scope) -> None: ...
    async def cited_context(self, scope: Scope, question: str, *, revision: str | None = None,
                            max_bytes: int = 8192, max_passages: int = 8) -> EvidenceBundle: ...
    async def resolve_locator(self, scope: Scope, source: str, revision: str, locator: str) -> Locator: ...
    async def recall_facts(self, scope: Scope, *, destination: Destination = Destination.PROJECT) -> list[Fact]: ...


class LocalReadBroker:
    def __init__(self, store: LocalReadStore, journal: OperationJournal | None = None) -> None:
        self.store = store
        self.journal = journal

    async def search(self, scope: Scope, query: str, revision: str | None, current: Callable[[], bool]) -> EvidenceBundle:
        tool = _permit(scope, Role.FILES, {"tool": "files.search_evidence", "query": query, "revision": revision},
                       SearchEvidence, current)
        return await _read(scope, current, self.store.validate,
                           lambda: self.store.cited_context(scope, tool.query, revision=tool.revision,
                                                            max_bytes=65536, max_passages=24), tool, self.journal)

    async def inspect(self, scope: Scope, source: str, revision: str, locator: str,
                      current: Callable[[], bool]) -> Locator:
        tool = _permit(scope, Role.FILES, {"tool": "files.inspect_citation", "source": source,
                                          "revision": revision, "locator": locator}, InspectCitation, current)
        return await _read(scope, current, self.store.validate,
                           lambda: self.store.resolve_locator(scope, tool.source, tool.revision, tool.locator),
                           tool, self.journal)

    async def recall(self, scope: Scope, destination: Destination, current: Callable[[], bool]) -> list[Fact]:
        tool = _permit(scope, Role.MEMORY, {"tool": "memory.recall_facts", "destination": destination.value},
                       RecallFacts, current)
        return await _read(scope, current, self.store.validate,
                           lambda: self.store.recall_facts(scope, destination=Destination(tool.destination)),
                           tool, self.journal)


class ApprovedProjectStore(Protocol):
    async def approved_project_root(self, scope: Scope) -> Path: ...


class EditorLaunchBroker:
    def __init__(self, store: ApprovedProjectStore, launcher: VSCodeLauncher,
                 journal: OperationJournal | None = None) -> None:
        self.store = store
        self.launcher = launcher
        self.journal = journal

    async def open_project(self, scope: Scope, current: Callable[[], bool], *, target: Path | None = None) -> None:
        tool = _permit(scope, Role.SYSTEM, {"tool": "system.open_approved_project"}, OpenApprovedProject, current)
        await _record(self.journal, scope, tool, lambda dispatch: self._launch(scope, current, target, dispatch))

    async def _launch(self, scope: Scope, current: Callable[[], bool], target: Path | None,
                      dispatch: DispatchMarker | None) -> None:
        approved = await self.store.approved_project_root(scope)
        root = await asyncio.to_thread(canonical_directory, approved)
        if root.parts != approved.parts or not current():
            raise Failure(Code.SCOPE)
        if target is not None and (await asyncio.to_thread(canonical_directory, target)).parts != root.parts:
            raise Failure(Code.SCOPE)
        image = await asyncio.to_thread(self.launcher.resolve)
        with pin_path(image) as handle:
            await asyncio.to_thread(self.launcher.verify, image, handle)
            with pin_path(root, directory=True):
                if dispatch is not None:
                    if (await self.store.approved_project_root(scope)).parts != root.parts:
                        raise Failure(Code.SCOPE)
                    _require_current(current)
                    await dispatch()
                if (await self.store.approved_project_root(scope)).parts != root.parts:
                    raise Failure(Code.SCOPE)
                _require_current(current)
                self.launcher.launch(image, root)
