#!/usr/bin/env python3
"""Record a consultation outcome, then bill it. Closes the visit loop.

Default run reproduces Anita's story: after reviewing her rising HbA1c and
high LDL, the doctor adds a statin, records it, and the hospital pharmacy
bills the new medicine plus the consultation fee.

    python scripts/consult.py                    # Anita demo
    python scripts/consult.py --patient anita \\
        --diagnosis "Type 2 diabetes with dyslipidemia" \\
        --drug "Atorvastatin" --dose "10 mg" --freq "once daily" --fee 500

The recorded medication is written into the ledger, so a later
`python scripts/followup.py` will remind Anita about the new drug too.
Payment is mocked -- no real charge occurs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careloop.billing.invoice import build_invoice, mock_pay  # noqa: E402
from careloop.ledger.record import record_visit  # noqa: E402
from careloop.ledger.store import backend_name, load_ledger  # noqa: E402

BAR = "=" * 60


def main() -> int:
    p = argparse.ArgumentParser(description="Record a consultation and bill it.")
    p.add_argument("--patient", default="anita")
    p.add_argument("--name", default="Anita Rao")
    p.add_argument("--diagnosis", default="Type 2 diabetes with dyslipidemia")
    p.add_argument("--drug", default="Atorvastatin")
    p.add_argument("--dose", default="10 mg")
    p.add_argument("--freq", default="once daily")
    p.add_argument("--instructions", default="Recheck lipid panel in 3 months.")
    p.add_argument("--doctor", default="Dr. R. Menon")
    p.add_argument("--fee", type=int, default=500)
    args = p.parse_args()

    meds = [{"drug": args.drug, "dose": args.dose, "frequency": args.freq,
             "indication": args.diagnosis}] if args.drug else []

    print(f"{BAR}\nRecording consultation for {args.name}\nStore: {backend_name()}\n{BAR}")

    result = record_visit(
        args.patient,
        diagnosis=args.diagnosis,
        medications=meds,
        instructions=args.instructions,
        doctor=args.doctor,
        patient_name=args.name,
    )
    print(f"Diagnosis : {result['diagnosis']}")
    print(f"Prescribed: {', '.join(result['prescribed']) or '(none)'}")
    print(f"Status    : {result['note']}")

    # Show the medication now living in the ledger.
    ledger = load_ledger(args.patient)
    print("\nMedications now on file:")
    for m in ledger.medications:
        print(f"  - {m.drug} {m.dose} {m.frequency}".rstrip() + f"  [{m.status}]")

    # Bill the new prescription plus the consultation fee.
    print(f"\n{BAR}\nBILLING\n{BAR}")
    invoice = build_invoice(args.patient, args.name, medications=meds, consultation_fee=args.fee)
    print(invoice.render())
    receipt = mock_pay(invoice)
    print(f"\nPayment: {receipt['status']}")
    print(f"Reference: {receipt['reference']}   Amount: {receipt['currency']} {receipt['amount']:,}")
    print(f"\n{BAR}")
    print("The new medication is on the ledger, so `followup.py` will now")
    print("remind about it too. That is the loop closing.")
    print(f"{BAR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
