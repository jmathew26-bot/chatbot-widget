from networking_agent.agents.verification import verify_ut_status
from networking_agent.db.models import Source
from networking_agent.enums import UTStatus
from tests.factories import make_person


def _add_source(session, person, snippet="", title=""):
    session.add(Source(person_id=person.id, url="https://example.com", title=title, snippet=snippet))
    session.flush()
    session.refresh(person)


def test_verified_when_source_explicitly_names_ut_austin(db_session, ctx):
    person = make_person(db_session)
    _add_source(db_session, person, snippet="She graduated from the University of Texas at Austin in 2015.")
    result = verify_ut_status(ctx, person)
    assert result.ut_status == UTStatus.VERIFIED
    assert person.ut_status == "VERIFIED"


def test_false_when_source_names_a_different_ut_system_school(db_session, ctx):
    person = make_person(db_session)
    _add_source(db_session, person, snippet="He earned his degree from UT Dallas in 2012.")
    result = verify_ut_status(ctx, person)
    assert result.ut_status == UTStatus.FALSE


def test_unverified_when_no_evidence_either_way(db_session, ctx):
    person = make_person(db_session)
    _add_source(db_session, person, snippet="He works in sales in Austin.")
    result = verify_ut_status(ctx, person)
    assert result.ut_status == UTStatus.UNVERIFIED


def test_does_not_confuse_ut_san_antonio_with_ut_austin(db_session, ctx):
    person = make_person(db_session)
    _add_source(db_session, person, snippet="Graduate of the University of Texas at San Antonio.")
    result = verify_ut_status(ctx, person)
    assert result.ut_status == UTStatus.FALSE
