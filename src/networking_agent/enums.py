"""Shared enums. Kept in one place so DB models, Pydantic schemas, and
agents all agree on the same vocabulary."""
from __future__ import annotations

import enum


class Category(str, enum.Enum):
    TECH_SALES = "tech-sales"
    CRE = "cre"
    OTHER = "other"


class UTStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    LIKELY = "LIKELY"
    UNVERIFIED = "UNVERIFIED"
    FALSE = "FALSE"


class FactType(str, enum.Enum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"


class EmailVerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    UNVERIFIED = "UNVERIFIED"
    BOUNCED = "BOUNCED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"


class OutreachStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    SENT = "SENT"
    FAILED = "FAILED"


class RelationshipStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    RESEARCHED = "RESEARCHED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    CONTACTED = "CONTACTED"
    FOLLOW_UP_1 = "FOLLOW_UP_1"
    FOLLOW_UP_2 = "FOLLOW_UP_2"
    RESPONDED = "RESPONDED"
    MEETING_SCHEDULED = "MEETING_SCHEDULED"
    MET = "MET"
    NURTURE = "NURTURE"
    NO_RESPONSE = "NO_RESPONSE"
    DECLINED = "DECLINED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    BLOCKED = "BLOCKED"


class ReplyClassification(str, enum.Enum):
    POSITIVE = "POSITIVE"
    INTERESTED = "INTERESTED"
    MEETING_REQUESTED = "MEETING_REQUESTED"
    NEEDS_FOLLOW_UP = "NEEDS_FOLLOW_UP"
    NOT_NOW = "NOT_NOW"
    DECLINED = "DECLINED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"
    BOUNCE = "BOUNCE"
    AUTOMATED_RESPONSE = "AUTOMATED_RESPONSE"
    UNKNOWN = "UNKNOWN"


# Reply classifications that must immediately stop all scheduled follow-ups.
STOP_FOLLOWUP_CLASSIFICATIONS = {
    ReplyClassification.POSITIVE,
    ReplyClassification.INTERESTED,
    ReplyClassification.MEETING_REQUESTED,
    ReplyClassification.NOT_NOW,
    ReplyClassification.DECLINED,
    ReplyClassification.DO_NOT_CONTACT,
    ReplyClassification.BOUNCE,
}

NEGATIVE_CLASSIFICATIONS = {
    ReplyClassification.DECLINED,
    ReplyClassification.DO_NOT_CONTACT,
}


class ActivityType(str, enum.Enum):
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_DRAFTED = "EMAIL_DRAFTED"
    REPLY_RECEIVED = "REPLY_RECEIVED"
    MEETING_SCHEDULED = "MEETING_SCHEDULED"
    MEETING_HELD = "MEETING_HELD"
    MANUAL_NOTE = "MANUAL_NOTE"
    STATUS_CHANGE = "STATUS_CHANGE"
    DISCOVERED = "DISCOVERED"
    RESEARCHED = "RESEARCHED"
    SCORED = "SCORED"


class MeetingType(str, enum.Enum):
    COFFEE = "coffee"
    LUNCH = "lunch"
    OFFICE = "office"
    PHONE = "phone"
    ZOOM = "zoom"


class MeetingStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
