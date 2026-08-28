"""The deterministic triage engine.

RULES DECIDE, AI EXPLAINS.

No large language model is invoked anywhere in this file, and none ever
should be. Urgency and routing are decided by a weighted score plus a
red-flag override. Given the same inputs and the same dataset, this
function returns the same output every single time -- which is the whole
reason a clinician can be asked to trust it.

Algorithm
---------
1. Resolve each submitted symptom external id against the dataset.
   Unknown ids are reported, never silently dropped.
2. For every mapping row touching a matched symptom, add its weight to
   that mapping's condition. Record the contribution for the audit trail.
3. Sort conditions by score descending. Ties break by clinical priority
   (Critical > Urgent > Routine), then alphabetically so the order is
   stable across runs.
4. RED-FLAG OVERRIDE: if the top-ranked condition is flagged, the result
   is forced to Critical and routed to Emergency Medicine regardless of
   score. Scanning depth is configurable but defaults to 1, matching the
   original Salesforce implementation.
5. Otherwise the triage level and specialty are taken from the
   top-ranked condition as authored in the reference data.
"""

from __future__ import annotations

from collections import defaultdict

from .models import (
    PRIORITY_RANK,
    Contribution,
    ScoredCondition,
    TriageResult,
)

EMERGENCY_SPECIALTY_ID = "SPEC_EM"
FALLBACK_SPECIALTY_ID = "SPEC_GP"
DEFAULT_TOP_N = 3
DEFAULT_RED_FLAG_SCAN_DEPTH = 1


class TriageEngine:
    """Scores a symptom set against the reference dataset."""

    def __init__(
        self,
        dataset,
        top_n: int = DEFAULT_TOP_N,
        red_flag_scan_depth: int = DEFAULT_RED_FLAG_SCAN_DEPTH,
    ) -> None:
        self.data = dataset
        self.top_n = top_n
        self.red_flag_scan_depth = red_flag_scan_depth

    def _specialty_name(self, specialty_id: str) -> str:
        spec = self.data.specialties.get(specialty_id)
        return spec.name if spec else specialty_id

    def score(self, symptom_external_ids) -> TriageResult:
        matched: list[str] = []
        unknown: list[str] = []
        seen: set[str] = set()

        for sid in symptom_external_ids:
            key = (sid or "").strip().upper()
            if not key or key in seen:
                continue
            seen.add(key)
            (matched if key in self.data.symptoms else unknown).append(key)

        if not matched:
            return TriageResult(
                triage_level="Routine",
                recommended_specialty=FALLBACK_SPECIALTY_ID,
                specialty_name=self._specialty_name(FALLBACK_SPECIALTY_ID),
                is_red_flag=False,
                probable_conditions=[],
                matched_symptoms=[],
                unknown_symptoms=unknown,
                rationale=[
                    "No recognised symptoms were submitted, so no condition "
                    "could be scored. Defaulted to Routine / General Medicine."
                ],
            )

        totals: dict[str, int] = defaultdict(int)
        contributions: dict[str, list[Contribution]] = defaultdict(list)

        for sid in matched:
            symptom = self.data.symptoms[sid]
            for mapping in self.data.mappings_by_symptom.get(sid, []):
                if mapping.condition not in self.data.conditions:
                    continue
                totals[mapping.condition] += mapping.weight
                contributions[mapping.condition].append(
                    Contribution(
                        symptom_id=sid,
                        symptom_name=symptom.name,
                        weight=mapping.weight,
                    )
                )

        if not totals:
            return TriageResult(
                triage_level="Routine",
                recommended_specialty=FALLBACK_SPECIALTY_ID,
                specialty_name=self._specialty_name(FALLBACK_SPECIALTY_ID),
                is_red_flag=False,
                probable_conditions=[],
                matched_symptoms=matched,
                unknown_symptoms=unknown,
                rationale=[
                    "Symptoms were recognised but no condition mapping exists "
                    "for them. Defaulted to Routine / General Medicine."
                ],
            )

        def sort_key(item):
            condition_id, total = item
            condition = self.data.conditions[condition_id]
            return (
                -total,
                -PRIORITY_RANK[condition.triage_priority],
                condition.name,
            )

        ranked: list[ScoredCondition] = []
        for position, (condition_id, total) in enumerate(
            sorted(totals.items(), key=sort_key), start=1
        ):
            condition = self.data.conditions[condition_id]
            ranked.append(
                ScoredCondition(
                    rank=position,
                    external_id=condition.external_id,
                    name=condition.name,
                    score=total,
                    triage_priority=condition.triage_priority,
                    is_red_flag=condition.is_red_flag,
                    recommended_specialty=condition.recommended_specialty,
                    specialty_name=self._specialty_name(
                        condition.recommended_specialty
                    ),
                    clinical_note=condition.clinical_note,
                    contributions=sorted(
                        contributions[condition_id],
                        key=lambda c: (-c.weight, c.symptom_name),
                    ),
                )
            )

        top = ranked[: self.top_n]
        leader = ranked[0]
        rationale: list[str] = [c.why() for c in top]

        scan = ranked[: self.red_flag_scan_depth]
        flagged = next((c for c in scan if c.is_red_flag), None)

        if flagged is not None:
            rationale.append(
                f"RED-FLAG OVERRIDE: {flagged.name} is a red-flag condition. "
                f"Triage forced to Critical and routed to Emergency Medicine, "
                f"bypassing the authored priority."
            )
            return TriageResult(
                triage_level="Critical",
                recommended_specialty=EMERGENCY_SPECIALTY_ID,
                specialty_name=self._specialty_name(EMERGENCY_SPECIALTY_ID),
                is_red_flag=True,
                probable_conditions=top,
                matched_symptoms=matched,
                unknown_symptoms=unknown,
                rationale=rationale,
            )

        rationale.append(
            f"Top-ranked condition is {leader.name} (score {leader.score}). "
            f"Triage level and routing taken from its authored values."
        )
        return TriageResult(
            triage_level=leader.triage_priority,
            recommended_specialty=leader.recommended_specialty,
            specialty_name=leader.specialty_name,
            is_red_flag=False,
            probable_conditions=top,
            matched_symptoms=matched,
            unknown_symptoms=unknown,
            rationale=rationale,
        )
