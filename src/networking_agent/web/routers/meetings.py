from __future__ import annotations

import datetime as dt
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.agents import scheduling
from networking_agent.db.models import Meeting, Person
from networking_agent.web.deps import get_ctx, get_db
from networking_agent.web.templating import templates

router = APIRouter()


@router.get("/meetings")
def list_meetings(
    request: Request,
    person_id: int | None = None,
    days_ahead: int = 7,
    duration: int | None = None,
    error: str = "",
    session: Session = Depends(get_db),
):
    ctx = get_ctx(session)
    meetings = session.execute(select(Meeting).order_by(Meeting.scheduled_at.desc())).scalars().all()
    people = session.execute(select(Person).where(Person.excluded.is_(False)).order_by(Person.full_name)).scalars().all()

    slots = []
    selected_person = None
    if person_id:
        selected_person = session.get(Person, person_id)
        duration = duration or ctx.settings.meetings.default_duration_minutes
        window_start = dt.datetime.now(dt.timezone.utc)
        window_end = window_start + dt.timedelta(days=days_ahead)
        slots = scheduling.propose_slots(ctx, window_start, window_end, duration)

    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "meetings": meetings, "people": people, "slots": slots,
            "person_id": person_id, "selected_person": selected_person,
            "days_ahead": days_ahead, "duration": duration or ctx.settings.meetings.default_duration_minutes,
            "error": error, "meeting_types": ctx.settings.meetings.austin_meeting_types,
            "active": "meetings",
        },
    )


@router.post("/meetings/schedule")
def schedule_meeting(
    person_id: int = Form(...),
    start: str = Form(...),
    duration: int = Form(...),
    meeting_type: str = Form(...),
    session: Session = Depends(get_db),
):
    ctx = get_ctx(session)
    person = session.get(Person, person_id)
    if person is None:
        return RedirectResponse(url="/meetings", status_code=303)
    email_record = next((e for e in person.emails if e.is_primary), None)
    try:
        scheduling.schedule_meeting(
            ctx, person, dt.datetime.fromisoformat(start), duration, meeting_type,
            attendee_email=email_record.email_address if email_record else None,
        )
    except scheduling.SchedulingConflictError as e:
        return RedirectResponse(url=f"/meetings?person_id={person_id}&error={quote(str(e))}", status_code=303)
    return RedirectResponse(url="/meetings", status_code=303)
