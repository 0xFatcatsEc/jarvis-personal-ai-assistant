"""One cooperative worker for explicitly requested source indexing."""
import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from ..contracts.messages import Code, Failure, Scope
from ..storage.repositories import Repositories

MAX_PENDING = 24


@dataclass(slots=True)
class IndexJob:
    scope: Scope
    path: Path
    cancelled: Event = field(default_factory=Event)

    @property
    def key(self) -> tuple[Scope, tuple[str, ...]]:
        return self.scope, self.path.parts


class IndexQueue:
    def __init__(self, store: Repositories, report: Callable[[Scope, str], None]) -> None:
        self.store = store
        self.report = report
        self.pending: OrderedDict[tuple[Scope, tuple[str, ...]], IndexJob] = OrderedDict()
        self.active: IndexJob | None = None
        self.running = False
        self.idle = Event()
        self.idle.set()

    def set_foreground(self, busy: bool) -> None:
        if busy:
            self.idle.clear()
        else:
            self.idle.set()

    def put(self, scope: Scope, path: Path) -> bool:
        job = IndexJob(scope, path)
        if job.key not in self.pending and len(self.pending) >= MAX_PENDING:
            raise Failure(Code.BUSY)
        if self.active is not None and self.active.key == job.key:
            self.active.cancelled.set()
        self.pending[job.key] = job
        if self.running:
            return False
        self.running = True
        return True

    def clear(self) -> None:
        self.pending.clear()
        if self.active is not None:
            self.active.cancelled.set()

    def _checkpoint(self, job: IndexJob) -> None:
        while not job.cancelled.is_set():
            if self.idle.wait(.05) and not job.cancelled.is_set():
                return
        raise Failure(Code.CONFLICT)

    async def _index(self, job: IndexJob) -> str:
        def checkpoint() -> None:
            self._checkpoint(job)

        await asyncio.to_thread(checkpoint)
        receipt = await self.store.approve_source(job.scope, job.path, checkpoint=checkpoint)
        await asyncio.to_thread(checkpoint)
        locators = await self.store.extract_locators(job.scope, receipt.source_id, receipt.revision_id,
                                                     checkpoint=checkpoint)
        previous = await self.store.active_revision(job.scope, receipt.source_id)
        await asyncio.to_thread(checkpoint)
        replaces = (receipt.source_id, previous) if previous and previous != receipt.revision_id else None
        await self.store.publish_revision(job.scope, receipt.source_id, receipt.revision_id, replaces=replaces)
        return f"Saved locators: {len(locators)} · Pages needing OCR: {sum(item.ocr_needed for item in locators)}"

    async def drain(self) -> None:
        try:
            while self.pending:
                _, job = self.pending.popitem(last=False)
                self.active = job
                try:
                    message = await self._index(job)
                except Failure as error:
                    message = str(error)
                except Exception:
                    message = "Source indexing failed. Try selecting the file again."
                if not job.cancelled.is_set():
                    self.report(job.scope, message)
        finally:
            self.active = None
            self.running = False
