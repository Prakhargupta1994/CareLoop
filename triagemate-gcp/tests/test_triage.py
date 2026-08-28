"""Engine tests. These are the reproducibility argument, so keep them honest.

    python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careloop.engine.loader import load_dataset  # noqa: E402
from careloop.engine.triage import TriageEngine  # noqa: E402


@pytest.fixture(scope="module")
def engine() -> TriageEngine:
    return TriageEngine(load_dataset())


def test_dataset_has_no_integrity_problems():
    problems = load_dataset().validate()
    assert problems == [], "\n".join(problems)


def test_emergency_specialty_exists():
    data = load_dataset()
    assert "SPEC_EM" in data.specialties
    assert data.specialties["SPEC_EM"].name == "Emergency Medicine"


def test_rakesh_chest_pain_is_critical_emergency(engine):
    """The canonical smoke test carried over from the Salesforce build."""
    result = engine.score(
        ["SYM_CHEST_PAIN_RAD", "SYM_CHEST_PAIN", "SYM_SWEATING", "SYM_SOB"]
    )
    assert result.triage_level == "Critical"
    assert result.specialty_name == "Emergency Medicine"
    assert result.is_red_flag is True
    assert result.probable_conditions[0].name == "Acute coronary syndrome"
    assert result.probable_conditions[0].score == 28


def test_anita_osmotic_symptoms_route_to_endocrinology(engine):
    result = engine.score(
        ["SYM_THIRST", "SYM_FREQ_URINATION", "SYM_BLURRED_VISION", "SYM_WEIGHT_LOSS"]
    )
    assert result.triage_level == "Urgent"
    assert result.specialty_name == "Endocrinology"
    assert result.is_red_flag is False
    assert result.probable_conditions[0].name == "Type 2 diabetes mellitus"


def test_sneha_cold_symptoms_stay_routine(engine):
    result = engine.score(["SYM_RUNNY_NOSE", "SYM_SNEEZING", "SYM_SORE_THROAT"])
    assert result.triage_level == "Routine"
    assert result.is_red_flag is False
    assert result.recommended_specialty in {"SPEC_GP", "SPEC_ENT"}


def test_red_flag_overrides_a_higher_scoring_authored_priority(engine):
    """Meningitis outranks migraine and forces Critical + Emergency."""
    result = engine.score(
        ["SYM_NECK_STIFF", "SYM_PHOTOPHOBIA", "SYM_FEVER", "SYM_HEADACHE"]
    )
    assert result.probable_conditions[0].name == "Meningitis"
    assert result.triage_level == "Critical"
    assert result.recommended_specialty == "SPEC_EM"
    assert any("RED-FLAG OVERRIDE" in line for line in result.rationale)


def test_unknown_symptoms_are_reported_not_swallowed(engine):
    result = engine.score(["SYM_CHEST_PAIN", "SYM_TELEPORTATION"])
    assert "SYM_TELEPORTATION" in result.unknown_symptoms
    assert "SYM_CHEST_PAIN" in result.matched_symptoms


def test_empty_input_degrades_safely(engine):
    result = engine.score([])
    assert result.triage_level == "Routine"
    assert result.probable_conditions == []
    assert result.is_red_flag is False


def test_input_is_order_and_case_insensitive(engine):
    a = engine.score(["SYM_CHEST_PAIN_RAD", "SYM_SWEATING", "SYM_SOB"])
    b = engine.score(["sym_sob", " SYM_SWEATING ", "SYM_CHEST_PAIN_RAD"])
    assert a.triage_level == b.triage_level
    assert a.recommended_specialty == b.recommended_specialty
    assert [c.name for c in a.probable_conditions] == [
        c.name for c in b.probable_conditions
    ]


def test_duplicate_symptoms_do_not_inflate_the_score(engine):
    once = engine.score(["SYM_CHEST_PAIN"])
    twice = engine.score(["SYM_CHEST_PAIN", "SYM_CHEST_PAIN"])
    assert once.probable_conditions[0].score == twice.probable_conditions[0].score


def test_engine_is_deterministic_across_repeated_runs(engine):
    """Same input, twenty runs, byte-identical output. This is the pitch."""
    symptoms = ["SYM_FEVER", "SYM_COUGH", "SYM_SORE_THROAT", "SYM_FATIGUE"]
    baseline = engine.score(symptoms).to_dict()
    for _ in range(20):
        assert engine.score(symptoms).to_dict() == baseline


def test_score_breakdown_sums_to_the_reported_score(engine):
    result = engine.score(["SYM_CHEST_PAIN_RAD", "SYM_SWEATING", "SYM_SOB"])
    for condition in result.probable_conditions:
        assert sum(c.weight for c in condition.contributions) == condition.score
