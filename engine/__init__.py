"""TrustLens engine: explainable confidence for organisational knowledge.

Public API:
    build_engine(settings) -> TrustEngine
    TrustEngine.ask(question) -> AskResponse
"""

from __future__ import annotations

from .config import Settings, load_rules
from .llm import GeminiClient, LLMClient, OfflineClient, OpenAICompatClient
from .loader import load_knowledge_base
from .models import Context
from .pipeline import CompanyNotAllowed, InvalidQuestion, TrustEngine
from .retrieval import KeywordRetriever

__all__ = ["build_engine", "TrustEngine", "InvalidQuestion", "CompanyNotAllowed"]


def build_engine(settings: Settings, llm: LLMClient | None = None) -> TrustEngine:
    rules = load_rules(settings.rules_path)
    kb = load_knowledge_base(settings.data_dir, rules)
    if llm is None:
        # Priority: Gemini API key, then an OpenAI-compatible key (Groq/OpenRouter), then Vertex AI.
        if settings.gemini_api_key:
            llm = GeminiClient(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds)
        elif settings.llm_api_key:
            llm = OpenAICompatClient(settings.llm_api_key, settings.llm_base_url, settings.llm_model,
                                     settings.llm_timeout_seconds)
        elif settings.vertex_project:
            llm = GeminiClient(None, settings.gemini_model, settings.llm_timeout_seconds,
                               settings.vertex_project, settings.vertex_location)
        else:
            llm = OfflineClient()
    context = Context(user=settings.demo_user, country=settings.demo_country, as_of_date=settings.as_of_date)
    return TrustEngine(kb=kb, rules=rules, retriever=KeywordRetriever(kb.sources.values()), llm=llm, context=context)
