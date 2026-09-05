
# TriageGuard — Build Spec (NexusTiq24, TRACK_ID=PS01)

Paste this whole document into Claude Code / your coding tool as the build prompt.
It scaffolds the full repo in one command per the hackathon's submission rules.

## 1. What this is

A patient-intake triage assistant. A patient describes their situation in plain
language; the system asks follow-up questions when information needed for a rule
is missing, checks the case against a small set of triage rules (fever, injury,
chest pain, breathing difficulty, abdominal pain), and produces a triage note:
urgency level + department, the specific rule and reasoning behind it, what the
patient reported vs. what follow-ups established, and what remains unknown. It
never diagnoses. Every recommendation cites the rule it came from. Uncertain or
high-risk cases escalate to a human instead of guessing.

## 2. Why this design (the anti-hallucination angle)

The brief's hardest constraint isn't the rules themselves — it's knowing *when
the system doesn't actually have enough information to apply one confidently*,
and escalating instead of quietly filling the gap. That's the same problem your
DeltaFormer work tackled with entropy-gated retrieval: use the model's own
uncertainty as a signal to decide *whether* to act, not just *how*.

| Task | Who does it | Why |
|---|---|---|
| Rule definitions (symptom → required fields → urgency/department) | Deterministic, hand-written YAML | These are the actual clinical logic; they must not vary run to run |
| Extracting structured fields from the patient's free text (symptom present? severity? duration? red-flag fields?) | LLM (`gemini-3.5-flash-lite`), structured JSON output, one field-set at a time | Only place free text needs interpreting |
| Deciding which rule applies | Deterministic, once fields are extracted | Pure lookup against the YAML rule table — never left to the LLM to "decide" |
| Deciding whether a required field is confidently extracted or genuinely ambiguous | LLM emits a `confidence` (0–1) per extracted field alongside the value | This is your entropy-gated idea, adapted: gate on the model's stated/measured confidence per field, not a global one |
| Generating the follow-up question when a field is missing/low-confidence | LLM, templated from the rule's required-fields list | Keeps questions scoped to what the rule actually needs, not open-ended |
| Escalating to a human | Deterministic: fires if any red-flag field is present, if two rules could both apply, or if a required field stays low-confidence after one follow-up round | Escalation is a hard trigger in code, never an LLM "choice" |
| Writing the final triage note | LLM, but only from the verified field values + the rule text — never from the raw patient message directly | Prevents the note from re-introducing something the extraction step already flagged as uncertain |

Concrete anti-hallucination check: the triage note generator is given the
extracted-fields JSON and the matched rule's exact text as its only inputs (not
the raw conversation). After generation, a deterministic check confirms every
urgency/department claim in the note matches the rule that was actually matched
in code — if it doesn't, the note is regenerated once, then the case is
escalated rather than shown with an unverified note.

## 3. Data you generate

- `data/triage_rules.yaml` — 5 conditions (fever, injury, chest pain, breathing
  difficulty, abdominal pain), each with: required fields, red-flag fields that
  force escalation regardless of anything else, and the resulting
  urgency/department if fields fall within a given range.
- No patient corpus needed up front — this is a live conversational flow, not a
  RAG-over-documents problem, so `gemini-embedding-001` isn't required here.
  (If you want to use it anyway for judge-visibility on the "embeddings" line,
  you could embed patient descriptions against condition exemplars as a first
  routing step before rule matching — optional, not load-bearing.)
- `data/sample_transcripts/` — 8–10 scripted example conversations for your demo
  video: a couple of clean single-rule cases, one multi-symptom case that should
  trigger escalation (ambiguous between two rules), one with a red flag present
  from the first message (immediate escalation, no follow-up needed), one where
  the patient gives vague answers twice in a row (low-confidence escalation).

## 4. Repo shape (fixed by the rules)

```
triage-guard/
  app.py                    # starts FastAPI + serves built frontend, port 8000
  requirements.txt
  README.md                 # first line EXACTLY: TRACK_ID=PS01
  src/
    rules.py                 # loads triage_rules.yaml, deterministic matching
    extractor.py              # gemini-3.5-flash-lite calls, structured field extraction + confidence
    followup.py               # generates the next question from missing/low-confidence fields
    escalation.py              # deterministic escalation trigger logic
    note_generator.py          # builds the triage note from verified fields + rule text
    note_verifier.py            # checks note claims match the matched rule in code
  data/
    triage_rules.yaml
    sample_transcripts/*.txt
  frontend/dist/              # simple chat-style intake UI
```

## 5. Model config

- LLM: `gemini-3.5-flash-lite`, temperature 0–0.1, JSON-schema-constrained output
  for both extraction (`{field, value, confidence}` per field) and the triage
  note. Low-latency model is a good fit here since this is a multi-turn
  conversation and you want quick round trips per message.
- Read `GEMINI_API_KEY` from env; on any API failure, don't crash — treat it as
  "extraction failed" for that turn, ask the patient to rephrase once, then
  escalate if it fails again.
- Confidence threshold: start around 0.6 for "usable," 0.6–0.8 as a gray zone
  worth one follow-up question, below 0.6 or still gray after a follow-up →
  escalate. Tune these visibly in `rules.py` so a judge can see the logic, not
  buried in a prompt.

## 6. Pipeline (per conversation turn)

1. Patient message comes in (first message or a follow-up answer).
2. `extractor.py` pulls whatever fields it can from the message so far, each
   with a confidence score, against the fields required by *all* conditions
   whose keywords appear in the conversation (keyword match is deterministic —
   e.g. "chest" → chest-pain rule fields become relevant).
3. `escalation.py` checks red flags and multi-rule ambiguity first — if either
   fires, stop here and escalate with what's known so far.
4. If any required field for the leading candidate rule is missing or in the
   gray zone, `followup.py` asks specifically for that field. Go to step 1 on
   the patient's reply, but cap follow-ups (e.g. 2 rounds) before escalating on
   persistent low confidence.
5. Once all required fields for one rule clear the confidence threshold,
   `rules.py` deterministically resolves urgency/department.
6. `note_generator.py` writes the note from verified fields + rule text only.
7. `note_verifier.py` deterministically confirms the note's stated
   urgency/department/rule match what step 5 actually resolved; regenerate once
   on mismatch, then escalate if it still doesn't match.

## 7. Evaluation-criteria checklist (build against this)

- [ ] `python app.py` serves on :8000 within 90s on a fresh clone.
- [ ] Real, incremental commit history (don't dump at the end).
- [ ] Clear file-level separation between deterministic rule logic and LLM calls
      (sections above map 1:1 to files).
- [ ] Handles: clean single-rule case, red-flag immediate escalation,
      multi-rule ambiguity, persistent vague answers, and an API-failure turn.
- [ ] Every urgency/department claim traceable to a specific rule ID; note never
      states a recommendation the code didn't independently resolve.
- [ ] README: TRACK_ID=PS01 on line 1, what/how/data description, demo link.

## 8. Prompt to hand to your coding assistant

> Build a FastAPI app called TriageGuard implementing the pipeline in section 6
> above. Use `gemini-3.5-flash-lite` via the `GEMINI_API_KEY` env var for both
> field extraction (structured JSON with a per-field confidence score) and
> triage-note generation, no other network calls. Keep the triage rule table,
> confidence-threshold logic, escalation triggers, and note verification
> entirely in deterministic Python, separate from the LLM-calling modules — the
> LLM should never decide urgency/department itself, only extract fields and
> phrase text. Escalate to a human (a clearly marked terminal state, not a
> retry) whenever a red-flag field is present, two rules remain plausible after
> extraction, or a required field stays below the confidence threshold after
> one follow-up round. After generating a triage note, deterministically verify
> its stated urgency/department against the rule the code actually matched;
> regenerate once on mismatch, then escalate rather than show an unverified
> note. Write `data/triage_rules.yaml` covering fever, injury, chest pain,
> breathing difficulty, and abdominal pain with required fields and red flags
> for each, plus 8–10 sample conversation transcripts for the demo video
> covering the escalation cases explicitly. Serve a minimal chat-style intake
> frontend from `frontend/dist`, built and committed, single process on port
> 8000.
