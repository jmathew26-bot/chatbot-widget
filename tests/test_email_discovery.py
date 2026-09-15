from networking_agent.adapters.base import DiscoveredEmail
from networking_agent.agents import email_discovery
from networking_agent.db.models import Company, EmailRecord
from tests.factories import make_person


class FakePeopleDataProvider:
    def __init__(self, result: DiscoveredEmail | None):
        self.result = result
        self.calls = []

    def find_email(self, full_name, company, domain):
        self.calls.append((full_name, company, domain))
        return self.result


def _add_company(session, name="Salesforce"):
    company = Company(name=name, normalized_name=name.lower(), category="tech-sales", quality_score=80)
    session.add(company)
    session.flush()
    return company


def test_discover_email_creates_record_when_provider_finds_one(db_session, ctx):
    company = _add_company(db_session)
    person = make_person(db_session, current_company_id=company.id)
    ctx.people_data = FakePeopleDataProvider(
        DiscoveredEmail(email="jane@salesforce.com", source="hunter.io", confidence=0.95, verification_status="HIGH_CONFIDENCE")
    )

    record = email_discovery.discover_email(ctx, person)

    assert record is not None
    assert record.email_address == "jane@salesforce.com"
    assert record.verification_status == "HIGH_CONFIDENCE"
    assert record.is_primary is True


def test_discover_email_returns_none_when_provider_finds_nothing(db_session, ctx):
    company = _add_company(db_session)
    person = make_person(db_session, current_company_id=company.id)
    ctx.people_data = FakePeopleDataProvider(None)

    record = email_discovery.discover_email(ctx, person)

    assert record is None
    assert person.emails == []


def test_discover_email_skips_if_person_already_has_primary_email(db_session, ctx):
    company = _add_company(db_session)
    person = make_person(db_session, current_company_id=company.id)
    db_session.add(EmailRecord(person_id=person.id, email_address="existing@x.com", is_primary=True))
    db_session.flush()
    db_session.refresh(person)

    provider = FakePeopleDataProvider(
        DiscoveredEmail(email="new@x.com", source="hunter.io", confidence=0.9, verification_status="VERIFIED")
    )
    ctx.people_data = provider

    record = email_discovery.discover_email(ctx, person)

    assert record is None
    assert len(provider.calls) == 0  # never even looked it up


def test_discover_email_returns_none_without_company(db_session, ctx):
    person = make_person(db_session, current_company_id=None)
    ctx.people_data = FakePeopleDataProvider(
        DiscoveredEmail(email="x@y.com", source="hunter.io", confidence=0.9, verification_status="VERIFIED")
    )

    record = email_discovery.discover_email(ctx, person)

    assert record is None


def test_discover_email_upgrades_unverified_via_mx_check(db_session, ctx):
    """Hunter can return UNVERIFIED (low score); the local MX/A check
    should be allowed to upgrade it to HIGH_CONFIDENCE (never downgrade a
    provider's own better verdict)."""
    company = _add_company(db_session)
    person = make_person(db_session, current_company_id=company.id)
    ctx.people_data = FakePeopleDataProvider(
        DiscoveredEmail(email="jane@salesforce.com", source="hunter.io", confidence=0.3, verification_status="UNVERIFIED")
    )
    # ctx.email_verification is FakeEmailVerifier from conftest, always returns HIGH_CONFIDENCE

    record = email_discovery.discover_email(ctx, person)

    assert record.verification_status == "HIGH_CONFIDENCE"


def test_discover_email_keeps_verified_status_from_provider(db_session, ctx):
    """A provider-reported VERIFIED status must not be re-run through (and
    potentially downgraded by) the local MX check."""
    company = _add_company(db_session)
    person = make_person(db_session, current_company_id=company.id)

    class DowngradingVerifier:
        def verify(self, email):
            return "UNVERIFIED"

    ctx.email_verification = DowngradingVerifier()
    ctx.people_data = FakePeopleDataProvider(
        DiscoveredEmail(email="jane@salesforce.com", source="hunter.io", confidence=0.99, verification_status="VERIFIED")
    )

    record = email_discovery.discover_email(ctx, person)

    assert record.verification_status == "VERIFIED"
