"""FOLLOW-UP AGENT: computes and enforces the outreach cadence. Max 3
total attempts (initial + 2 follow-ups), ~5 business days then ~7-10
business days, and an immediate, permanent stop the moment a reply of any
kind arrives (that part is enforced by the Response Agent calling
cancel_followups()).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from networking_agent.config import Settings
from networking_agent.db.models import Person, Relationship
from networking_agent.enums import RelationshipStatus
from networking_agent.logging_utils import log_action
from networking_agent.services.cadence import add_business_days


def compute_next_action_date(
    settings: Settings, attempts_count: int, from_time: dt.datetime
) -> dt.datetime | None:
    cfg = settings.followups
    if attempts_count <= 0 or attempts_count >= cfg.max_total_attempts:
        return None
    if attempts_count == 1:
        return add_business_days(from_time, cfg.followup_1_business_days)
    if attempts_count == 2:
        return add_business_days(from_time, cfg.followup_2_business_days_after_followup_1)
    return None


_STATUS_BY_SEQUENCE = {
    1: RelationshipStatus.CONTACTED,
    2: RelationshipStatus.FOLLOW_UP_1,
    3: RelationshipStatus.FOLLOW_UP_2,
}


def register_sent(settings: Settings, relationship: Relationship, sequence_number: int, sent_at: dt.datetime) -> None:
    relationship.attempts_count = sequence_number
    relationship.last_contact = sent_at
    if sequence_number == 1:
        relationship.date_first_contacted = sent_at
    relationship.status = _STATUS_BY_SEQUENCE.get(sequence_number, relationship.status).value
    relationship.next_action_date = compute_next_action_date(settings, sequence_number, sent_at)


def cancel_followups(relationship: Relationship, reason: str) -> None:
    relationship.next_action_date = None
    log_action("followup", "followups_cancelled", person=str(relationship.person_id), reason=reason)


def get_due_followups(session, settings: Settings, as_of: dt.datetime | None = None) -> list[Person]:
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    eligible_statuses = {RelationshipStatus.CONTACTED.value, RelationshipStatus.FOLLOW_UP_1.value}
    rows = session.execute(
        select(Relationship).where(
            Relationship.next_action_date.is_not(None),
            Relationship.next_action_date <= as_of,
            Relationship.status.in_(eligible_statuses),
            Relationship.attempts_count < settings.followups.max_total_attempts,
        )
    ).scalars()
    return [r.person for r in rows]


def mark_exhausted_no_response(session, settings: Settings, as_of: dt.datetime | None = None) -> list[Person]:
    """After the final follow-up's window has passed with no reply, stop
    (design doc: 'If there is no response after that, mark NO RESPONSE.
    Do not continue indefinitely.')."""
    as_of = as_of or dt.datetime.now(dt.timezone.utc)
    rows = session.execute(
        select(Relationship).where(
            Relationship.status == RelationshipStatus.FOLLOW_UP_2.value,
            Relationship.reply_status.is_(None),
            Relationship.attempts_count >= settings.followups.max_total_attempts,
            Relationship.next_action_date.is_(None),
        )
    ).scalars()
    updated = []
    for rel in rows:
        cutoff = add_business_days(
            rel.last_contact, settings.followups.followup_2_business_days_after_followup_1
        )
        if as_of >= cutoff:
            rel.status = RelationshipStatus.NO_RESPONSE.value
            updated.append(rel.person)
            log_action("followup", "no_response", person=rel.person.full_name)
    return updated
