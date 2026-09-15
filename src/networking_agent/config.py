"""Loads config/config.yaml + .env into a single validated Settings object.

Secrets live in environment variables (.env); everything else (targeting
rules, scoring weights, cadence, tone) lives in config/config.yaml so it can
be edited without touching code.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"
CONFIG_EXAMPLE_PATH = REPO_ROOT / "config" / "config.example.yaml"
USER_PROFILE_PATH = REPO_ROOT / "USER_PROFILE.md"
ENV_PATH = REPO_ROOT / ".env"


class ScoringWeights(BaseModel):
    ut_austin: int = 25
    career_relevance: int = 20
    company_quality: int = 15
    seniority: int = 10
    geography: int = 10
    career_interest: int = 10
    relationship_value: int = 10


class ScoringConfig(BaseModel):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    thresholds: dict[str, int] = Field(
        default_factory=lambda: {
            "exceptional": 90,
            "high_priority": 80,
            "good": 70,
            "review": 60,
        }
    )


class FollowupConfig(BaseModel):
    max_total_attempts: int = 3
    followup_1_business_days: int = 5
    followup_2_business_days_after_followup_1: int = 8


class EmailConfig(BaseModel):
    min_words: int = 60
    default_max_words: int = 130
    hard_max_words: int = 160
    tone: str = "intelligent, relaxed, professional, curious, confident, personable, concise"
    banned_phrases: list[str] = Field(default_factory=list)


class MeetingConfig(BaseModel):
    default_duration_minutes: int = 25
    min_duration_minutes: int = 20
    max_duration_minutes: int = 30
    austin_meeting_types: list[str] = Field(default_factory=list)
    remote_meeting_types: list[str] = Field(default_factory=list)


class LimitsConfig(BaseModel):
    daily_discovery_limit: int = 25
    daily_email_limit: int = 10
    default_discover_count: int = 20


class Settings(BaseModel):
    raw: dict[str, Any] = Field(default_factory=dict)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    followups: FollowupConfig = Field(default_factory=FollowupConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    meetings: MeetingConfig = Field(default_factory=MeetingConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    autonomous_sending_enabled: bool = False

    database_url: str = "sqlite:///./data/networking.db"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    google_cse_api_key: str | None = None
    google_cse_cx: str | None = None
    bing_search_api_key: str | None = None

    hunter_api_key: str | None = None
    apollo_api_key: str | None = None
    people_data_labs_api_key: str | None = None
    rocketreach_api_key: str | None = None

    gmail_credentials_json: str | None = None
    gmail_token_json: str | None = None
    gmail_sender_email: str | None = None

    google_calendar_credentials_json: str | None = None
    google_calendar_token_json: str | None = None
    google_calendar_id: str = "primary"

    @property
    def targets(self) -> dict[str, Any]:
        return self.raw.get("targets", {})

    @property
    def user(self) -> dict[str, Any]:
        return self.raw.get("user", {})

    def user_profile_text(self) -> str:
        if USER_PROFILE_PATH.exists():
            return USER_PROFILE_PATH.read_text()
        return ""


def _load_yaml() -> dict[str, Any]:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


@lru_cache
def get_settings() -> Settings:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    raw = _load_yaml()

    def env_bool(name: str, default: bool) -> bool:
        val = os.environ.get(name)
        if val is None:
            return default
        return val.strip().lower() in ("1", "true", "yes", "on")

    return Settings(
        raw=raw,
        scoring=ScoringConfig(**raw.get("scoring", {})),
        followups=FollowupConfig(**raw.get("followups", {})),
        email=EmailConfig(**raw.get("email", {})),
        meetings=MeetingConfig(**raw.get("meetings", {})),
        limits=LimitsConfig(**raw.get("limits", {})),
        autonomous_sending_enabled=env_bool(
            "AUTONOMOUS_SENDING_ENABLED",
            bool(raw.get("autonomous_sending_enabled", False)),
        ),
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/networking.db"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        google_cse_api_key=os.environ.get("GOOGLE_CSE_API_KEY") or None,
        google_cse_cx=os.environ.get("GOOGLE_CSE_CX") or None,
        bing_search_api_key=os.environ.get("BING_SEARCH_API_KEY") or None,
        hunter_api_key=os.environ.get("HUNTER_API_KEY") or None,
        apollo_api_key=os.environ.get("APOLLO_API_KEY") or None,
        people_data_labs_api_key=os.environ.get("PEOPLE_DATA_LABS_API_KEY") or None,
        rocketreach_api_key=os.environ.get("ROCKETREACH_API_KEY") or None,
        gmail_credentials_json=os.environ.get("GMAIL_CREDENTIALS_JSON") or None,
        gmail_token_json=os.environ.get("GMAIL_TOKEN_JSON") or None,
        gmail_sender_email=os.environ.get("GMAIL_SENDER_EMAIL") or None,
        google_calendar_credentials_json=os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON") or None,
        google_calendar_token_json=os.environ.get("GOOGLE_CALENDAR_TOKEN_JSON") or None,
        google_calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
    )
