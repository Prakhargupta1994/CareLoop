"""Deterministic follow-up scheduling.

RULES DECIDE, AI EXPLAINS -- the async-tail edition.

Given a patient's ledger, this decides two things, with no model involved:
  1. Which active medications are due for a refill (from the prescription
     date plus a supply window).
  2. Whether a lab trend warrants a gentle check-in nudge (a tracked
     analyte sitting above a demo target and still rising).

The output is a FollowUpPlan. A separate step turns it into a friendly
patient message. As with triage, the decision is auditable: every reminder
carries the dates and numbers it was derived from.

The analyte targets here are DEMO-GRADE, not a medical reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DEFAULT_DAYS_SUPPLY = 30
DEFAULT_REMINDER_LEAD = 7  # start reminding this many days before it runs out

# Upper bounds only, for the demo. A rising value above this suggests a
# check-in. Not clinical guidance.
ANALYTE_TARGETS = {"HbA1c": 7.0}


@dataclass
class RefillReminder:
    drug: str
    dose: str
    frequency: str
    prescribed_date: str
    due_date: str
    days_overdue: int
    status: str  # due / upcoming / ok


@dataclass
class CheckIn:
    reason: str
    detail: str


@dataclass
class FollowUpPlan:
    patient_id: str
    patient_name: str
    as_of: str
    refills: list[RefillReminder] = field(default_factory=list)
    checkins: list[CheckIn] = field(default_factory=list)

    @property
    def due_refills(self) -> list[RefillReminder]:
        return [r for r in self.refills if r.status == "due"]

    @property
    def needs_followup(self) -> bool:
        return bool(self.due_refills) or bool(self.checkins)


def _parse(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def build_plan(
    ledger,
    as_of: date | None = None,
    days_supply: int = DEFAULT_DAYS_SUPPLY,
    reminder_lead: int = DEFAULT_REMINDER_LEAD,
) -> FollowUpPlan:
    """Compute a patient's follow-up plan as of a given date (default today)."""
    as_of = as_of or date.today()
    plan = FollowUpPlan(
        patient_id=ledger.patient_id,
        patient_name=ledger.patient_name,
        as_of=as_of.isoformat(),
    )

    # --- refill reminders for active, dated medications ---
    for med in ledger.medications:
        if med.status == "stopped":
            continue
        prescribed = _parse(med.prescribed_date)
        if prescribed is None:
            continue  # cannot schedule a refill without a start date

        due = date.fromordinal(prescribed.toordinal() + days_supply)
        overdue = as_of.toordinal() - due.toordinal()

        if overdue >= 0:
            status = "due"
        elif overdue >= -reminder_lead:
            status = "upcoming"
        else:
            status = "ok"

        plan.refills.append(
            RefillReminder(
                drug=med.drug,
                dose=med.dose,
                frequency=med.frequency,
                prescribed_date=med.prescribed_date,
                due_date=due.isoformat(),
                days_overdue=max(overdue, 0),
                status=status,
            )
        )

    # --- check-in nudges from rising lab trends above a demo target ---
    for analyte, series in ledger.lab_results.items():
        target = ANALYTE_TARGETS.get(analyte)
        if target is None or len(series) < 2:
            continue
        first, last = series[0].value, series[-1].value
        if last > target and last > first:
            plan.checkins.append(
                CheckIn(
                    reason=f"rising {analyte}",
                    detail=f"{analyte} {first:g} -> {last:g}, above target {target:g}",
                )
            )

    return plan
