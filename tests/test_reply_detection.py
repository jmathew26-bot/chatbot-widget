from networking_agent.agents import crm, email_agent, response, sending
from networking_agent.db.models import EmailRecord
from tests.factories import make_person


def _send_to(db_session, ctx, person):
    db_session.add(EmailRecord(person_id=person.id, email_address="jane@x.com", is_primary=True, verification_status="VERIFIED"))
    db_session.flush()
    db_session.refresh(person)
    outreach, _ = email_agent.draft_email(ctx, person, sequence_number=1)
    crm.approve_outreach(ctx, outreach)
    outcome = sending.send_outreach(ctx, outreach)
    assert outcome.sent
    return outreach


def test_check_replies_for_person_returns_none_without_thread(db_session, ctx):
    person = make_person(db_session)
    assert response.check_replies_for_person(ctx, person) is None


def test_check_replies_detects_and_classifies_new_message(db_session, ctx):
    person = make_person(db_session)
    outreach = _send_to(db_session, ctx, person)

    ctx.email.add_reply(outreach.thread_id, "jane@x.com", "Sounds good, I'd love to grab coffee!")

    result = response.check_replies_for_person(ctx, person)

    assert result is not None
    assert result.classification.value in ("POSITIVE", "INTERESTED")
    assert person.relationship.status == "RESPONDED"
    assert person.relationship.next_action_date is None  # follow-ups cancelled


def test_check_replies_ignores_messages_from_our_own_address(db_session, ctx):
    ctx.settings.gmail_sender_email = "me@mycompany.com"
    person = make_person(db_session)
    outreach = _send_to(db_session, ctx, person)

    ctx.email.add_reply(outreach.thread_id, "Me <me@mycompany.com>", "just a note to self")

    result = response.check_replies_for_person(ctx, person)

    assert result is None


def test_check_replies_does_not_reprocess_same_message(db_session, ctx):
    person = make_person(db_session)
    outreach = _send_to(db_session, ctx, person)
    ctx.email.add_reply(outreach.thread_id, "jane@x.com", "Not interested right now.")

    first = response.check_replies_for_person(ctx, person)
    second = response.check_replies_for_person(ctx, person)

    assert first is not None
    assert second is None  # nothing new since last check


def test_check_replies_processes_only_new_messages_on_second_check(db_session, ctx):
    person = make_person(db_session)
    outreach = _send_to(db_session, ctx, person)
    ctx.email.add_reply(outreach.thread_id, "jane@x.com", "Let me think about it, thanks for reaching out.")
    response.check_replies_for_person(ctx, person)

    ctx.email.add_reply(outreach.thread_id, "jane@x.com", "Actually, do not contact me again.")
    result = response.check_replies_for_person(ctx, person)

    assert result is not None
    assert result.classification.value == "DO_NOT_CONTACT"


def test_check_all_replies_scans_contacted_relationships(db_session, ctx):
    person = make_person(db_session)
    outreach = _send_to(db_session, ctx, person)
    ctx.email.add_reply(outreach.thread_id, "jane@x.com", "Sounds great, happy to chat!")

    found = response.check_all_replies(ctx)

    assert len(found) == 1
    assert found[0][0].id == person.id
