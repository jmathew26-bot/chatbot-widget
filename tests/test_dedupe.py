from networking_agent.services.dedupe import (
    build_normalized_identity,
    find_existing_person,
    normalize_company,
    normalize_name,
)
from tests.factories import make_person


def test_normalize_name_strips_case_and_punctuation():
    assert normalize_name("Jane  Q. Smith!") == "jane q smith"


def test_normalize_company_strips_legal_suffixes():
    assert normalize_company("Stream Realty Partners, LLC") == "stream realty partners"


def test_same_person_same_company_is_duplicate(db_session):
    make_person(db_session, full_name="Jane Smith", company_name="Salesforce")
    existing = find_existing_person(db_session, "Jane Smith", "Salesforce")
    assert existing is not None
    assert existing.full_name == "Jane Smith"


def test_different_person_same_company_is_not_duplicate(db_session):
    make_person(db_session, full_name="Jane Smith", company_name="Salesforce")
    existing = find_existing_person(db_session, "John Doe", "Salesforce")
    assert existing is None


def test_same_profile_url_is_duplicate_even_if_name_varies_slightly(db_session):
    url = "https://example.com/in/janesmith"
    make_person(db_session, full_name="Jane Smith", company_name="Salesforce", profile_url=url)
    existing = find_existing_person(db_session, "Jane Q Smith", "Salesforce Inc", profile_url=url)
    assert existing is not None


def test_email_match_is_duplicate(db_session):
    from networking_agent.db.models import EmailRecord

    person = make_person(db_session, full_name="Jane Smith", company_name="Salesforce")
    db_session.add(EmailRecord(person_id=person.id, email_address="jane@salesforce.com"))
    db_session.flush()

    existing = find_existing_person(db_session, "Someone Else", "Other Co", email="jane@salesforce.com")
    assert existing is not None
    assert existing.id == person.id


def test_build_normalized_identity_prefers_url():
    assert build_normalized_identity("A B", "C", "https://x.com/Y/") == "url:https://x.com/y"
