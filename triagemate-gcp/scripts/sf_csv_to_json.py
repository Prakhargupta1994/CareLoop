#!/usr/bin/env python3
"""Converts Salesforce reference-object CSV exports into engine JSON.

Export these four from Workbench (Queries -> SOQL Query -> Bulk CSV) or
Data Loader, keeping the default API-name headers:

    Specialty__c.csv
    Symptom__c.csv
    Condition__c.csv
    Symptom_Condition_Map__c.csv

Then:

    python scripts/sf_csv_to_json.py path/to/csv_folder

Relationship columns are read from the __r.External_Id__c form, which is
what the exports produce. If a column is missing the script says which
one rather than writing a silently broken dataset.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "careloop" / "data"

SPECS = {
    "Specialty__c.csv": {
        "out": "specialties.json",
        "required": ["External_Id__c", "Name"],
        "fields": {
            "external_id": "External_Id__c",
            "name": "Name",
            "description": "Description__c",
        },
    },
    "Symptom__c.csv": {
        "out": "symptoms.json",
        "required": ["External_Id__c", "Name"],
        "fields": {
            "external_id": "External_Id__c",
            "name": "Name",
            "body_system": "Body_System__c",
        },
    },
    "Condition__c.csv": {
        "out": "conditions.json",
        "required": ["External_Id__c", "Name", "Triage_Priority__c"],
        "fields": {
            "external_id": "External_Id__c",
            "name": "Name",
            "recommended_specialty": "Recommended_Specialty__r.External_Id__c",
            "triage_priority": "Triage_Priority__c",
            "is_red_flag": "Is_Red_Flag__c",
            "clinical_note": "Clinical_Note__c",
        },
    },
    "Symptom_Condition_Map__c.csv": {
        "out": "symptom_condition_map.json",
        "required": ["External_Id__c", "Weight__c"],
        "fields": {
            "external_id": "External_Id__c",
            "symptom": "Symptom__r.External_Id__c",
            "condition": "Condition__r.External_Id__c",
            "weight": "Weight__c",
        },
    },
}

BOOL_FIELDS = {"is_red_flag"}
INT_FIELDS = {"weight"}
UPPER_FIELDS = {"external_id", "symptom", "condition", "recommended_specialty"}
DEFAULTS = {"body_system": "General", "description": "", "clinical_note": ""}


def convert(csv_path: Path, spec: dict) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise SystemExit(f"{csv_path.name}: file is empty")

    headers = set(rows[0].keys())
    missing = [c for c in spec["required"] if c not in headers]
    if missing:
        raise SystemExit(
            f"{csv_path.name}: missing required column(s) {missing}.\n"
            f"Found: {sorted(headers)}"
        )

    out: list[dict] = []
    for line_no, row in enumerate(rows, start=2):
        record: dict = {}
        for key, column in spec["fields"].items():
            value = (row.get(column) or "").strip()

            if not value:
                if key in BOOL_FIELDS:
                    record[key] = False
                    continue
                if key in DEFAULTS:
                    record[key] = DEFAULTS[key]
                    continue
                raise SystemExit(
                    f"{csv_path.name} line {line_no}: column {column!r} is "
                    f"empty but required for {key!r}. If the lookup is blank "
                    f"in Salesforce, fix it there and re-export."
                )

            if key in BOOL_FIELDS:
                record[key] = value.lower() in {"true", "1", "yes"}
            elif key in INT_FIELDS:
                record[key] = int(float(value))
            elif key in UPPER_FIELDS:
                record[key] = value.upper()
            else:
                record[key] = value
        out.append(record)

    seen: set[str] = set()
    dupes = {r["external_id"] for r in out if r["external_id"] in seen or seen.add(r["external_id"])}
    if dupes:
        raise SystemExit(
            f"{csv_path.name}: duplicate external ids {sorted(dupes)[:5]}. "
            f"This usually means the object was loaded twice in Salesforce."
        )

    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    source = Path(sys.argv[1])
    if not source.is_dir():
        raise SystemExit(f"Not a directory: {source}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename, spec in SPECS.items():
        csv_path = source / filename
        if not csv_path.exists():
            raise SystemExit(f"Expected {csv_path} but it does not exist.")
        records = convert(csv_path, spec)
        target = OUT_DIR / spec["out"]
        with target.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, indent=2, ensure_ascii=False)
        print(f"{filename:32} -> {spec['out']:28} {len(records):>5} rows")

    print("\nNow run:  python scripts/smoke_test.py")
    print("Expected counts from the Salesforce README: 16 / 83 / 61 / 280")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
