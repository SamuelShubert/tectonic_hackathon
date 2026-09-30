"""Retrieval (build plan section 6). OWNER: teammate (P3).

BASELINE so the API runs end to end. Replace freely, but keep the signature:
    retrieve(question: str, sources: list[dict], k: int = 6) -> list[dict]
Country filtering happens AFTER retrieval (in rules), so excluded sources stay visible.
"""
import re

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "be", "do", "does", "did", "i", "we", "you",
    "for", "of", "to", "in", "on", "at", "and", "or", "what", "when", "how", "who",
    "which", "can", "my", "our", "this", "that", "it", "with", "about", "long", "much",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9%]+", text.lower()) if t not in STOPWORDS and len(t) > 1}


def retrieve(question: str, sources: list[dict], k: int = 6) -> list[dict]:
    q = _tokens(question)
    if not q:
        return []
    scored = []
    for src in sources:
        title = _tokens(src.get("title") or "")
        body = _tokens(src.get("content") or "")
        score = 2 * len(q & title) + len(q & body)
        if score > 0:
            scored.append((score, src["id"], src))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [src for _, _, src in scored[:k]]
