"""Bounded editor metadata and canonical local workspace identity."""
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote_to_bytes, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ..contracts.messages import Code, Failure, Scope
from ..knowledge.ingestion import approved_stream
from .launch import canonical_directory

Identifier = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
Coordinate = Annotated[int, Field(ge=0, le=2**31 - 1)]


class _Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Binding(_Metadata):
    project: Identifier
    conversation: Identifier
    generation: Coordinate
    grant: Coordinate

    @classmethod
    def from_scope(cls, scope: Scope) -> "Binding":
        return cls(project=scope.project, conversation=scope.conversation,
                   generation=scope.generation, grant=scope.grant)


class Position(_Metadata):
    line: Coordinate
    character: Coordinate


class Selection(_Metadata):
    anchor: Position
    active: Position


class Diagnostic(_Metadata):
    start: Position
    end: Position
    severity: int = Field(ge=0, le=3)
    message: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def ordered(self) -> "Diagnostic":
        if (self.start.line, self.start.character) > (self.end.line, self.end.character):
            raise ValueError("Diagnostic range is reversed")
        return self


class Snapshot(_Metadata):
    workspace_uri: str = Field(min_length=1, max_length=1024)
    document_uri: str = Field(min_length=1, max_length=1024)
    document_id: Identifier
    document_version: int = Field(ge=1, le=2**31 - 1)
    dirty: bool
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: Selection
    diagnostics: list[Diagnostic] = Field(max_length=4)


def local_file_uri(uri: str) -> Path:
    try:
        if any(ord(character) < 32 for character in uri) or re.search(r"%(?![0-9a-fA-F]{2})", uri):
            raise ValueError
        parsed = urlsplit(uri)
        if parsed.scheme != "file" or parsed.netloc or "?" in uri or "#" in uri or not uri.startswith("file:///"):
            raise ValueError
        decoded = unquote_to_bytes(parsed.path).decode("utf-8")
        if not re.match(r"^/[a-zA-Z]:/", decoded) or "\\" in decoded:
            raise ValueError
        tail = decoded[4:].removesuffix("/")
        parts = tail.split("/") if tail else []
        if any(not part or part in (".", "..") or part.endswith((".", " "))
               or any(ord(character) < 32 or character in ':<>|"*?' for character in part)
               or Path(part).is_reserved() for part in parts):
            raise ValueError
        return Path(decoded[1:])
    except (ValueError, UnicodeError) as error:
        raise Failure(Code.SCOPE) from error


def resolve_snapshot(root: Path, snapshot: Snapshot) -> str:
    return resolve_document(root, snapshot.workspace_uri, snapshot.document_uri)


def resolve_document(root: Path, workspace_uri: str, document_uri: str) -> str:
    if canonical_directory(root).parts != root.parts:
        raise Failure(Code.SCOPE)
    if canonical_directory(local_file_uri(workspace_uri)).parts != root.parts:
        raise Failure(Code.SCOPE)
    with approved_stream(root, local_file_uri(document_uri)) as (relative, _, _size):
        return relative


class BufferHistory:
    """Bound version state to the open document and its canonical file."""
    def __init__(self) -> None:
        self.active: dict[str, tuple[str, int, str]] = {}
        self.identities: dict[str, str] = {}

    def accept(self, path: str, snapshot: Snapshot) -> None:
        self.accept_identity(path, snapshot.document_id, snapshot.document_version, snapshot.sha256)

    def accept_identity(self, path: str, identity: str, version: int, digest: str) -> None:
        previous = self.active.get(path)
        if identity in self.identities:
            if self.identities[identity] != path or previous is None or previous[0] != identity:
                raise Failure(Code.CONFLICT)
            if version < previous[1] or (version == previous[1] and digest != previous[2]):
                raise Failure(Code.CONFLICT)
        elif len(self.identities) >= 256:
            raise Failure(Code.BUSY)
        self.identities[identity] = path
        self.active[path] = identity, version, digest

    def copy(self) -> "BufferHistory":
        result = BufferHistory()
        result.active = self.active.copy()
        result.identities = self.identities.copy()
        return result
