"""Turn a document's text into structured DocumentFacts.

Two extractors, one interface:

  extract_with_gemini(text, filename) -- the real one. Asks Gemini to read
      the document into the fixed fact schema. It is told, firmly, to
      report only what the document literally contains and never to infer,
      diagnose, or fill gaps. This is the sanctioned use of the LLM:
      reading unstructured text into structure. It decides nothing.

  MockExtractor -- canned facts for the sample documents, so the whole
      pipeline runs offline with no API key and no network. Same role the
      deterministic summary fallback played in the Salesforce build: the
      demo never depends on a live model.

Both return the same DocumentFacts, so compact.merge_facts neither knows
nor cares which produced them.
"""

from __future__ import annotations

import json
import os
import re

from .schema import (
    Allergy,
    ChronicCondition,
    DocumentFacts,
    LabValue,
    Medication,
)

MODEL = os.getenv("CARELOOP_MODEL", "gemini-3.6-flash")

# The schema Gemini is asked to fill. Kept in the prompt as plain English
# plus a JSON skeleton -- reliable across models and easy to eyeball.
_EXTRACTION_PROMPT = """
You are a clinical data extractor. You are given the raw text of ONE
medical document (a lab report, prescription, discharge note, or bill).

Extract ONLY what the document literally states. Do not infer a diagnosis,
do not estimate values, do not add anything that is not written. If a field
is not present, leave it out. You are not a clinician and you make no
clinical judgement -- you only transcribe into structure.

Return a single JSON object, no prose, no markdown fences, matching:

{
  "doc_type": "lab_report | prescription | visit_note | discharge | bill | other",
  "doc_date": "YYYY-MM-DD if stated, else empty",
  "allergies": [
    {"allergen": "", "reaction": "", "severity": "Mild|Moderate|Severe|Unknown"}
  ],
  "chronic_conditions": [
    {"name": "", "diagnosed_date": "YYYY-MM-DD or empty", "status": "active|resolved"}
  ],
  "medications": [
    {"drug": "", "dose": "", "frequency": "", "indication": "", "status": "active|stopped"}
  ],
  "labs": [
    {"analyte": "", "value": 0, "unit": "", "date": "YYYY-MM-DD or empty",
     "ref_range": "", "flag": "high|low|normal or empty"}
  ],
  "notes": ["short factual lines worth keeping, verbatim where possible"]
}

Document text:
---
{DOCUMENT}
---
""".strip()


def _facts_from_json(payload: dict) -> DocumentFacts:
    """Build DocumentFacts from parsed JSON, tolerating missing fields."""
    doc_date = payload.get("doc_date", "")

    def lab(row: dict) -> LabValue | None:
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            return None
        return LabValue(
            analyte=str(row.get("analyte", "")).strip(),
            value=value,
            unit=str(row.get("unit", "")).strip(),
            date=str(row.get("date", "") or doc_date).strip(),
            ref_range=str(row.get("ref_range", "")).strip(),
            flag=str(row.get("flag", "")).strip(),
        )

    labs = [lv for row in payload.get("labs", []) if (lv := lab(row))]

    return DocumentFacts(
        doc_type=payload.get("doc_type", ""),
        doc_date=doc_date,
        allergies=[
            Allergy(
                allergen=str(a.get("allergen", "")).strip(),
                reaction=str(a.get("reaction", "")).strip(),
                severity=str(a.get("severity", "")).strip(),
                first_seen=doc_date,
            )
            for a in payload.get("allergies", [])
            if a.get("allergen")
        ],
        chronic_conditions=[
            ChronicCondition(
                name=str(c.get("name", "")).strip(),
                diagnosed_date=str(c.get("diagnosed_date", "")).strip(),
                status=str(c.get("status", "active")).strip() or "active",
            )
            for c in payload.get("chronic_conditions", [])
            if c.get("name")
        ],
        medications=[
            Medication(
                drug=str(m.get("drug", "")).strip(),
                dose=str(m.get("dose", "")).strip(),
                frequency=str(m.get("frequency", "")).strip(),
                indication=str(m.get("indication", "")).strip(),
                status=str(m.get("status", "active")).strip() or "active",
                prescribed_date=doc_date,
            )
            for m in payload.get("medications", [])
            if m.get("drug")
        ],
        labs=labs,
        notes=[str(n).strip() for n in payload.get("notes", []) if str(n).strip()],
    )


def _loads_lenient(text: str) -> dict:
    """Parse JSON even if the model wrapped it in prose or a code fence."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: grab the outermost {...} block.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def extract_with_gemini(text: str, filename: str = "") -> DocumentFacts:
    """Real extraction. Reuses the same auth/env as the ADK agent.

    google.genai.Client() picks up GOOGLE_API_KEY (or the Vertex env vars)
    automatically, so whichever mode you got `adk run` working in, this uses
    the same one. No separate configuration.
    """
    from google import genai  # imported lazily so offline tests never need it

    client = genai.Client()
    prompt = _EXTRACTION_PROMPT.replace("{DOCUMENT}", text)
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0},
    )
    try:
        payload = _loads_lenient(response.text or "{}")
    except json.JSONDecodeError:
        # Extraction failed -- record the document but assert no facts,
        # rather than guessing. A gap is safer than a fabrication.
        return DocumentFacts(doc_type="unparsed")
    return _facts_from_json(payload)


class MockExtractor:
    """Offline extractor with canned facts for the sample documents.

    Keyed by filename so `ingest.py --mock` reproduces Anita's story with no
    network. The facts below are what a correct Gemini extraction of each
    sample document should return.
    """

    _CANNED: dict[str, DocumentFacts] = {}

    def __call__(self, text: str, filename: str = "") -> DocumentFacts:
        if filename in self._CANNED:
            return self._CANNED[filename]
        # Unknown document offline: no facts, but it still gets recorded.
        return DocumentFacts(doc_type="unknown")


def _register(name: str, facts: DocumentFacts) -> None:
    MockExtractor._CANNED[name] = facts


_register(
    "2024-01-15_lab_apollo.txt",
    DocumentFacts(
        doc_type="lab_report",
        doc_date="2024-01-15",
        labs=[
            LabValue("HbA1c", 6.8, "%", "2024-01-15", "4.0-5.6", "high"),
            LabValue("Fasting glucose", 128, "mg/dL", "2024-01-15", "70-100", "high"),
            LabValue("LDL", 142, "mg/dL", "2024-01-15", "<100", "high"),
        ],
        notes=["Apollo Diagnostics, Bengaluru. Fasting sample."],
    ),
)
_register(
    "2024-01-15_prescription.txt",
    DocumentFacts(
        doc_type="prescription",
        doc_date="2024-01-15",
        chronic_conditions=[
            ChronicCondition("Type 2 diabetes mellitus", "2024-01-15", "active")
        ],
        medications=[
            Medication("Metformin", "500 mg", "twice daily", "Type 2 diabetes", "active")
        ],
        allergies=[Allergy("Penicillin", "rash", "Moderate")],
        notes=["Dr. R. Menon. Review in 3 months."],
    ),
)
_register(
    "2024-04-20_lab_apollo.txt",
    DocumentFacts(
        doc_type="lab_report",
        doc_date="2024-04-20",
        labs=[
            LabValue("HbA1c", 7.2, "%", "2024-04-20", "4.0-5.6", "high"),
            LabValue("LDL", 138, "mg/dL", "2024-04-20", "<100", "high"),
        ],
    ),
)
_register(
    "2024-08-10_lab_citycare.txt",
    DocumentFacts(
        doc_type="lab_report",
        doc_date="2024-08-10",
        labs=[
            LabValue("HbA1c", 7.5, "%", "2024-08-10", "4.0-5.6", "high"),
        ],
        notes=["CityCare Labs. Suboptimal glycaemic control noted."],
    ),
)
_register(
    "2024-08-10_visit_note.txt",
    DocumentFacts(
        doc_type="visit_note",
        doc_date="2024-08-10",
        medications=[
            Medication(
                "Metformin", "1000 mg", "twice daily", "Type 2 diabetes", "active"
            )
        ],
        # Same allergy, restated more severely -- exercises the "keep the
        # more severe reading" merge rule.
        allergies=[Allergy("Penicillin", "hives and swelling", "Severe")],
        notes=["Dose increased due to rising HbA1c. Reinforced diet and exercise."],
    ),
)
