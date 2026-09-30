"""Acceptance tests: the build plan's section 7 table, as code.

The scripted LLM returns what a well-behaved model should say. The test then
checks that the DETERMINISTIC layer turns that into the expected confidence,
expert and exclusions.
"""

from __future__ import annotations

from engine.models import ConfidenceLevel, RuleStatus
from engine.rules import assess_source
from tests.conftest import ScriptedLLM


def test_q1_superseded_conflict_resolved_is_high(make_engine):
    llm = ScriptedLLM({
        "answer": "Belgian double holiday pay is 92% of gross monthly salary, paid in May or June.",
        "answer_status": "answered", "winning_source_id": "DOC-001",
        "cited_source_ids": ["DOC-001", "E1"],
        "conflicts": [{"source_ids": ["DOC-001", "DOC-002", "T4"], "summary": "v2 and a chat say 85%",
                       "resolved": True, "resolution": "DOC-001 (v3) replaces DOC-002"}],
        "exceptions": [],
    })
    r = make_engine(llm).ask("What is the Belgian double holiday pay percentage and when is it paid?")
    assert r.confidence.level == ConfidenceLevel.HIGH
    assert r.ask_expert.id == "sofie.maes"
    doc2 = next(s for s in r.sources if s.id == "DOC-002")
    assert doc2.verdict == RuleStatus.FAIL


def test_q2_exception_in_informal_sources_with_leaving_owner_is_medium(make_engine):
    llm = ScriptedLLM({
        "answer": "For Brouwerij Van de Leie, double holiday pay is advanced to April.",
        "answer_status": "answered", "winning_source_id": "E2",
        "cited_source_ids": ["E2", "DOC-010", "DOC-001"],
        "conflicts": [],
        "exceptions": [{"source_ids": ["E2", "DOC-010"], "summary": "Company agreement advances payment to April"}],
    })
    r = make_engine(llm).ask("When do I pay double holiday pay for Brouwerij Van de Leie?",
                             company="brouwerij-van-de-leie")
    assert r.confidence.level == ConfidenceLevel.MEDIUM
    text = " ".join(r.confidence.reasons)
    assert "informal sources" in text
    assert "Jens Wouters leaves on 2026-10-15" in text
    assert "Capture this knowledge" in r.confidence.action
    # Jens (leaving) owns the cited DOC-010: ask him first, then the BE payroll expert.
    assert r.ask_expert.id == "jens.wouters"
    assert "15 Oct" in r.ask_expert.why and "Sofie Maes" in r.ask_expert.why


def test_q3_unresolved_conflict_is_low(make_engine):
    llm = ScriptedLLM({
        "answer": "Unclear: the procedure says December payroll, a recent chat says a separate run on 20 December.",
        "answer_status": "uncertain", "winning_source_id": None,
        "cited_source_ids": ["DOC-003", "T1"],
        "conflicts": [{"source_ids": ["DOC-003", "T1"], "summary": "December payroll vs separate run on 20 Dec",
                       "resolved": False, "resolution": ""}],
        "exceptions": [],
    })
    r = make_engine(llm).ask("When is the end-of-year premium paid for PC 200 clients this year?")
    assert r.confidence.level == ConfidenceLevel.LOW
    assert r.ask_expert.id == "sofie.maes"  # owner of DOC-003, the most authoritative cited source
    assert "Don't act yet" in r.confidence.action


def test_q4_copy_with_warnings_does_not_win(make_engine):
    llm = ScriptedLLM({
        "answer": "The December payroll cutoff is 15 December.", "answer_status": "answered",
        "winning_source_id": "DOC-007", "cited_source_ids": ["DOC-007"],
        "conflicts": [{"source_ids": ["DOC-007", "DOC-008"], "summary": "Copy says 18 December", "resolved": True,
                       "resolution": "DOC-007 is current and owned; DOC-008 is an ownerless outdated copy"}],
        "exceptions": [],
    })
    r = make_engine(llm).ask("What is the December payroll cutoff in Belgium?")
    assert r.confidence.level == ConfidenceLevel.HIGH
    doc8 = next(s for s in r.sources if s.id == "DOC-008")
    assert doc8.verdict == RuleStatus.WARN


def test_q5_wrong_country_is_excluded_and_never_sent_to_llm(make_engine):
    llm = ScriptedLLM({
        "answer": "A Belgian employee gets 100% guaranteed salary for the first 30 days.",
        "answer_status": "answered", "winning_source_id": "DOC-006",
        "cited_source_ids": ["DOC-006"], "conflicts": [], "exceptions": [],
    })
    r = make_engine(llm).ask("How long does a Belgian employee get 100% sick pay?")
    assert r.confidence.level == ConfidenceLevel.HIGH
    excluded = {e.id: e.reason for e in r.excluded_sources}
    assert "DOC-005" in excluded and "DE" in excluded["DOC-005"]
    assert 'id="DOC-005"' not in llm.prompts[0]


def test_llm_picking_superseded_source_is_overruled(make_engine):
    """The LLM cannot talk its way to High by choosing a replaced document."""
    llm = ScriptedLLM({
        "answer": "It is 85%.", "answer_status": "answered", "winning_source_id": "DOC-002",
        "cited_source_ids": ["DOC-002"], "conflicts": [], "exceptions": [],
    })
    r = make_engine(llm).ask("What is the Belgian double holiday pay percentage?")
    assert r.confidence.level == ConfidenceLevel.LOW
    assert any("Replaced by DOC-001" in reason for reason in r.confidence.reasons)


def test_rules_are_deterministic_and_labelled(kb, rules, ctx):
    doc2 = assess_source(kb.sources["DOC-002"], ctx, kb, rules)
    labels = " | ".join(r.label for r in doc2.rules)
    assert "Replaced by DOC-001" in labels
    assert "Pieter Claes has left" in labels
    assert "Status unknown" in labels
    assert doc2 == assess_source(kb.sources["DOC-002"], ctx, kb, rules)  # same input, same output


def test_offline_routing_follows_relevance_not_authority(make_engine):
    """Regression: with no LLM answer, a sick-pay question must route to the sick-pay owner."""
    r = make_engine(ScriptedLLM(RuntimeError("offline"))).ask("How long does a Belgian employee get 100% sick pay?")
    assert r.ask_expert.id == "hanne.peeters"
    assert r.sources[0].id == "DOC-006"
