"""Identify the bytes of one explicitly selected local file without retaining a copy."""
import hashlib
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ..contracts.messages import Code, Failure
from ..settings import check_local_route


@dataclass(frozen=True, slots=True)
class SourceRevision:
    source_id: str
    revision_id: str
    relative_path: str
    sha256: str
    byte_count: int


def _opened_path(stream: BinaryIO, path: Path) -> Path:
    if os.name != "nt":
        if not os.path.samestat(os.fstat(stream.fileno()), path.stat()):
            raise Failure(Code.CONFLICT)
        return path
    import ctypes
    import msvcrt
    from ctypes import wintypes

    final_name = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    final_name.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    final_name.restype = wintypes.DWORD
    name = ctypes.create_unicode_buffer(32768)
    size = final_name(msvcrt.get_osfhandle(stream.fileno()), name, len(name), 0)
    if not 0 < size < len(name):
        raise Failure(Code.SCOPE)
    return Path(name.value.removeprefix("\\\\?\\"))


@contextmanager
def approved_stream(root: Path, selected: Path) -> Iterator[tuple[str, BinaryIO, int]]:
    if (not selected.is_absolute() or str(selected).startswith("\\\\") or
            any(":" in part or part == ".." or Path(part).is_reserved() for part in selected.parts[1:])):
        raise Failure(Code.SCOPE)
    try:
        check_local_route(selected)
        path = selected.resolve(strict=True)
        # Compare exact canonical components even in case-sensitive Windows directories.
        if path.parts[:len(root.parts)] != root.parts or not path.is_file():
            raise Failure(Code.SCOPE)
        with path.open("rb") as stream:
            actual = _opened_path(stream, path)
            before = os.fstat(stream.fileno())
            if (actual.parts != path.parts or before.st_nlink != 1 or
                    not stat.S_ISREG(before.st_mode)):
                raise Failure(Code.SCOPE)
            yield path.relative_to(root).as_posix(), stream, before.st_size
            after = os.fstat(stream.fileno())
            if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                    or not os.path.samestat(after, path.stat())):
                raise Failure(Code.CONFLICT)
    except (OSError, ValueError, RuntimeError) as exc:
        raise Failure(Code.SCOPE) from exc


def fingerprint(root: Path, selected: Path, checkpoint: Callable[[], None] | None = None) -> tuple[str, str, int]:
    with approved_stream(root, selected) as (relative, stream, size):
        if checkpoint is None:
            return relative, hashlib.file_digest(stream, "sha256").hexdigest(), size
        digest = hashlib.sha256()
        while True:
            checkpoint()
            chunk = stream.read(256 * 1024)
            if not chunk:
                return relative, digest.hexdigest(), size
            digest.update(chunk)
