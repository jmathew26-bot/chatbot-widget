"""RESPONSE AGENT: classifies incoming replies and immediately stops
follow-ups on any positive OR negative signal (only NEEDS_FOLLOW_UP /
UNKNOWN leave the cadence running, since those aren't really an answer
yet).
"""
from __future__ import annotations

import re

from networking_agent.agents.context import AgentContext
from networking_agent.agents.followup import cancel_followups
from networking_agent.db.models import Activity, Person
from networking_agent.enums import (
    STOP_FOLLOWUP_CLASSIFICATIONS,
    ActivityType,
    EmailVerificationStatus,
    RelationshipStatus,
    ReplyClassification,
)
from networking_agent.logging_utils import log_action
from networking_agent.schemas.prospect import ReplyClassificationResult
from networking_agent.services.llm_json import LLMOutputError, parse_llm_json

_DECLINE_PATTERNS = [r"\bnot interested\b", r"\bno thanks\b", r"\bplease remove\b", r"\bunsubscribe\b"]
_DNC_PATTERNS = [r"\bdo not contact\b", r"\bstop contacting\b", r"\bremove me\b"]
_POSITIVE_PATTERNS = [r"\bhappy to\b", r"\bsounds good\b", r"\blet's do it\b", r"\blove to\b", r"\bwould love\b"]
_MEETING_PATTERNS = [r"\bcalendar\b", r"\bavailab", r"\bschedule\b", r"\bwhat time\b", r"\btimes work\b"]
_AUTOMATED_PATTERNS = [r"\bout of office\b", r"\bautomatic reply\b", r"\bauto-reply\b", r"\bon vacation\b"]
_BOUNCE_PATTERNS = [r"\bundeliverable\b", r"\bmailer-daemon\b", r"\bdelivery.{0,10}fail", r"\bbounce"]


def _heuristic_classify(text: str) -> ReplyClassificationResult:
    lower = text.lower()

    def matches(patterns: list[str]) -> bool:
        return any(re.search(p, lower) for p in patterns)

    if matches(_BOUNCE_PATTERNS):
        return ReplyClassificationResult(classification=ReplyClassification.BOUNCE, confidence=0.9)
    if matches(_AUTOMATED_PATTERNS):
        return ReplyClassificationResult(classification=ReplyClassification.AUTOMATED_RESPONSE, confidence=0.8)
    if matches(_DNC_PATTERNS):
        return ReplyClassificationResult(classification=ReplyClassification.DO_NOT_CONTACT, confidence=0.9)
    if matches(_DECLINE_PATTERNS):
        return ReplyClassificationResult(classification=ReplyClassification.DECLINED, confidence=0.8)
    if matches(_MEETING_PATTERNS):
        return ReplyClassificationResult(classification=ReplyClassification.MEETING_REQUESTED, confidence=0.7)
    if matches(_POSITIVE_PATTERNS):
        return ReplyClassificationResult(classification=ReplyClassification.INTERESTED, confidence=0.6)
    return ReplyClassificationResult(
        classification=ReplyClassification.UNKNOWN, confidence=0.3,
        rationale="No confident keyword match; needs manual review.",
    )


def _llm_classify(ctx: AgentContext, text: str) -> ReplyClassificationResult:
    system = (
        "Classify an email reply to a personal networking outreach message into "
        "exactly one category: POSITIVE, INTERESTED, MEETING_REQUESTED, "
        "NEEDS_FOLLOW_UP, NOT_NOW, DECLINED, DO_NOT_CONTACT, BOUNCE, "
        "AUTOMATED_RESPONSE, or UNKNOWN."
    )
    schema_hint = (
        '{"classification": str, "confidence": float, "rationale": str, '
        '"suggested_next_action": str}'
    )
    raw = ctx.llm.generate_json(system, f"Reply text:\n{text}", schema_hint)
    return parse_llm_json(raw, ReplyClassificationResult)


def classify_reply(ctx: AgentContext, text: str) -> ReplyClassificationResult:
    if ctx.llm.is_available():
        try:
            return _llm_classify(ctx, text)
        except (LLMOutputError, RuntimeError) as e:
            log_action("response", "llm_classification_failed", error=str(e))
    return _heuristic_classify(text)


def _apply_classification(
    ctx: AgentContext, person: Person, result: ReplyClassificationResult, extra_payload: dict | None = None
) -> None:
    relationship = person.relationship
    relationship.reply_status = result.classification.value

    if result.classification in STOP_FOLLOWUP_CLASSIFICATIONS:
        cancel_followups(relationship, reason=f"reply classified as {result.classification.value}")

    if result.classification == ReplyClassification.BOUNCE:
        for email in person.emails:
            if email.is_primary:
                email.verification_status = EmailVerificationStatus.BOUNCED.value
        relationship.status = RelationshipStatus.DO_NOT_CONTACT.value
    elif result.classification == ReplyClassification.DO_NOT_CONTACT:
        relationship.status = RelationshipStatus.DO_NOT_CONTACT.value
        for email in person.emails:
            email.verification_status = EmailVerificationStatus.DO_NOT_CONTACT.value
    elif result.classification == ReplyClassification.DECLINED:
        relationship.status = RelationshipStatus.DECLINED.value
    elif result.classification == ReplyClassification.MEETING_REQUESTED:
        relationship.status = RelationshipStatus.RESPONDED.value
    elif result.classification in (ReplyClassification.POSITIVE, ReplyClassification.INTERESTED):
        relationship.status = RelationshipStatus.RESPONDED.value
    elif result.classification == ReplyClassification.NOT_NOW:
        relationship.status = RelationshipStatus.NURTURE.value
    # NEEDS_FOLLOW_UP / AUTOMATED_RESPONSE / UNKNOWN: leave status + cadence as-is.

    payload = {"classification": result.classification.value, "confidence": result.confidence}
    payload.update(extra_payload or {})
    ctx.session.add(
        Activity(person_id=person.id, activity_type=ActivityType.REPLY_RECEIVED.value, payload=payload)
    )
    log_action(
        "response", "reply_classified", person=person.full_name,
        classification=result.classification.value, confidence=result.confidence,
    )


def apply_reply(ctx: AgentContext, person: Person, reply_text: str) -> ReplyClassificationResult:
    """Manual entry path: `network inbox --person-id X --reply-text '...'`
    or the web Replies form."""
    result = classify_reply(ctx, reply_text)
    _apply_classification(ctx, person, result, extra_payload={"source": "manual"})
    return result


def check_replies_for_person(ctx: AgentContext, person: Person) -> ReplyClassificationResult | None:
    """Looks at the Gmail thread of the most recently sent Outreach for
    this person, finds any message not already processed and not from us,
    and classifies+applies it. Returns None if there's nothing new (no
    thread_id -- i.e. never sent via Gmail -- or no new messages)."""
    sent_with_thread = [
        o for o in person.outreach if o.status == "SENT" and o.thread_id and o.sent_at is not None
    ]
    if not sent_with_thread:
        return None
    outreach = max(sent_with_thread, key=lambda o: o.sent_at)

    messages = ctx.email.list_thread_messages(outreach.thread_id)
    if not messages:
        return None

    sender_email = (ctx.settings.gmail_sender_email or "").lower()
    already_checked = outreach.last_reply_checked_message_id
    seen_marker = already_checked is None
    new_messages = []
    for msg in messages:
        if not seen_marker:
            if msg.message_id == already_checked:
                seen_marker = True
            continue
        if sender_email and sender_email in msg.from_address.lower():
            continue  # our own message in the thread
        new_messages.append(msg)

    if not new_messages:
        return None

    latest = new_messages[-1]
    result = classify_reply(ctx, latest.body_text)
    outreach.last_reply_checked_message_id = latest.message_id
    _apply_classification(
        ctx, person, result,
        extra_payload={"source": "gmail_thread", "message_id": latest.message_id, "from": latest.from_address},
    )
    return result


def check_all_replies(ctx: AgentContext) -> list[tuple[Person, ReplyClassificationResult]]:
    """Scans every CONTACTED/FOLLOW_UP relationship's Gmail thread for new
    replies. No-ops (returns []) when the EmailProvider has no real
    threads (ConsoleEmailProvider dry-run mode)."""
    from sqlalchemy import select

    from networking_agent.db.models import Relationship

    rows = ctx.session.execute(
        select(Relationship).where(
            Relationship.status.in_(["CONTACTED", "FOLLOW_UP_1", "FOLLOW_UP_2"])
        )
    ).scalars()
    found = []
    for relationship in rows:
        result = check_replies_for_person(ctx, relationship.person)
        if result is not None:
            found.append((relationship.person, result))
    return found
