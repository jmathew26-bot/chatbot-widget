import datetime as dt

from networking_agent.agents import followup, response
from networking_agent.enums import RelationshipStatus
from tests.factories import make_person


def test_register_sent_schedules_followup_1(db_session, ctx, test_settings):
    person = make_person(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    followup.register_sent(test_settings, person.relationship, sequence_number=1, sent_at=now)
    assert person.relationship.status == RelationshipStatus.CONTACTED.value
    assert person.relationship.next_action_date is not None
    assert person.relationship.next_action_date > now


def test_register_sent_third_attempt_schedules_no_more_followups(db_session, ctx, test_settings):
    person = make_person(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    followup.register_sent(test_settings, person.relationship, sequence_number=3, sent_at=now)
    assert person.relationship.next_action_date is None


def test_positive_reply_cancels_pending_followups(db_session, ctx):
    person = make_person(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    followup.register_sent(ctx.settings, person.relationship, sequence_number=1, sent_at=now)
    assert person.relationship.next_action_date is not None

    response.apply_reply(ctx, person, "Sounds good, I'd love to grab coffee!")

    assert person.relationship.next_action_date is None
    assert person.relationship.status == RelationshipStatus.RESPONDED.value


def test_decline_reply_cancels_followups_and_marks_declined(db_session, ctx):
    person = make_person(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    followup.register_sent(ctx.settings, person.relationship, sequence_number=1, sent_at=now)

    response.apply_reply(ctx, person, "Thanks but I'm not interested right now.")

    assert person.relationship.next_action_date is None
    assert person.relationship.status == RelationshipStatus.DECLINED.value


def test_do_not_contact_reply_marks_email_do_not_contact(db_session, ctx):
    from networking_agent.db.models import EmailRecord

    person = make_person(db_session)
    person.emails.append(EmailRecord(person_id=person.id, email_address="jane@example.com", is_primary=True))
    db_session.flush()
    now = dt.datetime.now(dt.timezone.utc)
    followup.register_sent(ctx.settings, person.relationship, sequence_number=1, sent_at=now)

    response.apply_reply(ctx, person, "Please do not contact me again.")

    assert person.relationship.status == RelationshipStatus.DO_NOT_CONTACT.value
    assert person.relationship.next_action_date is None
    assert person.emails[0].verification_status == "DO_NOT_CONTACT"


def test_needs_follow_up_classification_does_not_cancel_cadence(db_session, ctx):
    person = make_person(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    followup.register_sent(ctx.settings, person.relationship, sequence_number=1, sent_at=now)
    next_date_before = person.relationship.next_action_date

    # Ambiguous text that the heuristic classifier can't confidently place ->
    # UNKNOWN, which must NOT silently cancel a pending follow-up.
    response.apply_reply(ctx, person, "Thanks for reaching out.")

    assert person.relationship.next_action_date == next_date_before


def test_get_due_followups_only_returns_past_due(db_session, ctx):
    person_due = make_person(db_session, full_name="Jane Smith", company_name="Salesforce")
    person_future = make_person(db_session, full_name="John Doe", company_name="Snowflake")
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)

    followup.register_sent(ctx.settings, person_due.relationship, 1, past - dt.timedelta(days=10))
    person_due.relationship.next_action_date = past
    followup.register_sent(ctx.settings, person_future.relationship, 1, dt.datetime.now(dt.timezone.utc))
    person_future.relationship.next_action_date = future
    db_session.flush()

    due = followup.get_due_followups(db_session, ctx.settings)
    assert person_due in due
    assert person_future not in due


def test_max_three_attempts_enforced(test_settings):
    assert test_settings.followups.max_total_attempts == 3
    now = dt.datetime.now(dt.timezone.utc)
    assert followup.compute_next_action_date(test_settings, 3, now) is None
