"""Data shapes for the patient health ledger.

Two things live here:

  DocumentFacts -- what the extractor pulls out of ONE document. This is
      the fixed schema Gemini is asked to fill. It only ever reports what
      a document literally says.

  Ledger -- the single compacted record per patient, built by merging
      many DocumentFacts together. This is what a later triage or brief
      step reads instead of forty raw pages.

Nothing in this module talks to Gemini, Drive, or Firestore. It is plain
data, so the merge logic that operates on it stays testable offline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Severity ordering for allergies. When two documents disagree, the more
# severe wins -- under-stating an allergy is the dangerous direction.
SEVERITY_ORDER = {"": 0, "unknown": 0, "mild": 1, "moderate": 2, "severe": 3}


@dataclass
class Allergy:
    allergen: str
    reaction: str = ""
    severity: str = ""  # Mild / Moderate / Severe / Unknown
    source: str = ""
    first_seen: str = ""  # the date of the document it first appeared in


@dataclass
class ChronicCondition:
    name: str
    diagnosed_date: str = ""
    status: str = "active"
    source: str = ""


@dataclass
class Medication:
    drug: str
    dose: str = ""
    frequency: str = ""
    indication: str = ""
    status: str = "active"  # active / stopped
    prescribed_date: str = ""
    sources: list[str] = field(default_factory=list)


@dataclass
class LabValue:
    analyte: str
    value: float
    unit: str = ""
    date: str = ""
    ref_range: str = ""
    flag: str = ""  # high / low / normal
    source: str = ""


@dataclass
class DocumentRecord:
    filename: str
    doc_type: str = ""
    doc_date: str = ""
    ingested_at: str = ""
    content_hash: str = ""


@dataclass
class DocumentFacts:
    """Everything the extractor found in a single document."""

    doc_type: str = ""
    doc_date: str = ""
    allergies: list[Allergy] = field(default_factory=list)
    chronic_conditions: list[ChronicCondition] = field(default_factory=list)
    medications: list[Medication] = field(default_factory=list)
    labs: list[LabValue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Ledger:
    patient_id: str
    patient_name: str = ""
    allergies: list[Allergy] = field(default_factory=list)
    chronic_conditions: list[ChronicCondition] = field(default_factory=list)
    medications: list[Medication] = field(default_factory=list)
    # analyte name -> time-ordered series. This is where trends live.
    lab_results: dict[str, list[LabValue]] = field(default_factory=dict)
    documents: list[DocumentRecord] = field(default_factory=list)
    clinical_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Ledger":
        led = cls(
            patient_id=data["patient_id"],
            patient_name=data.get("patient_name", ""),
            clinical_notes=list(data.get("clinical_notes", [])),
        )
        led.allergies = [Allergy(**a) for a in data.get("allergies", [])]
        led.chronic_conditions = [
            ChronicCondition(**c) for c in data.get("chronic_conditions", [])
        ]
        led.medications = [Medication(**m) for m in data.get("medications", [])]
        led.documents = [DocumentRecord(**d) for d in data.get("documents", [])]
        led.lab_results = {
            analyte: [LabValue(**v) for v in series]
            for analyte, series in data.get("lab_results", {}).items()
        }
        return led

    def lab_trend(self, analyte: str) -> str:
        """Render one analyte's series as an arrow chain, e.g. 6.8 -> 7.2 -> 7.5."""
        series = self.lab_results.get(analyte, [])
        if not series:
            return f"{analyte}: no readings"
        unit = series[-1].unit
        chain = " -> ".join(f"{v.value:g}" for v in series)
        return f"{analyte}: {chain} {unit}".rstrip()
