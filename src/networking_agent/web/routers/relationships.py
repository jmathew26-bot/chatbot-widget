from __future__ import annotations

import datetime as dt
from collections import Counter

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.agents import crm
from networking_agent.db.models import Person
from networking_agent.web.deps import get_ctx, get_db
from networking_agent.web.templating import templates

router = APIRouter()


@router.get("/relationships")
def list_relationships(request: Request, session: Session = Depends(get_db)):
    people = session.execute(select(Person)).scalars().all()
    status_counts = Counter(p.relationship.status for p in people if p.relationship)
    def sort_key(p: Person) -> dt.datetime:
        if not p.relationship:
            return dt.datetime.min
        return p.relationship.last_contact or p.relationship.date_discovered or dt.datetime.min

    people = sorted(people, key=sort_key, reverse=True)
    return templates.TemplateResponse(
        request, "relationships.html", {"people": people, "status_counts": status_counts, "active": "relationships"}
    )


@router.post("/relationships/{person_id}/note")
def add_note(person_id: int, note: str = Form(...), session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    person = session.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if note.strip():
        crm.add_note(ctx, person, note.strip())
    return RedirectResponse(url=f"/prospects/{person_id}", status_code=303)
