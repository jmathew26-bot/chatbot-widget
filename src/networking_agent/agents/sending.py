"""Single choke point for actually sending an approved Outreach. Both the
CLI (`network send`) and the web dashboard's Outreach page call this --
one place enforces approval-gating, email-verification-gating, and the
daily send cap, so neither surface can drift out of sync with the other.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select

from networking_agent.adapters.base import EmailMessage
from networking_agent.agents import crm, followup
from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Activity, EmailRecord, Outreach, Person
from networking_agent.enums import ActivityType, EmailVerificationStatus, OutreachStatus
from networking_agent.logging_utils import log_action

SENDABLE_VERIFICATION_STATUSES = {
    EmailVerificationStatus.VERIFIED.value,
    EmailVerificationStatus.HIGH_CONFIDENCE.value,
}


@dataclass
class SendOutcome:
    sent: bool
    reason: str | None = None


def get_primary_email(person: Person) -> EmailRecord | None:
    for e in person.emails:
        if e.is_primary:
            return e
    return person.emails[0] if person.emails else None


def count_sent_today(session) -> int:
    start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return session.execute(
        select(func.count(Outreach.id)).where(
            Outreach.status == OutreachStatus.SENT.value, Outreach.sent_at >= start
        )
    ).scalar_one()


def daily_send_cap(ctx: AgentContext) -> int:
    if ctx.settings.live_test_mode:
        return ctx.settings.live_test_max_sends_per_day
    return ctx.settings.limits.daily_email_limit


def send_outreach(ctx: AgentContext, outreach: Outreach) -> SendOutcome:
    """Raises crm.ApprovalRequiredError if the outreach was never approved
    -- that is a programming error in the caller, not a normal skip case,
    so it is not swallowed into a SendOutcome."""
    crm.assert_approved_for_sending(outreach)

    cap = daily_send_cap(ctx)
    sent_today = count_sent_today(ctx.session)
    if sent_today >= cap:
        reason = f"daily send cap reached ({sent_today}/{cap}){' [LIVE_TEST_MODE]' if ctx.settings.live_test_mode else ''}"
        log_action("sending", "cap_reached", person=outreach.person.full_name, reason=reason)
        return SendOutcome(sent=False, reason=reason)

    person = outreach.person
    email_record = get_primary_email(person)
    if email_record is None:
        return SendOutcome(sent=False, reason="no email on file")
    if email_record.verification_status not in SENDABLE_VERIFICATION_STATUSES:
        return SendOutcome(
            sent=False,
            reason=(
                f"email verification status is {email_record.verification_status}, "
                "not VERIFIED/HIGH_CONFIDENCE"
            ),
        )

    message = EmailMessage(to_address=email_record.email_address, subject=outreach.subject, body=outreach.body)
    result = ctx.email.send(message, idempotency_key=outreach.idempotency_key)
    now = dt.datetime.now(dt.timezone.utc)

    if not result.success:
        outreach.status = OutreachStatus.FAILED.value
        log_action("sending", "send_failed", person=person.full_name, error=result.error)
        return SendOutcome(sent=False, reason=result.error or "send failed")

    outreach.status = OutreachStatus.SENT.value
    outreach.sent_at = now
    outreach.provider_message_id = result.provider_message_id
    outreach.thread_id = result.thread_id
    followup.register_sent(ctx.settings, person.relationship, outreach.sequence_number, now)
    ctx.session.add(
        Activity(person_id=person.id, activity_type=ActivityType.EMAIL_SENT.value, payload={"outreach_id": outreach.id})
    )
    log_action("sending", "sent", person=person.full_name, outreach_id=outreach.id)
    return SendOutcome(sent=True)
