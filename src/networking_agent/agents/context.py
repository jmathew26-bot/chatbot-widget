"""Shared dependency bundle so agents receive one object instead of five
positional provider arguments. Built once per CLI invocation."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from networking_agent.adapters.base import (
    CalendarProvider,
    EmailProvider,
    EmailVerificationProvider,
    LLMProvider,
    PeopleDataProvider,
    SearchProvider,
)
from networking_agent.adapters.calendar_provider import get_calendar_provider
from networking_agent.adapters.email_provider import get_email_provider
from networking_agent.adapters.email_verification_provider import get_email_verification_provider
from networking_agent.adapters.llm_provider import get_llm_provider
from networking_agent.adapters.people_data_provider import get_people_data_provider
from networking_agent.adapters.search_provider import get_search_provider
from networking_agent.config import Settings, get_settings


@dataclass
class AgentContext:
    session: Session
    settings: Settings
    search: SearchProvider
    llm: LLMProvider
    email: EmailProvider
    calendar: CalendarProvider
    people_data: PeopleDataProvider
    email_verification: EmailVerificationProvider

    @classmethod
    def build(cls, session: Session, settings: Settings | None = None) -> "AgentContext":
        settings = settings or get_settings()
        return cls(
            session=session,
            settings=settings,
            search=get_search_provider(settings),
            llm=get_llm_provider(settings),
            email=get_email_provider(settings),
            calendar=get_calendar_provider(settings),
            people_data=get_people_data_provider(settings),
            email_verification=get_email_verification_provider(),
        )
