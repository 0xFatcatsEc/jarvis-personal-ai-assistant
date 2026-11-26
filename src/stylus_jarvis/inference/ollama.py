"""Bounded, cancellable, numeric-loopback Ollama HTTP adapter."""
import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, aclosing
from dataclasses import asdict
from typing import Any

import httpx

from ..contracts.messages import ChatMessage, Code, Failure
from ..settings import Manifest, Settings
from ..runtime.offline import verify_listener


class Ollama:
    def __init__(self, settings: Settings, manifest: Manifest, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.manifest = manifest
        host = settings.host if ":" not in settings.host else f"[{settings.host}]"
        self._client = httpx.AsyncClient(base_url=f"http://{host}:{settings.port}", trust_env=False,
                                         follow_redirects=False, transport=transport,
                                         headers={"Accept-Encoding": "identity"})

    async def _metadata(self, path: str) -> dict[str, Any]:
        async with self._client.stream("GET", path, timeout=3) as reply:
            reply.raise_for_status()
            data = bytearray()
            async for block in reply.aiter_bytes(chunk_size=16384):
                data.extend(block)
                if len(data) > 2**20:
                    raise Failure(Code.STREAM)
            value = json.loads(data)
            if not isinstance(value, dict):
                raise Failure(Code.STREAM)
            return value

    async def probe(self) -> None:
        await asyncio.to_thread(verify_listener, self.settings.host, self.settings.port)
        try:
            async with asyncio.timeout(3):
                status = await self._metadata("/api/status")
                if not isinstance(status.get("cloud"), dict) or status["cloud"].get("disabled") is not True:
                    raise Failure(Code.OFFLINE, detail="Offline policy blocked the model: Ollama did not confirm "
                                  "that cloud features are disabled. Start it with the guarded model launcher.")
                models = (await self._metadata("/api/tags"))["models"]
                for model in models:
                    if model["name"] == self.manifest.model:
                        if model.get("remote_model") or model.get("remote_host"):
                            raise Failure(Code.OFFLINE)
                        if model["digest"].removeprefix("sha256:") != self.manifest.digest:
                            raise Failure(Code.DIGEST)
                        break
                else:
                    raise Failure(Code.MODEL)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise Failure(Code.MODEL) from exc
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise Failure(Code.STREAM) from exc

    async def generate(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        # Check the effective native boundary and current service before any prompt
        # leaves this process, including calls made directly to the adapter.
        await self.probe()
        # The pinned Qwen template always opens a thinking block. With think=False
        # Ollama returns that block as content. Request separate thinking frames and
        # consume only the answer field.
        payload = {"model": self.manifest.model, "messages": [asdict(m) for m in messages],
                   "think": True, "stream": True,
                   "options": {"num_ctx": self.settings.context, "num_predict": self.settings.output,
                               "temperature": 0, "seed": 41}}
        try:
            async with asyncio.timeout(300), AsyncExitStack() as stack:
                response = await stack.enter_async_context(
                    self._client.stream("POST", "/api/chat", json=payload, timeout=60))
                response.raise_for_status()
                buffer = bytearray()
                total = 0
                chunks = await stack.enter_async_context(aclosing(response.aiter_bytes()))
                deadline = 60
                terminal_deadline: float | None = None
                truncated = False
                while True:
                    try:
                        async with asyncio.timeout_at(
                            terminal_deadline if terminal_deadline is not None else
                            asyncio.get_running_loop().time() + deadline
                        ):
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
                        if terminal_deadline is not None:
                            raise Failure(Code.STREAM)
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
                            reason = frame.get("done_reason")
                            count = frame.get("eval_count")
                            if reason == "length" or (reason in (None, "") and
                                    type(count) is int and count >= self.settings.output):
                                truncated = True
                            elif reason not in (None, "", "stop"):
                                raise Failure(Code.STREAM)
                            # Let HTTPX consume the response boundary before releasing the stream.
                            terminal_deadline = asyncio.get_running_loop().time() + 2
                    if len(buffer) > 1024*1024:
                        raise Failure(Code.STREAM)
                if terminal_deadline is None:
                    raise Failure(Code.STREAM)
                if truncated:
                    raise Failure(Code.TOKEN_LIMIT)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise Failure(Code.MODEL) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise Failure(Code.STREAM) from exc

    async def close(self) -> None:
        await self._client.aclose()

