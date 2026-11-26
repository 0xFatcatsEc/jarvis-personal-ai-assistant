"""Editor v1 framing and strict validation."""
import json
import re
from dataclasses import dataclass
from struct import Struct
from typing import Literal
from pydantic import ValidationError

from .patch import PatchApproval, PatchPreview, PatchRecovery
from .snapshot import Binding, Snapshot


HEADER = Struct("<I")
MAX_FRAME = 4096
VERSION = 1
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
SESSION = re.compile(r"[0-9a-f]{32}", re.ASCII)


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Request:
    request_id: int
    operation: Literal["pair", "ping", "snapshot", "preview_patch", "authorize_patch", "recover_patch"]
    credential: str
    deadline_ms: int
    window: str | None = None
    binding: Binding | None = None
    snapshot: Snapshot | None = None
    patches: bool = False
    patch: PatchPreview | PatchApproval | PatchRecovery | None = None


def _unique(fields: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in fields:
        if key in result:
            raise ProtocolError("Duplicate JSON field")
        result[key] = value
    return result


def decode_object(payload: str) -> object:
    return json.loads(payload, object_pairs_hook=_unique)


def decode_request(payload: bytes, now_ms: int) -> Request:
    if not 0 < len(payload) <= MAX_FRAME:
        raise ProtocolError("Invalid frame size")
    try:
        data = decode_object(payload.decode("utf-8"))
    except (ValueError, RecursionError) as error:
        raise ProtocolError("Invalid JSON") from error
    if not isinstance(data, dict):
        raise ProtocolError("Expected an object")
    request_id, deadline = data.get("request_id"), data.get("deadline_ms")
    if type(request_id) is not int or not 1 <= request_id <= 2**31 - 1:
        raise ProtocolError("Invalid request ID")
    if type(deadline) is not int or not now_ms < deadline <= now_ms + 5000:
        raise ProtocolError("Invalid request deadline")
    common = {"operation", "request_id", "deadline_ms"}
    operation = data.get("operation")
    pairing = common | {"versions", "invitation"}
    if operation == "pair" and data.keys() in (pairing, pairing | {"window"}, pairing | {"window", "patches"}):
        versions, invitation = data["versions"], data["invitation"]
        window = data.get("window")
        if (isinstance(versions, list) and 1 <= len(versions) <= 8
                and all(type(version) is int and 1 <= version <= 255 for version in versions)
                and VERSION in versions and isinstance(invitation, str) and TOKEN.fullmatch(invitation)
                and ("window" not in data or isinstance(window, str) and SESSION.fullmatch(window))
                and ("patches" not in data or data["patches"] is True)):
            return Request(request_id, "pair", invitation, deadline, window, patches=data.get("patches", False))
    version, session = data.get("version"), data.get("session")
    if type(version) is int and version == VERSION and isinstance(session, str) and SESSION.fullmatch(session):
        authenticated = common | {"version", "session"}
        if operation == "ping" and data.keys() == authenticated:
            return Request(request_id, "ping", session, deadline)
        payload_key = {"snapshot": "snapshot", "preview_patch": "patch", "authorize_patch": "patch",
                       "recover_patch": "patch"}.get(
            operation if isinstance(operation, str) else "")
        if payload_key and data.keys() == authenticated | {"window", "binding", payload_key}:
            window = data["window"]
            if isinstance(window, str) and SESSION.fullmatch(window):
                try:
                    binding = Binding.model_validate(data["binding"])
                    if operation == "snapshot":
                        return Request(request_id, "snapshot", session, deadline, window, binding,
                                       Snapshot.model_validate(data["snapshot"]))
                    if operation == "preview_patch":
                        return Request(request_id, "preview_patch", session, deadline, window, binding,
                                       patch=PatchPreview.model_validate(data["patch"]))
                    if operation == "recover_patch":
                        return Request(request_id, "recover_patch", session, deadline, window, binding,
                                       patch=PatchRecovery.model_validate(data["patch"]))
                    return Request(request_id, "authorize_patch", session, deadline, window, binding,
                                   patch=PatchApproval.model_validate(data["patch"]))
                except ValidationError as error:
                    raise ProtocolError("Invalid editor metadata") from error
    raise ProtocolError("Unsupported editor request")


def encode_frame(data: dict[str, object]) -> bytes:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    if not 0 < len(payload) <= MAX_FRAME:
        raise ProtocolError("Invalid frame size")
    return HEADER.pack(len(payload)) + payload
