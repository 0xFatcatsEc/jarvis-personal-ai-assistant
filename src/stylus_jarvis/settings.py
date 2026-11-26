"""Immutable local configuration. No environment-controlled model destination."""
import ipaddress
import os
import stat
import sys
import tempfile
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .contracts.messages import Code, Failure


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Manifest(Frozen):
    version: Literal[1]
    build: str
    model: str = Field(pattern=r"^qwen3:[a-zA-Z0-9_.-]+$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Settings(Frozen):
    version: Literal[1] = 1
    host: str = "127.0.0.1"
    port: int = Field(default=11434, ge=1, le=65535)
    context: int = Field(default=4096, ge=2048, le=32768)
    output: int = Field(default=512, ge=32, le=1024)
    offline: Literal[True] = True

    @field_validator("host")
    @classmethod
    def local_only(cls, value: str) -> str:
        address = ipaddress.ip_address(value)
        if not address.is_loopback or "%" in value:
            raise ValueError("numeric loopback required")
        return str(address)


def profile_path() -> Path:
    raw = os.getenv("LOCALAPPDATA")
    if not raw or not Path(raw).is_absolute():
        raise Failure(Code.SETTINGS, field="LOCALAPPDATA")
    rehearsal = Path(raw) / "StylusJarvis-Rehearsal"
    if Path(sys.executable) == rehearsal / "runtime/python/python.exe":
        return local_data_path(rehearsal)
    return local_data_path(Path(raw) / "StylusJarvis")


def _onedrive_roots() -> set[Path]:
    roots = {Path(v) for k, v in os.environ.items() if k.lower().startswith("onedrive") and v}
    if os.name == "nt":
        import winreg

        try:
            accounts = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts")
        except FileNotFoundError:
            return roots
        with accounts:
            for index in range(winreg.QueryInfoKey(accounts)[0]):
                with winreg.OpenKey(accounts, winreg.EnumKey(accounts, index)) as account:
                    try:
                        folder, _ = winreg.QueryValueEx(account, "UserFolder")
                    except FileNotFoundError:
                        continue
                    if folder:
                        roots.add(Path(os.path.expandvars(folder)))
    return roots


def check_local_route(path: Path) -> None:
    """Inspect Windows link targets before a filesystem worker follows them."""
    if os.name != "nt":
        return
    import ctypes

    path = Path(os.path.abspath(path))
    for _ in range(64):
        if (str(path).startswith("\\\\") or not path.is_absolute() or
                ctypes.windll.kernel32.GetDriveTypeW(path.anchor) not in (2, 3)):
            raise Failure(Code.OFFLINE)
        parent = Path(path.anchor)
        for index, name in enumerate(path.parts[1:], 2):
            parent = parent / name
            try:
                info = parent.lstat()
            except FileNotFoundError:
                return
            # Cloud placeholders may request recall on open or on data access.
            if info.st_file_attributes & (stat.FILE_ATTRIBUTE_OFFLINE | 0x40000 | 0x400000):
                raise Failure(Code.OFFLINE)
            if info.st_reparse_tag in (stat.IO_REPARSE_TAG_SYMLINK, stat.IO_REPARSE_TAG_MOUNT_POINT):
                target = os.readlink(parent)
                if target.startswith("\\\\?\\") and len(target) > 6 and target[5:7] == ":\\":
                    target = target[4:]
                path = Path(os.path.abspath((parent.parent / target).joinpath(*path.parts[index:])))
                break
        else:
            return
    raise Failure(Code.OFFLINE)


def local_data_path(path: Path) -> Path:
    """Resolve existing ancestors before checking a possibly new data location."""
    try:
        if str(path).startswith("\\\\"):
            raise Failure(Code.SETTINGS, field="data_directory")
        check_local_route(path)
        existing = path.absolute()
        missing: list[str] = []
        while True:
            try:
                existing.lstat()
                break
            except FileNotFoundError:
                if existing == existing.parent:
                    raise
                missing.append(existing.name)
                existing = existing.parent
        # Strict resolution rejects inaccessible and dangling reparse targets.
        ancestor = existing.resolve(strict=True)
        result = ancestor.joinpath(*reversed(missing)).resolve()
        if str(result).startswith("\\\\"):
            raise Failure(Code.SETTINGS, field="data_directory")
        for sync in _onedrive_roots():
            if str(sync).startswith("\\\\"):
                continue  # A UNC root cannot contain the validated local path.
            if result.is_relative_to(sync.absolute()):
                raise Failure(Code.SETTINGS, field="data_directory")
            check_local_route(sync)
            if result.is_relative_to(sync.resolve()):
                raise Failure(Code.SETTINGS, field="data_directory")
        if os.name == "nt":
            import ctypes

            volume = ctypes.create_unicode_buffer(32768)
            kernel = ctypes.windll.kernel32
            if not kernel.GetVolumePathNameW(str(ancestor), volume, len(volume)):
                raise ctypes.WinError()
            # DRIVE_REMOVABLE and DRIVE_FIXED are local disk volumes.
            if kernel.GetDriveTypeW(volume.value) not in (2, 3):
                raise Failure(Code.SETTINGS, field="data_directory")
        return result
    except (OSError, RuntimeError) as exc:
        raise Failure(Code.SETTINGS, field="data_directory") from exc


def load(root: Path) -> tuple[Settings, Manifest]:
    path = root / "config" / "settings.toml"
    try:
        check_local_route(path)
        manifest = Manifest.model_validate(tomllib.loads(files(__package__).joinpath("release-manifest.toml").read_text("utf-8")))
        values = tomllib.loads(path.read_text("utf-8")) if path.exists() else {}
        return Settings.model_validate(values), manifest
    except ValidationError as exc:
        location = exc.errors(include_input=False)[0]["loc"]
        allowed = Settings.model_fields.keys() | Manifest.model_fields.keys()
        field = str(location[0]) if location and location[0] in allowed else "configuration"
        raise Failure(Code.SETTINGS, field=field) from exc
    except (ValueError, OSError) as exc:
        raise Failure(Code.SETTINGS) from exc


def save(root: Path, settings: Settings) -> None:
    """Replace preferences atomically. Caller publishes the snapshot after success."""
    folder = root / "config"
    temporary: Path | None = None
    try:
        check_local_route(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False) as out:
            temporary = Path(out.name)
            out.write(f'version = 1\nhost = "{settings.host}"\nport = {settings.port}\n')
            out.write(f"context = {settings.context}\noutput = {settings.output}\noffline = true\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, folder / "settings.toml")
    except OSError as exc:
        raise Failure(Code.SETTINGS) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

