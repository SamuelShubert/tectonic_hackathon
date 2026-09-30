"""Deterministic confidence and expert routing: the code decides.

Inputs: the rule assessments (Layer 1) and the validated LLM findings
(Layer 2). Output: High / Medium / Low, the exact reasons, one action, and
the person to ask.

Every reason string points to a concrete rule label or LLM finding, so
"why Medium?" always has a traceable answer. The LLM cannot talk its way
to "High": if it picks a superseded source as the winner, the rules fail
that source and confidence drops to Low.
"""

from __future__ import annotations

from .config import RulesConfig
from .loader import KnowledgeBase
from .models import (
    Confidence,
    ConfidenceLevel,
    Context,
    ExpertRef,
    LLMAnswer,
    OwnerStatus,
    RuleStatus,
    SourceAssessment,
    SourceType,
)

_INFORMAL = {SourceType.EMAIL, SourceType.CHAT, SourceType.CLIENT_NOTE}

_OWNER_PROBLEM = {
    OwnerStatus.MISSING: "has no owner",
    OwnerStatus.LEFT: "is owned by someone who has left",
    OwnerStatus.LEAVING: "is owned by someone who is leaving",
    OwnerStatus.EXTERNAL: "comes from an external sender",
    OwnerStatus.UNLISTED: "was written by someone outside the expert directory",
}


def _anchor_source(
    answer: LLMAnswer, usable: dict[str, SourceAssessment], cfg: RulesConfig
) -> SourceAssessment | None:
    """The source the decision hinges on.

    1. The LLM's winning source, if valid.
    2. Else the most authoritative non-failing source the LLM cited.
    3. Else (no LLM answer) the most RELEVANT non-failing source. `usable`
       is in retrieval order, so relevance beats authority here: a sick-pay
       question must not be routed via the holiday-pay policy owner.
    """
    if answer.winning_source_id in usable:
        return usable[answer.winning_source_id]
    cited = [usable[i] for i in answer.cited_source_ids if i in usable]
    if cited:
        return min(cited, key=lambda a: (a.verdict == RuleStatus.FAIL, cfg.authority_rank(a.source_type), a.id))
    non_failing = [a for a in usable.values() if a.verdict != RuleStatus.FAIL]
    return (non_failing or list(usable.values()) or [None])[0]


def select_expert(
    answer: LLMAnswer,
    usable: dict[str, SourceAssessment],
    ctx: Context,
    kb: KnowledgeBase,
    cfg: RulesConfig,
) -> ExpertRef | None:
    anchor = _anchor_source(answer, usable, cfg)
    if anchor and anchor.owner_status == OwnerStatus.ACTIVE and anchor.owner in kb.experts:
        expert = kb.experts[anchor.owner]
        return ExpertRef(id=expert.id, name=expert.name, role=expert.role,
                         why=f"Owns {anchor.id} ({anchor.title})")

    # Fallback: an active expert covering this country, by configured role priority.
    candidates = [
        e for e in kb.experts.values()
        if e.status == "active" and not e.leaving_date and ctx.country in e.countries
    ]

    def priority(expert) -> tuple[int, str]:
        for rank, keyword in enumerate(cfg.escalation_role_priority):
            if keyword.lower() in expert.role.lower():
                return rank, expert.id
        return len(cfg.escalation_role_priority), expert.id

    if not candidates:
        return None
    expert = min(candidates, key=priority)
    if anchor:
        problem = _OWNER_PROBLEM.get(anchor.owner_status, "cannot be verified by its owner")
        why = f"{anchor.id} {problem}; {expert.name} covers {ctx.country}"
    else:
        why = f"No usable source; {expert.name} covers {ctx.country}"
    return ExpertRef(id=expert.id, name=expert.name, role=expert.role, why=why)


def compute_confidence(
    answer: LLMAnswer,
    usable: dict[str, SourceAssessment],
    expert: ExpertRef | None,
    ctx: Context,
    kb: KnowledgeBase,
) -> Confidence:
    """Rules evaluated in order; the first level with reasons wins."""
    winner = usable.get(answer.winning_source_id or "")
    cited = [usable[i] for i in answer.cited_source_ids if i in usable]
    ask = f"ask {expert.name}" if expert else "ask your team lead"

    # ---- LOW -------------------------------------------------------------
    low: list[str] = []
    if not usable:
        low.append("No usable source found for your country")
    if answer.answer_status == "no_answer":
        low.append("No answer could be produced from trusted sources")
    if answer.answer_status == "uncertain":
        low.append("The sources do not agree clearly enough to answer")
    for c in answer.conflicts:
        if not c.resolved:
            low.append(f"Unresolved conflict between {', '.join(c.source_ids)}: {c.summary}")
    if answer.answer_status == "answered" and winner is None:
        low.append("The answer is not anchored to a verifiable source")
    if winner and winner.verdict == RuleStatus.FAIL:
        low.append(f"Best source {winner.id} failed checks: {'; '.join(winner.labels(RuleStatus.FAIL))}")
    if low:
        return Confidence(level=ConfidenceLevel.LOW, reasons=tuple(dict.fromkeys(low)),
                          action=f"Don't act yet: {ask}.")

    # ---- MEDIUM ----------------------------------------------------------
    medium: list[str] = []
    actions = ["Verify before acting."]
    if winner and winner.verdict == RuleStatus.WARN:
        medium.append(f"Best source {winner.id} has warnings: {'; '.join(winner.labels(RuleStatus.WARN))}")
    for e in answer.exceptions:
        types = {usable[i].source_type for i in e.source_ids if i in usable}
        if types and types <= _INFORMAL:
            medium.append(f"Exception found only in informal sources ({', '.join(e.source_ids)}): {e.summary}")
            actions.append("Add this exception to the official client file.")
    leaving = {a.owner for a in ([winner] if winner else []) + cited
               if a.has_rule("handover_risk", RuleStatus.WARN) and a.owner}
    for owner_id in sorted(leaving):
        exp = kb.experts[owner_id]
        medium.append(f"Knowledge holder {exp.name} leaves on {exp.leaving_date}")
        actions.append(f"Capture this knowledge before {exp.name} leaves on {exp.leaving_date}.")
    if medium:
        return Confidence(level=ConfidenceLevel.MEDIUM, reasons=tuple(dict.fromkeys(medium)),
                          action=" ".join(dict.fromkeys(actions)))

    # ---- HIGH ------------------------------------------------------------
    high = [f"Best source {winner.id} passed all checks"] if winner else []
    high += [f"Conflict resolved: {c.resolution or c.summary}" for c in answer.conflicts if c.resolved]
    return Confidence(level=ConfidenceLevel.HIGH, reasons=tuple(high), action="Safe to act.")
