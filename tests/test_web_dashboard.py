from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from networking_agent.agents import crm, discovery, research, scoring
from networking_agent.agents import verification as verification_agent
from networking_agent.agents.context import AgentContext
from networking_agent.config import get_settings
from networking_agent.db.base import Base
import networking_agent.db.models  # noqa: F401
from networking_agent.db.models import EmailRecord
from networking_agent.schemas.prospect import SearchResult
from networking_agent.web.app import app
from networking_agent.web.deps import get_db


class FakeSearch:
    def __init__(self, url="https://example.com/in/janedoe", name="Jane Doe", company="Snowflake"):
        self.url, self.name, self.company = url, name, company

    def search(self, query, num_results=10):
        return [
            SearchResult(
                url=self.url,
                title=f"{self.name} - Enterprise Account Executive - {self.company} | LinkedIn",
                snippet=f"{self.name}, University of Texas at Austin grad, now EAE at {self.company} based in Austin, TX.",
                query=query,
            )
        ]


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app, raise_server_exceptions=False), TestSession
    app.dependency_overrides.clear()


def _seed_person(SessionFactory, fake_search=None):
    session = SessionFactory()
    ctx = AgentContext.build(session, get_settings())
    ctx.search = fake_search or FakeSearch()
    people = discovery.discover(ctx, "tech-sales", "Austin", 1)
    person = people[0]
    verification_agent.verify_ut_status(ctx, person)
    research.research_person(ctx, person)
    scoring.score_person(ctx, person)
    crm.promote_after_scoring(ctx, person)
    session.add(EmailRecord(person_id=person.id, email_address="jane.doe@snowflake.com", is_primary=True))
    session.commit()
    person_id = person.id
    session.close()
    return person_id


@pytest.mark.parametrize(
    "path",
    ["/today", "/prospects", "/outreach", "/replies", "/meetings", "/relationships", "/analytics", "/settings"],
)
def test_pages_render_with_no_data(client, path):
    test_client, _ = client
    response = test_client.get(path)
    assert response.status_code == 200


def test_root_redirects_to_today(client):
    test_client, _ = client
    response = test_client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/today"


def test_outreach_review_and_send_flow(client):
    test_client, SessionFactory = client
    person_id = _seed_person(SessionFactory)

    outreach_page = test_client.get("/outreach")
    assert "Jane Doe" in outreach_page.text

    draft_resp = test_client.post(f"/outreach/draft/{person_id}", follow_redirects=True)
    assert draft_resp.status_code == 200
    assert "Approve" in draft_resp.text

    approve_resp = test_client.post("/outreach/1/approve", follow_redirects=True)
    assert "Send now" in approve_resp.text

    send_resp = test_client.post("/outreach/1/send", follow_redirects=True)
    assert send_resp.status_code == 200

    sent_check = SessionFactory()
    from networking_agent.db.models import Outreach

    outreach = sent_check.get(Outreach, 1)
    assert outreach.status == "SENT"
    sent_check.close()


def test_skip_does_not_send(client):
    test_client, SessionFactory = client
    person_id = _seed_person(SessionFactory)
    test_client.post(f"/outreach/draft/{person_id}", follow_redirects=True)
    test_client.post("/outreach/1/skip", follow_redirects=True)

    send_resp = test_client.post("/outreach/1/send", follow_redirects=False)
    # ApprovalRequiredError propagates as a 500 -- the point is it must not
    # silently succeed and mark this SKIPPED outreach as sent.
    assert send_resp.status_code == 500

    check = SessionFactory()
    from networking_agent.db.models import Outreach

    outreach = check.get(Outreach, 1)
    assert outreach.status == "SKIPPED"
    check.close()


def test_add_note_persists(client):
    test_client, SessionFactory = client
    person_id = _seed_person(SessionFactory)
    resp = test_client.post(
        f"/relationships/{person_id}/note", data={"note": "Great conversation at a conference."}, follow_redirects=True
    )
    assert "Great conversation at a conference." in resp.text


def test_schedule_and_collision(client):
    import datetime as dt

    test_client, SessionFactory = client
    person_id = _seed_person(SessionFactory)

    start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    ).isoformat()
    resp = test_client.post(
        "/meetings/schedule",
        data={"person_id": person_id, "start": start, "duration": 30, "meeting_type": "coffee"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "coffee" in resp.text

    # Seed a distinct second person and try to double-book the identical slot.
    second_search = FakeSearch(url="https://example.com/in/johnsmith", name="John Smith", company="CBRE")
    second_id = _seed_person(SessionFactory, second_search)
    resp2 = test_client.post(
        "/meetings/schedule",
        data={"person_id": second_id, "start": start, "duration": 30, "meeting_type": "zoom"},
        follow_redirects=False,
    )
    assert resp2.status_code == 303
    assert "error=" in resp2.headers["location"]
