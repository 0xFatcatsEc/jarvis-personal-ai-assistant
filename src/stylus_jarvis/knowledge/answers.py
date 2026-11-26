"""Select verbatim answer quotes from already authorized retained passages."""
import re

from .context import EvidenceBundle, Passage, concepts

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def extract_answer(question: str, evidence: EvidenceBundle) -> EvidenceBundle:
    """Select the best matching sentence per passage, retaining its original citations."""
    groups = [frozenset(re.findall(r'"([^"]+)"', group)) for group in concepts(question)]
    if not groups:
        return EvidenceBundle(())

    def score(sentence: str) -> tuple[int, tuple[bool, ...]]:
        words = set(re.findall(r"[^\W_]+", sentence.casefold()))
        matched = tuple(bool(words & group) for group in groups)
        return sum(matched), matched

    quotes = []
    for passage in evidence.passages:
        # The PDF extractor can wrap one sentence across several lines. Keep those line breaks.
        sentences = _SENTENCE_BOUNDARY.split(passage.text.strip())
        sentence = max(sentences, key=score, default="")
        if sentence and score(sentence)[0]:
            quotes.append(Passage(sentence, passage.citations))
    return EvidenceBundle(tuple(quotes))
