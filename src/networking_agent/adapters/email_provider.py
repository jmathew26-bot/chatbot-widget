from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from networking_agent.adapters.base import EmailMessage, EmailProvider, IncomingMessage, SendResult
from networking_agent.config import REPO_ROOT, Settings

logger = logging.getLogger("networking_agent.email")

OUTBOX_DIR = REPO_ROOT / "data" / "outbox"

# Minimal scopes for what this app does: send from the user's own mailbox
# and read thread contents for reply detection. There is no narrower Gmail
# scope for reading specific threads -- gmail.readonly is Google's
# coarsest-but-still-read-only grade, required for threads().get /
# messages().get / users().getProfile.
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]


def _extract_plain_text(payload: dict) -> str:
    """Walk a Gmail message payload for the first text/plain part; falls
    back to text/html with tags stripped if that's all the sender gave us."""
    import base64
    import re

    def decode(data: str) -> str:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")

    def walk(part: dict) -> tuple[str | None, str | None]:
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if mime_type == "text/plain" and body_data:
            return decode(body_data), None
        if mime_type == "text/html" and body_data:
            return None, decode(body_data)
        plain, html = None, None
        for sub in part.get("parts", []) or []:
            p, h = walk(sub)
            plain = plain or p
            html = html or h
        return plain, html

    plain, html = walk(payload)
    if plain:
        return plain.strip()
    if html:
        return re.sub(r"<[^>]+>", " ", html).strip()
    return ""


class ConsoleEmailProvider(EmailProvider):
    """Default provider: no real send happens. Writes each approved message
    to data/outbox/ as a .eml-like text file and logs it, keyed by an
    idempotency key so retries never produce a second file/send.

    This is intentional: real sending requires the user to explicitly wire
    up GmailEmailProvider with OAuth credentials. Nothing goes out to the
    public internet through this provider.
    """

    def __init__(self):
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, message: EmailMessage, idempotency_key: str) -> SendResult:
        path = OUTBOX_DIR / f"{idempotency_key}.txt"
        if path.exists():
            logger.info("idempotent no-op: %s already written", idempotency_key)
            return SendResult(success=True, provider_message_id=idempotency_key)
        path.write_text(
            f"To: {message.to_address}\n"
            f"Subject: {message.subject}\n"
            f"Date: {dt.datetime.now(dt.timezone.utc).isoformat()}\n\n"
            f"{message.body}\n"
        )
        logger.info("wrote outbound email to %s (dry-run, no network send)", path)
        return SendResult(success=True, provider_message_id=idempotency_key)

    def fetch_replies(self, since: dt.datetime) -> list[dict]:
        return []

    def list_thread_messages(self, thread_id: str) -> list[IncomingMessage]:
        return []  # no real thread exists in dry-run mode


class GmailEmailProvider(EmailProvider):
    """Real Gmail send/read via the Gmail API. Requires OAuth credentials
    (GMAIL_CREDENTIALS_JSON / GMAIL_TOKEN_JSON) obtained through Google Cloud
    Console with the gmail.send and gmail.readonly scopes.

    Not wired up by default -- get_email_provider() only returns this when
    both credential files exist on disk, so a fresh checkout always starts
    on ConsoleEmailProvider (safe, offline).
    """

    def __init__(self, credentials_path: str, token_path: str, sender_email: str | None):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        scopes = GMAIL_SCOPES
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
        self._service = build("gmail", "v1", credentials=creds)
        self.sender_email = sender_email

    def send(self, message: EmailMessage, idempotency_key: str) -> SendResult:
        import base64
        from email.mime.text import MIMEText

        mime = MIMEText(message.body)
        mime["to"] = message.to_address
        mime["subject"] = message.subject
        if self.sender_email:
            mime["from"] = self.sender_email
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        try:
            result = self._service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return SendResult(success=True, provider_message_id=result.get("id"), thread_id=result.get("threadId"))
        except Exception as e:  # noqa: BLE001
            logger.error("gmail send failed: %s", e)
            return SendResult(success=False, error=str(e))

    def fetch_replies(self, since: dt.datetime) -> list[dict]:
        query = f"after:{int(since.timestamp())}"
        try:
            resp = self._service.users().messages().list(userId="me", q=query).execute()
        except Exception as e:  # noqa: BLE001
            logger.error("gmail fetch_replies failed: %s", e)
            return []
        out = []
        for msg_meta in resp.get("messages", []):
            msg = self._service.users().messages().get(userId="me", id=msg_meta["id"]).execute()
            out.append(msg)
        return out

    def whoami(self) -> str:
        """Used by `network gmail-test` to confirm real access without
        sending anything -- returns the authenticated account's email
        address via Gmail's own profile endpoint."""
        profile = self._service.users().getProfile(userId="me").execute()
        return profile.get("emailAddress", "")

    def list_thread_messages(self, thread_id: str) -> list[IncomingMessage]:
        try:
            thread = self._service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        except Exception as e:  # noqa: BLE001
            logger.error("gmail list_thread_messages failed for thread=%s: %s", thread_id, e)
            return []

        out = []
        for msg in thread.get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            internal_date = msg.get("internalDate")
            received_at = (
                dt.datetime.fromtimestamp(int(internal_date) / 1000, tz=dt.timezone.utc)
                if internal_date
                else dt.datetime.now(dt.timezone.utc)
            )
            out.append(
                IncomingMessage(
                    message_id=msg["id"],
                    from_address=headers.get("from", ""),
                    body_text=_extract_plain_text(msg.get("payload", {})),
                    received_at=received_at,
                )
            )
        return out


def get_email_provider(settings: Settings) -> EmailProvider:
    if (
        settings.gmail_credentials_json
        and Path(settings.gmail_credentials_json).exists()
        and settings.gmail_token_json
    ):
        try:
            return GmailEmailProvider(
                settings.gmail_credentials_json, settings.gmail_token_json, settings.gmail_sender_email
            )
        except ImportError:
            logger.warning("google-api-python-client not installed; falling back to ConsoleEmailProvider")
    return ConsoleEmailProvider()
