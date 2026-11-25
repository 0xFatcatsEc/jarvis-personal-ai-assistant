"""Windows named-pipe transport. The Qt thread never waits on pending I/O."""
import asyncio
import ctypes as c
import os
import re
from ctypes import wintypes as w
from typing import Any

from .protocol import HEADER, MAX_FRAME, ProtocolError

if os.name == "nt":
    import _winapi


class _SecurityAttributes(c.Structure):
    _fields_ = [("size", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]


def _bind(library: Any, name: str, result: Any, *arguments: Any) -> Any:
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


class LocalPipe:
    def __init__(self, name: str, owner_sid: str) -> None:
        if os.name != "nt" or not re.fullmatch(r"S-1-(?:[0-9]+-){1,14}[0-9]+", owner_sid):
            raise OSError("Invalid Windows pipe owner")
        self.kernel = c.WinDLL("kernel32", use_last_error=True, winmode=0x800)
        self.security = c.WinDLL("advapi32", use_last_error=True, winmode=0x800)
        convert = _bind(self.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", w.BOOL,
                        w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(w.DWORD))
        free = _bind(self.kernel, "LocalFree", w.HANDLE, w.HANDLE)
        descriptor = c.c_void_p()
        # Duplex clients request generic read/write. First-instance ownership and
        # the single-instance limit keep the listening instance under desktop control.
        if not convert(f"D:P(A;;0x12019f;;;{owner_sid})", 1, c.byref(descriptor), None):
            raise c.WinError(c.get_last_error())
        try:
            create = _bind(self.kernel, "CreateNamedPipeW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD,
                           w.DWORD, w.DWORD, w.DWORD, w.DWORD, c.POINTER(_SecurityAttributes))
            attributes = _SecurityAttributes(c.sizeof(_SecurityAttributes), descriptor, False)
            # Duplex, overlapped, first instance. Byte mode with PIPE_REJECT_REMOTE_CLIENTS.
            self.handle = create(name, 0x40080003, 0x8, 1, MAX_FRAME + 4, MAX_FRAME + 4, 0, c.byref(attributes))
            if self.handle in (None, c.c_void_p(-1).value):
                raise c.WinError(c.get_last_error())
        finally:
            free(descriptor)

    @staticmethod
    async def _finish(operation: Any) -> int:
        try:
            while _winapi.WaitForSingleObject(operation.event, 0) == _winapi.WAIT_TIMEOUT:
                await asyncio.sleep(.02)
            count, error = operation.GetOverlappedResult(False)
            if error:
                raise c.WinError(error)
            return count
        except asyncio.CancelledError:
            operation.cancel()
            try:
                operation.GetOverlappedResult(True)
            except OSError:
                pass
            raise

    async def connect(self) -> None:
        operation = _winapi.ConnectNamedPipe(self.handle, overlapped=True)
        try:
            await self._finish(operation)
        except OSError as error:
            # CPython signals the event itself on ERROR_PIPE_CONNECTED. There is
            # no kernel I/O completion record to retrieve in that case.
            if error.winerror != 996:  # ERROR_IO_INCOMPLETE
                raise
            peer = w.DWORD()
            client_pid = _bind(self.kernel, "GetNamedPipeClientProcessId", w.BOOL, w.HANDLE, c.POINTER(w.DWORD))
            if not client_pid(self.handle, c.byref(peer)):
                raise error

    async def _read_exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            operation, _ = _winapi.ReadFile(self.handle, size - len(data), overlapped=True)
            received = await self._finish(operation)
            if not received:
                raise EOFError
            data.extend(operation.getbuffer()[:received])
        return bytes(data)

    async def receive(self) -> bytes:
        size, = HEADER.unpack(await self._read_exact(HEADER.size))
        if not 0 < size <= MAX_FRAME:
            raise ProtocolError("Invalid frame size")
        return await self._read_exact(size)

    async def send(self, data: bytes) -> None:
        operation, _ = _winapi.WriteFile(self.handle, data, overlapped=True)
        if await self._finish(operation) != len(data):
            raise OSError("Partial pipe response")

    def disconnect(self) -> None:
        disconnect = _bind(self.kernel, "DisconnectNamedPipe", w.BOOL, w.HANDLE)
        if not disconnect(self.handle) and (error := c.get_last_error()) not in (109, 233):
            raise c.WinError(error)

    def close(self) -> None:
        _winapi.CloseHandle(self.handle)

    def peer_sid(self) -> str:
        """Read the effective SID associated with the most recent client write."""
        impersonate = _bind(self.security, "ImpersonateNamedPipeClient", w.BOOL, w.HANDLE)
        revert = _bind(self.security, "RevertToSelf", w.BOOL)
        set_token = _bind(self.security, "SetThreadToken", w.BOOL, c.POINTER(w.HANDLE), w.HANDLE)
        thread = _bind(self.kernel, "GetCurrentThread", w.HANDLE)
        open_token = _bind(self.security, "OpenThreadToken", w.BOOL,
                           w.HANDLE, w.DWORD, w.BOOL, c.POINTER(w.HANDLE))
        info = _bind(self.security, "GetTokenInformation", w.BOOL, w.HANDLE, w.DWORD,
                     c.c_void_p, w.DWORD, c.POINTER(w.DWORD))
        convert = _bind(self.security, "ConvertSidToStringSidW", w.BOOL, c.c_void_p, c.POINTER(w.LPWSTR))
        free = _bind(self.kernel, "LocalFree", w.HANDLE, w.HANDLE)
        token = w.HANDLE()
        if not impersonate(self.handle):
            raise c.WinError(c.get_last_error())
        try:
            if not open_token(thread(), 0x0008, True, c.byref(token)):  # TOKEN_QUERY
                raise c.WinError(c.get_last_error())
        finally:
            if not revert() and not set_token(None, None):
                os._exit(1)  # Never continue the desktop under a client token.
        try:
            buffer = c.create_string_buffer(256)
            length = w.DWORD()
            if not info(token, 1, buffer, len(buffer), c.byref(length)):  # TokenUser
                raise c.WinError(c.get_last_error())
            sid = c.cast(buffer, c.POINTER(c.c_void_p))[0]
            name = w.LPWSTR()
            if not convert(sid, c.byref(name)):
                raise c.WinError(c.get_last_error())
            try:
                return name.value
            finally:
                free(c.cast(name, c.c_void_p))
        finally:
            _winapi.CloseHandle(token.value)
