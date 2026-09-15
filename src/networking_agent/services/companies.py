from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.db.models import Company
from networking_agent.services.dedupe import normalize_company

# Coarse default quality scores for companies named directly in the target
# lists (config/config.yaml). Anything not in this list starts neutral (50)
# and can be raised/lowered manually in the companies table as the learning
# loop accumulates response-rate data.
_KNOWN_QUALITY_DEFAULTS = 80


def get_or_create_company(
    session: Session, name: str, category: str, austin_presence: bool = False, texas_presence: bool = False
) -> Company | None:
    if not name or name.strip().upper() == "UNKNOWN":
        return None
    normalized = normalize_company(name)
    existing = session.execute(
        select(Company).where(Company.normalized_name == normalized)
    ).scalar_one_or_none()
    if existing:
        return existing
    company = Company(
        name=name.strip(),
        normalized_name=normalized,
        category=category,
        quality_score=_KNOWN_QUALITY_DEFAULTS,
        austin_presence=austin_presence,
        texas_presence=texas_presence,
    )
    session.add(company)
    session.flush()
    return company


def is_known_target_company(settings_targets: dict, category: str, name: str) -> bool:
    key = "cre" if category == "cre" else "tech_sales"
    companies = settings_targets.get(key, {}).get("companies", [])
    normalized_targets = {normalize_company(c) for c in companies}
    return normalize_company(name) in normalized_targets


def guess_domain(company: Company | str) -> str | None:
    """Best-effort domain guess for a company name, used when no verified
    website is on file. This is a heuristic (companyname.com) -- it is
    intentionally never treated as a verified fact, only as an input to
    PeopleDataProvider.find_email(), whose own confidence/verification
    status is what actually gates sending."""
    website = company.website if isinstance(company, Company) else None
    if website:
        return website.replace("https://", "").replace("http://", "").split("/")[0]
    name = company if isinstance(company, str) else company.name
    if not name:
        return None
    cleaned = (
        name.lower()
        .replace(" & ", "")
        .replace("&", "")
        .replace(",", "")
        .replace(".", "")
        .split(" (")[0]
    )
    cleaned = "".join(ch for ch in cleaned if ch.isalnum())
    return f"{cleaned}.com" if cleaned else None
