"""Compaction merge tests -- pure, offline, deterministic.

These construct DocumentFacts directly and exercise the merge rules
without any extractor or model. This is the correctness proof for the
ledger: the same facts always produce the same ledger.

    python -m pytest tests/test_compact.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careloop.ledger.compact import merge_facts  # noqa: E402
from careloop.ledger.schema import (  # noqa: E402
    Allergy,
    ChronicCondition,
    DocumentFacts,
    DocumentRecord,
    Ledger,
    LabValue,
    Medication,
)


def rec(name: str, date: str = "", h: str = "") -> DocumentRecord:
    return DocumentRecord(filename=name, doc_date=date, content_hash=h or name)


@pytest.fixture
def ledger() -> Ledger:
    return Ledger(patient_id="anita", patient_name="Anita Rao")


def test_single_lab_value_lands_in_a_series(ledger):
    merge_facts(
        ledger,
        DocumentFacts(labs=[LabValue("HbA1c", 6.8, "%", "2024-01-15")]),
        rec("a.txt", "2024-01-15"),
    )
    assert [v.value for v in ledger.lab_results["HbA1c"]] == [6.8]


def test_lab_values_form_a_chronological_trend(ledger):
    # Ingested out of order on purpose; the series must still sort by date.
    merge_facts(ledger, DocumentFacts(labs=[LabValue("HbA1c", 7.5, "%", "2024-08-10")]), rec("c.txt", "2024-08-10"))
    merge_facts(ledger, DocumentFacts(labs=[LabValue("HbA1c", 6.8, "%", "2024-01-15")]), rec("a.txt", "2024-01-15"))
    merge_facts(ledger, DocumentFacts(labs=[LabValue("HbA1c", 7.2, "%", "2024-04-20")]), rec("b.txt", "2024-04-20"))
    assert [v.value for v in ledger.lab_results["HbA1c"]] == [6.8, 7.2, 7.5]
    assert ledger.lab_trend("HbA1c") == "HbA1c: 6.8 -> 7.2 -> 7.5 %"


def test_reingesting_the_same_document_is_a_noop(ledger):
    facts = DocumentFacts(labs=[LabValue("HbA1c", 6.8, "%", "2024-01-15")])
    doc = rec("a.txt", "2024-01-15", h="HASH1")
    assert merge_facts(ledger, facts, doc) is True
    # Same hash again -> skipped, no duplicate point.
    assert merge_facts(ledger, facts, doc) is False
    assert len(ledger.lab_results["HbA1c"]) == 1
    assert len(ledger.documents) == 1


def test_same_reading_from_two_files_is_not_double_counted(ledger):
    # Different files (different hashes) but the identical date+value reading.
    merge_facts(ledger, DocumentFacts(labs=[LabValue("HbA1c", 6.8, "%", "2024-01-15")]), rec("a.txt", h="H1"))
    merge_facts(ledger, DocumentFacts(labs=[LabValue("HbA1c", 6.8, "%", "2024-01-15")]), rec("b.txt", h="H2"))
    assert len(ledger.lab_results["HbA1c"]) == 1


def test_multiple_analytes_are_tracked_independently(ledger):
    merge_facts(
        ledger,
        DocumentFacts(
            labs=[
                LabValue("HbA1c", 6.8, "%", "2024-01-15"),
                LabValue("LDL", 142, "mg/dL", "2024-01-15"),
            ]
        ),
        rec("a.txt", "2024-01-15"),
    )
    assert set(ledger.lab_results) == {"HbA1c", "LDL"}


def test_allergy_dedup_keeps_the_more_severe_reading(ledger):
    merge_facts(ledger, DocumentFacts(allergies=[Allergy("Penicillin", "rash", "Moderate")]), rec("a.txt", h="H1"))
    merge_facts(ledger, DocumentFacts(allergies=[Allergy("Penicillin", "swelling", "Severe")]), rec("b.txt", h="H2"))
    assert len(ledger.allergies) == 1
    assert ledger.allergies[0].severity == "Severe"


def test_allergy_severity_never_downgrades(ledger):
    merge_facts(ledger, DocumentFacts(allergies=[Allergy("Penicillin", "", "Severe")]), rec("a.txt", h="H1"))
    merge_facts(ledger, DocumentFacts(allergies=[Allergy("Penicillin", "", "Mild")]), rec("b.txt", h="H2"))
    assert ledger.allergies[0].severity == "Severe"


def test_medication_latest_dose_wins_and_sources_accumulate(ledger):
    merge_facts(ledger, DocumentFacts(medications=[Medication("Metformin", "500 mg", "twice daily")]), rec("script.txt", h="H1"))
    merge_facts(ledger, DocumentFacts(medications=[Medication("Metformin", "1000 mg", "twice daily")]), rec("visit.txt", h="H2"))
    assert len(ledger.medications) == 1
    assert ledger.medications[0].dose == "1000 mg"
    assert ledger.medications[0].sources == ["script.txt", "visit.txt"]


def test_chronic_condition_dedup_keeps_earliest_diagnosis(ledger):
    merge_facts(ledger, DocumentFacts(chronic_conditions=[ChronicCondition("Type 2 diabetes mellitus", "2024-01-15")]), rec("a.txt", h="H1"))
    merge_facts(ledger, DocumentFacts(chronic_conditions=[ChronicCondition("type 2 diabetes mellitus", "2024-06-01")]), rec("b.txt", h="H2"))
    assert len(ledger.chronic_conditions) == 1
    assert ledger.chronic_conditions[0].diagnosed_date == "2024-01-15"


def test_notes_are_deduplicated(ledger):
    merge_facts(ledger, DocumentFacts(notes=["Fasting sample."]), rec("a.txt", h="H1"))
    merge_facts(ledger, DocumentFacts(notes=["Fasting sample.", "New note."]), rec("b.txt", h="H2"))
    assert ledger.clinical_notes == ["Fasting sample.", "New note."]


def test_empty_document_records_but_adds_no_facts(ledger):
    assert merge_facts(ledger, DocumentFacts(doc_type="bill"), rec("bill.txt", h="H1")) is True
    assert len(ledger.documents) == 1
    assert ledger.allergies == []
    assert ledger.lab_results == {}


def test_round_trip_through_dict_is_lossless(ledger):
    merge_facts(
        ledger,
        DocumentFacts(
            allergies=[Allergy("Penicillin", "rash", "Severe")],
            medications=[Medication("Metformin", "1000 mg", "twice daily")],
            labs=[LabValue("HbA1c", 7.5, "%", "2024-08-10")],
        ),
        rec("a.txt", "2024-08-10", h="H1"),
    )
    restored = Ledger.from_dict(ledger.to_dict())
    assert restored.to_dict() == ledger.to_dict()
