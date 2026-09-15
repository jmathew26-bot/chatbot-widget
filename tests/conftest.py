from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from networking_agent.adapters.base import EmailVerificationProvider
from networking_agent.adapters.calendar_provider import NullCalendarProvider
from networking_agent.adapters.llm_provider import NullLLMProvider
from networking_agent.adapters.people_data_provider import NullPeopleDataProvider
from networking_agent.adapters.search_provider import MockSearchProvider
from networking_agent.agents.context import AgentContext
from networking_agent.config import EmailConfig, FollowupConfig, LimitsConfig, MeetingConfig, ScoringConfig, Settings
from networking_agent.db.base import Base
import networking_agent.db.models  # noqa: F401


class FakeEmailProvider:
    """Test double that also simulates Gmail threading: send() opens a
    thread keyed off the idempotency key, and tests can push simulated
    incoming messages into it via add_reply() to exercise
    response.check_all_replies() without real Gmail credentials."""

    def __init__(self):
        self.sent = []
        self.threads: dict[str, list] = {}
        self._next_message_id = 1

    def send(self, message, idempotency_key: str):
        from networking_agent.adapters.base import SendResult

        existing = next((m for m in self.sent if m["idempotency_key"] == idempotency_key), None)
        if existing:
            return SendResult(success=True, provider_message_id=idempotency_key, thread_id=existing["thread_id"])
        thread_id = f"thread-{idempotency_key}"
        self.sent.append({"message": message, "idempotency_key": idempotency_key, "thread_id": thread_id})
        self.threads.setdefault(thread_id, [])
        return SendResult(success=True, provider_message_id=idempotency_key, thread_id=thread_id)

    def fetch_replies(self, since):
        return []

    def list_thread_messages(self, thread_id):
        return self.threads.get(thread_id, [])

    def add_reply(self, thread_id: str, from_address: str, body_text: str):
        import datetime as dt

        from networking_agent.adapters.base import IncomingMessage

        message_id = f"msg-{self._next_message_id}"
        self._next_message_id += 1
        self.threads.setdefault(thread_id, []).append(
            IncomingMessage(
                message_id=message_id, from_address=from_address, body_text=body_text,
                received_at=dt.datetime.now(dt.timezone.utc),
            )
        )
        return message_id


class FakeEmailVerifier(EmailVerificationProvider):
    def verify(self, email: str) -> str:
        return "HIGH_CONFIDENCE"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def test_settings():
    return Settings(
        raw={
            "targets": {
                "tech_sales": {
                    "titles": ["Account Executive", "Regional Vice President"],
                    "companies": ["Salesforce", "Snowflake"],
                },
                "cre": {
                    "titles": ["Associate", "Managing Director"],
                    "companies": ["CBRE", "JLL"],
                },
                "locations": {
                    "tier_1": ["Austin"],
                    "tier_2": ["Texas", "Dallas"],
                    "tier_3": ["Denver", "New York"],
                },
                "excluded_companies": [],
                "excluded_people": [],
            },
            "user": {"name": "Test User"},
        },
        scoring=ScoringConfig(),
        followups=FollowupConfig(),
        email=EmailConfig(),
        meetings=MeetingConfig(),
        limits=LimitsConfig(),
        autonomous_sending_enabled=False,
    )


@pytest.fixture()
def ctx(db_session, test_settings):
    return AgentContext(
        session=db_session,
        settings=test_settings,
        search=MockSearchProvider(),
        llm=NullLLMProvider(),
        email=FakeEmailProvider(),
        calendar=NullCalendarProvider(),
        people_data=NullPeopleDataProvider(),
        email_verification=FakeEmailVerifier(),
    )
