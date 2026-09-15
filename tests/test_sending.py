import pytest

from networking_agent.agents import crm, email_agent, sending
from networking_agent.db.models import EmailRecord
from tests.factories import make_person


def _approved_outreach(db_session, ctx, person):
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    crm.approve_outreach(ctx, outreach)
    return outreach


def test_send_blocked_when_no_email_on_file(db_session, ctx):
    person = make_person(db_session)
    outreach = _approved_outreach(db_session, ctx, person)

    outcome = sending.send_outreach(ctx, outreach)

    assert outcome.sent is False
    assert "no email" in outcome.reason
    assert outreach.status == "APPROVED"


def test_send_blocked_when_unverified(db_session, ctx):
    person = make_person(db_session)
    db_session.add(EmailRecord(person_id=person.id, email_address="j@x.com", is_primary=True, verification_status="UNVERIFIED"))
    db_session.flush()
    db_session.refresh(person)
    outreach = _approved_outreach(db_session, ctx, person)

    outcome = sending.send_outreach(ctx, outreach)

    assert outcome.sent is False
    assert "UNVERIFIED" in outcome.reason
    assert outreach.status == "APPROVED"


def test_send_blocked_when_bounced(db_session, ctx):
    person = make_person(db_session)
    db_session.add(EmailRecord(person_id=person.id, email_address="j@x.com", is_primary=True, verification_status="BOUNCED"))
    db_session.flush()
    db_session.refresh(person)
    outreach = _approved_outreach(db_session, ctx, person)

    outcome = sending.send_outreach(ctx, outreach)

    assert outcome.sent is False


@pytest.mark.parametrize("status", ["VERIFIED", "HIGH_CONFIDENCE"])
def test_send_succeeds_for_sendable_statuses(db_session, ctx, status):
    person = make_person(db_session)
    db_session.add(EmailRecord(person_id=person.id, email_address="j@x.com", is_primary=True, verification_status=status))
    db_session.flush()
    db_session.refresh(person)
    outreach = _approved_outreach(db_session, ctx, person)

    outcome = sending.send_outreach(ctx, outreach)

    assert outcome.sent is True
    assert outreach.status == "SENT"
    assert outreach.sent_at is not None


def test_send_records_thread_id_from_provider(db_session, ctx):
    person = make_person(db_session)
    db_session.add(EmailRecord(person_id=person.id, email_address="j@x.com", is_primary=True, verification_status="VERIFIED"))
    db_session.flush()
    db_session.refresh(person)
    outreach = _approved_outreach(db_session, ctx, person)

    sending.send_outreach(ctx, outreach)

    assert outreach.thread_id == f"thread-{outreach.idempotency_key}"


def test_send_registers_followup_cadence(db_session, ctx):
    person = make_person(db_session)
    db_session.add(EmailRecord(person_id=person.id, email_address="j@x.com", is_primary=True, verification_status="VERIFIED"))
    db_session.flush()
    db_session.refresh(person)
    outreach = _approved_outreach(db_session, ctx, person)

    sending.send_outreach(ctx, outreach)

    assert person.relationship.status == "CONTACTED"
    assert person.relationship.next_action_date is not None


def test_daily_send_cap_blocks_after_limit(db_session, ctx):
    ctx.settings.limits.daily_email_limit = 2
    outreaches = []
    for i in range(3):
        person = make_person(db_session, full_name=f"Person {i}", company_name="Salesforce")
        db_session.add(EmailRecord(person_id=person.id, email_address=f"p{i}@x.com", is_primary=True, verification_status="VERIFIED"))
        db_session.flush()
        db_session.refresh(person)
        outreaches.append(_approved_outreach(db_session, ctx, person))

    outcomes = [sending.send_outreach(ctx, o) for o in outreaches]

    assert [o.sent for o in outcomes] == [True, True, False]
    assert "cap" in outcomes[-1].reason


def test_live_test_mode_caps_sends_at_5_even_if_config_allows_more(db_session, ctx):
    ctx.settings.limits.daily_email_limit = 100  # would normally allow plenty
    ctx.settings.live_test_mode = True
    outreaches = []
    for i in range(6):
        person = make_person(db_session, full_name=f"Person {i}", company_name="Salesforce")
        db_session.add(EmailRecord(person_id=person.id, email_address=f"p{i}@x.com", is_primary=True, verification_status="VERIFIED"))
        db_session.flush()
        db_session.refresh(person)
        outreaches.append(_approved_outreach(db_session, ctx, person))

    outcomes = [sending.send_outreach(ctx, o) for o in outreaches]

    assert sum(1 for o in outcomes if o.sent) == 5
    assert "LIVE_TEST_MODE" in outcomes[-1].reason


def test_send_outreach_raises_on_unapproved(db_session, ctx):
    person = make_person(db_session)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)  # still DRAFT

    with pytest.raises(crm.ApprovalRequiredError):
        sending.send_outreach(ctx, outreach)
