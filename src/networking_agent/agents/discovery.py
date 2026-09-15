"""DISCOVERY AGENT: finds candidate professionals via the configured
SearchProvider and turns raw search results into unverified Person rows
(status DISCOVERED). Does not verify UT status, research, or score --
that's downstream agents' job.
"""
from __future__ import annotations

import re

from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Activity, Employment, Person, Relationship, Source
from networking_agent.enums import ActivityType, RelationshipStatus
from networking_agent.logging_utils import log_action
from networking_agent.schemas.prospect import CandidateExtraction, CandidateExtractionResponse, SearchResult
from networking_agent.services.companies import get_or_create_company
from networking_agent.services.dedupe import build_normalized_identity, find_existing_person
from networking_agent.services.llm_json import LLMOutputError, parse_llm_json
from networking_agent.services.query_builder import build_queries

_TITLE_SPLIT_RE = re.compile(r"\s*[-|–]\s*")


def _heuristic_extract(result: SearchResult, category: str) -> CandidateExtraction | None:
    """Fallback used when no LLM is configured. Parses the common
    "Name - Title - Company | Site" shape of professional-profile search
    result titles. Conservative: returns None (no candidate) rather than
    guessing when the shape doesn't match, so we never fabricate a person.
    """
    parts = _TITLE_SPLIT_RE.split(result.title)
    parts = [p.strip() for p in parts if p.strip() and "linkedin" not in p.lower()]
    if len(parts) < 2:
        return None
    name = parts[0]
    if len(name.split()) < 2 or len(name.split()) > 4:
        return None
    rest = " ".join(parts[1:])
    return CandidateExtraction(
        full_name=name,
        title=parts[1] if len(parts) > 1 else "UNKNOWN",
        company=parts[2] if len(parts) > 2 else "UNKNOWN",
        location="UNKNOWN",
        category=category,
        profile_url=result.url,
        evidence_snippet=result.snippet or rest,
        source_url=result.url,
    )


def _llm_extract(ctx: AgentContext, result: SearchResult, category: str) -> CandidateExtraction | None:
    system = (
        "You extract structured candidate data for a personal networking tool. "
        "You are given ONE web search result. Decide whether it plausibly names a "
        "specific real individual professional (not a company page, job listing, "
        "directory list, or news roundup) who could match the target persona. "
        "Never invent facts not present in the title/snippet/url -- use UNKNOWN for "
        "anything not stated."
    )
    prompt = (
        f"Category: {category}\n"
        f"Search query: {result.query}\n"
        f"Result title: {result.title}\n"
        f"Result URL: {result.url}\n"
        f"Result snippet: {result.snippet}\n"
    )
    schema_hint = (
        '{"is_candidate": bool, "candidate": {"full_name": str, "title": str, '
        '"company": str, "location": str, "category": str, "profile_url": str|null, '
        '"evidence_snippet": str, "source_url": str} | null}'
    )
    raw = ctx.llm.generate_json(system, prompt, schema_hint)
    parsed = parse_llm_json(raw, CandidateExtractionResponse)
    if not parsed.is_candidate or parsed.candidate is None:
        return None
    return parsed.candidate


def extract_candidate(ctx: AgentContext, result: SearchResult, category: str) -> CandidateExtraction | None:
    if ctx.llm.is_available():
        try:
            return _llm_extract(ctx, result, category)
        except (LLMOutputError, RuntimeError) as e:
            log_action("discovery", "llm_extraction_failed", source=result.url, error=str(e))
    return _heuristic_extract(result, category)


def discover(ctx: AgentContext, category: str, location: str | None, count: int) -> list[Person]:
    key = "cre" if category == "cre" else "tech_sales"
    targets = ctx.settings.targets.get(key, {})
    titles = targets.get("titles", [])
    companies = targets.get("companies", [])
    excluded_people = {n.lower() for n in ctx.settings.targets.get("excluded_people", [])}
    excluded_companies = {c.lower() for c in ctx.settings.targets.get("excluded_companies", [])}

    queries = build_queries(category, titles, companies, location, limit=30)
    log_action("discovery", "queries_built", query_count=len(queries), category=category, location=location)

    seen_urls: set[str] = set()
    candidates: list[tuple[CandidateExtraction, SearchResult]] = []
    for query in queries:
        if len(candidates) >= count * 3:
            break
        results = ctx.search.search(query, num_results=10)
        for result in results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            extraction = extract_candidate(ctx, result, category)
            if extraction is None:
                continue
            if extraction.full_name.lower() in excluded_people:
                continue
            if extraction.company.lower() in excluded_companies:
                continue
            candidates.append((extraction, result))

    created: list[Person] = []
    for extraction, result in candidates:
        if len(created) >= count:
            break
        existing = find_existing_person(
            ctx.session, extraction.full_name, extraction.company, extraction.profile_url
        )
        if existing is not None:
            log_action(
                "discovery", "duplicate_skipped", person=extraction.full_name, source=result.url
            )
            continue

        company = get_or_create_company(ctx.session, extraction.company, category)

        name_parts = extraction.full_name.split()
        person = Person(
            full_name=extraction.full_name,
            first_name=name_parts[0],
            last_name=name_parts[-1] if len(name_parts) > 1 else None,
            normalized_identity=build_normalized_identity(
                extraction.full_name, extraction.company, extraction.profile_url
            ),
            profile_url=extraction.profile_url,
            current_title=extraction.title,
            current_company_id=company.id if company else None,
            location=extraction.location,
            category=category,
        )
        ctx.session.add(person)
        ctx.session.flush()

        if company:
            ctx.session.add(
                Employment(
                    person_id=person.id,
                    company_id=company.id,
                    company_name_raw=extraction.company,
                    title=extraction.title,
                    is_current=True,
                    fact_type="INFERENCE",
                    source_url=result.url,
                )
            )
        ctx.session.add(
            Source(
                person_id=person.id,
                url=result.url,
                title=result.title,
                snippet=result.snippet,
                claim="discovery search result",
                fact_type="FACT",
            )
        )
        ctx.session.add(Relationship(person_id=person.id, status=RelationshipStatus.DISCOVERED.value))
        ctx.session.add(
            Activity(
                person_id=person.id,
                activity_type=ActivityType.DISCOVERED.value,
                payload={"query": result.query, "source_url": result.url},
            )
        )
        log_action("discovery", "person_discovered", person=person.full_name, source=result.url)
        created.append(person)

    return created
