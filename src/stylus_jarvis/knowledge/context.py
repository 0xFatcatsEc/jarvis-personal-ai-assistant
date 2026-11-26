"""Bounded, extractive evidence for citation consumers."""
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Citation:
    source: str
    revision: str
    locator: str
    relative_path: str
    page: int | None
    start: int | None
    end: int | None


@dataclass(frozen=True, slots=True)
class Passage:
    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    passages: tuple[Passage, ...]

    @property
    def status(self) -> str:
        return "evidence" if self.passages else "insufficient_evidence"

    def payload(self) -> str:
        """Canonical evidence array. Its UTF-8 size includes all citation metadata."""
        return json.dumps([asdict(p) for p in self.passages], ensure_ascii=False, separators=(",", ":"))


_STOP = frozenset("a an the at in on for of to if out this that our is are be can do does did "
                  "what which who when where how long someone while tries happens holds keep use".split())

# Small explicit equivalence classes keep the query inspectable and offline.
_FORMS = (("database", "databases", "sqlite", "postgresql", "mysql", "mariadb"),
          ("own", "owns", "owner", "owners"), ("start", "starts", "started"),
          ("close", "closes", "closing"), ("checkout", "checkouts"))


def concepts(question: str) -> list[str]:
    words = re.findall(r"[^\W_]+", re.sub(r"\bcheck\s+out\b", "checkout", question.casefold()))
    groups = []
    for word in words:
        if word in _STOP:
            continue
        forms = next((g for g in _FORMS if word in g), (word,))
        # Engine names are precise terms when explicitly requested.
        if forms == _FORMS[0] and word not in ("database", "databases"):
            forms = (word,)
        phrase = " OR ".join(f'"{form}"' for form in forms)
        if phrase not in groups:
            groups.append(phrase)
    return groups


def combine(left: Passage, right: Passage) -> Passage | None:
    """Coalesce exact copies or coordinate-verified overlapping text in one revision."""
    citations = tuple(dict.fromkeys((*left.citations, *right.citations)))
    if left.text == right.text:
        return Passage(left.text, citations)
    # A multi-origin copy has no single absolute span for an extended quote.
    origins = {(c.source, c.revision) for c in citations}
    if len(origins) != 1 or any(c.start is None for c in citations):
        return None
    a = min(c.start for c in left.citations if c.start is not None)
    b = min(c.start for c in right.citations if c.start is not None)
    if b < a:
        return combine(right, left)
    offset = b - a
    overlap = min(len(left.text) - offset, len(right.text))
    if overlap <= 0 or left.text[offset:offset + overlap] != right.text[:overlap]:
        return None
    # Identical quotes grouped at different positions cannot establish an extended span.
    for passage, start in ((left, a), (right, b)):
        if max(c.end for c in passage.citations if c.end is not None) != start + len(passage.text):
            return None
    return Passage(left.text + right.text[overlap:], citations)


def assemble(candidates: Iterable[Passage], max_bytes: int, max_passages: int) -> EvidenceBundle:
    passages: list[Passage] = []
    for proposal in candidates:
        if len(proposal.text) > max_bytes:
            continue
        remaining = list(enumerate(passages))
        position = len(passages)
        # Extending a range can connect two previously disjoint ranges.
        while True:
            for index, (rank, existing) in enumerate(remaining):
                merged = combine(existing, proposal)
                if merged is not None:
                    proposal = merged
                    position = min(position, rank)
                    remaining.pop(index)
                    break
            else:
                break
        if len(remaining) >= max_passages:
            continue
        remaining.append((position, proposal))
        updated = EvidenceBundle(tuple(p for _, p in sorted(remaining, key=lambda item: item[0])))
        if len(updated.payload().encode("utf-8")) <= max_bytes:
            passages = list(updated.passages)
    return EvidenceBundle(tuple(passages))
