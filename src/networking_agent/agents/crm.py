"""CRM AGENT: owns Relationship state transitions and Activity logging.
This is the single place that enforces the relationship state machine and
-- critically -- the "only APPROVE allows sending" rule from the design
doc. agents/response.py and agents/scheduling.py also transition state
directly for their own concerns (reply classification, meeting booked);
this module is for the discover -> review -> send lifecycle.
"""
from __future__ import annotations

import datetime as dt

from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Activity, Outreach, Person, Relationship
from networking_agent.enums import ActivityType, OutreachStatus, RelationshipStatus, UTStatus
from networking_agent.logging_utils import log_action


class ApprovalRequiredError(Exception):
    """Raised if code ever attempts to send an Outreach that a human has
    not explicitly approved. This must never be caught-and-ignored."""


def _log_status_change(ctx: AgentContext, person: Person, old_status: str, new_status: str, reason: str) -> None:
    ctx.session.add(
        Activity(
            person_id=person.id,
            activity_type=ActivityType.STATUS_CHANGE.value,
            payload={"from": old_status, "to": new_status, "reason": reason},
        )
    )
    log_action("crm", "status_change", person=person.full_name, old=old_status, new=new_status, reason=reason)


def promote_after_scoring(ctx: AgentContext, person: Person) -> None:
    """VERIFIED + above the review threshold -> enters the review queue
    automatically. LIKELY -> stays RESEARCHED, needs an explicit manual
    pull into review (see `network review --include-likely`). Everything
    else never auto-queues."""
    relationship = person.relationship
    old_status = relationship.status
    review_threshold = ctx.settings.scoring.thresholds.get("review", 60)

    if person.excluded:
        relationship.status = RelationshipStatus.DO_NOT_CONTACT.value
    elif person.total_score < review_threshold:
        relationship.status = RelationshipStatus.RESEARCHED.value
    elif UTStatus(person.ut_status) == UTStatus.VERIFIED:
        relationship.status = RelationshipStatus.READY_FOR_REVIEW.value
    else:
        relationship.status = RelationshipStatus.RESEARCHED.value

    if relationship.status != old_status:
        _log_status_change(ctx, person, old_status, relationship.status, "post-scoring promotion")


def include_for_manual_review(ctx: AgentContext, person: Person) -> None:
    """Explicit human opt-in to review a LIKELY (or otherwise non-auto-queued)
    prospect. Does not bypass the review threshold."""
    relationship = person.relationship
    old_status = relationship.status
    relationship.status = RelationshipStatus.READY_FOR_REVIEW.value
    _log_status_change(ctx, person, old_status, relationship.status, "manual review pull")


def approve_outreach(ctx: AgentContext, outreach: Outreach) -> None:
    outreach.status = OutreachStatus.APPROVED.value
    outreach.approved_at = dt.datetime.now(dt.timezone.utc)
    person = outreach.person
    old_status = person.relationship.status
    person.relationship.status = RelationshipStatus.APPROVED.value
    _log_status_change(ctx, person, old_status, person.relationship.status, "outreach approved")


def edit_outreach(ctx: AgentContext, outreach: Outreach, subject: str, body: str) -> None:
    outreach.subject = subject
    outreach.body = body
    outreach.status = OutreachStatus.EDITED.value
    log_action("crm", "outreach_edited", person=outreach.person.full_name, outreach_id=outreach.id)


def skip_outreach(ctx: AgentContext, outreach: Outreach) -> None:
    outreach.status = OutreachStatus.SKIPPED.value
    log_action("crm", "outreach_skipped", person=outreach.person.full_name, outreach_id=outreach.id)


def block_person(ctx: AgentContext, person: Person, reason: str) -> None:
    person.excluded = True
    person.exclusion_reason = reason
    old_status = person.relationship.status
    person.relationship.status = RelationshipStatus.BLOCKED.value
    for outreach in person.outreach:
        if outreach.status in (OutreachStatus.DRAFT.value, OutreachStatus.EDITED.value):
            outreach.status = OutreachStatus.BLOCKED.value
    _log_status_change(ctx, person, old_status, person.relationship.status, f"blocked: {reason}")


def assert_approved_for_sending(outreach: Outreach) -> None:
    if outreach.status not in (OutreachStatus.APPROVED.value, OutreachStatus.EDITED.value):
        raise ApprovalRequiredError(
            f"Outreach {outreach.id} has status={outreach.status!r}; only APPROVED/EDITED "
            f"(human-reviewed) outreach may be sent."
        )
    relationship = outreach.person.relationship
    if relationship.status == RelationshipStatus.DO_NOT_CONTACT.value or outreach.person.excluded:
        raise ApprovalRequiredError(f"Person {outreach.person.full_name} is blocked/do-not-contact.")


def add_note(ctx: AgentContext, person: Person, note: str) -> None:
    ctx.session.add(Activity(person_id=person.id, activity_type=ActivityType.MANUAL_NOTE.value, payload={"note": note}))
    if person.relationship.notes:
        person.relationship.notes += f"\n{note}"
    else:
        person.relationship.notes = note
    log_action("crm", "note_added", person=person.full_name)
