"""SCORING AGENT: computes the 0-100 prospect score (deterministic, see
services/scoring_rules.py) and produces the one-sentence networking
thesis ("why is this person worth meeting"). If no convincing thesis can
be produced, the design doc says to lower the score -- implemented here as
a penalty when personalization_angles is empty and UT status is weak.
"""
from __future__ import annotations

from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Person
from networking_agent.enums import UTStatus
from networking_agent.logging_utils import log_action
from networking_agent.services.companies import is_known_target_company
from networking_agent.services.llm_json import LLMOutputError, parse_llm_json
from networking_agent.services.scoring_rules import ScoreBreakdown, compute_score
from pydantic import BaseModel


class ThesisResult(BaseModel):
    networking_thesis: str


NO_THESIS_PENALTY = 8


def _target_titles(ctx: AgentContext, person: Person) -> list[str]:
    key = "cre" if person.category == "cre" else "tech_sales"
    return ctx.settings.targets.get(key, {}).get("titles", [])


def _category_match(ctx: AgentContext, person: Person) -> bool:
    company_name = person.current_company.name if person.current_company else ""
    return is_known_target_company(ctx.settings.targets, person.category, company_name) or bool(
        _target_titles(ctx, person)
        and any(t.lower() in (person.current_title or "").lower() for t in _target_titles(ctx, person))
    )


def _llm_thesis(ctx: AgentContext, person: Person) -> str:
    system = (
        "Write ONE sentence answering 'why is this person worth meeting?' for a "
        "networking prospect. Base it only on the facts given -- do not invent "
        "achievements. Style: e.g. 'UT Austin alumnus who has spent 12 years moving "
        "through enterprise software sales leadership and now manages strategic "
        "accounts at a leading cybersecurity company.' Keep it to one sentence."
    )
    prompt = (
        f"Name: {person.full_name}\n"
        f"Title: {person.current_title}\n"
        f"Company: {person.current_company.name if person.current_company else 'UNKNOWN'}\n"
        f"Location: {person.location}\n"
        f"UT status: {person.ut_status}\n"
        f"UT degree: {person.ut_degree}\n"
        f"Personalization angles: {person.personalization_angles}\n"
    )
    raw = ctx.llm.generate_json(system, prompt, '{"networking_thesis": str}')
    return parse_llm_json(raw, ThesisResult).networking_thesis


def _fallback_thesis(person: Person) -> str:
    company = person.current_company.name if person.current_company else "an unlisted company"
    ut_clause = ""
    if person.ut_status == UTStatus.VERIFIED.value:
        ut_clause = "UT Austin alumnus "
    elif person.ut_status == UTStatus.LIKELY.value:
        ut_clause = "likely UT Austin alumnus "
    location_clause = f" based in {person.location}" if person.location and person.location != "UNKNOWN" else ""
    sentence = f"{ut_clause}working as {person.current_title} at {company}{location_clause}.".strip()
    return sentence[0].upper() + sentence[1:] if sentence else sentence


def score_person(ctx: AgentContext, person: Person) -> ScoreBreakdown:
    ut_status = UTStatus(person.ut_status)
    category_match = _category_match(ctx, person)
    company_quality = person.current_company.quality_score if person.current_company else 50
    locations = ctx.settings.targets.get("locations", {})
    num_employers = len(person.employment) or 1
    has_notable_transition = len(person.personalization_angles) > 0

    breakdown = compute_score(
        ut_status=ut_status,
        title=person.current_title,
        target_titles=_target_titles(ctx, person),
        category_match=category_match,
        company_quality_0_100=company_quality,
        location=person.location,
        tier_1=locations.get("tier_1", []),
        tier_2=locations.get("tier_2", []),
        tier_3=locations.get("tier_3", []),
        num_employers=num_employers,
        has_notable_transition=has_notable_transition,
        weights=ctx.settings.scoring.weights,
        thresholds=ctx.settings.scoring.thresholds,
    )

    if ctx.llm.is_available():
        try:
            thesis = _llm_thesis(ctx, person)
        except (LLMOutputError, RuntimeError) as e:
            log_action("scoring", "llm_thesis_failed", person=person.full_name, error=str(e))
            thesis = _fallback_thesis(person)
    else:
        thesis = _fallback_thesis(person)

    total = breakdown.total_score
    if not person.personalization_angles and ut_status not in (UTStatus.VERIFIED, UTStatus.LIKELY):
        total = max(0, total - NO_THESIS_PENALTY)
        breakdown.total_score = total

    person.ut_score = breakdown.ut_score
    person.career_relevance_score = breakdown.career_relevance_score
    person.company_quality_score = breakdown.company_quality_score
    person.seniority_score = breakdown.seniority_score
    person.geography_score = breakdown.geography_score
    person.career_interest_score = breakdown.career_interest_score
    person.relationship_value_score = breakdown.relationship_value_score
    person.total_score = total
    person.networking_thesis = thesis

    log_action(
        "scoring", "person_scored", person=person.full_name, total_score=total,
        classification=breakdown.classification,
    )
    return breakdown
