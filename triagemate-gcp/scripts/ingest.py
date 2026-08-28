#!/usr/bin/env python3
"""Ingest a folder of patient documents into a compacted ledger.

Offline, no API key, canned extraction (use this to see the pipeline work):

    python scripts/ingest.py --docs scripts/sample_docs --patient anita --mock

Real extraction with Gemini (uses the same key/env as `adk run`):

    python scripts/ingest.py --docs scripts/sample_docs --patient anita

The ledger is written to whichever backend CARELOOP_STORE selects:
local JSON (default) or Firestore. Set CARELOOP_STORE=firestore to write
to the database instead -- nothing else about the command changes.

Re-run either one twice: the ledger will not change the second time.
Documents are fingerprinted and skipped if already ingested.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careloop.ledger.compact import merge_facts  # noqa: E402
from careloop.ledger.extract import MockExtractor, extract_with_gemini  # noqa: E402
from careloop.ledger.schema import DocumentRecord  # noqa: E402
from careloop.ledger.sources import read_local_folder  # noqa: E402
from careloop.ledger.store import backend_name, load_ledger, save_ledger  # noqa: E402

BAR = "-" * 68


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact patient documents.")
    parser.add_argument("--docs", required=True, help="Folder of documents.")
    parser.add_argument("--patient", required=True, help="Patient id (lowercase).")
    parser.add_argument("--name", default="", help="Patient display name.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use canned offline extraction instead of calling Gemini.",
    )
    args = parser.parse_args()

    extractor = MockExtractor() if args.mock else extract_with_gemini
    mode = "offline mock" if args.mock else "Gemini"

    ledger = load_ledger(args.patient, args.name)
    print(f"{BAR}\nIngesting patient '{args.patient}'  [{mode}]")
    print(f"Store: {backend_name()}")

    merged = skipped = 0
    for doc in read_local_folder(args.docs):
        facts = extractor(doc.text, doc.filename)
        record = DocumentRecord(
            filename=doc.filename,
            doc_type=facts.doc_type,
            doc_date=facts.doc_date,
            ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            content_hash=doc.content_hash,
        )
        if merge_facts(ledger, facts, record):
            merged += 1
            print(f"  + {doc.filename}  ({facts.doc_type or 'unknown'})")
        else:
            skipped += 1
            print(f"  . {doc.filename}  already ingested, skipped")

    save_ledger(ledger)

    print(f"\n{BAR}\nLEDGER FOR {ledger.patient_name or ledger.patient_id}")
    print(f"Documents: {len(ledger.documents)}  ({merged} new, {skipped} skipped)")

    if ledger.allergies:
        print("\nAllergies:")
        for a in ledger.allergies:
            sev = f" [{a.severity}]" if a.severity else ""
            rxn = f" -- {a.reaction}" if a.reaction else ""
            print(f"  ! {a.allergen}{sev}{rxn}")

    if ledger.chronic_conditions:
        print("\nChronic conditions:")
        for c in ledger.chronic_conditions:
            when = f" (since {c.diagnosed_date})" if c.diagnosed_date else ""
            print(f"  - {c.name}{when}")

    if ledger.medications:
        print("\nMedications:")
        for m in ledger.medications:
            print(f"  - {m.drug} {m.dose} {m.frequency}".rstrip() + f"  [{m.status}]")

    if ledger.lab_results:
        print("\nLab trends:")
        for analyte in sorted(ledger.lab_results):
            print(f"  {ledger.lab_trend(analyte)}")

    print(f"{BAR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
