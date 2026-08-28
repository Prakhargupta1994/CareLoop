"""Conversational doctor tools: record a decision to the ledger, and email.

These let the clinician work entirely in the chat: pull up the patient
(get_patient_ledger), decide, then TELL the agent what they decided and the
agent writes it into the record and can send the patient a note.

RULES DECIDE, AI EXPLAINS: the clinician makes every clinical decision.
These tools only transcribe the clinician's stated decision and send a
message. The agent must never invent a diagnosis, a prescription, or a
test -- it records only what the clinician explicitly says.
"""

from __future__ import annotations

from ..followup.compose import compose_visit_summary
from ..followup.send import send
from ..ledger.record import record_visit
from ..ledger.store import load_ledger


def record_consultation(
    patient_id: str,
    diagnosis: str = "",
    medication: str = "",
    dose: str = "",
    frequency: str = "",
    instructions: str = "",
    doctor: str = "",
) -> dict:
    """Write the clinician's decision from THIS visit into the patient's ledger.

    Call this only after the clinician has explicitly stated what they are
    prescribing or advising. Do not fill in a drug, dose, or diagnosis the
    clinician did not say. If a detail is missing, ask the clinician rather
    than guessing.

    Args:
        patient_id: The patient's id, e.g. "anita".
        diagnosis: The clinician's stated diagnosis or reason for the visit.
        medication: A drug the clinician is prescribing (blank if none).
        dose: The dose, e.g. "10 mg".
        frequency: How often, e.g. "once daily".
        instructions: Any advice or tests the clinician wants on record,
            e.g. "recheck lipid panel in 3 months".
        doctor: The clinician's name.

    Returns:
        A confirmation of what was written to the ledger.
    """
    meds = (
        [{"drug": medication, "dose": dose, "frequency": frequency, "indication": diagnosis}]
        if medication
        else []
    )
    return record_visit(
        patient_id,
        diagnosis=diagnosis,
        medications=meds,
        instructions=instructions,
        doctor=doctor,
    )


def email_patient(patient_id: str, to_email: str = "") -> dict:
    """Send the patient a plain-language summary of their latest visit.

    Composes a short note from what is on the ledger (the most recent visit
    and current medications) and sends it via the configured mailer (printed
    to the console by default; a real email if email sending is set up).

    Args:
        patient_id: The patient's id.
        to_email: The recipient address. Defaults to a placeholder if omitted.

    Returns:
        The send status.
    """
    ledger = load_ledger(patient_id)
    message = compose_visit_summary(ledger)
    to = to_email or f"{patient_id}@example.com"
    return send(to, message["subject"], message["body"])
