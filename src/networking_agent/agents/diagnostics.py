"""ANALYTICS/OPS: `network doctor`. Read-only environment checks -- never
constructs a real Gmail/Calendar provider (that would trigger an
interactive OAuth flow), only inspects file presence and, for OAuth
tokens, whether a refresh_token is present. Never prints a secret value,
only booleans/status strings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from networking_agent.config import Settings

# Recommended for a fully "live" run; absence just means that capability
# degrades gracefully (see README "What needs credentials").
RECOMMENDED_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_CX",
    "HUNTER_API_KEY",
    "GMAIL_CREDENTIALS_JSON",
    "GMAIL_TOKEN_JSON",
    "GOOGLE_CALENDAR_CREDENTIALS_JSON",
    "GOOGLE_CALENDAR_TOKEN_JSON",
]


@dataclass
class CheckResult:
    name: str
    status: str  # "ok" | "warning" | "error" | "not_configured"
    detail: str


def _oauth_status(name: str, creds_path: str | None, token_path: str | None, scopes: list[str]) -> CheckResult:
    """Distinguishable states, in order: not_configured (no client
    credentials) / error (credentials file invalid, or dependency missing)
    / warning (client credentials present, authentication required) /
    error (token file invalid/incomplete) / warning (token expired but
    refreshable) / ok (authorized). Never touches the network -- expiry is
    read from the token file's own `expiry` timestamp, not verified
    against Google, so this can't hang or fail on a flaky connection.
    """
    if not creds_path or not Path(creds_path).exists():
        return CheckResult(name, "not_configured", "no OAuth client credentials file on disk")

    try:
        client_config = json.loads(Path(creds_path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult(name, "error", f"credentials file is invalid: {e}")
    if "installed" not in client_config and "web" not in client_config:
        return CheckResult(
            name, "error",
            "credentials file is not a valid OAuth client JSON (missing 'installed'/'web' key) -- "
            "make sure you downloaded an OAuth client ID (Desktop app), not a service-account key or API key",
        )

    if not token_path or not Path(token_path).exists():
        return CheckResult(
            name, "warning",
            "OAuth client credentials present, authentication required -- "
            f"run `network {'gmail-test' if 'gmail' in name else 'calendar-test'}` to authenticate",
        )

    try:
        from google.oauth2.credentials import Credentials

        # google-auth itself requires refresh_token/client_id/client_secret
        # to be present and raises ValueError otherwise -- so by the time
        # this succeeds, creds.refresh_token is guaranteed truthy.
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    except ImportError:
        return CheckResult(
            name, "error",
            "google-auth-oauthlib / google-api-python-client not installed -- pip install -r requirements.txt",
        )
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return CheckResult(
            name, "error",
            f"token file is invalid or incomplete ({e}) -- delete it and re-authenticate",
        )

    if creds.expired:
        return CheckResult(name, "warning", "access token expired, but refresh_token present -- will refresh automatically on next use")
    return CheckResult(name, "ok", "authorized")


def check_database(settings: Settings) -> CheckResult:
    try:
        from sqlalchemy import create_engine, text

        from networking_agent.db.session import ensure_sqlite_dir

        ensure_sqlite_dir(settings.database_url)
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return CheckResult("database", "ok", settings.database_url)
    except Exception as e:  # noqa: BLE001
        return CheckResult("database", "error", str(e))


def check_llm(settings: Settings) -> CheckResult:
    if settings.anthropic_api_key:
        return CheckResult("llm_provider", "ok", f"Anthropic configured (model={settings.anthropic_model})")
    return CheckResult(
        "llm_provider", "not_configured",
        "ANTHROPIC_API_KEY not set -- research/scoring/email-drafting fall back to deterministic, fact-only templates",
    )


def check_search(settings: Settings) -> CheckResult:
    if settings.google_cse_api_key and settings.google_cse_cx:
        return CheckResult("search_provider", "ok", "Google Programmable Search Engine configured")
    return CheckResult(
        "search_provider", "not_configured",
        "GOOGLE_CSE_API_KEY / GOOGLE_CSE_CX not set -- `network discover` will always return 0 results",
    )


def check_email_discovery(settings: Settings) -> CheckResult:
    if settings.hunter_api_key:
        return CheckResult("email_discovery_provider", "ok", "Hunter.io configured")
    return CheckResult(
        "email_discovery_provider", "not_configured",
        "HUNTER_API_KEY not set -- discovered people will have no email on file unless added manually",
    )


def check_gmail(settings: Settings) -> CheckResult:
    from networking_agent.adapters.email_provider import GMAIL_SCOPES

    return _oauth_status("gmail", settings.gmail_credentials_json, settings.gmail_token_json, GMAIL_SCOPES)


def check_calendar(settings: Settings) -> CheckResult:
    from networking_agent.adapters.calendar_provider import CALENDAR_SCOPES

    return _oauth_status(
        "google_calendar", settings.google_calendar_credentials_json, settings.google_calendar_token_json,
        CALENDAR_SCOPES,
    )


def check_missing_env_vars() -> CheckResult:
    import os

    missing = [name for name in RECOMMENDED_ENV_VARS if not os.environ.get(name)]
    if not missing:
        return CheckResult("env_vars", "ok", "all recommended variables are set")
    return CheckResult("env_vars", "warning", f"not set: {', '.join(missing)}")


def check_send_mode(settings: Settings) -> CheckResult:
    gmail_ready = check_gmail(settings).status == "ok"
    if gmail_ready:
        return CheckResult("send_mode", "ok", "LIVE (Gmail) -- approved outreach will actually send")
    return CheckResult(
        "send_mode", "not_configured",
        "DRY RUN (ConsoleEmailProvider) -- approved outreach is written to data/outbox/, nothing is emailed",
    )


def check_live_test_mode(settings: Settings) -> CheckResult:
    if settings.live_test_mode:
        return CheckResult(
            "live_test_mode", "ok",
            f"ON -- discovery capped at {settings.live_test_max_discover}, sends capped at {settings.live_test_max_sends_per_day}/day",
        )
    return CheckResult(
        "live_test_mode", "warning",
        f"OFF -- normal limits apply (daily_discovery_limit={settings.limits.daily_discovery_limit}, "
        f"daily_email_limit={settings.limits.daily_email_limit}). Consider LIVE_TEST_MODE=true until you trust the pipeline.",
    )


def run_diagnostics(settings: Settings) -> list[CheckResult]:
    return [
        check_database(settings),
        check_llm(settings),
        check_search(settings),
        check_email_discovery(settings),
        check_gmail(settings),
        check_calendar(settings),
        check_send_mode(settings),
        check_live_test_mode(settings),
        check_missing_env_vars(),
    ]
