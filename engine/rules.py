"""Layer 1: deterministic trust rules on source METADATA.

Each rule is a small pure function with the same signature:

    rule(source, ctx, kb, cfg) -> RuleResult | None

Returning None means "this rule has nothing to say about this source".
To add a rule, write one function and append it to RULES. Nothing else
changes. Rules never read the content and never call the LLM, so every
label can be traced back to one metadata fact.
"""

from __future__ import annotations

from typing import Callable

from .config import RulesConfig
from .loader import KnowledgeBase
from .models import (
    Context,
    OwnerStatus,
    RuleResult,
    RuleStatus,
    Source,
    SourceAssessment,
    SourceStatus,
    SourceType,
)

Rule = Callable[[Source, Context, KnowledgeBase, RulesConfig], "RuleResult | None"]

_TYPE_LABELS = {
    SourceType.POLICY: "Official policy",
    SourceType.PROCEDURE: "Official procedure",
    SourceType.CLIENT_NOTE: "Client note",
    SourceType.EMAIL: "Email (informal)",
    SourceType.CHAT: "Chat message (informal)",
    SourceType.UNKNOWN: "Unclassified source",
}


# --------------------------------------------------------------------------
# Owner resolution (shared by rules, confidence and expert routing)
# --------------------------------------------------------------------------


def owner_status(source: Source, ctx: Context, kb: KnowledgeBase) -> OwnerStatus:
    if not source.owner:
        return OwnerStatus.MISSING
    expert = kb.experts.get(source.owner)
    if expert is None:
        return OwnerStatus.EXTERNAL if "@" in source.owner else OwnerStatus.UNLISTED
    if expert.status == "left" or (expert.left_date and expert.left_date <= ctx.as_of_date):
        return OwnerStatus.LEFT
    if expert.status == "leaving" or expert.leaving_date:
        # A leaving date in the past means the person is already gone.
        if expert.leaving_date and expert.leaving_date <= ctx.as_of_date:
            return OwnerStatus.LEFT
        return OwnerStatus.LEAVING
    return OwnerStatus.ACTIVE


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


def rule_country(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> RuleResult:
    if source.country in (ctx.country, "ALL"):
        return RuleResult(rule="country_match", status=RuleStatus.PASS,
                          label=f"Applies to {ctx.country}" if source.country != "ALL" else "Applies to all countries")
    return RuleResult(rule="country_match", status=RuleStatus.FAIL,
                      label=f"Applies to {source.country}, you are working on {ctx.country}")


def rule_superseded(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> RuleResult | None:
    if source.superseded_by:
        return RuleResult(rule="superseded", status=RuleStatus.FAIL,
                          label=f"Replaced by {source.superseded_by}, don't use")
    if source.supersedes:
        return RuleResult(rule="superseded", status=RuleStatus.INFO,
                          label=f"Latest version, replaces {source.supersedes}")
    return None


def rule_freshness(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> RuleResult:
    age_days = (ctx.as_of_date - source.last_updated).days
    if age_days < 0:
        return RuleResult(rule="freshness", status=RuleStatus.WARN,
                          label=f"Dated in the future ({source.last_updated.isoformat()}), check the date")
    max_age = cfg.max_age_days.get(source.source_type, 365)
    months = age_days // 30
    if age_days > max_age:
        return RuleResult(rule="freshness", status=RuleStatus.WARN,
                          label=(f"Possibly outdated: last updated {months} months ago "
                                 f"(review expected every {max_age // 30} months)"))
    when = "this month" if months == 0 else f"{months} month{'s' if months != 1 else ''} ago"
    return RuleResult(rule="freshness", status=RuleStatus.PASS, label=f"Updated {when}")


def rule_status(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> RuleResult:
    if source.status == SourceStatus.CURRENT:
        return RuleResult(rule="status", status=RuleStatus.PASS, label="Status: current")
    if source.status == SourceStatus.DRAFT:
        return RuleResult(rule="status", status=RuleStatus.WARN, label="Draft, never officially published")
    if source.status == SourceStatus.INFORMAL:
        return RuleResult(rule="status", status=RuleStatus.INFO, label="Informal communication, not an official document")
    return RuleResult(rule="status", status=RuleStatus.WARN, label="Status unknown in the source system")


def rule_owner(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> RuleResult:
    status = owner_status(source, ctx, kb)
    expert = kb.experts.get(source.owner or "")
    name = expert.name if expert else (source.owner or "")
    if status == OwnerStatus.MISSING:
        return RuleResult(rule="owner", status=RuleStatus.WARN, label="No owner: nobody vouches for this")
    if status == OwnerStatus.LEFT:
        when = f" ({expert.left_date.isoformat()})" if expert and expert.left_date else ""
        return RuleResult(rule="owner", status=RuleStatus.WARN, label=f"Owner {name} has left the company{when}")
    if status == OwnerStatus.EXTERNAL:
        return RuleResult(rule="owner", status=RuleStatus.WARN, label=f"External sender ({name}), not verified internally")
    if status == OwnerStatus.UNLISTED:
        return RuleResult(rule="owner", status=RuleStatus.INFO, label=f"Written by {name} (not a listed expert)")
    return RuleResult(rule="owner", status=RuleStatus.PASS, label=f"Owned by {name}")


def rule_handover(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> RuleResult | None:
    if owner_status(source, ctx, kb) != OwnerStatus.LEAVING:
        return None
    expert = kb.experts[source.owner]  # LEAVING implies the owner is in the directory
    if expert.leaving_date is None:
        return RuleResult(rule="handover_risk", status=RuleStatus.WARN,
                          label=f"Owner {expert.name} is leaving (date unknown)")
    days_left = (expert.leaving_date - ctx.as_of_date).days
    status = RuleStatus.WARN if days_left <= cfg.handover_window_days else RuleStatus.INFO
    return RuleResult(rule="handover_risk", status=status,
                      label=f"Owner {expert.name} leaves on {expert.leaving_date.isoformat()} ({days_left} days)")


def rule_authority(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> RuleResult:
    return RuleResult(rule="authority", status=RuleStatus.INFO, label=_TYPE_LABELS[source.source_type])


# Order = display order in the UI.
RULES: tuple[Rule, ...] = (
    rule_country,
    rule_superseded,
    rule_freshness,
    rule_status,
    rule_owner,
    rule_handover,
    rule_authority,
)


# --------------------------------------------------------------------------
# Assessment
# --------------------------------------------------------------------------


def _verdict(results: list[RuleResult]) -> RuleStatus:
    statuses = {r.status for r in results}
    if RuleStatus.FAIL in statuses:
        return RuleStatus.FAIL
    if RuleStatus.WARN in statuses:
        return RuleStatus.WARN
    return RuleStatus.PASS


def assess_source(source: Source, ctx: Context, kb: KnowledgeBase, cfg: RulesConfig) -> SourceAssessment:
    results = [r for rule in RULES if (r := rule(source, ctx, kb, cfg)) is not None]
    country_fail = next((r for r in results if r.rule == "country_match" and r.status == RuleStatus.FAIL), None)
    return SourceAssessment(
        id=source.id,
        title=source.title,
        source_type=source.source_type,
        country=source.country,
        company=source.company,
        has_pdf=source.id in kb.pdf_ids,
        owner=source.owner,
        owner_status=owner_status(source, ctx, kb),
        last_updated=source.last_updated,
        verdict=_verdict(results),
        excluded=country_fail is not None,
        exclusion_reason=country_fail.label if country_fail else None,
        rules=tuple(results),
    )
