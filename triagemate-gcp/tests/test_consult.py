"""Consultation write-back + billing tests -- offline, deterministic.

    python -m pytest tests/test_consult.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_ledger_dir():
    """Point the local store at a throwaway dir so tests don't touch real data."""
    tmp = tempfile.mkdtemp()
    old_store = os.environ.get("CARELOOP_STORE")
    old_dir = os.environ.get("CARELOOP_LEDGER_DIR")
    os.environ["CARELOOP_STORE"] = "local"
    os.environ["CARELOOP_LEDGER_DIR"] = tmp
    # store.py reads these at import time, so reload it
    import importlib
    import careloop.ledger.store as store
    importlib.reload(store)
    yield tmp
    if old_store is None:
        os.environ.pop("CARELOOP_STORE", None)
    else:
        os.environ["CARELOOP_STORE"] = old_store
    if old_dir is None:
        os.environ.pop("CARELOOP_LEDGER_DIR", None)
    else:
        os.environ["CARELOOP_LEDGER_DIR"] = old_dir
    importlib.reload(store)


def _record(**kw):
    import importlib
    import careloop.ledger.record as record
    importlib.reload(record)
    return record.record_visit(**kw)


def test_recording_a_visit_adds_the_medication_to_the_ledger():
    from careloop.ledger.store import load_ledger
    out = _record(
        patient_id="p1", patient_name="Test One",
        diagnosis="Dyslipidemia",
        medications=[{"drug": "Atorvastatin", "dose": "10 mg", "frequency": "once daily"}],
        visit_date="2024-09-15",
    )
    assert out["recorded"] is True
    assert "Atorvastatin 10 mg" in out["prescribed"]
    led = load_ledger("p1")
    assert any(m.drug == "Atorvastatin" for m in led.medications)


def test_recorded_medication_has_the_visit_date_so_followup_can_schedule_it():
    from careloop.followup.schedule import build_plan
    from careloop.ledger.store import load_ledger
    from datetime import date
    _record(
        patient_id="p2", patient_name="Test Two",
        medications=[{"drug": "Atorvastatin", "dose": "10 mg", "frequency": "once daily"}],
        visit_date="2024-09-15",
    )
    led = load_ledger("p2")
    plan = build_plan(led, as_of=date(2024, 10, 20))  # past the 30-day supply
    assert any(r.drug == "Atorvastatin" and r.status == "due" for r in plan.refills)


def test_recording_the_same_visit_twice_is_idempotent():
    from careloop.ledger.store import load_ledger
    args = dict(
        patient_id="p3", patient_name="Test Three",
        diagnosis="Dyslipidemia",
        medications=[{"drug": "Atorvastatin", "dose": "10 mg", "frequency": "once daily"}],
        visit_date="2024-09-15", doctor="Dr X", instructions="recheck",
    )
    first = _record(**args)
    second = _record(**args)
    assert first["recorded"] is True
    assert second["recorded"] is False
    led = load_ledger("p3")
    statins = [m for m in led.medications if m.drug == "Atorvastatin"]
    assert len(statins) == 1  # not duplicated


def test_visit_updates_dose_of_an_existing_medication():
    from careloop.ledger.store import load_ledger
    _record(patient_id="p4", medications=[{"drug": "Metformin", "dose": "500 mg", "frequency": "twice daily"}], visit_date="2024-01-15")
    _record(patient_id="p4", medications=[{"drug": "Metformin", "dose": "1000 mg", "frequency": "twice daily"}], visit_date="2024-08-10")
    led = load_ledger("p4")
    mets = [m for m in led.medications if m.drug == "Metformin"]
    assert len(mets) == 1
    assert mets[0].dose == "1000 mg"


# --- billing (no ledger needed) -----------------------------------------
def test_invoice_totals_consultation_fee_plus_known_drug_price():
    from careloop.billing.invoice import build_invoice
    inv = build_invoice("p", "Pat", medications=[{"drug": "Atorvastatin", "dose": "10 mg"}], consultation_fee=500)
    # 500 consult + 180 atorvastatin
    assert inv.total == 680
    assert len(inv.items) == 2


def test_invoice_uses_default_price_for_unknown_drug():
    from careloop.billing.invoice import build_invoice, DEFAULT_DRUG_PRICE, DEFAULT_CONSULT_FEE
    inv = build_invoice("p", "Pat", medications=[{"drug": "Zorblaxifen"}])
    assert inv.total == DEFAULT_CONSULT_FEE + DEFAULT_DRUG_PRICE


def test_invoice_with_no_medications_is_just_the_fee():
    from careloop.billing.invoice import build_invoice
    inv = build_invoice("p", "Pat", medications=[], consultation_fee=500)
    assert inv.total == 500


def test_mock_pay_reports_paid_and_matches_total():
    from careloop.billing.invoice import build_invoice, mock_pay
    inv = build_invoice("p", "Pat", medications=[{"drug": "Metformin"}], consultation_fee=500)
    receipt = mock_pay(inv)
    assert "mock" in receipt["status"].lower()
    assert receipt["amount"] == inv.total
