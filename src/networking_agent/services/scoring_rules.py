"""Deterministic, reproducible scoring. Kept rule-based (not LLM-based) so
that scores are stable, testable, and explainable -- the same inputs
always produce the same score, and analytics can attribute outcomes to
specific factors. The LLM is used elsewhere (Research/Email agents) for
prose, not for arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass

from networking_agent.config import ScoringWeights
from networking_agent.enums import UTStatus

SENIOR_TITLE_KEYWORDS = [
    "chief", "cro", "cto", "ceo", "president", "managing director", "partner",
    "executive vice president", "evp", "senior vice president", "svp",
    "vice president", "vp", "area vice president", "regional vice president",
    "head of", "director",
]
MID_TITLE_KEYWORDS = ["manager", "senior", "sr.", "sr ", "principal", "lead"]

EXACT_TITLE_MATCH_BONUS = 20
PARTIAL_TITLE_MATCH_BONUS = 10


@dataclass
class ScoreBreakdown:
    ut_score: int
    career_relevance_score: int
    company_quality_score: int
    seniority_score: int
    geography_score: int
    career_interest_score: int
    relationship_value_score: int
    total_score: int
    classification: str


def score_ut(ut_status: UTStatus, weight: int) -> int:
    if ut_status == UTStatus.VERIFIED:
        return weight
    if ut_status == UTStatus.LIKELY:
        return round(weight * 0.6)
    return 0  # UNVERIFIED, FALSE


def score_career_relevance(title: str, target_titles: list[str], category_match: bool, weight: int) -> int:
    if not category_match:
        return round(weight * 0.15)
    title_lower = title.lower().strip()
    normalized_targets = [t.lower() for t in target_titles]
    if title_lower in normalized_targets:
        return weight
    if any(t in title_lower or title_lower in t for t in normalized_targets):
        return round(weight * 0.7)
    return round(weight * 0.35)


def score_company_quality(company_quality_0_100: int, weight: int) -> int:
    return round(weight * (max(0, min(company_quality_0_100, 100)) / 100))


def score_seniority(title: str, weight: int) -> int:
    title_lower = title.lower()
    if any(k in title_lower for k in SENIOR_TITLE_KEYWORDS):
        return weight
    if any(k in title_lower for k in MID_TITLE_KEYWORDS):
        return round(weight * 0.65)
    # Individual contributors are still approachable, valuable contacts --
    # design doc explicitly warns against only targeting senior executives.
    return round(weight * 0.4)


def score_geography(location: str, tier_1: list[str], tier_2: list[str], tier_3: list[str], weight: int) -> int:
    location_lower = (location or "").lower()
    if location_lower == "unknown" or not location_lower:
        return 0
    if any(t.lower() in location_lower for t in tier_1):
        return weight
    if any(t.lower() in location_lower for t in tier_2):
        return round(weight * 0.7)
    if any(t.lower() in location_lower for t in tier_3):
        return round(weight * 0.4)
    return round(weight * 0.2)


def score_career_interest(num_employers: int, has_notable_transition: bool, weight: int) -> int:
    base = min(num_employers, 4) / 4 * weight * 0.6
    if has_notable_transition:
        base += weight * 0.4
    return round(min(base, weight))


def score_relationship_value(seniority_score: int, seniority_weight: int, category_match: bool, weight: int) -> int:
    seniority_ratio = seniority_score / seniority_weight if seniority_weight else 0
    base = seniority_ratio * weight * 0.7
    if category_match:
        base += weight * 0.3
    return round(min(base, weight))


def classify(total_score: int, thresholds: dict[str, int]) -> str:
    if total_score >= thresholds.get("exceptional", 90):
        return "Exceptional"
    if total_score >= thresholds.get("high_priority", 80):
        return "High Priority"
    if total_score >= thresholds.get("good", 70):
        return "Good"
    if total_score >= thresholds.get("review", 60):
        return "Review"
    return "Do Not Contact Automatically"


def compute_score(
    *,
    ut_status: UTStatus,
    title: str,
    target_titles: list[str],
    category_match: bool,
    company_quality_0_100: int,
    location: str,
    tier_1: list[str],
    tier_2: list[str],
    tier_3: list[str],
    num_employers: int,
    has_notable_transition: bool,
    weights: ScoringWeights,
    thresholds: dict[str, int],
) -> ScoreBreakdown:
    ut = score_ut(ut_status, weights.ut_austin)
    career_relevance = score_career_relevance(title, target_titles, category_match, weights.career_relevance)
    company_quality = score_company_quality(company_quality_0_100, weights.company_quality)
    seniority = score_seniority(title, weights.seniority)
    geography = score_geography(location, tier_1, tier_2, tier_3, weights.geography)
    career_interest = score_career_interest(num_employers, has_notable_transition, weights.career_interest)
    relationship_value = score_relationship_value(
        seniority, weights.seniority, category_match, weights.relationship_value
    )

    total = ut + career_relevance + company_quality + seniority + geography + career_interest + relationship_value
    total = max(0, min(total, 100))

    # FALSE UT status (attended a different UT system school) is disqualifying
    # regardless of everything else -- never auto-contact on a false premise.
    if ut_status == UTStatus.FALSE:
        total = min(total, 40)

    return ScoreBreakdown(
        ut_score=ut,
        career_relevance_score=career_relevance,
        company_quality_score=company_quality,
        seniority_score=seniority,
        geography_score=geography,
        career_interest_score=career_interest,
        relationship_value_score=relationship_value,
        total_score=total,
        classification=classify(total, thresholds),
    )
