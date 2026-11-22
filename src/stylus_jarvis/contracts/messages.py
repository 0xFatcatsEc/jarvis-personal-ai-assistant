"""Shared, transport-independent records and safe user-facing failures."""
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4


class Code(StrEnum):
    SETTINGS = "settings"
    SCHEMA = "schema"
    STORE = "store"
    BUSY = "busy"
    SCOPE = "scope"
    INPUT = "input"
    CONFLICT = "conflict"
    MODEL = "model_unavailable"
    DIGEST = "model_digest"
    STREAM = "invalid_stream"
    INTERNAL = "internal"


ACTIONS = {
    Code.SETTINGS: "Check the local configuration and release manifest, then retry.",
    Code.SCHEMA: "Open with the matching application build or restore a verified snapshot.",
    Code.STORE: "Check local disk access and space, then retry the save.",
    Code.BUSY: "Wait for the current operation to finish.",
    Code.SCOPE: "Select an available project and conversation again.",
    Code.INPUT: "Shorten or correct the message and try again.",
    Code.CONFLICT: "Refresh the conversation before submitting a new request.",
    Code.MODEL: "Start local Ollama and provision the pinned Qwen model, then recheck.",
    Code.DIGEST: "Provision the model revision specified in the release manifest.",
    Code.STREAM: "The local stream ended incorrectly. Review the partial answer before retrying.",
    Code.INTERNAL: "Reopen the conversation and check its saved state.",
}


class Failure(Exception):
    def __init__(self, code: Code, *, field: str = "") -> None:
        self.code = code
        self.reference = uuid4()
        self.field = field
        super().__init__(ACTIONS[code] + (f" Field: {field}." if field else ""))


class State(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class Scope:
    owner: str
    project: str
    conversation: str
    grant: int
    generation: int
    offline: bool = True


@dataclass(frozen=True, slots=True)
class Turn:
    key: str
    question: str
    answer: str
    state: State


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    scope: Scope
    request: UUID
    kind: str
    text: str

