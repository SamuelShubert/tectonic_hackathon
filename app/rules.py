"""Rules + confidence + expert selection (build plan sections 4 and 5). OWNER: teammate (P2).

STUB so the API runs end to end. Only country_match, superseded and authority are real.
Replace the bodies, but KEEP THESE SIGNATURES (main.py calls them):

    evaluate_source(source, context, all_sources, experts) -> list[RuleResult]
    source_verdict(rule_results) -> "pass" | "warn" | "fail"
    exclusion_reason(rule_results) -> str | None      # not None = move to excluded_sources
    compute_confidence(answer, scored_sources, context) -> {"level", "reasons", "action"}
    select_expert(answer, scored_sources, context, experts, question) -> {"id","role","why"} | None

RuleResult = {"rule": str, "status": "pass"|"warn"|"fail"|"info", "label": str}
scored_sources = [{**source, "verdict": str, "rules": [RuleResult]}]   (included sources only)
Owner status: app.loader.owner_status(owner, experts)
  -> state in active | leaving | left | colleague | external | none
"""
from app.loader import owner_status

AUTHORITY_LABEL = {
    "policy": "Official policy",
    "procedure": "Official procedure",
    "client_note": "Client note",
    "email": "Email",
    "chat": "Informal chat message",
}


def _country_match(source, context, all_sources, experts):
    if source["country"] in (context["country"], "ALL"):
        return {"rule": "country_match", "status": "pass", "label": f"Applies to {context['country']}"}
    return {"rule": "country_match", "status": "fail",
            "label": f"Applies to {source['country']}, you are working on {context['country']}"}


def _superseded(source, context, all_sources, experts):
    if source.get("superseded_by"):
        return {"rule": "superseded", "status": "fail",
                "label": f"Replaced by {source['superseded_by']}, don't use"}
    return None


def _authority(source, context, all_sources, experts):
    return {"rule": "authority", "status": "info",
            "label": AUTHORITY_LABEL.get(source["source_type"], source["source_type"])}


# TODO(P2): add freshness, status, owner, handover_risk (section 4).
RULES = [_country_match, _superseded, _authority]


def evaluate_source(source, context, all_sources, experts):
    results = []
    for rule in RULES:
        res = rule(source, context, all_sources, experts)
        if res:
            results.append(res)
    return results


def source_verdict(rule_results):
    statuses = {r["status"] for r in rule_results if r["rule"] != "country_match"}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def exclusion_reason(rule_results):
    for r in rule_results:
        if r["rule"] == "country_match" and r["status"] == "fail":
            return r["label"]
    return None


def compute_confidence(answer, scored_sources, context):
    # TODO(P2): full section 5 logic.
    by_id = {s["id"]: s for s in scored_sources}
    winner = by_id.get(answer.get("winning_source_id"))
    if answer.get("answer_status") != "answered" or not winner:
        return {"level": "Low", "reasons": ["No reliable answer found"], "action": "Don't act yet, ask an expert."}
    if any(not c.get("resolved") for c in answer.get("conflicts", [])):
        return {"level": "Low", "reasons": ["Sources disagree and the conflict is unresolved"],
                "action": "Don't act yet, ask an expert."}
    if winner["verdict"] != "pass":
        return {"level": "Medium", "reasons": [f"Main source {winner['id']} has warnings"], "action": "Verify, then act."}
    return {"level": "High", "reasons": [f"Main source {winner['id']} passes all checks"], "action": "Safe to act."}


def select_expert(answer, scored_sources, context, experts, question):
    # TODO(P2): topic tie-break, "ask Jens before he leaves" (see review notes in README).
    by_id = {s["id"]: s for s in scored_sources}
    winner = by_id.get(answer.get("winning_source_id"))
    if winner and winner.get("owner"):
        if owner_status(winner["owner"], experts)["state"] == "active":
            e = experts[winner["owner"]]
            return {"id": e["id"], "role": e["role"], "why": f"Owner of the main source ({winner['id']})"}
    for e in experts.values():
        if e.get("status") == "active" and context["country"] in e.get("countries", []):
            return {"id": e["id"], "role": e["role"], "why": f"Active expert for {context['country']}"}
    return None
