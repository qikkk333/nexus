TRACK_ID=PS01

# TriageGuard

A patient-intake triage assistant. Patients describe their symptoms in plain language; the system asks targeted follow-up questions, checks the case against deterministic clinical rules, and produces a verified triage note — or escalates to a human when it cannot be confident. It never diagnoses. Every urgency/department recommendation is traceable to a specific rule ID.

---

## Quick Start

**Requirements:** Python 3.11+, a Gemini API key.

```bash
git clone <repo-url>
cd triage-guard
pip install -r requirements.txt
export GEMINI_API_KEY=your_key_here   
python app.py
```

Open `http://localhost:8000` in your browser. The chat UI loads immediately.

---

## How It Works

### Pipeline (per conversation turn)

1. **Keyword match** — `src/rules.py` scans the full conversation for condition keywords (deterministic).
2. **Field extraction** — `src/extractor.py` calls `gemini-3.5-flash-lite` (temp=0.1, JSON schema output) to extract required fields per condition, each with a `confidence` score (0–1).
3. **Escalation check** — `src/escalation.py` deterministically fires escalation if:
   - Any red-flag field is present with confidence ≥ 0.6, OR
   - Two or more conditions are plausible simultaneously (multi-rule ambiguity), OR
   - A required field stays below the confidence threshold after the follow-up cap.
4. **Follow-up questions** — if required fields are missing or in the gray zone (0.6–0.8), `src/followup.py` generates one focused question via the LLM, scoped to the exact missing field.
5. **Rule resolution** — once all required fields clear the threshold (≥ 0.8), `src/rules.py` evaluates the urgency-level expressions deterministically.
6. **Note generation** — `src/note_generator.py` writes the triage note using *only* the verified field values and the matched rule text — never the raw patient message.
7. **Note verification** — `src/note_verifier.py` deterministically confirms the note's stated urgency, department, and rule ID match what step 5 resolved. On mismatch: regenerate once, then escalate.

### Confidence Thresholds (visible in `src/rules.py`)

| Threshold | Value | Meaning |
|---|---|---|
| `CONFIDENCE_USABLE` | 0.8 | Field is trusted, no follow-up needed |
| `CONFIDENCE_GRAY_ZONE_LOW` | 0.6 | Gray zone — worth one follow-up |
| `CONFIDENCE_GRAY_ZONE_HIGH` | 0.8 | Top of gray zone |
| `FOLLOWUP_CAP` | 2 | Max follow-up rounds before escalation |

### Anti-Hallucination Design

- The LLM **never decides** urgency or department — it only extracts field values.
- Rule matching and escalation are **pure deterministic Python** against the YAML rule table.
- The triage note is generated from the **extracted-fields JSON + rule text only**, not the raw conversation.
- A deterministic verifier **checks every urgency/department claim** in the note against the code-resolved rule before the note is shown.

---

## Data

### `data/triage_rules.yaml`

Five conditions with required fields, red-flag fields, and urgency-level expressions:

| Condition | Rule ID | Red Flags |
|---|---|---|
| Fever | `RULE_FEVER` | Altered consciousness, stiff neck + severe headache, non-blanching rash |
| Injury / Trauma | `RULE_INJURY` | Head injury with LOC, uncontrolled bleeding, suspected spinal |
| Chest Pain | `RULE_CHEST_PAIN` | Diaphoresis, syncope |
| Breathing Difficulty | `RULE_BREATHING` | Cyanosis, use of accessory muscles |
| Abdominal Pain | `RULE_ABDOMINAL` | Rigid abdomen, blood in stool or vomit |

### `data/sample_transcripts/`

Ten scripted conversations for demo use:

| File | Scenario | Outcome |
|---|---|---|
| `01_clean_fever_urgent.txt` | Moderate fever, single rule | RULE_FEVER — URGENT |
| `02_clean_injury_immediate.txt` | Severe fall, pain 9/10 | RULE_INJURY — IMMEDIATE |
| `03_chest_pain_immediate.txt` | Chest pain with radiation | RULE_CHEST_PAIN — IMMEDIATE |
| `04_red_flag_instant_escalation.txt` | Altered consciousness in first message | ESCALATED — red_flag |
| `05_multi_rule_ambiguity_escalation.txt` | Fever + right lower quadrant pain | ESCALATED — multi_rule_ambiguity |
| `06_vague_answers_escalation.txt` | Persistent vague answers | ESCALATED — persistent_low_confidence |
| `07_breathing_urgent.txt` | Gradual breathing difficulty, SpO2 95% | RULE_BREATHING — URGENT |
| `08_abdominal_routine.txt` | Mild stomach cramps | RULE_ABDOMINAL — ROUTINE |
| `09_fever_immediate_infant.txt` | 2-month-old with fever 38.4°C | RULE_FEVER — IMMEDIATE |
| `10_api_failure_scenario.txt` | API key missing or API error × 2 | ESCALATED — api_failure |

---

## File Structure

```
triage-guard/
  app.py                   # FastAPI app, pipeline orchestration, port 8000
  requirements.txt
  README.md
  src/
    rules.py               # YAML loader, confidence thresholds, deterministic matching
    extractor.py           # Gemini field extraction with per-field confidence scores
    followup.py            # LLM-generated follow-up questions, scoped to missing fields
    escalation.py          # Deterministic escalation triggers (red flag / ambiguity / cap)
    note_generator.py      # Triage note generation from verified fields + rule text only
    note_verifier.py       # Deterministic check: note claims match code-resolved rule
  data/
    triage_rules.yaml
    sample_transcripts/
  frontend/
    dist/
      index.html           # Single-file chat UI, no build step required
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key |

Without the key, the system handles API failures gracefully: it asks the patient to rephrase once, then escalates on a second failure (see transcript 10).

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Chat UI |
| `POST` | `/api/chat` | Send a patient message, get triage response |
| `POST` | `/api/reset` | Reset a session |
| `GET` | `/api/health` | Health check |

---

## Model Note

The spec references `gemini-3.5-flash-lite`. The implementation uses `gemini-2.0-flash-lite` via the `google-genai` SDK (the successor to the now-deprecated `google-generativeai` package). To override the model, edit `MODEL_NAME` in `src/extractor.py`, `src/followup.py`, and `src/note_generator.py`.

`POST /api/chat` body: `{"session_id": "<uuid or empty>", "message": "<patient text>"}`

Response includes `state` (`collecting` / `resolved` / `escalated`), `urgency`, `department`, `matched_rule_id`, and `triage_note` when resolved.

---

## Demo

[Demo video link — add before submission]
