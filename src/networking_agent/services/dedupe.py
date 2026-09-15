"""Duplicate prevention. Every path that could create a new Person or send
an email must go through here first -- see design doc "DUPLICATE
PREVENTION": search by email, full name + company, profile URL, and
normalized identity before ever treating someone as a new prospect.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from networking_agent.db.models import EmailRecord, Person


def normalize_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def normalize_company(company: str) -> str:
    company = company.lower().strip()
    company = re.sub(r"[^a-z0-9\s]", "", company)
    suffixes = [" inc", " llc", " corp", " corporation", " company", " co", " lp", " llp"]
    for suf in suffixes:
        if company.endswith(suf):
            company = company[: -len(suf)]
    return re.sub(r"\s+", " ", company).strip()


def build_normalized_identity(full_name: str, company: str, profile_url: str | None) -> str:
    if profile_url:
        return f"url:{profile_url.strip().rstrip('/').lower()}"
    return f"name:{normalize_name(full_name)}|company:{normalize_company(company)}"


def find_existing_person(
    session: Session, full_name: str, company: str, profile_url: str | None = None, email: str | None = None
) -> Person | None:
    if email:
        record = session.execute(
            select(EmailRecord).where(EmailRecord.email_address == email.lower().strip())
        ).scalar_one_or_none()
        if record:
            return session.get(Person, record.person_id)

    normalized_identity = build_normalized_identity(full_name, company, profile_url)
    existing = session.execute(
        select(Person).where(Person.normalized_identity == normalized_identity)
    ).scalar_one_or_none()
    if existing:
        return existing

    if profile_url:
        # Also check name+company match in case the same person was
        # discovered once via profile_url and once without it.
        fallback_identity = build_normalized_identity(full_name, company, None)
        existing = session.execute(
            select(Person).where(Person.normalized_identity == fallback_identity)
        ).scalar_one_or_none()
        if existing:
            return existing

    return None
