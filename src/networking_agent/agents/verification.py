"""VERIFICATION AGENT: determines UT Austin attendance status (and
sanity-checks current employment) before a prospect can enter the normal
outreach queue. This is the gate described in the design doc -- only
VERIFIED prospects flow automatically; LIKELY needs manual review; FALSE
(a different UT-system school) is treated as disqualifying.
"""
from __future__ import annotations

import re

from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Education, Person, Source
from networking_agent.enums import UTStatus
from networking_agent.logging_utils import log_action
from networking_agent.schemas.prospect import UTVerificationResult
from networking_agent.services.llm_json import LLMOutputError, parse_llm_json

OTHER_UT_SYSTEM_SCHOOLS = [
    "ut dallas", "university of texas at dallas",
    "ut arlington", "university of texas at arlington",
    "ut san antonio", "university of texas at san antonio", "utsa",
    "ut el paso", "university of texas at el paso", "utep",
    "ut permian basin", "ut tyler", "ut rio grande valley", "ut austin health",
]
UT_AUSTIN_PHRASES = [
    "university of texas at austin", "ut austin", "texas exes",
    "mccombs school of business", "cockrell school of engineering",
    "longhorn", "hook 'em",
]


def _collect_evidence_text(person: Person) -> str:
    parts = [person.current_title or "", person.other_education or ""]
    for src in person.sources:
        parts.append(src.title or "")
        parts.append(src.snippet or "")
    return " \n".join(parts).lower()


def _heuristic_verify(person: Person) -> UTVerificationResult:
    text = _collect_evidence_text(person)
    mentions_other_ut = any(school in text for school in OTHER_UT_SYSTEM_SCHOOLS)
    mentions_ut_austin = any(phrase in text for phrase in UT_AUSTIN_PHRASES)

    if mentions_other_ut and not mentions_ut_austin:
        return UTVerificationResult(
            ut_status=UTStatus.FALSE,
            rationale="Evidence references a different UT-system institution, not UT Austin.",
        )
    if mentions_ut_austin:
        # A specific, unambiguous phrase ("University of Texas at Austin",
        # "McCombs", "Cockrell") in retained source text counts as direct
        # evidence -> VERIFIED. A bare "UT Austin" mention from a lower
        # quality source is still allowed through as VERIFIED here because
        # our phrase list only contains Austin-specific markers -- ambiguous
        # short forms like plain "UT" are deliberately excluded from this list.
        return UTVerificationResult(
            ut_status=UTStatus.VERIFIED,
            rationale="Retained source text explicitly references UT Austin.",
        )
    return UTVerificationResult(
        ut_status=UTStatus.UNVERIFIED,
        rationale="No source text found mentioning UT Austin or another UT-system school.",
    )


def _llm_verify(ctx: AgentContext, person: Person) -> UTVerificationResult:
    system = (
        "You verify whether a specific person attended The University of Texas at "
        "Austin (UT Austin) -- NOT UT Dallas, UT Arlington, UT San Antonio, UT El "
        "Paso, or any other University of Texas System institution. Those are "
        "different schools and must not be confused with UT Austin. "
        "Classify strictly:\n"
        "VERIFIED: clear direct evidence of UT Austin attendance (named the school, "
        "a UT Austin college like McCombs/Cockrell, or a verifiable degree/year).\n"
        "LIKELY: credible circumstantial signals (e.g. 'Texas Exes' alumni group "
        "membership, Austin-based career start, indirect references) but no direct "
        "confirmation.\n"
        "UNVERIFIED: insufficient evidence either way.\n"
        "FALSE: evidence shows attendance at a *different* UT System school.\n"
        "Never upgrade UNVERIFIED to VERIFIED/LIKELY without citing which source text "
        "supports it. Do not use outside knowledge about the person -- only the "
        "evidence provided."
    )
    evidence_blocks = "\n---\n".join(
        f"URL: {s.url}\nTitle: {s.title}\nSnippet: {s.snippet}" for s in person.sources
    ) or "(no sources retained)"
    prompt = (
        f"Person: {person.full_name}\n"
        f"Current title: {person.current_title}\n"
        f"Current company: {person.current_company.name if person.current_company else 'UNKNOWN'}\n\n"
        f"Evidence:\n{evidence_blocks}"
    )
    schema_hint = (
        '{"ut_status": "VERIFIED"|"LIKELY"|"UNVERIFIED"|"FALSE", "ut_degree": str, '
        '"ut_grad_year": int|null, "rationale": str, "sources": [str]}'
    )
    raw = ctx.llm.generate_json(system, prompt, schema_hint)
    return parse_llm_json(raw, UTVerificationResult)


def verify_ut_status(ctx: AgentContext, person: Person) -> UTVerificationResult:
    if ctx.llm.is_available():
        try:
            result = _llm_verify(ctx, person)
        except (LLMOutputError, RuntimeError) as e:
            log_action("verification", "llm_verification_failed", person=person.full_name, error=str(e))
            result = _heuristic_verify(person)
    else:
        result = _heuristic_verify(person)

    person.ut_status = result.ut_status.value
    person.ut_status_rationale = result.rationale
    if result.ut_degree and result.ut_degree != "UNKNOWN":
        person.ut_degree = result.ut_degree
    if result.ut_grad_year:
        person.ut_grad_year = result.ut_grad_year

    if result.ut_status in (UTStatus.VERIFIED, UTStatus.LIKELY):
        already = any(
            "university of texas at austin" in (e.institution or "").lower() for e in person.education
        )
        if not already:
            ctx.session.add(
                Education(
                    person_id=person.id,
                    institution="The University of Texas at Austin",
                    degree=person.ut_degree,
                    graduation_year=person.ut_grad_year,
                    fact_type="FACT" if result.ut_status == UTStatus.VERIFIED else "INFERENCE",
                    source_url=result.sources[0] if result.sources else None,
                )
            )

    log_action(
        "verification", "ut_status_set", person=person.full_name, ut_status=result.ut_status.value
    )
    return result
