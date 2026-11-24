"""Immutable capture requests and version-addressable fact receipts."""
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from ..contracts.messages import Code, Failure, Scope


class Destination(StrEnum):
    PROJECT = "project"
    PERSONAL = "personal"


class Origin(StrEnum):
    USER = "user"
    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class FactDraft:
    scope: Scope
    text: str
    destination: Destination = Destination.PROJECT
    origin: Origin = Origin.USER
    locator: str | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if (not isinstance(self.destination, Destination) or not isinstance(self.origin, Origin)
                or not self.text.strip() or len(self.text) > 8192 or "\x00" in self.text):
            raise Failure(Code.INPUT)
        if self.destination == Destination.PERSONAL and self.locator is not None:
            raise Failure(Code.SCOPE)


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    version: int
    owner: str
    project: str | None
    text: str
    origin: Origin
    locator: str | None
    source: str | None
    revision: str | None
