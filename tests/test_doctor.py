import json

from networking_agent.agents import diagnostics
from networking_agent.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(database_url="sqlite:///:memory:")
    base.update(overrides)
    return Settings(**base)


def test_check_database_ok_for_valid_sqlite_url():
    result = diagnostics.check_database(_settings(database_url="sqlite:///:memory:"))
    assert result.status == "ok"


def test_check_database_error_for_bad_url():
    result = diagnostics.check_database(_settings(database_url="not-a-real-url://nope"))
    assert result.status == "error"


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
    creds.write_text("{}")
    result = diagnostics.check_gmail(
        _settings(gmail_credentials_json=str(creds), gmail_token_json=str(tmp_path / "missing_token.json"))
    )
    assert result.status == "warning"


def test_check_gmail_ok_with_valid_refresh_token(tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"refresh_token": "r-123"}))
    result = diagnostics.check_gmail(_settings(gmail_credentials_json=str(creds), gmail_token_json=str(token)))
    assert result.status == "ok"
    assert "r-123" not in result.detail  # never print the token value


def test_check_gmail_warning_when_token_missing_refresh(tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "a-123"}))
    result = diagnostics.check_gmail(_settings(gmail_credentials_json=str(creds), gmail_token_json=str(token)))
    assert result.status == "warning"


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
