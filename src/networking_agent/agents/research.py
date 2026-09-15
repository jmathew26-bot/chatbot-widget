"""RESEARCH AGENT: gathers additional public evidence about a prospect
(recent moves, interviews, specialties) and separates it into FACT vs
INFERENCE vs UNKNOWN. Every claim keeps its source URL (design doc: "Every
factual field should retain its source URL. Do not hallucinate missing
information.").
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Person, Source
from networking_agent.logging_utils import log_action
from networking_agent.services.llm_json import LLMOutputError, parse_llm_json


class ResearchFinding(BaseModel):
    claim: str
    fact_type: str = "INFERENCE"  # FACT | INFERENCE
    source_url: str


class ResearchSummary(BaseModel):
    personalization_angles: list[str] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


def _research_queries(person: Person) -> list[str]:
    company = person.current_company.name if person.current_company else ""
    return [
        f'"{person.full_name}" "{company}" interview',
        f'"{person.full_name}" "{company}" promoted OR promotion',
        f'"{person.full_name}" podcast OR panel OR speaker',
        f'"{person.full_name}" "{company}" announcement',
    ]


def gather_additional_sources(ctx: AgentContext, person: Person) -> list[Source]:
    existing_urls = {s.url for s in person.sources}
    new_sources: list[Source] = []
    for query in _research_queries(person):
        for result in ctx.search.search(query, num_results=5):
            if result.url in existing_urls:
                continue
            existing_urls.add(result.url)
            src = Source(
                person_id=person.id,
                url=result.url,
                title=result.title,
                snippet=result.snippet,
                claim="research search result",
                fact_type="INFERENCE",
            )
            ctx.session.add(src)
            new_sources.append(src)
    return new_sources


def _llm_summarize(ctx: AgentContext, person: Person) -> ResearchSummary:
    system = (
        "You are a research analyst building a factual dossier on a networking "
        "prospect. Read the provided source snippets and produce: (1) personalization "
        "angles -- specific, verifiable details a personalized email could reference "
        "(recent promotion, unusual career move, published interview, specialty area); "
        "(2) findings, each tagged FACT (directly stated in a source) or INFERENCE "
        "(a reasonable conclusion you drew, not directly stated), each with the source "
        "URL it came from; (3) risks -- anything that makes this prospect a bad fit or "
        "the evidence shaky. Never state something as FACT unless a source snippet "
        "says it. If there is not enough evidence for a strong personalization angle, "
        "return an empty list rather than inventing one."
    )
    evidence = "\n---\n".join(
        f"URL: {s.url}\nTitle: {s.title}\nSnippet: {s.snippet}" for s in person.sources
    ) or "(no sources)"
    prompt = (
        f"Person: {person.full_name}\n"
        f"Title: {person.current_title}\n"
        f"Company: {person.current_company.name if person.current_company else 'UNKNOWN'}\n"
        f"Location: {person.location}\n\n"
        f"Sources:\n{evidence}"
    )
    schema_hint = (
        '{"personalization_angles": [str], '
        '"findings": [{"claim": str, "fact_type": "FACT"|"INFERENCE", "source_url": str}], '
        '"risks": [str]}'
    )
    raw = ctx.llm.generate_json(system, prompt, schema_hint)
    return parse_llm_json(raw, ResearchSummary)


def _fallback_summarize(person: Person) -> ResearchSummary:
    findings = [
        ResearchFinding(
            claim=f"Currently {person.current_title} at "
            f"{person.current_company.name if person.current_company else 'UNKNOWN'}",
            fact_type="INFERENCE",
            source_url=person.sources[0].url if person.sources else "UNKNOWN",
        )
    ]
    return ResearchSummary(personalization_angles=[], findings=findings, risks=[])


def research_person(ctx: AgentContext, person: Person) -> ResearchSummary:
    gather_additional_sources(ctx, person)
    ctx.session.flush()

    if ctx.llm.is_available():
        try:
            summary = _llm_summarize(ctx, person)
        except (LLMOutputError, RuntimeError) as e:
            log_action("research", "llm_summarize_failed", person=person.full_name, error=str(e))
            summary = _fallback_summarize(person)
    else:
        summary = _fallback_summarize(person)

    person.personalization_angles = summary.personalization_angles
    person.risks = summary.risks
    for finding in summary.findings:
        exists = any(
            s.claim == finding.claim and s.url == finding.source_url for s in person.sources
        )
        if not exists:
            ctx.session.add(
                Source(
                    person_id=person.id,
                    url=finding.source_url,
                    claim=finding.claim,
                    fact_type=finding.fact_type,
                )
            )

    log_action(
        "research", "research_completed", person=person.full_name,
        angles=len(summary.personalization_angles), findings=len(summary.findings),
    )
    return summary
