from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.agents import crm, email_agent, sending
from networking_agent.db.models import Outreach, Person, Relationship
from networking_agent.enums import OutreachStatus, RelationshipStatus
from networking_agent.web.deps import get_ctx, get_db
from networking_agent.web.templating import templates

router = APIRouter()


def _get_outreach_or_404(session: Session, outreach_id: int) -> Outreach:
    outreach = session.get(Outreach, outreach_id)
    if outreach is None:
        raise HTTPException(status_code=404, detail="Outreach not found")
    return outreach


@router.get("/outreach")
def list_outreach(request: Request, message: str = "", session: Session = Depends(get_db)):
    pending = session.execute(
        select(Outreach).where(Outreach.status.in_([OutreachStatus.DRAFT.value, OutreachStatus.EDITED.value, OutreachStatus.APPROVED.value]))
        .order_by(Outreach.created_at.desc())
    ).scalars().all()
    ready_no_draft = session.execute(
        select(Person).join(Relationship).where(
            Relationship.status == RelationshipStatus.READY_FOR_REVIEW.value
        )
    ).scalars().all()
    ready_no_draft = [p for p in ready_no_draft if not any(o.sequence_number == 1 for o in p.outreach)]
    sent = session.execute(
        select(Outreach).where(Outreach.status == OutreachStatus.SENT.value).order_by(Outreach.sent_at.desc()).limit(20)
    ).scalars().all()
    return templates.TemplateResponse(
        request, "outreach.html",
        {"pending": pending, "ready_no_draft": ready_no_draft, "sent": sent, "active": "outreach", "message": message},
    )


@router.post("/outreach/draft/{person_id}")
def draft_for_person(person_id: int, session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    person = session.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    email_agent.draft_email(ctx, person, sequence_number=1)
    return RedirectResponse(url="/outreach", status_code=303)


@router.post("/outreach/{outreach_id}/approve")
def approve(outreach_id: int, session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    outreach = _get_outreach_or_404(session, outreach_id)
    crm.approve_outreach(ctx, outreach)
    return RedirectResponse(url="/outreach", status_code=303)


@router.post("/outreach/{outreach_id}/edit")
def edit(
    outreach_id: int,
    subject: str = Form(...),
    body: str = Form(...),
    approve_now: str = Form(""),
    session: Session = Depends(get_db),
):
    ctx = get_ctx(session)
    outreach = _get_outreach_or_404(session, outreach_id)
    crm.edit_outreach(ctx, outreach, subject, body)
    if approve_now == "on":
        crm.approve_outreach(ctx, outreach)
    return RedirectResponse(url="/outreach", status_code=303)


@router.post("/outreach/{outreach_id}/skip")
def skip(outreach_id: int, session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    outreach = _get_outreach_or_404(session, outreach_id)
    crm.skip_outreach(ctx, outreach)
    return RedirectResponse(url="/outreach", status_code=303)


@router.post("/outreach/{outreach_id}/block")
def block(outreach_id: int, reason: str = Form("not a fit"), session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    outreach = _get_outreach_or_404(session, outreach_id)
    crm.block_person(ctx, outreach.person, reason)
    return RedirectResponse(url="/outreach", status_code=303)


@router.post("/outreach/{outreach_id}/send")
def send_one(outreach_id: int, session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    outreach = _get_outreach_or_404(session, outreach_id)
    outcome = sending.send_outreach(ctx, outreach)
    msg = "Sent." if outcome.sent else f"Not sent: {outcome.reason}"
    return RedirectResponse(url=f"/outreach?message={quote(msg)}", status_code=303)


@router.post("/outreach/send-all")
def send_all(session: Session = Depends(get_db)):
    ctx = get_ctx(session)
    pending = session.execute(
        select(Outreach).where(Outreach.status.in_([OutreachStatus.APPROVED.value, OutreachStatus.EDITED.value]))
    ).scalars().all()
    sent_count = 0
    skipped: list[str] = []
    for outreach in pending:
        outcome = sending.send_outreach(ctx, outreach)
        if outcome.sent:
            sent_count += 1
        else:
            skipped.append(f"{outreach.person.full_name} ({outcome.reason})")
    msg = f"Sent {sent_count}/{len(pending)}."
    if skipped:
        msg += " Skipped: " + "; ".join(skipped)
    return RedirectResponse(url=f"/outreach?message={quote(msg)}", status_code=303)
