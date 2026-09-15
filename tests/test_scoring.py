from networking_agent.config import ScoringWeights
from networking_agent.enums import UTStatus
from networking_agent.services.scoring_rules import compute_score


def _score(**overrides):
    defaults = dict(
        ut_status=UTStatus.VERIFIED,
        title="Enterprise Account Executive",
        target_titles=["Enterprise Account Executive", "Account Executive"],
        category_match=True,
        company_quality_0_100=90,
        location="Austin, TX",
        tier_1=["Austin"],
        tier_2=["Texas"],
        tier_3=["Denver"],
        num_employers=3,
        has_notable_transition=True,
        weights=ScoringWeights(),
        thresholds={"exceptional": 90, "high_priority": 80, "good": 70, "review": 60},
    )
    defaults.update(overrides)
    return compute_score(**defaults)


def test_verified_ut_gets_full_ut_weight():
    result = _score(ut_status=UTStatus.VERIFIED)
    assert result.ut_score == 25


def test_likely_ut_gets_partial_weight():
    result = _score(ut_status=UTStatus.LIKELY)
    assert 0 < result.ut_score < 25


def test_unverified_ut_gets_zero():
    result = _score(ut_status=UTStatus.UNVERIFIED)
    assert result.ut_score == 0


def test_false_ut_is_capped_low_regardless_of_other_factors():
    result = _score(ut_status=UTStatus.FALSE)
    assert result.total_score <= 40


def test_austin_location_scores_higher_than_out_of_footprint():
    austin = _score(location="Austin, TX")
    other = _score(location="Miami, FL")
    assert austin.geography_score > other.geography_score


def test_total_score_never_exceeds_100():
    result = _score()
    assert result.total_score <= 100


def test_score_is_deterministic():
    a = _score()
    b = _score()
    assert a == b


def test_classification_thresholds():
    from networking_agent.services.scoring_rules import classify

    thresholds = {"exceptional": 90, "high_priority": 80, "good": 70, "review": 60}
    assert classify(95, thresholds) == "Exceptional"
    assert classify(85, thresholds) == "High Priority"
    assert classify(75, thresholds) == "Good"
    assert classify(65, thresholds) == "Review"
    assert classify(40, thresholds) == "Do Not Contact Automatically"
