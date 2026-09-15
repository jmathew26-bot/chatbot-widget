"""EMAIL AGENT: drafts personalized networking outreach. Enforces the
design doc's tone/length/structure rules and never sends anything itself
-- it only ever produces a DRAFT Outreach row that a human must approve.
"""
from __future__ import annotations

import hashlib
import uuid

from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Outreach, Person
from networking_agent.logging_utils import log_action
from networking_agent.schemas.prospect import EmailDraft
from networking_agent.services.llm_json import LLMOutputError, parse_llm_json

UT_MENTION_VARIANTS = [
    "I've been making an effort to meet more UT alumni doing interesting things{location_clause}.",
    "I came across your background while looking through fellow Longhorns working in {field}.",
    "Your background caught my attention while I was looking at UT alumni in {field}.",
    "I try to make a point of meeting other Longhorns building interesting careers{location_clause}.",
]

CTA_VARIANTS_AUSTIN = [
    "Would you be up for coffee sometime in the next few weeks?",
    "If you're ever up for grabbing coffee or lunch, I'd enjoy it.",
    "Would a quick coffee or call work sometime in the next couple weeks?",
]
CTA_VARIANTS_REMOTE = [
    "Would you be open to a quick call sometime in the next few weeks?",
    "If you have 20 minutes for a call sometime soon, I'd enjoy it.",
    "Would a short call work sometime in the next couple weeks?",
]

SUBJECT_TEMPLATES = [
    "Fellow Longhorn",
    "UT Austin",
    "Austin + UT",
    "Quick introduction",
    "Longhorn in tech",
    "Longhorn in CRE",
]


def _variant_for(person: Person, variants: list[str]) -> str:
    idx = int(hashlib.sha256(f"{person.id}:{person.full_name}".encode()).hexdigest(), 16) % len(variants)
    return variants[idx]


def _subject_options_for(person: Person) -> list[str]:
    off_category_subject = "Longhorn in CRE" if person.category != "cre" else "Longhorn in tech"
    candidates = [s for s in SUBJECT_TEMPLATES if s != off_category_subject]
    idx = int(hashlib.sha256(f"subj:{person.id}".encode()).hexdigest(), 16) % len(candidates)
    ordered = candidates[idx:] + candidates[:idx]
    return ordered[:3]


def _is_austin(location: str) -> bool:
    return "austin" in (location or "").lower()


def _mentions_ut(person) -> bool:
    return person.ut_status in ("VERIFIED", "LIKELY")


def _fallback_draft(ctx: AgentContext, person: Person, sequence_number: int) -> EmailDraft:
    company = person.current_company.name if person.current_company else "your company"
    field = "enterprise technology" if person.category == "tech-sales" else "commercial real estate"
    location_clause = f" in {person.location}" if person.location and person.location != "UNKNOWN" else ""

    opener = ""
    if _mentions_ut(person):
        opener = _variant_for(person, UT_MENTION_VARIANTS).format(location_clause=location_clause, field=field)

    angle = person.personalization_angles[0] if person.personalization_angles else None
    reason = (
        f" Your move to {person.current_title} at {company} stood out to me."
        if angle is None
        else f" {angle}"
    )

    cta = _variant_for(person, CTA_VARIANTS_AUSTIN if _is_austin(person.location) else CTA_VARIANTS_REMOTE)

    if sequence_number == 1:
        body = (
            f"Hi {person.first_name or person.full_name.split()[0]},\n\n"
            f"{opener}{reason}\n\n"
            f"{cta}\n\n"
            f"Best,\n{ctx.settings.user.get('name', 'Me')}"
        ).strip()
    elif sequence_number == 2:
        body = (
            f"Hi {person.first_name or person.full_name.split()[0]},\n\n"
            f"Wanted to send this along in case my last note got buried -- "
            f"still would enjoy a short conversation if the timing works better now.\n\n"
            f"{cta}\n\n"
            f"Best,\n{ctx.settings.user.get('name', 'Me')}"
        ).strip()
    else:
        body = (
            f"Hi {person.first_name or person.full_name.split()[0]},\n\n"
            f"I'll leave this here -- if a conversation ever makes sense on your end, "
            f"I'd still enjoy connecting.\n\n"
            f"Best,\n{ctx.settings.user.get('name', 'Me')}"
        ).strip()

    return EmailDraft(
        subject_options=_subject_options_for(person),
        body=body,
        word_count=len(body.split()),
        personalization_used=angle or "",
        template_tag=f"fallback-seq{sequence_number}",
    )


def _llm_draft(ctx: AgentContext, person: Person, sequence_number: int) -> EmailDraft:
    email_cfg = ctx.settings.email
    is_followup = sequence_number > 1
    system = (
        "You write short, personal networking emails on behalf of the user described "
        "in USER_PROFILE below, to a professional prospect. This is NOT marketing, "
        "recruiting, or sales outreach -- it reads like one successful professional "
        "reaching out to another for a conversation, nothing more.\n\n"
        f"Tone: {email_cfg.tone}.\n"
        f"Length: {email_cfg.min_words}-{email_cfg.default_max_words} words "
        f"(hard max {email_cfg.hard_max_words}).\n"
        f"Never use these phrases: {', '.join(email_cfg.banned_phrases)}.\n"
        "Structure (vary it, don't rigidly repeat the same shape every time): "
        "a personal reason for contacting them, credible common ground, why their "
        "background caught your attention, a simple low-pressure meeting request "
        "(coffee/lunch/call, never force a calendar link).\n"
        "Only reference UT Austin naturally if their UT status is VERIFIED or LIKELY "
        "-- never claim a Longhorn connection otherwise. Only use a personalization "
        "detail that is explicitly given below -- never invent one. Do not claim to "
        "know the person, fabricate shared history, or mention anything not provided.\n"
        + (
            "This is a brief, low-pressure follow-up to an earlier unanswered email -- "
            "keep it especially short, no guilt, no 'just bumping this' / 'just "
            "following up' language.\n"
            if is_followup
            else ""
        )
        + "Produce exactly 3 subject line options: simple, not clickbait (style examples: "
        f"{', '.join(SUBJECT_TEMPLATES)})."
    )
    company = person.current_company.name if person.current_company else "UNKNOWN"
    prompt = (
        f"USER_PROFILE:\n{ctx.settings.user_profile_text()}\n\n"
        f"PROSPECT:\n"
        f"Name: {person.full_name} (first name: {person.first_name})\n"
        f"Title: {person.current_title}\n"
        f"Company: {company}\n"
        f"Location: {person.location}\n"
        f"UT status: {person.ut_status} ({person.ut_status_rationale})\n"
        f"UT degree/year: {person.ut_degree} / {person.ut_grad_year}\n"
        f"Networking thesis: {person.networking_thesis}\n"
        f"Personalization angles: {person.personalization_angles}\n"
        f"Sequence number: {sequence_number} (1=initial, 2=follow-up 1, 3=follow-up 2)\n"
    )
    schema_hint = (
        '{"subject_options": [str, str, str], "body": str, "word_count": int, '
        '"personalization_used": str, "template_tag": str}'
    )
    raw = ctx.llm.generate_json(system, prompt, schema_hint)
    draft = parse_llm_json(raw, EmailDraft)
    draft.word_count = len(draft.body.split())
    return draft


def _check_banned_phrases(body: str, banned_phrases: list[str]) -> list[str]:
    body_lower = body.lower()
    return [p for p in banned_phrases if p.lower() in body_lower]


def draft_email(ctx: AgentContext, person: Person, sequence_number: int = 1) -> tuple[Outreach, list[str]]:
    if ctx.llm.is_available():
        try:
            draft = _llm_draft(ctx, person, sequence_number)
        except LLMOutputError as e:
            log_action("email_agent", "llm_draft_failed", person=person.full_name, error=str(e))
            draft = _fallback_draft(ctx, person, sequence_number)
    else:
        draft = _fallback_draft(ctx, person, sequence_number)

    warnings: list[str] = []
    hard_max = ctx.settings.email.hard_max_words
    if draft.word_count > hard_max:
        warnings.append(f"Draft is {draft.word_count} words, over the hard max of {hard_max}.")
    banned_hits = _check_banned_phrases(draft.body, ctx.settings.email.banned_phrases)
    if banned_hits:
        warnings.append(f"Contains banned phrase(s): {', '.join(banned_hits)}")

    outreach = Outreach(
        person_id=person.id,
        sequence_number=sequence_number,
        subject=draft.subject_options[0],
        subject_options=draft.subject_options,
        body=draft.body,
        template_tag=draft.template_tag,
        personalization_angle=draft.personalization_used,
        idempotency_key=str(uuid.uuid4()),
    )
    ctx.session.add(outreach)
    ctx.session.flush()

    log_action(
        "email_agent", "email_drafted", person=person.full_name, sequence_number=sequence_number,
        word_count=draft.word_count, warnings=len(warnings),
    )
    return outreach, warnings
