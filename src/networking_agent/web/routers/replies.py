from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.agents import response
from networking_agent.db.models import Activity, Person
from networking_agent.enums import ActivityType
from networking_agent.web.deps import get_ctx, get_db
from networking_agent.web.templating import templates

router = APIRouter()


@router.get("/replies")
def list_replies(request: Request, session: Session = Depends(get_db)):
    contacted = session.execute(
        select(Person).where(Person.excluded.is_(False))
    ).scalars().all()
    contacted = [p for p in contacted if p.relationship and p.relationship.date_first_contacted]

    recent_activity = session.execute(
        select(Activity).where(Activity.activity_type == ActivityType.REPLY_RECEIVED.value)
        .order_by(Activity.created_at.desc()).limit(20)
    ).scalars().all()
    return templates.TemplateResponse(
        request, "replies.html", {"contacted": contacted, "recent_activity": recent_activity, "active": "replies"}
    )


@router.post("/replies/classify")
def classify(person_id: int = Form(...), reply_text: str = Form(...), session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    person = session.get(Person, person_id)
    if person is not None and reply_text.strip():
        response.apply_reply(ctx, person, reply_text)
    return RedirectResponse(url="/replies", status_code=303)
