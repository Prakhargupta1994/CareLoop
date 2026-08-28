# CareLoop — Master Reference (Google Cloud / ADK)

Single source of truth for the GCP port of the triage project. If you are picking this up in a
fresh session, read this first — it covers the architecture, every module, the environment/auth
setup (including the exact problems already solved), how to run and test everything, and the
day-by-day plan. Prefer grounding answers here over re-deriving.

> **Sibling reference:** the Salesforce build (`TriageMate`) has its own master `README.md`. CareLoop
> reuses that project's clinical dataset and its core principle, but is a separate codebase on a
> separate stack. This doc is authoritative for the GCP side.

> **Safety framing (keep it in the pitch):** clinical *decision support*, not diagnosis. Output is
> always addressed to a licensed clinician for review, red-flag patterns escalate immediately, and
> all patient data in the repo is synthetic. The symptom/condition data is demo-grade.

---

## 1. What this is
A GCP-native autonomous triage agent for the **All Things Agentic** hackathon, **Taskmaster** track
(deadline **31 Aug 2026**). It reuses the Salesforce project's concept and clinical data, rebuilt on
Gemini + Google ADK + Google Cloud.

The end-to-end loop: patient health documents land in a folder (Drive) → each is compacted into a
structured per-patient **ledger** → a deterministic engine scores symptoms and triages → a
clinician brief is produced → async follow-up (refill reminders, check-ins) fires later over Gmail.

**Built so far:** the triage engine, the compaction ledger, the ADK agent, all offline-tested.
Drive, Firestore, Cloud Run, and the async loop are the remaining wiring.

---

## 2. Design principle (the spine — non-negotiable)
Carried over verbatim from the Salesforce build and extended:

- **Rules decide, AI explains.** A deterministic weighted score + red-flag override owns every
  urgency and routing decision. No LLM is in that path. Ever.
- **Gemini extracts, rules merge.** For document ingestion, the LLM reads unstructured PDFs into a
  fixed fact schema — it never invents the ledger and never decides anything clinical. Deterministic
  Python does the merging.

The sanctioned LLM uses are: reading documents into structure (extraction), and turning a structured
result into prose (the brief). Nothing else.

---

## 3. Architecture
```
Drive folder  ─┐                                    ┌─ Clinician brief
Patient chat  ─┼─>  ADK agent (Cloud Run)          ─┼─ Gmail follow-up
Scheduler     ─┘     compaction (Gemini extracts)   └─ Drive write-back
                     triage engine (pure Python)
                     explain layer (Gemini)
                              │
                     Firestore health ledger
```
The **compaction** step is the key technical angle: rather than pushing dozens of pages into context
per visit, each document is merged once into a single structured ledger per patient (allergies,
chronic conditions, active meds, and lab trends over time). Later steps read the ledger, not the raw
files. The **lab trend** (e.g. HbA1c 6.8 → 7.2 → 7.5 across three reports) emerges from the merge and
is the single most demoable output.

---

## 4. Repository layout
```
triagemate-gcp/
  README.md                      public-facing spin-up doc
  requirements.txt
  careloop/
    __init__.py                  imports agent; ADK-optional guard so the engine runs without ADK
    agent.py                     ADK root agent (reads CARELOOP_MODEL from env)
    .env / .env.example          auth + model config (never commit .env)
    engine/                      TRIAGE — no LLM, ever
      models.py                  domain dataclasses (mirror the Salesforce objects)
      triage.py                  deterministic scoring + red-flag override
      loader.py                  dataset load + integrity validation
    tools/
      triage_tools.py            ADK function tools: list_symptoms, run_triage, dataset_health
    ledger/                      COMPACTION — Gemini extracts, rules merge
      schema.py                  Ledger + DocumentFacts dataclasses
      compact.py                 deterministic merge (the tested heart)
      extract.py                 Gemini extractor + offline MockExtractor
      store.py                   local JSON store (Firestore drop-in sketched inside)
      sources.py                 local folder reader (Drive drop-in sketched inside)
    data/                        clinical reference JSON (starter set; swap for full export)
  scripts/
    smoke_test.py                three demo patients through the engine, no cloud
    sf_csv_to_json.py            Salesforce CSV export -> engine JSON
    ingest.py                    document -> ledger pipeline (CLI, --mock or real)
    sample_docs/                 Anita's 5 synthetic documents (the trend + allergy story)
  tests/
    test_triage.py               12 engine tests incl. a determinism check
    test_compact.py              12 merge tests incl. idempotency
```

---

## 5. The triage engine (`careloop/engine/`)
Pure Python port of the Salesforce Apex scoring logic. No model involved.

**Data model** (mirrors the Salesforce reference objects one-to-one, so the export drops in):
`Specialty`, `Symptom`, `Condition`, `Mapping`. Loaded from four JSON files in `careloop/data/`.

**Algorithm** (`triage.py`):
1. Resolve each submitted symptom id; unknown ids are reported, never silently dropped.
2. Sum mapping weights per condition; record each contribution for the audit trail.
3. Sort by score desc, ties broken by clinical priority (Critical > Urgent > Routine) then name.
4. **Red-flag override:** if the top condition is flagged → force Critical + route to `SPEC_EM`
   (Emergency Medicine), bypassing the authored priority. Scan depth defaults to 1.
5. Otherwise take triage level + specialty from the top-ranked condition as authored.

**Dataset:** starter set is small (16 specialties / 22 symptoms / 12 conditions / 50 mappings). The
full Salesforce export is **16 / 83 / 61 / 280** — swap it in with `scripts/sf_csv_to_json.py`.

**Canonical smoke test:** chest pain radiating + sweating + breathless → `Critical | Emergency
Medicine | red flag`, ACS scoring 28. Matches the Salesforce build exactly.

---

## 6. The compaction ledger (`careloop/ledger/`)
**Ledger** (one per patient): allergies, chronic conditions, medications, `lab_results` (analyte →
time-ordered series), documents ingested, clinical notes.

**DocumentFacts**: the fixed schema the extractor fills from ONE document.

**Merge rules** (`compact.py`, all deterministic):
| Data | Rule |
|---|---|
| Allergies | Dedup by allergen; keep the **more severe** reading (never downgrade an allergy). |
| Chronic conditions | Dedup by name; keep the **earliest** diagnosis date. |
| Medications | Dedup by drug; **latest document wins** on dose/frequency/status; all sources kept. |
| Lab results | Append to the analyte's series; dedup by (date, value); series sorted by date. |
| Notes | Deduplicated verbatim. |

**Idempotency (hard requirement, carried from the Salesforce upsert discipline):** each document is
fingerprinted (SHA-256 of its text). Re-ingesting the same folder skips already-merged documents, so
no lab reading is ever double-counted. Re-running `ingest.py` twice must leave the ledger unchanged.

---

## 7. Extraction (`careloop/ledger/extract.py`)
Two extractors, one interface, so `compact.merge_facts` neither knows nor cares which produced the
facts:
- **`extract_with_gemini`** — the real one. `google.genai.Client()` picks up the same env as the ADK
  agent (API key or Vertex), so no separate config. Prompted to report only what a document literally
  says — no inference, no diagnosis. JSON parsed leniently (tolerates fences/prose). On a parse
  failure it records the document with **no** facts rather than fabricating.
- **`MockExtractor`** — canned facts for the five sample documents, so the pipeline runs fully
  offline with no key. Same role the deterministic summary fallback played in Salesforce: the demo
  never depends on a live model.

---

## 8. Sources & store (local now, cloud next)
Both ends are pluggable and currently local, deliberately, so confirming the compaction *logic*
never drags in a cloud permissions problem.
- **`sources.py`** — reads a local folder (`.txt`/`.md` directly, `.pdf` via `pypdf`). **Drive
  drop-in** sketched inside: use a **service account + shared folder** (share one Drive folder with
  the service account's email) — NOT user OAuth, which is the part that eats a day.
- **`store.py`** — local JSON file. **Firestore drop-in** sketched inside: one document per patient
  in a `ledgers` collection, same `load_ledger` / `save_ledger` interface.

---

## 9. The ADK agent (`careloop/agent.py`)
`root_agent` is an ADK `Agent` reading `CARELOOP_MODEL` from env. Tools: `list_symptoms`,
`run_triage`, `dataset_health`. The instruction enforces the sequence: read symptoms → `list_symptoms`
→ `run_triage` → report the result exactly (never change the level, never re-rank, never add a
condition the engine didn't return) → write a clinician brief, escalation first if red-flagged.

Run from the **repository root** (the folder containing `careloop/`), never from inside `careloop/`.

---

## 10. Environment & auth (`careloop/.env`)
Two working paths. **Pick one.** The model MUST be **Gemini 3.5 or newer** (hackathon rule); the code
default is `gemini-3.6-flash`. Confirm which model + mode you have working and record it here.

**Path A — Gemini API key (simplest, use for local dev):**
```
GOOGLE_API_KEY="<key from aistudio.google.com/app/apikey>"
GOOGLE_GENAI_USE_VERTEXAI=FALSE
CARELOOP_MODEL="gemini-3.6-flash"
```
With a real key, ADK and the extractor talk to the Gemini API directly — no Vertex, no region wall.

**Path B — Vertex / Gemini Enterprise Agent Platform (needed for Cloud Run, Day 5):**
```
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT="<project-id>"
GOOGLE_CLOUD_LOCATION="global"
CARELOOP_MODEL="gemini-3.6-flash"
```
Then: `gcloud auth application-default login` (writes ADC credentials the SDK auto-detects).

**List the models your project can actually serve before assuming one:**
- API key: `curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=KEY" | grep gemini`
- Vertex: `gcloud ai models list --region=global | grep -i gemini`

---

## 11. Running everything
```bash
# from repo root, venv active, pip install -r requirements.txt

# ENGINE (offline, no key)
python scripts/smoke_test.py                 # 3 patients: Routine / Urgent / Critical
python -m pytest tests/ -v                    # 24 tests

# COMPACTION (offline mock, then real Gemini)
python scripts/ingest.py --docs scripts/sample_docs --patient anita --name "Anita Rao" --mock
python scripts/ingest.py --docs scripts/sample_docs --patient anita --name "Anita Rao"

# AGENT (terminal — no CORS)
adk run careloop

# AGENT (dev UI — add --allow_origins on Cloud Shell, use Web Preview)
adk web                                       # local machine: no flags needed
adk web --port 8080 --allow_origins="*"       # Cloud Shell
```

---

## 12. Acceptance testing (one full pass before moving on)
| # | Step | Command | Expected | If it fails |
|---|---|---|---|---|
| 1 | Engine | `python scripts/smoke_test.py` | 3 patients, Critical case red-flagged, ACS=28 | data not loaded / import error |
| 2 | All tests | `python -m pytest tests/ -v` | 24 passed | logic regression |
| 3 | Compaction (mock) | `ingest.py … --mock` | `HbA1c: 6.8 -> 7.2 -> 7.5 %`, penicillin **Severe** | merge bug |
| 4 | Idempotency | re-run step 3 | all docs "already ingested, skipped", trend unchanged | hashing broken |
| 5 | Compaction (real) | `ingest.py …` (no `--mock`) | trend matches step 3 | Gemini misread a doc → tighten prompt |
| 6 | Agent (terminal) | `adk run careloop` + chest-pain prompt | `Critical / Emergency`, `list_symptoms`+`run_triage` visible | auth/model (see §13) |
| 7 | Agent (UI) | `adk web` + same prompt | same result, both tool calls fire in the trace panel | CORS on Cloud Shell (see §13) |
| 8 | Agent (UI, second case) | Anita's symptoms in the UI | `Urgent / Endocrinology`, no red flag | — |

Steps 1–4 are verified offline in-repo. Steps 5–8 require the live environment.

---

## 13. Known issues already solved (don't re-debug these)
| Symptom | Cause | Fix |
|---|---|---|
| `DefaultCredentialsError: application_default_credentials.json not found` | Cloud Shell sets `GOOGLE_APPLICATION_CREDENTIALS` pointing at a missing file; SDK tried Vertex OAuth | `unset GOOGLE_APPLICATION_CREDENTIALS`; use an API key, OR `gcloud auth application-default login` |
| `adk web` loads but every `.js` is **403 Forbidden** (CSS/favicon OK) | Cloud Shell Web Preview proxy → ES-module scripts fetched cross-origin, blocked by CORS | `adk web --allow_origins="*"` (or `regex:https://.*\.cloudshell\.dev`); open via **Web Preview**, not a typed URL |
| `404 NOT_FOUND … gemini-1.5-flash … not found in region` | `.env` not being read → ADK fell back to its 1.5 default, which isn't served on Vertex in-region | Ensure `.env` is read (run from repo root); set `CARELOOP_MODEL` to a 3.5+ model the project serves |
| Model/flags in `.env` ignored | Cloud Shell ambient env vars override the file; or `.env` in the wrong folder | `unset` the conflicting vars; confirm `careloop/.env` exists; `export` the vars directly to test |
| `adk web` shows no agents | Run from inside `careloop/` instead of repo root | Run `adk web` from the folder that *contains* `careloop/` |
| `adk` command not found | venv not active in a new terminal | `source .venv/bin/activate` |
| Wildcard `--allow_origins` still 403s | Some setups reject `*` for module scripts | Use the regex form matching Cloud Shell's rotating host |
| Cloud Shell resets, error returns | `unset`/`export` only last the session; container is ephemeral | Prefer running locally; re-apply env on reconnect |

**General isolation trick:** `adk run` (terminal) has no browser, so no CORS. If `adk run` works but
`adk web` doesn't, the problem is 100% the proxy/CORS, not your agent — exactly the front-end-vs-engine
split used in the Salesforce build.

---

## 14. Status & the day plan
**Verified (offline, in-repo):** engine (12 tests), compaction (12 tests), both smoke tests. Anita's
ledger shows the HbA1c trend and the escalated penicillin allergy. Agent runs end to end via
`adk run`.

| Day | Scope | State |
|---|---|---|
| 1–2 | Repo, engine port, ADK agent, tests | **Done** |
| 3 | Compaction ledger + extraction (local source/store) | **Done, offline-verified** |
| 4 | Real Drive source (service account) + Firestore store + wire ledger into the agent (brief surfaces allergies/history) | Next |
| 5 | Cloud Run deploy (Vertex auth) + prove backend on GCP for submission | — |
| 6 | Async loop: Cloud Scheduler → Pub/Sub → refill reminders + check-ins via Gmail | — |
| 7 | README, architecture diagram, `adk eval` reproducibility run | — |
| 8 | ~4-min demo video (must show Cloud Run/Vertex as proof) + buffer | — |

**Submission checklist (from the rules):** hosted URL (encouraged), text description, public/shared
repo, spin-up instructions in README, architecture diagram, ~4-min demo video showing the backend on
Google Cloud. Gemini 3.5+ via API or Vertex; at least one Google agent framework (ADK); at least one
GCP service (Cloud Run + Firestore). Bonus: a blog/social post with `#AllThingsAgenticHackathon`.

**Guardrails to keep:** medication features are refill reminders for what a clinician already
prescribed — never "the agent suggests you buy X." Pharmacy purchase is a deep-link or a documented
mock, never a hidden mock. Wearables (if added) are wellness context only, not triage inputs. All
data synthetic.
