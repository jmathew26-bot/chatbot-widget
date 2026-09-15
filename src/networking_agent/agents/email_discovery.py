"""Email discovery: finds a professional work email for a person via the
configured PeopleDataProvider, then upgrades its confidence via the
configured EmailVerificationProvider. Never guesses -- if PeopleDataProvider
returns nothing (no provider configured, or the provider found nothing),
no EmailRecord is created and the person simply has no email on file until
one is added manually or a provider is configured.

Only VERIFIED/HIGH_CONFIDENCE records are allowed into the send queue --
see crm.assert_approved_for_sending's callers in cli.py/web/routers/outreach.py.
"""
from __future__ import annotations

from networking_agent.agents.context import AgentContext
from networking_agent.db.models import EmailRecord, Person
from networking_agent.enums import EmailVerificationStatus
from networking_agent.logging_utils import log_action
from networking_agent.services.companies import guess_domain

_STATUS_RANK = {
    EmailVerificationStatus.DO_NOT_CONTACT.value: -1,
    EmailVerificationStatus.BOUNCED.value: -1,
    EmailVerificationStatus.UNVERIFIED.value: 0,
    EmailVerificationStatus.HIGH_CONFIDENCE.value: 1,
    EmailVerificationStatus.VERIFIED.value: 2,
}


def _better_status(a: str, b: str) -> str:
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b


def discover_email(ctx: AgentContext, person: Person) -> EmailRecord | None:
    if any(e.is_primary for e in person.emails):
        return None  # already has one on file; don't overwrite a manual entry

    company = person.current_company
    if company is None:
        log_action("email_discovery", "skipped_no_company", person=person.full_name)
        return None

    domain = guess_domain(company)
    found = ctx.people_data.find_email(person.full_name, company.name, domain)
    if found is None:
        log_action("email_discovery", "not_found", person=person.full_name, source="none")
        return None

    verification_status = found.verification_status
    if verification_status not in (EmailVerificationStatus.VERIFIED.value,):
        mx_status = ctx.email_verification.verify(found.email)
        verification_status = _better_status(verification_status, mx_status)

    record = EmailRecord(
        person_id=person.id,
        email_address=found.email,
        source=found.source,
        confidence=found.confidence,
        verification_status=verification_status,
        is_primary=True,
    )
    ctx.session.add(record)
    ctx.session.flush()
    log_action(
        "email_discovery", "email_found", person=person.full_name, source=found.source,
        verification_status=verification_status,
    )
    return record
