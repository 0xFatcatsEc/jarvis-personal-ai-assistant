"""Desktop-owned invitation and session lifecycle for editor v1."""
import asyncio
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..contracts.messages import Code, Failure, Scope
from ..security.broker import ApprovedProjectStore
from ..storage.editor_journal import EditorJournal
from .launch import canonical_directory
from .named_pipe import LocalPipe
from .patch import (REVIEW_SECONDS, DocumentBase, PatchApproval, PatchPreview, PatchProposal,
                    PatchRecovery, ReviewedPatch, now_ms, verify_digest)
from .protocol import VERSION, ProtocolError, Request, decode_object, decode_request, encode_frame
from .snapshot import Binding, BufferHistory, Snapshot, local_file_uri, resolve_document, resolve_snapshot

INVITATION_SECONDS = 90
SESSION_SECONDS = 900
IDLE_SECONDS = 30


@dataclass(frozen=True, slots=True)
class SharedSnapshot:
    scope: Scope
    window: str
    workspace: Path
    relative_path: str
    metadata: Snapshot


class EditorBridge:
    def __init__(self, owner_sid: str, status: Callable[[str], None], *,
                 store: ApprovedProjectStore | None = None,
                 current_scope: Callable[[], Scope | None] | None = None,
                 journal: EditorJournal | None = None) -> None:
        self.owner_sid = owner_sid
        self.status = status
        self.store = store
        self.current_scope = current_scope
        self.journal = journal
        self.snapshot: SharedSnapshot | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def issue(self, scope: Scope | None = None) -> str:
        async with self._lock:
            if scope is not None:
                await self._approved_root(scope)
            await self._stop()
            name = rf"\\.\pipe\stylus-jarvis-editor-{secrets.token_hex(16)}"
            credential = secrets.token_urlsafe(32)
            pipe = LocalPipe(name, self.owner_sid)
            self._task = asyncio.create_task(self._serve(pipe, credential, scope))
            self.status("Waiting for VS Code pairing")
            return json.dumps({"pipe": name, "invitation": credential}, separators=(",", ":"))

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        if task := self._task:
            self._task = None
            # Let a newly scheduled server take ownership of its handle first.
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _approved_root(self, scope: Scope) -> Path:
        if (self.store is None or self.current_scope is None or scope.owner != self.owner_sid
                or self.current_scope() != scope):
            raise Failure(Code.SCOPE)
        root = await self.store.approved_project_root(scope)
        if self.current_scope() != scope:
            raise Failure(Code.SCOPE)
        return root

    async def _serve(self, pipe: LocalPipe, credential: str, scope: Scope | None) -> None:
        loop = asyncio.get_running_loop()
        invitation_deadline = loop.time() + INVITATION_SECONDS
        try:
            while loop.time() < invitation_deadline:
                async with asyncio.timeout_at(invitation_deadline):
                    await pipe.connect()
                try:
                    async with asyncio.timeout_at(min(invitation_deadline, loop.time() + 5)):
                        request = decode_request(await pipe.receive(), time.time_ns() // 1_000_000)
                        if (pipe.peer_sid() != self.owner_sid or request.operation != "pair"
                                or not secrets.compare_digest(request.credential, credential)):
                            raise ProtocolError("Pairing refused")
                except (TimeoutError, EOFError, OSError, ProtocolError):
                    pipe.disconnect()
                    continue
                credential = ""
                first_id, window, patches = request.request_id, request.window, request.patches
                del request
                await self._session(pipe, first_id, window, scope, patches)
                return
        except (TimeoutError, EOFError, OSError, ProtocolError, Failure):
            pass
        finally:
            pipe.close()
            self.snapshot = None
            self.status("VS Code disconnected")

    async def _session(self, pipe: LocalPipe, last_id: int, window: str | None,
                       scope: Scope | None, patches: bool) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SESSION_SECONDS
        session = secrets.token_hex(16)
        hello: dict[str, object] = {"request_id": last_id, "version": VERSION, "session": session,
                                    "capabilities": ["ping"]}
        binding = None
        journal = self.journal if patches else None
        if scope is not None:
            await self._approved_root(scope)
            if window is not None:
                binding = Binding.from_scope(scope)
                capabilities = ["ping", "snapshot", "patch"] if journal else ["ping", "snapshot"]
                hello.update(capabilities=capabilities, window=window, binding=binding.model_dump())
        buffers = BufferHistory()
        review: ReviewedPatch | None = None
        dispatched: str | None = None
        self.status("VS Code paired")
        async with asyncio.timeout(5):
            await pipe.send(encode_frame(hello))
        while True:
            async with asyncio.timeout_at(min(deadline, loop.time() + IDLE_SECONDS)):
                request = decode_request(await pipe.receive(), time.time_ns() // 1_000_000)
                if (loop.time() >= deadline or pipe.peer_sid() != self.owner_sid or request.operation == "pair"
                        or request.request_id <= last_id or not secrets.compare_digest(request.credential, session)):
                    raise ProtocolError("Session refused")
                last_id = request.request_id
                response: dict[str, object] = {"request_id": last_id, "version": VERSION, "ok": True}
                remaining = (request.deadline_ms - time.time_ns() // 1_000_000) / 1000
                async with asyncio.timeout(remaining):
                    root = await self._approved_root(scope) if scope is not None else None
                    if request.operation != "ping":
                        if (scope is None or root is None or binding is None
                                or request.binding != binding or request.window != window):
                            raise ProtocolError("Editor binding refused")
                        if request.operation == "snapshot":
                            assert window is not None
                            error = await self._publish(request, scope, window, root, buffers)
                            if error is not None:
                                response.update(ok=False, error=error.value)
                        else:
                            if journal is None or window is None:
                                raise ProtocolError("Patch capability unavailable")
                            try:
                                if isinstance(request.patch, PatchPreview):
                                    review = None
                                    receipt = await journal.latest(scope, root)
                                    if receipt is not None and receipt["state"] == "uncertain":
                                        raise Failure(Code.BUSY)
                                    review, buffers = await self._prepare_patch(scope, root, buffers, request.patch)
                                    response["digest"] = review.digest
                                elif isinstance(request.patch, PatchApproval):
                                    previous, review = review, None
                                    await self._authorize_patch(scope, root, buffers, previous, request.patch)
                                    assert previous is not None
                                    expires = min(request.deadline_ms, now_ms() + 2000)
                                    dispatched = await journal.reserve(scope, root, window, previous, expires)
                                    if (await self._approved_root(scope)).parts != root.parts:
                                        raise Failure(Code.SCOPE)
                                    if expires <= now_ms():
                                        raise TimeoutError
                                    response.update(digest=request.patch.digest, expires_ms=expires,
                                                    operation_id=dispatched)
                                elif isinstance(request.patch, PatchRecovery):
                                    report = await self._recover_patch(journal, scope, root, request.patch, dispatched)
                                    if (await self._approved_root(scope)).parts != root.parts:
                                        raise Failure(Code.SCOPE)
                                    response["report"] = report
                            except Failure as error:
                                response.update(ok=False, error=error.code.value)
                    await pipe.send(encode_frame(response))

    async def _recover_patch(self, journal: EditorJournal, scope: Scope, root: Path,
                             request: PatchRecovery, dispatched: str | None) -> dict | None:
        def resolve() -> dict[str, DocumentBase]:
            if canonical_directory(local_file_uri(request.workspace_uri)).parts != root.parts:
                raise Failure(Code.SCOPE)
            observed = {}
            for base in request.observed:
                path = resolve_document(root, request.workspace_uri, base.document_uri)
                if path in observed:
                    raise Failure(Code.CONFLICT)
                observed[path] = base
            return observed

        observed = await asyncio.to_thread(resolve)
        if (await self._approved_root(scope)).parts != root.parts:
            raise Failure(Code.SCOPE)
        if request.action == "latest":
            return await journal.latest(scope, root)
        assert request.operation is not None
        if request.action == "result" and request.operation != dispatched:
            raise Failure(Code.SCOPE)
        return await journal.settle(scope, root, request.operation, observed,
                                    settled_dispatch=request.action == "result",
                                    acknowledge=request.action == "acknowledge")

    async def _prepare_patch(self, scope: Scope, root: Path, buffers: BufferHistory,
                             request: PatchPreview) -> tuple[ReviewedPatch, BufferHistory]:
        if not verify_digest(request.proposal, request.digest):
            raise Failure(Code.CONFLICT)
        try:
            proposal = PatchProposal.model_validate(decode_object(request.proposal))
        except (ValidationError, ValueError, RecursionError) as error:
            raise ProtocolError("Invalid patch proposal") from error
        if any(verify_digest(target.replacement, target.base.sha256) for target in proposal.targets):
            raise Failure(Code.CONFLICT)
        paths = await asyncio.to_thread(proposal.paths, root)
        if (await self._approved_root(scope)).parts != root.parts:
            raise Failure(Code.SCOPE)
        candidate = buffers.copy()
        self._check_patch_bases(candidate, proposal, paths)
        return ReviewedPatch(proposal, request.digest, paths,
                             asyncio.get_running_loop().time() + REVIEW_SECONDS), candidate

    @staticmethod
    def _check_patch_bases(buffers: BufferHistory, proposal: PatchProposal, paths: tuple[str, ...]) -> None:
        for path, target in zip(paths, proposal.targets, strict=True):
            base = target.base
            buffers.accept_identity(path, base.document_id, base.document_version, base.sha256)

    async def _authorize_patch(self, scope: Scope, root: Path, buffers: BufferHistory,
                               review: ReviewedPatch | None, request: PatchApproval) -> None:
        loop = asyncio.get_running_loop()
        if (review is None or not request.approved or request.digest != review.digest
                or loop.time() >= review.expiry or request.observed != [target.base for target in review.proposal.targets]):
            raise Failure(Code.CONFLICT)
        paths = await asyncio.to_thread(review.proposal.paths, root)
        if paths != review.paths or (await self._approved_root(scope)).parts != root.parts:
            raise Failure(Code.SCOPE)
        if loop.time() >= review.expiry:
            raise Failure(Code.CONFLICT)
        self._check_patch_bases(buffers.copy(), review.proposal, paths)

    async def _publish(self, request: Request, scope: Scope, window: str, root: Path,
                       buffers: BufferHistory) -> Code | None:
        assert request.snapshot is not None
        snapshot = request.snapshot
        try:
            path = await asyncio.to_thread(resolve_snapshot, root, snapshot)
        except Failure as error:
            return error.code
        if (await self._approved_root(scope)).parts != root.parts:
            raise Failure(Code.SCOPE)
        if time.time_ns() // 1_000_000 >= request.deadline_ms:
            raise TimeoutError
        try:
            buffers.accept(path, snapshot)
        except Failure as error:
            return error.code
        self.snapshot = SharedSnapshot(scope, window, root, path, snapshot)
        self.status("VS Code context received")
        return None
