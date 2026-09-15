import datetime as dt

import pytest

from networking_agent.agents import scheduling
from tests.factories import make_person


def _dt(hour, day=15):
    return dt.datetime(2026, 9, day, hour, 0, tzinfo=dt.timezone.utc)


def test_first_booking_succeeds(db_session, ctx):
    person = make_person(db_session)
    meeting = scheduling.schedule_meeting(ctx, person, _dt(10), 30, "coffee")
    assert meeting.calendar_event_id


def test_double_booking_the_same_slot_raises(db_session, ctx):
    person_a = make_person(db_session, full_name="Jane Smith", company_name="Salesforce")
    person_b = make_person(db_session, full_name="John Doe", company_name="Snowflake")
    scheduling.schedule_meeting(ctx, person_a, _dt(10), 30, "coffee")
    with pytest.raises(scheduling.SchedulingConflictError):
        scheduling.schedule_meeting(ctx, person_b, _dt(10), 30, "zoom")


def test_overlapping_but_not_identical_slot_raises(db_session, ctx):
    person_a = make_person(db_session, full_name="Jane Smith", company_name="Salesforce")
    person_b = make_person(db_session, full_name="John Doe", company_name="Snowflake")
    scheduling.schedule_meeting(ctx, person_a, _dt(10), 30, "coffee")  # 10:00-10:30
    with pytest.raises(scheduling.SchedulingConflictError):
        scheduling.schedule_meeting(ctx, person_b, _dt(10).replace(minute=15), 30, "zoom")  # 10:15-10:45


def test_back_to_back_non_overlapping_slots_both_succeed(db_session, ctx):
    person_a = make_person(db_session, full_name="Jane Smith", company_name="Salesforce")
    person_b = make_person(db_session, full_name="John Doe", company_name="Snowflake")
    scheduling.schedule_meeting(ctx, person_a, _dt(10), 30, "coffee")  # 10:00-10:30
    meeting_b = scheduling.schedule_meeting(ctx, person_b, _dt(10).replace(minute=30), 30, "zoom")  # 10:30-11:00
    assert meeting_b.calendar_event_id


def test_propose_slots_excludes_already_booked_time(db_session, ctx):
    person = make_person(db_session)
    scheduling.schedule_meeting(ctx, person, _dt(10), 30, "coffee")
    slots = scheduling.propose_slots(ctx, _dt(9), _dt(12), duration_minutes=30, max_slots=20)
    assert not any(s.start == _dt(10) for s in slots)
