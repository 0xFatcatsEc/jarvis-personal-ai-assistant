"""Explicit offline role inventory and proposal validation."""
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from pydantic import ValidationError

from ..contracts.messages import Code, Failure, Scope
from ..contracts.tools import InspectCitation, LocalTool, OpenApprovedProject, ReadSavedCode, RecallFacts, SearchEvidence


class Role(StrEnum):
    CODING = "coding"
    SYSTEM = "system"
    FILES = "files"
    MEMORY = "memory"
    EMAIL = "email"
    RESEARCH = "research"


_TOOLS: Mapping[Role, Mapping[str, type[LocalTool]]] = MappingProxyType({
    Role.CODING: MappingProxyType({"coding.read_saved_code": ReadSavedCode}),
    Role.SYSTEM: MappingProxyType({"system.open_approved_project": OpenApprovedProject}),
    Role.FILES: MappingProxyType({"files.search_evidence": SearchEvidence, "files.inspect_citation": InspectCitation}),
    Role.MEMORY: MappingProxyType({"memory.recall_facts": RecallFacts}),
    Role.EMAIL: MappingProxyType({}),
    Role.RESEARCH: MappingProxyType({}),
})


@dataclass(frozen=True, slots=True)
class ScopedProposal:
    """A validated proposal paired with the scope supplied by the runtime."""

    scope: Scope
    role: Role
    tool: LocalTool


def offline_tools(role: Role) -> Mapping[str, type[LocalTool]]:
    """Available contract types for a selected role."""
    if not isinstance(role, Role):
        raise Failure(Code.INPUT)
    return _TOOLS[role]


def prepare_proposal(scope: Scope, role: Role, payload: object) -> ScopedProposal:
    """Bind a strictly validated request for the next policy stage."""
    if scope.offline is not True:
        raise Failure(Code.OFFLINE)
    tools = offline_tools(role)
    if not tools:
        raise Failure(Code.OFFLINE)
    if type(payload) is not dict or type(payload.get("tool")) is not str:
        raise Failure(Code.INPUT)
    contract = tools.get(payload["tool"])
    if contract is None:
        raise Failure(Code.INPUT)
    try:
        parsed = contract.model_validate(payload)
    except ValidationError:
        raise Failure(Code.INPUT) from None
    return ScopedProposal(scope, role, parsed)
