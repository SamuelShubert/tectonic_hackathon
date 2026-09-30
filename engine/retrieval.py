"""Retrieval: find the sources relevant to a question.

Swappable by design. The pipeline only depends on the Retriever protocol,
so embeddings (or SD Worx's own enterprise search) can replace
KeywordRetriever without touching anything else.

KeywordRetriever scores sources by the rare words they share with the
question (IDF weighting). "Brouwerij" appears in 3 sources and counts a
lot; "pay" appears everywhere and counts little. At ~20 sources this is
fast, deterministic and good enough.

Country filtering is deliberately NOT done here: sources for the wrong
country are retrieved and then shown as excluded, with the reason. Visible
filtering is explainable; silent filtering is a black box.

Client isolation IS done here (the `visible` predicate): another client's
sources are confidential, so they are never candidates, never sent to the
LLM and never shown. That is an access rule, not a relevance judgement.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Callable, Iterable, Protocol

from .models import Source

_TOKEN = re.compile(r"[a-z0-9€%]+")
_STOPWORDS = frozenset(
    "a an and are as at be but by do does for from get has have how i in is it its "
    "me my of on or our so that the their them then there this to up was we what "
    "when where which who why will with you your".split()
)
MAX_QUESTION_TOKENS = 64


def tokenize(text: str) -> list[str]:
    tokens = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in _STOPWORDS or len(tok) < 2:
            continue
        # Minimal stemming: "payments" -> "payment", "days" -> "day".
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        tokens.append(tok)
    return tokens


class Retriever(Protocol):
    def retrieve(self, question: str, k: int,
                 visible: Callable[[Source], bool] | None = None) -> list[Source]: ...


class KeywordRetriever:
    def __init__(self, sources: Iterable[Source]) -> None:
        self._sources = list(sources)
        self._tokens = {s.id: set(tokenize(f"{s.title} {s.content}")) for s in self._sources}
        doc_freq = Counter(tok for toks in self._tokens.values() for tok in toks)
        n = len(self._sources)
        self._idf = {tok: math.log((n + 1) / (df + 0.5)) for tok, df in doc_freq.items()}

    def retrieve(self, question: str, k: int,
                 visible: Callable[[Source], bool] | None = None) -> list[Source]:
        # Cap query tokens: bounds CPU per request regardless of input.
        query = set(tokenize(question)[:MAX_QUESTION_TOKENS])
        if not query:
            return []
        scored = []
        for source in self._sources:
            if visible is not None and not visible(source):
                continue
            overlap = query & self._tokens[source.id]
            if overlap:
                score = sum(self._idf.get(tok, 0.0) for tok in overlap)
                scored.append((score, source.id, source))
        # Sort by score, then ID, so equal scores give a stable, reproducible order.
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [source for _, _, source in scored[:k]]
