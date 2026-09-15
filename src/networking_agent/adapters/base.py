"""Abstract adapter interfaces. Concrete providers are swapped in via
factory functions in each adapter module, selected at runtime by which
credentials are present in Settings. Agents depend only on these
interfaces, never on a specific provider class.
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field

from networking_agent.schemas.prospect import SearchResult


class SearchProvider(abc.ABC):
    @abc.abstractmethod
    def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        ...


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate_json(self, system: str, prompt: str, schema_hint: str) -> str:
        """Return raw JSON text matching the caller's pydantic schema."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        ...


@dataclass
class EmailMessage:
    to_address: str
    subject: str
    body: str
    in_reply_to: str | None = None


@dataclass
class SendResult:
    success: bool
    provider_message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None


@dataclass
class IncomingMessage:
    message_id: str
    from_address: str
    body_text: str
    received_at: dt.datetime


class EmailProvider(abc.ABC):
    @abc.abstractmethod
    def send(self, message: EmailMessage, idempotency_key: str) -> SendResult:
        ...

    @abc.abstractmethod
    def fetch_replies(self, since: dt.datetime) -> list[dict]:
        ...

    @abc.abstractmethod
    def list_thread_messages(self, thread_id: str) -> list[IncomingMessage]:
        """All messages in the given thread, oldest first. Used to detect
        replies to a specific sent Outreach without relying on a blind
        inbox scan."""


@dataclass
class TimeSlot:
    start: dt.datetime
    end: dt.datetime


class CalendarProvider(abc.ABC):
    @abc.abstractmethod
    def list_busy(self, start: dt.datetime, end: dt.datetime) -> list[TimeSlot]:
        ...

    @abc.abstractmethod
    def create_event(
        self, title: str, start: dt.datetime, end: dt.datetime, attendee_email: str | None,
        description: str = "",
    ) -> str:
        """Returns a calendar_event_id."""


@dataclass
class DiscoveredEmail:
    email: str
    source: str
    confidence: float
    verification_status: str = "UNVERIFIED"


class PeopleDataProvider(abc.ABC):
    @abc.abstractmethod
    def find_email(self, full_name: str, company: str, domain: str | None) -> DiscoveredEmail | None:
        ...


class EmailVerificationProvider(abc.ABC):
    @abc.abstractmethod
    def verify(self, email: str) -> str:
        """Returns an EmailVerificationStatus value."""
