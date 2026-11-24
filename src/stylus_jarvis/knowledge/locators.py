"""Version-one extraction coordinates and retained evidence."""
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader, __version__

from ..contracts.messages import Code, Failure
from .ingestion import SourceRevision, approved_stream


@dataclass(frozen=True, slots=True)
class Locator:
    id: str
    revision: str
    extractor: str
    page: int | None
    start: int | None
    end: int | None
    excerpt: str
    ocr_needed: bool


MAX_BYTES = 16 * 1024 * 1024
MAX_CHARACTERS = 2_000_000


def extract(root: Path, revision: SourceRevision, checkpoint: Callable[[], None] | None = None) -> list[Locator]:
    if checkpoint is not None:
        checkpoint()
    with approved_stream(root, root / revision.relative_path) as (relative, stream, size):
        if size > MAX_BYTES:
            raise Failure(Code.INPUT)
        data = stream.read(MAX_BYTES + 1)
    if relative != revision.relative_path or hashlib.sha256(data).hexdigest() != revision.sha256:
        raise Failure(Code.CONFLICT)
    if Path(relative).suffix.lower() == ".pdf":
        records = []
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted or not 0 < len(reader.pages) <= 2000:
                raise Failure(Code.INPUT)
            total = 0
            for number, page in enumerate(reader.pages, 1):
                if checkpoint is not None:
                    checkpoint()
                text = page.extract_text()
                total += len(text)
                if total > MAX_CHARACTERS:
                    raise Failure(Code.INPUT)
                records.append(Locator(uuid4().hex, revision.revision_id, f"page-v1/pypdf-{__version__}",
                                       number, None, None, text, not text.strip()))
        except Failure:
            raise
        except Exception as exc:
            raise Failure(Code.INPUT) from exc
        return records
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Failure(Code.INPUT) from exc
    if "\x00" in text or len(text) > MAX_CHARACTERS:
        raise Failure(Code.INPUT)
    return [Locator(uuid4().hex, revision.revision_id, "utf8-v1", None, start,
                    min(start + 1024, len(text)), text[start:start + 1024], False)
            for start in range(0, max(1, len(text)), 1024)]
