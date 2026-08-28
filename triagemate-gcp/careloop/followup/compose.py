"""Turn a FollowUpPlan into a friendly, patient-facing message.

Two composers, one shape (subject + body), mirroring the extractor split:
  compose_message      -- deterministic template. Works offline, always the
                          same, safe for the demo.
  compose_with_gemini  -- Gemini writes a warmer version from the same plan.

Patient-facing safety rules (these are NOT clinician briefs):
  - A refill reminder is for a medication a clinician ALREADY prescribed. It
    never suggests a new medication or a dose change.
  - A check-in nudge points the patient to their doctor. It never diagnoses,
    never alarms, never explains what a number "means".
  - Every message is a reminder only, says so, and offers a way to opt out.
"""

from __future__ import annotations

import os

from .schedule import FollowUpPlan

MODEL = os.getenv("CARELOOP_MODEL", "gemini-3.5-flash")

REFILL_LINK = os.getenv("CARELOOP_REFILL_LINK", "[refill link]")


def compose_message(plan: FollowUpPlan) -> dict:
    """Deterministic patient message from the plan."""
    name = plan.patient_name or "there"
    lines = [f"Hi {name},", "", "A quick reminder from your care team."]

    due = plan.due_refills
    for r in due:
        med = f"{r.drug} {r.dose}".strip()
        freq = f" ({r.frequency})" if r.frequency else ""
        lines.append(f"- It looks like it's time to refill your {med}{freq}.")

    for c in plan.checkins:
        lines.append(
            "- When you have a moment, it's worth booking a check-in with your "
            "doctor to review how things are going."
        )

    if due:
        lines += ["", f"You can start a refill here: {REFILL_LINK}"]

    lines += [
        "",
        "This is a reminder only, not medical advice. Your doctor remains your "
        "best source for any decisions about your care.",
        "Reply STOP to stop these reminders.",
    ]

    subject = (
        "Time to refill your medication"
        if due
        else "A quick check-in from your care team"
    )
    return {"subject": subject, "body": "\n".join(lines)}


def compose_with_gemini(plan: FollowUpPlan) -> dict:
    """Gemini writes the message from the structured plan. Falls back to the
    template if the call fails, so a flaky network never breaks the sweep."""
    from google import genai  # imported lazily; offline path needs no ADK/genai

    facts = []
    for r in plan.due_refills:
        facts.append(
            f"Refill due: {r.drug} {r.dose} {r.frequency}, "
            f"prescribed {r.prescribed_date}, {r.days_overdue} days overdue."
        )
    for c in plan.checkins:
        facts.append(f"Check-in suggested: {c.detail}.")
    if not facts:
        facts.append("No action needed right now.")

    prompt = (
        "Write a short, warm reminder to a patient named "
        f"{plan.patient_name or 'the patient'} from their care team, based ONLY "
        "on the facts below. Rules: this is a reminder, not medical advice; do "
        "not diagnose; do not explain what any number means; for a check-in, "
        "simply and gently suggest they see their doctor; never suggest a new "
        "medication or a dose change; keep it to a few short sentences; end with "
        "a one-line opt-out. Do not invent anything not in the facts.\n\n"
        "Facts:\n- " + "\n- ".join(facts)
    )

    try:
        client = genai.Client()
        resp = client.models.generate_content(
            model=MODEL, contents=prompt, config={"temperature": 0.4}
        )
        body = (resp.text or "").strip()
        if not body:
            raise ValueError("empty response")
    except Exception:
        return compose_message(plan)

    subject = (
        "Time to refill your medication"
        if plan.due_refills
        else "A quick check-in from your care team"
    )
    return {"subject": subject, "body": body}


def compose_visit_summary(ledger) -> dict:
    """A short post-visit note to the patient, built from the ledger.

    Uses the most recent visit note and the patient's active medications.
    Patient-facing safety rules apply: it states what the clinician recorded,
    it does not diagnose or explain what anything means, and it points the
    patient back to their doctor for questions.
    """
    name = ledger.patient_name or "there"
    lines = [f"Hi {name},", "", "A quick summary from your recent visit."]

    # newest visit note, if any
    visit_notes = [n for n in ledger.clinical_notes if n.lower().startswith("consultation")]
    if visit_notes:
        lines.append(f"- {visit_notes[-1]}")

    active = [m for m in ledger.medications if m.status != "stopped"]
    if active:
        lines.append("- Your current medications:")
        for m in active:
            lines.append(f"    * {m.drug} {m.dose} {m.frequency}".rstrip())

    lines += [
        "",
        "If you have questions about any of this, please contact your doctor. "
        "This is a summary only, not medical advice.",
        "Reply STOP to stop these messages.",
    ]
    return {"subject": "A summary from your recent visit", "body": "\n".join(lines)}
