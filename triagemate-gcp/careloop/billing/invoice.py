"""Mock hospital-pharmacy billing.

Given the medications a clinician prescribed plus a consultation fee, this
itemises an invoice and produces a MOCK payment confirmation. There is no
real payment here and there must not be: real money means a payment gateway
and PCI scope, which is out of bounds for a demo. Everything below is
clearly labelled mock, and the demo should say so.

The price list is demo-grade and not a real formulary. Amounts are in INR.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Demo-grade monthly prices for a hospital pharmacy, in INR. Unknown drugs
# fall back to a default so a new prescription still bills.
PHARMACY_PRICES = {
    "metformin": 120,
    "atorvastatin": 180,
    "amlodipine": 90,
    "losartan": 140,
    "aspirin": 40,
    "amoxicillin": 150,
    "azithromycin": 210,
    "paracetamol": 30,
    "omeprazole": 110,
    "levothyroxine": 160,
    "insulin": 450,
}
DEFAULT_DRUG_PRICE = 100
DEFAULT_CONSULT_FEE = 500
CURRENCY = "INR"


@dataclass
class LineItem:
    description: str
    quantity: int
    unit_price: int
    amount: int


@dataclass
class Invoice:
    patient_id: str
    patient_name: str
    items: list[LineItem] = field(default_factory=list)
    currency: str = CURRENCY

    @property
    def total(self) -> int:
        return sum(i.amount for i in self.items)

    def render(self) -> str:
        width = 52
        lines = ["-" * width, f"HOSPITAL PHARMACY -- INVOICE (MOCK)".center(width)]
        who = self.patient_name or self.patient_id
        lines += [f"Patient: {who}", "-" * width]
        for it in self.items:
            left = it.description[:36]
            lines.append(f"{left:<38}{self.currency} {it.amount:>7,}")
        lines.append("-" * width)
        lines.append(f"{'TOTAL':<38}{self.currency} {self.total:>7,}")
        lines.append("-" * width)
        return "\n".join(lines)


def _price_for(drug: str) -> int:
    key = drug.strip().lower().split()[0] if drug.strip() else ""
    return PHARMACY_PRICES.get(key, DEFAULT_DRUG_PRICE)


def build_invoice(
    patient_id: str,
    patient_name: str,
    medications: list[dict] | None = None,
    consultation_fee: int = DEFAULT_CONSULT_FEE,
    days_supply: int = 30,
) -> Invoice:
    """Itemise a consultation fee plus a month's supply of each medication."""
    invoice = Invoice(patient_id=patient_id, patient_name=patient_name)

    if consultation_fee:
        invoice.items.append(
            LineItem("Consultation fee", 1, consultation_fee, consultation_fee)
        )

    for med in medications or []:
        drug = med.get("drug", "")
        if not drug:
            continue
        unit = _price_for(drug)
        label = f"{drug} {med.get('dose', '')}".strip() + f" ({days_supply}-day supply)"
        invoice.items.append(LineItem(label, 1, unit, unit))

    return invoice


def mock_pay(invoice: Invoice) -> dict:
    """Pretend to charge the invoice. No real payment occurs."""
    reference = "PAY-" + datetime.now(timezone.utc).strftime("%Y%m%d") + "-" + str(
        random.randint(1000, 9999)
    )
    return {
        "status": "PAID (mock -- no real charge)",
        "reference": reference,
        "amount": invoice.total,
        "currency": invoice.currency,
    }
