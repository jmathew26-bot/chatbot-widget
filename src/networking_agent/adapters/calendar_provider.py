from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from networking_agent.adapters.base import CalendarProvider, TimeSlot
from networking_agent.config import Settings

logger = logging.getLogger("networking_agent.calendar")


class NullCalendarProvider(CalendarProvider):
    """No calendar wired up. list_busy always returns empty (scheduling
    agent will still avoid double-booking *within this app's own meetings
    table*, it just can't see the user's real calendar)."""

    def list_busy(self, start: dt.datetime, end: dt.datetime) -> list[TimeSlot]:
        return []

    def create_event(
        self, title: str, start: dt.datetime, end: dt.datetime, attendee_email: str | None,
        description: str = "",
    ) -> str:
        logger.info("NullCalendarProvider: would create event %r at %s (no calendar configured)", title, start)
        return f"local-{start.isoformat()}"


class GoogleCalendarProvider(CalendarProvider):
    """Real Google Calendar integration. Requires OAuth credentials with the
    calendar scope. Not used unless credential files exist on disk."""

    def __init__(self, credentials_path: str, token_path: str, calendar_id: str):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/calendar"]
        creds = None
        token_file = Path(token_path)
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
                creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json())
        self._service = build("calendar", "v3", credentials=creds)
        self.calendar_id = calendar_id

    def list_busy(self, start: dt.datetime, end: dt.datetime) -> list[TimeSlot]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": self.calendar_id}],
        }
        resp = self._service.freebusy().query(body=body).execute()
        busy = resp["calendars"][self.calendar_id]["busy"]
        return [
            TimeSlot(start=dt.datetime.fromisoformat(b["start"]), end=dt.datetime.fromisoformat(b["end"]))
            for b in busy
        ]

    def create_event(
        self, title: str, start: dt.datetime, end: dt.datetime, attendee_email: str | None,
        description: str = "",
    ) -> str:
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if attendee_email:
            event["attendees"] = [{"email": attendee_email}]
        created = self._service.events().insert(calendarId=self.calendar_id, body=event).execute()
        return created["id"]


def get_calendar_provider(settings: Settings) -> CalendarProvider:
    if (
        settings.google_calendar_credentials_json
        and Path(settings.google_calendar_credentials_json).exists()
        and settings.google_calendar_token_json
    ):
        try:
            return GoogleCalendarProvider(
                settings.google_calendar_credentials_json,
                settings.google_calendar_token_json,
                settings.google_calendar_id,
            )
        except ImportError:
            logger.warning("google-api-python-client not installed; falling back to NullCalendarProvider")
    return NullCalendarProvider()
