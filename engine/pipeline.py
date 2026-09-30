"""TrustEngine: the single entry point that runs the whole flow.

    question
      -> sanitise
      -> retrieve candidate sources           (retrieval.py, swappable)
      -> assess each source with rules        (rules.py, deterministic)
      -> split: usable vs excluded (country)  (excluded are SHOWN, not hidden)
      -> LLM reads usable sources + labels    (llm.py, untrusted, validated)
      -> pick expert + compute confidence     (confidence.py, deterministic)
      -> AskResponse

The engine is built once with its dependencies injected. Tests and the API
construct it the same way, and swapping the retriever or the LLM is a
constructor argument, not a code change.
"""

from __future__ import annotations

import re
import unicodedata

from .config import RulesConfig
from .confidence import compute_confidence, select_expert
from .llm import LLMClient, ask_llm
from .loader import KnowledgeBase
from .models import AskResponse, Context, ExcludedSource, RuleStatus
from .retrieval import Retriever
from .rules import assess_source

MAX_QUESTION_CHARS = 500
_WHITESPACE = re.compile(r"\s+")

_VERDICT_ORDER = {RuleStatus.PASS: 0, RuleStatus.WARN: 1, RuleStatus.FAIL: 2}


class InvalidQuestion(ValueError):
    pass


class CompanyNotAllowed(PermissionError):
    """The company is unknown or not in this user's portfolio. Deliberately one error for both,
    so the API cannot be used to discover which company IDs exist."""


def sanitise_question(question: str) -> str:
    """Normalise unicode, drop control/invisible characters, collapse whitespace.

    Invisible characters (zero-width, bidi overrides) are a common trick to
    hide instructions from humans while the LLM still reads them.
    """
    text = unicodedata.normalize("NFKC", question)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t")
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) < 3:
        raise InvalidQuestion("Question is too short")
    if len(text) > MAX_QUESTION_CHARS:
        raise InvalidQuestion("Question is too long")
    return text


class TrustEngine:
    def __init__(
        self,
        kb: KnowledgeBase,
        rules: RulesConfig,
        retriever: Retriever,
        llm: LLMClient,
        context: Context,
    ) -> None:
        self._kb = kb
        self._rules = rules
        self._retriever = retriever
        self._llm = llm
        self._ctx = context

    @property
    def context(self) -> Context:
        return self._ctx

    @property
    def knowledge_base(self) -> KnowledgeBase:
        return self._kb

    def ask(self, question: str, company: str | None = None) -> AskResponse:
        question = sanitise_question(question)
        kb, cfg = self._kb, self._rules
        # Authorization: the company must be in the (server-side) portfolio of the context user.
        if not kb.can_access(self._ctx.user, company):
            raise CompanyNotAllowed()
        ctx = self._ctx.model_copy(update={"company": company})
        client = kb.companies.get(company) if company else None

        # Client isolation: general sources plus the selected client's own sources, nothing else.
        def visible(source) -> bool:
            return source.company is None or source.company == company

        candidates = self._retriever.retrieve(question, k=cfg.retrieval_top_k, visible=visible)
        assessed = [(s, assess_source(s, ctx, kb, cfg)) for s in candidates]

        usable_items = [(s, a) for s, a in assessed if not a.excluded]
        excluded = [
            ExcludedSource(id=a.id, title=a.title, reason=a.exclusion_reason or "Not applicable")
            for _, a in assessed if a.excluded
        ]
        usable = {a.id: a for _, a in usable_items}

        answer = ask_llm(self._llm, question, usable_items, cfg.max_content_chars_per_source,
                         client.name if client else None)
        expert = select_expert(answer, usable, ctx, kb, cfg)
        confidence = compute_confidence(answer, usable, expert, ctx, kb)

        # Display order: cited sources first, then verdict, then retrieval relevance.
        cited = {sid: i for i, sid in enumerate(answer.cited_source_ids)}
        relevance = {sid: i for i, sid in enumerate(usable)}
        ordered = sorted(
            usable.values(),
            key=lambda a: (cited.get(a.id, len(cited)), _VERDICT_ORDER[a.verdict], relevance[a.id]),
        )

        return AskResponse(
            question=question,
            context=ctx,
            answer=answer,
            confidence=confidence,
            ask_expert=expert,
            sources=ordered,
            excluded_sources=excluded,
        )
