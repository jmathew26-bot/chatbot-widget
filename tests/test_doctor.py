import datetime as dt
import json

from networking_agent.agents import diagnostics
from networking_agent.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(database_url="sqlite:///:memory:")
    base.update(overrides)
    return Settings(**base)


def _valid_client_json() -> str:
    """Minimal realistic shape of a downloaded "Desktop app" OAuth client
    JSON -- has the 'installed' key our validation looks for."""
    return json.dumps(
        {
            "installed": {
                "client_id": "fake.apps.googleusercontent.com",
                "client_secret": "fake-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
    )


def _token_json(refresh_token: str | None = "r-123", expiry: dt.datetime | None = None) -> str:
    data = {
        "client_id": "fake.apps.googleusercontent.com",
        "client_secret": "fake-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/gmail.send"],
    }
    if refresh_token:
        data["refresh_token"] = refresh_token
    if expiry:
        data["expiry"] = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps(data)


def test_check_database_ok_for_valid_sqlite_url():
    result = diagnostics.check_database(_settings(database_url="sqlite:///:memory:"))
    assert result.status == "ok"


def test_check_database_error_for_bad_url():
    result = diagnostics.check_database(_settings(database_url="not-a-real-url://nope"))
    assert result.status == "error"


def test_check_database_creates_missing_parent_directory(tmp_path):
    """Regression: a fresh checkout has no data/ dir yet (before the first
    `alembic upgrade head`) -- doctor must not report a false error just
    because the directory doesn't exist."""
    db_dir = tmp_path / "does" / "not" / "exist" / "yet"
    assert not db_dir.exists()
    # Absolute sqlite URLs use four slashes (sqlite:////abs/path) --
    # SQLAlchemy's own convention, parsed via make_url rather than assumed.
    result = diagnostics.check_database(_settings(database_url=f"sqlite:///{db_dir}/networking.db"))
    assert result.status == "ok"
    assert db_dir.exists()


def test_check_llm_not_configured_without_key():
    result = diagnostics.check_llm(_settings(anthropic_api_key=None))
    assert result.status == "not_configured"


def test_check_llm_ok_with_key():
    result = diagnostics.check_llm(_settings(anthropic_api_key="sk-fake"))
    assert result.status == "ok"
    assert "sk-fake" not in result.detail  # never print the secret itself


def test_check_search_not_configured_without_keys():
    result = diagnostics.check_search(_settings())
    assert result.status == "not_configured"


def test_check_search_ok_with_both_keys():
    result = diagnostics.check_search(_settings(google_cse_api_key="k", google_cse_cx="cx"))
    assert result.status == "ok"


def test_check_gmail_not_configured_without_credentials_file():
    result = diagnostics.check_gmail(_settings(gmail_credentials_json=None))
    assert result.status == "not_configured"


def test_check_gmail_warning_when_credentials_present_but_no_token(tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text(_valid_client_json())
    result = diagnostics.check_gmail(
        _settings(gmail_credentials_json=str(creds), gmail_token_json=str(tmp_path / "missing_token.json"))
    )
    assert result.status == "warning"
    assert "authentication required" in result.detail


def test_check_gmail_error_when_credentials_file_is_not_an_oauth_client(tmp_path):
    """Regression: an empty/malformed JSON (or e.g. a service-account key,
    or a bare API key) must be reported as invalid, not silently accepted."""
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    result = diagnostics.check_gmail(
        _settings(gmail_credentials_json=str(creds), gmail_token_json=str(tmp_path / "missing_token.json"))
    )
    assert result.status == "error"
    assert "not a valid OAuth client" in result.detail


def test_check_gmail_ok_with_valid_unexpired_refresh_token(tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text(_valid_client_json())
    token = tmp_path / "token.json"
    token.write_text(_token_json(refresh_token="r-123", expiry=dt.datetime.utcnow() + dt.timedelta(hours=1)))
    result = diagnostics.check_gmail(_settings(gmail_credentials_json=str(creds), gmail_token_json=str(token)))
    assert result.status == "ok"
    assert "r-123" not in result.detail  # never print the token value


def test_check_gmail_warning_when_token_expired_but_refreshable(tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text(_valid_client_json())
    token = tmp_path / "token.json"
    token.write_text(_token_json(refresh_token="r-123", expiry=dt.datetime.utcnow() - dt.timedelta(hours=1)))
    result = diagnostics.check_gmail(_settings(gmail_credentials_json=str(creds), gmail_token_json=str(token)))
    assert result.status == "warning"
    assert "expired" in result.detail and "refresh_token present" in result.detail


def test_check_gmail_error_when_token_missing_refresh(tmp_path):
    """google-auth itself requires refresh_token to be present in the
    token file and raises before we'd ever see a Credentials object
    without one -- so this surfaces as an invalid/incomplete token, not a
    distinguishable 'missing refresh_token' state."""
    creds = tmp_path / "creds.json"
    creds.write_text(_valid_client_json())
    token = tmp_path / "token.json"
    token.write_text(_token_json(refresh_token=None))
    result = diagnostics.check_gmail(_settings(gmail_credentials_json=str(creds), gmail_token_json=str(token)))
    assert result.status == "error"
    assert "invalid or incomplete" in result.detail


def test_check_send_mode_dry_run_without_gmail():
    result = diagnostics.check_send_mode(_settings())
    assert "DRY RUN" in result.detail


def test_check_live_test_mode_reports_caps_when_on():
    result = diagnostics.check_live_test_mode(_settings(live_test_mode=True))
    assert result.status == "ok"
    assert "20" in result.detail and "5" in result.detail


def test_run_diagnostics_never_raises_and_returns_all_checks():
    results = diagnostics.run_diagnostics(_settings())
    assert len(results) == 9
    assert all(r.status in ("ok", "warning", "error", "not_configured") for r in results)
