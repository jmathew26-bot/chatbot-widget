"""ANALYTICS AGENT: measures effectiveness. Everything here is read-only
aggregation over the DB -- it never optimizes for volume, only surfaces
response/meeting rates so a human can decide where to invest attention
(design doc: "Optimize toward MEETINGS WITH HIGH-VALUE PEOPLE.").
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from networking_agent.db.models import Company, Meeting, Outreach, Person, Relationship
from networking_agent.enums import OutreachStatus


def _today_range() -> tuple[dt.datetime, dt.datetime]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + dt.timedelta(days=1)


def _week_range() -> tuple[dt.datetime, dt.datetime]:
    now = dt.datetime.now(dt.timezone.utc)
    return now - dt.timedelta(days=7), now + dt.timedelta(days=7)


def morning_brief(session: Session) -> dict:
    today_start, today_end = _today_range()
    week_start, week_end = _week_range()

    new_prospects = session.execute(
        select(func.count(Person.id)).where(Person.created_at >= today_start, Person.created_at < today_end)
    ).scalar_one()
    high_priority = session.execute(
        select(func.count(Person.id)).where(Person.total_score >= 80, Person.excluded.is_(False))
    ).scalar_one()
    awaiting_approval = session.execute(
        select(func.count(Outreach.id)).where(Outreach.status == OutreachStatus.DRAFT.value)
    ).scalar_one()
    followups_due = session.execute(
        select(func.count(Relationship.id)).where(
            Relationship.next_action_date.is_not(None), Relationship.next_action_date <= dt.datetime.now(dt.timezone.utc)
        )
    ).scalar_one()
    replies_received = session.execute(
        select(func.count(Relationship.id)).where(
            Relationship.reply_status.is_not(None), Relationship.last_contact >= today_start
        )
    ).scalar_one()
    meetings_this_week = session.execute(
        select(func.count(Meeting.id)).where(Meeting.scheduled_at >= week_start, Meeting.scheduled_at <= week_end)
    ).scalar_one()

    return {
        "new_prospects_discovered": new_prospects,
        "high_priority": high_priority,
        "emails_awaiting_approval": awaiting_approval,
        "followups_due": followups_due,
        "replies_received_today": replies_received,
        "meetings_scheduled_this_week": meetings_this_week,
    }


def response_rate_by_field(session: Session, field_getter, sent_only: bool = True) -> dict[str, dict]:
    """Generic grouped response-rate calculation. field_getter(person) ->
    the bucket key (e.g. person.category, person.current_title, seniority
    bucket, person.location, ut_grad_year bucket)."""
    outreach_rows = session.execute(
        select(Outreach).where(Outreach.status == OutreachStatus.SENT.value)
    ).scalars()

    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"sent": 0, "replied": 0, "positive": 0, "meetings": 0})
    for outreach in outreach_rows:
        person = outreach.person
        key = str(field_getter(person)) or "UNKNOWN"
        buckets[key]["sent"] += 1
        rel = person.relationship
        if rel and rel.reply_status:
            buckets[key]["replied"] += 1
            if rel.reply_status in ("POSITIVE", "INTERESTED", "MEETING_REQUESTED"):
                buckets[key]["positive"] += 1
        if rel and rel.meeting_status == "SCHEDULED":
            buckets[key]["meetings"] += 1

    out = {}
    for key, counts in buckets.items():
        sent = counts["sent"] or 1
        out[key] = {
            **counts,
            "response_rate": round(counts["replied"] / sent, 3),
            "meeting_rate": round(counts["meetings"] / sent, 3),
        }
    return out


def response_rate_by_industry(session: Session) -> dict:
    return response_rate_by_field(session, lambda p: p.industry)


def response_rate_by_title(session: Session) -> dict:
    return response_rate_by_field(session, lambda p: p.current_title)


def response_rate_by_category(session: Session) -> dict:
    return response_rate_by_field(session, lambda p: p.category)


def response_rate_by_geography(session: Session) -> dict:
    return response_rate_by_field(session, lambda p: p.location)


def response_rate_by_ut_grad_period(session: Session) -> dict:
    def bucket(p: Person) -> str:
        if not p.ut_grad_year:
            return "UNKNOWN"
        decade = (p.ut_grad_year // 5) * 5
        return f"{decade}-{decade + 4}"

    return response_rate_by_field(session, bucket)


def response_rate_by_template(session: Session) -> dict:
    outreach_rows = session.execute(
        select(Outreach).where(Outreach.status == OutreachStatus.SENT.value)
    ).scalars()
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"sent": 0, "replied": 0})
    for outreach in outreach_rows:
        key = outreach.template_tag or "UNKNOWN"
        buckets[key]["sent"] += 1
        rel = outreach.person.relationship
        if rel and rel.reply_status:
            buckets[key]["replied"] += 1
    return {
        k: {**v, "response_rate": round(v["replied"] / (v["sent"] or 1), 3)} for k, v in buckets.items()
    }


def company_leaderboard(session: Session) -> list[dict]:
    companies = session.execute(select(Company).order_by(Company.quality_score.desc())).scalars()
    return [
        {"name": c.name, "category": c.category, "quality_score": c.quality_score, "people_count": len(c.people)}
        for c in companies
    ]
