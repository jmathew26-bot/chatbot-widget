"""SCHEDULING AGENT: proposes open meeting windows and creates calendar
events on confirmation. Checks for collisions against both the external
calendar (via CalendarProvider.list_busy) and this app's own Meeting
table, so it can never double-book even if the calendar integration isn't
configured (NullCalendarProvider) -- our own records are still authoritative
for meetings *we* created.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from networking_agent.adapters.base import TimeSlot
from networking_agent.agents.context import AgentContext
from networking_agent.db.models import Meeting, Person
from networking_agent.enums import MeetingStatus, RelationshipStatus
from networking_agent.logging_utils import log_action


class SchedulingConflictError(Exception):
    pass


def _as_utc(value: dt.datetime) -> dt.datetime:
    """SQLite has no native timezone-aware storage, so datetimes read back
    from the Meeting table come back naive even though they were written
    as UTC-aware. Normalize before comparing so this doesn't blow up (or
    silently miscompare) against timezone-aware values from calendar
    providers or caller-supplied windows."""
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def _overlaps(a_start: dt.datetime, a_end: dt.datetime, b_start: dt.datetime, b_end: dt.datetime) -> bool:
    a_start, a_end, b_start, b_end = (_as_utc(v) for v in (a_start, a_end, b_start, b_end))
    return a_start < b_end and b_start < a_end


def _existing_meeting_slots(ctx: AgentContext) -> list[TimeSlot]:
    rows = ctx.session.execute(
        select(Meeting).where(Meeting.status.in_([MeetingStatus.PROPOSED.value, MeetingStatus.SCHEDULED.value]))
    ).scalars()
    return [
        TimeSlot(start=m.scheduled_at, end=m.scheduled_at + dt.timedelta(minutes=m.duration_minutes))
        for m in rows
    ]


def is_slot_free(ctx: AgentContext, start: dt.datetime, end: dt.datetime) -> bool:
    busy = ctx.calendar.list_busy(start, end) + _existing_meeting_slots(ctx)
    return not any(_overlaps(start, end, slot.start, slot.end) for slot in busy)


def propose_slots(
    ctx: AgentContext, window_start: dt.datetime, window_end: dt.datetime, duration_minutes: int, max_slots: int = 5
) -> list[TimeSlot]:
    busy = ctx.calendar.list_busy(window_start, window_end) + _existing_meeting_slots(ctx)
    slots: list[TimeSlot] = []
    cursor = window_start
    step = dt.timedelta(minutes=30)
    duration = dt.timedelta(minutes=duration_minutes)
    while cursor + duration <= window_end and len(slots) < max_slots:
        candidate_end = cursor + duration
        if cursor.hour >= 9 and candidate_end.hour <= 18 and cursor.weekday() < 5:
            if not any(_overlaps(cursor, candidate_end, b.start, b.end) for b in busy):
                slots.append(TimeSlot(start=cursor, end=candidate_end))
        cursor += step
    return slots


def schedule_meeting(
    ctx: AgentContext,
    person: Person,
    start: dt.datetime,
    duration_minutes: int,
    meeting_type: str,
    attendee_email: str | None = None,
) -> Meeting:
    end = start + dt.timedelta(minutes=duration_minutes)
    if not is_slot_free(ctx, start, end):
        raise SchedulingConflictError(f"{start.isoformat()} conflicts with an existing commitment")

    calendar_event_id = ctx.calendar.create_event(
        title=f"Networking: {person.full_name}",
        start=start,
        end=end,
        attendee_email=attendee_email,
        description=person.networking_thesis or "",
    )
    meeting = Meeting(
        person_id=person.id,
        scheduled_at=start,
        duration_minutes=duration_minutes,
        meeting_type=meeting_type,
        calendar_event_id=calendar_event_id,
        status=MeetingStatus.SCHEDULED.value,
    )
    ctx.session.add(meeting)
    if person.relationship:
        person.relationship.status = RelationshipStatus.MEETING_SCHEDULED.value
        person.relationship.meeting_status = MeetingStatus.SCHEDULED.value
    log_action("scheduling", "meeting_scheduled", person=person.full_name, start=start.isoformat())
    return meeting
