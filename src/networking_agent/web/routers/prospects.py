from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.db.models import Person
from networking_agent.enums import RelationshipStatus
from networking_agent.web.deps import get_db
from networking_agent.web.templating import templates

router = APIRouter()


@router.get("/prospects")
def list_prospects(
    request: Request,
    category: str = "",
    status: str = "",
    ut_status: str = "",
    min_score: int = 0,
    sort: str = "score",
    order: str = "desc",
    session: Session = Depends(get_db),
):
    query = select(Person)
    if category:
        query = query.where(Person.category == category)
    if ut_status:
        query = query.where(Person.ut_status == ut_status)
    if min_score:
        query = query.where(Person.total_score >= min_score)

    people = session.execute(query).scalars().all()
    if status:
        people = [p for p in people if p.relationship and p.relationship.status == status]

    reverse = order != "asc"
    if sort == "name":
        people.sort(key=lambda p: p.full_name.lower(), reverse=reverse)
    elif sort == "company":
        people.sort(key=lambda p: (p.current_company.name if p.current_company else ""), reverse=reverse)
    elif sort == "status":
        people.sort(key=lambda p: (p.relationship.status if p.relationship else ""), reverse=reverse)
    else:
        people.sort(key=lambda p: p.total_score, reverse=reverse)

    statuses = [s.value for s in RelationshipStatus]
    return templates.TemplateResponse(
        request,
        "prospects.html",
        {
            "people": people,
            "category": category,
            "status": status,
            "ut_status": ut_status,
            "min_score": min_score,
            "sort": sort,
            "order": order,
            "statuses": statuses,
            "active": "prospects",
        },
    )


@router.get("/prospects/{person_id}")
def prospect_detail(request: Request, person_id: int, session: Session = Depends(get_db)):
    person = session.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return templates.TemplateResponse(request, "prospect_detail.html", {"p": person, "active": "prospects"})
