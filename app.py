import uuid
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src import rules, extractor, followup, escalation, note_generator, note_verifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TriageGuard")

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

_sessions: dict[str, dict] = {}


def _new_session() -> dict:
    return {
        "messages": [],
        "state": "collecting",
        "followup_count": 0,
        "api_failure_count": 0,
        "relevant_conditions": [],
        "extracted_fields": {},
        "leading_condition": None,
        "matched_rule": None,
        "escalation_reason": None,
        "triage_note": None,
    }


def _get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = _new_session()
    return _sessions[session_id]


class ChatRequest(BaseModel):
    session_id: str = ""
    message: str


class ChatResponse(BaseModel):
    session_id: str
    message: str
    state: str
    urgency: str | None = None
    department: str | None = None
    matched_rule_id: str | None = None
    triage_note: str | None = None
    escalation_reason: str | None = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    session = _get_session(session_id)

    if session["state"] in ("resolved", "escalated"):
        return ChatResponse(
            session_id=session_id,
            message="This consultation is complete. Please start a new session for a new case.",
            state=session["state"],
            urgency=session["matched_rule"]["urgency"] if session["matched_rule"] else None,
            department=session["matched_rule"]["department"] if session["matched_rule"] else None,
            matched_rule_id=session["matched_rule"]["rule_id"] if session["matched_rule"] else None,
            triage_note=session["triage_note"],
            escalation_reason=session["escalation_reason"],
        )

    session["messages"].append({"role": "patient", "content": req.message})

    all_text = " ".join(m["content"] for m in session["messages"])
    relevant_conditions = rules.get_relevant_conditions(all_text)
    session["relevant_conditions"] = relevant_conditions

    if not relevant_conditions:
        return ChatResponse(
            session_id=session_id,
            message=(
                "I wasn't able to identify a specific medical condition from your description. "
                "Could you tell me more about your symptoms? For example, do you have a fever, "
                "pain, difficulty breathing, or an injury?"
            ),
            state="collecting",
        )

    extracted = await extractor.extract_all(relevant_conditions, session["messages"])

    if extracted is None:
        session["api_failure_count"] += 1
        if session["api_failure_count"] >= 2:
            session["state"] = "escalated"
            session["escalation_reason"] = escalation.REASON_API_FAILURE
            return ChatResponse(
                session_id=session_id,
                message=(
                    "ESCALATED TO HUMAN: The system was unable to process your information after "
                    "repeated attempts. Please seek immediate in-person medical assessment."
                ),
                state="escalated",
                escalation_reason=escalation.REASON_API_FAILURE,
            )
        return ChatResponse(
            session_id=session_id,
            message=(
                "I'm having difficulty understanding that. Could you rephrase your description "
                "of your symptoms in different words?"
            ),
            state="collecting",
        )

    session["api_failure_count"] = 0
    session["extracted_fields"] = extracted

    esc = escalation.check_escalation(
        relevant_conditions,
        extracted,
        session["followup_count"],
    )
    if esc["should_escalate"]:
        session["state"] = "escalated"
        session["escalation_reason"] = esc["reason"]
        return ChatResponse(
            session_id=session_id,
            message=f"ESCALATED TO HUMAN: {esc['reason_message']}",
            state="escalated",
            escalation_reason=esc["reason"],
        )

    leading = rules.get_leading_condition(relevant_conditions, extracted)
    session["leading_condition"] = leading
    condition = rules.get_condition(leading)
    fields_for_cond = extracted.get(leading, {})

    ready, issues = rules.check_fields_ready(condition, fields_for_cond)

    if not ready:
        if session["followup_count"] >= rules.FOLLOWUP_CAP:
            session["state"] = "escalated"
            session["escalation_reason"] = escalation.REASON_LOW_CONFIDENCE
            return ChatResponse(
                session_id=session_id,
                message=(
                    "ESCALATED TO HUMAN: Sufficient information could not be gathered after "
                    "multiple follow-up questions. A clinician should assess this case directly."
                ),
                state="escalated",
                escalation_reason=escalation.REASON_LOW_CONFIDENCE,
            )

        top_issue = issues[0]
        question = await followup.get_question(top_issue, condition["display_name"], session["messages"])
        session["messages"].append({"role": "assistant", "content": question})
        session["followup_count"] += 1
        return ChatResponse(
            session_id=session_id,
            message=question,
            state="collecting",
        )

    matched = rules.match_rule(leading, fields_for_cond)
    session["matched_rule"] = matched

    note = await note_generator.generate(condition, matched, fields_for_cond)

    valid, mismatches = note_verifier.verify(note, matched)
    if not valid:
        logger.warning("Note verification failed (%s), regenerating: %s", matched["rule_id"], mismatches)
        note = await note_generator.generate(condition, matched, fields_for_cond)
        valid, mismatches = note_verifier.verify(note, matched)
        if not valid:
            session["state"] = "escalated"
            session["escalation_reason"] = "note_verification_failed"
            return ChatResponse(
                session_id=session_id,
                message=(
                    "ESCALATED TO HUMAN: The system could not produce a verified triage note. "
                    "A clinician must review this case."
                ),
                state="escalated",
                escalation_reason="note_verification_failed",
            )

    session["triage_note"] = note
    session["state"] = "resolved"

    return ChatResponse(
        session_id=session_id,
        message=note,
        state="resolved",
        urgency=matched["urgency"],
        department=matched["department"],
        matched_rule_id=matched["rule_id"],
        triage_note=note,
    )


@app.post("/api/reset")
async def reset(req: ChatRequest) -> JSONResponse:
    session_id = req.session_id or str(uuid.uuid4())
    _sessions[session_id] = _new_session()
    return JSONResponse({"session_id": session_id, "status": "reset"})


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "model": "gemini-3.5-flash-lite"})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIST / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
