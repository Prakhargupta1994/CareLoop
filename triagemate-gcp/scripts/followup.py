#!/usr/bin/env python3
"""The async follow-up sweep: who needs a refill or a check-in, and remind them.

This is the job that would run on a schedule (Cloud Scheduler -> Cloud Run
Job) to work in the background without anyone driving it. Run it by hand to
see what it would do:

    python scripts/followup.py                     # everyone in the store
    python scripts/followup.py --patient anita     # one patient
    python scripts/followup.py --as-of 2024-09-15  # pretend it's this date
    python scripts/followup.py --real              # Gemini writes the message

It reads patients from whichever store CARELOOP_STORE selects (local JSON or
Firestore) and, by default, prints the emails instead of sending them
(CARELOOP_MAILER=mock). Nothing here decides anything clinical: it reminds
about medications a clinician already prescribed and nudges toward a doctor.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careloop.followup.compose import compose_message, compose_with_gemini  # noqa: E402
from careloop.followup.schedule import build_plan  # noqa: E402
from careloop.followup.send import send  # noqa: E402
from careloop.ledger.store import backend_name, list_patients, load_ledger  # noqa: E402

BAR = "=" * 60


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the follow-up sweep.")
    parser.add_argument("--patient", default="", help="One patient id (default: all).")
    parser.add_argument("--as-of", default="", help="Pretend today is YYYY-MM-DD.")
    parser.add_argument("--to", default="", help="Override recipient email.")
    parser.add_argument(
        "--real", action="store_true", help="Use Gemini to write the message."
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    compose = compose_with_gemini if args.real else compose_message

    patients = [args.patient] if args.patient else list_patients()
    print(f"{BAR}\nFollow-up sweep  (as of {as_of.isoformat()})")
    print(f"Store: {backend_name()}   Patients: {len(patients)}\n{BAR}")

    if not patients:
        print("No patients on file. Ingest someone first.")
        return 0

    reminded = 0
    for pid in patients:
        ledger = load_ledger(pid)
        plan = build_plan(ledger, as_of=as_of)

        if not plan.needs_followup:
            print(f"\n{plan.patient_name or pid}: nothing due.")
            continue

        reasons = []
        if plan.due_refills:
            reasons.append(
                "refill " + ", ".join(r.drug for r in plan.due_refills)
            )
        if plan.checkins:
            reasons.append("check-in (" + "; ".join(c.detail for c in plan.checkins) + ")")
        print(f"\n{plan.patient_name or pid}: {', '.join(reasons)}")

        message = compose(plan)
        to = args.to or f"{pid}@example.com"
        send(to, message["subject"], message["body"])
        reminded += 1

    print(f"\n{BAR}\nSwept {len(patients)} patient(s); {reminded} reminder(s) sent.\n{BAR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
