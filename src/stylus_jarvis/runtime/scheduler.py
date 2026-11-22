"""Single-slot admission on the owning asyncio/Qt event loop."""
import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ..contracts.messages import Code, Failure


@dataclass(slots=True)
class Reservation:
    request: UUID
    stopped: bool = False
    stream: asyncio.Task[None] | None = None

    def stop(self) -> None:
        self.stopped = True
        if self.stream is not None:
            self.stream.cancel()

    async def consume(self, work: Coroutine[Any, Any, None]) -> None:
        self.stream = asyncio.create_task(work)
        if self.stopped:
            self.stream.cancel()
        try:
            await self.stream
        finally:
            self.stream = None


class Scheduler:
    def __init__(self) -> None:
        self.current: Reservation | None = None
        self.closing = False
        self.idle = asyncio.Event()
        self.idle.set()

    def reserve(self, request: UUID) -> Reservation:
        if self.closing or self.current is not None:
            raise Failure(Code.BUSY)
        self.current = Reservation(request)
        self.idle.clear()
        return self.current

    def release(self, slot: Reservation) -> None:
        if self.current is slot:
            self.current = None
            self.idle.set()

    def stop(self) -> None:
        if self.current:
            self.current.stop()

    async def shutdown(self, grace: float = 5.0) -> bool:
        self.closing = True
        self.stop()
        try:
            await asyncio.wait_for(self.idle.wait(), grace)
            return True
        except TimeoutError:
            return False

