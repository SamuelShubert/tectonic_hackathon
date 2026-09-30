"""Shared fixtures.

The LLM is replaced by ScriptedLLM, which returns fixed JSON. This tests
everything the CODE decides (retrieval, rules, validation, confidence,
routing) deterministically, without network calls or API costs.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from engine.config import load_rules
from engine.loader import load_knowledge_base
from engine.models import Context
from engine.pipeline import TrustEngine
from engine.retrieval import KeywordRetriever

ROOT = Path(__file__).resolve().parent.parent


class ScriptedLLM:
    def __init__(self, response: dict | str | Exception) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response if isinstance(self.response, str) else json.dumps(self.response)


@pytest.fixture(scope="session")
def rules():
    return load_rules(ROOT / "config" / "rules.yaml")


@pytest.fixture(scope="session")
def kb(rules):
    return load_knowledge_base(ROOT / "data", rules)


@pytest.fixture(scope="session")
def ctx():
    return Context(user="arne.goossens", country="BE", as_of_date=date(2026, 9, 30))


@pytest.fixture
def make_engine(kb, rules, ctx):
    def _make(llm) -> TrustEngine:
        return TrustEngine(kb=kb, rules=rules, retriever=KeywordRetriever(kb.sources.values()), llm=llm, context=ctx)
    return _make
