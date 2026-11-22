"""Immutable local configuration. No environment-controlled model destination."""
import ipaddress
import os
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
    result = (Path(raw) / "StylusJarvis").resolve()
    synced = [Path(v).resolve() for k, v in os.environ.items() if k.lower().startswith("onedrive") and v]
    if str(result).startswith("\\\\") or any(result.is_relative_to(root) for root in synced):
        raise Failure(Code.SETTINGS, field="data_directory")
    return result


def load(root: Path) -> tuple[Settings, Manifest]:
    path = root / "config" / "settings.toml"
    try:
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

