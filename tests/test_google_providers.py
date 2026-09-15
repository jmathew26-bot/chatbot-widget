"""Unit tests for the Gmail/Calendar provider methods added for
`network gmail-test` / `calendar-test` / `*-test-send` / `*-test-create`.

These bypass __init__ (which performs real OAuth) and inject a mocked
`_service` so we can verify the Gmail/Calendar API call shapes and
response parsing without any real credentials or network access -- no
real message is sent and no real event is created by these tests.
"""
from unittest.mock import MagicMock

from networking_agent.adapters.calendar_provider import CALENDAR_SCOPES, GoogleCalendarProvider
from networking_agent.adapters.email_provider import GMAIL_SCOPES, GmailEmailProvider


def _make_gmail_provider(service: MagicMock) -> GmailEmailProvider:
    provider = object.__new__(GmailEmailProvider)
    provider._service = service
    provider.sender_email = None
    return provider


def _make_calendar_provider(service: MagicMock, calendar_id: str = "primary") -> GoogleCalendarProvider:
    provider = object.__new__(GoogleCalendarProvider)
    provider._service = service
    provider.calendar_id = calendar_id
    return provider


def test_gmail_whoami_returns_email_address():
    service = MagicMock()
    service.users().getProfile(userId="me").execute.return_value = {"emailAddress": "me@example.com"}
    provider = _make_gmail_provider(service)

    assert provider.whoami() == "me@example.com"


def test_gmail_scopes_are_minimal():
    assert GMAIL_SCOPES == [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]


def test_calendar_scopes_are_minimal_not_full_calendar_scope():
    assert CALENDAR_SCOPES == [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.freebusy",
    ]
    assert "https://www.googleapis.com/auth/calendar" not in CALENDAR_SCOPES


def test_calendar_get_calendar_info_returns_service_response():
    service = MagicMock()
    service.calendars().get(calendarId="primary").execute.return_value = {
        "id": "primary", "summary": "Jane Doe", "timeZone": "America/Chicago",
    }
    provider = _make_calendar_provider(service)

    info = provider.get_calendar_info()

    assert info["summary"] == "Jane Doe"
    service.calendars().get.assert_any_call(calendarId="primary")


def test_calendar_delete_event_calls_events_delete_with_ids():
    service = MagicMock()
    provider = _make_calendar_provider(service, calendar_id="primary")

    provider.delete_event("evt-123")

    service.events().delete.assert_any_call(calendarId="primary", eventId="evt-123")
    service.events().delete(calendarId="primary", eventId="evt-123").execute.assert_called()


def test_gmail_send_records_thread_id_from_response():
    from networking_agent.adapters.base import EmailMessage

    service = MagicMock()
    service.users().messages().send(userId="me", body={"raw": "x"}).execute.return_value = {
        "id": "msg-1", "threadId": "thread-1",
    }
    provider = _make_gmail_provider(service)

    result = provider.send(EmailMessage(to_address="a@b.com", subject="hi", body="hello"), "idem-1")

    assert result.success is True
    assert result.thread_id == "thread-1"
    assert result.provider_message_id == "msg-1"
