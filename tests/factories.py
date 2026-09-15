from __future__ import annotations

from networking_agent.db.models import Person, Relationship
from networking_agent.enums import RelationshipStatus
from networking_agent.services.dedupe import build_normalized_identity


def make_person(session, full_name="Jane Smith", company_name="Salesforce", category="tech-sales", **kwargs) -> Person:
    profile_url = kwargs.get("profile_url")
    defaults = dict(
        full_name=full_name,
        first_name=full_name.split()[0],
        last_name=full_name.split()[-1],
        normalized_identity=build_normalized_identity(full_name, company_name, profile_url),
        current_title="Account Executive",
        location="Austin, TX",
        category=category,
        ut_status="UNVERIFIED",
    )
    defaults.update(kwargs)
    person = Person(**defaults)
    session.add(person)
    session.flush()
    session.add(Relationship(person_id=person.id, status=RelationshipStatus.DISCOVERED.value))
    session.flush()
    session.refresh(person)
    return person
