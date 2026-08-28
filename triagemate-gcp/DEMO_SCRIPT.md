# Demo cheat-sheet

The order to run things while recording. Roughly four minutes if I don't ramble.

Two things live in two places: the **chat UI** does triage + history lookup, and a
few **terminal scripts** do the consultation write-back, the billing, and the
follow-up. I show both. Have two terminal tabs open.

## Before recording

Make sure Anita's record exists in whatever store I'm on:

```bash
cd ~/triagemate-gcp
python scripts/ingest.py --docs scripts/sample_docs --patient anita --name "Anita Rao" --mock
```

If demoing the deployed version, just open the `.run.app` URL instead of `adk web`.
No CORS there, and it doesn't reset like Cloud Shell.

## Opening line (say this)

"Most AI waits for you to ask. This one doesn't. It reads a patient's records,
triages them, briefs the doctor, records what the doctor decides, and then follows
up on its own weeks later. And the urgency call is made by rules, not the model, so
a doctor can actually audit it."

## Part 1 - chat UI

Watch the trace panel each time. The tool calls firing is the proof the model hands
the decision to the engine.

1. Routine (calm baseline)
   > Someone has a runny nose, sneezing, and a mild cough for two days.

   Expect: Routine, General Medicine. Point at `run_triage` in the trace.

2. Urgent + history (the big one, spend the most time here)
   > Patient anita is here with increased thirst, frequent urination, blurred vision, and weight loss. What's the triage?

   Expect: `run_triage` AND `get_patient_ledger` both fire. Urgent, Endocrinology.
   The brief pulls in her HbA1c climbing 6.8 to 7.2 to 7.5, her Metformin, and her
   penicillin allergy. Say: "the symptoms alone don't tell you her control is
   slipping. The record does."

3. Critical, red-flag override (the finish)
   > I've had crushing chest pain spreading into my left arm for the last hour, I'm sweating and short of breath.

   Expect: Critical, Emergency Medicine, red-flag banner, Acute coronary syndrome.
   Say: "the model never made this call. A red-flag rule did, and skipped the score."

## Part 2 - terminal (the autonomous tail)

Switch to the terminal tab.

4. Consultation write-back + billing
   ```bash
   python scripts/consult.py
   ```
   Say: "the doctor adds a statin for her high cholesterol. It writes back into her
   file, and the pharmacy bills it plus the consult fee. Payment's mocked."

5. The follow-up drafting a reminder with Gemini
   ```bash
   python scripts/followup.py --real
   ```
   Say: "later, on its own, it sees she's due and drafts the reminder. Rules decide
   she's due, Gemini writes the note. Email's mocked, but this is the exact message
   it would send."

6. The loop closing (optional, if time)
   ```bash
   python scripts/followup.py --patient anita --as-of 2026-10-15
   ```
   Say: "and because the doctor's new prescription went into the file, a month later
   the follow-up reminds her about that drug too. That's the loop."

## Proof shot for the "runs on Google Cloud" requirement

Show the Cloud Run console (https://console.cloud.google.com/run) with the careloop
service, and the `.run.app` URL loading. Ten seconds of that is enough.

## Say at the end

"Synthetic data throughout, the clinical dataset is demo-grade, and email and
payment are mocked. Everything else is real and running on Cloud Run and Firestore."

## Don't forget

- Say the mocked parts out loud. Nobody minds a documented mock.
- Keep it moving. The urgent-with-history moment is the one that lands, give it room.
- If a tool call doesn't fire on the anita prompt, add "patient id anita" explicitly.
