"""Domain model for the deterministic triage engine.

These mirror the Salesforce reference objects one-to-one so the exported
data drops in without transformation:

    Specialty__c              -> Specialty
    Symptom__c                -> Symptom
    Condition__c              -> Condition
    Symptom_Condition_Map__c  -> Mapping

Nothing in this module knows about Gemini, ADK, or Google Cloud. That is
deliberate: the engine must be testable and reproducible on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


TRIAGE_LEVELS = ("Routine", "Urgent", "Critical")
PRIORITY_RANK = {level: i for i, level in enumerate(TRIAGE_LEVELS)}


@dataclass(frozen=True)
class Specialty:
    external_id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class Symptom:
    external_id: str
    name: str
    body_system: str = "General"


@dataclass(frozen=True)
class Condition:
    external_id: str
    name: str
    recommended_specialty: str
    triage_priority: str
    is_red_flag: bool = False
    clinical_note: str = ""

    def __post_init__(self) -> None:
        if self.triage_priority not in PRIORITY_RANK:
            raise ValueError(
                f"{self.external_id}: triage_priority {self.triage_priority!r} "
                f"must be one of {TRIAGE_LEVELS}"
            )


@dataclass(frozen=True)
class Mapping:
    external_id: str
    symptom: str
    condition: str
    weight: int


@dataclass
class Contribution:
    """One symptom's contribution to one condition's score."""

    symptom_id: str
    symptom_name: str
    weight: int


@dataclass
class ScoredCondition:
    rank: int
    external_id: str
    name: str
    score: int
    triage_priority: str
    is_red_flag: bool
    recommended_specialty: str
    specialty_name: str
    clinical_note: str = ""
    contributions: list[Contribution] = field(default_factory=list)

    def why(self) -> str:
        """Human-readable breakdown. This is the answer to 'why this rank?'."""
        parts = [f"{c.symptom_name} +{c.weight}" for c in self.contributions]
        return f"{self.name}: {' , '.join(parts)} = {self.score}"


@dataclass
class TriageResult:
    triage_level: str
    recommended_specialty: str
    specialty_name: str
    is_red_flag: bool
    probable_conditions: list[ScoredCondition]
    matched_symptoms: list[str]
    unknown_symptoms: list[str]
    rationale: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
