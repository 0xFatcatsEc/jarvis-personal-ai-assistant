"""Local-only routing and prompt budgeting."""
from collections.abc import AsyncGenerator

from ..contracts.messages import ChatMessage, Code, Failure
from ..contracts.ports import Model
from ..settings import Manifest, Settings


class Router:
    def __init__(self, local: Model, settings: Settings, manifest: Manifest) -> None:
        self.local = local
        self.digest = manifest.digest
        self._budget = settings.context - settings.output - 128
        self.verified = False

    def history_budget(self, prompt: str) -> int:
        # UTF-8 byte count conservatively bounds text tokens; reserve template overhead.
        remaining = self._budget - len(prompt.encode("utf-8"))
        if not prompt.strip() or remaining < 0:
            raise Failure(Code.INPUT)
        return remaining

    async def probe(self) -> None:
        self.verified = False
        await self.local.probe()
        self.verified = True

    def generate(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        if not self.verified:
            raise Failure(Code.MODEL)
        return self.local.generate(messages)

