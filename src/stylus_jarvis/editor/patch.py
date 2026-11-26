"""Typed text-only patch proposals and connection-scoped review state."""
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from ..contracts.messages import Code, Failure
from .snapshot import Identifier, _Metadata, resolve_document

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
REVIEW_SECONDS = 120


class DocumentBase(_Metadata):
    document_uri: str = Field(min_length=1, max_length=1024)
    document_id: Identifier
    document_version: int = Field(ge=1, le=2**31 - 1)
    sha256: Digest


class PatchTarget(_Metadata):
    base: DocumentBase
    replacement: str = Field(max_length=4096)

    @field_validator("replacement")
    @classmethod
    def unicode_text(cls, text: str) -> str:
        text.encode("utf-8")
        return text


class PatchProposal(_Metadata):
    workspace_uri: str = Field(min_length=1, max_length=1024)
    targets: list[PatchTarget] = Field(min_length=1, max_length=3)

    def paths(self, root: Path) -> tuple[str, ...]:
        paths = tuple(resolve_document(root, self.workspace_uri, target.base.document_uri)
                      for target in self.targets)
        if len(set(paths)) != len(paths):
            raise Failure(Code.CONFLICT)
        return paths


@dataclass(frozen=True, slots=True)
class ReviewedPatch:
    proposal: PatchProposal
    digest: str
    paths: tuple[str, ...]
    expiry: float


class PatchPreview(_Metadata):
    digest: Digest
    proposal: str = Field(min_length=1, max_length=4096)


class PatchApproval(_Metadata):
    digest: Digest
    approved: bool
    observed: list[DocumentBase] = Field(min_length=1, max_length=3)


class PatchRecovery(_Metadata):
    action: Literal["latest", "result", "observe", "acknowledge"]
    workspace_uri: str = Field(min_length=1, max_length=1024)
    operation: Identifier | None = None
    observed: list[DocumentBase] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def check_action(self) -> "PatchRecovery":
        has_operation = "operation" in self.model_fields_set if self.action == "latest" else self.operation is not None
        if has_operation == (self.action == "latest"):
            raise ValueError("Operation identity does not match the recovery action")
        if self.action in ("latest", "acknowledge") and self.observed:
            raise ValueError("This action does not accept observations")
        return self


def verify_digest(serialized: str, digest: str) -> bool:
    try:
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest() == digest
    except UnicodeError:
        return False


def now_ms() -> int:
    return time.time_ns() // 1_000_000
