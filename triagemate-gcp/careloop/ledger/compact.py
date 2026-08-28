"""Deterministic compaction: merge one document's facts into the ledger.

GEMINI EXTRACTS, RULES MERGE.

The extractor (Gemini, or the offline mock) turns an unstructured document
into DocumentFacts. Everything in THIS file is plain Python with no model
in the loop -- given the same facts it produces the same ledger every
time. That determinism is why the merge can be trusted and why it is
tested exhaustively offline.

Idempotency is a hard requirement, carried over from the Salesforce
data-loading discipline (always upsert, never double-load). Re-ingesting
the same folder must not duplicate a single lab reading. We enforce that
by fingerprinting each document's content and skipping any we have already
merged.
"""

from __future__ import annotations

from .schema import (
    SEVERITY_ORDER,
    Allergy,
    ChronicCondition,
    DocumentFacts,
    DocumentRecord,
    Ledger,
    LabValue,
    Medication,
)


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _merge_allergy(ledger: Ledger, incoming: Allergy, doc: DocumentRecord) -> None:
    key = _norm(incoming.allergen)
    if not key:
        return
    for existing in ledger.allergies:
        if _norm(existing.allergen) == key:
            # Keep the more severe reading; never downgrade an allergy.
            if SEVERITY_ORDER.get(_norm(incoming.severity), 0) > SEVERITY_ORDER.get(
                _norm(existing.severity), 0
            ):
                existing.severity = incoming.severity
            if not existing.reaction and incoming.reaction:
                existing.reaction = incoming.reaction
            return
    ledger.allergies.append(
        Allergy(
            allergen=incoming.allergen.strip(),
            reaction=incoming.reaction,
            severity=incoming.severity,
            source=doc.filename,
            first_seen=incoming.first_seen or doc.doc_date,
        )
    )


def _merge_condition(
    ledger: Ledger, incoming: ChronicCondition, doc: DocumentRecord
) -> None:
    key = _norm(incoming.name)
    if not key:
        return
    for existing in ledger.chronic_conditions:
        if _norm(existing.name) == key:
            # Keep the earliest diagnosis date we have seen.
            if incoming.diagnosed_date and (
                not existing.diagnosed_date
                or incoming.diagnosed_date < existing.diagnosed_date
            ):
                existing.diagnosed_date = incoming.diagnosed_date
            if incoming.status:
                existing.status = incoming.status
            return
    ledger.chronic_conditions.append(
        ChronicCondition(
            name=incoming.name.strip(),
            diagnosed_date=incoming.diagnosed_date,
            status=incoming.status or "active",
            source=doc.filename,
        )
    )


def _merge_medication(
    ledger: Ledger, incoming: Medication, doc: DocumentRecord
) -> None:
    key = _norm(incoming.drug)
    if not key:
        return
    for existing in ledger.medications:
        if _norm(existing.drug) == key:
            # Same drug seen again: the most recent document wins on dose,
            # frequency, and status, but we keep every source for the trail.
            if incoming.dose:
                existing.dose = incoming.dose
            if incoming.frequency:
                existing.frequency = incoming.frequency
            if incoming.indication and not existing.indication:
                existing.indication = incoming.indication
            if incoming.status:
                existing.status = incoming.status
            if incoming.prescribed_date:
                existing.prescribed_date = incoming.prescribed_date
            if doc.filename not in existing.sources:
                existing.sources.append(doc.filename)
            return
    ledger.medications.append(
        Medication(
            drug=incoming.drug.strip(),
            dose=incoming.dose,
            frequency=incoming.frequency,
            indication=incoming.indication,
            status=incoming.status or "active",
            prescribed_date=incoming.prescribed_date or doc.doc_date,
            sources=[doc.filename],
        )
    )


def _merge_lab(ledger: Ledger, incoming: LabValue, doc: DocumentRecord) -> None:
    analyte = incoming.analyte.strip()
    if not analyte:
        return
    series = ledger.lab_results.setdefault(analyte, [])

    # De-dup a reading by (date, value) so re-ingesting the same report does
    # not add the same point twice.
    for existing in series:
        if existing.date == incoming.date and existing.value == incoming.value:
            return

    series.append(
        LabValue(
            analyte=analyte,
            value=incoming.value,
            unit=incoming.unit,
            date=incoming.date or doc.doc_date,
            ref_range=incoming.ref_range,
            flag=incoming.flag,
            source=doc.filename,
        )
    )
    # Keep every analyte's series in chronological order so trends read left
    # to right regardless of the order documents were ingested.
    series.sort(key=lambda v: v.date)


def merge_facts(
    ledger: Ledger, facts: DocumentFacts, doc: DocumentRecord
) -> bool:
    """Merge one document into the ledger in place.

    Returns True if the document was newly merged, False if it was skipped
    because an identical document had already been ingested.
    """
    if doc.content_hash and any(
        d.content_hash == doc.content_hash for d in ledger.documents
    ):
        return False

    ledger.documents.append(doc)

    for allergy in facts.allergies:
        _merge_allergy(ledger, allergy, doc)
    for condition in facts.chronic_conditions:
        _merge_condition(ledger, condition, doc)
    for medication in facts.medications:
        _merge_medication(ledger, medication, doc)
    for lab in facts.labs:
        _merge_lab(ledger, lab, doc)
    for note in facts.notes:
        cleaned = note.strip()
        if cleaned and cleaned not in ledger.clinical_notes:
            ledger.clinical_notes.append(cleaned)

    return True
