"""TrustLens engine: explainable confidence for organisational knowledge.

Public API:
    build_engine(settings) -> TrustEngine
    TrustEngine.ask(question) -> AskResponse
"""

from __future__ import annotations

from .config import Settings, load_rules
from .llm import GeminiClient, LLMClient, OfflineClient
from .loader import load_knowledge_base
from .models import Context
from .pipeline import InvalidQuestion, TrustEngine
from .retrieval import KeywordRetriever

__all__ = ["build_engine", "TrustEngine", "InvalidQuestion"]


def build_engine(settings: Settings, llm: LLMClient | None = None) -> TrustEngine:
    rules = load_rules(settings.rules_path)
    kb = load_knowledge_base(settings.data_dir, rules)
    if llm is None:
        llm = (
            GeminiClient(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds)
            if settings.llm_enabled
            else OfflineClient()
        )
    context = Context(user=settings.demo_user, country=settings.demo_country, as_of_date=settings.as_of_date)
    return TrustEngine(kb=kb, rules=rules, retriever=KeywordRetriever(kb.sources.values()), llm=llm, context=context)
