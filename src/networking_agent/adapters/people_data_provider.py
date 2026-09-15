from __future__ import annotations

import logging

import httpx

from networking_agent.adapters.base import DiscoveredEmail, PeopleDataProvider
from networking_agent.config import Settings

logger = logging.getLogger("networking_agent.people_data")


class NullPeopleDataProvider(PeopleDataProvider):
    """No email-discovery provider configured. Never guesses -- returns
    None so the caller records email verification_status=UNVERIFIED and
    leaves the field for manual entry."""

    def find_email(self, full_name: str, company: str, domain: str | None) -> DiscoveredEmail | None:
        return None


class HunterEmailFinder(PeopleDataProvider):
    """Hunter.io Email Finder API. Requires a company domain (Hunter's API
    is domain-based, not name-based search)."""

    BASE_URL = "https://api.hunter.io/v2/email-finder"

    def __init__(self, api_key: str, timeout: float = 10.0):
        self.api_key = api_key
        self.timeout = timeout

    def find_email(self, full_name: str, company: str, domain: str | None) -> DiscoveredEmail | None:
        if not domain:
            logger.info("HunterEmailFinder: no domain known for %s at %s, skipping", full_name, company)
            return None
        parts = full_name.split()
        params = {
            "domain": domain,
            "first_name": parts[0],
            "last_name": parts[-1] if len(parts) > 1 else "",
            "api_key": self.api_key,
        }
        try:
            resp = httpx.get(self.BASE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except httpx.HTTPError as e:
            logger.warning("Hunter lookup failed for %s: %s", full_name, e)
            return None
        email = data.get("email")
        if not email:
            return None
        score = data.get("score", 0)  # 0-100
        status = "HIGH_CONFIDENCE" if score >= 80 else "UNVERIFIED"
        return DiscoveredEmail(email=email, source="hunter.io", confidence=score / 100.0, verification_status=status)


def get_people_data_provider(settings: Settings) -> PeopleDataProvider:
    if settings.hunter_api_key:
        return HunterEmailFinder(settings.hunter_api_key)
    return NullPeopleDataProvider()
