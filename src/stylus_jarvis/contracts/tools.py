"""Version-one local tool proposals. Runtime authority travels separately."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

TOOL_CONTRACT_VERSION = 1

RecordId = Annotated[str, StringConstraints(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")]


class ToolProposal(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class ReadSavedCode(ToolProposal):
    tool: Literal["coding.read_saved_code"]
    source: RecordId
    revision: RecordId
    max_bytes: int = Field(default=8192, ge=2, le=65536)


class OpenApprovedProject(ToolProposal):
    tool: Literal["system.open_approved_project"]
    # The broker obtains both the root and executable from trusted application state.


class SearchEvidence(ToolProposal):
    tool: Literal["files.search_evidence"]
    query: str = Field(min_length=1, max_length=512)
    revision: RecordId | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, query: str) -> str:
        if not query.strip() or "\x00" in query:
            raise ValueError("Search query must contain text and have no NUL characters")
        return query


class InspectCitation(ToolProposal):
    tool: Literal["files.inspect_citation"]
    source: RecordId
    revision: RecordId
    locator: RecordId


class RecallFacts(ToolProposal):
    tool: Literal["memory.recall_facts"]
    destination: Literal["project", "personal"]


LocalTool = ReadSavedCode | OpenApprovedProject | SearchEvidence | InspectCitation | RecallFacts
ToolOutcome = Literal["succeeded", "denied", "failed", "cancelled"]
