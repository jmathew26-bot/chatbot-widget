from __future__ import annotations

from urllib.parse import quote

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
def list_replies(request: Request, message: str = "", session: Session = Depends(get_db)):
    contacted = session.execute(
        select(Person).where(Person.excluded.is_(False))
    ).scalars().all()
    contacted = [p for p in contacted if p.relationship and p.relationship.date_first_contacted]

    recent_activity = session.execute(
        select(Activity).where(Activity.activity_type == ActivityType.REPLY_RECEIVED.value)
        .order_by(Activity.created_at.desc()).limit(20)
    ).scalars().all()
    return templates.TemplateResponse(
        request, "replies.html",
        {"contacted": contacted, "recent_activity": recent_activity, "active": "replies", "message": message},
    )


@router.post("/replies/check")
def check_replies(session: Session = Depends(get_db)):
    """Scans Gmail threads for every contacted person for new replies.
    No-ops safely if Gmail isn't configured (ConsoleEmailProvider has no
    real threads)."""
    ctx = get_ctx(session)
    found = response.check_all_replies(ctx)
    if found:
        msg = "; ".join(f"{p.full_name}: {r.classification.value}" for p, r in found)
    else:
        msg = "No new replies found (requires Gmail credentials to scan threads)."
    return RedirectResponse(url=f"/replies?message={quote(msg)}", status_code=303)


@router.post("/replies/classify")
def classify(person_id: int = Form(...), reply_text: str = Form(...), session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    person = session.get(Person, person_id)
    msg = ""
    if person is not None and reply_text.strip():
        result = response.apply_reply(ctx, person, reply_text)
        msg = f"Classified as {result.classification.value}"
    return RedirectResponse(url=f"/replies?message={quote(msg)}", status_code=303)
