"""Offline policy for the shipped Python workers and Windows model processes."""
import ctypes
import ipaddress
import os
import socket
import subprocess
import sys
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ..contracts.messages import Code, Failure


_approved_command: ContextVar[str | None] = ContextVar("offline_helper", default=None)
_installed = False


def _loopback(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    try:
        return isinstance(host, str) and "%" not in host and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event.startswith("socket."):
        if event == "socket.__new__" and threading.current_thread() is not threading.main_thread():
            raise Failure(Code.OFFLINE)
        if event in {"socket.getaddrinfo", "socket.gethostbyname"}:
            if not _loopback(args[0]):
                raise Failure(Code.OFFLINE)
        elif event in {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg", "socket.getnameinfo"}:
            address = args[0] if event == "socket.getnameinfo" else args[1]
            if (threading.current_thread() is not threading.main_thread() or
                    not isinstance(address, tuple) or not _loopback(address[0])):
                raise Failure(Code.OFFLINE)
            # Reverse lookup can use the system DNS service even for numeric input.
            if event == "socket.getnameinfo" and not args[1] & socket.NI_NUMERICHOST:
                raise Failure(Code.OFFLINE)
        if event == "socket.gethostbyaddr":
            raise Failure(Code.OFFLINE)
    elif event == "subprocess.Popen":
        if args[1] != _approved_command.get() or _approved_command.get() is None:
            raise Failure(Code.OFFLINE)
    elif event in {"os.system", "os.startfile", "os.spawn", "os.posix_spawn", "os.exec"}:
        raise Failure(Code.OFFLINE)


def install_worker_policy() -> None:
    global _installed
    if not _installed:
        sys.addaudithook(_audit)
        _installed = True


def _system_directory() -> Path:
    buffer = ctypes.create_unicode_buffer(32768)
    if not 0 < ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)) < len(buffer):
        raise Failure(Code.OFFLINE)
    return Path(buffer.value)


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    token = _approved_command.set(subprocess.list2cmdline(args))
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    finally:
        _approved_command.reset(token)


def whoami() -> bytes:
    return _run([str(_system_directory() / "whoami.exe"), "/user", "/fo", "csv", "/nh"], 5).stdout


def _check_windows(arguments: list[str]) -> None:
    if os.name != "nt":
        raise Failure(Code.OFFLINE)
    image = ctypes.create_unicode_buffer(32768)
    if not 0 < ctypes.windll.kernel32.GetModuleFileNameW(None, image, len(image)) < len(image):
        raise Failure(Code.OFFLINE)
    checker = Path(__file__).with_name("offline-policy.ps1")
    powershell = _system_directory() / "WindowsPowerShell/v1.0/powershell.exe"
    try:
        _run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned", "-File", str(checker),
              "-PythonImage", image.value, *arguments], 30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Failure(Code.OFFLINE) from exc


def verify_application() -> None:
    _check_windows(["-Mode", "CheckApp"])


def verify_listener(host: str, port: int) -> None:
    if not _loopback(host):
        raise Failure(Code.OFFLINE)
    _check_windows(["-Mode", "Verify", "-ListenAddress", host, "-Port", str(port)])
