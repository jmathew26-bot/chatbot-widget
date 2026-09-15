"""The end-to-end discovery pipeline shared by `network discover` and
`network live-test`: DISCOVER -> VERIFY UT -> RESEARCH -> SCORE ->
CRM-promote -> FIND/VERIFY EMAIL. Stops before drafting -- email drafting
happens lazily in `network review` / the web Outreach page, on demand,
so LLM calls aren't spent on prospects nobody ever reviews.
"""
from __future__ import annotations

from networking_agent.agents import crm, discovery, email_discovery, research, scoring
from networking_agent.agents import verification as verification_agent
from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Person


def enrich_discovered_people(ctx: AgentContext, people: list[Person]) -> None:
    """Runs VERIFY -> RESEARCH -> SCORE -> CRM-promote -> FIND/VERIFY EMAIL
    for a batch of just-discovered people."""
    for person in people:
        verification_agent.verify_ut_status(ctx, person)
        research.research_person(ctx, person)
        scoring.score_person(ctx, person)
        crm.promote_after_scoring(ctx, person)
        email_discovery.discover_email(ctx, person)
    ctx.session.flush()


def run_discovery_pipeline(ctx: AgentContext, category: str, location: str | None, count: int) -> list[Person]:
    people = discovery.discover(ctx, category, location, count)
    enrich_discovered_people(ctx, people)
    return people
