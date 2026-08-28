"""Follow-up scheduling tests -- pure, offline, deterministic.

A fixed as_of date makes every assertion stable regardless of the real
calendar.

    python -m pytest tests/test_followup.py -v
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careloop.followup.compose import compose_message  # noqa: E402
from careloop.followup.schedule import build_plan  # noqa: E402
from careloop.ledger.schema import Ledger, LabValue, Medication  # noqa: E402


def ledger_with(meds=None, labs=None) -> Ledger:
    led = Ledger(patient_id="anita", patient_name="Anita Rao")
    led.medications = meds or []
    for lv in labs or []:
        led.lab_results.setdefault(lv.analyte, []).append(lv)
    return led


def test_overdue_medication_is_due_for_refill():
    led = ledger_with(
        meds=[Medication("Metformin", "1000 mg", "twice daily", prescribed_date="2024-08-10")]
    )
    plan = build_plan(led, as_of=date(2024, 9, 15))  # due 2024-09-09
    assert len(plan.refills) == 1
    assert plan.refills[0].status == "due"
    assert plan.refills[0].days_overdue == 6
    assert plan.needs_followup is True


def test_recent_medication_is_not_yet_due():
    led = ledger_with(
        meds=[Medication("Metformin", "500 mg", "twice daily", prescribed_date="2024-08-10")]
    )
    plan = build_plan(led, as_of=date(2024, 8, 20))  # well before due, before lead window
    assert plan.refills[0].status == "ok"
    assert plan.needs_followup is False


def test_medication_inside_lead_window_is_upcoming_not_due():
    led = ledger_with(
        meds=[Medication("Metformin", "500 mg", "twice daily", prescribed_date="2024-08-10")]
    )
    # due 2024-09-09; five days before is inside the 7-day lead window
    plan = build_plan(led, as_of=date(2024, 9, 4))
    assert plan.refills[0].status == "upcoming"
    assert plan.due_refills == []


def test_stopped_medication_is_skipped():
    led = ledger_with(
        meds=[Medication("Metformin", "500 mg", "twice daily", status="stopped",
                         prescribed_date="2024-01-01")]
    )
    plan = build_plan(led, as_of=date(2024, 12, 31))
    assert plan.refills == []


def test_medication_without_a_date_cannot_be_scheduled():
    led = ledger_with(meds=[Medication("Metformin", "500 mg", "twice daily")])
    plan = build_plan(led, as_of=date(2024, 12, 31))
    assert plan.refills == []


def test_rising_hba1c_above_target_triggers_a_checkin():
    led = ledger_with(
        labs=[
            LabValue("HbA1c", 6.8, "%", "2024-01-15"),
            LabValue("HbA1c", 7.5, "%", "2024-08-10"),
        ]
    )
    plan = build_plan(led, as_of=date(2024, 8, 20))
    assert len(plan.checkins) == 1
    assert "HbA1c" in plan.checkins[0].detail


def test_stable_in_range_labs_do_not_trigger_a_checkin():
    led = ledger_with(
        labs=[
            LabValue("HbA1c", 5.2, "%", "2024-01-15"),
            LabValue("HbA1c", 5.4, "%", "2024-08-10"),  # rising but below target
        ]
    )
    plan = build_plan(led, as_of=date(2024, 8, 20))
    assert plan.checkins == []


def test_falling_labs_do_not_trigger_a_checkin():
    led = ledger_with(
        labs=[
            LabValue("HbA1c", 8.0, "%", "2024-01-15"),
            LabValue("HbA1c", 7.1, "%", "2024-08-10"),  # above target but improving
        ]
    )
    plan = build_plan(led, as_of=date(2024, 8, 20))
    assert plan.checkins == []


def test_anita_full_story_gets_both_a_refill_and_a_checkin():
    led = ledger_with(
        meds=[Medication("Metformin", "1000 mg", "twice daily", prescribed_date="2024-08-10")],
        labs=[
            LabValue("HbA1c", 6.8, "%", "2024-01-15"),
            LabValue("HbA1c", 7.2, "%", "2024-04-20"),
            LabValue("HbA1c", 7.5, "%", "2024-08-10"),
        ],
    )
    plan = build_plan(led, as_of=date(2024, 9, 15))
    assert plan.due_refills and plan.checkins
    msg = compose_message(plan)
    assert "Metformin" in msg["body"]
    assert "reminder only" in msg["body"].lower()
    assert "STOP" in msg["body"]


def test_message_is_calm_when_only_a_checkin_is_due():
    led = ledger_with(
        labs=[
            LabValue("HbA1c", 6.9, "%", "2024-01-15"),
            LabValue("HbA1c", 7.3, "%", "2024-08-10"),
        ]
    )
    plan = build_plan(led, as_of=date(2024, 8, 20))
    msg = compose_message(plan)
    assert "check-in" in msg["subject"].lower()
    assert "doctor" in msg["body"].lower()
