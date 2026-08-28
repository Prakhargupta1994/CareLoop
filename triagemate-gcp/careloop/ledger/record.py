"""Write a clinician's consultation outcome back into the patient's ledger.

This closes the loop. Until now the ledger only grew from ingested
documents; this lets the outcome of a visit -- a diagnosis, a new
prescription, follow-up instructions -- become part of the record too. The
new medication it records is exactly what the follow-up sweep will later
remind the patient about, so the visit drives the reminders.

RULES DECIDE, AI EXPLAINS still holds: the CLINICIAN makes the decision,
and this only transcribes their stated decision into the record -- the same
role extraction plays for documents. It never generates a diagnosis or a
prescription of its own.

A recorded visit is merged with the same compaction logic as any document,
so the usual guarantees apply: the latest dose wins, allergies are never
downgraded, and recording the identical visit twice is idempotent.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from .compact import merge_facts
from .schema import DocumentFacts, DocumentRecord, Medication
from .store import load_ledger, save_ledger


def record_visit(
    patient_id: str,
    *,
    diagnosis: str = "",
    medications: list[dict] | None = None,
    instructions: str = "",
    doctor: str = "",
    visit_date: str = "",
    patient_name: str = "",
) -> dict:
    """Record a consultation outcome into a patient's ledger.

    Args:
        patient_id: The patient's ledger id.
        diagnosis: The clinician's stated diagnosis for this visit (free text).
        medications: New prescriptions, each a dict with keys drug, dose,
            frequency, and optionally indication.
        instructions: Any follow-up instructions to keep on the record.
        doctor: The clinician's name.
        visit_date: YYYY-MM-DD; defaults to today.
        patient_name: Used only if the ledger does not exist yet.

    Returns:
        A summary of what was recorded.
    """
    visit_date = visit_date or date.today().isoformat()
    ledger = load_ledger(patient_id, patient_name)

    meds = [
        Medication(
            drug=m["drug"],
            dose=m.get("dose", ""),
            frequency=m.get("frequency", ""),
            indication=m.get("indication", "") or diagnosis,
            status="active",
            prescribed_date=visit_date,
        )
        for m in (medications or [])
        if m.get("drug")
    ]

    header = f"Consultation {visit_date}" + (f" with {doctor}" if doctor else "")
    if diagnosis:
        header += f" -- diagnosis: {diagnosis}"
    notes = [header]
    if instructions:
        notes.append(instructions)

    facts = DocumentFacts(
        doc_type="visit_note",
        doc_date=visit_date,
        medications=meds,
        notes=notes,
    )

    # Fingerprint the visit so recording the same one twice is a no-op.
    payload = "|".join(
        [
            patient_id,
            visit_date,
            doctor,
            diagnosis,
            instructions,
            ";".join(f"{m.drug}:{m.dose}:{m.frequency}" for m in meds),
        ]
    )
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    record = DocumentRecord(
        filename=f"visit_{visit_date}_{content_hash[:6]}",
        doc_type="visit_note",
        doc_date=visit_date,
        ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        content_hash=content_hash,
    )

    newly_recorded = merge_facts(ledger, facts, record)
    save_ledger(ledger)

    return {
        "recorded": newly_recorded,
        "patient_id": patient_id,
        "visit_date": visit_date,
        "diagnosis": diagnosis,
        "prescribed": [f"{m.drug} {m.dose}".strip() for m in meds],
        "note": (
            "Recorded to the ledger. Refill reminders for any new medication "
            "will follow automatically."
            if newly_recorded
            else "This exact visit was already on file; nothing changed."
        ),
    }
