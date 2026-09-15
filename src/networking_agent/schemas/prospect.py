"""Schema-validated structures passed between agents and produced by LLM
calls. Nothing gets written to the DB without passing through one of
these -- this is the enforcement point for "validate all model output
before inserting into the database."
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from networking_agent.enums import ReplyClassification, UTStatus


class SearchResult(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    query: str = ""


class CandidateExtraction(BaseModel):
    """One candidate person pulled out of a search result by the Discovery
    Agent, before verification/research/scoring."""

    full_name: str
    title: str = "UNKNOWN"
    company: str = "UNKNOWN"
    location: str = "UNKNOWN"
    category: str = "other"
    profile_url: str | None = None
    evidence_snippet: str = ""
    source_url: str = ""

    @field_validator("full_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v.split()) < 2:
            raise ValueError("full_name must contain at least a first and last name")
        return v


class CandidateExtractionResponse(BaseModel):
    """Wrapper the LLM returns for one search result: either a plausible
    named individual matching the target persona, or not."""

    is_candidate: bool
    candidate: CandidateExtraction | None = None


class UTVerificationResult(BaseModel):
    ut_status: UTStatus
    ut_degree: str = "UNKNOWN"
    ut_grad_year: int | None = None
    rationale: str
    sources: list[str] = Field(default_factory=list)


class ProspectEvaluation(BaseModel):
    """Mirrors the scoring JSON contract in the design doc."""

    person_id: int | str = ""
    ut_status: UTStatus
    career_relevance_score: int = Field(ge=0, le=20)
    company_quality_score: int = Field(ge=0, le=15)
    seniority_score: int = Field(ge=0, le=10)
    geography_score: int = Field(ge=0, le=10)
    career_interest_score: int = Field(ge=0, le=10)
    relationship_value_score: int = Field(ge=0, le=10)
    ut_score: int = Field(ge=0, le=25)
    total_score: int = Field(ge=0, le=100)
    networking_thesis: str = ""
    personalization_angles: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class EmailDraft(BaseModel):
    subject_options: list[str] = Field(min_length=1, max_length=3)
    body: str
    word_count: int = 0
    personalization_used: str = ""
    template_tag: str = "default"

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body must not be empty")
        return v


class ReplyClassificationResult(BaseModel):
    classification: ReplyClassification
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str = ""
    suggested_next_action: str = ""
