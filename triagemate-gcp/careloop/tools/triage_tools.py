"""ADK function tools that expose the deterministic engine to Gemini.

The model is allowed to CALL these. It is not allowed to compute their
results itself. Every tool returns a plain dict so the tool-call trace in
the ADK dev UI shows exactly what the engine decided -- which is the
demo moment: the judge watches the model hand off the decision.
"""

from __future__ import annotations

from ..engine.loader import get_dataset
from ..engine.triage import TriageEngine


def list_symptoms(body_system: str = "") -> dict:
    """Lists the clinical symptoms the triage engine recognises.

    Call this to translate a patient's free-text complaint into the
    canonical symptom ids the engine needs. Always call it before
    run_triage so you use real ids rather than inventing them.

    Args:
        body_system: Optional filter, for example "Cardiovascular" or
            "Respiratory". Leave empty to list everything.

    Returns:
        A dict with the matching symptoms grouped by body system.
    """
    data = get_dataset()
    grouped: dict[str, list[dict]] = {}
    wanted = body_system.strip().lower()

    for symptom in data.symptoms.values():
        if wanted and symptom.body_system.lower() != wanted:
            continue
        grouped.setdefault(symptom.body_system, []).append(
            {"id": symptom.external_id, "name": symptom.name}
        )

    for entries in grouped.values():
        entries.sort(key=lambda e: e["name"])

    return {
        "status": "success",
        "count": sum(len(v) for v in grouped.values()),
        "by_body_system": grouped,
    }


def run_triage(symptom_ids: list[str]) -> dict:
    """Runs the deterministic triage engine on a set of symptom ids.

    This is the ONLY way a triage level or specialty may be produced. Do
    not estimate urgency yourself, do not adjust the result, and do not
    soften or escalate it. Report exactly what comes back, then explain
    it in plain language for the clinician.

    Args:
        symptom_ids: Canonical symptom external ids from list_symptoms,
            for example ["SYM_CHEST_PAIN_RAD", "SYM_SWEATING"].

    Returns:
        A dict containing the triage level, the routed specialty, the
        red-flag status, the ranked probable conditions with their
        scores, and a rationale trace showing how each score was built.
    """
    engine = TriageEngine(get_dataset())
    result = engine.score(symptom_ids)

    return {
        "status": "success",
        "triage_level": result.triage_level,
        "recommended_specialty": result.specialty_name,
        "recommended_specialty_id": result.recommended_specialty,
        "is_red_flag": result.is_red_flag,
        "probable_conditions": [
            {
                "rank": c.rank,
                "name": c.name,
                "score": c.score,
                "authored_priority": c.triage_priority,
                "is_red_flag": c.is_red_flag,
                "clinical_note": c.clinical_note,
                "score_breakdown": [
                    f"{contrib.symptom_name} +{contrib.weight}"
                    for contrib in c.contributions
                ],
            }
            for c in result.probable_conditions
        ],
        "matched_symptoms": result.matched_symptoms,
        "unrecognised_symptoms": result.unknown_symptoms,
        "rationale": result.rationale,
        "disclaimer": (
            "Clinical decision support for a licensed clinician. "
            "Not a diagnosis and not for direct patient consumption."
        ),
    }


def dataset_health() -> dict:
    """Reports reference-data counts and any integrity problems.

    Useful for verifying a fresh data load before a demo.

    Returns:
        A dict with row counts per object and a list of problems found.
    """
    data = get_dataset()
    problems = data.validate()
    return {
        "status": "success" if not problems else "warning",
        "counts": data.counts(),
        "problems": problems,
    }
