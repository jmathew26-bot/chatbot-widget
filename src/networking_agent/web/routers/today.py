from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.agents import analytics, followup
from networking_agent.db.models import Person
from networking_agent.web.deps import get_ctx, get_db
from networking_agent.web.templating import templates

router = APIRouter()


@router.get("/")
def root(request: Request):
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/today")


@router.get("/today")
def today(request: Request, session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    brief = analytics.morning_brief(session)
    due_people = followup.get_due_followups(session, ctx.settings)
    top = session.execute(
        select(Person).where(Person.excluded.is_(False)).order_by(Person.total_score.desc()).limit(8)
    ).scalars().all()
    return templates.TemplateResponse(
        request, "today.html", {"brief": brief, "due_people": due_people, "top": top, "active": "today"}
    )
