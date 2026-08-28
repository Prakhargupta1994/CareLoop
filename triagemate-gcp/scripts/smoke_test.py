#!/usr/bin/env python3
"""Runs the demo patients through the engine. No cloud, no API key, no network.

    python scripts/smoke_test.py

If this passes, the clinical core is sound and every later failure is a
plumbing problem, not a logic problem.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careloop.engine.loader import load_dataset  # noqa: E402
from careloop.engine.triage import TriageEngine  # noqa: E402

PATIENTS = [
    (
        "Sneha",
        "runny nose, sneezing, sore throat",
        ["SYM_RUNNY_NOSE", "SYM_SNEEZING", "SYM_SORE_THROAT"],
        "Routine",
    ),
    (
        "Anita",
        "thirst, frequent urination, blurred vision, weight loss",
        ["SYM_THIRST", "SYM_FREQ_URINATION", "SYM_BLURRED_VISION", "SYM_WEIGHT_LOSS"],
        "Urgent",
    ),
    (
        "Rakesh",
        "chest pain to arm, sweating, breathless",
        ["SYM_CHEST_PAIN_RAD", "SYM_CHEST_PAIN", "SYM_SWEATING", "SYM_SOB"],
        "Critical",
    ),
]

BAR = "-" * 68


def main() -> int:
    data = load_dataset()
    problems = data.validate()

    print(BAR)
    print("Reference data:", ", ".join(f"{k}={v}" for k, v in data.counts().items()))
    if problems:
        print("\nDATA PROBLEMS FOUND:")
        for problem in problems:
            print(f"  ! {problem}")
        return 1
    print("Integrity: clean")

    engine = TriageEngine(data)
    failures = 0

    for name, complaint, symptom_ids, expected in PATIENTS:
        result = engine.score(symptom_ids)
        ok = result.triage_level == expected

        print(f"\n{BAR}\n{name} -- {complaint}")
        print(f"  Triage      : {result.triage_level}")
        print(f"  Route to    : {result.specialty_name}")
        print(f"  Red flag    : {result.is_red_flag}")
        print("  Probable    :")
        for condition in result.probable_conditions:
            print(f"    {condition.rank}. {condition.name} (score {condition.score})")
            print(
                "       "
                + ", ".join(
                    f"{c.symptom_name} +{c.weight}" for c in condition.contributions
                )
            )
        print("  Rationale   :")
        for line in result.rationale:
            print(f"    - {line}")

        if not ok:
            failures += 1
            print(f"  >>> FAIL: expected {expected}, got {result.triage_level}")

    print(f"\n{BAR}")
    if failures:
        print(f"{failures} of {len(PATIENTS)} patients did not match expectations.")
        return 1
    print(f"All {len(PATIENTS)} demo patients triaged as expected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
