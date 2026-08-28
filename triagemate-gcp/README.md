# CareLoop

An autonomous clinical-triage agent on Gemini, Google ADK, and Google Cloud.
Submitted to the All Things Agentic Hackathon (Taskmaster track).

> **Decision support, not diagnosis.** Every output is for a licensed clinician
> to review. All patient data in this repo is synthetic; the symptom/condition
> dataset is demo-grade, not a medical reference. Payment and email are mocked
> and labeled as such.

## The idea: rules decide, AI explains

A deterministic engine owns every clinical decision — a weighted score plus a
red-flag override sets urgency and routing, auditable and identical on the same
input every time. Gemini's role is language only: reading unstructured
documents into a fixed schema ("Gemini extracts, rules merge") and turning the
structured result into readable prose. No LLM is in the decision path.

## What it does (the full loop)

1. **Ingest & compact** — reads a patient's documents and merges them into one
   structured ledger (allergies, chronic conditions, medications, lab trends).
2. **Triage** — scores probable conditions from symptoms, assigns urgency,
   routes to a specialty, escalates red flags instantly.
3. **Brief the clinician** — a plain-language summary that pulls in history
   (e.g. surfacing a penicillin allergy before prescribing).
4. **Write back & bill** — the clinician's decision is recorded to the ledger;
   the prescription + consultation fee are itemised (mock payment).
5. **Follow up autonomously** — a sweep finds who is due for a refill or a
   check-in and sends the reminder.

## Architecture

```
Documents ─┐                                   ┌─ Clinician brief
Patient   ─┼─>  ADK agent (Cloud Run)         ─┼─ Patient email
Scheduler ─┘     compaction (Gemini extracts)  └─ Ledger write-back + billing
                 triage engine (pure Python)
                 explanation (Gemini)
                          │
                 Firestore health ledger
```

## Stack

- **Gemini 3.5 Flash** via **Google ADK** (agent, tools, dev UI)
- **Cloud Run** — deployed agent + web UI on one origin
- **Firestore** — the patient ledger, persisted in the cloud
- **Deterministic Python engine** — triage, compaction merge, follow-up
  scheduling; 34 tests including a reproducibility check
- **Pluggable backends** — local vs. cloud storage, mock vs. real email, each
  one environment flip apart

## Spin-up (local, no cloud, no API key)

Requires Python 3.10+.

```bash
git clone <repo-url>
cd triagemate-gcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# verify the clinical core — 3 patients, 34 tests, all offline
python scripts/smoke_test.py
python -m pytest tests/ -v

# build a patient's compacted ledger from sample documents
python scripts/ingest.py --docs scripts/sample_docs --patient anita --name "Anita Rao" --mock
```

## Run the agent

```bash
cp careloop/.env.example careloop/.env     # add your Gemini API key or Vertex config
adk web                                     # dev UI; run from the repo root
```

Open the dev UI, pick `careloop`, and try:

> Patient anita is here with increased thirst, frequent urination, blurred
> vision, and weight loss. What's the triage?

The trace shows the model calling the deterministic engine and reading the
ledger — it never decides urgency itself.

## Deploy to Google Cloud

```bash
adk deploy cloud_run --project=<PROJECT> --region=asia-south1 \
  --service_name=careloop --with_ui ./careloop \
  -- --allow-unauthenticated \
  --set-env-vars=GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=<PROJECT>,GOOGLE_CLOUD_LOCATION=global,CARELOOP_MODEL=gemini-3.5-flash,CARELOOP_STORE=firestore
```

The Cloud Run service account needs `roles/datastore.user` (Firestore) and, on
first deploy, the default build service account needs the Cloud Build roles.

## The async follow-up + consultation loop

```bash
python scripts/consult.py                              # record a visit + bill it
python scripts/followup.py --real                      # Gemini writes the reminder
python scripts/followup.py --patient anita --as-of 2026-10-15   # a month on, the new drug is due
```

## Layout

```
careloop/
  agent.py            ADK root agent
  engine/             deterministic triage — no LLM
  ledger/             compaction, extraction, store (local/Firestore), write-back
  followup/           scheduling, message composition, delivery (mock/SMTP)
  billing/            mock hospital-pharmacy invoice
  tools/              ADK function tools
  data/               clinical reference JSON
scripts/              ingest, smoke_test, followup, consult, sf_csv_to_json
tests/                34 tests (triage, compaction, follow-up, consultation)
```

## Safety posture

Output is always for a clinician, never shown to a patient as a diagnosis.
Red-flag patterns bypass scoring and escalate to Emergency Medicine.
Unrecognised symptoms are reported, never guessed. Medication features are
refill reminders for what a clinician already prescribed — never a suggestion
to buy. All data is synthetic.

## License

MIT
