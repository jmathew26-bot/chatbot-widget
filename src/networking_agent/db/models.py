from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from networking_agent.db.base import Base
from networking_agent.enums import (
    ActivityType,
    Category,
    EmailVerificationStatus,
    MeetingStatus,
    MeetingType,
    OutreachStatus,
    RelationshipStatus,
    ReplyClassification,
    UTStatus,
)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    industry: Mapped[str | None] = mapped_column(String(255), default=None)
    category: Mapped[str | None] = mapped_column(String(32), default=None)  # Category
    size_estimate: Mapped[str | None] = mapped_column(String(64), default=None)
    headquarters: Mapped[str | None] = mapped_column(String(255), default=None)
    austin_presence: Mapped[bool] = mapped_column(Boolean, default=False)
    texas_presence: Mapped[bool] = mapped_column(Boolean, default=False)
    website: Mapped[str | None] = mapped_column(String(512), default=None)
    quality_score: Mapped[int] = mapped_column(Integer, default=50)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    people: Mapped[list[Person]] = relationship(back_populates="current_company")


class Person(Base):
    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("normalized_identity", name="uq_people_normalized_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    full_name: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(128), default=None)
    last_name: Mapped[str | None] = mapped_column(String(128), default=None)

    # Deduplication key: normalized "firstlast|company" or profile url when known.
    normalized_identity: Mapped[str] = mapped_column(String(512), index=True)
    profile_url: Mapped[str | None] = mapped_column(String(1024), default=None)

    current_title: Mapped[str] = mapped_column(String(255), default="UNKNOWN")
    current_company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), default=None
    )
    location: Mapped[str] = mapped_column(String(255), default="UNKNOWN")
    industry: Mapped[str] = mapped_column(String(255), default="UNKNOWN")
    category: Mapped[str] = mapped_column(String(32), default=Category.OTHER.value)
    years_experience: Mapped[int | None] = mapped_column(Integer, default=None)

    ut_status: Mapped[str] = mapped_column(String(32), default=UTStatus.UNVERIFIED.value)
    ut_status_rationale: Mapped[str | None] = mapped_column(Text, default=None)
    ut_degree: Mapped[str] = mapped_column(String(255), default="UNKNOWN")
    ut_grad_year: Mapped[int | None] = mapped_column(Integer, default=None)
    other_education: Mapped[str] = mapped_column(String(512), default="UNKNOWN")

    networking_thesis: Mapped[str | None] = mapped_column(Text, default=None)
    personalization_angles: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)

    ut_score: Mapped[int] = mapped_column(Integer, default=0)
    career_relevance_score: Mapped[int] = mapped_column(Integer, default=0)
    company_quality_score: Mapped[int] = mapped_column(Integer, default=0)
    seniority_score: Mapped[int] = mapped_column(Integer, default=0)
    geography_score: Mapped[int] = mapped_column(Integer, default=0)
    career_interest_score: Mapped[int] = mapped_column(Integer, default=0)
    relationship_value_score: Mapped[int] = mapped_column(Integer, default=0)
    total_score: Mapped[int] = mapped_column(Integer, default=0)

    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(255), default=None)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    current_company: Mapped[Company | None] = relationship(back_populates="people")
    education: Mapped[list[Education]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    employment: Mapped[list[Employment]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    sources: Mapped[list[Source]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    emails: Mapped[list[EmailRecord]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    outreach: Mapped[list[Outreach]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    meetings: Mapped[list[Meeting]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    relationship: Mapped[Relationship | None] = relationship(
        back_populates="person", uselist=False, cascade="all, delete-orphan"
    )


class Education(Base):
    __tablename__ = "education"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    institution: Mapped[str] = mapped_column(String(255))
    degree: Mapped[str] = mapped_column(String(255), default="UNKNOWN")
    field: Mapped[str] = mapped_column(String(255), default="UNKNOWN")
    graduation_year: Mapped[int | None] = mapped_column(Integer, default=None)
    fact_type: Mapped[str] = mapped_column(String(16), default="INFERENCE")
    source_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="education")


class Employment(Base):
    __tablename__ = "employment"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), default=None)
    company_name_raw: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255), default="UNKNOWN")
    start_date: Mapped[str | None] = mapped_column(String(32), default=None)
    end_date: Mapped[str | None] = mapped_column(String(32), default=None)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    fact_type: Mapped[str] = mapped_column(String(16), default="INFERENCE")
    source_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="employment")


class Source(Base):
    """A retained citation for a factual claim about a person."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str | None] = mapped_column(String(512), default=None)
    snippet: Mapped[str | None] = mapped_column(Text, default=None)
    claim: Mapped[str | None] = mapped_column(String(512), default=None)
    fact_type: Mapped[str] = mapped_column(String(16), default="INFERENCE")
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="sources")


class EmailRecord(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    email_address: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(128), default="UNKNOWN")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verification_status: Mapped[str] = mapped_column(
        String(32), default=EmailVerificationStatus.UNVERIFIED.value
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="emails")


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id"), default=None)
    sequence_number: Mapped[int] = mapped_column(Integer, default=1)  # 1, 2 (fu1), 3 (fu2)
    subject: Mapped[str] = mapped_column(String(255))
    subject_options: Mapped[list] = mapped_column(JSON, default=list)
    body: Mapped[str] = mapped_column(Text)
    template_tag: Mapped[str | None] = mapped_column(String(64), default=None)
    personalization_angle: Mapped[str | None] = mapped_column(String(512), default=None)
    status: Mapped[str] = mapped_column(String(32), default=OutreachStatus.DRAFT.value)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    scheduled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), default=None)
    thread_id: Mapped[str | None] = mapped_column(String(255), default=None)
    last_reply_checked_message_id: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="outreach")


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    activity_type: Mapped[str] = mapped_column(String(32))  # ActivityType
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="activities")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    scheduled_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=25)
    meeting_type: Mapped[str] = mapped_column(String(32), default=MeetingType.ZOOM.value)
    calendar_event_id: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[str] = mapped_column(String(32), default=MeetingStatus.PROPOSED.value)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="meetings")


class Relationship(Base):
    """1:1 with Person. Tracks the state-machine + cadence data the CRM
    and follow-up agents operate on."""

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), unique=True)

    status: Mapped[str] = mapped_column(String(32), default=RelationshipStatus.DISCOVERED.value)
    date_discovered: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    date_first_contacted: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_contact: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_action_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    reply_status: Mapped[str | None] = mapped_column(String(32), default=None)  # ReplyClassification
    meeting_status: Mapped[str | None] = mapped_column(String(32), default=None)
    last_meeting: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    relationship_strength: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    person: Mapped[Person] = relationship(back_populates="relationship")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32))
    location_filter: Mapped[str | None] = mapped_column(String(255), default=None)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
