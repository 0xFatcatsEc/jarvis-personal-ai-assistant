"""Turn lifecycle. The database owns durability; the event loop owns admission and selection."""
import asyncio
import time
from collections.abc import Callable
from contextlib import aclosing
from uuid import UUID

from ..contracts.messages import ChatMessage, Code, Failure, PendingSave, RuntimeEvent, Scope, State, Turn
from ..contracts.ports import ConversationStore, LocalRoute
from .diagnostics import Diagnostics, Event
from .scheduler import Scheduler


class Coordinator:
    def __init__(self, store: ConversationStore, router: LocalRoute, scheduler: Scheduler,
                 diagnostics: Diagnostics, emit: Callable[[RuntimeEvent], None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.store = store
        self.router = router
        self.scheduler = scheduler
        self.log = diagnostics
        self.emit = emit
        self.clock = clock
        self.selection: Scope | None = None
        self.pending: PendingSave | None = None
        self.recoverable = False

    def select(self, scope: Scope | None) -> None:
        if scope != self.selection:
            self.scheduler.stop()
            self.selection = scope

    def _deliver(self, scope: Scope, request: UUID, kind: str, text: str) -> None:
        if self.selection == scope:
            self.emit(RuntimeEvent(scope, request, kind, text))

    async def retry_save(self) -> Turn:
        item = self.pending
        scope = self.selection
        if item is None or scope is None or not scope.offline or (scope.owner, scope.project, scope.conversation) != (
            item.scope.owner, item.scope.project, item.scope.conversation
        ):
            raise Failure(Code.SCOPE)
        if scope.grant != item.scope.grant:
            await self.store.validate(scope)
        settled = False
        try:
            result = await self.store.finish(item.scope, item.key, item.state, item.answer, item.error)
            settled = True
        except Failure as exc:
            settled = exc.code == Code.SCOPE
            raise
        finally:
            if settled and self.pending is item:
                if self.recoverable:
                    await self.store.clear_recovery(item.key)
                if self.pending is item:
                    self.recoverable = False
                    self.pending = None
        await self.store.validate(item.scope)
        if scope != self.selection:
            raise Failure(Code.SCOPE)
        return result

    async def submit(self, scope: Scope, request: UUID, prompt: str) -> Turn:
        if scope != self.selection:
            raise Failure(Code.SCOPE)
        slot = self.scheduler.reserve(request)
        started = self.clock()
        try:
            prior = await self.store.lookup(scope, request, prompt)
            if prior is not None:
                await self.store.validate(scope)
            if slot.stopped or scope != self.selection:
                raise Failure(Code.SCOPE)
            if prior is not None:
                if prior.state == State.ACTIVE:
                    raise Failure(Code.BUSY)
                return prior
            if self.pending is not None:
                raise Failure(Code.STORE)
            remaining = self.router.history_budget(prompt)
            await self.store.validate(scope, require_root=True)
            await self.router.probe()
            history = await self.store.context(scope, remaining)
            if slot.stopped or scope != self.selection:
                raise Failure(Code.SCOPE)
            turn, fresh = await self.store.begin(scope, request, prompt, self.router.digest)
            if not fresh:
                await self.store.validate(scope)
                if self.selection != scope:
                    raise Failure(Code.SCOPE)
                if turn.state == State.ACTIVE:
                    raise Failure(Code.BUSY)
                return turn
            answer = ""
            state = State.COMPLETED
            error = None

            async def stream() -> None:
                nonlocal answer
                ordinal = 0
                last = self.clock()
                await self.store.validate(scope, require_root=True)
                stream = self.router.generate([*history, ChatMessage("user", prompt)])
                async with aclosing(stream):
                    async for part in stream:
                        await self.store.validate(scope)
                        if self.selection != scope or slot.stopped:
                            raise asyncio.CancelledError
                        if not answer:
                            self.log.emit(Event.FIRST, run=request, elapsed_ms=(self.clock()-started)*1000)
                        answer += part
                        self._deliver(scope, request, "fragment", part)
                        now = self.clock()
                        if now-last >= 1:
                            ordinal += 1
                            await self.store.checkpoint(scope, turn.key, ordinal, answer)
                            last = now

            try:
                await slot.consume(stream())
            except asyncio.CancelledError:
                state = State.CANCELLED
            except Failure as exc:
                error = exc.code
                state = State.TOKEN_LIMIT if error == Code.TOKEN_LIMIT else State.FAILED
            except Exception:
                error = Code.INTERNAL
                state = State.FAILED
            self.log.emit(Event.FINISH, run=request, code=error, outcome=state,
                          elapsed_ms=(self.clock()-started)*1000, digest=self.router.digest)
            try:
                result = await self.store.finish(scope, turn.key, state, answer, error)
            except Failure as exc:
                if exc.code in (Code.STORE, Code.BUSY):
                    item = PendingSave(scope, turn.key, state, answer, error)
                    self.recoverable = False
                    try:
                        await self.store.preserve(item)
                        self.recoverable = True
                    finally:
                        self.pending = item
                        self._deliver(scope, request, "unsaved", "Reply unsaved. Retry the save in this conversation.")
                raise
            if error is not None and state != State.TOKEN_LIMIT:
                raise Failure(error)
            await self.store.validate(scope)
            self._deliver(scope, request, "saved", result.state.value)
            return result
        finally:
            self.scheduler.release(slot)

