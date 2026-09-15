from typer.testing import CliRunner

from networking_agent.cli import app

runner = CliRunner()


def test_doctor_command_runs_and_reports_not_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/doctor.db")
    from networking_agent.config import get_settings

    get_settings.cache_clear()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "database" in result.output
    assert "not_configured" in result.output


def test_live_test_caps_count_at_20_regardless_of_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/live.db")
    from networking_agent.config import get_settings
    from networking_agent.db.session import init_db

    get_settings.cache_clear()
    init_db()

    captured = {}

    def fake_discover(ctx, category, location, count):
        captured["count"] = count
        return []

    monkeypatch.setattr("networking_agent.cli.discovery.discover", fake_discover)

    result = runner.invoke(app, ["live-test", "--category", "tech-sales", "--location", "Austin", "--count", "9999"])

    assert result.exit_code == 0
    assert captured["count"] == 20
    assert "LIVE TEST MODE" in result.output


def test_discover_respects_daily_discovery_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/discover.db")
    from networking_agent.config import get_settings
    from networking_agent.db.session import init_db

    get_settings.cache_clear()
    init_db()

    captured = {}

    def fake_discover(ctx, category, location, count):
        captured["count"] = count
        return []

    monkeypatch.setattr("networking_agent.cli.discovery.discover", fake_discover)

    result = runner.invoke(app, ["discover", "--category", "tech-sales", "--count", "9999"])

    assert result.exit_code == 0
    assert captured["count"] == get_settings().limits.daily_discovery_limit
