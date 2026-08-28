"""ADK function tools exposing the compacted patient ledger to the agent.

This is where the two halves of CareLoop join. The triage engine decides
urgency from symptoms; the ledger supplies the history -- allergies, active
medications, chronic conditions, and lab trends -- that a clinician brief
must account for. The archetypal moment: triage points toward a treatment,
but the patient is allergic to penicillin, and the brief has to surface
that before anything is prescribed.

The model may READ the ledger. It still decides nothing clinical: the
ledger is context for the explanation, exactly as the reference dataset is
context for the score. Urgency and routing come only from run_triage.

Reads go through careloop.ledger.store, so whichever backend is active
(local JSON or Firestore) the agent transparently uses the same one the
ingest pipeline wrote to.
"""

from __future__ import annotations

from ..ledger.store import ledger_exists, list_patients, load_ledger


def list_patient_ledgers() -> dict:
    """List the patient ids that have a compacted ledger on file.

    Use this to discover which patients you can look up, or to recover when
    get_patient_ledger reports that an id was not found.

    Returns:
        A dict with the list of available patient ids.
    """
    return {"status": "success", "patients": list_patients()}


def get_patient_ledger(patient_id: str) -> dict:
    """Retrieve a patient's compacted health history from the ledger.

    Call this whenever a patient's history matters -- to check for allergies
    that affect prescribing, list current medications, note known chronic
    conditions, or read a lab trend over time. Always check allergies before
    discussing any treatment.

    Args:
        patient_id: The patient's id, e.g. "anita".

    Returns:
        A dict with the patient's allergies, active medications, chronic
        conditions, lab trends, document count, and notes. If no ledger
        exists, returns the list of patient ids that do, so you can retry.
    """
    if not ledger_exists(patient_id):
        return {
            "status": "not_found",
            "message": (
                f"No ledger on file for patient '{patient_id}'. Run the ingest "
                f"pipeline for them first, or pick from the available list."
            ),
            "available_patients": list_patients(),
        }

    ledger = load_ledger(patient_id)
    active_meds = [m for m in ledger.medications if m.status != "stopped"]

    return {
        "status": "success",
        "patient_id": ledger.patient_id,
        "patient_name": ledger.patient_name,
        "allergies": [
            {"allergen": a.allergen, "severity": a.severity, "reaction": a.reaction}
            for a in ledger.allergies
        ],
        "active_medications": [
            {
                "drug": m.drug,
                "dose": m.dose,
                "frequency": m.frequency,
                "indication": m.indication,
            }
            for m in active_meds
        ],
        "chronic_conditions": [
            {"name": c.name, "since": c.diagnosed_date, "status": c.status}
            for c in ledger.chronic_conditions
        ],
        "lab_trends": {
            analyte: ledger.lab_trend(analyte)
            for analyte in sorted(ledger.lab_results)
        },
        "documents_on_file": len(ledger.documents),
        "clinical_notes": ledger.clinical_notes,
    }
