import pytest
from pydantic import ValidationError

from networking_agent.schemas.prospect import CandidateExtraction, EmailDraft, ProspectEvaluation
from networking_agent.enums import UTStatus


def test_candidate_extraction_requires_first_and_last_name():
    with pytest.raises(ValidationError):
        CandidateExtraction(full_name="Cher")


def test_candidate_extraction_accepts_full_name():
    c = CandidateExtraction(full_name="Jane Smith")
    assert c.title == "UNKNOWN"


def test_email_draft_rejects_empty_body():
    with pytest.raises(ValidationError):
        EmailDraft(subject_options=["Fellow Longhorn"], body="   ")


def test_email_draft_requires_at_least_one_subject_option():
    with pytest.raises(ValidationError):
        EmailDraft(subject_options=[], body="Hello there.")


def test_prospect_evaluation_enforces_subscore_ranges():
    with pytest.raises(ValidationError):
        ProspectEvaluation(
            ut_status=UTStatus.VERIFIED,
            career_relevance_score=999,  # out of range (max 20)
            company_quality_score=10,
            seniority_score=5,
            geography_score=5,
            career_interest_score=5,
            relationship_value_score=5,
            ut_score=25,
            total_score=60,
        )


def test_prospect_evaluation_valid_payload():
    evaluation = ProspectEvaluation(
        ut_status=UTStatus.VERIFIED,
        career_relevance_score=18,
        company_quality_score=14,
        seniority_score=8,
        geography_score=10,
        career_interest_score=9,
        relationship_value_score=8,
        ut_score=25,
        total_score=92,
        networking_thesis="UT Austin alum in enterprise sales.",
    )
    assert evaluation.total_score == 92
