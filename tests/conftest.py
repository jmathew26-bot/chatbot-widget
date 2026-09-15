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
    def __init__(self):
        self.sent = []

    def send(self, message, idempotency_key: str):
        from networking_agent.adapters.base import SendResult

        if any(m["idempotency_key"] == idempotency_key for m in self.sent):
            return SendResult(success=True, provider_message_id=idempotency_key)
        self.sent.append({"message": message, "idempotency_key": idempotency_key})
        return SendResult(success=True, provider_message_id=idempotency_key)

    def fetch_replies(self, since):
        return []


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
