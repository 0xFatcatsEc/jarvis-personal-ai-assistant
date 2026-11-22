"""Bounded, cancellable, numeric-loopback Ollama HTTP adapter."""
import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import asdict

import httpx

from ..contracts.messages import ChatMessage, Code, Failure
from ..settings import Manifest, Settings


class Ollama:
    def __init__(self, settings: Settings, manifest: Manifest, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.manifest = manifest
        host = settings.host if ":" not in settings.host else f"[{settings.host}]"
        self._client = httpx.AsyncClient(base_url=f"http://{host}:{settings.port}", trust_env=False,
                                         follow_redirects=False, transport=transport,
                                         headers={"Accept-Encoding": "identity"})

    async def probe(self) -> None:
        try:
            async with asyncio.timeout(3), self._client.stream("GET", "/api/tags", timeout=3) as reply:
                reply.raise_for_status()
                data = bytearray()
                async for block in reply.aiter_bytes(chunk_size=16384):
                    data.extend(block)
                    if len(data) > 2**20:
                        raise Failure(Code.STREAM)
                models = json.loads(data)["models"]
                for model in models:
                    if model["name"] == self.manifest.model:
                        if model["digest"].removeprefix("sha256:") != self.manifest.digest:
                            raise Failure(Code.DIGEST)
                        return
                raise Failure(Code.MODEL)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise Failure(Code.MODEL) from exc
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise Failure(Code.STREAM) from exc

    async def generate(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        payload = {"model": self.manifest.model, "messages": [asdict(m) for m in messages],
                   "think": False, "stream": True,
                   "options": {"num_ctx": self.settings.context, "num_predict": self.settings.output}}
        try:
            async with asyncio.timeout(300), self._client.stream("POST", "/api/chat", json=payload, timeout=60) as response:
                response.raise_for_status()
                buffer = bytearray()
                total = 0
                chunks = aiter(response.aiter_bytes())
                deadline = 60
                while True:
                    try:
                        async with asyncio.timeout(deadline):
                            chunk = await anext(chunks)
                    except StopAsyncIteration:
                        # A final NDJSON record may omit its trailing newline.
                        if not buffer:
                            break
                        chunk = b"\n"
                    deadline = 30
                    total += len(chunk)
                    if total > 8*1024*1024:
                        raise Failure(Code.STREAM)
                    buffer.extend(chunk)
                    while (end := buffer.find(b"\n")) >= 0:
                        line = bytes(buffer[:end])
                        del buffer[:end+1]
                        if not line.strip():
                            continue
                        if len(line) > 1024*1024:
                            raise Failure(Code.STREAM)
                        frame = json.loads(line)
                        if not isinstance(frame, dict) or "error" in frame or type(frame.get("done")) is not bool:
                            raise Failure(Code.STREAM)
                        content = frame["message"]["content"]
                        if not isinstance(content, str):
                            raise Failure(Code.STREAM)
                        if content:
                            yield content
                        if frame["done"]:
                            return
                    if len(buffer) > 1024*1024:
                        raise Failure(Code.STREAM)
                raise Failure(Code.STREAM)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise Failure(Code.MODEL) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise Failure(Code.STREAM) from exc

    async def close(self) -> None:
        await self._client.aclose()

