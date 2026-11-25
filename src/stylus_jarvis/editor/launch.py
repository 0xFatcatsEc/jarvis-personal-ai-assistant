"""Windows adapter for opening one approved folder in stable VS Code."""
import ctypes as c
import os
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes as w
from pathlib import Path

from ..contracts.messages import Code, Failure
from ..runtime.offline import open_vscode_window
from ..settings import check_local_route
from .authenticode import is_stable_vscode


def canonical_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise Failure(Code.SCOPE)
    try:
        check_local_route(path)
        resolved = path.resolve(strict=True)
        check_local_route(resolved)
        if not resolved.is_dir():
            raise Failure(Code.SCOPE)
        return resolved
    except OSError as error:
        raise Failure(Code.SCOPE) from error


@contextmanager
def pin_path(path: Path, *, directory: bool = False) -> Iterator[int]:
    """Hold the canonical object against replacement through process creation."""
    kernel = c.WinDLL("kernel32", use_last_error=True, winmode=0x800)
    create = kernel.CreateFileW
    create.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE)
    create.restype = w.HANDLE
    release = kernel.CloseHandle
    release.argtypes = (w.HANDLE,)
    release.restype = w.BOOL
    name = kernel.GetFinalPathNameByHandleW
    name.argtypes = (w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD)
    name.restype = w.DWORD
    access = 0x80 if directory else 0x80000000  # FILE_READ_ATTRIBUTES or GENERIC_READ
    share = 3 if directory else 1  # Allow directory readers and writers, and deny deletion.
    flags = 0x02000000 if directory else 0  # FILE_FLAG_BACKUP_SEMANTICS for directories
    handle = create(str(path), access, share, None, 3, flags, None)
    error = Code.SCOPE if directory else Code.EDITOR
    if handle in (None, c.c_void_p(-1).value):
        raise Failure(error)
    try:
        buffer = c.create_unicode_buffer(32768)
        size = name(handle, buffer, len(buffer), 0)
        if not 0 < size < len(buffer) or Path(buffer.value.removeprefix("\\\\?\\")).parts != path.parts:
            raise Failure(error)
        yield handle
    finally:
        release(handle)


class VSCodeLauncher:
    def resolve(self) -> Path:
        if os.name != "nt":
            raise Failure(Code.EDITOR)
        locations = (
            ("LOCALAPPDATA", "Programs/Microsoft VS Code/Code.exe"),
            ("ProgramW6432", "Microsoft VS Code/Code.exe"),
            ("ProgramFiles", "Microsoft VS Code/Code.exe"),
        )
        for variable, relative in locations:
            base = Path(os.environ.get(variable, ""))
            if not base.is_absolute():
                continue
            candidate = base / relative
            try:
                check_local_route(candidate)
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError:
                continue
            except OSError as error:
                raise Failure(Code.EDITOR) from error
            if resolved.parts != candidate.parts or not resolved.is_file():
                raise Failure(Code.EDITOR)
            return resolved
        raise Failure(Code.EDITOR)

    def verify(self, image: Path, handle: int) -> None:
        try:
            trusted = is_stable_vscode(image, handle)
        except (OSError, AttributeError) as error:
            raise Failure(Code.EDITOR) from error
        if not trusted:
            raise Failure(Code.EDITOR)

    def launch(self, image: Path, root: Path) -> None:
        open_vscode_window(image, root)
